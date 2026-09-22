import pytest

from backend.knowledge import (
    KnowledgeEvidenceHorizonStatus,
    KnowledgeItemKind,
    build_knowledge_item,
    classify_knowledge_revision,
    resolve_evidence_horizon,
)
from backend.knowledge.repository import KnowledgeRevisionSnapshot
from backend.knowledge.revisions import KnowledgeRevisionStatus
from backend.knowledge.sqlite_repository import SQLiteKnowledgeRepository


def _item(revision="rev-1"):
    return build_knowledge_item(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2024-24099",
        title="Real Decreto 1155/2024",
        item_kind=KnowledgeItemKind.LEGISLATION,
        content_text="Texto vigente.",
        source_revision=revision,
    )


def _snapshot(*, revision_number, observed_at, source_revision="rev-1"):
    item = _item(source_revision)

    return KnowledgeRevisionSnapshot(
        revision_number=revision_number,
        revision_status=KnowledgeRevisionStatus.NEW,
        item=item,
        record_sha256="deadbeef",
        observed_at=observed_at,
    )


def test_never_ingested_when_no_revisions_observed():
    horizon = resolve_evidence_horizon(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2024-24099",
        revisions=(),
    )

    assert (
        horizon.status
        is KnowledgeEvidenceHorizonStatus.NEVER_INGESTED
    )
    assert horizon.checked_as_of == ""
    assert horizon.observation_count == 0


def test_checked_reports_latest_observation_by_timestamp():
    revisions = (
        _snapshot(
            revision_number=1,
            observed_at="2026-01-01T00:00:00+00:00",
            source_revision="rev-1",
        ),
        _snapshot(
            revision_number=2,
            observed_at="2026-06-05T08:08:48+00:00",
            source_revision="rev-2",
        ),
    )

    horizon = resolve_evidence_horizon(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2024-24099",
        revisions=revisions,
    )

    assert horizon.status is KnowledgeEvidenceHorizonStatus.CHECKED
    assert horizon.checked_as_of == "2026-06-05T08:08:48+00:00"
    assert horizon.source_revision == "rev-2"
    assert horizon.observation_count == 2
    assert "2026-06-05T08:08:48+00:00" in horizon.reason


def test_absence_of_later_revision_is_not_evidence_of_absence():
    horizon = resolve_evidence_horizon(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2024-24099",
        revisions=(
            _snapshot(
                revision_number=1,
                observed_at="2026-01-01T00:00:00+00:00",
            ),
        ),
    )

    # A "CHECKED" horizon must never be misread as "no later change
    # exists anywhere"; it only claims that within what Knowledge has
    # observed, no later authoritative change has appeared.
    assert horizon.checked is True
    assert "no se ha observado" in horizon.reason.lower()
    assert "2026-01-01T00:00:00+00:00" in horizon.reason


def test_requires_non_empty_external_id():
    with pytest.raises(ValueError):
        resolve_evidence_horizon(
            source_key="BOE_CONSOLIDATED",
            external_id="",
            revisions=(),
        )


def test_evidence_horizon_reflects_real_sqlite_ingestion_history(tmp_path):
    db_path = tmp_path / "evidence_horizon.db"
    repository = SQLiteKnowledgeRepository(db_path)
    repository.initialize_schema()

    first = _item("rev-1")
    decision = classify_knowledge_revision(
        previous=None,
        current=first,
    )

    repository.persist(first, decision)

    second = _item("rev-2")
    decision_2 = classify_knowledge_revision(
        previous=first,
        current=second,
    )

    repository.persist(second, decision_2)

    revisions = repository.list_revisions(
        "BOE_CONSOLIDATED",
        "BOE-A-2024-24099",
    )

    horizon = resolve_evidence_horizon(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2024-24099",
        revisions=revisions,
    )

    assert horizon.status is KnowledgeEvidenceHorizonStatus.CHECKED
    assert horizon.observation_count == 2
    assert horizon.source_revision == "rev-2"
    assert horizon.checked_as_of != ""
