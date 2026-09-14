"""Evidencia efímera del inventario canónico de acciones de CURRENT.

La evidencia procede del backend después de normalizar
una captura Site Architecture.

No concede permisos.
No se publica por /qcc/context.
No contiene valores de formulario ni texto DOM.

Sirve únicamente como autoridad para canonicalizar
posteriormente una señal humana:

    capture A
    + canonical live_actions A
    + human DOM signal
"""

from __future__ import annotations

from backend.qcc.context.navigation_context import (
    normalize_navigation_context,
)


from dataclasses import (
    dataclass,
)
from datetime import (
    datetime,
    timezone,
)
from uuid import (
    uuid4,
)
from typing import (
    Mapping,
)


# Human discovery window.
#
# This governs how long canonical action evidence for CURRENT A
# may wait for a physical human interaction.
#
# It is deliberately longer than the post-click causal window:
# - A -> human click: up to 30 minutes
# - human click -> B: remains short (30 seconds)
QCC_LIVE_ACTION_EVIDENCE_TTL_SECONDS = (
    30.0 * 60.0
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
        "QCC_LIVE_ACTION_EVIDENCE_FINGERPRINT_REQUIRED",
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
            "QCC_LIVE_ACTION_EVIDENCE_FINGERPRINT_INVALID"
        )

    return normalized


def _optional_bool(
    value,
):
    if value is None:
        return None

    if isinstance(
        value,
        bool,
    ):
        return value

    raise ValueError(
        "QCC_LIVE_ACTION_EVIDENCE_BOOLEAN_INVALID"
    )


def _optional_float(
    value,
):
    if value is None:
        return None

    try:
        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "QCC_LIVE_ACTION_EVIDENCE_FLOAT_INVALID"
        ) from exc


@dataclass(
    frozen=True,
    slots=True,
)
class QccCanonicalLiveAction:
    """Acción canónica producida por backend Site Architecture."""

    kind: str
    policy: str
    selector: str
    frame_path: str = "main"

    visible: bool | None = None
    disabled: bool | None = None
    in_viewport: bool | None = None
    opacity: float | None = None
    pointer_events: str | None = None

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "kind",
            _upper(
                self.kind,
                "QCC_LIVE_ACTION_EVIDENCE_KIND_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "policy",
            _upper(
                self.policy,
                "QCC_LIVE_ACTION_EVIDENCE_POLICY_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "selector",
            _required_text(
                self.selector,
                "QCC_LIVE_ACTION_EVIDENCE_SELECTOR_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "frame_path",
            (
                str(
                    self.frame_path
                    or "main"
                ).strip()
                or "main"
            ),
        )

        object.__setattr__(
            self,
            "visible",
            _optional_bool(
                self.visible
            ),
        )

        object.__setattr__(
            self,
            "disabled",
            _optional_bool(
                self.disabled
            ),
        )

        object.__setattr__(
            self,
            "in_viewport",
            _optional_bool(
                self.in_viewport
            ),
        )

        object.__setattr__(
            self,
            "opacity",
            _optional_float(
                self.opacity
            ),
        )

        pointer_events = (
            None
            if self.pointer_events is None
            else (
                str(
                    self.pointer_events
                ).strip()
                or None
            )
        )

        object.__setattr__(
            self,
            "pointer_events",
            pointer_events,
        )

    @classmethod
    def from_action(
        cls,
        action,
    ):
        if isinstance(
            action,
            cls,
        ):
            return action

        if not isinstance(
            action,
            Mapping,
        ):
            raise TypeError(
                "QCC_LIVE_ACTION_EVIDENCE_ACTION_INVALID"
            )

        return cls(
            kind=action.get(
                "kind"
            ),
            policy=action.get(
                "policy"
            ),
            selector=action.get(
                "selector"
            ),
            frame_path=action.get(
                "frame_path"
            )
            or "main",
            visible=action.get(
                "visible"
            ),
            disabled=action.get(
                "disabled"
            ),
            in_viewport=action.get(
                "in_viewport"
            ),
            opacity=action.get(
                "opacity"
            ),
            pointer_events=action.get(
                "pointer_events"
            ),
        )

    def identity(
        self,
    ) -> tuple[
        str,
        str,
        str,
        str,
    ]:
        return (
            self.kind,
            self.policy,
            self.selector,
            self.frame_path,
        )


@dataclass(
    frozen=True,
    slots=True,
)
class QccLiveActionEvidence:
    """Inventario canónico ligado a un CURRENT exacto."""

    session_id: str
    site_code: str
    environment: str

    before_state: str | None
    before_fingerprint: str

    actions: tuple[
        QccCanonicalLiveAction,
        ...,
    ]

    captured_at: datetime

    # Opaque backend-generated handle for the exact snapshot A.
    #
    # Chrome transports it but never derives semantic authority
    # from it.
    evidence_id: str | None = None
    navigation_context: object = ()

    def __post_init__(
        self,
    ) -> None:
        session_id = _required_text(
            self.session_id,
            "QCC_LIVE_ACTION_EVIDENCE_SESSION_ID_REQUIRED",
        )

        site_code = _upper(
            self.site_code,
            "QCC_LIVE_ACTION_EVIDENCE_SITE_REQUIRED",
        )

        environment = _upper(
            self.environment,
            "QCC_LIVE_ACTION_EVIDENCE_ENVIRONMENT_REQUIRED",
        )

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

        fingerprint = _fingerprint(
            self.before_fingerprint
        )

        if not isinstance(
            self.actions,
            (
                tuple,
                list,
            ),
        ):
            raise TypeError(
                "QCC_LIVE_ACTION_EVIDENCE_ACTIONS_INVALID"
            )

        actions = tuple(
            QccCanonicalLiveAction
            .from_action(
                action
            )
            for action
            in self.actions
        )

        captured_at = (
            self.captured_at
        )

        if not isinstance(
            captured_at,
            datetime,
        ):
            raise ValueError(
                "QCC_LIVE_ACTION_EVIDENCE_TIME_INVALID"
            )

        if (
            captured_at.tzinfo
            is None
            or captured_at.utcoffset()
            is None
        ):
            raise ValueError(
                "QCC_LIVE_ACTION_EVIDENCE_TIME_TZ_REQUIRED"
            )

        captured_at = (
            captured_at.astimezone(
                timezone.utc
            )
        )

        evidence_id = (
            str(
                self.evidence_id
                or ""
            ).strip()
            or uuid4().hex
        )

        if len(evidence_id) > 128:
            raise ValueError(
                "QCC_LIVE_ACTION_EVIDENCE_ID_INVALID"
            )

        object.__setattr__(
            self,
            "evidence_id",
            evidence_id,
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
            fingerprint,
        )

        object.__setattr__(
            self,
            "actions",
            actions,
        )

        object.__setattr__(
            self,
            "captured_at",
            captured_at,
        )

        object.__setattr__(
            self,
            "navigation_context",
            normalize_navigation_context(
                self.navigation_context
            ),
        )

    def is_fresh(
        self,
        *,
        now: datetime | None = None,
        ttl_seconds: float = (
            QCC_LIVE_ACTION_EVIDENCE_TTL_SECONDS
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
                "QCC_LIVE_ACTION_EVIDENCE_NOW_INVALID"
            )

        if (
            reference.tzinfo
            is None
            or reference.utcoffset()
            is None
        ):
            raise ValueError(
                "QCC_LIVE_ACTION_EVIDENCE_NOW_TZ_REQUIRED"
            )

        reference = (
            reference.astimezone(
                timezone.utc
            )
        )

        age = (
            reference
            - self.captured_at
        ).total_seconds()

        return (
            0.0
            <= age
            <= float(
                ttl_seconds
            )
        )

    def candidates_for(
        self,
        *,
        selector,
        frame_path="main",
    ) -> tuple[
        QccCanonicalLiveAction,
        ...,
    ]:
        """Busca por localización DOM, no por policy aportada externamente."""

        normalized_selector = (
            _required_text(
                selector,
                "QCC_LIVE_ACTION_EVIDENCE_SELECTOR_REQUIRED",
            )
        )

        normalized_frame_path = (
            str(
                frame_path
                or "main"
            ).strip()
            or "main"
        )

        return tuple(
            action
            for action
            in self.actions
            if (
                action.selector
                == normalized_selector
                and action.frame_path
                == normalized_frame_path
            )
        )
