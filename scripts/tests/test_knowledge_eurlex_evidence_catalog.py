"""Mechanism tests for the deterministic verified EUR-Lex evidence catalog.

Uses only SYNTHETIC byte strings, never real EUR-Lex payloads. Does not
touch ``full_structure``/``article_structure`` parser semantics.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

from backend.knowledge.eurlex.evidence import (
    EurLexEvidenceArtifact,
    save_eurlex_evidence_artifact,
)
from backend.knowledge.eurlex.evidence_catalog import (
    build_eurlex_evidence_catalog,
)


_SYNTHETIC_BODY_A = b"synthetic-catalog-payload-A"
_SYNTHETIC_BODY_B = b"synthetic-catalog-payload-B"


def _artifact(
    *,
    requested_identifier="32099R9999",
    canonical_identifier=None,
    source_url="https://example.test/eurlex/32099R9999",
    body=_SYNTHETIC_BODY_A,
) -> EurLexEvidenceArtifact:
    return EurLexEvidenceArtifact(
        provider="EUR_LEX",
        requested_identifier=requested_identifier,
        canonical_identifier=canonical_identifier,
        source_url=source_url,
        content_type="application/xhtml+xml",
        body=body,
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_empty_or_missing_root_returns_empty_catalog(tmp_path):
    catalog = build_eurlex_evidence_catalog(tmp_path / "does-not-exist")

    assert catalog.verified == ()
    assert catalog.rejected == ()


def test_catalog_lists_verified_artifacts_in_deterministic_order(tmp_path):
    first = save_eurlex_evidence_artifact(
        _artifact(source_url="https://example.test/a"), root_dir=tmp_path
    )
    second = save_eurlex_evidence_artifact(
        _artifact(source_url="https://example.test/b"), root_dir=tmp_path
    )

    catalog_1 = build_eurlex_evidence_catalog(tmp_path)
    catalog_2 = build_eurlex_evidence_catalog(tmp_path)

    assert len(catalog_1.verified) == 2
    assert catalog_1.verified == catalog_2.verified

    expected_order = tuple(
        sorted(
            (
                first.metadata_path.stem,
                second.metadata_path.stem,
            )
        )
    )
    assert tuple(e.artifact_id for e in catalog_1.verified) == expected_order


def test_catalog_filters_by_requested_identifier(tmp_path):
    save_eurlex_evidence_artifact(
        _artifact(
            requested_identifier="32099R9999",
            source_url="https://example.test/a",
        ),
        root_dir=tmp_path,
    )
    save_eurlex_evidence_artifact(
        _artifact(
            requested_identifier="32099L8888",
            source_url="https://example.test/b",
        ),
        root_dir=tmp_path,
    )

    catalog = build_eurlex_evidence_catalog(
        tmp_path,
        requested_identifier="32099L8888",
    )

    assert len(catalog.verified) == 1
    assert catalog.verified[0].requested_identifier == "32099L8888"


def test_catalog_filters_by_canonical_identifier(tmp_path):
    save_eurlex_evidence_artifact(
        _artifact(
            canonical_identifier="02099R9999-20990101",
            source_url="https://example.test/a",
        ),
        root_dir=tmp_path,
    )
    save_eurlex_evidence_artifact(
        _artifact(
            canonical_identifier=None,
            source_url="https://example.test/b",
        ),
        root_dir=tmp_path,
    )

    catalog = build_eurlex_evidence_catalog(
        tmp_path,
        canonical_identifier="02099R9999-20990101",
    )

    assert len(catalog.verified) == 1
    assert (
        catalog.verified[0].canonical_identifier
        == "02099R9999-20990101"
    )


def test_catalog_filters_by_artifact_id(tmp_path):
    paths = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)
    save_eurlex_evidence_artifact(
        _artifact(body=_SYNTHETIC_BODY_B), root_dir=tmp_path
    )

    catalog = build_eurlex_evidence_catalog(
        tmp_path,
        artifact_id=paths.metadata_path.stem,
    )

    assert len(catalog.verified) == 1
    assert catalog.verified[0].artifact_id == paths.metadata_path.stem


def test_orphaned_raw_without_metadata_is_rejected_not_verified(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "orphan-raw-only.raw").write_bytes(_SYNTHETIC_BODY_A)

    catalog = build_eurlex_evidence_catalog(tmp_path)

    assert catalog.verified == ()
    assert len(catalog.rejected) == 1
    assert catalog.rejected[0].stem == "orphan-raw-only"
    assert catalog.rejected[0].metadata_path is None


def test_orphaned_metadata_without_raw_is_rejected_not_verified(tmp_path):
    paths = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)
    paths.raw_path.unlink()

    catalog = build_eurlex_evidence_catalog(tmp_path)

    assert catalog.verified == ()
    assert len(catalog.rejected) == 1
    assert catalog.rejected[0].metadata_path == paths.metadata_path


def test_tampered_raw_body_is_rejected_not_verified(tmp_path):
    paths = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)
    paths.raw_path.write_bytes(_SYNTHETIC_BODY_B)

    catalog = build_eurlex_evidence_catalog(tmp_path)

    assert catalog.verified == ()
    assert len(catalog.rejected) == 1


def test_tampered_metadata_hash_is_rejected_not_verified(tmp_path):
    paths = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)

    metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    metadata["sha256"] = "0" * 64
    paths.metadata_path.write_text(
        json.dumps(metadata), encoding="utf-8"
    )

    catalog = build_eurlex_evidence_catalog(tmp_path)

    assert catalog.verified == ()
    assert len(catalog.rejected) == 1


def test_incomplete_metadata_is_rejected_not_verified(tmp_path):
    paths = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)

    metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    del metadata["byte_length"]
    paths.metadata_path.write_text(
        json.dumps(metadata), encoding="utf-8"
    )

    catalog = build_eurlex_evidence_catalog(tmp_path)

    assert catalog.verified == ()
    assert len(catalog.rejected) == 1


def test_mixed_valid_and_corrupt_artifacts_only_expose_valid_ones(
    tmp_path,
):
    valid = save_eurlex_evidence_artifact(
        _artifact(source_url="https://example.test/valid"),
        root_dir=tmp_path,
    )
    corrupt = save_eurlex_evidence_artifact(
        _artifact(
            source_url="https://example.test/corrupt",
            body=_SYNTHETIC_BODY_B,
        ),
        root_dir=tmp_path,
    )
    corrupt.raw_path.write_bytes(b"tampered-bytes")

    catalog = build_eurlex_evidence_catalog(tmp_path)

    assert len(catalog.verified) == 1
    assert catalog.verified[0].artifact_id == valid.metadata_path.stem
    assert len(catalog.rejected) == 1
    assert catalog.rejected[0].stem == corrupt.metadata_path.stem
