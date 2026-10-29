"""Run named experiments:  python run.py exp1 exp2 ...   (python run.py list)"""
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")

import lightgbm as lgb
from sklearn.kernel_ridge import KernelRidge
from sklearn.linear_model import ElasticNet, Lasso, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler
from sklearn.svm import SVR

import common
import features as F


# ---- model factories: each returns fit_predict(Xtr, ytr, Xva) ----
def sk(make):
    return lambda Xtr, ytr, Xva: make().fit(Xtr, ytr).predict(Xva)


def lasso(alpha=0.0005):
    return sk(lambda: make_pipeline(RobustScaler(), Lasso(alpha=alpha, max_iter=100000)))


def ridge(alpha=10):
    return sk(lambda: make_pipeline(RobustScaler(), Ridge(alpha=alpha)))


def enet(alpha=0.0005, l1=0.9):
    return sk(lambda: make_pipeline(RobustScaler(), ElasticNet(alpha=alpha, l1_ratio=l1, max_iter=100000)))


def svr(C=20, eps=0.008, gamma=0.0003):
    return sk(lambda: make_pipeline(RobustScaler(), SVR(C=C, epsilon=eps, gamma=gamma)))


def kridge(alpha=0.6, degree=2, coef0=2.5):
    return sk(lambda: make_pipeline(RobustScaler(), KernelRidge(alpha=alpha, kernel="polynomial", degree=degree, coef0=coef0)))


LGB_BASE = dict(n_estimators=3000, learning_rate=0.01, num_leaves=8, min_child_samples=10,
                subsample=0.7, subsample_freq=1, colsample_bytree=0.3, reg_lambda=1.0,
                random_state=42, verbose=-1, n_jobs=4)


def lgbm(**kw):
    return sk(lambda: lgb.LGBMRegressor(**{**LGB_BASE, **kw}))


def xgbm(**kw):
    import xgboost as xgb
    p = dict(n_estimators=3000, learning_rate=0.01, max_depth=3, subsample=0.7, colsample_bytree=0.3,
             min_child_weight=1, reg_lambda=1.0, enable_categorical=True, tree_method="hist", n_jobs=4, random_state=42)
    return sk(lambda: xgb.XGBRegressor(**{**p, **kw}))


def catb(**kw):
    from catboost import CatBoostRegressor

    p = dict(iterations=3000, learning_rate=0.03, depth=6, l2_leaf_reg=3, random_seed=42, verbose=0, thread_count=4)
    p.update(kw)

    def fp(Xtr, ytr, Xva):
        cats = [c for c in Xtr.columns if str(Xtr[c].dtype) == "category"]
        tr = Xtr.copy(); va = Xva.copy()
        for c in cats:
            tr[c] = tr[c].astype(str); va[c] = va[c].astype(str)
        return CatBoostRegressor(cat_features=cats, **p).fit(tr, ytr).predict(va)
    return fp


def gbr(**kw):
    from sklearn.ensemble import GradientBoostingRegressor
    p = dict(n_estimators=3000, learning_rate=0.02, max_depth=4, max_features="sqrt",
             min_samples_leaf=15, min_samples_split=10, loss="huber", subsample=0.8, random_state=42)
    p.update(kw)
    return sk(lambda: GradientBoostingRegressor(**p))


def trim(fp_make, q=0.02):
    """Fit, drop the q share of training rows with largest in-sample residual, refit. Train-side only."""
    def fp(Xtr, ytr, Xva):
        r = np.abs(ytr - fp_make(Xtr, ytr, Xtr))
        keep = r <= np.quantile(r, 1 - q)
        return fp_make(common._take(Xtr, np.where(keep)[0]), ytr[keep], Xva)
    return fp


def huber(eps=1.35, alpha=0.0005):
    from sklearn.linear_model import HuberRegressor
    return sk(lambda: make_pipeline(RobustScaler(), HuberRegressor(epsilon=eps, alpha=alpha, max_iter=5000)))


def offset(fp_make, col="GrLivArea"):
    """Tree predicts log(price) - log(col); add it back. Helps trees with the size trend."""
    def fp(Xtr, ytr, Xva):
        return fp_make(Xtr, ytr - np.log1p(Xtr[col].values), Xva) + np.log1p(Xva[col].values)
    return fp


def hybrid(lin_fp, tree_fp, shrink=1.0, tree_on_lin=False):
    """Linear model first, then tree on its in-fold residuals. X is (Xlin, Xtree)."""
    def fp(Xtr, ytr, Xva):
        (Ltr, Ttr), (Lva, Tva) = Xtr, Xva
        if tree_on_lin:  # tree models that need plain numbers (monotone transforms don't matter to trees)
            Ttr, Tva = Ltr, Lva
        base_tr = lin_fp(Ltr, ytr, Ltr)
        base_va = lin_fp(Ltr, ytr, Lva)
        return base_va + shrink * tree_fp(Ttr, ytr - base_tr, Tva)
    return fp


# ---- experiments: name -> (feature opts, view, model, note) ----
FEAT1 = dict(ordinal=True, extra=True, garage_fix=True)
EXPS = {
    # baseline = the submitted script
    "lasso_v0": ({}, "lin", lasso(), "baseline features, Lasso"),
    "lgb_v0": ({}, "tree", lgbm(), "baseline features, LightGBM"),
    # feature groups one by one (Lasso is fast and sensitive to features)
    "lasso_ord": (dict(ordinal=True), "lin", lasso(), "+ all ordinal maps"),
    "lasso_extra": (dict(extra=True), "lin", lasso(), "+ extra features"),
    "lasso_gfix": (dict(garage_fix=True), "lin", lasso(), "+ GarageYrBlt fix"),
    "lasso_rare": (dict(drop_rare=True), "lin", lasso(), "+ drop rare dummies"),
    "lasso_f1": (FEAT1, "lin", lasso(), "ordinal+extra+gfix"),
    "lasso_f1r": ({**FEAT1, "drop_rare": True}, "lin", lasso(), "f1 + drop rare"),
    "lgb_f1": (FEAT1, "tree", lgbm(), "f1, LightGBM"),
    "ridge_f1": (FEAT1, "lin", ridge(), "f1, Ridge"),
    "enet_f1": (FEAT1, "lin", enet(), "f1, ElasticNet"),
    "svr_f1": (FEAT1, "lin", svr(), "f1, SVR rbf"),
    "krr_f1": (FEAT1, "lin", kridge(), "f1, KernelRidge poly2"),
    "gbr_f1": (FEAT1, "tree_ohe", gbr(), "f1, sklearn GBR huber"),
    "xgb_f1": (FEAT1, "tree", xgbm(), "f1, XGBoost"),
    "cat_f1": (FEAT1, "tree", catb(), "f1, CatBoost"),
    "lasso_f1_t1": (FEAT1, "lin", trim(lasso(), 0.01), "f1, Lasso, trim 1% train"),
    "lasso_f1_t2": (FEAT1, "lin", trim(lasso(), 0.02), "f1, Lasso, trim 2% train"),
    "lasso_f1_t4": (FEAT1, "lin", trim(lasso(), 0.04), "f1, Lasso, trim 4% train"),
    "svr_f1_t2": (FEAT1, "lin", trim(svr(), 0.02), "f1, SVR, trim 2%"),
    "huber_f1": (FEAT1, "lin", huber(), "f1, Huber linear"),
    "svr_f1_tuned": (FEAT1, "lin", svr(10, 0.02, 0.001), "f1, SVR C=10 g=1e-3 eps=.02 (tuned on repeat 0)"),
    "svr_f1_t2b": (FEAT1, "lin", svr(10, 0.02, 0.002), "f1, SVR C=10 g=2e-3"),
    "lgb_f1_off": (FEAT1, "tree", offset(lgbm()), "f1, LightGBM on log(price/GrLivArea)"),
    "lgb_f1_offsf": (FEAT1, "tree", offset(lgbm(), "TotalSF"), "f1, LightGBM on log(price/TotalSF)"),
    "hyb_lasso_lgb": (FEAT1, "both", hybrid(lasso(), lgbm(n_estimators=500, learning_rate=0.01)), "Lasso then LGB on residuals"),
    **{f"hyb_lasso_lgb_n{n}": (FEAT1, "both", hybrid(lasso(), lgbm(n_estimators=n, learning_rate=0.01)), f"Lasso + LGB resid, {n} trees") for n in (250, 1000, 2000)},
    "hyb_lasso_lgb_l4": (FEAT1, "both", hybrid(lasso(), lgbm(n_estimators=1000, learning_rate=0.01, num_leaves=4)), "Lasso + LGB resid, 4 leaves"),
    "hyb_lasso_lgb_l16": (FEAT1, "both", hybrid(lasso(), lgbm(n_estimators=1000, learning_rate=0.01, num_leaves=16, min_child_samples=20)), "Lasso + LGB resid, 16 leaves"),
    "hyb_svr_lgb": (FEAT1, "both", hybrid(svr(10, 0.02, 0.001), lgbm(n_estimators=500, learning_rate=0.01)), "SVR + LGB resid"),
    "hyb_lasso2_lgb": (FEAT1, "both", hybrid(lasso(0.001), lgbm(n_estimators=1000, learning_rate=0.01)), "stronger Lasso + LGB resid"),
    "lasso_rel": ({**FEAT1, "rel": True}, "lin", lasso(), "f1 + neighborhood-relative"),
    "lasso_dec": ({**FEAT1, "decade": True}, "lin", lasso(), "f1 + built decade dummies"),
    "svr_rel": ({**FEAT1, "rel": True}, "lin", svr(10, 0.02, 0.001), "f1 + rel, SVR"),
    "hyb_rel": ({**FEAT1, "rel": True}, "both", hybrid(lasso(), lgbm(n_estimators=1000, learning_rate=0.01)), "f1 + rel, hybrid"),
    "lgb_rel": ({**FEAT1, "rel": True}, "tree", lgbm(), "f1 + rel, LightGBM"),
    "hyb_lasso_gbr": (FEAT1, "both", hybrid(lasso(), gbr(n_estimators=600), tree_on_lin=True), "Lasso + GBR resid"),
    "hyb_lasso_cat": (FEAT1, "both", hybrid(lasso(), catb(iterations=800)), "Lasso + CatBoost resid"),
    "gbr_rel": ({**FEAT1, "rel": True}, "tree_ohe", gbr(), "f1 + rel, GBR"),
    "xgb_rel": ({**FEAT1, "rel": True}, "tree", xgbm(), "f1 + rel, XGBoost"),
    "krr_tuned": (FEAT1, "lin", kridge(3, 3, 5), "f1, KRR alpha=3 deg3 coef0=5"),
    "lasso_f2": ({**FEAT1, "poly": True}, "lin", lasso(), "f1 + squared terms"),
    **{f"lasso_f1_a{a}": (FEAT1, "lin", lasso(a * 1e-4), f"f1, Lasso alpha={a}e-4") for a in (2, 3, 4, 6, 8, 10)},
}


def build_view(fopts, view):
    train, test = common.load()
    df, y, ids, n, o = F.build(train, test, **fopts)
    if view == "lin":
        X, Xt = F.to_linear(df, n, o)
    elif view == "tree_ohe":  # trees that need plain numbers: one-hot, no log transform
        X, Xt = F.to_linear(df, n, {**o, "skew_thr": 1e9})
    elif view == "both":
        L, Lt = F.to_linear(df, n, o)
        T, Tt = F.to_tree(df, n)
        X, Xt = (L, T), (Lt, Tt)
    else:
        X, Xt = F.to_tree(df, n)
    return X, y, Xt


def main(names):
    if names == ["list"]:
        print("\n".join(EXPS)); return
    for nm in names:
        fopts, view, model, note = EXPS[nm]
        X, y, Xt = build_view(fopts, view)
        common.run_cv(nm, model, X, y, Xt, note=note)


if __name__ == "__main__":
    main(sys.argv[1:])
