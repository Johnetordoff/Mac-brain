from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db
from .config import APP_DIR
from .metrics import collect_snapshot

MIB = 1024 * 1024
GIB = 1024 * MIB
_DISK_BYTES = 16 * MIB
_CPU_ROUNDS = 220_000


def _repo_commit() -> str:
    root = Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = (result.stdout or "").strip()
    return value if result.returncode == 0 and value else "unknown"


def _cpu_benchmark() -> Dict[str, Any]:
    samples: List[float] = []
    for _ in range(3):
        started = time.perf_counter()
        hashlib.pbkdf2_hmac(
            "sha256",
            b"macbrain-nightly-cpu-benchmark",
            b"fixed-salt-v1",
            _CPU_ROUNDS,
            dklen=32,
        )
        samples.append(time.perf_counter() - started)
    ordered = sorted(samples)
    return {
        "seconds_median": ordered[len(ordered) // 2],
        "seconds_samples": samples,
        "rounds": _CPU_ROUNDS,
        "lower_is_better": True,
    }


def _disk_benchmark() -> Dict[str, Any]:
    bench_dir = APP_DIR / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(str(bench_dir))
    if usage.free < 512 * MIB:
        return {
            "skipped": True,
            "reason": "less than 512 MiB free; benchmark will not add disk pressure",
        }

    target = bench_dir / "io-benchmark.tmp"
    block = bytes(range(256)) * 4096  # exactly 1 MiB, deterministic
    digest = hashlib.sha256()
    write_started = time.perf_counter()
    try:
        with target.open("wb", buffering=0) as fh:
            for _ in range(_DISK_BYTES // len(block)):
                fh.write(block)
            fh.flush()
            os.fsync(fh.fileno())
        write_seconds = time.perf_counter() - write_started

        read_started = time.perf_counter()
        with target.open("rb", buffering=0) as fh:
            while True:
                chunk = fh.read(MIB)
                if not chunk:
                    break
                digest.update(chunk)
        read_seconds = time.perf_counter() - read_started
    finally:
        try:
            target.unlink()
        except FileNotFoundError:
            pass

    return {
        "bytes": _DISK_BYTES,
        "write_seconds": write_seconds,
        "write_mib_per_second": (_DISK_BYTES / MIB) / max(write_seconds, 1e-9),
        "read_seconds": read_seconds,
        "read_mib_per_second": (_DISK_BYTES / MIB) / max(read_seconds, 1e-9),
        "sha256": digest.hexdigest(),
        "write_higher_is_better": True,
        "read_higher_is_better": True,
    }


def _inference_benchmark() -> Dict[str, Any]:
    try:
        from .llm import generate
        started = time.perf_counter()
        answer = generate([
            {
                "role": "user",
                "content": "Benchmark request. Reply with exactly: MAC BRAIN BENCHMARK READY",
            }
        ])
        elapsed = time.perf_counter() - started
        return {
            "seconds": elapsed,
            "exact_reply": answer.strip() == "MAC BRAIN BENCHMARK READY",
            "reply_chars": len(answer),
            "lower_is_better": True,
        }
    except Exception as exc:
        return {
            "skipped": True,
            "reason": f"{type(exc).__name__}: {exc}"[:400],
        }


def _pct_change(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100.0


def _metric_comparison(
    name: str,
    current: Optional[float],
    previous: Optional[float],
    *,
    higher_is_better: bool,
    tolerance_percent: float,
) -> Optional[Dict[str, Any]]:
    if current is None or previous is None:
        return None
    change = _pct_change(float(current), float(previous))
    if change is None:
        state = "inconclusive"
    elif abs(change) <= tolerance_percent:
        state = "stable"
    else:
        improved = change > 0 if higher_is_better else change < 0
        state = "improved" if improved else "regressed"
    return {
        "metric": name,
        "current": current,
        "previous": previous,
        "percent_change": change,
        "higher_is_better": higher_is_better,
        "tolerance_percent": tolerance_percent,
        "state": state,
    }


def compare_runs(current: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not previous:
        return {
            "verdict": "baseline",
            "metrics": [],
            "note": "First comparable run; future runs will compare against this baseline.",
        }

    current_metrics = current.get("metrics", {})
    previous_metrics = previous.get("metrics", {})
    candidates = [
        _metric_comparison(
            "cpu_seconds_median",
            current_metrics.get("cpu_seconds_median"),
            previous_metrics.get("cpu_seconds_median"),
            higher_is_better=False,
            tolerance_percent=7.0,
        ),
        _metric_comparison(
            "disk_write_mib_per_second",
            current_metrics.get("disk_write_mib_per_second"),
            previous_metrics.get("disk_write_mib_per_second"),
            higher_is_better=True,
            tolerance_percent=12.0,
        ),
        _metric_comparison(
            "disk_read_mib_per_second",
            current_metrics.get("disk_read_mib_per_second"),
            previous_metrics.get("disk_read_mib_per_second"),
            higher_is_better=True,
            tolerance_percent=15.0,
        ),
        _metric_comparison(
            "inference_seconds",
            current_metrics.get("inference_seconds"),
            previous_metrics.get("inference_seconds"),
            higher_is_better=False,
            tolerance_percent=10.0,
        ),
        _metric_comparison(
            "disk_free_bytes",
            current_metrics.get("disk_free_bytes"),
            previous_metrics.get("disk_free_bytes"),
            higher_is_better=True,
            tolerance_percent=0.5,
        ),
        _metric_comparison(
            "swap_used_bytes",
            current_metrics.get("swap_used_bytes"),
            previous_metrics.get("swap_used_bytes"),
            higher_is_better=False,
            tolerance_percent=10.0,
        ),
    ]
    metrics = [row for row in candidates if row is not None]
    states = [row["state"] for row in metrics if row["state"] != "inconclusive"]
    improved = states.count("improved")
    regressed = states.count("regressed")
    changed = improved + regressed

    if changed == 0:
        verdict = "stable"
    elif improved and not regressed:
        verdict = "improved"
    elif regressed and not improved:
        verdict = "regressed"
    else:
        verdict = "mixed"

    return {
        "verdict": verdict,
        "metrics": metrics,
        "improved_metrics": improved,
        "regressed_metrics": regressed,
        "note": (
            "Stable/noisy measurements are not forced into success or failure. "
            "A diagnostic change can still be useful before speed improves."
        ),
    }


def run_benchmarks(*, include_inference: bool = True) -> Dict[str, Any]:
    snapshot = collect_snapshot()
    cpu = _cpu_benchmark()
    disk = _disk_benchmark()
    inference = _inference_benchmark() if include_inference else {"skipped": True, "reason": "disabled"}

    load = snapshot.get("load", {})
    cpus = max(int(load.get("cpus", 1) or 1), 1)
    metrics: Dict[str, Any] = {
        "cpu_seconds_median": cpu.get("seconds_median"),
        "disk_write_mib_per_second": disk.get("write_mib_per_second"),
        "disk_read_mib_per_second": disk.get("read_mib_per_second"),
        "inference_seconds": inference.get("seconds"),
        "disk_free_bytes": int(snapshot.get("disk", {}).get("free", 0) or 0),
        "disk_total_bytes": int(snapshot.get("disk", {}).get("total", 0) or 0),
        "swap_used_bytes": int(snapshot.get("swap", {}).get("used", 0) or 0),
        "load_per_cpu": float(load.get("1m", 0.0) or 0.0) / cpus,
    }
    run = {
        "benchmark_version": 1,
        "generated_ts": time.time(),
        "repo_commit": _repo_commit(),
        "metrics": metrics,
        "cpu": cpu,
        "disk": disk,
        "inference": inference,
        "environment": {
            "load": load,
            "battery": snapshot.get("battery", {}),
            "thermal": snapshot.get("thermal", ""),
            "memory_total": snapshot.get("memory_total", 0),
        },
    }

    previous_rows = db.recent_benchmark_runs(1)
    previous_payload = previous_rows[0]["payload"] if previous_rows else None
    run["comparison"] = compare_runs(run, previous_payload)
    run_id = db.add_benchmark_run(run["repo_commit"], run)
    run["run_id"] = run_id
    return run
