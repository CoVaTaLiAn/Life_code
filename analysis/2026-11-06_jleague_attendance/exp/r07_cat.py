"""ラウンド7: CatBoost の特徴量の組み合わせとパラメータ。予測は preds/ に保存（後でアンサンブルに使う）。"""
import pickle
import lib
df = lib.load_all()
B = {"hist": False, "away_fanbase": True}
CF = [
    ("R07-01", "+地方", {"region": True}),
    ("R07-02", "+地方＋ホーム最終戦など", {"region": True, "season_pos": True}),
    ("R07-03", "+地方＋連休・ナイター", {"region": True, "calendar": True}),
    ("R07-04", "+地方＋ホーム最終戦など＋日程", {"region": True, "season_pos": True, "schedule": True}),
    ("R07-05", "+地方−アウェイの集客力", {"region": True, "away_fanbase": False}),
    ("R07-06", "+地方−中継", {"region": True, "tv": False}),
]
for eid, name, extra in CF:
    cfg = {**B, **extra}
    r, p = lib.evaluate(df, cfg, "cat", "occ", {"depth": 4}, return_preds=True)
    lib.log(eid, "R07 CatBoost 特徴量", name, name, r, cfg, "cat", "occ", {"depth": 4})
    pickle.dump(p, open(f"preds/{eid}.pkl", "wb"))
