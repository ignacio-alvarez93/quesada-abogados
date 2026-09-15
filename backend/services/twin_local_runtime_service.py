"""Runtime HTTP local para revisiones AUTO TWIN materializadas.

Responsabilidad:

    MaterializedRevision
            ↓
    TwinLocalRuntimeService
            ↓
    127.0.0.1:<ephemeral>/runtime/index.html

El servicio:

- sirve únicamente una revisión física existente;
- escucha exclusivamente en loopback;
- mantiene lifecycle start/status/stop;
- es idempotente por twin + revision;
- no ejecuta Chrome;
- no navega REAL;
- no materializa;
- no valida;
- no promociona ACTIVE.
"""

from __future__ import annotations

import atexit
from functools import partial
from http.server import (
    SimpleHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path
import re
import threading


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

DEFAULT_MATERIALIZED_ROOT = (
    PROJECT_ROOT
    / "data"
    / "qcc"
    / "auto_twin"
    / "materialized"
)


_SAFE_SEGMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)


class _QuietTwinHandler(
    SimpleHTTPRequestHandler
):
    def log_message(
        self,
        format,
        *args,
    ):
        return


class TwinLocalRuntimeService:
    """Owner de runtimes HTTP AUTO TWIN locales."""

    def __init__(
        self,
        *,
        materialized_root=None,
        host="127.0.0.1",
    ):
        self.materialized_root = Path(
            materialized_root
            or DEFAULT_MATERIALIZED_ROOT
        )

        if host != "127.0.0.1":
            raise ValueError(
                "QCC_AUTO_TWIN_LOCAL_RUNTIME_HOST_REJECTED"
            )

        self.host = host

        self._lock = threading.RLock()

        self._runtimes = {}

    def _segment(
        self,
        value,
        *,
        error,
    ):
        value = str(
            value
            or ""
        ).strip()

        if not _SAFE_SEGMENT.fullmatch(
            value
        ):
            raise ValueError(
                error
            )

        return value

    def _revision_dir(
        self,
        *,
        twin_key,
        revision_id,
    ):
        twin_key = self._segment(
            twin_key,
            error=(
                "QCC_AUTO_TWIN_LOCAL_RUNTIME_TWIN_KEY_INVALID"
            ),
        )

        revision_id = self._segment(
            revision_id,
            error=(
                "QCC_AUTO_TWIN_LOCAL_RUNTIME_REVISION_ID_INVALID"
            ),
        )

        directory = (
            self.materialized_root
            / twin_key
            / revision_id
        )

        if not directory.is_dir():
            raise FileNotFoundError(
                "QCC_AUTO_TWIN_LOCAL_RUNTIME_REVISION_NOT_FOUND:"
                + revision_id
            )

        runtime_index = (
            directory
            / "runtime"
            / "index.html"
        )

        if not runtime_index.is_file():
            raise FileNotFoundError(
                "QCC_AUTO_TWIN_LOCAL_RUNTIME_INDEX_NOT_FOUND:"
                + revision_id
            )

        return (
            twin_key,
            revision_id,
            directory,
        )

    def get_status(
        self,
        *,
        twin_key,
    ):
        twin_key = self._segment(
            twin_key,
            error=(
                "QCC_AUTO_TWIN_LOCAL_RUNTIME_TWIN_KEY_INVALID"
            ),
        )

        with self._lock:
            runtime = self._runtimes.get(
                twin_key
            )

            if runtime is None:
                return {
                    "twin_key":
                        twin_key,

                    "status":
                        "STOPPED",

                    "revision_id":
                        None,

                    "host":
                        self.host,

                    "port":
                        None,

                    "base_url":
                        None,

                    "url":
                        None,
                }

            return {
                "twin_key":
                    twin_key,

                "status":
                    "RUNNING",

                "revision_id":
                    runtime[
                        "revision_id"
                    ],

                "host":
                    self.host,

                "port":
                    runtime[
                        "port"
                    ],

                "base_url":
                    runtime[
                        "base_url"
                    ],

                "url":
                    runtime[
                        "url"
                    ],
            }

    def start(
        self,
        *,
        twin_key,
        revision_id,
    ):
        (
            twin_key,
            revision_id,
            revision_dir,
        ) = self._revision_dir(
            twin_key=twin_key,
            revision_id=revision_id,
        )

        with self._lock:
            current = self._runtimes.get(
                twin_key
            )

            if (
                current is not None
                and current[
                    "revision_id"
                ]
                == revision_id
            ):
                return self.get_status(
                    twin_key=twin_key
                )

            if current is not None:
                self._stop_locked(
                    twin_key
                )

            handler = partial(
                _QuietTwinHandler,
                directory=str(
                    revision_dir
                ),
            )

            server = ThreadingHTTPServer(
                (
                    self.host,
                    0,
                ),
                handler,
            )

            server.daemon_threads = True

            port = int(
                server.server_address[1]
            )

            base_url = (
                f"http://{self.host}:{port}"
            )

            url = (
                base_url
                + "/runtime/index.html"
            )

            thread = threading.Thread(
                target=server.serve_forever,
                name=(
                    "qcc-auto-twin-local-"
                    + twin_key
                ),
                daemon=True,
            )

            self._runtimes[
                twin_key
            ] = {
                "revision_id":
                    revision_id,

                "server":
                    server,

                "thread":
                    thread,

                "port":
                    port,

                "base_url":
                    base_url,

                "url":
                    url,
            }

            thread.start()

            return self.get_status(
                twin_key=twin_key
            )

    def _stop_locked(
        self,
        twin_key,
    ):
        runtime = self._runtimes.pop(
            twin_key,
            None,
        )

        if runtime is None:
            return False

        server = runtime[
            "server"
        ]

        thread = runtime[
            "thread"
        ]

        server.shutdown()
        server.server_close()

        if (
            thread.is_alive()
            and thread
            is not threading.current_thread()
        ):
            thread.join(
                timeout=2.0
            )

        return True

    def stop(
        self,
        *,
        twin_key,
    ):
        twin_key = self._segment(
            twin_key,
            error=(
                "QCC_AUTO_TWIN_LOCAL_RUNTIME_TWIN_KEY_INVALID"
            ),
        )

        with self._lock:
            stopped = self._stop_locked(
                twin_key
            )

        result = self.get_status(
            twin_key=twin_key
        )

        result[
            "stopped"
        ] = stopped

        return result

    def stop_all(
        self,
    ):
        with self._lock:
            keys = list(
                self._runtimes
            )

            for twin_key in keys:
                self._stop_locked(
                    twin_key
                )


_DEFAULT_SERVICE = (
    TwinLocalRuntimeService()
)


def get_default_twin_local_runtime_service():
    return _DEFAULT_SERVICE


atexit.register(
    _DEFAULT_SERVICE.stop_all
)
