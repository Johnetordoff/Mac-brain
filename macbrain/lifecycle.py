from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from .config import load_config, set_mission_active

LABEL = "com.macbrain.performancehunter"
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
CONTAINMENT_MARKER = Path("/Library/Application Support/MacBrain/containment-active")


def launch_agent_running() -> bool:
    return subprocess.run(
        ["/bin/launchctl", "list", LABEL],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _terminate_local_llama_processes() -> List[int]:
    """Terminate only llama-cli processes using Mac Brain's configured runtime path."""
    cfg = load_config()
    expected = str(Path(str(cfg.get("llama_cli", ""))).expanduser())
    if not expected:
        return []
    try:
        p = subprocess.run(
            ["/bin/ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    killed: List[int] = []
    me = os.getpid()
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        command = parts[1]
        if pid == me:
            continue
        # llama-cli is invoked as the first argv element by Mac Brain.
        if command == expected or command.startswith(expected + " "):
            try:
                os.kill(pid, signal.SIGTERM)
                killed.append(pid)
            except (ProcessLookupError, PermissionError):
                pass
    return killed


def stop_mac_brain() -> Dict[str, object]:
    """Fail closed: mark inactive first, then unload the worker and stop local inference."""
    set_mission_active(False)
    if LAUNCH_AGENT.exists():
        subprocess.run(
            ["/bin/launchctl", "unload", str(LAUNCH_AGENT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    killed = _terminate_local_llama_processes()
    return {"running": launch_agent_running(), "terminated_llama_pids": killed}


def start_mac_brain(require_tty: bool = True) -> Dict[str, object]:
    """Start only after an explicit interactive user code word."""
    if require_tty and not sys.stdin.isatty():
        raise RuntimeError("Mac Brain can only be started from an interactive terminal.")
    if not CONTAINMENT_MARKER.exists():
        raise RuntimeError("Mac Brain cannot start because verified network containment is not armed.")
    if not LAUNCH_AGENT.exists():
        raise RuntimeError(f"LaunchAgent is not installed: {LAUNCH_AGENT}")
    phrase = input("Type START MAC BRAIN to start the local AI mission: ").strip()
    if phrase != "START MAC BRAIN":
        raise RuntimeError("Start cancelled. Mac Brain remains off.")

    # The worker itself is fail-closed after containment: it exits immediately unless
    # the current-boot active marker already exists. Write that marker only after the
    # interactive TTY/code-word checks above, then roll it back if launchctl fails.
    set_mission_active(False)
    if not set_mission_active(True, user_authorized=True):
        raise RuntimeError("Mac Brain activation was not authorized.")
    result = subprocess.run(
        ["/bin/launchctl", "load", str(LAUNCH_AGENT)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        set_mission_active(False)
        detail = (result.stderr or result.stdout or "launchctl load failed").strip()
        raise RuntimeError(detail)
    return {"running": launch_agent_running()}
