# 使い方（コマンド一覧）

ふだんは Claude に話しかければ、AI社員がこのコマンドを使って作業します。自分で動かすときの一覧です。

必要なもの：Python 3.11 以上（追加のインストールは不要）。

```bash
./solo --help              # 全体
./solo invoice new --help  # 各コマンドの詳しい使い方
```

共通のオプション：
- `--root フォルダ`：データの場所（既定は `company/`）。サンプルは `examples/demo`
- `--today YYYY-MM-DD`：今日の日付を変えて試算する

## 請求と入金

```bash
# 請求書を作る（まず --dry-run で中身を確認）
./solo invoice new --client "株式会社アルファ" --subject "11月 業務支援" \
  --item "業務支援（11月）:1:400000" --item "交通費:1:3000" --dry-run

# 軽減税率（8%）の品目は最後に :8
./solo invoice new --client "ベータ商事" --item "撮影用お菓子:2:1500:8" --item "撮影:1:50000"

# 入金を記録（振込手数料が引かれていたら --amount に実額）
./solo invoice paid INV-202611-001 --date 2026-12-28 --amount 439340

# 一覧 / 未入金だけ
./solo invoice list
./solo invoice list --unpaid
```

- 請求番号は `INV-年月-連番` で自動
- 消費税は税率ごとに1回だけ端数を切り捨て（インボイス制度のルール）
- 支払期限は `config.toml` の `due_rule`（翌月末 / N日後）
- `company/finance/invoices/` に `.md` と `.html` ができる。HTML をブラウザで開いて「印刷 → PDFに保存」で PDF になる

## 経費

```bash
# 1件記帳（勘定科目は支払先・内容から自動判定。--account で指定も可）
./solo expense add --date 2026-11-05 --payee "AWS" --amount 1200 --method 法人カード --voucher "メール領収書"

# カード・銀行の明細CSVを取り込む（列名はCSVの1行目に合わせる）
./solo expense import company/inbox/card_202611.csv \
  --date-col 利用日 --payee-col 利用店名 --amount-col 利用金額 --method 法人カード --dry-run
```

- 銀行のCSVは文字コードが Shift_JIS のことが多い → `--encoding cp932`
- 同じ日付・支払先・金額の行はとばす（二重取り込みの防止）。マイナス（返金）はとばす
- 自動判定のルールは `company/config/account_rules.csv`（キーワード → 勘定科目）。よく使う支払先を足すと賢くなる
- 判定できなかったものは「要確認」になる

## 案件

```bash
./solo deal "アルファ 業務支援" --client 株式会社アルファ --stage 提案 --amount 400000 --prob 60 \
  --next "見積の回答を確認" --next-date 2026-11-10
./solo deals            # 段階ごとの件数・金額
./solo deals --stale    # 次の行動日が過ぎた案件
```

段階：見込 → 接触 → 商談 → 提案 → 受注 / 失注

## レポート

```bash
./solo report weekly --save              # 週次（今週やること・数字・案件・期限）
./solo report monthly 2026-11 --save --kpi   # 月次（損益・未入金・資金繰り・要確認）
./solo cashflow --months 6               # 資金繰り
./solo dashboard                         # company/reports/dashboard.html
```

## 期限

```bash
./solo deadlines                                 # 今日から12か月
./solo deadlines --from 2026-11-01 --to 2027-12-31 --save   # admin/deadlines-calendar.md に保存
./solo deadlines --ics company/reports/deadlines.ics       # カレンダー用ファイル
```

`.ics` は Googleカレンダーの「設定 → インポートとエクスポート → インポート」で取り込めます（7日前と1日前に通知）。

## 試算

```bash
# 単価30万円、外注3割、1件40時間、月20万円の利益を残したい
./solo breakeven --price 300000 --variable-rate 0.3 --hours 40 --profit 200000
```

固定費は `company/finance/recurring.csv` の合計（年払いは12で割る）。`--fixed` で上書きできます。

## 点検

```bash
./solo check
```

日付・金額の形式、税込と税抜＋税の不一致、請求番号の重複、二重記帳の疑い、勘定科目・証憑の抜け、10万円以上の物品などを点検します。エラーがあると終了コード1。
