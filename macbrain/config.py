from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict

APP_DIR = Path(os.environ.get("MACBRAIN_HOME", Path.home() / ".macbrain"))
DB_PATH = APP_DIR / "macbrain.sqlite3"
CONFIG_PATH = APP_DIR / "config.json"
QUARANTINE_DIR = APP_DIR / "quarantine"
MISSION_ACTIVE_PATH = APP_DIR / "mission.active"

DEFAULT_CONFIG: Dict[str, Any] = {
    "mission": "speed_up_mac_brain",
    "sample_seconds": 60,
    "report_seconds": 120,
    "deep_scan_minutes": 30,
    "llm_synthesis_minutes": 15,
    "llm_threads": 2,
    "llm_context": 2048,
    "llm_predict": 320,
    "idle_load_per_cpu_max": 0.55,
    "model_path": str(APP_DIR / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"),
    "llama_cli": str(APP_DIR / "runtime" / "llama-cli"),
    "quarantine_dir": str(QUARANTINE_DIR),
}


def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    ensure_dirs()
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            config.update(json.loads(CONFIG_PATH.read_text()))
        except (ValueError, OSError):
            pass
    return config


def save_config(config: Dict[str, Any]) -> None:
    ensure_dirs()
    CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    os.chmod(CONFIG_PATH, 0o600)


def _boot_id() -> str:
    """Return a per-boot identifier so an active marker never survives a reboot."""
    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.boottime"],
            capture_output=True, text=True, check=False,
        ).stdout
        m = re.search(r"sec\s*=\s*(\d+)", out or "")
        if m:
            return "darwin:" + m.group(1)
    except OSError:
        pass
    # Test/non-macOS fallback. Linux boot_id changes every boot.
    try:
        return "linux:" + Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown-boot"


def mission_active() -> bool:
    if not MISSION_ACTIVE_PATH.exists():
        return False
    try:
        data = json.loads(MISSION_ACTIVE_PATH.read_text())
    except (ValueError, OSError):
        return False
    return data.get("mission") == "speed_up_mac_brain" and data.get("boot_id") == _boot_id()


def set_mission_active(active: bool, *, user_authorized: bool = False) -> bool:
    """Set mission state. Activation is fail-closed unless the explicit user-start path authorizes it.

    Existing/bootstrap code may safely call set_mission_active(True): it will not wake Mac Brain.
    Only lifecycle.start_mac_brain(), after TTY + code-word + containment checks, passes
    user_authorized=True. Deactivation is always allowed.
    """
    ensure_dirs()
    if active:
        if not user_authorized:
            return False
        MISSION_ACTIVE_PATH.write_text(json.dumps({"mission": "speed_up_mac_brain", "boot_id": _boot_id()}) + "\n")
        os.chmod(MISSION_ACTIVE_PATH, 0o600)
        return True
    try:
        MISSION_ACTIVE_PATH.unlink()
    except FileNotFoundError:
        pass
    return True
