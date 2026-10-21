#!/bin/bash
# 公開用サンプル: 各自の実パスへ置き換えて使用する
set -euo pipefail

SOURCE='/REPLACE_WITH_YOUR_ICLOUD_OBSIDIAN_VAULT'
DEST='/REPLACE_WITH_YOUR_GOOGLE_DRIVE_OBSIDIAN_GEMINI'

if [ ! -d "$SOURCE" ] || [ ! -d "$DEST" ]; then
  echo 'ERROR: 同期フォルダが見つかりません' >&2
  exit 1
fi

if ! /usr/bin/find "$SOURCE" -type f -name '*.md' -print -quit | /usr/bin/grep -q .; then
  echo 'ERROR: Markdownが見つからないため安全停止' >&2
  exit 1
fi

OPTIONS=(-avm --delete --delete-excluded --itemize-changes)
if [ "${DRY_RUN:-0}" = '1' ]; then
  OPTIONS+=(--dry-run)
fi

/usr/bin/rsync "${OPTIONS[@]}" \
  --include='*/' \
  --include='*.md' \
  --exclude='*' \
  "$SOURCE/" "$DEST/"
