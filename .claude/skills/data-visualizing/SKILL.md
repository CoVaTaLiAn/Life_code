---
name: data-visualizing
description: 表データのカテゴリ列ごとに、各カテゴリの統計（件数・割合・目的変数の平均・数値列の中央値と 25〜75% の範囲）を図にして画像（PNG）で保存し、レポートにする。可視化だけを行い、データは変更しない。「カテゴリ別に可視化して」「カテゴリごとの統計を図にして」「画像で保存して」と頼まれたときに使う。中身の調査は data-profiling、汚れの修正は data-cleansing、数値への変換は data-encoding が担当する。
---

# カテゴリ別の統計の可視化（図にして画像で保存するだけ。変更しない）

**この処理は可視化だけ**を行う。入力はクレンジング後の `cleaned.csv` が基本（表記ゆれが残っていると同じカテゴリが別の棒になる）。
生データも渡せるが、その場合は種類を推定して描く。`D=analysis/<YYYY-MM-DD>_<名前>`

## 準備
```bash
python3 -c "import matplotlib" 2>/dev/null || pip install -q matplotlib
```
日本語フォント（IPAGothic / Noto Sans CJK JP など）がなければ `apt-get install -y fonts-ipafont-gothic`。

## 実行
```bash
python3 .claude/skills/data-visualizing/scripts/visualize_categories.py \
  --input $D/02_cleanse/cleaned.csv --out $D/07_visualize [--target <目的変数>] \
  [--columns 列,列] [--values 列,列] [--top 15] [--max-values 6] [--dpi 200]
```
| 引数 | 既定 | 意味 |
|---|---|---|
| `--columns` | カテゴリ・真偽の列と、値が 10 種類以下の数値列 | 図にするカテゴリ列 |
| `--values` | 数値列を先頭から `--max-values` 個 | カテゴリ別に統計を取る数値列 |
| `--target` | なし | 数値か 0/1 の目的変数。カテゴリ別の平均（0/1 なら割合）を図に入れる |
| `--top` | 15 | 1枚に出すカテゴリ数。残りは「その他」にまとめる。欠損は「(欠損)」として出す |

## 出力
| ファイル | 内容 |
|---|---|
| `figs/<列名>.png` | カテゴリ列1つにつき1枚。左から 件数（割合）→ 目的変数の平均 → 数値列ごとの分布 |
| `category_stats.csv` | 図にした数値すべて（列・カテゴリ・件数・割合・平均・標準偏差・最小・25%・中央値・75%・最大） |
| `report.md` / `report.html` | 図と、同じ数値の表。html は画像埋め込みで単体で開ける |

図の読み方: 薄い帯がそのカテゴリの 25〜75% の範囲、点が中央値、点線が全体の中央値（目的変数は全体の平均）。
件数の少ないカテゴリは値がぶれやすいので、左端の件数と合わせて読む。

## 確認して渡す
- 画像を Read で目視する（ラベルの重なり、文字化け、カテゴリの並び）
- `report.html` と、必要な画像を SendUserFile で送る
- 返答には、目的変数や数値が全体と大きく違うカテゴリを、件数つきで書く（20 件未満のカテゴリは断定しない）
- 見本: `analysis/example_dataprep_sample/07_visualize/report.md`
