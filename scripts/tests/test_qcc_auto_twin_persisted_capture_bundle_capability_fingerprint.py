"""WO 2D-20V: capability-aware materialization fingerprint source.

Covers _current_functional_fingerprint() and its wiring into
load_auto_twin_persisted_capture_bundle() in
backend/qcc/auto_twin/persisted_capture_bundle.py.

The real-shaped scenarios copy the REAL, already-recorded TITULAR and
FAMILIAR captures (data/qcc/site_architecture/
20260912_060218_754542_25a0d363 and .../20260912_060631_109928_94d6a6ca)
into an isolated tmp_path -- read-only against the real repository
data -- to prove the exact end-to-end fix for the defect found in the
final 2D-20 CALL 1 (matrev-684fc2abc9bbea4402bd0261): both captures'
own cached state_observation.json carry the SAME pre-2D-20H generic
fingerprint (d0af84c...), yet the materialized bundle must now project
each to its distinct, capability-aware CURRENT identity, exactly as
QccSiteArchitectureIngestor._observe_state() already does at
observation-ingestion time.

Purely synthetic fixtures cover provider-neutrality, branch-code
neutrality, and fail-closed ambiguity -- never touching real data.

Never runs real PASS 2, never mutates data/.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.automation.site_architecture import (
    adapt_qcc_extension_capture,
    normalize_dom_capture,
)
from backend.qcc.auto_twin.persisted_capture_bundle import (
    _current_functional_fingerprint,
    load_auto_twin_persisted_capture_bundle,
)
from backend.qcc.site_architecture.ingestor import (
    QccSiteArchitectureIngestor,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CAPTURE_ROOT = REPO_ROOT / "data" / "qcc" / "site_architecture"

TITULAR_CAPTURE_ID = "20260912_060218_754542_25a0d363"
FAMILIAR_CAPTURE_ID = "20260912_060631_109928_94d6a6ca"

TITULAR_FINGERPRINT = (
    "52efb715d5688ad10cb2945d862847868ce25b4"
    "208f6ca84dcf57aa8a4032311"
)
FAMILIAR_FINGERPRINT = (
    "88c730539a17c84d7c3ac6fb753c7ba40a748928"
    "9f7d0c950d815f3aa568ae38"
)
LEGACY_GENERIC_FINGERPRINT = (
    "d0af84caa02f93f585f9df7f3e2ef82b487348a"
    "64550e07c54f481e58e84e2f4"
)


def _real_captures_available():
    return (
        (REAL_CAPTURE_ROOT / TITULAR_CAPTURE_ID).is_dir()
        and (REAL_CAPTURE_ROOT / FAMILIAR_CAPTURE_ID).is_dir()
    )


requires_real_captures = pytest.mark.skipif(
    not _real_captures_available(),
    reason=(
        "real TITULAR/FAMILIAR capture evidence not present in this "
        "checkout"
    ),
)


def _copy_real_capture(dest_root, capture_id):
    """Read-only against the real repository data: copies into an
    isolated tmp_path, never writes back to the source."""

    shutil.copytree(
        REAL_CAPTURE_ROOT / capture_id,
        dest_root / capture_id,
    )


# ---------------------------------------------------------------
# Real-shaped end-to-end fixtures.
# ---------------------------------------------------------------


@requires_real_captures
def test_titular_capture_projects_to_current_titular_fingerprint(
    tmp_path,
):
    _copy_real_capture(tmp_path, TITULAR_CAPTURE_ID)

    bundle = load_auto_twin_persisted_capture_bundle(
        capture_id=TITULAR_CAPTURE_ID,
        root=tmp_path,
    )

    assert bundle["fingerprint"] == TITULAR_FINGERPRINT
    assert bundle["raw_fingerprint"] == LEGACY_GENERIC_FINGERPRINT
    assert bundle["site_code"] == "MERCURIO"


@requires_real_captures
def test_familiar_capture_projects_to_current_familiar_fingerprint(
    tmp_path,
):
    _copy_real_capture(tmp_path, FAMILIAR_CAPTURE_ID)

    bundle = load_auto_twin_persisted_capture_bundle(
        capture_id=FAMILIAR_CAPTURE_ID,
        root=tmp_path,
    )

    assert bundle["fingerprint"] == FAMILIAR_FINGERPRINT
    assert bundle["raw_fingerprint"] == LEGACY_GENERIC_FINGERPRINT
    assert bundle["site_code"] == "MERCURIO"


@requires_real_captures
def test_legacy_generic_fingerprint_remains_historically_readable_but_not_current(
    tmp_path,
):
    _copy_real_capture(tmp_path, TITULAR_CAPTURE_ID)

    bundle = load_auto_twin_persisted_capture_bundle(
        capture_id=TITULAR_CAPTURE_ID,
        root=tmp_path,
    )

    # Historical evidence unchanged and still readable...
    assert bundle["raw_fingerprint"] == LEGACY_GENERIC_FINGERPRINT

    # ...but it never becomes the CURRENT projected identity once a
    # capability-aware replacement exists for it.
    assert bundle["fingerprint"] != LEGACY_GENERIC_FINGERPRINT
    assert bundle["fingerprint"] == TITULAR_FINGERPRINT

    # The raw, persisted capture files on disk are byte-for-byte
    # untouched.
    raw_state_observation = json.loads(
        (
            tmp_path
            / TITULAR_CAPTURE_ID
            / "state_observation.json"
        ).read_text(encoding="utf-8")
    )

    assert (
        raw_state_observation["fingerprint"]
        == LEGACY_GENERIC_FINGERPRINT
    )


@requires_real_captures
def test_observation_and_materialization_projections_agree(
    tmp_path,
):
    """The exact same immutable capture must yield the exact same
    CURRENT fingerprint whether projected via observation ingestion
    (QccSiteArchitectureIngestor._observe_state(), 2D-20H/J) or via
    materialization-time bundle loading (2D-20V) -- proving the fix
    reuses the canonical semantics rather than a parallel one."""

    _copy_real_capture(tmp_path, TITULAR_CAPTURE_ID)

    raw_capture = json.loads(
        (
            tmp_path
            / TITULAR_CAPTURE_ID
            / "qcc_capture.json"
        ).read_text(encoding="utf-8")
    )

    adapted = adapt_qcc_extension_capture(raw_capture)
    snapshot = normalize_dom_capture(adapted)
    observed = QccSiteArchitectureIngestor().observe_candidate(
        raw_capture
    )

    bundle = load_auto_twin_persisted_capture_bundle(
        capture_id=TITULAR_CAPTURE_ID,
        root=tmp_path,
    )

    assert observed["fingerprint"] == bundle["fingerprint"]
    assert observed["fingerprint"] == TITULAR_FINGERPRINT


# ---------------------------------------------------------------
# Synthetic fixtures: provider-neutrality, branch-code neutrality,
# fail-closed ambiguity.
# ---------------------------------------------------------------


def _pest_familiar_element(*, hidden):
    return {
        "id": "pestFamiliar",
        "style": "display: none;" if hidden else "",
    }


def test_non_mercurio_provider_preserves_legacy_fingerprint():
    generic = "a" * 64

    result = _current_functional_fingerprint(
        site_code="SOME_OTHER_SITE",
        functional_state="EX01_PERSONAL",
        generic_fingerprint=generic,
        snapshot={
            "elements": [
                _pest_familiar_element(hidden=False)
            ]
        },
    )

    assert result == generic


def test_non_ex01_personal_state_preserves_legacy_fingerprint():
    generic = "b" * 64

    result = _current_functional_fingerprint(
        site_code="MERCURIO",
        functional_state="EX01_AUTHORIZATION",
        generic_fingerprint=generic,
        snapshot={
            "elements": [
                _pest_familiar_element(hidden=False)
            ]
        },
    )

    assert result == generic


def test_ambiguous_capability_signal_fails_closed_to_generic():
    """No pestFamiliar element observable at all -- must never borrow
    or guess a different fingerprint; stays exactly as recorded."""

    generic = "c" * 64

    result = _current_functional_fingerprint(
        site_code="MERCURIO",
        functional_state="EX01_PERSONAL",
        generic_fingerprint=generic,
        snapshot={"elements": []},
    )

    assert result == generic


def test_malformed_snapshot_fails_closed_to_generic():
    generic = "d" * 64

    result = _current_functional_fingerprint(
        site_code="MERCURIO",
        functional_state="EX01_PERSONAL",
        generic_fingerprint=generic,
        snapshot=None,
    )

    assert result == generic


def test_branch_codes_alone_do_not_affect_current_fingerprint():
    generic = "e" * 64

    snapshot_130 = {
        "elements": [
            _pest_familiar_element(hidden=True),
            {"id": "datosForAut", "value": "130"},
        ]
    }

    snapshot_131_same_capability = {
        "elements": [
            _pest_familiar_element(hidden=True),
            {"id": "datosForAut", "value": "131"},
        ]
    }

    result_130 = _current_functional_fingerprint(
        site_code="MERCURIO",
        functional_state="EX01_PERSONAL",
        generic_fingerprint=generic,
        snapshot=snapshot_130,
    )

    result_131 = _current_functional_fingerprint(
        site_code="MERCURIO",
        functional_state="EX01_PERSONAL",
        generic_fingerprint=generic,
        snapshot=snapshot_131_same_capability,
    )

    assert result_130 == result_131
    assert result_130 != generic


def test_distinct_capability_signals_project_distinct_fingerprints():
    generic = "f" * 64

    titular = _current_functional_fingerprint(
        site_code="MERCURIO",
        functional_state="EX01_PERSONAL",
        generic_fingerprint=generic,
        snapshot={
            "elements": [
                _pest_familiar_element(hidden=True)
            ]
        },
    )

    familiar = _current_functional_fingerprint(
        site_code="MERCURIO",
        functional_state="EX01_PERSONAL",
        generic_fingerprint=generic,
        snapshot={
            "elements": [
                _pest_familiar_element(hidden=False)
            ]
        },
    )

    assert titular != familiar
    assert titular != generic
    assert familiar != generic


def test_lowercase_site_code_still_matches_mercurio():
    """site_code casing from persisted metadata must not silently
    disable the capability augmentation for the real provider."""

    generic = "1" * 64

    result = _current_functional_fingerprint(
        site_code="mercurio",
        functional_state="EX01_PERSONAL",
        generic_fingerprint=generic,
        snapshot={
            "elements": [
                _pest_familiar_element(hidden=True)
            ]
        },
    )

    assert result != generic
