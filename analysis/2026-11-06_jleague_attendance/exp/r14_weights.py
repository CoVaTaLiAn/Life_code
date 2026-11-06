"""ラウンド14: 学習データの重み付け（後半戦を重く／新しいシーズンを重く）。"""
import pickle
import lib
df = lib.load_all()
RB = {"hist": False, "away_fanbase": True, "region": True, "players": True,
      "drop": ("home_japan", "away_japan", "japan_total"), "season_pos": True, "combo": True}
CB = {"hist": False, "away_fanbase": True, "region": True, "players": True,
      "drop": ("home_japan", "away_japan", "japan_total")}
E = [
    ("R14-01", "Ridge 後半戦×2", "ridge", RB, {"alpha": 20.0}, "h2", (0,)),
    ("R14-02", "Ridge 新しいシーズンほど重く", "ridge", RB, {"alpha": 20.0}, "recent", (0,)),
    ("R14-03", "Ridge 両方", "ridge", RB, {"alpha": 20.0}, "h2+recent", (0,)),
    ("R14-04", "CatBoost 後半戦×2", "cat", CB, {"depth": 4}, "h2", (0, 1, 2)),
    ("R14-05", "CatBoost 新しいシーズンほど重く", "cat", CB, {"depth": 4}, "recent", (0, 1, 2)),
]
for eid, name, model, cfg, params, wt, seeds in E:
    r, p = lib.evaluate(df, cfg, model, "occ", params, seeds=seeds, return_preds=True, weight=wt)
    lib.log(eid, "R14 重み付け", name, name, r, cfg, model, "occ", params, note=f"weight={wt}")
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
