"""ラウンド18: 重み付き Ridge（収容人数^1＋後半戦×2）の alpha と追加特徴量。"""
import pickle
import lib
df = lib.load_all()
RB = {"hist": False, "away_fanbase": True, "region": True, "players": True,
      "drop": ("home_japan", "away_japan", "japan_total"), "season_pos": True, "combo": True}
E = [
    ("R18-01", "alpha=10", RB, {"alpha": 10.0}),
    ("R18-02", "alpha=40", RB, {"alpha": 40.0}),
    ("R18-03", "alpha=20 ＋連休・ナイター", {**RB, "calendar": True}, {"alpha": 20.0}),
    ("R18-04", "alpha=20 ＋前年シーズン", {**RB, "hist_prev": True}, {"alpha": 20.0}),
    ("R18-05", "alpha=20 ＋日本代表クラスの人数", {**RB, "drop": ()}, {"alpha": 20.0}),
    ("R18-06", "alpha=20 −アウェイの集客力", {**RB, "away_fanbase": False}, {"alpha": 20.0}),
    ("R18-07", "alpha=20 ＋カード（ホーム×アウェイ）", {**RB, "combo": "full"}, {"alpha": 20.0}),
]
for eid, name, cfg, params in E:
    r, p = lib.evaluate(df, cfg, "ridge", "occ", params, seeds=(0,), return_preds=True, weight="cap1+h2")
    lib.log(eid, "R18 重み付き Ridge", name, name, r, cfg, "ridge", "occ", params, note="weight=cap1+h2")
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
