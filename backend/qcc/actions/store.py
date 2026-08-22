"""Cola thread-safe de acciones humanas QCC.

No es persistencia canónica.

Una acción se consume exactamente una vez desde
este proceso Bridge. Si el runtime no puede obtenerla,
el flujo superior debe conservar su fallback manual.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
from typing import Any

from backend.qcc.contracts.actions import (
    QccActionRequest,
)


QCC_ACTION_QUEUE_LIMIT = 16


@dataclass(
    frozen=True,
    slots=True,
)
class QccQueuedAction:
    action_id: int
    request: QccActionRequest

    def to_payload(
        self,
    ) -> dict[str, Any]:
        payload = (
            self.request
            .to_payload()
        )

        return {
            "action_id":
                self.action_id,
            **payload,
        }


class QccActionStore:
    """Colas de acciones aisladas por sesión."""

    def __init__(
        self,
    ) -> None:
        self._lock = threading.RLock()

        self._queues: dict[
            str,
            deque[QccQueuedAction],
        ] = {}

        self._next_action_id = 1

    def submit(
        self,
        request: QccActionRequest,
    ) -> QccQueuedAction:
        if not isinstance(
            request,
            QccActionRequest,
        ):
            raise TypeError(
                "QCC_ACTION_REQUEST_TYPE_INVALID"
            )

        with self._lock:
            queue = self._queues.setdefault(
                request.session_id,
                deque(),
            )

            if (
                len(queue)
                >= QCC_ACTION_QUEUE_LIMIT
            ):
                raise ValueError(
                    "QCC_ACTION_QUEUE_FULL"
                )

            queued = QccQueuedAction(
                action_id=(
                    self._next_action_id
                ),
                request=request,
            )

            self._next_action_id += 1

            queue.append(
                queued
            )

            return queued

    def consume_next(
        self,
        session_id: str,
    ) -> QccQueuedAction | None:
        session_id = str(
            session_id
        ).strip()

        if not session_id:
            raise ValueError(
                "QCC_ACTION_SESSION_ID_REQUIRED"
            )

        with self._lock:
            queue = self._queues.get(
                session_id
            )

            if not queue:
                return None

            action = queue.popleft()

            if not queue:
                self._queues.pop(
                    session_id,
                    None,
                )

            return action

    def pending_count(
        self,
        session_id: str,
    ) -> int:
        with self._lock:
            queue = self._queues.get(
                str(
                    session_id
                ).strip()
            )

            return (
                len(queue)
                if queue is not None
                else 0
            )

    def clear_session(
        self,
        session_id: str,
    ) -> int:
        with self._lock:
            queue = self._queues.pop(
                str(
                    session_id
                ).strip(),
                None,
            )

            return (
                len(queue)
                if queue is not None
                else 0
            )
