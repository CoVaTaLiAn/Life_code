import datetime as dt
import unittest

from helpers import make_store
from solo import invoice

D = dt.date


class InvoiceTest(unittest.TestCase):
    def setUp(self):
        self.s = make_store()

    def test_tax_rounded_once_per_rate(self):
        # 1品目ずつ端数処理すると 33+33+33=99 だが、税率ごとに1回なら 333*3*10% = 99.9 → 99
        inv = invoice.build(self.s, "A社", ["a:1:333", "b:1:333", "c:1:333"], D(2026, 11, 10))
        self.assertEqual((inv.subtotal, inv.tax, inv.total), (999, 99, 1098))

    def test_mixed_rates(self):
        inv = invoice.build(self.s, "A社", ["制作:1:350000", "菓子:2:1500:8"], D(2026, 11, 10))
        self.assertEqual(inv.by_rate, {10: (350000, 35000), 8: (3000, 240)})
        self.assertEqual(inv.total, 388240)

    def test_numbering_and_due_date(self):
        a = invoice.build(self.s, "A社", ["x:1:1000"], D(2026, 11, 10))
        self.assertEqual(a.number, "INV-202611-001")
        self.assertEqual(a.due_date, D(2026, 12, 31))
        invoice.issue(self.s, a)
        b = invoice.build(self.s, "B社", ["x:1:1000"], D(2026, 11, 20))
        self.assertEqual(b.number, "INV-202611-002")
        c = invoice.build(self.s, "C社", ["x:1:1000"], D(2027, 1, 31))
        self.assertEqual(c.number, "INV-202701-001")
        self.assertEqual(c.due_date, D(2027, 2, 28))

    def test_days_rule(self):
        self.assertEqual(invoice.due_date(D(2026, 11, 10), "days:30"), D(2026, 12, 10))

    def test_issue_writes_files_and_ledger(self):
        inv = invoice.build(self.s, "A社", ["x:2:5000"], D(2026, 11, 10), subject="テスト")
        md, html = invoice.issue(self.s, inv)
        self.assertTrue(md.exists() and html.exists())
        self.assertIn("¥11,000", md.read_text(encoding="utf-8"))
        row = self.s.read("sales")[0]
        self.assertEqual((row["税抜金額"], row["消費税"], row["税込金額"]), ("10000", "1000", "11000"))

    def test_html_escapes_client_name(self):
        inv = invoice.build(self.s, "<script>", ["x:1:1"], D(2026, 11, 10))
        self.assertNotIn("<script>", invoice.to_html(self.s, inv))

    def test_mark_paid_and_receivables(self):
        invoice.issue(self.s, invoice.build(self.s, "A社", ["x:1:10000"], D(2026, 11, 10)))
        ar = invoice.receivables(self.s, D(2027, 1, 5))
        self.assertEqual(ar[0]["超過日数"], 5)
        r = invoice.mark_paid(self.s, "INV-202611-001", D(2027, 1, 6), amount=10560)
        self.assertIn("差額440円", r["備考"])
        self.assertEqual(invoice.receivables(self.s, D(2027, 1, 7)), [])
        with self.assertRaises(ValueError):
            invoice.mark_paid(self.s, "INV-202611-001", D(2027, 1, 7))

    def test_bad_item_spec(self):
        with self.assertRaises(ValueError):
            invoice.Item.parse("内容だけ")
        with self.assertRaises(ValueError):
            invoice.Item.parse("x:1:100:5")
        self.assertEqual(invoice.Item.parse(r"A\:B:1:100").name, "A:B")


if __name__ == "__main__":
    unittest.main()
