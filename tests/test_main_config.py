"""main.py の Config API テスト。"""

import asyncio

from src import cache
from src.main import (
    DefaultAccountsPayload,
    api_clear_default_accounts,
    api_get_default_accounts,
    api_set_default_accounts,
)


def test_default_accounts_api_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "cache.db")

    assert asyncio.run(api_get_default_accounts()) == {"accountIds": None}

    payload = DefaultAccountsPayload(accountIds=["111111111111", "222222222222"])
    assert asyncio.run(api_set_default_accounts(payload)) == {"accountIds": ["111111111111", "222222222222"]}
    assert asyncio.run(api_get_default_accounts()) == {"accountIds": ["111111111111", "222222222222"]}

    assert asyncio.run(api_clear_default_accounts()) == {"accountIds": None}
