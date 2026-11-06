"""ラウンド5: 別のモデル、J1/J2 別モデル、乱数の揺れの大きさ。土台 = R02-06。"""
import lib
df = lib.load_all()
cfg = {"hist": False, "away_fanbase": True}
E = [
    ("R05-01", "LightGBM seed 3,4,5（乱数の揺れの確認）", "lgb", {}, dict(seeds=(3, 4, 5))),
    ("R05-02", "LightGBM seed 6,7,8（乱数の揺れの確認）", "lgb", {}, dict(seeds=(6, 7, 8))),
    ("R05-03", "LightGBM J1/J2 別モデル", "lgb", {}, dict(by_stage=True)),
    ("R05-04", "CatBoost depth=6", "cat", {}, {}),
    ("R05-05", "CatBoost depth=4", "cat", {"depth": 4}, {}),
    ("R05-06", "CatBoost depth=8", "cat", {"depth": 8}, {}),
    ("R05-07", "XGBoost depth=6", "xgb", {}, {}),
    ("R05-08", "XGBoost depth=4", "xgb", {"max_depth": 4}, {}),
    ("R05-09", "Ridge（線形）alpha=3", "ridge", {"alpha": 3.0}, dict(seeds=(0,))),
    ("R05-10", "Ridge（線形）alpha=0.3", "ridge", {"alpha": 0.3}, dict(seeds=(0,))),
]
for eid, name, model, params, kw in E:
    r = lib.evaluate(df, cfg, model, "occ", params, **kw)
    lib.log(eid, "R05 モデル比較", name, name, r, cfg, model, "occ", params, note=str(kw))
