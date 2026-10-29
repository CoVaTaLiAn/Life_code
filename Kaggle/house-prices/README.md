# House Prices - Advanced Regression Techniques

https://www.kaggle.com/competitions/house-prices-advanced-regression-techniques

## 提出手順（Kaggle Notebook）
1. コンペページ → **Code** → **New Notebook**（データは自動で追加される）
2. `house_prices.py` の中身を全部コピーして1つのセルに貼り、実行（約15秒）
3. 右上 **Save Version** → 「Save & Run All (Commit)」
4. 実行が終わったら、Notebook の **Output** タブ → `submission.csv` → **Submit**

## 中身
- 目的変数は `log1p(SalePrice)`（評価指標が対数 RMSE のため）
- 外れ値2件を除外、欠損埋め、品質ランクの数値化、合計面積などの特徴量
- Lasso（線形）+ LightGBM（木）を 50/50 でブレンド

## 手元での CV（5-fold, 対数 RMSE）
| Lasso | LightGBM | Blend |
|---|---|---|
| 0.1125 | 0.1163 | 0.1096 |
