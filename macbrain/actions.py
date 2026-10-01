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


def _is_within(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def _validate_target(target: str) -> Path:
    """Return the filesystem entry to mutate, refusing protected locations.

    The returned path resolves parent directories but NOT the final component, so a
    symlink target means the link itself. Resolving it fully would make quarantine or
    --delete act on whatever the link points to (e.g. a real Documents folder).
    Both the entry and its fully resolved destination must pass the blocklist.
    """
    raw = Path(target).expanduser()
    if not raw.is_absolute():
        raise PermissionError(f"refusing relative cleanup target {target!r}")
    lexical = Path(os.path.normpath(str(raw)))
    if lexical == Path("/"):
        raise PermissionError("refusing broad destructive target")
    entry = lexical.parent.resolve() / lexical.name
    candidates = {str(entry), str(lexical.resolve())}
    protected = [str(p) for p in DYNAMIC_BLOCKED_PREFIXES] + [str(Path.home().resolve())]
    for s in candidates:
        for prefix in BLOCKED_PREFIXES:
            if _is_within(s, prefix):
                raise PermissionError(f"Mac Brain refuses to mutate protected target {s}")
        for prefix in DYNAMIC_BLOCKED_PREFIXES:
            if _is_within(s, str(prefix)):
                raise PermissionError(f"Mac Brain refuses to mutate its own state/control path {s}")
        # Removing an ancestor (e.g. /Users) would remove the home folder or Mac Brain itself.
        if s == "/" or any(_is_within(p, s) for p in protected):
            raise PermissionError(f"refusing broad destructive target {s}")
    return entry


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
    if not (p.exists() or p.is_symlink()):
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
    if p.is_symlink():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(str(p))
    elif p.exists():
        p.unlink()
    else:
        raise FileNotFoundError(str(p))
    db.set_proposal_status(proposal_id, "deleted")
