# Obsidian（iCloud）→ Google Drive 自動同期

Mac の iCloud にある Obsidian の保管庫から、Markdown ファイルだけを Google Drive のフォルダへ5分ごとにコピーする仕組み。
Google Drive 側のコピーを Gemini などから読めるようにするのが目的。

## しくみ

- `rsync` で `*.md` だけを同期する（保管庫で消したファイルは Drive 側でも消える）
- 同期元に Markdown が1つもないとき（iCloud が未ダウンロードなど）は、Drive 側を消さないよう安全停止する
- macOS の `launchd` で5分ごとに実行する

## 使い方

1. `examples/obsidian-sync.example.sh` を `~/bin/obsidian-sync.sh` にコピーし、`SOURCE`（保管庫）と `DEST`（Drive のフォルダ）を自分のパスに書き換える
2. お試し：`DRY_RUN=1 bash ~/bin/obsidian-sync.sh`（何が同期されるかだけ表示）
3. `examples/com.obsidian.gdrive.example.plist` の `USERNAME` を自分のユーザー名に書き換え、`~/Library/LaunchAgents/com.obsidian.gdrive.plist` として置く
4. 登録：`launchctl load ~/Library/LaunchAgents/com.obsidian.gdrive.plist`

ログは `~/Library/Logs/obsidian-sync.log`（エラーは `obsidian-sync-error.log`）。

## ファイル

| ファイル | 内容 |
|---|---|
| `examples/obsidian-sync.example.sh` | 同期スクリプトの見本 |
| `examples/com.obsidian.gdrive.example.plist` | 5分ごとに実行する launchd 設定の見本 |
