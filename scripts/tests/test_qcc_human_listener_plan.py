from datetime import (
    datetime,
    timezone,
)

import pytest

from backend.qcc.context.human_listener_plan import (
    QccHumanListenerTarget,
    build_human_listener_plan,
)
from backend.qcc.context.live_action_evidence import (
    QccLiveActionEvidence,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.live_navigation import (
    QccLiveNavigationContext,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


NOW = datetime(
    2026,
    8,
    31,
    13,
    30,
    tzinfo=timezone.utc,
)

FP = "a" * 64


def _session():
    return QccPresentationSession(
        session_id="session-1",
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
        session_id="session-1",
        updated_at=NOW,
        current_state="STATE_A",
        current_fingerprint=FP,
    )


def _action(
    selector,
    *,
    frame_path="main",
    kind="BUTTON",
    policy="HUMAN_ONLY",
):
    return {
        "kind":
            kind,

        "policy":
            policy,

        "selector":
            selector,

        "frame_path":
            frame_path,
    }


def _store(
    actions,
):
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_live_navigation(
        _navigation()
    )

    store.set_navigation_environment(
        "REAL",
        session_id="session-1",
    )

    store.set_live_action_evidence(
        QccLiveActionEvidence(
            session_id="session-1",
            site_code="MERCURIO",
            environment="REAL",
            before_state="STATE_A",
            before_fingerprint=FP,
            actions=tuple(
                actions
            ),
            captured_at=NOW,
        )
    )

    return store


def test_target_accepts_main():
    target = (
        QccHumanListenerTarget(
            selector="#continuar",
            frame_path="main",
        )
    )

    assert (
        target.frame_path
        == "main"
    )


def test_target_accepts_exact_chrome_frame_id():
    target = (
        QccHumanListenerTarget(
            selector="#continuar",
            frame_path="qcc-frame:7",
        )
    )

    assert (
        target.frame_path
        == "qcc-frame:7"
    )


def test_target_rejects_frame_index_fallback():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_LISTENER_FRAME_UNSUPPORTED"
        ),
    ):
        QccHumanListenerTarget(
            selector="#continuar",
            frame_path="qcc-frame-index:1",
        )


def test_plan_preserves_backend_canonical_selector_exactly():
    store = _store(
        (
            _action(
                '[id="a:b"]'
            ),
        )
    )

    plan = (
        build_human_listener_plan(
            store,
            now=NOW,
        )
    )

    assert (
        plan.targets[0].selector
        == '[id="a:b"]'
    )


def test_plan_does_not_replace_name_selector_with_select_specific_selector():
    store = _store(
        (
            _action(
                '[name="provincia"]'
            ),
        )
    )

    plan = (
        build_human_listener_plan(
            store,
            now=NOW,
        )
    )

    assert (
        plan.targets[0].selector
        == '[name="provincia"]'
    )


def test_plan_preserves_data_testid_selector():
    store = _store(
        (
            _action(
                '[data-testid="continue"]'
            ),
        )
    )

    plan = (
        build_human_listener_plan(
            store,
            now=NOW,
        )
    )

    assert (
        plan.targets[0].selector
        == '[data-testid="continue"]'
    )


def test_plan_preserves_qcc_frame_id():
    store = _store(
        (
            _action(
                "#continuar",
                frame_path="qcc-frame:22",
            ),
        )
    )

    plan = (
        build_human_listener_plan(
            store,
            now=NOW,
        )
    )

    assert (
        plan.targets[0].frame_path
        == "qcc-frame:22"
    )


def test_ambiguous_locator_is_not_exposed_to_browser():
    store = _store(
        (
            _action(
                "#continuar",
                policy="HUMAN_ONLY",
            ),
            _action(
                "#continuar",
                policy="REQUIRES_POLICY",
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_LISTENER_TARGETS_UNAVAILABLE"
        ),
    ):
        build_human_listener_plan(
            store,
            now=NOW,
        )


def test_unsupported_frame_is_not_exposed():
    store = _store(
        (
            _action(
                "#continuar",
                frame_path=(
                    "qcc-frame-index:1"
                ),
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_LISTENER_TARGETS_UNAVAILABLE"
        ),
    ):
        build_human_listener_plan(
            store,
            now=NOW,
        )


def test_transport_contains_only_locator_fields():
    store = _store(
        (
            _action(
                "#continuar"
            ),
        )
    )

    payload = (
        build_human_listener_plan(
            store,
            now=NOW,
        )
        .to_transport_dict()
    )

    assert payload == {
        "targets": [
            {
                "selector":
                    "#continuar",

                "frame_path":
                    "main",
            }
        ]
    }

    serialized = str(
        payload
    )

    for forbidden in (
        "policy",
        "kind",
        "environment",
        "site_code",
        "fingerprint",
        "HUMAN_ONLY",
    ):
        assert (
            forbidden
            not in serialized
        )


def test_plan_requires_runtime_evidence():
    store = QccContextStore()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_HUMAN_LISTENER_EVIDENCE_REQUIRED"
        ),
    ):
        build_human_listener_plan(
            store,
            now=NOW,
        )


def test_non_navigation_action_is_not_exposed_to_click_listener():
    store = _store(
        (
            _action(
                "#country",
                kind="SELECT",
                policy="STATE_CHANGE_CANDIDATE",
            ),
            _action(
                "#continuar",
                kind="BUTTON",
                policy="REQUIRES_POLICY",
            ),
        )
    )

    plan = (
        build_human_listener_plan(
            store,
            now=NOW,
        )
    )

    assert (
        tuple(
            target.selector
            for target
            in plan.targets
        )
        == (
            "#continuar",
        )
    )
