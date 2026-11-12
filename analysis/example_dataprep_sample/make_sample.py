#!/usr/bin/env python3
"""前処理の見本用の架空データ（わざと汚してある）を作る。 python3 make_sample.py → data/raw.csv, data/raw_test.csv"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.RandomState(0)
N = 600
pref = rng.choice(["東京都", "大阪府", "愛知県", "福岡県", "北海道", "神奈川県", "埼玉県", "千葉県", "兵庫県", "京都府",
                   "宮城県", "広島県", "静岡県", "新潟県", "長野県"], N, p=[.25, .12, .1, .08, .07, .07, .06, .05, .05, .04, .03, .03, .02, .02, .01])
age = rng.normal(42, 13, N).round().clip(18, 85)
income = np.exp(rng.normal(15.3, .5, N)).round(-3)
plan = rng.choice(["Free", "Basic", "Premium"], N, p=[.5, .35, .15])
rank = rng.choice(["ブロンズ", "シルバー", "ゴールド"], N, p=[.6, .3, .1])
visits = rng.poisson(6, N)
minutes = rng.gamma(2, 15, N).round(1)
start = pd.Timestamp("2023-01-01") + pd.to_timedelta(rng.randint(0, 900, N), unit="D")
mail = rng.rand(N) < .6
churn = (rng.rand(N) < 1 / (1 + np.exp(-(-1.2 + (plan == "Free") * .9 - visits * .12 + (age < 30) * .5)))).astype(int)
df = pd.DataFrame({
    "顧客ＩＤ": [f"C{i:05d}" for i in range(1, N + 1)], " 年齢 ": age.astype(int).astype(str), "性別": rng.choice(["男性", "女性"], N),
    "都道府県": pref, "郵便番号": [f"{rng.randint(0, 9999999):07d}" for _ in range(N)], "プラン": plan, "会員ランク": rank,
    "年収": [f"￥{int(v):,}" for v in income], "月間来店回数": visits.astype(str), "平均滞在分": minutes.astype(str),
    "登録日": start.strftime("%Y/%m/%d"), "メール受信": np.where(mail, "はい", "いいえ"), "割引率": [f"{v}%" for v in rng.choice([0, 5, 10, 20], N)],
    "コメント": rng.choice(["特になし", "店員さんの対応がとても丁寧で、また利用したいと思いました。", "待ち時間が長いのが気になります。改善を期待しています。",
                         "商品の種類が豊富で選ぶのが楽しいです。", ""], N, p=[.2, .15, .15, .1, .4]),
    "国": "日本", "備考": "", "年齢コピー": age.astype(int).astype(str), "解約": churn.astype(str)})
i = lambda k: rng.choice(N, k, replace=False)  # noqa: E731
df.loc[i(15), " 年齢 "] = "999"                      # 欠損コード
df.loc[i(6), " 年齢 "] = ["不明", "３５", "四十", "２８", "-", "５１"]  # 読めない値・全角
df["年齢コピー"] = df[" 年齢 "]
df.loc[i(25), "性別"] = rng.choice(["男", "Ｍ", "女", " 女性"], 25)
df.loc[i(30), "プラン"] = rng.choice(["free", "FREE ", "ｂａｓｉｃ", "Premium　", "premium"], 30)
df.loc[i(12), "都道府県"] = rng.choice(["東京", "大阪", "TOKYO"], 12)
df.loc[i(40), "年収"] = rng.choice(["", "NA", "N/A", "-"], 40)
df.loc[i(3), "年収"] = ["￥980,000,000", "￥1", "▲500,000"]
df.loc[i(8), "月間来店回数"] = "-1"
df.loc[i(4), "平均滞在分"] = ["1440", "2000", "-5", "null"]
df.loc[i(10), "登録日"] = ["2023年4月1日", "2024-02-30", "2099/01/01", "", "R5.4.1", "2023/5/7", "2024-06-15", "1899/12/31", "2023.08.09", "不明"]
df.loc[i(20), "メール受信"] = rng.choice(["yes", "No", "", "○"], 20)
df.loc[i(10), "会員ランク"] = "不明"
raw = pd.concat([df, df.iloc[i(12)], pd.DataFrame([dict.fromkeys(df.columns, "")] * 3)], ignore_index=True)
raw = raw.sample(frac=1, random_state=1).reset_index(drop=True)
out = Path(__file__).parent / "data"
out.mkdir(exist_ok=True)
raw.iloc[:500].to_csv(out / "raw.csv", index=False, encoding="cp932", errors="replace")
test = raw.iloc[500:].drop(columns="解約").copy()
test.iloc[:5, 3] = "沖縄県"  # 学習用にない値
test.to_csv(out / "raw_test.csv", index=False, encoding="cp932", errors="replace")
print("data/raw.csv", raw.iloc[:500].shape, "data/raw_test.csv", test.shape)
