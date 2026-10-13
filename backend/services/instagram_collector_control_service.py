"""Application controller shared by authenticated startup and the IT view.

The existing runtime is one-shot, so every execution builds a fresh runtime,
waits for its collection and closes it on a dedicated worker. A single
controller per CRM session provides single-flight for autostart and manual
runs. Reading state or saving settings never creates a runtime or browser.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging
import re
import threading
from uuid import uuid4

from backend.services.instagram_collector_configuration_service import (
    InstagramCollectorConfigurationService,
    InvalidInstagramConfiguration,
    SETTINGS_KEY,
    create_crm_instagram_runtime,
)


logger = logging.getLogger(__name__)

ACCOUNT_PATTERN = re.compile(r"[A-Za-z0-9_.]{1,30}")
FAILURE_STATUSES = {"ERROR", "BLOCKED", "NOT_CONFIGURED"}


class _CandidateLookup:
    """Validate unsaved settings against the registered source/domain."""

    def __init__(self, lookup, value):
        self._lookup, self._value = lookup, value

    def get_config(self, key, default=None):
        return json.dumps(self._value) if key == SETTINGS_KEY else default

    def get_source_by_code(self, code):
        return self._lookup.get_source_by_code(code)

    def get_domain_by_code(self, code):
        return self._lookup.get_domain_by_code(code)


class InstagramCollectorControlService:
    def __init__(self, *, lookup, save_setting, repository, runtime_factory=create_crm_instagram_runtime):
        self.lookup, self.save_setting, self.repository = lookup, save_setting, repository
        self.configuration = InstagramCollectorConfigurationService(lookup)
        self.runtime_factory = runtime_factory
        self._lock = threading.RLock()
        self._future = self._runtime = None
        self._closed = False
        self._autostart = False
        self._history = []
        self._status = "IDLE"

    def settings(self):
        raw = self.lookup.get_config(SETTINGS_KEY)
        value = json.loads(raw) if raw else {}
        if not isinstance(value, dict):
            raise ValueError("Invalid settings")
        return value

    def _busy(self):
        return bool(self._future and not self._future.done())

    def save(self, enabled, accounts, limit):
        accounts = [a.strip().lstrip("@") for a in accounts if a and a.strip()]
        if type(enabled) is not bool or type(limit) is not int or limit < 1:
            raise ValueError("Configuración inválida")
        if any(not ACCOUNT_PATTERN.fullmatch(a) for a in accounts):
            raise ValueError("Cuenta inválida")
        with self._lock:
            if self._closed or self._runtime is not None or self._busy():
                raise ValueError("Espere al cierre de la ejecución")
            value = self.settings()
            value.update(enabled=enabled, accounts=[dict(account=a, limit=limit) for a in dict.fromkeys(accounts)])
            # Fail before writing: enabling requires the registered source,
            # domain and governed profile already stored in the settings.
            InstagramCollectorConfigurationService(_CandidateLookup(self.lookup, value)).load()
            self.save_setting(SETTINGS_KEY, json.dumps(value))

    def start(self):
        """Authenticated autostart: once per session and never after a manual run."""
        with self._lock:
            if self._autostart:
                return self._future
            self._autostart = True
            if self._history or self._busy():
                return self._future
            return self.execute()

    def execute(self):
        with self._lock:
            if self._closed:
                return None
            if self._runtime is not None or self._busy():
                return self._future
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="instagram-control")
            self._status = "RUNNING"
            self._future = executor.submit(self._run)
            self._future.add_done_callback(lambda _: executor.shutdown(wait=False))
            return self._future

    def _run(self):
        record = dict(id=uuid4().hex, date=datetime.now(timezone.utc).isoformat(), status="ERROR", result=None, error=None)
        runtime = None
        try:
            try:
                startup = self.configuration.load()
            except InvalidInstagramConfiguration:
                record.update(status="NOT_CONFIGURED", error="INVALID_CONFIGURATION")
                return
            record["status"] = startup.status
            if startup.status != "IDLE":
                return
            with self._lock:
                if self._closed:
                    record["status"] = "CLOSED"
                    return
                runtime = self.runtime_factory()
                self._runtime = runtime
                future = runtime.start()
            if future is not None:
                future.result()
            snapshot = runtime.snapshot
            record.update(status=snapshot.status, result=snapshot.result)
            if snapshot.status in FAILURE_STATUSES:
                record["error"] = "COLLECTION_FAILED"
        except Exception as exc:
            status = runtime.snapshot.status if runtime is not None else "ERROR"
            record.update(status=status if status in FAILURE_STATUSES else "ERROR", error="COLLECTION_FAILED")
            logger.error("Instagram control ref=%s error=%s", record["id"], type(exc).__name__)
        finally:
            released = self._close_runtime(runtime)
            if not released:
                record.update(status="CLEANUP_REQUIRED", error="OWNERSHIP_RETAINED")
            with self._lock:
                if released:
                    self._runtime = None
                self._status = record["status"]
                self._history.append(record)

    @staticmethod
    def _close_runtime(runtime):
        """True once the runtime holds no collector or worker.

        close() returns None when the runtime never owned a worker.
        """
        if runtime is None:
            return True
        try:
            closing = runtime.close()
            return closing is None or closing.result() is True
        except Exception as exc:
            logger.error("Instagram control cleanup error=%s", type(exc).__name__)
            return False

    def close(self):
        with self._lock:
            self._closed = True
        return self.retry_cleanup()

    def retry_cleanup(self):
        with self._lock:
            if self._busy():
                return self._future
            if self._runtime is None:
                return None
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="instagram-cleanup")
            self._future = executor.submit(self._release)
            self._future.add_done_callback(lambda _: executor.shutdown(wait=False))
            return self._future

    def _release(self):
        released = self._close_runtime(self._runtime)
        if released:
            with self._lock:
                self._runtime = None
                self._status = "CLOSED"
        return released

    def state(self):
        with self._lock:
            busy = self._busy()
            history = [dict(r) for r in self._history]
            status = self._status
            retained = self._runtime is not None
        problem = None
        try:
            settings = self.settings()
        except (ValueError, TypeError):
            settings, problem = {}, "INVALID_SETTINGS"
        try:
            effective = self.configuration.load().status
        except InvalidInstagramConfiguration:
            effective, problem = "NOT_CONFIGURED", problem or "INVALID_CONFIGURATION"
        latest = history[-1] if history else None
        rows = []
        if latest and latest["result"]:
            for observation_id in dict.fromkeys(latest["result"].observation_ids):
                observation = self.repository.get_observation(observation_id)
                if observation:
                    rows.append(observation)
        return dict(settings=settings, status=status if history or busy else effective,
                    busy=busy, retained=retained, effective=effective, problem=problem,
                    history=history, latest=latest, rows=rows)


def create_crm_instagram_control():
    """Compose lazily: constructors perform no reads or browser operations."""
    from backend.repositories.instagram_collector_settings_repository import (
        SQLiteInstagramCollectorSettingsRepository,
    )
    from backend.repositories.sqlite_trend_intelligence_repository import (
        SQLiteTrendIntelligenceReadOnlyLookup, SQLiteTrendIntelligenceRepository,
    )
    from backend.services.config_service import DB_PATH

    # config_service.set_config() runs ensure_config_runtime_schema(), which may
    # migrate tables; the settings repository only writes the existing store.
    return InstagramCollectorControlService(
        lookup=SQLiteTrendIntelligenceReadOnlyLookup(DB_PATH),
        repository=SQLiteTrendIntelligenceRepository(DB_PATH),
        save_setting=SQLiteInstagramCollectorSettingsRepository(DB_PATH).save,
    )
