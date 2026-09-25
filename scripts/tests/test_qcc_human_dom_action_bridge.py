import json
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from urllib.error import (
    HTTPError,
)
from urllib.request import (
    Request,
    urlopen,
)

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.context.live_action_evidence import (
    QccLiveActionEvidence,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_REAL_ORIGIN,
)


NOW = datetime.now(
    timezone.utc
)

FP_A = "a" * 64


def _session(
    session_id="human-session-1",
):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        started_at=NOW,
        status=(
            QccPresentationStatus
            .WAITING_USER
        ),
        current_step="TEST",
        progress=50,
        requires_user_action=True,
    )


def _navigation():
    return QccLiveNavigationContext(
        session_id="human-session-1",
        updated_at=NOW,
        current_state="STATE_A",
        current_fingerprint=FP_A,
    )


def _canonical_action():
    return {
        "kind":
            "BUTTON",

        "policy":
            "HUMAN_ONLY",

        "selector":
            "#continuar",

        "frame_path":
            "main",

        "visible":
            True,

        "disabled":
            False,

        "in_viewport":
            True,

        "opacity":
            1.0,

        "pointer_events":
            "auto",
    }


def _evidence(
    *,
    captured_at=None,
):
    return QccLiveActionEvidence(
        session_id="human-session-1",
        site_code="MERCURIO",
        environment="REAL",
        before_state="STATE_A",
        before_fingerprint=FP_A,
        actions=(
            _canonical_action(),
        ),
        captured_at=(
            captured_at
            or datetime.now(
                timezone.utc
            )
        ),
    )


def _post(
    bridge,
    path,
    payload,
):
    request = Request(
        (
            f"http://{bridge.host}:"
            f"{bridge.port}"
            + path
        ),
        data=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    try:
        response = urlopen(
            request,
            timeout=3,
        )

    except HTTPError as exc:
        return (
            exc.code,
            json.loads(
                exc.read().decode(
                    "utf-8"
                )
            ),
        )

    with response:
        return (
            response.status,
            json.loads(
                response.read().decode(
                    "utf-8"
                )
            ),
        )


def _ready_bridge():
    bridge = QccBridgeServer(
        port=0,
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.context_store.set_live_navigation(
        _navigation()
    )

    bridge.context_store.set_navigation_environment(
        "REAL",
        session_id="human-session-1",
    )

    evidence = _evidence()

    bridge.context_store.set_live_action_evidence(
        evidence
    )

    bridge.start()

    return (
        bridge,
        evidence,
    )


def _signal_payload(
    evidence,
    *,
    event_id="event-1",
    selector="#continuar",
):
    # Do not manufacture a timestamp in the future.
    #
    # The signal must occur after the canonical evidence,
    # but QccHumanDomSignal.is_fresh() also correctly
    # rejects future timestamps.
    #
    # Wait for the wall clock to naturally advance beyond
    # captured_at instead of adding an artificial +1 ms.
    observed = datetime.now(
        timezone.utc
    )

    while (
        observed
        <= evidence.captured_at
    ):
        observed = datetime.now(
            timezone.utc
        )

    return {
        "protocol_version":
            QCC_PROTOCOL_VERSION,

        "signal": {
            "event_id":
                event_id,

            "selector":
                selector,

            "frame_path":
                "main",

            "observed_at":
                observed.isoformat(),
        },
    }


def test_bridge_accepts_minimal_human_dom_signal():
    bridge, evidence = (
        _ready_bridge()
    )

    try:
        status, payload = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            _signal_payload(
                evidence
            ),
        )

        assert status == 200

        assert payload == {
            "ok":
                True,
            "accepted":
                True,
            "event_id":
                "event-1",
        }

        pending = (
            bridge.context_store
            .get_observed_human_action(
                now=datetime.now(
                    timezone.utc
                )
            )
        )

        assert pending is not None

        # Authority came from backend evidence.
        assert pending.kind == "BUTTON"
        assert (
            pending.policy
            == "HUMAN_ONLY"
        )
        assert (
            pending.environment
            == "REAL"
        )
        assert (
            pending.before_fingerprint
            == FP_A
        )

    finally:
        bridge.close()


def test_bridge_response_never_echoes_runtime_authority():
    bridge, evidence = (
        _ready_bridge()
    )

    try:
        status, payload = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            _signal_payload(
                evidence
            ),
        )

        assert status == 200

        serialized = json.dumps(
            payload
        )

        for forbidden in (
            "HUMAN_ONLY",
            "BUTTON",
            "#continuar",
            "REAL",
            FP_A,
            "before_state",
            "before_fingerprint",
            "policy",
            "kind",
        ):
            assert (
                forbidden
                not in serialized
            )

    finally:
        bridge.close()


def test_bridge_rejects_browser_policy_authority():
    bridge, evidence = (
        _ready_bridge()
    )

    try:
        payload = _signal_payload(
            evidence
        )

        payload[
            "signal"
        ][
            "policy"
        ] = "AUTOMATION_ALLOWED"

        status, response = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            payload,
        )

        assert status == 400

        assert (
            response["error"]
            == "QCC_HUMAN_DOM_SIGNAL_FIELD_INVALID"
        )

        assert (
            bridge.context_store
            .get_observed_human_action()
            is None
        )

    finally:
        bridge.close()


def test_bridge_rejects_browser_environment_authority():
    bridge, evidence = (
        _ready_bridge()
    )

    try:
        payload = _signal_payload(
            evidence
        )

        payload[
            "signal"
        ][
            "environment"
        ] = "LAB"

        status, response = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            payload,
        )

        assert status == 400

        assert (
            response["error"]
            == "QCC_HUMAN_DOM_SIGNAL_FIELD_INVALID"
        )

    finally:
        bridge.close()


def test_bridge_session_is_taken_from_route():
    bridge, evidence = (
        _ready_bridge()
    )

    try:
        status, response = _post(
            bridge,
            (
                "/qcc/session/"
                "other-session/"
                "human-dom-action"
            ),
            _signal_payload(
                evidence
            ),
        )

        assert status == 409

        assert (
            response["error"]
            == "QCC_HUMAN_DOM_SIGNAL_SESSION_NOT_ACTIVE"
        )

    finally:
        bridge.close()


def test_bridge_rejects_unknown_selector():
    bridge, evidence = (
        _ready_bridge()
    )

    try:
        status, response = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            _signal_payload(
                evidence,
                selector="#unknown",
            ),
        )

        assert status == 400

        assert (
            response["error"]
            == "QCC_HUMAN_DOM_SIGNAL_ACTION_NOT_FOUND"
        )

    finally:
        bridge.close()


def test_bridge_rejects_protocol_mismatch():
    bridge, evidence = (
        _ready_bridge()
    )

    try:
        payload = _signal_payload(
            evidence
        )

        payload[
            "protocol_version"
        ] = 999

        status, response = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            payload,
        )

        assert status == 400

        assert (
            response["error"]
            == "QCC_PROTOCOL_VERSION_INVALID"
        )

    finally:
        bridge.close()


class _CaptureIngestor:
    def ingest(
        self,
        capture,
        *,
        context=None,
    ):
        return {
            "capture_id":
                "capture-A",

            "context_mode":
                "SESSION_BOUND",

            "session_id":
                "human-session-1",

            "page": {
                "url": (
                    MERCURIO_REAL_ORIGIN
                    + "/mercurio/"
                    + "entradaMercurio.html"
                ),
            },

            "site_code":
                "MERCURIO",

            "state_observation": {
                "state":
                    "STATE_A",

                "fingerprint":
                    FP_A,
            },

            "live_actions": (
                _canonical_action(),
            ),

            "counts": {
                "elements":
                    1,
            },
        }


def test_capture_automatically_binds_canonical_action_evidence():
    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _CaptureIngestor()
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        status, payload = _post(
            bridge,
            "/qcc/site-architecture/capture",
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "capture": {
                    "test":
                        True,
                },
            },
        )

        assert status == 200

        assert (
            payload[
                "live_projection"
            ][
                "projected"
            ]
            is True
        )

        evidence = (
            bridge.context_store
            .get_live_action_evidence(
                now=datetime.now(
                    timezone.utc
                )
            )
        )

        assert evidence is not None

        assert (
            evidence.environment
            == "REAL"
        )

        assert (
            evidence.before_fingerprint
            == FP_A
        )

        assert (
            len(
                evidence.actions
            )
            == 1
        )

        assert (
            evidence.actions[0]
            .policy
            == "HUMAN_ONLY"
        )

    finally:
        bridge.close()


def test_capture_returns_authority_free_human_listener_plan():
    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _CaptureIngestor()
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        status, payload = _post(
            bridge,
            "/qcc/site-architecture/capture",
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "capture": {
                    "test":
                        True,
                },
            },
        )

        assert status == 200

        assert (
            payload[
                "human_listener_plan"
            ]
            == {
                "targets": [
                    {
                        "selector":
                            "#continuar",

                        "frame_path":
                            "main",
                    }
                ]
            }
        )

        serialized = json.dumps(
            payload[
                "human_listener_plan"
            ]
        )

        for forbidden in (
            "policy",
            "kind",
            "environment",
            "site_code",
            "fingerprint",
            "HUMAN_ONLY",
            "BUTTON",
            FP_A,
        ):
            assert (
                forbidden
                not in serialized
            )

    finally:
        bridge.close()


FP_B1 = "b" * 64
FP_B2 = "c" * 64


class _CausalEpisodeCaptureIngestor:
    def __init__(self):
        self.index = 0

        self.states = (
            (
                "STATE_A",
                FP_A,
            ),
            (
                "STATE_B1",
                FP_B1,
            ),
            (
                "STATE_B2",
                FP_B2,
            ),
        )

    def ingest(
        self,
        capture,
        *,
        context=None,
    ):
        if self.index >= len(
            self.states
        ):
            raise AssertionError(
                "unexpected extra capture"
            )

        state, fingerprint = (
            self.states[
                self.index
            ]
        )

        capture_id = (
            f"causal-capture-"
            f"{self.index}"
        )

        self.index += 1

        return {
            "capture_id":
                capture_id,

            # El Bridge usa received_at como frontera temporal
            # para correlacionar CURRENT B con la acción humana
            # pendiente.
            "received_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "context_mode":
                "SESSION_BOUND",

            "session_id":
                "human-session-1",

            "page": {
                "url": (
                    MERCURIO_REAL_ORIGIN
                    + "/mercurio/"
                    + "entradaMercurio.html"
                ),
            },

            "site_code":
                "MERCURIO",

            "state_observation": {
                "state":
                    state,

                "fingerprint":
                    fingerprint,
            },

            "live_actions": (
                _canonical_action(),
            ),

            "counts": {
                "elements":
                    1,
            },
        }


def _capture_once(
    bridge,
):
    return _post(
        bridge,
        "/qcc/site-architecture/capture",
        {
            "protocol_version":
                QCC_PROTOCOL_VERSION,

            "capture": {
                "test":
                    True,
            },
        },
    )


def test_bridge_causal_episode_persists_only_latest_current(
    tmp_path,
):
    from backend.qcc.navigation_knowledge.store import (
        NavigationKnowledgeStore,
    )
    from backend.qcc.navigation_learning import (
        HumanNavigationCandidateStore,
    )

    candidates = (
        HumanNavigationCandidateStore(
            root=(
                tmp_path
                / "candidates"
            )
        )
    )

    knowledge = (
        NavigationKnowledgeStore(
            root=(
                tmp_path
                / "knowledge"
            )
        )
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _CausalEpisodeCaptureIngestor()
        ),
        human_navigation_candidate_store=(
            candidates
        ),
        navigation_knowledge_store=(
            knowledge
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        # --------------------------------------------------
        # CURRENT A
        # --------------------------------------------------

        status, _ = _capture_once(
            bridge
        )

        assert status == 200

        evidence_a = (
            bridge.context_store
            .get_live_action_evidence(
                now=datetime.now(
                    timezone.utc
                )
            )
        )

        assert evidence_a is not None
        assert (
            evidence_a.before_fingerprint
            == FP_A
        )

        # --------------------------------------------------
        # ACTION X
        # --------------------------------------------------

        status, response = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            _signal_payload(
                evidence_a,
                event_id="event-X",
            ),
        )

        assert status == 200
        assert (
            response["event_id"]
            == "event-X"
        )

        # No candidate yet:
        # the causal episode is still open.
        snapshot = candidates.snapshot(
            "MERCURIO",
            environment="REAL",
        )

        assert (
            snapshot["candidate_count"]
            == 0
        )

        # --------------------------------------------------
        # CURRENT B1
        #
        # First provisional destination.
        # --------------------------------------------------

        status, response = _capture_once(
            bridge
        )

        assert status == 200

        provisional_b1 = (
            bridge.context_store
            .get_observed_human_transition()
        )

        assert provisional_b1 is not None
        assert (
            provisional_b1.event_id
            == "event-X"
        )
        assert (
            provisional_b1.after_fingerprint
            == FP_B1
        )

        snapshot = candidates.snapshot(
            "MERCURIO",
            environment="REAL",
        )

        assert (
            snapshot["candidate_count"]
            == 0
        )

        # --------------------------------------------------
        # CURRENT B2
        #
        # Same physical ACTION X.
        # Must replace B1.
        # --------------------------------------------------

        status, response = _capture_once(
            bridge
        )

        assert status == 200

        provisional_b2 = (
            bridge.context_store
            .get_observed_human_transition()
        )

        assert provisional_b2 is not None
        assert (
            provisional_b2.event_id
            == "event-X"
        )
        assert (
            provisional_b2.after_state
            == "STATE_B2"
        )
        assert (
            provisional_b2.after_fingerprint
            == FP_B2
        )

        snapshot = candidates.snapshot(
            "MERCURIO",
            environment="REAL",
        )

        assert (
            snapshot["candidate_count"]
            == 0
        )

        # B2 capture also installs canonical evidence for
        # the next physical action.
        evidence_b2 = (
            bridge.context_store
            .get_live_action_evidence(
                now=datetime.now(
                    timezone.utc
                )
            )
        )

        assert evidence_b2 is not None
        assert (
            evidence_b2.before_fingerprint
            == FP_B2
        )

        # --------------------------------------------------
        # ACTION Y
        #
        # This is the causal boundary:
        #
        #   finalize X -> B2
        #   persist X -> B2
        #   open Y
        # --------------------------------------------------

        status, response = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            _signal_payload(
                evidence_b2,
                event_id="event-Y",
            ),
        )

        assert status == 200
        assert (
            response["event_id"]
            == "event-Y"
        )

        # --------------------------------------------------
        # Persistent proof
        # --------------------------------------------------

        snapshot = candidates.snapshot(
            "MERCURIO",
            environment="REAL",
        )

        assert (
            snapshot["candidate_count"]
            == 1
        )

        candidate = (
            snapshot[
                "candidates"
            ][0]
        )

        assert (
            candidate[
                "event_ids"
            ]
            == [
                "event-X"
            ]
        )

        assert (
            candidate[
                "before_fingerprint"
            ]
            == FP_A
        )

        assert (
            candidate[
                "after_state"
            ]
            == "STATE_B2"
        )

        assert (
            candidate[
                "after_fingerprint"
            ]
            == FP_B2
        )

        # Explicit negative proof:
        # B1 was only a provisional snapshot.
        assert (
            candidate[
                "after_fingerprint"
            ]
            != FP_B1
        )

        # ACTION Y is now the new open episode.
        pending = (
            bridge.context_store
            .get_observed_human_action(
                now=datetime.now(
                    timezone.utc
                )
            )
        )

        assert pending is not None
        assert (
            pending.event_id
            == "event-Y"
        )

    finally:
        bridge.close()


def test_invalid_next_action_cannot_finalize_previous_provisional(
    tmp_path,
):
    from backend.qcc.navigation_knowledge.store import (
        NavigationKnowledgeStore,
    )
    from backend.qcc.navigation_learning import (
        HumanNavigationCandidateStore,
    )

    candidates = (
        HumanNavigationCandidateStore(
            root=(
                tmp_path
                / "candidates"
            )
        )
    )

    knowledge = (
        NavigationKnowledgeStore(
            root=(
                tmp_path
                / "knowledge"
            )
        )
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _CausalEpisodeCaptureIngestor()
        ),
        human_navigation_candidate_store=(
            candidates
        ),
        navigation_knowledge_store=(
            knowledge
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        # CURRENT A
        status, _ = _capture_once(
            bridge
        )
        assert status == 200

        evidence_a = (
            bridge.context_store
            .get_live_action_evidence(
                now=datetime.now(
                    timezone.utc
                )
            )
        )

        assert evidence_a is not None

        # ACTION X válida
        status, _ = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            _signal_payload(
                evidence_a,
                event_id="event-X",
            ),
        )
        assert status == 200

        # CURRENT B1 provisional
        status, _ = _capture_once(
            bridge
        )
        assert status == 200

        provisional = (
            bridge.context_store
            .get_observed_human_transition()
        )

        assert provisional is not None
        assert provisional.after_fingerprint == FP_B1

        # Y no pertenece a la evidencia canónica de CURRENT B1.
        # Debe rechazarse ANTES de cerrar X.
        evidence_b1 = (
            bridge.context_store
            .get_live_action_evidence(
                now=datetime.now(
                    timezone.utc
                )
            )
        )

        assert evidence_b1 is not None

        status, response = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            _signal_payload(
                evidence_b1,
                event_id="event-Y",
                selector="#unknown",
            ),
        )

        assert status == 400
        assert (
            response["error"]
            == "QCC_HUMAN_DOM_SIGNAL_ACTION_NOT_FOUND"
        )

        # PRUEBA CRÍTICA:
        # Y inválida jamás convierte B1 en candidate persistente.
        snapshot = candidates.snapshot(
            "MERCURIO",
            environment="REAL",
        )

        assert snapshot["candidate_count"] == 0

        # X sigue pendiente; no fue consumida por la señal inválida.
        pending = (
            bridge.context_store
            .get_observed_human_action()
        )

        assert pending is not None
        assert pending.event_id == "event-X"

    finally:
        bridge.close()

def test_snapshot_addressed_next_action_boundary_rejects_transitive_shortcut(
    tmp_path,
):
    """
    Exact asynchronous browser race:

        capture A
        physical X at A

        capture B
        physical Y at B

        capture C

        HTTP X arrives while CURRENT=C
        HTTP Y arrives while CURRENT=C

    Correct causal result:

        A --X--> B

    Forbidden shortcut:

        A --X--> C
    """

    from backend.qcc.navigation_knowledge.store import (
        NavigationKnowledgeStore,
    )
    from backend.qcc.navigation_learning import (
        HumanNavigationCandidateStore,
    )

    candidates = (
        HumanNavigationCandidateStore(
            root=(
                tmp_path
                / "candidates"
            )
        )
    )

    knowledge = (
        NavigationKnowledgeStore(
            root=(
                tmp_path
                / "knowledge"
            )
        )
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _CausalEpisodeCaptureIngestor()
        ),
        human_navigation_candidate_store=(
            candidates
        ),
        navigation_knowledge_store=(
            knowledge
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        # --------------------------------------------------
        # CAPTURE A
        # --------------------------------------------------

        status, _ = _capture_once(
            bridge
        )

        assert status == 200

        evidence_a = (
            bridge.context_store
            .get_live_action_evidence()
        )

        assert evidence_a is not None
        assert (
            evidence_a.before_fingerprint
            == FP_A
        )

        # Physical X happened here, but transport is delayed.
        click_x_at = datetime.now(
            timezone.utc
        )

        while (
            click_x_at
            <= evidence_a.captured_at
        ):
            click_x_at = datetime.now(
                timezone.utc
            )

        # --------------------------------------------------
        # CAPTURE B
        # --------------------------------------------------

        status, _ = _capture_once(
            bridge
        )

        assert status == 200

        evidence_b = (
            bridge.context_store
            .get_live_action_evidence()
        )

        assert evidence_b is not None
        assert (
            evidence_b.before_fingerprint
            == FP_B1
        )

        # Physical Y happens while user is really in B.
        click_y_at = datetime.now(
            timezone.utc
        )

        while (
            click_y_at
            <= evidence_b.captured_at
        ):
            click_y_at = datetime.now(
                timezone.utc
            )

        # --------------------------------------------------
        # CAPTURE C WINS BOTH TRANSPORT RACES
        # --------------------------------------------------

        status, _ = _capture_once(
            bridge
        )

        assert status == 200

        current = (
            bridge.context_store
            .get_live_navigation()
        )

        assert current is not None
        assert (
            current.current_state
            == "STATE_B2"
        )
        assert (
            current.current_fingerprint
            == FP_B2
        )

        # Historical A/B evidence must remain addressable.
        assert (
            bridge.context_store
            .get_live_action_evidence_by_id(
                evidence_a.evidence_id
            )
            is not None
        )

        assert (
            bridge.context_store
            .get_live_action_evidence_by_id(
                evidence_b.evidence_id
            )
            is not None
        )

        # --------------------------------------------------
        # DELAYED HTTP X
        #
        # CURRENT is already C.
        # X must anchor to Evidence A and remain open.
        # It MUST NOT synthesize A->C.
        # --------------------------------------------------

        status, response = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "signal": {
                    "event_id":
                        "event-X-late",

                    "selector":
                        "#continuar",

                    "frame_path":
                        "main",

                    "observed_at":
                        click_x_at.isoformat(),

                    "evidence_id":
                        evidence_a.evidence_id,
                },
            },
        )

        assert status == 200
        assert (
            response["event_id"]
            == "event-X-late"
        )

        pending_x = (
            bridge.context_store
            .get_observed_human_action()
        )

        assert pending_x is not None
        assert (
            pending_x.before_fingerprint
            == FP_A
        )

        # Critical negative proof:
        # delayed X alone cannot join to mutable CURRENT C.
        assert (
            bridge.context_store
            .get_observed_human_transition()
            is None
        )

        snapshot = candidates.snapshot(
            "MERCURIO",
            environment="REAL",
        )

        assert (
            snapshot["candidate_count"]
            == 0
        )

        # --------------------------------------------------
        # DELAYED HTTP Y
        #
        # Y is snapshot-addressed to B even though CURRENT=C.
        # Therefore Y.before is the authoritative causal
        # boundary for X.
        # --------------------------------------------------

        status, response = _post(
            bridge,
            (
                "/qcc/session/"
                "human-session-1/"
                "human-dom-action"
            ),
            {
                "protocol_version":
                    QCC_PROTOCOL_VERSION,

                "signal": {
                    "event_id":
                        "event-Y-late",

                    "selector":
                        "#continuar",

                    "frame_path":
                        "main",

                    "observed_at":
                        click_y_at.isoformat(),

                    "evidence_id":
                        evidence_b.evidence_id,
                },
            },
        )

        assert status == 200
        assert (
            response["event_id"]
            == "event-Y-late"
        )

        # --------------------------------------------------
        # PERSISTENT PROOF:
        #
        #     A --X--> B
        #
        # and NEVER:
        #
        #     A --X--> C
        # --------------------------------------------------

        snapshot = candidates.snapshot(
            "MERCURIO",
            environment="REAL",
        )

        assert (
            snapshot["candidate_count"]
            == 1
        )

        candidate = (
            snapshot[
                "candidates"
            ][0]
        )

        assert (
            candidate["event_ids"]
            == [
                "event-X-late"
            ]
        )

        assert (
            candidate[
                "before_state"
            ]
            == "STATE_A"
        )

        assert (
            candidate[
                "before_fingerprint"
            ]
            == FP_A
        )

        assert (
            candidate[
                "after_state"
            ]
            == "STATE_B1"
        )

        assert (
            candidate[
                "after_fingerprint"
            ]
            == FP_B1
        )

        # Explicit transitive-shortcut rejection.
        assert (
            candidate[
                "after_fingerprint"
            ]
            != FP_B2
        )

        # Y becomes the new open causal episode,
        # also anchored to its own historical Evidence B.
        pending_y = (
            bridge.context_store
            .get_observed_human_action()
        )

        assert pending_y is not None
        assert (
            pending_y.event_id
            == "event-Y-late"
        )

        assert (
            pending_y.before_state
            == "STATE_B1"
        )

        assert (
            pending_y.before_fingerprint
            == FP_B1
        )

        # CURRENT may remain C; that does not redefine Y.before.
        current = (
            bridge.context_store
            .get_live_navigation()
        )

        assert (
            current.current_fingerprint
            == FP_B2
        )

    finally:
        bridge.close()


# ---------------------------------------------------------
# QCC_AUTO_TWIN_ASYNC_POST_LEARNING_MATERIALIZATION_V1
#
# Real POST /qcc/session/<id>/human-dom-action with a blocked
# injected materialization processor.
# ---------------------------------------------------------


FP_B = "b" * 64
TRIGGER_CAPTURE_ID = "cap-Y-exact"


def _navigation_action(selector):
    return {
        **_canonical_action(),
        "kind":
            "LINK",

        "policy":
            "NAVIGATION_CANDIDATE",

        "selector":
            selector,
    }


def test_human_dom_action_returns_before_materialization_processor(
    tmp_path,
):
    import threading

    from backend.qcc.auto_twin.managed_site_registry import (
        AutoTwinManagedSite,
    )
    from backend.qcc.auto_twin.managed_site_store import (
        AutoTwinManagedSiteStore,
    )
    from backend.qcc.auto_twin.observation_store import (
        AutoTwinObservationStore,
    )
    from backend.qcc.navigation_knowledge.store import (
        NavigationKnowledgeStore,
    )
    from backend.qcc.navigation_learning.human_candidate_store import (
        HumanNavigationCandidateStore,
    )

    entered = threading.Event()
    release = threading.Event()
    calls = []
    finished = []

    def blocked_processor(*, twin_key, trigger_capture_id):
        calls.append((twin_key, trigger_capture_id))
        entered.set()

        assert release.wait(timeout=10.0)

        finished.append(True)

        return {"status": "NO_CHANGE"}

    managed_store = AutoTwinManagedSiteStore(
        path=tmp_path / "managed.json"
    )

    managed_store.register(
        AutoTwinManagedSite(
            twin_key="mercurio",
            site_code="MERCURIO",
            origins=(MERCURIO_REAL_ORIGIN,),
        )
    )

    candidate_root = tmp_path / "candidates"

    bridge = QccBridgeServer(
        port=0,
        site_architecture_output_root=tmp_path / "captures",
        navigation_knowledge_store=NavigationKnowledgeStore(
            root=tmp_path / "knowledge"
        ),
        human_navigation_candidate_store=(
            HumanNavigationCandidateStore(
                root=candidate_root
            )
        ),
        auto_twin_store=managed_store,
        auto_twin_observation_store=AutoTwinObservationStore(
            path=tmp_path / "observation_state.json"
        ),
        auto_twin_materialization_processor=blocked_processor,
    )

    coordinator = (
        bridge._server
        .qcc_auto_twin_materialization_coordinator
    )

    context_store = bridge.context_store

    context_store.set_active_session(
        _session()
    )

    context_store.set_navigation_environment(
        "REAL",
        session_id="human-session-1",
    )

    context_store.set_live_navigation(
        _navigation()
    )

    evidence_a = QccLiveActionEvidence(
        session_id="human-session-1",
        site_code="MERCURIO",
        environment="REAL",
        before_state="STATE_A",
        before_fingerprint=FP_A,
        actions=(
            _navigation_action("#continuar"),
        ),
        captured_at=datetime.now(
            timezone.utc
        ),
    )

    context_store.set_live_action_evidence(
        evidence_a
    )

    bridge.start()

    try:
        route = (
            "/qcc/session/"
            "human-session-1/"
            "human-dom-action"
        )

        # Action X: pending, nothing to finalize yet.
        status, _ = _post(
            bridge,
            route,
            _signal_payload(
                evidence_a,
                event_id="event-x",
                selector="#continuar",
            ),
        )

        assert status == 200
        assert calls == []

        # The Twin navigated to B; Y's evidence is the exact
        # backend-owned capture that closes X -> Y.before.
        context_store.set_live_navigation(
            QccLiveNavigationContext(
                session_id="human-session-1",
                updated_at=datetime.now(
                    timezone.utc
                ),
                current_state="STATE_B",
                current_fingerprint=FP_B,
            )
        )

        evidence_b = QccLiveActionEvidence(
            session_id="human-session-1",
            site_code="MERCURIO",
            environment="REAL",
            before_state="STATE_B",
            before_fingerprint=FP_B,
            actions=(
                _navigation_action("#enviar"),
            ),
            captured_at=datetime.now(
                timezone.utc
            ),
            capture_id=TRIGGER_CAPTURE_ID,
        )

        context_store.set_live_action_evidence(
            evidence_b
        )

        # _post uses a 3s client timeout: a synchronous
        # materialization would time out here, because the
        # processor is blocked until released below.
        status, payload = _post(
            bridge,
            route,
            _signal_payload(
                evidence_b,
                event_id="event-y",
                selector="#enviar",
            ),
        )

        # 1. HTTP 200 BEFORE the processor is released.
        assert status == 200
        assert payload["accepted"] is True
        assert not release.is_set()
        assert finished == []

        # 2. Causal transition finalized: X was consumed and Y is
        #    now the pending action.
        pending = context_store.get_observed_human_action(
            now=datetime.now(
                timezone.utc
            )
        )

        assert pending is not None
        assert pending.event_id == "event-y"

        # 3. Learning persisted (CandidateStore, before release).
        candidate_files = [
            path
            for path in candidate_root.rglob("*")
            if path.is_file()
        ]

        assert candidate_files

        persisted = "".join(
            path.read_text(encoding="utf-8")
            for path in candidate_files
        )

        assert "#continuar" in persisted
        assert "onclick" not in persisted

        # 4. Job enqueued and picked up by the worker, still blocked.
        assert entered.wait(timeout=5.0)

        running = coordinator.snapshot()

        assert running["running_count"] == 1
        assert running["worker_alive"] is True
        assert finished == []

        # 5. Release, then drain.
        release.set()

        assert coordinator.wait_until_idle(timeout=5.0)

        assert finished == [True]

        # 6. Exact trusted authority reached the processor:
        #    managed-registry twin_key + Y's exact capture id.
        assert calls == [
            (
                "mercurio",
                TRIGGER_CAPTURE_ID,
            )
        ]

        result = coordinator.snapshot()["last_result"]

        assert result["status"] == "NO_CHANGE"
        assert result["twin_key"] == "mercurio"
        assert (
            result["trigger_capture_id"]
            == TRIGGER_CAPTURE_ID
        )

    finally:
        release.set()
        bridge.close()
