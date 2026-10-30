# company/ — 自社のデータ

| 場所 | 中身 |
|---|---|
| `config.toml` | 会社の設定（設立日・決算月・請求・税・手元資金・目標）。**最初に埋める** |
| `profile.md` | 事業内容・目標・使っているツール |
| `policies.md` | AIが自分でやってよいこと / オーナーの確認が必要なこと |
| `config/account_rules.csv` | 経費の勘定科目を自動で決めるキーワード |
| `finance/` | 売上台帳 `sales.csv`、経費台帳 `expenses.csv`、固定費 `recurring.csv`、請求書 `invoices/` |
| `sales/` | 案件 `pipeline.csv`、見積書 `quotes/`、提案書 `proposals/` |
| `strategy/` | KPI `kpi.csv`、事業計画 |
| `admin/` | 期限 `deadlines-calendar.md`、契約 `contracts.csv`、契約チェックリスト、アカウント管理表 |
| `projects/` | 案件ごとの作業計画・制作物 |
| `templates/` | 契約書・議事録・規程・見積書・提案書・納品書・メールのひな形 |
| `reports/` | 週次・月次レポート、ダッシュボード、カレンダー用ファイル |
| `inbox/` | 受け取った資料の一時置き場（**git に入らない**） |

CSV は直接編集せず、`./solo` コマンド（または AI社員）を通して更新する。形式は `docs/data.md`。
