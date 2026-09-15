"""Runtime SeleniumBase gobernado para AUTO TWIN.

Responsabilidad:

    MaterializedRevision
        ↓
    TwinLocalRuntimeService
        ↓
    localhost exacto de la revisión
        ↓
    BrowserSession SeleniumBase PERSISTENT
        ↓
    Chrome Twin gobernado

Este servicio NO navega REAL y NO hace Discovery.

El navegador Twin es el entorno donde posteriormente se
validarán automatizaciones antes de ejecutarlas contra REAL.
"""

from __future__ import annotations

import atexit
import json
from pathlib import Path
import queue
import re
import threading
from urllib.parse import urljoin

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
from backend.qcc.client.browser_profile_reporter import (
    QccBrowserProfileReporter,
)
from backend.services.twin_local_runtime_service import (
    TwinLocalRuntimeService,
)


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

AUTO_TWIN_BROWSER_START_WAIT_SECONDS = 75.0
AUTO_TWIN_BROWSER_STOP_WAIT_SECONDS = 60.0
AUTO_TWIN_BROWSER_COMMAND_WAIT_SECONDS = 30.0

_SAFE_SEGMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)



# QCC_AUTO_TWIN_BROWSER_SCRIPT_EXECUTION_SURFACE
#
# BrowserSession may expose classic WebDriver semantics:
#
#     execute_script("return ...", *args)
#
# or SeleniumBase CDP semantics:
#
#     evaluate(expression)
#
# A top-level `return` is illegal in CDP evaluate(), therefore CDP
# statements are wrapped in an IIFE and args are transported as JSON.
def _execute_browser_script(
    *,
    browser,
    script,
    args,
):
    script = str(
        script
        or ""
    )

    args = list(
        args
        or []
    )

    evaluator = getattr(
        browser,
        "evaluate",
        None,
    )

    if callable(
        evaluator
    ):
        try:
            encoded_args = json.dumps(
                args,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise TypeError(
                "QCC_AUTO_TWIN_BROWSER_SCRIPT_ARGS_NOT_JSON_SERIALIZABLE"
            ) from exc

        expression = (
            "(function(){\n"
            + script
            + "\n}).apply(null,"
            + encoded_args
            + ")"
        )

        return evaluator(
            expression
        )

    executor = getattr(
        browser,
        "execute_script",
        None,
    )

    if not callable(
        executor
    ):
        raise RuntimeError(
            "QCC_AUTO_TWIN_BROWSER_SCRIPT_EXECUTION_UNAVAILABLE"
        )

    return executor(
        script,
        *args,
    )


class TwinBrowserRuntimeService:
    """Owner de navegadores SeleniumBase AUTO TWIN."""

    def __init__(
        self,
        *,
        materialized_root=None,
        local_runtime_service=None,
        browser_session_factory=None,
        profile_resolver=None,
        browser_open=None,
        reporter_factory=None,
    ):
        self.materialized_root = Path(
            materialized_root
            or DEFAULT_MATERIALIZED_ROOT
        )

        self.local_runtime_service = (
            local_runtime_service
            or TwinLocalRuntimeService(
                materialized_root=(
                    self.materialized_root
                )
            )
        )

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

    def _profile_key(
        self,
        twin_key,
    ):
        return (
            "twin_runtime_"
            + twin_key.lower()
        )

    def _revision_dir(
        self,
        *,
        twin_key,
        revision_id,
    ):
        twin_key = self._segment(
            twin_key,
            error=(
                "QCC_AUTO_TWIN_BROWSER_TWIN_KEY_INVALID"
            ),
        )

        revision_id = self._segment(
            revision_id,
            error=(
                "QCC_AUTO_TWIN_BROWSER_REVISION_ID_INVALID"
            ),
        )

        directory = (
            self.materialized_root
            / twin_key
            / revision_id
        )

        if not directory.is_dir():
            raise FileNotFoundError(
                "QCC_AUTO_TWIN_BROWSER_REVISION_NOT_FOUND:"
                + revision_id
            )

        registry = (
            directory
            / "runtime"
            / "registry.json"
        )

        if not registry.is_file():
            raise FileNotFoundError(
                "QCC_AUTO_TWIN_BROWSER_REGISTRY_NOT_FOUND:"
                + revision_id
            )

        return (
            twin_key,
            revision_id,
            directory,
            registry,
        )

    def _resolve_state(
        self,
        *,
        registry_path,
        pathname=None,
        state_id=None,
    ):
        payload = json.loads(
            registry_path.read_text(
                encoding="utf-8"
            )
        )

        states = payload.get(
            "states"
        )

        if not isinstance(
            states,
            list,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_BROWSER_REGISTRY_STATES_INVALID"
            )

        requested_pathname = str(
            pathname
            or ""
        ).strip()

        requested_state_id = str(
            state_id
            or ""
        ).strip()

        selected = None

        # -------------------------------------------------
        # Exact physical-state authority.
        # -------------------------------------------------
        if requested_state_id:
            matches = [
                state
                for state in states
                if (
                    isinstance(
                        state,
                        dict,
                    )
                    and str(
                        state.get(
                            "state_id"
                        )
                        or ""
                    ).strip()
                    == requested_state_id
                )
            ]

            if not matches:
                raise KeyError(
                    "QCC_AUTO_TWIN_BROWSER_STATE_ID_NOT_FOUND:"
                    + requested_state_id
                )

            if len(matches) != 1:
                raise ValueError(
                    "QCC_AUTO_TWIN_BROWSER_STATE_ID_AMBIGUOUS:"
                    + requested_state_id
                )

            selected = matches[0]

            if (
                requested_pathname
                and str(
                    selected.get(
                        "pathname"
                    )
                    or ""
                ).strip()
                != requested_pathname
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_BROWSER_STATE_ID_PATHNAME_MISMATCH:"
                    + requested_state_id
                )

        # -------------------------------------------------
        # Legacy/UI compatibility.
        #
        # pathname keeps its previous first-match behavior.
        # Causal validation MUST use state_id.
        # -------------------------------------------------
        elif requested_pathname:
            for state in states:
                if not isinstance(
                    state,
                    dict,
                ):
                    continue

                if (
                    str(
                        state.get(
                            "pathname"
                        )
                        or ""
                    )
                    == requested_pathname
                ):
                    selected = state
                    break

            if selected is None:
                raise KeyError(
                    "QCC_AUTO_TWIN_BROWSER_PATHNAME_NOT_FOUND:"
                    + requested_pathname
                )

        else:
            for state in states:
                if isinstance(
                    state,
                    dict,
                ):
                    selected = state
                    break

        if selected is None:
            raise ValueError(
                "QCC_AUTO_TWIN_BROWSER_NO_RUNTIME_STATE"
            )

        runtime_entry = str(
            selected.get(
                "runtime_entry"
            )
            or ""
        ).strip()

        if not runtime_entry:
            raise ValueError(
                "QCC_AUTO_TWIN_BROWSER_RUNTIME_ENTRY_MISSING"
            )

        return (
            selected,
            runtime_entry,
        )

    def _public_status(
        self,
        *,
        twin_key,
        runtime=None,
    ):
        profile_key = self._profile_key(
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

                "pathname":
                    None,

                "url":
                    None,

                "profile_key":
                    profile_key,

                "profile_dir":
                    str(
                        self._profile_resolver(
                            profile_key
                        )
                    ),

                "browser_session_mode":
                    BrowserSessionMode.PERSISTENT.value,

                "qcc_registered":
                    False,

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
                twin_key,

            "status":
                runtime.get(
                    "status"
                )
                or "STOPPED",

            "revision_id":
                runtime.get(
                    "revision_id"
                ),

            "pathname":
                runtime.get(
                    "pathname"
                ),

            "url":
                runtime.get(
                    "url"
                ),

            "profile_key":
                runtime.get(
                    "profile_key"
                ),

            "profile_dir":
                runtime.get(
                    "profile_dir"
                ),

            "browser_session_mode":
                BrowserSessionMode.PERSISTENT.value,

            "qcc_registered":
                runtime.get(
                    "qcc_registered"
                )
                is True,

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
        twin_key = self._segment(
            twin_key,
            error=(
                "QCC_AUTO_TWIN_BROWSER_TWIN_KEY_INVALID"
            ),
        )

        with self._lock:
            return self._public_status(
                twin_key=twin_key,
                runtime=(
                    self._runtimes.get(
                        twin_key
                    )
                ),
            )

    def _run_runtime(
        self,
        *,
        twin_key,
        runtime,
    ):
        """Browser owner thread.

        SeleniumBase nace y muere en este mismo hilo.
        """

        session = None
        shutdown_done = False

        try:
            runtime[
                "owner_thread_id"
            ] = threading.get_ident()

            config = BrowserSessionConfig(
                consumer="auto_twin_runtime",
                mode=(
                    BrowserSessionMode.PERSISTENT
                ),
                headless=False,
                profile_key=(
                    runtime[
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
                runtime[
                    "url"
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
                # QCC es observabilidad fail-open.
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

            # QCC_AUTO_TWIN_BROWSER_OWNER_COMMAND_LOOP
            #
            # SeleniumBase/browser ownership remains in this thread.
            # External callers enqueue bounded commands; they never
            # touch browser/session directly from another thread.
            command_queue = runtime[
                "command_queue"
            ]

            while not runtime[
                "stop_requested"
            ].is_set():
                try:
                    command = (
                        command_queue.get(
                            timeout=0.10
                        )
                    )

                except queue.Empty:
                    continue

                if not isinstance(
                    command,
                    dict,
                ):
                    continue

                done = command.get(
                    "done"
                )

                try:
                    kind = command.get(
                        "kind"
                    )

                    if (
                        kind
                        != "EXECUTE_SCRIPT"
                    ):
                        raise RuntimeError(
                            "QCC_AUTO_TWIN_BROWSER_COMMAND_INVALID"
                        )

                    command[
                        "result"
                    ] = _execute_browser_script(
                        browser=browser,
                        script=command[
                            "script"
                        ],
                        args=(
                            command.get(
                                "args"
                            )
                            or []
                        ),
                    )

                except Exception as exc:
                    command[
                        "error"
                    ] = exc

                finally:
                    if done is not None:
                        done.set()

            with self._lock:
                runtime[
                    "status"
                ] = "STOPPING"

            result = session.shutdown(
                BrowserShutdownMode.CLOSE
            )

            shutdown_done = True

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
            if (
                session is not None
                and not shutdown_done
            ):
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
            if runtime.get(
                "owns_local_runtime"
            ):
                try:
                    self.local_runtime_service.stop(
                        twin_key=twin_key
                    )

                except Exception:
                    pass

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
        revision_id,
        pathname=None,
        state_id=None,
    ):
        (
            twin_key,
            revision_id,
            _revision_dir,
            registry_path,
        ) = self._revision_dir(
            twin_key=twin_key,
            revision_id=revision_id,
        )

        selected_state, runtime_entry = (
            self._resolve_state(
                registry_path=(
                    registry_path
                ),
                pathname=pathname,
                state_id=state_id,
            )
        )

        resolved_pathname = str(
            selected_state.get(
                "pathname"
            )
            or ""
        )

        resolved_state_id = str(
            selected_state.get(
                "state_id"
            )
            or ""
        ).strip()

        if not resolved_state_id:
            raise ValueError(
                "QCC_AUTO_TWIN_BROWSER_STATE_ID_MISSING"
            )

        profile_key = self._profile_key(
            twin_key
        )

        profile_dir = str(
            self._profile_resolver(
                profile_key
            )
        )

        with self._lock:
            current = self._runtimes.get(
                twin_key
            )

            if current is not None:
                current_status = current.get(
                    "status"
                )

                if (
                    current_status
                    in {
                        "STARTING",
                        "RUNNING",
                        "STOPPING",
                    }
                ):
                    if (
                        current.get(
                            "revision_id"
                        )
                        == revision_id
                        and current.get(
                            "pathname"
                        )
                        == resolved_pathname
                        and current.get(
                            "state_id"
                        )
                        == resolved_state_id
                    ):
                        return (
                            self._public_status(
                                twin_key=twin_key,
                                runtime=current,
                            )
                        )

                    raise RuntimeError(
                        "QCC_AUTO_TWIN_BROWSER_ALREADY_RUNNING:"
                        + twin_key
                    )

                self._runtimes.pop(
                    twin_key,
                    None,
                )

            previous_local = (
                self.local_runtime_service
                .get_status(
                    twin_key=twin_key
                )
            )

            owns_local_runtime = not (
                previous_local.get(
                    "status"
                )
                == "RUNNING"
                and previous_local.get(
                    "revision_id"
                )
                == revision_id
            )

            local = (
                self.local_runtime_service
                .start(
                    twin_key=twin_key,
                    revision_id=revision_id,
                )
            )

            base_url = str(
                local.get(
                    "base_url"
                )
                or ""
            ).strip()

            if not base_url:
                raise RuntimeError(
                    "QCC_AUTO_TWIN_BROWSER_LOCAL_BASE_URL_MISSING"
                )

            target_url = urljoin(
                base_url.rstrip("/")
                + "/",
                runtime_entry.lstrip("/"),
            )

            runtime = {
                "revision_id":
                    revision_id,

                "state_id":
                    resolved_state_id,

                "pathname":
                    resolved_pathname,

                "runtime_entry":
                    runtime_entry,

                "url":
                    target_url,

                "profile_key":
                    profile_key,

                "profile_dir":
                    profile_dir,

                "status":
                    "STARTING",

                "qcc_registered":
                    False,

                "owner_thread_id":
                    None,

                "last_error":
                    None,

                "session":
                    None,

                "browser":
                    None,

                "command_queue":
                    queue.Queue(),

                "owns_local_runtime":
                    owns_local_runtime,

                "ready_event":
                    threading.Event(),

                "stop_requested":
                    threading.Event(),

                "stopped_event":
                    threading.Event(),
            }

            thread = threading.Thread(
                target=self._run_runtime,
                kwargs={
                    "twin_key":
                        twin_key,

                    "runtime":
                        runtime,
                },
                name=(
                    "qcc-auto-twin-browser-"
                    + twin_key
                ),
                daemon=True,
            )

            runtime[
                "thread"
            ] = thread

            self._runtimes[
                twin_key
            ] = runtime

            thread.start()

        # SeleniumBase vive en otro hilo.
        runtime[
            "ready_event"
        ].wait(
            timeout=(
                AUTO_TWIN_BROWSER_START_WAIT_SECONDS
            )
        )

        return self.get_status(
            twin_key=twin_key
        )

    def execute_script(
        self,
        *,
        twin_key,
        script,
        args=None,
        timeout=None,
    ):
        """Ejecuta JS exclusivamente en el browser owner thread."""

        twin_key = self._segment(
            twin_key,
            error=(
                "QCC_AUTO_TWIN_BROWSER_TWIN_KEY_INVALID"
            ),
        )

        script = str(
            script
            or ""
        )

        if not script.strip():
            raise ValueError(
                "QCC_AUTO_TWIN_BROWSER_SCRIPT_REQUIRED"
            )

        if args is None:
            args = []

        elif not isinstance(
            args,
            (list, tuple),
        ):
            raise TypeError(
                "QCC_AUTO_TWIN_BROWSER_SCRIPT_ARGS_INVALID"
            )

        wait_seconds = (
            AUTO_TWIN_BROWSER_COMMAND_WAIT_SECONDS
            if timeout is None
            else float(
                timeout
            )
        )

        if wait_seconds <= 0:
            raise ValueError(
                "QCC_AUTO_TWIN_BROWSER_COMMAND_TIMEOUT_INVALID"
            )

        with self._lock:
            runtime = self._runtimes.get(
                twin_key
            )

            if (
                runtime is None
                or runtime.get(
                    "status"
                )
                != "RUNNING"
            ):
                raise RuntimeError(
                    "QCC_AUTO_TWIN_BROWSER_NOT_RUNNING:"
                    + twin_key
                )

            command_queue = runtime.get(
                "command_queue"
            )

            if command_queue is None:
                raise RuntimeError(
                    "QCC_AUTO_TWIN_BROWSER_COMMAND_QUEUE_MISSING"
                )

            command = {
                "kind":
                    "EXECUTE_SCRIPT",

                "script":
                    script,

                "args":
                    list(
                        args
                    ),

                "done":
                    threading.Event(),

                "result":
                    None,

                "error":
                    None,
            }

            command_queue.put(
                command
            )

        completed = command[
            "done"
        ].wait(
            timeout=wait_seconds
        )

        if not completed:
            raise TimeoutError(
                "QCC_AUTO_TWIN_BROWSER_COMMAND_TIMEOUT:"
                + twin_key
            )

        error = command.get(
            "error"
        )

        if error is not None:
            raise RuntimeError(
                "QCC_AUTO_TWIN_BROWSER_COMMAND_FAILED:"
                + str(
                    error
                )
            ) from error

        return command.get(
            "result"
        )

    def stop(
        self,
        *,
        twin_key,
    ):
        twin_key = self._segment(
            twin_key,
            error=(
                "QCC_AUTO_TWIN_BROWSER_TWIN_KEY_INVALID"
            ),
        )

        with self._lock:
            runtime = self._runtimes.get(
                twin_key
            )

            if runtime is None:
                return self._public_status(
                    twin_key=twin_key,
                    runtime=None,
                )

            runtime[
                "stop_requested"
            ].set()

        runtime[
            "stopped_event"
        ].wait(
            timeout=(
                AUTO_TWIN_BROWSER_STOP_WAIT_SECONDS
            )
        )

        with self._lock:
            result = self._public_status(
                twin_key=twin_key,
                runtime=runtime,
            )

            if result[
                "status"
            ] in {
                "STOPPED",
                "ERROR",
            }:
                self._runtimes.pop(
                    twin_key,
                    None,
                )

            return result

    def stop_all(
        self,
    ):
        with self._lock:
            keys = list(
                self._runtimes
            )

        for twin_key in keys:
            try:
                self.stop(
                    twin_key=twin_key
                )

            except Exception:
                pass


_DEFAULT_SERVICE = (
    TwinBrowserRuntimeService()
)


def get_default_twin_browser_runtime_service():
    return _DEFAULT_SERVICE


atexit.register(
    _DEFAULT_SERVICE.stop_all
)
