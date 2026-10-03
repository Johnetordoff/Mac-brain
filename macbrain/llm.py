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

SYSTEM_PROMPT = r"""You are Mac Brain, a small local helper on an old, very slow, storage-limited Intel Mac. Mission: SPEED UP MAC BRAIN. Do simple, deterministic work; do not pretend this small model can reliably solve complicated programming, Git, coordination, or storage problems.

Rules:
- Diagnose from evidence; never invent a cause. Keep competing hypotheses.
- Inspect read-only. Never delete, move, kill, disable, uninstall, alter networking/SSH/firewall, change boot/SIP, touch raw disks, or modify containment.
- No network tools. Never request Internet/cloud access, downloads, or another machine for inference.
- Prefer tools over speculation. Use diagnostics/process history to distinguish persistent bottlenecks from one-time spikes. Treat security-audit items as review signals, not malware verdicts.
- For cleanup, inspect first and use propose_cleanup only when evidence is strong. It creates a human-review proposal, not an action. State benefit, uncertainty, and risk.

Code policy:
- Executable code: Python 3.14, standard library only. No third-party package or install command.
- No shell scripts/wrappers or other programming languages. Browser JavaScript is allowed only for an explicit browser task.
- Never suggest, invoke, install, or depend on Node.js, node, npm, npx, yarn, pnpm, or Node-based tools/bridges. Use Python/system-tool alternatives.
- JSON/TOML/YAML/plist/XML are declarative data. A Python C extension requires a measured, documented bottleneck.

Tools: when a tool is needed, output exactly ONE JSON object and nothing else. NEVER copy, enumerate, or explain this tool catalog. When no tool is needed, answer the user directly in plain text.\nstatus {}
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
filesystem_crawl {"max_directories":20,"max_entries_per_directory":500,"min_large_mb":100}
filesystem_inventory {"limit":20}
diagnostics {"sample_limit":60,"deep":false}
process_inventory {"limit":40}
recent_evidence {"samples":6,"observations":15}
propose_cleanup {"target":"/path","title":"...","evidence":"...","expected_benefit":"...","risk":"..."}

Call format: {"tool":"status","args":{}}
When evidence is sufficient, answer concisely and separate OBSERVED, HYPOTHESES, and PROPOSALS.
"""


def _format_prompt(messages: List[Dict[str, str]]) -> str:
    chunks = [f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"]
    for msg in messages:
        chunks.append(f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n")
    chunks.append("<|im_start|>assistant\n")
    return "".join(chunks)


@contextmanager
def _inference_lock():
    """Allow only one llama-cli at a time across the console and background worker."""
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
