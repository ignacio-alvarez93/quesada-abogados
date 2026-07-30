import unittest
from datetime import datetime
from unittest.mock import patch

from frontend.components.period_filter import (
    PERIOD_ALL,
    PERIOD_LAST_7_DAYS,
    build_period_filter,
)


class FakePage:
    def __init__(self):
        self.overlay = []
        self.update_count = 0

    def update(self):
        self.update_count += 1


class PeriodFilterAutocompleteTest(
    unittest.TestCase
):
    def test_selects_last_7_days(self):
        page = FakePage()
        results = []

        with patch(
            "frontend.components.period_filter."
            "datetime"
        ) as mocked_datetime:
            mocked_datetime.now.return_value = (
                datetime(
                    2026,
                    7,
                    30,
                    10,
                    0,
                    0,
                )
            )
            mocked_datetime.strptime = (
                datetime.strptime
            )

            component = build_period_filter(
                page,
                on_change=results.append,
            )

            component.select(
                {
                    "id": PERIOD_LAST_7_DAYS,
                    "label": "Últimos 7 días",
                }
            )

        self.assertEqual(
            component.get_period_value(),
            PERIOD_LAST_7_DAYS,
        )
        self.assertEqual(
            results[-1]["value"],
            PERIOD_LAST_7_DAYS,
        )
        self.assertEqual(
            results[-1]["date_from"],
            "2026-07-24 00:00:00",
        )
        self.assertEqual(
            results[-1]["date_to"],
            "2026-07-30 23:59:59",
        )

    def test_can_reset_to_all(self):
        page = FakePage()

        component = build_period_filter(
            page,
            initial_value=(
                PERIOD_LAST_7_DAYS
            ),
        )

        component.set_period_value(
            PERIOD_ALL,
            update=False,
        )

        self.assertEqual(
            component.get_period_value(),
            PERIOD_ALL,
        )
        self.assertEqual(
            component.get_value(),
            "Todas",
        )


if __name__ == "__main__":
    unittest.main()
