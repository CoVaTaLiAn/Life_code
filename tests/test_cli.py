"""コマンドを実際に動かす通しのテスト。"""

import contextlib
import datetime as dt
import io
import unittest

from helpers import make_store
from solo import cashflow, invoice
from solo.cli import main


def run(store, *args) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            main(["--root", str(store.root), *args])
        except SystemExit as e:
            if e.code not in (0, None):
                raise AssertionError(f"終了コード {e.code}: {buf.getvalue()}")
    return buf.getvalue()


class CliFlowTest(unittest.TestCase):
    def test_full_month(self):
        s = make_store(founded="2026-11-02", fye=10, balance=2_000_000, as_of="2026-11-02")
        s.write("recurring", [{"名前": "役員報酬", "金額": "300000", "頻度": "monthly", "支払日": "25",
                               "開始": "2026-11-01"}])
        run(s, "--today", "2026-11-05", "deal", "A社 支援", "--client", "A社", "--stage", "商談",
            "--amount", "400000", "--prob", "50", "--next", "提案書", "--next-date", "2026-11-10")
        out = run(s, "--today", "2026-11-30", "quote", "--client", "A社", "--item", "支援:1:400000")
        self.assertIn("お見積金額：¥440,000", out)
        self.assertNotIn("お振込先", out)
        run(s, "--today", "2026-11-30", "deal", "A社 支援", "--stage", "受注", "--prob", "100")
        out = run(s, "--today", "2026-11-30", "invoice", "new", "--client", "A社", "--item", "支援:1:400000")
        self.assertIn("INV-202611-001", out)
        run(s, "expense", "add", "--date", "2026-11-25", "--payee", "代表者", "--amount", "300000",
            "--account", "役員報酬", "--voucher", "給与台帳")
        run(s, "expense", "add", "--date", "2026-11-10", "--payee", "AWS", "--amount", "1200", "--voucher", "mail")

        self.assertIn("問題は見つかりませんでした", run(s, "check"))
        out = run(s, "--today", "2026-12-03", "report", "monthly", "2026-11", "--save", "--kpi")
        self.assertIn("利益 138,800円", out)
        self.assertTrue((s.root / "reports" / "2026-11_monthly.md").exists())
        kpi = s.read("kpi")[0]
        self.assertEqual((kpi["受注数"], kpi["手元資金"]), ("1", str(2_000_000 - 301_200)))

        run(s, "invoice", "paid", "INV-202611-001", "--date", "2026-12-28")
        self.assertEqual(invoice.receivables(s, dt.date(2026, 12, 29)), [])
        self.assertEqual(cashflow.balance_at(s, dt.date(2026, 12, 31)), 2_000_000 - 301_200 + 440_000)

        out = run(s, "--today", "2026-12-03", "status")
        self.assertIn("未入金", out)
        out = run(s, "--today", "2026-12-03", "dashboard")
        self.assertTrue((s.root / "reports" / "dashboard.html").exists())
        out = run(s, "--today", "2026-11-03", "deadlines", "--ics", str(s.root / "reports" / "d.ics"))
        self.assertIn("法人設立届出書", out)

    def test_quote_numbering(self):
        s = make_store()
        run(s, "--today", "2026-11-30", "quote", "--client", "A", "--item", "x:1:100")
        out = run(s, "--today", "2026-11-30", "quote", "--client", "B", "--item", "x:1:100")
        self.assertIn("Q-202611-002", out)
        self.assertEqual(s.read("sales"), [])

    def test_bad_input_exits_with_message(self):
        s = make_store()
        with self.assertRaises(AssertionError):
            run(s, "invoice", "new", "--client", "A", "--item", "壊れた品目")
        with self.assertRaises(AssertionError):
            run(s, "deal", "X", "--stage", "謎")

    def test_csv_written_with_bom_for_excel(self):
        s = make_store()
        run(s, "expense", "add", "--date", "2026-11-10", "--payee", "AWS", "--amount", "1200")
        self.assertTrue(s.path("expenses").read_bytes().startswith(b"\xef\xbb\xbf"))


if __name__ == "__main__":
    unittest.main()
