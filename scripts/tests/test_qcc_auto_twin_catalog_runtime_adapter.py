from pathlib import Path
import json


from backend.qcc.auto_twin.catalog_runtime_adapter import (
    AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_VERSION,
    catalog_runtime_adapter_source,
    inject_catalog_runtime_adapter,
)


ROOT = Path(__file__).resolve().parents[2]

BUILDER = (
    ROOT
    / "backend"
    / "qcc"
    / "auto_twin"
    / "materialization_builder.py"
)


def payload():
    return {
        "schema_version":
            1,

        "pathname":
            "/example",

        "catalog_count":
            2,

        "option_count":
            2,

        "catalogs": [
            {
                "catalog_key":
                    "main::#alpha",

                "catalog_type":
                    "custom_select",

                "selector":
                    "#alpha",

                "state": {
                    "selected_label":
                        "Uno",

                    "selected_value":
                        "1",

                    "selected_index":
                        0,
                },

                "options": [
                    {
                        "label":
                            "Uno",

                        "value":
                            "1",

                        "selected":
                            True,

                        "disabled":
                            False,
                    },

                    {
                        "label":
                            "Dos",

                        "value":
                            "",

                        "selected":
                            False,

                        "disabled":
                            False,
                    },
                ],
            },

            {
                "catalog_key":
                    "main::#dynamic",

                "catalog_type":
                    "custom_select",

                "selector":
                    "#dynamic",

                "state": {
                    "selected_label":
                        "",

                    "selected_value":
                        "",

                    "selected_index":
                        -1,
                },

                "options":
                    [],
            },
        ],
    }


def test_adapter_version_is_explicit():
    assert (
        AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_VERSION
        == 2
    )


def test_adapter_is_network_free_and_provider_neutral():
    source = (
        catalog_runtime_adapter_source()
    )

    lowered = (
        source.lower()
    )

    for forbidden in (
        "fetch(",
        "xmlhttprequest",
        "redsara",
        "red_sara",
        "mercurio",
        "dnt-select",
        "represented.",
        "#country",
        "#tipodoc",
    ):
        assert (
            forbidden
            not in lowered
        )


def test_adapter_uses_generic_accessibility_surface():
    source = (
        catalog_runtime_adapter_source()
    )

    assert (
        '[role="combobox"]'
        in source
    )

    assert (
        '[role="option"]'
        in source
    )

    assert (
        "shadowRoot"
        in source
    )

    assert (
        "composedPath()"
        in source
    )


def test_runtime_never_fabricates_raw_option_value():
    source = (
        catalog_runtime_adapter_source()
    )

    assert (
        "rawValue"
        in source
    )

    # Contract is semantic, not formatting-dependent:
    #
    #     item.value
    #         ↓
    #     rawValue
    #         ↓
    #     state.selected_value
    #
    # Label must never be promoted into a fabricated raw value.
    compact = " ".join(
        source.split()
    )

    assert (
        "const rawValue = normalize( item.value );"
        in compact
    )

    assert (
        "state.selected_value = rawValue;"
        in compact
    )

    assert (
        "state.selected_value = label;"
        not in compact
    )


def test_injection_embeds_catalog_payload_without_network():
    html = (
        "<!doctype html>"
        "<html><body>"
        '<div id="alpha"></div>'
        "</body></html>"
    )

    result = (
        inject_catalog_runtime_adapter(
            html,
            payload(),
        )
    )

    assert (
        'id="qcc-auto-twin-catalog-runtime-data"'
        in result
    )

    assert (
        'data-qcc-auto-twin-catalog-runtime="2"'
        in result
    )

    assert (
        '"selector":"#alpha"'
        in result
    )

    assert (
        "fetch("
        not in result
    )


def test_injection_is_idempotent():
    first = (
        inject_catalog_runtime_adapter(
            "<html><body></body></html>",
            payload(),
        )
    )

    second = (
        inject_catalog_runtime_adapter(
            first,
            payload(),
        )
    )

    assert second == first


def test_empty_global_catalog_list_does_not_inject():
    empty = payload()

    empty[
        "catalogs"
    ] = []

    result = (
        inject_catalog_runtime_adapter(
            "<html><body></body></html>",
            empty,
        )
    )

    assert (
        "qcc-auto-twin-catalog-runtime-data"
        not in result
    )


def test_script_termination_is_escaped_in_payload():
    data = payload()

    data[
        "catalogs"
    ][0][
        "options"
    ][0][
        "label"
    ] = "</script><script>boom()</script>"

    result = (
        inject_catalog_runtime_adapter(
            "<html><body></body></html>",
            data,
        )
    )

    # Only our actual runtime script closing tag should exist.
    assert (
        "</script><script>boom()"
        not in result
    )

    assert (
        "\\u003c/script\\u003e"
        in result
    )


def test_zero_option_dynamic_catalog_is_preserved_not_fabricated():
    result = (
        inject_catalog_runtime_adapter(
            "<html><body></body></html>",
            payload(),
        )
    )

    marker = (
        '<script type="application/json" '
        'id="qcc-auto-twin-catalog-runtime-data">'
    )

    start = (
        result.index(
            marker
        )
        + len(
            marker
        )
    )

    end = result.index(
        "</script>",
        start,
    )

    decoded = json.loads(
        result[
            start:end
        ]
    )

    dynamic = next(
        catalog
        for catalog in decoded[
            "catalogs"
        ]
        if (
            catalog[
                "selector"
            ]
            == "#dynamic"
        )
    )

    assert (
        dynamic[
            "options"
        ]
        == []
    )


def test_builder_integrates_adapter_after_network_guard():
    source = BUILDER.read_text(
        encoding="utf-8"
    )

    guard = source.index(
        "local_html = _inject_guard("
    )

    adapter = source.index(
        "QCC_AUTO_TWIN_STATIC_CATALOG_RUNTIME_ADAPTER"
    )

    write = source.index(
        '/ "index.html"',
        adapter,
    )

    assert (
        guard
        < adapter
        < write
    )


def test_builder_writes_adapter_only_for_catalog_runtime():
    source = BUILDER.read_text(
        encoding="utf-8"
    )

    assert (
        "if catalog_runtime_payload is not None:"
        in source
    )

    assert (
        "AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_FILENAME"
        in source
    )

    assert (
        '"catalog_runtime_adapter_version"'
        in source
    )

    assert (
        '"catalog_runtime_adapter_mode"'
        in source
    )
