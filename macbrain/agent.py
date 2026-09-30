from __future__ import annotations

import json
from typing import Any, Dict, List

from .llm import generate, maybe_tool_call
from .tools import run_tool


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
    evidence: List[str] = []
    for _ in range(max_tool_steps):
        context = "\n\n".join(evidence)[-4500:]
        prompt = question
        if context:
            prompt += "\n\nEVIDENCE GATHERED SO FAR:\n" + context
        answer = generate([{"role": "user", "content": prompt}])
        call = maybe_tool_call(answer)
        if not call:
            return answer
        try:
            result = run_tool(call["tool"], call.get("args", {}))
            evidence.append(f"TOOL {call['tool']}: {_compact(result)}")
        except Exception as exc:
            evidence.append(f"TOOL {call['tool']} ERROR: {exc!r}")
    context = "\n\n".join(evidence)[-4500:]
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
