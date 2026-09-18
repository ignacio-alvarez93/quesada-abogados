"""Mechanism tests for the EUR-Lex raw evidence/provenance container.

These tests use small SYNTHETIC byte strings only, to exercise the
evidence container and its idempotency/tamper-detection mechanics.

They are NOT authentic EUR-Lex fixtures and must never be treated as
such, nor as parser semantics fixtures. They do not touch
``full_structure``/``article_structure`` parsing at all.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from backend.knowledge.eurlex.evidence import (
    EurLexEvidenceArtifact,
    EurLexEvidenceError,
    EurLexEvidenceIntegrityError,
    acquire_eurlex_consolidated_evidence,
    acquire_eurlex_original_evidence,
    acquire_eurlex_tree_notice_evidence,
    import_eurlex_evidence_file,
    load_eurlex_evidence_artifact,
    save_eurlex_evidence_artifact,
    verify_eurlex_evidence_artifact,
)
from backend.knowledge.eurlex.transport import EurLexHttpResponse


_SYNTHETIC_BODY_A = b"synthetic-mechanism-payload-A"
_SYNTHETIC_BODY_B = b"synthetic-mechanism-payload-B"


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


def test_save_and_load_roundtrip_preserves_bytes_and_metadata(tmp_path):
    artifact = _artifact()

    paths = save_eurlex_evidence_artifact(artifact, root_dir=tmp_path)

    assert paths.raw_path.read_bytes() == _SYNTHETIC_BODY_A

    loaded = load_eurlex_evidence_artifact(paths.metadata_path)

    assert loaded.body == artifact.body
    assert loaded.sha256_hex == artifact.sha256_hex
    assert loaded.byte_length == len(_SYNTHETIC_BODY_A)
    assert loaded.provider == "EUR_LEX"
    assert loaded.requested_identifier == "32099R9999"
    assert loaded.source_url == artifact.source_url
    assert loaded.artifact_id == artifact.artifact_id


def test_identical_bytes_and_source_identity_is_idempotent(tmp_path):
    first = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)
    second = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)

    assert first.metadata_path == second.metadata_path
    assert first.raw_path == second.raw_path

    files = sorted(tmp_path.iterdir())
    assert len(files) == 2  # one .raw + one .json, never duplicated


def test_distinct_bytes_same_identity_preserve_both_artifacts(tmp_path):
    first = save_eurlex_evidence_artifact(_artifact(body=_SYNTHETIC_BODY_A), root_dir=tmp_path)
    second = save_eurlex_evidence_artifact(_artifact(body=_SYNTHETIC_BODY_B), root_dir=tmp_path)

    assert first.metadata_path != second.metadata_path
    assert first.raw_path.read_bytes() == _SYNTHETIC_BODY_A
    assert second.raw_path.read_bytes() == _SYNTHETIC_BODY_B


def test_distinct_source_identity_same_bytes_preserve_both_artifacts(tmp_path):
    first = save_eurlex_evidence_artifact(
        _artifact(source_url="https://example.test/one"),
        root_dir=tmp_path,
    )
    second = save_eurlex_evidence_artifact(
        _artifact(source_url="https://example.test/two"),
        root_dir=tmp_path,
    )

    assert first.metadata_path != second.metadata_path


def test_empty_body_is_rejected():
    with pytest.raises(ValueError):
        _artifact(body=b"")


def test_retrieved_at_requires_timezone_aware():
    with pytest.raises(ValueError):
        EurLexEvidenceArtifact(
            provider="EUR_LEX",
            requested_identifier="32099R9999",
            source_url="https://example.test/eurlex/32099R9999",
            body=_SYNTHETIC_BODY_A,
            retrieved_at=datetime(2026, 1, 1),
        )


def test_extra_metadata_rejects_reserved_key():
    with pytest.raises(ValueError):
        EurLexEvidenceArtifact(
            provider="EUR_LEX",
            requested_identifier="32099R9999",
            source_url="https://example.test/eurlex/32099R9999",
            body=_SYNTHETIC_BODY_A,
            extra_metadata={"sha256": "tampering-attempt"},
        )


def test_import_eurlex_evidence_file_rejects_missing_file(tmp_path):
    with pytest.raises(EurLexEvidenceError):
        import_eurlex_evidence_file(
            source_path=tmp_path / "missing.xhtml",
            requested_identifier="32099R9999",
            source_url="https://example.test/eurlex/32099R9999",
            root_dir=tmp_path / "evidence",
        )


def test_import_eurlex_evidence_file_rejects_empty_file(tmp_path):
    empty_file = tmp_path / "empty.xhtml"
    empty_file.write_bytes(b"")

    with pytest.raises(EurLexEvidenceError):
        import_eurlex_evidence_file(
            source_path=empty_file,
            requested_identifier="32099R9999",
            source_url="https://example.test/eurlex/32099R9999",
            root_dir=tmp_path / "evidence",
        )


def test_import_eurlex_evidence_file_roundtrips_operator_payload(tmp_path):
    source_file = tmp_path / "operator_downloaded.xhtml"
    source_file.write_bytes(_SYNTHETIC_BODY_A)

    paths = import_eurlex_evidence_file(
        source_path=source_file,
        requested_identifier="32099R9999",
        canonical_identifier="02099R9999-20990101",
        source_url="https://example.test/eurlex/32099R9999",
        root_dir=tmp_path / "evidence",
    )

    loaded = verify_eurlex_evidence_artifact(paths.metadata_path)

    assert loaded.body == _SYNTHETIC_BODY_A
    assert loaded.canonical_identifier == "02099R9999-20990101"


def test_load_fails_closed_when_raw_body_is_tampered(tmp_path):
    paths = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)

    paths.raw_path.write_bytes(_SYNTHETIC_BODY_B)

    with pytest.raises(EurLexEvidenceIntegrityError):
        load_eurlex_evidence_artifact(paths.metadata_path)


def test_load_fails_closed_when_metadata_hash_is_tampered(tmp_path):
    paths = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)

    metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    metadata["sha256"] = "0" * 64
    paths.metadata_path.write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    with pytest.raises(EurLexEvidenceIntegrityError):
        load_eurlex_evidence_artifact(paths.metadata_path)


def test_load_fails_closed_when_metadata_incomplete(tmp_path):
    paths = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)

    metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    del metadata["byte_length"]
    paths.metadata_path.write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    with pytest.raises(EurLexEvidenceIntegrityError):
        load_eurlex_evidence_artifact(paths.metadata_path)


def test_load_fails_closed_when_filename_does_not_match_artifact_id(tmp_path):
    paths = save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)

    renamed_metadata = paths.metadata_path.with_name("renamed.json")
    renamed_raw = paths.raw_path.with_name("renamed.raw")
    renamed_metadata.write_text(
        paths.metadata_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    renamed_raw.write_bytes(paths.raw_path.read_bytes())

    with pytest.raises(EurLexEvidenceIntegrityError):
        load_eurlex_evidence_artifact(renamed_metadata)


class _FakeAcquisitionTransport:
    """Fake reusing the real EurLexHttpResponse shape, no network I/O."""

    def fetch_tree_notice(self, celex):
        return EurLexHttpResponse(
            requested_url="https://example.test/cellar/tree",
            final_url="https://example.test/cellar/tree",
            status=200,
            content_type="application/xml",
            body=_SYNTHETIC_BODY_A,
            transport="CELLAR_TREE",
        )

    def fetch_original_content(self, celex):
        return EurLexHttpResponse(
            requested_url="https://example.test/cellar/content",
            final_url="https://example.test/cellar/content",
            status=200,
            content_type="application/xhtml+xml",
            body=_SYNTHETIC_BODY_A,
            transport="CELLAR_CONTENT",
        )

    def resolve_latest_consolidated(self, original_celex):
        notice = self.fetch_tree_notice(original_celex)
        return "02099R9999-20990101", notice

    def fetch_consolidated_content(self, consolidated_celex):
        return EurLexHttpResponse(
            requested_url="https://example.test/eli/consolidated",
            final_url="https://example.test/eli/consolidated",
            status=200,
            content_type="text/html",
            body=_SYNTHETIC_BODY_B,
            transport="ELI_CONSOLIDATED",
        )


def test_acquire_original_evidence_uses_existing_transport(tmp_path):
    transport = _FakeAcquisitionTransport()

    paths = acquire_eurlex_original_evidence(
        transport,
        "32099R9999",
        root_dir=tmp_path,
    )

    loaded = load_eurlex_evidence_artifact(paths.metadata_path)

    assert loaded.body == _SYNTHETIC_BODY_A
    assert loaded.canonical_identifier == "32099R9999"


def test_acquire_tree_notice_evidence_uses_existing_transport(tmp_path):
    transport = _FakeAcquisitionTransport()

    paths = acquire_eurlex_tree_notice_evidence(
        transport,
        "32099R9999",
        root_dir=tmp_path,
    )

    loaded = load_eurlex_evidence_artifact(paths.metadata_path)

    assert loaded.body == _SYNTHETIC_BODY_A


def test_acquire_consolidated_evidence_records_resolved_canonical_identity(tmp_path):
    transport = _FakeAcquisitionTransport()

    paths = acquire_eurlex_consolidated_evidence(
        transport,
        "32099R9999",
        root_dir=tmp_path,
    )

    loaded = load_eurlex_evidence_artifact(paths.metadata_path)

    assert loaded.body == _SYNTHETIC_BODY_B
    assert loaded.requested_identifier == "32099R9999"
    assert loaded.canonical_identifier == "02099R9999-20990101"
