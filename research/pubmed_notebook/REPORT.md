# PubMed 論文探索ノートブック Ver4：変更点と検証結果

2026-11-06

## まとめ

- **元の検索式の MeSH 用語が無効だった。** `"Cervical Neoplasms"[MeSH Terms]` は MeSH に存在せず、PubMed は黙って無視していた（正しくは `"Uterine Cervical Neoplasms"[Mesh]`）。
  Ver4 では PubMed の警告を `Summary` シートに出すので、こうした誤りに気づける。
- **検索式を改良すると、体液検体の論文が増えた。** `[tiab]` を付け、腕の表記（-3p/-5p）なしも入れ、MeSH を直した。
  同じ「年の制限なし」の条件で比べると、miRNA 5種の合計が 6件 → 23件になった。
- **コードの不具合を直した。** 発行年が空になる、エラーが記録されない、書籍が抜ける、などを直した。
- **無料枠のまま使える。** Colab 無料枠と無料のAIチャットで完結する。検索式を作らせるプロンプトは [query_prompt.md](query_prompt.md)。

## 1. 検索式の検証

### 元の入力（`pubmed_inputdata_original.xlsx`）で見つかった問題

| 問題 | 該当 | 影響 |
|---|---|---|
| `"Cervical Neoplasms"[MeSH Terms]` が MeSH に存在しない | 全10本 | MeSH による検索が効かず、"cervical cancer" などの語で書かれた論文しか拾えない |
| フィールドタグなし（`"blood"` など） | 全10本 | `[All Fields]` 扱いになり、著者所属や雑誌名にもヒットする |
| 同じ語が2回入っている（`"microRNA-126" OR … OR "microRNA-126"`） | 詳細版4本 | 結果は変わらないが、AIが作った検索式の質のチェックが要る |
| 基本版が `-3p`/`-5p` 付きの表記だけ | 基本版5本 | 腕の表記がない古い論文（`miR-126` など）を拾えない |

PubMed の実際の解釈（`Query Translation`）を見ると、MeSH の部分が消えている：

```
("miR-126-3p"[All Fields] OR ...) AND ("cervical cancer"[All Fields] OR "cervical carcinoma"[All Fields]) AND ("blood"[All Fields] OR ...)
```

### 改良版（`pubmed_inputdata_sample_v4.xlsx`、17本）

構成：全体用2本、miRNA 5種 × 3段階（①miRNA×子宮頸がん ②＋体液 ③＋診断性能）

| miRNA | 元・基本版（年制限なし） | 元・詳細版（2021年以降） | 改良版 ①広い | ②＋体液 | ③＋診断 |
|---|---|---|---|---|---|
| miR-126-3p | 0 | 1 | 32 | 6 | 4 |
| miR-451a | 0 | 1 | 6 | 1 | 0 |
| miR-144-3p | 1 | 1 | 14 | 2 | 1 |
| miR-20b-5p | 1 | 1 | 13 | 2 | 1 |
| miR-155-5p | 4 | 8 | 44 | 12 | 10 |
| 全体（子宮頸がん×miRNA×体液） | | | 306 | | |
| 全体のレビュー・メタ解析 | | | 66 | | |

- 全体の2本は50件を超えたので論文は取っていない（ヒット数の目安として記録）
- 論文を取った15本から重複を除いて **103本**。うち体液の検索式（②③）で当たったのは **22本**
- 結果は [example_output/](example_output/) にある

### 改良版でも残る注意点

- `blood[tiab]` は血管の話にも当たる。実例：PMID 24037526（miR-126 と血管新生）は "blood and lymphatic vessels" で②に入った。同様に `plasma[tiab]` は "plasma membrane" にも当たりうる。気になるなら `"blood sample*"[tiab]`・`serum[tiab]` などに絞る
- `"miR-126"[tiab]` は miR-126-5p の論文も拾う。広い版としては意図どおりだが、-3p に限るなら採点のときに見分ける
- 体液のブロックに `"cervical mucus"`（子宮頸管粘液）を入れたので、子宮頸部の局所検体も入る。また、アブストの背景で触れただけの論文も当たる（実例：PMID 32323808 は HeLa 細胞の研究だが、背景に cervical mucus の記述がある）。血液・尿に限るなら外す

## 2. コードの変更点（Ver3 → Ver4）

| 項目 | Ver3 | Ver4 |
|---|---|---|
| 発行年 | `PubDate` に `Year` がないと空欄 | `MedlineDate`（例 "2021 Jan-Feb"）→ 電子版の日付 → 完了日の順に探す。サンプル103本で空欄0 |
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

## 3. AIに検索式を作らせるときの要点

[query_prompt.md](query_prompt.md) に入れた指示：

1. MeSH は実在する用語だけ使う（今回の誤りの再発防止）
2. 自由語には必ず `[tiab]`
3. 腕の表記あり/なしの両方
4. 広い順に段階的に（50件ルールで「どこから絞れたか」が分かる）
5. 出力は CSV（そのまま入力に使える）

実行後は `Summary` の `PubMed Warning` と `Hit Count` をAIに貼って直させる、という往復を想定している。

## 4. 確認したこと

- 元の入力10本：ヒット数が Ver3 の出力と一致（0, 0, 1, 1, 4, 1, 1, 1, 1, 8）
- 改良版17本：エラー0、発行年の空欄0、4シートと Markdown が出力される
- CSV の読み込み（" の二重化、BOM付き）
- 実行環境：Python 3、biopython 1.88（Colab 上では未実行。Colab 用のセルは `google.colab` がない環境では何もしない）

## 5. このリポジトリの `pubmed-survey` スキルとの関係

`.claude/skills/pubmed-survey` は同じ流れ（検索 → 50件以下を収集 → 重複除外）に、Claude による関連度の採点とまとめレポートを加えたもの。Claude Code が使えるときはスキル、無料枠で回すときはこのノートブック、と使い分ける。
