"""ラウンド13: 組み合わせカテゴリ（線形モデル向け）。"""
import pickle
import lib
df = lib.load_all()
B = {"hist": False, "away_fanbase": True, "region": True, "players": True,
     "drop": ("home_japan", "away_japan", "japan_total"), "season_pos": True}
E = [
    ("R13-01", "Ridge alpha=20 ＋組み合わせカテゴリ", {**B, "combo": True}, {"alpha": 20.0}),
    ("R13-02", "Ridge alpha=10 ＋組み合わせカテゴリ", {**B, "combo": True}, {"alpha": 10.0}),
    ("R13-03", "Ridge alpha=20 ＋組み合わせカテゴリ＋カード", {**B, "combo": "full"}, {"alpha": 20.0}),
    ("R13-04", "Ridge alpha=40 ＋組み合わせカテゴリ", {**B, "combo": True}, {"alpha": 40.0}),
]
for eid, name, cfg, params in E:
    r, p = lib.evaluate(df, cfg, "ridge", "occ", params, seeds=(0,), return_preds=True)
    lib.log(eid, "R13 組み合わせカテゴリ", name, name, r, cfg, "ridge", "occ", params)
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
