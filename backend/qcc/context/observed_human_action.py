"""Evidencia efímera de una acción humana observada en el DOM.

No es un permiso de ejecución.
No es un QccActionRequest.
No forma parte del snapshot público de QCC.

Su único propósito es permitir correlacionar de forma
explícita:

    observation A
    + human action event
    + observation B

antes de aprender una transición.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
)
from datetime import (
    datetime,
    timezone,
)

from backend.qcc.context.navigation_context import (
    normalize_navigation_context,
)


QCC_OBSERVED_HUMAN_ACTION_SOURCE = (
    "TRUSTED_DOM_HUMAN_ACTION"
)

QCC_OBSERVED_HUMAN_ACTION_TTL_SECONDS = (
    30.0
)


def _required_text(
    value,
    error,
):
    normalized = str(
        value
        or ""
    ).strip()

    if not normalized:
        raise ValueError(
            error
        )

    return normalized


def _upper(
    value,
    error,
):
    return _required_text(
        value,
        error,
    ).upper()


def _fingerprint(
    value,
):
    normalized = _required_text(
        value,
        "QCC_OBSERVED_HUMAN_ACTION_FINGERPRINT_REQUIRED",
    ).lower()

    if (
        len(normalized) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character in normalized
        )
    ):
        raise ValueError(
            "QCC_OBSERVED_HUMAN_ACTION_FINGERPRINT_INVALID"
        )

    return normalized


@dataclass(
    frozen=True,
    slots=True,
)
class QccObservedHumanAction:
    """Identidad funcional de un clic/acción humana observada."""

    event_id: str
    session_id: str
    site_code: str
    environment: str

    before_state: str | None
    before_fingerprint: str

    kind: str
    policy: str
    selector: str
    frame_path: str

    observed_at: datetime
    navigation_context: tuple[dict, ...] = ()

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "navigation_context",
            normalize_navigation_context(
                self.navigation_context
            ),
        )

        event_id = _required_text(
            self.event_id,
            "QCC_OBSERVED_HUMAN_ACTION_EVENT_ID_REQUIRED",
        )

        if len(event_id) > 128:
            raise ValueError(
                "QCC_OBSERVED_HUMAN_ACTION_EVENT_ID_INVALID"
            )

        session_id = _required_text(
            self.session_id,
            "QCC_OBSERVED_HUMAN_ACTION_SESSION_ID_REQUIRED",
        )

        site_code = _upper(
            self.site_code,
            "QCC_OBSERVED_HUMAN_ACTION_SITE_REQUIRED",
        )

        environment = _upper(
            self.environment,
            "QCC_OBSERVED_HUMAN_ACTION_ENVIRONMENT_REQUIRED",
        )

        kind = _upper(
            self.kind,
            "QCC_OBSERVED_HUMAN_ACTION_KIND_REQUIRED",
        )

        policy = _upper(
            self.policy,
            "QCC_OBSERVED_HUMAN_ACTION_POLICY_REQUIRED",
        )

        selector = _required_text(
            self.selector,
            "QCC_OBSERVED_HUMAN_ACTION_SELECTOR_REQUIRED",
        )

        frame_path = str(
            self.frame_path
            or "main"
        ).strip() or "main"

        before_state = (
            None
            if self.before_state is None
            else (
                str(
                    self.before_state
                ).strip().upper()
                or None
            )
        )

        before_fingerprint = (
            _fingerprint(
                self.before_fingerprint
            )
        )

        observed_at = self.observed_at

        if not isinstance(
            observed_at,
            datetime,
        ):
            raise ValueError(
                "QCC_OBSERVED_HUMAN_ACTION_TIME_INVALID"
            )

        if (
            observed_at.tzinfo
            is None
            or observed_at.utcoffset()
            is None
        ):
            raise ValueError(
                "QCC_OBSERVED_HUMAN_ACTION_TIME_TZ_REQUIRED"
            )

        observed_at = (
            observed_at
            .astimezone(
                timezone.utc
            )
        )

        object.__setattr__(
            self,
            "event_id",
            event_id,
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
            "environment",
            environment,
        )

        object.__setattr__(
            self,
            "before_state",
            before_state,
        )

        object.__setattr__(
            self,
            "before_fingerprint",
            before_fingerprint,
        )

        object.__setattr__(
            self,
            "kind",
            kind,
        )

        object.__setattr__(
            self,
            "policy",
            policy,
        )

        object.__setattr__(
            self,
            "selector",
            selector,
        )

        object.__setattr__(
            self,
            "frame_path",
            frame_path,
        )

        object.__setattr__(
            self,
            "observed_at",
            observed_at,
        )

    @property
    def source(
        self,
    ) -> str:
        return (
            QCC_OBSERVED_HUMAN_ACTION_SOURCE
        )

    def is_fresh(
        self,
        *,
        now: datetime | None = None,
        ttl_seconds: float = (
            QCC_OBSERVED_HUMAN_ACTION_TTL_SECONDS
        ),
    ) -> bool:
        if ttl_seconds <= 0:
            return False

        reference = (
            datetime.now(
                timezone.utc
            )
            if now is None
            else now
        )

        if not isinstance(
            reference,
            datetime,
        ):
            raise ValueError(
                "QCC_OBSERVED_HUMAN_ACTION_NOW_INVALID"
            )

        if (
            reference.tzinfo is None
            or reference.utcoffset()
            is None
        ):
            raise ValueError(
                "QCC_OBSERVED_HUMAN_ACTION_NOW_TZ_REQUIRED"
            )

        reference = (
            reference.astimezone(
                timezone.utc
            )
        )

        age = (
            reference
            - self.observed_at
        ).total_seconds()

        return (
            0.0
            <= age
            <= float(
                ttl_seconds
            )
        )

    def transition_action(
        self,
    ) -> dict[str, str]:
        """Identidad exacta aceptada por state_transition."""

        return {
            "kind":
                self.kind,

            "policy":
                self.policy,

            "selector":
                self.selector,

            "frame_path":
                self.frame_path,
        }
