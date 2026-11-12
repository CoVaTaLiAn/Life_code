"""段階5 欠損の整理: 欠損の状況をまとめ、欠損コード（999 など）を指定に従って欠損にする。補完はしない。"""
import numpy as np
import tabprep_common as tc

NAME, TITLE = "missing", "欠損の整理"
ROLE = "欠損の状況を列ごとにまとめ、欠損コードの候補を挙げる。指定された欠損コードだけを欠損にし、すべて空の列・行を除く。値の補完はしない"
NEXT = "段階6（外れ値）"


def add_args(ap):
    ap.add_argument("--sentinel", default="", help="[段階5] 欠損コードを欠損にする（例: 年齢=999,年収=-1）")
    ap.add_argument("--null-category", default="", help="[段階5] カテゴリの値を欠損にする（例: 職業=不明）")
    ap.add_argument("--drop-col-missing", type=float, help="[段階5] 欠損率がこの値以上の列を削除（例: 0.9）")
    ap.add_argument("--drop-row-missing", type=float, help="[段階5] 欠損率がこの値以上の行を削除（例: 0.8）")


def run(df, schema, a):
    actions, review = [], []
    for c, v in tc.parse_kv(a.sentinel).items():
        if schema.get(c) != "numeric":
            raise SystemExit(f"--sentinel: {c} は数値列ではありません")
        hit = df[c] == float(v)
        actions.append([c, f"欠損コード {v} を欠損にした", int(hit.sum()), ""])
        df[c] = df[c].mask(hit, np.nan)
    for c, v in tc.parse_kv(a.null_category).items():
        hit = df[c] == v
        actions.append([c, f"`{v}` を欠損にした", int(hit.sum()), ""])
        df[c] = df[c].mask(hit, np.nan)
    for c in df.columns:
        if schema.get(c) == "numeric":
            for v, cnt in tc.sentinel_candidates(df[c]):
                review.append([c, f"欠損コードらしい値 {tc.fmt(float(v))}（欠損なら --sentinel {c}={tc.fmt(float(v)).replace(',', '')}）", cnt,
                               f"他の値の範囲 {tc.fmt(float(df[c][df[c] != v].min()))}〜{tc.fmt(float(df[c][df[c] != v].max()))}"])
        elif schema.get(c) == "category":
            ph = df[c][df[c].astype(str).str.casefold().isin(tc.PLACEHOLDERS)]
            if len(ph):
                review.append([c, f"「不明」などの値（欠損として扱うなら --null-category {c}={ph.iloc[0]}）", len(ph), tc.examples(ph.unique())])
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        actions.append(["（列）", "すべて欠損の列を削除", len(empty_cols), tc.examples(empty_cols)])
    rate = df.isna().mean()
    if a.drop_col_missing is not None:
        high = [c for c in df.columns if rate[c] >= a.drop_col_missing and c not in empty_cols]
        if high:
            actions.append(["（列）", f"欠損率 {tc.pct(a.drop_col_missing, 0)} 以上の列を削除", len(high), tc.examples(high)])
        empty_cols += high
    df = df.drop(columns=empty_cols)
    schema = {c: k for c, k in schema.items() if c in df.columns}
    row_rate = df.isna().mean(axis=1)
    drop_rows = row_rate >= (a.drop_row_missing if a.drop_row_missing is not None else 1.0)
    if drop_rows.sum():
        actions.append(["（行）", "欠損だらけの行を削除" if a.drop_row_missing is not None else "すべて欠損の行を削除", int(drop_rows.sum()), ""])
        df = df[~drop_rows].reset_index(drop=True)
    for c in df.columns:
        r = df[c].isna().mean()
        if r >= .5:
            review.append([c, "欠損が半分以上（使うか確認。削除するなら --drop-col-missing）", int(df[c].isna().sum()), tc.pct(r)])
    rows = [[c, tc.KIND_JA[schema[c]], int(df[c].isna().sum()), tc.pct(df[c].isna().mean()),
             "█" * round(20 * df[c].isna().mean())] for c in df.columns if df[c].isna().any()]
    rows.sort(key=lambda r: -r[2])
    n_complete = int((~df.isna().any(axis=1)).sum())
    notes = [f"欠損が1つもない行: {n_complete:,} / {len(df):,}（{tc.pct(n_complete / max(len(df), 1))}）",
             "値の補完（中央値など）はここではしない。補完の値は学習用データから決める必要があるため、エンコーディングで行う。"]
    tables = [("欠損のある列", ["列", "種類", "欠損数", "欠損率", ""], rows)]
    return df, schema, {"actions": actions, "review": review, "notes": notes, "tables": tables}
