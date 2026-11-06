"""最終モデル: 選んだメンバーを seed 5つで学習し、検証スコアを出してから、test を予測して提出ファイルを作る。

使い方: python3 final.py <名前>   （MEMBERS の中から選ぶ）
出力: ../submit_<名前>.csv（sample_submit と同じ形式）、preds/FINAL_<名前>_*.pkl、experiments.csv に記録
"""
import pickle
import sys

import numpy as np
import pandas as pd

import lib

SEEDS = (0, 1, 2, 3, 4)
RB = {"hist": False, "away_fanbase": True, "region": True, "players": True,
      "drop": ("home_japan", "away_japan", "japan_total"), "season_pos": True, "combo": True}
CB = {"hist": False, "away_fanbase": True, "region": True, "players": True,
      "drop": ("home_japan", "away_japan", "japan_total")}
LB = {"hist": False, "away_fanbase": True, "players": True, "season_pos": True, "schedule": True}

# (表示名, モデル, 特徴量, パラメータ, 重み)
M = {
    "cat": ("CatBoost depth=4", "cat", CB, {"depth": 4}, None),
    "cat_cap2": ("CatBoost depth=4・収容人数^2", "cat", CB, {"depth": 4}, "cap2"),
    "ridge_h2": ("Ridge alpha=20・後半戦×2", "ridge", RB, {"alpha": 20.0}, "h2"),
    "ridge_cap1h2": ("Ridge alpha=20・収容人数^1＋後半戦×2", "ridge", RB, {"alpha": 20.0}, "cap1+h2"),
    "ridge_cap2": ("Ridge alpha=20・収容人数^2", "ridge", RB, {"alpha": 20.0}, "cap2"),
    "lgb_cap1": ("LightGBM num_leaves=7・収容人数^1", "lgb", LB, {"num_leaves": 7}, "cap1"),
}
MEMBERS = {
    "cat2_ridge2": ["cat", "cat_cap2", "ridge_h2", "ridge_cap1h2"],
    "cat2_ridge2_lgb": ["cat", "cat_cap2", "ridge_h2", "ridge_cap1h2", "lgb_cap1"],
    "best3": ["cat", "ridge_h2", "ridge_cap2"],
}


def main(name):
    df = lib.load_all()
    keys = MEMBERS[name]
    val, test = {}, {}
    for k in keys:
        label, model, cfg, params, wt = M[k]
        seeds = SEEDS if model != "ridge" else (0,)
        r, p = lib.evaluate(df, cfg, model, "occ", params, seeds=seeds, return_preds=True, weight=wt)
        lib.log(f"FINAL-{name}-{k}", "最終モデルの部品（seed 5つ）", label, label, r, cfg, model, "occ", params,
                note=f"weight={wt}")
        val[k] = p
        test[k] = lib.predict_test(df, cfg, model, "occ", params, seeds=seeds, weight=wt)
        pickle.dump({"val": p, "test": test[k]}, open(f"preds/FINAL_{name}_{k}.pkl", "wb"))
    # 単純平均
    res = {}
    for f in lib.FOLDS:
        p = np.mean([val[k][f].values for k in keys], axis=0)
        y = df.loc[val[keys[0]][f].index, "y"].values
        res[f] = float(np.sqrt(np.mean((y - p) ** 2)))
    res["mean"] = float(np.mean([res[f] for f in lib.FOLDS]))
    lib.log(f"FINAL-{name}", "最終モデル（単純平均）", " + ".join(M[k][0] for k in keys),
            "最終候補のアンサンブル（seed 5つ）", res, model="blend", note=" + ".join(keys))
    pred = np.mean([test[k].values for k in keys], axis=0)
    sub = pd.DataFrame({"id": df.loc[test[keys[0]].index, "id"].values, "y": pred})
    ss = pd.read_csv(lib.D / "sample_submit.csv", header=None, names=["id", "_"])
    out = ss[["id"]].merge(sub, on="id", how="left")
    assert len(out) == 313 and out["y"].notna().all()
    out.to_csv(lib.ROOT / f"submit_{name}.csv", header=False, index=False)
    print("saved", lib.ROOT / f"submit_{name}.csv", out["y"].describe().round(0).to_dict())


if __name__ == "__main__":
    main(sys.argv[1])
