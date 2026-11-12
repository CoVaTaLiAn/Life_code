# 前処理の見本（架空データ）

役割ごとに分けた3つの処理（プロファイリング・クレンジング・エンコーディング）を、わざと汚した架空の顧客データ（解約の予測を想定）に通した結果。
データそのもの（CSV）はコミットしていない。`python3 make_sample.py` で `data/raw.csv`（学習用 500 行）と `data/raw_test.csv`（テスト用 115 行）を作り直せる。

| 順 | フォルダ | 処理 | レポート |
|---|---|---|---|
| 1 | `01_profile_raw/` | プロファイリング（生データ） | [report.md](01_profile_raw/report.md) |
| 2 | `02_cleanse/` | クレンジング（まとめ） | [report.md](02_cleanse/report.md) |
| | `02_cleanse/stage1_structure/` | 段階1 構造 | [report.md](02_cleanse/stage1_structure/report.md) |
| | `02_cleanse/stage2_text/` | 段階2 文字の正規化 | [report.md](02_cleanse/stage2_text/report.md) |
| | `02_cleanse/stage3_types/` | 段階3 型の変換 | [report.md](02_cleanse/stage3_types/report.md) |
| | `02_cleanse/stage4_categories/` | 段階4 カテゴリの統一 | [report.md](02_cleanse/stage4_categories/report.md) |
| | `02_cleanse/stage5_missing/` | 段階5 欠損の整理 | [report.md](02_cleanse/stage5_missing/report.md) |
| | `02_cleanse/stage6_outliers/` | 段階6 外れ値 | [report.md](02_cleanse/stage6_outliers/report.md) |
| 3 | `03_profile_cleaned/` | プロファイリング（クレンジング後）＋エンコーディング計画 | [report.md](03_profile_cleaned/report.md) |
| 4 | `04_encode/` | エンコーディング（学習用で fit） | [report.md](04_encode/report.md) |
| 5 | `05_cleanse_test/` | テスト用データに同じクレンジング | [report.md](05_cleanse_test/report.md) |
| 6 | `06_encode_test/` | テスト用データに同じ変換（apply） | [report.md](06_encode_test/report.md) |
| 7 | `07_visualize/` | カテゴリ別の統計の可視化（画像は `figs/`） | [report.md](07_visualize/report.md) |

実行したコマンド（リポジトリのルートで）:
```bash
D=analysis/example_dataprep_sample; S=.claude/skills
C="python3 $S/data-cleansing/scripts/cleanse.py"; R="年収=0:100000000,平均滞在分=0:600,登録日=2000-01-01:2026-12-31"
python3 $D/make_sample.py
python3 $S/data-profiling/scripts/profile_data.py --input $D/data/raw.csv --out $D/01_profile_raw --target 解約
$C --out $D/02_cleanse --stage 1 --input $D/data/raw.csv --drop-constant
$C --out $D/02_cleanse --stage 2
$C --out $D/02_cleanse --stage 3
$C --out $D/02_cleanse --stage 4 --map "性別:男=男性;性別:M=男性;性別:女=女性;都道府県:東京=東京都;都道府県:TOKYO=東京都;都道府県:大阪=大阪府"
$C --out $D/02_cleanse --stage 5 --sentinel "年齢=999,月間来店回数=-1" --null-category "会員ランク=不明"
$C --out $D/02_cleanse --stage 6 --range "$R"
python3 $S/data-profiling/scripts/profile_data.py --input $D/02_cleanse/cleaned.csv --out $D/03_profile_cleaned --target 解約
python3 $S/data-encoding/scripts/encode.py fit --input $D/02_cleanse/cleaned.csv --plan $D/03_profile_cleaned/encoding_plan.json --out $D/04_encode
$C --input $D/data/raw_test.csv --out $D/05_cleanse_test --stage all --drop-constant \
  --schema-from $D/02_cleanse/cleaned.schema.json --category-map $D/02_cleanse/stage4_categories/category_map.json \
  --sentinel "年齢=999,月間来店回数=-1" --null-category "会員ランク=不明" --range "$R"
python3 $S/data-encoding/scripts/encode.py apply --input $D/05_cleanse_test/cleaned.csv --state $D/04_encode/encoder_state.json --out $D/06_encode_test
python3 $S/data-visualizing/scripts/visualize_categories.py --input $D/02_cleanse/cleaned.csv --out $D/07_visualize --target 解約
```
