# GAS 自動反映のセットアップ（PCで1回だけ）

これを済ませると、リポジトリの `gas/gmail-sorter/` が main に入るたびに GitHub Actions が Apps Script へ自動で反映する。
スマホから Claude にコード修正を頼み、マージするだけで GAS が更新される。

所要時間：15分ほど

## 1. clasp を入れてログイン

1. Node.js 20 以上を入れる（https://nodejs.org の LTS 版）
2. ターミナル（Windows は PowerShell）で：
   ```
   npm install -g @google/clasp@3.1.3
   clasp login
   ```
   ブラウザが開くので、Gmail と同じ Google アカウントで許可する。
3. https://script.google.com/home/usersettings を開き「Google Apps Script API」をオンにする

## 2. GAS プロジェクトの ID を控える

GAS をまだ作っていなければ、先に `gmail-sorter/README.md` の設置手順で作る。

GAS エディタの左メニュー「プロジェクトの設定」→「ID」の **スクリプト ID** をコピーする。

## 3. GitHub に登録する

リポジトリの Settings → Secrets and variables → Actions を開く。

| 種類 | 名前 | 値 |
|---|---|---|
| Secrets タブ →「New repository secret」 | `CLASPRC_JSON` | ログインで作られたファイルの中身（下のコマンドでコピー） |
| Variables タブ →「New repository variable」 | `GAS_SCRIPT_ID` | 手順2のスクリプト ID |

`CLASPRC_JSON` の中身のコピー：
- Mac：`cat ~/.clasprc.json | pbcopy`
- Windows：`Get-Content $HOME\.clasprc.json | Set-Clipboard`

このファイルは Google アカウントへのアクセス権そのもの。Secrets 以外（チャット・メモ・コミット）には貼らない。

## 4. 動作確認

GitHub の Actions タブ →「Deploy GAS」→「Run workflow」。緑のチェックが付けば成功。
GAS エディタを再読み込みすると、リポジトリのコードに置き換わっている。

## その後の使い方

- コード修正：Claude に「GASの○○を直して」と頼み、変更が main に入れば自動で反映される
- 反映されるのはコードだけ。トリガーやラベルを変えたときは、GAS エディタで `setup` を1回実行する
- 失敗したら Actions タブのログを見る。多くはログインの期限切れなので、PC で `clasp login` をやり直し、`CLASPRC_JSON` を貼り直す
