"""auth.py のテスト: config パーサー、トークンキャッシュ読取、SHA1 パス互換性."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.auth import (
    SSOConfigError,
    _cache_path_for_session,
    _load_cached_token,
    _save_token_cache,
    get_sso_session,
    get_sso_sessions,
)

# ============================================================
# ヘルパー
# ============================================================


def _write_aws_config(path, content: str):
    """テスト用の ~/.aws/config を書き込む."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _write_token_cache(cache_dir, session_name: str, data: dict):
    """テスト用のトークンキャッシュファイルを書き込む."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = hashlib.sha1(session_name.encode()).hexdigest() + ".json"
    (cache_dir / filename).write_text(json.dumps(data))


def _future_iso(hours: int = 12) -> str:
    """現在から指定時間後の ISO 8601 文字列を返す."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 1) -> str:
    """現在から指定時間前の ISO 8601 文字列を返す."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ============================================================
# config パーサー: get_sso_sessions
# ============================================================


class TestGetSsoSessions:
    def test_single_session(self, tmp_path):
        """sso-session が 1 つ → 正常に取得できる."""
        config_path = tmp_path / "config"
        _write_aws_config(
            config_path,
            """\
[sso-session my_session]
sso_start_url = https://example.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access
""",
        )
        sessions = get_sso_sessions(config_path)
        assert len(sessions) == 1
        assert sessions[0]["name"] == "my_session"
        assert sessions[0]["start_url"] == "https://example.awsapps.com/start"
        assert sessions[0]["region"] == "us-east-1"

    def test_multiple_sessions(self, tmp_path):
        """sso-session が複数 → 全て取得できる."""
        config_path = tmp_path / "config"
        _write_aws_config(
            config_path,
            """\
[sso-session session_a]
sso_start_url = https://a.awsapps.com/start
sso_region = us-east-1

[sso-session session_b]
sso_start_url = https://b.awsapps.com/start
sso_region = ap-northeast-1
""",
        )
        sessions = get_sso_sessions(config_path)
        assert len(sessions) == 2
        names = {s["name"] for s in sessions}
        assert names == {"session_a", "session_b"}

    def test_no_sso_session_raises(self, tmp_path):
        """sso-session が 0 → SSOConfigError."""
        config_path = tmp_path / "config"
        _write_aws_config(
            config_path,
            """\
[profile some_profile]
region = us-east-1
""",
        )
        with pytest.raises(SSOConfigError, match="sso-session が定義されていません"):
            get_sso_sessions(config_path)

    def test_missing_config_file_raises(self, tmp_path):
        """config ファイルが存在しない → SSOConfigError."""
        config_path = tmp_path / "nonexistent"
        with pytest.raises(SSOConfigError, match="見つかりません"):
            get_sso_sessions(config_path)

    def test_missing_keys_use_fallbacks(self, tmp_path):
        """sso_region 等が未定義 → フォールバック値が使われる."""
        config_path = tmp_path / "config"
        _write_aws_config(
            config_path,
            """\
[sso-session minimal]
sso_start_url = https://example.awsapps.com/start
""",
        )
        sessions = get_sso_sessions(config_path)
        assert sessions[0]["region"] == ""
        assert sessions[0]["scopes"] == "sso:account:access"

    def test_non_sso_sections_ignored(self, tmp_path):
        """profile セクションは sso-session として扱われない."""
        config_path = tmp_path / "config"
        _write_aws_config(
            config_path,
            """\
[profile dev]
sso_session = my_session
sso_account_id = 123456789012
region = ap-northeast-1

[sso-session my_session]
sso_start_url = https://example.awsapps.com/start
sso_region = us-east-1
""",
        )
        sessions = get_sso_sessions(config_path)
        assert len(sessions) == 1
        assert sessions[0]["name"] == "my_session"


# ============================================================
# session 選択: get_sso_session
# ============================================================


class TestGetSsoSession:
    def test_auto_select_single(self, tmp_path):
        """session が 1 つなら名前省略で自動選択."""
        config_path = tmp_path / "config"
        _write_aws_config(
            config_path,
            """\
[sso-session only_one]
sso_start_url = https://example.awsapps.com/start
sso_region = us-east-1
""",
        )
        session = get_sso_session(config_path=config_path)
        assert session["name"] == "only_one"

    def test_select_by_name(self, tmp_path):
        """名前を指定して特定の session を取得."""
        config_path = tmp_path / "config"
        _write_aws_config(
            config_path,
            """\
[sso-session alpha]
sso_start_url = https://a.awsapps.com/start
sso_region = us-east-1

[sso-session beta]
sso_start_url = https://b.awsapps.com/start
sso_region = ap-northeast-1
""",
        )
        session = get_sso_session("beta", config_path=config_path)
        assert session["name"] == "beta"
        assert session["region"] == "ap-northeast-1"

    def test_multiple_without_name_raises(self, tmp_path):
        """session が複数で名前省略 → SSOConfigError."""
        config_path = tmp_path / "config"
        _write_aws_config(
            config_path,
            """\
[sso-session alpha]
sso_start_url = https://a.awsapps.com/start
sso_region = us-east-1

[sso-session beta]
sso_start_url = https://b.awsapps.com/start
sso_region = ap-northeast-1
""",
        )
        with pytest.raises(SSOConfigError, match="複数あります"):
            get_sso_session(config_path=config_path)

    def test_nonexistent_name_raises(self, tmp_path):
        """存在しない session 名 → SSOConfigError."""
        config_path = tmp_path / "config"
        _write_aws_config(
            config_path,
            """\
[sso-session real]
sso_start_url = https://example.awsapps.com/start
sso_region = us-east-1
""",
        )
        with pytest.raises(SSOConfigError, match="見つかりません"):
            get_sso_session("ghost", config_path=config_path)


# ============================================================
# SHA1 キャッシュパス互換性
# ============================================================


class TestCachePathForSession:
    def test_sha1_hash_matches(self):
        """キャッシュファイル名が session 名の SHA1 と一致する."""
        name = "sso_session_250508"
        expected_hash = hashlib.sha1(name.encode()).hexdigest()
        path = _cache_path_for_session(name)
        assert path.name == expected_hash + ".json"

    def test_custom_cache_dir(self, tmp_path):
        """cache_dir を指定するとそのディレクトリ配下にパスが生成される."""
        path = _cache_path_for_session("test", cache_dir=tmp_path)
        assert path.parent == tmp_path

    def test_different_names_produce_different_paths(self):
        """異なる session 名 → 異なるファイルパス."""
        path_a = _cache_path_for_session("session_a")
        path_b = _cache_path_for_session("session_b")
        assert path_a != path_b


# ============================================================
# トークンキャッシュ読取: _load_cached_token
# ============================================================


class TestLoadCachedToken:
    def test_valid_token(self, tmp_path):
        """有効期限内のトークン → データが返る."""
        _write_token_cache(
            tmp_path,
            "my_session",
            {
                "accessToken": "valid-token-123",
                "expiresAt": _future_iso(12),
                "startUrl": "https://example.awsapps.com/start",
                "region": "us-east-1",
            },
        )
        result = _load_cached_token("my_session", cache_dir=tmp_path)
        assert result is not None
        assert result["accessToken"] == "valid-token-123"

    def test_expired_token_returns_none(self, tmp_path):
        """有効期限切れ → None."""
        _write_token_cache(
            tmp_path,
            "my_session",
            {
                "accessToken": "expired-token",
                "expiresAt": _past_iso(1),
            },
        )
        result = _load_cached_token("my_session", cache_dir=tmp_path)
        assert result is None

    def test_missing_access_token_returns_none(self, tmp_path):
        """accessToken キーなし → None."""
        _write_token_cache(
            tmp_path,
            "my_session",
            {
                "clientId": "some-client",
                "clientSecret": "some-secret",
                "expiresAt": _future_iso(12),
            },
        )
        result = _load_cached_token("my_session", cache_dir=tmp_path)
        assert result is None

    def test_no_cache_file_returns_none(self, tmp_path):
        """キャッシュファイルが存在しない → None."""
        result = _load_cached_token("nonexistent", cache_dir=tmp_path)
        assert result is None

    def test_corrupted_json_returns_none(self, tmp_path):
        """壊れた JSON → None."""
        tmp_path.mkdir(parents=True, exist_ok=True)
        filename = hashlib.sha1(b"broken").hexdigest() + ".json"
        (tmp_path / filename).write_text("not valid json{{{")
        result = _load_cached_token("broken", cache_dir=tmp_path)
        assert result is None

    def test_utc_z_suffix_handled(self, tmp_path):
        """expiresAt が 'Z' 末尾（AWS CLI 形式） → 正しくパースされる."""
        _write_token_cache(
            tmp_path,
            "my_session",
            {
                "accessToken": "z-token",
                "expiresAt": "2099-12-31T23:59:59Z",
            },
        )
        result = _load_cached_token("my_session", cache_dir=tmp_path)
        assert result is not None
        assert result["accessToken"] == "z-token"


# ============================================================
# トークンキャッシュ書き込み: _save_token_cache
# ============================================================


class TestSaveTokenCache:
    def test_creates_cache_file(self, tmp_path):
        """キャッシュファイルが正しいパスに作成される."""
        cache_dir = tmp_path / "sso" / "cache"
        token_data = {"accessToken": "new-token", "expiresAt": _future_iso(12)}
        _save_token_cache("my_session", token_data, cache_dir=cache_dir)

        expected_path = cache_dir / (hashlib.sha1(b"my_session").hexdigest() + ".json")
        assert expected_path.exists()

        saved = json.loads(expected_path.read_text())
        assert saved["accessToken"] == "new-token"

    def test_file_permissions(self, tmp_path):
        """キャッシュファイルのパーミッションが 0o600."""
        cache_dir = tmp_path / "cache"
        _save_token_cache("perm_test", {"accessToken": "x", "expiresAt": _future_iso()}, cache_dir=cache_dir)

        path = cache_dir / (hashlib.sha1(b"perm_test").hexdigest() + ".json")
        assert oct(path.stat().st_mode & 0o777) == oct(0o600)

    def test_roundtrip(self, tmp_path):
        """保存したトークンを読み取れる."""
        cache_dir = tmp_path / "cache"
        token_data = {
            "accessToken": "roundtrip-token",
            "expiresAt": _future_iso(12),
            "startUrl": "https://example.awsapps.com/start",
        }
        _save_token_cache("roundtrip", token_data, cache_dir=cache_dir)
        result = _load_cached_token("roundtrip", cache_dir=cache_dir)
        assert result is not None
        assert result["accessToken"] == "roundtrip-token"
