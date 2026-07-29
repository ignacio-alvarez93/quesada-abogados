"""
Proveedor de entrada Gmail mediante Gmail API.

Características:

- OAuth 2.0;
- permiso gmail.readonly;
- no modifica mensajes ni etiquetas;
- filtro exacto por remitente oficial;
- lectura incremental mediante internalDate;
- descarga en formato RAW/RFC822;
- deduplicación mediante el núcleo común.
"""

import base64
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from backend.services.email_platform import (
    email_account_service,
    email_expedient_sync_service,
    email_rfc822_parser,
    gmail_oauth_service,
)
from backend.services.email_platform.providers.base_email_provider import (
    BaseEmailProvider,
)


EXTRANJERIA_SENDER = (
    "notificaciones.extranjeria@correo.gob.es"
)

DEHU_SENDER = (
    "no-reply-notifica@correo.gob.es"
)

DEFAULT_OFFICIAL_SENDERS = (
    EXTRANJERIA_SENDER,
    DEHU_SENDER,
)

DEFAULT_INITIAL_LOOKBACK_DAYS = 30
DEFAULT_MAX_RESULTS = 100


def _configuration(account):
    try:
        config = json.loads(
            account.get("config_json")
            or "{}"
        )
    except Exception:
        config = {}

    raw_sender_filters = (
        config.get("sender_filters")
    )

    if isinstance(raw_sender_filters, str):
        raw_sender_filters = [
            value.strip()
            for value in raw_sender_filters.split(",")
            if value.strip()
        ]

    if not isinstance(
        raw_sender_filters,
        (list, tuple, set),
    ):
        legacy_sender = str(
            config.get("sender_filter")
            or ""
        ).strip().lower()

        raw_sender_filters = (
            [legacy_sender]
            if legacy_sender
            else list(DEFAULT_OFFICIAL_SENDERS)
        )

    sender_filters = []

    for value in raw_sender_filters:
        sender = str(value or "").strip().lower()

        if sender and sender not in sender_filters:
            sender_filters.append(sender)

    return {
        "sender_filters": sender_filters,
        "sender_filter":
            (
                sender_filters[0]
                if sender_filters
                else ""
            ),
        "initial_lookback_days":
            max(
                1,
                int(
                    config.get(
                        "initial_lookback_days"
                    )
                    or DEFAULT_INITIAL_LOOKBACK_DAYS
                ),
            ),
        "max_results":
            max(
                1,
                min(
                    500,
                    int(
                        config.get("max_results")
                        or DEFAULT_MAX_RESULTS
                    ),
                ),
            ),
    }


def _load_google_build():
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Faltan las dependencias de Gmail API. "
            "Ejecuta: pip install -r requirements.txt"
        ) from exc

    return build


def _urlsafe_b64decode(value):
    raw = str(value or "").encode("ascii")

    padding = b"=" * (-len(raw) % 4)

    return base64.urlsafe_b64decode(
        raw + padding
    )


class GmailApiProvider(
    BaseEmailProvider
):
    def __init__(
        self,
        account,
        *,
        service=None,
        service_factory=None,
        interactive_auth=True,
    ):
        self.account = dict(account or {})
        self.config = _configuration(
            self.account
        )
        self._service = service
        self.service_factory = service_factory
        self.interactive_auth = bool(
            interactive_auth
        )

    def _open(self):
        if self._service is not None:
            return self._service

        credentials = (
            gmail_oauth_service
            .load_credentials(
                self.account,
                interactive=self.interactive_auth,
            )
        )

        if self.service_factory:
            self._service = self.service_factory(
                credentials
            )
        else:
            build = _load_google_build()

            self._service = build(
                "gmail",
                "v1",
                credentials=credentials,
                cache_discovery=False,
            )

        return self._service

    def test_connection(self):
        service = self._open()

        profile = (
            service.users()
            .getProfile(userId="me")
            .execute()
        )

        authenticated_email = str(
            profile.get("emailAddress")
            or ""
        ).strip().lower()

        configured_email = str(
            self.account.get("email_address")
            or ""
        ).strip().lower()

        if (
            authenticated_email
            and configured_email
            and authenticated_email
            != configured_email
        ):
            raise RuntimeError(
                "La cuenta autorizada en Google no coincide "
                "con la cuenta configurada en el CRM: "
                f"{authenticated_email} != {configured_email}"
            )

        return {
            "ok": True,
            "provider": "GMAIL_API",
            "account_email":
                authenticated_email
                or configured_email,
            "messages_total":
                int(
                    profile.get(
                        "messagesTotal"
                    )
                    or 0
                ),
            "history_id":
                str(
                    profile.get(
                        "historyId"
                    )
                    or ""
                ),
        }

    def _initial_after_millis(self):
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(
                days=self.config[
                    "initial_lookback_days"
                ]
            )
        )

        return int(
            cutoff.timestamp() * 1000
        )

    def _cursor_millis(self):
        cursor = str(
            self.account.get(
                "last_sync_cursor"
            )
            or ""
        ).strip()

        if cursor.isdigit():
            return int(cursor)

        return self._initial_after_millis()

    def _build_query(self):
        senders = list(
            self.config.get(
                "sender_filters"
            )
            or []
        )

        cursor_millis = self._cursor_millis()

        # Solapamiento de un segundo:
        # evita perder mensajes con la misma marca temporal.
        after_seconds = max(
            0,
            (cursor_millis // 1000) - 1,
        )

        query = [
            f"after:{after_seconds}",
        ]

        if len(senders) == 1:
            query.append(
                f"from:{senders[0]}"
            )

        elif len(senders) > 1:
            sender_query = " ".join(
                f"from:{sender}"
                for sender in senders
            )

            query.append(
                "{" + sender_query + "}"
            )

        return " ".join(query)

    def _list_message_refs(self, service):
        message_refs = []
        page_token = None
        query = self._build_query()

        while True:
            request = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=self.config[
                        "max_results"
                    ],
                    pageToken=page_token,
                )
            )

            response = request.execute()

            message_refs.extend(
                response.get("messages")
                or []
            )

            page_token = response.get(
                "nextPageToken"
            )

            if not page_token:
                break

        unique = {}

        for item in message_refs:
            message_id = str(
                item.get("id")
                or ""
            ).strip()

            if message_id:
                unique[message_id] = item

        return list(unique.values())

    def _get_raw_message(
        self,
        service,
        message_id,
    ):
        response = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="raw",
            )
            .execute()
        )

        raw = response.get("raw")

        if not raw:
            raise RuntimeError(
                "Gmail no devolvió el contenido RAW "
                f"del mensaje {message_id}"
            )

        return {
            "raw_bytes":
                _urlsafe_b64decode(raw),
            "message_id":
                str(
                    response.get("id")
                    or message_id
                ),
            "thread_id":
                str(
                    response.get("threadId")
                    or ""
                ),
            "internal_date":
                int(
                    response.get(
                        "internalDate"
                    )
                    or 0
                ),
            "history_id":
                str(
                    response.get(
                        "historyId"
                    )
                    or ""
                ),
            "label_ids":
                list(
                    response.get("labelIds")
                    or []
                ),
        }

    def sync_incoming(self):
        account_id = int(
            self.account["id"]
        )

        processed = []
        errors = []

        try:
            service = self._open()

            refs = self._list_message_refs(
                service
            )

            downloaded = []

            for item in refs:
                message_id = str(
                    item.get("id")
                    or ""
                ).strip()

                if not message_id:
                    continue

                try:
                    downloaded.append(
                        self._get_raw_message(
                            service,
                            message_id,
                        )
                    )
                except Exception as exc:
                    errors.append(
                        {
                            "message_id":
                                message_id,
                            "error": str(exc),
                        }
                    )
                    break

            downloaded.sort(
                key=lambda item: (
                    int(
                        item.get(
                            "internal_date"
                        )
                        or 0
                    ),
                    item.get("message_id") or "",
                )
            )

            last_cursor = self._cursor_millis()

            if not errors:
                for item in downloaded:
                    message_id = item[
                        "message_id"
                    ]

                    try:
                        normalized = (
                            email_rfc822_parser
                            .parse_rfc822_message(
                                item["raw_bytes"],
                                provider="GMAIL_API",
                                account_email=(
                                    self.account[
                                        "email_address"
                                    ]
                                ),
                                provider_message_id=(
                                    message_id
                                ),
                                folder="INBOX",
                            )
                        )

                        normalized[
                            "provider_thread_id"
                        ] = item["thread_id"]

                        normalized[
                            "account_id"
                        ] = account_id

                        normalized[
                            "raw_metadata"
                        ].update(
                            {
                                "gmail_internal_date":
                                    item[
                                        "internal_date"
                                    ],
                                "gmail_history_id":
                                    item[
                                        "history_id"
                                    ],
                                "gmail_label_ids":
                                    item[
                                        "label_ids"
                                    ],
                            }
                        )

                        result = (
                            email_expedient_sync_service
                            .process_message(
                                normalized
                            )
                        )

                        processed.append(
                            {
                                "message_id":
                                    message_id,
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
                                "internal_date":
                                    item[
                                        "internal_date"
                                    ],
                            }
                        )

                        last_cursor = max(
                            last_cursor,
                            int(
                                item[
                                    "internal_date"
                                ]
                                or 0
                            ),
                        )

                        email_account_service.update_sync_success(
                            account_id,
                            cursor=last_cursor,
                        )

                        self.account[
                            "last_sync_cursor"
                        ] = str(last_cursor)

                    except Exception as exc:
                        errors.append(
                            {
                                "message_id":
                                    message_id,
                                "error": str(exc),
                            }
                        )

                        email_account_service.update_sync_error(
                            account_id,
                            (
                                f"Mensaje {message_id}: "
                                f"{exc}"
                            ),
                        )

                        break

            if not refs and not errors:
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
                "uids_found": len(refs),
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
