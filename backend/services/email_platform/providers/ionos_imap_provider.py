"""
Proveedor de entrada IONOS mediante IMAP SSL.

Características:

- acceso de solo lectura;
- búsqueda incremental por UID;
- BODY.PEEK[] para no marcar como leído;
- no mueve ni elimina mensajes;
- detiene el avance del cursor ante un error.
"""

import imaplib
import json
import os
import ssl

from backend.services.email_platform import (
    email_account_service,
    email_expedient_sync_service,
    email_rfc822_parser,
)
from backend.services.email_platform.providers.base_email_provider import (
    BaseEmailProvider,
)


DEFAULT_HOST = "imap.ionos.es"
DEFAULT_PORT = 993
DEFAULT_FOLDER = "INBOX"

EXTRANJERIA_SENDER = (
    "notificaciones.extranjeria@correo.gob.es"
)


def _configuration(account):
    try:
        config = json.loads(
            account.get("config_json")
            or "{}"
        )
    except Exception:
        config = {}

    credential_key = str(
        account.get("credential_key")
        or "QUESADA_IONOS"
    ).strip().upper()

    return {
        "host":
            str(
                config.get("host")
                or DEFAULT_HOST
            ).strip(),
        "port":
            int(
                config.get("port")
                or DEFAULT_PORT
            ),
        "folder":
            str(
                config.get("folder")
                or DEFAULT_FOLDER
            ).strip(),
        "sender_filter":
            str(
                config.get("sender_filter")
                or EXTRANJERIA_SENDER
            ).strip().lower(),
        "username":
            os.getenv(
                credential_key + "_USERNAME",
                account.get("email_address")
                or "",
            ).strip(),
        "password":
            os.getenv(
                credential_key + "_PASSWORD",
                "",
            ),
    }


class IonosImapProvider(
    BaseEmailProvider
):
    def __init__(
        self,
        account,
        *,
        imap_factory=None,
    ):
        self.account = dict(account or {})
        self.config = _configuration(
            self.account
        )
        self.imap_factory = (
            imap_factory
            or imaplib.IMAP4_SSL
        )

    def _validate_credentials(self):
        if not self.config["username"]:
            raise ValueError(
                "Falta el usuario IMAP de IONOS"
            )

        if not self.config["password"]:
            credential_key = str(
                self.account.get(
                    "credential_key"
                )
                or "QUESADA_IONOS"
            ).strip().upper()

            raise ValueError(
                "Falta la variable de entorno "
                + credential_key
                + "_PASSWORD"
            )

    def _open(self):
        self._validate_credentials()

        context = ssl.create_default_context()

        client = self.imap_factory(
            self.config["host"],
            self.config["port"],
            ssl_context=context,
        )

        client.login(
            self.config["username"],
            self.config["password"],
        )

        status, _ = client.select(
            self.config["folder"],
            readonly=True,
        )

        if status != "OK":
            try:
                client.logout()
            except Exception:
                pass

            raise RuntimeError(
                "No se pudo abrir la carpeta "
                + self.config["folder"]
            )

        return client

    def test_connection(self):
        client = self._open()

        try:
            return {
                "ok": True,
                "host": self.config["host"],
                "port": self.config["port"],
                "folder":
                    self.config["folder"],
                "account_email":
                    self.account.get(
                        "email_address"
                    ),
            }
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def _search_uids(self, client):
        last_cursor = str(
            self.account.get(
                "last_sync_cursor"
            )
            or ""
        ).strip()

        criteria = []

        if last_cursor.isdigit():
            criteria.extend(
                [
                    "UID",
                    f"{int(last_cursor) + 1}:*",
                ]
            )

        sender_filter = self.config[
            "sender_filter"
        ]

        if sender_filter:
            criteria.extend(
                [
                    "FROM",
                    f'"{sender_filter}"',
                ]
            )

        if not criteria:
            criteria = ["ALL"]

        status, data = client.uid(
            "SEARCH",
            None,
            *criteria,
        )

        if status != "OK":
            raise RuntimeError(
                "IONOS no pudo ejecutar "
                "la búsqueda IMAP"
            )

        raw = (
            data[0]
            if data
            else b""
        )

        if isinstance(raw, bytes):
            values = raw.split()
        else:
            values = str(raw).split()

        uids = []

        for value in values:
            decoded = (
                value.decode("ascii")
                if isinstance(value, bytes)
                else str(value)
            )

            if decoded.isdigit():
                uids.append(int(decoded))

        return sorted(set(uids))

    def _fetch_raw_message(
        self,
        client,
        uid,
    ):
        status, data = client.uid(
            "FETCH",
            str(uid),
            "(BODY.PEEK[])",
        )

        if status != "OK":
            raise RuntimeError(
                f"No se pudo descargar el UID {uid}"
            )

        for item in data or []:
            if (
                isinstance(item, tuple)
                and len(item) >= 2
                and isinstance(
                    item[1],
                    bytes,
                )
            ):
                return item[1]

        raise RuntimeError(
            f"El UID {uid} no contenía RFC822"
        )

    def sync_incoming(self):
        account_id = int(
            self.account["id"]
        )

        client = None
        processed = []
        errors = []

        try:
            client = self._open()
            uids = self._search_uids(
                client
            )

            for uid in uids:
                try:
                    raw_message = (
                        self._fetch_raw_message(
                            client,
                            uid,
                        )
                    )

                    normalized = (
                        email_rfc822_parser
                        .parse_rfc822_message(
                            raw_message,
                            provider="IONOS_IMAP",
                            account_email=(
                                self.account[
                                    "email_address"
                                ]
                            ),
                            provider_message_id=uid,
                            folder=self.config[
                                "folder"
                            ],
                        )
                    )

                    result = (
                        email_expedient_sync_service
                        .process_message(
                            normalized
                        )
                    )

                    processed.append(
                        {
                            "uid": uid,
                            "status":
                                result.get(
                                    "status"
                                ),
                            "email_message_id":
                                result.get(
                                    "email_message_id"
                                ),
                            "expediente_id":
                                result.get(
                                    "expediente_id"
                                ),
                        }
                    )

                    email_account_service.update_sync_success(
                        account_id,
                        cursor=uid,
                    )

                    self.account[
                        "last_sync_cursor"
                    ] = str(uid)

                except Exception as exc:
                    errors.append(
                        {
                            "uid": uid,
                            "error": str(exc),
                        }
                    )

                    email_account_service.update_sync_error(
                        account_id,
                        (
                            f"UID {uid}: "
                            f"{exc}"
                        ),
                    )

                    break

            if not uids:
                email_account_service.update_sync_success(
                    account_id
                )

            return {
                "ok": not bool(errors),
                "account_id": account_id,
                "account_email":
                    self.account[
                        "email_address"
                    ],
                "uids_found": len(uids),
                "processed": processed,
                "errors": errors,
                "last_cursor":
                    self.account.get(
                        "last_sync_cursor"
                    )
                    or "",
            }

        except Exception as exc:
            email_account_service.update_sync_error(
                account_id,
                str(exc),
            )
            raise

        finally:
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    pass
