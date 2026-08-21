"""
Heartbeat local de la UI del ERP para ICP Plus.

Permite que el worker autónomo sepa si existe una UI autenticada
capaz de mostrar el AlertDialog T-60.

No usa SQLite.
No usa Flet.
No contiene datos de clientes.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import time


HEARTBEAT_PATH = (
    Path(tempfile.gettempdir())
    / "quesada_abogados_icpplus_ui_heartbeat.json"
)

DEFAULT_MAX_AGE_SECONDS = 5

HEARTBEAT_REPLACE_RETRIES = 8
HEARTBEAT_REPLACE_RETRY_SECONDS = 0.03


def _now():
    return datetime.now().astimezone()


def _ensure_datetime(value):
    if isinstance(
        value,
        datetime,
    ):
        result = value
    else:
        result = datetime.fromisoformat(
            str(value)
        )

    if result.tzinfo is None:
        result = result.replace(
            tzinfo=_now().tzinfo
        )

    return result


def mark_alive(
    instance_id,
    *,
    now=None,
):
    instance_id = str(
        instance_id
        or ""
    ).strip()

    if not instance_id:
        raise ValueError(
            "ICPPLUS_UI_INSTANCE_ID_REQUIRED"
        )

    now = _ensure_datetime(
        now
        or _now()
    )

    payload = {
        "instance_id":
            instance_id,

        "pid":
            os.getpid(),

        "updated_at":
            now.isoformat(),
    }

    HEARTBEAT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = HEARTBEAT_PATH.with_name(
        HEARTBEAT_PATH.name
        + f".{os.getpid()}.tmp"
    )

    last_error = None

    for attempt in range(
        HEARTBEAT_REPLACE_RETRIES
    ):
        temp_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        try:
            temp_path.replace(
                HEARTBEAT_PATH
            )

            last_error = None
            break

        except PermissionError as exc:
            last_error = exc

            if (
                attempt
                >= HEARTBEAT_REPLACE_RETRIES
                - 1
            ):
                break

            time.sleep(
                HEARTBEAT_REPLACE_RETRY_SECONDS
            )

    if last_error is not None:
        raise last_error

    return dict(
        payload
    )


def get_heartbeat():
    try:
        if not HEARTBEAT_PATH.exists():
            return None

        payload = json.loads(
            HEARTBEAT_PATH.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            payload,
            dict,
        ):
            return None

        return payload

    except Exception:
        return None


def is_alive(
    *,
    max_age_seconds=DEFAULT_MAX_AGE_SECONDS,
    now=None,
):
    heartbeat = get_heartbeat()

    if not heartbeat:
        return False

    updated_at = heartbeat.get(
        "updated_at"
    )

    if not updated_at:
        return False

    try:
        updated = _ensure_datetime(
            updated_at
        )

        now = _ensure_datetime(
            now
            or _now()
        )

        age_seconds = (
            now
            - updated
        ).total_seconds()

        return (
            age_seconds
            >= 0
            and age_seconds
            <= float(
                max_age_seconds
            )
        )

    except Exception:
        return False


def clear(
    instance_id,
):
    instance_id = str(
        instance_id
        or ""
    ).strip()

    current = get_heartbeat()

    if not current:
        return False

    # Una instancia antigua nunca borra el heartbeat
    # de otra instancia de ERP posterior.
    if (
        str(
            current.get(
                "instance_id"
            )
            or ""
        )
        != instance_id
    ):
        return False

    try:
        HEARTBEAT_PATH.unlink(
            missing_ok=True
        )
    except Exception:
        return False

    return True
