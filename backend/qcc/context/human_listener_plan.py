"""Plan efímero para observar acciones humanas en Chrome.

IMPORTANTE:

El navegador NO genera selectores canónicos.

Los targets salen exclusivamente de
QccLiveActionEvidence, que a su vez procede del
inventario canónico producido por Site Architecture.

El plan solo contiene localización DOM:

    selector
    frame_path

Nunca contiene:

    kind
    policy
    site_code
    environment
    fingerprint
"""

from __future__ import annotations

from collections import (
    Counter,
)
from dataclasses import (
    dataclass,
)

from backend.qcc.context.store import (
    QccContextStore,
)


@dataclass(
    frozen=True,
    slots=True,
)
class QccHumanListenerTarget:
    selector: str
    frame_path: str

    def __post_init__(
        self,
    ) -> None:
        selector = str(
            self.selector
            or ""
        ).strip()

        frame_path = str(
            self.frame_path
            or ""
        ).strip()

        if not selector:
            raise ValueError(
                "QCC_HUMAN_LISTENER_SELECTOR_REQUIRED"
            )

        if not frame_path:
            raise ValueError(
                "QCC_HUMAN_LISTENER_FRAME_REQUIRED"
            )

        # Solo aceptamos identidades que Chrome puede
        # resolver determinísticamente.
        if (
            frame_path != "main"
            and not frame_path.startswith(
                "qcc-frame:"
            )
        ):
            raise ValueError(
                "QCC_HUMAN_LISTENER_FRAME_UNSUPPORTED"
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

    def to_dict(
        self,
    ):
        return {
            "selector":
                self.selector,

            "frame_path":
                self.frame_path,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class QccHumanListenerPlan:
    session_id: str
    targets: tuple[
        QccHumanListenerTarget,
        ...,
    ]
    evidence_id: str | None = None

    def __post_init__(
        self,
    ) -> None:
        session_id = str(
            self.session_id
            or ""
        ).strip()

        if not session_id:
            raise ValueError(
                "QCC_HUMAN_LISTENER_SESSION_REQUIRED"
            )

        object.__setattr__(
            self,
            "session_id",
            session_id,
        )

        object.__setattr__(
            self,
            "targets",
            tuple(
                self.targets
                or ()
            ),
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

        object.__setattr__(
            self,
            "evidence_id",
            evidence_id,
        )

    def to_transport_dict(
        self,
    ):
        """Payload deliberadamente sin autoridad."""

        return {
            "targets": [
                target.to_dict()
                for target
                in self.targets
            ],
        }


def build_human_listener_plan(
    context_store: QccContextStore,
    *,
    now=None,
) -> QccHumanListenerPlan:
    """Deriva targets únicamente de evidencia canónica fresca."""

    if not isinstance(
        context_store,
        QccContextStore,
    ):
        raise TypeError(
            "QCC_HUMAN_LISTENER_CONTEXT_STORE_INVALID"
        )

    evidence = (
        context_store
        .get_live_action_evidence(
            now=now
        )
    )

    if evidence is None:
        raise ValueError(
            "QCC_HUMAN_LISTENER_EVIDENCE_REQUIRED"
        )

    # Primera versión deliberadamente reducida:
    #
    # solo observamos acciones de navegación que pueden
    # materializarse mediante un click físico.
    #
    # No observamos SELECT / RADIO / CHECKBOX /
    # INPUT_VALUE / FILE_UPLOAD para evitar convertir
    # interacción de formulario en falsas transiciones.
    observable_kinds = {
        "BUTTON",
        "LINK",
        "SUBMIT",
        "TAB",
    }

    identities = [
        (
            action.selector,
            action.frame_path,
        )
        for action
        in evidence.actions
        if action.kind
        in observable_kinds
    ]

    counts = Counter(
        identities
    )

    targets = []

    for (
        selector,
        frame_path,
    ) in identities:

        # El browser nunca recibe una identidad
        # ambigua.
        if (
            counts[
                (
                    selector,
                    frame_path,
                )
            ]
            != 1
        ):
            continue

        try:
            target = (
                QccHumanListenerTarget(
                    selector=selector,
                    frame_path=frame_path,
                )
            )

        except ValueError:
            # qcc-frame-index:* y cualquier frame
            # no resoluble quedan fuera.
            continue

        if target not in targets:
            targets.append(
                target
            )

    if not targets:
        raise ValueError(
            "QCC_HUMAN_LISTENER_TARGETS_UNAVAILABLE"
        )

    return (
        QccHumanListenerPlan(
            session_id=(
                evidence.session_id
            ),
            targets=tuple(
                targets
            ),
            evidence_id=(
                evidence.evidence_id
            ),
        )
    )
