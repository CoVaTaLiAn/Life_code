# Yahoo!メール 緊急以外を既読にする

Yahoo!メール（Yahoo! JAPAN）の受信箱で、緊急なもの以外の未読メールを既読にする Python スクリプト。フォルダへの振り分けはしない。

「緊急」は、件名に次のような語を含むメール。`src/sort_yahoo_mail.py` 冒頭の `URGENT_SUBJECT`・`URGENT_FROM` で変えられる。

- 緊急・至急・重要・警告
- 認証・確認コード・ワンタイム・パスワード・本人確認・ログイン・セキュリティ
- 不正・不審・ロック・停止
- 支払い期限・未払い・延滞・督促・期限切れ

例外として、`ALWAYS_READ` に当たるメール（Yahoo!路線情報、M3ベネフィット）は緊急っぽい件名でも既読にする。

## 使い方

事前に Yahoo!メールの「設定 → IMAP/POP/SMTPアクセス」で IMAP を「利用する」にし、「Yahoo! JAPAN公式サービス以外からのアクセスも有効にする」をオンにする。

```bash
python3 src/sort_yahoo_mail.py            # お試し（件数と、未読のまま残すメールの件名を表示）
python3 src/sort_yahoo_mail.py --run      # 実際に既読にする
```

以前の版で作った振り分けフォルダ（要確認・買い物・会員登録・メルマガ）を元に戻すときは:

```bash
python3 src/sort_yahoo_mail.py --restore-folders
```

フォルダのメールを受信箱に戻し、空になったフォルダを消す。

ID とパスワードは、環境変数 `YAHOO_USER`・`YAHOO_PASS` → macOS キーチェーン → 実行時の入力、の順に探す。

## Mac で毎日自動実行する

```bash
bash src/setup_mac.sh
```

ID とパスワードをキーチェーンに保存し、毎朝7時に `--run` で動く設定（launchd）を入れ、その場で1回実行する。記録は `~/Library/Logs/yahoo-mail-sorter.log`。止めるときは `launchctl unload ~/Library/LaunchAgents/com.life-code.yahoo-mail-sorter.plist`。

## ファイル

| ファイル | 内容 |
|---|---|
| `src/sort_yahoo_mail.py` | 本体（標準ライブラリだけで動く） |
| `src/setup_mac.sh` | Mac で毎日自動実行するための設定 |
