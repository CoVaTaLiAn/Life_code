"""ラウンド3: 過去の実績を「本番と同じ鮮度」で作る（学習用の行も古い値にする）。"""
import lib
df = lib.load_all()
S = {"hist_mode": "stale"}
E = [
    ("R03-01", "過去実績（基本セット）を本番の鮮度で", {"hist": True, **S}),
    ("R03-02", "過去実績なし＋同シーズン内の平均を本番の鮮度で", {"hist": False, "hist_season": True, **S}),
    ("R03-03", "過去実績なし＋前年シーズン平均・昇格降格", {"hist": False, "hist_prev": True, **S}),
    ("R03-04", "過去実績（本番の鮮度）＋前年シーズン", {"hist": True, "hist_prev": True, **S}),
    ("R03-05", "過去実績なし＋アウェイの集客力を本番の鮮度で", {"hist": False, "away_fanbase": True, **S}),
    ("R03-06", "過去実績（本番の鮮度）＋同シーズン＋直近", {"hist": True, "hist_season": True, "hist_last": True, **S}),
]
for eid, name, cfg in E:
    r = lib.evaluate(df, cfg)
    lib.log(eid, "R03 過去実績の鮮度", name, name, r, cfg)
