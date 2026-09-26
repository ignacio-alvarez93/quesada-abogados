"""QCC AUTO TWIN historical causal endpoint recovery.

Covers the new _historical_causal_endpoint_fingerprints() /
_historical_causal_endpoint_recovery() helpers in
backend/qcc/auto_twin/automatic_materialization.py, and their wiring
into reconcile_auto_twin_discovery_materialization().

Bug: AutoTwinObservationStore keeps no fingerprint history (only
baseline_fingerprint/last_fingerprint per identity). Once further REAL
observations advance an identity's last_fingerprint past a historical
TWIN_ELIGIBLE causal endpoint, _new_state_navigation_source() (which
only ever compares against the CURRENT last_fingerprint) can never
select that endpoint's evidence again -- even though the
HumanNavigationCandidate evidence proving it TWIN_ELIGIBLE is durable
and immutable. The historical endpoint must still become its own
physical Twin state (PASS 1) so the navigation transition can become
materializable once both endpoints physically exist (PASS 2, already
covered by test_qcc_auto_twin_learned_navigation_reaches_runtime.py's
_navigation_refresh_for_latest_revision() contract, reused directly
below).

The real end-to-end reconcile() proof
(test_recovered_endpoint_coexists_with_advanced_state) copies the REAL,
already-recorded TITULAR baseline capture
(data/qcc/site_architecture/20260912_060218_754542_25a0d363) into an
isolated tmp_path, exactly mirroring
test_qcc_auto_twin_causal_baseline_fallback.py's pattern, so the
site/state compatibility revalidation runs against genuine,
independently re-parsed DOM content. It is skipped when that real
capture evidence is not present in this checkout; every other test in
this module needs only cheap synthetic fixtures.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.qcc.auto_twin.automatic_materialization import (
    AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED,
    REQUIRED_ARTIFACTS,
    _historical_causal_endpoint_fingerprints,
    _historical_causal_endpoint_recovery,
    _navigation_refresh_for_latest_revision,
    reconcile_auto_twin_discovery_materialization,
)

from backend.qcc.auto_twin.navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    project_twin_eligible_navigation_candidates,
)

from backend.qcc.site_architecture import (
    QccSiteArchitectureIngestor,
)


FP_BEFORE = "3" * 64
FP_LATER = "9" * 64


# ---------------------------------------------------------------
# _historical_causal_endpoint_fingerprints() -- pure, no fixtures.
# ---------------------------------------------------------------


def _raw_candidate(
    *,
    candidate_id,
    before_fingerprint,
    after_fingerprint,
):
    return {
        "candidate_id": candidate_id,
        "evidence_source": AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
        "observation_count": 1,
        "status": "CONFIRMED",
        "before_fingerprint": before_fingerprint,
        "after_fingerprint": after_fingerprint,
        "navigation_context": [],
        "action": {
            "kind": "LINK",
            "policy": "NAVIGATION_CANDIDATE",
            "selector": 'a[onclick="irEx02()"]:qcc-nth-onclick(1)',
            "frame_path": "main",
        },
    }


def _projected(raw_candidate):
    return project_twin_eligible_navigation_candidates(
        {"candidates": [raw_candidate]}
    )[0]


def test_fingerprints_collects_only_missing_twin_eligible_endpoints():
    after_missing = "a" * 64

    eligible = _projected(
        _raw_candidate(
            candidate_id="cand-a",
            before_fingerprint=FP_BEFORE,
            after_fingerprint=after_missing,
        )
    )

    already_physical = _projected(
        _raw_candidate(
            candidate_id="cand-b",
            before_fingerprint=FP_BEFORE,
            after_fingerprint=FP_BEFORE,
        )
    )

    # Would otherwise contribute its own after_fingerprint to `missing`
    # -- only the eligibility override below must suppress it.
    not_eligible = dict(
        _projected(
            _raw_candidate(
                candidate_id="cand-c",
                before_fingerprint=FP_BEFORE,
                after_fingerprint="d" * 64,
            )
        )
    )
    not_eligible["eligibility"] = "SOMETHING_ELSE"

    missing = _historical_causal_endpoint_fingerprints(
        (eligible, already_physical, not_eligible),
        physical_fingerprints={FP_BEFORE},
    )

    assert missing == {after_missing}


def test_fingerprints_empty_when_everything_already_physical():
    eligible = _projected(
        _raw_candidate(
            candidate_id="cand-a",
            before_fingerprint=FP_BEFORE,
            after_fingerprint=FP_LATER,
        )
    )

    missing = _historical_causal_endpoint_fingerprints(
        (eligible,),
        physical_fingerprints={FP_BEFORE, FP_LATER},
    )

    assert missing == set()


# ---------------------------------------------------------------
# _historical_causal_endpoint_recovery() -- cheap synthetic fixture,
# mirrors test_qcc_site_architecture_observe_gate.py's minimal
# QCC_EXTENSION_DOM_CAPTURE shape so observe_candidate() genuinely
# recomputes fingerprint/pathname/site_code/functional_state in
# memory, exactly as production does.
# ---------------------------------------------------------------


def _extension_capture(
    *,
    pathname,
    body,
):
    frame = {
        "schema_version": 1,
        "captured_at": "2026-09-26T11:24:50Z",
        "url": "https://managed.test" + pathname,
        "origin": "https://managed.test",
        "pathname": pathname,
        "hostname": "managed.test",
        "title": "Managed twin page",
        "ready_state": "complete",
        "content_type": "text/html",
        "character_set": "UTF-8",
        "html": "<html><body>" + body + "</body></html>",
        "counts": {"elements": 0},
        "elements": [],
        "shadow_roots": [],
    }

    return {
        "ok": True,
        "capture_type": "QCC_EXTENSION_DOM_CAPTURE",
        "schema_version": 1,
        "captured_at": "2026-09-26T11:24:50Z",
        "tab_id": 1,
        "captured_frames": 1,
        # Extra key ignored by adapt_qcc_extension_capture(), read by
        # _capture_profile_key() exactly like a real qcc_capture.json.
        "browser_profile_key": "twin_discovery",
        "frames": [
            {
                "frame_id": 0,
                "document_id": "same-document",
                "result": frame,
            }
        ],
    }


def _ingested_fingerprint(capture_payload):
    return QccSiteArchitectureIngestor().observe_candidate(
        capture_payload
    )["fingerprint"]


def _write_capture(
    root,
    capture_id,
    capture_payload,
    *,
    omit=(),
):
    directory = root / capture_id
    directory.mkdir(parents=True, exist_ok=True)

    omit = set(omit)

    for filename in REQUIRED_ARTIFACTS:
        if filename in omit:
            continue

        path = directory / filename

        if filename == "qcc_capture.json":
            path.write_text(
                json.dumps(capture_payload),
                encoding="utf-8",
            )

        elif filename == "state_observation.json":
            path.write_text(
                json.dumps(
                    {
                        "fingerprint": _ingested_fingerprint(
                            capture_payload
                        ),
                    }
                ),
                encoding="utf-8",
            )

        elif filename.endswith(".png"):
            path.write_bytes(b"QCC_TEST_PNG")

        else:
            path.write_text("{}", encoding="utf-8")


def test_recovery_succeeds_for_exact_complete_matching_identity(
    tmp_path,
):
    capture = _extension_capture(
        pathname="/ex02",
        body="ENDPOINT_CONTENT",
    )

    fingerprint = _ingested_fingerprint(capture)

    _write_capture(tmp_path, "cap-endpoint", capture)

    observed_states = {
        "ex02": {
            "pathname": "/ex02",
            "functional_state": None,
        },
    }

    recovered = _historical_causal_endpoint_recovery(
        fingerprint=fingerprint,
        capture_root=tmp_path,
        expected_site_code=None,
        observed_states=observed_states,
    )

    assert recovered == {
        "capture_id": "cap-endpoint",
        "pathname": "/ex02",
        "functional_state": None,
    }


def test_recovery_fails_closed_when_identity_not_currently_tracked(
    tmp_path,
):
    capture = _extension_capture(
        pathname="/ex02",
        body="ENDPOINT_CONTENT",
    )

    fingerprint = _ingested_fingerprint(capture)

    _write_capture(tmp_path, "cap-endpoint", capture)

    observed_states = {
        "other": {
            "pathname": "/completely-different-route",
            "functional_state": None,
        },
    }

    recovered = _historical_causal_endpoint_recovery(
        fingerprint=fingerprint,
        capture_root=tmp_path,
        expected_site_code=None,
        observed_states=observed_states,
    )

    assert recovered is None


def test_recovery_fails_closed_on_site_code_mismatch(
    tmp_path,
):
    """An unregistered/unrecognized page has no site_code at all --
    a caller-supplied expected_site_code must still be honored and
    never silently ignored."""

    capture = _extension_capture(
        pathname="/ex02",
        body="ENDPOINT_CONTENT",
    )

    fingerprint = _ingested_fingerprint(capture)

    _write_capture(tmp_path, "cap-endpoint", capture)

    observed_states = {
        "ex02": {
            "pathname": "/ex02",
            "functional_state": None,
        },
    }

    recovered = _historical_causal_endpoint_recovery(
        fingerprint=fingerprint,
        capture_root=tmp_path,
        expected_site_code="MANAGED_TWIN",
        observed_states=observed_states,
    )

    assert recovered is None


def test_recovery_fails_closed_when_capture_incomplete(
    tmp_path,
):
    capture = _extension_capture(
        pathname="/ex02",
        body="ENDPOINT_CONTENT",
    )

    fingerprint = _ingested_fingerprint(capture)

    _write_capture(
        tmp_path,
        "cap-endpoint",
        capture,
        omit=("page.mhtml", "screenshot_viewport.png"),
    )

    observed_states = {
        "ex02": {
            "pathname": "/ex02",
            "functional_state": None,
        },
    }

    recovered = _historical_causal_endpoint_recovery(
        fingerprint=fingerprint,
        capture_root=tmp_path,
        expected_site_code=None,
        observed_states=observed_states,
    )

    assert recovered is None


def test_recovery_fails_closed_when_no_capture_matches_fingerprint(
    tmp_path,
):
    recovered = _historical_causal_endpoint_recovery(
        fingerprint="f" * 64,
        capture_root=tmp_path,
        expected_site_code=None,
        observed_states={},
    )

    assert recovered is None


# ---------------------------------------------------------------
# PASS 2: once both endpoints physically exist, the transition itself
# becomes materializable -- already the existing, unchanged contract
# of _navigation_refresh_for_latest_revision() (see
# test_qcc_auto_twin_learned_navigation_reaches_runtime.py). Proven
# here specifically against the two fingerprints this recovery
# mechanism is meant to close the gap for.
# ---------------------------------------------------------------


def _write_registry(revision_dir, states):
    runtime_dir = revision_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    (runtime_dir / "registry.json").write_text(
        json.dumps({"states": list(states)}),
        encoding="utf-8",
    )


def test_recovered_endpoint_makes_transition_materializable(
    tmp_path,
):
    candidate = _projected(
        _raw_candidate(
            candidate_id="cand-ex01-ex02",
            before_fingerprint=FP_BEFORE,
            after_fingerprint=FP_LATER,
        )
    )

    _write_registry(
        tmp_path,
        [
            {"state_id": "STATE_EX01", "fingerprint": FP_BEFORE},
        ],
    )

    # Before recovery: the after_fingerprint has no physical
    # representative yet -- the transition is correctly excluded.
    selected, refresh = _navigation_refresh_for_latest_revision(
        revision_dir=tmp_path,
        candidates=(candidate,),
    )

    assert selected == ()
    assert refresh is False

    # PASS 1 recovers the historical endpoint into its own physical
    # state in a new revision (simulated here directly on the
    # registry, exactly what materialize_auto_twin_plan() would persist
    # for a state_source produced by _historical_causal_endpoint_
    # recovery()).
    _write_registry(
        tmp_path,
        [
            {"state_id": "STATE_EX01", "fingerprint": FP_BEFORE},
            {"state_id": "STATE_EX02_RECOVERED", "fingerprint": FP_LATER},
        ],
    )

    selected, refresh = _navigation_refresh_for_latest_revision(
        revision_dir=tmp_path,
        candidates=(candidate,),
    )

    assert refresh is True
    assert len(selected) == 1
    assert selected[0]["candidate_id"] == "cand-ex01-ex02"


# ---------------------------------------------------------------
# Full reconcile() integration.
# ---------------------------------------------------------------


class ManagedStore:
    def __init__(self, site_code="MANAGED_TWIN"):
        self.site_code = site_code

    def get(self, twin_key):
        if twin_key != "managed_twin":
            return None

        return SimpleNamespace(
            twin_key="managed_twin",
            site_code=self.site_code,
            origins=("https://managed.test",),
            enabled=True,
            auto_update=True,
            discover_unknown_states=True,
        )


class ObservationStore:
    def __init__(self, states):
        self.states = states

    def snapshot(self, twin_key=None, *, current_only=False):
        return {
            "twins": {
                "managed_twin": {
                    "twin_key": "managed_twin",
                    "states": self.states,
                    "supersessions": {},
                }
            }
        }


class RevisionStore:
    def __init__(self, revisions=None):
        self.revisions = list(revisions or [])

    def list(self, *, twin_key=None):
        return [
            revision
            for revision in self.revisions
            if twin_key is None or revision.get("twin_key") == twin_key
        ]


class HumanNavigationCandidateStore:
    def __init__(self, candidates):
        self._candidates = list(candidates)

    def snapshot(self, site_code, *, environment="REAL"):
        return {"candidates": list(self._candidates)}


def _plan_spy(calls):
    def build(**kwargs):
        calls.append(kwargs)

        return {
            "plan_id": "matplan-test",
            "twin_key": kwargs["twin_key"],
            "materialization_mode": kwargs["materialization_mode"],
            "state_sources": list(kwargs["state_sources"]),
        }

    return build


def _materializer_spy(calls):
    def build(**kwargs):
        calls.append(kwargs)

        plan = kwargs["plan"]

        manifest = [
            {
                "state_id": item["state_id"],
                "source_capture_id": item["capture_id"],
                "pathname": item["pathname"],
                "functional_state": item.get("functional_state"),
            }
            for item in plan["state_sources"]
        ]

        return {
            "revision": {
                "materialized_revision_id": (
                    "matrev-test-" + str(len(manifest))
                ),
                "materialization_mode": plan["materialization_mode"],
                "state_manifest": manifest,
            }
        }

    return build


def _write_generic_capture(root, capture_id):
    directory = root / capture_id
    directory.mkdir(parents=True, exist_ok=True)

    for filename in REQUIRED_ARTIFACTS:
        path = directory / filename

        if filename == "qcc_capture.json":
            path.write_text(
                json.dumps({"browser_profile_key": "twin_discovery"}),
                encoding="utf-8",
            )

        elif filename.endswith(".png"):
            path.write_bytes(b"QCC_TEST_PNG")

        else:
            path.write_text("{}", encoding="utf-8")


def _write_renderer_marker(materialized_root, twin_key, revision_id):
    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    from backend.qcc.auto_twin.navigation_transition_runtime import (
        AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,
        AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME,
    )

    runtime_dir = materialized_root / twin_key / revision_id / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    (runtime_dir / "renderer.json").write_text(
        json.dumps(
            {"renderer_version": AUTO_TWIN_RUNTIME_RENDERER_VERSION}
        ),
        encoding="utf-8",
    )

    (runtime_dir / AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME).write_text(
        json.dumps(
            {
                "adapter_version": (
                    AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION
                ),
                "transitions": [],
            }
        ),
        encoding="utf-8",
    )


def test_recovery_is_a_safe_no_op_when_no_evidence_exists(
    tmp_path,
):
    """Non-regression guard: when nothing on disk can satisfy a
    TWIN_ELIGIBLE endpoint, the new recovery pass must never fabricate
    a state or otherwise change the existing, already-correct
    reconciliation outcome."""

    captures = tmp_path / "captures"
    materialized = tmp_path / "materialized"

    _write_generic_capture(captures, "cap-ex01-old")
    _write_generic_capture(captures, "cap-ex02-baseline")

    (
        captures / "cap-ex02-baseline" / "state_observation.json"
    ).write_text(
        json.dumps({"fingerprint": FP_LATER}),
        encoding="utf-8",
    )

    _write_registry(
        materialized / "managed_twin" / "matrev-old",
        [{"state_id": "STATE_EX01", "fingerprint": FP_BEFORE}],
    )

    _write_renderer_marker(materialized, "managed_twin", "matrev-old")

    previous = {
        "twin_key": "managed_twin",
        "materialized_revision_id": "matrev-old",
        "materialization_mode": "BOOTSTRAP_REAL",
        "state_manifest": [
            {
                "state_id": "STATE_EX01",
                "source_capture_id": "cap-ex01-old",
                "pathname": "/ex01",
                "functional_state": None,
            },
        ],
    }

    states = {
        "ex02-key": {
            "pathname": "/ex02",
            "functional_state": None,
            "baseline_capture_id": "cap-ex02-baseline",
            "last_capture_id": "cap-ex02-baseline",
            "last_fingerprint": FP_LATER,
        },
    }

    # A candidate whose after_fingerprint has no capture evidence
    # anywhere on disk at all -- recovery must find nothing and defer,
    # exactly like before this fix.
    unreachable_endpoint = "e" * 64

    human_navigation_candidate_store = HumanNavigationCandidateStore(
        [
            _raw_candidate(
                candidate_id="cand-ex01-ex02",
                before_fingerprint=FP_BEFORE,
                after_fingerprint=unreachable_endpoint,
            )
        ]
    )

    plan_calls = []

    result = reconcile_auto_twin_discovery_materialization(
        managed_site_store=ManagedStore(),
        observation_store=ObservationStore(states),
        capture_root=captures,
        trigger_capture_id="cap-ex02-baseline",
        materialized_root=materialized,
        revision_store=RevisionStore([previous]),
        plan_builder=_plan_spy(plan_calls),
        materializer=_materializer_spy([]),
        human_navigation_candidate_store=human_navigation_candidate_store,
    )

    assert result["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED

    # Only the normal BASELINE-sourced "/ex02" state was added -- the
    # unreachable historical endpoint never fabricates a second one.
    assert result["added_state_count"] == 1

    sources = plan_calls[0]["state_sources"]
    assert len(sources) == 2

    ex02_sources = [
        item for item in sources if item["pathname"] == "/ex02"
    ]

    assert len(ex02_sources) == 1
    assert ex02_sources[0]["capture_id"] == "cap-ex02-baseline"


# ---------------------------------------------------------------
# Real-shaped fixture: exercises the actual reported gap against
# genuine, independently re-parsed DOM evidence and a real registered
# site_code (MERCURIO) -- see test_qcc_auto_twin_causal_baseline_
# fallback.py, whose exact same real-capture pattern this reuses.
# ---------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CAPTURE_ROOT = REPO_ROOT / "data" / "qcc" / "site_architecture"

TITULAR_BASELINE_CAPTURE_ID = "20260912_060218_754542_25a0d363"


def _real_capture_available():
    return (REAL_CAPTURE_ROOT / TITULAR_BASELINE_CAPTURE_ID).is_dir()


requires_real_capture = pytest.mark.skipif(
    not _real_capture_available(),
    reason=(
        "real 20260912_060218_754542_25a0d363 capture evidence "
        "not present in this checkout"
    ),
)


def _copy_real_capture(dest_root, capture_id):
    shutil.copytree(
        REAL_CAPTURE_ROOT / capture_id,
        dest_root / capture_id,
    )


@requires_real_capture
def test_recovered_endpoint_coexists_with_advanced_state(
    tmp_path,
):
    captures = tmp_path / "captures"
    materialized = tmp_path / "materialized"

    _copy_real_capture(captures, TITULAR_BASELINE_CAPTURE_ID)

    from backend.qcc.auto_twin.automatic_materialization import (
        _recompute_capture_identity,
    )

    real_identity = _recompute_capture_identity(
        captures,
        TITULAR_BASELINE_CAPTURE_ID,
    )

    assert real_identity is not None
    assert real_identity["site_code"] == "MERCURIO"

    real_pathname = real_identity["pathname"]
    real_functional_state = real_identity["functional_state"]

    # QCC_AUTO_TWIN_CANONICAL_FINGERPRINT_DRIFT_V1 (see
    # test_qcc_auto_twin_causal_baseline_fallback.py): the fingerprint
    # HASH this capture recomputes to is a CURRENT-recognizer
    # implementation detail, not an immutable historical constant. This
    # is the recovered endpoint's own fingerprint -- both the
    # TWIN_ELIGIBLE historical evidence being recovered (below) and
    # this copy's cached state_observation.json index (which
    # _complete_discovery_capture_for_fingerprint() searches by) are
    # realigned to it, exactly as a capture freshly ingested by TODAY's
    # pipeline would already have on disk.
    titular_fingerprint = real_identity["fingerprint"]

    (
        captures / TITULAR_BASELINE_CAPTURE_ID / "state_observation.json"
    ).write_text(
        json.dumps(
            {
                "fingerprint": titular_fingerprint,
                "state": real_functional_state,
            }
        ),
        encoding="utf-8",
    )

    _write_generic_capture(captures, "cap-ex01-old")
    _write_generic_capture(captures, "cap-personal-baseline")

    (
        captures / "cap-personal-baseline" / "state_observation.json"
    ).write_text(
        json.dumps(
            {
                "fingerprint": FP_LATER,
                "state": real_functional_state,
            }
        ),
        encoding="utf-8",
    )

    _write_registry(
        materialized / "managed_twin" / "matrev-old",
        [{"state_id": "STATE_EX01_AUTH", "fingerprint": FP_BEFORE}],
    )

    _write_renderer_marker(materialized, "managed_twin", "matrev-old")

    previous = {
        "twin_key": "managed_twin",
        "materialized_revision_id": "matrev-old",
        "materialization_mode": "BOOTSTRAP_REAL",
        "state_manifest": [
            {
                "state_id": "STATE_EX01_AUTH",
                "source_capture_id": "cap-ex01-old",
                "pathname": "/auth",
                "functional_state": None,
            },
        ],
    }

    states = {
        "personal-key": {
            "pathname": real_pathname,
            "functional_state": real_functional_state,
            "baseline_capture_id": "cap-personal-baseline",
            "last_capture_id": "cap-personal-baseline",
            "last_fingerprint": FP_LATER,
        },
    }

    human_navigation_candidate_store = HumanNavigationCandidateStore(
        [
            _raw_candidate(
                candidate_id="cand-auth-personal",
                before_fingerprint=FP_BEFORE,
                after_fingerprint=titular_fingerprint,
            )
        ]
    )

    plan_calls = []

    result = reconcile_auto_twin_discovery_materialization(
        managed_site_store=ManagedStore(site_code="MERCURIO"),
        observation_store=ObservationStore(states),
        capture_root=captures,
        trigger_capture_id="cap-personal-baseline",
        materialized_root=materialized,
        revision_store=RevisionStore([previous]),
        plan_builder=_plan_spy(plan_calls),
        materializer=_materializer_spy([]),
        human_navigation_candidate_store=human_navigation_candidate_store,
    )

    assert result["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    assert result["added_state_count"] == 2

    sources = plan_calls[0]["state_sources"]

    matching = [
        item for item in sources if item["pathname"] == real_pathname
    ]

    assert len(matching) == 2

    capture_ids = {item["capture_id"] for item in matching}

    assert capture_ids == {
        "cap-personal-baseline",
        TITULAR_BASELINE_CAPTURE_ID,
    }

    state_ids = {item["state_id"] for item in matching}
    assert len(state_ids) == 2
