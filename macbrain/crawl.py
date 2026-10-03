from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import db

# Broad local coverage without descending into device files, mounted external/network
# volumes, transient sockets, or Mac Brain's own state tree.
DEFAULT_ROOTS = (
    Path.home(),
    Path("/Applications"),
    Path("/Library"),
    Path("/System"),
    Path("/usr"),
    Path("/private/etc"),
    Path("/private/var"),
    Path("/Users/Shared"),
)

BLOCKED_PREFIXES = (
    "/dev",
    "/Volumes",
    "/private/var/run",
    "/private/var/vm",
)

SKIP_NAMES = {
    ".Spotlight-V100",
    ".DocumentRevisions-V100",
    ".fseventsd",
    ".TemporaryItems",
}


def _allowed(path: Path) -> bool:
    text = str(path)
    macbrain = str(Path.home() / ".macbrain")
    if text == macbrain or text.startswith(macbrain + "/"):
        return False
    return not any(text == prefix or text.startswith(prefix + "/") for prefix in BLOCKED_PREFIXES)


def _existing_roots(roots: Optional[Iterable[Path]] = None) -> List[Path]:
    selected = list(roots) if roots is not None else list(DEFAULT_ROOTS)
    out = []
    seen = set()
    for raw in selected:
        try:
            path = Path(raw).expanduser().resolve()
        except OSError:
            continue
        text = str(path)
        if text in seen or not path.exists() or not path.is_dir() or not _allowed(path):
            continue
        seen.add(text)
        out.append(path)
    return out


def ensure_initialized(roots: Optional[Iterable[Path]] = None) -> None:
    if db.filesystem_crawl_initialized():
        return
    db.reset_filesystem_crawl(str(path) for path in _existing_roots(roots))


def crawl_step(
    *,
    roots: Optional[Iterable[Path]] = None,
    max_directories: int = 20,
    max_entries_per_directory: int = 500,
    min_large_mb: int = 100,
) -> Dict[str, Any]:
    """Advance a persistent, bounded read-only filesystem inventory.

    The crawl remembers unvisited directories in SQLite. Each call scans only a small
    batch, records directory metadata plus large files, queues child directories, and
    returns. This lets the old Mac gradually learn the filesystem without a huge one-shot
    recursive walk.
    """
    ensure_initialized(roots)
    max_directories = min(max(int(max_directories), 1), 200)
    max_entries_per_directory = min(max(int(max_entries_per_directory), 50), 2000)
    min_large_mb = min(max(int(min_large_mb), 1), 10240)
    min_large_bytes = min_large_mb * 1024 * 1024

    try:
        os.nice(10)
    except OSError:
        pass

    batch = db.pop_filesystem_frontier(max_directories)
    if not batch:
        stats = db.filesystem_crawl_stats()
        return {
            "complete": True,
            "directories_scanned": 0,
            "entries_seen": 0,
            "new_directories_queued": 0,
            "permission_errors": 0,
            **stats,
        }

    inventory: List[Dict[str, Any]] = []
    queued: List[tuple[str, int]] = []
    scanned = 0
    entries_seen = 0
    permission_errors = 0
    truncated_directories = 0

    for item in batch:
        path = Path(item["path"])
        depth = int(item["depth"])
        entry_offset = int(item.get("entry_offset", 0))
        if not _allowed(path):
            continue
        scanned += 1
        try:
            st = path.stat()
            inventory.append({
                "path": str(path),
                "kind": "directory",
                "bytes": 0,
                "mtime": st.st_mtime,
            })
        except (OSError, PermissionError, FileNotFoundError):
            pass

        count = 0
        processed_this_pass = 0
        has_more = False
        try:
            with os.scandir(path) as it:
                for index, entry in enumerate(it):
                    if index < entry_offset:
                        continue
                    if processed_this_pass >= max_entries_per_directory:
                        has_more = True
                        truncated_directories += 1
                        break
                    processed_this_pass += 1
                    count += 1
                    entries_seen += 1
                    if entry.name in SKIP_NAMES:
                        continue
                    child = Path(entry.path)
                    if not _allowed(child):
                        continue
                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except (OSError, PermissionError, FileNotFoundError):
                        permission_errors += 1
                        continue
                    try:
                        if entry.is_symlink():
                            inventory.append({
                                "path": entry.path,
                                "kind": "symlink",
                                "bytes": int(stat.st_size),
                                "mtime": float(stat.st_mtime),
                            })
                        elif entry.is_dir(follow_symlinks=False):
                            queued.append((entry.path, depth + 1))
                            inventory.append({
                                "path": entry.path,
                                "kind": "directory",
                                "bytes": 0,
                                "mtime": float(stat.st_mtime),
                            })
                        elif entry.is_file(follow_symlinks=False) and stat.st_size >= min_large_bytes:
                            inventory.append({
                                "path": entry.path,
                                "kind": "file",
                                "bytes": int(stat.st_size),
                                "mtime": float(stat.st_mtime),
                            })
                    except (OSError, PermissionError, FileNotFoundError):
                        permission_errors += 1
        except (OSError, PermissionError, FileNotFoundError):
            permission_errors += 1
        if has_more:
            db.requeue_filesystem_path(path, depth, entry_offset + processed_this_pass)

    db.upsert_filesystem_inventory(inventory)
    added = db.enqueue_filesystem_paths(queued)
    stats = db.filesystem_crawl_stats()
    result = {
        "complete": stats["frontier_directories"] == 0,
        "directories_scanned": scanned,
        "entries_seen": entries_seen,
        "new_directories_queued": added,
        "permission_errors": permission_errors,
        "truncated_directories": truncated_directories,
        **stats,
    }
    db.add_observation("filesystem_crawl_step", "local_filesystem", result)
    return result
