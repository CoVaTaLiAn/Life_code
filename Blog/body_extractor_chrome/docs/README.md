# 本文だけコピー（Chrome拡張）

Webページから広告・メニュー・サイドバー・フッターを除いた**本文だけ**を取り出し、コピーやファイル保存ができるChrome拡張です。

本文の判定には、Firefoxのリーダービューと同じ [Mozilla Readability](https://github.com/mozilla/readability)（Apache-2.0）を使っています。

## できること

- アイコンをクリック（または `Alt+Shift+R`）で本文を抽出してポップアップに表示
- **テキスト** / **Markdown**（見出し・リスト・リンク・引用・コードを保持）を切り替え
- 「タイトル・URLを付ける」で先頭に出典を追加
- ワンクリックでコピー、`.txt` / `.md` で保存
- ページ上で文字を選択してから開くと、**選択範囲だけ**を取り出す
- 本文を特定できないページはページ全体のテキストで代用

## インストール

1. このフォルダ（`Blog/body_extractor_chrome/src`）をPCにダウンロード
2. Chromeで `chrome://extensions` を開く
3. 右上の「デベロッパーモード」をオン
4. 「パッケージ化されていない拡張機能を読み込む」→ `src` フォルダを選択
5. ツールバーのパズルアイコンからピン留めすると使いやすいです

EdgeやBraveなどChromium系ブラウザでも同じ手順で使えます。

## 構成

```
src/
├── manifest.json          拡張の設定（Manifest V3）
├── popup/                 ポップアップ画面
│   ├── popup.html
│   ├── popup.css
│   └── popup.js
├── content/extract.js     ページに注入して本文を抽出・整形
└── lib/Readability.js     Mozilla Readability 0.5.0
```

## 権限

- `activeTab` … アイコンを押したタブだけにアクセス（常時すべてのサイトを読むことはしません）
- `scripting` … 抽出スクリプトをそのタブに注入

データは外部に送信しません。

## 制限

- `chrome://` のページやChromeウェブストアでは動きません
- PDFビューアや、ログイン後に動的に読み込むページでは抽出できないことがあります
