"""cache.py のテスト: TTL と Cost Explorer bucket キャッシュ."""

import sqlite3
from datetime import datetime, timedelta, timezone

from src import cache


def test_cost_cache_default_ttl_is_one_week(monkeypatch, tmp_path):
    """既存 cost_cache のデフォルト TTL は 1 week。"""
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "cache.db")
    cache.set_cached("cost:test", {"value": 1})

    conn = sqlite3.connect(str(cache.DB_PATH))
    conn.execute(
        "UPDATE cost_cache SET fetched_at = ? WHERE cache_key = ?",
        ((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(), "cost:test"),
    )
    conn.commit()
    conn.close()

    assert cache.get_cached("cost:test") == {"value": 1}


def test_cost_cache_expires_after_one_week(monkeypatch, tmp_path):
    """1 week を超えた cost_cache は期限切れとして扱う。"""
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "cache.db")
    cache.set_cached("cost:test", {"value": 1})

    conn = sqlite3.connect(str(cache.DB_PATH))
    conn.execute(
        "UPDATE cost_cache SET fetched_at = ? WHERE cache_key = ?",
        ((datetime.now(timezone.utc) - timedelta(days=8)).isoformat(), "cost:test"),
    )
    conn.commit()
    conn.close()

    assert cache.get_cached("cost:test") is None


def test_cost_period_cache_roundtrip(monkeypatch, tmp_path):
    """Cost Explorer の ResultsByTime 1 bucket を保存・取得できる。"""
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "cache.db")
    period = {
        "TimePeriod": {"Start": "2026-06-01", "End": "2026-06-02"},
        "Groups": [{"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "1.23"}}}],
    }

    cache.set_cost_period_cached(
        "123456789012",
        "DAILY",
        "SERVICE",
        period,
        role_name="ReadOnlyAccess",
    )

    result = cache.get_cost_period_cached(
        "123456789012",
        "DAILY",
        "SERVICE",
        "2026-06-01",
        "2026-06-02",
    )
    assert result is not None
    assert result["data"] == period
    assert result["roleName"] == "ReadOnlyAccess"


def test_cost_period_cache_expired(monkeypatch, tmp_path):
    """古い Cost Explorer bucket は期限切れとして扱う。"""
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "cache.db")
    period = {"TimePeriod": {"Start": "2026-06-01", "End": "2026-06-02"}, "Groups": []}
    cache.set_cost_period_cached("123456789012", "DAILY", "SERVICE", period)

    conn = sqlite3.connect(str(cache.DB_PATH))
    conn.execute(
        "UPDATE cost_period_cache SET fetched_at = ?",
        ((datetime.now(timezone.utc) - timedelta(days=8)).isoformat(),),
    )
    conn.commit()
    conn.close()

    result = cache.get_cost_period_cached(
        "123456789012",
        "DAILY",
        "SERVICE",
        "2026-06-01",
        "2026-06-02",
    )
    assert result is None


def test_default_account_ids_roundtrip(monkeypatch, tmp_path):
    """Config タブの default account IDs を SQLite に保存・削除できる。"""
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "cache.db")

    assert cache.get_default_account_ids() is None

    cache.set_default_account_ids(["111111111111", "222222222222"])
    assert cache.get_default_account_ids() == ["111111111111", "222222222222"]

    assert cache.clear_default_account_ids() is True
    assert cache.get_default_account_ids() is None
