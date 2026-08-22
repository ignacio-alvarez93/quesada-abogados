from __future__ import annotations

import argparse
import json
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8767

DOCUMENT_PATH = (
    "/mercurio/"
    "presentacionTelematicaDocumentacion.html"
)

ROUTES = {
    DOCUMENT_PATH:
        (
            STATIC_ROOT
            / "documentacion.html"
        ),

    "/mercurio/resources/lab/"
    "mercurio_lab.css":
        (
            STATIC_ROOT
            / "mercurio_lab.css"
        ),

    "/mercurio/resources/lab/"
    "mercurio_lab.js":
        (
            STATIC_ROOT
            / "mercurio_lab.js"
        ),
}

CONTENT_TYPES = {
    ".html":
        "text/html; charset=utf-8",
    ".css":
        "text/css; charset=utf-8",
    ".js":
        (
            "application/javascript; "
            "charset=utf-8"
        ),
}


class MercurioLabServer(
    ThreadingHTTPServer
):
    allow_reuse_address = True


class MercurioLabHandler(
    BaseHTTPRequestHandler
):
    server_version = (
        "QuesadaMercurioLab/1.0"
    )

    def _send_bytes(
        self,
        *,
        status,
        content_type,
        body,
    ):
        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Content-Length",
            str(
                len(
                    body
                )
            ),
        )

        self.send_header(
            "Cache-Control",
            (
                "no-store, no-cache, "
                "must-revalidate, max-age=0"
            ),
        )

        self.send_header(
            "Pragma",
            "no-cache",
        )

        self.end_headers()

        if (
            self.command
            != "HEAD"
        ):
            self.wfile.write(
                body
            )

    def _serve(
        self,
    ):
        path = (
            urlsplit(
                self.path
            )
            .path
        )

        if path == "/health":
            payload = {
                "ok": True,
                "service":
                    "mercurio_lab",
                "version":
                    "1.0",
                "document_path":
                    DOCUMENT_PATH,
            }

            self._send_bytes(
                status=200,
                content_type=(
                    "application/json; "
                    "charset=utf-8"
                ),
                body=(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                    )
                    .encode(
                        "utf-8"
                    )
                ),
            )

            return

        target = ROUTES.get(
            path
        )

        if target is None:
            self._send_bytes(
                status=404,
                content_type=(
                    "text/plain; "
                    "charset=utf-8"
                ),
                body=b"Not Found",
            )

            return

        if not target.is_file():
            self._send_bytes(
                status=500,
                content_type=(
                    "text/plain; "
                    "charset=utf-8"
                ),
                body=(
                    b"Mercurio Lab asset "
                    b"missing"
                ),
            )

            return

        content_type = (
            CONTENT_TYPES.get(
                target.suffix.lower(),
                (
                    "application/"
                    "octet-stream"
                ),
            )
        )

        self._send_bytes(
            status=200,
            content_type=content_type,
            body=target.read_bytes(),
        )

    def do_GET(
        self,
    ):
        self._serve()

    def do_HEAD(
        self,
    ):
        self._serve()

    def do_POST(
        self,
    ):
        # Blindaje deliberado:
        # el LAB nunca recibe ni remite
        # presentaciones administrativas.
        self._send_bytes(
            status=405,
            content_type=(
                "application/json; "
                "charset=utf-8"
            ),
            body=(
                json.dumps(
                    {
                        "ok": False,
                        "error":
                            (
                                "MERCURIO_LAB_"
                                "POST_DISABLED"
                            ),
                    }
                )
                .encode(
                    "utf-8"
                )
            ),
        )

    def log_message(
        self,
        format,
        *args,
    ):
        print(
            "[MERCURIO-LAB]",
            format % args,
        )


def run(
    *,
    port=DEFAULT_PORT,
):
    server = MercurioLabServer(
        (
            DEFAULT_HOST,
            int(
                port
            ),
        ),
        MercurioLabHandler,
    )

    url = (
        f"http://{DEFAULT_HOST}:"
        f"{int(port)}"
        f"{DOCUMENT_PATH}"
    )

    print(
        "=" * 72
    )
    print(
        "MERCURIO DOCUMENTATION LAB"
    )
    print(
        "=" * 72
    )
    print(
        f"URL: {url}"
    )
    print(
        "NETWORK: LOCALHOST ONLY"
    )
    print(
        "POST: DISABLED"
    )
    print(
        "=" * 72
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        server.server_close()


def main():
    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
    )

    args = parser.parse_args()

    run(
        port=args.port,
    )


if __name__ == "__main__":
    main()
