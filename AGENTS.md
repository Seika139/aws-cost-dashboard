# AGENTS.md

AWS SSO 配下の複数アカウントのコストを可視化するローカルダッシュボード。

## 技術スタック

- バックエンド: Python 3.12+ / FastAPI / boto3
- フロントエンド: Vanilla JS / Chart.js / HTML / CSS（フレームワークなし）
- パッケージ管理: uv
- リンター: ruff (line-length=120, select=E,F,I,W)

## コマンド

```bash
mise run serve      # 起動 (port 8100)
mise run dev        # 開発（ホットリロード）
mise run sso-login  # SSO ログイン（ブラウザ認証）
mise run test       # テスト
mise run lint       # リント
mise run format     # フォーマット
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

- 料金キャッシュ（サーバー）: SQLite `data/cache.db` — TTL 24時間
- 料金キャッシュ（クライアント）: localStorage `awscc:cost:*` — TTL 1時間
- ユーザー設定: localStorage `awscc:config:defaultAccounts` — 永続（サーバー保存なし）
- `cost.py` のレスポンス構造を変えたらサーバーキャッシュのクリアが必要（`DELETE /api/cache` または DB 直接削除）

## ファイル構成

- `src/auth.py` — SSO 設定読取（~/.aws/config）、OIDC デバイス認可フロー、トークンキャッシュ、アカウント一覧、ロール一覧、一時クレデンシャル取得
- `src/accounts.py` — アカウント＋ロール情報の組み立て
- `src/cost.py` — Cost Explorer API ラッパー。全5メトリクス一括取得、Net系フォールバック、ページネーション
- `src/cache.py` — SQLite キャッシュ CRUD
- `src/main.py` — FastAPI ルーティング。ポート 8100
- `static/app.js` — SPA ロジック。フェッチ（同時実行数制限）、描画（IntersectionObserver 遅延）、localStorage キャッシュ
- `static/style.css` — ダークテーマ CSS。CSS変数ベース
- `static/index.html` — SPA エントリポイント
