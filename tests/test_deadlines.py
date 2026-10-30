import datetime as dt
import unittest

from helpers import make_store
from solo import deadlines

D = dt.date


def by_title(items, part):
    hits = [d for d in items if part in d.title]
    assert hits, f"{part} が見つからない: {[d.title for d in items]}"
    return hits


class DeadlineTest(unittest.TestCase):
    def test_founding_filings(self):
        s = make_store(founded="2026-11-02", fye=10)
        items = deadlines.generate(s, D(2026, 11, 1), D(2028, 3, 31))
        self.assertEqual(by_title(items, "新規適用届")[0].date, D(2026, 11, 7))
        self.assertEqual(by_title(items, "給与支払事務所")[0].date, D(2026, 12, 2))
        setup = by_title(items, "法人設立届出書")[0]
        self.assertEqual((setup.original, setup.date), (D(2027, 1, 2), D(2027, 1, 4)))
        self.assertEqual(by_title(items, "青色申告")[0].date, D(2027, 2, 1))

    def test_blue_return_capped_by_short_first_year(self):
        # 3/1設立・3月決算 → 1期目は1か月。期限は 3/31 の前日
        s = make_store(founded="2026-03-01", fye=3)
        items = deadlines.generate(s, D(2026, 3, 1), D(2026, 12, 31))
        self.assertEqual(by_title(items, "青色申告")[0].date, D(2026, 3, 30))

    def test_corporate_tax_due_two_months_after_year_end(self):
        s = make_store(founded="2026-04-01", fye=3)
        items = deadlines.generate(s, D(2026, 4, 1), D(2027, 12, 31))
        tax = by_title(items, "法人税")[0]
        self.assertEqual(tax.date, D(2027, 5, 31))
        self.assertFalse(by_title(items, "決算公告") == [])

    def test_godo_has_no_public_notice_or_officer_term(self):
        s = make_store(founded="2026-04-01", fye=3, type_="合同会社")
        items = deadlines.generate(s, D(2026, 4, 1), D(2040, 12, 31))
        self.assertFalse(any("決算公告" in d.title for d in items))
        self.assertFalse(any("重任登記" in d.title for d in items))
        self.assertTrue(any("社員総会" in d.title for d in items))

    def test_withholding_special_vs_monthly(self):
        s = make_store(special=True)
        items = deadlines.generate(s, D(2027, 1, 1), D(2027, 12, 31))
        self.assertEqual(len(by_title(items, "源泉所得税の納付")), 2)
        s2 = make_store(special=False)
        items2 = deadlines.generate(s2, D(2027, 1, 1), D(2027, 12, 31))
        self.assertGreaterEqual(len(by_title(items2, "源泉所得税の納付")), 11)

    def test_consumption_tax_only_when_taxable(self):
        s = make_store(founded="2026-04-01", fye=3, taxable=True)
        items = deadlines.generate(s, D(2026, 4, 1), D(2027, 12, 31))
        self.assertTrue(by_title(items, "消費税の申告"))

    def test_ics_format(self):
        s = make_store()
        ics = deadlines.to_ics(deadlines.generate(s, D(2026, 11, 1), D(2027, 3, 31)), "テスト")
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertEqual(ics.count("BEGIN:VEVENT"), ics.count("END:VEVENT"))
        self.assertIn("DTSTART;VALUE=DATE:20261107", ics)
        self.assertIn("TRIGGER:-P7D", ics)


if __name__ == "__main__":
    unittest.main()
