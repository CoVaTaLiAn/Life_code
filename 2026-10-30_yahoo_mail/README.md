# Yahoo!メール 緊急・重要なもの以外を既読にする

Yahoo!メール（Yahoo! JAPAN）の受信箱で、緊急・重要なもの以外の未読メールを既読にする Python スクリプト。フォルダへの振り分けはしない。

## ルールを変える（コードは触らなくてよい）

**`rules.txt` を書き換えるだけ。** 次の実行から反映される。Mac なら次で開ける。

```bash
open -e ~/Documents/Life_code/2026-10-30_yahoo_mail/rules.txt
```

| 見出し | 意味 |
|---|---|
| `[必ず既読]` | 件名か差出人に含まれていれば、必ず既読（例：路線情報、M3ベネフィット） |
| `[必ず残す]` | 件名か差出人に含まれていれば、必ず未読のまま |
| `[Jevに伝えること]` | Jev が「未読で残すべきか」を判断するときの説明 |
| `[緊急キーワード]` | Jev が使えないときだけ、これを件名に含むものを残す |
| `[数値]` | 「残す確率」（上げるほど既読が増える）と、1回に Jev に聞く上限 |

## 判定の順番

1. `[必ず既読]` → 既読、`[必ず残す]` → 未読のまま
2. Jev（TypeSafe AI）に「未読で残すべき確率」を聞き、`残す確率` 以上なら未読のまま、それ以外は既読
3. Jev のキーがない・エラー・上限超えのときは `[緊急キーワード]` で判定

一度「残す」と決めたメールは `~/.yahoo-mail-sorter-state.json` に記録し、次回は Jev に聞き直さない（費用を抑えるため）。

## 使い方

事前に Yahoo!メールの「設定 → IMAP/POP/SMTPアクセス」で IMAP を「利用する」にし、「Yahoo! JAPAN公式サービス以外からのアクセスも有効にする」をオンにする。

```bash
python3 src/sort_yahoo_mail.py            # お試し（件数と、未読のまま残すメールの件名・理由を表示）
python3 src/sort_yahoo_mail.py --run      # 実際に既読にする
python3 src/sort_yahoo_mail.py --restore-folders   # 以前の版の振り分けフォルダを受信箱に戻して消す
```

Yahoo の ID とパスワードは、環境変数 `YAHOO_USER`・`YAHOO_PASS` → macOS キーチェーン → 実行時の入力、の順に探す。Jev の API キーは、環境変数 `TYPESAFE_API_KEY` → キーチェーン（サービス名 `typesafe-api-key`）の順に探す。

Jev のキーだけ後から保存するとき:

```bash
security add-generic-password -U -s typesafe-api-key -a jev -T /usr/bin/security -w
```

## Mac で毎日自動実行する

```bash
bash src/setup_mac.sh
```

ID・パスワード（と、任意で Jev のキー）をキーチェーンに保存し、毎朝7時に `--run` で動く設定（launchd）を入れ、その場で1回実行する。記録は `~/Library/Logs/yahoo-mail-sorter.log`。止めるときは `launchctl unload ~/Library/LaunchAgents/com.life-code.yahoo-mail-sorter.plist`。

## ファイル

| ファイル | 内容 |
|---|---|
| `rules.txt` | 既読ルール（自分で書き換える） |
| `src/sort_yahoo_mail.py` | 本体（標準ライブラリだけで動く） |
| `src/setup_mac.sh` | Mac で毎日自動実行するための設定 |
