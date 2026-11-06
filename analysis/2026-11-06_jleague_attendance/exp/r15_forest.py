"""ラウンド15: ランダムフォレスト・ExtraTrees（アンサンブルの多様性のため）。"""
import pickle
import lib
df = lib.load_all()
C = {"hist": False, "away_fanbase": True, "region": True, "players": True,
     "drop": ("home_japan", "away_japan", "japan_total"), "season_pos": True}
E = [
    ("R15-01", "ランダムフォレスト leaf=3 max_features=0.5", "rf", {}),
    ("R15-02", "ランダムフォレスト leaf=1 max_features=0.3", "rf", {"min_samples_leaf": 1, "max_features": 0.3}),
    ("R15-03", "ExtraTrees leaf=3 max_features=0.5", "et", {}),
    ("R15-04", "ExtraTrees leaf=1 max_features=0.7", "et", {"min_samples_leaf": 1, "max_features": 0.7}),
]
for eid, name, model, params in E:
    r, p = lib.evaluate(df, C, model, "occ", params, seeds=(0,), return_preds=True)
    lib.log(eid, "R15 フォレスト", name, name, r, C, model, "occ", params)
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
