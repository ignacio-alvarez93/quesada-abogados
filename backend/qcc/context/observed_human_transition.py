"""Evidencia causal efímera de una transición humana observada.

Correlaciona exclusivamente:

    observation A
    + trusted human DOM action
    + observation B

No concede permisos.
No ejecuta acciones.
No persiste NavigationKnowledge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from backend.qcc.context.observed_human_action import (
    QccObservedHumanAction,
)


QCC_OBSERVED_HUMAN_TRANSITION_SCHEMA_VERSION = 1
QCC_OBSERVED_HUMAN_TRANSITION_TYPE = (
    "QCC_OBSERVED_HUMAN_TRANSITION"
)
QCC_OBSERVED_HUMAN_TRANSITION_SOURCE = (
    "TRUSTED_DOM_HUMAN_CAUSAL_JOIN"
)


def _required_text(value, error):
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(error)
    return normalized


def _upper(value, error):
    return _required_text(
        value,
        error,
    ).upper()


def _fingerprint(value, error):
    normalized = _required_text(
        value,
        error,
    ).lower()

    if (
        len(normalized) != 64
        or any(
            character not in "0123456789abcdef"
            for character in normalized
        )
    ):
        raise ValueError(error)

    return normalized


def normalize_utc_datetime(
    value,
    error,
):
    if isinstance(value, str):
        text = value.strip()

        if text.endswith("Z"):
            text = (
                text[:-1]
                + "+00:00"
            )

        try:
            value = datetime.fromisoformat(
                text
            )
        except ValueError as exc:
            raise ValueError(
                error
            ) from exc

    if not isinstance(
        value,
        datetime,
    ):
        raise ValueError(
            error
        )

    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            error
        )

    return value.astimezone(
        timezone.utc
    )


def _optional_state(value):
    if value is None:
        return None

    return (
        str(value).strip().upper()
        or None
    )


@dataclass(
    frozen=True,
    slots=True,
)
class QccObservedHumanTransition:
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

    after_state: str | None
    after_fingerprint: str

    action_observed_at: datetime
    after_observed_at: datetime

    def __post_init__(self):
        object.__setattr__(
            self,
            "event_id",
            _required_text(
                self.event_id,
                "QCC_HUMAN_TRANSITION_EVENT_ID_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "session_id",
            _required_text(
                self.session_id,
                "QCC_HUMAN_TRANSITION_SESSION_ID_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "site_code",
            _upper(
                self.site_code,
                "QCC_HUMAN_TRANSITION_SITE_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "environment",
            _upper(
                self.environment,
                "QCC_HUMAN_TRANSITION_ENVIRONMENT_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "before_state",
            _optional_state(
                self.before_state
            ),
        )

        object.__setattr__(
            self,
            "after_state",
            _optional_state(
                self.after_state
            ),
        )

        object.__setattr__(
            self,
            "before_fingerprint",
            _fingerprint(
                self.before_fingerprint,
                "QCC_HUMAN_TRANSITION_BEFORE_FINGERPRINT_INVALID",
            ),
        )

        object.__setattr__(
            self,
            "after_fingerprint",
            _fingerprint(
                self.after_fingerprint,
                "QCC_HUMAN_TRANSITION_AFTER_FINGERPRINT_INVALID",
            ),
        )

        object.__setattr__(
            self,
            "kind",
            _upper(
                self.kind,
                "QCC_HUMAN_TRANSITION_KIND_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "policy",
            _upper(
                self.policy,
                "QCC_HUMAN_TRANSITION_POLICY_REQUIRED",
            ),
        )

        object.__setattr__(
            self,
            "selector",
            _required_text(
                self.selector,
                "QCC_HUMAN_TRANSITION_SELECTOR_REQUIRED",
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

        action_observed_at = normalize_utc_datetime(
            self.action_observed_at,
            "QCC_HUMAN_TRANSITION_ACTION_TIME_INVALID",
        )

        after_observed_at = normalize_utc_datetime(
            self.after_observed_at,
            "QCC_HUMAN_TRANSITION_AFTER_TIME_INVALID",
        )

        if (
            after_observed_at
            <= action_observed_at
        ):
            raise ValueError(
                "QCC_HUMAN_TRANSITION_AFTER_NOT_AFTER_ACTION"
            )

        object.__setattr__(
            self,
            "action_observed_at",
            action_observed_at,
        )

        object.__setattr__(
            self,
            "after_observed_at",
            after_observed_at,
        )

    @classmethod
    def from_action(
        cls,
        action: QccObservedHumanAction,
        *,
        after_state,
        after_fingerprint,
        after_observed_at,
    ):
        if not isinstance(
            action,
            QccObservedHumanAction,
        ):
            raise TypeError(
                "QCC_HUMAN_TRANSITION_ACTION_TYPE_INVALID"
            )

        return cls(
            event_id=action.event_id,
            session_id=action.session_id,
            site_code=action.site_code,
            environment=action.environment,
            before_state=action.before_state,
            before_fingerprint=(
                action.before_fingerprint
            ),
            kind=action.kind,
            policy=action.policy,
            selector=action.selector,
            frame_path=action.frame_path,
            after_state=after_state,
            after_fingerprint=(
                after_fingerprint
            ),
            action_observed_at=(
                action.observed_at
            ),
            after_observed_at=(
                after_observed_at
            ),
        )

    @property
    def changed(self) -> bool:
        return (
            self.before_fingerprint
            != self.after_fingerprint
        )

    @property
    def source(self) -> str:
        return (
            QCC_OBSERVED_HUMAN_TRANSITION_SOURCE
        )

    def transition_action(self):
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

    def to_runtime_dict(self):
        return {
            "schema_version":
                QCC_OBSERVED_HUMAN_TRANSITION_SCHEMA_VERSION,

            "transition_type":
                QCC_OBSERVED_HUMAN_TRANSITION_TYPE,

            "source":
                self.source,

            "event_id":
                self.event_id,

            "session_id":
                self.session_id,

            "site_code":
                self.site_code,

            "environment":
                self.environment,

            "before_state":
                self.before_state,

            "before_fingerprint":
                self.before_fingerprint,

            "action":
                self.transition_action(),

            "after_state":
                self.after_state,

            "after_fingerprint":
                self.after_fingerprint,

            "changed":
                self.changed,

            "action_observed_at":
                self.action_observed_at.isoformat(),

            "after_observed_at":
                self.after_observed_at.isoformat(),
        }
