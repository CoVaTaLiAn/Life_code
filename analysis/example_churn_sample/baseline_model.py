#!/usr/bin/env python3
"""初期モデル（特徴量エンジニアリング込み）。

eda_baseline.py の出力（cleaned_train.csv, y.csv, results.json, cleaned_test.csv）と同じフォルダに置いて実行する:
    python3 baseline_model.py

やっていること:
  1. クレンジング済みデータを読む
  2. add_features() で特徴量を足す（← ここを育てていく）
  3. 「特徴量を足す前」と「足した後」を同じ交差検証の分割で比べる
  4. 重要度を model_importance.csv に、テストがあれば予測を submission.csv に保存する

必要: pandas numpy scikit-learn lightgbm
"""
import json
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn import metrics as skm
from sklearn.model_selection import GroupKFold, KFold, StratifiedGroupKFold, StratifiedKFold, TimeSeriesSplit, train_test_split

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
R = json.loads((HERE / "results.json").read_text())
TARGET, TASK, KINDS, PRIMARY = R["target"], R["task"], R["kinds"], R["primary"]
SEED, N_SPLITS = 42, 5
DROP = set(R["ids"]) | {TARGET} | ({R["group"]} if R.get("group") else set())

PARAMS = dict(n_estimators=5000, learning_rate=0.03, num_leaves=31, min_child_samples=20,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
              random_state=SEED, verbose=-1)


# ------------------------------------------------------------------ 特徴量
def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """特徴量エンジニアリング。train と test の両方に同じ処理がかかる。

    - 目的変数を使う処理（target encoding など）はここに書かない（リークする）。
    - 日時の列は datetime 型、カテゴリは文字列で入ってくる。
    - 新しく作った列は自動でモデルに入る（数値はそのまま、文字列はカテゴリ扱い）。
    """
    df = df.copy()
    # 1. 欠損コードの扱い: 年齢 999 は欠損とみなす
    df["年齢"] = df["年齢"].where(df["年齢"] != 999)
    # 2. 欠損そのものが情報: 利用GB が欠損の顧客は全員解約していた
    df["利用GB_欠損"] = df["月間利用GB"].isna().astype(int)
    # 3. 重複情報の削除: 利用GB_MB換算 は 月間利用GB × 1024
    df = df.drop(columns=["利用GB_MB換算"])
    # 4. 表記ゆれ（意味的に同じ）: プレミアム と Premium
    df["プラン"] = df["プラン"].replace({"プレミアム": "Premium"})
    # 5. 比: 契約期間あたりの問い合わせ回数（不満の強さ）
    df["問い合わせ_per_月"] = df["問い合わせ回数"] / (df["契約月数"] + 1)
    # 6. グループ集約: 同じプランの平均料金との差（割高感）
    df["プラン内_料金差"] = df["月額料金"] - df.groupby("プラン")["月額料金"].transform("mean")
    return df


# ------------------------------------------------------------------ 以下は通常いじらなくてよい
def load(name):
    df = pd.read_csv(HERE / name, low_memory=False)
    for c, k in KINDS.items():
        if c not in df:
            continue
        if k == "datetime":
            df[c] = pd.to_datetime(df[c], errors="coerce")
        elif k in ("category", "text"):
            df[c] = df[c].astype("string")
    return df


def to_matrix(df, levels=None):
    """モデルに入れる行列を作る。日時は分解、文字列はカテゴリ型、テキストは文字数。"""
    X = pd.DataFrame(index=df.index)
    fit = levels is None
    levels = {} if fit else levels
    for c in df.columns:
        if c in DROP:
            continue
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            X[f"{c}__year"], X[f"{c}__month"], X[f"{c}__dow"] = s.dt.year, s.dt.month, s.dt.dayofweek
            X[f"{c}__days"] = (s - pd.Timestamp("1970-01-01")).dt.days
            if (s.dropna().dt.hour != 0).mean() > 0.05:
                X[f"{c}__hour"] = s.dt.hour
        elif KINDS.get(c) == "text":
            X[f"{c}__len"] = s.str.len()
        elif pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            X[c] = s.astype(float)
        else:
            if fit:
                levels[c] = list(s.value_counts().index[:200])
            v = s.where(s.isin(levels[c]) | s.isna(), "__other__")
            X[c] = pd.Categorical(v, categories=levels[c] + ["__other__"])
    num = X.select_dtypes(exclude="category").columns
    X[num] = X[num].astype(float).replace([np.inf, -np.inf], np.nan)
    return X, levels


def splits(df, y):
    idx = np.arange(len(df))
    if R.get("time_col"):
        order = np.argsort(df[R["time_col"]].values, kind="stable")
        return [(order[a], order[b]) for a, b in TimeSeriesSplit(N_SPLITS).split(order)]
    if R.get("group"):
        g = df[R["group"]].astype(str).values
        sp = StratifiedGroupKFold(N_SPLITS, shuffle=True, random_state=SEED) if TASK != "regression" else GroupKFold(N_SPLITS)
        return list(sp.split(idx, y, g))
    if TASK != "regression" and np.bincount(y).min() >= 2:
        k = min(N_SPLITS, np.bincount(y).min())
        return list(StratifiedKFold(k, shuffle=True, random_state=SEED).split(idx, y))
    return list(KFold(N_SPLITS, shuffle=True, random_state=SEED).split(idx))


def predict(m, X):
    if TASK == "regression":
        return m.predict(X)
    p = m.predict_proba(X)
    return p[:, 1] if TASK == "binary" else p


def score(y, p):
    if TASK == "binary":
        return {"auc": skm.roc_auc_score(y, p), "pr_auc": skm.average_precision_score(y, p),
                "logloss": skm.log_loss(y, np.clip(p, 1e-7, 1 - 1e-7)), "accuracy": skm.accuracy_score(y, p >= .5),
                "f1": skm.f1_score(y, p >= .5)}
    if TASK == "multiclass":
        return {"accuracy": skm.accuracy_score(y, p.argmax(1)), "macro_f1": skm.f1_score(y, p.argmax(1), average="macro"),
                "logloss": skm.log_loss(y, np.clip(p, 1e-7, 1), labels=list(range(p.shape[1])))}
    out = {"rmse": skm.mean_squared_error(y, p) ** .5, "mae": skm.mean_absolute_error(y, p), "r2": skm.r2_score(y, p)}
    if y.min() >= 0:
        out["rmsle"] = skm.mean_squared_error(np.log1p(y), np.log1p(np.clip(p, 0, None))) ** .5
    return out


def cv(df, y, sp, name):
    X, _ = to_matrix(df)
    Model = lgb.LGBMRegressor if TASK == "regression" else lgb.LGBMClassifier
    folds, imps, iters = [], [], []
    params = {**PARAMS, "min_child_samples": int(max(5, min(20, len(X) // 100)))}  # eda_baseline.py と同じ設定
    for tr, va in sp:
        # 早期終了用に学習foldの15%を取り分ける（検証foldは使わない）
        strat = y[tr] if TASK != "regression" and np.bincount(y[tr]).min() >= 2 else None
        fit, es = train_test_split(tr, test_size=0.15, random_state=SEED, stratify=strat)
        m = Model(**params)
        m.fit(X.iloc[fit], y[fit], eval_set=[(X.iloc[es], y[es])],
              callbacks=[lgb.early_stopping(100, verbose=False)])
        folds.append(score(y[va], predict(m, X.iloc[va])))
        imps.append(pd.Series(m.booster_.feature_importance("gain"), index=X.columns))
        iters.append(m.best_iteration_)
    f = pd.DataFrame(folds)
    imp = pd.concat(imps, axis=1).mean(axis=1)
    print(f"[{name}] 特徴量 {X.shape[1]}列  " + "  ".join(f"{k}={f[k].mean():.4f}±{f[k].std():.4f}" for k in f))
    return f.mean(), (imp / imp.sum()).sort_values(ascending=False), int(np.mean(iters))


def main():
    df = load("cleaned_train.csv")
    y = pd.read_csv(HERE / "y.csv")["y"].values
    if TASK != "regression":
        y = y.astype(int)
    sp = splits(df, y)
    base, _, _ = cv(df, y, sp, "特徴量追加前")
    dfe = add_features(df)
    new_cols = [c for c in dfe.columns if c not in df.columns]
    after, imp, n_iter = cv(dfe, y, sp, "特徴量追加後")
    d = after[PRIMARY] - base[PRIMARY]
    better = d > 0 if PRIMARY in ("auc", "pr_auc", "accuracy", "f1", "macro_f1", "r2") else d < 0
    print(f"\n{PRIMARY}: {base[PRIMARY]:.4f} → {after[PRIMARY]:.4f}（{d:+.4f}, {'変化なし' if abs(d) < 1e-9 else ('改善' if better else '悪化')}）")
    if new_cols:
        print("追加した列の重要度: " + ", ".join(f"{c}={imp.get(c, 0):.1%}" for c in new_cols))
    imp.rename("importance").to_csv(HERE / "model_importance.csv")
    pd.DataFrame({"追加前": base, "追加後": after}).to_csv(HERE / "model_scores.csv")

    if (HERE / "cleaned_test.csv").exists():
        te = add_features(load("cleaned_test.csv"))
        X, lv = to_matrix(dfe)
        Xt, _ = to_matrix(te, lv)
        Model = lgb.LGBMRegressor if TASK == "regression" else lgb.LGBMClassifier
        m = Model(**{**PARAMS, "min_child_samples": int(max(5, min(20, len(X) // 100))),
                     "n_estimators": int(max(50, n_iter * 1.1))}).fit(X, y)
        p = predict(m, Xt[X.columns])
        sub = te[[c for c in R["ids"] if c in te]].copy()
        if TASK == "multiclass":
            for i, c in enumerate(R["classes"]):
                sub[f"prob_{c}"] = p[:, i]
        else:
            sub[TARGET if TASK == "regression" else f"prob_{R['positive']}"] = p
        sub.to_csv(HERE / "submission.csv", index=False)
        print(f"テスト予測を保存: {HERE / 'submission.csv'}")


if __name__ == "__main__":
    main()
