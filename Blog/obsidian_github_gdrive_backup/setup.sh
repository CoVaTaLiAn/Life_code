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

# GitHub に既存の履歴があれば引き継ぐ（Vault のファイルには触らない）
if g fetch -q origin "$GIT_BRANCH" 2>/dev/null && ! g rev-parse -q --verify HEAD >/dev/null; then
  g update-ref "refs/heads/$GIT_BRANCH" "origin/$GIT_BRANCH"
  g reset -q
  g branch -q --set-upstream-to="origin/$GIT_BRANCH" "$GIT_BRANCH"
  echo "GitHub の既存履歴を引き継ぎました"
  if [ "${SKIP_CONFIRM:-0}" != 1 ]; then
    echo "=== Obsidian と GitHub の差分（A=Obsidianにだけある / D=GitHubにだけある→削除される / M=Obsidianの内容で上書き）==="
    g add -A
    g -c core.quotepath=false diff --cached --name-status HEAD
    g reset -q
    read -r -p "Obsidian の内容で GitHub を更新します。よろしいですか？ [y/N] " ans
    [ "$ans" = y ] || { echo "中止しました"; exit 1; }
  fi
fi

# .gitignore（Vault 直下。Obsidian の端末ごとの状態ファイルを除外）
if [ ! -f "$VAULT/.gitignore" ]; then
  cp "$HERE/vault.gitignore" "$VAULT/.gitignore"
  echo ".gitignore を Vault に配置"
fi

g add -A
g ls-files -ci --exclude-standard -z | xargs -0 -r git --git-dir="$GIT_DIR_PATH" --work-tree="$VAULT" rm -q --cached --
g diff --cached --quiet || g commit -q -m "Sync with Obsidian vault (Obsidian is source of truth)"
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
