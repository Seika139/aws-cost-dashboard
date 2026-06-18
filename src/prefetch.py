"""Cost Explorer cache prefetch CLI."""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from src.auth import SSOTokenExpiredError, list_accounts
from src.cache import get_default_account_ids
from src.cost import get_account_cost

logger = logging.getLogger(__name__)


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _next_month(day: date) -> date:
    return _add_months(day.replace(day=1), 1)


def default_date_range(months: int, today: date | None = None) -> tuple[str, str]:
    """months 個分の月を、当月を含めて返す。End は翌月初日。"""
    if months < 1:
        raise ValueError("--months must be greater than or equal to 1")
    base = today or date.today()
    current_month = base.replace(day=1)
    start = _add_months(current_month, -(months - 1))
    end = _next_month(current_month)
    return start.isoformat(), end.isoformat()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prefetch AWS Cost Explorer data into SQLite cache.")
    parser.add_argument(
        "--preset",
        choices=["custom", "dashboard-default"],
        default="custom",
        help="Prefetch preset. dashboard-default uses default accounts, 24 monthly months, and 4 daily months.",
    )
    parser.add_argument(
        "--granularity",
        choices=["DAILY", "MONTHLY", "BOTH"],
        default="BOTH",
        help="Cost Explorer granularity to prefetch. Default: BOTH",
    )
    parser.add_argument("--months", type=int, default=3, help="Months to prefetch including the current month.")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD). Overrides --months when used with --end.")
    parser.add_argument("--end", help="End date (YYYY-MM-DD, exclusive). Overrides --months when used with --start.")
    parser.add_argument(
        "--group-by",
        choices=["SERVICE", "REGION", "USAGE_TYPE", "NONE"],
        default="SERVICE",
        help="Cost Explorer group_by dimension. Default: SERVICE",
    )
    parser.add_argument("--accounts", help="Comma-separated account IDs. Default: all SSO accounts.")
    parser.add_argument(
        "--use-default-accounts",
        action="store_true",
        help="Use Config tab default accounts stored in SQLite. If unset there, all accounts are used.",
    )
    parser.add_argument(
        "--monthly-months",
        type=int,
        default=24,
        help="Months for MONTHLY prefetch when --preset dashboard-default is used.",
    )
    parser.add_argument(
        "--daily-months",
        type=int,
        default=4,
        help="Months for DAILY prefetch when --preset dashboard-default is used.",
    )
    parser.add_argument("--concurrency", type=int, default=4, help="Max parallel account fetches. Default: 4")
    parser.add_argument("--dry-run", action="store_true", help="Print the prefetch plan without fetching AWS data.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def _granularities(value: str) -> list[str]:
    if value == "BOTH":
        return ["MONTHLY", "DAILY"]
    return [value]


def _select_accounts(accounts: list[dict], account_ids: str | None) -> list[dict]:
    if not account_ids:
        return accounts
    requested = {account_id.strip() for account_id in account_ids.split(",") if account_id.strip()}
    return [account for account in accounts if account["accountId"] in requested]


def _select_default_accounts(accounts: list[dict]) -> list[dict]:
    default_ids = get_default_account_ids()
    if default_ids is None:
        return accounts
    requested = set(default_ids)
    return [account for account in accounts if account["accountId"] in requested]


def _mask_account_id(account_id: str) -> str:
    if len(account_id) < 8:
        return account_id
    return f"{account_id[:4]}****{account_id[-4:]}"


def _prefetch_one(account: dict, start: str, end: str, granularity: str, group_by: str) -> tuple[str, bool, str]:
    account_id = account["accountId"]
    account_name = account.get("accountName", account_id)
    result = get_account_cost(account_id, start, end, granularity, group_by)
    if result is None or result.get("error"):
        return account_name, False, result.get("error", "failed") if result else "failed"
    return account_name, True, f"{len(result.get('results', []))} periods"


def _build_jobs(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    if args.preset == "dashboard-default":
        monthly_start, monthly_end = default_date_range(args.monthly_months)
        daily_start, daily_end = default_date_range(args.daily_months)
        return [("MONTHLY", monthly_start, monthly_end), ("DAILY", daily_start, daily_end)]

    if args.start or args.end:
        if not args.start or not args.end:
            raise SystemExit("--start and --end must be provided together")
        start, end = args.start, args.end
    else:
        start, end = default_date_range(args.months)
    return [(granularity, start, end) for granularity in _granularities(args.granularity)]


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")

    try:
        accounts = list_accounts()
    except SSOTokenExpiredError as exc:
        logger.error("%s", exc)
        return 1

    if args.preset == "dashboard-default" or args.use_default_accounts:
        accounts = _select_default_accounts(accounts)
    else:
        accounts = _select_accounts(accounts, args.accounts)

    jobs = _build_jobs(args)
    logger.info(
        "Prefetch plan: preset=%s accounts=%s jobs=%s group_by=%s concurrency=%s",
        args.preset,
        len(accounts),
        ",".join(f"{granularity}:{start}:{end}" for granularity, start, end in jobs),
        args.group_by,
        args.concurrency,
    )

    if args.dry_run:
        for account in accounts:
            logger.info("Dry run account=%s (%s)", account.get("accountName"), _mask_account_id(account["accountId"]))
        return 0

    failures = 0
    for granularity, start, end in jobs:
        logger.info("Prefetch granularity=%s start=%s end=%s", granularity, start, end)
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            futures = [
                pool.submit(_prefetch_one, account, start, end, granularity, args.group_by) for account in accounts
            ]
            for future in as_completed(futures):
                account_name, ok, detail = future.result()
                if ok:
                    logger.info("Prefetch ok: account=%s granularity=%s detail=%s", account_name, granularity, detail)
                else:
                    failures += 1
                    logger.warning(
                        "Prefetch failed: account=%s granularity=%s detail=%s",
                        account_name,
                        granularity,
                        detail,
                    )

    if failures:
        logger.warning("Prefetch completed with failures: %s", failures)
        return 1
    logger.info("Prefetch completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
