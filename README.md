# Life_code

## CSV の初期分析（`csv-analysis` スキル / `data-analyst` エージェント）

CSV と課題（何を予測したいか）を渡すと、クレンジング → 初期統計 → 特徴量エンジニアリング案 → ベースラインモデル → 特徴量込みの初期モデルまで行い、日本語レポートにまとめる。

- 頼み方: 「この CSV で〇〇を予測したい。初期分析して」（CSV はチャット添付・リポジトリ内・Google Drive のどれでも可）
- 手順: `.claude/skills/csv-analysis/SKILL.md`
- 出力: `analysis/<日付>_<課題>/report.md`・`report.html`（図付き）、`baseline_model.py`（特徴量を足して育てる初期モデル）
- 見本（架空データ）: [`analysis/example_churn_sample/report.md`](analysis/example_churn_sample/report.md)
- 元データと中間 CSV は `.gitignore` でコミット対象外
- コンペ（Kaggle・SIGNATE）の解法は別リポジトリ [kaggle-signate_solution](https://github.com/CoVaTaLiAn/kaggle-signate_solution) に置く（例: Jリーグ観客動員数予測）

## SQL練習サイト（`sql-practice/`）

ボタンとリストを選ぶだけで SQL を組み立てて、その場で実行・答え合わせができる練習サイト。

- 開き方: `sql-practice/index.html` をブラウザで開くだけ（サーバー不要。SQLite をブラウザ内で動かす sql.js を CDN から読み込むのでネット接続は必要）
- 練習問題 36 問・4レベル
  - Lv.1 初級（SELECT・WHERE・並べ替え）/ Lv.2 中級（集計・結合・パターン検索）/ Lv.3 上級（複数結合・日付関数・CASE・RANK）
  - Lv.4 実践: サブクエリ、自己結合、PARTITION BY、WITH＋LAG の前月比、累計、構成比、グループ内トップ、重複チェックなど業務でよく書く SQL
- 組み立て台: 列ボタン、集計・変換・順位・CASE の関数、複数の JOIN、WHERE（値は実データから選択）、GROUP BY、HAVING、ORDER BY、LIMIT
- 手書きの問題では、句・関数・WITH・ウィンドウ関数などの部品を押すとカーソル位置に挿入される。書きかけは問題ごとにブラウザに保存
- 正解すると番号に緑の丸が付く（ブラウザに保存）。「自由に組み立てる」タブでは問題なしで試せる
- 練習用データ: 社員（employees）・部署（departments）・商品（products）・売上（sales）の架空データ
