from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .code_policy import enforce_response_code_policy
from .config import load_config
from .llm import SYSTEM_PROMPT, generate, maybe_tool_call
from .tools import run_tool

_PROSE_CHARS_PER_TOKEN = 3.0
_EVIDENCE_CHARS_PER_TOKEN = 2.0
_TEMPLATE_OVERHEAD_TOKENS = 96
_MIN_EVIDENCE_CHARS = 600
_EXACT_REPLY_RE = re.compile(r"^\s*reply\s+(?:with\s+)?exactly\s*:\s*(.+?)\s*$", re.IGNORECASE)


def _exact_reply_request(question: str) -> str | None:
    """Handle literal readiness/echo requests without invoking the local model."""
    if "\n" in question or "\r" in question:
        return None
    match = _EXACT_REPLY_RE.fullmatch(question)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value or None


def _looks_like_tool_catalog_echo(answer: str) -> bool:
    """Detect the small model copying multiple tool examples instead of choosing one."""
    tool_names = set()
    for raw in answer.splitlines():
        line = raw.strip()
        if not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("tool"), str) and isinstance(obj.get("args"), dict):
            tool_names.add(obj["tool"])
            if len(tool_names) >= 2:
                return True
    return False


def evidence_char_budget(question: str, cfg: Dict[str, Any]) -> int:
    n_ctx = int(cfg.get("llm_context", 2048))
    n_predict = int(cfg.get("llm_predict", 320))
    fixed = (len(SYSTEM_PROMPT) + len(question) + 120) / _PROSE_CHARS_PER_TOKEN
    free_tokens = n_ctx - n_predict - fixed - _TEMPLATE_OVERHEAD_TOKENS
    return max(_MIN_EVIDENCE_CHARS, int(free_tokens * _EVIDENCE_CHARS_PER_TOKEN))


def _compact(value: Any, max_chars: int = 4200) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...<truncated>"


def _policy_checked(answer: str) -> str:
    try:
        return enforce_response_code_policy(answer, browser_context=False)
    except ValueError as exc:
        return (
            "Mac Brain refused its own generated code because it violated the Python-only "
            f"standard-library policy: {exc}."
        )


def ask(question: str, max_tool_steps: int = 5) -> str:
    """Run a small bounded read-only loop; generated executable code fails closed."""
    literal = _exact_reply_request(question)
    if literal is not None:
        return literal

    budget = evidence_char_budget(question, load_config())
    evidence: List[str] = []
    for _ in range(max_tool_steps):
        context = "\n\n".join(evidence)[-budget:]
        prompt = question
        if context:
            prompt += "\n\nEVIDENCE GATHERED SO FAR:\n" + context
        answer = generate([{"role": "user", "content": prompt}])
        if _looks_like_tool_catalog_echo(answer):
            correction = (
                prompt
                + "\n\nYour previous response incorrectly copied the tool catalog. "
                + "Do not list or explain tools. Either output exactly ONE valid tool-call "
                + "JSON object, or answer the user's question directly in plain text."
            )
            answer = generate([{"role": "user", "content": correction}])
            if _looks_like_tool_catalog_echo(answer):
                return (
                    "Mac Brain's local model echoed its tool catalog instead of answering. "
                    "No tool action was taken; retry the request."
                )
        call = maybe_tool_call(answer)
        if not call:
            return _policy_checked(answer)
        try:
            result = run_tool(call["tool"], call.get("args", {}))
            evidence.append(f"TOOL {call['tool']}: {_compact(result, budget)}")
        except Exception as exc:
            evidence.append(f"TOOL {call['tool']} ERROR: {exc!r}")
    context = "\n\n".join(evidence)[-budget:]
    final_prompt = (
        question
        + "\n\nEVIDENCE GATHERED SO FAR:\n"
        + context
        + "\n\nTool-step limit reached. Answer from this evidence now; do not request another tool."
    )
    answer = generate([{"role": "user", "content": final_prompt}])
    if maybe_tool_call(answer):
        return "I reached my inspection-step limit. Ask me to continue from the evidence already collected."
    return _policy_checked(answer)
