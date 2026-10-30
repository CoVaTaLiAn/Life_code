# 台帳の形式

すべて UTF-8 の CSV（1行目が列名）。Excel や Googleスプレッドシートでも開けます。
列の定義は `tools/solo/store.py` の `SCHEMAS` が正です。

## company/config.toml

| 区分 | 項目 | 意味 |
|---|---|---|
| company | name, type, representative, postal_code, address, email, phone | 会社情報（請求書に載る） |
| company | founded | 設立日 YYYY-MM-DD |
| company | fiscal_year_end_month | 決算月（1〜12） |
| company | officer_term_years | 役員の任期（株式会社） |
| invoice | registration_number | インボイス登録番号（T＋13桁） |
| invoice | default_tax_rate | 既定の税率（10） |
| invoice | due_rule | `next_month_end`（翌月末）または `days:30` |
| invoice | bank, note | 振込先、備考 |
| tax | consumption_taxable | 消費税の課税事業者か |
| tax | withholding_special | 源泉所得税の納期の特例を受けるか |
| cash | balance, as_of | 手元資金とその基準日 |
| cash | warn_months | 固定費の何か月分を下回ったら警告するか |
| goal | monthly_sales, monthly_profit | 月の目標 |

## finance/sales.csv（売上台帳）

| 列 | 例 | メモ |
|---|---|---|
| 請求番号 | INV-202611-001 | `./solo invoice new` が採番 |
| 請求日 | 2026-11-30 | 売上はこの日の月に計上（概算） |
| 取引先 | 株式会社アルファ | |
| 内容 | 11月 業務支援 | |
| 税抜金額 / 消費税 / 税込金額 | 400000 / 40000 / 440000 | 税抜＋消費税＝税込 |
| 入金予定日 | 2026-12-31 | |
| 入金日 | 2026-12-28 | 空なら未入金 |
| 備考 | | 入金額の差額などが自動で入る |

## finance/expenses.csv（経費台帳）

| 列 | 例 |
|---|---|
| 日付 | 2026-11-05 |
| 支払先 | AWS |
| 内容 | サーバー代 |
| 勘定科目 | 通信費（不明なら「要確認」） |
| 税込金額 | 1200 |
| 消費税 | 課税事業者なら概算。免税なら空 |
| 支払方法 | 法人カード |
| 証憑 | 領収書のファイル名・保管場所（なければ「証憑なし」） |
| 備考 | |

## finance/recurring.csv（固定費）

| 列 | 例 | メモ |
|---|---|---|
| 名前 | 役員報酬 | |
| 金額 | 300000 | 0 の行は無視 |
| 頻度 | monthly / yearly | |
| 支払日 | 25 | 31 と書くと月末 |
| 支払月 | 12 | yearly のときだけ |
| 開始 / 終了 | 2026-11-01 / | 空なら無期限 |

## sales/pipeline.csv（案件）

案件名, 相手先, 担当者, 段階（見込/接触/商談/提案/受注/失注）, 見込金額, 受注確度(%), 次の行動, 次の行動日, 最終更新, 備考

## admin/contracts.csv（契約）

相手先, 契約名, 締結日, 開始日, 終了日, 自動更新, 解約予告期限（日付で書くと週次レポートで知らせる）, 保管場所, 備考

## strategy/kpi.csv（KPI）

月, 売上, 経費, 利益, 新規商談数, 受注数, 手元資金, 備考（`./solo report monthly --kpi` で自動更新）

## config/account_rules.csv（勘定科目の自動判定）

キーワード, 勘定科目。支払先＋内容にキーワードが含まれると、その科目にする（大文字小文字は区別しない、長いキーワードが優先）。
