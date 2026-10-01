from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .config import GIT_REPOS_DIR

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _git_binary() -> str:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git is not installed or not on PATH")
    return git


def validate_repo_name(name: str) -> str:
    if not _NAME_RE.fullmatch(name or ""):
        raise ValueError(
            "Repository name must start with a letter or digit and contain only "
            "letters, digits, '.', '_' or '-' (max 128 characters)."
        )
    if name in {".", ".."} or name.endswith(".git"):
        raise ValueError("Use the repository name without a .git suffix.")
    return name


def repo_path(name: str) -> Path:
    validate_repo_name(name)
    GIT_REPOS_DIR.mkdir(parents=True, exist_ok=True)
    return GIT_REPOS_DIR / (name + ".git")


def _run_git(args: List[str], *, timeout: int = 30) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({"LC_ALL": "C", "LANG": "C", "GIT_TERMINAL_PROMPT": "0"})
    return subprocess.run(
        [_git_binary()] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )


def _require_ok(result: subprocess.CompletedProcess, action: str) -> str:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown git error").strip()
        raise RuntimeError(f"{action} failed: {detail}")
    return result.stdout


def create_repo(name: str) -> Path:
    path = repo_path(name)
    if path.exists():
        raise FileExistsError(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    _require_ok(_run_git(["init", "--bare", str(path)]), f"create {name}")
    return path


def import_local_repo(name: str, source: str) -> Path:
    """Mirror a repository already present on this Mac; never fetch a network source."""
    validate_repo_name(name)
    if "://" in source or re.match(r"^[^/]+@[^:]+:", source):
        raise ValueError("Only a local filesystem path may be imported.")
    src = Path(source).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(str(src))
    target = repo_path(name)
    if target.exists():
        raise FileExistsError(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    _require_ok(
        _run_git(["clone", "--mirror", "--local", str(src), str(target)], timeout=60),
        f"import {name}",
    )
    return target


def _repo_git(name: str, args: List[str]) -> subprocess.CompletedProcess:
    return _run_git(["--git-dir", str(repo_path(name))] + args)


def _directory_bytes(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(str(path)):
        for filename in files:
            try:
                total += os.path.getsize(os.path.join(root, filename))
            except OSError:
                pass
    return total


def repo_summary(name: str) -> Dict[str, object]:
    path = repo_path(name)
    if not path.is_dir():
        raise FileNotFoundError(str(path))
    refs = _require_ok(
        _repo_git(name, ["for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags"]),
        f"read refs for {name}",
    ).splitlines()
    count = _repo_git(name, ["rev-list", "--all", "--count"])
    commits = int(count.stdout.strip() or "0") if count.returncode == 0 else 0
    last = _repo_git(
        name,
        ["log", "-1", "--date=iso-strict", "--format=%H%x09%ad%x09%an%x09%s", "--all"],
    )
    latest: Optional[Dict[str, str]] = None
    if last.returncode == 0 and last.stdout.strip():
        parts = last.stdout.strip().split("\t", 3)
        if len(parts) == 4:
            latest = {"sha": parts[0], "date": parts[1], "author": parts[2], "subject": parts[3]}
    return {
        "name": name,
        "path": str(path),
        "branches": len([x for x in refs if x.startswith("refs/heads/")]),
        "tags": len([x for x in refs if x.startswith("refs/tags/")]),
        "commits": commits,
        "bytes": _directory_bytes(path),
        "latest": latest,
    }


def list_repos() -> List[Dict[str, object]]:
    GIT_REPOS_DIR.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, object]] = []
    for path in sorted(GIT_REPOS_DIR.glob("*.git")):
        if path.is_dir():
            rows.append(repo_summary(path.name[:-4]))
    return rows
