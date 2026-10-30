#!/bin/bash
# Obsidian Vault を
#   1) GitHub（private リポジトリ）へ定期 commit & push
#   2) Google Drive（Google Drive for desktop のフォルダ）へミラー + 日次スナップショット
# するスクリプト。launchd から定期実行する想定。
#
# 設定は ~/.config/obsidian-backup.conf に書く（config.example.conf を参照）。
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

CONF="${OBSIDIAN_BACKUP_CONF:-$HOME/.config/obsidian-backup.conf}"
if [ ! -f "$CONF" ]; then
  echo "ERROR: 設定ファイルがありません: $CONF" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$CONF"

: "${VAULT:?VAULT を設定してください}"
: "${GIT_DIR_PATH:=$HOME/.obsidian-vault.git}"
: "${GIT_BRANCH:=main}"
: "${GDRIVE_DIR:?GDRIVE_DIR を設定してください}"
: "${SNAPSHOT_KEEP_DAYS:=30}"
: "${ENABLE_GITHUB:=1}"
: "${ENABLE_GDRIVE:=1}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# 多重起動防止
LOCK="${TMPDIR:-/tmp}/obsidian-backup.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  log "別の実行が進行中のためスキップ"
  exit 0
fi
trap 'rmdir "$LOCK"' EXIT

# 安全チェック: Vault が空（iCloud 未ダウンロード等）なら何もしない
if [ ! -d "$VAULT" ]; then
  echo "ERROR: Vault が見つかりません: $VAULT" >&2
  exit 1
fi
if ! find "$VAULT" -type f -name '*.md' -print -quit | grep -q .; then
  echo "ERROR: Markdown が見つからないため安全停止（GitHub/Drive の削除事故防止）" >&2
  exit 1
fi

status=0

# --diff: GitHub（LifeLog）との差分を表示するだけで何も変更しない
if [ "${1:-}" = "--diff" ]; then
  g() { git --git-dir="$GIT_DIR_PATH" --work-tree="$VAULT" "$@"; }
  g fetch -q origin "$GIT_BRANCH"
  tmpidx=$(mktemp); trap 'rm -f "$tmpidx"; rmdir "$LOCK"' EXIT
  export GIT_INDEX_FILE="$tmpidx"
  g read-tree "origin/$GIT_BRANCH"
  g add -A
  echo "=== Obsidian と GitHub(origin/$GIT_BRANCH) の差分（A=Obsidianにだけある / D=GitHubにだけある / M=内容が違う）==="
  g -c core.quotepath=false diff --cached --name-status "origin/$GIT_BRANCH"
  exit 0
fi

# ---------- 1) GitHub ----------
if [ "$ENABLE_GITHUB" = 1 ]; then
  # .git を iCloud 内に置くと同期で壊れやすいので、Vault の外に置く
  g() { git --git-dir="$GIT_DIR_PATH" --work-tree="$VAULT" "$@"; }
  if [ ! -d "$GIT_DIR_PATH" ]; then
    echo "ERROR: $GIT_DIR_PATH がありません。先に setup.sh を実行してください" >&2
    status=1
  else
    g add -A
    # .gitignore 対象なのに追跡されているファイル（.DS_Store 等）を GitHub から外す
    g ls-files -ci --exclude-standard -z | xargs -0 -r git --git-dir="$GIT_DIR_PATH" --work-tree="$VAULT" rm -q --cached --
    if g diff --cached --quiet; then
      log "GitHub: 変更なし"
    else
      changed=$(g diff --cached --name-only | wc -l | tr -d ' ')
      g commit -q -m "vault backup: $(date '+%Y-%m-%d %H:%M') (${changed} files)"
      log "GitHub: commit (${changed} files)"
    fi
    if ! g push -q origin "$GIT_BRANCH" 2>/dev/null; then
      # 他所で GitHub が更新されていた場合: 履歴は残しつつ内容は Obsidian を正とする
      g fetch -q origin "$GIT_BRANCH" &&
        g merge -q -s ours --no-edit -m "merge origin (keep Obsidian content)" "origin/$GIT_BRANCH" || true
    fi
    if g push -q origin "$GIT_BRANCH" 2>&1; then
      log "GitHub: push 完了"
    else
      echo "ERROR: GitHub への push に失敗（ネットワーク/認証を確認）" >&2
      status=1
    fi
  fi
fi

# ---------- 2) Google Drive ----------
if [ "$ENABLE_GDRIVE" = 1 ]; then
  # Drive 本体（親フォルダ）があればバックアップ先は自動作成
  if [ ! -d "$(dirname "$GDRIVE_DIR")" ]; then
    echo "ERROR: Google Drive フォルダが見つかりません: $(dirname "$GDRIVE_DIR")（Google Drive for desktop が起動しているか確認）" >&2
    status=1
  else
    MIRROR="$GDRIVE_DIR/mirror"
    SNAPDIR="$GDRIVE_DIR/snapshots"
    mkdir -p "$MIRROR" "$SNAPDIR"

    # ミラー（最新状態。添付画像なども含め Vault 全体）
    rsync -a --delete \
      --exclude='.DS_Store' \
      --exclude='.obsidian/workspace*.json' \
      --exclude='.trash/' \
      "$VAULT/" "$MIRROR/"
    log "Google Drive: ミラー更新"

    # 日次スナップショット（1日1回だけ作る。ミラーを誤って消しても戻せるように）
    today=$(date '+%Y-%m-%d')
    snap="$SNAPDIR/vault_${today}.tar.gz"
    if [ ! -f "$snap" ]; then
      tar -czf "$snap.tmp" -C "$VAULT" \
        --exclude='.DS_Store' --exclude='.trash' .
      mv "$snap.tmp" "$snap"
      log "Google Drive: スナップショット作成 $(basename "$snap")"
      # 古いスナップショットを削除
      find "$SNAPDIR" -name 'vault_*.tar.gz' -type f -mtime +"$SNAPSHOT_KEEP_DAYS" -print -delete \
        | sed 's/^/  削除: /'
    fi
  fi
fi

exit "$status"
