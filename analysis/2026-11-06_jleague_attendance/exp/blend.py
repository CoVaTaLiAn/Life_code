"""保存済みの予測（preds/*.pkl）の組み合わせを単純平均で評価する。
使い方: python3 blend.py <記録ID> [使う予測の接頭辞...]"""
import itertools
import pickle
import sys
from pathlib import Path

import numpy as np

import lib

eid = sys.argv[1]
prefixes = sys.argv[2:] or [""]
df = lib.load_all()
P = {Path(f).stem: pickle.load(open(f, "rb")) for f in sorted(Path("preds").glob("*.pkl"))
     if any(Path(f).stem.startswith(x) for x in prefixes)}
folds = list(lib.FOLDS)
y = {f: df.loc[next(iter(P.values()))[f].index, "y"].values for f in folds}
rmse = lambda a, b: float(np.sqrt(np.mean((a - b) ** 2)))
rows = []
for n in range(1, 5):
    for comb in itertools.combinations(P, n):
        s = {f: rmse(y[f], np.mean([P[k][f].values for k in comb], axis=0)) for f in folds}
        rows.append((np.mean(list(s.values())), s, comb))
rows.sort(key=lambda r: r[0])
print(f"候補 {len(P)} 個、組み合わせ {len(rows)} 通り。上位10:")
for m, s, comb in rows[:10]:
    print(f"  mean={m:.0f}（{s[folds[0]]:.0f} / {s[folds[1]]:.0f}）  {' + '.join(comb)}")
m, s, comb = rows[0]
lib.log(eid, "アンサンブル", "単純平均の最良: " + " + ".join(comb), f"候補 {len(P)} 個から1〜4個の単純平均",
        {**s, "mean": m}, model="blend", note=" + ".join(comb))
