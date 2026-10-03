from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from . import db
from .benchmarks import run_benchmarks
from .config import APP_DIR, load_config
from .crawl import crawl_step
from .diagnostics import build_diagnostic_packet

HANDOFF_DIR = APP_DIR / "handoff"


def _render_report(packet: Dict[str, Any]) -> str:
    benchmark = packet["benchmark"]
    comparison = benchmark.get("comparison", {})
    diagnostic = packet["diagnostic"]
    fs = diagnostic.get("filesystem_inventory", {})
    lines = [
        "MAC BRAIN NIGHTLY SELF-REVIEW",
        f"Date: {packet['date']}",
        f"Repository commit: {benchmark.get('repo_commit', 'unknown')}",
        f"Benchmark verdict: {comparison.get('verdict', 'inconclusive')}",
        "",
        "BENCHMARKS",
    ]
    for metric in comparison.get("metrics", []):
        change = metric.get("percent_change")
        change_text = "n/a" if change is None else f"{change:+.1f}%"
        lines.append(
            f"- {metric.get('metric')}: {metric.get('state')} "
            f"(current={metric.get('current')}, previous={metric.get('previous')}, change={change_text})"
        )

    metrics = benchmark.get("metrics", {})
    lines.extend([
        f"- Free disk: {int(metrics.get('disk_free_bytes', 0)) / (1024**3):.1f} GB",
        f"- Swap used: {int(metrics.get('swap_used_bytes', 0)) / (1024**3):.2f} GB",
        f"- Load per CPU at benchmark time: {float(metrics.get('load_per_cpu', 0.0)):.2f}",
        "",
        "FILESYSTEM INVENTORY",
        f"- Files indexed: {fs.get('files_seen', 0)}",
        f"- Indexed file bytes: {int(fs.get('file_bytes_indexed', 0)) / (1024**3):.1f} GB",
        f"- Crawl frontier remaining: {fs.get('frontier_directories', 0)} directories",
        f"- Nightly crawl steps: {packet.get('crawl', {}).get('steps', 0)}",
        f"- Nightly crawl entries examined: {packet.get('crawl', {}).get('entries_seen', 0)}",
        "",
        "EVIDENCE-BACKED BOTTLENECKS",
    ])
    bottlenecks = diagnostic.get("bottlenecks", [])
    if not bottlenecks:
        lines.append("- No strong bottleneck has enough evidence yet.")
    for item in bottlenecks[:20]:
        lines.append(
            f"- [{str(item.get('severity', 'info')).upper()}] "
            f"{item.get('kind')}: {item.get('subject')}"
        )
        lines.append(f"  Evidence: {json.dumps(item.get('evidence', {}), sort_keys=True)}")
        lines.append(f"  Next: {item.get('next_step')}")

    lines.extend(["", "ENGINEERING REQUESTS"])
    requests = diagnostic.get("engineering_requests", [])
    if not requests:
        lines.append("- None yet; continue collecting evidence.")
    for item in requests[:20]:
        lines.append(
            f"- {item.get('id')} [{str(item.get('severity', 'info')).upper()}] "
            f"{item.get('problem')} — {item.get('subject')}"
        )
        lines.append(f"  Requested work: {item.get('requested_engineering_work')}")
        lines.append(f"  Constraint: {item.get('constraint')}")

    analysis = str(packet.get("model_analysis", "")).strip()
    if analysis:
        lines.extend(["", "LOCAL MODEL SELF-REVIEW", analysis])

    lines.extend([
        "",
        "RULE",
        "A change is not considered successful merely because it was deployed.",
        "Re-run the same benchmarks after changes. Keep the change only if evidence supports it,",
        "or retain it explicitly as diagnostic/preparatory work toward a later measurable improvement.",
    ])
    return "\n".join(lines) + "\n"


def _model_review(benchmark: Dict[str, Any]) -> str:
    try:
        from .agent import ask as agent_ask
        verdict = benchmark.get("comparison", {}).get("verdict", "inconclusive")
        commit = benchmark.get("repo_commit", "unknown")
        return agent_ask(
            "Nightly Mac Brain self-review. Use diagnostics, process history, filesystem inventory, "
            "and recent evidence to identify the strongest causes of slowness and the next engineering "
            "work an external, more capable coding agent should perform. "
            f"The repeatable benchmark verdict is {verdict}; current repository commit is {commit}. "
            "Do not call a change successful unless benchmark evidence supports that. A change may still "
            "be useful if it improves diagnosis or prepares a later fix. Prefer concrete evidence and "
            "specific next investigations. Do not delete files, kill processes, disable services, change "
            "networking, or generate a Git operation."
        )
    except Exception as exc:
        return f"Local model review unavailable: {type(exc).__name__}: {exc}"[:1000]


def run_nightly(*, include_model_review: bool = True) -> Dict[str, Any]:
    cfg = load_config()
    started = time.time()
    max_minutes = max(5, min(int(cfg.get("nightly_crawl_minutes", 45)), 240))
    deadline = time.monotonic() + max_minutes * 60

    benchmark = run_benchmarks(
        include_inference=bool(cfg.get("nightly_include_inference_benchmark", True))
    )

    crawl_steps = 0
    crawl_entries = 0
    last_crawl: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_crawl = crawl_step(
            max_directories=50,
            max_entries_per_directory=500,
            min_large_mb=100,
        )
        crawl_steps += 1
        crawl_entries += int(last_crawl.get("entries_seen", 0) or 0)
        if last_crawl.get("complete"):
            break
        # Yield between filesystem batches on the old Mac.
        time.sleep(1)

    diagnostic = build_diagnostic_packet(
        sample_limit=360,
        deep=True,
        collect_current=True,
    )
    model_analysis = _model_review(benchmark) if include_model_review else ""

    now = datetime.now().astimezone()
    packet: Dict[str, Any] = {
        "nightly_version": 1,
        "date": now.date().isoformat(),
        "started_ts": started,
        "finished_ts": time.time(),
        "benchmark": benchmark,
        "crawl": {
            "steps": crawl_steps,
            "entries_seen": crawl_entries,
            "last_result": last_crawl,
            "time_budget_minutes": max_minutes,
        },
        "diagnostic": diagnostic,
        "model_analysis": model_analysis,
        "success_rule": (
            "Compare repeatable benchmarks before/after changes. Improvement is evidence-backed, "
            "not assumed. Stable/regressed/mixed results require more diagnosis or a new solution; "
            "diagnostic/preparatory changes may be retained when explicitly justified."
        ),
    }

    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(packet, indent=2, sort_keys=True) + "\n"
    text_report = _render_report(packet)
    date_name = packet["date"]
    (HANDOFF_DIR / f"nightly-{date_name}.json").write_text(json_text, encoding="utf-8")
    (HANDOFF_DIR / f"nightly-{date_name}.txt").write_text(text_report, encoding="utf-8")
    (HANDOFF_DIR / "latest.json").write_text(json_text, encoding="utf-8")
    (HANDOFF_DIR / "latest.txt").write_text(text_report, encoding="utf-8")
    db.set_runtime_state("last_nightly_date", date_name)
    db.add_report(
        "nightly",
        f"Nightly self-review complete for {date_name}; benchmark verdict: "
        f"{benchmark.get('comparison', {}).get('verdict', 'inconclusive')}.",
    )
    return packet


def latest_nightly() -> Dict[str, Any] | None:
    path = HANDOFF_DIR / "latest.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None
