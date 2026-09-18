"""Mechanism tests for the thin operator CLIs under scripts/knowledge.

Every CLI here is a thin wrapper that delegates to existing backend
services. These tests never perform real network requests: acquisition
mode routing is exercised by monkeypatching the delegated backend
functions, not the network transport.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.knowledge.eurlex.evidence import (
    EurLexEvidenceArtifact,
    save_eurlex_evidence_artifact,
)
from scripts.knowledge import acquire_eurlex_evidence as acquire_cli
from scripts.knowledge import list_eurlex_evidence as list_cli
from scripts.knowledge import (
    select_eurlex_forensic_evidence as select_cli,
)


_SYNTHETIC_BODY_A = b"synthetic-cli-payload-A"


def _artifact(**overrides) -> EurLexEvidenceArtifact:
    defaults = dict(
        provider="EUR_LEX",
        requested_identifier="32099R9999",
        canonical_identifier=None,
        source_url="https://example.test/eurlex/32099R9999",
        content_type="application/xhtml+xml",
        body=_SYNTHETIC_BODY_A,
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return EurLexEvidenceArtifact(**defaults)


class _RecordingPaths:
    def __init__(self, metadata_path, raw_path):
        self.metadata_path = metadata_path
        self.raw_path = raw_path


def test_acquire_cli_routes_tree_notice_mode(tmp_path, monkeypatch):
    calls = []

    def fake_acquire(transport, celex, **kwargs):
        calls.append(("TREE_NOTICE", celex, kwargs))
        return _RecordingPaths(
            tmp_path / "a.json", tmp_path / "a.raw"
        )

    monkeypatch.setattr(
        acquire_cli,
        "_ACQUIRE_BY_MODE",
        {
            **acquire_cli._ACQUIRE_BY_MODE,
            "TREE_NOTICE": fake_acquire,
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "acquire_eurlex_evidence.py",
            "--mode",
            "TREE_NOTICE",
            "--celex",
            "32099R9999",
            "--root-dir",
            str(tmp_path),
        ],
    )

    exit_code = acquire_cli.main()

    assert exit_code == 0
    assert calls == [
        ("TREE_NOTICE", "32099R9999", {"root_dir": str(tmp_path)})
    ]


def test_acquire_cli_routes_original_mode(tmp_path, monkeypatch):
    calls = []

    def fake_acquire(transport, celex, **kwargs):
        calls.append(("ORIGINAL", celex, kwargs))
        return _RecordingPaths(
            tmp_path / "a.json", tmp_path / "a.raw"
        )

    monkeypatch.setattr(
        acquire_cli,
        "_ACQUIRE_BY_MODE",
        {
            **acquire_cli._ACQUIRE_BY_MODE,
            "ORIGINAL": fake_acquire,
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "acquire_eurlex_evidence.py",
            "--mode",
            "ORIGINAL",
            "--celex",
            "32099R9999",
        ],
    )

    exit_code = acquire_cli.main()

    assert exit_code == 0
    assert calls == [("ORIGINAL", "32099R9999", {})]


def test_acquire_cli_routes_consolidated_mode(tmp_path, monkeypatch):
    calls = []

    def fake_acquire(transport, celex, **kwargs):
        calls.append(("CONSOLIDATED", celex, kwargs))
        return _RecordingPaths(
            tmp_path / "a.json", tmp_path / "a.raw"
        )

    monkeypatch.setattr(
        acquire_cli,
        "_ACQUIRE_BY_MODE",
        {
            **acquire_cli._ACQUIRE_BY_MODE,
            "CONSOLIDATED": fake_acquire,
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "acquire_eurlex_evidence.py",
            "--mode",
            "CONSOLIDATED",
            "--celex",
            "32099R9999",
        ],
    )

    exit_code = acquire_cli.main()

    assert exit_code == 0
    assert calls == [("CONSOLIDATED", "32099R9999", {})]


def test_acquire_cli_rejects_unknown_mode(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "acquire_eurlex_evidence.py",
            "--mode",
            "BOGUS",
            "--celex",
            "32099R9999",
        ],
    )

    with pytest.raises(SystemExit):
        acquire_cli.main()


def test_acquire_cli_requires_celex(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "acquire_eurlex_evidence.py",
            "--mode",
            "ORIGINAL",
        ],
    )

    with pytest.raises(SystemExit):
        acquire_cli.main()


def test_list_cli_delegates_and_reports_catalog(
    tmp_path, monkeypatch, capsys
):
    save_eurlex_evidence_artifact(_artifact(), root_dir=tmp_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "list_eurlex_evidence.py",
            "--root-dir",
            str(tmp_path),
        ],
    )

    exit_code = list_cli.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Evidencia EUR-Lex verificada (1)" in output
    assert "32099R9999" in output


def test_select_cli_delegates_and_reports_manifest(
    tmp_path, monkeypatch, capsys
):
    evidence_root = tmp_path / "evidence"
    selection_root = tmp_path / "selection"

    paths = save_eurlex_evidence_artifact(
        _artifact(), root_dir=evidence_root
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "select_eurlex_forensic_evidence.py",
            "--artifact-id",
            paths.metadata_path.stem,
            "--selection-id",
            "case-forensic-primary",
            "--evidence-root",
            str(evidence_root),
            "--selection-root",
            str(selection_root),
        ],
    )

    exit_code = select_cli.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Manifest:" in output
    assert paths.metadata_path.stem in output
