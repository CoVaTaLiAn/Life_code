# PubMed 論文探索ノートブック Ver4：変更点

2026-11-06

## まとめ

- **コードの不具合を直した。** 発行年が空になる、エラーが記録されない、書籍が抜ける、などを直した。
- **AIが作った検索式を確かめる列を足した。** PubMed が無視した語（存在しない MeSH 名など）、PubMed の実際の解釈、括弧・" の数の不一致、同じ語の重複を `Summary` シートに出す。
- **無料枠のまま使える。** Colab 無料枠と無料のAIチャットで完結する。検索式を作らせるプロンプトは [query_prompt.md](query_prompt.md)。

## 1. コードの変更点（Ver3 → Ver4）

| 項目 | Ver3 | Ver4 |
|---|---|---|
| 発行年 | `PubDate` に `Year` がないと空欄 | `MedlineDate`（"2021 Jan-Feb" の形）→ 電子版の日付 → 完了日の順に探す |
| エラー | 画面に表示して次へ。Summary に残らない | 通信エラーは2・4・8秒待って再試行。失敗したら Summary の `Status` に `ERROR: …` と記録し、最後に件数を表示 |
| 検索式の確認 | なし | `Query Check`（括弧・" の数、同じ語の重複）、`PubMed Warning`（PubMed が無視した語）、`Query Translation`（PubMed の解釈）を Summary に追加 |
| 書籍 | `PubmedBookArticle` を読まない | 読む |
| 重複の記録 | Markdown には最初の検索式の Target だけ | `Unique_Papers` シートを追加。ヒットした全検索式・Target・回数・PubMed のリンク |
| アブスト | 見出し（BACKGROUND: など）が消える | 見出しを残す |
| 入力 | xlsx のみ | csv も可（AIの出力を貼って保存するだけでよい。BOM付きでも読める） |
| Excel のセル上限 | 長いアブストで保存に失敗しうる | 32,000字で切る |
| 取得件数 | 毎回500件のIDを取得 | 必要な50件だけ |
| 設定 | コード中に散らばる | 先頭にまとめた（メール、APIキー、入力ファイル、件数の上限） |
| Colab | 手動でアップロード・ダウンロード | アップロード・ダウンロードのセルを追加 |

無料枠のための仕組みはそのまま：API キーなしで1秒間隔（APIキーがあれば0.4秒）、ライブラリは biopython / pandas / openpyxl だけ。

## 2. AIに検索式を作らせるときの要点

[query_prompt.md](query_prompt.md) に入れた指示：

1. MeSH は実在する正式名だけ使う（存在しない MeSH 名は PubMed に黙って無視される）
2. 自由語には必ず `[tiab]`（タグなしは `[All Fields]` 扱いになり、著者所属や雑誌名にも当たる）
3. 表記の揺れをすべて入れる（遺伝子記号、サブタイプの有無など）
4. 広い順に段階的に（50件ルールで「どこから絞れたか」が分かる）
5. 出力は CSV（そのまま入力に使える）

実行後は `Summary` の `PubMed Warning` と `Hit Count` をAIに貼って直させる、という往復を想定している。

### 自由語で気をつけること

- `blood[tiab]` は "blood vessel" など血管の話にも当たる。`plasma[tiab]` は "plasma membrane" にも当たりうる
- アブストの背景で触れただけの論文も当たるので、関連度は読んで判断する

## 3. 確認したこと

- Ver3 と同じ入力で、ヒット数が Ver3 の出力と一致
- 17本の検索式でエラー0、発行年の空欄0、4シートと Markdown が出力される
- CSV の読み込み（" の二重化、BOM付き）
- 実行環境：Python 3、biopython 1.88（Colab 上では未実行。Colab 用のセルは `google.colab` がない環境では何もしない）

## 4. このリポジトリの `pubmed-survey` スキルとの関係

`.claude/skills/pubmed-survey` は同じ流れ（検索 → 50件以下を収集 → 重複除外）に、Claude による関連度の採点とまとめレポートを加えたもの。Claude Code が使えるときはスキル、無料枠で回すときはこのノートブック、と使い分ける。
