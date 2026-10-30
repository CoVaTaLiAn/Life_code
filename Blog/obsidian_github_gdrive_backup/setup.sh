#!/bin/bash
# 初回セットアップ: Vault 用 git リポジトリ（Vault 外に .git）を作り、GitHub に初回 push し、
# launchd に登録する。
set -euo pipefail

CONF="${OBSIDIAN_BACKUP_CONF:-$HOME/.config/obsidian-backup.conf}"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$CONF"
: "${VAULT:?}" "${GITHUB_REMOTE:?GITHUB_REMOTE を設定してください}"
: "${GIT_DIR_PATH:=$HOME/.obsidian-vault.git}"
: "${GIT_BRANCH:=main}"
: "${INTERVAL_SECONDS:=1800}"

g() { git --git-dir="$GIT_DIR_PATH" --work-tree="$VAULT" "$@"; }

if [ ! -d "$GIT_DIR_PATH" ]; then
  git init -q --bare "$GIT_DIR_PATH"
  git --git-dir="$GIT_DIR_PATH" config core.bare false
  git --git-dir="$GIT_DIR_PATH" config core.worktree "$VAULT"
  g symbolic-ref HEAD "refs/heads/$GIT_BRANCH"
  g remote add origin "$GITHUB_REMOTE"
  echo "git リポジトリ作成: $GIT_DIR_PATH"
fi

# .gitignore（Vault 直下。Obsidian の端末ごとの状態ファイルを除外）
if [ ! -f "$VAULT/.gitignore" ]; then
  cp "$HERE/vault.gitignore" "$VAULT/.gitignore"
  echo ".gitignore を Vault に配置"
fi

g add -A
g diff --cached --quiet || g commit -q -m "initial vault import"
g push -u origin "$GIT_BRANCH"

# スクリプトと launchd 登録
mkdir -p "$HOME/bin" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cp "$HERE/obsidian-backup.sh" "$HOME/bin/obsidian-backup.sh"
chmod +x "$HOME/bin/obsidian-backup.sh"

PLIST="$HOME/Library/LaunchAgents/com.obsidian.backup.plist"
sed -e "s#__HOME__#$HOME#g" -e "s#__INTERVAL__#$INTERVAL_SECONDS#g" \
  "$HERE/com.obsidian.backup.plist" > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "launchd 登録完了（${INTERVAL_SECONDS}秒ごと）: $PLIST"
