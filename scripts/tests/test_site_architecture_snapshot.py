import json

import pytest

from backend.automation.site_architecture import (
    SiteArchitectureSnapshot,
    SiteArchitectureSource,
    build_normalized_snapshot_payload,
    write_normalized_snapshot,
)
from backend.automation.site_architecture.schema import (
    SITE_ARCHITECTURE_TOP_LEVEL_KEYS,
)


def _snapshot():
    return SiteArchitectureSnapshot(
        source=SiteArchitectureSource(
            kind="DOM_CAPTURE",
            schema_version=1,
        ),
    )


def test_normalized_snapshot_has_exact_top_level_contract():
    payload = (
        build_normalized_snapshot_payload(
            _snapshot()
        )
    )

    assert (
        tuple(payload)
        == SITE_ARCHITECTURE_TOP_LEVEL_KEYS
    )

    assert payload["schema_version"] == 1
    assert (
        payload["source"]["kind"]
        == "DOM_CAPTURE"
    )


def test_normalized_snapshot_can_be_written_as_json(
    tmp_path,
):
    path = write_normalized_snapshot(
        _snapshot(),
        tmp_path / "site_architecture.json",
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert payload["schema_version"] == 1
    assert (
        payload["source"]["kind"]
        == "DOM_CAPTURE"
    )


def test_normalized_snapshot_rejects_invalid_object():
    with pytest.raises(
        ValueError,
        match="SITE_ARCHITECTURE_SNAPSHOT_INVALID",
    ):
        build_normalized_snapshot_payload(
            {}
        )
