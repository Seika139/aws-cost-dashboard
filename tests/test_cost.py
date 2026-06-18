"""cost.py のテスト: Cost Explorer bucket 分割と欠損範囲の結合."""

from datetime import date

from src import cache, cost
from src.cache import DEFAULT_COST_CACHE_TTL_HOURS, FINALIZED_COST_CACHE_TTL_HOURS
from src.cost import _cost_period_ttl_hours, _expected_periods, _group_contiguous_periods


def test_expected_periods_daily():
    """DAILY は 1 日 bucket に分割する。"""
    assert _expected_periods("2026-06-01", "2026-06-04", "DAILY") == [
        ("2026-06-01", "2026-06-02"),
        ("2026-06-02", "2026-06-03"),
        ("2026-06-03", "2026-06-04"),
    ]


def test_expected_periods_monthly():
    """MONTHLY は月 bucket に分割する。"""
    assert _expected_periods("2026-05-01", "2026-07-01", "MONTHLY") == [
        ("2026-05-01", "2026-06-01"),
        ("2026-06-01", "2026-07-01"),
    ]


def test_group_contiguous_periods():
    """連続する欠損 bucket は 1 回の Cost Explorer 取得範囲にまとめる。"""
    assert _group_contiguous_periods(
        [
            ("2026-06-01", "2026-06-02"),
            ("2026-06-02", "2026-06-03"),
            ("2026-06-05", "2026-06-06"),
        ]
    ) == [
        ("2026-06-01", "2026-06-03"),
        ("2026-06-05", "2026-06-06"),
    ]


def test_cost_period_ttl_hours(monkeypatch):
    """過去確定月は長期 TTL、当月 bucket は通常 TTL。"""

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 18)

    monkeypatch.setattr(cost, "date", FixedDate)

    assert _cost_period_ttl_hours("2026-06-01") == FINALIZED_COST_CACHE_TTL_HOURS
    assert _cost_period_ttl_hours("2026-07-01") == DEFAULT_COST_CACHE_TTL_HOURS


def test_get_account_cost_fetches_only_missing_periods(monkeypatch, tmp_path):
    """period cache にある bucket は再利用し、欠けた範囲だけ Cost Explorer から取得する。"""
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "cache.db")
    cached_period = {
        "TimePeriod": {"Start": "2026-06-02", "End": "2026-06-03"},
        "Groups": [{"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "2"}}}],
    }
    cache.set_cost_period_cached("123456789012", "DAILY", "SERVICE", cached_period, role_name="ReadOnlyAccess")

    calls = []

    def fake_paginate(_ce, kwargs):
        start = kwargs["TimePeriod"]["Start"]
        end = kwargs["TimePeriod"]["End"]
        calls.append((start, end))
        return [
            {
                "TimePeriod": {"Start": start, "End": end},
                "Groups": [{"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "1"}}}],
            }
        ]

    monkeypatch.setattr(cost, "_pick_cost_role", lambda _account_id: "ReadOnlyAccess")
    monkeypatch.setattr(cost, "_get_ce_client", lambda _account_id, _role_name: object())
    monkeypatch.setattr(cost, "_paginate_cost", fake_paginate)

    result = cost.get_account_cost("123456789012", "2026-06-01", "2026-06-04", "DAILY", "SERVICE")

    assert calls == [("2026-06-01", "2026-06-02"), ("2026-06-03", "2026-06-04")]
    assert [p["TimePeriod"]["Start"] for p in result["results"]] == [
        "2026-06-01",
        "2026-06-02",
        "2026-06-03",
    ]
