"""ラウンド12: 線形モデル（Ridge）の改良。計算が軽いので Optuna と並行して回す。"""
import pickle
import lib
df = lib.load_all()
B = {"hist": False, "away_fanbase": True, "region": True}
E = [
    ("R12-01", "alpha=1", B, {"alpha": 1.0}, "occ"),
    ("R12-02", "alpha=10", B, {"alpha": 10.0}, "occ"),
    ("R12-03", "alpha=30", B, {"alpha": 30.0}, "occ"),
    ("R12-04", "alpha=3、ロジット収容率", B, {"alpha": 3.0}, "logit"),
    ("R12-05", "alpha=3、+スター", {**B, "players": True, "drop": ("home_japan", "away_japan", "japan_total")}, {"alpha": 3.0}, "occ"),
    ("R12-06", "alpha=3、+スター＋代表", {**B, "players": True}, {"alpha": 3.0}, "occ"),
    ("R12-07", "alpha=3、+ホーム最終戦など", {**B, "season_pos": True}, {"alpha": 3.0}, "occ"),
    ("R12-08", "alpha=3、+連休・ナイター", {**B, "calendar": True}, {"alpha": 3.0}, "occ"),
    ("R12-09", "alpha=3、+日程", {**B, "schedule": True}, {"alpha": 3.0}, "occ"),
    ("R12-10", "alpha=3、+過去実績（基本セット）", {**B, "hist": True}, {"alpha": 3.0}, "occ"),
    ("R12-11", "alpha=3、+前年シーズン", {**B, "hist_prev": True}, {"alpha": 3.0}, "occ"),
    ("R12-12", "alpha=3、−審判", {**B, "referee": False}, {"alpha": 3.0}, "occ"),
    ("R12-13", "alpha=3、−順位", {**B, "standings": False}, {"alpha": 3.0}, "occ"),
]
for eid, name, cfg, params, target in E:
    r, p = lib.evaluate(df, cfg, "ridge", target, params, seeds=(0,), return_preds=True)
    lib.log(eid, "R12 線形モデル", name, name, r, cfg, "ridge", target, params)
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
