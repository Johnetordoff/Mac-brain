#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ANCHOR = Path("/etc/pf.anchors/macbrain")
ANCHOR_NEW = Path("/etc/pf.anchors/macbrain.new")
BACKUP = Path("/etc/pf.conf.macbrain-backup")
PF_CONF = Path("/etc/pf.conf")
PF_NEW = Path("/etc/pf.conf.macbrain-new")
SUPPORT = Path("/Library/Application Support/MacBrain")
DAEMON = Path("/Library/LaunchDaemons/com.macbrain.networklock.plist")
WATCHDOG = SUPPORT / "network-watchdog.py"
WATCHDOG_CONFIG = SUPPORT / "network-watchdog.json"
PF_STATE = SUPPORT / "pf-was-enabled"
NETWORK_BEFORE = SUPPORT / "network-before.txt"
NETWORK_META = SUPPORT / "network-meta.json"
CONTAINMENT_MARKER = SUPPORT / "containment-active"


def run(args: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode != 0:
        detail = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{detail}")
    return result


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Must run as root.")


def root_private(path: Path, mode: int = 0o600) -> None:
    os.chown(path, 0, 0)
    os.chmod(path, mode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--gateway", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--netmask", required=True)
    args = parser.parse_args()
    for value in (args.source, args.gateway, args.ip, args.netmask):
        ipaddress.IPv4Address(value)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.interface):
        parser.error("invalid interface")
    if not args.service.strip():
        parser.error("network service is required")
    return args


def pf_enabled() -> bool:
    result = run(["/sbin/pfctl", "-s", "info"], check=False, capture=True)
    return result.returncode == 0 and "Status: Enabled" in (result.stdout or "")


def prepare_support(args: argparse.Namespace) -> None:
    SUPPORT.mkdir(parents=True, exist_ok=True)
    root_private(SUPPORT, 0o700)
    if not PF_STATE.exists():
        PF_STATE.write_text("enabled\n" if pf_enabled() else "disabled\n", encoding="utf-8")
        root_private(PF_STATE)
    if not BACKUP.exists():
        shutil.copy2(PF_CONF, BACKUP)
        root_private(BACKUP)
    if not NETWORK_BEFORE.exists():
        result = run(["/usr/sbin/networksetup", "-getinfo", args.service], capture=True)
        NETWORK_BEFORE.write_text(result.stdout or "", encoding="utf-8")
        root_private(NETWORK_BEFORE)
    NETWORK_META.write_text(
        json.dumps(
            {
                "service": args.service,
                "interface": args.interface,
                "gateway": args.gateway,
                "local_ip": args.ip,
                "netmask": args.netmask,
                "source": args.source,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    root_private(NETWORK_META)


def anchor_text(args: argparse.Namespace) -> str:
    return (
        "# Speed Up Mac Brain containment anchor. Root-owned; Mac Brain cannot modify it.\n"
        "pass quick on lo0 all\n\n"
        "# The one ordinary remote doorway: controller-initiated IPv4 SSH.\n"
        f"pass in quick on {args.interface} inet proto tcp from {args.source} "
        f"to {args.ip} port 22 flags any keep state\n\n"
        "# No other IP traffic. Established SSH replies use the state above.\n"
        f"block drop quick on {args.interface} inet6 all\n"
        f"block drop quick on {args.interface} inet all\n"
    )


def _is_apple_filter_anchor(line: str) -> bool:
    """Recognize Apple's wildcard PF filter anchor without regex escaping ambiguity."""
    stripped = line.strip()
    return stripped.startswith('anchor "com.apple/*"')


def build_pf_config() -> None:
    original = PF_CONF.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    inserted = False
    for line in original:
        stripped = line.strip()
        if stripped.startswith('anchor "macbrain"') or stripped.startswith('load anchor "macbrain"'):
            continue
        if not inserted and _is_apple_filter_anchor(line):
            output.append('anchor "macbrain"')
            inserted = True
        output.append(line)
    if not inserted:
        output.append('anchor "macbrain"')
    output.append('load anchor "macbrain" from "/etc/pf.anchors/macbrain"')
    PF_NEW.write_text("\n".join(output) + "\n", encoding="utf-8")
    root_private(PF_NEW)


def install_pf(args: argparse.Namespace) -> None:
    old_anchor = ANCHOR.with_suffix(".previous")
    if ANCHOR.exists():
        shutil.copy2(ANCHOR, old_anchor)
        root_private(old_anchor)
    ANCHOR_NEW.write_text(anchor_text(args), encoding="utf-8")
    root_private(ANCHOR_NEW)
    shutil.copy2(ANCHOR_NEW, ANCHOR)
    root_private(ANCHOR)
    validation = run(["/sbin/pfctl", "-nf", str(PF_NEW)], check=False, capture=True)
    if validation.returncode != 0:
        if old_anchor.exists():
            shutil.move(old_anchor, ANCHOR)
        else:
            ANCHOR.unlink(missing_ok=True)
        ANCHOR_NEW.unlink(missing_ok=True)
        PF_NEW.unlink(missing_ok=True)
        detail = ((validation.stderr or "") + "\n" + (validation.stdout or "")).strip()
        raise RuntimeError(f"PF validation failed; existing networking left active: {detail}")
    old_anchor.unlink(missing_ok=True)
    ANCHOR_NEW.unlink(missing_ok=True)
    shutil.move(PF_NEW, PF_CONF)
    root_private(PF_CONF, 0o644)
    root_private(ANCHOR)


def restore_network_from_record(args: argparse.Namespace) -> None:
    if not NETWORK_BEFORE.exists():
        return
    before = NETWORK_BEFORE.read_text(encoding="utf-8", errors="replace")
    first = before.splitlines()[0] if before.splitlines() else ""
    if "DHCP" in first.upper():
        run(["/usr/sbin/networksetup", "-setdhcp", args.service], check=False)
    else:
        run(
            ["/usr/sbin/networksetup", "-setmanual", args.service, args.ip, args.netmask, args.gateway],
            check=False,
        )
    if "IPv6: Automatic" in before:
        run(["/usr/sbin/networksetup", "-setv6automatic", args.service], check=False)


def rollback_all(args: argparse.Namespace) -> None:
    run(["/bin/launchctl", "unload", str(DAEMON)], check=False)
    for path in (DAEMON, WATCHDOG, WATCHDOG_CONFIG, CONTAINMENT_MARKER):
        path.unlink(missing_ok=True)
    if BACKUP.exists():
        shutil.copy2(BACKUP, PF_CONF)
        run(["/sbin/pfctl", "-f", str(PF_CONF)], check=False)
    if PF_STATE.exists() and PF_STATE.read_text(encoding="utf-8").strip() == "disabled":
        run(["/sbin/pfctl", "-d"], check=False)
    ANCHOR.unlink(missing_ok=True)
    restore_network_from_record(args)


def install_watchdog(args: argparse.Namespace) -> None:
    source = Path(__file__).resolve().with_name("network_watchdog.py")
    if not source.exists():
        raise RuntimeError(f"watchdog source missing: {source}")
    shutil.copy2(source, WATCHDOG)
    root_private(WATCHDOG, 0o700)
    WATCHDOG_CONFIG.write_text(json.dumps({"service": args.service}) + "\n", encoding="utf-8")
    root_private(WATCHDOG_CONFIG)
    payload = {
        "Label": "com.macbrain.networklock",
        "ProgramArguments": [str(Path(sys.executable).resolve()), str(WATCHDOG), "--config", str(WATCHDOG_CONFIG)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
    }
    with DAEMON.open("wb") as fh:
        plistlib.dump(payload, fh)
    root_private(DAEMON)
    run(["/bin/launchctl", "unload", str(DAEMON)], check=False)
    run(["/bin/launchctl", "load", str(DAEMON)])


def verify(args: argparse.Namespace) -> None:
    pf_info = run(["/sbin/pfctl", "-s", "info"], check=False, capture=True).stdout or ""
    pf_rules = run(["/sbin/pfctl", "-a", "macbrain", "-sr"], check=False, capture=True).stdout or ""
    net_info = run(["/usr/sbin/networksetup", "-getinfo", args.service], check=False, capture=True).stdout or ""
    expected = f"pass in quick on {args.interface} inet proto tcp from {args.source}"
    if "Status: Enabled" not in pf_info:
        raise RuntimeError("PF is not enabled")
    if expected not in pf_rules:
        raise RuntimeError("controller SSH rule is missing")
    if "block drop quick" not in pf_rules:
        raise RuntimeError("blocking PF rule is missing")
    if run(["/sbin/route", "-n", "get", "default"], check=False, capture=True).returncode == 0:
        raise RuntimeError("IPv4 default route is still present")
    if "IPv6: Off" not in net_info:
        raise RuntimeError("IPv6 is not disabled on the active network service")

    macbrain_line = None
    apple_line = None
    for index, line in enumerate(PF_CONF.read_text(encoding="utf-8").splitlines(), start=1):
        if macbrain_line is None and line.strip() == 'anchor "macbrain"':
            macbrain_line = index
        if apple_line is None and _is_apple_filter_anchor(line):
            apple_line = index
    if macbrain_line is None:
        raise RuntimeError("Mac Brain PF anchor is missing from pf.conf")
    if apple_line is not None and macbrain_line >= apple_line:
        raise RuntimeError("Mac Brain PF anchor is not ahead of Apple's filter anchor")


def apply_network_boundary(args: argparse.Namespace) -> None:
    run(["/usr/sbin/networksetup", "-setmanual", args.service, args.ip, args.netmask, args.gateway])
    run(["/usr/sbin/networksetup", "-setv6off", args.service])
    run(["/sbin/route", "-n", "delete", "default"], check=False)
    run(["/sbin/pfctl", "-f", str(PF_CONF)])
    run(["/sbin/pfctl", "-e"], check=False)


def main() -> int:
    require_root()
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    args = parse_args()
    prepare_support(args)
    try:
        build_pf_config()
        install_pf(args)
        apply_network_boundary(args)
        install_watchdog(args)
        verify(args)
        CONTAINMENT_MARKER.write_text("armed\n", encoding="utf-8")
        root_private(CONTAINMENT_MARKER)
    except Exception as exc:
        print(f"Containment setup failed; restoring pre-Mac-Brain networking: {exc}", file=sys.stderr)
        rollback_all(args)
        return 1

    print("Mac Brain network containment armed and verified.")
    print(f"Controller SSH source: {args.source}")
    print(f"Interface: {args.interface} ({args.service})")
    print("IPv4 default route: removed")
    print("IPv6: disabled on active service")
    print("PF: only controller-initiated SSH is permitted at the IP layer")
    print("Root watchdog: active")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
