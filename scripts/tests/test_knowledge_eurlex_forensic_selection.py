"""Mechanism tests for deterministic forensic selection of EUR-Lex evidence.

Uses only SYNTHETIC byte strings. The forensic manifest references
already-verified evidence artifacts; it never copies raw bytes and
never touches parser semantics.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from backend.knowledge.eurlex.evidence import (
    EurLexEvidenceArtifact,
    save_eurlex_evidence_artifact,
)
from backend.knowledge.eurlex.forensic_selection import (
    EurLexForensicSelectionError,
    EurLexForensicSelectionIntegrityError,
    load_eurlex_forensic_selection,
    select_eurlex_forensic_evidence,
    verify_eurlex_forensic_selection,
)


_SYNTHETIC_BODY_A = b"synthetic-forensic-payload-A"
_SYNTHETIC_BODY_B = b"synthetic-forensic-payload-B"


def _artifact(
    *,
    requested_identifier="32099R9999",
    canonical_identifier="02099R9999-20990101",
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


def _evidence_root(tmp_path):
    return tmp_path / "evidence"


def _selection_root(tmp_path):
    return tmp_path / "selection"


def test_select_writes_manifest_referencing_verified_artifact(tmp_path):
    evidence_paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=_evidence_root(tmp_path)
    )

    selection = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )

    assert selection.artifact_id == evidence_paths.metadata_path.stem
    assert selection.evidence_metadata_path == evidence_paths.metadata_path
    assert selection.evidence_raw_path == evidence_paths.raw_path
    assert selection.manifest_path.is_file()

    # never copies raw bytes into the manifest tree
    assert not (
        selection.manifest_path.parent / evidence_paths.raw_path.name
    ).exists()


def test_select_never_rewrites_underlying_raw_evidence(tmp_path):
    evidence_paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=_evidence_root(tmp_path)
    )
    original_raw_bytes = evidence_paths.raw_path.read_bytes()

    select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )

    assert evidence_paths.raw_path.read_bytes() == original_raw_bytes


def test_select_raises_for_unknown_artifact_id(tmp_path):
    with pytest.raises(EurLexForensicSelectionError):
        select_eurlex_forensic_evidence(
            artifact_id="does-not-exist__deadbeef",
            selection_id="case-forensic-primary",
            evidence_root=_evidence_root(tmp_path),
            selection_root=_selection_root(tmp_path),
        )


def test_repeated_selection_same_identity_is_idempotent(tmp_path):
    evidence_paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=_evidence_root(tmp_path)
    )

    first = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )
    second = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )

    assert first.manifest_path == second.manifest_path
    assert first.selection_key == second.selection_key
    assert first.selected_at == second.selected_at

    files = sorted(_selection_root(tmp_path).iterdir())
    assert len(files) == 1


def test_different_selection_identity_produces_distinct_manifest(
    tmp_path,
):
    evidence_paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=_evidence_root(tmp_path)
    )

    first = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )
    second = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-secondary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )

    assert first.manifest_path != second.manifest_path
    assert first.selection_key != second.selection_key


def test_load_forensic_selection_round_trip(tmp_path):
    evidence_paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=_evidence_root(tmp_path)
    )

    selection = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )

    loaded = load_eurlex_forensic_selection(selection.manifest_path)

    assert loaded == selection

    verified = verify_eurlex_forensic_selection(selection.manifest_path)
    assert verified == selection


def test_load_fails_closed_when_underlying_evidence_disappears(tmp_path):
    evidence_paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=_evidence_root(tmp_path)
    )

    selection = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )

    evidence_paths.raw_path.unlink()
    evidence_paths.metadata_path.unlink()

    with pytest.raises(EurLexForensicSelectionIntegrityError):
        load_eurlex_forensic_selection(selection.manifest_path)


def test_load_fails_closed_when_underlying_evidence_is_tampered(
    tmp_path,
):
    evidence_paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=_evidence_root(tmp_path)
    )

    selection = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )

    evidence_paths.raw_path.write_bytes(_SYNTHETIC_BODY_B)

    with pytest.raises(EurLexForensicSelectionIntegrityError):
        load_eurlex_forensic_selection(selection.manifest_path)


def test_load_fails_closed_when_manifest_sha256_is_tampered(tmp_path):
    evidence_paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=_evidence_root(tmp_path)
    )

    selection = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )

    manifest = json.loads(
        selection.manifest_path.read_text(encoding="utf-8")
    )
    manifest["sha256"] = "0" * 64
    selection.manifest_path.write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(EurLexForensicSelectionIntegrityError):
        load_eurlex_forensic_selection(selection.manifest_path)


def test_load_fails_closed_when_manifest_selection_key_is_tampered(
    tmp_path,
):
    evidence_paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=_evidence_root(tmp_path)
    )

    selection = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )

    manifest = json.loads(
        selection.manifest_path.read_text(encoding="utf-8")
    )
    manifest["selection_id"] = "tampered-selection-id"
    selection.manifest_path.write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(EurLexForensicSelectionIntegrityError):
        load_eurlex_forensic_selection(selection.manifest_path)


def test_load_fails_closed_when_manifest_incomplete(tmp_path):
    evidence_paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=_evidence_root(tmp_path)
    )

    selection = select_eurlex_forensic_evidence(
        artifact_id=evidence_paths.metadata_path.stem,
        selection_id="case-forensic-primary",
        evidence_root=_evidence_root(tmp_path),
        selection_root=_selection_root(tmp_path),
    )

    manifest = json.loads(
        selection.manifest_path.read_text(encoding="utf-8")
    )
    del manifest["sha256"]
    selection.manifest_path.write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(EurLexForensicSelectionIntegrityError):
        load_eurlex_forensic_selection(selection.manifest_path)


def test_load_missing_manifest_raises_error(tmp_path):
    with pytest.raises(EurLexForensicSelectionError):
        load_eurlex_forensic_selection(tmp_path / "missing.json")
