from datetime import (
    datetime,
    timezone,
)
import json
from urllib.error import (
    HTTPError,
)
from urllib.request import (
    Request,
    urlopen,
)

import pytest

import backend.qcc.bridge.server as qcc_bridge_server

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.context.live_state_projection import (
    LIVE_STATE_SITE_UNRECOGNIZED,
)
from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)
from backend.qcc.navigation_knowledge import (
    NavigationKnowledgeStore,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_LAB_ORIGIN,
    MERCURIO_REAL_ORIGIN,
)


FP_A = "a" * 64


class _MutableFakeIngestor:
    def __init__(
        self,
        url,
    ):
        self.url = url

    def ingest(
        self,
        capture,
        *,
        context=None,
    ):
        return {
            "capture_id":
                "capture-1",

            "context_mode":
                "SESSION_BOUND",

            "session_id":
                "session-1",

            "page": {
                "url":
                    self.url,
            },

            "site_code":
                "MERCURIO",

            "state_observation": {
                "state":
                    "MERCURIO_ENTRY_IDLE",

                "fingerprint":
                    FP_A,
            },

            "live_actions":
                (),

            "counts": {
                "elements":
                    0,
            },
        }


def _session():
    return QccPresentationSession(
        session_id="session-1",
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime(
            2026,
            8,
            31,
            9,
            0,
            tzinfo=timezone.utc,
        ),
        status=(
            QccPresentationStatus
            .AUTOMATING
        ),
        current_step="TEST",
        progress=0,
        requires_user_action=False,
        last_event=None,
    )


def _post_json(
    bridge,
    path,
    payload,
):
    body = json.dumps(
        payload
    ).encode(
        "utf-8"
    )

    request = Request(
        (
            f"http://{bridge.host}:"
            f"{bridge.port}"
            + path
        ),
        data=body,
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


def _post_capture(
    bridge,
):
    return _post_json(
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


def _post_intent(
    bridge,
):
    intent = QccNavigationIntent(
        session_id="session-1",
        site_code="MERCURIO",
        target_state=(
            "MERCURIO_MODEL_SELECTION"
        ),
    )

    return _post_json(
        bridge,
        (
            "/qcc/session/"
            "session-1/"
            "navigation-intent"
        ),
        {
            "protocol_version":
                QCC_PROTOCOL_VERSION,

            "intent":
                intent.to_payload(),
        },
    )


def _fake_planner(
    calls,
):
    def fake(
        context_store,
        knowledge_store,
        **kwargs,
    ):
        calls.append(
            dict(
                kwargs
            )
        )

        return {
            "refreshed":
                False,

            "reason":
                "TEST",

            "planning":
                None,
        }

    return fake


@pytest.mark.parametrize(
    (
        "origin",
        "expected_environment",
    ),
    (
        (
            MERCURIO_LAB_ORIGIN,
            "LAB",
        ),
        (
            MERCURIO_REAL_ORIGIN,
            "REAL",
        ),
    ),
)
def test_capture_resolves_live_origin_into_runtime_environment(
    tmp_path,
    monkeypatch,
    origin,
    expected_environment,
):
    calls = []

    monkeypatch.setattr(
        qcc_bridge_server,
        "refresh_live_navigation_plan",
        _fake_planner(
            calls
        ),
    )

    ingestor = _MutableFakeIngestor(
        origin
        + "/mercurio/"
        + "entradaMercurio.html"
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            ingestor
        ),
        navigation_knowledge_store=(
            NavigationKnowledgeStore(
                root=(
                    tmp_path
                    / "knowledge"
                )
            )
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        status, payload = (
            _post_capture(
                bridge
            )
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

        assert (
            bridge.context_store
            .get_navigation_environment()
            == expected_environment
        )

        assert len(calls) == 1

        assert (
            calls[0][
                "environment"
            ]
            == expected_environment
        )

        assert (
            calls[0][
                "include_runtime_plan"
            ]
            is True
        )

        # Runtime-only:
        # never leaks through the public payload.
        assert (
            "environment"
            not in payload
        )

        assert (
            "navigation_environment"
            not in (
                bridge.context_store
                .snapshot()
            )
        )

    finally:
        bridge.close()


def test_navigation_intent_reuses_session_runtime_environment(
    tmp_path,
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        qcc_bridge_server,
        "refresh_live_navigation_plan",
        _fake_planner(
            calls
        ),
    )

    ingestor = _MutableFakeIngestor(
        MERCURIO_REAL_ORIGIN
        + "/mercurio/"
        + "entradaMercurio.html"
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            ingestor
        ),
        navigation_knowledge_store=(
            NavigationKnowledgeStore(
                root=(
                    tmp_path
                    / "knowledge"
                )
            )
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        capture_status, _ = (
            _post_capture(
                bridge
            )
        )

        assert (
            capture_status
            == 200
        )

        assert (
            bridge.context_store
            .get_navigation_environment()
            == "REAL"
        )

        calls.clear()

        intent_status, _ = (
            _post_intent(
                bridge
            )
        )

        assert (
            intent_status
            == 200
        )

        assert len(calls) == 1

        assert (
            calls[0][
                "environment"
            ]
            == "REAL"
        )

        assert (
            "include_runtime_plan"
            not in calls[0]
        )

    finally:
        bridge.close()


def test_unresolved_managed_origin_never_projects_or_plans(
    tmp_path,
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        qcc_bridge_server,
        "refresh_live_navigation_plan",
        _fake_planner(
            calls
        ),
    )

    ingestor = _MutableFakeIngestor(
        "https://example.invalid"
        "/mercurio/"
        "entradaMercurio.html"
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            ingestor
        ),
        navigation_knowledge_store=(
            NavigationKnowledgeStore(
                root=(
                    tmp_path
                    / "knowledge"
                )
            )
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        status, payload = (
            _post_capture(
                bridge
            )
        )

        assert status == 200

        assert (
            payload[
                "live_projection"
            ][
                "projected"
            ]
            is False
        )

        assert (
            payload[
                "live_projection"
            ][
                "reason"
            ]
            == LIVE_STATE_SITE_UNRECOGNIZED
        )

        assert (
            bridge.context_store
            .get_navigation_environment()
            is None
        )

        assert (
            bridge.context_store
            .get_live_navigation()
            is None
        )

        assert calls == []

    finally:
        bridge.close()


def test_unresolved_origin_clears_current_but_preserves_bound_scope(
    tmp_path,
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        qcc_bridge_server,
        "refresh_live_navigation_plan",
        _fake_planner(
            calls
        ),
    )

    ingestor = _MutableFakeIngestor(
        MERCURIO_LAB_ORIGIN
        + "/mercurio/"
        + "entradaMercurio.html"
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            ingestor
        ),
        navigation_knowledge_store=(
            NavigationKnowledgeStore(
                root=(
                    tmp_path
                    / "knowledge"
                )
            )
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        status, _ = (
            _post_capture(
                bridge
            )
        )

        assert status == 200

        assert (
            bridge.context_store
            .get_navigation_environment()
            == "LAB"
        )

        assert (
            bridge.context_store
            .get_live_navigation()
            is not None
        )

        calls.clear()

        ingestor.url = (
            "https://example.invalid"
            "/mercurio/"
            "entradaMercurio.html"
        )

        status, payload = (
            _post_capture(
                bridge
            )
        )

        assert status == 200

        assert (
            payload[
                "live_projection"
            ][
                "projected"
            ]
            is False
        )

        # Established session scope remains LAB:
        # no silent reclassification.
        assert (
            bridge.context_store
            .get_navigation_environment()
            == "LAB"
        )

        # But CURRENT is invalidated.
        assert (
            bridge.context_store
            .get_live_navigation()
            is None
        )

        assert calls == []

        # A later intent cannot re-plan against
        # stale CURRENT.
        status, _ = (
            _post_intent(
                bridge
            )
        )

        assert status == 200
        assert calls == []

    finally:
        bridge.close()


def test_same_session_cannot_cross_lab_to_real(
    tmp_path,
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        qcc_bridge_server,
        "refresh_live_navigation_plan",
        _fake_planner(
            calls
        ),
    )

    ingestor = _MutableFakeIngestor(
        MERCURIO_LAB_ORIGIN
        + "/mercurio/"
        + "entradaMercurio.html"
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            ingestor
        ),
        navigation_knowledge_store=(
            NavigationKnowledgeStore(
                root=(
                    tmp_path
                    / "knowledge"
                )
            )
        ),
    )

    bridge.context_store.set_active_session(
        _session()
    )

    bridge.start()

    try:
        status, _ = (
            _post_capture(
                bridge
            )
        )

        assert status == 200

        assert (
            bridge.context_store
            .get_navigation_environment()
            == "LAB"
        )

        old_current = (
            bridge.context_store
            .get_live_navigation()
        )

        ingestor.url = (
            MERCURIO_REAL_ORIGIN
            + "/mercurio/"
            + "entradaMercurio.html"
        )

        status, payload = (
            _post_capture(
                bridge
            )
        )

        assert status == 400

        assert (
            payload[
                "error"
            ]
            == (
                "QCC_NAVIGATION_ENVIRONMENT_CONFLICT"
            )
        )

        assert (
            bridge.context_store
            .get_navigation_environment()
            == "LAB"
        )

        # Conflict occurred before a new CURRENT
        # could overwrite the previous observation.
        assert (
            bridge.context_store
            .get_live_navigation()
            == old_current
        )

    finally:
        bridge.close()
