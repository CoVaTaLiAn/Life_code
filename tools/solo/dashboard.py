"""台帳から1枚の HTML ダッシュボードを作る（外部ライブラリなし・オフラインで開ける）。"""

from __future__ import annotations

import datetime as dt
import html

from . import cashflow, dates, deadlines, invoice, pipeline, report
from .store import Store, fmt, money, yen

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;--sales:#2f6fdf;--cost:#c9772b;--good:#2e8b57;--bad:#c0392b}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1e;--ink:#eeeeea;--muted:#a0a09a;--line:#33332f;--sales:#6d9cf0;--cost:#e09a55;--good:#5cbf86;--bad:#e2685a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 "Hiragino Sans","Noto Sans JP","Yu Gothic",system-ui,sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:0 0 12px}.muted{color:var(--muted);font-size:13px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.kpi .v{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums}.kpi .l{color:var(--muted);font-size:13px}
.two{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));margin-top:12px}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:6px 4px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.bad{color:var(--bad);font-weight:600}.good{color:var(--good)}
.legend span{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 12px;vertical-align:middle}
svg text{fill:var(--muted);font-size:11px}
"""


def _bars(months: list[tuple[str, int, int]]) -> str:
    w, h, pad = 640, 200, 28
    top = max([max(s, e) for _, s, e in months] + [1])
    bw = (w - pad) / max(len(months), 1)
    parts = [f'<svg viewBox="0 0 {w} {h + 24}" width="100%" role="img" aria-label="月別の売上と経費">',
             f'<line x1="{pad}" y1="{h}" x2="{w}" y2="{h}" stroke="var(--line)"/>']
    for i, (label, s, e) in enumerate(months):
        x = pad + i * bw
        for j, (v, color, name) in enumerate(((s, "var(--sales)", "売上"), (e, "var(--cost)", "経費"))):
            bh = (h - 10) * v / top
            parts.append(f'<rect x="{x + 4 + j * (bw - 8) / 2:.1f}" y="{h - bh:.1f}" width="{(bw - 10) / 2:.1f}" '
                         f'height="{bh:.1f}" rx="2" fill="{color}"><title>{label} {name} {v:,}円</title></rect>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{h + 16}" text-anchor="middle">{label[5:]}月</text>')
    parts.append("</svg>")
    return "".join(parts)


def build(store: Store, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    e = html.escape
    name = store.cfg("company.name", "会社")
    ms = dt.date(today.year, today.month, 1)
    cur = report.pl(store, ms, today)
    ytd = report.pl(store, report.fiscal_start(store, today), today)
    ar = invoice.receivables(store, today)
    cf = cashflow.forecast(store, 3, today)
    fixed = cashflow.monthly_fixed(store)
    stale = pipeline.overdue(store, today)
    summ = pipeline.summary(store)
    soon = deadlines.generate(store, today, today + dt.timedelta(days=45))

    months = []
    for k in range(11, -1, -1):
        m = dates.add_months(ms, -k)
        p = report.pl(store, m, dates.month_end(m.year, m.month))
        months.append((dates.ym(m), p["売上"], p["経費"]))

    goal = yen(store.cfg("goal.monthly_sales", 0))
    goal_txt = f"目標の {cur['売上'] * 100 // goal}%" if goal else "目標未設定"
    runway = cf[-1].end_balance / fixed if fixed else None
    over = sum(1 for r in ar if r["超過日数"] > 0)

    def kpi(label, value, sub="", cls=""):
        return f'<div class="card kpi"><div class="l">{label}</div><div class="v {cls}">{value}</div><div class="muted">{sub}</div></div>'

    tiles = "".join([
        kpi("今月の売上", f"{money(cur['売上'])}", goal_txt),
        kpi("今月の利益", f"{money(cur['利益'])}", f"期首から {money(ytd['利益'])}", "bad" if cur["利益"] < 0 else ""),
        kpi("未入金", f"{money(sum(yen(r['税込金額']) for r in ar))}", f"{len(ar)}件（期限超過 {over}件）", "bad" if over else ""),
        kpi("3か月後の手元資金", f"{money(cf[-1].end_balance)}",
            f"固定費の {runway:.1f} か月分" if runway is not None else "固定費未設定",
            "bad" if runway is not None and runway < int(store.cfg('cash.warn_months', 6)) else ""),
    ])
    ar_rows = "".join(
        f"<tr><td>{e(r['取引先'])}<div class=muted>{e(r['請求番号'])}</div></td><td class=n>{money(yen(r['税込金額']))}</td>"
        f"<td class=n{' bad' if r['超過日数'] else ''}>{e(r['入金予定日'])}{'<br>' + str(r['超過日数']) + '日超過' if r['超過日数'] else ''}</td></tr>"
        for r in ar) or "<tr><td colspan=3 class=muted>なし</td></tr>"
    pipe_rows = "".join(
        f"<tr><td>{s['段階']}</td><td class=n>{s['件数']}</td><td class=n>{money(s['見込金額'])}</td><td class=n>{money(s['加重金額'])}</td></tr>"
        for s in summ if s["件数"]) or "<tr><td colspan=4 class=muted>登録なし</td></tr>"
    stale_rows = "".join(
        f"<li>{e(r['案件名'])}（{e(r['相手先'])}）— {e(r.get('次の行動') or '次の行動が未設定')}</li>" for r in stale)
    dl_rows = "".join(
        f"<tr><td class=n>{d.date:%m/%d}</td><td>{e(d.title)}<div class=muted>{e(d.where)}</div></td></tr>" for d in soon
    ) or "<tr><td colspan=2 class=muted>なし</td></tr>"
    cf_rows = "".join(
        f"<tr><td>{m.ym}</td><td class=n>{money(m.actual_in + m.expected_in + m.overdue_in)}</td>"
        f"<td class=n>{money(m.actual_out + m.expected_out)}</td><td class=n><b>{money(m.end_balance)}</b></td></tr>" for m in cf)
    acc_rows = "".join(f"<tr><td>{e(k)}</td><td class=n>{money(v)}</td></tr>" for k, v in ytd["勘定科目別"].items()) \
        or "<tr><td colspan=2 class=muted>なし</td></tr>"

    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>経営ダッシュボード</title><style>{CSS}</style></head>
<body><main>
<h1>{e(name)} 経営ダッシュボード</h1><div class="muted">{today:%Y年%m月%d日} 時点・税込の概算</div>
<div class="grid">{tiles}</div>
<div class="card"><h2>月別の売上と経費（12か月）</h2>
<div class="legend muted"><span style="background:var(--sales)"></span>売上<span style="background:var(--cost)"></span>経費</div>
{_bars(months)}</div>
<div class="two">
<div class="card"><h2>未入金</h2><table><tr><th>取引先</th><th class=n>金額</th><th class=n>期限</th></tr>{ar_rows}</table></div>
<div class="card"><h2>資金繰り（3か月）</h2><table><tr><th>月</th><th class=n>入金</th><th class=n>支払</th><th class=n>月末残高</th></tr>{cf_rows}</table></div>
<div class="card"><h2>案件</h2><table><tr><th>段階</th><th class=n>件数</th><th class=n>見込</th><th class=n>加重</th></tr>{pipe_rows}</table>
{('<p class="bad">止まっている案件</p><ul>' + stale_rows + '</ul>') if stale_rows else ''}</div>
<div class="card"><h2>45日以内の期限</h2><table>{dl_rows}</table></div>
<div class="card"><h2>経費の内訳（期首から）</h2><table>{acc_rows}</table></div>
</div></main></body></html>
"""
