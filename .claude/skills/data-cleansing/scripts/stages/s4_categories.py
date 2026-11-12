"""段階4 カテゴリの統一: カテゴリ列の表記ゆれを1つの書き方にまとめる。"""
import difflib
import json

import tabprep_common as tc

NAME, TITLE = "categories", "カテゴリの統一"
ROLE = "カテゴリ列で、大文字小文字・空白・記号だけが違う書き方を最多の書き方に統一する。似ているだけの値は統一せず確認に回す"
NEXT = "段階5（欠損の整理）"


def add_args(ap):
    ap.add_argument("--map", default="", help="[段階4] 手で統一する（例: 性別:M=男性;性別:F=女性）")
    ap.add_argument("--category-map", help="[段階4] 別のデータで作った category_map.json を先に適用する")
    ap.add_argument("--no-auto-merge", action="store_true", help="[段階4] 自動の統一をしない（報告のみ）")


def run(df, schema, a):
    actions, review, rows, full_map = [], [], [], {}
    manual = {}
    if a.category_map:
        manual = json.load(open(a.category_map, encoding="utf-8"))
    for part in a.map.split(";"):
        if ":" in part and "=" in part:
            col, kv = part.split(":", 1)
            old, new = kv.split("=", 1)
            manual.setdefault(col.strip(), {})[old.strip()] = new.strip()
    for c in df.columns:
        if schema.get(c) != "category":
            continue
        before = df[c].nunique()
        m = dict(manual.get(c, {}))
        if m:
            hit = df[c].isin(list(m))
            if hit.sum():
                actions.append([c, "指定どおりに統一", int(hit.sum()), tc.examples([f"{k}→{v}" for k, v in m.items()], width=40)])
            df[c] = df[c].replace(m)
        for canon, g in tc.variant_groups(df[c]):
            others = {k: v for k, v in g.items() if k != canon}
            if a.no_auto_merge:
                review.append([c, "表記ゆれ（自動統一なしの指定）", sum(others.values()), " = ".join(g)])
                continue
            actions.append([c, f"表記ゆれを `{canon}` に統一", sum(others.values()),
                            tc.examples([f"{k}({v}件)" for k, v in others.items()], k=4, width=30)])
            m.update({k: canon for k in others})
            df[c] = df[c].replace({k: canon for k in others})
        vc = df[c].dropna().astype(str).value_counts()
        if 2 <= len(vc) <= 300:
            keys = {v: tc.variant_key(v) for v in vc.index}
            vals = list(vc.index)
            for i, x in enumerate(vals):
                for y in vals[i + 1:]:
                    kx, ky = sorted((keys[x], keys[y]), key=len)
                    if kx and (ky.startswith(kx) or (len(kx) >= 3 and difflib.SequenceMatcher(None, kx, ky).ratio() >= .8)):
                        review.append([c, "似ている値（同じものなら --map で統一）", int(vc[y]), f"{x}({vc[x]}件) と {y}({vc[y]}件)"])
        if m:
            full_map[c] = m
        rare = int((vc / max(vc.sum(), 1) < .01).sum())
        rows.append([c, before, df[c].nunique(), rare, tc.examples(vc.index[:4])])
    notes = ["統一の対応表は `category_map.json` に保存した。テスト用データには `--category-map` で同じ対応を適用する。",
             "件数の少ない値をまとめる処理（「その他」化）はここではしない。エンコーディングで扱う。"]
    tables = [("カテゴリ列の種類数", ["列", "統一前の種類数", "統一後の種類数", "1% 未満の値の数", "多い値"], rows)]
    return df, schema, {"actions": actions, "review": review, "notes": notes, "tables": tables,
                        "files": {"category_map.json": full_map}}
