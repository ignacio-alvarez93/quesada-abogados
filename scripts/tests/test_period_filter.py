import unittest
from datetime import datetime

from frontend.components.period_filter import (
    PERIOD_ALL,
    PERIOD_CUSTOM,
    PERIOD_LAST_7_DAYS,
    PERIOD_LAST_30_DAYS,
    PERIOD_TODAY,
    resolve_period,
)


class PeriodFilterTest(
    unittest.TestCase
):
    def setUp(self):
        self.now = datetime(
            2026,
            7,
            30,
            10,
            30,
            0,
        )

    def test_all_has_no_limits(self):
        result = resolve_period(
            PERIOD_ALL,
            now=self.now,
        )

        self.assertEqual(
            result["date_from"],
            "",
        )
        self.assertEqual(
            result["date_to"],
            "",
        )

    def test_today(self):
        result = resolve_period(
            PERIOD_TODAY,
            now=self.now,
        )

        self.assertEqual(
            result["date_from"],
            "2026-07-30 00:00:00",
        )
        self.assertEqual(
            result["date_to"],
            "2026-07-30 23:59:59",
        )

    def test_last_7_days_includes_today(self):
        result = resolve_period(
            PERIOD_LAST_7_DAYS,
            now=self.now,
        )

        self.assertEqual(
            result["date_from"],
            "2026-07-24 00:00:00",
        )
        self.assertEqual(
            result["date_to"],
            "2026-07-30 23:59:59",
        )

    def test_last_30_days_includes_today(self):
        result = resolve_period(
            PERIOD_LAST_30_DAYS,
            now=self.now,
        )

        self.assertEqual(
            result["date_from"],
            "2026-07-01 00:00:00",
        )
        self.assertEqual(
            result["date_to"],
            "2026-07-30 23:59:59",
        )

    def test_custom_range(self):
        result = resolve_period(
            PERIOD_CUSTOM,
            custom_from="10/07/2026",
            custom_to="20/07/2026",
            now=self.now,
        )

        self.assertEqual(
            result["date_from"],
            "2026-07-10 00:00:00",
        )
        self.assertEqual(
            result["date_to"],
            "2026-07-20 23:59:59",
        )

    def test_custom_open_range(self):
        result = resolve_period(
            PERIOD_CUSTOM,
            custom_from="",
            custom_to="20/07/2026",
            now=self.now,
        )

        self.assertEqual(
            result["date_from"],
            "",
        )
        self.assertEqual(
            result["date_to"],
            "2026-07-20 23:59:59",
        )

    def test_rejects_invalid_range(self):
        with self.assertRaises(
            ValueError
        ):
            resolve_period(
                PERIOD_CUSTOM,
                custom_from="21/07/2026",
                custom_to="20/07/2026",
                now=self.now,
            )


if __name__ == "__main__":
    unittest.main()
