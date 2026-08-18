import unittest

import flet as ft

from frontend.components.app_snackbar import (
    build_snackbar,
    show_snackbar,
)


class FakePage:
    def __init__(
        self,
    ):
        self.dialog = None

    def show_dialog(
        self,
        dialog,
    ):
        self.dialog = dialog


class LegacyFakePage:
    def __init__(
        self,
    ):
        self.snack_bar = None
        self.updated = 0

    def update(
        self,
    ):
        self.updated += 1


class AppSnackbarComponentTest(
    unittest.TestCase
):
    def test_build_success_snackbar(
        self,
    ):
        snackbar = build_snackbar(
            "Archivo descargado",
            severity="success",
        )

        self.assertEqual(
            snackbar.bgcolor,
            "#ECFDF3",
        )

        self.assertEqual(
            snackbar.behavior,
            ft.SnackBarBehavior.FLOATING,
        )

        self.assertTrue(
            snackbar.show_close_icon
        )

        self.assertIsInstance(
            snackbar.content,
            ft.Row,
        )

    def test_build_error_snackbar(
        self,
    ):
        snackbar = build_snackbar(
            "Error",
            severity="error",
        )

        self.assertEqual(
            snackbar.bgcolor,
            "#FEF3F2",
        )

    def test_unknown_severity_falls_back_to_info(
        self,
    ):
        snackbar = build_snackbar(
            "Información",
            severity="UNKNOWN",
        )

        self.assertEqual(
            snackbar.bgcolor,
            "#EFF8FF",
        )

    def test_show_uses_page_show_dialog(
        self,
    ):
        page = FakePage()

        snackbar = show_snackbar(
            page,
            "Descargado",
            severity="success",
        )

        self.assertIs(
            page.dialog,
            snackbar,
        )

    def test_show_has_legacy_fallback(
        self,
    ):
        page = LegacyFakePage()

        snackbar = show_snackbar(
            page,
            "Descargado",
        )

        self.assertIs(
            page.snack_bar,
            snackbar,
        )

        self.assertTrue(
            snackbar.open
        )

        self.assertEqual(
            page.updated,
            1,
        )


if __name__ == "__main__":
    unittest.main()
