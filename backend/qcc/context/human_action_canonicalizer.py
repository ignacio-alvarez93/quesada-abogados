"""Canonicalización backend de una señal humana DOM.

La señal procedente del navegador NO puede decidir:

- kind
- policy
- site_code
- environment
- before_state
- before_fingerprint

Todos esos datos se reconstruyen desde el CURRENT y el
inventario canónico de acciones capturado previamente por
el backend.

Regla:

    capture A
    + canonical live_actions A
    + minimal human DOM signal
    -> exactly one canonical action
    -> QccObservedHumanAction

0 candidatos:
    rechazo.

>1 candidatos:
    rechazo por ambigüedad.

La función NO concede permiso de automatización.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
)
from datetime import (
    datetime,
    timezone,
)

from backend.qcc.context.observed_human_action import (
    QCC_OBSERVED_HUMAN_ACTION_TTL_SECONDS,
    QccObservedHumanAction,
)
from backend.qcc.context.store import (
    QccContextStore,
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


@dataclass(
    frozen=True,
    slots=True,
)
class QccHumanDomSignal:
    """Señal mínima de una acción física observada en el DOM.

    IMPORTANTE:
    este contrato deliberadamente NO contiene policy/kind.
    """

    event_id: str
    session_id: str
    selector: str
    frame_path: str
    observed_at: datetime
    evidence_id: str | None = None

    def __post_init__(
        self,
    ) -> None:
        event_id = _required_text(
            self.event_id,
            "QCC_HUMAN_DOM_SIGNAL_EVENT_ID_REQUIRED",
        )

        if len(event_id) > 128:
            raise ValueError(
                "QCC_HUMAN_DOM_SIGNAL_EVENT_ID_INVALID"
            )

        session_id = _required_text(
            self.session_id,
            "QCC_HUMAN_DOM_SIGNAL_SESSION_ID_REQUIRED",
        )

        selector = _required_text(
            self.selector,
            "QCC_HUMAN_DOM_SIGNAL_SELECTOR_REQUIRED",
        )

        frame_path = (
            str(
                self.frame_path
                or "main"
            ).strip()
            or "main"
        )

        observed_at = (
            self.observed_at
        )

        if not isinstance(
            observed_at,
            datetime,
        ):
            raise ValueError(
                "QCC_HUMAN_DOM_SIGNAL_TIME_INVALID"
            )

        if (
            observed_at.tzinfo
            is None
            or observed_at.utcoffset()
            is None
        ):
            raise ValueError(
                "QCC_HUMAN_DOM_SIGNAL_TIME_TZ_REQUIRED"
            )

        observed_at = (
            observed_at.astimezone(
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

        evidence_id = (
            None
            if self.evidence_id is None
            else (
                str(
                    self.evidence_id
                ).strip()
                or None
            )
        )

        if (
            evidence_id is not None
            and len(evidence_id) > 128
        ):
            raise ValueError(
                "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_ID_INVALID"
            )

        object.__setattr__(
            self,
            "evidence_id",
            evidence_id,
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
                "QCC_HUMAN_DOM_SIGNAL_NOW_INVALID"
            )

        if (
            reference.tzinfo
            is None
            or reference.utcoffset()
            is None
        ):
            raise ValueError(
                "QCC_HUMAN_DOM_SIGNAL_NOW_TZ_REQUIRED"
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


def resolve_human_dom_signal(
    context_store: QccContextStore,
    signal: QccHumanDomSignal,
    *,
    now: datetime | None = None,
    ttl_seconds: float = (
        QCC_OBSERVED_HUMAN_ACTION_TTL_SECONDS
    ),
) -> QccObservedHumanAction:
    """Resuelve una señal humana contra evidencia canónica sin registrarla."""

    if not isinstance(
        context_store,
        QccContextStore,
    ):
        raise TypeError(
            "QCC_HUMAN_DOM_SIGNAL_CONTEXT_STORE_INVALID"
        )

    if not isinstance(
        signal,
        QccHumanDomSignal,
    ):
        raise TypeError(
            "QCC_HUMAN_DOM_SIGNAL_TYPE_INVALID"
        )

    # PresentationSession OR technical ObservationScope.
    session = (
        context_store
        .get_observation_identity()
    )

    if (
        session is None
        or session.session_id
        != signal.session_id
    ):
        raise ValueError(
            "QCC_HUMAN_DOM_SIGNAL_SESSION_NOT_ACTIVE"
        )

    current = (
        context_store
        .get_live_navigation()
    )

    # Legacy signals remain CURRENT-addressed.
    #
    # Snapshot-addressed signals do not require CURRENT
    # to still equal A: navigation may already have reached B.
    if signal.evidence_id is None:
        if current is None:
            raise ValueError(
                "QCC_HUMAN_DOM_SIGNAL_CURRENT_REQUIRED"
            )

        if (
            current.session_id
            != signal.session_id
        ):
            raise ValueError(
                "QCC_HUMAN_DOM_SIGNAL_CURRENT_SESSION_MISMATCH"
            )

    environment = (
        context_store
        .get_navigation_environment()
    )

    if environment is None:
        raise ValueError(
            "QCC_HUMAN_DOM_SIGNAL_ENVIRONMENT_REQUIRED"
        )

    if not signal.is_fresh(
        now=now,
        ttl_seconds=ttl_seconds,
    ):
        raise ValueError(
            "QCC_HUMAN_DOM_SIGNAL_STALE"
        )

    # CURRENT A has its own human interaction window.
    #
    # Do NOT reuse ttl_seconds here:
    # ttl_seconds governs freshness of the just-observed human
    # signal / pending post-click action, whereas LiveActionEvidence
    # may legitimately wait longer for the human to act.
    if signal.evidence_id is not None:
        evidence = (
            context_store
            .get_live_action_evidence_by_id(
                signal.evidence_id,
                now=now,
            )
        )

        if evidence is None:
            raise ValueError(
                "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_ID_NOT_FOUND"
            )

    else:
        evidence = (
            context_store
            .get_live_action_evidence(
                now=now,
            )
        )

        if evidence is None:
            raise ValueError(
                "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_REQUIRED"
            )

    # La señal debe haber ocurrido DESPUÉS de la captura
    # que constituye observation A.
    if (
        signal.observed_at
        < evidence.captured_at
    ):
        raise ValueError(
            "QCC_HUMAN_DOM_SIGNAL_BEFORE_EVIDENCE"
        )

    if (
        evidence.session_id
        != signal.session_id
    ):
        raise ValueError(
            "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_SESSION_MISMATCH"
        )

    if (
        evidence.environment
        != environment
    ):
        raise ValueError(
            "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_ENVIRONMENT_MISMATCH"
        )

    if (
        signal.evidence_id is None
        and evidence.before_fingerprint
        != current.current_fingerprint
    ):
        raise ValueError(
            "QCC_HUMAN_DOM_SIGNAL_EVIDENCE_FINGERPRINT_MISMATCH"
        )

    candidates = (
        evidence.candidates_for(
            selector=signal.selector,
            frame_path=signal.frame_path,
        )
    )

    if not candidates:
        raise ValueError(
            "QCC_HUMAN_DOM_SIGNAL_ACTION_NOT_FOUND"
        )

    if len(candidates) != 1:
        raise ValueError(
            "QCC_HUMAN_DOM_SIGNAL_ACTION_AMBIGUOUS"
        )

    canonical = (
        candidates[0]
    )

    observed = (
        QccObservedHumanAction(
            event_id=(
                signal.event_id
            ),
            session_id=(
                signal.session_id
            ),
            site_code=(
                evidence.site_code
            ),
            environment=(
                evidence.environment
            ),
            before_state=(
                evidence.before_state
            ),
            before_fingerprint=(
                evidence.before_fingerprint
            ),
            kind=(
                canonical.kind
            ),
            policy=(
                canonical.policy
            ),
            selector=(
                canonical.selector
            ),
            frame_path=(
                canonical.frame_path
            ),
            navigation_context=(
                getattr(
                    evidence,
                    "navigation_context",
                    (),
                )
            ),
            observed_at=(
                signal.observed_at
            ),
            evidence_capture_id=(
                getattr(
                    evidence,
                    "capture_id",
                    None,
                )
            ),
        )
    )

    return observed


def canonicalize_human_dom_signal(
    context_store: QccContextStore,
    signal: QccHumanDomSignal,
    *,
    now: datetime | None = None,
    ttl_seconds: float = (
        QCC_OBSERVED_HUMAN_ACTION_TTL_SECONDS
    ),
) -> QccObservedHumanAction:
    """Resuelve y registra una señal humana contra evidencia canónica."""

    observed = resolve_human_dom_signal(
        context_store,
        signal,
        now=now,
        ttl_seconds=ttl_seconds,
    )

    # ContextStore vuelve a validar:
    # session/site/environment/CURRENT exactos.
    return (
        context_store
        .set_observed_human_action(
            observed
        )
    )
