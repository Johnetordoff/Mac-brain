from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from . import __version__, db
from .actions import permanent_delete, quarantine
from .agent import ask as agent_ask
from .config import DB_PATH, load_config, mission_active
from .hunter import daemon, run_once


def _bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n)
    for unit in units:
        if x < 1024 or unit == units[-1]:
            return f"{x:.1f} {unit}"
        x /= 1024
    return f"{n} B"


def print_status() -> None:
    result = run_once(deep=False)["snapshot"]
    disk = result["disk"]
    swap = result["swap"]
    load = result["load"]
    print(f"Mac Brain {__version__}")
    print("Mission: SPEED UP MAC BRAIN")
    print(f"Load: {load['1m']:.2f} / {load['5m']:.2f} / {load['15m']:.2f} on {load['cpus']} CPU(s)")
    print(f"Disk free: {_bytes(disk['free'])} of {_bytes(disk['total'])}")
    print(f"Swap used: {_bytes(swap['used'])}")
    battery = result.get("battery", {})
    if battery:
        pct = battery.get("percent")
        pct_text = f" {pct}%" if pct is not None else ""
        print(f"Power: {battery.get('source', 'unknown')}{pct_text} ({battery.get('status', 'unknown')})")
    print("Top CPU processes:")
    for p in result["processes"][:8]:
        print(f"  {p['cpu']:6.1f}%  pid {p['pid']:>5}  {p['command']}")
    print(f"Mission active: {'yes' if mission_active() else 'no'}")
    print(f"Open proposals: {len(db.list_proposals('open'))}")
    print(f"Evidence DB: {DB_PATH}")


def print_proposals() -> None:
    rows = db.list_proposals("open")
    if not rows:
        print("No open proposals.")
        return
    for r in rows:
        print(f"P{r['id']:04d}  {r['title']}")
        print(f"       kind: {r['kind']}")
        if r.get("target"):
            print(f"       target: {r['target']}")
        print(f"       evidence: {r['evidence']}")
        print(f"       expected benefit: {r['expected_benefit']}")
        print(f"       risk: {r['risk']}")
        print()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="macbrain")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("monitor")
    sub.add_parser("doctor")
    sub.add_parser("console")
    sub.add_parser("prearm-console")
    sub.add_parser("security-audit")
    first = sub.add_parser("first-mission")
    first.add_argument("--no-llm", action="store_true")
    q = sub.add_parser("ask")
    q.add_argument("question")
    sub.add_parser("proposals")
    p = sub.add_parser("proposal")
    p.add_argument("id")
    a = sub.add_parser("approve")
    a.add_argument("id")
    mode = a.add_mutually_exclusive_group(required=True)
    mode.add_argument("--quarantine", action="store_true")
    mode.add_argument("--delete", action="store_true")
    a.add_argument("--confirm-delete", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "status":
        print_status()
    elif args.cmd == "monitor":
        daemon()
    elif args.cmd == "console":
        from .console import run_console
        return run_console()
    elif args.cmd == "prearm-console":
        from .console import run_prearm_console
        return run_prearm_console()
    elif args.cmd == "security-audit":
        from .security import security_baseline
        audit = security_baseline()
        db.add_observation("security_baseline", "manual", audit)
        print(json.dumps(audit, indent=2, sort_keys=True))
    elif args.cmd == "doctor":
        from pathlib import Path
        from .config import load_config
        cfg = load_config()
        launch_plist = Path.home() / "Library/LaunchAgents/com.macbrain.performancehunter.plist"
        launch_running = subprocess.run(
            ["/bin/launchctl", "list", "com.macbrain.performancehunter"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        ).returncode == 0
        recent = db.recent_samples(1)
        fresh_sample = bool(recent and time.time() - float(recent[0].get("ts", 0)) < 300)
        checks = {
            "local_model": Path(str(cfg.get("model_path", ""))).exists(),
            "llama_cli": Path(str(cfg.get("llama_cli", ""))).exists(),
            "evidence_db": DB_PATH.exists(),
            "fresh_evidence_sample": fresh_sample,
            "launch_agent_plist": launch_plist.exists(),
            "launch_agent_running": launch_running,
            "command_wrapper": Path("/usr/local/bin/macbrain").exists(),
        }
        for name, ok in checks.items():
            print(f"{'OK' if ok else 'FAIL'}  {name}")
        if not all(checks.values()):
            return 2
        print("Mac Brain local components are present.")
    elif args.cmd == "first-mission":
        # Keep the pre-demonstration pass bounded on this very slow Mac. Deep recursive
        # area scans wait for the background mission when the machine is idle/on AC.
        result = run_once(deep=False)
        from .tools import run_tool
        print("Baseline performance sample complete.")
        print("\nStartup process / persistence / listener audit (non-destructive):")
        try:
            security = run_tool("security_audit", {})
            print(f"  running processes inventoried: {security.get('process_count', 0)}")
            print(f"  third-party process paths seen: {security.get('third_party_process_count', 0)}")
            print(f"  launch items inventoried: {len(security.get('launch_items', []))}")
            print(f"  TCP listeners inventoried: {len(security.get('listeners', []))}")
            print(f"  suspicious/unverified items needing review: {security.get('review_item_count', 0)}")
            for item in security.get("review_items", [])[:12]:
                subject = item.get("path") or item.get("target") or item.get("plist") or item.get("endpoint") or item.get("command") or "unknown"
                reasons = "; ".join(item.get("reasons", []))
                print(f"    REVIEW: {subject} — {reasons}")
            print("  NOTE: review items are not malware verdicts; they are things Mac Brain should explain before optimization.")
        except Exception as exc:
            print(f"  security/process audit could not complete: {exc}")
        print("\nBaseline audit complete.")
        print_proposals()
        print("\nLargest user files found in the bounded first pass (large does NOT mean deletable):")
        try:
            largest = run_tool("largest_files", {"path": str(os.path.expanduser("~")), "limit": 12, "min_mb": 100, "max_entries": 20000})
            for row in largest.get("files", [])[:12]:
                print(f"  {_bytes(int(row['bytes'])):>10}  {row['path']}")
            db.add_observation("largest_files_baseline", str(os.path.expanduser("~")), largest)
        except Exception as exc:
            print(f"  bounded largest-file pass could not complete: {exc}")
        print("\nKnown cleanup candidate areas (still require inspection/approval):")
        try:
            hints = run_tool("cleanup_hints", {"limit": 12, "download_files": 12})
            for row in hints[:12]:
                print(f"  {_bytes(int(row['bytes'])):>10}  {row['category']}: {row['path']}")
            db.add_observation("cleanup_hints_baseline", "known_locations", {"rows": hints})
        except Exception as exc:
            print(f"  cleanup-hint pass could not complete: {exc}")
        if not args.no_llm:
            print("\nMac Brain synthesis:\n")
            print(agent_ask("This is your first mission. Using the evidence you have just collected, explain the strongest current hypotheses for why this Mac is slow and what I should investigate first. Start with the biggest likely-reclaimable areas, but distinguish exact observations from guesses. Do not delete or disable anything."))
    elif args.cmd == "ask":
        print(agent_ask(args.question))
    elif args.cmd == "proposals":
        print_proposals()
    elif args.cmd == "proposal":
        pid = int(str(args.id).upper().lstrip("P"))
        row = db.get_proposal(pid)
        if not row:
            print("Proposal not found", file=sys.stderr)
            return 2
        print(json.dumps(row, indent=2, sort_keys=True))
    elif args.cmd == "approve":
        pid = int(str(args.id).upper().lstrip("P"))
        if args.quarantine:
            dest = quarantine(pid)
            print(f"Quarantined to {dest}")
        else:
            if not args.confirm_delete:
                print("Permanent deletion requires --confirm-delete", file=sys.stderr)
                return 2
            permanent_delete(pid)
            print(f"P{pid:04d} permanently deleted by explicit user command.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
