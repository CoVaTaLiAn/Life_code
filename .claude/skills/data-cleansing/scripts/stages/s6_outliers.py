"""段階6 外れ値: 数値・日時のありえない値や極端な値を挙げる。指定があるときだけ直す。"""
import numpy as np
import pandas as pd
import tabprep_common as tc

NAME, TITLE = "outliers", "外れ値"
ROLE = "数値列の極端な値・ありえない値、日時列のおかしな日付を挙げる。既定では値を変えず、範囲や方法の指定があるときだけ直す"
NEXT = "クレンジング完了。クレンジング後のデータをもう一度プロファイリングし、エンコーディングへ"


def add_args(ap):
    ap.add_argument("--range", default="", help="[段階6] ありうる範囲を指定し、外の値を欠損にする（例: 年齢=0:120,単価=0:,登録日=2000-01-01:2026-12-31）")
    ap.add_argument("--outlier", default="", help="[段階6] 列ごとの外れ値の扱い（例: 年収=clip,滞在分=nan）。"
                    "clip=境界の値に丸める、nan=欠損にする")
    ap.add_argument("--iqr-k", type=float, default=3.0, help="[段階6] 外れ値の境界（四分位範囲の何倍か。既定 3）")


def run(df, schema, a):
    actions, review, rows, fences_out = [], [], [], {}
    for c, r in tc.parse_kv(a.range).items():
        lo, hi = (r.split(":") + [""])[:2]
        if schema.get(c) == "datetime":
            lo, hi = pd.Timestamp(lo or "1677-09-22"), pd.Timestamp(hi or "2262-04-11")
        elif schema.get(c) == "numeric":
            lo, hi = (float(lo) if lo else -np.inf), (float(hi) if hi else np.inf)
        else:
            raise SystemExit(f"--range: {c} は数値列でも日時列でもありません")
        hit = (df[c] < lo) | (df[c] > hi)
        actions.append([c, f"範囲 {r} の外の値を欠損にした", int(hit.sum()), tc.examples(df[c][hit].unique())])
        df[c] = df[c].mask(hit, np.nan)
    how = tc.parse_kv(a.outlier)
    for c in df.columns:
        if schema.get(c) == "datetime":
            x = df[c].dropna()
            fut, old = x > pd.Timestamp.now(), x < pd.Timestamp("1900-01-01")
            if fut.sum():
                review.append([c, "未来の日時", int(fut.sum()), tc.examples(x[fut].unique())])
            if old.sum():
                review.append([c, "1900年より前の日時", int(old.sum()), tc.examples(x[old].unique())])
            continue
        if schema.get(c) != "numeric":
            continue
        x = df[c].dropna()
        if 0 < (x < 0).mean() < .05:
            review.append([c, f"負の値が少数だけある（ありえないなら --range {c}=0:）", int((x < 0).sum()), tc.examples(x[x < 0].unique())])
        f = tc.iqr_fences(x, a.iqr_k)
        if not f:
            continue
        lo, hi = f
        out = (df[c] < lo) | (df[c] > hi)
        fences_out[c] = [lo, hi]
        rows.append([c, float(x.min()), lo, float(x.median()), hi, float(x.max()), int(out.sum()), tc.pct(out.mean(), 2)])
        if not out.sum():
            continue
        ex = tc.examples(sorted(df[c][out].unique(), key=lambda v: -abs(v - x.median())))
        if how.get(c) == "clip":
            df[c] = df[c].clip(lo, hi)
            actions.append([c, f"外れ値を境界（{tc.fmt(lo)}〜{tc.fmt(hi)}）に丸めた", int(out.sum()), ex])
        elif how.get(c) == "nan":
            df[c] = df[c].mask(out, np.nan)
            actions.append([c, "外れ値を欠損にした", int(out.sum()), ex])
        else:
            review.append([c, f"極端な値（境界 {tc.fmt(lo)}〜{tc.fmt(hi)} の外）", int(out.sum()), ex])
    notes = [f"境界は 第1四分位 − {a.iqr_k}×四分位範囲 〜 第3四分位 + {a.iqr_k}×四分位範囲。裾の長い分布（金額など）では本物の値も外れ値に見える。"
             "その場合は値を変えず、エンコーディングの対数変換（log1p）に任せる。",
             "テスト用データに clip を使うと境界がデータごとに変わる。学習用と揃えたいときは `--range` で同じ範囲を明示する。"]
    tables = [("数値列の境界と外れ値の数", ["列", "最小", "下の境界", "中央値", "上の境界", "最大", "外れ値", "割合"], rows)]
    return df, schema, {"actions": actions, "review": review, "notes": notes, "tables": tables,
                        "files": {"fences.json": fences_out}}
