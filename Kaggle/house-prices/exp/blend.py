"""Blend cached models.  python blend.py name1 name2 ...  [--out submission.csv]

Weights: non-negative, sum to 1. Scored honestly with a second-level CV:
weights are fitted on OOF rows of 4 folds and scored on the 5th, for every repeat.
"""
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import common


def fit_weights(P, y):
    k = P.shape[0]
    f = lambda w: common.rmse(y, w @ P)
    cons = ({"type": "eq", "fun": lambda w: w.sum() - 1},)
    return minimize(f, np.ones(k) / k, bounds=[(0, 1)] * k, constraints=cons, method="SLSQP").x


def main(argv):
    out = None
    if "--out" in argv:
        i = argv.index("--out"); out = argv[i + 1]; argv = argv[:i] + argv[i + 2:]
    oofs, tests, y = [], [], None
    for nm in argv:
        o, t, y = common.load_cache(nm)
        oofs.append(o); tests.append(t)
    O = np.stack(oofs)  # models x repeats x n
    eq = O.mean(0)
    w = fit_weights(O.mean(1), y)
    held = []
    for r, folds in enumerate(common.splits(len(y))):
        p = np.zeros(len(y))
        for tr, va in folds:
            p[va] = fit_weights(O[:, r, tr], y[tr]) @ O[:, r, va]
        held.append(common.rmse(y, p))
    print("models:", " ".join(f"{n}={common.rmse(y, O[i].mean(0)):.5f}" for i, n in enumerate(argv)))
    print(f"equal-weight blend CV : {np.mean([common.rmse(y, eq[r]) for r in range(eq.shape[0])]):.5f}")
    print(f"fitted weights        : " + " ".join(f"{n}={x:.2f}" for n, x in zip(argv, w)))
    print(f"fitted blend CV (nested): {np.mean(held):.5f}")
    if out:
        train, test = common.load()
        pred = np.expm1(w @ np.stack(tests))
        pd.DataFrame({"Id": test.Id.values, "SalePrice": pred}).to_csv(out, index=False)
        print("wrote", out)
    return w


if __name__ == "__main__":
    main(sys.argv[1:])
