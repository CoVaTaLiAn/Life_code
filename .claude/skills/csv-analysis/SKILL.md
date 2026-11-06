---
name: csv-analysis
description: CSV の表データと課題（何を予測・分析したいか）を受け取り、データクレンジング → 初期統計（分布・欠損・目的変数との関係・相関・train/test の差）→ 特徴量エンジニアリング案 → ベースラインモデル（交差検証）→ 特徴量を足した初期モデルまで行い、傾向と次の一手が分かる日本語レポートにまとめる。CSV・表データ・データ分析・EDA・前処理・特徴量・機械学習モデル・予測・コンペを頼まれたときに使う。
---

# CSV 初期分析（クレンジング → 統計 → 特徴量案 → 初期モデル → レポート）

- 分析スクリプト: `.claude/skills/csv-analysis/scripts/eda_baseline.py`
- 初期モデルの雛形: `.claude/skills/csv-analysis/templates/baseline_model.py`
- 以下 `S=.claude/skills/csv-analysis/scripts/eda_baseline.py`、`D=analysis/<YYYY-MM-DD>_<課題の英語スラッグ>`

ゴールは「ユーザーが傾向を掴み、どの特徴量エンジニアリングをやるか自分で判断できる」こと。
数字は必ずスクリプトの出力から引用し、推測は推測と書く。

## 0. 準備
```bash
python3 -c "import pandas, sklearn, scipy, matplotlib, lightgbm" 2>/dev/null || pip install -q pandas scikit-learn scipy matplotlib lightgbm
```
日本語フォント（IPAGothic / Noto Sans CJK JP など）があれば図に使われる。なければ `apt-get install -y fonts-ipafont-gothic`。

## 1. 入力を受け取る
- **CSV**: リポジトリ内のパス、チャットに添付されたファイル、Google Drive（`mcp__Google_Drive__search_files` → `download_file_content`）、URL のどれでもよい。`$D/data/` に置く（`analysis/**/data/` と CSV は git に入れない）。
- **課題**: 「何を予測したいか」「評価指標」「予測に使える情報の時点」。課題文から読み取る。
- train / test の2ファイルがあれば両方使う。Excel なら CSV に変換してから。

## 2. 中身をざっと見て、設定を決める
```bash
head -5 $D/data/train.csv; wc -l $D/data/train.csv
```
課題と列名から以下を決める。**決められないのが目的変数だけのときに限り、ユーザーに1回だけ質問する**。それ以外は妥当な判断をしてレポートに書く。

| 引数 | 決め方 |
|---|---|
| `--target` | 課題で予測したいもの（必須） |
| `--task` | 通常 auto。数値でも種類が少ない（評価 1〜5 など）とき分類か回帰かを課題から決める |
| `--metric` | 課題に指標があればそれ（auc / pr_auc / logloss / accuracy / f1 / macro_f1 / rmse / mae / rmsle / r2）。なければ既定（2値 auc、多クラス macro_f1、回帰 rmse） |
| `--time` | 「将来を予測する」課題で日時列があれば指定 → 時系列分割で検証 |
| `--group` | 同じ顧客・患者などが複数行ある場合、その列 → 同じグループが学習と検証にまたがらない |
| `--id` | 自動判定に漏れた ID 列 |
| `--drop` | **予測時点では分からない情報（結果の後に決まる列）**、目的変数の言い換え。リークになる |

## 3. 実行
```bash
python3 $S run --train $D/data/train.csv [--test $D/data/test.csv] --target <列> --out $D \
  --title "<課題の短い名前>" --goal "<課題を1文で>" [--metric ...] [--time ...] [--group ...] [--id ...] [--drop ...]
```
出力: `report.md` / `report.html`（画像埋め込みで単体で開ける）/ `figs/*.png` / `results.json` / `cleaned_train.csv` / `cleaned_test.csv` / `y.csv` / `column_profile.csv` / `univariate.csv` / `oof.csv` / `worst_errors.csv` / `predictions.csv`

やっていること:
- **クレンジング**: 文字コード・区切り文字の自動判定、列名の正規化、全角→半角、欠損表記の統一（NA, -, null など）、数値化（¥ , % を除去）、0/1 化（はい/いいえ等）、日時化、カテゴリの表記ゆれ統一、空列・定数列・重複列・重複行の削除、ID 列の除外。欠損コード（999, -1）や極端な値は **置換せず「要確認」として記録**
- **統計**: 列ごとのプロファイル、欠損と目的変数の関係、相互情報量＋種類別の指標（AUC / Spearman / Cramér's V / η²）、分位ごとの目的変数、相関の強い組、時間推移、train/test の差（KS・未知カテゴリ・adversarial validation）、リーク疑い
- **モデル**: 何もしない基準・線形・LightGBM を同じ分割で交差検証。学習と検証のスコア差、重要度、ROC/較正/混同行列/残差、外した行

## 4. 結果を確認し、必要なら再実行
`report.md` を読み、`figs/` の図は Read で目視する。次のどれかがあれば引数を直して再実行する:
- 型の判定ミス（数値のはずがカテゴリ等）→ 元データを確認して `--drop` や前処理で対処
- ID の誤判定 → `--id`
- リーク疑い（単独で目的変数をほぼ説明できる列）→ 課題の意味から事後情報なら `--drop`
- 日時があって課題が将来予測なのに `--time` なし → 付ける

## 5. 初期モデル（特徴量エンジニアリング込み）
```bash
cp .claude/skills/csv-analysis/templates/baseline_model.py $D/
```
`$D/baseline_model.py` の `add_features()` に、レポートの「特徴量エンジニアリングの候補」の優先度「高」から **3〜6個** を実装する（欠損コードの NaN 化、欠損フラグ、比・差、グループ集約、日時の差 など。目的変数を使う処理は書かない）。
```bash
python3 $D/baseline_model.py
```
追加前後のスコアを同じ分割で比べる。効かなかった特徴量も「効かなかった」と記録する（判断材料になる）。結果は `model_scores.csv` / `model_importance.csv` / `submission.csv`。

## 6. 考察を書く → `$D/insights.md` → レポートに反映
```markdown
### 結論（3行）
### データの品質で気になる点
（要確認の値・表記ゆれ・欠損の偏り・重複。ユーザーに確認したいことは明記）
### 見えた傾向
（目的変数と関係が強い列トップ5〜8を「どの値で目的変数がどう変わるか」まで数字付きで。図番号でなく図の名前で参照）
### 特徴量エンジニアリングの提案（優先順）
| # | 案 | 根拠（数字） | 期待効果 | 初期モデルで試した結果 |
（自動候補を課題の意味で取捨選択・具体化する。ドメイン的に意味のある組み合わせを優先し、試していない案は「未実施」）
### モデルについて
（最良モデルと指標、何もしない基準との差、過学習の度合い、外した行の共通点、指標の選び方の注意）
### 次の一手
（優先順に3〜5個）
```
```bash
python3 $S render --out $D
```
`insights.md` が「0. まとめと考察」に入った `report.md` と `report.html` が作られる。

## 7. 渡す
- `report.html` を SendUserFile で送る（スマホでも図付きで読める）。共有したい場合は Artifact での公開を1行で提案する
- コミットするのは `report.md` `report.html` `insights.md` `figs/` `baseline_model.py` `model_scores.csv`。データ（CSV）は `.gitignore` で除外済み
- 最後の返答は、結論3行・主要スコア・特徴量案の上位3つ・ユーザーに確認したいこと
