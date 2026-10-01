from __future__ import annotations

import json
from typing import Any, Dict, List

from .code_policy import enforce_response_code_policy
from .config import load_config
from .llm import SYSTEM_PROMPT, generate, maybe_tool_call
from .tools import run_tool

_PROSE_CHARS_PER_TOKEN = 3.0
_EVIDENCE_CHARS_PER_TOKEN = 2.0
_TEMPLATE_OVERHEAD_TOKENS = 96
_MIN_EVIDENCE_CHARS = 600


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
    budget = evidence_char_budget(question, load_config())
    evidence: List[str] = []
    for _ in range(max_tool_steps):
        context = "\n\n".join(evidence)[-budget:]
        prompt = question
        if context:
            prompt += "\n\nEVIDENCE GATHERED SO FAR:\n" + context
        answer = generate([{"role": "user", "content": prompt}])
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
