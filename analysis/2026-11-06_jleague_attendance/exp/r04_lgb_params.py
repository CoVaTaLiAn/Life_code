"""ラウンド4: LightGBM のパラメータ（木の大きさ・カテゴリの扱い・正則化）。土台 + アウェイの集客力。"""
import sys
import lib
df = lib.load_all()
cfg = {"hist": False, "away_fanbase": True}
P = [
    ("R04-01", "num_leaves=7", {"num_leaves": 7}),
    ("R04-02", "num_leaves=15", {"num_leaves": 15}),
    ("R04-03", "num_leaves=63", {"num_leaves": 63}),
    ("R04-04", "min_child_samples=5", {"min_child_samples": 5}),
    ("R04-05", "min_child_samples=10", {"min_child_samples": 10}),
    ("R04-06", "min_child_samples=40", {"min_child_samples": 40}),
    ("R04-07", "learning_rate=0.01", {"learning_rate": 0.01}),
    ("R04-08", "colsample_bytree=0.5", {"colsample_bytree": 0.5}),
    ("R04-09", "reg_lambda=10", {"reg_lambda": 10}),
    ("R04-10", "カテゴリ: cat_smooth=1, min_data_per_group=5", {"cat_smooth": 1, "min_data_per_group": 5}),
    ("R04-11", "カテゴリ: cat_l2=1, cat_smooth=1, min_data_per_group=5", {"cat_l2": 1, "cat_smooth": 1, "min_data_per_group": 5}),
    ("R04-12", "カテゴリ: max_cat_to_onehot=64（one-hot 分割）", {"max_cat_to_onehot": 64}),
    ("R04-13", "早期終了なし・固定 500 本", {"fixed_rounds": 500}),
    ("R04-14", "早期終了なし・固定 1500 本", {"fixed_rounds": 1500}),
]
for eid, name, params in P:
    r = lib.evaluate(df, cfg, "lgb", "occ", params)
    lib.log(eid, "R04 LightGBM パラメータ", name, name, r, cfg, "lgb", "occ", params)
