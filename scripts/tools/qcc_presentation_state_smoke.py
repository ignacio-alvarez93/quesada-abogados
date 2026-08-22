"""Smoke manual de estados dinámicos QCC.

No ejecuta SeleniumBase.
Simula el flujo que posteriormente publicará
una presentación asistida real.
"""

from dataclasses import replace
from datetime import (
    datetime,
    timezone,
)
import time

from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.qcc.contracts.protocol import (
    QccPresentationSession,
    QccPresentationStatus,
)


STEP_SECONDS = 5


def _publish(
    server,
    session,
):
    server.context_store.set_active_session(
        session
    )

    print(
        "[QCC-DEMO]",
        session.status.value,
        "|",
        session.progress,
        "%",
        "|",
        session.current_step,
        flush=True,
    )


def main():
    server = QccBridgeServer()

    base = QccPresentationSession(
        session_id="qcc-dynamic-smoke-001",
        expedient_id=1842,
        client_id=321,
        procedure=(
            "REAGRUPACION_FAMILIAR_INICIAL"
        ),
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime.now(
            timezone.utc
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

    states = [
        base,
        replace(
            base,
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
                    "Continúe manualmente en Mercurio",
            },
        ),
        replace(
            base,
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
            base,
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
            base,
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

    server.start()

    print(
        "[QCC-DEMO] listening "
        "http://127.0.0.1:8766",
        flush=True,
    )

    try:
        for index, state in enumerate(
            states
        ):
            _publish(
                server,
                state,
            )

            if index < len(states) - 1:
                time.sleep(
                    STEP_SECONDS
                )

        print(
            "[QCC-DEMO] ciclo completado.",
            flush=True,
        )

        print(
            "[QCC-DEMO] Ctrl+C para cerrar.",
            flush=True,
        )

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        pass
    finally:
        server.close()

        print(
            "[QCC-DEMO] closed",
            flush=True,
        )


if __name__ == "__main__":
    main()
