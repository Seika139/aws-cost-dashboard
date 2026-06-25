# AGENTS.md

AWS SSO 配下の複数アカウントのコストを可視化するローカルダッシュボード。

## 技術スタック

- バックエンド: Python 3.12+ / FastAPI / boto3
- フロントエンド: Vanilla JS / Chart.js / HTML / CSS（フレームワークなし）
- パッケージ管理: uv
- リント/フォーマット: ruff (Python, line-length=120, select=E,F,I,W) / dprint (Markdown / TOML / JSON) / shfmt + shellcheck (shell) / yamllint (YAML)。`mise run lint` / `mise run format` で一括実行

## コマンド

```bash
mise run serve      # 起動 (port 8100)
mise run dev        # 開発（ホットリロード）
mise run sso-login  # SSO ログイン（ブラウザ認証）
mise run prefetch-cost -- --granularity BOTH --months 3  # Cost Explorer 事前取得
mise run prefetch-dashboard-default  # default accounts を 24か月 Monthly + 4か月 Daily で事前取得
mise run prefetch-launchd-install    # macOS launchd の事前取得ジョブを登録
mise run prefetch-launchd-status     # launchd の状態確認
mise run prefetch-launchd-logs       # launchd のログ確認
mise run test       # テスト
mise run lint       # リント (dprint/ruff/shfmt/shellcheck/yamllint)
mise run format     # フォーマット (dprint/ruff/shfmt/yamllint)
mise run grant-permissions  # .mise/tasks/*.sh に実行権限を付与
```

## コーディングルール

### セキュリティ

- **innerHTML 使用禁止**: pre-commit フックで検知される。DOM 構築は必ず `document.createElement` / `textContent` / `appendChild` を使う
- SSO トークンやクレデンシャルをソースコードにハードコードしない

### フロントエンド (static/)

- フレームワークを導入しない。Vanilla JS + DOM API のみ
- Chart.js はCDNから読み込み（バンドラーなし）
- CSS変数は `:root` の既存テーマに従う（ダークテーマ: charcoal + amber accent）
- フォント: DM Sans (UI) + JetBrains Mono (数値/コード)

### バックエンド (src/)

- ruff でリント・フォーマットしてからコミットする
- Cost Explorer API は高額（$0.01/リクエスト）なので必ずキャッシュ経由で呼ぶ
- 新しい API エンドポイントには `SSOTokenExpiredError` のハンドリングを入れる

### AWS SSO 設定

- SSO 設定は `~/.aws/config` の `[sso-session ...]` セクションから動的に読み取る（ハードコード不可）
- トークン読取元: `~/.aws/sso/cache/*.json`（ファイル名は session 名の SHA1 ハッシュ）
- SSO ログインはアプリの UI（ヘッダーの SSO Login ボタン）または `mise run sso-login` から実行可能

### キャッシュ・データ保存

- 料金キャッシュ（サーバー）: SQLite `data/cache.db` — 当月 bucket は TTL 1週間、過去確定月 bucket は TTL 90日
- 料金キャッシュ（クライアント）: localStorage `awscc:cost:*` — TTL 1時間
- SSO account / role metadata: SQLite `data/cache.db` — TTL 24時間（SSO token 有効性は別途確認）
- ユーザー設定: localStorage `awscc:config:defaultAccounts` + SQLite `user_settings.default_accounts`
- `cost.py` のレスポンス構造を変えたらサーバーキャッシュのクリアが必要（`DELETE /api/cache` または DB 直接削除）
- `DAILY` と `MONTHLY` は相互変換しない。Cost Explorer の `ResultsByTime` 単位で、同じ granularity 内だけ部分再利用する

## ファイル構成

- `src/auth.py` — SSO 設定読取（~/.aws/config）、OIDC デバイス認可フロー、トークンキャッシュ、アカウント一覧、ロール一覧、一時クレデンシャル取得
- `src/accounts.py` — アカウント＋ロール情報の組み立て
- `src/cost.py` — Cost Explorer API ラッパー。全5メトリクス一括取得、Net系フォールバック、期間 bucket キャッシュ
- `src/cache.py` — SQLite キャッシュ CRUD
- `src/pricing.py` — Price List API ラッパー。On-Demand 単価取得
- `src/resources.py` — EC2 / ECS / RDS / S3 / ElastiCache の棚卸し、Actual Cost 付与
- `src/prefetch.py` — Cost Explorer cache 事前取得 CLI
- `src/main.py` — FastAPI ルーティング。ポート 8100
- `.mise/tasks/prefetch-launchd-*.sh` — macOS launchd 事前取得ジョブの登録・削除・即時実行・状態/ログ確認
- `.mise/tasks/lint.sh` / `.mise/tasks/format.sh` — 全言語のリント・フォーマット (dprint/ruff/shfmt/shellcheck/yamllint)
- `.mise/common.sh` — mise タスク共通のシェルヘルパー（ANSI 色付け関数）
- `dprint.json` — dprint の設定（Markdown / TOML / JSON プラグイン、除外パス）
- `static/app.js` — SPA ロジック。フェッチ（同時実行数制限）、描画（IntersectionObserver 遅延）、localStorage キャッシュ
- `static/style.css` — ダークテーマ CSS。CSS変数ベース
- `static/index.html` — SPA エントリポイント
