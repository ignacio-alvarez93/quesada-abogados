import unittest

from frontend.views.calls_view import (
    _format_timestamp,
)


class CallsViewTimezoneTest(
    unittest.TestCase
):
    def test_sqlite_naive_utc_is_shown_in_madrid_summer_time(
        self,
    ):
        self.assertEqual(
            _format_timestamp(
                "2026-08-16 15:03:30"
            ),
            "16/08/2026 17:03",
        )


    def test_explicit_utc_offset_is_converted(
        self,
    ):
        self.assertEqual(
            _format_timestamp(
                "2026-08-16T15:09:00+00:00"
            ),
            "16/08/2026 17:09",
        )


    def test_provider_madrid_offset_is_not_double_shifted(
        self,
    ):
        self.assertEqual(
            _format_timestamp(
                "2026-08-16T17:09:00+02:00"
            ),
            "16/08/2026 17:09",
        )


    def test_winter_uses_cet_not_fixed_plus_two(
        self,
    ):
        self.assertEqual(
            _format_timestamp(
                "2026-12-16 15:00:00"
            ),
            "16/12/2026 16:00",
        )


    def test_empty_value_is_dash(
        self,
    ):
        self.assertEqual(
            _format_timestamp(None),
            "—",
        )


    def test_unknown_text_is_preserved(
        self,
    ):
        self.assertEqual(
            _format_timestamp(
                "fecha-provider-desconocida"
            ),
            "fecha-provider-desconocida",
        )


if __name__ == "__main__":
    unittest.main()
