from pathlib import Path


SERVER = Path(
    "backend/qcc/bridge/server.py"
)


def _source():
    return SERVER.read_text(
        encoding="utf-8"
    )


def test_visual_artifact_bridge_has_binary_endpoint():
    source = _source()

    required = (
        "/qcc/site-architecture/visual-artifact",
        "QCC_VISUAL_ARTIFACT_MAX_BYTES",
        "_read_binary_with_limit",
        "attach_visual_artifact",
        '"image/png"',
    )

    for token in required:
        assert token in source


def test_visual_artifact_bridge_binds_capture_and_kind_via_headers():
    source = _source()

    required = (
        "X-QCC-Protocol-Version",
        "X-QCC-Capture-Id",
        "X-QCC-Visual-Kind",
        "QCC_VISUAL_ARTIFACT_CAPTURE_ID_REQUIRED",
        "QCC_VISUAL_ARTIFACT_KIND_REQUIRED",
    )

    for token in required:
        assert token in source


def test_visual_artifact_bridge_keeps_png_out_of_raw_capture_contract():
    source = _source()

    start = source.index(
        'path\n            == "/qcc/site-architecture/visual-artifact"'
    )

    end = source.index(
        "# POST /qcc/site-architecture/capture",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        "attach_visual_artifact"
        in block
    )

    assert (
        "qcc_capture.json"
        not in block
    )

    assert (
        "base64"
        not in block.lower()
    )

    assert (
        "JSON.stringify"
        not in block
    )
