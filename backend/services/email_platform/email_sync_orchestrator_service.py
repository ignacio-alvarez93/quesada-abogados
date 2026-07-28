"""
Orquestación de sincronizaciones manuales de correo.

Responsabilidades:

- localizar cuentas de entrada activas por proveedor;
- ejecutar sincronizaciones incrementales;
- impedir ejecuciones concurrentes dentro del proceso;
- devolver un resumen estable para la interfaz;
- mantener compatibilidad con la API histórica de IONOS;
- no contener dependencias de Flet.
"""

import os
import threading

from backend.services.email_platform import (
    email_account_service,
)
from backend.services.email_platform.providers.gmail_api_provider import (
    GmailApiProvider,
)
from backend.services.email_platform.providers.ionos_imap_provider import (
    IonosImapProvider,
)


PROVIDER_IONOS = "IONOS_IMAP"
PROVIDER_GMAIL = "GMAIL_API"

_PROVIDER_CONFIG = {
    PROVIDER_IONOS: {
        "label": "IONOS",
        "email_env":
            "QUESADA_IONOS_ACCOUNT_EMAIL",
        "provider_class":
            IonosImapProvider,
    },
    PROVIDER_GMAIL: {
        "label": "Gmail",
        "email_env":
            "QUESADA_GMAIL_ACCOUNT_EMAIL",
        "provider_class":
            GmailApiProvider,
    },
}

_SYNC_LOCK = threading.Lock()


def _text(value):
    return str(value or "").strip()


def _normalize_email(value):
    return _text(value).lower()


def _normalize_provider(value):
    provider = _text(value).upper()

    if provider not in _PROVIDER_CONFIG:
        raise ValueError(
            "Proveedor de correo no soportado: "
            f"{provider or '(vacío)'}"
        )

    return provider


def _provider_label(provider):
    provider = _normalize_provider(provider)

    return _PROVIDER_CONFIG[
        provider
    ]["label"]


def _load_configured_account(
    provider,
    *,
    account_email=None,
):
    provider = _normalize_provider(
        provider
    )

    config = _PROVIDER_CONFIG[
        provider
    ]

    requested_email = _normalize_email(
        account_email
        or os.getenv(
            config["email_env"],
            "",
        )
    )

    accounts = (
        email_account_service
        .get_active_incoming_accounts(
            provider=provider
        )
    )

    label = config["label"]

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
            f"No existe una cuenta {label} "
            f"activa para {requested_email}."
        )

    if len(accounts) == 1:
        return accounts[0]

    if not accounts:
        raise RuntimeError(
            f"No existe ninguna cuenta {label} "
            "activa configurada en el CRM."
        )

    raise RuntimeError(
        f"Hay varias cuentas {label} activas. "
        f"Define {config['email_env']}."
    )


def get_provider_status(
    provider,
    *,
    account_email=None,
):
    """
    Devuelve el estado persistido sin conectarse
    al proveedor.
    """
    provider = _normalize_provider(
        provider
    )

    account = _load_configured_account(
        provider,
        account_email=account_email,
    )

    return {
        "account_id": int(account["id"]),
        "account_email":
            account.get("email_address") or "",
        "provider":
            account.get("provider") or provider,
        "provider_label":
            _provider_label(provider),
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


def get_ionos_status(
    *,
    account_email=None,
):
    return get_provider_status(
        PROVIDER_IONOS,
        account_email=account_email,
    )


def get_gmail_status(
    *,
    account_email=None,
):
    return get_provider_status(
        PROVIDER_GMAIL,
        account_email=account_email,
    )


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


def _build_provider(
    provider,
    account,
    *,
    provider_factory=None,
):
    if provider_factory:
        return provider_factory(account)

    provider_class = _PROVIDER_CONFIG[
        provider
    ]["provider_class"]

    if provider == PROVIDER_GMAIL:
        return provider_class(
            account,
            interactive_auth=False,
        )

    return provider_class(account)


def _busy_result(provider):
    label = _provider_label(provider)

    return {
        "ok": False,
        "busy": True,
        "provider": provider,
        "provider_label": label,
        "message":
            "Ya hay una revisión de correo "
            "en curso.",
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


def sync_provider_extranjeria(
    provider,
    *,
    account_email=None,
    provider_factory=None,
):
    """
    Ejecuta una revisión incremental manual
    del proveedor indicado.
    """
    provider = _normalize_provider(
        provider
    )

    acquired = _SYNC_LOCK.acquire(
        blocking=False
    )

    if not acquired:
        return _busy_result(provider)

    try:
        account = _load_configured_account(
            provider,
            account_email=account_email,
        )

        email_provider = _build_provider(
            provider,
            account,
            provider_factory=provider_factory,
        )

        result = (
            email_provider.sync_incoming()
        )

        summary = _summarize_provider_result(
            result
        )

        summary.update(
            {
                "busy": False,
                "provider": provider,
                "provider_label":
                    _provider_label(provider),
            }
        )

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


def sync_ionos_extranjeria(
    *,
    account_email=None,
    provider_factory=None,
):
    return sync_provider_extranjeria(
        PROVIDER_IONOS,
        account_email=account_email,
        provider_factory=provider_factory,
    )


def sync_gmail_extranjeria(
    *,
    account_email=None,
    provider_factory=None,
):
    return sync_provider_extranjeria(
        PROVIDER_GMAIL,
        account_email=account_email,
        provider_factory=provider_factory,
    )
