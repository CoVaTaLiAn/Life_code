# Obsidian → GitHub ＋ Google Drive 自動バックアップ（macOS）

30分ごと（変更可）に次の2つを自動で行います。

| 先 | 内容 |
|---|---|
| **GitHub**（private リポジトリ） | 変更があれば自動 commit & push。履歴で過去の版に戻せる |
| **Google Drive**（kohei.kobayashi818@gmail.com） | `ObsidianBackup/mirror/` に最新状態をミラー ＋ `snapshots/` に1日1回 `vault_YYYY-MM-DD.tar.gz` を保存（30日保持） |

安全装置：Vault に `.md` が1つも無い（iCloud 未ダウンロード等）ときは何もせず停止します。
`.git` は iCloud 内に置くと壊れやすいので、Vault の外（`~/.obsidian-vault.git`）に置きます。

## ファイル

- `obsidian-backup.sh` … 本体（launchd から定期実行）
- `setup.sh` … 初回セットアップ（git 初期化・初回 push・launchd 登録）
- `config.example.conf` … 設定ファイルの見本
- `vault.gitignore` … Vault に置く `.gitignore`
- `com.obsidian.backup.plist` … launchd 定義のテンプレート

## セットアップ手順

### 1. 準備
1. GitHub で **private** リポジトリを作る（例: `CoVaTaLiAn/obsidian-vault`）。ノートは個人情報なので必ず private に。
2. Mac から GitHub に SSH で push できるようにしておく（`ssh -T git@github.com` で確認）。
3. [Google Drive for desktop](https://www.google.com/drive/download/) を入れて kohei.kobayashi818@gmail.com でログイン。
   Finder に `~/Library/CloudStorage/GoogleDrive-kohei.kobayashi818@gmail.com/マイドライブ` が出ればOK。

### 2. 設定
```bash
mkdir -p ~/.config
```
```bash
cp config.example.conf ~/.config/obsidian-backup.conf
```
```bash
open -e ~/.config/obsidian-backup.conf
```
`VAULT`（Vault の場所）、`GITHUB_REMOTE`、`GDRIVE_DIR` を自分の環境に合わせて書き換えます。

### 3. 実行
```bash
bash setup.sh
```
初回 push と launchd 登録まで行います。以後は自動です。

### 4. 権限（重要）
iCloud フォルダを launchd から読むため、**システム設定 → プライバシーとセキュリティ → フルディスクアクセス** に `/bin/bash` を追加してください（「+」→ ⌘⇧G で `/bin/bash`）。

## 確認・操作

```bash
tail -f ~/Library/Logs/obsidian-backup.log ~/Library/Logs/obsidian-backup-error.log
```
```bash
bash ~/bin/obsidian-backup.sh
```
（今すぐ手動実行）
```bash
launchctl unload ~/Library/LaunchAgents/com.obsidian.backup.plist
```
（停止）

片方だけ使いたい場合は設定で `ENABLE_GITHUB=0` / `ENABLE_GDRIVE=0`。

## 復元
- GitHub: `git clone` するか、GitHub 上で過去のコミットからファイルを取り出す
- Google Drive: `mirror/` をそのままコピー、または `snapshots/` の tar.gz をダブルクリックで展開

## 補足
- 旧手順 `../obsidian_icloud_gdrive` は `.md` のみを Drive にコピーするものでした。こちらは画像なども含め Vault 全体をバックアップします。両方動かす必要はありません（旧 plist は `launchctl unload` で停止）。
- Obsidian の端末ごとの状態ファイル（`workspace.json` など）は GitHub に上げません。
