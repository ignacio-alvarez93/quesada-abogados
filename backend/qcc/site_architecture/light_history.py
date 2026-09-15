"""Histórico ligero de observaciones QCC Site Architecture.

Conserva exclusivamente identidad funcional y fingerprints.

No persiste:
- DOM
- HTML
- MHTML
- screenshots
- geometría
- valores de formularios
- payloads del navegador

El histórico es independiente del ring de evidencia pesada.

"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit


QCC_ARCHITECTURE_LIGHT_HISTORY_SCHEMA_VERSION = 1

QCC_ARCHITECTURE_LIGHT_HISTORY_TYPE = (
    "QCC_ARCHITECTURE_LIGHT_HISTORY"
)

_HISTORY_LOCK = threading.RLock()


def _normalized_origin(
    value,
):
    parsed = urlsplit(
        str(
            value
            or ""
        ).strip()
    )

    scheme = (
        parsed.scheme
        or ""
    ).lower()

    host = (
        parsed.hostname
        or ""
    ).lower()

    if (
        scheme not in {
            "http",
            "https",
        }
        or not host
    ):
        return None

    try:
        port = parsed.port
    except ValueError:
        return None

    if ":" in host:
        host = f"[{host}]"

    default_port = (
        80
        if scheme == "http"
        else 443
    )

    suffix = (
        ""
        if (
            port is None
            or port == default_port
        )
        else f":{port}"
    )

    return (
        f"{scheme}://"
        f"{host}"
        f"{suffix}"
    )


def _normalized_code(
    value,
    *,
    fallback=None,
):
    normalized = str(
        value
        or ""
    ).strip().upper()

    return (
        normalized
        or fallback
    )


class QccArchitectureLightHistory:
    """Memoria cronológica PII-safe de fingerprints funcionales."""

    def __init__(
        self,
        *,
        root,
    ):
        self._root = Path(
            root
        )

    @property
    def root(
        self,
    ):
        return self._root

    @staticmethod
    def _identity(
        *,
        browser_profile_key,
        origin,
        architecture_scope,
        functional_state,
    ):
        profile_key = str(
            browser_profile_key
            or ""
        ).strip()

        normalized_origin = (
            _normalized_origin(
                origin
            )
        )

        normalized_scope = (
            _normalized_code(
                architecture_scope,
                fallback="GENERAL",
            )
        )

        normalized_state = (
            _normalized_code(
                functional_state
            )
        )

        if (
            not profile_key
            or not normalized_origin
            or not normalized_scope
        ):
            return None

        return {
            "browser_profile_key":
                profile_key,

            "origin":
                normalized_origin,

            "architecture_scope":
                normalized_scope,

            "functional_state":
                normalized_state,
        }

    @staticmethod
    def _identity_digest(
        identity,
    ):
        canonical = json.dumps(
            identity,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            canonical.encode(
                "utf-8"
            )
        ).hexdigest()

    def _history_path(
        self,
        identity,
    ):
        return (
            self._root
            / (
                self._identity_digest(
                    identity
                )
                + ".jsonl"
            )
        )

    @staticmethod
    def _last_observation(
        path,
    ):
        if not path.is_file():
            return None

        try:
            lines = (
                path.read_text(
                    encoding="utf-8"
                )
                .splitlines()
            )
        except OSError:
            return None

        for raw_line in reversed(
            lines
        ):
            raw_line = (
                raw_line.strip()
            )

            if not raw_line:
                continue

            try:
                candidate = json.loads(
                    raw_line
                )
            except (
                ValueError,
                TypeError,
            ):
                continue

            if isinstance(
                candidate,
                dict,
            ):
                return candidate

        return None

    def append(
        self,
        *,
        capture_id,
        observed_at,
        browser_profile_key,
        origin,
        site_code,
        architecture_scope,
        functional_state,
        fingerprint,
    ):
        capture_id = str(
            capture_id
            or ""
        ).strip()

        fingerprint = str(
            fingerprint
            or ""
        ).strip()

        if (
            not capture_id
            or not fingerprint
        ):
            return None

        identity = self._identity(
            browser_profile_key=
                browser_profile_key,

            origin=
                origin,

            architecture_scope=
                architecture_scope,

            functional_state=
                functional_state,
        )

        if identity is None:
            return None

        history_path = (
            self._history_path(
                identity
            )
        )

        with _HISTORY_LOCK:
            previous = (
                self._last_observation(
                    history_path
                )
            )

            previous_fingerprint = (
                str(
                    (
                        previous
                        or {}
                    ).get(
                        "fingerprint"
                    )
                    or ""
                ).strip()
                or None
            )

            changed = (
                None
                if previous_fingerprint
                is None
                else (
                    previous_fingerprint
                    != fingerprint
                )
            )

            observation = {
                "schema_version":
                    QCC_ARCHITECTURE_LIGHT_HISTORY_SCHEMA_VERSION,

                "observation_type":
                    QCC_ARCHITECTURE_LIGHT_HISTORY_TYPE,

                "observed_at":
                    str(
                        observed_at
                        or ""
                    ).strip()
                    or None,

                "capture_id":
                    capture_id,

                **identity,

                "site_code":
                    (
                        _normalized_code(
                            site_code
                        )
                    ),

                "fingerprint":
                    fingerprint,

                "previous_fingerprint":
                    previous_fingerprint,

                "changed":
                    changed,
            }

            self._root.mkdir(
                parents=True,
                exist_ok=True,
            )

            with history_path.open(
                "a",
                encoding="utf-8",
                newline="\n",
            ) as stream:
                stream.write(
                    json.dumps(
                        observation,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )

                stream.write(
                    "\n"
                )

            return observation
