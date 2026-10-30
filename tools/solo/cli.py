"""コマンドの入口。`./solo --help` で使い方が出る。"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import (cashflow, check, dashboard, dates, deadlines, expense, invoice, pipeline, report,
               simulate)
from .store import Store, fmt, yen


def _today(a) -> dt.date:
    return dates.parse(a.today) if a.today else dt.date.today()


def _save(store: Store, name: str, text: str) -> Path:
    p = store.root / "reports" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def cmd_invoice_new(a, s: Store):
    inv = invoice.build(s, a.client, a.item, dates.parse(a.date) if a.date else _today(a), a.subject,
                        dates.parse(a.due) if a.due else None)
    paths = invoice.issue(s, inv, dry_run=a.dry_run)
    print(invoice.to_markdown(s, inv))
    print(("（試し：保存していません）" if a.dry_run else "保存しました：") + " / ".join(str(p) for p in paths))


def cmd_quote(a, s: Store):
    q = invoice.build_quote(s, a.client, a.item, dates.parse(a.date) if a.date else _today(a), a.subject,
                            a.valid_days)
    paths = invoice.save_quote(s, q, dry_run=a.dry_run)
    print(invoice.to_markdown(s, q))
    print(("（試し：保存していません）" if a.dry_run else "保存しました：") + " / ".join(str(p) for p in paths))


def cmd_status(a, s: Store):
    """スマホで読める一言サマリー。"""
    t = _today(a)
    cur = report.pl(s, t.replace(day=1), t)
    ar = invoice.receivables(s, t)
    over = [r for r in ar if r["超過日数"] > 0]
    stale = pipeline.overdue(s, t)
    soon = deadlines.generate(s, t, t + dt.timedelta(days=14))
    cf = cashflow.forecast(s, 3, t)
    fixed = cashflow.monthly_fixed(s)
    print(f"{t:%m/%d} 今月 売上{fmt(cur['売上'])} / 利益{fmt(cur['利益'])}")
    print(f"未入金 {len(ar)}件 {fmt(sum(yen(r['税込金額']) for r in ar))}円" + (f"（⚠期限超過 {len(over)}件）" if over else ""))
    print(f"3か月後の手元資金 {fmt(cf[-1].end_balance)}円" + (f"（固定費{cf[-1].end_balance / fixed:.1f}か月分）" if fixed else ""))
    if stale:
        print(f"止まっている案件 {len(stale)}件：" + "、".join(r["案件名"] for r in stale[:3]))
    if soon:
        print(f"次の期限 {soon[0].date:%m/%d} {soon[0].title}")


def cmd_invoice_paid(a, s: Store):
    r = invoice.mark_paid(s, a.number, dates.parse(a.date) if a.date else _today(a),
                          yen(a.amount) if a.amount else None)
    print(f"入金を記録しました：{r['請求番号']} {r['取引先']} {fmt(yen(r['税込金額']))}円 {r['入金日']}")


def cmd_invoice_list(a, s: Store):
    rows = invoice.receivables(s, _today(a)) if a.unpaid else s.read("sales")
    for r in rows:
        status = "入金済 " + r["入金日"] if r.get("入金日") else "未入金"
        if r.get("超過日数"):
            status += f"（{r['超過日数']}日超過）"
        print(f"{r['請求番号']}  {r['請求日']}  {r['取引先']}  {fmt(yen(r['税込金額']))}円  期限{r['入金予定日']}  {status}")
    if not rows:
        print("なし")


def cmd_expense_add(a, s: Store):
    r = expense.add(s, dates.parse(a.date) if a.date else _today(a), a.payee, a.desc or "", yen(a.amount),
                    a.account, a.method or "", a.voucher or "", a.note or "")
    print(f"記帳しました：{r['日付']} {r['支払先']} {fmt(yen(r['税込金額']))}円 → {r['勘定科目']}")


def cmd_expense_import(a, s: Store):
    added, skipped = expense.import_csv(s, Path(a.file), a.date_col, a.payee_col, a.amount_col, a.method or "",
                                        a.encoding, a.desc_col, a.dry_run)
    for r in added:
        print(f"{r['日付']}  {r['支払先']}  {fmt(yen(r['税込金額']))}円  → {r['勘定科目']}")
    unknown = sum(1 for r in added if r["勘定科目"] == expense.UNKNOWN)
    print(f"{'（試し）' if a.dry_run else ''}追加 {len(added)}件 / 重複でとばした {skipped}件 / 科目が要確認 {unknown}件")


def cmd_deal(a, s: Store):
    fields = {"相手先": a.client, "担当者": a.contact, "段階": a.stage, "見込金額": a.amount,
              "受注確度(%)": a.prob, "次の行動": a.next, "次の行動日": a.next_date, "備考": a.note}
    if a.stage and a.stage not in pipeline.STAGES:
        sys.exit(f"段階は {pipeline.STAGES} のどれかです")
    r = pipeline.upsert(s, a.name, today=_today(a), **fields)
    print(f"保存しました：{r['案件名']}（{r.get('相手先', '')}）段階:{r['段階']} 次:{r.get('次の行動', '')} {r.get('次の行動日', '')}")


def cmd_deals(a, s: Store):
    if a.stale:
        rows = pipeline.overdue(s, _today(a))
        for r in rows:
            late = f"{r['遅れ日数']}日遅れ" if r["遅れ日数"] is not None else "次の行動日なし"
            print(f"{r['案件名']}（{r['相手先']}）{r['段階']}  {r.get('次の行動', '')}  {late}")
        print("なし" if not rows else "")
        return
    for st in pipeline.summary(s):
        if st["件数"]:
            print(f"{st['段階']}: {st['件数']}件  見込 {fmt(st['見込金額'])}円  加重 {fmt(st['加重金額'])}円")


def cmd_report_monthly(a, s: Store):
    if a.month:
        y, m = (int(x) for x in a.month.split("-"))
    else:
        prev = dates.add_months(_today(a).replace(day=1), -1)
        y, m = prev.year, prev.month
    text = report.monthly(s, y, m, _today(a))
    print(text)
    if a.save:
        print(f"保存しました：{_save(s, f'{y:04d}-{m:02d}_monthly.md', text)}")
    if a.kpi:
        r = report.update_kpi(s, y, m, _today(a))
        print(f"KPIを更新しました：{r['月']} 売上{fmt(yen(r['売上']))} 利益{fmt(yen(r['利益']))}")


def cmd_report_weekly(a, s: Store):
    t = _today(a)
    text = report.weekly(s, t)
    print(text)
    if a.save:
        print(f"保存しました：{_save(s, f'{t:%Y-%m-%d}_weekly.md', text)}")


def cmd_cashflow(a, s: Store):
    print(cashflow.to_markdown(s, cashflow.forecast(s, a.months, _today(a))))


def cmd_deadlines(a, s: Store):
    start = dates.parse(a.start) if a.start else _today(a)
    end = dates.parse(a.end) if a.end else dates.add_months(start, 12)
    items = deadlines.generate(s, start, end)
    print(deadlines.to_markdown(items))
    if a.ics:
        Path(a.ics).write_text(deadlines.to_ics(items, s.cfg("company.name", "")), encoding="utf-8", newline="")
        print(f"カレンダー用ファイルを書き出しました：{a.ics}（Googleカレンダーの「設定 → インポート」で取り込めます）")
    if a.save:
        head = (f"# 期限一覧（{start} 〜 {end}）\n\n自動計算した目安。提出前に公式情報・税理士で確認する。"
                "土日祝・年末年始に当たる国税の期限は翌営業日にずらしてある。\n\n")
        p = s.root / "admin" / "deadlines-calendar.md"
        p.write_text(head + deadlines.to_markdown(items), encoding="utf-8")
        print(f"保存しました：{p}")


def cmd_breakeven(a, s: Store):
    fixed = yen(a.fixed) if a.fixed else cashflow.monthly_fixed(s)
    b = simulate.BreakEven(yen(a.price), a.variable_rate, fixed, yen(a.profit or 0), a.hours or 0)
    print(b.to_markdown())


def cmd_check(a, s: Store):
    issues = check.run(s)
    for lvl, where, msg in issues:
        print(f"[{lvl}] {where}: {msg}")
    errors = sum(1 for i in issues if i[0] == "エラー")
    print(f"エラー {errors}件 / 注意 {len(issues) - errors}件" if issues else "問題は見つかりませんでした")
    sys.exit(1 if errors else 0)


def cmd_dashboard(a, s: Store):
    out = Path(a.out) if a.out else s.root / "reports" / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dashboard.build(s, _today(a)), encoding="utf-8")
    print(f"ダッシュボードを書き出しました：{out}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="solo", description="1人会社の台帳・レポート・期限管理ツール")
    p.add_argument("--root", help="データの場所（既定：company/）")
    p.add_argument("--today", help="今日の日付を指定（試算・テスト用）YYYY-MM-DD")
    sub = p.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("invoice", help="請求書").add_subparsers(dest="sub", required=True)
    x = inv.add_parser("new", help="請求書を作り、売上台帳に追加する")
    x.add_argument("--client", required=True, help="取引先名（御中の前）")
    x.add_argument("--item", action="append", default=[], required=True,
                   help="'内容:数量:単価[:税率]'（何度でも指定可）例：'Webサイト制作:1:300000'")
    x.add_argument("--subject", default="", help="件名")
    x.add_argument("--date", help="請求日（既定：今日）")
    x.add_argument("--due", help="支払期限（既定：config の due_rule）")
    x.add_argument("--dry-run", action="store_true", help="保存せずに中身だけ表示")
    x.set_defaults(fn=cmd_invoice_new)
    x = inv.add_parser("paid", help="入金を記録する")
    x.add_argument("number")
    x.add_argument("--date", help="入金日（既定：今日）")
    x.add_argument("--amount", help="実際の入金額（振込手数料が引かれていた場合など）")
    x.set_defaults(fn=cmd_invoice_paid)
    x = inv.add_parser("list", help="請求の一覧")
    x.add_argument("--unpaid", action="store_true", help="未入金だけ")
    x.set_defaults(fn=cmd_invoice_list)

    x = sub.add_parser("quote", help="見積書を作る（sales/quotes/ に保存。台帳には入れない）")
    x.add_argument("--client", required=True)
    x.add_argument("--item", action="append", default=[], required=True, help="'内容:数量:単価[:税率]'")
    x.add_argument("--subject", default="")
    x.add_argument("--date", help="発行日（既定：今日）")
    x.add_argument("--valid-days", type=int, default=30, help="有効期限（日数）")
    x.add_argument("--dry-run", action="store_true")
    x.set_defaults(fn=cmd_quote)

    x = sub.add_parser("status", help="いまの状況を数行で")
    x.set_defaults(fn=cmd_status)

    ex = sub.add_parser("expense", help="経費").add_subparsers(dest="sub", required=True)
    x = ex.add_parser("add", help="経費を1件記帳する（勘定科目は自動判定）")
    x.add_argument("--date")
    x.add_argument("--payee", required=True, help="支払先")
    x.add_argument("--amount", required=True, help="税込金額")
    x.add_argument("--desc", help="内容")
    x.add_argument("--account", help="勘定科目（省略すると自動判定）")
    x.add_argument("--method", help="支払方法（法人カード、口座振替など）")
    x.add_argument("--voucher", help="証憑のファイル名や保管場所")
    x.add_argument("--note")
    x.set_defaults(fn=cmd_expense_add)
    x = ex.add_parser("import", help="カード・銀行の明細CSVを取り込む")
    x.add_argument("file")
    x.add_argument("--date-col", required=True, help="日付の列名")
    x.add_argument("--payee-col", required=True, help="支払先の列名")
    x.add_argument("--amount-col", required=True, help="金額の列名")
    x.add_argument("--desc-col", help="内容の列名")
    x.add_argument("--method", help="支払方法として記録する名前")
    x.add_argument("--encoding", default="utf-8-sig", help="文字コード（銀行のCSVは cp932 が多い）")
    x.add_argument("--dry-run", action="store_true")
    x.set_defaults(fn=cmd_expense_import)

    x = sub.add_parser("deal", help="案件を追加・更新する")
    x.add_argument("name", help="案件名")
    x.add_argument("--client", help="相手先")
    x.add_argument("--contact", help="先方の担当者")
    x.add_argument("--stage", help=f"段階：{' / '.join(pipeline.STAGES)}")
    x.add_argument("--amount", help="見込金額")
    x.add_argument("--prob", help="受注確度(%)")
    x.add_argument("--next", help="次の行動")
    x.add_argument("--next-date", help="次の行動日")
    x.add_argument("--note")
    x.set_defaults(fn=cmd_deal)
    x = sub.add_parser("deals", help="案件の集計")
    x.add_argument("--stale", action="store_true", help="次の行動日が過ぎた案件だけ")
    x.set_defaults(fn=cmd_deals)

    rp = sub.add_parser("report", help="レポート").add_subparsers(dest="sub", required=True)
    x = rp.add_parser("monthly", help="月次締めレポート（既定：先月）")
    x.add_argument("month", nargs="?", help="YYYY-MM")
    x.add_argument("--save", action="store_true", help="reports/ に保存")
    x.add_argument("--kpi", action="store_true", help="strategy/kpi.csv を更新")
    x.set_defaults(fn=cmd_report_monthly)
    x = rp.add_parser("weekly", help="週次経営会議レポート")
    x.add_argument("--save", action="store_true")
    x.set_defaults(fn=cmd_report_weekly)

    x = sub.add_parser("cashflow", help="資金繰りの見通し")
    x.add_argument("--months", type=int, default=3)
    x.set_defaults(fn=cmd_cashflow)

    x = sub.add_parser("deadlines", help="届出・税金の期限を日付で出す")
    x.add_argument("--from", dest="start", help="開始日（既定：今日）")
    x.add_argument("--to", dest="end", help="終了日（既定：12か月後）")
    x.add_argument("--ics", help="カレンダー取り込み用 .ics ファイルの書き出し先")
    x.add_argument("--save", action="store_true", help="admin/deadlines-calendar.md に保存")
    x.set_defaults(fn=cmd_deadlines)

    x = sub.add_parser("breakeven", help="損益分岐点の試算")
    x.add_argument("--price", required=True, help="1件あたりの売上（税抜）")
    x.add_argument("--fixed", help="月の固定費（既定：recurring.csv の合計）")
    x.add_argument("--variable-rate", type=float, default=0.0, help="変動費率 0〜1（例：外注3割なら 0.3）")
    x.add_argument("--profit", help="月の目標利益")
    x.add_argument("--hours", type=float, help="1件あたりの作業時間")
    x.set_defaults(fn=cmd_breakeven)

    x = sub.add_parser("check", help="台帳の点検")
    x.set_defaults(fn=cmd_check)

    x = sub.add_parser("dashboard", help="HTMLダッシュボードを作る")
    x.add_argument("--out", help="書き出し先（既定：reports/dashboard.html）")
    x.set_defaults(fn=cmd_dashboard)
    return p


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    s = Store.open(a.root)
    try:
        a.fn(a, s)
    except (ValueError, KeyError, FileNotFoundError) as e:
        sys.exit(f"エラー：{e}")
