from __future__ import annotations

import re
import threading
import time
from typing import Optional

from . import db
from .agent import ask as agent_ask
from .config import mission_active, set_mission_active


def is_affirmative(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    normalized = " ".join(normalized.split())
    if not normalized:
        return False
    phrases = (
        "yes", "yeah", "yep", "yup", "go", "go for it", "start", "start it",
        "start mission", "do it", "begin", "affirmative", "you got it",
    )
    if normalized in phrases:
        return True
    if "go for it" in normalized or normalized.startswith("yes ") or normalized.startswith("yeah "):
        return True
    return False


def _report_watcher(stop: threading.Event, start_id: int) -> None:
    last_id = start_id
    while not stop.wait(1.0):
        try:
            rows = db.reports_since(last_id, 25)
        except Exception:
            continue
        for row in rows:
            last_id = max(last_id, int(row["id"]))
            stamp = time.strftime("%H:%M:%S", time.localtime(float(row["ts"])))
            print(f"\n[Mac Brain {stamp} · {row['kind']}] {row['text']}\n", flush=True)



def is_takeover_phrase(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    normalized = " ".join(normalized.split())
    return normalized in {
        "take over mac brain",
        "take over",
        "arm mac brain",
        "give mac brain the computer",
    }


def run_prearm_console() -> int:
    """Interactive demonstration stage while ordinary networking is still intact.

    Mac Brain may inspect and reason using only its read-only/proposal tools. The autonomous
    background mission is not enabled here, and no network containment has been applied yet.
    The installer continues to the irreversible-ish network handoff only after an explicit
    TAKE OVER MAC BRAIN command.
    """
    print("\n=== MAC BRAIN DEMONSTRATION STAGE ===")
    print("Hey John. I'm Mac Brain. Networking is still normal right now.")
    print("I can inspect this Mac, reason locally, and show you what I think is making it slow, but I am not yet running the autonomous mission and I cannot delete anything on my own.")
    print("Ask me something like: can you speed this up?")
    print("When you're satisfied that I can inspect the machine intelligently, type: TAKE OVER MAC BRAIN")
    print("That returns control to the installer, which will apply the SSH-only/no-egress containment before the autonomous mission starts.\n")

    while True:
        try:
            text = input("macbrain-demo> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 2
        if not text:
            continue
        lower = text.lower().strip()
        if is_takeover_phrase(text):
            print("Takeover approved. Returning to the installer so it can arm low-level network containment first.")
            return 0
        if lower in {"quit", "exit", "cancel"}:
            print("Takeover cancelled. Networking remains normal and the autonomous mission has not started.")
            return 2
        if lower in {"proposals", "show proposals"}:
            from .__main__ import print_proposals
            print_proposals()
            continue
        if lower == "status":
            from .__main__ import print_status
            print_status()
            continue
        if lower in {"help", "?"}:
            print("Ask me normal questions. Useful examples: 'can you speed this up?', 'show me the biggest files', 'what looks redundant?', 'what is using CPU?'. Type TAKE OVER MAC BRAIN when satisfied.")
            continue
        print("Thinking locally in demonstration mode. I can inspect and propose, but not execute cleanup...")
        try:
            print(agent_ask(text))
        except Exception as exc:
            print(f"Local AI error: {exc}")


def run_console() -> int:
    active = mission_active()
    if active:
        print("Hey John. I'm Mac Brain, your local AI unit. My mission is already active: speed up this computer.")
        print("I'll keep working in the background after this terminal closes. Reports will appear here while this console is open.")
    else:
        print("Hey John. I'm Mac Brain, your local AI unit. I'm here to speed up this computer.")
        print("My mission is to hunt for evidence explaining why this Mac is slow, find reclaimable junk carefully, and propose changes without deleting anything on my own.")
        print("If that's what you want, tell me to go for it.")

    stop = threading.Event()
    watcher = threading.Thread(target=_report_watcher, args=(stop, db.latest_report_id()), daemon=True)
    watcher.start()
    try:
        while True:
            try:
                text = input("macbrain> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            lower = text.lower().strip()

            if not mission_active():
                if is_affirmative(text):
                    set_mission_active(True)
                    db.add_report(
                        "mission",
                        "Mission accepted. SPEED UP MAC BRAIN is active. I am monitoring continuously; heavier filesystem investigation and local AI reasoning will run in the background when this Mac is on AC power and sufficiently idle. I will not delete anything without your explicit approval.",
                    )
                    print("Mission active. Go do something else if you want; I will keep working after this terminal closes.")
                    continue
                if lower in {"quit", "exit"}:
                    break
                print("I haven't started the autonomous mission yet. Say 'go for it', 'yes', or 'start mission' when you want me to begin.")
                continue

            if lower in {"quit", "exit"}:
                print("Leaving the console. The background mission keeps running.")
                break
            if lower in {"pause", "pause mission", "stop mission"}:
                set_mission_active(False)
                db.add_report("mission", "Mission paused by John. Cheap evidence collection remains available, but autonomous deep scans and AI reasoning are paused.")
                print("Mission paused. Say 'go for it' when you want me to resume.")
                continue
            if lower in {"resume", "resume mission", "start", "start mission", "go", "go for it"}:
                set_mission_active(True)
                db.add_report("mission", "Mission resumed. SPEED UP MAC BRAIN is active again.")
                print("Mission active.")
                continue
            if lower == "status":
                from .__main__ import print_status
                print_status()
                continue
            if lower in {"proposals", "show proposals"}:
                from .__main__ import print_proposals
                print_proposals()
                continue
            if lower in {"help", "?"}:
                print("Talk to me normally, or use: status | proposals | pause | resume | quit")
                continue

            print("Thinking locally. The background hunter is still running...")
            try:
                print(agent_ask(text))
            except Exception as exc:
                print(f"Local AI error: {exc}")
        return 0
    finally:
        stop.set()
