"""Objetivo duradero de navegación para una sesión QCC.

El intent pertenece a la sesión, no al DOM.

Una nueva captura puede invalidar:
- route;
- next_step;
- governance.

Pero no debe borrar el objetivo solicitado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
import re


QCC_NAVIGATION_INTENT_SCHEMA_VERSION = 1
QCC_NAVIGATION_INTENT_TYPE = (
    "QCC_NAVIGATION_INTENT"
)


_CODE_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_.:/-]{0,127}$"
)


def _required_code(
    value,
    *,
    error,
):
    normalized = str(
        value
        or ""
    ).strip().upper()

    if not _CODE_PATTERN.fullmatch(
        normalized
    ):
        raise ValueError(
            error
        )

    return normalized


def _optional_state(
    value,
):
    if value is None:
        return None

    normalized = str(
        getattr(
            value,
            "value",
            value,
        )
        or ""
    ).strip().upper()

    if not normalized:
        return None

    if not _CODE_PATTERN.fullmatch(
        normalized
    ):
        raise ValueError(
            "QCC_NAVIGATION_INTENT_TARGET_STATE_INVALID"
        )

    return normalized


def _optional_fingerprint(
    value,
):
    if value is None:
        return None

    normalized = str(
        value
        or ""
    ).strip().lower()

    if not normalized:
        return None

    if (
        len(normalized) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character
            in normalized
        )
    ):
        raise ValueError(
            "QCC_NAVIGATION_INTENT_TARGET_FINGERPRINT_INVALID"
        )

    return normalized


@dataclass(
    frozen=True,
    slots=True,
)
class QccNavigationIntent:
    """Objetivo explícito asociado a una sesión."""

    session_id: str
    site_code: str

    target_state: str | None = None
    target_fingerprint: str | None = None

    requested_at: datetime | None = None

    def __post_init__(
        self,
    ):
        session_id = str(
            self.session_id
            or ""
        ).strip()

        if not session_id:
            raise ValueError(
                "QCC_NAVIGATION_INTENT_SESSION_ID_REQUIRED"
            )

        site_code = (
            _required_code(
                self.site_code,
                error=(
                    "QCC_NAVIGATION_INTENT_SITE_CODE_INVALID"
                ),
            )
        )

        target_state = (
            _optional_state(
                self.target_state
            )
        )

        target_fingerprint = (
            _optional_fingerprint(
                self.target_fingerprint
            )
        )

        if (
            target_state is None
            and target_fingerprint is None
        ):
            raise ValueError(
                "QCC_NAVIGATION_INTENT_TARGET_REQUIRED"
            )

        requested_at = (
            self.requested_at
        )

        if requested_at is None:
            requested_at = (
                datetime.now(
                    timezone.utc
                )
            )

        if not isinstance(
            requested_at,
            datetime,
        ):
            raise ValueError(
                "QCC_NAVIGATION_INTENT_REQUESTED_AT_INVALID"
            )

        if requested_at.tzinfo is None:
            requested_at = (
                requested_at.replace(
                    tzinfo=timezone.utc
                )
            )

        object.__setattr__(
            self,
            "session_id",
            session_id,
        )

        object.__setattr__(
            self,
            "site_code",
            site_code,
        )

        object.__setattr__(
            self,
            "target_state",
            target_state,
        )

        object.__setattr__(
            self,
            "target_fingerprint",
            target_fingerprint,
        )

        object.__setattr__(
            self,
            "requested_at",
            requested_at,
        )

    @classmethod
    def from_payload(
        cls,
        payload,
    ):
        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_NAVIGATION_INTENT_PAYLOAD_INVALID"
            )

        allowed = {
            "schema_version",
            "intent_type",
            "session_id",
            "site_code",
            "target",
            "requested_at",
        }

        unexpected = (
            set(payload)
            - allowed
        )

        if unexpected:
            key = sorted(
                str(item)
                for item in unexpected
            )[0]

            raise ValueError(
                "QCC_NAVIGATION_INTENT_FIELD_NOT_ALLOWED:"
                + key
            )

        if (
            payload.get(
                "schema_version"
            )
            != QCC_NAVIGATION_INTENT_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_NAVIGATION_INTENT_SCHEMA_INVALID"
            )

        if (
            payload.get(
                "intent_type"
            )
            != QCC_NAVIGATION_INTENT_TYPE
        ):
            raise ValueError(
                "QCC_NAVIGATION_INTENT_TYPE_INVALID"
            )

        target = payload.get(
            "target"
        )

        if not isinstance(
            target,
            dict,
        ):
            raise ValueError(
                "QCC_NAVIGATION_INTENT_TARGET_INVALID"
            )

        unexpected_target = (
            set(target)
            - {
                "state",
                "fingerprint",
            }
        )

        if unexpected_target:
            key = sorted(
                str(item)
                for item in unexpected_target
            )[0]

            raise ValueError(
                "QCC_NAVIGATION_INTENT_FIELD_NOT_ALLOWED:"
                "target."
                + key
            )

        requested_at = payload.get(
            "requested_at"
        )

        if requested_at is not None:
            raw = str(
                requested_at
            ).strip()

            if raw.endswith(
                "Z"
            ):
                raw = (
                    raw[:-1]
                    + "+00:00"
                )

            try:
                requested_at = (
                    datetime.fromisoformat(
                        raw
                    )
                )

            except ValueError as exc:
                raise ValueError(
                    "QCC_NAVIGATION_INTENT_REQUESTED_AT_INVALID"
                ) from exc

        return cls(
            session_id=str(
                payload.get(
                    "session_id",
                    "",
                )
            ),

            site_code=str(
                payload.get(
                    "site_code",
                    "",
                )
            ),

            target_state=(
                target.get(
                    "state"
                )
            ),

            target_fingerprint=(
                target.get(
                    "fingerprint"
                )
            ),

            requested_at=(
                requested_at
            ),
        )

    def to_payload(
        self,
    ):
        return {
            "schema_version":
                QCC_NAVIGATION_INTENT_SCHEMA_VERSION,

            "intent_type":
                QCC_NAVIGATION_INTENT_TYPE,

            "session_id":
                self.session_id,

            "site_code":
                self.site_code,

            "target": {
                "state":
                    self.target_state,

                "fingerprint":
                    self.target_fingerprint,
            },

            "requested_at":
                self.requested_at.isoformat(),
        }
