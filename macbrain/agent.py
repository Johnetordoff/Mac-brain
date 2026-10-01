from __future__ import annotations

import json
from typing import Any, Dict, List

from .config import load_config
from .llm import SYSTEM_PROMPT, generate, maybe_tool_call
from .tools import run_tool

# Conservative chars-per-token estimates. Real English is ~4 chars/token and compact
# JSON with paths is ~2.5-3, so dividing by 3 for prose and 2 for evidence keeps the
# prompt under llama-cli's hard "prompt is too long" limit with room to answer.
_PROSE_CHARS_PER_TOKEN = 3.0
_EVIDENCE_CHARS_PER_TOKEN = 2.0
_TEMPLATE_OVERHEAD_TOKENS = 96
_MIN_EVIDENCE_CHARS = 600


def evidence_char_budget(question: str, cfg: Dict[str, Any]) -> int:
    """How many characters of tool evidence fit next to the system prompt and question.

    llama-cli exits with "prompt is too long" if the prompt alone exceeds n_ctx, and the reply
    also needs room for llm_predict tokens. On the 2048-token default, a fixed 4500-char
    evidence window plus the system prompt overflowed after the first large tool result.
    """
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


def ask(question: str, max_tool_steps: int = 5) -> str:
    """Run a small, bounded read-only agent loop.

    The model never receives a generic shell or networking tool. Each inspection step is
    deterministic Python/local macOS tooling. Tool results are compacted aggressively so
    this remains usable with a ~2k context on a 6 GB Intel Mac.
    """
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
            return answer
        try:
            result = run_tool(call["tool"], call.get("args", {}))
            evidence.append(f"TOOL {call['tool']}: {_compact(result, budget)}")
        except Exception as exc:
            evidence.append(f"TOOL {call['tool']} ERROR: {exc!r}")
    # Give the model one final chance to answer without another tool call.
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
    return answer
