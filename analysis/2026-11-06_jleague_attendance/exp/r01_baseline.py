"""ラウンド1: 現行モデルを本番と同じ形の検証で測り直し、主要な要素を1つずつ外す。"""
import lib
df = lib.load_all()
E = [
    ("R01-01", "現行モデル（過去実績＋順位、収容率で学習）", {}, "lgb", "occ"),
    ("R01-02", "順位なし", {"standings": False}, "lgb", "occ"),
    ("R01-03", "過去実績なし", {"hist": False}, "lgb", "occ"),
    ("R01-04", "過去実績・順位なし（ベースライン相当）", {"hist": False, "standings": False}, "lgb", "occ"),
    ("R01-05", "観客数をそのまま学習", {}, "lgb", "raw"),
    ("R01-06", "log(観客数)で学習", {}, "lgb", "log"),
    ("R01-07", "sqrt(観客数)で学習", {}, "lgb", "sqrt"),
    ("R01-08", "期待観客数に対する倍率で学習", {}, "lgb", "ratio_expected"),
    ("R01-09", "何も特徴量なしのベースライン相当: 観客数そのまま・過去実績/順位なし", {"hist": False, "standings": False}, "lgb", "raw"),
]
for eid, name, cfg, model, target in E:
    r = lib.evaluate(df, cfg, model, target)
    lib.log(eid, "R01 測り直し・アブレーション", name, name, r, cfg, model, target)
