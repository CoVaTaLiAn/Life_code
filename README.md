# Life_code

## CSV の初期分析（`csv-analysis` スキル / `data-analyst` エージェント）

CSV と課題（何を予測したいか）を渡すと、クレンジング → 初期統計 → 特徴量エンジニアリング案 → ベースラインモデル → 特徴量込みの初期モデルまで行い、日本語レポートにまとめる。

- 頼み方: 「この CSV で〇〇を予測したい。初期分析して」（CSV はチャット添付・リポジトリ内・Google Drive のどれでも可）
- 手順: `.claude/skills/csv-analysis/SKILL.md`
- 出力: `analysis/<日付>_<課題>/report.md`・`report.html`（図付き）、`baseline_model.py`（特徴量を足して育てる初期モデル）
- 見本（架空データ）: [`analysis/example_churn_sample/report.md`](analysis/example_churn_sample/report.md)
- 元データと中間 CSV は `.gitignore` でコミット対象外
- コンペ（Kaggle・SIGNATE）の解法は別リポジトリ [kaggle-signate_solution](https://github.com/CoVaTaLiAn/kaggle-signate_solution) に置く（例: Jリーグ観客動員数予測）
