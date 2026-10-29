# House Prices - Advanced Regression Techniques

https://www.kaggle.com/competitions/house-prices-advanced-regression-techniques

## 提出手順（Kaggle Notebook）
1. コンペページ → **Code** → **New Notebook**（データは自動で追加される）
2. `house_prices.py` の中身を全部コピーして1つのセルに貼り、実行（CV込みで数分。急ぐときは `RUN_CV = False`）
3. 右上 **Save Version** → 「Save & Run All (Commit)」
4. 実行が終わったら、Notebook の **Output** タブ → `submission.csv` → **Submit**

## 中身（v3）
SVR、Lasso→GBR残差補正、Lasso→LightGBM残差補正、GBR の4モデル均等ブレンド。
手元 CV（5-fold×3回）: v1 0.1091 → **v3 0.1056**。経緯は [REPORT.md](REPORT.md)。
