"""
Cliente mínimo para Telegram Bot API.

No conoce tareas ni avisos.
Solo transporta texto.

Configuración esperada:

TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


TELEGRAM_API_BASE = (
    "https://api.telegram.org"
)


class TelegramConfigurationError(
    RuntimeError
):
    pass


class TelegramDeliveryError(
    RuntimeError
):
    pass


def get_configuration():
    token = str(
        os.getenv(
            "TELEGRAM_BOT_TOKEN",
            "",
        )
    ).strip()

    chat_id = str(
        os.getenv(
            "TELEGRAM_CHAT_ID",
            "",
        )
    ).strip()

    if not token:
        raise TelegramConfigurationError(
            "TELEGRAM_BOT_TOKEN no configurado."
        )

    if not chat_id:
        raise TelegramConfigurationError(
            "TELEGRAM_CHAT_ID no configurado."
        )

    return {
        "token": token,
        "chat_id": chat_id,
    }


def is_configured():
    try:
        get_configuration()
    except TelegramConfigurationError:
        return False

    return True


def send_message(
    text,
    *,
    token=None,
    chat_id=None,
    timeout=15,
):
    clean_text = str(
        text or ""
    ).strip()

    if not clean_text:
        raise ValueError(
            "El mensaje no puede estar vacío."
        )

    if token is None or chat_id is None:
        config = get_configuration()

        token = (
            token
            or config["token"]
        )

        chat_id = (
            chat_id
            or config["chat_id"]
        )

    token = str(token).strip()
    chat_id = str(chat_id).strip()

    if not token:
        raise TelegramConfigurationError(
            "Token Telegram vacío."
        )

    if not chat_id:
        raise TelegramConfigurationError(
            "Chat ID Telegram vacío."
        )

    endpoint = (
        f"{TELEGRAM_API_BASE}/"
        f"bot{token}/sendMessage"
    )

    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": clean_text,
        }
    ).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Content-Type":
                "application/"
                "x-www-form-urlencoded",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            raw = response.read().decode(
                "utf-8"
            )

    except urllib.error.HTTPError as exc:
        detail = ""

        try:
            detail = (
                exc.read()
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )
        except Exception:
            detail = ""

        raise TelegramDeliveryError(
            "Telegram HTTP "
            f"{exc.code}: "
            f"{detail or exc.reason}"
        ) from exc

    except urllib.error.URLError as exc:
        raise TelegramDeliveryError(
            "No se pudo conectar con Telegram: "
            f"{exc.reason}"
        ) from exc

    try:
        data = json.loads(raw)

    except json.JSONDecodeError as exc:
        raise TelegramDeliveryError(
            "Telegram devolvió una "
            "respuesta no JSON."
        ) from exc

    if not data.get("ok"):
        raise TelegramDeliveryError(
            "Telegram rechazó el mensaje: "
            f"{data}"
        )

    return data
