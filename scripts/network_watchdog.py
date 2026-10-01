#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


def run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
    )


def pf_ok() -> bool:
    info = run(["/sbin/pfctl", "-s", "info"], capture=True)
    rules = run(["/sbin/pfctl", "-a", "macbrain", "-sr"], capture=True)
    return (
        info.returncode == 0
        and "Status: Enabled" in (info.stdout or "")
        and rules.returncode == 0
        and "block drop quick" in (rules.stdout or "")
    )


def reassert_pf() -> None:
    run(["/sbin/pfctl", "-f", "/etc/pf.conf"])
    run(["/sbin/pfctl", "-e"])


def remove_default_route() -> None:
    check = run(["/sbin/route", "-n", "get", "default"], capture=True)
    if check.returncode == 0:
        run(["/sbin/route", "-n", "delete", "default"])


def ipv6_is_off(service: str) -> bool:
    result = run(["/usr/sbin/networksetup", "-getinfo", service], capture=True)
    return result.returncode == 0 and "IPv6: Off" in (result.stdout or "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    service = str(config["service"])

    tick = 0
    while True:
        if not pf_ok():
            reassert_pf()
        remove_default_route()
        if tick % 15 == 0 and not ipv6_is_off(service):
            run(["/usr/sbin/networksetup", "-setv6off", service])
        tick += 1
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
