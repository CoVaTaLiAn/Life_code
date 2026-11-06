"""ラウンド17: LightGBM に収容人数の重み。"""
import pickle
import lib
df = lib.load_all()
LB = {"hist": False, "away_fanbase": True, "players": True, "season_pos": True, "schedule": True}
E = [
    ("R17-01", "LightGBM nl7 土台＋選手＋ホーム最終戦＋日程（重みなし）", {"num_leaves": 7}, None),
    ("R17-02", "LightGBM nl7 同上 収容人数^2", {"num_leaves": 7}, "cap2"),
    ("R17-03", "LightGBM nl7 同上 収容人数^1", {"num_leaves": 7}, "cap1"),
    ("R17-04", "LightGBM nl7 mcs5 同上 収容人数^2", {"num_leaves": 7, "min_child_samples": 5}, "cap2"),
]
for eid, name, params, wt in E:
    r, p = lib.evaluate(df, LB, "lgb", "occ", {**params, "n_jobs": 2}, return_preds=True, weight=wt)
    lib.log(eid, "R17 LightGBM 重み", name, name, r, LB, "lgb", "occ", params, note=f"weight={wt}")
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
