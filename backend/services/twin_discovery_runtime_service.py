"""Runtime gobernado de navegadores AUTO TWIN Discovery.

Arquitectura:

    Flet
      ↓ start / stop
    TwinDiscoveryRuntimeService
      ↓
    dedicated browser owner thread
      ↓
    SeleniumBaseBrowserSession
      ↓
    Chrome PERSISTENT
      ↓
    QCC + Mercurio REAL

El hilo propietario:

- crea SeleniumBase;
- abre la URL inicial;
- conserva vivo el BrowserSession;
- ejecuta su shutdown.

Flet nunca crea ni destruye directamente el navegador.

QCC se instala manualmente una sola vez dentro del perfil
persistente ``twin_discovery``.
"""

from __future__ import annotations

import atexit
import threading

from backend.automation.browser_actions import (
    open_url,
)
from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionMode,
    BrowserShutdownMode,
)
from backend.automation.browser_profiles import (
    get_browser_profile_dir,
)
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)
from backend.qcc.auto_twin.profile_policy import (
    AUTO_TWIN_DISCOVERY_PROFILE_KEY,
    build_auto_twin_profile_policy,
)
from backend.qcc.client.browser_profile_reporter import (
    QccBrowserProfileReporter,
)


AUTO_TWIN_DISCOVERY_EXTENSION_MODE = (
    "MANUAL_PERSISTENT"
)

AUTO_TWIN_DISCOVERY_START_WAIT_SECONDS = 75.0
AUTO_TWIN_DISCOVERY_STOP_WAIT_SECONDS = 60.0


MERCURIO_DISCOVERY_URL = (
    "https://mercurio.delegaciondelgobierno.gob.es"
    "/mercurio/inicioMercurio.html"
)


RED_SARA_DISCOVERY_URL = (
    "https://reg.redsara.es/es/"
)


DISCOVERY_TARGETS = {
    "mercurio": {
        "site_code":
            "MERCURIO",

        "label":
            "Mercurio",

        "initial_url":
            MERCURIO_DISCOVERY_URL,

        "profile_key":
            AUTO_TWIN_DISCOVERY_PROFILE_KEY,
    },
    "red_sara": {
        "site_code":
            "RED_SARA",

        "label":
            "Red SARA",

        "initial_url":
            RED_SARA_DISCOVERY_URL,

        "profile_key":
            AUTO_TWIN_DISCOVERY_PROFILE_KEY,
    },
}


class TwinDiscoveryRuntimeService:
    """Owner coordinador de BrowserSession Discovery."""

    def __init__(
        self,
        *,
        browser_session_factory=None,
        profile_resolver=None,
        browser_open=None,
        reporter_factory=None,
    ):
        self._browser_session_factory = (
            browser_session_factory
            or SeleniumBaseBrowserSession
        )

        self._profile_resolver = (
            profile_resolver
            or get_browser_profile_dir
        )

        self._browser_open = (
            browser_open
            or open_url
        )

        self._reporter_factory = (
            reporter_factory
            or QccBrowserProfileReporter
        )

        self._lock = (
            threading.RLock()
        )

        self._runtimes = {}

    def _target(
        self,
        twin_key,
    ):
        key = str(
            twin_key
            or ""
        ).strip()

        target = DISCOVERY_TARGETS.get(
            key
        )

        if target is None:
            raise KeyError(
                "QCC_AUTO_TWIN_DISCOVERY_TARGET_UNKNOWN:"
                + key
            )

        return key, target

    def _public_status(
        self,
        *,
        key,
        target,
        runtime=None,
    ):
        if runtime is None:
            profile_dir = str(
                self._profile_resolver(
                    target[
                        "profile_key"
                    ]
                )
            )

            return {
                "twin_key":
                    key,

                "site_code":
                    target[
                        "site_code"
                    ],

                "status":
                    "STOPPED",

                "profile_key":
                    target[
                        "profile_key"
                    ],

                "browser_session_mode":
                    BrowserSessionMode.PERSISTENT.value,

                "initial_url":
                    target[
                        "initial_url"
                    ],

                "qcc_registered":
                    False,

                "qcc_extension_mode":
                    AUTO_TWIN_DISCOVERY_EXTENSION_MODE,

                "profile_dir":
                    profile_dir,

                "owner_thread_id":
                    None,

                "owner_thread_alive":
                    False,

                "last_error":
                    None,
            }

        thread = runtime.get(
            "thread"
        )

        return {
            "twin_key":
                key,

            "site_code":
                target[
                    "site_code"
                ],

            "status":
                runtime.get(
                    "status"
                )
                or "STOPPED",

            "profile_key":
                target[
                    "profile_key"
                ],

            "browser_session_mode":
                BrowserSessionMode.PERSISTENT.value,

            "initial_url":
                target[
                    "initial_url"
                ],

            "qcc_registered":
                runtime.get(
                    "qcc_registered"
                )
                is True,

            "qcc_extension_mode":
                AUTO_TWIN_DISCOVERY_EXTENSION_MODE,

            "profile_dir":
                runtime[
                    "profile_dir"
                ],

            "owner_thread_id":
                runtime.get(
                    "owner_thread_id"
                ),

            "owner_thread_alive":
                bool(
                    thread is not None
                    and thread.is_alive()
                ),

            "last_error":
                runtime.get(
                    "last_error"
                ),
        }

    def get_status(
        self,
        *,
        twin_key,
    ):
        key, target = self._target(
            twin_key
        )

        with self._lock:
            runtime = (
                self._runtimes.get(
                    key
                )
            )

            return self._public_status(
                key=key,
                target=target,
                runtime=runtime,
            )

    def _run_runtime(
        self,
        *,
        key,
        target,
        runtime,
    ):
        """Browser owner thread.

        SeleniumBase nace y muere en este mismo hilo.
        """

        session = None

        try:
            runtime[
                "owner_thread_id"
            ] = threading.get_ident()

            config = BrowserSessionConfig(
                consumer=(
                    "auto_twin_discovery"
                ),
                mode=(
                    BrowserSessionMode.PERSISTENT
                ),
                headless=False,
                profile_key=(
                    target[
                        "profile_key"
                    ]
                ),
            )

            session = (
                self._browser_session_factory(
                    config=config,
                    profile_resolver=(
                        self._profile_resolver
                    ),
                )
            )

            browser = session.start()

            self._browser_open(
                browser,
                target[
                    "initial_url"
                ],
            )

            qcc_registered = False

            try:
                qcc_registered = bool(
                    self._reporter_factory(
                        browser_profile_key=(
                            session
                            .identity
                            .profile_key
                        ),
                        browser_session_mode=(
                            session
                            .identity
                            .mode
                        ),
                    ).register()
                )

            except Exception:
                # QCC continúa siendo observabilidad
                # fail-open respecto del browser lifecycle.
                qcc_registered = False

            with self._lock:
                runtime[
                    "session"
                ] = session

                runtime[
                    "browser"
                ] = browser

                runtime[
                    "qcc_registered"
                ] = qcc_registered

                runtime[
                    "status"
                ] = "RUNNING"

                runtime[
                    "last_error"
                ] = None

            runtime[
                "ready_event"
            ].set()

            # El BrowserSession permanece vivo aquí.
            #
            # No existe loop de automatización:
            # el usuario navega libremente por Mercurio.
            runtime[
                "stop_requested"
            ].wait()

            with self._lock:
                runtime[
                    "status"
                ] = "STOPPING"

            result = session.shutdown(
                BrowserShutdownMode.CLOSE
            )

            has_error = bool(
                result is not None
                and getattr(
                    result,
                    "has_error",
                    False,
                )
            )

            with self._lock:
                if has_error:
                    runtime[
                        "status"
                    ] = "ERROR"

                    runtime[
                        "last_error"
                    ] = str(
                        getattr(
                            result,
                            "error",
                            None,
                        )
                        or "shutdown_failed"
                    )

                else:
                    runtime[
                        "status"
                    ] = "STOPPED"

                    runtime[
                        "last_error"
                    ] = None

        except Exception as exc:
            # Si el startup llegó a crear sesión,
            # cualquier cleanup también ocurre en
            # este mismo owner thread.
            if session is not None:
                try:
                    session.shutdown(
                        BrowserShutdownMode.CLOSE
                    )

                except Exception:
                    pass

            with self._lock:
                runtime[
                    "status"
                ] = "ERROR"

                runtime[
                    "last_error"
                ] = (
                    f"{type(exc).__name__}: {exc}"
                )

            runtime[
                "ready_event"
            ].set()

        finally:
            runtime[
                "ready_event"
            ].set()

            runtime[
                "stopped_event"
            ].set()

    def start(
        self,
        *,
        twin_key,
    ):
        key, target = self._target(
            twin_key
        )

        policy = (
            build_auto_twin_profile_policy(
                target[
                    "profile_key"
                ]
            )
        )

        if (
            not policy.active_discovery
            or not policy.deep_capture
        ):
            raise RuntimeError(
                "QCC_AUTO_TWIN_DISCOVERY_POLICY_REJECTED"
            )

        profile_dir = str(
            self._profile_resolver(
                target[
                    "profile_key"
                ]
            )
        )

        with self._lock:
            # Un mismo perfil persistente solo puede tener
            # un BrowserSession owner simultáneo.
            #
            # Hoy Mercurio y Red SARA reutilizan
            # ``twin_discovery`` secuencialmente.
            for other_key, other_runtime in (
                self._runtimes.items()
            ):
                if other_key == key:
                    continue

                if (
                    other_runtime.get(
                        "status"
                    )
                    in {
                        "STARTING",
                        "RUNNING",
                        "STOPPING",
                    }
                ):
                    raise RuntimeError(
                        "QCC_AUTO_TWIN_DISCOVERY_PROFILE_BUSY:"
                        + target[
                            "profile_key"
                        ]
                    )

            current = (
                self._runtimes.get(
                    key
                )
            )

            if current is not None:
                status = current.get(
                    "status"
                )

                if status in {
                    "STARTING",
                    "RUNNING",
                    "STOPPING",
                }:
                    return (
                        self._public_status(
                            key=key,
                            target=target,
                            runtime=current,
                        )
                    )

                # ERROR / STOPPED:
                # nueva ejecución gobernada.
                self._runtimes.pop(
                    key,
                    None,
                )

            runtime = {
                "status":
                    "STARTING",

                "profile_dir":
                    profile_dir,

                "session":
                    None,

                "browser":
                    None,

                "qcc_registered":
                    False,

                "owner_thread_id":
                    None,

                "last_error":
                    None,

                "ready_event":
                    threading.Event(),

                "stop_requested":
                    threading.Event(),

                "stopped_event":
                    threading.Event(),

                "thread":
                    None,
            }

            thread = threading.Thread(
                target=self._run_runtime,
                kwargs={
                    "key":
                        key,

                    "target":
                        target,

                    "runtime":
                        runtime,
                },
                name=(
                    "qcc-auto-twin-discovery-"
                    + key
                ),
                daemon=True,
            )

            runtime[
                "thread"
            ] = thread

            self._runtimes[
                key
            ] = runtime

            thread.start()

        # Esperamos fuera del lock.
        #
        # SeleniumBase está ejecutándose en otro hilo,
        # por lo que nunca entra en el event loop de Flet.
        runtime[
            "ready_event"
        ].wait(
            timeout=(
                AUTO_TWIN_DISCOVERY_START_WAIT_SECONDS
            )
        )

        return self.get_status(
            twin_key=key
        )

    def stop(
        self,
        *,
        twin_key,
    ):
        key, target = self._target(
            twin_key
        )

        with self._lock:
            runtime = (
                self._runtimes.get(
                    key
                )
            )

            if runtime is None:
                return (
                    self._public_status(
                        key=key,
                        target=target,
                        runtime=None,
                    )
                )

            runtime[
                "stop_requested"
            ].set()

        # El shutdown ocurre en el browser owner thread.
        runtime[
            "stopped_event"
        ].wait(
            timeout=(
                AUTO_TWIN_DISCOVERY_STOP_WAIT_SECONDS
            )
        )

        with self._lock:
            status = runtime.get(
                "status"
            )

            if status == "STOPPED":
                self._runtimes.pop(
                    key,
                    None,
                )

                return (
                    self._public_status(
                        key=key,
                        target=target,
                        runtime=None,
                    )
                )

            return self._public_status(
                key=key,
                target=target,
                runtime=runtime,
            )

    def stop_all(
        self,
    ):
        with self._lock:
            keys = list(
                self._runtimes
            )

        # Primero señalamos todos.
        for key in keys:
            with self._lock:
                runtime = (
                    self._runtimes.get(
                        key
                    )
                )

                if runtime is not None:
                    runtime[
                        "stop_requested"
                    ].set()

        # Después esperamos cada owner.
        for key in keys:
            with self._lock:
                runtime = (
                    self._runtimes.get(
                        key
                    )
                )

            if runtime is None:
                continue

            runtime[
                "stopped_event"
            ].wait(
                timeout=(
                    AUTO_TWIN_DISCOVERY_STOP_WAIT_SECONDS
                )
            )


_DEFAULT_DISCOVERY_RUNTIME = (
    TwinDiscoveryRuntimeService()
)


def get_default_twin_discovery_runtime_service():
    return _DEFAULT_DISCOVERY_RUNTIME


atexit.register(
    _DEFAULT_DISCOVERY_RUNTIME.stop_all
)
