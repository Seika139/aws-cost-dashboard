# AWS Cost Dashboard

<div align="center">
  <a href="https://github.com/Seika139/aws-cost-dashboard/actions/workflows/uv-qualify.yml">
    <img alt="Qualify Code" src="https://github.com/Seika139/aws-cost-dashboard/actions/workflows/uv-qualify.yml/badge.svg">
  </a>
  <a href="https://github.com/Seika139/aws-cost-dashboard/actions/workflows/lint-markdown.yml">
    <img alt="Lint Markdown" src="https://github.com/Seika139/aws-cost-dashboard/actions/workflows/lint-markdown.yml/badge.svg">
  </a>
</div>

AWS SSO (IAM Identity Center) 配下の複数アカウントのコストデータを横断的に可視化するローカルダッシュボード。

## 機能

- **マルチアカウント対応**: SSO 配下の全アカウントを自動検出・一覧表示
- **コスト可視化**:
  - アカウント別トータルコストの折れ線グラフ（Overview）
  - アカウントごとのサービス別積み上げ棒グラフ
  - コスト集計テーブル（シェア率付き）
- **5種のコストメトリクス**: Unblended / Amortized / Blended / Net Unblended / Net Amortized を切替可能
- **柔軟なフィルタリング**: 期間（年月セレクタ）、粒度（Monthly/Daily）、アカウント選択
- **2層キャッシュ**: サーバー側 SQLite (期間 bucket キャッシュ) + クライアント側 localStorage (1h TTL) で Cost Explorer API の課金を最小化
- **バックグラウンド事前取得**: `mise run prefetch-cost` で Cost Explorer データを先にキャッシュ可能
- **パフォーマンス最適化**: 同時実行数制限付きフェッチ、IntersectionObserver によるチャート遅延描画

## 前提条件

- [mise](https://mise.jdx.dev/) で Python 3.12 と uv を自動管理（`mise.toml` で定義済み）
- AWS SSO (IAM Identity Center) へのアクセス権
- `~/.aws/config` に `[sso-session ...]` セクションが設定されていること

## セットアップ

```bash
# ツール（Python, uv）と依存パッケージのインストール
mise install && uv sync

# AWS SSO ログイン（以下のいずれかの方法）

# 方法1: mise task（ブラウザが自動で開く）
mise run sso-login

# 方法2: ダッシュボード起動後、ヘッダーの「SSO Login」ボタンから
mise run serve
# → http://localhost:8100 を開き、右上の SSO Login をクリック

# 方法3: AWS CLI（従来の方法）
aws sso login --sso-session <your-session-name>
```

`~/.aws/config` に `sso-session` が 1 つだけ定義されている場合、セッション名の指定は不要（自動選択される）。

## 起動

```bash
mise run serve
```

ブラウザで <http://localhost:8100> を開く。

## アーキテクチャ

```text
aws-cost-dashboard/
├── src/
│   ├── main.py        # FastAPI サーバー / ルーティング
│   ├── auth.py        # SSO 設定読取 / OIDC ログイン / クレデンシャル取得
│   ├── accounts.py    # アカウント一覧 + ロール情報
│   ├── cost.py        # Cost Explorer API ラッパー（全5メトリクス取得）
│   ├── pricing.py     # Price List API ラッパー（On-Demand 単価取得）
│   ├── resources.py   # EC2/ECS/RDS/S3/ElastiCache の棚卸し
│   └── cache.py       # SQLite キャッシュ（期間 bucket / SSO metadata / resource snapshot）
├── static/
│   ├── index.html     # SPA エントリポイント
│   ├── app.js         # クライアントロジック / Chart.js 描画
│   └── style.css      # ダークテーマ UI
├── data/              # SQLite DB（.gitignore 対象）
└── pyproject.toml
```

### データフロー

```text
Browser (app.js)
  ├─ localStorage cache (1h TTL) ─ hit → render
  └─ miss → GET /api/cost/{account_id}
               └─ FastAPI (main.py)
                    └─ SQLite period cache ─ hit → respond
                    └─ miss → Cost Explorer API
                                └─ SSO get_role_credentials
                                     └─ ~/.aws/sso/cache/ (access token)
                                          └─ ~/.aws/config (sso-session 設定)
```

### API エンドポイント

| Method | Path                           | 説明                                       |
| ------ | ------------------------------ | ------------------------------------------ |
| GET    | `/`                            | ダッシュボード HTML                        |
| GET    | `/api/accounts`                | 全アカウント一覧（高速版）                 |
| GET    | `/api/accounts/detail`         | 全アカウント＋ロール情報                   |
| GET    | `/api/cost`                    | 全アカウントのコスト一括取得               |
| GET    | `/api/cost/{account_id}`       | 単一アカウントのコスト取得                 |
| DELETE | `/api/cache`                   | サーバーキャッシュ全削除                   |
| GET    | `/api/config/default-accounts` | デフォルト選択アカウント取得               |
| POST   | `/api/config/default-accounts` | デフォルト選択アカウント保存               |
| DELETE | `/api/config/default-accounts` | デフォルト選択アカウント削除               |
| GET    | `/api/sso/sessions`            | `~/.aws/config` の sso-session 一覧        |
| POST   | `/api/sso/login`               | SSO ログイン開始（認証 URL を返す）        |
| POST   | `/api/sso/login/poll`          | 認証完了をポーリング（トークン取得・保存） |

`/api/cost/{account_id}` のクエリパラメータ:

| パラメータ    | デフォルト    | 説明                                      |
| ------------- | ------------- | ----------------------------------------- |
| `start`       | 3か月前の月初 | 開始日 (YYYY-MM-DD)                       |
| `end`         | 今月の月初    | 終了日 (YYYY-MM-DD)                       |
| `granularity` | `MONTHLY`     | `MONTHLY` or `DAILY`                      |
| `group_by`    | `SERVICE`     | `SERVICE`, `REGION`, `USAGE_TYPE`, `NONE` |

### コストメトリクス

| メトリクス         | 説明                                                   |
| ------------------ | ------------------------------------------------------ |
| Unblended Cost     | 実際の使用料金。RI/SP の割引は購入アカウントにのみ適用 |
| Amortized Cost     | RI/SP の前払い費用を契約期間で按分した料金             |
| Blended Cost       | 組織全体の平均料金率で計算したコスト                   |
| Net Unblended Cost | EDP 等の契約割引適用後の実コスト                       |
| Net Amortized Cost | 契約割引適用後の按分コスト（最も実態に近い）           |

Net 系メトリクスが使えないアカウントでは自動的に基本3メトリクスにフォールバックする。

### キャッシュ・データ保存

Cost Explorer API は 1リクエストあたり $0.01 課金されるため、2層キャッシュと期間 bucket キャッシュで呼び出し回数を最小化している。

#### 料金データのキャッシュ

| レイヤー                | 保存先                 | TTL                                     | キー形式 / 粒度                                            |
| ----------------------- | ---------------------- | --------------------------------------- | ---------------------------------------------------------- |
| サーバー（期間 bucket） | SQLite `data/cache.db` | 当月 bucket は 1週間、過去確定月は 90日 | `account_id + granularity + group_by + period_start/end`   |
| サーバー（旧 exact）    | SQLite `data/cache.db` | 1週間                                   | `cost:{account_id}:{start}:{end}:{granularity}:{group_by}` |
| クライアント            | localStorage           | 1時間                                   | `awscc:cost:{account_id}:{start}:{end}:{granularity}`      |

`DAILY` と `MONTHLY` は AWS 側で集計方法が異なる可能性があるため、相互に合算・変換しない。`DAILY` は日単位、`MONTHLY` は月単位の bucket として個別にキャッシュする。

リクエストの流れ:

1. クライアント localStorage にヒット → そのまま描画（API リクエストなし）
2. localStorage にない → サーバーへリクエスト → SQLite の期間 bucket にヒットした部分は再利用
3. SQLite で不足している bucket だけ AWS Cost Explorer API を呼び出し → SQLite に保存 → レスポンス返却

UI の「Clear Cache」ボタンでサーバー (SQLite) とクライアント (localStorage) の両方を一括クリアできる。

#### SSO アカウント・ロール情報のキャッシュ

SSO の account list / role list も SQLite に 24時間キャッシュする。SSO トークン自体の有効性は `~/.aws/sso/cache/` で先に確認するため、トークン切れをキャッシュで隠さない。

#### ユーザー設定の保存

Config タブの設定はブラウザの localStorage とサーバー側 SQLite の両方に保存される。SQLite 側の設定は `prefetch` からも利用される。

| 設定                     | 保存先                                               | 内容                                |
| ------------------------ | ---------------------------------------------------- | ----------------------------------- |
| デフォルト選択アカウント | localStorage `awscc:config:defaultAccounts` / SQLite | 選択されたアカウントIDの配列 (JSON) |

- 全アカウント選択の場合はキーを保存しない（未設定 = 全選択として扱う）
- Config タブの「Save」で保存、「Reset to All」で削除
- 保存した設定は次回ページ読み込み時に Cost Explorer タブの Account Filter に自動反映される
- 既存ブラウザの localStorage 設定は、ダッシュボード読み込み時に SQLite 側へ自動同期される

### パフォーマンス

- **同時実行数制限**: アカウントを6件ずつ並列フェッチ（AWS API レート制限の回避）
- **プログレスバー**: フェッチ進捗をリアルタイム表示（`12 / 34 accounts`）
- **チャート遅延描画**: `IntersectionObserver` でビューポート外のチャートは `<canvas>` のみ配置し、スクロールで近づいたときに `Chart.js` インスタンスを生成
- **メトリクス切替**: 全5メトリクスを一括取得済みのため、ドロップダウン変更時は再フェッチ不要で即座に再描画
- **診断ログ**: サーバーログに cache hit / miss / expired と Cost Explorer fetch 範囲を出力。ブラウザ console には `[awscc] account cost fetch` と `[awscc] dashboard timing` を出力

## 開発

[mise](https://mise.jdx.dev/) でタスクを管理している。

```bash
mise run dev        # 開発サーバー（ホットリロード）
mise run sso-login  # SSO ログイン（ブラウザ認証）
mise run prefetch-cost -- --granularity BOTH --months 3  # Cost Explorer データを事前取得
mise run prefetch-dashboard-default  # default accounts を対象に 24か月 Monthly + 4か月 Daily を事前取得
mise run lint       # リンター（dprint/ruff/shfmt/shellcheck/yamllint）
mise run format     # フォーマッター（dprint/ruff/shfmt/yamllint）
```

### バックグラウンド事前取得

よく見る期間を先に取得しておくと、ダッシュボード表示時は SQLite cache hit になりやすい。

推奨手順:

1. `mise run serve` で起動し、ブラウザで Config タブを開く
2. Default Account Selection で普段見るアカウントを選び、`Save` を押す
3. `mise run prefetch-cost -- --preset dashboard-default --dry-run` で対象と期間を確認する
4. 手動で一度取得するなら `mise run prefetch-dashboard-default` を実行する
5. 毎日自動取得するなら `mise run prefetch-launchd-install` を実行する

```bash
# Config タブの Default Account Selection を対象にする定期実行向けプリセット
# MONTHLY: 当月を含む直近24か月 / DAILY: 当月を含む直近4か月
mise run prefetch-dashboard-default

# 当月を含む直近3か月を DAILY / MONTHLY 両方で取得
mise run prefetch-cost -- --granularity BOTH --months 3

# 月次だけ直近12か月を取得
mise run prefetch-cost -- --granularity MONTHLY --months 12

# 特定アカウントだけ取得
mise run prefetch-cost -- --accounts 123456789012,210987654321 --granularity DAILY --months 2

# 取得せず対象だけ確認
mise run prefetch-cost -- --preset dashboard-default --dry-run
```

macOS で定期実行する場合は `cron` より `launchd` が安定する。以下で毎日 11:30 と 14:30（Mac のローカルタイムゾーン）のジョブを作成・登録する。

```bash
mise run prefetch-launchd-install

# 時刻を変える（複数指定可）
mise run prefetch-launchd-install -- --time 7:30 --time 13:30

# 登録済み job をすぐ実行する
mise run prefetch-launchd-run

# 状態を見る
mise run prefetch-launchd-status

# 削除する
mise run prefetch-launchd-uninstall
```

ジョブは `mise run prefetch-cost -- --preset dashboard-default` を実行する。SSO トークンが切れている場合、prefetch はログにエラーを出して終了するため、必要に応じて `mise run sso-login` で再ログインする。ログは `data/logs/prefetch-launchd.log` と `data/logs/prefetch-launchd.err` に出力される。

ログを確認する場合:

```bash
mise run prefetch-launchd-logs

# stderr だけ直近分を見る
mise run prefetch-launchd-logs -- --stderr --no-follow
```

## トラブルシューティング

### SSO トークンエラー

```text
SSO トークンが見つからないか有効期限切れです。
```

以下のいずれかでログインし直す:

1. ダッシュボードのヘッダーにある「SSO Login」ボタンをクリック
2. `mise run sso-login` を実行
3. `aws sso login --sso-session <session-name>` を実行

ログイン後、ダッシュボードのリロードだけで復帰する。トークン切れの場合はモーダルが自動で表示される。

### 特定アカウントのコストが取得できない

- そのアカウントに Cost Explorer へのアクセス権を持つロールがない可能性がある
- ロール優先順位: `ReadOnlyCostViewer` > `ReadOnlyAccess` > `ViewOnlyAccess` > `BillingViewAccess` > その他
- Accounts タブの「Show Roles」トグルで各アカウントのロールを確認可能

### Net 系メトリクスが表示されない

Net Unblended / Net Amortized は EDP（Enterprise Discount Program）契約があるアカウントでのみ利用可能。該当しないアカウントでは自動的にフォールバックされる。
