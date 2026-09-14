import json
from pathlib import Path

import pytest

from backend.qcc.auto_twin.materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
    build_auto_twin_materialized_revision,
)

from backend.qcc.auto_twin.materialized_revision_store import (
    AUTO_TWIN_MATERIALIZED_MANIFEST_FILENAME,
    AutoTwinMaterializedRevisionStore,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def _record(
    *,
    twin_key="mercurio",
    capture_id="capture-1",
    content_hash=HASH_B,
    created_at="2026-09-05T13:30:00Z",
):
    return build_auto_twin_materialized_revision(
        twin_key=twin_key,
        materialization_mode=(
            AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
        ),
        source_capture_ids=[
            capture_id,
        ],
        candidate_refs=[],
        state_manifest=[
            {
                "state_id":
                    "EX01_PERSONAL",

                "source_capture_id":
                    capture_id,

                "pathname":
                    "/mercurio/nuevaSolicitud-EX01.html",

                "functional_state":
                    "EX01_PERSONAL",
            },
        ],
        artifact_manifest=[
            {
                "path":
                    "states/personal/page.html",

                "kind":
                    "HTML",

                "sha256":
                    HASH_A,

                "size_bytes":
                    123,
            },
        ],
        content_sha256=(
            content_hash
        ),
        created_at=(
            created_at
        ),
    )


def test_store_writes_exact_manifest_layout(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    record = _record()

    saved = store.save(
        record
    )

    manifest = (
        tmp_path
        / "mercurio"
        / record[
            "materialized_revision_id"
        ]
        / AUTO_TWIN_MATERIALIZED_MANIFEST_FILENAME
    )

    assert manifest.is_file()

    assert saved == record

    persisted = json.loads(
        manifest.read_text(
            encoding="utf-8"
        )
    )

    assert persisted == record


def test_store_get_round_trip(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    record = _record()

    store.save(
        record
    )

    loaded = store.get(
        twin_key="mercurio",
        materialized_revision_id=(
            record[
                "materialized_revision_id"
            ]
        ),
    )

    assert loaded == record
    assert loaded is not record


def test_store_missing_revision_returns_none(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    assert (
        store.get(
            twin_key="mercurio",
            materialized_revision_id="matrev-missing",
        )
        is None
    )


def test_same_record_is_idempotent(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    record = _record()

    first = store.save(
        record
    )

    second = store.save(
        record
    )

    assert first == second


def test_same_identity_with_later_created_at_keeps_first_record(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    first = _record(
        created_at=(
            "2026-09-05T13:30:00Z"
        )
    )

    second = _record(
        created_at=(
            "2026-09-05T18:00:00Z"
        )
    )

    assert (
        first[
            "materialized_revision_id"
        ]
        == second[
            "materialized_revision_id"
        ]
    )

    stored_first = store.save(
        first
    )

    stored_second = store.save(
        second
    )

    assert stored_second == stored_first

    assert (
        stored_second[
            "created_at"
        ]
        == "2026-09-05T13:30:00Z"
    )


def test_store_lists_multiple_site_revisions(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    first = _record(
        capture_id="capture-1",
        created_at=(
            "2026-09-05T13:30:00Z"
        ),
    )

    second = _record(
        capture_id="capture-2",
        content_hash=("c" * 64),
        created_at=(
            "2026-09-05T14:30:00Z"
        ),
    )

    store.save(
        second
    )

    store.save(
        first
    )

    records = store.list(
        twin_key="mercurio"
    )

    assert [
        item[
            "created_at"
        ]
        for item in records
    ] == [
        "2026-09-05T13:30:00Z",
        "2026-09-05T14:30:00Z",
    ]


def test_store_lists_across_twins(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    store.save(
        _record(
            twin_key="mercurio"
        )
    )

    store.save(
        _record(
            twin_key="other-site",
            capture_id="capture-other",
        )
    )

    assert len(
        store.list()
    ) == 2

    assert len(
        store.list(
            twin_key="mercurio"
        )
    ) == 1


@pytest.mark.parametrize(
    "twin_key",
    (
        "../mercurio",
        "/absolute",
        "mercurio/other",
        "",
    ),
)
def test_store_rejects_unsafe_twin_key(
    tmp_path,
    twin_key,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    with pytest.raises(
        ValueError
    ):
        store.get(
            twin_key=twin_key,
            materialized_revision_id="matrev-test",
        )


@pytest.mark.parametrize(
    "revision_id",
    (
        "../revision",
        "/revision",
        "foo/bar",
        "",
    ),
)
def test_store_rejects_unsafe_revision_id(
    tmp_path,
    revision_id,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    with pytest.raises(
        ValueError
    ):
        store.get(
            twin_key="mercurio",
            materialized_revision_id=(
                revision_id
            ),
        )


def test_store_detects_tampered_manifest(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    record = _record()

    store.save(
        record
    )

    manifest = store.manifest_path(
        twin_key="mercurio",
        materialized_revision_id=(
            record[
                "materialized_revision_id"
            ]
        ),
    )

    payload = json.loads(
        manifest.read_text(
            encoding="utf-8"
        )
    )

    payload[
        "content_sha256"
    ] = "d" * 64

    manifest.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError
    ):
        store.get(
            twin_key="mercurio",
            materialized_revision_id=(
                record[
                    "materialized_revision_id"
                ]
            ),
        )


def test_list_detects_directory_identity_mismatch(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    record = _record()

    wrong_dir = (
        tmp_path
        / "wrong-twin"
        / record[
            "materialized_revision_id"
        ]
    )

    wrong_dir.mkdir(
        parents=True
    )

    (
        wrong_dir
        / AUTO_TWIN_MATERIALIZED_MANIFEST_FILENAME
    ).write_text(
        json.dumps(
            record
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            "TWIN_KEY_MISMATCH"
        ),
    ):
        store.list()


def test_store_exposes_no_update_delete_or_promote(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    for forbidden in (
        "update",
        "delete",
        "promote",
        "activate",
    ):
        assert not hasattr(
            store,
            forbidden
        )


def test_atomic_write_leaves_no_temp_files(
    tmp_path,
):
    store = AutoTwinMaterializedRevisionStore(
        root=tmp_path
    )

    store.save(
        _record()
    )

    temp_files = list(
        Path(
            tmp_path
        ).rglob(
            "*.tmp"
        )
    )

    assert temp_files == []
