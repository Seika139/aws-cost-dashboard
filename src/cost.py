"""Cost Explorer API ラッパー。複数アカウントのコストデータを取得."""

import logging
from datetime import date, timedelta

import boto3

from src.auth import get_role_credentials, list_account_roles, list_accounts
from src.cache import (
    DEFAULT_COST_CACHE_TTL_HOURS,
    FINALIZED_COST_CACHE_TTL_HOURS,
    get_cached,
    get_cost_period_cached,
    set_cached,
    set_cost_periods_cached,
)

logger = logging.getLogger(__name__)

# コスト取得に使うロールの優先順位（上から順に試す）
COST_ROLE_PRIORITY = [
    "ReadOnlyCostViewer",
    "ReadOnlyAccess",
    "ViewOnlyAccess",
    "BillingViewAccess",
]


def _pick_cost_role(account_id: str) -> str | None:
    """アカウントで利用可能なロールのうち、コスト閲覧に適したものを選ぶ."""
    roles = list_account_roles(account_id)
    role_names = {r["roleName"] for r in roles}

    for preferred in COST_ROLE_PRIORITY:
        if preferred in role_names:
            return preferred

    # 優先リストに該当がなければ最初のロールを試す
    if role_names:
        return next(iter(role_names))
    return None


def _get_ce_client(account_id: str, role_name: str):
    """指定アカウント用の Cost Explorer クライアントを作成."""
    creds = get_role_credentials(account_id, role_name)
    return boto3.client("ce", region_name="us-east-1", **creds)


ALL_METRICS = [
    "UnblendedCost",
    "AmortizedCost",
    "BlendedCost",
    "NetUnblendedCost",
    "NetAmortizedCost",
]


def get_account_cost(
    account_id: str,
    start: str,
    end: str,
    granularity: str = "MONTHLY",
    group_by: str = "SERVICE",
) -> dict | None:
    """1アカウントのコストデータを取得（キャッシュ付き）.

    全5種のコストメトリクスを一度に取得する。
    Net 系メトリクスが使えない場合は基本3メトリクスでフォールバック。
    """
    cache_key = f"cost:{account_id}:{start}:{end}:{granularity}:{group_by}"
    cached = get_cached(cache_key, max_age_hours=DEFAULT_COST_CACHE_TTL_HOURS)
    if cached is not None:
        logger.info(
            "Cost exact cache hit: account=%s start=%s end=%s granularity=%s group_by=%s",
            account_id,
            start,
            end,
            granularity,
            group_by,
        )
        set_cost_periods_cached(
            account_id,
            granularity,
            group_by,
            cached.get("results", []),
            role_name=cached.get("roleName"),
        )
        return cached

    expected_periods = _expected_periods(start, end, granularity)
    cached_periods, missing_periods, cached_role = _load_period_cache(
        account_id, expected_periods, granularity, group_by
    )
    if not missing_periods:
        logger.info(
            "Cost period cache full hit: account=%s start=%s end=%s granularity=%s group_by=%s periods=%s",
            account_id,
            start,
            end,
            granularity,
            group_by,
            len(cached_periods),
        )
        return {"accountId": account_id, "roleName": cached_role, "results": cached_periods}

    logger.info(
        "Cost period cache partial/miss: "
        "account=%s start=%s end=%s granularity=%s group_by=%s hit_periods=%s missing_periods=%s",
        account_id,
        start,
        end,
        granularity,
        group_by,
        len(cached_periods),
        len(missing_periods),
    )

    role_name = _pick_cost_role(account_id)
    if role_name is None:
        logger.warning("No role available for account %s", account_id)
        return None

    try:
        ce = _get_ce_client(account_id, role_name)
        fetched_results = []
        for fetch_start, fetch_end in _group_contiguous_periods(missing_periods):
            logger.info(
                "Cost Explorer fetch: account=%s start=%s end=%s granularity=%s group_by=%s",
                account_id,
                fetch_start,
                fetch_end,
                granularity,
                group_by,
            )
            fetched_results.extend(_fetch_cost_range(ce, fetch_start, fetch_end, granularity, group_by))

        set_cost_periods_cached(account_id, granularity, group_by, fetched_results, role_name=role_name)

        results = sorted(cached_periods + fetched_results, key=lambda period: period["TimePeriod"]["Start"])
        data = {"accountId": account_id, "roleName": role_name, "results": results}
        set_cached(cache_key, data)
        return data

    except Exception:
        logger.exception("Failed to get cost for account %s with role %s", account_id, role_name)
        return None


def _paginate_cost(ce, kwargs: dict) -> list:
    """Cost Explorer のページネーションを処理."""
    results = []
    kw = dict(kwargs)
    while True:
        resp = ce.get_cost_and_usage(**kw)
        results.extend(resp["ResultsByTime"])
        if "NextPageToken" in resp:
            kw["NextPageToken"] = resp["NextPageToken"]
        else:
            break
    return results


def _fetch_cost_range(ce, start: str, end: str, granularity: str, group_by: str) -> list:
    """指定範囲の Cost Explorer データを取得する。"""
    kwargs = {
        "TimePeriod": {"Start": start, "End": end},
        "Granularity": granularity,
        "Metrics": ALL_METRICS,
    }
    if group_by != "NONE":
        kwargs["GroupBy"] = [{"Type": "DIMENSION", "Key": group_by}]

    try:
        return _paginate_cost(ce, kwargs)
    except ce.exceptions.BillExpirationException:
        # Net 系メトリクスが使えないアカウントではフォールバック
        kwargs["Metrics"] = ["UnblendedCost", "AmortizedCost", "BlendedCost"]
        return _paginate_cost(ce, kwargs)
    except Exception:
        # その他のメトリクスエラーでもフォールバック
        kwargs["Metrics"] = ["UnblendedCost"]
        return _paginate_cost(ce, kwargs)


def _next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _expected_periods(start: str, end: str, granularity: str) -> list[tuple[str, str]]:
    """リクエスト範囲を Cost Explorer の bucket 単位に分割する。End は排他的。"""
    current = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    periods = []

    while current < end_date:
        if granularity == "DAILY":
            next_date = current + timedelta(days=1)
        elif granularity == "MONTHLY":
            next_date = _next_month(current)
        else:
            next_date = end_date
        if next_date > end_date:
            next_date = end_date
        periods.append((current.isoformat(), next_date.isoformat()))
        current = next_date

    return periods


def _load_period_cache(
    account_id: str,
    expected_periods: list[tuple[str, str]],
    granularity: str,
    group_by: str,
) -> tuple[list[dict], list[tuple[str, str]], str | None]:
    cached_periods = []
    missing_periods = []
    cached_role = None
    for period_start, period_end in expected_periods:
        entry = get_cost_period_cached(
            account_id,
            granularity,
            group_by,
            period_start,
            period_end,
            max_age_hours=_cost_period_ttl_hours(period_end),
        )
        if entry is None:
            missing_periods.append((period_start, period_end))
            continue
        cached_periods.append(entry["data"])
        if cached_role is None and entry.get("roleName"):
            cached_role = entry["roleName"]
    return cached_periods, missing_periods, cached_role


def _group_contiguous_periods(periods: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """連続して欠けている bucket を Cost Explorer に渡せる範囲にまとめる。"""
    if not periods:
        return []
    sorted_periods = sorted(periods)
    ranges = []
    range_start, range_end = sorted_periods[0]
    for period_start, period_end in sorted_periods[1:]:
        if period_start == range_end:
            range_end = period_end
            continue
        ranges.append((range_start, range_end))
        range_start, range_end = period_start, period_end
    ranges.append((range_start, range_end))
    return ranges


def _cost_period_ttl_hours(period_end: str) -> int:
    """過去確定月は長く、当月を含む bucket は通常 TTL にする。"""
    current_month_start = date.today().replace(day=1)
    if date.fromisoformat(period_end) <= current_month_start:
        return FINALIZED_COST_CACHE_TTL_HOURS
    return DEFAULT_COST_CACHE_TTL_HOURS


def get_all_accounts_cost(
    start: str | None = None,
    end: str | None = None,
    granularity: str = "MONTHLY",
    group_by: str = "SERVICE",
) -> list[dict]:
    """全アカウントのコストデータを取得.

    デフォルト期間: 過去3ヶ月
    """
    if end is None:
        end = date.today().replace(day=1).isoformat()
    if start is None:
        end_date = date.fromisoformat(end)
        start_date = (end_date - timedelta(days=90)).replace(day=1)
        start = start_date.isoformat()

    accounts = list_accounts()
    results = []
    for acct in accounts:
        logger.info("Fetching cost for %s (%s)...", acct["accountName"], acct["accountId"])
        cost = get_account_cost(acct["accountId"], start, end, granularity, group_by)
        if cost is not None:
            cost["accountName"] = acct["accountName"]
            results.append(cost)
        else:
            results.append(
                {
                    "accountId": acct["accountId"],
                    "accountName": acct["accountName"],
                    "roleName": None,
                    "results": [],
                    "error": "Failed to fetch cost data",
                }
            )
    return results
