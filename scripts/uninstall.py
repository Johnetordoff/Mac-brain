#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> int:
    launch = Path.home() / "Library" / "LaunchAgents" / "com.macbrain.performancehunter.plist"
    subprocess.run(["/bin/launchctl", "unload", str(launch)], check=False)
    launch.unlink(missing_ok=True)
    print("Mac Brain Performance Hunter stopped and its user LaunchAgent removed.")
    print("Local model, evidence DB, configuration, Git vault, and quarantine remain in ~/.macbrain.")
    print("The SSH-only network lock is intentionally NOT removed by this program.")
    print("A human administrator at the physical Mac must deliberately run:")
    print("  sudo python3 scripts/network_unlock.py")
    print("before reopening networking.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
