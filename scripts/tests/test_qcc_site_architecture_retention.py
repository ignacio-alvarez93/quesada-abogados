import json

import pytest

from backend.qcc.site_architecture.ingestor import (
    DEFAULT_QCC_SITE_ARCHITECTURE_RETENTION_LIMIT,
    QccSiteArchitectureIngestor,
)


def _ingestor(
    tmp_path,
    *,
    limit=3,
):
    return QccSiteArchitectureIngestor(
        output_root=tmp_path,
        recognizer_registry=object(),
        retention_limit=limit,
    )


def _capture_dir(
    root,
    capture_id,
    *,
    profile,
    origin,
):
    folder = root / capture_id
    folder.mkdir()

    metadata = {
        "capture_id":
            capture_id,

        "retention": {
            "mode":
                "PROFILE_ORIGIN_RING",

            "browser_profile_key":
                profile,

            "origin":
                origin,
        },
    }

    (
        folder
        / "metadata.json"
    ).write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    return folder


def test_default_retention_limit_is_30():
    assert (
        DEFAULT_QCC_SITE_ARCHITECTURE_RETENTION_LIMIT
        == 30
    )


def test_retention_scope_is_profile_plus_origin(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path
    )

    scope = ingestor._retention_scope(
        {
            "browser_profile_key":
                "instagram_monitor",
        },
        page_url=(
            "https://www.instagram.com/"
            "example"
        ),
    )

    assert (
        scope["browser_profile_key"]
        == "instagram_monitor"
    )

    assert (
        scope["origin"]
        == "https://www.instagram.com"
    )

    assert scope["limit"] == 3


def test_unbound_capture_has_no_retention_scope(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path
    )

    assert (
        ingestor._retention_scope(
            {},
            page_url="https://example.com",
        )
        is None
    )


def test_ring_removes_oldest_capture(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path,
        limit=3,
    )

    for number in range(1, 5):
        _capture_dir(
            tmp_path,
            f"capture-{number:02d}",
            profile="profile-a",
            origin="https://example.com",
        )

    removed = (
        ingestor._prune_retention_scope(
            current_capture_id=
                "capture-04",

            scope={
                "browser_profile_key":
                    "profile-a",

                "origin":
                    "https://example.com",
            },
        )
    )

    assert removed == [
        "capture-01"
    ]

    assert not (
        tmp_path
        / "capture-01"
    ).exists()

    assert (
        tmp_path
        / "capture-04"
    ).exists()


def test_ring_does_not_delete_other_scope(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path,
        limit=2,
    )

    _capture_dir(
        tmp_path,
        "capture-01",
        profile="profile-a",
        origin="https://example.com",
    )

    _capture_dir(
        tmp_path,
        "capture-02",
        profile="profile-a",
        origin="https://example.com",
    )

    _capture_dir(
        tmp_path,
        "capture-03",
        profile="profile-a",
        origin="https://example.com",
    )

    _capture_dir(
        tmp_path,
        "capture-other",
        profile="profile-b",
        origin="https://example.com",
    )

    ingestor._prune_retention_scope(
        current_capture_id=
            "capture-03",

        scope={
            "browser_profile_key":
                "profile-a",

            "origin":
                "https://example.com",
        },
    )

    assert (
        tmp_path
        / "capture-other"
    ).exists()


def test_current_capture_is_never_selected_as_victim(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path,
        limit=2,
    )

    for capture_id in (
        "000-current",
        "100-old",
        "200-new",
    ):
        _capture_dir(
            tmp_path,
            capture_id,
            profile="profile-a",
            origin="https://example.com",
        )

    removed = (
        ingestor._prune_retention_scope(
            current_capture_id=
                "000-current",

            scope={
                "browser_profile_key":
                    "profile-a",

                "origin":
                    "https://example.com",
            },
        )
    )

    assert (
        "000-current"
        not in removed
    )

    assert (
        tmp_path
        / "000-current"
    ).exists()


def test_invalid_retention_limit_is_rejected(
    tmp_path,
):
    with pytest.raises(
        ValueError,
        match=(
            "QCC_SITE_ARCHITECTURE_"
            "RETENTION_LIMIT_INVALID"
        ),
    ):
        QccSiteArchitectureIngestor(
            output_root=tmp_path,
            recognizer_registry=object(),
            retention_limit=0,
        )



def test_ingest_wires_profile_origin_retention_after_metadata():
    from pathlib import Path

    source = Path(
        "backend/qcc/site_architecture/ingestor.py"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        "    def ingest("
    )

    block = source[start:]

    scope_pos = block.index(
        "self._retention_scope("
    )

    metadata_pos = block.index(
        '"metadata.json"'
    )

    prune_pos = block.index(
        "self._prune_retention_scope("
    )

    return_pos = block.index(
        "return runtime_result"
    )

    assert (
        scope_pos
        < metadata_pos
        < prune_pos
        < return_pos
    )


def test_ingest_persists_retention_scope_in_metadata():
    import re
    from pathlib import Path

    source = Path(
        "backend/qcc/site_architecture/ingestor.py"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        "    def ingest("
    )

    block = source[start:]

    assert re.search(
        r'metadata\s*\[\s*"retention"\s*\]'
        r'\s*=\s*dict\s*\(\s*retention_scope\s*\)',
        block,
    )


def test_legacy_capture_without_scope_is_not_pruned():
    from pathlib import Path

    source = Path(
        "backend/qcc/site_architecture/ingestor.py"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        "    def ingest("
    )

    block = source[start:]

    assert (
        "if retention_scope is not None:"
        in block
    )


def test_retention_result_is_runtime_observable():
    from pathlib import Path

    source = Path(
        "backend/qcc/site_architecture/ingestor.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"retention_removed_capture_ids"'
        in source
    )


def test_retention_marker_exists():
    from pathlib import Path

    source = Path(
        "backend/qcc/site_architecture/ingestor.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_SITE_ARCHITECTURE_RETENTION_RING_V1"
        in source
    )
