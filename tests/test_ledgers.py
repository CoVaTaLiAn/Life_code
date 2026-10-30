import datetime as dt
import unittest

from helpers import make_store
from solo import cashflow, check, contracts, expense, pipeline, report, simulate

D = dt.date


class ExpenseTest(unittest.TestCase):
    def setUp(self):
        self.s = make_store()

    def test_classify_prefers_longer_keyword(self):
        self.s.write("account_rules", [{"キーワード": "Google", "勘定科目": "通信費"},
                                       {"キーワード": "Google 広告", "勘定科目": "広告宣伝費"}])
        self.assertEqual(expense.classify(self.s, "GOOGLE 広告 11月"), "広告宣伝費")
        self.assertEqual(expense.classify(self.s, "google workspace"), "通信費")
        self.assertEqual(expense.classify(self.s, "謎の店"), expense.UNKNOWN)

    def test_import_dedupes_and_skips_refunds(self):
        p = self.s.root / "inbox" / "card.csv"
        p.write_text("日付,店,金額\n2026/11/05,AWS,1200\n2026/11/06,返金,-500\n2026/11/07,謎の店,\"3,300\"\n",
                     encoding="cp932")
        added, skipped = expense.import_csv(self.s, p, "日付", "店", "金額", encoding="cp932")
        self.assertEqual(len(added), 2)
        self.assertEqual(added[1]["税込金額"], "3300")
        added, skipped = expense.import_csv(self.s, p, "日付", "店", "金額", encoding="cp932")
        self.assertEqual((len(added), skipped), (0, 2))

    def test_import_skips_preamble_rows(self):
        p = self.s.root / "inbox" / "bank.csv"
        p.write_text("口座番号,1234567\n期間,2026年11月\n取引日,摘要,出金,入金\n"
                     "2026年11月5日,ｶ)ｻﾝﾌﾟﾙ,5500,\n2026年11月6日,振込入金,,100000\n", encoding="cp932")
        added, _ = expense.import_csv(self.s, p, "取引日", "摘要", "出金", encoding="cp932", skip_rows=2)
        self.assertEqual([(r["日付"], r["税込金額"]) for r in added], [("2026-11-05", "5500")])

    def test_import_reports_missing_columns(self):
        p = self.s.root / "inbox" / "bad.csv"
        p.write_text("a,b\n1,2\n", encoding="utf-8")
        with self.assertRaises(KeyError):
            expense.import_csv(self.s, p, "日付", "店", "金額")

    def test_tax_estimate_only_when_taxable(self):
        self.assertEqual(expense.tax_estimate(self.s, 11000), "")
        s2 = make_store(taxable=True)
        self.assertEqual(expense.tax_estimate(s2, 11000), "1000")


class CashflowTest(unittest.TestCase):
    def test_forecast(self):
        s = make_store(balance=1_000_000, as_of="2026-11-01")
        s.write("recurring", [
            {"名前": "役員報酬", "金額": "300000", "頻度": "monthly", "支払日": "25", "開始": "2026-11-01"},
            {"名前": "均等割", "金額": "70000", "頻度": "yearly", "支払日": "31", "支払月": "12", "開始": "2026-11-01"},
        ])
        s.write("sales", [
            {"請求番号": "1", "請求日": "2026-11-10", "取引先": "A", "税込金額": "550000", "入金予定日": "2026-12-31"},
            {"請求番号": "2", "請求日": "2026-10-01", "取引先": "B", "税込金額": "110000", "入金予定日": "2026-11-05"},
        ])
        s.write("expenses", [{"日付": "2026-11-03", "支払先": "X", "税込金額": "20000", "勘定科目": "通信費"}])
        rows = cashflow.forecast(s, 2, D(2026, 11, 10))
        by = {m.ym: m for m in rows}
        nov, dec = by["2026-11"], by["2026-12"]
        self.assertEqual((nov.actual_out, nov.overdue_in, nov.expected_out), (20000, 110000, 300000))
        self.assertEqual(nov.end_balance, 1_000_000 - 20000 + 110000 - 300000)
        self.assertEqual((dec.expected_in, dec.expected_out), (550000, 370000))
        self.assertEqual(dec.end_balance, nov.end_balance + 550000 - 370000)
        self.assertEqual(cashflow.monthly_fixed(s), 300000 + 70000 // 12)

    def test_month_end_day_clamped(self):
        s = make_store()
        s.write("recurring", [{"名前": "x", "金額": "1", "頻度": "monthly", "支払日": "31", "開始": "2026-01-01"}])
        got = cashflow.recurring_on(s, D(2027, 2, 1), D(2027, 2, 28))
        self.assertEqual(got[0][0], D(2027, 2, 28))


class PipelineTest(unittest.TestCase):
    def test_summary_and_overdue(self):
        s = make_store()
        pipeline.upsert(s, "A", 相手先="a", 段階="提案", 見込金額=100000, **{"受注確度(%)": 50}, 次の行動日="2026-11-01")
        pipeline.upsert(s, "B", 相手先="b", 段階="受注", 見込金額=200000, **{"受注確度(%)": 100})
        pipeline.upsert(s, "C", 相手先="c", 段階="商談", 次の行動日="2026-12-01")
        summ = {x["段階"]: x for x in pipeline.summary(s)}
        self.assertEqual(summ["提案"]["加重金額"], 50000)
        stale = pipeline.overdue(s, D(2026, 11, 10))
        self.assertEqual([r["案件名"] for r in stale], ["A"])
        self.assertEqual(stale[0]["遅れ日数"], 9)
        pipeline.upsert(s, "A", 段階="受注")
        self.assertEqual(len(s.read("pipeline")), 3)

    def test_rejects_unknown_stage(self):
        with self.assertRaises(ValueError):
            pipeline.upsert(make_store(), "X", 段階="謎")


class ReportTest(unittest.TestCase):
    def test_fiscal_start_respects_founding(self):
        s = make_store(founded="2026-11-02", fye=10)
        self.assertEqual(report.fiscal_start(s, D(2027, 3, 1)), D(2026, 11, 2))
        self.assertEqual(report.fiscal_start(s, D(2027, 11, 5)), D(2027, 11, 1))

    def test_monthly_and_weekly_render(self):
        s = make_store()
        s.write("sales", [{"請求番号": "INV-1", "請求日": "2026-11-30", "取引先": "A", "税抜金額": "100000",
                           "消費税": "10000", "税込金額": "110000", "入金予定日": "2026-12-31"}])
        s.write("expenses", [{"日付": "2026-11-05", "支払先": "X", "勘定科目": "通信費", "税込金額": "10000", "証憑": "あり"}])
        text = report.monthly(s, 2026, 11, D(2026, 12, 3))
        self.assertIn("利益 100,000円", text)
        self.assertIn("売上の100%が「A」", text)
        row = report.update_kpi(s, 2026, 11, D(2026, 12, 3))
        self.assertEqual(row["利益"], "100000")
        self.assertIn("今週やること", report.weekly(s, D(2026, 12, 3)))


class ContractTest(unittest.TestCase):
    def test_upcoming_ignores_text_dates(self):
        s = make_store()
        s.write("contracts", [
            {"相手先": "A", "契約名": "x", "解約予告期限": "2026-12-01"},
            {"相手先": "B", "契約名": "y", "解約予告期限": "終了の1か月前", "終了日": "2026-11-20"},
            {"相手先": "C", "契約名": "z", "終了日": "2027-06-01"},
        ])
        got = contracts.upcoming(s, D(2026, 11, 10), 45)
        self.assertEqual([r["相手先"] for r in got], ["A", "B"])


class CheckTest(unittest.TestCase):
    def test_finds_problems(self):
        s = make_store()
        s.write("sales", [
            {"請求番号": "1", "請求日": "2026-11-01", "取引先": "A", "税抜金額": "100", "消費税": "10", "税込金額": "111"},
            {"請求番号": "1", "請求日": "2026/13/01", "取引先": "A", "税抜金額": "1", "消費税": "0", "税込金額": "1"},
        ])
        s.write("expenses", [
            {"日付": "2026-11-01", "支払先": "X", "勘定科目": "要確認", "税込金額": "100", "証憑": ""},
            {"日付": "2026-11-01", "支払先": "X", "勘定科目": "要確認", "税込金額": "100", "証憑": ""},
            {"日付": "2026-11-02", "支払先": "PC", "勘定科目": "消耗品費", "税込金額": "150000", "証憑": "あり"},
        ])
        msgs = "\n".join(m for _, _, m in check.run(s))
        for needle in ("税込と合いません", "2回あります", "日付になっていません", "二重記帳", "勘定科目が未確定",
                       "証憑", "資産計上"):
            self.assertIn(needle, msgs)

    def test_clean_store_passes(self):
        self.assertEqual([i for i in check.run(make_store()) if i[0] == "エラー"], [])


class BreakEvenTest(unittest.TestCase):
    def test_units(self):
        b = simulate.BreakEven(price=100000, variable_rate=0.2, fixed=400000, target_profit=100000)
        self.assertEqual(b.units, 7)  # 500000 / 80000 = 6.25 → 7
        with self.assertRaises(ValueError):
            _ = simulate.BreakEven(100, 1.0, 1000).units
        self.assertEqual(simulate.runway(1_000_000, 400_000, 150_000), 4.0)


if __name__ == "__main__":
    unittest.main()
