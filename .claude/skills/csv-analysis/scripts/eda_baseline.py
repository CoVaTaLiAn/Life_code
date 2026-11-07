#!/usr/bin/env python3
"""CSV の初期分析: クレンジング → 初期統計 → 特徴量エンジニアリング案 → ベースラインモデル → レポート。

使い方:
  python3 eda_baseline.py run --train train.csv --target y --out analysis/<dir> \
      [--test test.csv] [--task auto|binary|multiclass|regression] [--metric auc] \
      [--id ID] [--time date] [--group user_id] [--drop a,b] [--title "課題名"] [--goal "課題の説明"]
  python3 eda_baseline.py render --out analysis/<dir>   # insights.md を書いた後にレポートを作り直す

出力 (<out>/): report.md, report.html（画像埋め込み・単体で開ける）, figs/*.png, results.json,
  cleaned_train.csv, column_profile.csv, oof.csv, worst_errors.csv, predictions.csv（--test 時）

必要: pandas numpy scipy scikit-learn matplotlib（lightgbm があれば使う。なければ sklearn の HistGradientBoosting）
"""
import argparse
import base64
import csv
import datetime as dt
import html
import io
import json
import re
import sys
import time
import unicodedata
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

try:
    import lightgbm as lgb
except Exception:  # pragma: no cover
    lgb = None

SEED = 42
NULL_TOKENS = {"", "na", "n/a", "nan", "null", "none", "nil", "-", "--", "―", "—", "?", "#n/a",
               "#null!", "#value!", "missing", "(blank)", "undefined", "inf", "-inf"}
BOOL_MAP = {"true": 1, "false": 0, "yes": 1, "no": 0, "y": 1, "n": 0, "t": 1, "f": 0,
            "はい": 1, "いいえ": 0, "有": 1, "無": 0, "あり": 1, "なし": 0, "○": 1, "×": 0,
            "on": 1, "off": 0}
NUM_STRIP = r"[,\s¥$€£円%]"
DATE_LIKE = re.compile(r"^\d{4}[-/.年]\d{1,2}([-/.月]\d{1,2})?|^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}")
ID_NAME = re.compile(r"(^|[_\s])(id|ID|Id)$|^(id|ID)([_\s]|$)|番号|ＩＤ|コード$|^uuid$", re.I)


# ---------------------------------------------------------------- 共通
def setup_font():
    names = {f.name for f in font_manager.fontManager.ttflist}
    for c in ["IPAexGothic", "IPAGothic", "Noto Sans CJK JP", "Noto Sans JP", "Hiragino Sans",
              "Yu Gothic", "Meiryo", "TakaoGothic"]:
        if c in names:
            plt.rcParams["font.family"] = c
            break
    plt.rcParams.update({"axes.unicode_minus": False, "figure.dpi": 110, "axes.grid": True,
                         "grid.alpha": .3, "axes.spines.top": False, "axes.spines.right": False})


def fmt(v, nd=3):
    if v is None:
        return "-"
    if isinstance(v, (float, np.floating)):
        if np.isnan(v):
            return "-"
        a = abs(v)
        if a != 0 and (a >= 1e6 or a < 1e-3):
            return f"{v:.2e}"
        return f"{v:,.{nd}f}".rstrip("0").rstrip(".") if nd else f"{v:,.0f}"
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    return str(v).replace("|", "／").replace("\n", " ")


def pct(v):
    return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v * 100:.1f}%"


def md_table(df, max_rows=60):
    if df is None or len(df) == 0:
        return "_（該当なし）_\n"
    df = df.head(max_rows)
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(fmt(v) for v in r.values) + " |")
    return "\n".join(lines) + "\n"


def savefig(fig, out, name):
    p = out / "figs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return f"figs/{name}"


def short(s, n=18):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + "…"


# ---------------------------------------------------------------- 読み込み・クレンジング
def read_csv_any(path, sep=None):
    raw = Path(path).read_bytes()
    enc = "latin-1"
    for e in ["utf-8-sig", "utf-8", "cp932", "euc-jp"]:
        try:
            text = raw.decode(e)
            enc = e
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")
    if sep is None:
        try:
            sep = csv.Sniffer().sniff(text[:50000], delimiters=",\t;|").delimiter
        except csv.Error:
            sep = ","
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
    return df, enc, sep


def normalize_colnames(cols, log):
    out, seen = [], set()
    for i, c in enumerate(cols):
        n = re.sub(r"\s+", "_", unicodedata.normalize("NFKC", str(c)).strip())
        if not n or n.lower().startswith("unnamed:"):
            n = f"col_{i}"
        base, k = n, 1
        while n in seen:
            n = f"{base}_{k}"
            k += 1
        seen.add(n)
        out.append(n)
    changed = [(a, b) for a, b in zip(cols, out) if a != b]
    if changed:
        log.append(("列名の正規化（全角→半角・空白→_・重複/空の列名）",
                    f"{len(changed)}列: " + ", ".join(f"`{a}`→`{b}`" for a, b in changed[:8])
                    + (" …" if len(changed) > 8 else "")))
    return out


def parse_numeric(s):
    t = s.str.replace(NUM_STRIP, "", regex=True).str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    t = t.str.replace(r"^▲", "-", regex=True)
    return pd.to_numeric(t, errors="coerce")


def parse_datetime(s):
    t = s.str.replace(r"[年月]", "-", regex=True).str.replace("日", "", regex=False)
    d = pd.to_datetime(t, errors="coerce", format="mixed")
    try:
        if getattr(d.dt, "tz", None) is not None:
            d = d.dt.tz_convert(None)
    except Exception:
        pass
    return d


def infer_column(s, forced=None):
    """s: 文字列 Series（欠損は NaN）。(変換後 Series, 種類, メモ) を返す。"""
    nn = s.dropna()
    if forced is None and len(nn) == 0:
        return s, "empty", ""
    if forced in (None, "numeric"):
        num = parse_numeric(nn)
        ratio = num.notna().mean() if len(nn) else 1.0
        if forced == "numeric" or ratio >= 0.95:
            full = parse_numeric(s)
            bad = nn[num.isna()].unique()[:5]
            note = []
            if len(bad):
                note.append(f"数値にできない値 {int(num.isna().sum())}件を欠損に（例: {', '.join(map(str, bad))}）")
            if len(nn) and nn.str.contains(r"[,¥$円%]", regex=True).mean() > 0.1:
                note.append("桁区切り・通貨記号・% を除去して数値化")
            return full, "numeric", "; ".join(note)
    if forced in (None, "bool"):
        low = nn.str.lower()
        u = set(low.unique())
        if forced == "bool" or (len(u) == 2 and u <= set(BOOL_MAP)):
            return s.str.lower().map(BOOL_MAP).astype(float), "bool", f"{sorted(u)} を 0/1 に変換" if forced is None else ""
    if forced in (None, "datetime"):
        smp = nn.sample(min(300, len(nn)), random_state=0) if len(nn) else nn
        if forced == "datetime" or (len(smp) and smp.str.match(DATE_LIKE).mean() >= 0.9):
            d = parse_datetime(s)
            if forced == "datetime" or d[nn.index].notna().mean() >= 0.9:
                nbad = int(d[nn.index].isna().sum())
                return d, "datetime", (f"日時にできない値 {nbad}件を欠損に" if nbad else "")
    if forced == "text":
        return s, "text", ""
    if forced == "category":
        return s, "category", ""
    if len(nn) and nn.str.len().mean() >= 30 and nn.nunique() / len(nn) > 0.5:
        return s, "text", ""
    return s, "category", ""


def clean(df_raw, log, schema=None, target=None, drop_cols=()):
    df = df_raw.copy()
    df.columns = normalize_colnames(list(df.columns), log)
    n_nfkc = n_null = 0
    tokens_seen = {}
    for c in df.columns:
        s0 = df[c].astype(str)
        s = s0.str.normalize("NFKC").str.strip()
        n_nfkc += int((s != s0.str.strip()).sum())
        is_null = s.str.lower().isin(NULL_TOKENS)
        for tkn, k in s[is_null & (s != "")].value_counts().head(5).items():
            tokens_seen[tkn] = tokens_seen.get(tkn, 0) + int(k)
        n_null += int(is_null.sum())
        df[c] = s.mask(is_null)
    if n_nfkc:
        log.append(("全角英数・記号を半角に、前後の空白を除去", f"{n_nfkc:,}セル"))
    if n_null:
        tk = ", ".join(f"'{k}'({v})" for k, v in sorted(tokens_seen.items(), key=lambda x: -x[1])[:8])
        log.append(("欠損の表記を統一（空文字・NA・- など → 欠損）", f"{n_null:,}セル" + (f"。空文字以外: {tk}" if tk else "")))

    kinds, out = {}, {}
    for c in df.columns:
        if c in drop_cols:
            continue
        if schema is not None:
            if c not in schema:
                continue
            ser, k, note = infer_column(df[c], forced=schema[c] if schema[c] != "empty" else "category")
            k = schema[c]
        else:
            ser, k, note = infer_column(df[c])
            if note:
                log.append((f"`{c}` の型変換（→{k}）", note))
        out[c] = ser
        kinds[c] = k
    res = pd.DataFrame(out, index=df.index)
    for c, k in kinds.items():
        if k != "category":
            continue
        s = res[c]
        key = s.str.lower().str.replace(r"[\s_\-・]", "", regex=True)
        canon = s.groupby(key).agg(lambda v: v.value_counts().idxmax())
        mapped = key.map(canon).where(s.notna())
        changed = (mapped != s) & s.notna()
        if changed.any():
            ex = ", ".join(f"'{a}'→'{b}'" for a, b in pd.DataFrame({"a": s[changed], "b": mapped[changed]}).drop_duplicates().head(5).values)
            if schema is None:
                log.append((f"`{c}` の表記ゆれを統一（大文字小文字・空白・記号の違い）", f"{int(changed.sum())}セル: {ex}"))
            res[c] = mapped
    if schema is not None:
        for c in schema:
            if c not in res.columns and c != target:
                res[c] = np.nan
        return res, kinds

    if drop_cols:
        log.append(("指定された列を除外", ", ".join(drop_cols)))
    # 全部欠損
    empty = [c for c in res.columns if res[c].isna().all()]
    # 連番インデックス列（CSV に書き出された index）
    idx_like = []
    for c in res.columns:
        if kinds[c] == "numeric" and re.match(r"^col_\d+$|^index$", c, re.I):
            v = res[c].dropna().values
            if len(v) == len(res) and (np.array_equal(v, np.arange(len(v))) or np.array_equal(v, np.arange(1, len(v) + 1))):
                idx_like.append(c)
    const = [c for c in res.columns if c not in empty and c != target and res[c].nunique(dropna=False) <= 1]
    dropped = set(empty + idx_like + const)
    # 中身が同じ列
    dup_cols, seen = [], {}
    for c in res.columns:
        if c in dropped or c == target:
            continue
        key = pd.util.hash_pandas_object(res[c].astype(str), index=False).sum()
        if key in seen and res[c].astype(str).equals(res[seen[key]].astype(str)):
            dup_cols.append(f"{c}(= {seen[key]})")
            dropped.add(c)
        else:
            seen[key] = c
    if empty:
        log.append(("全て欠損の列を削除", ", ".join(empty)))
    if idx_like:
        log.append(("連番インデックス列を削除", ", ".join(idx_like)))
    if const:
        log.append(("値が1種類しかない列を削除", ", ".join(const)))
    if dup_cols:
        log.append(("他の列と中身が同じ列を削除", ", ".join(dup_cols)))
    res = res.drop(columns=list(dropped))
    for c in dropped:
        kinds.pop(c, None)
    nd = int(res.duplicated().sum())
    if nd:
        log.append(("完全に重複した行を削除", f"{nd:,}行"))
        res = res.drop_duplicates()
    return res, kinds


SENTINELS = [-1, -9, -99, -999, -9999, 99, 999, 9999, 99999, 999999]


def suspicious_values(df, kinds, cols):
    """欠損コード（999, -1 など）や極端な外れ値の候補。置換はせず報告だけ。"""
    notes = []
    for c in cols:
        if kinds.get(c) != "numeric":
            continue
        s = df[c].dropna()
        if len(s) < 20 or s.nunique() < 5:
            continue
        q1, q3 = s.quantile([.25, .75])
        iqr = q3 - q1
        for v in SENTINELS:
            k = int((s == v).sum())
            if k >= 2 and k / len(s) < 0.2 and iqr > 0 and (v > q3 + 5 * iqr or v < q1 - 5 * iqr or (v < 0 and bool((s[s != v] >= 0).all()))):
                notes.append((c, f"`{v}` が {k}件（他の値から大きく外れている）", "欠損コードの可能性。意味を確認し、欠損として扱う（NaN に置換＋欠損フラグ）"))
        if iqr > 0:
            far = s[(s > q3 + 10 * iqr) | (s < q1 - 10 * iqr)]
            far = far[~far.isin(SENTINELS)]
            if 0 < len(far) <= max(5, 0.005 * len(s)):
                notes.append((c, f"極端な値が {len(far)}件（例: {', '.join(fmt(x) for x in far.head(3))}）", "入力ミスか確認。誤りなら修正/除外、正しければクリップ"))
    return notes


def detect_ids(df, kinds, target, user_ids):
    ids = list(user_ids)
    for c in df.columns:
        if c == target or c in ids:
            continue
        s = df[c].dropna()
        if len(s) < 20:
            continue
        nun = s.nunique()
        name_hit = bool(ID_NAME.search(c))
        k = kinds[c]
        if k == "numeric":
            intlike = bool((s % 1 == 0).all())
            if intlike and nun >= 0.99 * len(s) and (name_hit or s.is_monotonic_increasing or s.is_monotonic_decreasing):
                ids.append(c)
            elif name_hit and intlike and nun > 0.5 * len(s):
                ids.append(c)
        elif k == "category" and (nun >= 0.95 * len(s) or (name_hit and nun > 0.5 * len(s))):
            ids.append(c)
    return ids


# ---------------------------------------------------------------- 統計
def column_profile(df, kinds, roles):
    rows = []
    n = len(df)
    for c in df.columns:
        s = df[c]
        k = kinds[c]
        r = {"列": c, "種類": k, "役割": roles.get(c, "特徴量"), "欠損率": s.isna().mean(), "ユニーク数": int(s.nunique())}
        nn = s.dropna()
        if k in ("numeric", "bool") and len(nn):
            q1, q3 = nn.quantile([.25, .75])
            iqr = q3 - q1
            r.update({"平均": nn.mean(), "標準偏差": nn.std(), "最小": nn.min(), "25%": q1, "中央値": nn.median(),
                      "75%": q3, "最大": nn.max(), "歪度": nn.skew() if len(nn) > 2 else np.nan,
                      "ゼロ率": (nn == 0).mean(), "外れ値率(IQR1.5)": ((nn < q1 - 1.5 * iqr) | (nn > q3 + 1.5 * iqr)).mean() if iqr > 0 else 0.0,
                      "負の値": int((nn < 0).sum())})
        elif k == "datetime" and len(nn):
            r.update({"最小": str(nn.min())[:19], "最大": str(nn.max())[:19]})
        elif len(nn):
            vc = nn.value_counts()
            r.update({"最頻値": short(vc.index[0], 24), "最頻値の割合": vc.iloc[0] / len(nn),
                      "1%未満のカテゴリ数": int((vc / len(nn) < 0.01).sum()),
                      "平均文字数": nn.str.len().mean()})
        r["n"] = n
        rows.append(r)
    return pd.DataFrame(rows)


def feature_numeric_view(df, kinds, feats):
    """MI 計算などのための数値行列。"""
    X = pd.DataFrame(index=df.index)
    disc = []
    for c in feats:
        k = kinds[c]
        if k in ("numeric", "bool"):
            X[c] = df[c].astype(float)
            disc.append(k == "bool")
        elif k == "datetime":
            X[c] = (df[c] - pd.Timestamp("1970-01-01")).dt.days.astype(float)
            disc.append(False)
        elif k == "category":
            vc = df[c].value_counts()
            keep = vc.index[:50]
            X[c] = pd.Categorical(df[c].where(df[c].isin(keep), "__other__")).codes.astype(float)
            disc.append(True)
        elif k == "text":
            X[c] = df[c].str.len().astype(float)
            disc.append(False)
    X = X.replace([np.inf, -np.inf], np.nan)
    return X, np.array(disc, dtype=bool)


def cramers_v(x, y):
    from scipy.stats import chi2_contingency
    tab = pd.crosstab(x, y)
    if tab.shape[0] < 2 or tab.shape[1] < 2:
        return np.nan
    chi2 = chi2_contingency(tab, correction=False)[0]
    n = tab.values.sum()
    return float(np.sqrt(chi2 / n / (min(tab.shape) - 1)))


def eta_squared(groups, y):
    d = pd.DataFrame({"g": groups.values, "y": np.asarray(y, dtype=float)}).dropna()
    if d["g"].nunique() < 2:
        return np.nan
    m = d["y"].mean()
    ssb = d.groupby("g")["y"].agg(lambda v: len(v) * (v.mean() - m) ** 2).sum()
    sst = ((d["y"] - m) ** 2).sum()
    return float(ssb / sst) if sst > 0 else np.nan


def univariate(df, kinds, feats, y, task):
    from scipy.stats import spearmanr
    from sklearn.feature_selection import mutual_info_classif, mutual_info_regression
    from sklearn.metrics import roc_auc_score

    X, disc = feature_numeric_view(df, kinds, feats)
    idx = X.index
    if len(idx) > 20000:
        idx = X.sample(20000, random_state=SEED).index
    Xm = X.loc[idx].copy()
    for c in Xm.columns:
        Xm[c] = Xm[c].fillna(Xm[c].median() if Xm[c].notna().any() else 0)
    ym = y.loc[idx]
    mi_fn = mutual_info_regression if task == "regression" else mutual_info_classif
    mi = mi_fn(Xm.values, ym.values, discrete_features=disc, random_state=SEED) if len(feats) else []
    rows = []
    for c, m in zip(X.columns, mi):
        k = kinds[c]
        s = df[c]
        r = {"特徴量": c, "種類": k, "相互情報量": float(m), "欠損率": float(s.isna().mean())}
        mask = s.notna()
        if k == "category":
            g = s.fillna("__NA__")
            if task == "regression":
                r["指標"], r["値"] = "η²(相関比)", eta_squared(g, y)
            else:
                r["指標"], r["値"] = "Cramér's V", cramers_v(g, y)
        else:
            v = X[c]
            if task == "binary":
                try:
                    auc = roc_auc_score(y[mask], v[mask])
                except ValueError:
                    auc = np.nan
                r["指標"], r["値"] = "単変量AUC", auc
                r["向き"] = "-" if np.isnan(auc) else ("大きいほど陽性" if auc >= 0.5 else "小さいほど陽性")
            elif task == "multiclass":
                r["指標"], r["値"] = "η²(相関比)", eta_squared(pd.Series(y[mask].values), v[mask])
            else:
                rho = spearmanr(v[mask], y[mask]).statistic if mask.sum() > 2 else np.nan
                r["指標"], r["値"] = "Spearman ρ", rho
                r["向き"] = "-" if np.isnan(rho) else ("正の相関" if rho > 0 else "負の相関")
        rows.append(r)
    u = pd.DataFrame(rows)
    if len(u):
        u = u.sort_values("相互情報量", ascending=False).reset_index(drop=True)
    return u


def leak_flags(u, task):
    flags = []
    for _, r in u.iterrows():
        v = r.get("値")
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        if (r["指標"] == "単変量AUC" and max(v, 1 - v) > 0.97) or \
           (r["指標"] in ("Spearman ρ",) and abs(v) > 0.97) or \
           (r["指標"] in ("Cramér's V", "η²(相関比)") and v > 0.9):
            flags.append(f"`{r['特徴量']}` 単独で目的変数をほぼ説明できます（{r['指標']}={fmt(v)}）。目的変数から作られた列・事後情報（リーク）でないか確認してください。")
    return flags


def missing_vs_target(df, feats, y, task):
    from scipy.stats import chi2_contingency, mannwhitneyu
    rows = []
    for c in feats:
        m = df[c].isna()
        if m.mean() < 0.01 or m.mean() > 0.99:
            continue
        if task == "regression":
            a, b = y[m], y[~m]
            p = mannwhitneyu(a, b).pvalue if len(a) > 2 and len(b) > 2 else np.nan
            rows.append({"特徴量": c, "欠損率": m.mean(), "欠損時の目的変数平均": a.mean(), "非欠損時の平均": b.mean(), "p値": p})
        else:
            tab = pd.crosstab(m, y)
            p = chi2_contingency(tab)[1] if tab.shape == (2, tab.shape[1]) and tab.shape[1] > 1 else np.nan
            if task == "binary":
                rows.append({"特徴量": c, "欠損率": m.mean(), "欠損時の陽性率": y[m].mean(), "非欠損時の陽性率": y[~m].mean(), "p値": p})
            else:
                rows.append({"特徴量": c, "欠損率": m.mean(), "p値": p})
    d = pd.DataFrame(rows)
    if len(d):
        d["欠損に意味がありそう"] = np.where(d["p値"] < 0.01, "○", "")
        d = d.sort_values("p値").reset_index(drop=True)
    return d


def corr_pairs(df, kinds, feats, thr=0.9):
    num = [c for c in feats if kinds[c] in ("numeric", "bool") and df[c].nunique() > 1]
    if len(num) < 2:
        return pd.DataFrame(), None
    sub = df[num].sample(min(len(df), 20000), random_state=SEED)
    cm = sub.corr(method="spearman")
    rows = []
    for i, a in enumerate(num):
        for b in num[i + 1:]:
            v = cm.loc[a, b]
            if pd.notna(v) and abs(v) >= thr:
                rows.append({"列A": a, "列B": b, "Spearman ρ": v})
    d = pd.DataFrame(rows)
    if len(d):
        d = d.reindex(d["Spearman ρ"].abs().sort_values(ascending=False).index).reset_index(drop=True)
    return d, cm


def drift(train, test, kinds, feats):
    from scipy.stats import ks_2samp
    rows = []
    for c in feats:
        k = kinds[c]
        a, b = train[c].dropna(), test[c].dropna()
        if len(a) == 0 or len(b) == 0:
            continue
        if k in ("numeric", "bool"):
            r = ks_2samp(a, b)
            rows.append({"特徴量": c, "指標": "KS統計量", "値": r.statistic, "train平均": a.mean(), "test平均": b.mean(),
                         "欠損率(train)": train[c].isna().mean(), "欠損率(test)": test[c].isna().mean()})
        elif k == "datetime":
            rows.append({"特徴量": c, "指標": "期間", "値": np.nan, "train平均": f"{str(a.min())[:10]}〜{str(a.max())[:10]}",
                         "test平均": f"{str(b.min())[:10]}〜{str(b.max())[:10]}",
                         "欠損率(train)": train[c].isna().mean(), "欠損率(test)": test[c].isna().mean()})
        elif k == "category":
            unseen = ~b.isin(set(a.unique()))
            rows.append({"特徴量": c, "指標": "trainに無いカテゴリの割合", "値": unseen.mean(), "train平均": "-", "test平均": "-",
                         "欠損率(train)": train[c].isna().mean(), "欠損率(test)": test[c].isna().mean()})
    d = pd.DataFrame(rows)
    if len(d):
        d = d.sort_values("値", ascending=False, na_position="last").reset_index(drop=True)
    return d


# ---------------------------------------------------------------- 図
def plot_target(y_raw, task, out):
    fig, axes = plt.subplots(1, 2 if task == "regression" else 1, figsize=(10 if task == "regression" else 6, 3.6))
    if task == "regression":
        y = y_raw.astype(float)
        axes[0].hist(y, bins=50, color="#4C72B0")
        axes[0].set_title("目的変数の分布")
        if y.min() >= 0:
            axes[1].hist(np.log1p(y), bins=50, color="#55A868")
            axes[1].set_title("log1p(目的変数) の分布")
        else:
            axes[1].boxplot(y, vert=False)
            axes[1].set_title("箱ひげ図")
    else:
        vc = y_raw.astype(str).value_counts()
        axes.barh([short(i) for i in vc.index[::-1]], vc.values[::-1], color="#4C72B0")
        for i, v in enumerate(vc.values[::-1]):
            axes.text(v, i, f" {v:,} ({v / vc.sum():.1%})", va="center", fontsize=8)
        axes.set_title("目的変数のクラス分布")
    return savefig(fig, out, "target.png")


def plot_missing(df, out):
    m = df.isna().mean()
    m = m[m > 0].sort_values()
    if len(m) == 0:
        return None
    m = m.tail(40)
    fig, ax = plt.subplots(figsize=(7, max(2, 0.28 * len(m) + 1)))
    ax.barh([short(i, 28) for i in m.index], m.values * 100, color="#C44E52")
    for i, v in enumerate(m.values):
        ax.text(v * 100, i, f" {v:.1%}", va="center", fontsize=8)
    ax.set_xlabel("欠損率 (%)")
    ax.set_title("列ごとの欠損率")
    return savefig(fig, out, "missing.png")


def plot_num_dists(df, cols, y, task, out, name="num_dist.png"):
    cols = cols[:16]
    if not cols:
        return None
    nc = 4
    nr = int(np.ceil(len(cols) / nc))
    fig, axes = plt.subplots(nr, nc, figsize=(13, 2.6 * nr))
    axes = np.atleast_1d(axes).ravel()
    for ax, c in zip(axes, cols):
        s = df[c].astype(float)
        lo, hi = s.quantile([.005, .995])
        if task == "regression" or y is None:
            ax.hist(s.dropna().clip(lo, hi), bins=40, color="#4C72B0")
        else:
            for cls in sorted(pd.unique(y))[:6]:
                v = s[y == cls].dropna().clip(lo, hi)
                if len(v):
                    ax.hist(v, bins=40, alpha=.5, density=True, label=str(cls))
            ax.legend(fontsize=7, title="目的変数", title_fontsize=7)
        ax.set_title(short(c, 28), fontsize=9)
        ax.tick_params(labelsize=7)
    for ax in axes[len(cols):]:
        ax.axis("off")
    fig.suptitle("数値特徴量の分布（上下0.5%は端に寄せて表示）" + ("・クラス別の密度" if task != "regression" else ""), fontsize=10)
    return savefig(fig, out, name)


def plot_num_vs_target(df, cols, y, task, out):
    cols = cols[:8]
    if not cols:
        return None
    nc = 4
    nr = int(np.ceil(len(cols) / nc))
    fig, axes = plt.subplots(nr, nc, figsize=(13, 3 * nr))
    axes = np.atleast_1d(axes).ravel()
    for ax, c in zip(axes, cols):
        s = df[c].astype(float)
        d = pd.DataFrame({"x": s, "y": y.values}).dropna()
        if len(d) == 0:
            continue
        if d["x"].nunique() <= 10:
            g = d.groupby("x").agg(y=("y", "mean"), n=("y", "size")).reset_index()
            ax.bar(g["x"].astype(str), g["y"], color="#4C72B0")
            for i, (yv, nv) in enumerate(zip(g["y"], g["n"])):
                ax.text(i, yv, f"n={nv:,}", ha="center", va="bottom", fontsize=7)
            ax.set_title(short(c, 28) + "（値ごとの平均）", fontsize=9)
            ax.tick_params(labelsize=7)
            continue
        try:
            d["bin"] = pd.qcut(d["x"], q=min(10, d["x"].nunique()), duplicates="drop")
        except ValueError:
            continue
        g = d.groupby("bin", observed=True).agg(x=("x", "median"), y=("y", "mean"), n=("y", "size"))
        if task == "regression":
            sm = d.sample(min(3000, len(d)), random_state=0)
            ax.scatter(sm["x"], sm["y"], s=4, alpha=.25, color="#4C72B0")
        ax.plot(g["x"], g["y"], marker="o", color="#C44E52", lw=2)
        ax.set_title(short(c, 28), fontsize=9)
        ax.set_ylabel({"binary": "陽性率", "multiclass": "クラス番号の平均", "regression": "目的変数"}[task], fontsize=8)
        ax.tick_params(labelsize=7)
    for ax in axes[len(cols):]:
        ax.axis("off")
    fig.suptitle("上位の数値特徴量と目的変数（10分位ごとの平均＝赤線。値の種類が少ない列は値ごとの平均）", fontsize=10)
    return savefig(fig, out, "num_vs_target.png")


def plot_cat_vs_target(df, cols, y, task, out):
    cols = cols[:6]
    if not cols or task == "multiclass":
        return None
    nc = 2
    nr = int(np.ceil(len(cols) / nc))
    fig, axes = plt.subplots(nr, nc, figsize=(12, 3.4 * nr))
    axes = np.atleast_1d(axes).ravel()
    base = y.mean()
    for ax, c in zip(axes, cols):
        g = pd.DataFrame({"c": df[c].fillna("(欠損)"), "y": y.values}).groupby("c")["y"].agg(["mean", "size"])
        g = g.sort_values("size", ascending=False).head(15).sort_values("mean")
        ax.barh([f"{short(i, 16)} (n={n:,})" for i, n in zip(g.index, g["size"])], g["mean"], color="#4C72B0")
        ax.axvline(base, color="#C44E52", ls="--", lw=1)
        ax.set_title(short(c, 30), fontsize=9)
        ax.tick_params(labelsize=7)
        ax.set_xlabel("陽性率" if task == "binary" else "目的変数の平均", fontsize=8)
    for ax in axes[len(cols):]:
        ax.axis("off")
    fig.suptitle("上位のカテゴリ特徴量と目的変数（件数上位15カテゴリ。破線は全体平均）", fontsize=10)
    return savefig(fig, out, "cat_vs_target.png")


def plot_corr(cm, out):
    if cm is None:
        return None
    cols = list(cm.columns)[:30]
    cm = cm.loc[cols, cols]
    fig, ax = plt.subplots(figsize=(min(12, 2 + 0.38 * len(cols)), min(10, 1.6 + 0.34 * len(cols))))
    im = ax.imshow(cm.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols)), [short(c, 14) for c in cols], rotation=90, fontsize=7)
    ax.set_yticks(range(len(cols)), [short(c, 14) for c in cols], fontsize=7)
    ax.grid(False)
    if len(cols) <= 15:
        for i in range(len(cols)):
            for j in range(len(cols)):
                ax.text(j, i, f"{cm.values[i, j]:.2f}", ha="center", va="center", fontsize=6)
    fig.colorbar(im, ax=ax, shrink=.7)
    ax.set_title("数値特徴量間の相関（Spearman）")
    return savefig(fig, out, "corr.png")


def plot_time(df, tcol, y, task, out):
    d = pd.DataFrame({"t": df[tcol], "y": y.values}).dropna()
    if len(d) < 20:
        return None
    span = (d["t"].max() - d["t"].min()).days
    freq = "D" if span <= 120 else ("W" if span <= 730 else "MS")
    g = d.set_index("t").resample(freq)["y"].agg(["mean", "size"])
    g = g[g["size"] > 0]
    fig, ax = plt.subplots(figsize=(11, 3.4))
    ax.plot(g.index, g["mean"], color="#4C72B0", marker=".")
    ax.set_ylabel("陽性率" if task == "binary" else "目的変数の平均")
    ax2 = ax.twinx()
    ax2.bar(g.index, g["size"], width={"D": 0.8, "W": 5, "MS": 20}[freq], alpha=.2, color="gray")
    ax2.set_ylabel("件数")
    ax2.grid(False)
    ax.set_title(f"「{tcol}」に沿った目的変数の推移（{ {'D': '日', 'W': '週', 'MS': '月'}[freq]}ごと）")
    return savefig(fig, out, "time_" + __import__("hashlib").md5(tcol.encode()).hexdigest()[:8] + ".png")


# ---------------------------------------------------------------- 特徴量エンジニアリング案
def fe_suggestions(prof, u, kinds, feats, mvt, pairs, task, y_raw, tcols, imb):
    rank = {r["特徴量"]: i for i, r in u.iterrows()} if len(u) else {}
    top = set(list(u["特徴量"])[:max(5, len(u) // 4)]) if len(u) else set()
    P = prof.set_index("列")
    rows = []

    def add(col, obs, prop, why_top=None):
        pr = "高" if (why_top if why_top is not None else col in top) else "中"
        rows.append({"優先度": pr, "対象": col, "観察": obs, "提案": prop})

    if task == "regression":
        yv = y_raw.astype(float)
        sk = yv.skew()
        if sk > 1 and yv.min() >= 0:
            add("（目的変数）", f"右に裾が長い（歪度 {sk:.2f}）", "log1p 変換した目的変数で学習し、予測時に expm1 で戻す。評価が RMSLE なら必須", True)
    else:
        if imb is not None and imb >= 5:
            add("（目的変数）", f"クラスの偏りが大きい（多数/少数 = {imb:.1f}倍）",
                "class_weight / scale_pos_weight を試す。評価は PR-AUC も見る。閾値は検証データで最適化", True)
    for c in feats:
        k = kinds[c]
        r = P.loc[c]
        if k == "numeric" and r.get("ユニーク数", 99) <= 2:
            continue
        if k == "numeric":
            sk = r.get("歪度", np.nan)
            if pd.notna(sk) and abs(sk) > 2:
                tip = "log1p" if r.get("最小", -1) >= 0 else "符号付き log / Yeo-Johnson"
                add(c, f"分布が大きく偏っている（歪度 {sk:.1f}）", f"{tip} 変換（線形モデル・NN向け。木モデルでは不要）")
            if r.get("外れ値率(IQR1.5)", 0) > 0.05:
                add(c, f"外れ値が多い（IQR基準で {pct(r['外れ値率(IQR1.5)'])}）", "上下1%でクリップ、または順位（rank）変換。入力ミスによる異常値か確認")
            if r.get("ユニーク数", 99) <= 10:
                add(c, f"値の種類が少ない（{int(r['ユニーク数'])}種）", "カテゴリとしても扱って比較（one-hot / target encoding）")
            if r.get("ゼロ率", 0) > 0.3:
                add(c, f"ゼロが多い（{pct(r['ゼロ率'])}）", "「0かどうか」のフラグを追加")
        elif k == "category":
            nun = r["ユニーク数"]
            if nun > 50:
                add(c, f"カテゴリ数が多い（{nun:,}種）", "count encoding / target encoding（CV内で計算してリークを防ぐ）")
            elif nun > 2:
                add(c, f"カテゴリ数 {nun}種", "one-hot（線形）またはそのままカテゴリ型（LightGBM）")
            if r.get("1%未満のカテゴリ数", 0) > 3:
                add(c, f"出現1%未満のカテゴリが {int(r['1%未満のカテゴリ数'])}種", "まれなカテゴリを「その他」にまとめる")
        elif k == "datetime":
            add(c, "日時の列", "年・月・曜日・時刻・祝日フラグ、基準日からの経過日数に分解。周期性は sin/cos。未来の情報を使わないよう時系列で検証", True)
        elif k == "text":
            add(c, f"自由記述（平均 {fmt(r.get('平均文字数'), 0)} 文字）", "文字数・単語数、TF-IDF、キーワードのフラグ、文埋め込み", True)
    if len(tcols) >= 2:
        add(" × ".join(tcols[:3]), "日時の列が複数", "日時どうしの差（例: 申込日→契約日の日数）を作る", True)
    if mvt is not None and len(mvt):
        for _, r in mvt[mvt["欠損に意味がありそう"] == "○"].head(8).iterrows():
            add(r["特徴量"], f"欠損の有無で目的変数が変わる（p={fmt(r['p値'])}）", "欠損フラグ列を追加（欠損そのものが情報）", True)
    if pairs is not None and len(pairs):
        for _, r in pairs.head(6).iterrows():
            add(f"{r['列A']} / {r['列B']}", f"強い相関（ρ={r['Spearman ρ']:.2f}）", "片方を削る、または比・差を特徴量にする")
    numtop = [c for c in (list(u["特徴量"]) if len(u) else []) if kinds[c] == "numeric"][:4]
    if len(numtop) >= 2:
        add(", ".join(numtop), "目的変数との関係が強い数値特徴量", "上位どうしの比・差・積（例: 金額÷回数＝単価）。ドメイン的に意味のある組み合わせを優先", True)
    cattop = [c for c in (list(u["特徴量"]) if len(u) else []) if kinds[c] == "category"][:2]
    if cattop and numtop:
        add(f"{cattop[0]} × {numtop[0]}", "上位のカテゴリと数値", f"`{cattop[0]}` ごとの `{numtop[0]}` の平均・標準偏差、その平均との差（グループ集約特徴量）", True)
    d = pd.DataFrame(rows)
    if len(d):
        d["_o"] = d["優先度"].map({"高": 0, "中": 1})
        d["_r"] = d["対象"].map(lambda c: rank.get(c, 999))
        d = d.sort_values(["_o", "_r"]).drop(columns=["_o", "_r"]).reset_index(drop=True)
    return d


# ---------------------------------------------------------------- モデリング
def model_frame(df, kinds, feats, cat_levels=None):
    X = pd.DataFrame(index=df.index)
    levels = {} if cat_levels is None else cat_levels
    for c in feats:
        k = kinds[c]
        if k in ("numeric", "bool"):
            X[c] = df[c].astype(float)
        elif k == "datetime":
            d = df[c]
            X[f"{c}__year"] = d.dt.year.astype(float)
            X[f"{c}__month"] = d.dt.month.astype(float)
            X[f"{c}__dow"] = d.dt.dayofweek.astype(float)
            X[f"{c}__days"] = (d - pd.Timestamp("1970-01-01")).dt.days.astype(float)
            if (d.dropna().dt.hour != 0).mean() > 0.05:
                X[f"{c}__hour"] = d.dt.hour.astype(float)
        elif k == "category":
            if cat_levels is None:
                vc = df[c].value_counts()
                levels[c] = list(vc.index[:200])
            s = df[c].where(df[c].isin(levels[c]) | df[c].isna(), "__other__")
            X[c] = pd.Categorical(s, categories=levels[c] + ["__other__"])
        elif k == "text":
            X[f"{c}__len"] = df[c].str.len().astype(float)
    num = X.select_dtypes(exclude="category").columns
    X[num] = X[num].replace([np.inf, -np.inf], np.nan)
    return X, levels


def make_splits(n, y, task, time_order=None, groups=None, k=5):
    from sklearn.model_selection import GroupKFold, KFold, StratifiedKFold, TimeSeriesSplit
    idx = np.arange(n)
    if time_order is not None:
        order = np.argsort(time_order, kind="stable")
        return [(order[tr], order[va]) for tr, va in TimeSeriesSplit(n_splits=k).split(order)], "時系列分割（TimeSeriesSplit, 過去で学習→未来で検証）"
    if groups is not None:
        if task != "regression":
            from sklearn.model_selection import StratifiedGroupKFold
            return list(StratifiedGroupKFold(k, shuffle=True, random_state=SEED).split(idx, y, groups)), "グループ層化K分割（同じグループは学習と検証に分かれない）"
        return list(GroupKFold(k).split(idx, y, groups)), "グループK分割（同じグループは学習と検証に分かれない）"
    if task != "regression":
        mc = np.bincount(y).min()
        if mc >= 2:
            kk = min(k, mc)
            return list(StratifiedKFold(kk, shuffle=True, random_state=SEED).split(idx, y)), f"層化{kk}分割交差検証"
    return list(KFold(k, shuffle=True, random_state=SEED).split(idx)), f"{k}分割交差検証"


def score(task, y, p, n_cls):
    from sklearn.metrics import (accuracy_score, average_precision_score, f1_score, log_loss, mean_absolute_error,
                                 mean_squared_error, r2_score, roc_auc_score)
    m = {}
    if task == "binary":
        try:
            m["auc"] = roc_auc_score(y, p)
            m["pr_auc"] = average_precision_score(y, p)
        except ValueError:
            m["auc"] = m["pr_auc"] = np.nan
        m["logloss"] = log_loss(y, np.clip(p, 1e-7, 1 - 1e-7), labels=[0, 1])
        m["accuracy"] = accuracy_score(y, p >= 0.5)
        m["f1"] = f1_score(y, p >= 0.5, zero_division=0)
    elif task == "multiclass":
        pred = p.argmax(1)
        m["accuracy"] = accuracy_score(y, pred)
        m["macro_f1"] = f1_score(y, pred, average="macro", zero_division=0)
        m["logloss"] = log_loss(y, np.clip(p, 1e-7, 1), labels=list(range(n_cls)))
    else:
        m["rmse"] = float(np.sqrt(mean_squared_error(y, p)))
        m["mae"] = mean_absolute_error(y, p)
        m["r2"] = r2_score(y, p)
        if y.min() >= 0:
            m["rmsle"] = float(np.sqrt(mean_squared_error(np.log1p(y), np.log1p(np.clip(p, 0, None)))))
    return m


HIGHER_BETTER = {"auc": True, "pr_auc": True, "accuracy": True, "f1": True, "macro_f1": True, "r2": True,
                 "logloss": False, "rmse": False, "mae": False, "rmsle": False}


def fit_predict(name, X_tr, y_tr, X_va, task, n_cls, n_small):
    """name: dummy / linear / gbdt。(予測, 学習データ予測, best_iter, importance) を返す。"""
    from sklearn.compose import ColumnTransformer
    from sklearn.dummy import DummyClassifier, DummyRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    def pred(model, X):
        if task == "regression":
            return model.predict(X)
        pr = model.predict_proba(X)
        return pr[:, 1] if task == "binary" else pr

    if name == "dummy":
        m = DummyRegressor() if task == "regression" else DummyClassifier(strategy="prior")
        m.fit(X_tr.iloc[:, :1].fillna(0) if X_tr.shape[1] else np.zeros((len(X_tr), 1)), y_tr)
        z_va, z_tr = np.zeros((len(X_va), 1)), np.zeros((len(X_tr), 1))
        return pred(m, z_va), pred(m, z_tr), None, None
    if name == "linear":
        cats = list(X_tr.select_dtypes(include="category").columns)
        nums = [c for c in X_tr.columns if c not in cats]

        def prep(X):
            X = X.copy()
            for c in cats:
                X[c] = X[c].astype(object).where(X[c].notna(), "__NA__").astype(str)
            return X
        pre = ColumnTransformer([
            ("num", make_pipeline(SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True), StandardScaler()), nums),
            ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=0.01, max_categories=30, sparse_output=False), cats),
        ])
        est = Ridge(alpha=1.0) if task == "regression" else LogisticRegression(max_iter=3000, C=1.0)
        m = make_pipeline(pre, est)
        a, b = prep(X_tr), prep(X_va)
        m.fit(a, y_tr)
        return pred(m, b), pred(m, a), None, None
    # gbdt
    from sklearn.model_selection import train_test_split
    strat = y_tr if (task != "regression" and np.bincount(y_tr).min() >= 2) else None
    i_fit, i_es = train_test_split(np.arange(len(X_tr)), test_size=0.15, random_state=SEED, stratify=strat)
    if lgb is not None:
        params = dict(n_estimators=5000, learning_rate=0.03, num_leaves=31, min_child_samples=n_small,
                      subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                      random_state=SEED, verbose=-1, n_jobs=-1)
        m = lgb.LGBMRegressor(**params) if task == "regression" else lgb.LGBMClassifier(**params)
        m.fit(X_tr.iloc[i_fit], y_tr[i_fit], eval_set=[(X_tr.iloc[i_es], y_tr[i_es])],
              callbacks=[lgb.early_stopping(100, verbose=False)])
        imp = pd.Series(m.booster_.feature_importance("gain"), index=X_tr.columns)
        return pred(m, X_va), pred(m, X_tr), int(m.best_iteration_ or m.n_estimators), imp
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    Xa, Xb = X_tr.copy(), X_va.copy()
    for c in Xa.select_dtypes(include="category").columns:
        if len(Xa[c].cat.categories) > 250:
            Xa[c], Xb[c] = Xa[c].cat.codes.replace(-1, np.nan), Xb[c].cat.codes.replace(-1, np.nan)
    kw = dict(max_iter=2000, learning_rate=0.05, early_stopping=True, validation_fraction=0.15,
              n_iter_no_change=50, categorical_features="from_dtype", random_state=SEED)
    m = HistGradientBoostingRegressor(**kw) if task == "regression" else HistGradientBoostingClassifier(**kw)
    m.fit(Xa, y_tr)
    return pred(m, Xb), pred(m, Xa), int(m.n_iter_), None


def run_models(X, y, task, n_cls, splits, primary):
    names = [("dummy", "ベースライン（平均/事前確率のみ）"), ("linear", "線形モデル（" + ("Ridge" if task == "regression" else "ロジスティック回帰") + "）"),
             ("gbdt", "勾配ブースティング（" + ("LightGBM" if lgb is not None else "HistGradientBoosting") + "）")]
    n_small = int(max(5, min(20, len(X) // 100)))
    res = {}
    for key, label in names:
        oof = np.full((len(X), n_cls) if task == "multiclass" else len(X), np.nan)
        folds, trains, iters, imps = [], [], [], []
        t0 = time.time()
        for tr, va in splits:
            p_va, p_tr, it, imp = fit_predict(key, X.iloc[tr], y[tr], X.iloc[va], task, n_cls, n_small)
            oof[va] = p_va
            folds.append(score(task, y[va], p_va, n_cls))
            trains.append(score(task, y[tr], p_tr, n_cls))
            if it:
                iters.append(it)
            if imp is not None:
                imps.append(imp)
        mask = ~np.isnan(oof if task != "multiclass" else oof[:, 0])
        fm = pd.DataFrame(folds)
        res[key] = {"label": label, "cv_mean": fm.mean().to_dict(), "cv_std": fm.std().to_dict(),
                    "train_mean": pd.DataFrame(trains).mean().to_dict(),
                    "oof_score": score(task, y[mask], oof[mask], n_cls), "oof": oof, "mask": mask,
                    "best_iter": float(np.mean(iters)) if iters else None,
                    "importance": (pd.concat(imps, axis=1).mean(axis=1) if imps else None), "sec": time.time() - t0}
    return res


def plot_importance(imp, out):
    if imp is None:
        return None
    s = (imp / imp.sum() * 100).sort_values().tail(25)
    fig, ax = plt.subplots(figsize=(7, max(2.5, 0.28 * len(s) + 1)))
    ax.barh([short(i, 30) for i in s.index], s.values, color="#4C72B0")
    ax.set_xlabel("重要度（gain, %）")
    ax.set_title("勾配ブースティングの特徴量重要度（上位25・全foldの平均）")
    return savefig(fig, out, "importance.png")


def plot_model_eval(task, y, oof, mask, classes, out):
    figs = []
    if task == "binary":
        from sklearn.metrics import precision_recall_curve, roc_curve
        yt, p = y[mask], oof[mask]
        fig, axes = plt.subplots(1, 3, figsize=(14, 3.8))
        fpr, tpr, _ = roc_curve(yt, p)
        axes[0].plot(fpr, tpr)
        axes[0].plot([0, 1], [0, 1], "--", color="gray")
        axes[0].set_title("ROC曲線")
        axes[0].set_xlabel("偽陽性率")
        axes[0].set_ylabel("真陽性率")
        pr, rc, _ = precision_recall_curve(yt, p)
        axes[1].plot(rc, pr)
        axes[1].axhline(yt.mean(), ls="--", color="gray")
        axes[1].set_title("適合率-再現率曲線")
        axes[1].set_xlabel("再現率")
        axes[1].set_ylabel("適合率")
        d = pd.DataFrame({"p": p, "y": yt})
        d["bin"] = pd.qcut(d["p"], 10, duplicates="drop")
        g = d.groupby("bin", observed=True).agg(p=("p", "mean"), y=("y", "mean"))
        axes[2].plot(g["p"], g["y"], marker="o")
        axes[2].plot([0, 1], [0, 1], "--", color="gray")
        axes[2].set_title("較正（予測確率 vs 実際の陽性率）")
        axes[2].set_xlabel("予測確率")
        axes[2].set_ylabel("実際の陽性率")
        figs.append(savefig(fig, out, "model_eval.png"))
    elif task == "multiclass":
        from sklearn.metrics import confusion_matrix
        pred = oof[mask].argmax(1)
        cm = confusion_matrix(y[mask], pred, labels=range(len(classes)), normalize="true")
        k = len(classes)
        fig, ax = plt.subplots(figsize=(min(10, 2 + .6 * k), min(9, 1.6 + .55 * k)))
        ax.imshow(cm, cmap="Blues", vmin=0, vmax=1)
        ax.grid(False)
        ax.set_xticks(range(k), [short(c, 12) for c in classes], rotation=90, fontsize=8)
        ax.set_yticks(range(k), [short(c, 12) for c in classes], fontsize=8)
        if k <= 15:
            for i in range(k):
                for j in range(k):
                    ax.text(j, i, f"{cm[i, j]:.2f}", ha="center", va="center", fontsize=7)
        ax.set_xlabel("予測")
        ax.set_ylabel("正解")
        ax.set_title("混同行列（行ごとに正規化）")
        figs.append(savefig(fig, out, "model_eval.png"))
    else:
        yt, p = y[mask], oof[mask]
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        sm = np.random.RandomState(0).choice(len(yt), min(5000, len(yt)), replace=False)
        axes[0].scatter(yt[sm], p[sm], s=5, alpha=.3)
        lo, hi = min(yt.min(), p.min()), max(yt.max(), p.max())
        axes[0].plot([lo, hi], [lo, hi], "--", color="gray")
        axes[0].set_xlabel("実測値")
        axes[0].set_ylabel("予測値")
        axes[0].set_title("予測 vs 実測")
        axes[1].hist(yt - p, bins=50)
        axes[1].set_title("残差（実測−予測）の分布")
        figs.append(savefig(fig, out, "model_eval.png"))
    return figs


def adversarial_auc(Xtr, Xte):
    if lgb is None:
        return None
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold
    X = pd.concat([Xtr, Xte], axis=0, ignore_index=True)
    yy = np.r_[np.zeros(len(Xtr)), np.ones(len(Xte))].astype(int)
    if len(X) > 40000:
        s = np.random.RandomState(0).choice(len(X), 40000, replace=False)
        X, yy = X.iloc[s].reset_index(drop=True), yy[s]
    oof = np.zeros(len(X))
    imps = []
    for tr, va in StratifiedKFold(3, shuffle=True, random_state=SEED).split(X, yy):
        m = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, verbose=-1, random_state=SEED)
        m.fit(X.iloc[tr], yy[tr])
        oof[va] = m.predict_proba(X.iloc[va])[:, 1]
        imps.append(pd.Series(m.booster_.feature_importance("gain"), index=X.columns))
    imp = pd.concat(imps, axis=1).mean(axis=1)
    return roc_auc_score(yy, oof), list((imp / imp.sum()).sort_values(ascending=False).head(5).round(3).items())


# ---------------------------------------------------------------- メイン処理
def cmd_run(a):
    setup_font()
    out = Path(a.out)
    (out / "figs").mkdir(parents=True, exist_ok=True)
    log = []
    raw, enc, sep = read_csv_any(a.train, a.sep)
    R = {"title": a.title or Path(a.train).stem, "goal": a.goal or "", "train": str(a.train), "test": a.test or "",
         "date": dt.date.today().isoformat(), "encoding": enc, "sep": sep, "raw_shape": list(raw.shape)}
    log.append(("読み込み", f"文字コード {enc}、区切り文字 `{repr(sep)[1:-1]}`、{raw.shape[0]:,}行 × {raw.shape[1]}列（全列を文字列として読み、型は後で推定）"))
    drop_cols = [c.strip() for c in (a.drop or "").split(",") if c.strip()]
    df, kinds = clean(raw, log, target=a.target, drop_cols=drop_cols)

    target = a.target
    if target not in df.columns:
        cand = [c for c in df.columns if unicodedata.normalize("NFKC", target).strip() == c]
        if not cand:
            sys.exit(f"目的変数 `{target}` が見つかりません。列: {list(df.columns)}")
        target = cand[0]
    n_before = len(df)
    df = df[df[target].notna()].reset_index(drop=True)
    if len(df) < n_before:
        log.append(("目的変数が欠損の行を除外", f"{n_before - len(df):,}行"))

    # タスク判定
    yk = kinds[target]
    task = a.task
    if task == "auto":
        nun = df[target].nunique()
        if yk in ("numeric",) and nun > 15:
            task = "regression"
        else:
            task = "binary" if nun == 2 else "multiclass"
    if task == "regression" and yk != "numeric":
        df[target] = parse_numeric(df[target].astype(str))
        df = df[df[target].notna()].reset_index(drop=True)
    y_raw = df[target]
    classes, pos = None, None
    if task == "regression":
        y = y_raw.astype(float).values
        n_cls = 1
    else:
        lab = y_raw.astype(str) if yk not in ("numeric", "bool") else y_raw.map(lambda v: fmt(float(v)))
        classes = sorted(lab.unique(), key=lambda v: (len(v), v))
        if task == "binary":
            if len(classes) != 2:
                sys.exit(f"binary を指定しましたがクラスが {len(classes)} 種類です: {classes[:10]}")
            pref = [c for c in classes if c.lower() in ("1", "true", "yes", "y", "はい", "あり", "有", "positive", "pos")]
            pos = pref[0] if pref else lab.value_counts().idxmin()
            classes = [c for c in classes if c != pos] + [pos]
        y = lab.map({c: i for i, c in enumerate(classes)}).values.astype(int)
        n_cls = len(classes)
    y_s = pd.Series(y, index=df.index)
    pd.DataFrame({"y": y}).to_csv(out / "y.csv", index=False)

    user_ids = [c.strip() for c in (a.id or "").split(",") if c.strip()]
    ids = detect_ids(df, kinds, target, user_ids)
    roles = {target: "目的変数"}
    for c in ids:
        roles[c] = "ID（学習に使わない）"
    if ids:
        log.append(("ID列と判断して特徴量から除外", ", ".join(ids) + "（--id で明示指定も可）"))
    tcol = a.time
    if tcol and kinds.get(tcol) != "datetime":
        sys.exit(f"--time `{tcol}` が日時の列として読めません（種類: {kinds.get(tcol)}）")
    if a.group:
        if a.group not in df.columns:
            sys.exit(f"--group `{a.group}` が見つかりません")
        roles[a.group] = "グループ（CV分割に使用・学習に使わない）"
    feats = [c for c in df.columns if c != target and c not in ids and c != a.group]
    if ids:
        dups_wo_id = int(df.drop(columns=ids).duplicated().sum())
        if dups_wo_id:
            log.append(("（注意）ID以外の全列が同じ行", f"{dups_wo_id:,}行。同じ対象の重複登録の可能性（削除はしていません）"))
    R.update({"target": target, "task": task, "classes": classes, "positive": pos, "n": len(df),
              "kinds": kinds, "ids": ids, "feats": feats, "time_col": tcol, "group": a.group})

    susp = suspicious_values(df, kinds, feats)
    for c, obs, _ in susp:
        log.append((f"（要確認）`{c}` の値", obs + "。置換はしていません"))
    prof = column_profile(df, kinds, roles)
    prof.to_csv(out / "column_profile.csv", index=False)
    df.to_csv(out / "cleaned_train.csv", index=False)

    figs = {}
    figs["target"] = plot_target(y_raw if task != "regression" else pd.Series(y), task, out)
    figs["missing"] = plot_missing(df.drop(columns=[target]), out)

    # 目的変数の要約
    tinfo = {}
    if task == "regression":
        ys = pd.Series(y)
        tinfo = {"平均": ys.mean(), "標準偏差": ys.std(), "最小": ys.min(), "中央値": ys.median(), "最大": ys.max(),
                 "歪度": ys.skew(), "負の値": int((ys < 0).sum()), "ゼロ": int((ys == 0).sum())}
        imb = None
    else:
        vc = pd.Series(y).value_counts().sort_index()
        tinfo = {"クラス": [{"クラス": classes[i], "件数": int(v), "割合": v / len(y)} for i, v in vc.items()]}
        imb = float(vc.max() / vc.min())
        tinfo["偏り(多数/少数)"] = imb
    R["target_info"] = tinfo

    u = univariate(df, kinds, feats, y_s, task)
    u.to_csv(out / "univariate.csv", index=False)
    flags = leak_flags(u, task)
    mvt = missing_vs_target(df, feats, y_s, task)
    pairs, cm = corr_pairs(df, kinds, feats)
    numf = [c for c in u["特徴量"] if kinds[c] in ("numeric",)] if len(u) else []
    catf = [c for c in u["特徴量"] if kinds[c] in ("category", "bool")] if len(u) else []
    figs["num_dist"] = plot_num_dists(df, numf, y if task != "regression" else None, task, out)
    figs["num_vs_target"] = plot_num_vs_target(df, numf, y_s, task, out)
    figs["cat_vs_target"] = plot_cat_vs_target(df, catf, y_s, task, out)
    figs["corr"] = plot_corr(cm, out)
    tcols = [c for c in feats if kinds[c] == "datetime"]
    figs["time"] = [p for p in (plot_time(df, c, y_s, task if task != "multiclass" else "regression", out) for c in ([tcol] if tcol else tcols[:3])) if p]
    fe = fe_suggestions(prof, u, kinds, feats, mvt, pairs, task, pd.Series(y) if task == "regression" else y_raw, tcols, imb)
    if susp:
        fe = pd.concat([pd.DataFrame([{"優先度": "高", "対象": c, "観察": o, "提案": p_} for c, o, p_ in susp]), fe], ignore_index=True)

    # 期待値などカテゴリ詳細（上位カテゴリ特徴量）
    cat_detail = []
    for c in catf[:6]:
        if kinds[c] != "category":
            continue
        g = pd.DataFrame({"c": df[c].fillna("(欠損)"), "y": y}).groupby("c")["y"].agg(["size", "mean"]).sort_values("size", ascending=False).head(10)
        g = g.reset_index().rename(columns={"c": "カテゴリ", "size": "件数", "mean": ("陽性率" if task == "binary" else "目的変数の平均")})
        cat_detail.append((c, g))

    # テストデータ
    test_df = None
    drift_df = None
    if a.test:
        tlog = []
        traw, _, _ = read_csv_any(a.test, a.sep)
        schema = {c: k for c, k in kinds.items() if c != target}
        test_df, _ = clean(traw, tlog, schema=schema, target=target)
        drift_df = drift(df, test_df, kinds, feats)
        test_df.to_csv(out / "cleaned_test.csv", index=False)
        R["test_shape"] = [len(test_df), traw.shape[1]]

    # モデリング
    X, levels = model_frame(df, kinds, feats)
    time_order = (df[tcol] - pd.Timestamp("1970-01-01")).dt.total_seconds().fillna(-1).values if tcol else None
    groups = df[a.group].astype(str).values if a.group else None
    splits, cv_desc = make_splits(len(X), y, task, time_order, groups)
    default_metric = {"binary": "auc", "multiclass": "macro_f1", "regression": "rmse"}[task]
    primary = a.metric or default_metric
    mres = run_models(X, y, task, n_cls, splits, primary)
    g = mres["gbdt"]
    figs["importance"] = plot_importance(g["importance"], out)
    figs["model_eval"] = plot_model_eval(task, y, g["oof"], g["mask"], classes, out)

    # OOF と誤差の大きい行
    oof_df = df[ids].copy() if ids else pd.DataFrame(index=df.index)
    oof_df["row"] = np.arange(len(df))
    oof_df[target] = y_raw.values
    if task == "multiclass":
        for i, c in enumerate(classes):
            oof_df[f"pred_{c}"] = g["oof"][:, i]
        loss = -np.log(np.clip(g["oof"][np.arange(len(y)), y], 1e-7, 1))
    elif task == "binary":
        oof_df[f"pred_{pos}"] = g["oof"]
        loss = -(y * np.log(np.clip(g["oof"], 1e-7, 1)) + (1 - y) * np.log(np.clip(1 - g["oof"], 1e-7, 1)))
    else:
        oof_df["pred"] = g["oof"]
        loss = np.abs(y - g["oof"])
    oof_df["誤差"] = loss
    oof_df.to_csv(out / "oof.csv", index=False)
    topimp = list(g["importance"].sort_values(ascending=False).index[:5]) if g["importance"] is not None else list(u["特徴量"][:5])
    topraw = [c for c in feats if any(t == c or t.startswith(c + "__") for t in topimp)][:5]
    worst = oof_df.assign(**{c: df[c].values for c in topraw}).dropna(subset=["誤差"]).sort_values("誤差", ascending=False).head(15)
    worst.to_csv(out / "worst_errors.csv", index=False)

    adv = None
    if test_df is not None:
        Xte, _ = model_frame(test_df, kinds, feats, cat_levels=levels)
        tcols_x = [c for c in X.columns if "__" in c and c.split("__")[0] in tcols] + [c for c in ("year",) if c in X.columns]
        keep = [c for c in X.columns if c not in tcols_x]
        adv = adversarial_auc(X[keep], Xte[keep]) if keep else None
        if lgb is not None:
            n_est = int(max(50, (g["best_iter"] or 300) * 1.1))
            params = dict(n_estimators=n_est, learning_rate=0.03, num_leaves=31, min_child_samples=int(max(5, min(20, len(X) // 100))),
                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=SEED, verbose=-1)
            m = lgb.LGBMRegressor(**params) if task == "regression" else lgb.LGBMClassifier(**params)
            m.fit(X, y)
            pr = m.predict(Xte[X.columns]) if task == "regression" else m.predict_proba(Xte[X.columns])
        else:
            pr, _, _, _ = fit_predict("gbdt", X, y, Xte[X.columns], task, n_cls, 20)
        sub = test_df[ids].copy() if ids and all(c in test_df for c in ids) else pd.DataFrame(index=test_df.index)
        if task == "regression":
            sub[target] = pr
        elif task == "binary":
            sub[f"{target}_prob_{pos}"] = pr if pr.ndim == 1 else pr[:, 1]
            sub[f"{target}_pred"] = np.where(sub[f"{target}_prob_{pos}"] >= 0.5, pos, classes[0])
        else:
            for i, c in enumerate(classes):
                sub[f"prob_{c}"] = pr[:, i]
            sub[f"{target}_pred"] = [classes[i] for i in pr.argmax(1)]
        sub.to_csv(out / "predictions.csv", index=False)

    # 保存（レポート描画に必要なものを JSON に）
    def tbl(d):
        return None if d is None else json.loads(d.to_json(orient="split", force_ascii=False, default_handler=str))
    R.update({
        "log": log, "profile": tbl(prof), "univariate": tbl(u), "leak": flags, "missing_vs_target": tbl(mvt),
        "corr_pairs": tbl(pairs), "fe": tbl(fe), "figs": figs, "cv_desc": cv_desc, "primary": primary,
        "cat_detail": [(c, tbl(gd)) for c, gd in cat_detail], "drift": tbl(drift_df), "adv": adv,
        "n_model_features": X.shape[1], "model_features": list(X.columns),
        "models": {k: {kk: (vv.to_dict() if isinstance(vv, pd.Series) else vv) for kk, vv in v.items() if kk not in ("oof", "mask")}
                   for k, v in mres.items()},
        "worst": tbl(worst.drop(columns=["row"]).head(10)), "gbdt_engine": "LightGBM" if lgb is not None else "HistGradientBoosting",
    })
    (out / "results.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    render(out)
    print(f"done: {out / 'report.md'}")
    print(f"task={task} target={target} n={len(df)} features={len(feats)} → model_features={X.shape[1]}")
    for k, v in mres.items():
        print(f"  {v['label']}: " + ", ".join(f"{m}={fmt(x)}" for m, x in v["cv_mean"].items()))


# ---------------------------------------------------------------- レポート
def T(d):
    if d is None:
        return None
    return pd.DataFrame(d["data"], columns=d["columns"])


def render(out):
    out = Path(out)
    R = json.loads((out / "results.json").read_text())
    task = R["task"]
    tname = {"binary": "2値分類", "multiclass": "多クラス分類", "regression": "回帰"}[task]
    L = []
    w = L.append
    w(f"# 初期分析レポート: {R['title']}\n")
    w(f"- 実行日: {R['date']}　／　データ: `{Path(R['train']).name}`（{R['raw_shape'][0]:,}行 × {R['raw_shape'][1]}列）" + (f"　／　テスト: `{Path(R['test']).name}`" if R["test"] else ""))
    if R["goal"]:
        w(f"- 課題: {R['goal']}")
    w(f"- 目的変数: `{R['target']}`（{tname}" + (f"、陽性クラス = `{R['positive']}`" if R.get("positive") else "") + f"）　／　主指標: **{R['primary']}**")
    w(f"- 分析対象: {R['n']:,}行、特徴量 {len(R['feats'])}列（ID {len(R['ids'])}列は除外）\n")

    ins = out / "insights.md"
    w("## 0. まとめと考察\n")
    if ins.exists():
        w(ins.read_text().strip() + "\n")
    else:
        w("> （ここに考察が入ります。`insights.md` を書いて `render` を実行してください）\n")
        # 自動の要点
        w(auto_summary(R) + "\n")

    w("## 1. データクレンジングの記録\n")
    w(md_table(pd.DataFrame(R["log"], columns=["処理", "内容"]), 100))

    w("## 2. 目的変数\n")
    w(f"![目的変数]({R['figs']['target']})\n")
    ti = R["target_info"]
    if task == "regression":
        w(md_table(pd.DataFrame([ti])))
        if ti["歪度"] > 1:
            w(f"- 右に裾が長い分布です（歪度 {ti['歪度']:.2f}）。log 変換を検討してください。\n")
    else:
        d = pd.DataFrame(ti["クラス"])
        d["割合"] = d["割合"].map(pct)
        w(md_table(d))
        w(f"- 多数クラス / 少数クラス = {ti['偏り(多数/少数)']:.1f} 倍\n")

    w("## 3. 列ごとのプロファイル\n")
    prof = T(R["profile"])
    base_cols = ["列", "種類", "役割", "欠損率", "ユニーク数"]
    num = prof[prof["種類"].isin(["numeric", "bool"])]
    oth = prof[~prof["種類"].isin(["numeric", "bool"])]
    if len(num):
        w("### 数値の列\n")
        d = num[[c for c in base_cols + ["平均", "標準偏差", "最小", "中央値", "最大", "歪度", "ゼロ率", "外れ値率(IQR1.5)", "負の値"] if c in num]].copy()
        for c in ["欠損率", "ゼロ率", "外れ値率(IQR1.5)"]:
            if c in d:
                d[c] = d[c].map(pct)
        w(md_table(d, 200))
    if len(oth):
        w("### カテゴリ・日時・テキストの列\n")
        d = oth[[c for c in base_cols + ["最頻値", "最頻値の割合", "1%未満のカテゴリ数", "平均文字数", "最小", "最大"] if c in oth]].copy()
        for c in ["欠損率", "最頻値の割合"]:
            if c in d:
                d[c] = d[c].map(pct)
        w(md_table(d, 200))
    w("全項目は `column_profile.csv` を参照。\n")

    w("## 4. 欠損\n")
    if R["figs"].get("missing"):
        w(f"![欠損率]({R['figs']['missing']})\n")
        mvt = T(R["missing_vs_target"])
        if mvt is not None and len(mvt):
            w("欠損の有無と目的変数の関係（p値が小さい＝欠損そのものに情報がある可能性）:\n")
            d = mvt.copy()
            for c in d.columns:
                if c in ("欠損率", "欠損時の陽性率", "非欠損時の陽性率"):
                    d[c] = d[c].map(pct)
            w(md_table(d, 30))
    else:
        w("欠損はありません。\n")

    w("## 5. 目的変数との関係（単変量）\n")
    u = T(R["univariate"])
    if u is not None and len(u):
        w("相互情報量（非線形の関係も拾う指標）の大きい順。`指標` は列の種類に応じた関係の強さ。\n")
        d = u.copy()
        d["欠損率"] = d["欠損率"].map(pct)
        w(md_table(d, 40))
    for k, cap in [("num_vs_target", "数値特徴量と目的変数"), ("cat_vs_target", "カテゴリ特徴量と目的変数"), ("num_dist", "数値特徴量の分布")]:
        if R["figs"].get(k):
            w(f"![{cap}]({R['figs'][k]})\n")
    for c, gd in R.get("cat_detail", []):
        d = T(gd)
        if d is not None and len(d):
            w(f"**`{c}` のカテゴリ別**（件数上位10）\n")
            if "陽性率" in d:
                d["陽性率"] = d["陽性率"].map(pct)
            w(md_table(d))

    w("## 6. 特徴量間の相関\n")
    if R["figs"].get("corr"):
        w(f"![相関]({R['figs']['corr']})\n")
    pairs = T(R["corr_pairs"])
    w("|ρ| ≥ 0.9 の組（ほぼ同じ情報を持つ列）:\n")
    w(md_table(pairs, 30))

    sec = 7
    if R["figs"].get("time"):
        w(f"## {sec}. 時間に沿った推移\n")
        for p in R["figs"]["time"]:
            w(f"![推移]({p})\n")
        sec += 1
    if R.get("drift"):
        w(f"## {sec}. train と test の違い\n")
        if R.get("adv"):
            auc, top = R["adv"]
            w(f"- train と test を見分けるモデルの AUC = **{auc:.3f}**（日時・年の列を除いて計算。0.5 に近いほど同じ分布。0.7 を超えると要注意）")
            w("- 見分けに効いている列: " + ", ".join(f"`{c}`({v:.0%})" for c, v in top) + "\n")
        d = T(R["drift"])
        for c in ("欠損率(train)", "欠損率(test)"):
            d[c] = d[c].map(pct)
        w(md_table(d, 30))
        sec += 1

    w(f"## {sec}. 特徴量エンジニアリングの候補（自動抽出）\n")
    w("データの統計から機械的に挙げた候補です。ドメイン知識での取捨選択が前提。優先度「高」は目的変数との関係が強い列や効果が大きい処理。\n")
    w(md_table(T(R["fe"]), 80))
    sec += 1

    w(f"## {sec}. ベースラインモデル\n")
    w(f"- 検証方法: {R['cv_desc']}")
    w(f"- モデルに入れた特徴量: {R['n_model_features']}列（日時は年・月・曜日・経過日数に分解、テキストは文字数のみ、カテゴリは LightGBM ではカテゴリ型／線形では one-hot）")
    w("- 前処理は最小限（欠損補完は中央値、スケーリングは線形のみ）。ここからの改善幅を測るための基準値です。\n")
    rows = []
    for k, v in R["models"].items():
        r = {"モデル": v["label"]}
        for m, x in v["cv_mean"].items():
            r[m] = f"{fmt(x)} ± {fmt(v['cv_std'].get(m))}"
        r[f"学習データでの{R['primary']}"] = fmt(v["train_mean"].get(R["primary"]))
        r["秒"] = f"{v['sec']:.1f}"
        rows.append(r)
    w(md_table(pd.DataFrame(rows)))
    g = R["models"]["gbdt"]
    p = R["primary"]
    if p in g["cv_mean"] and p in g["train_mean"]:
        gap = abs(g["train_mean"][p] - g["cv_mean"][p])
        w(f"- 勾配ブースティングの {p}: 学習 {fmt(g['train_mean'][p])} / 検証 {fmt(g['cv_mean'][p])}（検証の方が {fmt(gap)} 悪い）。差が大きいほど過学習気味。")
    if g.get("best_iter"):
        w(f"- 早期終了で選ばれた木の本数（平均）: {g['best_iter']:.0f}\n")
    if R["figs"].get("importance"):
        w(f"![重要度]({R['figs']['importance']})\n")
    for f in R["figs"].get("model_eval", []):
        w(f"![評価]({f})\n")
    wd = T(R["worst"])
    if wd is not None and len(wd):
        w("予測を大きく外した行（上位10。全行の予測は `oof.csv`）:\n")
        w(md_table(wd))
    if R["test"]:
        w("- テストデータの予測: `predictions.csv`（全学習データで再学習した勾配ブースティング）\n")
    sec += 1

    ms = out / "model_scores.csv"
    if ms.exists():
        w(f"## {sec}. 初期モデル（特徴量エンジニアリング込み）\n")
        w("`baseline_model.py` の `add_features()` で特徴量を足し（目的変数の変換を設定した場合はそれも含む）、上と同じ分割の交差検証で LightGBM を比べた結果。\n")
        sc = pd.read_csv(ms, index_col=0)
        sc["差"] = sc["追加後"] - sc["追加前"]
        w(md_table(sc.reset_index().rename(columns={sc.index.name or "index": "指標"})))
        bm = out / "baseline_model.py"
        if bm.exists():
            src = bm.read_text()
            m = re.search(r"def add_features\(.*?\n(.*?)\n    return df", src, re.S)
            if m:
                body = "\n".join(ln for ln in m.group(1).split("\n") if ln.strip() and not ln.strip().startswith(('"""', "- ", "目的変数", "日時の列", "新しく作った")) and "特徴量エンジニアリング。" not in ln)
                body = __import__("textwrap").dedent(body).replace("df = df.copy()\n", "")
                w("追加した処理:\n\n```python\n" + body + "\n```\n")
        mi = out / "model_importance.csv"
        if mi.exists():
            imp = pd.read_csv(mi)
            imp.columns = ["特徴量", "重要度"]
            imp["重要度"] = imp["重要度"].map(pct)
            w("特徴量追加後の重要度（上位15）:\n")
            w(md_table(imp.head(15)))
        sec += 1

    w(f"## {sec}. 注意点\n")
    notes = list(R["leak"])
    if task != "regression" and R["target_info"].get("偏り(多数/少数)", 1) >= 5:
        notes.append("クラスの偏りが大きいので accuracy は参考になりません。AUC / PR-AUC / F1 で判断してください。")
    if not R.get("time_col") and any(R["kinds"][c] == "datetime" for c in R["feats"]):
        notes.append("日時の列がありますがランダム分割で検証しています。本番で「未来を予測する」なら `--time <列>` で時系列分割にしてください（スコアは下がるのが普通）。")
    if R["n"] < 1000:
        notes.append(f"データが {R['n']:,} 行と少ないため、スコアのばらつき（±）が大きくなります。")
    notes.append("ID と判断した列は除外しています。誤判定なら `--id` で指定し直してください。")
    for n_ in notes:
        w(f"- {n_}")
    w("\n## 出力ファイル\n")
    w("`cleaned_train.csv` / `cleaned_test.csv`（クレンジング後）、`y.csv`（目的変数を数値化したもの）、`column_profile.csv`、`univariate.csv`、`oof.csv`（交差検証の予測）、`worst_errors.csv`、`results.json`" + ("、`predictions.csv`" if R["test"] else "") + "\n")
    md = "\n".join(L)
    (out / "report.md").write_text(md)
    (out / "report.html").write_text(md_to_html(md, out, R["title"]))


def best_model(R):
    p = R["primary"]
    sc = {k: v["cv_mean"].get(p, np.nan) for k, v in R["models"].items() if k != "dummy"}
    return (max if HIGHER_BETTER[p] else min)(sc, key=lambda k: sc[k] if not np.isnan(sc[k]) else (-np.inf if HIGHER_BETTER[p] else np.inf))


def auto_summary(R):
    s = []
    g = R["models"]["gbdt"]
    p = R["primary"]
    sc = {k: v["cv_mean"].get(p) for k, v in R["models"].items()}
    if all(v is not None for v in sc.values()):
        s.append(f"- {p}（交差検証）: " + "、".join(f"{R['models'][k]['label'].split('（')[0]} {fmt(v)}" for k, v in sc.items())
                 + f" → 最良は **{R['models'][best_model(R)]['label']}**")
    u = T(R["univariate"])
    if u is not None and len(u):
        s.append("- 目的変数と関係が強い列（相互情報量の上位）: " + ", ".join(f"`{c}`" for c in u["特徴量"][:5]))
    imp = g.get("importance")
    if imp:
        top = sorted(imp.items(), key=lambda x: -x[1])[:5]
        tot = sum(imp.values()) or 1
        s.append("- モデルの重要度の上位: " + ", ".join(f"`{k}`({v / tot:.0%})" for k, v in top))
    for f in R["leak"]:
        s.append(f"- ⚠ {f}")
    return "\n".join(s)


CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--soft:#f6f8fa;--accent:#0969da}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#3d444d;--soft:#151b23;--accent:#4493f8}}
:root[data-theme="dark"]{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#3d444d;--soft:#151b23;--accent:#4493f8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.7 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP","Yu Gothic",sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6em;margin:.2em 0 .6em}h2{font-size:1.3em;margin:2em 0 .6em;padding-bottom:.3em;border-bottom:1px solid var(--line)}h3{font-size:1.08em;margin:1.4em 0 .4em}
.tw{overflow-x:auto;margin:.6em 0 1.2em;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;font-size:13px;width:max-content;min-width:100%}th,td{padding:5px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
td{max-width:520px;white-space:normal}th{background:var(--soft);position:sticky;top:0}
img{max-width:100%;height:auto;background:#fff;border-radius:6px;border:1px solid var(--line);margin:.4em 0}
code{background:var(--soft);padding:.1em .35em;border-radius:4px;font-size:.92em}
blockquote{margin:.8em 0;padding:.2em 1em;border-left:4px solid var(--line);color:var(--muted)}
ul,ol{padding-left:1.4em}a{color:var(--accent)}
pre{overflow-x:auto;background:var(--soft);padding:10px 12px;border-radius:6px;font-size:12.5px}pre code{background:none;padding:0}
main>p,li{overflow-wrap:anywhere}
"""


def md_to_html(md, base, title):
    def inline(t):
        t = html.escape(t, quote=False)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![\w*])_([^_]+)_(?![\w*])", r"<em>\1</em>", t)
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
        return t

    lines = md.split("\n")
    o = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        st = ln.strip()
        if st.startswith("```"):
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                buf.append(lines[j])
                j += 1
            o.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
            i = j + 1
            continue
        if st.startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", st)
        if m:
            n = len(m.group(1))
            o.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
            i += 1
            continue
        m = re.match(r"^!\[(.*?)\]\((.*?)\)$", st)
        if m:
            p = base / m.group(2)
            if p.exists():
                b64 = base64.b64encode(p.read_bytes()).decode()
                o.append(f'<img alt="{html.escape(m.group(1))}" src="data:image/png;base64,{b64}">')
            i += 1
            continue
        if st.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
            body = [r for k, r in enumerate(cells) if not (k == 1 and all(re.match(r"^:?-+:?$", c) for c in r))]
            h = "<tr>" + "".join(f"<th>{inline(c)}</th>" for c in body[0]) + "</tr>"
            b = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body[1:])
            o.append(f'<div class="tw"><table><thead>{h}</thead><tbody>{b}</tbody></table></div>')
            continue
        if re.match(r"^\s*([-*]|\d+\.)\s+", ln):
            tag = "ol" if re.match(r"^\s*\d+\.", ln) else "ul"
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i]))
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip() and not re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                    items[-1] += " " + lines[i].strip()
                    i += 1
            o.append(f"<{tag}>" + "".join(f"<li>{inline(t)}</li>" for t in items) + f"</{tag}>")
            continue
        if st.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            o.append("<blockquote><p>" + inline(" ".join(buf)) + "</p></blockquote>")
            continue
        if not st:
            i += 1
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4}\s|\||!\[|```|>|\s*([-*]|\d+\.)\s)", lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        if not buf:
            buf.append(st)
            i += 1
        o.append("<p>" + "<br>".join(inline(t) for t in buf) + "</p>")
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(short(title, 30))}</title><style>{CSS}</style></head><body><main>{''.join(o)}</main></body></html>")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--train", required=True)
    r.add_argument("--target", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--test")
    r.add_argument("--task", default="auto", choices=["auto", "binary", "multiclass", "regression"])
    r.add_argument("--metric", choices=list(HIGHER_BETTER))
    r.add_argument("--id", help="ID列（カンマ区切り）")
    r.add_argument("--time", help="時系列分割に使う日時列")
    r.add_argument("--group", help="グループK分割に使う列（同じ顧客など）")
    r.add_argument("--drop", help="最初から除外する列（カンマ区切り）")
    r.add_argument("--sep", help="区切り文字（省略時は自動判定）")
    r.add_argument("--title")
    r.add_argument("--goal")
    q = sp.add_parser("render")
    q.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "run":
        cmd_run(a)
    else:
        setup_font()
        render(a.out)
        print(f"done: {Path(a.out) / 'report.md'}")


if __name__ == "__main__":
    main()
