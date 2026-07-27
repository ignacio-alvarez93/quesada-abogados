"""
Muestra los UIDs candidatos sin descargar ni procesar correos.
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


def main():
    account_email = os.getenv(
        "QUESADA_IONOS_ACCOUNT_EMAIL",
        "",
    ).strip().lower()

    if not account_email:
        raise RuntimeError(
            "Falta QUESADA_IONOS_ACCOUNT_EMAIL"
        )

    account = email_account_service.ensure_account(
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

    provider = IonosImapProvider(account)
    client = provider._open()

    try:
        uids = provider._search_uids(client)

        result = {
            "ok": True,
            "account_id": account["id"],
            "account_email":
                account["email_address"],
            "last_sync_cursor":
                account.get("last_sync_cursor")
                or "",
            "uids_found": len(uids),
            "first_uid":
                uids[0] if uids else None,
            "last_uid":
                uids[-1] if uids else None,
            "sample_last_uids":
                uids[-20:],
            "messages_downloaded": 0,
            "messages_processed": 0,
        }

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

    finally:
        try:
            client.logout()
        except Exception:
            pass

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
