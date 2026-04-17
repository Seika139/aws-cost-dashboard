"""SQLite ベースのキャッシュ。Cost Explorer API の課金を抑えるために使用."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cache.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cost_cache (
            cache_key   TEXT PRIMARY KEY,
            data        TEXT NOT NULL,
            fetched_at  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resource_snapshots (
            account_id      TEXT NOT NULL,
            service         TEXT NOT NULL,
            snapshot_date   TEXT NOT NULL,
            data            TEXT NOT NULL,
            fetched_at      TEXT NOT NULL,
            UNIQUE(account_id, service, snapshot_date)
        )
    """)
    conn.commit()
    return conn


def get_cached(key: str, max_age_hours: int = 24) -> dict | None:
    """キャッシュを取得。max_age_hours 以内のデータがあれば返す."""
    conn = _get_conn()
    row = conn.execute("SELECT data, fetched_at FROM cost_cache WHERE cache_key = ?", (key,)).fetchone()
    conn.close()
    if row is None:
        return None
    fetched_at = datetime.fromisoformat(row[1])
    age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
    if age_hours > max_age_hours:
        return None
    return json.loads(row[0])


def set_cached(key: str, data: dict) -> None:
    """キャッシュに保存."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO cost_cache (cache_key, data, fetched_at) VALUES (?, ?, ?)",
        (key, json.dumps(data), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def clear_cache() -> int:
    """キャッシュを全削除。削除した件数を返す."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM cost_cache")
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


# ============================================================
# Resource Snapshots
# ============================================================


def get_resource_snapshot(account_id: str, service: str, snapshot_date: str) -> list | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT data FROM resource_snapshots WHERE account_id = ? AND service = ? AND snapshot_date = ?",
        (account_id, service, snapshot_date),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return json.loads(row[0])


def set_resource_snapshot(account_id: str, service: str, snapshot_date: str, data: list) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO resource_snapshots (account_id, service, snapshot_date, data, fetched_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (account_id, service, snapshot_date, json.dumps(data), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_resource_history(account_id: str, service: str, days: int = 30) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT snapshot_date, data, fetched_at FROM resource_snapshots "
        "WHERE account_id = ? AND service = ? ORDER BY snapshot_date DESC LIMIT ?",
        (account_id, service, days),
    ).fetchall()
    conn.close()
    return [{"date": r[0], "data": json.loads(r[1]), "fetchedAt": r[2]} for r in rows]
