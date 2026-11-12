"""表データ前処理の共通部品（読み書き・型の判定・レポート出力）。

プロファイリング / クレンジング / エンコーディングの各スクリプトから使う。
ここには「判断」や「変換の実行手順」は置かない。それぞれの役割のスクリプトに置く。

必要: pandas numpy
"""
import csv
import datetime as dt
import html
import io
import json
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

KINDS = ("numeric", "bool", "datetime", "category", "text", "id")
KIND_JA = {"numeric": "数値", "bool": "真偽(0/1)", "datetime": "日時", "category": "カテゴリ",
           "text": "文章", "id": "ID"}
NULL_TOKENS = {"na", "n/a", "nan", "null", "none", "nil", "-", "--", "―", "—", "?", "#n/a",
               "#null!", "#value!", "#div/0!", "missing", "(blank)", "undefined"}
PLACEHOLDERS = {"不明", "unknown", "未回答", "無回答", "未入力", "未設定", "該当なし", "わからない"}
BOOL_MAP = {"true": 1, "false": 0, "yes": 1, "no": 0, "y": 1, "n": 0, "t": 1, "f": 0,
            "はい": 1, "いいえ": 0, "有": 1, "無": 0, "あり": 1, "なし": 0, "○": 1, "×": 0,
            "on": 1, "off": 0}
SENTINELS = (-1, -9, -99, -999, -9999, 99, 999, 9999, 99999)
NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
DATE_LIKE = re.compile(r"^(\d{4}[-/年]\d{1,2}([-/月]\d{1,2}日?)?([ T]\d{1,2}:\d{2}.*)?"
                       r"|\d{4}\.\d{1,2}\.\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4}( \d{1,2}:\d{2}.*)?)$")
ID_NAME = re.compile(r"(^|[_\s])id$|^id([_\s]|$)|番号|コード$|^uuid$|^no\.?$", re.I)
CTRL_RE = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f​﻿]")


# ---------------------------------------------------------------- 文字列の正規化
def nfkc(v):
    return unicodedata.normalize("NFKC", str(v))


def norm_text(v):
    """全角英数字→半角、制御文字の除去、前後の空白の除去、連続する空白を1つに。"""
    t = CTRL_RE.sub("", nfkc(v))
    return re.sub(r"\s+", " ", t).strip()


def is_null_token(v, tokens=NULL_TOKENS):
    return str(v).casefold() in tokens


def map_unique(s, f):
    """ユニークな値だけに f を適用して全体に写す（速い）。欠損は欠損のまま。"""
    d = {x: f(x) for x in pd.unique(s.dropna())}
    return s.map(d)


def variant_key(v):
    """表記ゆれ判定用のキー（大文字小文字・全角半角・空白・記号の違いを無視）。"""
    return re.sub(r"[\s\-_・.,/()]", "", nfkc(v).casefold())


def variant_groups(s):
    """同じキーに複数の書き方がある値の組を返す: [(代表, {書き方: 件数})]。代表は最多の書き方。"""
    vc = s.dropna().astype(str).value_counts()
    groups = {}
    for val, cnt in vc.items():
        groups.setdefault(variant_key(val), {})[val] = int(cnt)
    return [(max(g, key=g.get), g) for g in groups.values() if len(g) > 1]


# ---------------------------------------------------------------- 型の変換と判定
def to_number(v):
    t = nfkc(v).strip().replace("−", "-")
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    if t[:1] in ("▲", "△"):
        neg, t = True, t[1:]
    t = re.sub(r"[,\s¥$€£円%]", "", t)
    if not NUM_RE.match(t):
        return np.nan
    x = float(t)
    return -x if neg else x


def parse_datetime(s):
    u = pd.unique(s.dropna())
    if len(u) == 0:
        return pd.to_datetime(s, errors="coerce")
    pre = [re.sub(r"日", "", re.sub(r"[年月]", "-", nfkc(x))).strip() for x in u]
    try:
        parsed = pd.to_datetime(pd.Series(pre), errors="coerce", format="mixed")
    except Exception:
        parsed = pd.to_datetime(pd.Series(pre), errors="coerce", format="mixed", utc=True).dt.tz_localize(None)
    return pd.to_datetime(s.map(dict(zip(u, parsed))), errors="coerce")


def convert_kind(s, kind):
    """列を指定の種類に変換する。戻り値: (変換後, 変換できなかったセルの真偽列)"""
    if kind == "numeric":
        vals = map_unique(s, to_number).astype(float)
    elif kind == "bool":
        m = dict(BOOL_MAP, **{"1": 1, "0": 0, "1.0": 1, "0.0": 0})
        vals = map_unique(s, lambda x: m.get(str(x).casefold(), np.nan)).astype(float)
    elif kind == "datetime":
        vals = parse_datetime(s)
    else:
        return s, pd.Series(False, index=s.index)
    return vals, s.notna() & vals.isna()


def infer_kind(s, name=""):
    """文字列の列（欠損表記は欠損にしてある前提）の種類を判定する。
    戻り値: {kind, values, fail(変換できなかったセル), notes}"""
    v = s.dropna()
    res = {"kind": "category", "values": s, "fail": pd.Series(False, index=s.index), "notes": []}
    n = len(v)
    if n == 0:
        res["notes"].append("値が1つもない")
        return res
    low = set(pd.Series(pd.unique(v)).astype(str).str.casefold())
    if low <= set(BOOL_MAP):
        res["values"], res["fail"] = convert_kind(s, "bool")
        res["kind"] = "bool"
        return res
    if map_unique(v, lambda x: bool(DATE_LIKE.match(nfkc(x).strip()))).mean() >= .9:
        vals, fail = convert_kind(s, "datetime")
        if fail.sum() / n <= .1:
            res.update(kind="datetime", values=vals, fail=fail)
            return res
    vals, fail = convert_kind(s, "numeric")
    if 1 - fail.sum() / n >= .9:
        if v.astype(str).str.match(r"^0\d+$").mean() >= .3:
            res["notes"].append("先頭が 0 の数字（郵便番号・コードなど）なので数値にしない")
        else:
            x = vals.dropna()
            is_int = bool((x == x.round()).all())
            seq = is_int and x.nunique() == len(x) >= 20 and (
                bool(ID_NAME.search(name)) or bool((np.diff(np.sort(x.values)) == 1).all()))
            if seq:
                res["kind"] = "id"
                res["notes"].append("全行で値が異なる連番・番号")
                return res
            res.update(kind="numeric", values=vals, fail=fail)
            if v.astype(str).str.contains("%|％").mean() > .5:
                res["notes"].append("% 表記（% を外した数値にする。100 で割ってはいない）")
            return res
    nu = v.nunique()
    ur = nu / n
    avg_len = v.astype(str).str.len().mean()
    if (ID_NAME.search(name) and ur > .9) or (ur == 1 and n >= 20 and avg_len <= 40):
        res["kind"] = "id"
        res["notes"].append("全行でほぼ値が異なる")
    elif avg_len >= 30 or (ur > .5 and nu > 30):
        res["kind"] = "text"
    return res


def iqr_fences(x, k=3.0):
    """外れ値の境界（四分位範囲の k 倍）。四分位範囲が 0 のときは None。"""
    x = x.dropna()
    if len(x) < 8:
        return None
    q1, q3 = x.quantile(.25), x.quantile(.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    return float(q1 - k * iqr), float(q3 + k * iqr)


def sentinel_candidates(x):
    """欠損コードらしい値（999, -1 など。列の端にあり、他の値から離れて複数回出る）。"""
    x = x.dropna()
    out = []
    if x.nunique() < 5:
        return out
    for v in SENTINELS:
        cnt = int((x == v).sum())
        if cnt < 2:
            continue
        rest = x[x != v]
        if len(rest) < 5:
            continue
        spread = max(rest.quantile(.75) - rest.quantile(.25), rest.std(), 1e-9)
        if (v > rest.max() and v - rest.max() > 2 * spread) or (v < rest.min() and rest.min() - v > 2 * spread) \
                or (v < 0 <= rest.min()):
            out.append((v, cnt))
    return out


# ---------------------------------------------------------------- 読み書き
def read_raw(path):
    """CSV / TSV / Excel をすべて文字列として読む（空のセルだけ欠損にする）。戻り値: (df, 情報)"""
    p = Path(path)
    if p.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(p, dtype=str, keep_default_na=False)
        info = {"encoding": "excel", "sep": ""}
    else:
        raw = p.read_bytes()
        for enc in ("utf-8-sig", "cp932", "euc_jp", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeError:
                continue
        head = text[:20000]
        try:
            sep = csv.Sniffer().sniff(head, delimiters=",\t;|").delimiter
        except csv.Error:
            first = head.split("\n", 1)[0]
            sep = max(",\t;|", key=first.count)
        df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, na_values=[])
        info = {"encoding": enc, "sep": {"\t": "タブ"}.get(sep, sep)}
    df = df.astype(object)
    df = df.mask(df == "", np.nan)
    return df, info


def schema_path(path):
    return Path(path).with_suffix(".schema.json")


def load_table(path):
    """CSV を読む。隣に <名前>.schema.json があれば列の種類を適用する。戻り値: (df, schema or None, 情報)"""
    df, info = read_raw(path)
    sp = schema_path(path)
    if not sp.exists():
        return df, None, info
    schema = json.loads(sp.read_text(encoding="utf-8"))["columns"]
    for c, k in schema.items():
        if c in df.columns and k in ("numeric", "bool", "datetime"):
            df[c] = convert_kind(df[c], k)[0]
    return df, schema, info


def write_table(df, path, schema=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    if schema is not None:
        schema_path(path).write_text(
            json.dumps({"columns": schema}, ensure_ascii=False, indent=1), encoding="utf-8")


def jdump(obj, path):
    def default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if np.isnan(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (pd.Timestamp, dt.datetime, dt.date)):
            return o.isoformat()
        if isinstance(o, (set, tuple)):
            return list(o)
        return str(o)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=default), encoding="utf-8")


def parse_kv(text, sep=","):
    """"a=1,b=2" → {"a": "1", "b": "2"}"""
    out = {}
    for part in (text or "").split(sep):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ---------------------------------------------------------------- 表示
def fmt(v, nd=3):
    if v is None:
        return "-"
    if isinstance(v, (bool, np.bool_)):
        return "はい" if v else "いいえ"
    if isinstance(v, (float, np.floating)):
        if np.isnan(v):
            return "-"
        if float(v).is_integer() and abs(v) < 1e15:
            return f"{int(v):,}"
        a = abs(v)
        if a >= 1e6 or a < 1e-3:
            return f"{v:.2e}"
        return f"{v:,.{nd}f}".rstrip("0").rstrip(".")
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d %H:%M") if (v.hour or v.minute) else v.strftime("%Y-%m-%d")
    return str(v)


def pct(x, nd=1):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100 * x:.{nd}f}%"


def examples(values, k=3, width=24):
    out = []
    for v in list(values)[:k]:
        t = fmt(v)
        out.append(t if len(t) <= width else t[:width - 1] + "…")
    return " / ".join(out)


def spark(x, bins=10):
    """数値の分布を1行の棒で表す。"""
    x = pd.Series(x).dropna()
    if len(x) == 0 or x.min() == x.max():
        return ""
    h, _ = np.histogram(x, bins=bins)
    chars = "▁▂▃▄▅▆▇█"
    return "".join(chars[int(round((len(chars) - 1) * c / h.max()))] for c in h)


CSS = """
:root{--bg:#fff;--fg:#1c1c1e;--sub:#5b6068;--line:#d9dce1;--head:#f3f4f6;--acc:#1f5fbf}
@media(prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e8e9eb;--sub:#a0a5ad;--line:#33373e;--head:#22252b;--acc:#7fb0ff}}
body{background:var(--bg);color:var(--fg);font-family:-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;
line-height:1.7;margin:0 auto;padding:16px;max-width:1080px}
h1{font-size:1.4rem;margin:.2em 0}h2{font-size:1.15rem;border-bottom:2px solid var(--line);padding-bottom:4px;margin-top:2em}
h3{font-size:1rem;margin-top:1.4em}.meta{color:var(--sub);font-size:.9rem}
.tw{overflow-x:auto}table{border-collapse:collapse;font-size:.85rem;margin:.5em 0}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top;white-space:nowrap}
td.w{white-space:normal;min-width:14em}th{background:var(--head)}
code{background:var(--head);padding:1px 4px;border-radius:3px;font-size:.9em}
pre{background:var(--head);padding:10px;overflow-x:auto;font-size:.85rem}strong{color:var(--acc)}
"""


class Report:
    """1つの処理につき1つ作るレポート。report.md と report.html（単体で開ける）を書き出す。"""

    def __init__(self, title, role, meta=None):
        self.title, self.role, self.meta, self.blocks = title, role, dict(meta or {}), []
        self.meta.setdefault("作成日時", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))

    def h(self, text, level=2):
        self.blocks.append(("h", level, text))

    def p(self, text):
        self.blocks.append(("p", text))

    def ul(self, items):
        if items:
            self.blocks.append(("ul", [str(i) for i in items]))

    def code(self, text):
        self.blocks.append(("code", text))

    def table(self, headers, rows, empty="該当なし"):
        if not rows:
            self.p(empty)
        else:
            self.blocks.append(("table", list(headers), [[fmt(c) for c in r] for r in rows]))

    @staticmethod
    def _cell(c):
        return c.replace("|", "／").replace("\n", " ")

    def to_md(self):
        out = [f"# {self.title}", "", f"**役割**: {self.role}", ""]
        out += [f"- {k}: {v}" for k, v in self.meta.items()] + [""]
        for b in self.blocks:
            if b[0] == "h":
                out += ["#" * b[1] + " " + b[2], ""]
            elif b[0] == "p":
                out += [b[1], ""]
            elif b[0] == "ul":
                out += [f"- {i}" for i in b[1]] + [""]
            elif b[0] == "code":
                out += ["```", b[1], "```", ""]
            else:
                out.append("| " + " | ".join(map(self._cell, b[1])) + " |")
                out.append("|" + "---|" * len(b[1]))
                out += ["| " + " | ".join(map(self._cell, r)) + " |" for r in b[2]] + [""]
        return "\n".join(out)

    @staticmethod
    def _inline(t):
        t = html.escape(str(t))
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)

    def to_html(self):
        e = self._inline
        out = [f"<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
               f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
               f"<title>{html.escape(self.title)}</title><style>{CSS}</style></head><body>",
               f"<h1>{e(self.title)}</h1><p><strong>役割</strong>: {e(self.role)}</p><p class='meta'>",
               "<br>".join(f"{e(k)}: {e(v)}" for k, v in self.meta.items()), "</p>"]
        for b in self.blocks:
            if b[0] == "h":
                out.append(f"<h{b[1]}>{e(b[2])}</h{b[1]}>")
            elif b[0] == "p":
                out.append(f"<p>{e(b[1])}</p>")
            elif b[0] == "ul":
                out.append("<ul>" + "".join(f"<li>{e(i)}</li>" for i in b[1]) + "</ul>")
            elif b[0] == "code":
                out.append(f"<pre>{html.escape(b[1])}</pre>")
            else:
                out.append("<div class='tw'><table><tr>" + "".join(f"<th>{e(c)}</th>" for c in b[1]) + "</tr>")
                for r in b[2]:
                    out.append("<tr>" + "".join(
                        f"<td{' class=w' if len(c) > 40 else ''}>{e(c)}</td>" for c in r) + "</tr>")
                out.append("</table></div>")
        out.append("</body></html>")
        return "\n".join(out)

    def save(self, outdir, name="report"):
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{name}.md").write_text(self.to_md(), encoding="utf-8")
        (outdir / f"{name}.html").write_text(self.to_html(), encoding="utf-8")
        return outdir / f"{name}.html"
