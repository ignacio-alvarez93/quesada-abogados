from datetime import (
    datetime,
    timezone,
)

import pytest

from backend.qcc.context.navigation_intent import (
    QccNavigationIntent,
)
from backend.qcc.context.live_state_projection import (
    project_ingested_state_observation,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


FP_A = "a" * 64
FP_TARGET = "c" * 64


def _session(
    *,
    session_id="session-1",
    provider="TEST_SITE",
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


def _intent(
    *,
    session_id="session-1",
    site_code="TEST_SITE",
):
    return QccNavigationIntent(
        session_id=session_id,
        site_code=site_code,
        target_state="TARGET_STATE",
        target_fingerprint=(
            FP_TARGET
        ),
    )


def test_intent_requires_explicit_target():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_NAVIGATION_INTENT_TARGET_REQUIRED"
        ),
    ):
        QccNavigationIntent(
            session_id="s1",
            site_code="TEST_SITE",
        )


def test_intent_normalizes_codes():
    intent = QccNavigationIntent(
        session_id="s1",
        site_code="test_site",
        target_state="target_state",
    )

    assert (
        intent.site_code
        == "TEST_SITE"
    )

    assert (
        intent.target_state
        == "TARGET_STATE"
    )


def test_intent_is_bound_to_active_session():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    revision = (
        store.set_navigation_intent(
            _intent()
        )
    )

    assert revision > 0

    assert (
        store.get_navigation_intent()
        == _intent()
    )


def test_intent_rejects_wrong_session():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_NAVIGATION_INTENT_SESSION_NOT_ACTIVE"
        ),
    ):
        store.set_navigation_intent(
            _intent(
                session_id="other"
            )
        )


def test_intent_rejects_wrong_site():
    store = QccContextStore()

    store.set_active_session(
        _session(
            provider="SITE_A"
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_NAVIGATION_INTENT_SITE_MISMATCH"
        ),
    ):
        store.set_navigation_intent(
            _intent(
                site_code="SITE_B"
            )
        )


def test_same_session_refresh_preserves_intent():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_navigation_intent(
        _intent()
    )

    # Update de la misma sesión.
    store.set_active_session(
        _session()
    )

    assert (
        store.get_navigation_intent()
        is not None
    )


def test_new_session_clears_old_intent():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_navigation_intent(
        _intent()
    )

    store.set_active_session(
        _session(
            session_id="session-2"
        )
    )

    assert (
        store.get_navigation_intent()
        is None
    )


def test_clear_active_session_clears_intent():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_navigation_intent(
        _intent()
    )

    store.clear_active_session(
        session_id="session-1"
    )

    assert (
        store.get_navigation_intent()
        is None
    )


def test_new_dom_does_not_destroy_navigation_intent():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_navigation_intent(
        _intent()
    )

    result = {
        "session_id":
            "session-1",

        "site_code":
            "TEST_SITE",

        "received_at":
            "2026-08-26T12:00:00+00:00",

        "state_observation": {
            "state":
                "CURRENT_STATE",

            "fingerprint":
                FP_A,
        },
    }

    projection = (
        project_ingested_state_observation(
            store,
            result,
        )
    )

    assert (
        projection["projected"]
        is True
    )

    # Live route/target se reinician
    # porque pertenecían al DOM anterior.
    live = store.snapshot()[
        "live_navigation"
    ]

    assert (
        live["target"]["state"]
        is None
    )

    # Pero el objetivo duradero permanece
    # listo para recalcular la nueva ruta.
    intent = (
        store.get_navigation_intent()
    )

    assert (
        intent.target_state
        == "TARGET_STATE"
    )

    assert (
        intent.target_fingerprint
        == FP_TARGET
    )


def test_intent_payload_is_pii_safe():
    intent = _intent()

    payload = intent.to_payload()

    assert set(
        payload
    ) == {
        "schema_version",
        "intent_type",
        "session_id",
        "site_code",
        "target",
        "requested_at",
    }

    serialized = str(
        payload
    ).lower()

    forbidden = (
        "html",
        "cookie",
        "password",
        "certificate",
        "nie",
        "client_id",
        "expedient_id",
    )

    for token in forbidden:
        assert token not in serialized
