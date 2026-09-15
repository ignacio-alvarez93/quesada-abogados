from datetime import (
    datetime,
    timezone,
)

import pytest

from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)


def _session(
    *,
    session_id: str = "qcc-mercurio-001",
    progress: int = 42,
) -> QccPresentationSession:
    return QccPresentationSession(
        session_id=session_id,
        expedient_id=1842,
        client_id=321,
        procedure=(
            "REAGRUPACION_FAMILIAR_INICIAL"
        ),
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime(
            2026,
            8,
            22,
            8,
            30,
            tzinfo=timezone.utc,
        ),
        status=(
            QccPresentationStatus.AUTOMATING
        ),
        current_step="CLIENT_DATA",
        progress=progress,
        requires_user_action=False,
        last_event={
            "event":
                "presentation.step_started",
        },
    )


def test_context_starts_empty():
    store = QccContextStore()

    assert store.snapshot() == {
        "protocol_version":
            QCC_PROTOCOL_VERSION,
        "revision":
            0,
        "active":
            False,
        "active_session":
            None,

        "live_navigation":
            None,
    }


def test_context_accepts_seleniumbase_session():
    store = QccContextStore()

    revision = store.set_active_session(
        _session()
    )

    assert revision == 1

    snapshot = store.snapshot()

    assert snapshot["active"] is True
    assert snapshot["revision"] == 1

    session = snapshot["active_session"]

    assert session is not None
    assert session["provider"] == "MERCURIO"
    assert (
        session["runtime"]
        == "SELENIUMBASE_ASSISTED"
    )


def test_context_replaces_active_snapshot():
    store = QccContextStore()

    store.set_active_session(
        _session(
            progress=20,
        )
    )

    store.set_active_session(
        _session(
            progress=75,
        )
    )

    snapshot = store.snapshot()

    assert snapshot["revision"] == 2
    assert (
        snapshot["active_session"]["progress"]
        == 75
    )


def test_context_rejects_invalid_session_type():
    store = QccContextStore()

    with pytest.raises(
        TypeError,
        match="QCC_SESSION_TYPE_INVALID",
    ):
        store.set_active_session(
            object()
        )


def test_context_can_clear_matching_session():
    store = QccContextStore()

    store.set_active_session(
        _session()
    )

    cleared = store.clear_active_session(
        session_id="qcc-mercurio-001",
    )

    assert cleared is True

    snapshot = store.snapshot()

    assert snapshot["revision"] == 2
    assert snapshot["active"] is False
    assert snapshot["active_session"] is None


def test_old_runtime_cannot_clear_new_session():
    store = QccContextStore()

    store.set_active_session(
        _session(
            session_id="qcc-new-session",
        )
    )

    cleared = store.clear_active_session(
        session_id="qcc-old-session",
    )

    assert cleared is False

    assert (
        store.get_active_session().session_id
        == "qcc-new-session"
    )

    assert store.revision == 1
