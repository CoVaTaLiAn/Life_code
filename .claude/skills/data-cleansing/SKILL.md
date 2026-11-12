---
name: data-cleansing
description: 表データ（CSV・Excel）のクレンジングだけを、6つの段階（構造 → 文字の正規化 → 型の変換 → カテゴリの統一 → 欠損の整理 → 外れ値）に分けて行う。段階ごとにデータとレポートを残し、確認しながら進める。「クレンジングして」「データをきれいにして」「表記ゆれを直して」「欠損や外れ値を整理して」と頼まれたときに使う。中身の調査は data-profiling、数値への変換は data-encoding が担当する。
---

# データクレンジング（段階的。段階ごとにレポート）

**この処理はクレンジングだけ**を行う。先に `data-profiling` で生データを調べ、その「品質の気づき」を持って始める。
`D=analysis/<YYYY-MM-DD>_<名前>`、`C="python3 .claude/skills/data-cleansing/scripts/cleanse.py"`

## 段階
各段階の処理は `scripts/stages/` の別ファイル。`cleanse.py` は順番と入出力だけを受け持つ。

| 段階 | ファイル | 役割 | 自動で直すこと | 確認に回すこと（指定があれば直す） |
|---|---|---|---|---|
| 1 構造 | `s1_structure.py` | 表の形を整える | 列名の正規化、空の行・列、重複した行・列、紛れ込んだ見出し行 | 定数列（`--drop-constant`）、合計行 |
| 2 文字の正規化 | `s2_text.py` | 書き方を揃える | 全角英数字→半角、空白、制御文字、欠損表記（NA, - など）→欠損 | `--null-extra` `--null-keep` |
| 3 型の変換 | `s3_types.py` | 種類を決めて変換 | 数値（¥ , % を外す）、真偽→0/1、日時 | 読めなかった値の一覧、`--kind 列=種類` |
| 4 カテゴリの統一 | `s4_categories.py` | 表記ゆれをまとめる | 大文字小文字・空白・記号だけの違い | 似ているだけの値（`--map 列:旧=新;...`） |
| 5 欠損の整理 | `s5_missing.py` | 欠損を把握する | すべて欠損の列・行 | 欠損コード（`--sentinel 列=999`）、「不明」（`--null-category`）、`--drop-col-missing` |
| 6 外れ値 | `s6_outliers.py` | 極端な値を挙げる | なし | `--range 列=下:上`、`--outlier 列=clip` または `nan` |

方針: **意味を変えない整形は自動で行い、意味の判断が要るものは変更せず「要確認」に載せる。** 値の補完はしない（エンコーディングの役割）。

## 進め方
1段階ずつ実行し、その段階の `report.md` を読んでから次へ進む。
```bash
$C --input $D/data/raw.csv --out $D/02_cleanse --stage 1
$C --out $D/02_cleanse --stage 2          # 段階2以降は前の段階の出力を読む
$C --out $D/02_cleanse --stage 3 [--kind 郵便番号=category]
$C --out $D/02_cleanse --stage 4 [--map "性別:男=男性;性別:M=男性"]
$C --out $D/02_cleanse --stage 5 [--sentinel "年齢=999"] [--null-category "会員ランク=不明"]
$C --out $D/02_cleanse --stage 6 [--range "年収=0:100000000,登録日=2000-01-01:2026-12-31"]
```
- 各段階のレポートの「要確認」を読み、**課題やデータの意味から判断できるものはオプションを付けてその段階をやり直す**。判断できないもの（999 が欠損コードか本物の値か、など）は変更せず、ユーザーへの確認事項として返す
- ある段階をやり直すと、それより後の段階の出力は消える（作り直す）
- まず全体像だけ見たいときは `--stage all`（1〜6 を順に実行。レポートは段階ごとに出る）

## 出力
| 場所 | 内容 |
|---|---|
| `$D/02_cleanse/stage<N>_<名前>/` | その段階の `data.csv`・`data.schema.json`（段階3以降。列の種類）・`report.md`・`report.html`・`log.json` |
| `$D/02_cleanse/report.md` / `report.html` | 全段階のまとめ（段階ごとの行数・欠損の変化、全変更、残った要確認） |
| `$D/02_cleanse/cleaned.csv` / `cleaned.schema.json` | 段階6まで終わるとできる最終結果 |
| `stage4_categories/category_map.json` | 表記ゆれの対応表 |

## テスト用データにも同じクレンジングをかける
学習用と同じ種類・同じ対応表・同じ範囲を明示して、別の出力先で実行する。
```bash
$C --input $D/data/test.csv --out $D/05_cleanse_test --stage all \
  --schema-from $D/02_cleanse/cleaned.schema.json \
  --category-map $D/02_cleanse/stage4_categories/category_map.json \
  [学習用で使った --sentinel / --null-category / --range / --drop-constant と同じもの]
```
`--outlier clip` の境界はデータごとに変わるので、両方に使うときは `--range` で範囲を明示する。

## 渡す
- まとめの `report.html` を SendUserFile で送る（必要なら段階ごとのレポートも）
- 返答には、段階ごとの変更の要点、行数・欠損の変化、**残っている要確認**（ユーザーに決めてほしいこと）を書く
- 次は `cleaned.csv` を `data-profiling` に渡して計画を作り直し、`data-encoding` へ
- 見本: `analysis/example_dataprep_sample/02_cleanse/report.md`
