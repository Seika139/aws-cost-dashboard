"""prefetch.py のテスト: デフォルト期間と account 選択."""

from datetime import date

from src import prefetch
from src.prefetch import _build_jobs, _select_accounts, _select_default_accounts, default_date_range, parse_args


def test_default_date_range_includes_current_month():
    assert default_date_range(3, today=date(2026, 6, 18)) == ("2026-04-01", "2026-07-01")


def test_default_date_range_crosses_year_boundary():
    assert default_date_range(4, today=date(2026, 1, 10)) == ("2025-10-01", "2026-02-01")


def test_select_accounts_filters_by_exact_ids():
    accounts = [
        {"accountId": "111111111111", "accountName": "one"},
        {"accountId": "222222222222", "accountName": "two"},
    ]
    assert _select_accounts(accounts, "222222222222") == [{"accountId": "222222222222", "accountName": "two"}]


def test_select_default_accounts_uses_stored_ids(monkeypatch):
    accounts = [
        {"accountId": "111111111111", "accountName": "one"},
        {"accountId": "222222222222", "accountName": "two"},
    ]
    monkeypatch.setattr(prefetch, "get_default_account_ids", lambda: ["111111111111"])

    assert _select_default_accounts(accounts) == [{"accountId": "111111111111", "accountName": "one"}]


def test_select_default_accounts_falls_back_to_all_when_unset(monkeypatch):
    accounts = [
        {"accountId": "111111111111", "accountName": "one"},
        {"accountId": "222222222222", "accountName": "two"},
    ]
    monkeypatch.setattr(prefetch, "get_default_account_ids", lambda: None)

    assert _select_default_accounts(accounts) == accounts


def test_dashboard_default_jobs(monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 18)

    monkeypatch.setattr(prefetch, "date", FixedDate)
    args = parse_args(["--preset", "dashboard-default"])

    assert _build_jobs(args) == [
        ("MONTHLY", "2024-07-01", "2026-07-01"),
        ("DAILY", "2026-03-01", "2026-07-01"),
    ]
