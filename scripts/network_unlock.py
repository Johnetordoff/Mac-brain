#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKUP = Path("/etc/pf.conf.macbrain-backup")
PF_CONF = Path("/etc/pf.conf")
ANCHOR = Path("/etc/pf.anchors/macbrain")
SUPPORT = Path("/Library/Application Support/MacBrain")
DAEMON = Path("/Library/LaunchDaemons/com.macbrain.networklock.plist")
WATCHDOG = SUPPORT / "network-watchdog.py"
WATCHDOG_CONFIG = SUPPORT / "network-watchdog.json"
PF_STATE = SUPPORT / "pf-was-enabled"
NETWORK_BEFORE = SUPPORT / "network-before.txt"
NETWORK_META = SUPPORT / "network-meta.json"
LEGACY_NETWORK_META = SUPPORT / "network-meta"
CONTAINMENT_MARKER = SUPPORT / "containment-active"


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, check=False, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}")
    return result


def load_meta() -> dict[str, str]:
    if NETWORK_META.exists():
        raw = json.loads(NETWORK_META.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in raw.items()}
    # Backward-compatible recovery for machines armed by the earlier shell version.
    if LEGACY_NETWORK_META.exists():
        result: dict[str, str] = {}
        key_map = {
            "SERVICE": "service",
            "IFACE": "interface",
            "GATEWAY": "gateway",
            "LOCAL_IP": "local_ip",
            "NETMASK": "netmask",
            "SOURCE": "source",
        }
        for line in LEGACY_NETWORK_META.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep and key in key_map:
                result[key_map[key]] = value
        return result
    return {}


def main() -> int:
    if os.geteuid() != 0:
        print("Run with sudo from the physical Mac.", file=sys.stderr)
        return 1
    if not BACKUP.exists():
        print("No pre-Mac-Brain pf backup found.", file=sys.stderr)
        return 1

    run(["/bin/launchctl", "unload", str(DAEMON)], check=False)
    for path in (DAEMON, WATCHDOG, WATCHDOG_CONFIG, CONTAINMENT_MARKER):
        path.unlink(missing_ok=True)

    meta = load_meta()
    service = meta.get("service", "")
    gateway = meta.get("gateway", "")
    local_ip = meta.get("local_ip", "")
    netmask = meta.get("netmask", "")

    shutil.copy2(BACKUP, PF_CONF)
    run(["/sbin/pfctl", "-f", str(PF_CONF)])
    if PF_STATE.exists() and PF_STATE.read_text(encoding="utf-8").strip() == "disabled":
        run(["/sbin/pfctl", "-d"], check=False)
    ANCHOR.unlink(missing_ok=True)

    if service and NETWORK_BEFORE.exists():
        before = NETWORK_BEFORE.read_text(encoding="utf-8", errors="replace")
        first = before.splitlines()[0] if before.splitlines() else ""
        if "DHCP" in first.upper():
            run(["/usr/sbin/networksetup", "-setdhcp", service])
        elif local_ip and netmask and gateway:
            run(["/usr/sbin/networksetup", "-setmanual", service, local_ip, netmask, gateway])
        if "IPv6: Automatic" in before:
            run(["/usr/sbin/networksetup", "-setv6automatic", service])

    print(
        "Mac Brain network containment removed by local administrator. "
        "Pre-install PF/network configuration restored as closely as recorded."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
