"""ラウンド10: Optuna でパラメータ探索。探索中は seed 1つ、上位3つを seed 3つで測り直す。
使い方: python3 r10_optuna.py cat 40   /  python3 r10_optuna.py lgb 60"""
import json
import pickle
import sys

import optuna

import lib

optuna.logging.set_verbosity(optuna.logging.WARNING)
model, n_trials = sys.argv[1], int(sys.argv[2])
df = lib.load_all()
if model == "cat":
    cfg = {"hist": False, "away_fanbase": True, "region": True, "players": True,
           "drop": ("home_japan", "away_japan", "japan_total")}
else:
    cfg = {"hist": False, "away_fanbase": True, "players": True}
tag = "R10" if model == "cat" else "R11"


def space(t):
    if model == "cat":
        return dict(depth=t.suggest_int("depth", 3, 7), learning_rate=t.suggest_float("learning_rate", 0.02, 0.2, log=True),
                    l2_leaf_reg=t.suggest_float("l2_leaf_reg", 0.5, 30, log=True),
                    random_strength=t.suggest_float("random_strength", 0.1, 10, log=True),
                    bagging_temperature=t.suggest_float("bagging_temperature", 0, 2),
                    one_hot_max_size=t.suggest_categorical("one_hot_max_size", [2, 4, 10]))
    return dict(num_leaves=t.suggest_int("num_leaves", 3, 31), min_child_samples=t.suggest_int("min_child_samples", 3, 40),
                learning_rate=t.suggest_float("learning_rate", 0.01, 0.1, log=True),
                colsample_bytree=t.suggest_float("colsample_bytree", 0.4, 1.0),
                subsample=t.suggest_float("subsample", 0.5, 1.0), reg_lambda=t.suggest_float("reg_lambda", 1e-3, 30, log=True),
                cat_smooth=t.suggest_float("cat_smooth", 1, 50, log=True),
                min_data_per_group=t.suggest_int("min_data_per_group", 5, 100, log=True))


def objective(t):
    p = space(t)
    r = lib.evaluate(df, cfg, model, "occ", p, seeds=(0,))
    lib.log(f"{tag}-T{t.number:03d}", f"{tag} Optuna {model}（探索・seed1つ）", f"trial {t.number}", "Optuna の試行",
            r, cfg, model, "occ", p)
    t.set_user_attr("r", r)
    return r["mean"]


st = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=0))
st.optimize(objective, n_trials=n_trials)
top = sorted([t for t in st.trials if t.value is not None], key=lambda t: t.value)[:3]
for i, t in enumerate(top, 1):
    p = space(optuna.trial.FixedTrial(t.params))
    r, pr = lib.evaluate(df, cfg, model, "occ", p, return_preds=True)
    lib.log(f"{tag}-B{i}", f"{tag} Optuna {model}（上位を seed3つで再評価）", f"探索 {i} 位（trial {t.number}）",
            "Optuna の上位設定を seed 3つで測り直し", r, cfg, model, "occ", p)
    pickle.dump(pr, open(f"preds/{tag}-B{i}.pkl", "wb"))
json.dump([t.params for t in top], open(f"{tag}_top_params.json", "w"), ensure_ascii=False, indent=1)
