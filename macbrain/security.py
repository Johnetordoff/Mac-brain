from __future__ import annotations

import os
import plistlib
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


TRUSTED_SYSTEM_PREFIXES = (
    "/System/",
    "/usr/",
    "/bin/",
    "/sbin/",
)


def _run(args: List[str], timeout: int = 12) -> Tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        text = ((p.stdout or "") + ("\n" + p.stderr if p.stderr else "")).strip()
        return p.returncode, text
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "ERROR: %r" % (exc,)


def _is_system_path(path: str) -> bool:
    if path in {"/bin", "/sbin", "/usr", "/System"}:
        return True
    return any(path.startswith(prefix) for prefix in TRUSTED_SYSTEM_PREFIXES)


def _is_review_location(path: str) -> bool:
    home = str(Path.home())
    review_prefixes = (
        home + "/Downloads/",
        home + "/Desktop/",
        home + "/Public/",
        "/tmp/",
        "/private/tmp/",
        "/var/tmp/",
        "/private/var/tmp/",
    )
    return any(path.startswith(prefix) for prefix in review_prefixes)


def _signature_info(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return {"checked": False, "reason": "not_regular_file"}
    rc, out = _run(["/usr/bin/codesign", "-dv", "--verbose=3", path], timeout=10)
    info: Dict[str, Any] = {"checked": True, "signed": rc == 0}
    for key in ("Identifier", "TeamIdentifier", "Authority"):
        matches = re.findall(r"^%s=(.+)$" % re.escape(key), out, flags=re.MULTILINE)
        if matches:
            info[key.lower()] = matches if key == "Authority" else matches[-1]
    if rc != 0:
        info["detail"] = out[-600:]
    return info


def _process_inventory(max_processes: int = 500, signature_budget: int = 48) -> Dict[str, Any]:
    rc, raw = _run([
        "/bin/ps", "-axo", "pid=,ppid=,user=,%cpu=,%mem=,etime=,comm="
    ], timeout=15)
    rows: List[Dict[str, Any]] = []
    if rc != 0:
        return {"error": raw, "processes": rows, "review_items": []}

    unique_paths: List[str] = []
    seen = set()
    for line in raw.splitlines():
        parts = line.strip().split(None, 6)
        if len(parts) != 7:
            continue
        try:
            row = {
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "user": parts[2],
                "cpu": float(parts[3]),
                "mem_pct": float(parts[4]),
                "etime": parts[5],
                "command": parts[6],
            }
        except ValueError:
            continue
        rows.append(row)
        path = row["command"]
        if path.startswith("/") and path not in seen and not _is_system_path(path):
            seen.add(path)
            unique_paths.append(path)
        if len(rows) >= max_processes:
            break

    signatures: Dict[str, Dict[str, Any]] = {}
    for path in unique_paths[:signature_budget]:
        signatures[path] = _signature_info(path)

    review: List[Dict[str, Any]] = []
    for row in rows:
        path = str(row.get("command", ""))
        reasons: List[str] = []
        if path.startswith("/") and _is_review_location(path):
            reasons.append("running executable is in a user-writable temporary/download location")
        sig = signatures.get(path)
        if sig and sig.get("checked") and not sig.get("signed") and not _is_system_path(path):
            reasons.append("third-party executable did not validate as code-signed")
        if reasons:
            review.append({
                "kind": "process",
                "pid": row.get("pid"),
                "path": path,
                "reasons": reasons,
                "cpu": row.get("cpu"),
                "mem_pct": row.get("mem_pct"),
            })

    third_party = [r for r in rows if str(r.get("command", "")).startswith("/") and not _is_system_path(str(r.get("command", "")))]
    return {
        "process_count": len(rows),
        "third_party_process_count": len(third_party),
        "signature_paths_checked": len(signatures),
        "processes": rows,
        "signatures": signatures,
        "review_items": review,
    }


def _launch_target(pl: Dict[str, Any]) -> str:
    program = pl.get("Program")
    if isinstance(program, str) and program:
        return str(Path(program).expanduser())
    args = pl.get("ProgramArguments")
    if isinstance(args, list) and args and isinstance(args[0], str):
        return str(Path(args[0]).expanduser())
    return ""


def _persistence_inventory(signature_budget: int = 40) -> Dict[str, Any]:
    locations = [
        Path.home() / "Library" / "LaunchAgents",
        Path("/Library/LaunchAgents"),
        Path("/Library/LaunchDaemons"),
    ]
    items: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    signatures_checked = 0

    for location in locations:
        try:
            plists = sorted(location.glob("*.plist"))[:160]
        except OSError:
            continue
        for plist_path in plists:
            row: Dict[str, Any] = {"plist": str(plist_path)}
            try:
                st = plist_path.stat()
                row["plist_uid"] = st.st_uid
                row["plist_mode"] = oct(st.st_mode & 0o7777)
                with plist_path.open("rb") as fh:
                    pl = plistlib.load(fh)
                row["label"] = pl.get("Label")
                row["run_at_load"] = bool(pl.get("RunAtLoad"))
                row["keep_alive"] = bool(pl.get("KeepAlive"))
                target = _launch_target(pl)
                row["target"] = target
                reasons: List[str] = []
                if target:
                    target_path = Path(target)
                    if not target_path.exists():
                        reasons.append("launch item points to a missing target")
                    if _is_review_location(target):
                        reasons.append("launch item executes from a user-writable temporary/download location")
                    if target_path.exists() and target_path.is_file() and signatures_checked < signature_budget and not _is_system_path(target):
                        sig = _signature_info(target)
                        row["signature"] = sig
                        signatures_checked += 1
                        if sig.get("checked") and not sig.get("signed"):
                            reasons.append("persistent third-party target did not validate as code-signed")
                if str(location).startswith("/Library/"):
                    if st.st_uid != 0:
                        reasons.append("system-wide launch plist is not owned by root")
                    if st.st_mode & 0o022:
                        reasons.append("system-wide launch plist is group/world writable")
                if reasons:
                    review.append({"kind": "persistence", "plist": str(plist_path), "target": target, "reasons": reasons})
            except Exception as exc:
                row["parse_error"] = repr(exc)
                review.append({"kind": "persistence", "plist": str(plist_path), "target": "", "reasons": ["launch plist could not be parsed"]})
            items.append(row)

    return {"items": items, "review_items": review, "signature_paths_checked": signatures_checked}


def _listeners() -> Dict[str, Any]:
    rc, raw = _run(["/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], timeout=15)
    if rc not in (0, 1):
        return {"error": raw, "listeners": [], "review_items": []}
    rows: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    lines = raw.splitlines()
    for line in lines[1:121]:
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        row = {"command": parts[0], "pid": parts[1], "user": parts[2], "endpoint": parts[8]}
        rows.append(row)
        endpoint = parts[8]
        if "127.0.0.1:" not in endpoint and "[::1]:" not in endpoint and "localhost:" not in endpoint:
            review.append({"kind": "listener", "command": parts[0], "pid": parts[1], "endpoint": endpoint, "reasons": ["TCP listener is reachable beyond loopback unless the firewall blocks it"]})
    return {"listeners": rows, "review_items": review}


def _apple_security_components() -> Dict[str, Any]:
    paths = {
        "xprotect": Path("/Library/Apple/System/Library/CoreServices/XProtect.bundle/Contents/Info.plist"),
        "mrt": Path("/Library/Apple/System/Library/CoreServices/MRT.app/Contents/Info.plist"),
    }
    out: Dict[str, Any] = {}
    for name, info_path in paths.items():
        if not info_path.exists():
            out[name] = {"present": False}
            continue
        try:
            with info_path.open("rb") as fh:
                pl = plistlib.load(fh)
            out[name] = {
                "present": True,
                "version": pl.get("CFBundleShortVersionString") or pl.get("CFBundleVersion"),
            }
        except Exception as exc:
            out[name] = {"present": True, "read_error": repr(exc)}
    return out


def security_baseline() -> Dict[str, Any]:
    """Non-destructive first-pass security/process audit.

    This deliberately reports *review items*, not malware verdicts. Unsigned software,
    third-party launch agents, and network listeners can all be legitimate. The point is to
    make unexplained persistence/processes visible before performance cleanup begins.
    """
    proc = _process_inventory()
    persistence = _persistence_inventory()
    listeners = _listeners()
    review = []
    review.extend(proc.get("review_items", []))
    review.extend(persistence.get("review_items", []))
    review.extend(listeners.get("review_items", []))
    return {
        "process_count": proc.get("process_count", 0),
        "third_party_process_count": proc.get("third_party_process_count", 0),
        "process_signature_paths_checked": proc.get("signature_paths_checked", 0),
        "processes": proc.get("processes", []),
        "process_signatures": proc.get("signatures", {}),
        "launch_items": persistence.get("items", []),
        "listeners": listeners.get("listeners", []),
        "security_components": _apple_security_components(),
        "review_items": review[:120],
        "review_item_count": len(review),
        "interpretation": "Review items are suspicious/unverified signals only; this audit does not claim malware is present.",
    }
