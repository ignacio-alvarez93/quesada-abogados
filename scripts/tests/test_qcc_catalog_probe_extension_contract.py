from pathlib import Path


SOURCE_PATH = Path(
    "chrome_extension/qcc/background/"
    "service_worker.js"
)


def _source() -> str:
    return SOURCE_PATH.read_text(
        encoding="utf-8"
    )


def _probe_source() -> str:
    source = _source()

    start = source.index(
        "function captureCatalogProbe()"
    )

    end = source.index(
        "function visibilityOf(",
        start,
    )

    return source[start:end]


def test_qcc_dom_capture_contains_catalog_probe():
    source = _source()

    required = (
        "function captureCatalogProbe()",
        '"native_select"',
        "catalog_probe:",
        "catalog_count:",
        "options_count:",
        "dependency_hints:",
        "selected_value:",
        "selected_label:",
        "selected_values:",
        "selected_index:",
    )

    for token in required:
        assert token in source


def test_catalog_probe_reads_live_state():
    source = _probe_source()

    required = (
        "select.value",
        "select.selectedOptions",
        "select.selectedIndex",
        "option.value",
        "option.label",
        "option.selected",
        "option.disabled",
    )

    for token in required:
        assert token in source


def test_catalog_probe_links_dom_relationships():
    source = _source()

    required = (
        "catalogSelectorOf",
        "catalogLabelOf",
        "catalogDependencyHintsOf",
        ".getElementById(",
        "attributesOf(",
    )

    for token in required:
        assert token in source


def test_catalog_probe_is_passive():
    source = _probe_source()

    forbidden = (
        ".click(",
        ".dispatchEvent(",
        ".setAttribute(",
        ".removeAttribute(",
        ".appendChild(",
        ".replaceChildren(",
    )

    for token in forbidden:
        assert token not in source


def test_catalog_probe_rejects_self_dependency():
    source = _source()

    required = (
        "const referencedElement",
        "referencedElement !== null",
        "referencedElement !== element",
    )

    for token in required:
        assert token in source



def test_catalog_probe_supports_open_shadow_custom_selects():
    source = _source()

    required = (
        "function customCatalogComboboxOf(",
        "function customCatalogOptionSurfaceOf(",
        "function customCatalogOptionsOf(",
        "function captureCustomCatalogs()",
        '"custom_select"',
        "implementation:",
        "'[role=\"combobox\"][aria-haspopup=\"listbox\"]'",
        "'[role=\"option\"]'",
        "custom_catalog_count:",
        "native_catalog_count:",
    )

    for token in required:
        assert token in source


def test_custom_catalog_probe_is_passive():
    source = _source()

    start = source.index(
        "function customCatalogComboboxOf("
    )

    end = source.index(
        "function captureCatalogProbe()",
        start,
    )

    custom_source = source[
        start:end
    ]

    forbidden = (
        ".click(",
        ".dispatchEvent(",
        ".focus(",
        ".blur(",
        ".setAttribute(",
        ".removeAttribute(",
        ".appendChild(",
        ".replaceChildren(",
    )

    for token in forbidden:
        assert token not in custom_source


def test_custom_catalog_probe_captures_value_label_and_state():
    source = _source()

    required = (
        "customCatalogScalarValue(",
        "customCatalogSelectedLabel(",
        'input[slot="hidden"]',
        "surface.textContent",
        "option.selected",
        '"aria-selected"',
        "option.disabled",
        '"aria-disabled"',
        "selected_value:",
        "selected_label:",
        "selected_index:",
        "options_count:",
    )

    for token in required:
        assert token in source


def test_custom_catalog_probe_uses_stable_host_selector():
    source = _source()

    assert (
        "catalogSelectorOf("
        in source
    )

    assert (
        "element.tagName"
        in source
    )

    assert (
        "+ '[name=\"'"
        in source
    )


def test_custom_catalog_probe_does_not_encode_provider_identity():
    source = _source()

    start = source.index(
        "function customCatalogComboboxOf("
    )

    end = source.index(
        "function captureCatalogProbe()",
        start,
    )

    custom_source = (
        source[
            start:end
        ].lower()
    )

    forbidden = (
        "red_sara",
        "redsara",
        "mercurio",
        "dnt-select",
        "dnt-option",
    )

    for token in forbidden:
        assert token not in custom_source




def test_custom_catalog_probe_does_not_persist_diagnostic_property_surfaces():
    source = _source()

    assert "customCatalogPropertySurfaceOf(" not in source
    assert "customCatalogValueEvidenceOf(" not in source
    assert "property_surface:" not in source
    assert "value_evidence:" not in source
