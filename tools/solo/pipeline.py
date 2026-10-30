"""案件（営業パイプライン）の集計。"""

from __future__ import annotations

import datetime as dt

from . import dates
from .store import Store, yen

STAGES = ["見込", "接触", "商談", "提案", "受注", "失注"]
OPEN = {"見込", "接触", "商談", "提案"}


def summary(store: Store) -> list[dict]:
    rows = store.read("pipeline")
    out = []
    for st in STAGES:
        items = [r for r in rows if r.get("段階") == st]
        amount = sum(yen(r["見込金額"]) for r in items)
        weighted = sum(yen(r["見込金額"]) * yen(r.get("受注確度(%)") or 0) // 100 for r in items)
        out.append({"段階": st, "件数": len(items), "見込金額": amount, "加重金額": weighted})
    return out


def overdue(store: Store, today: dt.date | None = None) -> list[dict]:
    """次の行動日が過ぎた（または空の）進行中の案件。"""
    today = today or dt.date.today()
    out = []
    for r in store.read("pipeline"):
        if r.get("段階") not in OPEN:
            continue
        nd = r.get("次の行動日")
        if not nd or dates.parse(nd) < today:
            r = dict(r)
            r["遅れ日数"] = (today - dates.parse(nd)).days if nd else None
            out.append(r)
    return sorted(out, key=lambda r: r.get("次の行動日") or "")


def upsert(store: Store, name: str, **fields) -> dict:
    rows = store.read("pipeline")
    for r in rows:
        if r["案件名"] == name:
            r.update({k: str(v) for k, v in fields.items() if v is not None})
            r["最終更新"] = dt.date.today().isoformat()
            store.write("pipeline", rows)
            return r
    st = fields.get("段階") or "見込"
    if st not in STAGES:
        raise ValueError(f"段階は {STAGES} のどれかです")
    r = {"案件名": name, "段階": st, "最終更新": dt.date.today().isoformat()}
    r.update({k: str(v) for k, v in fields.items() if v is not None})
    rows.append(r)
    store.write("pipeline", rows)
    return r
