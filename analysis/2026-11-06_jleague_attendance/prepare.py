#!/usr/bin/env python3
"""Jリーグ観客動員数: 複数ファイルを1つの表に結合し、この課題に固有の整形をする。

入力（data/）: train.csv, train_add.csv, test.csv, condition.csv, condition_add.csv, stadium.csv
出力（data/）: train_merged.csv, test_merged.csv

汎用のクレンジング（全角→半角、% の数値化など）は eda_baseline.py が行うので、
ここでは「結合」と「この課題ならではの列の分解」だけを行う。
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd

D = Path(__file__).resolve().parent / "data"


def nfkc(s):
    return s.map(lambda v: unicodedata.normalize("NFKC", v).strip() if isinstance(v, str) else v)


def main():
    tr = pd.concat([pd.read_csv(D / "train.csv"), pd.read_csv(D / "train_add.csv")], ignore_index=True)
    # 2014/3/23 浦和-清水は処分による無観客試合（y=0）。通常の試合と仕組みが違うので学習から外す
    print("除外（無観客試合）:", tr.loc[tr["y"] == 0, "id"].tolist())
    tr = tr[tr["y"] > 0]
    te = pd.read_csv(D / "test.csv")
    cond = pd.concat([pd.read_csv(D / "condition.csv"), pd.read_csv(D / "condition_add.csv")], ignore_index=True)
    st = pd.read_csv(D / "stadium.csv")

    for df in (tr, te, cond, st):
        for c in df.columns:
            if pd.api.types.is_string_dtype(df[c]):
                df[c] = nfkc(df[c])

    # 試合当日の条件のうち、試合前に分かるものだけ使う。
    # スコアは試合後の情報、先発選手名は22列の固有名詞なので今回は除く。
    cond = cond[["id", "weather", "temperature", "humidity", "referee"]]
    st["pref"] = st["address"].str.extract(r"^(.+?[都道府県])")
    st = st.rename(columns={"name": "stadium", "capa": "capacity"})[["stadium", "capacity", "pref"]]

    tr["is_test"] = 0
    te["is_test"] = 1
    df = pd.concat([tr, te], ignore_index=True)
    df = df.merge(cond, on="id", how="left").merge(st, on="stadium", how="left")
    assert df["capacity"].notna().all(), "収容人数が結合できないスタジアムがあります"

    # 日付: year + "08/02(土)"、曜日と祝日
    md = df["gameday"].str.extract(r"(\d{2})/(\d{2})\((.+)\)")
    df["date"] = pd.to_datetime(df["year"].astype(str) + "-" + md[0] + "-" + md[1])
    df["weekday"] = md[2].str[0]
    df["holiday"] = md[2].str.contains("祝|休").astype(int)
    df["kickoff_hour"] = df["time"].str.split(":").map(lambda t: int(t[0]) + int(t[1]) / 60)

    # 節: "第18節第1日" → 18
    df["section"] = df["match"].str.extract(r"第(\d+)節").astype(int)
    df["last_section"] = (((df["stage"] == "J1") & (df["section"] == 34)) |
                          ((df["stage"] == "J2") & (df["section"] == 42))).astype(int)

    # 中継: "スカパー!/スカパー!プレミアムサービス/NHK BS1" を分解
    tv = df["tv"].str.split("/")
    df["tv_count"] = tv.map(len)
    df["tv_nhk_general"] = df["tv"].str.contains("NHK総合").astype(int)
    df["tv_nhk_bs"] = df["tv"].str.contains("NHK BS").astype(int)
    pay = re.compile(r"スカパー|e2|プレミアム")
    df["tv_free_count"] = tv.map(lambda xs: sum(1 for x in xs if not pay.search(x)))
    df["tv_recorded"] = df["tv"].str.contains("録").astype(int)

    # 天気: "曇のち雨" → 最初の天気と雨の有無
    df["weather_main"] = df["weather"].str[0]
    df["weather_rain"] = df["weather"].str.contains("雨").astype(int)

    # 地元対決: ホームチームの本拠地の県（最も多く使うスタジアムの県）が同じ
    home_pref = df.groupby("home")["pref"].agg(lambda s: s.value_counts().idxmax())
    df["away_pref"] = df["away"].map(home_pref)
    df["same_pref"] = (df["pref"] == df["away_pref"]).astype(int)
    df["main_stadium"] = (df["stadium"] == df["home"].map(
        df.groupby("home")["stadium"].agg(lambda s: s.value_counts().idxmax()))).astype(int)

    df = df.drop(columns=["gameday", "time", "match", "away_pref"])
    df = df.sort_values("date").reset_index(drop=True)
    df[df["is_test"] == 0].drop(columns="is_test").to_csv(D / "train_merged.csv", index=False)
    df[df["is_test"] == 1].drop(columns=["is_test", "y"]).to_csv(D / "test_merged.csv", index=False)
    print(df.groupby("is_test").size().to_dict(), df.shape)


if __name__ == "__main__":
    main()
