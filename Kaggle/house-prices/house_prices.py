"""House Prices - Advanced Regression Techniques: submission script (v3).

Kaggle notebook: paste this whole file into one cell and run (about 5 min with CV, 1 min without).
  -> writes /kaggle/working/submission.csv
Local: python house_prices.py <folder with train.csv and test.csv>

Final model = equal-weight blend of 4 models (log target):
  1. SVR (rbf)                                   on linear features
  2. Lasso, then GBR on Lasso's residuals        (3 seeds averaged)
  3. Lasso, then LightGBM on Lasso's residuals
  4. GBR (huber loss)                            (3 seeds averaged)
Experiment history and the reasons for each choice: REPORT.md.
"""
import glob
import os
import sys
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import skew
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Lasso
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler
from sklearn.svm import SVR

warnings.filterwarnings("ignore")
RUN_CV = True  # False -> skip the 5-fold check and just make the submission

QUAL = {"None": 0, "Po": 1, "Fa": 2, "TA": 3, "Gd": 4, "Ex": 5}
ORDINAL = {
    "BsmtExposure": {"None": 0, "No": 1, "Mn": 2, "Av": 3, "Gd": 4},
    "BsmtFinType1": {"None": 0, "Unf": 1, "LwQ": 2, "Rec": 3, "BLQ": 4, "ALQ": 5, "GLQ": 6},
    "BsmtFinType2": {"None": 0, "Unf": 1, "LwQ": 2, "Rec": 3, "BLQ": 4, "ALQ": 5, "GLQ": 6},
    "GarageFinish": {"None": 0, "Unf": 1, "RFn": 2, "Fin": 3},
    "Functional": {"Sal": 0, "Sev": 1, "Maj2": 2, "Maj1": 3, "Mod": 4, "Min2": 5, "Min1": 6, "Typ": 7},
    "Fence": {"None": 0, "MnWw": 1, "GdWo": 2, "MnPrv": 3, "GdPrv": 4},
    "PavedDrive": {"N": 0, "P": 1, "Y": 2},
    "LotShape": {"IR3": 0, "IR2": 1, "IR1": 2, "Reg": 3},
    "LandSlope": {"Sev": 0, "Mod": 1, "Gtl": 2},
    "CentralAir": {"N": 0, "Y": 1},
}


def is_num(s):
    return pd.api.types.is_numeric_dtype(s)


def find_data_dir():
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        return sys.argv[1]
    hits = glob.glob("/kaggle/input/**/train.csv", recursive=True)
    return os.path.dirname(hits[0]) if hits else "."


def build_features(train, test):
    train = train[~((train.GrLivArea > 4000) & (train.SalePrice < 300000))]  # 2 known outliers
    y = np.log1p(train.SalePrice.values)
    df = pd.concat([train.drop(columns="SalePrice"), test]).drop(columns="Id").reset_index(drop=True)

    # Missing values: NA mostly means "none".
    none_cols = ["PoolQC", "MiscFeature", "Alley", "Fence", "FireplaceQu", "GarageType", "GarageFinish",
                 "GarageQual", "GarageCond", "BsmtQual", "BsmtCond", "BsmtExposure", "BsmtFinType1",
                 "BsmtFinType2", "MasVnrType"]
    df[none_cols] = df[none_cols].fillna("None")
    zero_cols = ["GarageArea", "GarageCars", "BsmtFinSF1", "BsmtFinSF2", "BsmtUnfSF", "TotalBsmtSF",
                 "BsmtFullBath", "BsmtHalfBath", "MasVnrArea"]
    df[zero_cols] = df[zero_cols].fillna(0)
    df["GarageYrBlt"] = df.GarageYrBlt.fillna(df.YearBuilt)
    df.loc[df.GarageYrBlt > 2010, "GarageYrBlt"] = df.YearBuilt  # typo 2207 in test
    df["LotFrontage"] = df.groupby("Neighborhood").LotFrontage.transform(lambda s: s.fillna(s.median()))
    df = df.drop(columns=["Utilities"])
    for c in df.columns:
        df[c] = df[c].fillna(df[c].median() if is_num(df[c]) else df[c].mode()[0])

    # Ordered categories -> numbers.
    for c in ["ExterQual", "ExterCond", "BsmtQual", "BsmtCond", "HeatingQC", "KitchenQual",
              "FireplaceQu", "GarageQual", "GarageCond", "PoolQC"]:
        df[c] = df[c].map(QUAL).fillna(0)
    for c, m in ORDINAL.items():
        df[c] = df[c].map(m).fillna(0)
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
    df["QualTotalSF"] = df.OverallQual * df.TotalSF
    df["OverallQual2"] = df.OverallQual ** 2
    df["OverallGrade"] = df.OverallQual * df.OverallCond
    df["ExterGrade"] = df.ExterQual * df.ExterCond
    df["KitchenScore"] = df.KitchenAbvGr * df.KitchenQual
    df["GarageScore"] = df.GarageArea * df.GarageQual
    df["FinishedBsmtSF"] = df.BsmtFinSF1 + df.BsmtFinSF2
    df["LivLotRatio"] = df.GrLivArea / df.LotArea
    df["SFPerRoom"] = df.GrLivArea / (df.TotRmsAbvGrd + 1)
    df["IsRemodeled"] = (df.YearRemodAdd != df.YearBuilt).astype(int)
    df["IsNew"] = (df.YrSold == df.YearBuilt).astype(int)
    df["Has2ndFlr"] = (df["2ndFlrSF"] > 0).astype(int)
    df["HasFireplace"] = (df.Fireplaces > 0).astype(int)
    df["HasPool"] = (df.PoolArea > 0).astype(int)
    df["YrMo"] = df.YrSold + df.MoSold.astype(int) / 12.0

    n = len(y)
    cat_cols = [c for c in df.columns if not is_num(df[c])]
    num_cols = [c for c in df.columns if c not in cat_cols]

    # View for linear models / sklearn GBR: log1p skewed numbers, one-hot categories.
    lin = df.copy()
    skewed = [c for c in num_cols if abs(skew(lin[c])) > 0.75 and lin[c].min() >= 0]
    lin[skewed] = np.log1p(lin[skewed])
    lin = pd.get_dummies(lin, columns=cat_cols, dtype=float).values
    # View for LightGBM: native categories.
    tree = df.copy()
    for c in cat_cols:
        tree[c] = tree[c].astype("category")
    return (lin[:n], tree.iloc[:n]), (lin[n:], tree.iloc[n:]), y, test.Id.values


# ---- models: each is fit_predict((Ltr, Ttr), ytr, (Lva, Tva)) -> predictions ----
def lasso_fp(L, y, Lp):
    return make_pipeline(RobustScaler(), Lasso(alpha=0.0005, max_iter=100000)).fit(L, y).predict(Lp)


def gbr(seed, n=3000):
    return GradientBoostingRegressor(n_estimators=n, learning_rate=0.02, max_depth=4, max_features="sqrt",
                                     min_samples_leaf=15, min_samples_split=10, loss="huber",
                                     subsample=0.8, random_state=seed)


def m_svr(X, y, Xp):
    return make_pipeline(RobustScaler(), SVR(C=10, epsilon=0.02, gamma=0.001)).fit(X[0], y).predict(Xp[0])


def m_lasso_gbr(X, y, Xp):
    base_tr, base_p = lasso_fp(X[0], y, X[0]), lasso_fp(X[0], y, Xp[0])
    resid = [gbr(s, 600).fit(X[0], y - base_tr).predict(Xp[0]) for s in (1, 2, 3)]
    return base_p + np.mean(resid, axis=0)


def m_lasso_lgb(X, y, Xp):
    base_tr, base_p = lasso_fp(X[0], y, X[0]), lasso_fp(X[0], y, Xp[0])
    m = lgb.LGBMRegressor(n_estimators=500, learning_rate=0.01, num_leaves=8, min_child_samples=10,
                          subsample=0.7, subsample_freq=1, colsample_bytree=0.3, reg_lambda=1.0,
                          random_state=42, verbose=-1)
    return base_p + m.fit(X[1], y - base_tr).predict(Xp[1])


def m_gbr(X, y, Xp):
    return np.mean([gbr(s).fit(X[0], y).predict(Xp[0]) for s in (1, 2, 3)], axis=0)


MODELS = {"SVR": m_svr, "Lasso+GBR": m_lasso_gbr, "Lasso+LGB": m_lasso_lgb, "GBR": m_gbr}


def take(X, idx):
    return X[0][idx], X[1].iloc[idx]


def rmse(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


def main():
    d = find_data_dir()
    X, Xp, y, ids = build_features(pd.read_csv(os.path.join(d, "train.csv")), pd.read_csv(os.path.join(d, "test.csv")))

    if RUN_CV:
        oof = {k: np.zeros(len(y)) for k in MODELS}
        for tr, va in KFold(5, shuffle=True, random_state=0).split(y):
            for k, f in MODELS.items():
                oof[k][va] = f(take(X, tr), y[tr], take(X, va))
        for k in MODELS:
            print(f"CV RMSE {k:10s}: {rmse(y, oof[k]):.4f}")
        print(f"CV RMSE Blend     : {rmse(y, np.mean(list(oof.values()), axis=0)):.4f}")

    pred = np.mean([f(X, y, Xp) for f in MODELS.values()], axis=0)
    out = os.path.join("/kaggle/working" if os.path.isdir("/kaggle/working") else ".", "submission.csv")
    pd.DataFrame({"Id": ids, "SalePrice": np.expm1(pred)}).to_csv(out, index=False)
    print(f"Wrote {out}  rows={len(pred)}")


if __name__ == "__main__":
    main()
