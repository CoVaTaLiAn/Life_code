# Yahoo!メール 自動振り分け

Yahoo!メール（Yahoo! JAPAN）の受信箱を、件名と差出人でフォルダに振り分ける Python スクリプト。

| フォルダ | 振り分ける例 |
|---|---|
| 要確認 | 認証・確認コード・ログイン・本人確認 |
| 買い物 | 注文・発送・領収書、Amazon・楽天・メルカリなど |
| 会員登録 | 登録完了・ようこそ |
| メルマガ | キャンペーン・セール・クーポン、newsletter・noreply など |

どれにも当たらないメールは受信箱に残る。ルールは `src/sort_yahoo_mail.py` 冒頭の `RULES` で変えられる（上から順に判定）。

## 使い方

事前に Yahoo!メールの「設定 → IMAP/POP/SMTPアクセス」で「Yahoo! JAPAN公式サービス以外からのアクセスも有効にする」をオンにする。

```bash
python3 src/sort_yahoo_mail.py
```

お試し（何も動かさず、振り分け結果の件数だけ表示）。

```bash
python3 src/sort_yahoo_mail.py --run
```

実際に振り分ける。`--delete-old 90` を足すと、振り分け後にメルマガフォルダの90日より古いメールを削除する。

ID とパスワードは実行時に聞かれる。環境変数 `YAHOO_USER`・`YAHOO_PASS` に入れておけば聞かれない。

## ファイル

| ファイル | 内容 |
|---|---|
| `src/sort_yahoo_mail.py` | 振り分けスクリプト（標準ライブラリだけで動く） |
