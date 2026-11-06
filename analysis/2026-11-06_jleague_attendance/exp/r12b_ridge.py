"""ラウンド12b: Ridge の alpha と特徴量の組み合わせ。"""
import pickle
import lib
df = lib.load_all()
B = {"hist": False, "away_fanbase": True, "region": True}
S = {"players": True, "drop": ("home_japan", "away_japan", "japan_total")}
E = [
    ("R12-14", "alpha=5", B, {"alpha": 5.0}),
    ("R12-15", "alpha=15", B, {"alpha": 15.0}),
    ("R12-16", "alpha=10、+ホーム最終戦など", {**B, "season_pos": True}, {"alpha": 10.0}),
    ("R12-17", "alpha=10、+スター", {**B, **S}, {"alpha": 10.0}),
    ("R12-18", "alpha=10、+ホーム最終戦など＋スター", {**B, **S, "season_pos": True}, {"alpha": 10.0}),
    ("R12-19", "alpha=20、+ホーム最終戦など＋スター", {**B, **S, "season_pos": True}, {"alpha": 20.0}),
]
for eid, name, cfg, params in E:
    r, p = lib.evaluate(df, cfg, "ridge", "occ", params, seeds=(0,), return_preds=True)
    lib.log(eid, "R12 線形モデル", name, name, r, cfg, "ridge", "occ", params)
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
