from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from .config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations(ts);
CREATE INDEX IF NOT EXISTS idx_obs_kind ON observations(kind);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ts REAL NOT NULL,
    updated_ts REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT,
    evidence TEXT NOT NULL,
    expected_benefit TEXT NOT NULL,
    risk TEXT NOT NULL,
    action TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_ts ON reports(ts);

CREATE TABLE IF NOT EXISTS filesystem_crawl_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS filesystem_crawl_frontier (
    path TEXT PRIMARY KEY,
    depth INTEGER NOT NULL,
    entry_offset INTEGER NOT NULL DEFAULT 0,
    enqueued_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fs_frontier_depth ON filesystem_crawl_frontier(depth, enqueued_ts);

CREATE TABLE IF NOT EXISTS filesystem_inventory (
    path TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    bytes INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    seen_ts REAL NOT NULL,
    necessity_state TEXT NOT NULL DEFAULT 'unknown',
    necessity_evidence TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_fs_inventory_kind_bytes ON filesystem_inventory(kind, bytes DESC);

CREATE TABLE IF NOT EXISTS process_inventory (
    command TEXT PRIMARY KEY,
    first_seen_ts REAL NOT NULL,
    last_seen_ts REAL NOT NULL,
    samples INTEGER NOT NULL DEFAULT 0,
    cpu_sum REAL NOT NULL DEFAULT 0,
    cpu_max REAL NOT NULL DEFAULT 0,
    rss_kb_sum INTEGER NOT NULL DEFAULT 0,
    rss_kb_max INTEGER NOT NULL DEFAULT 0,
    last_pid INTEGER NOT NULL DEFAULT 0,
    necessity_state TEXT NOT NULL DEFAULT 'unknown',
    necessity_evidence TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_process_inventory_cpu_max ON process_inventory(cpu_max DESC);
CREATE INDEX IF NOT EXISTS idx_process_inventory_rss_max ON process_inventory(rss_kb_max DESC);
"""


@contextmanager
def connection():
    ensure_dirs()
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_sample(payload: Dict[str, Any], ts: Optional[float] = None) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO samples(ts,payload) VALUES (?,?)",
            (ts or time.time(), json.dumps(payload, sort_keys=True)),
        )


def recent_samples(limit: int = 20) -> List[Dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT ts,payload FROM samples ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"ts": r["ts"], **json.loads(r["payload"])} for r in rows]


def add_observation(kind: str, subject: str, payload: Dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO observations(ts,kind,subject,payload) VALUES (?,?,?,?)",
            (time.time(), kind, subject, json.dumps(payload, sort_keys=True)),
        )


def recent_observations(limit: int = 100) -> List[Dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT ts,kind,subject,payload FROM observations ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "ts": r["ts"],
            "kind": r["kind"],
            "subject": r["subject"],
            "payload": json.loads(r["payload"]),
        }
        for r in rows
    ]


def create_proposal(
    title: str,
    kind: str,
    target: Optional[str],
    evidence: str,
    expected_benefit: str,
    risk: str,
    action: str,
) -> int:
    now = time.time()
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM proposals WHERE status='open' AND kind=? AND COALESCE(target,'')=COALESCE(?, '') ORDER BY id DESC LIMIT 1",
            (kind, target),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE proposals SET updated_ts=?, title=?, evidence=?, expected_benefit=?, risk=?, action=? WHERE id=?",
                (now, title, evidence, expected_benefit, risk, action, row["id"]),
            )
            return int(row["id"])
        cur = conn.execute(
            """INSERT INTO proposals(created_ts,updated_ts,status,title,kind,target,evidence,expected_benefit,risk,action)
               VALUES (?,?, 'open', ?,?,?,?,?,?,?)""",
            (now, now, title, kind, target, evidence, expected_benefit, risk, action),
        )
        return int(cur.lastrowid)


def list_proposals(status: Optional[str] = "open") -> List[Dict[str, Any]]:
    q = "SELECT * FROM proposals"
    args: Iterable[Any] = ()
    if status:
        q += " WHERE status=?"
        args = (status,)
    q += " ORDER BY updated_ts DESC"
    with connection() as conn:
        return [dict(r) for r in conn.execute(q, args).fetchall()]


def get_proposal(proposal_id: int) -> Optional[Dict[str, Any]]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    return dict(row) if row else None


def set_proposal_status(proposal_id: int, status: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE proposals SET status=?, updated_ts=? WHERE id=?",
            (status, time.time(), proposal_id),
        )


def add_report(kind: str, text: str) -> int:
    clean = " ".join(str(text).split()) if kind == "heartbeat" else str(text).strip()
    with connection() as conn:
        cur = conn.execute(
            "INSERT INTO reports(ts,kind,text) VALUES (?,?,?)",
            (time.time(), kind, clean),
        )
        return int(cur.lastrowid)


def latest_report_id() -> int:
    with connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS id FROM reports").fetchone()
    return int(row["id"]) if row else 0


def reports_since(after_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id,ts,kind,text FROM reports WHERE id>? ORDER BY id ASC LIMIT ?",
            (after_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def prune(sample_days: float = 14, report_days: float = 30) -> None:
    """Drop old per-minute samples and console reports so the DB stays bounded.

    One ~4 KB sample per minute is ~2 GB/year, which would itself become a storage
    problem on the Mac this project is trying to speed up. Observations and proposals
    are kept: they are the durable findings.
    """
    now = time.time()
    with connection() as conn:
        conn.execute("DELETE FROM samples WHERE ts < ?", (now - sample_days * 86400,))
        conn.execute("DELETE FROM reports WHERE ts < ?", (now - report_days * 86400,))


def filesystem_crawl_initialized() -> bool:
    with connection() as conn:
        row = conn.execute(
            "SELECT value FROM filesystem_crawl_state WHERE key='initialized'"
        ).fetchone()
    return bool(row and row["value"] == "1")


def reset_filesystem_crawl(roots: Iterable[str]) -> None:
    now = time.time()
    unique = []
    seen = set()
    for raw in roots:
        path = str(raw)
        if path and path not in seen:
            seen.add(path)
            unique.append(path)
    with connection() as conn:
        conn.execute("DELETE FROM filesystem_crawl_frontier")
        conn.execute("DELETE FROM filesystem_inventory")
        conn.execute("DELETE FROM filesystem_crawl_state")
        conn.execute(
            "INSERT INTO filesystem_crawl_state(key,value) VALUES ('initialized','1')"
        )
        conn.execute(
            "INSERT INTO filesystem_crawl_state(key,value) VALUES ('started_ts',?)",
            (str(now),),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO filesystem_crawl_frontier(path,depth,entry_offset,enqueued_ts) VALUES (?,?,?,?)",
            [(path, 0, 0, now) for path in unique],
        )


def enqueue_filesystem_paths(rows: Iterable[tuple[str, int]]) -> int:
    now = time.time()
    with connection() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO filesystem_crawl_frontier(path,depth,entry_offset,enqueued_ts) VALUES (?,?,?,?)",
            [(str(path), int(depth), 0, now) for path, depth in rows],
        )
        return conn.total_changes - before


def pop_filesystem_frontier(limit: int) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    with connection() as conn:
        rows = conn.execute(
            "SELECT path,depth,entry_offset FROM filesystem_crawl_frontier "
            "ORDER BY depth ASC,enqueued_ts ASC,path ASC LIMIT ?",
            (limit,),
        ).fetchall()
        if rows:
            conn.executemany(
                "DELETE FROM filesystem_crawl_frontier WHERE path=?",
                [(row["path"],) for row in rows],
            )
    return [
        {
            "path": row["path"],
            "depth": int(row["depth"]),
            "entry_offset": int(row["entry_offset"]),
        }
        for row in rows
    ]


def upsert_filesystem_inventory(rows: Iterable[Dict[str, Any]]) -> None:
    now = time.time()
    payload = []
    for row in rows:
        payload.append((
            str(row["path"]),
            str(row["kind"]),
            int(row.get("bytes", 0) or 0),
            float(row.get("mtime", 0) or 0),
            now,
        ))
    if not payload:
        return
    with connection() as conn:
        conn.executemany(
            """
            INSERT INTO filesystem_inventory(path,kind,bytes,mtime,seen_ts)
            VALUES (?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                kind=excluded.kind,
                bytes=excluded.bytes,
                mtime=excluded.mtime,
                seen_ts=excluded.seen_ts
            """,
            payload,
        )


def filesystem_crawl_stats(limit: int = 20) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    with connection() as conn:
        frontier = conn.execute(
            "SELECT COUNT(*) AS n FROM filesystem_crawl_frontier"
        ).fetchone()["n"]
        inventory = conn.execute(
            "SELECT COUNT(*) AS n FROM filesystem_inventory"
        ).fetchone()["n"]
        directories = conn.execute(
            "SELECT COUNT(*) AS n FROM filesystem_inventory WHERE kind='directory'"
        ).fetchone()["n"]
        files = conn.execute(
            "SELECT COUNT(*) AS n FROM filesystem_inventory WHERE kind='file'"
        ).fetchone()["n"]
        file_bytes = conn.execute(
            "SELECT COALESCE(SUM(bytes),0) AS n FROM filesystem_inventory WHERE kind='file'"
        ).fetchone()["n"]
        necessity_rows = conn.execute(
            "SELECT necessity_state,COUNT(*) AS n FROM filesystem_inventory "
            "WHERE kind='file' GROUP BY necessity_state"
        ).fetchall()
        large_files = [
            dict(row)
            for row in conn.execute(
                "SELECT path,bytes,mtime,seen_ts,necessity_state,necessity_evidence "
                "FROM filesystem_inventory WHERE kind='file' ORDER BY bytes DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
    return {
        "frontier_directories": int(frontier),
        "inventory_items": int(inventory),
        "directories_seen": int(directories),
        "files_seen": int(files),
        "file_bytes_indexed": int(file_bytes),
        "necessity_counts": {row["necessity_state"]: int(row["n"]) for row in necessity_rows},
        "largest_files": large_files,
    }


def requeue_filesystem_path(path: str, depth: int, entry_offset: int) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO filesystem_crawl_frontier(path,depth,entry_offset,enqueued_ts)
            VALUES (?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                depth=excluded.depth,
                entry_offset=excluded.entry_offset,
                enqueued_ts=excluded.enqueued_ts
            """,
            (str(path), int(depth), int(entry_offset), time.time()),
        )


def get_filesystem_inventory(path: str) -> Optional[Dict[str, Any]]:
    with connection() as conn:
        row = conn.execute(
            "SELECT path,kind,bytes,mtime,seen_ts,necessity_state,necessity_evidence "
            "FROM filesystem_inventory WHERE path=?",
            (str(path),),
        ).fetchone()
    return dict(row) if row else None


def classify_filesystem_path(path: str, necessity_state: str, evidence: str) -> None:
    allowed = {"unknown", "necessary", "probably_necessary", "rebuildable", "redundant", "probably_unnecessary", "approved_cleanup"}
    state = str(necessity_state).strip().lower()
    if state not in allowed:
        raise ValueError(f"invalid necessity_state: {necessity_state}")
    with connection() as conn:
        cur = conn.execute(
            "UPDATE filesystem_inventory SET necessity_state=?, necessity_evidence=? WHERE path=?",
            (state, str(evidence).strip()[:2000], str(path)),
        )
        if cur.rowcount == 0:
            raise FileNotFoundError(str(path))


def record_process_snapshot(processes: Iterable[Dict[str, Any]], ts: Optional[float] = None) -> None:
    now = float(ts or time.time())
    rows = []
    for proc in processes:
        command = str(proc.get("command", "")).strip()
        if not command:
            continue
        rows.append((
            command,
            now,
            now,
            1,
            float(proc.get("cpu", 0.0) or 0.0),
            float(proc.get("cpu", 0.0) or 0.0),
            int(proc.get("rss_kb", 0) or 0),
            int(proc.get("rss_kb", 0) or 0),
            int(proc.get("pid", 0) or 0),
        ))
    if not rows:
        return
    with connection() as conn:
        conn.executemany(
            """
            INSERT INTO process_inventory(
                command,first_seen_ts,last_seen_ts,samples,cpu_sum,cpu_max,
                rss_kb_sum,rss_kb_max,last_pid
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(command) DO UPDATE SET
                last_seen_ts=excluded.last_seen_ts,
                samples=process_inventory.samples + 1,
                cpu_sum=process_inventory.cpu_sum + excluded.cpu_sum,
                cpu_max=MAX(process_inventory.cpu_max, excluded.cpu_max),
                rss_kb_sum=process_inventory.rss_kb_sum + excluded.rss_kb_sum,
                rss_kb_max=MAX(process_inventory.rss_kb_max, excluded.rss_kb_max),
                last_pid=excluded.last_pid
            """,
            rows,
        )


def process_inventory(limit: int = 40) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT
                command,first_seen_ts,last_seen_ts,samples,cpu_sum,cpu_max,
                rss_kb_sum,rss_kb_max,last_pid,necessity_state,necessity_evidence
            FROM process_inventory
            ORDER BY cpu_max DESC, rss_kb_max DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        samples = max(int(item["samples"]), 1)
        item["cpu_avg"] = float(item["cpu_sum"]) / samples
        item["rss_kb_avg"] = int(item["rss_kb_sum"]) / samples
        result.append(item)
    return result


def classify_process(command: str, necessity_state: str, evidence: str) -> None:
    allowed = {
        "unknown",
        "necessary",
        "probably_necessary",
        "optional",
        "probably_unnecessary",
        "approved_stop",
        "approved_disable",
    }
    state = str(necessity_state).strip().lower()
    if state not in allowed:
        raise ValueError(f"invalid necessity_state: {necessity_state}")
    with connection() as conn:
        cur = conn.execute(
            "UPDATE process_inventory SET necessity_state=?, necessity_evidence=? WHERE command=?",
            (state, str(evidence).strip()[:2000], str(command)),
        )
        if cur.rowcount == 0:
            raise FileNotFoundError(str(command))
