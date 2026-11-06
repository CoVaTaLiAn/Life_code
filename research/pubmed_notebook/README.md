# PubMed 論文探索ノートブック

Google Colab の無料枠で動く、PubMed の一括検索ツール。検索式はAI（無料版でよい）に作らせ、検索・論文収集はこのノートブックでする。

- Ver3 からの変更点：[REPORT.md](REPORT.md)
- 検索式を作らせるプロンプト：[query_prompt.md](query_prompt.md)

## 流れ

1. [query_prompt.md](query_prompt.md) を無料のAIチャットに貼り、検索式の CSV を作らせる
2. `pubmed_research_v4.ipynb` を Colab で開き、CSV（または xlsx）をアップロードして実行
3. 結果の `Summary` シートで警告とヒット数を見る → 必要ならAIに検索式を直させて再実行
4. `Unique_Papers` シートか `pubmed_papers.md` で論文を読む

## 入力（xlsx か csv）

| 列 | 必須 | 内容 |
|---|---|---|
| No | | 検索式の番号（なければ行番号） |
| Target | | 対象 |
| Category | | 分類 |
| PubMed Query | ○ | 検索式 |
| Query Intent | | 何を調べる検索式か |

## 出力

**`pubmed_search_results.xlsx`**

| シート | 中身 |
|---|---|
| Original_Queries | 入力そのまま |
| Summary | 検索式ごとのヒット数・状態・警告・PubMedの解釈 |
| Paper_Details | 検索式×論文（重複も1行ずつ。2回目以降はアブストを空にし、初出の番号を記録） |
| Unique_Papers | 重複なしの論文一覧。どの検索式で何回ヒットしたか、PubMedのリンク付き |

**`pubmed_papers.md`**：重複なしの論文とアブスト（AIに読ませて要約・採点させるときに使う）

## 設定（メインのセルの先頭）

| 項目 | 内容 |
|---|---|
| `Entrez.email` | 自分のメールアドレス（NCBIの利用ルール） |
| `Entrez.api_key` | 無料のNCBI APIキー（任意。あると速い） |
| `INPUT_FILE` | 入力ファイル名 |
| `MAX_DETAIL` | この件数以下の検索式だけ論文を取る（既定 50） |

## ファイル

| ファイル | 内容 |
|---|---|
| `pubmed_research_v4.ipynb` | 最新版ノートブック |
| `pubmed_search_v4.py` | 同じ中身のスクリプト（`python3 pubmed_search_v4.py` でも動く） |
