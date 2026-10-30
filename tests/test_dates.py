import datetime as dt
import unittest

import helpers  # noqa: F401
from solo import dates

D = dt.date


class HolidayTest(unittest.TestCase):
    def test_2026_holidays_match_official_list(self):
        # 内閣府「国民の祝日」2026年
        expected = {
            D(2026, 1, 1), D(2026, 1, 12), D(2026, 2, 11), D(2026, 2, 23), D(2026, 3, 20),
            D(2026, 4, 29), D(2026, 5, 3), D(2026, 5, 4), D(2026, 5, 5), D(2026, 5, 6),
            D(2026, 7, 20), D(2026, 8, 11), D(2026, 9, 21), D(2026, 9, 22), D(2026, 9, 23),
            D(2026, 10, 12), D(2026, 11, 3), D(2026, 11, 23),
        }
        self.assertEqual(set(dates.holidays(2026)), expected)

    def test_substitute_holiday(self):
        self.assertEqual(dates.holidays(2025)[D(2025, 2, 24)], "振替休日")
        self.assertEqual(dates.holidays(2027)[D(2027, 3, 22)], "振替休日")

    def test_add_months_clamps_day(self):
        self.assertEqual(dates.add_months(D(2026, 1, 31), 1), D(2026, 2, 28))
        self.assertEqual(dates.add_months(D(2028, 1, 31), 1), D(2028, 2, 29))
        self.assertEqual(dates.add_months(D(2026, 11, 2), 2), D(2027, 1, 2))
        self.assertEqual(dates.add_months(D(2026, 3, 15), -3), D(2025, 12, 15))

    def test_tax_due_skips_weekend_holiday_and_new_year(self):
        self.assertEqual(dates.tax_due(D(2026, 12, 31)), D(2027, 1, 4))   # 年末年始
        self.assertEqual(dates.tax_due(D(2027, 1, 31)), D(2027, 2, 1))    # 日曜
        self.assertEqual(dates.tax_due(D(2026, 5, 4)), D(2026, 5, 7))     # GW
        self.assertEqual(dates.tax_due(D(2026, 11, 30)), D(2026, 11, 30)) # 平日はそのまま

    def test_parse_formats(self):
        self.assertEqual(dates.parse("2026/1/5"), D(2026, 1, 5))
        with self.assertRaises(ValueError):
            dates.parse("")


if __name__ == "__main__":
    unittest.main()
