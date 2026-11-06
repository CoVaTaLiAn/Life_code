"""ラウンド9: アンサンブル。各モデルの予測（preds/*.pkl）を混ぜる。
混ぜる比率は「もう片方の年」で決めて当てはめる（その年の答えを見て比率を決めない）。"""
import itertools
import pickle
from pathlib import Path

import numpy as np
from scipy.optimize import nnls

import lib

df = lib.load_all()
# まだ予測が保存されていない候補を作る
need = [
    ("R09-01", "LightGBM 土台（num_leaves=7）", "lgb", {"hist": False, "away_fanbase": True}, {"num_leaves": 7}, {}),
    ("R09-02", "LightGBM 土台＋ホーム最終戦など＋日程（num_leaves=7）", "lgb",
     {"hist": False, "away_fanbase": True, "season_pos": True, "schedule": True}, {"num_leaves": 7}, {}),
    ("R09-03", "Ridge 土台＋地方（alpha=3）", "ridge", {"hist": False, "away_fanbase": True, "region": True}, {"alpha": 3.0}, {"seeds": (0,)}),
    ("R09-04", "LightGBM 土台（min_child_samples=5）", "lgb", {"hist": False, "away_fanbase": True}, {"min_child_samples": 5}, {}),
]
for eid, name, model, cfg, params, kw in need:
    if Path(f"preds/{eid}.pkl").exists():
        continue
    r, p = lib.evaluate(df, cfg, model, "occ", params, return_preds=True, **kw)
    lib.log(eid, "R09 アンサンブル用の単体モデル", name, name, r, cfg, model, "occ", params)
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))

P = {Path(f).stem: pickle.load(open(f, "rb")) for f in sorted(Path("preds").glob("*.pkl"))}
folds = list(lib.FOLDS)
y = {f: df.loc[P[next(iter(P))][f].index, "y"].values for f in folds}
rmse = lambda a, b: float(np.sqrt(np.mean((a - b) ** 2)))

def blend_score(keys):
    """単純平均と、もう片方の年で決めた重み（非負・合計1）の両方を返す。"""
    avg = {f: rmse(y[f], np.mean([P[k][f].values for k in keys], axis=0)) for f in folds}
    cross = {}
    for f, g in [(folds[0], folds[1]), (folds[1], folds[0])]:
        A = np.column_stack([P[k][g].values for k in keys])
        w, _ = nnls(A, y[g])
        w = w / w.sum() if w.sum() > 0 else np.ones(len(keys)) / len(keys)
        cross[f] = rmse(y[f], np.column_stack([P[k][f].values for k in keys]) @ w)
    return avg, cross

rows = []
keys = list(P)
for n in (1, 2, 3, 4):
    for comb in itertools.combinations(keys, n):
        avg, cross = blend_score(comb)
        rows.append((np.mean(list(avg.values())), np.mean(list(cross.values())), comb, avg))
rows.sort()
print("単純平均の上位10:")
for m, c, comb, avg in rows[:10]:
    print(f"  mean={m:.0f}（{avg[folds[0]]:.0f} / {avg[folds[1]]:.0f}） 重み調整={c:.0f}  {' + '.join(comb)}")
best = rows[0]
lib.log("R09-B1", "R09 アンサンブル", "単純平均の最良: " + " + ".join(best[2]), "予測の単純平均",
        {folds[0]: best[3][folds[0]], folds[1]: best[3][folds[1]], "mean": best[0]}, model="blend", note=" + ".join(best[2]))
