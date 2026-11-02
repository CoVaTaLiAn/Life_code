"""表形式データを統計的に可視化して、特徴量の傾向をまとめて確認するスクリプト。

使い方:
    python table_viz.py data.csv
    python table_viz.py data.xlsx --target group --out result
    python table_viz.py data.csv --target y --exclude id --max-pair 6

出力 (--out フォルダ):
    summary_numeric.csv / summary_categorical.csv  … 記述統計
    group_tests.csv                                … --target 指定時の群間検定
    01_missing.png ~ 08_pca.png                     … 各種グラフ
    report.html                                    … 上記をまとめたレポート
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

sns.set_theme(style="whitegrid", context="notebook")


def use_japanese_font():
    """PC に入っている日本語フォントを探して使う（Windows / Mac / Linux 対応）。"""
    from matplotlib import font_manager
    candidates = ["Yu Gothic", "Meiryo", "MS Gothic", "Hiragino Sans", "Hiragino Maru Gothic Pro",
                  "IPAexGothic", "IPAGothic", "Noto Sans CJK JP", "Noto Sans JP", "TakaoGothic"]
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return
    print("※ 日本語フォントが見つかりません。日本語の列名は □ で表示される場合があります。")


use_japanese_font()


# ---------- 読み込み ----------
def load_table(path: Path, sheet: str | None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, sheet_name=sheet or 0)
    sep = "\t" if suffix in (".tsv", ".txt") else ","
    for enc in ("utf-8-sig", "cp932"):  # Excel 由来の Shift_JIS にも対応
        try:
            return pd.read_csv(path, sep=sep, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"文字コードを判別できません: {path}")


def split_columns(df: pd.DataFrame, max_levels: int) -> tuple[list[str], list[str]]:
    """数値列とカテゴリ列に分ける。種類が少ない数値（0/1 など）はカテゴリ扱い。"""
    num, cat = [], []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) and s.nunique(dropna=True) > max_levels:
            num.append(c)
        elif s.nunique(dropna=True) <= 50:
            cat.append(c)
        # 種類が多すぎる文字列（ID や自由記述）は除外
    return num, cat


# ---------- 統計量 ----------
def numeric_summary(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    rows = []
    for c in cols:
        s = df[c].dropna()
        q1, q3 = s.quantile([0.25, 0.75])
        iqr = q3 - q1
        n_out = int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum())
        # 正規性: n が小さければ Shapiro-Wilk、大きければ D'Agostino
        if len(s) < 3:
            p_norm = np.nan
        elif len(s) <= 5000:
            p_norm = stats.shapiro(s).pvalue
        else:
            p_norm = stats.normaltest(s).pvalue
        rows.append({
            "列": c, "件数": len(s), "欠損率%": round(df[c].isna().mean() * 100, 1),
            "平均": s.mean(), "標準偏差": s.std(), "最小": s.min(), "第1四分位": q1,
            "中央値": s.median(), "第3四分位": q3, "最大": s.max(),
            "歪度": stats.skew(s), "尖度": stats.kurtosis(s),
            "外れ値数(IQR)": n_out, "正規性p値": p_norm,
            "正規分布?": "No" if p_norm < 0.05 else "Yes",
        })
    return pd.DataFrame(rows).round(4)


def categorical_summary(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    rows = []
    for c in cols:
        vc = df[c].value_counts(dropna=True)
        rows.append({
            "列": c, "件数": int(df[c].notna().sum()),
            "欠損率%": round(df[c].isna().mean() * 100, 1), "水準数": len(vc),
            "最頻値": vc.index[0] if len(vc) else None,
            "最頻値の割合%": round(vc.iloc[0] / vc.sum() * 100, 1) if len(vc) else None,
        })
    return pd.DataFrame(rows)


def group_tests(df, num, cat, target) -> pd.DataFrame:
    """target の群ごとに各特徴量の差を検定し、p値の小さい順に並べる。"""
    rows = []
    groups = df[target].dropna().unique()
    for c in num:
        data = [df.loc[df[target] == g, c].dropna() for g in groups]
        data = [d for d in data if len(d) >= 2]
        if len(data) < 2:
            continue
        if len(data) == 2:
            p_t = stats.ttest_ind(*data, equal_var=False).pvalue
            p_np = stats.mannwhitneyu(*data).pvalue
            names = ("Welch t検定", "Mann-Whitney U")
            # 効果量 Cohen's d
            pooled = np.sqrt((data[0].var() + data[1].var()) / 2)
            eff = (data[0].mean() - data[1].mean()) / pooled if pooled else np.nan
            eff_name = "Cohen's d"
        else:
            p_t = stats.f_oneway(*data).pvalue
            p_np = stats.kruskal(*data).pvalue
            names = ("一元配置ANOVA", "Kruskal-Wallis")
            allv = np.concatenate(data)
            ss_b = sum(len(d) * (d.mean() - allv.mean()) ** 2 for d in data)
            ss_t = ((allv - allv.mean()) ** 2).sum()
            eff, eff_name = (ss_b / ss_t if ss_t else np.nan), "η²"
        rows.append({"特徴量": c, "型": "数値", "パラメトリック検定": names[0], "p値": p_t,
                     "ノンパラ検定": names[1], "p値(ノンパラ)": p_np,
                     "効果量": eff_name, "効果量の値": eff})
    for c in cat:
        if c == target:
            continue
        tab = pd.crosstab(df[c], df[target])
        if tab.shape[0] < 2 or tab.shape[1] < 2:
            continue
        chi2, p, _, _ = stats.chi2_contingency(tab)
        v = np.sqrt(chi2 / (tab.values.sum() * (min(tab.shape) - 1)))
        rows.append({"特徴量": c, "型": "カテゴリ", "パラメトリック検定": "カイ二乗検定", "p値": p,
                     "ノンパラ検定": "", "p値(ノンパラ)": np.nan,
                     "効果量": "Cramér's V", "効果量の値": v})
    if not rows:
        return pd.DataFrame()
    res = pd.DataFrame(rows)
    # 多重比較補正 (Benjamini-Hochberg)
    res["q値(BH補正)"] = stats.false_discovery_control(res["p値"].fillna(1))
    res["有意(q<0.05)"] = np.where(res["q値(BH補正)"] < 0.05, "★", "")
    return res.sort_values("p値").round(5)


# ---------- グラフ ----------
def grid(n, ncol=4, size=3.2):
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(ncol * size, nrow * size * 0.85), squeeze=False)
    for ax in axes.flat[n:]:
        ax.set_visible(False)
    return fig, axes.flat


def save(fig, out: Path, name: str, saved: list):
    fig.tight_layout()
    fig.savefig(out / name, dpi=130, bbox_inches="tight")
    plt.close(fig)
    saved.append(name)


def plot_missing(df, out, saved):
    miss = df.isna().mean().sort_values(ascending=False) * 100
    if miss.max() == 0:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, max(4, len(df.columns) * 0.25)),
                                 gridspec_kw={"width_ratios": [1, 2]})
    miss.plot.barh(ax=a1, color="#d9534f")
    a1.invert_yaxis(); a1.set_xlabel("欠損率 (%)"); a1.set_title("列ごとの欠損率")
    sns.heatmap(df.isna().T, cbar=False, ax=a2, cmap=["#eeeeee", "#d9534f"])
    a2.set_title("欠損の位置（赤=欠損）"); a2.set_xlabel("行")
    save(fig, out, "01_missing.png", saved)


def plot_distributions(df, num, out, saved, target=None):
    if not num:
        return
    fig, axes = grid(len(num))
    for ax, c in zip(axes, num):
        sns.histplot(df, x=c, hue=target, kde=True, ax=ax, element="step", stat="density",
                     common_norm=False, legend=(c == num[0]))
        s = df[c].dropna()
        ax.set_title(f"{c}\n歪度={stats.skew(s):.2f}", fontsize=10)
        ax.set_xlabel("")
    fig.suptitle("数値特徴量の分布（ヒストグラム + KDE）", y=1.01)
    save(fig, out, "02_distributions.png", saved)


def plot_boxes(df, num, out, saved, target=None):
    if not num:
        return
    fig, axes = grid(len(num))
    for ax, c in zip(axes, num):
        if target:
            sns.boxplot(df, x=target, y=c, ax=ax, showfliers=False, color="#cfe2f3")
            sns.stripplot(df, x=target, y=c, ax=ax, size=2.5, alpha=0.5, color="#1f4e79")
        else:
            sns.boxplot(df, y=c, ax=ax, color="#cfe2f3")
        ax.set_title(c, fontsize=10); ax.set_ylabel("")
    title = f"箱ひげ図（{target} 別）" if target else "箱ひげ図（外れ値の確認）"
    fig.suptitle(title, y=1.01)
    save(fig, out, "03_boxplots.png", saved)


def plot_categoricals(df, cat, out, saved, target=None):
    cat = [c for c in cat if c != target]
    if not cat:
        return
    fig, axes = grid(len(cat), ncol=3, size=4)
    for ax, c in zip(axes, cat):
        order = df[c].value_counts().index[:20]
        if target:
            ct = pd.crosstab(df[c], df[target], normalize="index").loc[order] * 100
            ct.plot.barh(stacked=True, ax=ax, legend=(c == cat[0]), colormap="Set2")
            ax.set_xlabel(f"{target} の割合 (%)")
        else:
            sns.countplot(df, y=c, order=order, ax=ax, color="#5b9bd5")
        ax.set_title(c, fontsize=10); ax.set_ylabel("")
    fig.suptitle("カテゴリ特徴量の内訳", y=1.01)
    save(fig, out, "04_categorical.png", saved)


def plot_correlation(df, num, out, saved):
    if len(num) < 2:
        return
    size = max(6, len(num) * 0.55)
    fig, axes = plt.subplots(1, 2, figsize=(size * 2, size))
    for ax, method in zip(axes, ["pearson", "spearman"]):
        corr = df[num].corr(method=method)
        mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
        sns.heatmap(corr, mask=mask, cmap="RdBu_r", vmin=-1, vmax=1, center=0,
                    annot=len(num) <= 15, fmt=".2f", square=True, ax=ax,
                    cbar_kws={"shrink": 0.7})
        ax.set_title({"pearson": "Pearson 相関（直線関係）",
                      "spearman": "Spearman 相関（順位・単調関係）"}[method])
    save(fig, out, "05_correlation.png", saved)


def plot_top_pairs(df, num, out, saved, top=8):
    """相関の強いペアを散布図で確認。"""
    if len(num) < 2:
        return
    corr = df[num].corr(method="spearman").abs()
    pairs = (corr.where(np.triu(np.ones_like(corr, dtype=bool), k=1))
             .stack().sort_values(ascending=False).head(top))
    fig, axes = grid(len(pairs))
    for ax, ((a, b), r) in zip(axes, pairs.items()):
        sns.regplot(df, x=a, y=b, ax=ax, scatter_kws={"s": 8, "alpha": 0.5},
                    line_kws={"color": "#c00000"})
        ax.set_title(f"|ρ|={r:.2f}", fontsize=10)
    fig.suptitle("相関の強い特徴量ペア（上位）", y=1.01)
    save(fig, out, "06_top_pairs.png", saved)


def plot_pairplot(df, num, out, saved, target, max_cols):
    if len(num) < 2:
        return
    cols = num
    if len(num) > max_cols:  # 分散の大きい（情報量の多い）列を優先
        cols = df[num].apply(lambda s: s.std() / (abs(s.mean()) + 1e-9)).nlargest(max_cols).index.tolist()
    sample = df if len(df) <= 2000 else df.sample(2000, random_state=0)
    g = sns.pairplot(sample[cols + ([target] if target else [])].dropna(), hue=target,
                     corner=True, diag_kind="kde", plot_kws={"s": 10, "alpha": 0.6})
    g.figure.suptitle("ペアプロット", y=1.01)
    g.savefig(out / "07_pairplot.png", dpi=110, bbox_inches="tight")
    plt.close(g.figure)
    saved.append("07_pairplot.png")


def plot_pca(df, num, out, saved, target=None):
    if len(num) < 3:
        return
    X = df[num].dropna()
    if len(X) < 5:
        return
    Z = ((X - X.mean()) / X.std(ddof=0).replace(0, 1)).values
    U, S, Vt = np.linalg.svd(Z, full_matrices=False)
    ratio = S ** 2 / (S ** 2).sum()
    pcs = Z @ Vt[:2].T
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))
    # 寄与率
    k = min(10, len(ratio))
    axes[0].bar(range(1, k + 1), ratio[:k] * 100, color="#5b9bd5")
    axes[0].plot(range(1, k + 1), np.cumsum(ratio[:k]) * 100, "o-", color="#c00000", label="累積")
    axes[0].set_xlabel("主成分"); axes[0].set_ylabel("寄与率 (%)"); axes[0].legend()
    axes[0].set_title("主成分の寄与率")
    # スコア
    hue = df.loc[X.index, target].astype(str) if target else None
    sns.scatterplot(x=pcs[:, 0], y=pcs[:, 1], hue=hue, ax=axes[1], s=15, alpha=0.7)
    axes[1].set_xlabel(f"PC1 ({ratio[0]*100:.1f}%)"); axes[1].set_ylabel(f"PC2 ({ratio[1]*100:.1f}%)")
    axes[1].set_title("PCA スコアプロット")
    # 負荷量（どの特徴量が効いているか）
    load = pd.DataFrame(Vt[:2].T, index=num, columns=["PC1", "PC2"])
    load = load.loc[load.abs().max(axis=1).sort_values(ascending=False).index[:15]]
    load.plot.barh(ax=axes[2], color=["#5b9bd5", "#ed7d31"])
    axes[2].invert_yaxis(); axes[2].set_title("負荷量（寄与の大きい特徴量）")
    save(fig, out, "08_pca.png", saved)


def plot_group_effects(res, out, saved):
    """群間検定の結果を -log10(q) で並べ、効いている特徴量を一目で見る。"""
    if res.empty:
        return
    r = res.head(25).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, max(3, len(r) * 0.32)))
    vals = -np.log10(r["q値(BH補正)"].clip(lower=1e-300))
    ax.barh(r["特徴量"].astype(str), vals,
            color=np.where(r["q値(BH補正)"] < 0.05, "#c00000", "#aaaaaa"))
    ax.axvline(-np.log10(0.05), ls="--", color="k", lw=1)
    ax.set_xlabel("-log10(q値)  ← 右ほど群間差が大きい（破線: q=0.05）")
    ax.set_title("目的変数との関連の強さ")
    save(fig, out, "09_group_effects.png", saved)


# ---------- HTML レポート ----------
def write_report(out, src, df, tables: dict, images: list):
    parts = [f"<h1>データ可視化レポート</h1><p>ファイル: {html.escape(str(src))} ／ "
             f"{len(df):,} 行 × {df.shape[1]} 列</p>"]
    for title, t in tables.items():
        if t is not None and not t.empty:
            parts.append(f"<h2>{title}</h2>" + t.to_html(index=False, na_rep="", classes="t"))
    for img in images:
        parts.append(f'<h2>{img[3:-4]}</h2><img src="{img}">')
    css = ("body{font-family:sans-serif;max-width:1400px;margin:auto;padding:16px}"
           "img{max-width:100%;border:1px solid #ddd}"
           ".t{border-collapse:collapse;font-size:12px;display:block;overflow-x:auto}"
           ".t td,.t th{border:1px solid #ccc;padding:3px 6px;text-align:right}"
           ".t th{background:#f0f4fa}")
    (out / "report.html").write_text(
        f"<!doctype html><meta charset='utf-8'><style>{css}</style>{''.join(parts)}",
        encoding="utf-8")


# ---------- メイン ----------
def main():
    ap = argparse.ArgumentParser(description="表データの統計可視化")
    ap.add_argument("file", type=Path, help="CSV / TSV / Excel ファイル")
    ap.add_argument("--target", help="群分け・目的変数の列名（群間比較を行う）")
    ap.add_argument("--exclude", nargs="*", default=[], help="除外する列（ID など）")
    ap.add_argument("--sheet", help="Excel のシート名")
    ap.add_argument("--out", type=Path, help="出力フォルダ（既定: <ファイル名>_viz）")
    ap.add_argument("--max-levels", type=int, default=10,
                    help="数値でもこの種類数以下ならカテゴリ扱い（既定 10）")
    ap.add_argument("--max-pair", type=int, default=6, help="ペアプロットに使う最大列数")
    args = ap.parse_args()

    df = load_table(args.file, args.sheet).drop(columns=args.exclude, errors="ignore")
    out = args.out or args.file.with_name(args.file.stem + "_viz")
    out.mkdir(parents=True, exist_ok=True)

    target = args.target
    if target and target not in df.columns:
        raise SystemExit(f"--target の列が見つかりません: {target}")
    num, cat = split_columns(df, args.max_levels)
    if target:
        num = [c for c in num if c != target]
        if pd.api.types.is_numeric_dtype(df[target]) and df[target].nunique() > args.max_levels:
            # 連続値の目的変数は四分位で 4 群に分けて比較
            df[target] = pd.qcut(df[target], 4, duplicates="drop").astype(str)
        df[target] = df[target].astype(str).where(df[target].notna())
        if target not in cat:
            cat.append(target)
    print(f"{len(df)} 行 / 数値 {len(num)} 列 / カテゴリ {len(cat)} 列")

    s_num, s_cat = numeric_summary(df, num), categorical_summary(df, cat)
    s_num.to_csv(out / "summary_numeric.csv", index=False, encoding="utf-8-sig")
    s_cat.to_csv(out / "summary_categorical.csv", index=False, encoding="utf-8-sig")
    tests = group_tests(df, num, cat, target) if target else pd.DataFrame()
    if not tests.empty:
        tests.to_csv(out / "group_tests.csv", index=False, encoding="utf-8-sig")

    saved: list[str] = []
    plot_missing(df, out, saved)
    plot_distributions(df, num, out, saved, target)
    plot_boxes(df, num, out, saved, target)
    plot_categoricals(df, cat, out, saved, target)
    plot_correlation(df, num, out, saved)
    plot_top_pairs(df, num, out, saved)
    plot_pairplot(df, num, out, saved, target, args.max_pair)
    plot_pca(df, num, out, saved, target)
    plot_group_effects(tests, out, saved)

    write_report(out, args.file, df, {
        "群間比較（p値の小さい順）": tests,
        "数値特徴量の記述統計": s_num,
        "カテゴリ特徴量の記述統計": s_cat,
    }, saved)
    print(f"出力先: {out}/report.html")


if __name__ == "__main__":
    main()
