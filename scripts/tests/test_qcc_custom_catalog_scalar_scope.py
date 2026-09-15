from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

WORKER = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "background"
    / "service_worker.js"
)


def test_custom_catalog_scalar_helper_is_inside_capture_dom_frame():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    capture_start = text.index(
        "function captureDomFrame() {"
    )

    helper = text.index(
        "function customCatalogScalarValue(",
        capture_start,
    )

    options = text.index(
        "function customCatalogOptionsOf(",
        capture_start,
    )

    capture_end = text.index(
        "\n}\n",
        options,
    )

    assert (
        capture_start
        < helper
        < options
        < capture_end
    )


def test_custom_catalog_scalar_never_fabricates_raw_value():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "function customCatalogScalarValue("
    )

    end = text.index(
        "function customCatalogOptionsOf(",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        'return "";'
        in block
    )

    assert (
        "candidate.value"
        in block
    )

    assert (
        'candidate.getAttribute(\n'
        '              "value"'
        in block
    )
