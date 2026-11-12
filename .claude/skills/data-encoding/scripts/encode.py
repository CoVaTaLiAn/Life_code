#!/usr/bin/env python3
"""エンコーディング: クレンジング済みのデータを、計画（encoding_plan.json）に従ってすべて数値の表にする。

  python3 encode.py fit   --input cleaned.csv --plan encoding_plan.json --out <出力先> [--target 列] [--set 列=方法,...]
  python3 encode.py apply --input test_cleaned.csv --state <fit の出力先>/encoder_state.json --out <出力先>

fit は学習用データで変換の中身（カテゴリの一覧・平均・対応表など）を決めて保存し、apply は同じ変換を別のデータにかける。
どの列をどの方法にするかはここでは判断しない（プロファイリングが作った計画に従う。変えるなら計画を編集するか --set）。
出力: encoded.csv / encoder_state.json（fit のみ）/ feature_map.csv / report.md / report.html

方法: drop passthrough log1p standard minmax binary onehot label ordinal frequency target datetime text_stats
      target_label target_passthrough
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import tabprep_common as tc  # noqa: E402

ROLE = "計画に従って各列を数値に変換する。変換の中身は学習用データで決めて保存し、別のデータにも同じ変換をかけられるようにする"
SEED, NAN_KEY = 42, "__nan__"
NUMERIC_KINDS = ("numeric", "bool")
ALLOWED = {"numeric": {"passthrough", "log1p", "standard", "minmax", "binary", "onehot", "label", "frequency", "target"},
           "bool": {"passthrough", "binary"},
           "category": {"binary", "onehot", "label", "ordinal", "frequency", "target"},
           "id": {"frequency", "label"}, "text": {"text_stats"}, "datetime": {"datetime"}}


def key(v):
    """値を対応表のキー（文字列）にする。1.0 と 1 は同じキー。"""
    if pd.isna(v):
        return NAN_KEY
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return str(int(v))
    return str(v)


def keys(s):
    return s.map(key, na_action=None)


# ---------------------------------------------------------------- 数値
def _impute(s, st, name, out):
    if st.get("fill") is not None:
        if st.get("flag"):
            out[f"{name}__isna"] = s.isna().astype(int)
        s = s.fillna(st["fill"])
    return s


def fit_numeric(s, p, y, name, method):
    x = s.dropna()
    default = "median" if method in ("standard", "minmax") else "none"
    how = p.get("impute", default)
    fill = {"median": x.median(), "mean": x.mean(), "zero": 0.0}.get(how) if len(x) else None
    st = {"fill": None if fill is None else float(fill), "flag": bool(s.isna().any()) and fill is not None, "impute": how}
    if method == "log1p":
        st["signed"] = bool((x < 0).any())
    elif method == "standard":
        st.update(mean=float(x.mean()), std=float(x.std()) or 1.0)
    elif method == "minmax":
        st.update(min=float(x.min()), max=float(x.max()))
    note = f"欠損の補完: {how}" + (f"（{tc.fmt(st['fill'])}）＋欠損フラグ列" if st["flag"] else "")
    return st, note


def apply_numeric(s, st, name, method):
    out = {}
    s = _impute(s.astype(float), st, name, out)
    if method == "passthrough":
        out = {name: s, **out}
    elif method == "log1p":
        out = {f"{name}__log1p": np.sign(s) * np.log1p(s.abs()) if st["signed"] else np.log1p(s), **out}
    elif method == "standard":
        out = {f"{name}__std": (s - st["mean"]) / st["std"], **out}
    else:
        out = {f"{name}__minmax": (s - st["min"]) / ((st["max"] - st["min"]) or 1.0), **out}
    return pd.DataFrame(out), 0


# ---------------------------------------------------------------- カテゴリ
def fit_binary(s, p, y, name):
    vals = sorted(pd.unique(keys(s.dropna())))
    if len(vals) > 2:
        raise ValueError(f"binary は値が2種類の列だけ（{name} は {len(vals)} 種類）")
    pos = str(p["positive"]) if "positive" in p else vals[-1]
    st = {"map": {v: int(v == pos) for v in vals}}
    return st, "、".join(f"{k}→{v}" for k, v in st["map"].items())


def apply_binary(s, st, name):
    k = keys(s)
    unseen = int((~k.isin(list(st["map"]) + [NAN_KEY])).sum())
    return pd.DataFrame({name: k.map(st["map"]).astype(float)}), unseen


def fit_onehot(s, p, y, name):
    vc = keys(s.dropna()).value_counts()
    mx = int(p.get("max_categories", 30))
    cats = list(vc.index[:mx])
    st = {"categories": cats, "other": len(vc) > mx, "nan": bool(s.isna().any())}
    return st, f"{len(cats)} カテゴリ" + ("＋その他" if st["other"] else "") + ("＋欠損" if st["nan"] else "")


def apply_onehot(s, st, name):
    k = keys(s)
    out = {f"{name}={c}": (k == c).astype(int) for c in st["categories"]}
    unknown = ~k.isin(st["categories"] + [NAN_KEY])
    if st["other"]:
        out[f"{name}=__other"] = unknown.astype(int)
    if st["nan"]:
        out[f"{name}=__nan"] = (k == NAN_KEY).astype(int)
    return pd.DataFrame(out), 0 if st["other"] else int(unknown.sum())


def fit_label(s, p, y, name):
    st = {"map": {v: i for i, v in enumerate(sorted(pd.unique(keys(s.dropna()))))}}
    return st, f"{len(st['map'])} 種類を 0〜{len(st['map']) - 1} に（文字の順）。未知の値は -1"


def apply_label(s, st, name):
    k = keys(s)
    unknown = ~k.isin(list(st["map"]) + [NAN_KEY])
    return pd.DataFrame({f"{name}__label": k.map(st["map"]).astype(float).mask(unknown, -1)}), int(unknown.sum())


def fit_ordinal(s, p, y, name):
    if not p.get("order"):
        raise ValueError(f"ordinal には並び順が必要（計画の params.order。列: {name}）")
    st = {"map": {str(v): i for i, v in enumerate(p["order"])}}
    miss = sorted(set(pd.unique(keys(s.dropna()))) - set(st["map"]))
    return st, " < ".join(map(str, p["order"])) + (f"　※並び順にない値は欠損になる: {miss}" if miss else "")


def apply_ordinal(s, st, name):
    k = keys(s)
    return pd.DataFrame({f"{name}__ord": k.map(st["map"]).astype(float)}), int((~k.isin(list(st["map"]) + [NAN_KEY])).sum())


def fit_frequency(s, p, y, name):
    st = {"map": (keys(s).value_counts() / max(len(s), 1)).to_dict()}
    return st, f"{len(st['map'])} 種類を出現割合に。未知の値は 0"


def apply_frequency(s, st, name):
    k = keys(s)
    return pd.DataFrame({f"{name}__freq": k.map(st["map"]).fillna(0.0)}), int((~k.isin(list(st["map"]) + [NAN_KEY])).sum())


def fit_target(s, p, y, name):
    """目的変数の平均に置き換える。学習用データは fold 外の平均（自分の行の目的変数を使わない）。"""
    if y is None:
        raise ValueError(f"target には数値か2値の目的変数が必要（列: {name}）")
    m, k = float(p.get("smoothing", 10)), keys(s)
    ok = y.notna()
    prior = float(y[ok].mean())

    def table(idx):
        g = y[idx].groupby(k[idx]).agg(["sum", "count"])
        return ((g["sum"] + prior * m) / (g["count"] + m)).to_dict()
    folds = np.random.RandomState(SEED).permutation(len(s)) % int(p.get("folds", 5))
    oof = pd.Series(prior, index=s.index, dtype=float)
    for f in range(folds.max() + 1):
        te = folds == f
        oof[te] = k[te].map(table(ok & ~te)).fillna(prior).values
    st = {"map": table(ok), "prior": prior}
    return st, f"目的変数の平均（{folds.max() + 1} fold の fold 外、平滑化 {m:g}、全体平均 {prior:.4g}）", \
        pd.DataFrame({f"{name}__te": oof})


def apply_target(s, st, name):
    k = keys(s)
    return pd.DataFrame({f"{name}__te": k.map(st["map"]).fillna(st["prior"])}), int((~k.isin(list(st["map"]) + [NAN_KEY])).sum())


# ---------------------------------------------------------------- 日時・文章・目的変数
def fit_datetime(s, p, y, name):
    x = s.dropna()
    parts = p.get("parts") or (["year", "month", "day", "dayofweek", "is_weekend", "month_sin", "month_cos",
                                "dow_sin", "dow_cos", "elapsed_days"] +
                               (["hour", "hour_sin", "hour_cos"] if ((x.dt.hour != 0) | (x.dt.minute != 0)).any() else []))
    st = {"parts": parts, "origin": x.min().isoformat() if len(x) else "1970-01-01"}
    return st, f"{'、'.join(parts)}（経過日数の基準日 {st['origin'][:10]}）"


def apply_datetime(s, st, name):
    d, tau = s.dt, 2 * np.pi
    f = {"year": lambda: d.year, "month": lambda: d.month, "day": lambda: d.day, "dayofweek": lambda: d.dayofweek,
         "hour": lambda: d.hour, "is_weekend": lambda: (d.dayofweek >= 5).astype(float).mask(s.isna()),
         "month_sin": lambda: np.sin(tau * (d.month - 1) / 12), "month_cos": lambda: np.cos(tau * (d.month - 1) / 12),
         "dow_sin": lambda: np.sin(tau * d.dayofweek / 7), "dow_cos": lambda: np.cos(tau * d.dayofweek / 7),
         "hour_sin": lambda: np.sin(tau * d.hour / 24), "hour_cos": lambda: np.cos(tau * d.hour / 24),
         "elapsed_days": lambda: (s - pd.Timestamp(st["origin"])).dt.total_seconds() / 86400}
    return pd.DataFrame({f"{name}__{k}": f[k]().astype(float) for k in st["parts"]}), 0


def apply_text_stats(s, st, name):
    t = s.fillna("").astype(str)
    return pd.DataFrame({f"{name}__len": t.str.len(), f"{name}__words": t.str.split().str.len()}), 0


def fit_target_label(s, p, y, name):
    st = {"map": {v: i for i, v in enumerate(sorted(pd.unique(keys(s.dropna()))))}}
    return st, "、".join(f"{k}→{v}" for k, v in st["map"].items())


def apply_target_label(s, st, name):
    k = keys(s)
    return pd.DataFrame({name: k.map(st["map"]).astype(float)}), int((~k.isin(list(st["map"]) + [NAN_KEY])).sum())


FIT = {"binary": fit_binary, "onehot": fit_onehot, "label": fit_label, "ordinal": fit_ordinal,
       "frequency": fit_frequency, "datetime": fit_datetime, "target_label": fit_target_label,
       "text_stats": lambda s, p, y, name: ({}, "文字数と、空白で区切った単語数")}
APPLY = {"binary": apply_binary, "onehot": apply_onehot, "label": apply_label, "ordinal": apply_ordinal,
         "frequency": apply_frequency, "target": apply_target, "datetime": apply_datetime,
         "text_stats": apply_text_stats, "target_label": apply_target_label}
NUM_METHODS = ("passthrough", "log1p", "standard", "minmax", "target_passthrough")


def transform(s, method, st, name):
    if method in NUM_METHODS:
        return apply_numeric(s, st, name, "passthrough" if method == "target_passthrough" else method)
    return APPLY[method](s, st, name)


def target_vector(df, schema, target, warns):
    """ターゲットエンコーディング用の目的変数（数値か2値のときだけ）。"""
    if not target or target not in df.columns:
        return None
    t = df[target]
    if schema.get(target) in NUMERIC_KINDS:
        return t.astype(float)
    vals = sorted(pd.unique(t.dropna().astype(str)))
    if len(vals) == 2:
        return t.astype(str).map({vals[0]: 0.0, vals[1]: 1.0}).where(t.notna())
    warns.append(f"目的変数 `{target}` が {len(vals)} クラスなのでターゲットエンコーディングは使えない。頻度エンコーディングに切り替えた")
    return None


def write_outputs(a, mode, df, enc, rows, warns, target, extra_meta):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    enc.to_csv(out / "encoded.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"source": r["col"], "kind": r["kind"], "method": r["method"], "n_out": len(r["out"]),
                   "outputs": " ".join(r["out"])} for r in rows]).to_csv(out / "feature_map.csv", index=False, encoding="utf-8-sig")
    non_num = [c for c in enc.columns if not pd.api.types.is_numeric_dtype(enc[c])]
    nan = enc.isna().sum()
    feats = [c for c in enc.columns if c != target]
    rep = tc.Report(f"エンコーディング（{mode}）", ROLE, {
        "入力": a.input, "出力": str(out / "encoded.csv"), **extra_meta,
        "行 × 列": f"{df.shape[0]:,} × {df.shape[1]:,} → {enc.shape[0]:,} × {enc.shape[1]:,}"
                 f"（特徴量 {len(feats)} 列" + (f"＋目的変数 `{target}`" if target in enc.columns else "") + "）"})
    rep.h("1. 列ごとの変換")
    rep.table(["元の列", "種類", "方法", "出力の列数", "出力の列", "変換の中身", "未知の値"],
              [[r["col"], tc.KIND_JA.get(r["kind"], r["kind"]), r["method"], len(r["out"]),
                tc.examples(r["out"], k=4, width=30) + (" …" if len(r["out"]) > 4 else ""), r["detail"],
                r["unseen"] if mode == "apply" else "-"] for r in rows])
    if mode == "apply":
        rep.p("未知の値: 学習用データになかった値の数。One-Hot ではすべて 0（「その他」列があればそこ）、ラベルは -1、頻度は 0、ターゲットは全体平均になる。")
    rep.h("2. 方法ごとの集計")
    agg = pd.DataFrame([{"m": r["method"], "n": len(r["out"])} for r in rows]).groupby("m")["n"].agg(["count", "sum"])
    rep.table(["方法", "元の列数", "出力の列数"], [[m, int(v["count"]), int(v["sum"])] for m, v in agg.iterrows()])
    rep.h("3. 出力の確認")
    rep.table(["確認", "結果"], [
        ["すべての列が数値か", "はい" if not non_num else f"いいえ: {non_num}"],
        ["欠損が残っている列", f"{int((nan > 0).sum())} 列（{int(nan.sum()):,} セル）"],
        ["値が1種類しかない列", tc.examples([c for c in feats if enc[c].nunique(dropna=False) <= 1], k=6) or "なし"]])
    left = [[c, int(nan[c]), tc.pct(nan[c] / max(len(enc), 1))] for c in enc.columns if nan[c]]
    if left:
        rep.h("欠損が残っている列", 3)
        rep.table(["列", "欠損数", "欠損率"], left)
        rep.p("LightGBM などの木のモデルは欠損のまま学習できる。線形モデルなどで使うなら、計画で `standard` にするか `params` に `{\"impute\": \"median\"}` を足す。")
    rep.h("4. 注意")
    rep.ul(warns or ["特になし"])
    rep.h("5. 出力した列の統計値")
    desc = enc.describe().T
    rep.table(["列", "平均", "標準偏差", "最小", "中央値", "最大", "分布"],
              [[c, r["mean"], r["std"], r["min"], r["50%"], r["max"], tc.spark(enc[c])] for c, r in desc.iterrows()])
    path = rep.save(out)
    print(f"エンコーディング（{mode}）完了: {df.shape[1]} 列 → {enc.shape[1]} 列、注意 {len(warns)} 件\nレポート: {path}")


def cmd_fit(a):
    df, schema, _ = tc.load_table(a.input)
    if schema is None:
        sys.exit("入力の隣に .schema.json がありません。クレンジング（段階3以降）を通したデータを渡してください。")
    if not a.plan or not Path(a.plan).exists():
        sys.exit("--plan（encoding_plan.json）が必要です。先にクレンジング後のデータをプロファイリングしてください。")
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    target = a.target or plan.get("target")
    over = tc.parse_kv(a.set)
    warns, rows, frames, state = [], [], [], {"target": target, "columns": {}}
    y = target_vector(df, schema, target, warns)
    for col in df.columns:
        kind, spec = schema[col], plan["columns"].get(col)
        if spec is None:
            warns.append(f"`{col}` は計画にないので除外した（プロファイリングをやり直すか --set で指定）")
            spec = {"method": "drop", "params": {}}
        method, p = over.get(col, spec["method"]), dict(spec.get("params") or {})
        if col == target and not method.startswith("target_"):
            method = "target_passthrough" if kind in NUMERIC_KINDS else "target_label"
        if method == "target" and y is None:
            method = "frequency"
        if method not in ("drop", "target_label", "target_passthrough") and method not in ALLOWED.get(kind, ()):
            sys.exit(f"`{col}`（{tc.KIND_JA[kind]}）に `{method}` は使えません。使える方法: {sorted(ALLOWED[kind])} と drop")
        if method == "drop":
            state["columns"][col] = {"method": "drop", "kind": kind}
            rows.append({"col": col, "kind": kind, "method": "drop", "out": [], "detail": spec.get("reason", ""), "unseen": 0})
            continue
        s = df[col]
        if method in NUM_METHODS:
            st, detail = fit_numeric(s, p, y, col, method)
            frame, _ = transform(s, method, st, col)
        elif method == "target":
            st, detail, frame = fit_target(s, p, y, col)
        else:
            st, detail = FIT[method](s, p, y, col)
            frame, _ = transform(s, method, st, col)
        state["columns"][col] = {"method": method, "kind": kind, "state": st, "outputs": list(frame.columns)}
        rows.append({"col": col, "kind": kind, "method": method, "out": list(frame.columns), "detail": detail, "unseen": 0})
        frames.append(frame)
        if method == "onehot" and frame.shape[1] > 30:
            warns.append(f"`{col}` の One-Hot が {frame.shape[1]} 列になった。frequency か target を検討")
    enc = pd.concat(frames, axis=1) if frames else pd.DataFrame(index=df.index)
    if target in enc.columns:
        enc = enc[[c for c in enc.columns if c != target] + [target]]
    if enc.columns.duplicated().any():
        sys.exit(f"出力の列名が重複: {list(enc.columns[enc.columns.duplicated()])}")
    state["feature_order"] = list(enc.columns)
    tc.jdump(state, Path(a.out) / "encoder_state.json")
    if any(r["method"] == "target" for r in rows):
        warns.append("ターゲットエンコーディングの列は、学習用データでは fold 外の平均、apply では全データの平均を使う。"
                     "交差検証のスコアを厳密に見るときは、検証の fold ごとに fit し直す")
    write_outputs(a, "fit", df, enc, rows, warns, target, {"計画": a.plan, "変換の保存先": str(Path(a.out) / "encoder_state.json")})


def cmd_apply(a):
    df, schema, _ = tc.load_table(a.input)
    if schema is None:
        sys.exit("入力の隣に .schema.json がありません。学習用データと同じクレンジングを通したデータを渡してください。")
    state = json.loads(Path(a.state).read_text(encoding="utf-8"))
    target, warns, rows, frames = state["target"], [], [], []
    for col, c in state["columns"].items():
        if c["method"] == "drop":
            continue
        if col not in df.columns:
            if col == target:
                warns.append(f"目的変数 `{target}` は入力にない（予測用データとして扱った）")
                continue
            sys.exit(f"入力に列がありません: {col}")
        if schema.get(col) != c["kind"]:
            warns.append(f"`{col}` の種類が学習用と違う（学習用 {c['kind']}、今回 {schema.get(col)}）。"
                         "クレンジングの段階3で `--schema-from` を使って揃える")
            df[col] = tc.convert_kind(df[col].astype(object).where(df[col].notna()).map(str, na_action="ignore"), c["kind"])[0]
        frame, unseen = transform(df[col], c["method"], c["state"], col)
        frame = frame.reindex(columns=c["outputs"], fill_value=0)
        if unseen:
            warns.append(f"`{col}`: 学習用データにない値が {unseen:,} 件")
        rows.append({"col": col, "kind": c["kind"], "method": c["method"], "out": list(frame.columns),
                     "detail": "学習用データで決めた変換をそのまま適用", "unseen": unseen})
        frames.append(frame)
    extra = [c for c in df.columns if c not in state["columns"]]
    if extra:
        warns.append(f"学習用データになかった列は無視した: {extra}")
    enc = pd.concat(frames, axis=1)
    enc = enc[[c for c in state["feature_order"] if c in enc.columns]]
    write_outputs(a, "apply", df, enc, rows, warns, target, {"変換": a.state})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--input", required=True)
    f.add_argument("--plan", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--target")
    f.add_argument("--set", default="", help="計画の方法を上書き（例: 都道府県=frequency,年収=standard）")
    f.set_defaults(func=cmd_fit)
    p = sub.add_parser("apply")
    p.add_argument("--input", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_apply)
    a = ap.parse_args()
    try:
        a.func(a)
    except ValueError as e:
        sys.exit(f"エラー: {e}")


if __name__ == "__main__":
    main()
