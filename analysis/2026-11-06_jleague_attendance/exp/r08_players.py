"""ラウンド8: 先発のスター・日本代表クラスの人数。"""
import pickle
import lib
df = lib.load_all()
B = {"hist": False, "away_fanbase": True, "region": True}
E = [
    ("R08-01", "CatBoost 土台＋地方＋選手", "cat", {**B, "players": True}, {"depth": 4}),
    ("R08-02", "CatBoost 土台＋地方＋選手（スター人数のみ: 日本代表クラスを外す）", "cat",
     {**B, "players": True, "drop": ("home_japan", "away_japan", "japan_total")}, {"depth": 4}),
    ("R08-03", "LightGBM 土台＋選手（num_leaves=7）", "lgb", {"hist": False, "away_fanbase": True, "players": True}, {"num_leaves": 7}),
    ("R08-04", "LightGBM 土台＋地方＋選手（num_leaves=7）", "lgb", {**B, "players": True}, {"num_leaves": 7}),
]
for eid, name, model, cfg, params in E:
    r, p = lib.evaluate(df, cfg, model, "occ", params, return_preds=True)
    lib.log(eid, "R08 選手", name, name, r, cfg, model, "occ", params)
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
