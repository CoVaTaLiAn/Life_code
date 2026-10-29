"""Shared pieces for experiments: data loading, fixed CV splits, OOF caching, logging."""
import json
import os
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("HP_DATA", os.path.join(HERE, "..", "data"))
CACHE = os.path.join(HERE, "cache")
LOG = os.path.join(HERE, "results.jsonl")
os.makedirs(CACHE, exist_ok=True)

N_SPLITS, SEEDS = 5, (0, 1, 2)  # 5-fold x 3 repeats -> less noisy CV


def load():
    train = pd.read_csv(os.path.join(DATA_DIR, "train.csv"))
    test = pd.read_csv(os.path.join(DATA_DIR, "test.csv"))
    return train, test


def splits(n):
    out = []
    for s in SEEDS:
        out.append(list(KFold(N_SPLITS, shuffle=True, random_state=s).split(np.arange(n))))
    return out


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def run_cv(name, fit_predict, X, y, X_test, note="", fit_full=True):
    """fit_predict(Xtr, ytr, Xva) -> preds. Returns OOF (repeats x n) and test pred.

    OOF + test preds are cached by name so blends can reuse them.
    """
    t0 = time.time()
    n = len(y)
    oof = np.zeros((len(SEEDS), n))
    for r, folds in enumerate(splits(n)):
        for tr, va in folds:
            oof[r, va] = fit_predict(_take(X, tr), y[tr], _take(X, va))
    scores = [rmse(y, oof[r]) for r in range(len(SEEDS))]
    test_pred = fit_predict(X, y, X_test) if fit_full else None
    np.savez(os.path.join(CACHE, f"{name}.npz"), oof=oof, test=test_pred if test_pred is not None else np.array([]), y=y)
    rec = dict(name=name, cv=round(float(np.mean(scores)), 5), std=round(float(np.std(scores)), 5),
               sec=round(time.time() - t0, 1), note=note)
    with open(LOG, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"{name:32s} CV {rec['cv']:.5f} ±{rec['std']:.5f}  ({rec['sec']}s)  {note}", flush=True)
    return oof, test_pred


def _take(X, idx):
    if isinstance(X, tuple):
        return tuple(_take(x, idx) for x in X)
    return X.iloc[idx] if hasattr(X, "iloc") else X[idx]


def load_cache(name):
    d = np.load(os.path.join(CACHE, f"{name}.npz"))
    return d["oof"], d["test"], d["y"]
