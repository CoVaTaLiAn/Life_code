#!/usr/bin/env python3
"""特徴量候補のピックアップ: カテゴリ別の統計から、特徴量になりそうなものを選んで根拠の数字つきで報告する。

  python3 pick_features.py --input cleaned.csv --out <出力先> [--target 列] [--columns 列,列] [--values 列,列]
      [--min-count 20] [--perm 500]

見るもの:
  A カテゴリ列 → 目的変数（カテゴリによって目的変数が違うか）
  B 際立つカテゴリ（全体と明らかに違う個別のカテゴリ → フラグの候補）
  C カテゴリ列 × 数値列（カテゴリによって数値が違うか → カテゴリ内での相対値の候補）
  D カテゴリ列の組み合わせ（2つを掛け合わせると初めて見える差）
  E 欠損かどうか（欠損フラグの候補）
データは変更せず、特徴量も作らない（候補を選んで報告するだけ）。
出力: report.md / report.html / feature_candidates.csv / feature_candidates.json
必要: pandas numpy
"""
import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import tabprep_common as tc  # noqa: E402

ROLE = "カテゴリ別の統計から特徴量になりそうなものを選び、根拠の数字と作り方を付けて報告する（データは変更せず、特徴量も作らない）"
SEED, OTHER = 42, "その他"
PRI = {3: "高", 2: "中", 1: "低"}


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


def labels(s, min_count):
    """カテゴリのラベル（件数が min_count 未満の値は「その他」にまとめる。欠損は欠損のまま）。"""
    lab = s.map(lambda v: str(int(v)) if isinstance(v, (float, np.floating)) and float(v).is_integer() else str(v),
                na_action="ignore")
    vc = lab.value_counts()
    small = vc.index[vc < min_count]
    return lab.where(~lab.isin(small), OTHER) if len(small) >= 2 or (len(small) == 1 and OTHER not in vc.index) else lab


def eta2(codes, y, k):
    """カテゴリで説明できる割合（相関比 η²）。戻り値: (η², グループ数で補正した η²)"""
    n = len(y)
    cnt = np.bincount(codes, minlength=k)
    sums = np.bincount(codes, weights=y, minlength=k)
    used = cnt > 0
    sst = ((y - y.mean()) ** 2).sum()
    if sst == 0 or used.sum() < 2:
        return 0.0, 0.0
    ssb = (cnt[used] * (sums[used] / cnt[used] - y.mean()) ** 2).sum()
    e = ssb / sst
    return float(e), float(max(0.0, 1 - (1 - e) * (n - 1) / max(n - used.sum(), 1)))


def relation(lab, y, n_perm, rng):
    """カテゴリ（ラベル列）と数値 y の関係の強さ。並べ替え検定で「偶然でもこの強さになる確率」を出す。"""
    m = lab.notna() & y.notna()
    if m.sum() < 30 or lab[m].nunique() < 2:
        return None
    codes, uniq = pd.factorize(lab[m])
    yy = y[m].astype(float).values
    e, adj = eta2(codes, yy, len(uniq))
    hits = sum(eta2(codes, rng.permutation(yy), len(uniq))[0] >= e for _ in range(n_perm))
    return {"n": int(m.sum()), "k": len(uniq), "eta2": e, "adj": adj, "p": (1 + hits) / (1 + n_perm)}


def priority(r):
    if r["adj"] >= .06 and r["p"] < .01:
        return 3
    if r["adj"] >= .01 and r["p"] < .05:
        return 2
    return 1


def bar(x, scale=.2):
    return "█" * max(0, min(20, round(20 * x / scale)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", help="目的変数（数値か 0/1）。ないときは C（カテゴリ×数値）だけを見る")
    ap.add_argument("--columns", default="", help="見るカテゴリ列（既定は自動）")
    ap.add_argument("--values", default="", help="見る数値列（既定はすべて）")
    ap.add_argument("--min-count", type=int, default=20, help="この件数未満のカテゴリは「その他」にまとめ、個別には評価しない")
    ap.add_argument("--perm", type=int, default=500, help="並べ替え検定の回数")
    a = ap.parse_args()
    out = Path(a.out)
    rng = np.random.RandomState(SEED)
    df, schema, cleaned = typed_table(a.input)
    for c in [a.target] + a.columns.split(",") + a.values.split(","):
        if c and c not in df.columns:
            sys.exit(f"列がありません: {c}（列: {list(df.columns)}）")
    if a.target and schema[a.target] not in ("numeric", "bool"):
        sys.exit(f"目的変数 `{a.target}` は数値か 0/1 にしてください（種類: {tc.KIND_JA[schema[a.target]]}）")
    y = df[a.target].astype(float) if a.target else None
    nuniq = df.nunique()
    values = [c for c in a.values.split(",") if c] or [
        c for c in df.columns if schema[c] == "numeric" and nuniq[c] > 10 and c != a.target]
    cats = [c for c in a.columns.split(",") if c] or [
        c for c in df.columns if c != a.target and c not in values and nuniq[c] >= 2
        and (schema[c] in ("category", "bool") or (schema[c] == "numeric" and nuniq[c] <= 10))]
    lab = {c: labels(df[c], a.min_count) for c in cats}
    cand = []  # 候補: {pri, kind, feature, how, evidence, score}

    rep = tc.Report(f"特徴量候補のピックアップ: {Path(a.input).name}", ROLE, {
        "入力": a.input, "状態": "クレンジング済み（schema あり）" if cleaned else "未クレンジング（種類は推定）",
        "目的変数": a.target or "指定なし（カテゴリ×数値だけを見た）",
        "見た列": f"カテゴリ列 {len(cats)} 個 × 数値列 {len(values)} 個", "並べ替え検定": f"{a.perm} 回"})

    # ---------------- A カテゴリ → 目的変数
    rows_a, rows_b = [], []
    if a.target:
        overall, sd = y.mean(), y.std()
        for c in cats:
            r = relation(lab[c], y, a.perm, rng)
            if not r:
                continue
            g = y.groupby(lab[c]).agg(["mean", "count"])
            hi, lo = g["mean"].idxmax(), g["mean"].idxmin()
            ev = f"η² {r['adj']:.3f}、p {r['p']:.3f}。{hi} {tc.fmt(float(g.loc[hi, 'mean']))} ↔ {lo} {tc.fmt(float(g.loc[lo, 'mean']))}"
            rows_a.append([c, r["k"], r["adj"], r["p"], f"{hi}（{tc.fmt(float(g.loc[hi, 'mean']))}、{int(g.loc[hi, 'count'])}件）",
                           f"{lo}（{tc.fmt(float(g.loc[lo, 'mean']))}、{int(g.loc[lo, 'count'])}件）", PRI[priority(r)], bar(r["adj"])])
            enc = "そのまま One-Hot / 順序" if r["k"] <= 10 else "ターゲットエンコーディング（fold 外）か頻度"
            cand.append({"pri": priority(r), "kind": "A カテゴリそのもの", "feature": c, "how": f"`{c}` を {enc} で入れる",
                         "evidence": ev, "score": r["adj"]})
            # B 際立つカテゴリ
            for cat, row in g.iterrows():
                if row["count"] < a.min_count or cat == OTHER or len(g) <= 2:
                    continue
                se = sd / np.sqrt(row["count"])
                z = (row["mean"] - overall) / se
                if abs(z) >= 2.5:
                    rows_b.append([c, cat, int(row["count"]), row["mean"], overall, row["mean"] - overall, round(float(z), 1)])
                    cand.append({"pri": 3 if abs(z) >= 4 else 2, "kind": "B 際立つカテゴリ", "feature": f"{c}={cat} フラグ",
                                 "how": f"`{c}` が `{cat}` なら 1、それ以外は 0",
                                 "evidence": f"{a.target} の平均 {tc.fmt(float(row['mean']))}（全体 {tc.fmt(float(overall))}、{int(row['count'])} 件、差は標準誤差の {abs(z):.1f} 倍）",
                                 "score": abs(z) / 100})
    # ---------------- C カテゴリ × 数値
    rows_c = []
    for c, v in itertools.product(cats, values):
        r = relation(lab[c], df[v], a.perm, rng)
        if not r:
            continue
        g = df[v].groupby(lab[c]).median()
        p = priority(r)
        rows_c.append([c, v, r["adj"], r["p"], f"{g.idxmax()}（{tc.fmt(float(g.max()))}）", f"{g.idxmin()}（{tc.fmt(float(g.min()))}）",
                       PRI[p], bar(r["adj"])])
        if p >= 2:
            cand.append({"pri": p if not a.target else p - 1 or 1, "kind": "C カテゴリ内での相対値", "feature": f"{v} ÷ {c}別の中央値",
                         "how": f"`{v}` を、同じ `{c}` の行の中央値で割る（または引く）。中央値は学習用データだけで計算する",
                         "evidence": f"`{c}` によって `{v}` が違う（η² {r['adj']:.3f}、p {r['p']:.3f}。中央値 {g.idxmax()} {tc.fmt(float(g.max()))} ↔ {g.idxmin()} {tc.fmt(float(g.min()))}）",
                         "score": r["adj"]})
    # ---------------- D 組み合わせ
    rows_d = []
    if a.target:
        single = {r[0]: r[2] for r in rows_a}
        for c1, c2 in itertools.combinations([c for c in cats if lab[c].nunique() <= 10], 2):
            both = (lab[c1] + " × " + lab[c2]).where(lab[c1].notna() & lab[c2].notna())
            both = labels(both, a.min_count)
            r = relation(both, y, a.perm, rng)
            if not r:
                continue
            gain = r["adj"] - single.get(c1, 0) - single.get(c2, 0)
            if gain >= .01 and r["p"] < .05:
                g = y.groupby(both).agg(["mean", "count"])
                g = g[g.index != OTHER]
                hi, lo = g["mean"].idxmax(), g["mean"].idxmin()
                rows_d.append([f"{c1} × {c2}", r["k"], r["adj"], single.get(c1, 0), single.get(c2, 0), gain, r["p"],
                               f"{hi}（{tc.fmt(float(g.loc[hi, 'mean']))}、{int(g.loc[hi, 'count'])}件）",
                               f"{lo}（{tc.fmt(float(g.loc[lo, 'mean']))}、{int(g.loc[lo, 'count'])}件）"])
                cand.append({"pri": 3 if gain >= .03 else 2, "kind": "D 組み合わせ", "feature": f"{c1} × {c2}",
                             "how": f"`{c1}` と `{c2}` をつなげた新しいカテゴリを作り、頻度かターゲットエンコーディングで入れる",
                             "evidence": f"組み合わせの η² {r['adj']:.3f}（単独 {single.get(c1, 0):.3f} と {single.get(c2, 0):.3f} の和より {gain:.3f} 多い、p {r['p']:.3f}）",
                             "score": gain})
    # ---------------- E 欠損フラグ
    rows_e = []
    if a.target:
        for c in df.columns:
            miss = df[c].isna()
            if c == a.target or miss.sum() < a.min_count or (~miss).sum() < a.min_count:
                continue
            r = relation(miss.map({True: "欠損", False: "値あり"}), y, a.perm, rng)
            m1, m0 = y[miss].mean(), y[~miss].mean()
            p = priority(r)
            rows_e.append([c, int(miss.sum()), tc.pct(miss.mean()), m1, m0, m1 - m0, r["p"], PRI[p]])
            if p >= 2:
                cand.append({"pri": p, "kind": "E 欠損フラグ", "feature": f"{c} が欠損", "how": f"`{c}` が欠損なら 1、値があれば 0",
                             "evidence": f"{a.target} の平均: 欠損 {tc.fmt(float(m1))}（{int(miss.sum())} 件）↔ 値あり {tc.fmt(float(m0))}、p {r['p']:.3f}",
                             "score": r["adj"]})

    cand.sort(key=lambda d: (-d["pri"], -d["score"]))
    picked = [d for d in cand if d["pri"] >= 2]
    n_tests = len(rows_a) + len(rows_c) + len(rows_e) + (len(list(itertools.combinations([c for c in cats if lab[c].nunique() <= 10], 2))) if a.target else 0)

    rep.h("1. ピックアップした特徴量候補（優先度の高い順）")
    rep.table(["#", "優先度", "種類", "特徴量の案", "作り方", "根拠"],
              [[i + 1, PRI[d["pri"]], d["kind"], d["feature"], d["how"], d["evidence"]] for i, d in enumerate(picked)],
              empty="優先度が「中」以上の候補は見つからなかった")
    rep.p(f"優先度の決め方: **高** = η² が 0.06 以上で p < 0.01、**中** = η² が 0.01 以上で p < 0.05、それ以外は低（見送り）。"
          f"今回は {n_tests} 組を調べているので、p が 0.05 に近い「中」は偶然でも {max(1, round(n_tests * .05))} 件ほど出うる。"
          "ここに載ったものは「試す価値がある候補」で、効くかどうかはモデルに入れて交差検証で確かめる。")
    rep.ul(["η²（相関比）: その数値のばらつきのうち、カテゴリの違いで説明できる割合。0〜1。グループ数の多さで大きく見えないよう補正した値を使っている",
            "p: カテゴリと数値の対応をでたらめに入れ替えても、同じかそれ以上の強さになる割合（並べ替え検定）",
            f"件数が {a.min_count} 未満のカテゴリは「その他」にまとめ、個別には評価していない"])

    if a.target:
        rep.h(f"2. A カテゴリ列 → 目的変数 `{a.target}`")
        rows_a.sort(key=lambda r: -r[2])
        rep.table(["カテゴリ列", "グループ数", "η²", "p", "平均が最も高い", "平均が最も低い", "優先度", ""], rows_a)
        rep.h("3. B 際立つカテゴリ（フラグの候補）")
        rows_b.sort(key=lambda r: -abs(r[6]))
        rep.table(["カテゴリ列", "カテゴリ", "件数", f"{a.target} の平均", "全体の平均", "差", "差 ÷ 標準誤差"], rows_b,
                  empty="全体と明らかに違う個別のカテゴリはなかった（3 グループ以上の列で、差が標準誤差の 2.5 倍以上のもの）")
        rep.p("2 グループしかない列は、列そのものを入れれば足りるのでここには出さない。")
    rep.h(("4" if a.target else "2") + ". C カテゴリ列 × 数値列（カテゴリ内での相対値の候補）")
    rows_c.sort(key=lambda r: -r[2])
    rep.table(["カテゴリ列", "数値列", "η²", "p", "中央値が最も高い", "中央値が最も低い", "優先度", ""],
              [r for r in rows_c if r[6] != "低"], empty="カテゴリによって数値がはっきり違う組はなかった")
    rep.p(f"調べた {len(rows_c)} 組のうち、優先度が中以上のものだけを表示。"
          "カテゴリによって水準が違う数値は、「そのカテゴリの中で高いか低いか」に直すと、カテゴリの影響と個人差を分けられる。"
          + ("目的変数との関係は直接は見ていないので、候補一覧では優先度を1段下げている。" if a.target else ""))
    if a.target:
        rep.h("5. D カテゴリ列の組み合わせ")
        rows_d.sort(key=lambda r: -r[5])
        rep.table(["組み合わせ", "グループ数", "η²（組み合わせ）", "η²（1つ目だけ）", "η²（2つ目だけ）", "上乗せ", "p", "平均が最も高い", "平均が最も低い"],
                  rows_d, empty="2つを掛け合わせて初めて見える差はなかった（上乗せ 0.01 以上、p < 0.05 のもの）")
        rep.p("上乗せ: 組み合わせの η² から、それぞれ単独の η² を引いた値。木のモデルは組み合わせを自分で見つけられるので、効果は線形モデルで大きい。")
        rep.h("6. E 欠損かどうか（欠損フラグの候補）")
        rows_e.sort(key=lambda r: r[6])
        rep.table(["列", "欠損数", "欠損率", f"{a.target} の平均（欠損）", f"{a.target} の平均（値あり）", "差", "p", "優先度"], rows_e,
                  empty=f"欠損が {a.min_count} 件以上ある列はなかった")
    rep.h(("7" if a.target else "3") + ". 見送ったもの")
    low = [d for d in cand if d["pri"] < 2]
    rep.table(["種類", "特徴量の案", "根拠"], [[d["kind"], d["feature"], d["evidence"]] for d in low], empty="なし")
    rep.h(("8" if a.target else "4") + ". 使うときの注意")
    rep.ul(["目的変数を使って作る特徴量（ターゲットエンコーディング、カテゴリ別の目的変数の平均）は、必ず fold 外の値で作る。そうしないと検証スコアが良く見えすぎる",
            "カテゴリ別の中央値などの集計は学習用データだけで計算し、テスト用データには同じ値を当てる",
            "ここで見たのはカテゴリを軸にした関係だけ。数値列そのものと目的変数の関係、時間の流れ、リーク（予測時点で分からない情報）は別に確認する",
            "候補を採用したら、1つずつ足して交差検証のスコアで効果を確かめる。効かなかったものも記録する"])

    out.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame([{"priority": PRI[d["pri"]], "kind": d["kind"], "feature": d["feature"], "how": d["how"],
                           "evidence": d["evidence"], "score": round(d["score"], 4)} for d in cand])
    table.to_csv(out / "feature_candidates.csv", index=False, encoding="utf-8-sig")
    tc.jdump({"target": a.target, "candidates": table.to_dict("records")}, out / "feature_candidates.json")
    path = rep.save(out)
    print(f"ピックアップ完了: 候補 {len(picked)} 件（高 {sum(d['pri'] == 3 for d in cand)}、中 {sum(d['pri'] == 2 for d in cand)}）、"
          f"見送り {len(low)} 件\nレポート: {path}")


if __name__ == "__main__":
    main()
