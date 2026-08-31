from datetime import (
    datetime,
    timezone,
)

import pytest

from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


def _session(
    session_id="session-1",
    *,
    progress=0,
):
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1,
        client_id=1,
        procedure="TEST_PROCEDURE",
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
        progress=progress,
        requires_user_action=False,
        last_event=None,
    )


def test_environment_scope_starts_empty_and_is_not_public():
    store = QccContextStore()

    assert (
        store.get_navigation_environment()
        is None
    )

    snapshot = store.snapshot()

    assert (
        "navigation_environment"
        not in snapshot
    )

    assert (
        "environment"
        not in snapshot
    )


def test_environment_scope_requires_active_session():
    store = QccContextStore()

    with pytest.raises(
        ValueError,
        match=(
            "QCC_NAVIGATION_ENVIRONMENT_SESSION_NOT_ACTIVE"
        ),
    ):
        store.set_navigation_environment(
            "LAB",
            session_id="session-1",
        )


def test_environment_scope_is_bound_to_active_session():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_NAVIGATION_ENVIRONMENT_SESSION_NOT_ACTIVE"
        ),
    ):
        store.set_navigation_environment(
            "LAB",
            session_id="other-session",
        )


def test_environment_scope_is_private_and_does_not_change_revision():
    store = QccContextStore()

    revision = store.set_active_session(
        _session()
    )

    public_before = (
        store.snapshot()
    )

    result = (
        store.set_navigation_environment(
            "lab",
            session_id="session-1",
        )
    )

    assert result == "LAB"

    assert (
        store.get_navigation_environment()
        == "LAB"
    )

    assert store.revision == revision

    assert (
        store.snapshot()
        == public_before
    )


def test_same_session_preserves_environment_scope():
    store = QccContextStore()

    store.set_active_session(
        _session(
            progress=10
        )
    )

    store.set_navigation_environment(
        "LAB",
        session_id="session-1",
    )

    store.set_active_session(
        _session(
            progress=50
        )
    )

    assert (
        store.get_navigation_environment()
        == "LAB"
    )


def test_same_session_cannot_switch_environment():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_navigation_environment(
        "LAB",
        session_id="session-1",
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_NAVIGATION_ENVIRONMENT_CONFLICT"
        ),
    ):
        store.set_navigation_environment(
            "REAL",
            session_id="session-1",
        )

    assert (
        store.get_navigation_environment()
        == "LAB"
    )


def test_new_session_clears_environment_scope():
    store = QccContextStore()

    store.set_active_session(
        _session(
            "session-1"
        )
    )

    store.set_navigation_environment(
        "REAL",
        session_id="session-1",
    )

    store.set_active_session(
        _session(
            "session-2"
        )
    )

    assert (
        store.get_navigation_environment()
        is None
    )


def test_stale_session_cannot_clear_environment_scope():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_navigation_environment(
        "REAL",
        session_id="session-1",
    )

    assert (
        store.clear_navigation_environment(
            session_id="old-session",
        )
        is False
    )

    assert (
        store.get_navigation_environment()
        == "REAL"
    )


def test_clear_environment_scope_does_not_change_revision():
    store = QccContextStore()

    revision = store.set_active_session(
        _session()
    )

    store.set_navigation_environment(
        "LAB",
        session_id="session-1",
    )

    public_before = (
        store.snapshot()
    )

    assert (
        store.clear_navigation_environment(
            session_id="session-1",
        )
        is True
    )

    assert (
        store.get_navigation_environment()
        is None
    )

    assert store.revision == revision

    assert (
        store.snapshot()
        == public_before
    )


def test_clear_active_session_clears_environment_scope():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    store.set_navigation_environment(
        "REAL",
        session_id="session-1",
    )

    assert (
        store.clear_active_session(
            session_id="session-1",
        )
        is True
    )

    assert (
        store.get_navigation_environment()
        is None
    )
