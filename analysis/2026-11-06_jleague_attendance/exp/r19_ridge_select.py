"""ラウンド19: Ridge の後退選択。1列ずつ外して、両方の年で良くなる列だけを順に外す（最大6回）。
片方の年だけ良くなる列は外さない（たまたまの改善を拾わないため）。"""
import pickle
import lib
df = lib.load_all()
cfg = {"hist": False, "away_fanbase": False, "region": True, "players": True,
       "drop": ("home_japan", "away_japan", "japan_total"), "season_pos": True, "combo": True}
P = {"alpha": 20.0}
W = "cap1+h2"
base = lib.evaluate(df, cfg, "ridge", "occ", P, seeds=(0,), weight=W)
print("start", {k: round(v) for k, v in base.items()}, flush=True)
cols = list(lib.build_features(df, lib.FOLDS["H2_2013"], cfg).columns)
dropped = list(cfg["drop"])
for step in range(1, 7):
    best = None
    for c in cols:
        if c in dropped or c == "capacity":
            continue
        r = lib.evaluate(df, {**cfg, "drop": tuple(dropped + [c])}, "ridge", "occ", P, seeds=(0,), weight=W)
        if r["H2_2012"] < base["H2_2012"] and r["H2_2013"] < base["H2_2013"]:
            if best is None or r["mean"] < best[1]["mean"]:
                best = (c, r)
    if best is None:
        print("両方の年で良くなる列はもうない", flush=True)
        break
    dropped.append(best[0])
    base = best[1]
    c2 = {**cfg, "drop": tuple(dropped)}
    lib.log(f"R19-{step:02d}", "R19 Ridge 後退選択", f"−{best[0]}", f"外した列: {', '.join(dropped[3:])}", base, c2, "ridge", "occ", P,
            note=f"weight={W}")
r, p = lib.evaluate(df, {**cfg, "drop": tuple(dropped)}, "ridge", "occ", P, seeds=(0,), return_preds=True, weight=W)
pickle.dump(p, open("preds/R19-final.pkl", "wb"))
print("final drop:", dropped, {k: round(v) for k, v in r.items()})
