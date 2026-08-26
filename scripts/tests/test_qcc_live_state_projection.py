from datetime import (
    datetime,
    timezone,
)

from backend.qcc.context.live_state_projection import (
    LIVE_STATE_CAPTURE_NOT_SESSION_BOUND,
    LIVE_STATE_PROJECTED,
    LIVE_STATE_SITE_MISMATCH,
    LIVE_STATE_SITE_UNRECOGNIZED,
    LIVE_STATE_STALE_SESSION,
    project_ingested_state_observation,
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


FINGERPRINT_A = (
    "a" * 64
)

FINGERPRINT_B = (
    "b" * 64
)


def _session(
    *,
    session_id="session-1",
    provider="MERCURIO",
):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST",
        provider=provider,
        runtime="TEST_RUNTIME",
        started_at=datetime.now(
            timezone.utc
        ),
        status=(
            QccPresentationStatus
            .AUTOMATING
        ),
        current_step="TEST",
        progress=10,
        requires_user_action=False,
    )


def _result(
    *,
    session_id="session-1",
    site_code="MERCURIO",
    state="MERCURIO_INICIO",
    fingerprint=FINGERPRINT_A,
):
    return {
        "session_id":
            session_id,

        "site_code":
            site_code,

        "received_at":
            "2026-08-26T10:30:00+00:00",

        "state_observation": {
            "state":
                state,

            "fingerprint":
                fingerprint,
        },
    }


def test_matching_session_and_site_projects_current():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    projection = (
        project_ingested_state_observation(
            store,
            _result(),
        )
    )

    assert (
        projection["projected"]
        is True
    )

    assert (
        projection["reason"]
        == LIVE_STATE_PROJECTED
    )

    live = (
        store.snapshot()[
            "live_navigation"
        ]
    )

    assert (
        live["current"]["state"]
        == "MERCURIO_INICIO"
    )

    assert (
        live["current"]["fingerprint"]
        == FINGERPRINT_A
    )

    assert (
        live["target"]["state"]
        is None
    )

    assert (
        live["route"]["reachable"]
        is None
    )

    assert (
        live["next_step"]
        is None
    )

    assert (
        live["governance"]
        is None
    )


def test_manual_capture_does_not_project():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    result = _result()
    result["session_id"] = None

    projection = (
        project_ingested_state_observation(
            store,
            result,
        )
    )

    assert (
        projection["projected"]
        is False
    )

    assert (
        projection["reason"]
        == LIVE_STATE_CAPTURE_NOT_SESSION_BOUND
    )

    assert (
        store.get_live_navigation()
        is None
    )


def test_stale_capture_cannot_enter_new_session():
    store = QccContextStore()

    store.set_active_session(
        _session(
            session_id="new-session"
        )
    )

    projection = (
        project_ingested_state_observation(
            store,
            _result(
                session_id="old-session"
            ),
        )
    )

    assert (
        projection["projected"]
        is False
    )

    assert (
        projection["reason"]
        == LIVE_STATE_STALE_SESSION
    )


def test_wrong_site_cannot_contaminate_session():
    store = QccContextStore()

    store.set_active_session(
        _session(
            provider="MERCURIO"
        )
    )

    projection = (
        project_ingested_state_observation(
            store,
            _result(
                site_code="OTHER_SITE"
            ),
        )
    )

    assert (
        projection["projected"]
        is False
    )

    assert (
        projection["reason"]
        == LIVE_STATE_SITE_MISMATCH
    )

    assert (
        store.get_live_navigation()
        is None
    )


def test_unknown_site_is_persistable_but_not_live_projected():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    projection = (
        project_ingested_state_observation(
            store,
            _result(
                site_code=None,
                state=None,
            ),
        )
    )

    assert (
        projection["projected"]
        is False
    )

    assert (
        projection["reason"]
        == LIVE_STATE_SITE_UNRECOGNIZED
    )


def test_new_dom_invalidates_old_plan_and_governance():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_live_navigation(
        QccLiveNavigationContext(
            session_id="session-1",
            updated_at=datetime.now(
                timezone.utc
            ),
            current_state="OLD_STATE",
            current_fingerprint=(
                FINGERPRINT_B
            ),
            target_state="TARGET_STATE",
            target_fingerprint=(
                "c" * 64
            ),
            route_reachable=True,
            remaining_steps=2,
            next_step_kind="SELECT",
            next_step_policy=(
                "STATE_CHANGE_CANDIDATE"
            ),
            next_step_selector="#province",
            next_step_confidence=0.99,
            governance_decision=(
                "AUTOMATION_ALLOWED"
            ),
            governance_reason=(
                "OLD_DOM"
            ),
            automation_allowed=True,
        )
    )

    projection = (
        project_ingested_state_observation(
            store,
            _result(
                state="NEW_STATE",
                fingerprint=(
                    FINGERPRINT_A
                ),
            ),
        )
    )

    assert (
        projection["projected"]
        is True
    )

    live = (
        store.snapshot()[
            "live_navigation"
        ]
    )

    assert (
        live["current"]["state"]
        == "NEW_STATE"
    )

    assert (
        live["target"]["state"]
        is None
    )

    assert (
        live["route"]["reachable"]
        is None
    )

    assert (
        live["next_step"]
        is None
    )

    assert (
        live["governance"]
        is None
    )


def test_known_site_can_project_fingerprint_without_semantic_state():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    projection = (
        project_ingested_state_observation(
            store,
            _result(
                state=None,
            ),
        )
    )

    assert (
        projection["projected"]
        is True
    )

    live = (
        store.snapshot()[
            "live_navigation"
        ]
    )

    assert (
        live["current"]["state"]
        is None
    )

    assert (
        live["current"]["fingerprint"]
        == FINGERPRINT_A
    )


def test_site_binding_is_case_insensitive():
    store = QccContextStore()

    store.set_active_session(
        _session(
            provider="mercurio"
        )
    )

    projection = (
        project_ingested_state_observation(
            store,
            _result(
                site_code="MERCURIO"
            ),
        )
    )

    assert (
        projection["projected"]
        is True
    )
