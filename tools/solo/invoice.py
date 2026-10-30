"""請求書の作成と入金の記録。

- 請求番号は INV-YYYYMM-NNN（その月の連番）
- 消費税は税率ごとに1回だけ端数を切り捨てる（インボイス制度の端数処理ルール）
- Markdown と、ブラウザで印刷→PDF保存できる HTML を書き出し、売上台帳に1行追加する
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import dates
from .store import Store, fmt, yen


@dataclass
class Item:
    name: str
    qty: float
    unit_price: int
    rate: int = 10

    @property
    def amount(self) -> int:
        return int(round(self.qty * self.unit_price))

    @classmethod
    def parse(cls, spec: str, default_rate: int = 10) -> "Item":
        """'内容:数量:単価' または '内容:数量:単価:税率'。内容に ':' を含めたいときは '\\:' と書く。"""
        parts = [p.replace("\0", ":") for p in spec.replace("\\:", "\0").split(":")]
        if len(parts) not in (3, 4):
            raise ValueError(f"品目の書き方が違います: {spec!r}（例: 'Webサイト制作:1:300000'）")
        rate = int(parts[3]) if len(parts) == 4 else default_rate
        if rate not in (0, 8, 10):
            raise ValueError(f"税率は 0 / 8 / 10 のどれかです: {rate}")
        return cls(parts[0].strip(), float(parts[1]), yen(parts[2]), rate)


@dataclass
class Invoice:
    number: str
    issue_date: dt.date
    due_date: dt.date
    client: str
    items: list[Item]
    subject: str = ""
    note: str = ""
    by_rate: dict[int, tuple[int, int]] = field(init=False)

    def __post_init__(self):
        self.by_rate = {}
        for it in self.items:
            sub, _ = self.by_rate.get(it.rate, (0, 0))
            self.by_rate[it.rate] = (sub + it.amount, 0)
        for rate, (sub, _) in self.by_rate.items():
            self.by_rate[rate] = (sub, sub * rate // 100)

    @property
    def subtotal(self) -> int:
        return sum(s for s, _ in self.by_rate.values())

    @property
    def tax(self) -> int:
        return sum(t for _, t in self.by_rate.values())

    @property
    def total(self) -> int:
        return self.subtotal + self.tax


def due_date(issue: dt.date, rule: str) -> dt.date:
    if rule == "next_month_end":
        nxt = dates.add_months(issue.replace(day=1), 1)
        return dates.month_end(nxt.year, nxt.month)
    m = re.fullmatch(r"days:(\d+)", rule)
    if m:
        return issue + dt.timedelta(days=int(m.group(1)))
    raise ValueError(f"due_rule が読めません: {rule!r}")


def next_number(store: Store, issue: dt.date) -> str:
    prefix = f"INV-{issue.year:04d}{issue.month:02d}-"
    used = [r["請求番号"] for r in store.read("sales") if r.get("請求番号", "").startswith(prefix)]
    n = max((int(u[len(prefix):]) for u in used if u[len(prefix):].isdigit()), default=0) + 1
    return f"{prefix}{n:03d}"


def build(store: Store, client: str, item_specs: list[str], issue: dt.date | None = None,
          subject: str = "", due: dt.date | None = None) -> Invoice:
    issue = issue or dt.date.today()
    rate = int(store.cfg("invoice.default_tax_rate", 10))
    items = [Item.parse(s, rate) for s in item_specs]
    if not items:
        raise ValueError("品目が1つもありません")
    due = due or due_date(issue, store.cfg("invoice.due_rule", "next_month_end"))
    return Invoice(next_number(store, issue), issue, due, client, items, subject,
                   store.cfg("invoice.note", ""))


def _jdate(d: dt.date) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def to_markdown(store: Store, inv: Invoice) -> str:
    c = store.cfg("company", {}) or {}
    reg = store.cfg("invoice.registration_number", "")
    lines = [
        "# 請求書", "",
        f"請求番号：{inv.number}  ",
        f"請求日：{_jdate(inv.issue_date)}", "",
        f"**{inv.client} 御中**", "",
        *[f"{v}  " for v in (c.get("name"), " ".join(x for x in (c.get("postal_code"), c.get("address")) if x),
                             c.get("email"), c.get("phone")) if v],
        f"登録番号：{reg}" if reg else "（適格請求書発行事業者の登録なし）", "",
    ]
    if inv.subject:
        lines += [f"件名：{inv.subject}", ""]
    lines += [
        "下記のとおりご請求申し上げます。", "",
        f"**ご請求金額：¥{fmt(inv.total)}（税込）**  ",
        f"お支払期限：{_jdate(inv.due_date)}", "",
        "| 品目 | 数量 | 単価 | 金額（税抜） | 税率 |",
        "|---|---:|---:|---:|---:|",
    ]
    for it in inv.items:
        q = int(it.qty) if it.qty == int(it.qty) else it.qty
        mark = "※" if it.rate == 8 else ""
        lines.append(f"| {it.name}{mark} | {q} | ¥{fmt(it.unit_price)} | ¥{fmt(it.amount)} | {it.rate}% |")
    lines.append("")
    for rate, (sub, tax) in sorted(inv.by_rate.items(), reverse=True):
        lines.append(f"- {rate}%対象：¥{fmt(sub)}　消費税：¥{fmt(tax)}")
    if 8 in inv.by_rate:
        lines.append("- ※は軽減税率対象")
    lines += ["", f"**お振込先**：{store.cfg('invoice.bank', '')}", ""]
    if inv.note:
        lines.append(inv.note)
    return "\n".join(lines) + "\n"


def to_html(store: Store, inv: Invoice) -> str:
    c = store.cfg("company", {}) or {}
    e = html.escape
    reg = store.cfg("invoice.registration_number", "")
    rows = "".join(
        f"<tr><td>{e(it.name)}{'※' if it.rate == 8 else ''}</td>"
        f"<td class=n>{int(it.qty) if it.qty == int(it.qty) else it.qty}</td>"
        f"<td class=n>¥{fmt(it.unit_price)}</td><td class=n>¥{fmt(it.amount)}</td>"
        f"<td class=n>{it.rate}%</td></tr>"
        for it in inv.items
    )
    rates = "".join(
        f"<tr><td colspan=3>{r}%対象</td><td class=n>¥{fmt(s)}</td><td class=n>税 ¥{fmt(t)}</td></tr>"
        for r, (s, t) in sorted(inv.by_rate.items(), reverse=True)
    )
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>請求書 {e(inv.number)}</title>
<style>
@page {{ size: A4; margin: 18mm; }}
body {{ font-family: "Hiragino Sans", "Noto Sans JP", "Yu Gothic", sans-serif; color:#222; max-width: 760px; margin: 24px auto; padding: 0 16px; }}
h1 {{ text-align:center; letter-spacing: .5em; font-weight: 600; }}
.head {{ display:flex; justify-content:space-between; gap:24px; margin: 24px 0; flex-wrap: wrap; }}
.client {{ font-size: 1.2em; border-bottom: 1px solid #222; padding-bottom: 4px; }}
.total {{ font-size: 1.4em; font-weight: 700; border: 2px solid #222; padding: 8px 12px; display:inline-block; margin: 12px 0; }}
table {{ width:100%; border-collapse: collapse; margin-top: 12px; }}
th, td {{ border: 1px solid #999; padding: 6px 8px; }}
th {{ background:#f2f2f2; }}
.n {{ text-align:right; white-space:nowrap; }}
.muted {{ color:#666; font-size:.9em; }}
@media print {{ .noprint {{ display:none; }} body {{ margin:0; }} }}
</style></head><body>
<p class="noprint muted">ブラウザの「印刷」→「PDFに保存」でPDFにできます。</p>
<h1>請求書</h1>
<div class="head">
 <div><div class="client">{e(inv.client)} 御中</div>
  {f'<p>件名：{e(inv.subject)}</p>' if inv.subject else ''}
  <p>下記のとおりご請求申し上げます。</p>
  <div class="total">ご請求金額 ¥{fmt(inv.total)}（税込）</div>
  <p>お支払期限：{_jdate(inv.due_date)}</p></div>
 <div class="muted"><p>請求番号：{e(inv.number)}<br>請求日：{_jdate(inv.issue_date)}</p>
  <p>{'<br>'.join(e(v) for v in (c.get('name'), ' '.join(x for x in (c.get('postal_code'), c.get('address')) if x),
                                  c.get('email'), c.get('phone')) if v)}<br>
  {('登録番号：' + e(reg)) if reg else '適格請求書発行事業者の登録なし'}</p></div>
</div>
<table><thead><tr><th>品目</th><th>数量</th><th>単価</th><th>金額（税抜）</th><th>税率</th></tr></thead>
<tbody>{rows}</tbody>
<tfoot>{rates}
<tr><td colspan=3><b>合計</b></td><td class=n colspan=2><b>¥{fmt(inv.total)}</b>（うち消費税 ¥{fmt(inv.tax)}）</td></tr></tfoot></table>
{'<p class=muted>※は軽減税率対象</p>' if 8 in inv.by_rate else ''}
<p><b>お振込先</b>：{e(store.cfg('invoice.bank', ''))}</p>
<p class="muted">{e(inv.note)}</p>
</body></html>
"""


def issue(store: Store, inv: Invoice, dry_run: bool = False) -> list[Path]:
    """請求書ファイルを書き出し、売上台帳に追加する。"""
    out = store.root / "finance" / "invoices"
    md, ht = out / f"{inv.number}.md", out / f"{inv.number}.html"
    if dry_run:
        return [md, ht]
    out.mkdir(parents=True, exist_ok=True)
    md.write_text(to_markdown(store, inv), encoding="utf-8")
    ht.write_text(to_html(store, inv), encoding="utf-8")
    store.append("sales", {
        "請求番号": inv.number,
        "請求日": inv.issue_date.isoformat(),
        "取引先": inv.client,
        "内容": inv.subject or " / ".join(i.name for i in inv.items),
        "税抜金額": str(inv.subtotal),
        "消費税": str(inv.tax),
        "税込金額": str(inv.total),
        "入金予定日": inv.due_date.isoformat(),
        "入金日": "",
        "備考": "",
    })
    return [md, ht]


def mark_paid(store: Store, number: str, paid: dt.date, amount: int | None = None) -> dict:
    rows = store.read("sales")
    for r in rows:
        if r["請求番号"] == number:
            if r["入金日"]:
                raise ValueError(f"{number} はすでに {r['入金日']} に入金済みです")
            r["入金日"] = paid.isoformat()
            if amount is not None and amount != yen(r["税込金額"]):
                diff = yen(r["税込金額"]) - amount
                r["備考"] = (r["備考"] + f" 入金額{fmt(amount)}円（差額{fmt(diff)}円：振込手数料など要確認）").strip()
            store.write("sales", rows)
            return r
    raise KeyError(f"請求番号 {number} が売上台帳にありません")


def receivables(store: Store, today: dt.date | None = None) -> list[dict]:
    """未入金の一覧。期限超過の日数をつける。"""
    today = today or dt.date.today()
    out = []
    for r in store.read("sales"):
        if r.get("入金日"):
            continue
        due = dates.parse(r["入金予定日"]) if r.get("入金予定日") else None
        r = dict(r)
        r["超過日数"] = (today - due).days if due and due < today else 0
        out.append(r)
    return sorted(out, key=lambda r: r.get("入金予定日", ""))
