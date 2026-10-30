"""月次・週次のレポートとKPIの更新。売上は請求日、経費は支払日で月に割り振る（概算）。"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import cashflow, contracts, dates, deadlines, invoice, pipeline
from .store import Store, fmt, yen


def fiscal_start(store: Store, d: dt.date) -> dt.date:
    fye = int(store.cfg("company.fiscal_year_end_month", 3))
    start_month = fye % 12 + 1
    y = d.year if d.month >= start_month else d.year - 1
    s = dt.date(y, start_month, 1)
    founded = store.cfg("company.founded")
    if founded:
        f = dates.parse(founded)
        if s < f <= d:
            s = f
    return s


def pl(store: Store, start: dt.date, end: dt.date) -> dict:
    """期間の損益（税込ベースの概算）。"""
    sales = [r for r in store.read("sales") if start <= dates.parse(r["請求日"]) <= end]
    exps = [r for r in store.read("expenses") if start <= dates.parse(r["日付"]) <= end]
    by_acc: dict[str, int] = defaultdict(int)
    for r in exps:
        by_acc[r["勘定科目"] or "要確認"] += yen(r["税込金額"])
    s_total = sum(yen(r["税込金額"]) for r in sales)
    e_total = sum(by_acc.values())
    by_client: dict[str, int] = defaultdict(int)
    for r in sales:
        by_client[r["取引先"]] += yen(r["税込金額"])
    return {
        "売上": s_total, "経費": e_total, "利益": s_total - e_total,
        "勘定科目別": dict(sorted(by_acc.items(), key=lambda kv: -kv[1])),
        "取引先別": dict(sorted(by_client.items(), key=lambda kv: -kv[1])),
        "件数": {"売上": len(sales), "経費": len(exps)},
        "要確認": [r for r in exps if r["勘定科目"] in ("", "要確認") or r["証憑"] in ("", "証憑なし")],
    }


def _pl_table(cur: dict, ytd: dict) -> list[str]:
    return [
        "| | 当月 | 期首から累計 |", "|---|---:|---:|",
        f"| 売上 | {fmt(cur['売上'])} | {fmt(ytd['売上'])} |",
        f"| 経費 | {fmt(cur['経費'])} | {fmt(ytd['経費'])} |",
        f"| **利益** | **{fmt(cur['利益'])}** | **{fmt(ytd['利益'])}** |",
    ]


def monthly(store: Store, year: int, month: int, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    start, end = dt.date(year, month, 1), dates.month_end(year, month)
    cur, ytd = pl(store, start, end), pl(store, fiscal_start(store, end), end)
    goal_s = yen(store.cfg("goal.monthly_sales", 0))
    goal_p = yen(store.cfg("goal.monthly_profit", 0))
    ar = invoice.receivables(store, today)
    over = [r for r in ar if r["超過日数"] > 0]

    L = [f"# 月次締め {year}年{month}月", "", "## 結論", ""]
    L.append(f"- 売上 {fmt(cur['売上'])}円 / 経費 {fmt(cur['経費'])}円 / 利益 {fmt(cur['利益'])}円")
    if goal_s:
        L.append(f"- 売上目標 {fmt(goal_s)}円に対して {cur['売上'] * 100 // goal_s}%")
    if goal_p:
        L.append(f"- 利益目標 {fmt(goal_p)}円に対して {cur['利益'] * 100 // goal_p if goal_p else 0}%")
    L.append(f"- 未入金 {len(ar)}件 {fmt(sum(yen(r['税込金額']) for r in ar))}円（うち期限超過 {len(over)}件）")
    L.append(f"- 要確認の経費 {len(cur['要確認'])}件")
    L += ["", "## 損益（税込・概算）", "", *_pl_table(cur, ytd), "", "### 経費の内訳", ""]
    L += [f"- {k}：{fmt(v)}円" for k, v in cur["勘定科目別"].items()] or ["- なし"]
    if cur["取引先別"]:
        top, top_v = next(iter(cur["取引先別"].items()))
        share = top_v * 100 // cur["売上"] if cur["売上"] else 0
        L += ["", "### 取引先別の売上", ""]
        L += [f"- {k}：{fmt(v)}円" for k, v in cur["取引先別"].items()]
        if share >= 50:
            L.append(f"- ⚠ 売上の{share}%が「{top}」1社。依存度が高い")
    L += ["", "## 未入金", ""]
    L += [f"- {r['請求番号']} {r['取引先']} {fmt(yen(r['税込金額']))}円 期限 {r['入金予定日']}"
          + (f" **{r['超過日数']}日超過**" if r["超過日数"] else "") for r in ar] or ["- なし"]
    L += ["", "## 資金繰り（3か月）", "", cashflow.to_markdown(store, cashflow.forecast(store, 3, today))]
    L += ["## 要確認の経費（税理士への質問候補）", ""]
    L += [f"- {r['日付']} {r['支払先']} {fmt(yen(r['税込金額']))}円 科目:{r['勘定科目'] or '未設定'} 証憑:{r['証憑'] or 'なし'}"
          for r in cur["要確認"]] or ["- なし"]
    return "\n".join(L) + "\n"


def update_kpi(store: Store, year: int, month: int, today: dt.date | None = None) -> dict:
    start, end = dt.date(year, month, 1), dates.month_end(year, month)
    p = pl(store, start, end)
    deals = store.read("pipeline")
    new = sum(1 for r in deals if r.get("最終更新") and start <= dates.parse(r["最終更新"]) <= end
              and r.get("段階") in ("商談", "提案"))
    won = sum(1 for r in deals if r.get("段階") == "受注" and r.get("最終更新")
              and start <= dates.parse(r["最終更新"]) <= end)
    bal = cashflow.forecast(store, 1, today or end)
    match = [m for m in bal if m.ym == f"{year:04d}-{month:02d}"]
    row = {"月": f"{year:04d}-{month:02d}", "売上": str(p["売上"]), "経費": str(p["経費"]),
           "利益": str(p["利益"]), "新規商談数": str(new), "受注数": str(won),
           "手元資金": str(match[0].end_balance) if match else "", "備考": "自動集計"}
    rows = [r for r in store.read("kpi") if r["月"] != row["月"]] + [row]
    rows.sort(key=lambda r: r["月"])
    store.write("kpi", rows)
    return row


def weekly(store: Store, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    ms = dt.date(today.year, today.month, 1)
    cur = pl(store, ms, today)
    ar = invoice.receivables(store, today)
    over = [r for r in ar if r["超過日数"] > 0]
    stale = pipeline.overdue(store, today)
    summ = [s for s in pipeline.summary(store) if s["件数"]]
    soon = deadlines.generate(store, today, today + dt.timedelta(days=14))
    notice = contracts.upcoming(store, today, 45)
    cf = cashflow.forecast(store, 3, today)

    todo = []
    todo += [f"未入金の催促：{r['取引先']}（{r['超過日数']}日超過）" for r in over[:2]]
    todo += [f"期限：{d.title}（{d.date:%m/%d}）" for d in soon[:2]]
    todo += [f"案件のフォロー：{r['案件名']}（{r['相手先']}）" for r in stale[:2]]
    todo += [f"契約の更新判断：{c['契約名']}（{c['相手先']} 予告期限 {c['解約予告期限']}）" for c in notice[:1]]

    L = [f"# 週次経営会議 {today:%Y-%m-%d}", "", "## 今週やること", ""]
    L += [f"{i}. {t}" for i, t in enumerate(todo[:5], 1)] or ["- 急ぎの対応なし。営業（新規の接触）に時間を使う"]
    L += ["", "## 今月の数字（{:%m/%d}時点）".format(today), "",
          f"- 売上 {fmt(cur['売上'])}円 / 経費 {fmt(cur['経費'])}円 / 利益 {fmt(cur['利益'])}円",
          f"- 未入金 {len(ar)}件 {fmt(sum(yen(r['税込金額']) for r in ar))}円（期限超過 {len(over)}件）",
          f"- 3か月後の手元資金見込み {fmt(cf[-1].end_balance)}円", "", "## 案件", ""]
    L += [f"- {s['段階']}：{s['件数']}件 {fmt(s['見込金額'])}円（加重 {fmt(s['加重金額'])}円）" for s in summ] or ["- 登録なし"]
    if stale:
        L += ["", "止まっている案件："]
        L += [f"- {r['案件名']}（{r['相手先']}）次の行動：{r.get('次の行動') or '未設定'} {r.get('次の行動日') or ''}"
              for r in stale]
    L += ["", "## 14日以内の期限", ""]
    L += [f"- {d.date:%m/%d} {d.title}（{d.where}）" for d in soon] or ["- なし"]
    if notice:
        L += ["", "## 契約の解約予告期限（45日以内）", ""]
        L += [f"- {c['解約予告期限']} {c['相手先']}：{c['契約名']}" for c in notice]
    return "\n".join(L) + "\n"
