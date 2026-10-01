from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .config import GIT_REPOS_DIR

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MIB = 1024 * 1024
_GIB = 1024 * _MIB

# Mac Brain is an old, slow, space-constrained machine. These limits are
# intentionally conservative and deterministic; the local LLM is never
# consulted for Git storage decisions.
MIN_FREE_RESERVE_BYTES = 1 * _GIB
FREE_RESERVE_DIVISOR = 10
MAX_RECEIVE_BYTES = 256 * _MIB


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


def storage_capacity() -> Dict[str, object]:
    """Return a cheap filesystem-level capacity check; never scan repository contents."""
    GIT_REPOS_DIR.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(str(GIT_REPOS_DIR))
    reserve = max(MIN_FREE_RESERVE_BYTES, usage.total // FREE_RESERVE_DIVISOR)
    return {
        "total": int(usage.total),
        "used": int(usage.used),
        "free": int(usage.free),
        "reserve": int(reserve),
        "write_ok": bool(usage.free > reserve),
        "max_receive_bytes": MAX_RECEIVE_BYTES,
    }


def _require_write_capacity() -> None:
    capacity = storage_capacity()
    if not capacity["write_ok"]:
        raise RuntimeError(
            "Git storage is below its free-space reserve; refusing to add data. "
            "Free space on the physical Mac before trying again."
        )


def _repo_git_path(path: Path, args: List[str]) -> subprocess.CompletedProcess:
    return _run_git(["--git-dir", str(path)] + args)


def _install_storage_guard(path: Path) -> None:
    """Keep pushes bounded with a Python-only deterministic receive guard."""
    _require_ok(
        _repo_git_path(path, ["config", "receive.maxInputSize", str(MAX_RECEIVE_BYTES)]),
        "set receive size cap",
    )
    _require_ok(
        _repo_git_path(path, ["config", "receive.autogc", "false"]),
        "disable receive autogc",
    )
    _require_ok(
        _repo_git_path(path, ["config", "gc.auto", "0"]),
        "disable automatic gc",
    )

    python = str(Path(sys.executable).resolve())
    hook = path / "hooks" / "pre-receive"
    hook.write_text(
        f"#!{python}\n"
        "from __future__ import annotations\n"
        "import shutil\n"
        "import sys\n"
        "from pathlib import Path\n"
        "GIB = 1024 * 1024 * 1024\n"
        "repo = Path(__file__).resolve().parent.parent\n"
        "try:\n"
        "    usage = shutil.disk_usage(repo)\n"
        "except OSError:\n"
        "    print('Mac Brain: cannot verify free disk space; rejecting push.', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        "reserve = max(GIB, usage.total // 10)\n"
        "if usage.free <= reserve:\n"
        "    print('Mac Brain: low disk space; push rejected to preserve the storage reserve.', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    os.chmod(str(hook), 0o755)


def create_repo(name: str) -> Path:
    """Create one passive bare repository; no model, network fetch, or background sync."""
    _require_write_capacity()
    path = repo_path(name)
    if path.exists():
        raise FileExistsError(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    _require_ok(_run_git(["init", "--bare", str(path)]), f"create {name}")
    try:
        _install_storage_guard(path)
    except Exception:
        shutil.rmtree(str(path), ignore_errors=True)
        raise
    return path


def _repo_git(name: str, args: List[str]) -> subprocess.CompletedProcess:
    return _repo_git_path(repo_path(name), args)


def _count_refs(name: str, prefix: str) -> int:
    result = _repo_git(name, ["for-each-ref", "--format=%(refname)", prefix])
    if result.returncode != 0:
        return 0
    return sum(1 for line in result.stdout.splitlines() if line)


def _object_kib(name: str) -> Optional[int]:
    """Use Git's own cheap object accounting instead of recursively walking files."""
    result = _repo_git(name, ["count-objects", "-v"])
    if result.returncode != 0:
        return None
    values: Dict[str, int] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition(": ")
        if sep and value.isdigit():
            values[key] = int(value)
    if "size" not in values and "size-pack" not in values:
        return None
    return values.get("size", 0) + values.get("size-pack", 0)


def repo_summary(name: str) -> Dict[str, object]:
    """Explicit, bounded inspection of one repo; `list` never calls this."""
    path = repo_path(name)
    if not path.is_dir():
        raise FileNotFoundError(str(path))

    head = _repo_git(name, ["rev-parse", "--verify", "HEAD"])
    latest: Optional[Dict[str, str]] = None
    if head.returncode == 0 and head.stdout.strip():
        last = _repo_git(
            name,
            ["show", "-s", "--date=iso-strict", "--format=%H%x09%ad%x09%an%x09%s", "HEAD"],
        )
        if last.returncode == 0 and last.stdout.strip():
            parts = last.stdout.strip().split("\t", 3)
            if len(parts) == 4:
                latest = {"sha": parts[0], "date": parts[1], "author": parts[2], "subject": parts[3]}

    return {
        "name": name,
        "path": str(path),
        "branches": _count_refs(name, "refs/heads"),
        "tags": _count_refs(name, "refs/tags"),
        "object_kib": _object_kib(name),
        "latest": latest,
        "automatic_gc": False,
        "max_receive_bytes": MAX_RECEIVE_BYTES,
    }


def list_repos() -> List[str]:
    """List names only. Do not walk histories or calculate per-repository sizes."""
    GIT_REPOS_DIR.mkdir(parents=True, exist_ok=True)
    return [path.name[:-4] for path in sorted(GIT_REPOS_DIR.glob("*.git")) if path.is_dir()]
