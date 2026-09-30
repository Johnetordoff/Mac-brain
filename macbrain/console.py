from __future__ import annotations

import re
import threading
import time
from typing import Optional

from . import db
from .agent import ask as agent_ask
from .config import mission_active


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
    return text.strip() == "TAKE OVER MAC BRAIN"


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
    print("That returns control to the installer, which will apply the SSH-only/no-egress containment. Mac Brain will still remain OFF afterward.\n")

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
        print("Hey John. I'm Mac Brain, your local AI unit. I am ON because you explicitly started me.")
        print("I will keep working in the background until you run `macbrain stop` or type STOP MAC BRAIN here.")
    else:
        print("Hey John. I'm Mac Brain, your local AI unit. I am OFF.")
        print("Start is always explicit: leave this console, run `macbrain start`, and type START MAC BRAIN.")
        print("A reboot never starts Mac Brain automatically.")

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

            if text == "STOP MAC BRAIN":
                from .lifecycle import stop_mac_brain
                stop_mac_brain()
                db.add_report("mission", "Mac Brain stopped by explicit user code word.")
                print("Mac Brain is OFF and will remain off after reboot.")
                return 0

            if not mission_active():
                if lower in {"quit", "exit"}:
                    break
                if text == "START MAC BRAIN":
                    print("For startup isolation, use the shell command `macbrain start`; it will ask you to type START MAC BRAIN in an interactive terminal.")
                    continue
                print("Mac Brain is OFF. No ordinary conversation can start it. Run `macbrain start` when you want it on.")
                continue

            if lower in {"quit", "exit"}:
                print("Leaving the console. Mac Brain remains ON until you explicitly run `macbrain stop`.")
                break
            if lower in {"pause", "pause mission", "stop mission", "resume", "resume mission", "start", "start mission", "go", "go for it", "yes", "yeah"}:
                print("Lifecycle changes do not accept conversational shortcuts. Use `macbrain stop` or `macbrain start`.")
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
                print("Talk to me normally, or use: status | proposals | STOP MAC BRAIN | quit")
                continue

            print("Thinking locally. The background hunter is still running...")
            try:
                print(agent_ask(text))
            except Exception as exc:
                print(f"Local AI error: {exc}")
        return 0
    finally:
        stop.set()
