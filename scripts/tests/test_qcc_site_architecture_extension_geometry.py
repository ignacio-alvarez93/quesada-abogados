from pathlib import Path


JS = Path(
    "chrome_extension/qcc/background/"
    "service_worker.js"
).read_text(
    encoding="utf-8"
)


def test_qcc_extension_persists_browser_viewport():
    required = (
        "function viewportGeometryOfDocument()",
        "inner_width:",
        "inner_height:",
        "client_width:",
        "client_height:",
        "scroll_x:",
        "scroll_y:",
        "device_pixel_ratio:",
        "screen_x:",
        "screen_y:",
        "outer_width:",
        "outer_height:",
        "viewportGeometryOfDocument()",
    )

    for token in required:
        assert token in JS


def test_qcc_extension_persists_existing_element_rect():
    assert (
        ".getBoundingClientRect();"
        in JS
    )

    required = (
        "Number(rect.x)",
        "Number(rect.y)",
        "Number(rect.width)",
        "Number(rect.height)",
        "interactionSignals.rect",
    )

    for token in required:
        assert token in JS


def test_qcc_geometry_does_not_require_second_rect_measurement():
    assert (
        JS.count(
            ".getBoundingClientRect()"
        )
        == 1
    )
