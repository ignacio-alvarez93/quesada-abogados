"""
Prueba la conexión IONOS sin descargar ni procesar mensajes.
"""

import json
import os
import sys

from backend.services.email_platform import (
    email_account_service,
)
from backend.services.email_platform.providers.ionos_imap_provider import (
    IonosImapProvider,
)


def build_account():
    account_email = os.getenv(
        "QUESADA_IONOS_ACCOUNT_EMAIL",
        "",
    ).strip().lower()

    if not account_email:
        raise RuntimeError(
            "Falta QUESADA_IONOS_ACCOUNT_EMAIL"
        )

    return email_account_service.ensure_account(
        nombre="IONOS · Correo del despacho",
        email_address=account_email,
        provider="IONOS_IMAP",
        credential_key="QUESADA_IONOS",
        config={
            "host": os.getenv(
                "QUESADA_IONOS_HOST",
                "imap.ionos.es",
            ),
            "port": int(
                os.getenv(
                    "QUESADA_IONOS_PORT",
                    "993",
                )
            ),
            "folder": os.getenv(
                "QUESADA_IONOS_FOLDER",
                "INBOX",
            ),
            "sender_filter": (
                "notificaciones.extranjeria"
                "@correo.gob.es"
            ),
        },
        incoming_enabled=True,
        outgoing_enabled=False,
    )


def main():
    account = build_account()

    result = IonosImapProvider(
        account
    ).test_connection()

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
