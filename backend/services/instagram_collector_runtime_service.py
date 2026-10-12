"""CRM-owned, one-shot Instagram runtime; no scheduler or implicit DB setup.

Configuration discovery, collection and cleanup share a single worker.
Never initialize schema or seed a source during startup.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
import re
import threading

from backend.automation.browser_profiles import normalize_browser_profile_key
from backend.services.instagram_collector_configuration_service import InvalidInstagramConfiguration
from backend.trend_intelligence.sources.instagram_browser import (
    InstagramAccessBlockedError,
    InstagramBrowserCollector,
    InstagramCollectionConfig,
    run_instagram_collection,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstagramRuntimeSnapshot:
    status: str
    result: object = None
    error: Exception | None = None
    cleanup_error: Exception | None = None


class InstagramCollectorRuntimeService:
    """One startup attempt per CRM session, including concurrent callers.

    start() and close() return futures without waiting on the UI thread.
    Creation, collection and cleanup all belong to the same worker. Cleanup
    failures retain the collector and worker for a subsequent close() retry.
    An injected ingestion service must refer to an already configured source;
    this runtime never creates a database/schema/source or takes over Chrome.
    """

    def __init__(self, *, enabled=False, config=None, ingestion_service=None,
                 domain_code=None, collector_factory=None, configuration_service=None):
        self._configuration_service = configuration_service
        self._config = config
        self._ingestion_service = ingestion_service
        self._domain_code = domain_code
        self._collector_factory = collector_factory or InstagramBrowserCollector
        self._lock = threading.RLock()
        self._executor = None
        self._collector = None
        self._start_future = None
        self._close_future = None
        self._closing = False
        self._result = None
        self._error = None
        self._cleanup_error = None
        self._status = "DISABLED"
        if configuration_service is not None:
            self._status = "IDLE"
        if enabled is True:
            self._status = "NOT_CONFIGURED"
            if self._valid_configuration():
                self._status = "IDLE"

    def _valid_configuration(self):
        config = self._config
        if not isinstance(config, InstagramCollectionConfig):
            return False
        if type(config.headless) is not bool:
            return False
        if not callable(getattr(self._ingestion_service, "ingest", None)):
            return False
        try:
            if normalize_browser_profile_key(config.profile_key) != config.profile_key:
                return False
        except (ValueError, TypeError):
            return False
        return all(
            re.fullmatch(r"[A-Za-z0-9_.]{1,30}", target.account)
            and target.limit > 0 for target in config.targets
        )

    @property
    def snapshot(self):
        with self._lock:
            return InstagramRuntimeSnapshot(
                self._status, self._result, self._error, self._cleanup_error,
            )

    def start(self):
        with self._lock:
            if self._closing:
                return self._start_future
            if self._start_future is not None:
                return self._start_future
            if self._status != "IDLE":
                logger.info("Instagram runtime: %s", self._status)
                return None
            try:
                self._executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="instagram-runtime",
                )
                self._status = "RUNNING"
                self._start_future = self._executor.submit(self._collect)
            except Exception as exc:
                self._status, self._error = "ERROR", exc
                if self._executor is not None:
                    self._executor.shutdown(wait=False)
                    self._executor = None
                logger.exception("Instagram dispatch failed")
            return self._start_future

    def _collect(self):
        try:
            if self._configuration_service is not None:
                try:
                    startup = self._configuration_service.load()
                except InvalidInstagramConfiguration as exc:
                    with self._lock:
                        self._status, self._error = "NOT_CONFIGURED", exc
                    return None
                with self._lock:
                    self._status = startup.status
                if startup.status != "IDLE":
                    return None
                self._config, self._domain_code = startup.config, startup.domain_code
                if not self._valid_configuration():
                    with self._lock:
                        self._status = "NOT_CONFIGURED"
                    return None
                with self._lock:
                    self._status = "RUNNING"
            with self._lock:
                if self._closing:
                    self._status = "CLOSED"
                    return None
            config = self._config
            self._collector = self._collector_factory(
                profile_key=config.profile_key, headless=config.headless,
            )
            self._collector.start()
            result = run_instagram_collection(
                collector=self._collector, config=config,
                ingestion_service=self._ingestion_service,
                domain_code=self._domain_code,
            )
            with self._lock:
                self._result = result
                self._status = "SUCCESS"
            return result
        except Exception as exc:
            with self._lock:
                self._error = exc  # Keep identity, traceback and chained cause.
                self._status = (
                    "BLOCKED" if isinstance(exc, InstagramAccessBlockedError)
                    else "ERROR"
                )
            logger.exception("Instagram collection failed")
            raise
        finally:
            self._cleanup()

    def _cleanup(self):
        if self._collector is None:
            return True
        try:
            result = self._collector.shutdown()
            if result is not None and not getattr(result, "control_released", False):
                raise RuntimeError("Instagram shutdown did not release ownership")
        except Exception as exc:
            with self._lock:
                self._cleanup_error = exc
                if self._error is None:
                    self._status = "ERROR"
            logger.exception("Instagram cleanup failed; retaining owner for retry")
            return False
        self._collector = None
        return True

    def close(self):
        """Reject new starts; queue orderly cleanup after any in-flight work."""
        with self._lock:
            self._closing = True
            if self._executor is None:
                return self._close_future
            if self._close_future is not None and not self._close_future.done():
                return self._close_future
            self._close_future = self._executor.submit(self._close_on_worker)
            return self._close_future

    def _close_on_worker(self):
        if not self._cleanup():
            return False
        with self._lock:
            executor = self._executor
            self._executor = None
        executor.shutdown(wait=False, cancel_futures=False)
        return True
