"""QCC_BRANCH_CONTEXT_CAPTURE_V1 bridge sequencing regression suite.

Covers the corrected backend/qcc/bridge/server.py ordering for
POST /qcc/site-architecture/capture:

    live CURRENT projection
        -> human causal correlation/finalization
        -> human navigation learning
        -> BranchContext resolution (from THIS capture's learning
           result only)
        -> AUTO TWIN observation (exactly once)
        -> AUTO TWIN CandidateRevision projection
        -> post-learning AUTO TWIN materialization trigger

No timing-based assertions: ordering is proven either structurally
(static source position) or dynamically (deterministic spies wrapping
the real, unmocked implementations and recording call order).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import backend.qcc.bridge.server as qcc_bridge_server

from backend.qcc.auto_twin.candidate_revision_store import (
    AutoTwinCandidateRevisionStore,
)
from backend.qcc.auto_twin.managed_site_registry import (
    AutoTwinManagedSite,
)
from backend.qcc.auto_twin.managed_site_store import (
    AutoTwinManagedSiteStore,
)
from backend.qcc.auto_twin.observation_store import (
    AutoTwinObservationStore,
)
from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.context.observed_human_action import (
    QccObservedHumanAction,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)
from backend.qcc.navigation_knowledge import (
    NavigationKnowledgeStore,
)
from backend.qcc.navigation_learning import (
    HumanNavigationCandidateStore,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_LAB_ORIGIN,
)


ROOT = Path(__file__).resolve().parents[2]

SERVER_SOURCE = (
    ROOT / "backend" / "qcc" / "bridge" / "server.py"
).read_text(encoding="utf-8")

SITE = "MERCURIO"
ENV = "LAB"
PATHNAME = "/mercurio/entrada.html"
PROFILE_KEY = "twin_discovery"

FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64

ACTION_SELECTOR = "#continue"


def _iso(base, offset_seconds=0.0):
    """ISO timestamp near real wall-clock time.

    QccContextStore's pending human-action TTL (30s) is checked
    against the real `datetime.now()`, so fixture timestamps must be
    anchored to a real `base` instant, not a fixed fictional date.
    """

    return (
        base + timedelta(seconds=offset_seconds)
    ).isoformat()


def _nav_context(value):
    return [
        {
            "key": "ROUTE",
            "selector": "select#route",
            "frame_path": "main",
            "kind": "SELECT",
            "selected_values": [value],
        },
    ]


def _session():
    return QccPresentationSession(
        session_id="session-1",
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider=SITE,
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime.now(timezone.utc),
        status=QccPresentationStatus.AUTOMATING,
        current_step="TEST",
        progress=0,
        requires_user_action=False,
        last_event=None,
    )


class _ControlledIngestor:
    """Deterministic stand-in: the real ingestor's persisted-capture
    authority is not under test here, only the Bridge's own
    post-ingest sequencing."""

    def __init__(self, *, pathname=PATHNAME):
        self.pathname = pathname

    def ingest(self, capture, *, context=None):
        return {
            "capture_id": capture["capture_id"],
            "context_mode": "SESSION_BOUND",
            "session_id": "session-1",
            "received_at": capture["received_at"],
            "page": {
                "url": MERCURIO_LAB_ORIGIN + self.pathname,
            },
            "site_code": SITE,
            "state_observation": {
                "state": capture["state"],
                "fingerprint": capture["fingerprint"],
            },
            "live_actions": (),
            "counts": {"elements": 0},
        }


def _context_store(bridge):
    """The per-profile QccContextStore actually used by the capture
    handler for this test's browser_profile_key (see
    _qcc_resolve_context_store_for_profile() in server.py: a non-empty
    browser_profile_key always routes through the browser registry,
    never the bridge's own legacy context_store)."""

    return bridge.browser_registry.get_or_create_store(PROFILE_KEY)


def _post_capture(
    bridge,
    *,
    capture_id,
    state,
    fingerprint,
    received_at,
    browser_profile_key=PROFILE_KEY,
):
    body = json.dumps({
        "protocol_version": QCC_PROTOCOL_VERSION,
        "browser_profile_key": browser_profile_key,
        "capture": {
            "capture_id": capture_id,
            "state": state,
            "fingerprint": fingerprint,
            "received_at": received_at,
        },
    }).encode("utf-8")

    request = Request(
        f"http://{bridge.host}:{bridge.port}"
        "/qcc/site-architecture/capture",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        response = urlopen(request, timeout=3)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))

    with response:
        return (
            response.status,
            json.loads(response.read().decode("utf-8")),
        )


def _build_bridge(tmp_path, **kwargs):
    managed_store = AutoTwinManagedSiteStore(
        path=tmp_path / "managed.json"
    )

    managed_store.register(
        AutoTwinManagedSite(
            twin_key="mercurio_twin",
            site_code=SITE,
            origins=(MERCURIO_LAB_ORIGIN,),
            path_prefixes=("/mercurio",),
        )
    )

    defaults = dict(
        port=0,
        site_architecture_ingestor=_ControlledIngestor(),
        navigation_knowledge_store=NavigationKnowledgeStore(
            root=tmp_path / "knowledge"
        ),
        human_navigation_candidate_store=(
            HumanNavigationCandidateStore(
                root=tmp_path / "human-candidates"
            )
        ),
        auto_twin_store=managed_store,
        auto_twin_observation_store=AutoTwinObservationStore(
            path=tmp_path / "observation.json"
        ),
        auto_twin_candidate_store=AutoTwinCandidateRevisionStore(
            path=tmp_path / "candidate_revisions.json"
        ),
    )

    defaults.update(kwargs)

    bridge = QccBridgeServer(**defaults)
    _context_store(bridge).set_active_session(_session())
    bridge.start()

    return bridge


def _pre_populate_other_branch(bridge, *, selected_value, after_fingerprint):
    bridge.human_navigation_candidate_store.record_observed_transition({
        "changed": True,
        "event_id": "evt-pre-" + selected_value,
        "after_observed_at": "2026-09-05T15:00:05+00:00",
        "site_code": SITE,
        "environment": ENV,
        "before_state": "STATE_A",
        "before_fingerprint": FP_A,
        "navigation_context": _nav_context(selected_value),
        "kind": "LINK",
        "policy": "NAVIGATION_CANDIDATE",
        "selector": ACTION_SELECTOR,
        "frame_path": "main",
        "after_state": "STATE_B",
        "after_fingerprint": after_fingerprint,
    })


def _arm_pending_human_action(
    bridge, *, selected_value, event_id, observed_at,
):
    action = QccObservedHumanAction(
        event_id=event_id,
        session_id="session-1",
        site_code=SITE,
        environment=ENV,
        before_state="STATE_A",
        before_fingerprint=FP_A,
        kind="LINK",
        policy="NAVIGATION_CANDIDATE",
        selector=ACTION_SELECTOR,
        frame_path="main",
        observed_at=observed_at,
        navigation_context=tuple(_nav_context(selected_value)),
    )

    _context_store(bridge).set_observed_human_action(action)


class _CallSpy:
    """Wraps a real callable, recording invocation order/kwargs while
    always delegating to the original implementation."""

    def __init__(self, label, original, calls, *, capture_kwargs=None):
        self.label = label
        self.original = original
        self.calls = calls
        self.capture_kwargs = capture_kwargs or (lambda kwargs: None)

    def __call__(self, *args, **kwargs):
        self.calls.append(self.label)
        self.capture_kwargs(kwargs)
        return self.original(*args, **kwargs)


# ---------------------------------------------------------------------------
# 1/2/3. Static ordering: human causal finalization + navigation
# learning + BranchContext resolution happen (in source order, inside
# the capture handler) before the AUTO TWIN observation projection.
# ---------------------------------------------------------------------------


def test_source_order_learning_then_branch_resolution_then_observe():
    handler_start = SERVER_SOURCE.index(
        '"/qcc/site-architecture/capture"'
    )

    handler_end = SERVER_SOURCE.index(
        '"/qcc/auto-twin/catalog-dependency-probe"'
    )

    handler = SERVER_SOURCE[handler_start:handler_end]

    causal = handler.index(
        "correlate_observed_human_transition("
    )

    learning = handler.index(
        "process_observed_human_navigation_learning("
    )

    branch_resolution = handler.index(
        "resolve_auto_twin_branch_context_for_candidate("
    )

    observe = handler.index(
        "project_ingested_auto_twin_observation("
    )

    candidate_revision = handler.index(
        "project_auto_twin_candidate_revision(",
        observe,
    )

    post_learning_trigger = handler.index(
        "_qcc_project_auto_twin_materialization_after_human_learning(",
        candidate_revision,
    )

    assert (
        causal
        < learning
        < branch_resolution
        < observe
        < candidate_revision
        < post_learning_trigger
    )


def test_observe_called_exactly_once_per_capture_in_source():
    handler_start = SERVER_SOURCE.index(
        '"/qcc/site-architecture/capture"'
    )

    handler_end = SERVER_SOURCE.index(
        '"/qcc/auto-twin/catalog-dependency-probe"'
    )

    handler = SERVER_SOURCE[handler_start:handler_end]

    assert handler.count(
        "project_ingested_auto_twin_observation("
    ) == 1


def test_resolver_keyed_by_this_captures_learning_result():
    start = SERVER_SOURCE.index(
        "resolve_auto_twin_branch_context_for_candidate("
    )

    end = SERVER_SOURCE.index(
        "project_ingested_auto_twin_observation(",
        start,
    )

    block = SERVER_SOURCE[start:end]

    assert 'human_navigation_learning.get(\n                            "candidate_id"' in (
        SERVER_SOURCE[
            SERVER_SOURCE.index(
                "resolved_branch_context = None"
            ):
            start
        ]
    )

    assert "learned_candidate_id" in block


# ---------------------------------------------------------------------------
# 4/5/6/7. Dynamic end-to-end proof: branch resolution + observation +
# candidate revision + post-learning materialization all happen
# exactly once, in order, for one real capture, using the REAL
# resolver/learning/observation implementations wrapped by spies.
# ---------------------------------------------------------------------------


def test_resolved_branch_context_reaches_observe_in_correct_order(
    tmp_path, monkeypatch,
):
    bridge = _build_bridge(tmp_path)
    base = datetime.now(timezone.utc)

    try:
        status, _ = _post_capture(
            bridge,
            capture_id="cap-0",
            state="STATE_A",
            fingerprint=FP_A,
            received_at=_iso(base, 0),
        )

        assert status == 200

        assert (
            _context_store(bridge).get_navigation_environment()
            == ENV
        )

        # A previously learned sibling branch (route=130), recorded
        # independently of this capture: durable governed evidence
        # this capture's own candidate must be classified against.
        _pre_populate_other_branch(
            bridge,
            selected_value="130",
            after_fingerprint=FP_B,
        )

        _arm_pending_human_action(
            bridge,
            selected_value="131",
            event_id="evt-live-131",
            observed_at=datetime.now(timezone.utc),
        )

        calls = []
        branch_contexts_seen = []

        monkeypatch.setattr(
            qcc_bridge_server,
            "process_observed_human_navigation_learning",
            _CallSpy(
                "learning",
                qcc_bridge_server
                .process_observed_human_navigation_learning,
                calls,
            ),
        )

        monkeypatch.setattr(
            qcc_bridge_server,
            "resolve_auto_twin_branch_context_for_candidate",
            _CallSpy(
                "resolve_branch_context",
                qcc_bridge_server
                .resolve_auto_twin_branch_context_for_candidate,
                calls,
            ),
        )

        monkeypatch.setattr(
            qcc_bridge_server,
            "project_ingested_auto_twin_observation",
            _CallSpy(
                "observe",
                qcc_bridge_server
                .project_ingested_auto_twin_observation,
                calls,
                capture_kwargs=(
                    lambda kwargs: branch_contexts_seen.append(
                        kwargs.get("branch_context")
                    )
                ),
            ),
        )

        monkeypatch.setattr(
            qcc_bridge_server,
            "project_auto_twin_candidate_revision",
            _CallSpy(
                "candidate_revision",
                qcc_bridge_server
                .project_auto_twin_candidate_revision,
                calls,
            ),
        )

        monkeypatch.setattr(
            qcc_bridge_server,
            "_qcc_project_auto_twin_materialization_after_human_learning",
            _CallSpy(
                "post_learning_materialization",
                qcc_bridge_server
                ._qcc_project_auto_twin_materialization_after_human_learning,
                calls,
            ),
        )

        status, _ = _post_capture(
            bridge,
            capture_id="cap-1",
            state="STATE_C",
            fingerprint=FP_C,
            received_at=_iso(base, 11),
        )

        assert status == 200

        # Exactly once each, in the mandated order.
        assert calls == [
            "learning",
            "resolve_branch_context",
            "observe",
            "candidate_revision",
            "post_learning_materialization",
        ]

        # 4. The resolved BranchContext actually reached observe().
        assert len(branch_contexts_seen) == 1
        assert branch_contexts_seen[0] is not None
        assert branch_contexts_seen[0].discriminators

        # The materialized observation itself carries the resolved
        # branch identity.
        snapshot = (
            bridge.auto_twin_observation_store.snapshot()
        )

        states = (
            snapshot["twins"]["mercurio_twin"]["states"]
        )

        branch_scoped_states = [
            state
            for state in states.values()
            if state.get("last_fingerprint") == FP_C
        ]

        assert len(branch_scoped_states) == 1
        assert branch_scoped_states[0].get("branch_context_id")

    finally:
        bridge.close()


# ---------------------------------------------------------------------------
# 5. No context reaches observe() when branch is not proven (single,
# DETERMINISTIC outcome: no sibling branch evidence exists yet).
# ---------------------------------------------------------------------------


def test_no_resolved_branch_reaches_observe_without_contextual_resolution(
    tmp_path, monkeypatch,
):
    bridge = _build_bridge(tmp_path)
    base = datetime.now(timezone.utc)

    try:
        status, _ = _post_capture(
            bridge,
            capture_id="cap-0",
            state="STATE_A",
            fingerprint=FP_A,
            received_at=_iso(base, 0),
        )

        assert status == 200

        _arm_pending_human_action(
            bridge,
            selected_value="131",
            event_id="evt-live-131-only",
            observed_at=datetime.now(timezone.utc),
        )

        branch_contexts_seen = []

        monkeypatch.setattr(
            qcc_bridge_server,
            "project_ingested_auto_twin_observation",
            _CallSpy(
                "observe",
                qcc_bridge_server
                .project_ingested_auto_twin_observation,
                [],
                capture_kwargs=(
                    lambda kwargs: branch_contexts_seen.append(
                        kwargs.get("branch_context")
                    )
                ),
            ),
        )

        status, _ = _post_capture(
            bridge,
            capture_id="cap-1",
            state="STATE_C",
            fingerprint=FP_C,
            received_at=_iso(base, 11),
        )

        assert status == 200
        assert branch_contexts_seen == [None]

    finally:
        bridge.close()


# ---------------------------------------------------------------------------
# 8. Site Architecture capture still succeeds if AUTO TWIN BranchContext
# resolution fails.
# ---------------------------------------------------------------------------


def test_capture_succeeds_when_branch_resolution_raises(
    tmp_path, monkeypatch,
):
    bridge = _build_bridge(tmp_path)
    base = datetime.now(timezone.utc)

    try:
        status, _ = _post_capture(
            bridge,
            capture_id="cap-0",
            state="STATE_A",
            fingerprint=FP_A,
            received_at=_iso(base, 0),
        )

        assert status == 200

        _arm_pending_human_action(
            bridge,
            selected_value="131",
            event_id="evt-live-fail",
            observed_at=datetime.now(timezone.utc),
        )

        def _raise(*args, **kwargs):
            raise ValueError("QCC_TEST_FORCED_BRANCH_RESOLUTION_FAILURE")

        monkeypatch.setattr(
            qcc_bridge_server,
            "resolve_auto_twin_branch_context_for_candidate",
            _raise,
        )

        branch_contexts_seen = []

        monkeypatch.setattr(
            qcc_bridge_server,
            "project_ingested_auto_twin_observation",
            _CallSpy(
                "observe",
                qcc_bridge_server
                .project_ingested_auto_twin_observation,
                [],
                capture_kwargs=(
                    lambda kwargs: branch_contexts_seen.append(
                        kwargs.get("branch_context")
                    )
                ),
            ),
        )

        status, payload = _post_capture(
            bridge,
            capture_id="cap-1",
            state="STATE_C",
            fingerprint=FP_C,
            received_at=_iso(base, 11),
        )

        assert status == 200
        assert payload["ok"] is True

        # Observation still runs exactly once, with branch_context=None.
        assert branch_contexts_seen == [None]

    finally:
        bridge.close()


# ---------------------------------------------------------------------------
# 9/10. Legacy behavior preserved: no human transition, and no
# candidate store configured, both keep branch_context=None and a
# successful single observation.
# ---------------------------------------------------------------------------


def test_capture_without_human_transition_preserves_legacy_behavior(
    tmp_path, monkeypatch,
):
    bridge = _build_bridge(tmp_path)

    try:
        branch_contexts_seen = []

        monkeypatch.setattr(
            qcc_bridge_server,
            "project_ingested_auto_twin_observation",
            _CallSpy(
                "observe",
                qcc_bridge_server
                .project_ingested_auto_twin_observation,
                [],
                capture_kwargs=(
                    lambda kwargs: branch_contexts_seen.append(
                        kwargs.get("branch_context")
                    )
                ),
            ),
        )

        status, payload = _post_capture(
            bridge,
            capture_id="cap-0",
            state="STATE_A",
            fingerprint=FP_A,
            received_at="2026-09-05T15:00:00+00:00",
        )

        assert status == 200
        assert payload["ok"] is True
        assert branch_contexts_seen == [None]

    finally:
        bridge.close()


def test_capture_without_candidate_store_preserves_legacy_behavior(
    tmp_path, monkeypatch,
):
    bridge = _build_bridge(tmp_path)

    # Simulate a deployment with no HumanNavigationCandidateStore wired
    # at all, without falling back to the constructor's own default
    # (file-backed, real-data-root) instance.
    bridge._server.qcc_human_navigation_candidate_store = None

    try:
        branch_contexts_seen = []

        monkeypatch.setattr(
            qcc_bridge_server,
            "project_ingested_auto_twin_observation",
            _CallSpy(
                "observe",
                qcc_bridge_server
                .project_ingested_auto_twin_observation,
                [],
                capture_kwargs=(
                    lambda kwargs: branch_contexts_seen.append(
                        kwargs.get("branch_context")
                    )
                ),
            ),
        )

        status, payload = _post_capture(
            bridge,
            capture_id="cap-0",
            state="STATE_A",
            fingerprint=FP_A,
            received_at="2026-09-05T15:00:00+00:00",
        )

        assert status == 200
        assert payload["ok"] is True
        assert branch_contexts_seen == [None]

    finally:
        bridge.close()
