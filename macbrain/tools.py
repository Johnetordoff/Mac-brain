from __future__ import annotations

import hashlib
import os
import plistlib
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from . import db
from .hunter import deep_storage_scan, run_once
from .metrics import child_directory_sizes, directory_sizes, processes, spotlight_status, time_machine_status
from .security import security_baseline

# Deliberately no generic shell and no socket/network tool. The local model can only
# select deterministic inspection functions and can create non-destructive proposals.


def _safe_path(raw: str) -> Path:
    if not raw:
        raise ValueError("path required")
    p = Path(raw).expanduser().resolve()
    blocked = ("/dev", "/Volumes/Recovery", "/private/var/run")
    if any(str(p) == x or str(p).startswith(x + "/") for x in blocked):
        raise PermissionError("path is outside Mac Brain's inspection scope")
    return p


def _run(args: List[str], timeout: int = 15) -> str:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return ((p.stdout or "") + ("\n" + p.stderr if p.stderr else "")).strip()
    except Exception as exc:
        return f"ERROR: {exc!r}"


def tool_status(_: Dict[str, Any]) -> Dict[str, Any]:
    return run_once(deep=False)["snapshot"]


def tool_processes(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    limit = min(max(int(args.get("limit", 20)), 1), 60)
    return processes(limit)


def tool_storage(_: Dict[str, Any]) -> List[Dict[str, Any]]:
    return deep_storage_scan()[:40]


def tool_storage_path(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    p = _safe_path(str(args.get("path", "")))
    limit = min(max(int(args.get("limit", 30)), 1), 80)
    rows = child_directory_sizes(p, max_children=limit)
    return rows[:limit]


def tool_path_info(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _safe_path(str(args.get("path", "")))
    st = p.lstat()
    info: Dict[str, Any] = {
        "path": str(p),
        "exists": p.exists(),
        "directory": p.is_dir(),
        "symlink": p.is_symlink(),
        "size_bytes": st.st_size,
        "mtime": st.st_mtime,
        "mode": oct(st.st_mode & 0o7777),
        "owner_uid": st.st_uid,
        "group_gid": st.st_gid,
        "file_type": _run(["/usr/bin/file", "-b", str(p)], 8)[:1000],
    }
    if p.is_dir():
        measured = directory_sizes([p])
        if measured:
            info["recursive_size_bytes"] = measured[0]["bytes"]
    return info


def tool_list_dir(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    p = _safe_path(str(args.get("path", "")))
    limit = min(max(int(args.get("limit", 80)), 1), 200)
    result = []
    for child in list(p.iterdir())[:limit]:
        try:
            st = child.lstat()
            result.append({
                "name": child.name,
                "path": str(child),
                "dir": child.is_dir(),
                "symlink": child.is_symlink(),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
        except (OSError, PermissionError):
            result.append({"name": child.name, "path": str(child), "error": "unreadable"})
    return result


def tool_read_text(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _safe_path(str(args.get("path", "")))
    max_bytes = min(max(int(args.get("max_bytes", 16384)), 1), 65536)
    # Only regular files, and read at most max_bytes: read_bytes() on a multi-GB disk
    # image would pull it all into RAM on this 6 GB Mac, and a FIFO would block forever
    # and wedge the background AI cycle.
    if not p.is_file():
        raise ValueError(f"not a regular file: {p}")
    with p.open("rb") as fh:
        data = fh.read(max_bytes)
    return {"path": str(p), "text": data.decode("utf-8", errors="replace"), "bytes_read": len(data)}


def tool_launch_items(_: Dict[str, Any]) -> Dict[str, Any]:
    locations = [
        Path.home() / "Library" / "LaunchAgents",
        Path("/Library/LaunchAgents"),
        Path("/Library/LaunchDaemons"),
    ]
    out: Dict[str, Any] = {}
    for loc in locations:
        items = []
        try:
            for item in sorted(loc.glob("*.plist"))[:120]:
                row: Dict[str, Any] = {"path": str(item)}
                try:
                    with item.open("rb") as fh:
                        pl = plistlib.load(fh)
                    row.update({k: pl.get(k) for k in ("Label", "Program", "ProgramArguments", "RunAtLoad", "KeepAlive") if k in pl})
                except Exception as exc:
                    row["parse_error"] = repr(exc)
                items.append(row)
        except OSError as exc:
            out[str(loc)] = {"error": repr(exc)}
        else:
            out[str(loc)] = items
    return out


def tool_spotlight(_: Dict[str, Any]) -> Dict[str, Any]:
    return {"spotlight": spotlight_status()}


def tool_time_machine(_: Dict[str, Any]) -> Dict[str, Any]:
    return {"time_machine": time_machine_status()}




def tool_security_audit(_: Dict[str, Any]) -> Dict[str, Any]:
    result = security_baseline()
    db.add_observation("security_baseline", "startup", result)
    return result


def tool_cleanup_hints(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Measure known *candidate* areas without declaring them safe to delete.

    This gives the small local model macOS-specific priors while preserving the rule that
    evidence, not a path name alone, must justify a cleanup proposal.
    """
    home = Path.home()
    specs = [
        (home / "Library/Caches", "application caches", "Usually rebuildable, but inspect the specific app cache before removing it."),
        (home / "Library/Developer/Xcode/DerivedData", "Xcode derived build data", "Rebuildable build products; removing them makes future builds regenerate data."),
        (home / "Library/Developer/CoreSimulator/Caches", "CoreSimulator caches", "Usually rebuildable; simulator state elsewhere may still be important."),
        (home / "Library/Caches/Homebrew", "Homebrew download/build cache", "Usually reclaimable if no install/upgrade is currently running."),
        (home / ".npm/_cacache", "npm content cache", "Usually rebuildable from package registries, but Mac Brain is offline after arming."),
        (home / "Library/Caches/pip", "pip download/wheel cache", "Usually rebuildable from package indexes, but Mac Brain is offline after arming."),
        (home / ".Trash", "user Trash", "Potentially reclaimable only after confirming nothing needs restoration."),
    ]
    rows: List[Dict[str, Any]] = []
    for path, category, caution in specs:
        if not path.exists():
            continue
        measured = directory_sizes([path])
        if not measured:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append({
            "path": str(path),
            "category": category,
            "bytes": measured[0]["bytes"],
            "mtime": mtime,
            "age_days": max(0, int((time.time() - mtime) / 86400)) if mtime else None,
            "caution": caution,
            "automatic_delete": False,
        })

    downloads = home / "Downloads"
    suffixes = {".dmg", ".pkg", ".zip", ".tar", ".gz", ".bz2", ".xz"}
    if downloads.exists():
        try:
            files = []
            for child in downloads.iterdir():
                try:
                    if child.is_file() and child.suffix.lower() in suffixes:
                        st = child.stat()
                        files.append({
                            "path": str(child),
                            "category": "downloaded installer/archive",
                            "bytes": st.st_size,
                            "mtime": st.st_mtime,
                            "age_days": max(0, int((time.time() - st.st_mtime) / 86400)),
                            "caution": "Old installers/archives may be redundant, but filename/age alone does not prove that.",
                            "automatic_delete": False,
                        })
                except OSError:
                    continue
            files.sort(key=lambda x: x["bytes"], reverse=True)
            rows.extend(files[: min(max(int(args.get("download_files", 25)), 0), 50)])
        except OSError:
            pass
    rows.sort(key=lambda x: x["bytes"], reverse=True)
    return rows[: min(max(int(args.get("limit", 40)), 1), 80)]



def tool_largest_files(args: Dict[str, Any]) -> Dict[str, Any]:
    """Find large regular files with a bounded, low-priority walk.

    This is evidence gathering only. Large does not mean disposable. The bounded walk is
    important on this old Mac: Mac Brain must not make the machine unusable while looking.
    """
    raw_root = str(args.get("path", str(Path.home())))
    root = _safe_path(raw_root)
    limit = min(max(int(args.get("limit", 30)), 1), 100)
    min_mb = min(max(int(args.get("min_mb", 100)), 1), 10240)
    max_entries = min(max(int(args.get("max_entries", 30000)), 1000), 150000)
    min_bytes = min_mb * 1024 * 1024
    rows: List[Dict[str, Any]] = []
    scanned = 0
    truncated = False
    skip_names = {".Spotlight-V100", ".DocumentRevisions-V100", ".fseventsd", ".macbrain"}
    try:
        os.nice(10)
    except OSError:
        pass
    stack = [root]
    while stack and scanned < max_entries:
        base = stack.pop()
        try:
            with os.scandir(base) as it:
                for entry in it:
                    scanned += 1
                    if scanned >= max_entries:
                        truncated = True
                        break
                    if entry.name in skip_names:
                        continue
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except (OSError, PermissionError, FileNotFoundError):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False) and st.st_size >= min_bytes:
                        rows.append({
                            "path": entry.path,
                            "bytes": st.st_size,
                            "mtime": st.st_mtime,
                            "age_days": max(0, int((time.time() - st.st_mtime) / 86400)),
                            "automatic_delete": False,
                        })
        except (OSError, PermissionError, FileNotFoundError):
            continue
    rows.sort(key=lambda x: x["bytes"], reverse=True)
    return {"root": str(root), "scanned_entries": scanned, "truncated": truncated, "files": rows[:limit]}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tool_duplicate_large_files(args: Dict[str, Any]) -> Dict[str, Any]:
    """Find exact duplicates among large files, hashing only same-size candidates.

    It is intentionally bounded and only hashes files whose byte size already collides,
    which keeps the I/O cost reasonable. Exact hash equality is evidence of redundant
    content, but Mac Brain still does not decide which copy should be removed.
    """
    root = _safe_path(str(args.get("path", str(Path.home()))))
    min_mb = min(max(int(args.get("min_mb", 100)), 1), 10240)
    max_entries = min(max(int(args.get("max_entries", 30000)), 1000), 100000)
    max_hash_files = min(max(int(args.get("max_hash_files", 40)), 2), 120)
    min_bytes = min_mb * 1024 * 1024
    by_size: Dict[int, List[Path]] = {}
    scanned = 0
    stack = [root]
    skip_names = {".Spotlight-V100", ".DocumentRevisions-V100", ".fseventsd", ".macbrain"}
    try:
        os.nice(10)
    except OSError:
        pass
    while stack and scanned < max_entries:
        base = stack.pop()
        try:
            with os.scandir(base) as it:
                for entry in it:
                    scanned += 1
                    if scanned >= max_entries:
                        break
                    if entry.name in skip_names:
                        continue
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except (OSError, PermissionError, FileNotFoundError):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False) and st.st_size >= min_bytes:
                        by_size.setdefault(st.st_size, []).append(Path(entry.path))
        except (OSError, PermissionError, FileNotFoundError):
            continue
    candidates = [(size, paths) for size, paths in by_size.items() if len(paths) > 1]
    candidates.sort(key=lambda x: x[0], reverse=True)
    hashes: Dict[tuple, List[str]] = {}
    hashed = 0
    errors = 0
    for size, paths in candidates:
        for path in paths:
            if hashed >= max_hash_files:
                break
            try:
                digest = _sha256_file(path)
            except (OSError, PermissionError):
                errors += 1
                continue
            hashes.setdefault((size, digest), []).append(str(path))
            hashed += 1
        if hashed >= max_hash_files:
            break
    groups = []
    for (size, digest), paths in hashes.items():
        if len(paths) > 1:
            groups.append({
                "bytes_each": size,
                "sha256": digest,
                "paths": paths,
                "potential_reclaim_bytes": size * (len(paths) - 1),
                "automatic_delete": False,
            })
    groups.sort(key=lambda x: x["potential_reclaim_bytes"], reverse=True)
    return {"root": str(root), "scanned_entries": scanned, "hashed_files": hashed, "errors": errors, "duplicate_groups": groups}

def tool_recent_evidence(args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "samples": db.recent_samples(min(int(args.get("samples", 6)), 15)),
        "observations": db.recent_observations(min(int(args.get("observations", 15)), 50)),
        "proposals": db.list_proposals("open")[:25],
    }


def tool_propose_cleanup(args: Dict[str, Any]) -> Dict[str, Any]:
    target = _safe_path(str(args.get("target", "")))
    if not target.exists():
        raise FileNotFoundError(str(target))
    if str(target) in ("/", str(Path.home())):
        raise PermissionError("refusing broad cleanup target")
    evidence = str(args.get("evidence", "")).strip()
    benefit = str(args.get("expected_benefit", "")).strip()
    risk = str(args.get("risk", "")).strip() or "Unknown; inspect before approval."
    if len(evidence) < 12 or len(benefit) < 8:
        raise ValueError("cleanup proposal requires concrete evidence and expected benefit")
    pid = db.create_proposal(
        title=str(args.get("title", f"Cleanup candidate: {target.name}"))[:240],
        kind="ai_cleanup_candidate",
        target=str(target),
        evidence=evidence[:2000],
        expected_benefit=benefit[:1000],
        risk=risk[:1000],
        action="quarantine_then_review",
    )
    return {"proposal": f"P{pid:04d}", "target": str(target), "executed": False}


TOOLS = {
    "status": tool_status,
    "processes": tool_processes,
    "storage": tool_storage,
    "storage_path": tool_storage_path,
    "path_info": tool_path_info,
    "list_dir": tool_list_dir,
    "read_text": tool_read_text,
    "launch_items": tool_launch_items,
    "spotlight": tool_spotlight,
    "time_machine": tool_time_machine,
    "security_audit": tool_security_audit,
    "cleanup_hints": tool_cleanup_hints,
    "largest_files": tool_largest_files,
    "duplicate_large_files": tool_duplicate_large_files,
    "recent_evidence": tool_recent_evidence,
    "propose_cleanup": tool_propose_cleanup,
}


def run_tool(name: str, args: Dict[str, Any]) -> Any:
    if name not in TOOLS:
        raise ValueError(f"unknown tool {name!r}")
    return TOOLS[name](args)
