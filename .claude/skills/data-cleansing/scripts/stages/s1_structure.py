"""段階1 構造: 表の形を整える（列名・空の行と列・重複）。セルの値そのものは書き換えない。"""
import re

import numpy as np
import pandas as pd
import tabprep_common as tc

NAME, TITLE = "structure", "構造を整える"
ROLE = "列名を整え、空の行・列、重複した行・列、紛れ込んだ見出し行を取り除く。セルの値は書き換えない"
NEXT = "段階2（文字の正規化）"


def add_args(ap):
    ap.add_argument("--drop-constant", action="store_true", help="[段階1] 値が1種類しかない列を削除する（既定は報告のみ）")
    ap.add_argument("--keep-duplicates", action="store_true", help="[段階1] 完全に重複した行を残す")


def run(df, schema, a):
    actions, review, notes = [], [], []
    # 列名
    new, seen = [], {}
    for i, c in enumerate(df.columns):
        t = re.sub(r"\s+", "_", tc.norm_text(c))
        if not t or t.startswith("Unnamed:"):
            t = f"col_{i + 1}"
        seen[t] = seen.get(t, 0) + 1
        new.append(t if seen[t] == 1 else f"{t}_{seen[t]}")
    renamed = [(o, n_) for o, n_ in zip(df.columns, new) if o != n_]
    if renamed:
        actions.append(["（列名）", "列名を正規化（全角→半角、空白→_、空の名前に仮の名前）", len(renamed),
                        tc.examples([f"{o!r}→{n_}" for o, n_ in renamed], width=40)])
    old_names = [str(c) for c in df.columns]
    df.columns = new
    # 空白だけのセル → 欠損
    blank = df.apply(lambda s: s.notna() & s.astype(str).str.strip().eq(""))
    if blank.values.sum():
        actions.append(["（全体）", "空白だけのセルを欠損にした", int(blank.values.sum()), ""])
        df = df.mask(blank, np.nan)
    # 見出し行の紛れ込み
    hdr = (df.astype(str).values == np.array(old_names)).all(axis=1)
    if hdr.sum():
        actions.append(["（行）", "データの途中に入った見出し行を削除", int(hdr.sum()), ""])
        df = df[~hdr]
    # 空の行・列
    empty_rows = df.isna().all(axis=1)
    if empty_rows.sum():
        actions.append(["（行）", "すべて空の行を削除", int(empty_rows.sum()), ""])
        df = df[~empty_rows]
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        actions.append(["（列）", "すべて空の列を削除", len(empty_cols), tc.examples(empty_cols)])
        df = df.drop(columns=empty_cols)
    # 重複
    dup = df.duplicated()
    if dup.sum():
        if a.keep_duplicates:
            review.append(["（行）", "完全に重複した行（--keep-duplicates で残した）", int(dup.sum()), ""])
        else:
            actions.append(["（行）", "完全に重複した行を削除（最初の1行を残す）", int(dup.sum()),
                            f"例: 元の {int(dup.idxmax()) + 2} 行目"])
            df = df[~dup]
    dup_cols, cols = [], list(df.columns)
    for i, c in enumerate(cols):
        for p in cols[:i]:
            if p not in dup_cols and df[c].equals(df[p]):
                dup_cols.append(c)
                actions.append([c, f"`{p}` と中身が同じ列を削除", 1, ""])
                break
    df = df.drop(columns=dup_cols)
    # 定数列・合計行
    const = [c for c in df.columns if df[c].nunique(dropna=False) == 1]
    if const and a.drop_constant:
        actions.append(["（列）", "値が1種類しかない列を削除", len(const), tc.examples(const)])
        df = df.drop(columns=const)
    elif const:
        review.append(["（列）", "値が1種類しかない列（情報がない。--drop-constant で削除）", len(const), tc.examples(const)])
    if len(df.columns):
        total = df[df.columns[0]].astype(str).str.strip().str.casefold().isin({"合計", "総計", "計", "total", "小計"})
        if total.sum():
            review.append([df.columns[0], "合計行らしい行（集計値がデータに混ざっていないか確認）", int(total.sum()), ""])
    notes.append("pandas は同名の列を読み込み時に `名前.1` のように変える。元ファイルに同名の列がないか列名を確認する。")
    return df.reset_index(drop=True), schema, {"actions": actions, "review": review, "notes": notes, "tables": []}
