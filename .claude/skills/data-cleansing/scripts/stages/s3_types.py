"""段階3 型の変換: 列ごとに種類（数値・真偽・日時・カテゴリ・文章・ID）を決めて変換する。"""
import json

import tabprep_common as tc

NAME, TITLE = "types", "型の変換"
ROLE = "各列の種類を決め、数値（¥ , % を外す）・真偽（はい/いいえ→1/0）・日時に変換する。読めなかった値は欠損にして一覧にする"
NEXT = "段階4（カテゴリの統一）"


def add_args(ap):
    ap.add_argument("--kind", default="", help="[段階3] 種類を手で指定（例: 郵便番号=category,評価=numeric）。"
                    "種類: " + " ".join(tc.KINDS))
    ap.add_argument("--schema-from", help="[段階3] 別のデータ（学習用など）の schema.json と同じ種類にする")


def run(df, schema, a):
    forced = {}
    if a.schema_from:
        forced.update(json.load(open(a.schema_from, encoding="utf-8"))["columns"])
    forced.update(tc.parse_kv(a.kind))
    bad = {k: v for k, v in forced.items() if v not in tc.KINDS}
    if bad:
        raise SystemExit(f"種類の指定が不正: {bad}（使える種類: {tc.KINDS}）")
    actions, review, notes, rows, kinds = [], [], [], [], {}
    for c in df.columns:
        s = df[c]
        if c in forced:
            kind = forced[c]
            vals, fail = tc.convert_kind(s, kind)
            info = {"kind": kind, "values": vals, "fail": fail, "notes": ["種類は指定による"]}
        else:
            info = tc.infer_kind(s, c)
        kinds[c] = info["kind"]
        nn = s.notna()
        if info["kind"] in ("numeric", "bool", "datetime"):
            ok = nn & ~info["fail"]
            ex = [f"{o}→{tc.fmt(n_)}" for o, n_ in zip(s[ok].unique()[:3], info["values"][ok].unique()[:3])]
            actions.append([c, f"{tc.KIND_JA[info['kind']]}に変換", int(ok.sum()), tc.examples(ex, width=40)])
        if info["fail"].sum():
            review.append([c, f"{tc.KIND_JA[info['kind']]}として読めず欠損にした値", int(info["fail"].sum()),
                           tc.examples(s[info["fail"]].unique(), k=5)])
        notes += [f"`{c}`: {t}" for t in info["notes"]]
        df[c] = info["values"]
        rows.append([c, tc.KIND_JA[info["kind"]], int(nn.sum()), int(info["fail"].sum()), tc.examples(info["values"].dropna().unique())])
    notes.append("種類の判定が違う列は `--kind 列=種類` を付けてこの段階をやり直す。")
    tables = [("列の種類", ["列", "種類", "値のあるセル", "読めなかったセル", "変換後の例"], rows)]
    return df, kinds, {"actions": actions, "review": review, "notes": notes, "tables": tables}
