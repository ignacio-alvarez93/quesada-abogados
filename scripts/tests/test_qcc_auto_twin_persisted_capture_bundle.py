import json

import pytest

from backend.qcc.auto_twin import (
    AUTO_TWIN_PERSISTED_CAPTURE_BUNDLE_TYPE,
    load_auto_twin_persisted_capture_bundle,
)


PNG = (
    b"\x89PNG\r\n\x1a\n"
    + b"fixture"
)


def _write_json(
    path,
    value,
):
    path.write_text(
        json.dumps(
            value
        ),
        encoding="utf-8",
    )


def _bundle(
    tmp_path,
    *,
    capture_id="capture-1",
    profile_key="twin_discovery",
    pathname="/mercurio/page.html",
    functional_state="STATE_A",
    screenshot=True,
):
    root = (
        tmp_path
        / "site_architecture"
    )

    capture_dir = (
        root
        / capture_id
    )

    capture_dir.mkdir(
        parents=True
    )

    artifacts = {
        "raw_capture":
            "qcc_capture.json",

        "site_architecture":
            "site_architecture.json",

        "state_observation":
            "state_observation.json",

        "metadata":
            "metadata.json",
    }

    metadata = {
        "capture_id":
            capture_id,

        "site_code":
            "MERCURIO",

        "artifacts":
            artifacts,

        "retention": {
            "browser_profile_key":
                profile_key,
        },

        "state_observation": {
            "state":
                functional_state,

            "fingerprint":
                "fingerprint-1",
        },
    }

    if screenshot:
        artifacts[
            "screenshot_viewport"
        ] = (
            "screenshot_viewport.png"
        )

        metadata[
            "visual_evidence"
        ] = {
            "viewport": {
                "artifact":
                    "screenshot_viewport.png",

                "content_type":
                    "image/png",
            },
        }

        (
            capture_dir
            / "screenshot_viewport.png"
        ).write_bytes(
            PNG
        )

    _write_json(
        capture_dir
        / "metadata.json",
        metadata,
    )

    _write_json(
        capture_dir
        / "qcc_capture.json",
        {
            "schema_version":
                1,

            "browser_profile_key":
                profile_key,

            "main_url":
                (
                    "http://127.0.0.1:8767"
                    + pathname
                ),
        },
    )

    _write_json(
        capture_dir
        / "site_architecture.json",
        {
            "schema_version":
                1,

            "page": {
                "pathname":
                    pathname,

                "url":
                    (
                        "http://127.0.0.1:8767"
                        + pathname
                    ),
            },

            "viewport": {
                "inner_width":
                    1534,

                "inner_height":
                    911,

                "device_pixel_ratio":
                    1,

                "scroll_x":
                    0,

                "scroll_y":
                    0,
            },

            "elements":
                [],

            "catalogs":
                [],
        },
    )

    _write_json(
        capture_dir
        / "state_observation.json",
        {
            "schema_version":
                1,

            "state":
                functional_state,

            "fingerprint":
                "fingerprint-1",
        },
    )

    return (
        root,
        capture_dir,
    )


def test_load_complete_capture_bundle(
    tmp_path,
):
    root, capture_dir = (
        _bundle(
            tmp_path
        )
    )

    result = (
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
        )
    )

    assert (
        result[
            "bundle_type"
        ]
        == AUTO_TWIN_PERSISTED_CAPTURE_BUNDLE_TYPE
    )

    assert (
        result[
            "capture"
        ][
            "capture_id"
        ]
        == "capture-1"
    )

    assert (
        result[
            "capture"
        ][
            "browser_profile_key"
        ]
        == "twin_discovery"
    )

    assert (
        result[
            "capture"
        ][
            "pathname"
        ]
        == "/mercurio/page.html"
    )

    assert (
        result[
            "capture"
        ][
            "functional_state"
        ]
        == "STATE_A"
    )

    assert (
        result[
            "image_path"
        ]
        == str(
            capture_dir
            / "screenshot_viewport.png"
        )
    )


def test_rendering_profile_is_derived_from_snapshot_viewport(
    tmp_path,
):
    root, _ = _bundle(
        tmp_path
    )

    result = (
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
        )
    )

    profile = result[
        "rendering_profile"
    ]

    assert (
        profile[
            "inner_width"
        ]
        == 1534
    )

    assert (
        profile[
            "inner_height"
        ]
        == 911
    )

    assert (
        profile[
            "device_pixel_ratio"
        ]
        == 1
    )


@pytest.mark.parametrize(
    "capture_id",
    [
        "",
        ".",
        "..",
        "../capture",
        "a/b",
        r"a\b",
    ],
)
def test_capture_id_must_be_exact_simple_locator(
    tmp_path,
    capture_id,
):
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_ID_INVALID"
        ),
    ):
        load_auto_twin_persisted_capture_bundle(
            root=tmp_path,
            capture_id=capture_id,
        )


def test_unknown_capture_fails_closed(
    tmp_path,
):
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_NOT_FOUND"
        ),
    ):
        load_auto_twin_persisted_capture_bundle(
            root=tmp_path,
            capture_id="missing",
        )


def test_metadata_capture_id_must_match_directory(
    tmp_path,
):
    root, capture_dir = _bundle(
        tmp_path
    )

    metadata_path = (
        capture_dir
        / "metadata.json"
    )

    metadata = json.loads(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )

    metadata[
        "capture_id"
    ] = "other"

    _write_json(
        metadata_path,
        metadata,
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_METADATA_ID_MISMATCH"
        ),
    ):
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
        )


def test_profile_is_required_from_raw_capture(
    tmp_path,
):
    root, capture_dir = _bundle(
        tmp_path
    )

    raw_path = (
        capture_dir
        / "qcc_capture.json"
    )

    raw = json.loads(
        raw_path.read_text(
            encoding="utf-8"
        )
    )

    raw.pop(
        "browser_profile_key"
    )

    _write_json(
        raw_path,
        raw,
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_PROFILE_REQUIRED"
        ),
    ):
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
        )


def test_retention_profile_cannot_disagree_with_raw_capture(
    tmp_path,
):
    root, capture_dir = _bundle(
        tmp_path
    )

    metadata_path = (
        capture_dir
        / "metadata.json"
    )

    metadata = json.loads(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )

    metadata[
        "retention"
    ][
        "browser_profile_key"
    ] = "other-profile"

    _write_json(
        metadata_path,
        metadata,
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_PROFILE_MISMATCH"
        ),
    ):
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
        )


def test_pathname_is_required_from_site_architecture(
    tmp_path,
):
    root, capture_dir = _bundle(
        tmp_path
    )

    path = (
        capture_dir
        / "site_architecture.json"
    )

    snapshot = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    snapshot[
        "page"
    ][
        "pathname"
    ] = ""

    _write_json(
        path,
        snapshot,
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_PATHNAME_REQUIRED"
        ),
    ):
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
        )


def test_state_file_and_metadata_must_agree(
    tmp_path,
):
    root, capture_dir = _bundle(
        tmp_path
    )

    path = (
        capture_dir
        / "state_observation.json"
    )

    state = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    state[
        "fingerprint"
    ] = "different"

    _write_json(
        path,
        state,
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_STATE_MISMATCH"
        ),
    ):
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
        )


def test_screenshot_must_be_formally_registered(
    tmp_path,
):
    root, capture_dir = _bundle(
        tmp_path,
        screenshot=False,
    )

    (
        capture_dir
        / "screenshot_viewport.png"
    ).write_bytes(
        PNG
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_IMAGE_NOT_REGISTERED"
        ),
    ):
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
        )


def test_registered_screenshot_must_exist(
    tmp_path,
):
    root, capture_dir = _bundle(
        tmp_path
    )

    (
        capture_dir
        / "screenshot_viewport.png"
    ).unlink()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_IMAGE_MISSING"
        ),
    ):
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
        )


def test_invalid_png_signature_is_rejected(
    tmp_path,
):
    root, capture_dir = _bundle(
        tmp_path
    )

    (
        capture_dir
        / "screenshot_viewport.png"
    ).write_bytes(
        b"NOT PNG"
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_PERSISTED_CAPTURE_VIEWPORT_IMAGE_INVALID"
        ),
    ):
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
        )


def test_image_requirement_can_be_explicitly_disabled(
    tmp_path,
):
    root, _ = _bundle(
        tmp_path,
        screenshot=False,
    )

    result = (
        load_auto_twin_persisted_capture_bundle(
            root=root,
            capture_id="capture-1",
            require_viewport_image=False,
        )
    )

    assert (
        result[
            "image_path"
        ]
        is None
    )
