"""
Runtime persistente de DEHú para la sesión del ERP.

Responsabilidades:
- mantener una única instancia de DehuConnector;
- preservar afinidad de hilo SeleniumBase/CDP;
- iniciar Chrome de forma perezosa;
- serializar navegación y capturas;
- respetar ownership cuando el cierre falla.

No contiene SQL.
No conoce Flet.
No conoce SeleniumBase directamente.
"""

from concurrent.futures import (
    ThreadPoolExecutor,
)
import threading

from backend.automation.connectors.dehu_connector import (
    DehuConnector,
)


class DehuRuntimeService:
    def __init__(
        self,
        *,
        profile_key="dehu",
        headless=False,
        connector_factory=None,
    ):
        self.profile_key = str(
            profile_key
            or "dehu"
        ).strip()

        if not self.profile_key:
            raise ValueError(
                "profile_key de DEHú vacío"
            )

        self.headless = bool(
            headless
        )

        self.connector_factory = (
            connector_factory
            or DehuConnector
        )

        if not callable(
            self.connector_factory
        ):
            raise TypeError(
                "connector_factory debe ser callable"
            )

        self._connector = None

        # Toda interacción SeleniumBase/CDP debe conservar
        # afinidad con un único hilo durante la vida del runtime.
        self._executor = None
        self._executor_lock = (
            threading.Lock()
        )
        self._worker_thread_id = None

    @property
    def connector(
        self,
    ):
        return self._connector

    @property
    def started(
        self,
    ):
        return bool(
            self._connector
            and self._connector.browser
        )

    def _get_executor(
        self,
    ):
        with self._executor_lock:
            if self._executor is None:
                self._executor = (
                    ThreadPoolExecutor(
                        max_workers=1,
                        thread_name_prefix=(
                            "dehu-runtime"
                        ),
                    )
                )

            return self._executor

    def _execute_on_worker(
        self,
        callable_,
        *args,
        **kwargs,
    ):
        self._worker_thread_id = (
            threading.get_ident()
        )

        return callable_(
            *args,
            **kwargs,
        )

    def _run_serialized(
        self,
        callable_,
        *args,
        **kwargs,
    ):
        # Permite reentrada si una operación interna vuelve
        # a utilizar el runtime desde su propio worker.
        if (
            self._worker_thread_id
            == threading.get_ident()
        ):
            return callable_(
                *args,
                **kwargs,
            )

        executor = (
            self._get_executor()
        )

        future = executor.submit(
            self._execute_on_worker,
            callable_,
            *args,
            **kwargs,
        )

        return future.result()

    def _build_connector(
        self,
    ):
        if self._connector is None:
            self._connector = (
                self.connector_factory(
                    profile_key=(
                        self.profile_key
                    ),
                    headless=(
                        self.headless
                    ),
                )
            )

        return self._connector

    def _start_impl(
        self,
    ):
        connector = (
            self._build_connector()
        )

        if not connector.browser:
            connector.start()

        return connector

    def start(
        self,
    ):
        return self._run_serialized(
            self._start_impl
        )

    def _open_portal_impl(
        self,
        url=None,
    ):
        connector = (
            self._start_impl()
        )

        return connector.open_portal(
            url
        )

    def open_portal(
        self,
        url=None,
    ):
        return self._run_serialized(
            self._open_portal_impl,
            url,
        )

    def _capture_impl(
        self,
        label,
    ):
        if not self.started:
            raise RuntimeError(
                "DEHú no está iniciado"
            )

        return self._connector.capture(
            label
        )

    def capture(
        self,
        label,
    ):
        return self._run_serialized(
            self._capture_impl,
            label,
        )

    def _close_impl(
        self,
    ):
        connector = (
            self._connector
        )

        if connector is None:
            return False

        # DehuConnector conserva BrowserSession/browser
        # cuando el shutdown gobernado no se completa.
        closed = bool(
            connector.close()
        )

        if not closed:
            return False

        self._connector = None

        return True

    def close(
        self,
    ):
        result = self._run_serialized(
            self._close_impl
        )

        # Si sigue existiendo connector, todavía existe
        # ownership potencial del navegador.
        #
        # Conservamos el mismo worker para que un retry de
        # shutdown mantenga afinidad SeleniumBase/CDP.
        if (
            self._connector is not None
            and not result
        ):
            return False

        with self._executor_lock:
            executor = self._executor
            self._executor = None

        if executor is not None:
            executor.shutdown(
                wait=True,
                cancel_futures=False,
            )

        self._worker_thread_id = None

        return result
