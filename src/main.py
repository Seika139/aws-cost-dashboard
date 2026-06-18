"""AWS Cost Dashboard - FastAPI サーバー."""

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.accounts import get_accounts_with_roles
from src.auth import (
    SSOConfigError,
    SSOTokenExpiredError,
    get_sso_sessions,
    list_accounts,
    poll_sso_token,
    start_sso_login,
)
from src.cache import (
    clear_cache,
    clear_default_account_ids,
    get_default_account_ids,
    get_resource_history,
    set_default_account_ids,
)
from src.cost import get_account_cost, get_all_accounts_cost
from src.resources import get_account_resources

logging.basicConfig(level=logging.INFO)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="AWS Cost Dashboard")


class DefaultAccountsPayload(BaseModel):
    accountIds: list[str]


@app.exception_handler(SSOTokenExpiredError)
async def handle_sso_token_expired(_request: Request, exc: SSOTokenExpiredError):
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(SSOConfigError)
async def handle_sso_config_error(_request: Request, exc: SSOConfigError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/accounts")
async def api_accounts():
    """全アカウント一覧を返す（ロール情報なし・高速版）."""
    accounts = list_accounts()
    return {"accounts": accounts, "count": len(accounts)}


@app.get("/api/accounts/detail")
async def api_accounts_detail():
    """全アカウントとロール情報を返す（遅い）."""
    accounts = get_accounts_with_roles()
    return {"accounts": accounts, "count": len(accounts)}


@app.get("/api/cost")
async def api_cost(
    start: str | None = Query(None, description="開始日 YYYY-MM-DD"),
    end: str | None = Query(None, description="終了日 YYYY-MM-DD"),
    granularity: str = Query("MONTHLY", description="DAILY or MONTHLY"),
    group_by: str = Query("SERVICE", description="SERVICE, REGION, USAGE_TYPE, or NONE"),
):
    """全アカウントのコストデータを返す."""
    results = get_all_accounts_cost(start, end, granularity, group_by)
    return {"results": results, "count": len(results)}


@app.get("/api/cost/{account_id}")
async def api_cost_single(
    account_id: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
    granularity: str = Query("MONTHLY"),
    group_by: str = Query("SERVICE"),
):
    """単一アカウントのコストデータを返す."""
    from datetime import date, timedelta

    if end is None:
        end = date.today().replace(day=1).isoformat()
    if start is None:
        end_date = date.fromisoformat(end)
        start_date = (end_date - timedelta(days=90)).replace(day=1)
        start = start_date.isoformat()

    result = get_account_cost(account_id, start, end, granularity, group_by)
    if result is None:
        raise HTTPException(status_code=404, detail="Cost data not available for this account")
    return result


@app.delete("/api/cache")
async def api_clear_cache():
    """キャッシュを全削除."""
    count = clear_cache()
    return {"deleted": count}


# ============================================================
# Config
# ============================================================


@app.get("/api/config/default-accounts")
async def api_get_default_accounts():
    """Config タブのデフォルト選択アカウントを返す。None は全アカウント選択を意味する。"""
    return {"accountIds": get_default_account_ids()}


@app.post("/api/config/default-accounts")
async def api_set_default_accounts(payload: DefaultAccountsPayload):
    """Config タブのデフォルト選択アカウントを保存する。"""
    account_ids = [account_id for account_id in payload.accountIds if account_id]
    set_default_account_ids(account_ids)
    return {"accountIds": account_ids}


@app.delete("/api/config/default-accounts")
async def api_clear_default_accounts():
    """Config タブのデフォルト選択アカウントを削除する（全アカウント選択）。"""
    clear_default_account_ids()
    return {"accountIds": None}


# ============================================================
# Resources
# ============================================================


@app.get("/api/resources/{account_id}")
async def api_resources(
    account_id: str,
    service: str | None = Query(None, description="ec2, ecs, rds, s3, elasticache"),
):
    """アカウントのリソース情報を返す（日次スナップショット）."""
    result = await asyncio.to_thread(get_account_resources, account_id, service)
    return result


@app.get("/api/resources/{account_id}/history")
async def api_resource_history(
    account_id: str,
    service: str = Query(..., description="ec2, ecs, rds, s3, elasticache"),
    days: int = Query(30, description="取得する日数"),
):
    """リソーススナップショットの履歴を返す."""
    snapshots = get_resource_history(account_id, service, days)
    return {"accountId": account_id, "service": service, "snapshots": snapshots}


# ============================================================
# SSO 認証
# ============================================================

# 進行中のログインコンテキストを一時保持（単一ユーザー前提のローカルアプリ）
_login_context: dict | None = None


@app.get("/api/sso/sessions")
async def api_sso_sessions():
    """~/.aws/config に定義されている sso-session 一覧を返す."""
    sessions = get_sso_sessions()
    return {"sessions": sessions}


@app.post("/api/sso/login")
async def api_sso_login(session_name: str | None = Query(None)):
    """SSO ログインを開始し、ブラウザで開く認証 URL を返す."""
    global _login_context  # noqa: PLW0603
    _login_context = start_sso_login(session_name)
    return {
        "user_code": _login_context["user_code"],
        "verification_uri": _login_context["verification_uri"],
        "verification_uri_complete": _login_context["verification_uri_complete"],
        "expires_in": _login_context["expires_in"],
    }


@app.post("/api/sso/login/poll")
async def api_sso_login_poll():
    """ブラウザでの認証完了をポーリングする."""
    if _login_context is None:
        raise HTTPException(
            status_code=400, detail="ログインが開始されていません。先に /api/sso/login を呼んでください。"
        )
    result = await asyncio.to_thread(poll_sso_token, _login_context)
    return result
