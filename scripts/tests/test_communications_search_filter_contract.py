from pathlib import Path


SOURCE = Path(
    "frontend/views/communications_view.py"
).read_text(
    encoding="utf-8"
)


def test_search_is_bound_to_on_change():
    assert (
        "search_input.on_change = (\n"
        "            set_search_filter\n"
        "        )"
        in SOURCE
    )


def test_search_does_not_use_backend_filter():
    assert SOURCE.count(
        'search="",'
    ) >= 2


def test_search_handler_only_refreshes_sidebar():
    start = SOURCE.index(
        "    def set_search_filter("
    )
    end = SOURCE.index(
        "\n    def clear_filters(",
        start,
    )

    block = SOURCE[start:end]

    assert (
        "_refresh_conversation_list_control()"
        in block
    )

    assert "load_data(" not in block
    assert "refresh()" not in block
    assert "_safe_update()" not in block


def test_search_preserves_input_control():
    start = SOURCE.index(
        "    def set_search_filter("
    )
    end = SOURCE.index(
        "\n    def clear_filters(",
        start,
    )

    block = SOURCE[start:end]

    assert "search_input =" not in block
    assert "build_filters(" not in block


def test_local_filter_combines_search_and_unread():
    start = SOURCE.index(
        "    def _filtered_conversation_items("
    )
    end = SOURCE.index(
        "\n    def _visible_conversation_items(",
        start,
    )

    block = SOURCE[start:end]

    assert "_conversation_matches_search(" in block
    assert '"unread_only"' in block


def test_phone_search_uses_digits():
    assert (
        "def _conversation_search_digits("
        in SOURCE
    )

    assert (
        "query_digits"
        in SOURCE
    )

    assert (
        "query_digits\n"
        "            in phone_haystack"
        in SOURCE
    )


def test_search_is_accent_and_case_insensitive():
    assert (
        "unicodedata.normalize("
        in SOURCE
    )

    assert (
        ".casefold()"
        in SOURCE
    )


def test_search_button_removed():
    assert (
        'secondary_button(\n'
        '                        "Buscar",'
        not in SOURCE
    )


def test_communications_filters_use_app_autocomplete():
    assert (
        "channel_filter = AppAutocomplete("
        in SOURCE
    )

    assert (
        "linkage_filter = AppAutocomplete("
        in SOURCE
    )

    assert "ft.Dropdown(" not in SOURCE
