"""
Orquestación de sincronizaciones manuales de correo.

Responsabilidades:

- localizar la cuenta IONOS activa;
- ejecutar una única sincronización incremental;
- impedir ejecuciones concurrentes dentro del proceso;
- devolver un resumen estable y apto para la interfaz;
- no contener dependencias de Flet.
"""

import os
import threading

from backend.services.email_platform import (
    email_account_service,
)
from backend.services.email_platform.providers.ionos_imap_provider import (
    IonosImapProvider,
)


_PROVIDER = "IONOS_IMAP"
_DEFAULT_CREDENTIAL_KEY = "QUESADA_IONOS"

_SYNC_LOCK = threading.Lock()


def _text(value):
    return str(value or "").strip()


def _normalize_email(value):
    return _text(value).lower()


def _load_configured_account(
    *,
    account_email=None,
):
    requested_email = _normalize_email(
        account_email
        or os.getenv(
            "QUESADA_IONOS_ACCOUNT_EMAIL",
            "",
        )
    )

    accounts = (
        email_account_service
        .get_active_incoming_accounts(
            provider=_PROVIDER
        )
    )

    if requested_email:
        account = next(
            (
                item
                for item in accounts
                if _normalize_email(
                    item.get("email_address")
                ) == requested_email
            ),
            None,
        )

        if account:
            return account

        raise RuntimeError(
            "No existe una cuenta IONOS activa "
            f"para {requested_email}."
        )

    if len(accounts) == 1:
        return accounts[0]

    if not accounts:
        raise RuntimeError(
            "No existe ninguna cuenta IONOS activa "
            "configurada en el CRM."
        )

    raise RuntimeError(
        "Hay varias cuentas IONOS activas. "
        "Define QUESADA_IONOS_ACCOUNT_EMAIL."
    )


def get_ionos_status(
    *,
    account_email=None,
):
    """
    Devuelve el estado persistido de la cuenta sin conectarse a IONOS.
    """
    account = _load_configured_account(
        account_email=account_email
    )

    return {
        "account_id": int(account["id"]),
        "account_email":
            account.get("email_address") or "",
        "provider":
            account.get("provider") or "",
        "last_sync_cursor":
            account.get("last_sync_cursor") or "",
        "last_sync_at":
            account.get("last_sync_at") or "",
        "last_sync_status":
            account.get("last_sync_status") or "",
        "last_sync_error":
            account.get("last_sync_error") or "",
        "incoming_enabled":
            bool(
                int(
                    account.get(
                        "incoming_enabled"
                    )
                    or 0
                )
            ),
    }


def _summarize_provider_result(
    result,
):
    processed_rows = list(
        result.get("processed") or []
    )
    errors = list(
        result.get("errors") or []
    )

    applied = 0
    review_required = 0
    ignored = 0
    other = 0
    expedient_ids = []

    for row in processed_rows:
        status = _text(
            row.get("status")
        ).upper()

        if status in (
            "PROCESSED",
            "APPLIED",
        ):
            applied += 1

            expediente_id = row.get(
                "expediente_id"
            )

            if expediente_id:
                expedient_ids.append(
                    int(expediente_id)
                )

        elif status == "REVIEW_REQUIRED":
            review_required += 1

        elif status == "IGNORED":
            ignored += 1

        else:
            other += 1

    return {
        "ok": bool(result.get("ok")),
        "account_id":
            result.get("account_id"),
        "account_email":
            result.get("account_email") or "",
        "uids_found":
            int(result.get("uids_found") or 0),
        "processed_count":
            len(processed_rows),
        "applied_count": applied,
        "review_required_count":
            review_required,
        "ignored_count": ignored,
        "other_count": other,
        "error_count": len(errors),
        "errors": errors,
        "expedient_ids":
            sorted(set(expedient_ids)),
        "last_cursor":
            result.get("last_cursor") or "",
        "processed": processed_rows,
    }


def sync_ionos_extranjeria(
    *,
    account_email=None,
    provider_factory=None,
):
    """
    Ejecuta una revisión incremental manual de IONOS.

    Devuelve busy=True cuando otra revisión ya está ejecutándose.
    """
    acquired = _SYNC_LOCK.acquire(
        blocking=False
    )

    if not acquired:
        return {
            "ok": False,
            "busy": True,
            "message":
                "Ya hay una revisión de correo "
                "IONOS en curso.",
            "uids_found": 0,
            "processed_count": 0,
            "applied_count": 0,
            "review_required_count": 0,
            "ignored_count": 0,
            "other_count": 0,
            "error_count": 0,
            "errors": [],
            "expedient_ids": [],
        }

    try:
        account = _load_configured_account(
            account_email=account_email
        )

        provider_class = (
            provider_factory
            or IonosImapProvider
        )

        provider = provider_class(account)
        result = provider.sync_incoming()

        summary = _summarize_provider_result(
            result
        )
        summary["busy"] = False

        if summary["error_count"]:
            summary["message"] = (
                "La revisión terminó con errores."
            )
        elif not summary["uids_found"]:
            summary["message"] = (
                "No hay mensajes nuevos."
            )
        elif summary["applied_count"]:
            summary["message"] = (
                "Revisión completada con "
                f"{summary['applied_count']} "
                "expediente(s) actualizado(s)."
            )
        elif summary[
            "review_required_count"
        ]:
            summary["message"] = (
                "Hay mensajes pendientes "
                "de revisión."
            )
        else:
            summary["message"] = (
                "Revisión completada."
            )

        return summary

    finally:
        _SYNC_LOCK.release()
