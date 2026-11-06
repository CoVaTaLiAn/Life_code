"""ラウンド21: Optuna の LightGBM 設定に収容人数の重みを付け、後半戦・前半戦の両方の検証で比べる。"""
import json
import pickle
import lib
df = lib.load_all()
top = json.load(open("R11_top_params.json"))[0]
LB = {"hist": False, "away_fanbase": True, "players": True, "season_pos": True, "schedule": True}
LO = {"hist": False, "away_fanbase": True, "players": True}  # Optuna の探索時の特徴量
for eid, name, cfg, wt in [("R21-01", "Optuna 設定・探索時の特徴量・収容人数^1", LO, "cap1"),
                           ("R21-02", "Optuna 設定・ホーム最終戦＋日程も・収容人数^1", LB, "cap1")]:
    r, p = lib.evaluate(df, cfg, "lgb", "occ", top, return_preds=True, weight=wt)
    lib.log(eid, "R21 LightGBM 調整済み", name, name, r, cfg, "lgb", "occ", top, note=f"weight={wt}")
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
    r2, p2 = lib.evaluate(df, cfg, "lgb", "occ", top, return_preds=True, weight=wt, folds=lib.CHECK_FOLDS)
    lib.log(eid + "-CHK", "R21 LightGBM 調整済み（前半戦の検証）", name, "列名に注意: H2_2012欄=H1_2013, H2_2013欄=H1_2014",
            {"H2_2012": r2["H1_2013"], "H2_2013": r2["H1_2014"], "mean": r2["mean"]}, cfg, "lgb", "occ", top, note=f"weight={wt}")
    pickle.dump(p2, open(f"preds_chk/{eid}.pkl", "wb"))
