from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List


def _run(args: List[str], timeout: int = 8) -> str:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def load_average() -> Dict[str, float]:
    one, five, fifteen = os.getloadavg()
    return {"1m": one, "5m": five, "15m": fifteen, "cpus": os.cpu_count() or 1}


def memory_total() -> int:
    raw = _run(["/usr/sbin/sysctl", "-n", "hw.memsize"]).strip()
    try:
        return int(raw)
    except ValueError:
        return 0


def disk_usage(path: str = "/") -> Dict[str, int]:
    u = shutil.disk_usage(path)
    return {"total": u.total, "used": u.used, "free": u.free}


def swap_usage() -> Dict[str, int]:
    raw = _run(["/usr/sbin/sysctl", "-n", "vm.swapusage"])
    out = {"total": 0, "used": 0, "free": 0}
    for key in out:
        m = re.search(rf"{key}\s*=\s*([0-9.]+)([MGT])", raw)
        if m:
            factor = {"M": 1024**2, "G": 1024**3, "T": 1024**4}[m.group(2)]
            out[key] = int(float(m.group(1)) * factor)
    return out


def vm_stats() -> Dict[str, int]:
    raw = _run(["/usr/bin/vm_stat"])
    page_size = 4096
    m = re.search(r"page size of (\d+) bytes", raw)
    if m:
        page_size = int(m.group(1))
    values: Dict[str, int] = {"page_size": page_size}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        val = val.strip().rstrip(".")
        if val.isdigit():
            values[key.lower().replace(" ", "_")] = int(val) * page_size
    return values


def processes(limit: int = 20) -> List[Dict[str, Any]]:
    raw = _run([
        "/bin/ps", "-axo", "pid=,ppid=,%cpu=,%mem=,rss=,etime=,comm=", "-r"
    ], timeout=10)
    rows = []
    for line in raw.splitlines()[: max(limit * 3, 60)]:
        parts = line.strip().split(None, 6)
        if len(parts) != 7:
            continue
        try:
            rows.append({
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "cpu": float(parts[2]),
                "mem_pct": float(parts[3]),
                "rss_kb": int(parts[4]),
                "etime": parts[5],
                "command": parts[6],
            })
        except ValueError:
            continue
        if len(rows) >= limit:
            break
    return rows


def parse_pmset_battery(raw: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"source": "unknown", "percent": None, "status": "unknown", "raw": raw.strip()[:1000]}
    source = re.search(r"Now drawing from '([^']+)'", raw)
    if source:
        result["source"] = source.group(1)
    pct = re.search(r"(\d{1,3})%;", raw)
    if pct:
        result["percent"] = min(100, int(pct.group(1)))
    lower = raw.lower()
    for status in ("discharging", "charging", "charged"):
        if status in lower:
            result["status"] = status
            break
    return result


def battery_status() -> Dict[str, Any]:
    return parse_pmset_battery(_run(["/usr/bin/pmset", "-g", "batt"], timeout=8))


def on_ac_power(snapshot_or_battery: Dict[str, Any]) -> bool:
    battery = snapshot_or_battery.get("battery", snapshot_or_battery)
    return str(battery.get("source", "")).lower() == "ac power"


def battery_health() -> Dict[str, Any]:
    """Return only non-identifying health fields; do not persist battery serial numbers."""
    raw = _run(["/usr/sbin/system_profiler", "SPPowerDataType", "-detailLevel", "mini"], timeout=45)
    keys = {
        "Cycle Count": "cycle_count",
        "Condition": "condition",
        "Maximum Capacity": "maximum_capacity",
        "Full Charge Capacity (mAh)": "full_charge_capacity_mah",
        "Design Capacity (mAh)": "design_capacity_mah",
    }
    out: Dict[str, Any] = {}
    for line in raw.splitlines():
        text = line.strip()
        for label, key in keys.items():
            if text.startswith(label + ":"):
                value = text.split(":", 1)[1].strip()
                if key in {"cycle_count", "full_charge_capacity_mah", "design_capacity_mah"}:
                    digits = re.search(r"\d+", value.replace(",", ""))
                    out[key] = int(digits.group(0)) if digits else value
                else:
                    out[key] = value
    return out


def thermal_status() -> str:
    return _run(["/usr/bin/pmset", "-g", "therm"], timeout=8).strip()[:2000]


def spotlight_status() -> str:
    return _run(["/usr/bin/mdutil", "-s", "/"], timeout=10).strip()


def time_machine_status() -> str:
    return _run(["/usr/bin/tmutil", "status"], timeout=10).strip()


def collect_snapshot() -> Dict[str, Any]:
    return {
        "load": load_average(),
        "memory_total": memory_total(),
        "disk": disk_usage("/"),
        "swap": swap_usage(),
        "vm": vm_stats(),
        "processes": processes(20),
        "spotlight": spotlight_status(),
        "battery": battery_status(),
        "thermal": thermal_status(),
    }


def child_directory_sizes(path: Path, max_children: int = 120) -> List[Dict[str, Any]]:
    """Measure one directory level with a single du traversal.

    This matters on the old Mac: launching one recursive du per child repeatedly walks the
    same filesystem trees and can itself create disk pressure. macOS Big Sur's BSD du
    supports -d 1, so one process can return immediate directory totals.
    """
    if not path.exists() or not path.is_dir():
        return []
    raw = _run(["/usr/bin/du", "-k", "-d", "1", str(path)], timeout=180)
    root = str(path.resolve())
    rows: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            kb = int(parts[0])
        except ValueError:
            continue
        child = parts[1]
        try:
            resolved = str(Path(child).resolve())
        except OSError:
            resolved = child
        if resolved == root:
            continue
        rows.append({"path": child, "bytes": kb * 1024})
    rows.sort(key=lambda x: x["bytes"], reverse=True)
    return rows[:max_children]


def directory_sizes(paths: List[Path]) -> List[Dict[str, Any]]:
    results = []
    for path in paths:
        if not path.exists():
            continue
        raw = _run(["/usr/bin/du", "-sk", str(path)], timeout=90)
        first = raw.splitlines()[0] if raw else ""
        try:
            kb = int(first.split()[0])
        except (ValueError, IndexError):
            continue
        results.append({"path": str(path), "bytes": kb * 1024})
    return sorted(results, key=lambda x: x["bytes"], reverse=True)
