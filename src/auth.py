"""AWS SSO 認証: ~/.aws/config から SSO 設定を読み取り、トークン取得・ログイン・アカウント操作を行う."""

import configparser
import hashlib
import json
import logging
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.config import Config

from src.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

AWS_CONFIG_PATH = Path.home() / ".aws" / "config"
SSO_CACHE_DIR = Path.home() / ".aws" / "sso" / "cache"

# OIDC デバイス認可フローの設定
_OIDC_CLIENT_NAME = "aws-cost-dashboard"
_OIDC_CLIENT_TYPE = "public"
_OIDC_GRANT_TYPES = ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"]
_SSO_CACHE_TTL_HOURS = 24
_SSO_CONFIG = Config(
    signature_version=UNSIGNED,
    retries={"max_attempts": 5, "mode": "standard"},
    connect_timeout=5,
    read_timeout=30,
)


class SSOTokenExpiredError(Exception):
    """SSO トークンの有効期限切れ."""


class SSOConfigError(Exception):
    """~/.aws/config の SSO 設定に問題がある."""


# ============================================================
# ~/.aws/config パーサー
# ============================================================


def _parse_aws_config(config_path: Path | None = None) -> configparser.ConfigParser:
    """~/.aws/config をパースして返す."""
    path = config_path or AWS_CONFIG_PATH
    if not path.exists():
        raise SSOConfigError(f"{path} が見つかりません。AWS CLI の設定を行ってください。")
    config = configparser.ConfigParser()
    config.read(path)
    return config


def get_sso_sessions(config_path: Path | None = None) -> list[dict]:
    """~/.aws/config から全 sso-session を取得する."""
    config = _parse_aws_config(config_path)
    sessions = []
    for section in config.sections():
        if section.startswith("sso-session "):
            name = section.removeprefix("sso-session ")
            sessions.append(
                {
                    "name": name,
                    "start_url": config.get(section, "sso_start_url", fallback=""),
                    "region": config.get(section, "sso_region", fallback=""),
                    "scopes": config.get(section, "sso_registration_scopes", fallback="sso:account:access"),
                }
            )
    if not sessions:
        raise SSOConfigError("~/.aws/config に sso-session が定義されていません。")
    return sessions


def get_sso_session(session_name: str | None = None, *, config_path: Path | None = None) -> dict:
    """指定名の sso-session を返す。名前省略時は唯一の session を自動選択する."""
    sessions = get_sso_sessions(config_path)
    if session_name:
        for s in sessions:
            if s["name"] == session_name:
                return s
        raise SSOConfigError(f"sso-session '{session_name}' が見つかりません。")
    if len(sessions) == 1:
        return sessions[0]
    raise SSOConfigError(
        f"sso-session が複数あります: {[s['name'] for s in sessions]}。session_name を指定してください。"
    )


# ============================================================
# トークンキャッシュの読み書き
# ============================================================


def _cache_path_for_session(session_name: str, cache_dir: Path | None = None) -> Path:
    """sso-session 名から SHA1 ベースのキャッシュファイルパスを返す."""
    base = cache_dir or SSO_CACHE_DIR
    return base / f"{hashlib.sha1(session_name.encode()).hexdigest()}.json"


def _load_cached_token(session_name: str, cache_dir: Path | None = None) -> dict | None:
    """キャッシュからトークンデータを読み込む。有効期限切れなら None を返す."""
    cache_file = _cache_path_for_session(session_name, cache_dir)
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if "accessToken" not in data:
        return None
    expires_at = datetime.fromisoformat(data["expiresAt"].replace("Z", "+00:00"))
    if expires_at < datetime.now(timezone.utc):
        return None
    return data


def _save_token_cache(session_name: str, token_data: dict, cache_dir: Path | None = None) -> None:
    """トークンデータをキャッシュファイルに保存する."""
    base = cache_dir or SSO_CACHE_DIR
    base.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path_for_session(session_name, cache_dir)
    cache_file.write_text(json.dumps(token_data))
    cache_file.chmod(0o600)


# ============================================================
# アクセストークンの取得
# ============================================================


def _load_access_token_with_session(session_name: str | None = None) -> tuple[str, str, str]:
    """有効なアクセストークン、SSO リージョン、session 名を返す."""
    session = get_sso_session(session_name)
    cached = _load_cached_token(session["name"])
    if cached and cached.get("accessToken"):
        return cached["accessToken"], session["region"], session["name"]
    raise SSOTokenExpiredError(
        "SSO トークンが見つからないか有効期限切れです。ダッシュボードの SSO Login ボタン、"
        "または `mise run sso-login` を実行してください。"
    )


def _load_access_token(session_name: str | None = None) -> tuple[str, str]:
    """有効なアクセストークンと SSO リージョンを返す."""
    access_token, region, _session_name = _load_access_token_with_session(session_name)
    return access_token, region


def get_sso_client(session_name: str | None = None) -> tuple[boto3.client, str]:
    """認証済み SSO クライアントとアクセストークンを返す."""
    access_token, region = _load_access_token(session_name)
    client = boto3.client("sso", region_name=region, config=_SSO_CONFIG)
    return client, access_token


# ============================================================
# OIDC デバイス認可フロー（SSO ログイン）
# ============================================================


def _get_or_register_client(oidc_client: boto3.client, session: dict) -> dict:
    """OIDC クライアント登録を取得（キャッシュ or 新規登録）."""
    # クライアント登録キャッシュの探索
    for cache_file in SSO_CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if "clientId" in data and "clientSecret" in data and "accessToken" not in data:
            expires_at = datetime.fromisoformat(data["expiresAt"].replace("Z", "+00:00"))
            if expires_at > datetime.now(timezone.utc):
                return data

    # 新規登録
    resp = oidc_client.register_client(
        clientName=_OIDC_CLIENT_NAME,
        clientType=_OIDC_CLIENT_TYPE,
        grantTypes=_OIDC_GRANT_TYPES,
        scopes=session.get("scopes", "sso:account:access").split(","),
    )
    return {
        "clientId": resp["clientId"],
        "clientSecret": resp["clientSecret"],
        "expiresAt": datetime.fromtimestamp(resp["clientSecretExpiresAt"], tz=timezone.utc).isoformat(),
    }


def start_sso_login(session_name: str | None = None) -> dict:
    """OIDC デバイス認可フローを開始する。ブラウザで開く URL を返す."""
    session = get_sso_session(session_name)
    oidc_client = boto3.client("sso-oidc", region_name=session["region"], config=_SSO_CONFIG)

    client_reg = _get_or_register_client(oidc_client, session)
    auth_resp = oidc_client.start_device_authorization(
        clientId=client_reg["clientId"],
        clientSecret=client_reg["clientSecret"],
        startUrl=session["start_url"],
    )

    return {
        "session_name": session["name"],
        "region": session["region"],
        "start_url": session["start_url"],
        "client_id": client_reg["clientId"],
        "client_secret": client_reg["clientSecret"],
        "device_code": auth_resp["deviceCode"],
        "user_code": auth_resp["userCode"],
        "verification_uri": auth_resp["verificationUri"],
        "verification_uri_complete": auth_resp["verificationUriComplete"],
        "expires_in": auth_resp["expiresIn"],
        "interval": auth_resp.get("interval", 5),
    }


def poll_sso_token(login_context: dict) -> dict:
    """デバイス認可のポーリングを行い、トークンを取得・キャッシュする."""
    session_name = login_context["session_name"]
    oidc_client = boto3.client("sso-oidc", region_name=login_context["region"], config=_SSO_CONFIG)
    interval = login_context.get("interval", 5)
    deadline = time.time() + login_context.get("expires_in", 600)

    while time.time() < deadline:
        try:
            token_resp = oidc_client.create_token(
                clientId=login_context["client_id"],
                clientSecret=login_context["client_secret"],
                grantType="urn:ietf:params:oauth:grant-type:device_code",
                deviceCode=login_context["device_code"],
            )
            # トークンをキャッシュに保存
            expires_at = datetime.fromtimestamp(time.time() + token_resp["expiresIn"], tz=timezone.utc).isoformat()
            token_data = {
                "startUrl": login_context["start_url"],
                "region": login_context["region"],
                "accessToken": token_resp["accessToken"],
                "expiresAt": expires_at,
                "clientId": login_context["client_id"],
                "clientSecret": login_context["client_secret"],
                "registrationExpiresAt": "",
                "refreshToken": token_resp.get("refreshToken", ""),
            }
            _save_token_cache(session_name, token_data)
            logger.info("SSO ログイン成功: session=%s", session_name)
            return {"status": "success", "session_name": session_name, "expires_at": expires_at}
        except oidc_client.exceptions.AuthorizationPendingException:
            time.sleep(interval)
        except oidc_client.exceptions.SlowDownException:
            interval += 5
            time.sleep(interval)
        except oidc_client.exceptions.ExpiredTokenException:
            return {"status": "expired", "message": "認証の有効期限が切れました。再度ログインしてください。"}

    return {"status": "timeout", "message": "認証がタイムアウトしました。再度ログインしてください。"}


def sso_login_interactive(session_name: str | None = None) -> dict:
    """CLI 用: ブラウザを開いてログインし、完了まで待つ."""
    ctx = start_sso_login(session_name)
    print("ブラウザで認証ページを開きます...")
    print(f"  URL: {ctx['verification_uri_complete']}")
    print(f"  User Code: {ctx['user_code']}")
    webbrowser.open(ctx["verification_uri_complete"])
    print("ブラウザで認証を完了してください。待機中...")
    return poll_sso_token(ctx)


def list_accounts() -> list[dict]:
    """SSO 配下の全アカウントを取得する."""
    token, region, session_name = _load_access_token_with_session()
    cache_key = f"sso:accounts:{session_name}"
    cached = get_cached(cache_key, max_age_hours=_SSO_CACHE_TTL_HOURS)
    if cached is not None:
        return cached["accounts"]

    client = boto3.client("sso", region_name=region, config=_SSO_CONFIG)
    accounts = []
    paginator = client.get_paginator("list_accounts")
    for page in paginator.paginate(accessToken=token):
        accounts.extend(page["accountList"])
    accounts = sorted(accounts, key=lambda a: a["accountName"])
    set_cached(cache_key, {"accounts": accounts})
    return accounts


def list_account_roles(account_id: str) -> list[dict]:
    """指定アカウントで利用可能なロールを取得する."""
    token, region, session_name = _load_access_token_with_session()
    cache_key = f"sso:roles:{session_name}:{account_id}"
    cached = get_cached(cache_key, max_age_hours=_SSO_CACHE_TTL_HOURS)
    if cached is not None:
        return cached["roles"]

    client = boto3.client("sso", region_name=region, config=_SSO_CONFIG)
    paginator = client.get_paginator("list_account_roles")
    roles = []
    for page in paginator.paginate(accessToken=token, accountId=account_id):
        roles.extend(page["roleList"])
    set_cached(cache_key, {"roles": roles})
    return roles


def get_role_credentials(account_id: str, role_name: str) -> dict:
    """指定アカウント・ロールの一時クレデンシャルを取得する."""
    client, token = get_sso_client()
    resp = client.get_role_credentials(
        roleName=role_name,
        accountId=account_id,
        accessToken=token,
    )
    creds = resp["roleCredentials"]
    return {
        "aws_access_key_id": creds["accessKeyId"],
        "aws_secret_access_key": creds["secretAccessKey"],
        "aws_session_token": creds["sessionToken"],
    }
