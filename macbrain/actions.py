from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Dict

from . import db
from .config import APP_DIR, QUARANTINE_DIR, ensure_dirs

# Only explicit cleanup proposals may mutate the filesystem. Diagnostic, process,
# service, and large-directory investigation proposals are review-only.

BLOCKED_PREFIXES = [
    "/System",
    "/bin",
    "/sbin",
    "/usr",
    "/dev",
    "/private/dev",
    "/etc/ssh",
    "/private/etc/ssh",
    "/etc/pf.conf",
    "/private/etc/pf.conf",
    "/etc/pf.anchors",
    "/private/etc/pf.anchors",
    "/Library/Application Support/MacBrain",
    "/Library/LaunchDaemons/com.macbrain.networklock.plist",
]

ACTIONABLE_KINDS = {"ai_cleanup_candidate"}
ACTIONABLE_ACTIONS = {"quarantine_then_review"}

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_BLOCKED_PREFIXES = [
    APP_DIR.resolve(),
    PROJECT_ROOT.resolve(),
    (Path.home() / ".ssh").resolve(),
    (Path.home() / "Library/LaunchAgents/com.macbrain.performancehunter.plist").resolve(),
]


def _validate_target(target: str) -> Path:
    p = Path(target).expanduser().resolve()
    s = str(p)
    for prefix in BLOCKED_PREFIXES:
        if s == prefix or s.startswith(prefix + "/"):
            raise PermissionError(f"Mac Brain refuses to mutate protected target {s}")
    for prefix_path in DYNAMIC_BLOCKED_PREFIXES:
        prefix = str(prefix_path)
        if s == prefix or s.startswith(prefix + "/"):
            raise PermissionError(f"Mac Brain refuses to mutate its own state/control path {s}")
    if s in ("/", str(Path.home())):
        raise PermissionError("refusing broad destructive target")
    return p


def _actionable_proposal(proposal_id: int) -> Dict[str, object]:
    proposal = db.get_proposal(proposal_id)
    if not proposal:
        raise ValueError("proposal not found")
    if proposal.get("kind") not in ACTIONABLE_KINDS or proposal.get("action") not in ACTIONABLE_ACTIONS:
        raise PermissionError("proposal is diagnostic/review-only; Mac Brain may only mutate explicit cleanup proposals")
    return proposal


def quarantine(proposal_id: int) -> Path:
    ensure_dirs()
    proposal = _actionable_proposal(proposal_id)
    target = proposal.get("target")
    if not target:
        raise ValueError("proposal has no filesystem target")
    p = _validate_target(target)
    if not p.exists():
        raise FileNotFoundError(str(p))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = QUARANTINE_DIR / f"P{proposal_id:04d}-{stamp}-{p.name}"
    shutil.move(str(p), str(dest))
    db.set_proposal_status(proposal_id, "quarantined")
    return dest


def permanent_delete(proposal_id: int) -> None:
    proposal = _actionable_proposal(proposal_id)
    target = proposal.get("target")
    if not target:
        raise ValueError("proposal has no filesystem target")
    p = _validate_target(target)
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(str(p))
    elif p.exists() or p.is_symlink():
        p.unlink()
    else:
        raise FileNotFoundError(str(p))
    db.set_proposal_status(proposal_id, "deleted")
