#!/usr/bin/env python3
"""カテゴリ別の統計の可視化: カテゴリ列ごとに、各カテゴリの件数と数値列の統計を図にして画像で保存する（データは変更しない）。

  python3 visualize_categories.py --input cleaned.csv --out <出力先> [--target 列] [--columns 列,列] [--values 列,列]
      [--top 15] [--max-values 6] [--dpi 200]

カテゴリ列1つにつき画像1枚（figs/<列名>.png）。左から 件数 →（目的変数の平均）→ 数値列ごとの分布（25〜75% の帯と中央値）。
出力: figs/*.png / category_stats.csv（図にした数値すべて）/ report.md / report.html（画像埋め込み）
入力の隣に <名前>.schema.json（クレンジング後）があればその種類を使う。なければ種類を推定する。
必要: pandas numpy matplotlib
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import tabprep_common as tc  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

ROLE = "カテゴリ列ごとに、各カテゴリの件数と数値列の統計を図にして画像で保存する（データは変更しない）"
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, BLUE_LIGHT = "#2a78d6", "#9ec5f4"
OTHER, MISSING = "その他", "(欠損)"


def setup_font():
    names = {f.name for f in font_manager.fontManager.ttflist}
    for c in ["IPAexGothic", "IPAGothic", "Noto Sans CJK JP", "Noto Sans JP", "Hiragino Sans", "Yu Gothic", "Meiryo"]:
        if c in names:
            plt.rcParams["font.family"] = c
            return c
    return None


def typed_table(path):
    df, schema, _ = tc.load_table(path)
    if schema is not None:
        return df, schema, True
    schema = {}
    for c in df.columns:
        s = tc.map_unique(df[c], tc.norm_text)
        s = s.mask(s.notna() & tc.map_unique(s, lambda v: v == "" or tc.is_null_token(v)).fillna(False).astype(bool))
        info = tc.infer_kind(s, c)
        df[c], schema[c] = info["values"], info["kind"]
    return df, schema, False


def label_of(v):
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return str(int(v))
    return str(v)


def group_labels(s, top):
    """カテゴリのラベル列（欠損は「(欠損)」、上位 top より下は「その他」）と、表示順（件数の多い順）。"""
    lab = s.map(label_of, na_action="ignore").fillna(MISSING)
    vc = lab[lab != MISSING].value_counts()
    keep = list(vc.index[:top])
    lab = lab.where(lab.isin(keep + [MISSING]), OTHER)
    order = keep + [x for x in (OTHER, MISSING) if (lab == x).any()]
    return lab, order, len(vc)


def stats_for(df, lab, order, values):
    rows = []
    n = len(df)
    for cat in order:
        m = lab == cat
        base = {"category": cat, "count": int(m.sum()), "share": m.sum() / n}
        if not values:
            rows.append({**base, "value": None})
        for v in values:
            x = df.loc[m, v].dropna().astype(float)
            q = x.quantile([.25, .5, .75]) if len(x) else pd.Series([np.nan] * 3, index=[.25, .5, .75])
            rows.append({**base, "value": v, "n": len(x), "mean": x.mean(), "std": x.std(), "min": x.min(),
                         "q1": q[.25], "median": q[.5], "q3": q[.75], "max": x.max()})
    return pd.DataFrame(rows)


def short(t, n=14):
    return t if len(t) <= n else t[:n - 1] + "…"


def axis_num(v, _pos=None):
    """軸の数値。大きい数は「万」「億」で書く（1e6 のような表記を避ける）。"""
    a = abs(v)
    if a >= 1e8:
        return f"{v / 1e8:g}億"
    if a >= 1e4:
        return f"{v / 1e4:g}万"
    return f"{v:g}"


def style_axis(ax, title):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, fontsize=10, color=INK, loc="left", pad=8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(axis="x", colors=MUTED, labelsize=8, length=0)
    ax.tick_params(axis="y", colors=INK2, labelsize=9, length=0)
    ax.grid(axis="x", color=GRID, linewidth=.6)
    ax.set_axisbelow(True)


def draw(col, st, order, target, values, overall, path, dpi, n_total_cats):
    panels = ["count"] + ([target] if target else []) + values
    ncat = len(order)
    y = np.arange(ncat)[::-1]
    fig, axes = plt.subplots(1, len(panels), figsize=(3.6 + 2.5 * (len(panels) - 1), max(2.4, .36 * ncat + 1.5)),
                             sharey=True, squeeze=False, gridspec_kw={"width_ratios": [1.3] + [1] * (len(panels) - 1)})
    fig.patch.set_facecolor(SURFACE)
    first = st.drop_duplicates("category").set_index("category").loc[order]
    for ax, p in zip(axes[0], panels):
        if p == "count":
            style_axis(ax, "件数")
            ax.barh(y, first["count"], height=.62, color=BLUE)
            mx = first["count"].max()
            for yi, (cnt, sh) in zip(y, zip(first["count"], first["share"])):
                ax.text(cnt + mx * .02, yi, f"{cnt:,}（{100 * sh:.1f}%）", va="center", fontsize=8, color=INK2)
            ax.set_xlim(0, mx * 1.45)
            ax.set_yticks(y)
            ax.set_yticklabels([short(c) for c in order])
            continue
        d = st[st["value"] == p].set_index("category").loc[order]
        if p == target:
            style_axis(ax, f"{short(p, 10)} の平均")
            ax.hlines(y, 0, d["mean"], color=BLUE, linewidth=2)
            ax.plot(d["mean"], y, "o", color=BLUE, markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5)
            ref = overall[p]["mean"]
            mx = max(d["mean"].max(), ref)
            for yi, v in zip(y, d["mean"]):
                if pd.notna(v):
                    ax.text(v + mx * .05, yi, tc.fmt(float(v)), va="center", fontsize=8, color=INK2, zorder=5,
                            bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1})
            ax.set_xlim(min(0, d["mean"].min()), mx * 1.3)
        else:
            style_axis(ax, short(p, 12))
            ax.hlines(y, d["q1"], d["q3"], color=BLUE_LIGHT, linewidth=7, capstyle="round")
            ax.plot(d["median"], y, "o", color=BLUE, markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5)
            ref = overall[p]["median"]
        ax.xaxis.set_major_formatter(FuncFormatter(axis_num))
        ax.axvline(ref, color=MUTED, linewidth=1, linestyle=(0, (3, 3)), zorder=1)
    note = "帯: 25〜75% の範囲　点: 中央値　点線: 全体の中央値" if values else ""
    if target:
        note = f"「{target} の平均」の点線: 全体の平均　" + note
    if n_total_cats > len([c for c in order if c not in (OTHER, MISSING)]):
        note += f"　※全 {n_total_cats} 種類のうち件数の多い順に表示。残りは「{OTHER}」"
    fig.suptitle(f"{col}：カテゴリ別の統計", fontsize=12, color=INK, x=.01, ha="left", y=.995)
    fig.text(.01, .005, note, fontsize=8, color=MUTED, ha="left", va="bottom")
    fig.tight_layout(rect=(0, .05, 1, .95), w_pad=1.5)
    fig.savefig(path, dpi=dpi, facecolor=SURFACE)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", help="目的変数（数値か 0/1 なら、カテゴリ別の平均を図に入れる）")
    ap.add_argument("--columns", default="", help="図にするカテゴリ列（カンマ区切り。既定は自動）")
    ap.add_argument("--values", default="", help="統計を取る数値列（カンマ区切り。既定は数値列を先頭から）")
    ap.add_argument("--top", type=int, default=15, help="1枚に表示するカテゴリ数（残りは「その他」）")
    ap.add_argument("--max-values", type=int, default=6, help="1枚に入れる数値列の数")
    ap.add_argument("--dpi", type=int, default=200)
    a = ap.parse_args()
    out = Path(a.out)
    (out / "figs").mkdir(parents=True, exist_ok=True)
    font = setup_font()
    df, schema, cleaned = typed_table(a.input)
    for c in [a.target] + a.columns.split(",") + a.values.split(","):
        if c and c not in df.columns:
            sys.exit(f"列がありません: {c}（列: {list(df.columns)}）")
    target = a.target if a.target and schema[a.target] in ("numeric", "bool") else None
    notes = []
    if a.target and not target:
        notes.append(f"目的変数 `{a.target}` は数値ではないので、カテゴリ別の平均は図に入れていない")
    nuniq = df.nunique()
    all_values = [c for c in df.columns if schema[c] == "numeric" and nuniq[c] > 10 and c != a.target]
    values = [c for c in a.values.split(",") if c] or all_values[:a.max_values]
    if not a.values and len(all_values) > len(values):
        notes.append(f"数値列は先頭の {len(values)} 列だけ図にした（残り: {all_values[len(values):]}。`--values` で選べる）")
    cols = [c for c in a.columns.split(",") if c] or [
        c for c in df.columns if c != a.target and c not in values and nuniq[c] >= 2
        and (schema[c] in ("category", "bool") or (schema[c] == "numeric" and nuniq[c] <= 10))]
    if not cols:
        sys.exit("図にできるカテゴリ列がありません（--columns で指定してください）")
    stat_cols = ([target] if target else []) + values
    overall = {v: {"mean": float(df[v].mean()), "median": float(df[v].median())} for v in stat_cols}

    rep = tc.Report(f"カテゴリ別の統計の可視化: {Path(a.input).name}", ROLE, {
        "入力": a.input, "状態": "クレンジング済み（schema あり）" if cleaned else "未クレンジング（種類は推定）",
        "画像": f"{out / 'figs'}（{len(cols)} 枚、{a.dpi} dpi）", "数値の一覧": str(out / "category_stats.csv")})
    rep.h("1. 図にした列")
    all_stats, summary = [], []
    for col in cols:
        lab, order, n_cats = group_labels(df[col], a.top)
        st = stats_for(df, lab, order, stat_cols)
        name = re.sub(r"[^\w\-]+", "_", col).strip("_") or "col"
        draw(col, st, order, target, values, overall, out / "figs" / f"{name}.png", a.dpi, n_cats)
        st.insert(0, "column", col)
        all_stats.append(st)
        summary.append((col, name, st, order, n_cats))
    rep.table(["カテゴリ列", "種類数", "表示したカテゴリ", "画像"],
              [[col, n_cats, len(order), f"figs/{name}.png"] for col, name, _, order, n_cats in summary])
    rep.table(["図に入れた数値", "全体の平均", "全体の中央値"], [[v, o["mean"], o["median"]] for v, o in overall.items()],
              empty="数値列がないので件数だけを図にした")
    rep.p("図の読み方: 左端が各カテゴリの件数（割合）。数値列は、薄い帯がそのカテゴリの 25〜75% の範囲、点が中央値、点線が全体の中央値。"
          "点が点線から離れているカテゴリほど、その数値が全体と違う。件数の少ないカテゴリは値がぶれやすいので件数と合わせて読む。")
    rep.ul(notes + ([] if font else ["日本語フォントが見つからず、図の日本語が表示できていない可能性がある（`apt-get install -y fonts-ipafont-gothic`）"]))
    rep.h("2. 列ごとの図と数値")
    for col, name, st, order, n_cats in summary:
        rep.h(col, 3)
        rep.img(f"figs/{name}.png", f"{col} のカテゴリ別の統計")
        first = st.drop_duplicates("category").set_index("category")
        head = ["カテゴリ", "件数", "割合"] + ([f"{target} の平均"] if target else []) + [f"{v} の中央値" for v in values]
        rows = []
        for cat in order:
            r = [cat, int(first.loc[cat, "count"]), tc.pct(first.loc[cat, "share"])]
            d = st[st["category"] == cat].set_index("value")
            r += ([d.loc[target, "mean"]] if target else []) + [d.loc[v, "median"] for v in values]
            rows.append(r)
        rep.table(head, rows)
        if target and len(order) >= 2:
            d = st[(st["value"] == target) & (st["n"] >= 20)]
            if len(d) >= 2:
                hi, lo = d.loc[d["mean"].idxmax()], d.loc[d["mean"].idxmin()]
                rep.p(f"`{target}` の平均が最も高いのは **{hi['category']}**（{tc.fmt(float(hi['mean']))}、{int(hi['n'])} 件）、"
                      f"最も低いのは **{lo['category']}**（{tc.fmt(float(lo['mean']))}、{int(lo['n'])} 件）。20 件以上のカテゴリで比較。")
    pd.concat(all_stats).to_csv(out / "category_stats.csv", index=False, encoding="utf-8-sig")
    path = rep.save(out)
    print(f"可視化完了: カテゴリ列 {len(cols)} 個 → 画像 {len(cols)} 枚（{out / 'figs'}）\nレポート: {path}")


if __name__ == "__main__":
    main()
