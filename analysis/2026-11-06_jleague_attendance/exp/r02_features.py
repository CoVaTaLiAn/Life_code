"""ラウンド2: 土台（過去実績なし＋順位、収容率）に特徴量グループを1つずつ足す／外す。"""
import lib
df = lib.load_all()
B = {"hist": False}
E = [
    ("R02-01", "土台（R01-03 の再確認）", {}),
    ("R02-02", "+同シーズン内の過去平均", {"hist_season": True}),
    ("R02-03", "+直近5試合・指数平滑の収容率", {"hist_last": True}),
    ("R02-04", "+前年シーズンの平均・昇格/降格フラグ", {"hist_prev": True}),
    ("R02-05", "+本拠地間の距離", {"distance": True}),
    ("R02-06", "+アウェイチームのホームでの集客力", {"away_fanbase": True}),
    ("R02-07", "+日程（休養日数・同日同県の試合数）", {"schedule": True}),
    ("R02-08", "-中継の特徴量", {"tv": False}),
    ("R02-09", "-天気・気温・湿度", {"weather": False}),
    ("R02-10", "-審判", {"referee": False}),
    ("R02-11", "-スタジアム名・県（カテゴリ）", {"drop": ("stadium", "pref")}),
    ("R02-12", "-アウェイ（カテゴリ）", {"drop": ("away",)}),
    ("R02-13", "-年・節・通算日", {"drop": ("year", "section", "doy")}),
]
for eid, name, extra in E:
    cfg = {**B, **extra}
    r = lib.evaluate(df, cfg)
    lib.log(eid, "R02 特徴量グループ", name, name, r, cfg)
