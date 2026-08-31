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
