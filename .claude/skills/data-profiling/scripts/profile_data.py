#!/usr/bin/env python3
"""データプロファイリング: どういうデータがどのように入っているかを調べる（データは一切変更しない）。

  python3 profile_data.py --input data.csv --out <出力先> [--target 列名] [--title 名前]

列ごとに 種類・欠損・カテゴリ・統計値・品質の問題・おすすめのエンコーディング を出す。
出力: report.md / report.html / profile.json / column_profile.csv / encoding_plan.json
入力の隣に <名前>.schema.json（クレンジング後に作られる）があれば、その種類をそのまま使う。
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import tabprep_common as tc  # noqa: E402

ROLE = "データの中身を調べて報告する（変更はしない）。クレンジングとエンコーディングの判断材料を作る"
ORDERS = [["低", "中", "高"], ["小", "中", "大"], ["xs", "s", "m", "l", "xl", "xxl"], ["low", "medium", "high"],
          ["low", "mid", "high"], ["悪い", "普通", "良い"], ["初級", "中級", "上級"],
          ["不満", "やや不満", "普通", "やや満足", "満足"], ["bronze", "silver", "gold", "platinum"],
          ["ブロンズ", "シルバー", "ゴールド", "プラチナ"], ["中卒", "高卒", "専門卒", "大卒", "院卒"]]
METHOD_JA = {
    "drop": "使わない（除外）", "passthrough": "そのまま", "log1p": "対数変換 log1p", "standard": "標準化",
    "minmax": "0〜1 に正規化", "binary": "0/1 化", "onehot": "One-Hot", "label": "ラベル(整数)",
    "ordinal": "順序(整数)", "frequency": "頻度(出現割合)", "target": "ターゲット(目的変数の平均)",
    "datetime": "日時の分解＋周期", "text_stats": "文字数・単語数", "target_label": "目的変数: クラス→整数",
    "target_passthrough": "目的変数: そのまま"}


def detect_order(values):
    """順序のあるカテゴリなら並び順を返す。"""
    vals = [str(v) for v in values]
    low = {v.casefold(): v for v in vals}
    for order in ORDERS:
        hit = [low[o] for o in order if o in low]
        if len(hit) == len(vals) >= 2:
            return hit
    nums = [re.match(r"^\D{0,3}(\d+(\.\d+)?)", v) for v in vals]
    if 3 <= len(vals) <= 30 and all(nums):
        keyed = sorted(zip([float(m.group(1)) for m in nums], vals))
        if len({k for k, _ in keyed}) == len(vals):
            return [v for _, v in keyed]
    return None


def recommend(c, target):
    """列の性質からエンコーディングを1つ勧める。戻り値: (方法, パラメータ, 理由, 代わりの案)"""
    k, nu, miss = c["kind"], c["n_unique"], c["missing_rate"]
    if c["name"] == target:
        if k in ("numeric", "bool") and nu > 20:
            return "target_passthrough", {}, "目的変数（数値・回帰）。入力には使わない", []
        return "target_label", {}, f"目的変数（{nu} クラスの分類）。クラスを整数にする", []
    if nu <= 1:
        return "drop", {}, "値が1種類しかなく情報がない", []
    if miss >= .95:
        return "drop", {}, f"欠損が {tc.pct(miss)}。ほぼ空", ["欠損かどうかの 0/1 だけ残す"]
    if k == "id":
        return "drop", {}, "行を識別するだけの値。学習に使うと丸暗記になる", ["別の表との結合キーとして使う"]
    if k == "bool" or nu == 2:
        return "binary", {}, "値が2種類。0/1 にすれば十分", []
    if k == "numeric":
        st = c["stats"]
        if nu <= 10:
            return "passthrough", {}, f"数値だが {nu} 種類しかない。大小に意味があればそのまま", \
                ["コード値（大小に意味がない）なら onehot"]
        if st["min"] >= 0 and st["skew"] is not None and st["skew"] > 1:
            return "log1p", {}, f"右に裾が長い（歪度 {st['skew']:.1f}、0 以上）。対数で裾を縮める", \
                ["木のモデル（LightGBM など）だけなら passthrough でよい"]
        return "passthrough", {}, "分布に大きな偏りがない。木のモデルならそのまま使える", \
            ["線形モデル・ニューラルネットなら standard（標準化）"]
    if k == "datetime":
        return "datetime", {}, "年・月・曜日などに分解し、月と曜日は sin/cos で周期を表す", \
            ["基準日からの経過日数だけ使う"]
    if k == "text":
        return "text_stats", {}, "自由記述。まず文字数・単語数だけを数値にする", \
            ["TF-IDF や埋め込み（この処理の対象外。別途）", "drop"]
    order = detect_order(c["values_all"]) if nu <= 30 else None
    if order:
        return "ordinal", {"order": order}, "値に順序がある。順番どおりの整数にする", ["onehot"]
    if nu <= 10:
        return "onehot", {}, f"{nu} 種類と少ない。列が増えすぎず、順序の仮定も置かない", \
            ["木のモデルだけなら label"]
    alt_t = ["target（目的変数があるとき。fold 外の平均を使う）"] if not target else ["frequency"]
    if nu <= 50:
        if target:
            return "target", {}, f"{nu} 種類。One-Hot では列が増えすぎるので目的変数の平均に置き換える（fold 外で計算）", \
                ["frequency", "onehot（上位だけ残す）"]
        return "frequency", {}, f"{nu} 種類。One-Hot では列が増えすぎるので出現割合に置き換える", alt_t + ["onehot（上位だけ残す）"]
    if target:
        return "target", {}, f"{nu} 種類と多い。目的変数の平均に置き換える（fold 外で計算し、件数で平滑化）", ["frequency"]
    return "frequency", {}, f"{nu} 種類と多い。出現割合に置き換える", alt_t


def profile_column(name, raw, kind_forced):
    n = len(raw)
    c = {"name": name, "n": n, "issues": []}
    n_empty = int(raw.isna().sum())
    if kind_forced:  # クレンジング済み（schema あり）
        vals, kind, notes = raw, kind_forced, []
        c.update(n_null_token=0, n_normalize=0, n_fail=0)
    else:
        normed = tc.map_unique(raw, tc.norm_text)
        changed = raw.notna() & (normed != raw)
        tok = normed.notna() & normed.map(lambda v: tc.is_null_token(v) or v == "", na_action="ignore").fillna(False).astype(bool)
        clean = normed.mask(tok)
        info = tc.infer_kind(clean, name)
        vals, kind, notes = info["values"], info["kind"], info["notes"]
        c.update(n_null_token=int(tok.sum()), n_normalize=int(changed.sum()), n_fail=int(info["fail"].sum()))
        if changed.sum():
            c["issues"].append(("2 文字の正規化", "前後の空白・全角英数字・制御文字がある", int(changed.sum()),
                                tc.examples([repr(x) for x in raw[changed].unique()])))
        if tok.sum():
            c["issues"].append(("2 文字の正規化", "欠損を表す文字（NA, - など）が入っている", int(tok.sum()),
                                tc.examples(raw[tok].unique())))
        if info["fail"].sum():
            c["issues"].append(("3 型の変換", f"{tc.KIND_JA[kind]}として読めない値が混ざっている", int(info["fail"].sum()),
                                tc.examples(clean[info["fail"]].unique())))
    nn = vals.dropna()
    c.update(kind=kind, notes=notes, n_missing=int(n - len(nn)), n_empty=n_empty,
             missing_rate=(n - len(nn)) / n if n else 0.0, n_unique=int(nn.nunique()),
             examples=tc.examples(nn.unique()), values_all=[])
    if kind in ("numeric", "bool") and len(nn):
        q = nn.quantile([.25, .5, .75])
        fences = tc.iqr_fences(nn)
        n_out = int(((nn < fences[0]) | (nn > fences[1])).sum()) if fences else 0
        c["stats"] = {"mean": float(nn.mean()), "std": float(nn.std()) if len(nn) > 1 else 0.0,
                      "min": float(nn.min()), "q1": float(q[.25]), "median": float(q[.5]), "q3": float(q[.75]),
                      "max": float(nn.max()), "skew": float(nn.skew()) if nn.nunique() > 2 else None,
                      "zero_rate": float((nn == 0).mean()), "n_negative": int((nn < 0).sum()),
                      "n_outlier": n_out, "is_integer": bool((nn == nn.round()).all()), "hist": tc.spark(nn)}
        if n_out:
            c["issues"].append(("6 外れ値", "他の値から大きく離れた値（四分位範囲の3倍より外）", n_out,
                                tc.examples(sorted(nn[(nn < fences[0]) | (nn > fences[1])].unique(), key=abs, reverse=True))))
        for v, cnt in tc.sentinel_candidates(nn):
            c["issues"].append(("5 欠損", f"欠損コードらしい値 {tc.fmt(float(v))}", cnt, "意味を確認する"))
        if 0 < (nn < 0).mean() < .05:
            c["issues"].append(("6 外れ値", "負の値が少数だけある", int((nn < 0).sum()), tc.examples(nn[nn < 0].unique())))
        if nn.nunique() <= 12:
            vc = nn.value_counts().sort_index()
            c["top"] = [(tc.fmt(float(v)), int(cnt), cnt / len(nn)) for v, cnt in vc.items()]
    elif kind == "datetime" and len(nn):
        c["stats"] = {"min": nn.min(), "max": nn.max(), "days": int((nn.max() - nn.min()).days),
                      "has_time": bool(((nn.dt.hour != 0) | (nn.dt.minute != 0)).any())}
        if (nn > pd.Timestamp.now()).any():
            c["issues"].append(("6 外れ値", "未来の日時がある", int((nn > pd.Timestamp.now()).sum()), tc.fmt(nn.max())))
        if (nn < pd.Timestamp("1900-01-01")).any():
            c["issues"].append(("6 外れ値", "1900年より前の日時がある", int((nn < pd.Timestamp("1900-01-01")).sum()), tc.fmt(nn.min())))
    elif len(nn):
        s = nn.astype(str)
        vc = s.value_counts()
        ln = s.str.len()
        c["top"] = [(v, int(cnt), cnt / len(s)) for v, cnt in vc.head(10).items()]
        c["stats"] = {"len_mean": float(ln.mean()), "len_min": int(ln.min()), "len_max": int(ln.max()),
                      "top_share": float(vc.iloc[0] / len(s)), "n_rare": int((vc / len(s) < .01).sum()),
                      "n_once": int((vc == 1).sum())}
        if kind == "category":
            if c["n_unique"] <= 30:
                c["values_all"] = list(vc.index)
            groups = tc.variant_groups(s)
            if groups:
                c["issues"].append(("4 カテゴリの統一", "同じ意味と思われる書き方の違い（表記ゆれ）", len(groups),
                                    tc.examples([" = ".join(g) for _, g in groups], k=2, width=40)))
            ph = [v for v in vc.index if v.casefold() in tc.PLACEHOLDERS]
            if ph:
                c["issues"].append(("5 欠損", "「不明」などの値。欠損として扱うか確認", int(vc[ph].sum()), tc.examples(ph)))
    if c["missing_rate"] >= .5:
        c["issues"].append(("5 欠損", "欠損が半分以上", c["n_missing"], tc.pct(c["missing_rate"])))
    if c["n_unique"] == 1 and c["n_missing"] == 0:
        c["issues"].append(("1 構造", "値が1種類しかない（定数列）", n, c["examples"]))
    return c, vals


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", help="目的変数の列名（あればエンコーディングの推奨に反映）")
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    out = Path(a.out)
    df, schema, info = tc.load_table(a.input)
    if a.target and a.target not in df.columns:
        sys.exit(f"--target の列がありません: {a.target}（列: {list(df.columns)}）")
    n, m = df.shape
    cols, typed = [], {}
    for name in df.columns:
        c, vals = profile_column(name, df[name], (schema or {}).get(name))
        cols.append(c)
        typed[name] = vals
    for c in cols:
        c["method"], c["params"], c["reason"], c["alternatives"] = recommend(c, a.target)
    n_dup = int(df.duplicated().sum())
    kinds = pd.Series([c["kind"] for c in cols]).value_counts()
    miss_cells = sum(c["n_missing"] for c in cols)

    rep = tc.Report(f"データプロファイリング: {a.title or Path(a.input).name}", ROLE, {
        "入力": a.input, "状態": "クレンジング済み（schema あり）" if schema else "未クレンジング（種類は推定）",
        "文字コード / 区切り": f"{info['encoding']} / {info['sep']}"})
    rep.h("1. 全体")
    rep.table(["項目", "値"], [
        ["行数 × 列数", f"{n:,} × {m:,}"],
        ["列の種類", "、".join(f"{tc.KIND_JA[k]} {v}" for k, v in kinds.items())],
        ["欠損セル", f"{miss_cells:,}（全セルの {tc.pct(miss_cells / max(n * m, 1))}）"],
        ["完全に重複した行", f"{n_dup:,}"],
        ["目的変数", a.target or "指定なし"]])

    rep.h("2. 列の一覧")
    rep.table(["列", "種類", "欠損率", "種類数", "値の例", "おすすめのエンコーディング"],
              [[c["name"], tc.KIND_JA[c["kind"]], tc.pct(c["missing_rate"]), c["n_unique"], c["examples"],
                METHOD_JA[c["method"]]] for c in cols])

    rep.h("3. 数値列の統計値")
    nums = [c for c in cols if c["kind"] in ("numeric", "bool") and "stats" in c]
    rep.table(["列", "平均", "標準偏差", "最小", "25%", "中央値", "75%", "最大", "歪度", "0 の割合", "外れ値", "分布"],
              [[c["name"], c["stats"]["mean"], c["stats"]["std"], c["stats"]["min"], c["stats"]["q1"],
                c["stats"]["median"], c["stats"]["q3"], c["stats"]["max"], c["stats"]["skew"],
                tc.pct(c["stats"]["zero_rate"]), c["stats"]["n_outlier"], c["stats"]["hist"]] for c in nums])
    rep.p("歪度: 0 に近いほど左右対称、1 を超えると右に裾が長い。外れ値: 四分位範囲の3倍より外にある値の数。分布: 最小〜最大を10区間に分けた件数。")

    rep.h("4. カテゴリ列の中身")
    cats = [c for c in cols if c["kind"] == "category" and "top" in c]
    rep.table(["列", "種類数", "最多の値の割合", "1% 未満の値の数", "1回だけの値の数"],
              [[c["name"], c["n_unique"], tc.pct(c["stats"]["top_share"]), c["stats"]["n_rare"], c["stats"]["n_once"]]
               for c in cats])
    for c in cats + [c for c in nums if "top" in c and c["kind"] == "numeric"]:
        rep.h(f"{c['name']}（{c['n_unique']} 種類" + ("・上位10" if c["n_unique"] > 10 else "") + "）", 3)
        rep.table(["値", "件数", "割合", ""], [[v, cnt, tc.pct(sh), "█" * max(1, round(20 * sh))] for v, cnt, sh in c["top"]])

    rep.h("5. 日時・文章・ID の列")
    rows = []
    for c in cols:
        st = c.get("stats")
        if c["kind"] == "datetime" and st:
            rows.append([c["name"], "日時", f"{tc.fmt(st['min'])} 〜 {tc.fmt(st['max'])}（{st['days']:,} 日間）"
                         + ("、時刻あり" if st["has_time"] else "")])
        elif c["kind"] in ("text", "id") and st:
            rows.append([c["name"], tc.KIND_JA[c["kind"]],
                         f"種類数 {c['n_unique']:,}、文字数 {st['len_min']}〜{st['len_max']}（平均 {st['len_mean']:.1f}）"])
    rep.table(["列", "種類", "内容"], rows)

    rep.h("6. データ品質の気づき（クレンジングで対応すること）")
    issues = [[stage, c["name"], what, cnt, ex] for c in cols for stage, what, cnt, ex in c["issues"]]
    if n_dup:
        issues.append(["1 構造", "（行）", "完全に重複した行", n_dup, ""])
    issues.sort(key=lambda r: r[0])
    rep.table(["対応する段階", "列", "気づいたこと", "件数", "例"], issues, empty="問題は見つからなかった")
    notes = [f"`{c['name']}`: {t}" for c in cols for t in c["notes"]]
    rep.ul(notes)

    rep.h("7. 相関の強い数値列の組")
    num_df = pd.DataFrame({c["name"]: typed[c["name"]] for c in nums if c["n_unique"] > 2})
    pairs = []
    if num_df.shape[1] >= 2:
        corr = num_df.corr()
        for i, a_ in enumerate(corr.columns):
            for b_ in corr.columns[i + 1:]:
                if abs(corr.loc[a_, b_]) >= .9:
                    pairs.append([a_, b_, round(float(corr.loc[a_, b_]), 3)])
    rep.table(["列A", "列B", "相関係数"], pairs, empty="相関係数の絶対値が 0.9 以上の組はない")
    if pairs:
        rep.p("ほぼ同じ情報の列。線形モデルでは片方を外すか、差・比に作り直すことを検討する。")

    rep.h("8. おすすめのエンコーディング")
    rep.table(["列", "種類", "方法", "理由", "代わりの案"],
              [[c["name"], tc.KIND_JA[c["kind"]], f"{METHOD_JA[c['method']]} (`{c['method']}`)", c["reason"],
                " ／ ".join(c["alternatives"]) or "-"] for c in cols])
    rep.p("この内容は `encoding_plan.json` に書き出してある。変えたい列は `method` を書き換えてからエンコーディングに渡す。"
          + ("" if schema else " **未クレンジングのデータでの推定なので、クレンジング後にもう一度プロファイリングして計画を作り直すこと。**"))

    rep.h("9. 次の処理")
    rep.ul(["クレンジング（段階的）: `.claude/skills/data-cleansing/SKILL.md`"] if not schema else
           ["エンコーディング: `.claude/skills/data-encoding/SKILL.md`（`encoding_plan.json` を渡す）"])

    tc.jdump({"target": a.target, "source": a.input, "columns": {
        c["name"]: {"kind": c["kind"], "method": c["method"], "params": c["params"], "reason": c["reason"],
                    "alternatives": c["alternatives"]} for c in cols}}, out / "encoding_plan.json")
    tc.jdump({"input": a.input, "rows": n, "cols": m, "duplicate_rows": n_dup, "cleaned": bool(schema),
              "columns": [{k: v for k, v in c.items() if k != "values_all"} for c in cols]}, out / "profile.json")
    pd.DataFrame([{"column": c["name"], "kind": c["kind"], "missing_rate": round(c["missing_rate"], 4),
                   "n_unique": c["n_unique"], "examples": c["examples"], "encoding": c["method"],
                   "reason": c["reason"], **{k: v for k, v in (c.get("stats") or {}).items() if k != "hist"}}
                  for c in cols]).to_csv(out / "column_profile.csv", index=False, encoding="utf-8-sig")
    path = rep.save(out)
    print(f"プロファイリング完了: {n:,} 行 × {m:,} 列、品質の気づき {len(issues)} 件\nレポート: {path}\n計画: {out / 'encoding_plan.json'}")


if __name__ == "__main__":
    main()
