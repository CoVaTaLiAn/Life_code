"""ラウンド6: 新しい特徴量（連休・ナイター、ホーム開幕/最終戦、地方）。土台 = R02-06。"""
import lib
df = lib.load_all()
B = {"hist": False, "away_fanbase": True}
E = [
    ("R06-00", "土台（比較用）", {}),
    ("R06-01", "+連休・ナイター", {"calendar": True}),
    ("R06-02", "+ホーム開幕戦・最終戦・何試合目", {"season_pos": True}),
    ("R06-03", "+同じ地方・普段より小さい会場", {"region": True}),
    ("R06-04", "+3つ全部", {"calendar": True, "season_pos": True, "region": True}),
    ("R06-05", "+ホーム最終戦など＋日程", {"season_pos": True, "schedule": True}),
]
for eid, name, extra in E:
    cfg = {**B, **extra}
    for sfx, model, params in [("a", "lgb", {"num_leaves": 7}), ("b", "cat", {"depth": 4})]:
        r = lib.evaluate(df, cfg, model, "occ", params)
        lib.log(eid + sfx, "R06 新しい特徴量", f"{name}（{model}）", name, r, cfg, model, "occ", params)
