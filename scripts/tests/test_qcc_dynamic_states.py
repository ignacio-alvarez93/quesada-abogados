from dataclasses import replace
from datetime import (
    datetime,
    timezone,
)

from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


def _base_session():
    return QccPresentationSession(
        session_id="qcc-dynamic-001",
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
            9,
            0,
            tzinfo=timezone.utc,
        ),
        status=(
            QccPresentationStatus.AUTOMATING
        ),
        current_step="CLIENT_DATA",
        progress=25,
        requires_user_action=False,
        last_event={
            "event":
                "presentation.step_started",
            "message":
                "Completando datos del cliente",
        },
    )


def test_context_tracks_full_presentation_lifecycle():
    store = QccContextStore()

    session = _base_session()

    states = [
        session,
        replace(
            session,
            status=(
                QccPresentationStatus
                .WAITING_USER
            ),
            current_step="USER_CONFIRMATION",
            progress=60,
            requires_user_action=True,
            last_event={
                "event":
                    "presentation.waiting_user",
                "message":
                    "Esperando acción del usuario",
            },
        ),
        replace(
            session,
            status=(
                QccPresentationStatus
                .USER_ACTION_DETECTED
            ),
            current_step="USER_CONFIRMATION",
            progress=65,
            requires_user_action=False,
            last_event={
                "event":
                    "presentation.user_action_detected",
                "message":
                    "Acción manual detectada",
            },
        ),
        replace(
            session,
            status=(
                QccPresentationStatus
                .RESUMING
            ),
            current_step="UPLOAD_DOCUMENTS",
            progress=72,
            requires_user_action=False,
            last_event={
                "event":
                    "presentation.resuming",
                "message":
                    "Reanudando automatización",
            },
        ),
        replace(
            session,
            status=(
                QccPresentationStatus
                .COMPLETED
            ),
            current_step="COMPLETED",
            progress=100,
            requires_user_action=False,
            last_event={
                "event":
                    "presentation.completed",
                "message":
                    "Presentación completada",
            },
        ),
    ]

    observed = []

    for state in states:
        store.set_active_session(
            state
        )

        snapshot = store.snapshot()

        observed.append(
            snapshot[
                "active_session"
            ]["status"]
        )

    assert observed == [
        "AUTOMATING",
        "WAITING_USER",
        "USER_ACTION_DETECTED",
        "RESUMING",
        "COMPLETED",
    ]

    assert store.revision == 5

    final = store.snapshot()[
        "active_session"
    ]

    assert final["progress"] == 100

    assert final["last_event"][
        "event"
    ] == "presentation.completed"


def test_waiting_user_snapshot_requires_action():
    store = QccContextStore()

    session = replace(
        _base_session(),
        status=(
            QccPresentationStatus
            .WAITING_USER
        ),
        requires_user_action=True,
    )

    store.set_active_session(
        session
    )

    payload = store.snapshot()[
        "active_session"
    ]

    assert (
        payload["status"]
        == "WAITING_USER"
    )

    assert (
        payload["requires_user_action"]
        is True
    )
