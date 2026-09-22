from datetime import date

import pytest

from backend.knowledge import (
    KnowledgeBlock,
    KnowledgeDocumentValidity,
    KnowledgeStructuredDocument,
    KnowledgeTemporalResolutionStatus,
    KnowledgeValidityStatus,
    audit_document_temporal_integrity,
    block_timeline_issues,
    build_knowledge_block_version,
    resolve_block_version_at,
)


SOURCE = "BOE_CONSOLIDATED"
EXTERNAL_ID = "BOE-A-2024-24099"


def _version(block_id, position, *, effective_from, is_current, **kw):
    return build_knowledge_block_version(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        block_id=block_id,
        version_position=position,
        content_text=f"{block_id}-v{position}",
        effective_from=effective_from,
        is_current=is_current,
        **kw,
    )


def _block(block_id, position, title=""):
    return KnowledgeBlock(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        block_id=block_id,
        position=position,
        title=title,
    )


def _document(blocks, versions):
    return KnowledgeStructuredDocument(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        blocks=tuple(blocks),
        versions=tuple(versions),
    )


# ------------------------------------------------------------
# block_timeline_issues
# ------------------------------------------------------------


def test_clean_timeline_has_no_issues():
    versions = (
        _version("a1", 1, effective_from=date(2024, 1, 1), is_current=False),
        _version("a1", 2, effective_from=date(2024, 6, 1), is_current=True),
    )

    assert block_timeline_issues(versions) == ()


def test_undated_version_is_flagged():
    versions = (
        _version("a1", 1, effective_from=None, is_current=False),
        _version("a1", 2, effective_from=date(2024, 6, 1), is_current=True),
    )

    assert "UNDATED_VERSION" in block_timeline_issues(versions)


def test_non_monotonic_timeline_is_flagged():
    versions = (
        _version("a1", 1, effective_from=date(2024, 6, 1), is_current=False),
        _version("a1", 2, effective_from=date(2024, 1, 1), is_current=True),
    )

    assert "NON_MONOTONIC_TIMELINE" in block_timeline_issues(versions)


def test_same_day_versions_are_flagged_as_duplicate_effective_date():
    versions = (
        _version("a1", 1, effective_from=date(2024, 6, 1), is_current=False),
        _version("a1", 2, effective_from=date(2024, 6, 1), is_current=True),
    )

    assert "DUPLICATE_EFFECTIVE_DATE" in block_timeline_issues(versions)


def test_current_not_latest_is_flagged():
    versions = (
        _version("a1", 1, effective_from=date(2024, 1, 1), is_current=True),
        _version("a1", 2, effective_from=date(2024, 6, 1), is_current=False),
    )

    assert "CURRENT_NOT_LATEST" in block_timeline_issues(versions)


# ------------------------------------------------------------
# audit_document_temporal_integrity
# ------------------------------------------------------------


def test_document_audit_is_clean_when_all_blocks_are_sound():
    document = _document(
        [_block("a1", 1)],
        [
            _version("a1", 1, effective_from=date(2024, 1, 1), is_current=False),
            _version("a1", 2, effective_from=date(2024, 6, 1), is_current=True),
        ],
    )

    report = audit_document_temporal_integrity(document)

    assert report.clean is True
    assert report.block_issues == ()
    assert report.document_issues == ()
    assert report.affected_block_ids == ()


def test_document_audit_reports_per_block_issues():
    document = _document(
        [_block("a1", 1), _block("a2", 2)],
        [
            _version("a1", 1, effective_from=None, is_current=True),
            _version("a2", 1, effective_from=date(2024, 1, 1), is_current=True),
        ],
    )

    report = audit_document_temporal_integrity(document)

    assert report.clean is False
    assert report.affected_block_ids == ("a1",)

    issues_by_block = dict(report.block_issues)
    assert "UNDATED_VERSION" in issues_by_block["a1"]


def test_document_audit_flags_impossible_interval_against_validity_end_date():
    document = _document(
        [_block("a1", 1)],
        [
            _version("a1", 1, effective_from=date(2024, 1, 1), is_current=False),
            # This version claims to take effect AFTER the document's
            # own declared end of validity: an impossible interval.
            _version("a1", 2, effective_from=date(2026, 1, 1), is_current=True),
        ],
    )

    validity = KnowledgeDocumentValidity(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        status=KnowledgeValidityStatus.REPEALED,
        end_date=date(2025, 1, 1),
        reason="test",
    )

    report = audit_document_temporal_integrity(
        document,
        validity=validity,
    )

    assert "VALIDITY_BEFORE_LATEST_EFFECTIVE" in report.document_issues


def test_document_audit_does_not_flag_when_all_effective_dates_precede_end_date():
    document = _document(
        [_block("a1", 1)],
        [
            _version("a1", 1, effective_from=date(2024, 1, 1), is_current=True),
        ],
    )

    validity = KnowledgeDocumentValidity(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        status=KnowledgeValidityStatus.REPEALED,
        end_date=date(2025, 1, 1),
        reason="test",
    )

    report = audit_document_temporal_integrity(
        document,
        validity=validity,
    )

    assert report.document_issues == ()


def test_document_audit_ignores_in_force_validity_for_impossible_interval_check():
    # An IN_FORCE assertion carries no end_date semantics; the audit
    # must never fabricate an impossible-interval finding from it.
    document = _document(
        [_block("a1", 1)],
        [
            _version("a1", 1, effective_from=date(2026, 1, 1), is_current=True),
        ],
    )

    validity = KnowledgeDocumentValidity(
        source_key=SOURCE,
        external_id=EXTERNAL_ID,
        status=KnowledgeValidityStatus.IN_FORCE,
        end_date=None,
        reason="test",
    )

    report = audit_document_temporal_integrity(
        document,
        validity=validity,
    )

    assert report.document_issues == ()


def test_document_audit_rejects_wrong_types():
    with pytest.raises(TypeError):
        audit_document_temporal_integrity("not-a-document")


# ------------------------------------------------------------
# as_of boundary hardening: same-day ties and non-monotonic order
# ------------------------------------------------------------


def test_as_of_fails_closed_on_same_day_competing_versions():
    # Two versions of the same block both claim the same
    # effective_from: no single answer can be resolved without
    # fabricating an order the source never gave.
    document = _document(
        [_block("a1", 1)],
        [
            _version("a1", 1, effective_from=date(2024, 6, 1), is_current=False),
            _version("a1", 2, effective_from=date(2024, 6, 1), is_current=True),
        ],
    )

    resolution = resolve_block_version_at(document, "a1", date(2024, 6, 1))

    assert (
        resolution.status
        is KnowledgeTemporalResolutionStatus.AMBIGUOUS_EFFECTIVE_DATE
    )
    assert resolution.version is None


def test_as_of_fails_closed_on_non_monotonic_timeline():
    # version_position expresses observed order; if effective_from
    # contradicts that order, the timeline cannot be trusted for any
    # as_of query, not just the boundary date.
    document = _document(
        [_block("a1", 1)],
        [
            _version("a1", 1, effective_from=date(2024, 6, 1), is_current=False),
            _version("a1", 2, effective_from=date(2024, 1, 1), is_current=True),
        ],
    )

    resolution = resolve_block_version_at(document, "a1", date(2024, 12, 1))

    assert (
        resolution.status
        is KnowledgeTemporalResolutionStatus.NON_MONOTONIC_TIMELINE
    )
    assert resolution.version is None


def test_as_of_exactly_on_boundary_picks_the_new_version_not_the_old_one():
    document = _document(
        [_block("a1", 1)],
        [
            _version("a1", 1, effective_from=date(2024, 1, 1), is_current=False),
            _version("a1", 2, effective_from=date(2024, 6, 1), is_current=True),
        ],
    )

    day_before = resolve_block_version_at(document, "a1", date(2024, 5, 31))
    boundary_day = resolve_block_version_at(document, "a1", date(2024, 6, 1))

    assert day_before.version.version_position == 1
    assert boundary_day.version.version_position == 2
