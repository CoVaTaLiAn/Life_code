#!/bin/bash
# Yahoo!メールの「緊急以外を既読にする」処理を、Mac で毎日自動実行するための設定。
# 使い方: bash yahoo_mail/setup_mac.sh
set -e

SERVICE="yahoo-mail-sorter"
LABEL="com.life-code.yahoo-mail-sorter"
DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$DIR/sort_yahoo_mail.py"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/yahoo-mail-sorter.log"
PYTHON="$(python3 -c 'import sys; print(sys.executable)')"

echo "== 1/3 ログイン情報をキーチェーンに保存 =="
read -r -p "Yahoo! JAPAN ID またはメールアドレス: " YID
security delete-generic-password -s "$SERVICE" >/dev/null 2>&1 || true
echo "パスワードを2回聞かれます（入力しても表示されません）"
security add-generic-password -s "$SERVICE" -a "$YID" -T /usr/bin/security -w

read -r -p "Jev（TypeSafe AI）の API キーも保存しますか？ [y/N]: " ANS
if [ "$ANS" = "y" ] || [ "$ANS" = "Y" ]; then
  security delete-generic-password -s "typesafe-api-key" >/dev/null 2>&1 || true
  echo "API キーを2回聞かれます（入力しても表示されません）"
  security add-generic-password -s "typesafe-api-key" -a jev -T /usr/bin/security -w
fi

echo "== 2/3 毎日 朝7時に自動実行する設定 =="
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$SCRIPT</string>
    <string>--run</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "== 3/3 今すぐ1回実行する =="
"$PYTHON" "$SCRIPT" --run </dev/null

echo
echo "完了しました。これから毎朝7時に、緊急・重要なもの以外を自動で既読にします。"
echo "記録: $LOG"
echo "止めたいとき: launchctl unload $PLIST"
