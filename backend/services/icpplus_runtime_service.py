"""
Runtime serializado para consultas de disponibilidad ICP Plus.

Responsabilidades:
- ejecutar una única consulta ICP Plus cada vez;
- mantener toda la interacción desktop en un único worker;
- poseer temporalmente el connector durante la consulta;
- garantizar cierre del Chrome propiedad de esa ejecución;
- no conocer Flet;
- no conocer SQLite;
- no conocer expedientes ni clientes.

El connector productivo será IcpPlusDesktopConnector:
Chrome normal + Observer + input físico.
"""

from concurrent.futures import ThreadPoolExecutor
import threading


class IcpPlusRuntimeService:
    def __init__(
        self,
        *,
        connector_factory=None,
    ):
        self.connector_factory = (
            connector_factory
        )

        self._connector = None

        self._executor = None
        self._executor_lock = (
            threading.Lock()
        )

        self._worker_thread_id = None


    @property
    def connector(self):
        return self._connector


    @property
    def running(self):
        return (
            self._connector
            is not None
        )


    def _get_executor(self):
        with self._executor_lock:

            if self._executor is None:
                self._executor = (
                    ThreadPoolExecutor(
                        max_workers=1,
                        thread_name_prefix=(
                            "icpplus-runtime"
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
        # Reentrada segura si en el futuro una operación
        # interna vuelve a atravesar el runtime.
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


    def _resolve_connector_factory(
        self,
    ):
        if (
            self.connector_factory
            is not None
        ):
            return (
                self.connector_factory
            )

        # Import diferido:
        # permite arrancar/testear el ERP mientras completamos
        # la extracción del motor desktop productivo.
        from backend.automation.connectors.icpplus_desktop_connector import (
            IcpPlusDesktopConnector,
        )

        return (
            IcpPlusDesktopConnector
        )


    def _build_connector(self):
        if self._connector is None:

            factory = (
                self._resolve_connector_factory()
            )

            if not callable(factory):
                raise TypeError(
                    "connector_factory "
                    "debe ser callable"
                )

            self._connector = (
                factory()
            )

        return self._connector


    def _check_availability_impl(
        self,
        request,
    ):
        connector = (
            self._build_connector()
        )

        try:
            result = (
                connector
                .check_availability(
                    dict(
                        request
                        or {}
                    )
                )
            )

            if not isinstance(
                result,
                dict,
            ):
                raise RuntimeError(
                    "ICPPLUS_CONNECTOR_RESULT_INVALID"
                )

            return result

        finally:
            # Cada comprobación es one-shot.
            #
            # No dejamos Chrome ICP Plus vivo entre consultas.
            try:
                connector.close()

            finally:
                self._connector = None


    def check_availability(
        self,
        request,
    ):
        return self._run_serialized(
            self._check_availability_impl,
            request,
        )


    def _close_impl(self):
        connector = self._connector

        if connector is None:
            return True

        try:
            return bool(
                connector.close()
            )

        finally:
            self._connector = None


    def close(self):
        # Cierre idempotente.
        #
        # Si el runtime jamás se utilizó, no creamos un worker
        # exclusivamente para cerrarlo.
        with self._executor_lock:
            fully_idle = (
                self._executor is None
                and self._connector is None
            )

        if fully_idle:
            self._worker_thread_id = None
            return True

        result = self._run_serialized(
            self._close_impl
        )

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
