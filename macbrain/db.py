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
