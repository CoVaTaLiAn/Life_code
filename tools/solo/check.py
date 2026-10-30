"""台帳の点検：日付・金額の形式、重複、消費税の計算違い、証憑や勘定科目の抜けを探す。"""

from __future__ import annotations

from collections import Counter

from . import dates
from .expense import ACCOUNTS
from .pipeline import STAGES
from .store import SCHEMAS, Store, yen


def _date_ok(s: str) -> bool:
    try:
        dates.parse(s)
        return True
    except (ValueError, TypeError):
        return False


def _int_ok(s: str) -> bool:
    try:
        yen(s)
        return True
    except ValueError:
        return False


def run(store: Store) -> list[tuple[str, str, str]]:
    """(重要度, 台帳, 内容) のリスト。重要度は 'エラー' か '注意'。"""
    out: list[tuple[str, str, str]] = []

    for name in ("sales", "expenses", "pipeline", "contracts", "recurring"):
        p = store.path(name)
        if not p.exists():
            out.append(("注意", name, f"{p.relative_to(store.root)} がありません"))
            continue
        header = p.read_text(encoding="utf-8-sig").splitlines()[:1]
        cols = header[0].split(",") if header else []
        missing = [c for c in SCHEMAS[name] if c not in cols]
        if missing:
            out.append(("エラー", name, f"列が足りません：{missing}"))

    sales = store.read("sales")
    for i, r in enumerate(sales, 2):
        tag = f"{i}行目 {r.get('請求番号')}"
        for c in ("請求日", "入金予定日", "入金日"):
            if r.get(c) and not _date_ok(r[c]):
                out.append(("エラー", "sales", f"{tag}：{c} が日付になっていません（{r[c]}）"))
        if not all(_int_ok(r.get(c, "")) for c in ("税抜金額", "消費税", "税込金額")):
            out.append(("エラー", "sales", f"{tag}：金額が数字ではありません"))
        elif yen(r["税抜金額"]) + yen(r["消費税"]) != yen(r["税込金額"]):
            out.append(("エラー", "sales", f"{tag}：税抜＋消費税が税込と合いません"))
    for num, n in Counter(r["請求番号"] for r in sales if r.get("請求番号")).items():
        if n > 1:
            out.append(("エラー", "sales", f"請求番号 {num} が{n}回あります"))

    exps = store.read("expenses")
    seen = Counter((r["日付"], r["支払先"], r["税込金額"]) for r in exps)
    for k, n in seen.items():
        if n > 1:
            out.append(("注意", "expenses", f"同じ日付・支払先・金額が{n}件：{k[0]} {k[1]} {k[2]}円（二重記帳かも）"))
    for i, r in enumerate(exps, 2):
        tag = f"{i}行目 {r.get('日付')} {r.get('支払先')}"
        if not _date_ok(r.get("日付", "")):
            out.append(("エラー", "expenses", f"{tag}：日付が読めません"))
        if not _int_ok(r.get("税込金額", "")):
            out.append(("エラー", "expenses", f"{tag}：金額が数字ではありません"))
        acc = r.get("勘定科目", "")
        if acc in ("", "要確認"):
            out.append(("注意", "expenses", f"{tag}：勘定科目が未確定"))
        elif acc not in ACCOUNTS:
            out.append(("注意", "expenses", f"{tag}：見慣れない勘定科目「{acc}」"))
        if r.get("証憑") in ("", "証憑なし"):
            out.append(("注意", "expenses", f"{tag}：証憑（領収書など）がありません"))
        if _int_ok(r.get("税込金額", "")) and yen(r["税込金額"]) >= 100_000 and acc in ("消耗品費", "工具器具備品"):
            out.append(("注意", "expenses", f"{tag}：10万円以上の物品は資産計上（減価償却）の対象かも。税理士に確認"))

    for i, r in enumerate(store.read("pipeline"), 2):
        if r.get("段階") not in STAGES:
            out.append(("エラー", "pipeline", f"{i}行目 {r.get('案件名')}：段階「{r.get('段階')}」は {STAGES} のどれか"))
        if r.get("次の行動日") and not _date_ok(r["次の行動日"]):
            out.append(("エラー", "pipeline", f"{i}行目 {r.get('案件名')}：次の行動日が日付ではありません"))

    for i, r in enumerate(store.read("recurring"), 2):
        if r.get("頻度") not in ("monthly", "yearly"):
            out.append(("エラー", "recurring", f"{i}行目 {r.get('名前')}：頻度は monthly か yearly"))
        if r.get("頻度") == "yearly" and not (r.get("支払月") or "").isdigit():
            out.append(("エラー", "recurring", f"{i}行目 {r.get('名前')}：年払いは支払月が必要"))

    if not store.cfg("company.founded"):
        out.append(("注意", "config", "company.founded（設立日）が未設定"))
    reg = store.cfg("invoice.registration_number", "")
    if reg and not (reg.startswith("T") and len(reg) == 14 and reg[1:].isdigit()):
        out.append(("エラー", "config", f"インボイス登録番号の形が違います（T＋13桁）：{reg}"))
    return out
