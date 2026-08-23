from __future__ import annotations

import argparse
import json
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from tools.mercurio_lab.general_pages import (
    render_general_page,
)
from tools.mercurio_lab.ex01.pages import (
    render_ex01_page,
)
from tools.mercurio_lab.upload_backend import (
    parse_multipart_upload,
    render_upload_table,
)


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8767

DOCUMENT_PATH = (
    "/mercurio/"
    "presentacionTelematicaDocumentacion.html"
)

UPLOAD_PATH = (
    "/mercurio/"
    "uploadDocumento"
)

UPLOAD_RENOVA_PATH = (
    "/mercurio/"
    "uploadDocumentoRenova"
)

MAX_UPLOAD_BODY_BYTES = 12 * 1024 * 1024

ROUTES = {
    DOCUMENT_PATH:
        (
            STATIC_ROOT
            / "documentacion.html"
        ),

    "/mercurio/resources/js/"
    "plupload.full.min.js":
        STATIC_ROOT / "vendor" / "plupload.full.min.js",

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

    "/mercurio/resources/lab/"
    "mercurio_general.js":
        (
            STATIC_ROOT
            / "mercurio_general.js"
        ),

    "/mercurio/resources/lab/"
    "mercurio_general.css":
        (
            STATIC_ROOT
            / "mercurio_general.css"
        ),

    "/mercurio/resources/lab/"
    "mercurio_ex01.js":
        (
            STATIC_ROOT
            / "mercurio_ex01.js"
        ),

    "/mercurio/resources/lab/"
    "mercurio_ex01.css":
        (
            STATIC_ROOT
            / "mercurio_ex01.css"
        ),

    "/mercurio/resources/lab/"
    "calendar.svg":
        (
            STATIC_ROOT
            / "calendar.svg"
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

    ".svg":
        "image/svg+xml",
}


class MercurioLabServer(
    ThreadingHTTPServer
):
    allow_reuse_address = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._upload_lock = Lock()
        self._uploads = []

    def record_upload(self, upload):
        with self._upload_lock:
            self._uploads.append(upload)
            return tuple(self._uploads)


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

        ex01_page = render_ex01_page(
            path
        )

        if ex01_page is not None:
            self._send_bytes(
                status=200,
                content_type=(
                    "text/html; charset=utf-8"
                ),
                body=ex01_page,
            )
            return

        general_page = render_general_page(
            path
        )

        if general_page is not None:
            self._send_bytes(
                status=200,
                content_type=(
                    "text/html; charset=utf-8"
                ),
                body=general_page,
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

    def _handle_upload_post(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_UPLOAD_BODY_BYTES:
            raise ValueError("MERCURIO_LAB_UPLOAD_SIZE_INVALID")

        upload = parse_multipart_upload(
            content_type=self.headers.get("Content-Type", ""),
            body=self.rfile.read(length),
        )
        uploads = self.server.record_upload(upload)
        self._send_bytes(
            status=200,
            content_type="text/html; charset=utf-8",
            body=render_upload_table(uploads).encode("utf-8"),
        )

    def do_POST(
        self,
    ):
        path = urlsplit(self.path).path

        if path in {UPLOAD_PATH, UPLOAD_RENOVA_PATH}:
            try:
                self._handle_upload_post()
            except ValueError as exc:
                self._send_bytes(
                    status=400,
                    content_type="application/json; charset=utf-8",
                    body=json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"),
                )
            return

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

    base_url = (
        f"http://{DEFAULT_HOST}:"
        f"{int(port)}"
        "/"
    )

    document_url = (
        f"http://{DEFAULT_HOST}:"
        f"{int(port)}"
        f"{DOCUMENT_PATH}"
    )

    print(
        "=" * 72
    )
    print(
        "MERCURIO TWIN LAB"
    )
    print(
        "=" * 72
    )
    print(
        f"URL: {base_url}"
    )
    print(
        "EX01 DOCUMENTATION:"
    )
    print(
        document_url
    )
    print(
        "NETWORK: LOCALHOST ONLY"
    )
    print(
        "POST ADMINISTRATIVE: DISABLED"
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
