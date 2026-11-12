---
name: data-encoding
description: クレンジング済みの表データを、プロファイリングが作った計画（encoding_plan.json）に従ってすべて数値の表に変換する（エンコーディングだけを行う）。One-Hot・ラベル・順序・頻度・ターゲット・0/1 化・対数変換・標準化・日時の分解などに対応し、学習用で決めた変換をテスト用データにも同じ形でかけられる。変換の内容はレポートにする。「エンコーディングして」「カテゴリを数値にして」「モデルに入れられる形にして」と頼まれたときに使う。中身の調査は data-profiling、汚れの修正は data-cleansing が担当する。
---

# エンコーディング（計画どおりに数値へ変換）

**この処理はエンコーディングだけ**を行う。どの列をどの方法にするかは自分で決めない。
入力は次の2つ（どちらもなければ先にそれぞれの処理を実行する）:
- クレンジング済みのデータ `cleaned.csv`＋`cleaned.schema.json`（`data-cleansing` の出力）
- 計画 `encoding_plan.json`（**クレンジング後**のデータに対する `data-profiling` の出力）

`D=analysis/<YYYY-MM-DD>_<名前>`、`E="python3 .claude/skills/data-encoding/scripts/encode.py"`

## 1. 計画を確認する
`$D/03_profile_cleaned/report.md` の「おすすめのエンコーディング」を読み、課題の意味から変えるべき列を決める。
変える方法は2つ: `encoding_plan.json` の `method` / `params` を書き換える（記録が残るのでこちらを優先）か、`--set 列=方法`。

| 方法 | 対象 | 出力 | 補足（`params`） |
|---|---|---|---|
| `drop` | すべて | なし | |
| `passthrough` | 数値 | そのまま | `impute`: none / median / mean / zero |
| `log1p` | 数値 | `列__log1p` | 負の値があれば符号付きの対数 |
| `standard` / `minmax` | 数値 | `列__std` / `列__minmax` | 欠損は中央値で補完し `列__isna` を足す |
| `binary` | 2種類の値 | 0/1 | `positive`: 1 にする値 |
| `onehot` | カテゴリ | `列=値` ごとに 0/1 | `max_categories`（既定 30。超えた分は「その他」） |
| `label` | カテゴリ | `列__label` | 文字の順の整数。木のモデル向け |
| `ordinal` | カテゴリ | `列__ord` | `order`: 小さい順の並び（必須） |
| `frequency` | カテゴリ・ID | `列__freq` | 出現割合 |
| `target` | カテゴリ | `列__te` | 目的変数の平均。学習用は fold 外で計算。`smoothing`（既定 10）、`folds`（既定 5） |
| `datetime` | 日時 | 年・月・日・曜日・週末・月と曜日の sin/cos・経過日数 | `parts` で絞れる |
| `text_stats` | 文章 | `列__len` `列__words` | TF-IDF・埋め込みは対象外 |

モデルごとの目安: 木のモデル（LightGBM など）は `passthrough`・`label`・欠損そのままでよい。線形モデル・ニューラルネットは `standard`・`onehot`・欠損の補完が要る。

## 2. 学習用データで変換を決める（fit）
```bash
$E fit --input $D/02_cleanse/cleaned.csv --plan $D/03_profile_cleaned/encoding_plan.json --out $D/04_encode [--target <目的変数>] [--set 列=方法,...]
```
## 3. テスト用データに同じ変換をかける（apply）
```bash
$E apply --input $D/05_cleanse_test/cleaned.csv --state $D/04_encode/encoder_state.json --out $D/06_encode_test
```
テスト用データは、学習用と同じクレンジング（`data-cleansing` の「テスト用データにも…」）を通しておく。列の並びは学習用と同じになる。

## 出力（`--out` の中）
| ファイル | 内容 |
|---|---|
| `encoded.csv` | すべて数値の表（目的変数があれば最後の列） |
| `encoder_state.json` | 変換の中身（カテゴリの一覧・対応表・平均など）。apply に渡す |
| `feature_map.csv` | 元の列 → 出力の列の対応 |
| `report.md` / `report.html` | 列ごとの変換、方法ごとの集計、出力の確認（すべて数値か・残った欠損・定数列）、注意、出力列の統計値 |

## 4. レポートを確認する
- 「出力の確認」で、すべて数値になっているか、欠損が残っている列は意図どおりか
- apply の「未知の値」（学習用になかったカテゴリ）が多い列は、クレンジングの表記ゆれ統一が漏れていないか確認する
- `target` を使った列があるとき: 交差検証のスコアを厳密に見るなら、検証の fold ごとに fit し直す（レポートの注意に出る）

## 渡す
- `report.html` を SendUserFile で送る
- 返答には、列数の変化（元 → 出力）、方法ごとの内訳、残った欠損、注意を書く
- 見本: `analysis/example_dataprep_sample/04_encode/report.md`
