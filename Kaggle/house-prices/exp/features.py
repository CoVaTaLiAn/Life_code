"""Feature builder. Options let experiments switch feature groups on/off.

opts:
  outliers   : "two" (GrLivArea>4000 & cheap) | "none"
  ordinal    : True -> map all ordered categories to numbers (not only Qual/Cond)
  extra      : True -> extra hand-made features (interactions, flags)
  garage_fix : True -> GarageYrBlt missing -> YearBuilt (instead of 0)
  skew_thr   : skew threshold for log1p on linear features
  drop_rare  : True -> drop near-constant dummy columns for the linear model
"""
import numpy as np
import pandas as pd
from scipy.stats import skew

QUAL = {"None": 0, "Po": 1, "Fa": 2, "TA": 3, "Gd": 4, "Ex": 5}
QUAL_COLS = ["ExterQual", "ExterCond", "BsmtQual", "BsmtCond", "HeatingQC", "KitchenQual",
             "FireplaceQu", "GarageQual", "GarageCond", "PoolQC"]
ORDINAL_EXTRA = {
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
NONE_COLS = ["PoolQC", "MiscFeature", "Alley", "Fence", "FireplaceQu", "GarageType",
             "GarageFinish", "GarageQual", "GarageCond", "BsmtQual", "BsmtCond",
             "BsmtExposure", "BsmtFinType1", "BsmtFinType2", "MasVnrType"]
ZERO_COLS = ["GarageArea", "GarageCars", "BsmtFinSF1", "BsmtFinSF2",
             "BsmtUnfSF", "TotalBsmtSF", "BsmtFullBath", "BsmtHalfBath", "MasVnrArea"]

DEFAULT = dict(outliers="two", ordinal=False, extra=False, garage_fix=False, skew_thr=0.75, drop_rare=False, poly=False, nbhd=False, rel=False, decade=False)


def is_num(s):
    return pd.api.types.is_numeric_dtype(s)


def build(train, test, **kw):
    o = {**DEFAULT, **kw}
    if o["outliers"] == "two":
        train = train[~((train.GrLivArea > 4000) & (train.SalePrice < 300000))]
    y = np.log1p(train.SalePrice.values)
    test_ids = test.Id.values
    df = pd.concat([train.drop(columns="SalePrice"), test]).drop(columns="Id").reset_index(drop=True)

    df[NONE_COLS] = df[NONE_COLS].fillna("None")
    df[ZERO_COLS] = df[ZERO_COLS].fillna(0)
    if o["garage_fix"]:
        df["GarageYrBlt"] = df.GarageYrBlt.fillna(df.YearBuilt)
        df.loc[df.GarageYrBlt > 2010, "GarageYrBlt"] = df.YearBuilt  # one typo (2207) in test
    else:
        df["GarageYrBlt"] = df.GarageYrBlt.fillna(0)
    df["LotFrontage"] = df.groupby("Neighborhood").LotFrontage.transform(lambda s: s.fillna(s.median()))
    df = df.drop(columns=["Utilities"])
    for c in df.columns:
        df[c] = df[c].fillna(df[c].median() if is_num(df[c]) else df[c].mode()[0])

    for c in QUAL_COLS:
        df[c] = df[c].map(QUAL).fillna(0)
    if o["ordinal"]:
        for c, m in ORDINAL_EXTRA.items():
            df[c] = df[c].map(m).fillna(0)
    df["MSSubClass"] = df.MSSubClass.astype(str)
    df["MoSold"] = df.MoSold.astype(str)

    df["TotalSF"] = df.TotalBsmtSF + df["1stFlrSF"] + df["2ndFlrSF"]
    df["TotalBath"] = df.FullBath + 0.5 * df.HalfBath + df.BsmtFullBath + 0.5 * df.BsmtHalfBath
    df["TotalPorch"] = df.OpenPorchSF + df.EnclosedPorch + df["3SsnPorch"] + df.ScreenPorch + df.WoodDeckSF
    df["Age"] = df.YrSold - df.YearBuilt
    df["RemodAge"] = df.YrSold - df.YearRemodAdd
    df["QualSF"] = df.OverallQual * df.GrLivArea
    df["HasGarage"] = (df.GarageArea > 0).astype(int)
    df["HasBsmt"] = (df.TotalBsmtSF > 0).astype(int)

    if o["extra"]:
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

    if o["poly"]:
        for c in ["OverallQual", "GrLivArea", "TotalSF", "GarageCars", "TotalBath", "ExterQual", "KitchenQual", "Age"]:
            v = np.log1p(df[c]) if c in ("GrLivArea", "TotalSF") else df[c]
            df[c + "_sq"] = v ** 2
    if o["rel"]:
        # how this house compares with others in the same neighborhood (no price used)
        g = df.groupby("Neighborhood")
        for c in ["GrLivArea", "TotalSF", "OverallQual", "LotArea", "YearBuilt"]:
            df[c + "_rel"] = df[c] - g[c].transform("median")
        df["NbhdQual"] = g.OverallQual.transform("mean")
        df["NbhdSF"] = g.TotalSF.transform("median")
    if o["decade"]:
        df["BuiltDecade"] = (df.YearBuilt // 10 * 10).astype(str)
    if o["nbhd"]:
        # neighborhood "price tier" from train medians (target-derived; 25 groups, mild leak in CV)
        med = pd.Series(y).groupby(df.Neighborhood.iloc[:len(y)].values).median()
        df["NbhdTier"] = df.Neighborhood.map(med).fillna(med.median())
    return df, y, test_ids, len(y), o


def to_tree(df, n):
    t = df.copy()
    for c in t.columns:
        if not is_num(t[c]):
            t[c] = t[c].astype("category")
    return t.iloc[:n], t.iloc[n:]


def to_linear(df, n, o):
    lin = df.copy()
    cat_cols = [c for c in lin.columns if not is_num(lin[c])]
    num_cols = [c for c in lin.columns if c not in cat_cols]
    skewed = [c for c in num_cols if abs(skew(lin[c])) > o["skew_thr"] and lin[c].min() >= 0]
    lin[skewed] = np.log1p(lin[skewed])
    lin = pd.get_dummies(lin, columns=cat_cols, dtype=float)
    if o["drop_rare"]:
        keep = [c for c in lin.columns if lin[c].iloc[:n].nunique() > 1 and
                (lin[c].iloc[:n] != lin[c].iloc[:n].mode()[0]).sum() >= 5]
        lin = lin[keep]
    return lin.iloc[:n].values, lin.iloc[n:].values
