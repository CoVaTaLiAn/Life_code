"""ラウンド16: 収容人数で重み付け（学習の目標を評価指標に揃える）。"""
import pickle
import lib
df = lib.load_all()
RB = {"hist": False, "away_fanbase": True, "region": True, "players": True,
      "drop": ("home_japan", "away_japan", "japan_total"), "season_pos": True, "combo": True}
CB = {"hist": False, "away_fanbase": True, "region": True, "players": True,
      "drop": ("home_japan", "away_japan", "japan_total")}
E = [
    ("R16-01", "Ridge 収容人数^2", "ridge", RB, {"alpha": 20.0}, "cap2", (0,)),
    ("R16-02", "Ridge 収容人数^1", "ridge", RB, {"alpha": 20.0}, "cap1", (0,)),
    ("R16-03", "Ridge 収容人数^0.5", "ridge", RB, {"alpha": 20.0}, "cap05", (0,)),
    ("R16-04", "Ridge 収容人数^1＋後半戦×2", "ridge", RB, {"alpha": 20.0}, "cap1+h2", (0,)),
    ("R16-05", "CatBoost 収容人数^2", "cat", CB, {"depth": 4}, "cap2", (0, 1, 2)),
    ("R16-06", "CatBoost 収容人数^1", "cat", CB, {"depth": 4}, "cap1", (0, 1, 2)),
    ("R16-07", "CatBoost 収容人数^0.5", "cat", CB, {"depth": 4}, "cap05", (0, 1, 2)),
]
for eid, name, model, cfg, params, wt, seeds in E:
    r, p = lib.evaluate(df, cfg, model, "occ", params, seeds=seeds, return_preds=True, weight=wt)
    lib.log(eid, "R16 収容人数の重み", name, name, r, cfg, model, "occ", params, note=f"weight={wt}")
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
