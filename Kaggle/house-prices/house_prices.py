"""House Prices - Advanced Regression Techniques: submission script.

Kaggle notebook: paste this whole file into one cell and run.
  -> writes /kaggle/working/submission.csv
Local: python house_prices.py <folder with train.csv and test.csv>
  -> writes submission.csv in the current folder

Approach: log target, a few hand-made features,
Lasso (linear) + LightGBM (trees), blended 50/50. Prints 5-fold CV RMSE (log scale = the LB metric).
"""
import glob
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import skew
from sklearn.linear_model import LassoCV
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler

SEED = 42


def find_data_dir():
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        return sys.argv[1]
    hits = glob.glob("/kaggle/input/**/train.csv", recursive=True)
    if hits:
        return os.path.dirname(hits[0])
    return "."


def build_features(train, test):
    # Remove the 2 famous outliers (huge house, low price) from training.
    train = train[~((train.GrLivArea > 4000) & (train.SalePrice < 300000))]
    y = np.log1p(train.SalePrice.values)
    test_ids = test.Id.values
    df = pd.concat([train.drop(columns="SalePrice"), test]).drop(columns="Id").reset_index(drop=True)

    # NA here means "the house has none of this", not "unknown".
    none_cols = ["PoolQC", "MiscFeature", "Alley", "Fence", "FireplaceQu", "GarageType",
                 "GarageFinish", "GarageQual", "GarageCond", "BsmtQual", "BsmtCond",
                 "BsmtExposure", "BsmtFinType1", "BsmtFinType2", "MasVnrType"]
    df[none_cols] = df[none_cols].fillna("None")
    zero_cols = ["GarageYrBlt", "GarageArea", "GarageCars", "BsmtFinSF1", "BsmtFinSF2",
                 "BsmtUnfSF", "TotalBsmtSF", "BsmtFullBath", "BsmtHalfBath", "MasVnrArea"]
    df[zero_cols] = df[zero_cols].fillna(0)
    df["LotFrontage"] = df.groupby("Neighborhood").LotFrontage.transform(lambda s: s.fillna(s.median()))
    df = df.drop(columns=["Utilities"])  # almost constant
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            df[c] = df[c].fillna(df[c].mode()[0])
        else:
            df[c] = df[c].fillna(df[c].median())

    # Quality words -> numbers (order matters).
    qual = {"None": 0, "Po": 1, "Fa": 2, "TA": 3, "Gd": 4, "Ex": 5}
    for c in ["ExterQual", "ExterCond", "BsmtQual", "BsmtCond", "HeatingQC", "KitchenQual",
              "FireplaceQu", "GarageQual", "GarageCond", "PoolQC"]:
        df[c] = df[c].map(qual).fillna(0)
    df["MSSubClass"] = df.MSSubClass.astype(str)
    df["MoSold"] = df.MoSold.astype(str)

    # Hand-made features.
    df["TotalSF"] = df.TotalBsmtSF + df["1stFlrSF"] + df["2ndFlrSF"]
    df["TotalBath"] = df.FullBath + 0.5 * df.HalfBath + df.BsmtFullBath + 0.5 * df.BsmtHalfBath
    df["TotalPorch"] = df.OpenPorchSF + df.EnclosedPorch + df["3SsnPorch"] + df.ScreenPorch + df.WoodDeckSF
    df["Age"] = df.YrSold - df.YearBuilt
    df["RemodAge"] = df.YrSold - df.YearRemodAdd
    df["QualSF"] = df.OverallQual * df.GrLivArea
    df["HasGarage"] = (df.GarageArea > 0).astype(int)
    df["HasBsmt"] = (df.TotalBsmtSF > 0).astype(int)

    cat_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    num_cols = [c for c in df.columns if c not in cat_cols]

    # Trees: categories as pandas "category" dtype.
    tree = df.copy()
    for c in cat_cols:
        tree[c] = tree[c].astype("category")

    # Linear: un-skew numeric columns, one-hot categories.
    lin = df.copy()
    skewed = [c for c in num_cols if abs(skew(lin[c])) > 0.75 and lin[c].min() >= 0]
    lin[skewed] = np.log1p(lin[skewed])
    lin = pd.get_dummies(lin, columns=cat_cols, dtype=float)

    n = len(y)
    return (lin.iloc[:n].values, lin.iloc[n:].values,
            tree.iloc[:n], tree.iloc[n:], y, test_ids)


def make_lasso():
    return make_pipeline(RobustScaler(), LassoCV(alphas=np.logspace(-4.5, -2, 30), max_iter=50000, cv=5))


LGB_PARAMS = dict(n_estimators=3000, learning_rate=0.01, num_leaves=8, min_child_samples=10,
                  subsample=0.7, subsample_freq=1, colsample_bytree=0.3, reg_lambda=1.0,
                  random_state=SEED, verbose=-1)


def rmse(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


def main():
    data_dir = find_data_dir()
    train = pd.read_csv(os.path.join(data_dir, "train.csv"))
    test = pd.read_csv(os.path.join(data_dir, "test.csv"))
    Xl, Xl_test, Xt, Xt_test, y, test_ids = build_features(train, test)

    # 5-fold CV: out-of-fold predictions for each model.
    oof_lasso, oof_lgb = np.zeros(len(y)), np.zeros(len(y))
    for tr, va in KFold(5, shuffle=True, random_state=SEED).split(Xl):
        oof_lasso[va] = make_lasso().fit(Xl[tr], y[tr]).predict(Xl[va])
        oof_lgb[va] = lgb.LGBMRegressor(**LGB_PARAMS).fit(Xt.iloc[tr], y[tr]).predict(Xt.iloc[va])
    blend = 0.5 * oof_lasso + 0.5 * oof_lgb
    print(f"CV RMSE  Lasso: {rmse(y, oof_lasso):.4f}  LightGBM: {rmse(y, oof_lgb):.4f}  Blend: {rmse(y, blend):.4f}")

    # Refit on all training data and predict test.
    p_lasso = make_lasso().fit(Xl, y).predict(Xl_test)
    p_lgb = lgb.LGBMRegressor(**LGB_PARAMS).fit(Xt, y).predict(Xt_test)
    pred = np.expm1(0.5 * p_lasso + 0.5 * p_lgb)

    out_dir = "/kaggle/working" if os.path.isdir("/kaggle/working") else "."
    path = os.path.join(out_dir, "submission.csv")
    pd.DataFrame({"Id": test_ids, "SalePrice": pred}).to_csv(path, index=False)
    print(f"Wrote {path}  rows={len(pred)}")


if __name__ == "__main__":
    main()
