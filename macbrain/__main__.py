from __future__ import annotations

import argparse
import json
import os
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


def _print_git_repos() -> None:
    from .gitstore import list_repos
    names = list_repos()
    if not names:
        print("No Mac Brain Git repositories yet.")
        print("Create one with: macbrain git create NAME")
        return
    for name in names:
        print(name)


def _print_git_capacity() -> None:
    from .gitstore import storage_capacity
    capacity = storage_capacity()
    print(f"Disk total: {_bytes(int(capacity['total']))}")
    print(f"Disk free: {_bytes(int(capacity['free']))}")
    print(f"Protected free-space reserve: {_bytes(int(capacity['reserve']))}")
    print(f"Maximum one incoming Git receive: {_bytes(int(capacity['max_receive_bytes']))}")
    print(f"Accept new Git data: {'yes' if capacity['write_ok'] else 'no'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="macbrain")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("monitor")
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--expect-running", action="store_true")
    sub.add_parser("console")
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("prearm-console")
    sub.add_parser("security-audit")
    sub.add_parser("remote", help="serve one inbound controller JSON request on stdin/stdout")
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

    git_parser = sub.add_parser(
        "git",
        help="manage the passive inbound-only Git vault; no model reasoning or outbound sync",
    )
    git_sub = git_parser.add_subparsers(dest="git_cmd", required=True)
    git_sub.add_parser("list", help="cheap name-only listing of stored repositories")
    git_sub.add_parser("capacity", help="show free-space guard without scanning repositories")
    git_create = git_sub.add_parser("create", help="create an empty guarded bare repository")
    git_create.add_argument("name")
    git_info = git_sub.add_parser("info", help="explicitly inspect one repository")
    git_info.add_argument("name")

    args = parser.parse_args(argv)
    if args.cmd == "status":
        print_status()
    elif args.cmd == "monitor":
        daemon()
    elif args.cmd == "start":
        from .lifecycle import start_mac_brain
        try:
            state = start_mac_brain(require_tty=True)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print("Mac Brain started by explicit user command.")
        print(f"Background worker running: {'yes' if state.get('running') else 'no'}")
    elif args.cmd == "stop":
        from .lifecycle import stop_mac_brain
        state = stop_mac_brain()
        print("Mac Brain is OFF. Autonomous AI/background work is stopped.")
        if state.get("terminated_llama_pids"):
            print("Stopped local Qwen process(es): " + ", ".join(str(x) for x in state["terminated_llama_pids"]))
        print("It will remain OFF after logout or reboot until you explicitly run `macbrain start` and type START MAC BRAIN.")
    elif args.cmd == "console":
        from .console import run_console
        return run_console()
    elif args.cmd == "prearm-console":
        from .console import run_prearm_console
        return run_prearm_console()
    elif args.cmd == "remote":
        from .remote import run_stdio
        return run_stdio()
    elif args.cmd == "security-audit":
        from .security import security_baseline
        audit = security_baseline()
        db.add_observation("security_baseline", "manual", audit)
        print(json.dumps(audit, indent=2, sort_keys=True))
    elif args.cmd == "doctor":
        from pathlib import Path
        from .config import load_config
        cfg = load_config()
        from .lifecycle import CONTAINMENT_MARKER, LAUNCH_AGENT, launch_agent_running
        launch_plist = LAUNCH_AGENT
        launch_running = launch_agent_running()
        recent = db.recent_samples(1)
        fresh_sample = bool(recent and time.time() - float(recent[0].get("ts", 0)) < 300)
        active = mission_active()
        containment_marker = CONTAINMENT_MARKER
        # Before containment the installer intentionally starts the worker for a short
        # proof-of-life check. After containment, OFF means the worker must be unloaded.
        expect_running = bool(args.expect_running or active or not containment_marker.exists())
        checks = {
            "local_model": Path(str(cfg.get("model_path", ""))).exists(),
            "llama_cli": Path(str(cfg.get("llama_cli", ""))).exists(),
            "evidence_db": DB_PATH.exists(),
            "fresh_evidence_sample": fresh_sample,
            "launch_agent_plist": launch_plist.exists(),
            "launch_agent_state_expected": (launch_running == expect_running),
            "command_wrapper": Path("/usr/local/bin/macbrain").exists(),
        }
        for name, ok in checks.items():
            print(f"{'OK' if ok else 'FAIL'}  {name}")
        if not all(checks.values()):
            return 2
        print("Mac Brain local components are present.")
    elif args.cmd == "git":
        from .gitstore import create_repo, repo_summary
        try:
            if args.git_cmd == "list":
                _print_git_repos()
            elif args.git_cmd == "capacity":
                _print_git_capacity()
            elif args.git_cmd == "create":
                path = create_repo(args.name)
                print(f"Created passive guarded bare repository: {path}")
                print(f"SSH path from the authorized controller: .macbrain/git/{args.name}.git")
            elif args.git_cmd == "info":
                print(json.dumps(repo_summary(args.name), indent=2, sort_keys=True))
        except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
            print(f"Mac Brain Git: {exc}", file=sys.stderr)
            return 2
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
        if not mission_active():
            print("Mac Brain is OFF. Run `macbrain start` first.", file=sys.stderr)
            return 2
        print(agent_ask(args.question))
    elif args.cmd == "proposals":
        print_proposals()
    elif args.cmd in ("proposal", "approve"):
        try:
            pid = int(str(args.id).upper().lstrip("P"))
        except ValueError:
            print(f"Not a proposal id: {args.id} (expected something like P0007)", file=sys.stderr)
            return 2
    if args.cmd == "proposal":
        row = db.get_proposal(pid)
        if not row:
            print("Proposal not found", file=sys.stderr)
            return 2
        print(json.dumps(row, indent=2, sort_keys=True))
    elif args.cmd == "approve":
        try:
            if args.quarantine:
                dest = quarantine(pid)
                print(f"Quarantined to {dest}")
            else:
                if not args.confirm_delete:
                    print("Permanent deletion requires --confirm-delete", file=sys.stderr)
                    return 2
                permanent_delete(pid)
                print(f"P{pid:04d} permanently deleted by explicit user command.")
        except (PermissionError, FileNotFoundError, ValueError) as exc:
            print(f"P{pid:04d} not changed: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
