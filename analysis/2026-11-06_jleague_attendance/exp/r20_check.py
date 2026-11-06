"""ラウンド20: 最終候補の部品を、選択に使っていない前半戦の検証（CHECK_FOLDS）で測る。予測は preds_chk/ に保存。"""
import pickle
import lib
from final import M
df = lib.load_all()
for k, (label, model, cfg, params, wt) in M.items():
    seeds = (0,) if model == "ridge" else (0, 1, 2)
    r, p = lib.evaluate(df, cfg, model, "occ", params, seeds=seeds, return_preds=True, weight=wt, folds=lib.CHECK_FOLDS)
    lib.log(f"R20-{k}", "R20 前半戦の検証（選択に未使用）", label, "列名に注意: H2_2012欄=H1_2013, H2_2013欄=H1_2014",
            {"H2_2012": r["H1_2013"], "H2_2013": r["H1_2014"], "mean": r["mean"]}, cfg, model, "occ", params, note=f"weight={wt}")
    pickle.dump(p, open(f"preds_chk/{k}.pkl", "wb"))
