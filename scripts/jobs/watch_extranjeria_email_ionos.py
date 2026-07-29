"""
Ejecuta una sincronización puntual del buzón IONOS.

No contiene bucles permanentes. Podrá ser invocado posteriormente
por el scheduler del CRM, el PC bot o el Programador de tareas.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(
    PROJECT_ROOT / ".env.local",
    override=False,
)


from backend.services.email_platform import (
    email_account_service,
)
from backend.services.email_platform.providers.ionos_imap_provider import (
    IonosImapProvider,
)


def main():
    account_email = os.getenv(
        "QUESADA_IONOS_ACCOUNT_EMAIL",
        "",
    ).strip().lower()

    if not account_email:
        raise RuntimeError(
            "Falta QUESADA_IONOS_ACCOUNT_EMAIL"
        )

    account = (
        email_account_service.ensure_account(
            nombre=(
                "IONOS · Correo del despacho"
            ),
            email_address=account_email,
            provider="IONOS_IMAP",
            credential_key="QUESADA_IONOS",
            config={
                "host":
                    os.getenv(
                        "QUESADA_IONOS_HOST",
                        "imap.ionos.es",
                    ),
                "port":
                    int(
                        os.getenv(
                            "QUESADA_IONOS_PORT",
                            "993",
                        )
                    ),
                "folder":
                    os.getenv(
                        "QUESADA_IONOS_FOLDER",
                        "INBOX",
                    ),
                "sender_filters": [
                    (
                        "notificaciones."
                        "extranjeria@correo.gob.es"
                    ),
                    (
                        "no-reply-notifica"
                        "@correo.gob.es"
                    ),
                    (
                        "noreply.dehu"
                        "@correo.gob.es"
                    ),
                ],
            },
            incoming_enabled=True,
            outgoing_enabled=False,
        )
    )

    result = IonosImapProvider(
        account
    ).sync_incoming()

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
