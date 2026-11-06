#!/usr/bin/env python3
"""試合日時点の順位・勝ち点の特徴量を作る → data/standings.csv

- 全試合（train / train_add / test / 2014_add）の結果（condition のスコア）から、年×ディビジョンごとに順位表を作る
- 各試合の特徴量は「その試合日より前の試合」だけで計算する（同じ日の他会場の結果も使わない）
- 使うのは過去の試合結果だけで、観客数（目的変数）は使わない。試合日に誰でも知っている情報
"""
import unicodedata
from pathlib import Path

import pandas as pd

D = Path(__file__).resolve().parent / "data"
TEAMS = {"J1": 18, "J2": 22}
# 昇格・残留の境目（2012〜2014年の規定）
#   J1: 下位3チームが降格（16位以下）
#   J2: 1・2位が自動昇格、3〜6位が昇格プレーオフ。2013年以降は最下位（22位）が降格・入れ替え
PROMO_LINE = {"J2": 6}
RELEG_RANK = {"J1": 16}


def nfkc(v):
    return unicodedata.normalize("NFKC", v).strip() if isinstance(v, str) else v


def load():
    m = pd.concat([pd.read_csv(D / f) for f in ["train.csv", "train_add.csv", "test.csv", "2014_add.csv"]])
    c = pd.concat([pd.read_csv(D / "condition.csv"), pd.read_csv(D / "condition_add.csv")])
    df = m.merge(c[["id", "home_score", "away_score"]], on="id")
    for col in ["stage", "home", "away", "gameday"]:
        df[col] = df[col].map(nfkc)
    md = df["gameday"].str.extract(r"(\d{2})/(\d{2})")
    df["date"] = pd.to_datetime(df["year"].astype(str) + "-" + md[0] + "-" + md[1])
    return df[["id", "year", "stage", "date", "home", "away", "home_score", "away_score"]]


def table_ranks(tab):
    """勝ち点 → 得失点差 → 総得点 の順で順位を付ける（同じなら同順位）。"""
    t = pd.DataFrame.from_dict(tab, orient="index")
    t["gd"] = t["gf"] - t["ga"]
    key = t["pts"] * 1e6 + t["gd"] * 1e3 + t["gf"]
    t["rank"] = key.rank(ascending=False, method="min").astype(int)
    return t


def season_features(g, stage):
    n_teams = TEAMS[stage]
    n_games = (n_teams - 1) * 2
    teams = sorted(set(g["home"]) | set(g["away"]))
    tab = {t: {"pts": 0, "gf": 0, "ga": 0, "played": 0} for t in teams}
    form = {t: [] for t in teams}  # 直近の勝ち点（3/1/0）
    rows = []
    for date, day in g.sort_values("date").groupby("date", sort=True):
        t = table_ranks(tab)
        leader = t["pts"].max()
        srt = t.sort_values("rank")["pts"].values
        for _, r in day.iterrows():
            f = {"id": r["id"]}
            for side in ("home", "away"):
                team = r[side]
                s = t.loc[team]
                remaining = n_games - s["played"]
                f[f"{side}_rank"] = s["rank"]
                f[f"{side}_pts"] = s["pts"]
                f[f"{side}_played"] = s["played"]
                f[f"{side}_ppg"] = s["pts"] / s["played"] if s["played"] else None
                f[f"{side}_gd"] = s["gd"]
                f[f"{side}_behind_leader"] = leader - s["pts"]
                # まだ優勝の可能性があるか（残り試合を全勝すれば首位に届く）
                f[f"{side}_title_alive"] = int(s["pts"] + 3 * remaining >= leader)
                last5 = form[team][-5:]
                f[f"{side}_form5"] = sum(last5) / len(last5) if last5 else None
                if stage in PROMO_LINE:   # J2: 昇格プレーオフ圏（6位）との勝ち点差。プラスなら圏内
                    f[f"{side}_vs_promo_line"] = s["pts"] - srt[PROMO_LINE[stage] - 1]
                if stage in RELEG_RANK:   # J1: 降格圏（16位）との勝ち点差。小さいほど残留争い
                    f[f"{side}_vs_releg_line"] = s["pts"] - srt[RELEG_RANK[stage] - 1]
            f["remaining_games"] = n_games - (t.loc[r["home"], "played"] + t.loc[r["away"], "played"]) / 2
            f["rank_sum"] = f["home_rank"] + f["away_rank"]
            f["top_clash"] = int(max(f["home_rank"], f["away_rank"]) <= 4 and f["home_played"] >= 5)
            rows.append(f)
        # その日の試合結果を反映
        for _, r in day.iterrows():
            h, a, hs, as_ = r["home"], r["away"], r["home_score"], r["away_score"]
            ph, pa = (3, 0) if hs > as_ else ((0, 3) if hs < as_ else (1, 1))
            for team, gf, ga, p in ((h, hs, as_, ph), (a, as_, hs, pa)):
                tab[team]["pts"] += p
                tab[team]["gf"] += gf
                tab[team]["ga"] += ga
                tab[team]["played"] += 1
                form[team].append(p)
    out = pd.DataFrame(rows)
    final = table_ranks(tab)
    assert (final["played"] == n_games).all(), "試合数が足りないチームがあります"
    return out


def main():
    df = load()
    parts = [season_features(g, stage) for (year, stage), g in df.groupby(["year", "stage"])]
    st = pd.concat(parts, ignore_index=True)
    assert st["id"].is_unique and len(st) == len(df)
    st.to_csv(D / "standings.csv", index=False)
    print(st.shape, list(st.columns))


if __name__ == "__main__":
    main()
