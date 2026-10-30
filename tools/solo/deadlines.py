"""設立日・決算月から、届出・税金・社会保険の期限を具体的な日付で出す。

ここに入れているのは一般的なルール（2026年10月時点）。自治体ごとの違いや個別の事情は
反映しきれないので、出力には「確認先」を必ずつけ、提出前に公式情報と税理士で確認する。
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass

from . import dates
from .store import Store


@dataclass
class Deadline:
    date: dt.date
    title: str
    where: str
    detail: str = ""
    original: dt.date | None = None  # 土日祝で繰り下げる前の日付

    @property
    def shifted(self) -> bool:
        return self.original is not None and self.original != self.date


def _tax(d: dt.date) -> tuple[dt.date, dt.date]:
    return dates.tax_due(d), d


def first_fy_end(founded: dt.date, fye_month: int) -> dt.date:
    y = founded.year
    end = dates.month_end(y, fye_month)
    if end < founded:
        end = dates.month_end(y + 1, fye_month)
    return end


def fy_ends(founded: dt.date, fye_month: int, until: dt.date) -> list[dt.date]:
    out, e = [], first_fy_end(founded, fye_month)
    while e <= until:
        out.append(e)
        e = dates.month_end(e.year + 1, fye_month)
    return out


def generate(store: Store, start: dt.date, end: dt.date) -> list[Deadline]:
    c = store.cfg("company", {}) or {}
    founded = dates.parse(c.get("founded", dt.date.today().isoformat()))
    fye = int(c.get("fiscal_year_end_month", 3))
    kabushiki = c.get("type", "株式会社") == "株式会社"
    taxable = bool(store.cfg("tax.consumption_taxable", False))
    special = bool(store.cfg("tax.withholding_special", True))
    fy1 = first_fy_end(founded, fye)
    out: list[Deadline] = []

    def add(d: dt.date, title: str, where: str, detail: str = "", tax: bool = False):
        if tax:
            d2, orig = _tax(d)
            out.append(Deadline(d2, title, where, detail, orig))
        else:
            out.append(Deadline(d, title, where, detail))

    # ---- 設立直後（1回だけ） ----
    add(founded + dt.timedelta(days=5), "健康保険・厚生年金保険 新規適用届", "年金事務所",
        "役員報酬を払う社長1人の会社も加入が必要。設立の事実から5日以内")
    add(founded + dt.timedelta(days=15), "法人設立届（地方税）", "都道府県税事務所・市区町村",
        "期限は自治体ごとに違う（東京都は15日以内、多くは1〜2か月以内）。要確認")
    add(dates.add_months(founded, 1), "給与支払事務所等の開設届出書", "税務署",
        "役員報酬を払い始める事務所を開設した日から1か月以内。源泉所得税の納期の特例の承認申請も一緒に出すとよい",
        tax=True)
    add(dates.add_months(founded, 2), "法人設立届出書", "税務署",
        "設立の日から2か月以内。定款の写しなどを添付（e-Taxなら登記事項証明書は不要な場合あり）", tax=True)
    blue = min(dates.add_months(founded, 3), fy1) - dt.timedelta(days=1)
    add(blue, "青色申告の承認申請書", "税務署",
        "設立から3か月を経過した日と1期目の末日のどちらか早い日の前日まで。赤字の繰越（最長10年）などに必要", tax=True)
    add(dates.add_months(founded, 3) - dt.timedelta(days=1), "役員報酬の決定（期限）", "社内（議事録・決定書）",
        "事業年度の開始から3か月以内に決めれば、毎月同額の報酬が経費（損金）になる。以後その期は原則変えない")
    if not taxable:
        add(fy1, "インボイス登録の検討（1期目から登録する場合の申請期限）", "税務署",
            "免税事業者が設立初年度から登録したい場合、その事業年度中に申請すれば設立日にさかのぼって登録できる。要税理士確認")

    # ---- 決算ごと ----
    for e in fy_ends(founded, fye, dates.add_months(end, 12)):
        due = dates.add_months(e, 2)
        due = dates.month_end(due.year, due.month)
        add(due, f"法人税・地方法人税・住民税・事業税の申告と納付（{e:%Y年%m月}期）", "税務署・都道府県・市区町村",
            "決算日から2か月以内。赤字でも申告が必要で、住民税の均等割はかかる", tax=True)
        if taxable:
            add(due, f"消費税の申告と納付（{e:%Y年%m月}期）", "税務署", "課税事業者の場合", tax=True)
        meeting = "定時株主総会" if kabushiki else "定時社員総会（決算の承認）"
        add(due - dt.timedelta(days=7), f"{meeting}・決算書の承認", "社内（議事録）",
            "申告書に添付する決算書を承認しておく。1人会社でも議事録を作る")
        if kabushiki:
            add(due, f"決算公告（{e:%Y年%m月}期）", "官報・電子公告など",
                "定時株主総会のあと遅滞なく。株式会社の義務")
        add(dates.add_months(e, 3), "翌期の役員報酬の決定（期限）", "社内（議事録）",
            "期首から3か月以内。変えない場合も議事録に残すとよい")
        mid = dates.add_months(e, 8)
        add(dates.month_end(mid.year, mid.month), f"中間申告の確認（{e:%Y年%m月}期の翌期）", "税務署",
            "前期の法人税額が20万円を超えた場合などに必要。税務署から届く通知を確認", tax=True)
        if e == fy1:
            add(e, "2期目の消費税の課税判定（特定期間）", "税理士に確認",
                "1期目の最初の6か月の売上と給与がどちらも1,000万円を超えると、2期目から課税事業者になる")

    # ---- 毎年（暦年） ----
    for y in range(start.year, end.year + 2):
        if special:
            add(dt.date(y, 1, 20), "源泉所得税の納付（納期の特例：前年7〜12月分）", "税務署・金融機関", tax=True)
            add(dt.date(y, 7, 10), "源泉所得税の納付（納期の特例：1〜6月分）", "税務署・金融機関", tax=True)
        add(dt.date(y, 1, 31), "法定調書合計表の提出", "税務署", "役員報酬や報酬の支払いをまとめて報告", tax=True)
        add(dates.next_business_day(dt.date(y, 1, 31)), "給与支払報告書・償却資産申告書の提出", "市区町村",
            "償却資産は1月1日時点の事業用資産（PCなど）。少額なら申告不要の場合あり")
        add(dates.next_business_day(dt.date(y, 7, 10)), "社会保険の算定基礎届", "年金事務所", "7月1日〜10日")
        add(dt.date(y, 12, 1), "年末調整の準備（社長本人の分）", "社内", "翌年1月の源泉所得税納付で精算")
    if not special:
        m = dt.date(start.year, start.month, 1)
        while m <= end:
            add(dates.add_months(m, 1).replace(day=10), f"源泉所得税の納付（{m:%Y年%m月}分）", "税務署・金融機関", tax=True)
            m = dates.add_months(m, 1)

    # ---- 役員の任期（株式会社のみ） ----
    if kabushiki:
        term = int(c.get("officer_term_years", 10))
        limit = dates.add_months(founded, 12 * term)
        last = max(x for x in fy_ends(founded, fye, limit))
        due = dates.add_months(last, 3)
        add(due, "役員の任期満了・重任登記", "法務局",
            f"任期{term}年。満了後2週間以内に登記しないと過料の対象。日付は目安")

    out = [d for d in out if start <= d.date <= end]
    out.sort(key=lambda d: (d.date, d.title))
    return out


def to_markdown(items: list[Deadline]) -> str:
    lines = ["| 期限 | 内容 | 確認先 | メモ |", "|---|---|---|---|"]
    wd = "月火水木金土日"
    for d in items:
        s = f"{d.date:%Y-%m-%d}({wd[d.date.weekday()]})"
        if d.shifted:
            s += f"<br>※本来 {d.original:%m/%d}"
        lines.append(f"| {s} | {d.title} | {d.where} | {d.detail} |")
    return "\n".join(lines) + "\n"


def to_ics(items: list[Deadline], company: str = "") -> str:
    """Googleカレンダーなどに取り込める iCalendar 形式。終日予定で、7日前と1日前に通知。"""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//solo-company-os//deadlines//JA",
             "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{esc(company + ' 期限')}"]
    for d in items:
        uid = hashlib.sha1(f"{d.date}{d.title}".encode()).hexdigest()[:16]
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@solo-company-os",
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{d.date:%Y%m%d}",
            f"DTEND;VALUE=DATE:{d.date + dt.timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{esc('【期限】' + d.title)}",
            f"DESCRIPTION:{esc(f'確認先：{d.where}' + (chr(10) + d.detail if d.detail else ''))}",
        ]
        for days in (7, 1):
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(d.title)}",
                      f"TRIGGER:-P{days}D", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    # iCalendar は CRLF 改行。75オクテットの折り返しは主要カレンダーが不要なので省略
    return "\r\n".join(lines) + "\r\n"
