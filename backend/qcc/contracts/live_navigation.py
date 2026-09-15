"""Contrato PII-safe de navegación viva proyectada por QCC."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


QCC_LIVE_NAVIGATION_SCHEMA_VERSION = 1
QCC_LIVE_NAVIGATION_TYPE = (
    "QCC_LIVE_NAVIGATION_CONTEXT"
)


def _optional_text(
    value,
    *,
    max_length: int = 1024,
):
    if value is None:
        return None

    if not isinstance(
        value,
        str,
    ):
        raise ValueError(
            "QCC_LIVE_NAVIGATION_PAYLOAD_INVALID"
        )

    normalized = value.strip()

    if not normalized:
        return None

    if len(normalized) > max_length:
        raise ValueError(
            "QCC_LIVE_NAVIGATION_TEXT_TOO_LONG"
        )

    return normalized


def _mapping(
    value,
    *,
    field_name: str,
    allowed: set[str],
):
    if value is None:
        return {}

    if not isinstance(
        value,
        Mapping,
    ):
        raise ValueError(
            "QCC_LIVE_NAVIGATION_PAYLOAD_INVALID"
        )

    unexpected = (
        set(value)
        - allowed
    )

    if unexpected:
        key = sorted(
            str(item)
            for item in unexpected
        )[0]

        raise ValueError(
            "QCC_LIVE_NAVIGATION_FIELD_NOT_ALLOWED:"
            f"{field_name}.{key}"
        )

    return dict(value)


@dataclass(
    frozen=True,
    slots=True,
)
class QccLiveNavigationContext:
    """Proyección estructural del estado vivo de navegación.

    No contiene HTML, valores de formulario, texto DOM,
    cookies, certificados ni payloads arbitrarios.

    Tampoco concede permisos de ejecución:
    `governance_*` debe ser el resultado de la capa
    de gobierno correspondiente.
    """

    session_id: str
    updated_at: datetime

    current_state: str | None = None
    current_fingerprint: str | None = None

    target_state: str | None = None
    target_fingerprint: str | None = None

    route_reachable: bool | None = None
    remaining_steps: int | None = None

    next_step_kind: str | None = None
    next_step_policy: str | None = None
    next_step_selector: str | None = None
    next_step_frame_path: (
        tuple[str, ...]
        | None
    ) = None
    next_step_confidence: float | None = None

    governance_decision: str | None = None
    governance_reason: str | None = None
    automation_allowed: bool | None = None

    display_title: str | None = None
    display_instruction: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.session_id,
            str,
        ) or not self.session_id.strip():
            raise ValueError(
                "QCC_LIVE_NAVIGATION_SESSION_ID_REQUIRED"
            )

        if not isinstance(
            self.updated_at,
            datetime,
        ):
            raise ValueError(
                "QCC_LIVE_NAVIGATION_UPDATED_AT_INVALID"
            )

        for field_name in (
            "current_state",
            "current_fingerprint",
            "target_state",
            "target_fingerprint",
            "next_step_kind",
            "next_step_policy",
            "next_step_selector",
            "governance_decision",
            "governance_reason",
            "display_title",
            "display_instruction",
        ):
            value = getattr(
                self,
                field_name,
            )

            if (
                value is not None
                and not isinstance(
                    value,
                    str,
                )
            ):
                raise ValueError(
                    "QCC_LIVE_NAVIGATION_PAYLOAD_INVALID"
                )

        if (
            self.route_reachable
            is not None
            and not isinstance(
                self.route_reachable,
                bool,
            )
        ):
            raise ValueError(
                "QCC_LIVE_NAVIGATION_ROUTE_INVALID"
            )

        if (
            self.remaining_steps
            is not None
            and (
                not isinstance(
                    self.remaining_steps,
                    int,
                )
                or isinstance(
                    self.remaining_steps,
                    bool,
                )
                or self.remaining_steps < 0
            )
        ):
            raise ValueError(
                "QCC_LIVE_NAVIGATION_REMAINING_STEPS_INVALID"
            )

        if (
            self.automation_allowed
            is not None
            and not isinstance(
                self.automation_allowed,
                bool,
            )
        ):
            raise ValueError(
                "QCC_LIVE_NAVIGATION_AUTOMATION_FLAG_INVALID"
            )

        if (
            self.next_step_confidence
            is not None
        ):
            if (
                isinstance(
                    self.next_step_confidence,
                    bool,
                )
                or not isinstance(
                    self.next_step_confidence,
                    (int, float),
                )
            ):
                raise ValueError(
                    "QCC_LIVE_NAVIGATION_CONFIDENCE_INVALID"
                )

            if not (
                0.0
                <= float(
                    self.next_step_confidence
                )
                <= 1.0
            ):
                raise ValueError(
                    "QCC_LIVE_NAVIGATION_CONFIDENCE_INVALID"
                )

        if (
            self.next_step_frame_path
            is not None
        ):
            if not isinstance(
                self.next_step_frame_path,
                tuple,
            ):
                raise ValueError(
                    "QCC_LIVE_NAVIGATION_FRAME_PATH_INVALID"
                )

            if any(
                not isinstance(
                    part,
                    str,
                )
                for part
                in self.next_step_frame_path
            ):
                raise ValueError(
                    "QCC_LIVE_NAVIGATION_FRAME_PATH_INVALID"
                )

    def to_payload(
        self,
    ) -> dict[str, Any]:
        has_next_step = any(
            value is not None
            for value in (
                self.next_step_kind,
                self.next_step_policy,
                self.next_step_selector,
                self.next_step_frame_path,
                self.next_step_confidence,
            )
        )

        has_governance = any(
            value is not None
            for value in (
                self.governance_decision,
                self.governance_reason,
                self.automation_allowed,
            )
        )

        return {
            "schema_version":
                QCC_LIVE_NAVIGATION_SCHEMA_VERSION,

            "context_type":
                QCC_LIVE_NAVIGATION_TYPE,

            "session_id":
                self.session_id,

            "updated_at":
                self.updated_at.isoformat(),

            "current": {
                "state":
                    self.current_state,

                "fingerprint":
                    self.current_fingerprint,
            },

            "target": {
                "state":
                    self.target_state,

                "fingerprint":
                    self.target_fingerprint,
            },

            "route": {
                "reachable":
                    self.route_reachable,

                "remaining_steps":
                    self.remaining_steps,
            },

            "next_step":
                (
                    {
                        "kind":
                            self.next_step_kind,

                        "policy":
                            self.next_step_policy,

                        "selector":
                            self.next_step_selector,

                        "frame_path":
                            (
                                list(
                                    self.next_step_frame_path
                                )
                                if self.next_step_frame_path
                                is not None
                                else None
                            ),

                        "confidence":
                            (
                                float(
                                    self.next_step_confidence
                                )
                                if self.next_step_confidence
                                is not None
                                else None
                            ),
                    }
                    if has_next_step
                    else None
                ),

            "governance":
                (
                    {
                        "decision":
                            self.governance_decision,

                        "reason":
                            self.governance_reason,

                        "automation_allowed":
                            self.automation_allowed,
                    }
                    if has_governance
                    else None
                ),

            "display": {
                "title":
                    self.display_title,

                "instruction":
                    self.display_instruction,
            },
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "QccLiveNavigationContext":
        if not isinstance(
            payload,
            Mapping,
        ):
            raise ValueError(
                "QCC_LIVE_NAVIGATION_PAYLOAD_INVALID"
            )

        allowed_top_level = {
            "schema_version",
            "context_type",
            "session_id",
            "updated_at",
            "current",
            "target",
            "route",
            "next_step",
            "governance",
            "display",
        }

        unexpected = (
            set(payload)
            - allowed_top_level
        )

        if unexpected:
            key = sorted(
                str(item)
                for item in unexpected
            )[0]

            raise ValueError(
                "QCC_LIVE_NAVIGATION_FIELD_NOT_ALLOWED:"
                f"{key}"
            )

        if (
            payload.get(
                "schema_version"
            )
            != QCC_LIVE_NAVIGATION_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_LIVE_NAVIGATION_SCHEMA_VERSION_INVALID"
            )

        if (
            payload.get(
                "context_type"
            )
            != QCC_LIVE_NAVIGATION_TYPE
        ):
            raise ValueError(
                "QCC_LIVE_NAVIGATION_TYPE_INVALID"
            )

        try:
            updated_at = (
                datetime.fromisoformat(
                    str(
                        payload[
                            "updated_at"
                        ]
                    )
                )
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "QCC_LIVE_NAVIGATION_UPDATED_AT_INVALID"
            ) from exc

        current = _mapping(
            payload.get(
                "current"
            ),
            field_name="current",
            allowed={
                "state",
                "fingerprint",
            },
        )

        target = _mapping(
            payload.get(
                "target"
            ),
            field_name="target",
            allowed={
                "state",
                "fingerprint",
            },
        )

        route = _mapping(
            payload.get(
                "route"
            ),
            field_name="route",
            allowed={
                "reachable",
                "remaining_steps",
            },
        )

        next_step = _mapping(
            payload.get(
                "next_step"
            ),
            field_name="next_step",
            allowed={
                "kind",
                "policy",
                "selector",
                "frame_path",
                "confidence",
            },
        )

        governance = _mapping(
            payload.get(
                "governance"
            ),
            field_name="governance",
            allowed={
                "decision",
                "reason",
                "automation_allowed",
            },
        )

        display = _mapping(
            payload.get(
                "display"
            ),
            field_name="display",
            allowed={
                "title",
                "instruction",
            },
        )

        frame_path = (
            next_step.get(
                "frame_path"
            )
        )

        if frame_path is not None:
            if not isinstance(
                frame_path,
                (list, tuple),
            ):
                raise ValueError(
                    "QCC_LIVE_NAVIGATION_FRAME_PATH_INVALID"
                )

            frame_path = tuple(
                str(part)
                for part
                in frame_path
            )

        confidence = next_step.get(
            "confidence"
        )

        if confidence is not None:
            try:
                confidence = float(
                    confidence
                )
            except (
                TypeError,
                ValueError,
            ) as exc:
                raise ValueError(
                    "QCC_LIVE_NAVIGATION_CONFIDENCE_INVALID"
                ) from exc

        remaining_steps = route.get(
            "remaining_steps"
        )

        if remaining_steps is not None:
            if (
                isinstance(
                    remaining_steps,
                    bool,
                )
            ):
                raise ValueError(
                    "QCC_LIVE_NAVIGATION_REMAINING_STEPS_INVALID"
                )

            try:
                remaining_steps = int(
                    remaining_steps
                )
            except (
                TypeError,
                ValueError,
            ) as exc:
                raise ValueError(
                    "QCC_LIVE_NAVIGATION_REMAINING_STEPS_INVALID"
                ) from exc

        return cls(
            session_id=str(
                payload.get(
                    "session_id",
                    "",
                )
            ),
            updated_at=updated_at,

            current_state=_optional_text(
                current.get(
                    "state"
                )
            ),
            current_fingerprint=_optional_text(
                current.get(
                    "fingerprint"
                )
            ),

            target_state=_optional_text(
                target.get(
                    "state"
                )
            ),
            target_fingerprint=_optional_text(
                target.get(
                    "fingerprint"
                )
            ),

            route_reachable=route.get(
                "reachable"
            ),
            remaining_steps=remaining_steps,

            next_step_kind=_optional_text(
                next_step.get(
                    "kind"
                )
            ),
            next_step_policy=_optional_text(
                next_step.get(
                    "policy"
                )
            ),
            next_step_selector=_optional_text(
                next_step.get(
                    "selector"
                )
            ),
            next_step_frame_path=frame_path,
            next_step_confidence=confidence,

            governance_decision=_optional_text(
                governance.get(
                    "decision"
                )
            ),
            governance_reason=_optional_text(
                governance.get(
                    "reason"
                )
            ),
            automation_allowed=(
                governance.get(
                    "automation_allowed"
                )
            ),

            display_title=_optional_text(
                display.get(
                    "title"
                )
            ),
            display_instruction=_optional_text(
                display.get(
                    "instruction"
                ),
                max_length=2048,
            ),
        )
