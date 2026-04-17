# AWS Cost Dashboard

AWS SSO (IAM Identity Center) 配下の複数アカウントのコストデータを横断的に可視化するローカルダッシュボード。

## 機能

- **マルチアカウント対応**: SSO 配下の全アカウントを自動検出・一覧表示
- **コスト可視化**:
  - アカウント別トータルコストの折れ線グラフ（Overview）
  - アカウントごとのサービス別積み上げ棒グラフ
  - コスト集計テーブル（シェア率付き）
- **5種のコストメトリクス**: Unblended / Amortized / Blended / Net Unblended / Net Amortized を切替可能
- **柔軟なフィルタリング**: 期間（年月セレクタ）、粒度（Monthly/Daily）、アカウント選択
- **2層キャッシュ**: サーバー側 SQLite (24h TTL) + クライアント側 localStorage (1h TTL) で Cost Explorer API の課金を最小化
- **パフォーマンス最適化**: 同時実行数制限付きフェッチ、IntersectionObserver によるチャート遅延描画

## 前提条件

- [mise](https://mise.jdx.dev/) — Python 3.12 と uv を自動管理（`mise.toml` で定義済み）
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
│   └── cache.py       # SQLite キャッシュ（24h TTL）
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
                    └─ SQLite cache (24h TTL) ─ hit → respond
                    └─ miss → Cost Explorer API
                                └─ SSO get_role_credentials
                                     └─ ~/.aws/sso/cache/ (access token)
                                          └─ ~/.aws/config (sso-session 設定)
```

### API エンドポイント

| Method | Path                     | 説明                                       |
| ------ | ------------------------ | ------------------------------------------ |
| GET    | `/`                      | ダッシュボード HTML                        |
| GET    | `/api/accounts`          | 全アカウント一覧（高速版）                 |
| GET    | `/api/accounts/detail`   | 全アカウント＋ロール情報                   |
| GET    | `/api/cost`              | 全アカウントのコスト一括取得               |
| GET    | `/api/cost/{account_id}` | 単一アカウントのコスト取得                 |
| DELETE | `/api/cache`             | サーバーキャッシュ全削除                   |
| GET    | `/api/sso/sessions`      | `~/.aws/config` の sso-session 一覧        |
| POST   | `/api/sso/login`         | SSO ログイン開始（認証 URL を返す）        |
| POST   | `/api/sso/login/poll`    | 認証完了をポーリング（トークン取得・保存） |

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

Cost Explorer API は 1リクエストあたり $0.01 課金されるため、2層キャッシュで呼び出し回数を最小化している。

#### 料金データのキャッシュ

| レイヤー     | 保存先                 | TTL    | キー形式                                                   |
| ------------ | ---------------------- | ------ | ---------------------------------------------------------- |
| サーバー     | SQLite `data/cache.db` | 24時間 | `cost:{account_id}:{start}:{end}:{granularity}:{group_by}` |
| クライアント | localStorage           | 1時間  | `awscc:cost:{account_id}:{start}:{end}:{granularity}`      |

リクエストの流れ:

1. クライアント localStorage にヒット → そのまま描画（API リクエストなし）
2. localStorage にない → サーバーへリクエスト → SQLite にヒット → レスポンス返却（AWS API リクエストなし）
3. SQLite にもない → AWS Cost Explorer API を呼び出し → SQLite に保存 → レスポンス返却

UI の「Clear Cache」ボタンでサーバー (SQLite) とクライアント (localStorage) の両方を一括クリアできる。

#### ユーザー設定の保存

Config タブの設定もブラウザの localStorage に保存される。

| 設定                     | localStorage キー              | 内容                                |
| ------------------------ | ------------------------------ | ----------------------------------- |
| デフォルト選択アカウント | `awscc:config:defaultAccounts` | 選択されたアカウントIDの配列 (JSON) |

- 全アカウント選択の場合はキーを保存しない（未設定 = 全選択として扱う）
- Config タブの「Save」で保存、「Reset to All」で削除
- 保存した設定は次回ページ読み込み時に Cost Explorer タブの Account Filter に自動反映される
- サーバー側には保存されないため、ブラウザごとに独立した設定となる

### パフォーマンス

- **同時実行数制限**: アカウントを6件ずつ並列フェッチ（AWS API レート制限の回避）
- **プログレスバー**: フェッチ進捗をリアルタイム表示（`12 / 34 accounts`）
- **チャート遅延描画**: `IntersectionObserver` でビューポート外のチャートは `<canvas>` のみ配置し、スクロールで近づいたときに `Chart.js` インスタンスを生成
- **メトリクス切替**: 全5メトリクスを一括取得済みのため、ドロップダウン変更時は再フェッチ不要で即座に再描画

## 開発

[mise](https://mise.jdx.dev/) でタスクを管理している。

```bash
mise run dev        # 開発サーバー（ホットリロード）
mise run sso-login  # SSO ログイン（ブラウザ認証）
mise run lint       # リンター
mise run format     # フォーマッター
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
