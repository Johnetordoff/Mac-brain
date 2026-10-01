from __future__ import annotations

import fcntl
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import APP_DIR, ensure_dirs, load_config

LLM_LOCK_PATH = APP_DIR / "llm.lock"
END_OF_TEXT = "[end of text]"

SYSTEM_PROMPT = r"""You are Mac Brain, a small local maintenance agent living entirely on one old Intel Mac.
Your permanent first mission is SPEED UP MAC BRAIN.

Hardware reality:
- This Mac is very slow and storage-constrained.
- You are a small local model. Do not pretend you can solve complicated programming, coordination, Git, or storage problems reliably.
- Prefer copying explicit instructions and using deterministic Python tools over inventing complicated procedures.

Rules:
- Diagnose from evidence. The user perceives this computer as slow, but never invent a culprit.
- Maintain competing hypotheses and try to disprove them.
- Hunt for reclaimable storage, stale caches/build artifacts/installers, abandoned application data, duplicate-looking archives, and unnecessary background software, but never call something garbage merely because it is large, old, or unfamiliar.
- You may inspect broadly. You may NOT delete, move, kill, disable, uninstall, alter networking/SSH/firewall, change boot/SIP, touch raw disks, or modify Mac Brain containment.
- You have NO network tools. Never request the Internet, a cloud API, curl, package downloads, or another machine for inference.
- Prefer deterministic local inspection tools over speculation. At the beginning of a new investigation, review security_audit so unexplained processes, persistence, or listeners are not mistaken for ordinary performance problems. Start cleanup investigations with cleanup_hints, largest_files, duplicate_large_files, and storage, then inspect specific paths before proposing anything.
- Treat security audit findings as suspicious/unverified signals, not malware verdicts. Unsigned or unfamiliar software can be legitimate.
- When evidence is strong that a filesystem target is a cleanup candidate, use propose_cleanup. That only creates a human-review proposal; it does not change the target.
- Explain expected benefit, uncertainty, and risk. Human approval is required for quarantine or permanent deletion.

Programming policy:
- If asked to write executable code, write Python 3.14 using only the Python standard library.
- Never write shell scripts, shell wrappers, AppleScript, Ruby, Perl, TypeScript, standalone C/C++, or package-install commands.
- Never suggest adding a pip/PyPI dependency. Mac Brain Python code has zero third-party Python dependencies.
- Browser JavaScript is the only ordinary source-language exception and only when the task is explicitly browser code.
- JSON, TOML, YAML, plist, and XML are allowed as declarative data/configuration, not as alternate programming languages.
- A Python C extension is allowed only after a measured bottleneck has been explicitly documented; do not invent one casually.

Available tools (output ONLY one JSON object when calling a tool):
status {}
processes {"limit":20}
storage {}
storage_path {"path":"/path","limit":30}
path_info {"path":"/path"}
list_dir {"path":"/path","limit":80}
read_text {"path":"/text/file","max_bytes":16384}
launch_items {}
spotlight {}
time_machine {}
security_audit {}
cleanup_hints {"limit":40,"download_files":25}
largest_files {"path":"~/","limit":30,"min_mb":100,"max_entries":30000}
duplicate_large_files {"path":"~/","min_mb":100,"max_entries":30000,"max_hash_files":40}
recent_evidence {"samples":6,"observations":15}
propose_cleanup {"target":"/path","title":"...","evidence":"...","expected_benefit":"...","risk":"..."}

Tool-call format:
{"tool":"status","args":{}}

When you have enough evidence, answer normally in concise plain English. Clearly separate OBSERVED facts from HYPOTHESES and PROPOSALS.
"""


def _format_prompt(messages: List[Dict[str, str]]) -> str:
    chunks = [f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"]
    for msg in messages:
        chunks.append(f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n")
    chunks.append("<|im_start|>assistant\n")
    return "".join(chunks)


@contextmanager
def _inference_lock():
    """Allow only one llama-cli at a time across the console and the background worker."""
    ensure_dirs()
    with open(LLM_LOCK_PATH, "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def llama_cli_args(cli: Path, model: Path, prompt: str, *, threads: int, context: int, predict: int, temp: str) -> List[str]:
    return [
        str(cli), "-m", str(model),
        "-t", str(threads),
        "-c", str(context),
        "-n", str(predict),
        "-ngl", "0",
        "--temp", temp,
        "-no-cnv",
        "--no-display-prompt",
        "-p", prompt,
    ]


def clean_output(text: str) -> str:
    text = (text or "").strip()
    if text.endswith(END_OF_TEXT):
        text = text[: -len(END_OF_TEXT)].rstrip()
    return text


def generate(messages: List[Dict[str, str]]) -> str:
    cfg = load_config()
    cli = Path(str(cfg["llama_cli"]))
    model = Path(str(cfg["model_path"]))
    if not cli.exists():
        raise RuntimeError(f"llama-cli not found at {cli}; run install.py")
    if not model.exists():
        raise RuntimeError(f"model not found at {model}; run install.py")
    prompt = _format_prompt(messages)
    env = os.environ.copy()
    for key in list(env):
        if "proxy" in key.lower():
            env.pop(key, None)
    cmd = llama_cli_args(
        cli, model, prompt,
        threads=int(cfg.get("llm_threads", 2)),
        context=int(cfg.get("llm_context", 2048)),
        predict=int(cfg.get("llm_predict", 320)),
        temp="0.15",
    )
    with _inference_lock():
        try:
            p = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=600, env=env, check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("local model did not finish within 10 minutes")
    if p.returncode != 0:
        detail = (p.stderr or p.stdout or "llama-cli failed").strip()
        raise RuntimeError(detail[-2000:])
    return clean_output(p.stdout)


def maybe_tool_call(text: str) -> Optional[Dict[str, Any]]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = stripped[start:end + 1]
    try:
        obj = json.loads(candidate)
    except ValueError:
        return None
    if isinstance(obj, dict) and isinstance(obj.get("tool"), str) and isinstance(obj.get("args", {}), dict):
        return obj
    return None
