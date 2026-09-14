from pathlib import Path


WORKER = Path(
    "chrome_extension/qcc/background/service_worker.js"
)


def _source():
    return WORKER.read_text(
        encoding="utf-8"
    )


def test_extension_captures_constructable_shadow_stylesheets():
    source = _source()

    required = (
        "shadowRoot.adoptedStyleSheets",
        "sheet.cssRules",
        "rule.cssText",
        "shadowAdoptedStyleSheetCatalog",
        "shadowAdoptedStyleSheetKeyToId",
        "adoptedStyleSheetRefsOf",
        "adopted_stylesheet_refs",
        "adopted_stylesheet_count",
        "shadow_adopted_stylesheets",
        "stylesheet_id",
        "rule_count",
        "css_text",
        "source_url",
        "readable",
    )

    for token in required:
        assert token in source


def test_shadow_stylesheets_are_catalogued_not_duplicated_per_root():
    source = _source()

    function_start = source.index(
        "function inspectShadowRoots"
    )

    function_end = source.index(
        "const elements =",
        function_start,
    )

    block = source[
        function_start:function_end
    ]

    assert (
        "adoptedStyleSheetRefsOf("
        in block
    )

    assert (
        "adopted_stylesheet_refs:"
        in block
    )

    assert (
        "css_text:"
        not in block
    )


def test_shadow_stylesheet_catalog_is_returned_with_frame_capture():
    source = _source()

    assert (
        """shadow_adopted_stylesheets:
      shadowAdoptedStyleSheetCatalog"""
        in source
    )

    assert (
        """shadow_adopted_stylesheets:
        shadowAdoptedStyleSheetCatalog.length"""
        in source
    )


def test_shadow_stylesheet_capture_is_fail_open():
    source = _source()

    start = source.index(
        "function adoptedStyleSheetRefsOf"
    )

    end = source.index(
        "function inspectShadowRoots",
        start,
    )

    block = source[
        start:end
    ]

    assert "try {" in block
    assert "catch (_)" in block
    assert "CSS_RULES_UNREADABLE" in block
    assert "return [];" in block


def test_existing_capture_schema_remains_backward_compatible():
    source = _source()

    capture_start = source.index(
        "function captureDomFrame"
    )

    capture_end = source.index(
        "async function inspectActiveTabDom",
        capture_start,
    )

    block = source[
        capture_start:capture_end
    ]

    # La ampliación es evidencia opcional.
    # No hacemos una ruptura artificial del schema
    # mientras consumidores existentes ignoran
    # campos adicionales.
    assert (
        """schema_version:
      1"""
        in block
    )
