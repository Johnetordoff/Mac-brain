from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db
from .config import load_config, mission_active
from .metrics import battery_health, child_directory_sizes, collect_snapshot, directory_sizes, on_ac_power

GB = 1024 ** 3


def analyze_snapshot(s: Dict[str, Any]) -> List[int]:
    proposal_ids: List[int] = []
    disk = s.get("disk", {})
    total = max(int(disk.get("total", 0)), 1)
    free = int(disk.get("free", 0))
    free_pct = free / total
    if free < 20 * GB or free_pct < 0.10:
        proposal_ids.append(db.create_proposal(
            title=f"Disk space is low ({free/GB:.1f} GB free)",
            kind="low_disk",
            target="/",
            evidence=f"Root volume has {free/GB:.1f} GB free ({free_pct*100:.1f}% of total).",
            expected_benefit="Reclaiming safe disk space can reduce filesystem pressure and give swap/caches more working room.",
            risk="Diagnosis only. Do not delete files solely because they are large.",
            action="deep_storage_scan",
        ))

    swap = int(s.get("swap", {}).get("used", 0))
    memory = int(s.get("memory_total", 0))
    if swap > 1 * GB:
        memory_text = f" on a {memory/GB:.1f} GB Mac" if memory else ""
        proposal_ids.append(db.create_proposal(
            title=f"Heavy swap use ({swap/GB:.1f} GB)",
            kind="swap_pressure",
            target=None,
            evidence=f"vm.swapusage reports {swap/GB:.2f} GB in use{memory_text}.",
            expected_benefit="Reducing sustained memory pressure may improve responsiveness.",
            risk="Do not kill processes automatically; determine which workload is responsible first.",
            action="inspect_memory_processes",
        ))

    for proc in s.get("processes", []):
        cpu = float(proc.get("cpu", 0))
        cmd = proc.get("command", "")
        if cpu >= 75:
            proposal_ids.append(db.create_proposal(
                title=f"High CPU process: {Path(cmd).name or cmd} ({cpu:.0f}%)",
                kind="high_cpu",
                target=cmd,
                evidence=f"PID {proc.get('pid')} is currently using about {cpu:.1f}% CPU.",
                expected_benefit="If sustained and unnecessary, reducing this process can improve responsiveness.",
                risk="A single sample can be misleading. Confirm persistence before stopping anything.",
                action="observe_process",
            ))
    return proposal_ids


def inspect_battery_health() -> Dict[str, Any]:
    health = battery_health()
    if not health:
        return health
    db.add_observation("battery_health", "internal_battery", health)
    condition = str(health.get("condition", "")).strip()
    max_cap = str(health.get("maximum_capacity", "")).strip()
    bad_condition = bool(condition and condition.lower() not in {"normal", "good"})
    cap_match = None
    if max_cap.endswith("%"):
        try:
            cap_match = int(max_cap.rstrip("% "))
        except ValueError:
            pass
    if bad_condition or (cap_match is not None and cap_match < 80):
        evidence_parts = []
        if condition:
            evidence_parts.append(f"battery condition: {condition}")
        if max_cap:
            evidence_parts.append(f"maximum capacity: {max_cap}")
        if "cycle_count" in health:
            evidence_parts.append(f"cycle count: {health['cycle_count']}")
        db.create_proposal(
            title="Worn battery may be relevant to power/performance behavior",
            kind="battery_health",
            target=None,
            evidence="; ".join(evidence_parts) or "Battery health fields indicate degradation.",
            expected_benefit="Keeping Mac Brain on AC power avoids adding heavy scan/model load while the worn battery is discharging.",
            risk="Battery wear does not by itself prove the cause of slowness. Treat this as diagnostic context, not a cleanup action.",
            action="observe_power_behavior",
        )
    return health


def _record_storage_rows(rows: List[Dict[str, Any]]) -> None:
    for item in rows:
        db.add_observation("directory_size", item["path"], item)
        if item["bytes"] >= 10 * GB:
            db.create_proposal(
                title=f"Large area worth investigating: {item['path']} ({item['bytes']/GB:.1f} GB)",
                kind="large_directory",
                target=item["path"],
                evidence="Targeted scan found a large directory. Size alone is not evidence that it is disposable.",
                expected_benefit="Inspecting this area may reveal caches, build artifacts, old installers, or archives that can be reclaimed safely.",
                risk="Contents may be important user data. Read/classify before proposing deletion.",
                action="inspect_directory",
            )


def deep_storage_scan(roots: Optional[List[Path]] = None) -> List[Dict[str, Any]]:
    home = Path.home()
    if roots is None:
        roots = [
            home / "Library" / "Caches",
            home / "Library" / "Developer",
            home / "Downloads",
            Path("/Library/Caches"),
            Path("/Applications"),
        ]
    rows: List[Dict[str, Any]] = []
    roots_existing = [r for r in roots if r.exists()]
    rows.extend(directory_sizes(roots_existing))
    for root in roots_existing:
        rows.extend(child_directory_sizes(root, max_children=80))
    dedup = {row["path"]: row for row in rows}
    rows = sorted(dedup.values(), key=lambda x: x["bytes"], reverse=True)[:160]
    _record_storage_rows(rows)
    return rows


def run_once(deep: bool = False) -> Dict[str, Any]:
    snapshot = collect_snapshot()
    db.add_sample(snapshot)
    proposals = analyze_snapshot(snapshot)
    battery = inspect_battery_health() if deep else {}
    deep_results = deep_storage_scan() if deep else []
    return {"snapshot": snapshot, "proposal_ids": proposals, "deep": deep_results, "battery_health": battery}


def _heartbeat_text(snapshot: Dict[str, Any]) -> str:
    disk = snapshot.get("disk", {})
    load = snapshot.get("load", {})
    swap = snapshot.get("swap", {})
    battery = snapshot.get("battery", {})
    top = (snapshot.get("processes") or [{}])[0]
    free = int(disk.get("free", 0)) / GB
    swap_gb = int(swap.get("used", 0)) / GB
    cpus = max(int(load.get("cpus", 1)), 1)
    load1 = float(load.get("1m", 0.0))
    top_text = "none"
    if top:
        top_text = f"{Path(str(top.get('command', 'unknown'))).name or top.get('command', 'unknown')} at {float(top.get('cpu', 0.0)):.0f}% CPU"
    proposals = len(db.list_proposals("open"))
    source = str(battery.get("source", "unknown"))
    if source.lower() != "ac power":
        next_text = "Heavy AI/storage work is paused until AC power; cheap monitoring continues."
    elif load1 / cpus > float(load_config().get("idle_load_per_cpu_max", 0.55)):
        next_text = "The Mac is busy, so I am monitoring instead of adding heavy AI load right now."
    else:
        next_text = "The machine is quiet enough for background investigation when its next cycle is due."
    return (
        f"Still hunting. 1-minute load {load1:.2f} on {cpus} CPU(s); {free:.1f} GB disk free; "
        f"{swap_gb:.2f} GB swap used; top CPU process: {top_text}; {proposals} open finding(s). {next_text}"
    )


def _run_ai_cycle(done: threading.Event) -> None:
    try:
        from .agent import ask as agent_ask
        db.add_report("ai", "Starting a local AI reasoning cycle over the evidence collected so far. This runs only on this Mac.")
        text = agent_ask(
            "Autonomous SPEED UP MAC BRAIN cycle. Review recent evidence and open proposals. "
            "Investigate the strongest plausible causes of slowness and the most promising reclaimable-storage candidates. "
            "Use local inspection tools as needed, including the progressive filesystem inventory and process/launch-item evidence. Try to disprove your own hypotheses and connect high-CPU processes to their executable or persistence source when possible. If a filesystem target is genuinely well-supported as reclaimable, create a human-review cleanup proposal with propose_cleanup. "
            "Do not delete, quarantine, kill, disable, uninstall, or change networking. End with a concise progress report for John: what you observed, what you currently suspect, and what you will investigate next."
        )
        db.add_observation("llm_synthesis", "performance_hunter", {"text": text})
        db.add_report("ai", text)
    except Exception as exc:
        db.add_observation("llm_error", "performance_hunter", {"error": repr(exc)})
        db.add_report("ai_error", f"Local AI reasoning hit an error: {exc}. Cheap monitoring will continue.")
    finally:
        done.set()


def daemon() -> None:
    # After containment, an unloaded/accidentally loaded LaunchAgent must not do any work
    # unless the user explicitly activated Mac Brain during this boot. Before containment
    # the installer is allowed to run the daemon briefly for its proof-of-life test.
    containment_marker = Path("/Library/Application Support/MacBrain/containment-active")
    if containment_marker.exists() and not mission_active():
        return
    cfg = load_config()
    sample_seconds = max(15, int(cfg.get("sample_seconds", 60)))
    report_every = max(60, int(cfg.get("report_seconds", 120)))
    deep_every = max(300, int(cfg.get("deep_scan_minutes", 30)) * 60)
    synth_every = max(300, int(cfg.get("llm_synthesis_minutes", 15)) * 60)
    battery_every = 6 * 3600
    prune_every = 3600
    last_prune = 0.0
    started = time.time()
    last_deep = started
    last_synthesis = 0.0
    last_report = 0.0
    last_battery = 0.0
    home = Path.home()
    rotating_roots = [
        home,
        home / "Library" / "Application Support",
        home / "Library" / "Containers",
        home / "Library" / "Developer",
        Path("/Library/Application Support"),
        Path("/Users/Shared"),
    ]
    rotating_index = 0
    ai_done = threading.Event()
    ai_done.set()

    while True:
        now = time.time()
        try:
            snapshot = collect_snapshot()
            db.add_sample(snapshot)
            analyze_snapshot(snapshot)
            per_cpu = snapshot["load"]["1m"] / max(snapshot["load"]["cpus"], 1)
            idle = per_cpu <= float(cfg.get("idle_load_per_cpu_max", 0.55))
            ac = on_ac_power(snapshot)

            if now - last_prune >= prune_every:
                db.prune()
                last_prune = now

            if now - last_battery >= battery_every:
                inspect_battery_health()
                last_battery = now

            active = mission_active()
            if active and (last_report == 0.0 or now - last_report >= report_every):
                db.add_report("heartbeat", _heartbeat_text(snapshot))
                last_report = now

            if active and ac and idle and now - last_deep >= deep_every and ai_done.is_set():
                root = rotating_roots[rotating_index % len(rotating_roots)]
                rotating_index += 1
                if root.exists():
                    rows = deep_storage_scan([root])
                    largest = rows[0] if rows else None
                    if largest:
                        db.add_report(
                            "storage",
                            f"Background storage pass inspected {root}. Largest measured item in this pass: {largest['path']} ({largest['bytes']/GB:.1f} GB). I have not deleted anything.",
                        )
                    else:
                        db.add_report("storage", f"Background storage pass inspected {root}; no useful size result was produced. Nothing was changed.")

                from .crawl import crawl_step
                crawl = crawl_step(max_directories=20, max_entries_per_directory=500, min_large_mb=100)
                db.add_report(
                    "filesystem_crawl",
                    "Progressive filesystem inventory advanced by "
                    f"{crawl['directories_scanned']} directorie(s) and {crawl['entries_seen']} entries; "
                    f"{crawl['frontier_directories']} directories remain queued. "
                    f"Complete: {'yes' if crawl['complete'] else 'no'}. Nothing was changed.",
                )
                last_deep = now

            if active and ac and idle and ai_done.is_set() and (last_synthesis == 0.0 or now - last_synthesis >= synth_every):
                ai_done.clear()
                threading.Thread(target=_run_ai_cycle, args=(ai_done,), daemon=True).start()
                last_synthesis = now
        except Exception as exc:
            try:
                db.add_observation("monitor_error", "daemon", {"error": repr(exc)})
                if mission_active():
                    db.add_report("monitor_error", f"Background monitor hit an error: {exc}. I will keep trying on the next cycle.")
            except Exception:
                pass
        time.sleep(sample_seconds)
