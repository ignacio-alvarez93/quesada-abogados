"""WO 2D-20U: governed CAUSAL_BASELINE_FALLBACK.

Covers _causal_baseline_fallback_capture(), _recompute_capture_identity()
and their wiring into _new_state_navigation_source() in
backend/qcc/auto_twin/automatic_materialization.py.

The positive/negative-but-must-recompute scenarios copy the REAL,
already-recorded TITULAR baseline capture
(data/qcc/site_architecture/20260912_060218_754542_25a0d363) into an
isolated tmp_path -- this is read-only against the real repository
data (shutil.copytree never writes back) and gives the independent
recomputation pipeline (adapt_qcc_extension_capture ->
normalize_dom_capture -> QccSiteArchitectureIngestor.observe_candidate())
genuine, real-shaped DOM content to work against, exactly reproducing
the 2D-20T finding: baseline 20260912_060218_754542_25a0d363
independently revalidates to a stable capability-aware fingerprint
(TITULAR_FINGERPRINT below, recomputed at collection time rather than
hardcoded -- see QCC_AUTO_TWIN_CANONICAL_FINGERPRINT_DRIFT_V1, since
the exact hash is a CURRENT-recognizer implementation detail that
drifts across recognizer versions even though the capture's bytes
never change) while 20260912_060228_192874_aa602bac (the real,
still-incomplete CAUSAL_LAST) is missing
page.mhtml/screenshot_viewport.png.

Scenarios that never need real DOM content (CAUSAL_LAST valid,
CAUSAL_EQUIVALENT found, plain BASELINE path) reuse the same cheap
synthetic fixture style as
test_qcc_auto_twin_causal_equivalent_evidence.py.

This suite never runs real PASS 2 and never mutates
data/qcc/auto_twin/ or data/qcc/site_architecture/.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.qcc.auto_twin.automatic_materialization import (
    REQUIRED_ARTIFACTS,
    _causal_baseline_fallback_capture,
    _complete_discovery_capture_for_fingerprint,
    _new_state_navigation_source,
    _recompute_capture_identity,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CAPTURE_ROOT = REPO_ROOT / "data" / "qcc" / "site_architecture"

TITULAR_BASELINE_CAPTURE_ID = "20260912_060218_754542_25a0d363"
TITULAR_INCOMPLETE_LAST_CAPTURE_ID = "20260912_060228_192874_aa602bac"


def _real_capture_available():
    return (
        REAL_CAPTURE_ROOT / TITULAR_BASELINE_CAPTURE_ID
    ).is_dir()


# QCC_AUTO_TWIN_CANONICAL_FINGERPRINT_DRIFT_V1
#
# The exact fingerprint HASH produced for one immutable capture is an
# implementation detail of the CURRENT canonical recognizer -- it drifts
# across recognizer versions (e.g. new capability augmentation such as
# 2D-20H's apply_mercurio_functional_fingerprint_capability), even
# though the capture's own bytes never change. Hardcoding that hash as
# a frozen constant makes every test below brittle against unrelated
# recognizer improvements that never touch this capture's actual
# functional_state/site_code/state_variant_key identity. Recomputing it
# here once, directly against the real, unmodified, committed capture
# (read-only -- _recompute_capture_identity() never writes anything),
# keeps every test below anchored to whatever the CURRENT canonical
# pipeline actually produces instead of a stale historical value.
TITULAR_FINGERPRINT = (
    _recompute_capture_identity(
        REAL_CAPTURE_ROOT,
        TITULAR_BASELINE_CAPTURE_ID,
    )["fingerprint"]
    if _real_capture_available()
    else "0" * 64
)

UNRELATED_FINGERPRINT = (
    "cc" + "0" * 62
)


requires_real_capture = pytest.mark.skipif(
    not _real_capture_available(),
    reason=(
        "real 20260912_060218_754542_25a0d363 capture evidence "
        "not present in this checkout"
    ),
)


def _copy_real_capture(
    dest_root,
    capture_id,
    *,
    strip_artifacts=(),
):
    """Copy one real, immutable capture into an isolated tmp_path.

    Read-only against the real repository data: shutil.copytree only
    ever reads the source and writes under dest_root (tmp_path).
    """

    source = REAL_CAPTURE_ROOT / capture_id
    dest = dest_root / capture_id

    shutil.copytree(source, dest)

    for filename in strip_artifacts:
        (dest / filename).unlink(missing_ok=True)

    return dest


def _titular_state(
    *,
    last_capture_id=TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
    baseline_capture_id=TITULAR_BASELINE_CAPTURE_ID,
    last_fingerprint=TITULAR_FINGERPRINT,
    functional_state="EX01_PERSONAL",
    state_variant_key="NO_FAMILIAR_TAB",
):
    return {
        "baseline_capture_id": baseline_capture_id,
        "last_capture_id": last_capture_id,
        "last_fingerprint": last_fingerprint,
        "functional_state": functional_state,
        "state_variant_key": state_variant_key,
    }


def _titular_candidate():
    return {
        "before_fingerprint": (
            "0f048a41feded5af2ceae831e57bf6c1d"
            "79d3d86ccfe991c698a5b21e3e7aca2"
        ),
        "after_fingerprint": TITULAR_FINGERPRINT,
    }


# ---------------------------------------------------------------
# Cheap synthetic fixtures (no real DOM parsing required) -- mirrors
# test_qcc_auto_twin_causal_equivalent_evidence.py exactly, reused
# here to prove CAUSAL_LAST/CAUSAL_EQUIVALENT precedence is untouched.
# ---------------------------------------------------------------

FP_PERSONAL = (
    "d0af84caa02f93f585f9df7f3e2ef82"
    "b487348a64550e07c54f481e58e84e2f4"
)

FP_AUTH = (
    "0f048a41feded5af2ceae831e57bf6c1d"
    "79d3d86ccfe991c698a5b21e3e7aca2"
)


def _synthetic_capture(
    root,
    capture_id,
    *,
    fingerprint,
    functional_state,
    profile="twin_discovery",
    complete=True,
):
    directory = root / capture_id
    directory.mkdir(parents=True)

    for filename in REQUIRED_ARTIFACTS:
        if (
            not complete
            and filename
            in {"page.mhtml", "screenshot_viewport.png"}
        ):
            continue

        path = directory / filename

        if filename == "qcc_capture.json":
            path.write_text(
                json.dumps({"browser_profile_key": profile}),
                encoding="utf-8",
            )

        elif filename == "state_observation.json":
            path.write_text(
                json.dumps(
                    {
                        "fingerprint": fingerprint,
                        "state": functional_state,
                    }
                ),
                encoding="utf-8",
            )

        elif filename.endswith(".png"):
            path.write_bytes(b"QCC_TEST_PNG")

        else:
            path.write_text("{}", encoding="utf-8")


def _synthetic_state(last_capture_id):
    return {
        "baseline_capture_id": "baseline",
        "last_capture_id": last_capture_id,
        "last_fingerprint": FP_PERSONAL,
        "functional_state": "EX01_PERSONAL",
    }


def _synthetic_candidate():
    return {
        "before_fingerprint": FP_AUTH,
        "after_fingerprint": FP_PERSONAL,
    }


def test_valid_causal_last_still_wins_over_baseline_fallback(
    tmp_path,
):
    causal = "20260912_060635_complete"

    _synthetic_capture(
        tmp_path,
        causal,
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
    )

    source_id, source_kind = _new_state_navigation_source(
        _synthetic_state(causal),
        (_synthetic_candidate(),),
        capture_root=tmp_path,
    )

    assert source_id == causal
    assert source_kind == "CAUSAL_LAST"


def test_valid_causal_equivalent_still_wins_over_baseline_fallback(
    tmp_path,
):
    causal = "20260912_060635_incomplete"

    _synthetic_capture(
        tmp_path,
        causal,
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
        complete=False,
    )

    _synthetic_capture(
        tmp_path,
        "20260912_060631_equivalent",
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
    )

    source_id, source_kind = _new_state_navigation_source(
        _synthetic_state(causal),
        (_synthetic_candidate(),),
        capture_root=tmp_path,
    )

    assert source_id == "20260912_060631_equivalent"
    assert source_kind == "CAUSAL_EQUIVALENT"


def test_no_fallback_silently_degrades_to_baseline(
    tmp_path,
):
    """A state with no TWIN_ELIGIBLE candidate reference must keep the
    plain, unaffected BASELINE label -- CAUSAL_BASELINE_FALLBACK must
    never leak into this unrelated contract."""

    state = _synthetic_state("20260912_060635_never_referenced")

    source_id, source_kind = _new_state_navigation_source(
        state,
        (),  # no navigation candidates at all
        capture_root=tmp_path,
    )

    assert source_id == "baseline"
    assert source_kind == "BASELINE"


# ---------------------------------------------------------------
# Real-shaped TITULAR fixture: exercises the actual gap found by
# 2D-20T against genuine, independently re-parsed DOM evidence.
# ---------------------------------------------------------------


@requires_real_capture
def test_recompute_capture_identity_matches_real_titular_baseline(
    tmp_path,
):
    _copy_real_capture(tmp_path, TITULAR_BASELINE_CAPTURE_ID)

    identity = _recompute_capture_identity(
        tmp_path,
        TITULAR_BASELINE_CAPTURE_ID,
    )

    assert identity is not None
    assert identity["fingerprint"] == TITULAR_FINGERPRINT
    assert identity["functional_state"] == "EX01_PERSONAL"
    assert identity["site_code"] == "MERCURIO"
    assert identity["state_variant_key"] == "NO_FAMILIAR_TAB"


@requires_real_capture
def test_incomplete_causal_last_no_equivalent_selects_baseline_fallback(
    tmp_path,
):
    _copy_real_capture(tmp_path, TITULAR_BASELINE_CAPTURE_ID)

    _copy_real_capture(
        tmp_path,
        TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
        strip_artifacts=(
            "page.mhtml",
            "screenshot_viewport.png",
        ),
    )

    # No CAUSAL_EQUIVALENT exists: the generic-fingerprint index that
    # _complete_discovery_capture_for_fingerprint() searches never
    # contains the capability-aware TITULAR_FINGERPRINT (this is the
    # exact 2D-20T gap) -- confirmed directly here too.
    equivalent = _complete_discovery_capture_for_fingerprint(
        capture_root=tmp_path,
        fingerprint=TITULAR_FINGERPRINT,
        functional_state="EX01_PERSONAL",
        exclude_capture_id=TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
    )

    assert equivalent is None

    source_id, source_kind = _new_state_navigation_source(
        _titular_state(),
        (_titular_candidate(),),
        capture_root=tmp_path,
        expected_site_code="MERCURIO",
    )

    assert source_id == TITULAR_BASELINE_CAPTURE_ID
    assert source_kind == "CAUSAL_BASELINE_FALLBACK"


@requires_real_capture
def test_baseline_with_different_expected_fingerprint_is_rejected(
    tmp_path,
):
    _copy_real_capture(tmp_path, TITULAR_BASELINE_CAPTURE_ID)

    _copy_real_capture(
        tmp_path,
        TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
        strip_artifacts=(
            "page.mhtml",
            "screenshot_viewport.png",
        ),
    )

    state = _titular_state(
        last_fingerprint=UNRELATED_FINGERPRINT,
    )

    candidate = {
        "before_fingerprint": (
            "0f048a41feded5af2ceae831e57bf6c1d"
            "79d3d86ccfe991c698a5b21e3e7aca2"
        ),
        "after_fingerprint": UNRELATED_FINGERPRINT,
    }

    source_id, source_kind = _new_state_navigation_source(
        state,
        (candidate,),
        capture_root=tmp_path,
        expected_site_code="MERCURIO",
    )

    # Falls through to the existing, unchanged fail-closed contract:
    # CAUSAL_LAST is still reported (and remains evidence-incomplete
    # downstream), never the baseline.
    assert source_id == TITULAR_INCOMPLETE_LAST_CAPTURE_ID
    assert source_kind == "CAUSAL_LAST"


@requires_real_capture
def test_incomplete_baseline_is_rejected(
    tmp_path,
):
    _copy_real_capture(
        tmp_path,
        TITULAR_BASELINE_CAPTURE_ID,
        strip_artifacts=(
            "page.mhtml",
            "screenshot_viewport.png",
        ),
    )

    _copy_real_capture(
        tmp_path,
        TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
        strip_artifacts=(
            "page.mhtml",
            "screenshot_viewport.png",
        ),
    )

    source_id, source_kind = _new_state_navigation_source(
        _titular_state(),
        (_titular_candidate(),),
        capture_root=tmp_path,
        expected_site_code="MERCURIO",
    )

    assert source_id == TITULAR_INCOMPLETE_LAST_CAPTURE_ID
    assert source_kind == "CAUSAL_LAST"


@requires_real_capture
def test_incompatible_state_variant_is_rejected(
    tmp_path,
):
    _copy_real_capture(tmp_path, TITULAR_BASELINE_CAPTURE_ID)

    _copy_real_capture(
        tmp_path,
        TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
        strip_artifacts=(
            "page.mhtml",
            "screenshot_viewport.png",
        ),
    )

    state = _titular_state(
        state_variant_key="FAMILIAR_TAB_AVAILABLE",
    )

    source_id, source_kind = _new_state_navigation_source(
        state,
        (_titular_candidate(),),
        capture_root=tmp_path,
        expected_site_code="MERCURIO",
    )

    assert source_id == TITULAR_INCOMPLETE_LAST_CAPTURE_ID
    assert source_kind == "CAUSAL_LAST"


@requires_real_capture
def test_missing_baseline_is_rejected(
    tmp_path,
):
    _copy_real_capture(
        tmp_path,
        TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
        strip_artifacts=(
            "page.mhtml",
            "screenshot_viewport.png",
        ),
    )

    state = _titular_state(
        baseline_capture_id="",
    )

    source_id, source_kind = _new_state_navigation_source(
        state,
        (_titular_candidate(),),
        capture_root=tmp_path,
        expected_site_code="MERCURIO",
    )

    assert source_id == TITULAR_INCOMPLETE_LAST_CAPTURE_ID
    assert source_kind == "CAUSAL_LAST"


@requires_real_capture
def test_unrelated_provider_site_is_rejected(
    tmp_path,
):
    """A real, complete, exact-fingerprint baseline must still be
    rejected when it does not belong to the site being materialized --
    proves the guard is provider-neutral, not Mercurio-hardcoded."""

    _copy_real_capture(tmp_path, TITULAR_BASELINE_CAPTURE_ID)

    _copy_real_capture(
        tmp_path,
        TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
        strip_artifacts=(
            "page.mhtml",
            "screenshot_viewport.png",
        ),
    )

    source_id, source_kind = _new_state_navigation_source(
        _titular_state(),
        (_titular_candidate(),),
        capture_root=tmp_path,
        expected_site_code="UNRELATED_OTHER_SITE",
    )

    assert source_id == TITULAR_INCOMPLETE_LAST_CAPTURE_ID
    assert source_kind == "CAUSAL_LAST"


@requires_real_capture
def test_causal_baseline_fallback_capture_direct_contract(tmp_path):
    _copy_real_capture(tmp_path, TITULAR_BASELINE_CAPTURE_ID)

    accepted = _causal_baseline_fallback_capture(
        _titular_state(),
        capture_root=tmp_path,
        last_fingerprint=TITULAR_FINGERPRINT,
        baseline_capture_id=TITULAR_BASELINE_CAPTURE_ID,
        last_capture_id=TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
        expected_site_code="MERCURIO",
    )

    assert accepted == TITULAR_BASELINE_CAPTURE_ID

    # Same-as-last-capture is never a fallback (nothing to fall back
    # to).
    rejected_same = _causal_baseline_fallback_capture(
        _titular_state(),
        capture_root=tmp_path,
        last_fingerprint=TITULAR_FINGERPRINT,
        baseline_capture_id=TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
        last_capture_id=TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
        expected_site_code="MERCURIO",
    )

    assert rejected_same is None

    # No baseline recorded at all.
    rejected_missing = _causal_baseline_fallback_capture(
        _titular_state(baseline_capture_id=""),
        capture_root=tmp_path,
        last_fingerprint=TITULAR_FINGERPRINT,
        baseline_capture_id="",
        last_capture_id=TITULAR_INCOMPLETE_LAST_CAPTURE_ID,
        expected_site_code="MERCURIO",
    )

    assert rejected_missing is None
