import unittest

import flet as ft

from frontend.components.app_autocomplete import (
    AppAutocomplete,
)


class DummyPage:
    def __init__(self):
        self.update_calls = 0

    def update(self):
        self.update_calls += 1


class AppAutocompleteContractTests(unittest.TestCase):
    def setUp(self):
        self.page = DummyPage()

    def test_legacy_constructor_still_works(self):
        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            ["Juan", "Ana"],
        )

        self.assertIsNotNone(
            autocomplete.control
        )

        self.assertIsNotNone(
            autocomplete.input
        )

        self.assertTrue(
            callable(autocomplete.select)
        )

    def test_uses_native_editable_dropdown(self):
        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            ["Juan"],
        )

        self.assertIsInstance(
            autocomplete.dropdown,
            ft.Dropdown,
        )

        self.assertTrue(
            autocomplete.dropdown.editable
        )

    def test_optional_icon_is_supported(self):
        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            ["Juan"],
            icon=ft.Icons.PERSON_OUTLINE,
        )

        self.assertEqual(
            autocomplete.dropdown.leading_icon,
            ft.Icons.PERSON_OUTLINE,
        )

    def test_legacy_input_value_proxy(self):
        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            ["Juan", "Ana"],
        )

        autocomplete.input.value = "Ana"

        self.assertEqual(
            autocomplete.input.value,
            "Ana",
        )

        self.assertEqual(
            autocomplete.get_value(),
            "Ana",
        )

    def test_legacy_input_label_proxy(self):
        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            ["Juan"],
        )

        autocomplete.input.label = "Cliente pagador"

        self.assertEqual(
            autocomplete.dropdown.label,
            "Cliente pagador",
        )

    def test_legacy_input_error_proxy(self):
        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            ["Juan"],
        )

        autocomplete.input.error_text = "Obligatorio"

        self.assertEqual(
            autocomplete.dropdown.error_text,
            "Obligatorio",
        )

    def test_search_remains_accent_insensitive(self):
        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            [
                "María García",
                "Mohamed Ali",
            ],
        )

        matches = autocomplete._matches(
            "maria"
        )

        self.assertEqual(
            matches,
            ["María García"],
        )

    def test_structured_options_keep_subtitle(self):
        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            [
                {
                    "id": 1,
                    "label": "Juan Pérez",
                    "subtitle": "NIE X1234567L",
                }
            ],
        )

        option = autocomplete.dropdown.options[0]

        self.assertIsInstance(
            option.content,
            ft.Column,
        )

        self.assertEqual(
            option.content.controls[0].tooltip,
            "Juan Pérez",
        )

        self.assertEqual(
            option.content.controls[1].tooltip,
            "NIE X1234567L",
        )

    def test_menu_height_shrinks_with_results(self):
        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            [
                "Ana",
                "Ana María",
                "Juan",
                "Pedro",
            ],
            max_results=8,
        )

        autocomplete._set_dropdown_options(
            autocomplete.options,
            typed="Ana María",
            show_all=False,
        )

        self.assertEqual(
            len(autocomplete.dropdown.options),
            1,
        )

        self.assertEqual(
            autocomplete.dropdown.menu_height,
            42,
        )

    def test_menu_height_is_capped_by_max_results(self):
        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            [
                f"Cliente {number}"
                for number in range(30)
            ],
            max_results=4,
        )

        autocomplete._set_dropdown_options(
            autocomplete.options,
            typed="Cliente",
            show_all=False,
        )

        self.assertEqual(
            autocomplete.dropdown.menu_height,
            4 * 42,
        )

    def test_select_contract_is_preserved(self):
        selected = []

        autocomplete = AppAutocomplete(
            self.page,
            "Cliente",
            ["Juan Pérez"],
            on_select=selected.append,
        )

        option = autocomplete.dropdown.options[0]
        autocomplete.select(
            autocomplete._key_to_option[option.key]
        )

        self.assertEqual(
            autocomplete.get_value(),
            "Juan Pérez",
        )

        self.assertEqual(
            selected,
            ["Juan Pérez"],
        )


if __name__ == "__main__":
    unittest.main()
