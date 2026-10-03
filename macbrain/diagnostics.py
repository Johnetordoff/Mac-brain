from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

from . import db
from .metrics import collect_snapshot

GB = 1024 ** 3
MB = 1024 ** 2


def _severity_rank(name: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "info": 3}.get(name, 9)


def _bottleneck(
    kind: str,
    severity: str,
    subject: str,
    evidence: Dict[str, Any],
    next_step: str,
) -> Dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "subject": subject,
        "evidence": evidence,
        "next_step": next_step,
    }


def _recent_summary(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not samples:
        return {}
    loads = []
    swap = []
    free = []
    cpus = 1
    memory = 0
    for sample in samples:
        load = sample.get("load", {})
        cpus = max(int(load.get("cpus", cpus) or cpus), 1)
        loads.append(float(load.get("1m", 0.0) or 0.0))
        swap.append(int(sample.get("swap", {}).get("used", 0) or 0))
        free.append(int(sample.get("disk", {}).get("free", 0) or 0))
        memory = max(memory, int(sample.get("memory_total", 0) or 0))
    return {
        "samples": len(samples),
        "cpus": cpus,
        "memory_total": memory,
        "load_1m_avg": sum(loads) / len(loads),
        "load_1m_max": max(loads),
        "load_per_cpu_avg": (sum(loads) / len(loads)) / cpus,
        "swap_used_avg": int(sum(swap) / len(swap)),
        "swap_used_max": max(swap),
        "disk_free_min": min(free),
        "disk_free_latest": free[0],
    }


def _launch_matches(processes: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    from .security import security_baseline

    audit = security_baseline()
    by_command: Dict[str, List[Dict[str, Any]]] = {}
    commands = {str(row.get("command", "")) for row in processes}
    basenames = {Path(command).name: command for command in commands if command}
    for item in audit.get("launch_items", []):
        target = str(item.get("target", ""))
        if not target:
            continue
        match = target if target in commands else basenames.get(Path(target).name)
        if match:
            by_command.setdefault(match, []).append({
                "plist": item.get("plist"),
                "label": item.get("label"),
                "target": target,
                "run_at_load": item.get("run_at_load"),
                "keep_alive": item.get("keep_alive"),
            })
    return {
        "matches": by_command,
        "review_items": audit.get("review_items", [])[:40],
        "listeners": audit.get("listeners", [])[:40],
    }


def build_diagnostic_packet(*, sample_limit: int = 60, deep: bool = False) -> Dict[str, Any]:
    """Build deterministic performance evidence for a human/external engineer.

    This diagnoses and requests investigation. It never kills a process, disables a
    service, removes a file, changes networking, or approves a cleanup.
    """
    sample_limit = max(5, min(int(sample_limit), 720))
    current = collect_snapshot()
    db.add_sample(current)
    db.record_process_snapshot(current.get("processes", []))

    samples = db.recent_samples(sample_limit)
    recent = _recent_summary(samples)
    processes = db.process_inventory(80)
    fs = db.filesystem_crawl_stats(20)
    bottlenecks: List[Dict[str, Any]] = []

    disk = current.get("disk", {})
    total = max(int(disk.get("total", 0) or 0), 1)
    free = int(disk.get("free", 0) or 0)
    free_pct = free / total
    if free_pct < 0.10:
        bottlenecks.append(_bottleneck(
            "disk_pressure", "critical", "/",
            {"free_bytes": free, "total_bytes": total, "free_percent": free_pct * 100},
            "Use the filesystem inventory to identify well-supported cleanup candidates; do not delete merely because a file is large.",
        ))
    elif free < 20 * GB or free_pct < 0.15:
        bottlenecks.append(_bottleneck(
            "disk_pressure", "high", "/",
            {"free_bytes": free, "total_bytes": total, "free_percent": free_pct * 100},
            "Inspect large/rebuildable/redundant inventory entries and propose cleanup candidates.",
        ))

    memory = int(current.get("memory_total", 0) or 0)
    swap_used = int(current.get("swap", {}).get("used", 0) or 0)
    swap_max = int(recent.get("swap_used_max", swap_used) or swap_used)
    if swap_max > max(2 * GB, int(memory * 0.35) if memory else 2 * GB):
        severity = "high"
    elif swap_max > 1 * GB:
        severity = "medium"
    else:
        severity = ""
    if severity:
        bottlenecks.append(_bottleneck(
            "memory_pressure", severity, "system",
            {
                "memory_total_bytes": memory,
                "swap_used_now_bytes": swap_used,
                "swap_used_recent_max_bytes": swap_max,
            },
            "Identify recurring high-RSS processes and determine which are required for the MacBrain appliance role.",
        ))

    load_per_cpu = float(recent.get("load_per_cpu_avg", 0.0) or 0.0)
    if load_per_cpu >= 0.85:
        bottlenecks.append(_bottleneck(
            "sustained_cpu_pressure", "high", "system",
            {
                "load_per_cpu_avg": load_per_cpu,
                "load_1m_max": recent.get("load_1m_max", 0.0),
                "sample_count": recent.get("samples", 0),
            },
            "Attribute sustained CPU pressure to recurring processes before changing or stopping anything.",
        ))
    elif load_per_cpu >= 0.55:
        bottlenecks.append(_bottleneck(
            "sustained_cpu_pressure", "medium", "system",
            {
                "load_per_cpu_avg": load_per_cpu,
                "load_1m_max": recent.get("load_1m_max", 0.0),
                "sample_count": recent.get("samples", 0),
            },
            "Continue process sampling and identify repeat offenders.",
        ))

    offenders = []
    for row in processes:
        samples_seen = int(row.get("samples", 0) or 0)
        cpu_max = float(row.get("cpu_max", 0.0) or 0.0)
        cpu_avg = float(row.get("cpu_avg", 0.0) or 0.0)
        rss_max = int(row.get("rss_kb_max", 0) or 0)
        command = str(row.get("command", ""))
        if samples_seen < 2 and cpu_max < 75:
            continue
        if cpu_max >= 75 or cpu_avg >= 20 or rss_max >= 1024 * 1024:
            offenders.append(row)
            kind = "crash_loop_signal" if Path(command).name == "ReportCrash" else "recurring_process_pressure"
            severity = "high" if cpu_max >= 75 or cpu_avg >= 35 else "medium"
            bottlenecks.append(_bottleneck(
                kind,
                severity,
                command,
                {
                    "samples_seen": samples_seen,
                    "cpu_average_while_observed": cpu_avg,
                    "cpu_max": cpu_max,
                    "rss_kb_average_while_observed": row.get("rss_kb_avg", 0),
                    "rss_kb_max": rss_max,
                    "necessity_state": row.get("necessity_state", "unknown"),
                },
                (
                    "Inspect recent crash reports and the repeatedly crashing source process."
                    if kind == "crash_loop_signal"
                    else "Determine executable/persistence source and whether this workload is necessary for MacBrain."
                ),
            ))

    launch_evidence: Dict[str, Any] = {"matches": {}, "review_items": [], "listeners": []}
    if deep:
        launch_evidence = _launch_matches(offenders)

    for item in bottlenecks:
        subject = str(item.get("subject", ""))
        matches = launch_evidence.get("matches", {}).get(subject)
        if matches:
            item["launch_sources"] = matches

    bottlenecks.sort(key=lambda row: (_severity_rank(str(row.get("severity"))), str(row.get("kind")), str(row.get("subject"))))

    requests = []
    for index, item in enumerate(bottlenecks[:12], 1):
        requests.append({
            "id": f"D{index:03d}",
            "problem": item["kind"],
            "subject": item["subject"],
            "severity": item["severity"],
            "evidence": item["evidence"],
            "requested_engineering_work": item["next_step"],
            "constraint": "Measure first; no automatic delete/kill/disable/network change.",
        })

    packet = {
        "packet_version": 1,
        "generated_ts": time.time(),
        "mission": "SPEED UP MAC BRAIN",
        "current": {
            "load": current.get("load", {}),
            "disk": current.get("disk", {}),
            "swap": current.get("swap", {}),
            "memory_total": current.get("memory_total", 0),
            "battery": current.get("battery", {}),
            "thermal": current.get("thermal", ""),
        },
        "recent_summary": recent,
        "filesystem_inventory": {
            "files_seen": fs.get("files_seen", 0),
            "file_bytes_indexed": fs.get("file_bytes_indexed", 0),
            "frontier_directories": fs.get("frontier_directories", 0),
            "necessity_counts": fs.get("necessity_counts", {}),
            "largest_files": fs.get("largest_files", [])[:20],
        },
        "process_inventory": processes[:30],
        "bottlenecks": bottlenecks[:20],
        "engineering_requests": requests,
        "deep_attribution": launch_evidence if deep else {"performed": False},
        "safety": {
            "diagnostic_only": True,
            "automatic_process_termination": False,
            "automatic_file_deletion": False,
            "automatic_service_disable": False,
        },
    }
    db.add_observation("diagnostic_packet", "performance", packet)
    return packet


def render_diagnostic_summary(packet: Dict[str, Any]) -> str:
    current = packet.get("current", {})
    disk = current.get("disk", {})
    swap = current.get("swap", {})
    recent = packet.get("recent_summary", {})
    lines = [
        "MAC BRAIN PERFORMANCE DIAGNOSTIC",
        f"Recent samples: {recent.get('samples', 0)}",
        f"Average 1m load/CPU: {float(recent.get('load_per_cpu_avg', 0.0)):.2f}",
        f"Disk free: {int(disk.get('free', 0)) / GB:.1f} GB of {int(disk.get('total', 0)) / GB:.1f} GB",
        f"Swap used: {int(swap.get('used', 0)) / GB:.2f} GB",
        "",
        "Bottlenecks:",
    ]
    bottlenecks = packet.get("bottlenecks", [])
    if not bottlenecks:
        lines.append("  No strong bottleneck has enough evidence yet; keep sampling/crawling.")
    for item in bottlenecks[:12]:
        lines.append(
            f"  [{str(item.get('severity', 'info')).upper()}] "
            f"{item.get('kind')}: {item.get('subject')}"
        )
        lines.append(f"    Next: {item.get('next_step')}")
    lines.extend(["", "Engineering requests:"])
    requests = packet.get("engineering_requests", [])
    if not requests:
        lines.append("  None yet.")
    for item in requests[:12]:
        lines.append(
            f"  {item.get('id')} [{str(item.get('severity', 'info')).upper()}] "
            f"{item.get('problem')} — {item.get('subject')}"
        )
        lines.append(f"    {item.get('requested_engineering_work')}")
    return "\n".join(lines)
