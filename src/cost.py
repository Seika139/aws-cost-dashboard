"""Cost Explorer API ラッパー。複数アカウントのコストデータを取得."""

import logging
from datetime import date, timedelta

import boto3

from src.auth import get_role_credentials, list_account_roles, list_accounts
from src.cache import get_cached, set_cached

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
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    role_name = _pick_cost_role(account_id)
    if role_name is None:
        logger.warning("No role available for account %s", account_id)
        return None

    try:
        ce = _get_ce_client(account_id, role_name)
        kwargs = {
            "TimePeriod": {"Start": start, "End": end},
            "Granularity": granularity,
            "Metrics": ALL_METRICS,
        }
        if group_by != "NONE":
            kwargs["GroupBy"] = [{"Type": "DIMENSION", "Key": group_by}]

        try:
            results = _paginate_cost(ce, kwargs)
        except ce.exceptions.BillExpirationException:
            # Net 系メトリクスが使えないアカウントではフォールバック
            kwargs["Metrics"] = ["UnblendedCost", "AmortizedCost", "BlendedCost"]
            results = _paginate_cost(ce, kwargs)
        except Exception:
            # その他のメトリクスエラーでもフォールバック
            kwargs["Metrics"] = ["UnblendedCost"]
            results = _paginate_cost(ce, kwargs)

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
