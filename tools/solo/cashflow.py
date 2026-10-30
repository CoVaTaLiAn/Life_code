"""資金繰り表：手元資金と、今後の入金予定・固定費の支払予定から月末残高の見通しを出す。

考え方
- 基準日（config の cash.as_of）の残高から出発する
- 基準日より後・今日までの実績（入金済みの売上、記帳した経費）を反映する
- 今日より後は、未入金の売上（入金予定日）と固定費（recurring.csv）で見込む
- 期限を過ぎた未入金は「今月入る」とみなし、別に表示する
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field

from . import dates
from .store import Store, yen


@dataclass
class Month:
    ym: str
    actual_in: int = 0
    actual_out: int = 0
    expected_in: int = 0
    expected_out: int = 0
    overdue_in: int = 0
    end_balance: int = 0
    notes: list[str] = field(default_factory=list)


def recurring_on(store: Store, start: dt.date, end: dt.date) -> list[tuple[dt.date, str, int]]:
    """start〜end（両端含む）に発生する固定費の支払。"""
    out = []
    for r in store.read("recurring"):
        amount = yen(r["金額"])
        if amount <= 0:
            continue
        rs = dates.parse(r["開始"]) if r.get("開始") else dt.date.min
        re_ = dates.parse(r["終了"]) if r.get("終了") else dt.date.max
        day = int(r.get("支払日") or 1)
        m = dt.date(start.year, start.month, 1)
        while m <= end:
            if r["頻度"] == "monthly" or (r["頻度"] == "yearly" and int(r.get("支払月") or 0) == m.month):
                d = m.replace(day=min(day, calendar.monthrange(m.year, m.month)[1]))
                if start <= d <= end and rs <= d <= re_:
                    out.append((d, r["名前"], amount))
            m = dates.add_months(m, 1)
    return out


def monthly_fixed(store: Store) -> int:
    """1か月あたりの固定費（年払いは12で割る）。"""
    total = 0
    for r in store.read("recurring"):
        a = yen(r["金額"])
        total += a if r["頻度"] == "monthly" else a // 12
    return total


def forecast(store: Store, months: int = 3, today: dt.date | None = None) -> list[Month]:
    today = today or dt.date.today()
    as_of = dates.parse(store.cfg("cash.as_of", today.isoformat()))
    balance = yen(store.cfg("cash.balance", 0))

    first = dt.date(min(as_of, today).year, min(as_of, today).month, 1)
    last_m = dates.add_months(dt.date(today.year, today.month, 1), months - 1)
    last = dates.month_end(last_m.year, last_m.month)

    table: dict[str, Month] = {}
    m = first
    while m <= last:
        table[dates.ym(m)] = Month(dates.ym(m))
        m = dates.add_months(m, 1)

    # 実績（基準日の翌日〜今日）
    for r in store.read("sales"):
        if r.get("入金日"):
            d = dates.parse(r["入金日"])
            if as_of < d <= today and dates.ym(d) in table:
                table[dates.ym(d)].actual_in += yen(r["税込金額"])
    for r in store.read("expenses"):
        d = dates.parse(r["日付"])
        if as_of < d <= today and dates.ym(d) in table:
            table[dates.ym(d)].actual_out += yen(r["税込金額"])

    # 見込み（明日以降）
    cur = dates.ym(today)
    for r in store.read("sales"):
        if r.get("入金日") or not r.get("入金予定日"):
            continue
        d = dates.parse(r["入金予定日"])
        amt = yen(r["税込金額"])
        if d <= today:
            table[cur].overdue_in += amt
            table[cur].notes.append(f"未入金（期限超過）：{r['取引先']} {amt:,}円")
        elif dates.ym(d) in table:
            table[dates.ym(d)].expected_in += amt
    tomorrow = max(today, as_of) + dt.timedelta(days=1)
    for d, name, amt in recurring_on(store, tomorrow, last):
        table[dates.ym(d)].expected_out += amt

    for mo in table.values():
        balance += mo.actual_in - mo.actual_out + mo.expected_in + mo.overdue_in - mo.expected_out
        mo.end_balance = balance
    return [mo for k, mo in table.items() if k >= dates.ym(dates.add_months(today, -1))]


def to_markdown(store: Store, rows: list[Month]) -> str:
    fixed = monthly_fixed(store)
    warn = int(store.cfg("cash.warn_months", 6))
    lines = [
        f"固定費の目安：月 {fixed:,}円（{warn}か月分 = {fixed * warn:,}円を下回ると注意）", "",
        "| 月 | 入金（実績） | 支払（実績） | 入金（予定） | 未入金の回収見込み | 固定費（予定） | 月末残高 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for m in rows:
        flag = " ⚠" if fixed and m.end_balance < fixed * warn else ""
        lines.append(f"| {m.ym} | {m.actual_in:,} | {m.actual_out:,} | {m.expected_in:,} | {m.overdue_in:,} | "
                     f"{m.expected_out:,} | **{m.end_balance:,}**{flag} |")
    notes = [n for m in rows for n in m.notes]
    if notes:
        lines += ["", *[f"- {n}" for n in notes]]
    if fixed:
        lines += ["", f"手元資金は固定費の約 {rows[-1].end_balance / fixed:.1f} か月分（{rows[-1].ym}末時点）"]
    lines += ["", "※ 税金（法人税・消費税）や不定期の支払は含まない。概算。"]
    return "\n".join(lines) + "\n"
