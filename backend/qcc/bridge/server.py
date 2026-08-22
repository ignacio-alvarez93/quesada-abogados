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

from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
)
from backend.qcc.context.store import (
    QccContextStore,
)


QCC_BRIDGE_HOST = "127.0.0.1"
QCC_BRIDGE_PORT = 8766


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

    def _read_json(
        self,
    ) -> dict[str, Any]:
        raw_length = self.headers.get(
            "Content-Length",
            "0",
        )

        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError(
                "QCC_REQUEST_LENGTH_INVALID"
            ) from exc

        if (
            length <= 0
            or length > 65536
        ):
            raise ValueError(
                "QCC_REQUEST_LENGTH_INVALID"
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
        if self.path != "/qcc/session":
            self._send_json(
                404,
                {
                    "error":
                        "QCC_ROUTE_NOT_FOUND",
                },
            )
            return

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

        revision = (
            context_store
            .set_active_session(
                session
            )
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

        self._server = ThreadingHTTPServer(
            (host, port),
            _QccBridgeHandler,
        )

        self._server.qcc_context_store = (
            self._context_store
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
