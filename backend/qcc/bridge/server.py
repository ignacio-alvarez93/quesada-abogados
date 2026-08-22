"""Servidor HTTP local de Quesada Chrome Companion.

Contrato inicial:

    GET /qcc/health

El bridge:

- escucha únicamente en loopback;
- no accede a base de datos;
- no conoce SeleniumBase;
- no comparte proceso ni puerto con ICP Plus;
- no contiene lógica jurídica.
"""

from __future__ import annotations

import json
import threading
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from typing import Any
from urllib.parse import (
    unquote,
    urlparse,
)

from backend.qcc.contracts.actions import (
    QccActionRequest,
)
from backend.qcc.actions.store import (
    QccActionStore,
)
from backend.qcc.contracts.tools import (
    QccToolRequest,
)
from backend.qcc.tools.store import (
    QccToolStore,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
)
from backend.qcc.context.store import (
    QccContextStore,
)
from backend.qcc.site_architecture import (
    QccSiteArchitectureIngestor,
)


QCC_BRIDGE_HOST = "127.0.0.1"
QCC_BRIDGE_PORT = 8766

QCC_REQUEST_MAX_BYTES = 65536
QCC_SITE_ARCHITECTURE_MAX_BYTES = (
    64 * 1024 * 1024
)


def _health_payload() -> dict[str, Any]:
    return {
        "service": "qcc_bridge",
        "status": "ok",
        "protocol_version": QCC_PROTOCOL_VERSION,
    }


class _QccBridgeHandler(BaseHTTPRequestHandler):
    server_version = "QccBridge/0.1"

    def _send_json(
        self,
        status_code: int,
        payload: dict[str, Any],
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        self.send_response(status_code)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.send_header(
            "Cache-Control",
            "no-store",
        )
        self.end_headers()

        self.wfile.write(body)

    def _drain_request_body(
        self,
        length,
    ) -> None:
        """Descarta un body pendiente sin cargarlo completo en memoria."""

        remaining = max(
            int(length),
            0,
        )

        while remaining > 0:
            chunk = self.rfile.read(
                min(
                    65536,
                    remaining,
                )
            )

            if not chunk:
                break

            remaining -= len(chunk)

    def _read_json_with_limit(
        self,
        *,
        max_bytes,
        length_error,
    ) -> dict[str, Any]:
        raw_length = self.headers.get(
            "Content-Length",
            "0",
        )

        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError(
                length_error
            ) from exc

        if length <= 0:
            raise ValueError(
                length_error
            )

        if length > max_bytes:
            self._drain_request_body(
                length
            )

            raise ValueError(
                length_error
            )

        raw = self.rfile.read(
            length
        )

        try:
            payload = json.loads(
                raw.decode(
                    "utf-8"
                )
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "QCC_REQUEST_JSON_INVALID"
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "QCC_REQUEST_JSON_INVALID"
            )

        return payload

    def _read_json(
        self,
    ) -> dict[str, Any]:
        return self._read_json_with_limit(
            max_bytes=QCC_REQUEST_MAX_BYTES,
            length_error="QCC_REQUEST_LENGTH_INVALID",
        )

    def do_GET(self) -> None:
        if self.path == "/qcc/health":
            self._send_json(
                200,
                _health_payload(),
            )
            return

        if self.path == "/qcc/context":
            context_store = getattr(
                self.server,
                "qcc_context_store",
                None,
            )

            if context_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_CONTEXT_UNAVAILABLE",
                    },
                )
                return

            self._send_json(
                200,
                context_store.snapshot(),
            )
            return

        self._send_json(
            404,
            {
                "error": "QCC_ROUTE_NOT_FOUND",
            },
        )

    def do_POST(self) -> None:
        parsed = urlparse(
            self.path
        )

        path = (
            parsed.path.rstrip("/")
            or "/"
        )

        context_store = getattr(
            self.server,
            "qcc_context_store",
            None,
        )

        action_store = getattr(
            self.server,
            "qcc_action_store",
            None,
        )

        tool_store = getattr(
            self.server,
            "qcc_tool_store",
            None,
        )

        # ---------------------------------------------
        # QCC Extension -> Bridge:
        # POST /qcc/site-architecture/capture
        #
        # Funciona con Chrome manual o con una
        # presentación asistida activa.
        # ---------------------------------------------
        if path == "/qcc/site-architecture/capture":
            ingestor = getattr(
                self.server,
                "qcc_site_architecture_ingestor",
                None,
            )

            if ingestor is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_SITE_ARCHITECTURE_UNAVAILABLE",
                    },
                )
                return

            try:
                payload = self._read_json_with_limit(
                    max_bytes=(
                        QCC_SITE_ARCHITECTURE_MAX_BYTES
                    ),
                    length_error=(
                        "QCC_SITE_ARCHITECTURE_REQUEST_TOO_LARGE"
                    ),
                )

                if (
                    payload.get("protocol_version")
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                capture = payload.get(
                    "capture"
                )

                if not isinstance(
                    capture,
                    dict,
                ):
                    raise ValueError(
                        "QCC_SITE_ARCHITECTURE_CAPTURE_INVALID"
                    )

                context = (
                    context_store.snapshot()
                    if context_store is not None
                    else None
                )

                result = ingestor.ingest(
                    capture,
                    context=context,
                )

            except (
                TypeError,
                ValueError,
            ) as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok":
                        True,
                    "capture_id":
                        result["capture_id"],
                    "context_mode":
                        result["context_mode"],
                    "session_id":
                        result["session_id"],
                    "page":
                        result["page"],
                    "counts":
                        result["counts"],
                },
            )
            return

        # ---------------------------------------------
        # Runtime -> Bridge: snapshot de sesión
        # ---------------------------------------------
        if path == "/qcc/session":
            try:
                payload = self._read_json()

                if (
                    payload.get(
                        "protocol_version"
                    )
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

                raw_session = payload.get(
                    "session"
                )

                session = (
                    QccPresentationSession
                    .from_payload(
                        raw_session
                    )
                )

            except ValueError as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            if context_store is None:
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_CONTEXT_UNAVAILABLE",
                    },
                )
                return

            previous = (
                context_store
                .get_active_session()
            )

            revision = (
                context_store
                .set_active_session(
                    session
                )
            )

            if (
                action_store is not None
                and previous is not None
                and previous.session_id
                != session.session_id
            ):
                action_store.clear_session(
                    previous.session_id
                )

                if tool_store is not None:
                    tool_store.clear_session(
                        previous.session_id
                    )

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "revision":
                        revision,

                    "session_id":
                        session.session_id,
                },
            )
            return

        # ---------------------------------------------
        # Side Panel -> Bridge:
        # POST /qcc/session/<id>/tool
        #
        # Runtime -> Bridge:
        # POST /qcc/session/<id>/tool/consume
        # ---------------------------------------------
        tool_parts = [
            unquote(
                part
            )
            for part
            in path.strip("/").split("/")
            if part
        ]

        is_tool_route = (
            len(tool_parts) == 4
            and tool_parts[0] == "qcc"
            and tool_parts[1] == "session"
            and tool_parts[3] == "tool"
        )

        is_tool_consume_route = (
            len(tool_parts) == 5
            and tool_parts[0] == "qcc"
            and tool_parts[1] == "session"
            and tool_parts[3] == "tool"
            and tool_parts[4] == "consume"
        )

        if (
            is_tool_route
            or is_tool_consume_route
        ):
            if (
                context_store is None
                or tool_store is None
            ):
                self._send_json(
                    503,
                    {
                        "error":
                            "QCC_TOOL_CHANNEL_UNAVAILABLE",
                    },
                )
                return

            session_id = str(
                tool_parts[2]
            ).strip()

            try:
                payload = self._read_json()

                if (
                    payload.get(
                        "protocol_version"
                    )
                    != QCC_PROTOCOL_VERSION
                ):
                    raise ValueError(
                        "QCC_PROTOCOL_VERSION_INVALID"
                    )

            except ValueError as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            active_session = (
                context_store
                .get_active_session()
            )

            if (
                active_session is None
                or active_session.session_id
                != session_id
            ):
                self._send_json(
                    409,
                    {
                        "error":
                            "QCC_TOOL_SESSION_NOT_ACTIVE",
                    },
                )
                return

            if is_tool_route:
                try:
                    request = (
                        QccToolRequest
                        .from_payload(
                            payload,
                            session_id=session_id,
                        )
                    )

                    queued = (
                        tool_store
                        .submit(
                            request
                        )
                    )

                except (
                    TypeError,
                    ValueError,
                ) as exc:
                    self._send_json(
                        400,
                        {
                            "error":
                                str(exc),
                        },
                    )
                    return

                self._send_json(
                    200,
                    {
                        "ok":
                            True,

                        "tool_request_id":
                            queued.tool_request_id,

                        "session_id":
                            session_id,

                        "pending":
                            tool_store
                            .pending_count(
                                session_id
                            ),
                    },
                )
                return

            queued_tool = (
                tool_store
                .consume_next(
                    session_id
                )
            )

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "available":
                        queued_tool
                        is not None,

                    "tool":
                        (
                            queued_tool
                            .to_payload()
                            if queued_tool
                            is not None
                            else None
                        ),

                    "pending":
                        tool_store
                        .pending_count(
                            session_id
                        ),
                },
            )
            return

        # ---------------------------------------------
        # Side Panel -> Bridge:
        # POST /qcc/session/<id>/action
        #
        # Runtime -> Bridge:
        # POST /qcc/session/<id>/action/consume
        # ---------------------------------------------
        parts = [
            unquote(
                part
            )
            for part
            in path.strip("/").split("/")
            if part
        ]

        is_action_route = (
            len(parts) == 4
            and parts[0] == "qcc"
            and parts[1] == "session"
            and parts[3] == "action"
        )

        is_consume_route = (
            len(parts) == 5
            and parts[0] == "qcc"
            and parts[1] == "session"
            and parts[3] == "action"
            and parts[4] == "consume"
        )

        if not (
            is_action_route
            or is_consume_route
        ):
            self._send_json(
                404,
                {
                    "error":
                        "QCC_ROUTE_NOT_FOUND",
                },
            )
            return

        if (
            context_store is None
            or action_store is None
        ):
            self._send_json(
                503,
                {
                    "error":
                        "QCC_ACTION_CHANNEL_UNAVAILABLE",
                },
            )
            return

        session_id = str(
            parts[2]
        ).strip()

        # Leer SIEMPRE el body antes de responder.
        #
        # En Windows, cerrar una conexión HTTP con bytes
        # de request todavía pendientes puede provocar
        # WinError 10053 en el cliente en lugar de permitir
        # que urllib lea correctamente nuestro 4xx.
        try:
            payload = self._read_json()

            if (
                payload.get(
                    "protocol_version"
                )
                != QCC_PROTOCOL_VERSION
            ):
                raise ValueError(
                    "QCC_PROTOCOL_VERSION_INVALID"
                )

        except ValueError as exc:
            self._send_json(
                400,
                {
                    "error":
                        str(exc),
                },
            )
            return

        active_session = (
            context_store
            .get_active_session()
        )

        if (
            active_session is None
            or active_session.session_id
            != session_id
        ):
            self._send_json(
                409,
                {
                    "error":
                        "QCC_ACTION_SESSION_NOT_ACTIVE",
                },
            )
            return

        if is_action_route:
            try:
                request = (
                    QccActionRequest
                    .from_payload(
                        payload,
                        session_id=session_id,
                    )
                )

                queued = (
                    action_store
                    .submit(
                        request
                    )
                )

            except (
                TypeError,
                ValueError,
            ) as exc:
                self._send_json(
                    400,
                    {
                        "error":
                            str(exc),
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok":
                        True,

                    "action_id":
                        queued.action_id,

                    "session_id":
                        session_id,

                    "pending":
                        action_store
                        .pending_count(
                            session_id
                        ),
                },
            )
            return

        action = (
            action_store
            .consume_next(
                session_id
            )
        )

        self._send_json(
            200,
            {
                "ok":
                    True,

                "available":
                    action is not None,

                "action":
                    (
                        action.to_payload()
                        if action is not None
                        else None
                    ),

                "pending":
                    action_store
                    .pending_count(
                        session_id
                    ),
            },
        )

    def log_message(
        self,
        format: str,
        *args: object,
    ) -> None:
        # Evitamos ruido de requests HTTP en consola.
        return


class QccBridgeServer:
    """Owner explícito del servidor HTTP local QCC."""

    def __init__(
        self,
        *,
        host: str = QCC_BRIDGE_HOST,
        port: int = QCC_BRIDGE_PORT,
        context_store: (
            QccContextStore
            | None
        ) = None,
        action_store: (
            QccActionStore
            | None
        ) = None,
        tool_store: (
            QccToolStore
            | None
        ) = None,
        site_architecture_ingestor: (
            QccSiteArchitectureIngestor
            | None
        ) = None,
    ) -> None:
        if host != QCC_BRIDGE_HOST:
            raise ValueError(
                "QCC_BRIDGE_LOOPBACK_ONLY"
            )

        self._context_store = (
            context_store
            if context_store is not None
            else QccContextStore()
        )

        self._action_store = (
            action_store
            if action_store is not None
            else QccActionStore()
        )

        self._tool_store = (
            tool_store
            if tool_store is not None
            else QccToolStore()
        )

        self._site_architecture_ingestor = (
            site_architecture_ingestor
            if site_architecture_ingestor is not None
            else QccSiteArchitectureIngestor()
        )

        self._server = ThreadingHTTPServer(
            (host, port),
            _QccBridgeHandler,
        )

        self._server.qcc_context_store = (
            self._context_store
        )

        self._server.qcc_action_store = (
            self._action_store
        )

        self._server.qcc_tool_store = (
            self._tool_store
        )

        self._server.qcc_site_architecture_ingestor = (
            self._site_architecture_ingestor
        )

        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return str(
            self._server.server_address[0]
        )

    @property
    def port(self) -> int:
        return int(
            self._server.server_address[1]
        )

    @property
    def context_store(
        self,
    ) -> QccContextStore:
        return self._context_store

    @property
    def action_store(
        self,
    ) -> QccActionStore:
        return self._action_store

    @property
    def tool_store(
        self,
    ) -> QccToolStore:
        return self._tool_store

    @property
    def is_running(self) -> bool:
        return bool(
            self._thread
            and self._thread.is_alive()
        )

    def start(self) -> None:
        if self.is_running:
            return

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="qcc-bridge",
            daemon=True,
        )

        self._thread.start()

    def close(self) -> None:
        if self.is_running:
            self._server.shutdown()

        self._server.server_close()

        thread = self._thread

        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)

        self._thread = None


def run_qcc_bridge_forever() -> None:
    """Entry point manual de desarrollo."""

    server = QccBridgeServer()

    print(
        "[QCC-BRIDGE] listening",
        f"http://{server.host}:{server.port}",
    )

    try:
        server._server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()

        print(
            "[QCC-BRIDGE] closed"
        )


if __name__ == "__main__":
    run_qcc_bridge_forever()
