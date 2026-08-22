"""Cola independiente de herramientas QCC.

No comparte FIFO con las acciones del flujo.

Esto impide que consumidores especializados como
wait_for_qcc_document_action() puedan consumir o
descartar accidentalmente una herramienta diagnóstica.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading

from backend.qcc.contracts.tools import (
    QccToolRequest,
)


QCC_TOOL_QUEUE_LIMIT = 8


@dataclass(
    frozen=True,
    slots=True,
)
class QccQueuedTool:
    tool_request_id: int
    request: QccToolRequest

    def to_payload(
        self,
    ):
        return {
            "tool_request_id":
                self.tool_request_id,
            **self.request.to_payload(),
        }


class QccToolStore:
    """Colas diagnósticas aisladas por sesión."""

    def __init__(
        self,
    ) -> None:
        self._lock = threading.RLock()

        self._queues = {}

        self._next_tool_request_id = 1

        self._known_tools = {}

    def submit(
        self,
        request,
    ):
        if not isinstance(
            request,
            QccToolRequest,
        ):
            raise TypeError(
                "QCC_TOOL_REQUEST_TYPE_INVALID"
            )

        with self._lock:
            dedupe_key = (
                (
                    request.session_id,
                    request.client_tool_id,
                )
                if request.client_tool_id
                else None
            )

            if dedupe_key is not None:
                existing = (
                    self._known_tools
                    .get(
                        dedupe_key
                    )
                )

                if existing is not None:
                    if (
                        existing.request
                        != request
                    ):
                        raise ValueError(
                            "QCC_TOOL_IDEMPOTENCY_CONFLICT"
                        )

                    return existing

            queue = (
                self._queues
                .setdefault(
                    request.session_id,
                    deque(),
                )
            )

            if (
                len(queue)
                >= QCC_TOOL_QUEUE_LIMIT
            ):
                raise ValueError(
                    "QCC_TOOL_QUEUE_FULL"
                )

            queued = QccQueuedTool(
                tool_request_id=(
                    self._next_tool_request_id
                ),
                request=request,
            )

            self._next_tool_request_id += 1

            queue.append(
                queued
            )

            if dedupe_key is not None:
                self._known_tools[
                    dedupe_key
                ] = queued

            return queued

    def consume_next(
        self,
        session_id,
    ):
        session_id = str(
            session_id
        ).strip()

        if not session_id:
            raise ValueError(
                "QCC_TOOL_SESSION_ID_REQUIRED"
            )

        with self._lock:
            queue = (
                self._queues
                .get(
                    session_id
                )
            )

            if not queue:
                return None

            tool = queue.popleft()

            if not queue:
                self._queues.pop(
                    session_id,
                    None,
                )

            return tool

    def pending_count(
        self,
        session_id,
    ):
        with self._lock:
            queue = (
                self._queues
                .get(
                    str(
                        session_id
                    ).strip()
                )
            )

            return (
                len(queue)
                if queue is not None
                else 0
            )

    def clear_session(
        self,
        session_id,
    ):
        session_id = str(
            session_id
        ).strip()

        with self._lock:
            queue = self._queues.pop(
                session_id,
                None,
            )

            pending = (
                len(queue)
                if queue is not None
                else 0
            )

            keys = [
                key
                for key
                in self._known_tools
                if key[0] == session_id
            ]

            for key in keys:
                self._known_tools.pop(
                    key,
                    None,
                )

            return pending
