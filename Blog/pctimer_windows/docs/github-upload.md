# GitHubへのアップロード手順

## 1. 初回公開（GitHub Web UI）

1. ZIPを解凍し、`pc-auto-lock-timer/` フォルダーの中身を確認します。
2. GitHubで新しいリポジトリ（例：`pc-auto-lock-timer`）を作成します。
3. リポジトリ画面の **Add file → Upload files** を開きます。
4. `README.md`、`src/`、`docs/`、`.gitignore`をフォルダー構成を保ったまま追加します。GitHubのブラウザ画面でディレクトリ階層が維持されていることを確認してください。
5. 公開する内容に個人情報や認証情報が含まれていないことを確認し、コミットします。

## 2. Gitコマンドで登録する場合（新規リポジトリ）

WindowsのPowerShellまたはコマンドプロンプトで、解凍したプロジェクトのルートフォルダーへ移動してから実行します。以下の `<YOUR_USER>` はGitHubのユーザー名に、`<YOUR_REPOSITORY>` はリポジトリ名に置き換えてください。

```bash
git init
git add README.md src docs .gitignore
git commit -m "docs: PC自動ロックタイマーの技術レポートと実行コードを追加"
git branch -M main
git remote add origin https://github.com/<YOUR_USER>/<YOUR_REPOSITORY>.git
git push -u origin main
```

- Gitを利用するには事前にGitのインストールとGitHub認証が必要です。
- GitHub側に最初からREADMEなどを作成済みの場合、履歴が分岐する場合があります。既存リポジトリの状態を確認してから統合してください。
- すでに`git init`済み、または`origin`が登録済みのリポジトリでは、初期化・remoteの追加を重複実行しないでください。
- リポジトリに公開するのは`.hta`を含むソースコードとドキュメントです。HTAの実行はWindows上で行います。

## 3. 推奨コミットメッセージ

**Commit message（1行）：**

```text
docs: PC自動ロックタイマーの技術レポートと実行コードを追加
```

**Extended description（コミット詳細）：**

```text
- 既存の動作確認済みHTAコードをsrc/AutoLockTimer.htaとして収録
- timer.mdの開発記録をv1.0〜v1.5の変更履歴として整理
- 背景、目的、技術選定、処理フロー、ファイル構成をREADMEに記載
- 実際のエラー履歴と想定トラブルを区別してトラブルシューティングを作成
- 動作確認済みの申告を反映し、個別テストと環境情報の未確認事項を明示
- GitHubへのアップロード手順と.gitignoreを追加
```

`docs:`は今回の主目的が技術記録の追加であるための選択です。新規アプリの機能追加を中心に扱う初回コミットなら、`feat: PC自動ロックタイマーを追加` でも構いません。

## 4. 以降の更新方針

- 機能追加：`feat: ...`
- 不具合修正：`fix: ...`
- ドキュメント更新：`docs: ...`
- 内部構造の改善：`refactor: ...`

実装を変更した際は `src/` を更新し、理由と検証結果を `docs/changelog.md` と `docs/verification.md` に追記してください。
