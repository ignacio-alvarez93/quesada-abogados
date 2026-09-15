import json
from urllib.request import (
    Request,
    urlopen,
)

import backend.qcc.bridge.server as bridge_module

from backend.automation.site_architecture.managed_governance_registry import (
    ManagedSiteGovernanceRegistry,
)
from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
)


class _FakeIngestor:
    def __init__(
        self,
        *,
        session_bound=True,
    ):
        self.session_bound = (
            session_bound
        )

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
                (
                    "ASSISTED_PRESENTATION"
                    if self.session_bound
                    else "MANUAL"
                ),

            "session_id":
                (
                    "session-1"
                    if self.session_bound
                    else None
                ),

            "site_code":
                (
                    "MERCURIO"
                    if self.session_bound
                    else None
                ),

            "page": {
                "url":
                    (
                        "http://127.0.0.1:8767"
                        "/mercurio/"
                        "entradaMercurio.html"
                    ),

                "title":
                    "Mercurio Twin",
            },

            "state_observation": {
                "state":
                    "STATE_A",

                "fingerprint":
                    "a" * 64,
            },

            "live_actions": (
                {
                    "kind":
                        "BUTTON",

                    "policy":
                        "REQUIRES_POLICY",

                    "selector":
                        "#continue",

                    "frame_path":
                        "main",

                    "interaction": {
                        "visible":
                            True,

                        "disabled":
                            False,

                        "interactable":
                            True,
                    },
                },
            ),

            "counts": {
                "elements":
                    1,
            },
        }


def _post_capture(
    bridge,
):
    body = json.dumps({
        "protocol_version":
            QCC_PROTOCOL_VERSION,

        "capture": {
            "test":
                True,
        },
    }).encode(
        "utf-8"
    )

    request = Request(
        (
            f"http://{bridge.host}:"
            f"{bridge.port}"
            "/qcc/site-architecture/capture"
        ),
        data=body,
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    with urlopen(
        request,
        timeout=3,
    ) as response:
        return json.loads(
            response.read().decode(
                "utf-8"
            )
        )


def test_bridge_owns_managed_governance_registry():
    bridge = QccBridgeServer(
        port=0
    )

    try:
        assert isinstance(
            bridge.managed_governance_registry,
            ManagedSiteGovernanceRegistry,
        )

    finally:
        bridge.close()


def test_capture_uses_runtime_plan_for_governance_but_hides_it(
    monkeypatch,
):
    calls = {}

    def fake_projection(
        context_store,
        result,
    ):
        calls[
            "projection"
        ] = result

        return {
            "projected":
                True,

            "reason":
                "PROJECTED",
        }

    def fake_planning(
        context_store,
        knowledge_store,
        *,
        include_runtime_plan=False,
    ):
        calls[
            "include_runtime_plan"
        ] = include_runtime_plan

        return {
            "refreshed":
                True,

            "reason":
                "REFRESHED",

            "planning": {
                "projected":
                    True,

                "reason":
                    "PROJECTED",

                "runtime_plan": {
                    "schema_version":
                        1,

                    "plan_type":
                        "QCC_NAVIGATION_PLAN",

                    "secret_runtime_marker":
                        "MUST_NOT_LEAVE_BRIDGE",
                },
            },
        }

    def fake_governance(
        context_store,
        registry,
        *,
        planning_result,
        live_actions,
        page_url,
        site_code,
    ):
        calls[
            "planning_result"
        ] = planning_result

        calls[
            "live_actions"
        ] = live_actions

        calls[
            "page_url"
        ] = page_url

        calls[
            "site_code"
        ] = site_code

        return {
            "applied":
                True,

            "reason":
                "APPLIED",

            "decision":
                "HUMAN_ONLY",

            "automation_allowed":
                False,

            "revision":
                7,
        }

    monkeypatch.setattr(
        bridge_module,
        "project_ingested_state_observation",
        fake_projection,
    )

    monkeypatch.setattr(
        bridge_module,
        "refresh_live_navigation_plan",
        fake_planning,
    )

    monkeypatch.setattr(
        bridge_module,
        "apply_live_navigation_governance",
        fake_governance,
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _FakeIngestor()
        ),
    )

    bridge.start()

    try:
        payload = _post_capture(
            bridge
        )

        assert (
            calls[
                "include_runtime_plan"
            ]
            is True
        )

        assert (
            calls[
                "planning_result"
            ][
                "planning"
            ][
                "runtime_plan"
            ][
                "plan_type"
            ]
            == "QCC_NAVIGATION_PLAN"
        )

        assert len(
            calls[
                "live_actions"
            ]
        ) == 1

        assert (
            calls[
                "page_url"
            ]
            == (
                "http://127.0.0.1:8767"
                "/mercurio/"
                "entradaMercurio.html"
            )
        )

        assert (
            calls[
                "site_code"
            ]
            == "MERCURIO"
        )

        assert (
            payload[
                "live_governance"
            ][
                "decision"
            ]
            == "HUMAN_ONLY"
        )

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
        )

        assert (
            "runtime_plan"
            not in serialized
        )

        assert (
            "MUST_NOT_LEAVE_BRIDGE"
            not in serialized
        )

        assert (
            "live_actions"
            not in serialized
        )

        assert (
            payload[
                "live_planning"
            ][
                "planning"
            ].get(
                "runtime_plan"
            )
            is None
        )

    finally:
        bridge.close()


def test_capture_without_runtime_plan_does_not_govern(
    monkeypatch,
):
    governed = {
        "called":
            False,
    }

    monkeypatch.setattr(
        bridge_module,
        "project_ingested_state_observation",
        lambda context_store, result: {
            "projected":
                True,
        },
    )

    monkeypatch.setattr(
        bridge_module,
        "refresh_live_navigation_plan",
        lambda context_store,
        knowledge_store,
        include_runtime_plan=False: {
            "refreshed":
                True,

            "planning": {
                "projected":
                    True,
            },
        },
    )

    def fake_governance(
        *args,
        **kwargs,
    ):
        governed[
            "called"
        ] = True

        raise AssertionError(
            "governance must not run without canonical plan"
        )

    monkeypatch.setattr(
        bridge_module,
        "apply_live_navigation_governance",
        fake_governance,
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _FakeIngestor()
        ),
    )

    bridge.start()

    try:
        payload = _post_capture(
            bridge
        )

        assert (
            governed["called"]
            is False
        )

        assert (
            payload[
                "live_governance"
            ]
            is None
        )

    finally:
        bridge.close()


def test_unprojected_capture_never_replans_or_governs(
    monkeypatch,
):
    calls = {
        "planning":
            False,

        "governance":
            False,
    }

    monkeypatch.setattr(
        bridge_module,
        "project_ingested_state_observation",
        lambda context_store, result: {
            "projected":
                False,

            "reason":
                "CAPTURE_NOT_SESSION_BOUND",
        },
    )

    def fake_planning(
        *args,
        **kwargs,
    ):
        calls[
            "planning"
        ] = True

        raise AssertionError(
            "stale/unrelated capture must not replan"
        )

    def fake_governance(
        *args,
        **kwargs,
    ):
        calls[
            "governance"
        ] = True

        raise AssertionError(
            "stale/unrelated capture must not govern"
        )

    monkeypatch.setattr(
        bridge_module,
        "refresh_live_navigation_plan",
        fake_planning,
    )

    monkeypatch.setattr(
        bridge_module,
        "apply_live_navigation_governance",
        fake_governance,
    )

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _FakeIngestor(
                session_bound=False
            )
        ),
    )

    bridge.start()

    try:
        payload = _post_capture(
            bridge
        )

        assert (
            calls["planning"]
            is False
        )

        assert (
            calls["governance"]
            is False
        )

        assert (
            payload[
                "live_planning"
            ]
            is None
        )

        assert (
            payload[
                "live_governance"
            ]
            is None
        )

    finally:
        bridge.close()


def test_unregistered_site_remains_planning_only(
    monkeypatch,
):
    calls = {
        "governance":
            False,
    }

    monkeypatch.setattr(
        bridge_module,
        "project_ingested_state_observation",
        lambda context_store, result: {
            "projected":
                True,
        },
    )

    monkeypatch.setattr(
        bridge_module,
        "refresh_live_navigation_plan",
        lambda context_store,
        knowledge_store,
        include_runtime_plan=False: {
            "refreshed":
                True,

            "planning": {
                "projected":
                    True,

                "runtime_plan": {
                    "schema_version":
                        1,

                    "plan_type":
                        "QCC_NAVIGATION_PLAN",
                },
            },
        },
    )

    def fake_governance(
        *args,
        **kwargs,
    ):
        calls[
            "governance"
        ] = True

        raise AssertionError(
            "unregistered site must remain planning-only"
        )

    monkeypatch.setattr(
        bridge_module,
        "apply_live_navigation_governance",
        fake_governance,
    )

    class _UnregisteredIngestor:
        def ingest(
            self,
            capture,
            *,
            context=None,
        ):
            return {
                "capture_id":
                    "capture-unregistered",

                "context_mode":
                    "ASSISTED_PRESENTATION",

                "session_id":
                    "session-1",

                "site_code":
                    "TEST_SITE",

                "page": {
                    "url":
                        "https://example.test/app",

                    "title":
                        "Test",
                },

                "state_observation": {
                    "state":
                        "STATE_A",

                    "fingerprint":
                        "a" * 64,
                },

                "live_actions":
                    (),

                "counts": {
                    "elements":
                        0,
                },
            }

    bridge = QccBridgeServer(
        port=0,
        site_architecture_ingestor=(
            _UnregisteredIngestor()
        ),
    )

    bridge.start()

    try:
        payload = _post_capture(
            bridge
        )

        assert (
            calls["governance"]
            is False
        )

        assert (
            payload[
                "live_governance"
            ]
            is None
        )

    finally:
        bridge.close()
