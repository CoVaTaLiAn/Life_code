"""段階2 文字の正規化: セルの文字の書き方を揃える（意味は変えない）。欠損を表す文字を欠損にする。"""
import numpy as np
import tabprep_common as tc

NAME, TITLE = "text", "文字の正規化"
ROLE = "全角英数字→半角、前後や連続した空白・制御文字の除去、欠損を表す文字（NA, - など）を欠損に統一する。値の意味は変えない"
NEXT = "段階3（型の変換）"


def add_args(ap):
    ap.add_argument("--null-extra", default="", help="[段階2] 欠損として扱う文字を追加（カンマ区切り。例: 不明,未回答）")
    ap.add_argument("--null-keep", default="", help="[段階2] 欠損にしない文字（カンマ区切り。例: none,-）")


def run(df, schema, a):
    tokens = set(tc.NULL_TOKENS) | {t.strip().casefold() for t in a.null_extra.split(",") if t.strip()}
    tokens -= {t.strip().casefold() for t in a.null_keep.split(",") if t.strip()}
    actions, rows = [], []
    for c in df.columns:
        s = df[c]
        normed = tc.map_unique(s, tc.norm_text)
        changed = s.notna() & (normed != s)
        tok = normed.notna() & tc.map_unique(normed, lambda v: v == "" or tc.is_null_token(v, tokens)).fillna(False).astype(bool)
        if changed.sum():
            actions.append([c, "空白・全角英数字・制御文字を正規化", int(changed.sum()),
                            tc.examples([f"{o!r}→{n_!r}" for o, n_ in zip(s[changed].unique()[:3], normed[changed].unique()[:3])], width=40)])
        if tok.sum():
            actions.append([c, "欠損を表す文字を欠損にした", int(tok.sum()), tc.examples(s[tok].unique())])
        df[c] = normed.mask(tok, np.nan)
        rows.append([c, int(changed.sum()), int(tok.sum()), int(df[c].isna().sum())])
    notes = ["欠損として扱った文字: " + "、".join(f"`{t}`" for t in sorted(tokens)),
             "半角カナは全角カナになる（Unicode の NFKC 正規化）。大文字と小文字の違いはここでは触らない（段階4）。"]
    tables = [("列ごとの件数", ["列", "正規化したセル", "欠損にしたセル", "処理後の欠損"], [r for r in rows if r[1] or r[2]])]
    return df, schema, {"actions": actions, "review": [], "notes": notes, "tables": tables}
