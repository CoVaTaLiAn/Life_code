"""契約の管理：解約予告期限・終了日が近い契約を拾う。"""

from __future__ import annotations

import datetime as dt

from . import dates
from .store import Store


def upcoming(store: Store, today: dt.date | None = None, days: int = 45) -> list[dict]:
    today = today or dt.date.today()
    limit = today + dt.timedelta(days=days)
    out = []
    for r in store.read("contracts"):
        for col in ("解約予告期限", "終了日"):
            try:
                d = dates.parse(r.get(col) or "")
            except ValueError:
                continue  # 「終了の1か月前」のような文章は日付として読まない
            if today <= d <= limit:
                out.append(r)
                break
    return sorted(out, key=lambda r: r.get("解約予告期限") or r.get("終了日") or "")
