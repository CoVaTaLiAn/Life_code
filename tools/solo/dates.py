"""日付の計算（月の加算、月末、日本の祝日、期限の繰り下げ）。"""

from __future__ import annotations

import calendar
import datetime as dt
from functools import lru_cache

Date = dt.date


def parse(s: str) -> Date:
    """'2026-11-01' や '2026/11/1' を日付にする。"""
    s = s.strip().replace("/", "-")
    y, m, d = (int(x) for x in s.split("-"))
    return dt.date(y, m, d)


def month_end(year: int, month: int) -> Date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def add_months(d: Date, months: int) -> Date:
    """月を足す。日が存在しない場合はその月の末日にする（1/31 + 1か月 = 2/28）。"""
    total = d.year * 12 + (d.month - 1) + months
    y, m = divmod(total, 12)
    m += 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def ym(d: Date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


# ---- 日本の祝日（内閣府の公表ルールに基づく計算。2000〜2099年を想定） ----

def _nth_monday(year: int, month: int, n: int) -> Date:
    first = dt.date(year, month, 1)
    offset = (0 - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (n - 1))


def _vernal_equinox(year: int) -> int:
    return int(20.8431 + 0.242194 * (year - 1980) - (year - 1980) // 4)


def _autumnal_equinox(year: int) -> int:
    return int(23.2488 + 0.242194 * (year - 1980) - (year - 1980) // 4)


@lru_cache(maxsize=None)
def holidays(year: int) -> dict[Date, str]:
    """その年の国民の祝日・振替休日・国民の休日。"""
    h: dict[Date, str] = {
        dt.date(year, 1, 1): "元日",
        _nth_monday(year, 1, 2): "成人の日",
        dt.date(year, 2, 11): "建国記念の日",
        dt.date(year, 2, 23): "天皇誕生日",
        dt.date(year, 3, _vernal_equinox(year)): "春分の日",
        dt.date(year, 4, 29): "昭和の日",
        dt.date(year, 5, 3): "憲法記念日",
        dt.date(year, 5, 4): "みどりの日",
        dt.date(year, 5, 5): "こどもの日",
        _nth_monday(year, 7, 3): "海の日",
        dt.date(year, 8, 11): "山の日",
        _nth_monday(year, 9, 3): "敬老の日",
        dt.date(year, 9, _autumnal_equinox(year)): "秋分の日",
        _nth_monday(year, 10, 2): "スポーツの日",
        dt.date(year, 11, 3): "文化の日",
        dt.date(year, 11, 23): "勤労感謝の日",
    }
    # 国民の休日：祝日に挟まれた平日
    for d in sorted(h):
        nxt = d + dt.timedelta(days=2)
        mid = d + dt.timedelta(days=1)
        if nxt in h and mid not in h and mid.weekday() != 6:
            h[mid] = "国民の休日"
    # 振替休日：祝日が日曜なら、その後の最初の祝日でない日
    for d in sorted(list(h)):
        if d.weekday() == 6:
            s = d + dt.timedelta(days=1)
            while s in h:
                s += dt.timedelta(days=1)
            h[s] = "振替休日"
    return h


def is_holiday(d: Date) -> bool:
    return d in holidays(d.year)


def is_business_day(d: Date) -> bool:
    return d.weekday() < 5 and not is_holiday(d)


def next_business_day(d: Date) -> Date:
    while not is_business_day(d):
        d += dt.timedelta(days=1)
    return d


def tax_due(d: Date) -> Date:
    """国税の期限の繰り下げ。土日・祝日・12/29〜1/3 に当たる場合は次の日へ（国税通則法10条2項）。"""
    def closed(x: Date) -> bool:
        if x.weekday() >= 5 or is_holiday(x):
            return True
        return (x.month == 12 and x.day >= 29) or (x.month == 1 and x.day <= 3)

    while closed(d):
        d += dt.timedelta(days=1)
    return d
