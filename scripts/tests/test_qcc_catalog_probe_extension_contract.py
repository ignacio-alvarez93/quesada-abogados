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
