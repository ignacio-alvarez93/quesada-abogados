"""
Worker de entrega de notificaciones programadas.

Uso:

    python -m backend.workers.task_notification_worker --dry-run

    python -m backend.workers.task_notification_worker

El modo dry-run:

- consulta la outbox;
- construye mensajes;
- no cambia estados;
- no realiza llamadas de red.
"""

import argparse
from datetime import datetime

import sys


def _console_print(*args, sep=" ", end="\n"):
    """
    Impresión segura para terminales Windows que no soportan
    todos los caracteres Unicode.

    El mensaje original mantiene Unicode completo para Telegram;
    únicamente se adapta su representación en consola.
    """
    text = sep.join(
        str(arg)
        for arg in args
    )

    encoding = (
        getattr(sys.stdout, "encoding", None)
        or "utf-8"
    )

    safe_text = (
        text
        .encode(
            encoding,
            errors="replace",
        )
        .decode(
            encoding,
            errors="replace",
        )
    )

    sys.stdout.write(
        safe_text + end
    )


from backend.services import (
    notification_message_service,
)
from backend.services import (
    scheduled_notification_service,
)
from backend.services import (
    telegram_service,
)


def process_due_notifications(
    *,
    dry_run=False,
    now=None,
    limit=100,
):
    items = (
        scheduled_notification_service
        .list_due_notifications(
            now=now,
            limit=limit,
        )
    )

    summary = {
        "found": len(items),
        "sent": 0,
        "failed": 0,
        "dry_run": 0,
    }

    for notification in items:
        notification_id = int(
            notification["id"]
        )

        message = (
            notification_message_service
            .build_notification_message(
                notification
            )
        )

        if dry_run:
            summary["dry_run"] += 1

            _console_print()
            _console_print(
                "=" * 70
            )
            _console_print(
                "[DRY RUN]"
            )
            _console_print(
                "Notification ID:",
                notification_id,
            )
            _console_print(
                "Source:",
                notification[
                    "source_type"
                ],
                notification[
                    "source_id"
                ],
            )
            _console_print(
                "-" * 70
            )
            _console_print(message)
            _console_print(
                "=" * 70
            )

            continue

        try:
            (
                scheduled_notification_service
                .mark_processing(
                    notification_id
                )
            )

            telegram_service.send_message(
                message
            )

            (
                scheduled_notification_service
                .mark_sent(
                    notification_id
                )
            )

            summary["sent"] += 1

            _console_print(
                "ENVIADA",
                notification_id,
                notification[
                    "source_type"
                ],
                notification[
                    "source_id"
                ],
            )

        except Exception as exc:
            try:
                (
                    scheduled_notification_service
                    .mark_error(
                        notification_id,
                        str(exc),
                    )
                )
            except Exception:
                pass

            summary["failed"] += 1

            _console_print(
                "ERROR",
                notification_id,
                str(exc),
            )

    return summary


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Entrega avisos del calendario "
            "por Telegram."
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Muestra mensajes sin enviarlos "
            "ni cambiar la outbox."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=100,
    )

    args = parser.parse_args()

    _console_print(
        "Worker calendario / Telegram"
    )

    _console_print(
        "Hora:",
        datetime.now().isoformat(
            sep=" ",
            timespec="seconds",
        ),
    )

    _console_print(
        "Modo:",
        (
            "DRY-RUN"
            if args.dry_run
            else "ENVÍO REAL"
        ),
    )

    summary = process_due_notifications(
        dry_run=args.dry_run,
        limit=args.limit,
    )

    _console_print()
    _console_print("Resumen:")
    _console_print(
        "  encontradas:",
        summary["found"],
    )
    _console_print(
        "  enviadas:",
        summary["sent"],
    )
    _console_print(
        "  errores:",
        summary["failed"],
    )
    _console_print(
        "  dry-run:",
        summary["dry_run"],
    )


if __name__ == "__main__":
    main()
