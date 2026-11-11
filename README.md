# Life_code

生活まわりの小さな自動化・調査ツールをまとめたリポジトリ。

## プロジェクト一覧

| フォルダ | 内容 |
|---|---|
| [`gas/2026-11-01_gmail-sorter/`](gas/2026-11-01_gmail-sorter/README.md) | Gmail 自動振り分け（Google Apps Script）。main に入ると GAS へ自動反映 |
| [`2026-10-30_yahoo_mail/`](2026-10-30_yahoo_mail/README.md) | Yahoo!メールの受信箱をフォルダに振り分ける Python スクリプト |
| [`research/2026-11-06_pubmed_notebook/`](research/2026-11-06_pubmed_notebook/README.md) | PubMed 一括検索ノートブック（Google Colab 無料枠） |
| [`Blog/2026-10-21_obsidian_icloud_gdrive/`](Blog/2026-10-21_obsidian_icloud_gdrive/README.md) | Obsidian（iCloud）→ Google Drive の自動同期（Mac） |
| [`Blog/2026-10-24_pctimer_windows/`](Blog/2026-10-24_pctimer_windows/README.md) | 指定時刻に Windows をロックするタイマー |
| [`study/2026-11-11_stat-exam-practice/`](study/2026-11-11_stat-exam-practice/README.md) | 統計検定2級の記述ドリル（AIが出題・採点する Artifact ページ） |
| [`analysis/`](analysis/example_churn_sample/report.md) | CSV 初期分析の出力先（下記 `csv-analysis`） |
| `.claude/` | Claude Code 用のスキル・エージェント（`csv-analysis`・`pubmed-survey`・`gmail-triage` など） |

## 各プロジェクトの構成

どのプロジェクトも同じ形にそろえる（中身がないフォルダは作らない）。

```text
<作成日>_<名前>/
├── README.md   概要・使い方・ファイル一覧（必ず置く）
├── src/        コード本体
├── docs/       セットアップ手順・経緯・変更履歴などの補足資料
└── examples/   設定ファイルなどの見本
```

フォルダ名は `<作成日 YYYY-MM-DD>_<名前>`（例：`2026-11-01_gmail-sorter`）。日付はそのプロジェクトを最初にコミットした日。

新しいプロジェクトを足すときもこの形にし、上の一覧に1行追加する。

## CSV の初期分析（`csv-analysis` スキル / `data-analyst` エージェント）

CSV と課題（何を予測したいか）を渡すと、クレンジング → 初期統計 → 特徴量エンジニアリング案 → ベースラインモデル → 特徴量込みの初期モデルまで行い、日本語レポートにまとめる。

- 頼み方: 「この CSV で〇〇を予測したい。初期分析して」（CSV はチャット添付・リポジトリ内・Google Drive のどれでも可）
- 手順: `.claude/skills/csv-analysis/SKILL.md`
- 出力: `analysis/<日付>_<課題>/report.md`・`report.html`（図付き）、`baseline_model.py`（特徴量を足して育てる初期モデル）
- 見本（架空データ）: [`analysis/example_churn_sample/report.md`](analysis/example_churn_sample/report.md)
- 元データと中間 CSV は `.gitignore` でコミット対象外
- コンペ（Kaggle・SIGNATE）の解法は別リポジトリ [kaggle-signate_solution](https://github.com/CoVaTaLiAn/kaggle-signate_solution) に置く（例: Jリーグ観客動員数予測）
