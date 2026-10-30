---
name: monthly-close
description: 1人会社の月次締め。前月の記帳もれ確認、未請求・未入金の洗い出し、月次の損益、資金繰りの見通し、KPIの更新、税理士に渡す資料をまとめる。「月次締め」「先月の数字をまとめて」「税理士に送る資料を準備して」と頼まれたとき、または毎月初めの定期実行で使う。
---

# 月次締め

経理部（accounting）の手順。対象は前月1か月分（YYYY-MM）。

## 手順

1. **記帳もれの確認**
   - Gmail で前月の「請求書」「領収書」「ご利用明細」「receipt」「invoice」を検索する
   - `company/finance/expenses.csv` にない取引を `./solo expense add` で記帳する
   - カード・銀行の明細CSVが `company/inbox/` にあれば `./solo expense import ... --dry-run` で確認してから取り込む
2. **未請求の確認**：`company/sales/pipeline.csv` で前月に「受注」になった案件と、`./solo invoice list` を突き合わせ、請求していないものをオーナーに知らせる
3. **未入金**：`./solo invoice list --unpaid`。期限超過があれば催促メールの下書きを作る（送信はしない）
4. **点検**：`./solo check`。エラーは直し、「要確認」の科目は推測と理由をつけて一覧にする
5. **締めのレポート**：`./solo report monthly YYYY-MM --save --kpi`
6. **資金繰り**：`./solo cashflow --months 6`。手元資金が固定費の6か月分を下回る月があれば、対策（入金の前倒し、支出の見直し、融資の相談）を書く
7. **税理士への資料**：`company/reports/YYYY-MM_for-accountant.md` に、台帳の場所、証憑の一覧、要確認の取引と質問をまとめる
8. `./solo dashboard` を更新し、オーナーに結論（売上・利益・手元資金を1行ずつ）と、確認してほしいことを報告する

金額は概算と明記し、お金の移動はしない。
