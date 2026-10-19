"""
Trend Intelligence · clasificación inmediata tras una recogida (TI-4C.3E3A2).

Única excepción autorizada por docs/resolutions/
20261017_ti_analisis_inmediato_contrato.md: tras una recogida correcta y con
el navegador ya liberado, recorre classify_pending sobre el dominio de esa
recogida. Nada más: ni ventanas diarias, ni snapshots, ni scoring. Un único
lote de posts nunca es una tendencia; el resultado es provisional.

- Store explícito, absoluto y canónico (Path.resolve), EXISTING-ONLY: la
  factoría del productor abre en mode=rw y un fichero ausente da NO_STORE
  sin crearlo. Ninguna escritura fuera del repositorio del productor.
- Lock OS compartido con el CLI manual (backend.trend_intelligence.
  process_lock), adquirido ANTES de componer el productor y liberado en
  finally. Ocupado -> BUSY sin esperar; cualquier otro fallo -> LOCK_ERROR
  (fail closed, no se clasifica).
- Recorrido acotado: como máximo max_batches lotes de limit observaciones.
  Sin agotar el dominio -> INCOMPLETE con el cursor para reanudar.
- Conteos separados: scan_* describen todo lo recorrido en el dominio
  (incluidas observaciones históricas); run_* solo cuentan las
  observaciones recogidas por ESTE run. Nunca se atribuyen al run.
- La proyección no contiene captions, URLs, cuentas, cookies ni mensajes de
  error: solo códigos, contadores y el tipo de excepción.

Sin SQL, sin UI, sin navegador, sin hilos ni procesos.
"""

from dataclasses import dataclass
import logging
from pathlib import Path

from backend.trend_intelligence.process_lock import (
    ProcessLockBusy,
    acquire_process_lock,
)
from backend.trend_intelligence.producer import (
    DEFAULT_CLASSIFY_LIMIT,
    MAX_CLASSIFY_LIMIT,
    OUTCOME_ALREADY_CLASSIFIED,
    OUTCOME_AMBIGUOUS,
    OUTCOME_CLASSIFIED,
    OUTCOME_UNMATCHED,
    STATUS_NO_DOMAIN,
    STATUS_OK,
    create_trend_producer,
)


logger = logging.getLogger(__name__)

STATUS_SKIPPED = "SKIPPED"
STATUS_INVALID_STORE = "INVALID_STORE"
STATUS_BUSY = "BUSY"
STATUS_LOCK_ERROR = "LOCK_ERROR"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_ERROR = "ERROR"

DEFAULT_MAX_BATCHES = 10
MAX_BATCHES_HARD_CAP = 20

_RUN_COUNTERS = {
    OUTCOME_CLASSIFIED: "run_classified",
    OUTCOME_ALREADY_CLASSIFIED: "run_already_classified",
    OUTCOME_UNMATCHED: "run_unmatched",
    OUTCOME_AMBIGUOUS: "run_ambiguous",
}
_SCAN_COUNTERS = ("processed", "classified", "already_classified", "unmatched", "ambiguous")


@dataclass(frozen=True, slots=True)
class PostCollectionClassification:
    status: str
    domain_code: str | None = None
    after_id: int = 0
    next_after_id: int = 0
    batches: int = 0
    exhausted: bool = False
    # Whole domain walk (may include historical observations).
    scan_processed: int = 0
    scan_classified: int = 0
    scan_already_classified: int = 0
    scan_unmatched: int = 0
    scan_ambiguous: int = 0
    # Only the observations collected by this run.
    run_observations: int = 0
    run_classified: int = 0
    run_already_classified: int = 0
    run_unmatched: int = 0
    run_ambiguous: int = 0
    run_not_reached: int = 0
    missing_tables: tuple[str, ...] = ()
    error_type: str | None = None

    def projection(self):
        """Sanitized, provisional view: codes and counters only."""
        return dict(
            status=self.status,
            provisional=True,
            trend_scoring="NOT_COMPUTED",
            domain_code=self.domain_code,
            cursor=dict(after_id=self.after_id, next_after_id=self.next_after_id,
                        batches=self.batches, exhausted=self.exhausted),
            scan=dict(processed=self.scan_processed, classified=self.scan_classified,
                      already_classified=self.scan_already_classified,
                      unmatched=self.scan_unmatched, ambiguous=self.scan_ambiguous),
            run=dict(observations=self.run_observations, classified=self.run_classified,
                     already_classified=self.run_already_classified, unmatched=self.run_unmatched,
                     ambiguous=self.run_ambiguous, not_reached=self.run_not_reached),
            missing_tables=list(self.missing_tables),
            error_type=self.error_type,
        )


def _bounded_int(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} debe ser entero entre 1 y {maximum}")
    return value


def _run_ids(observation_ids):
    ids = tuple(dict.fromkeys(observation_ids or ()))
    if any(type(value) is not int or value < 1 for value in ids):
        raise ValueError("observation_ids deben ser enteros positivos")
    return ids


class TrendPostCollectionService:
    def __init__(self, *, producer_factory=create_trend_producer, lock=acquire_process_lock,
                 limit=DEFAULT_CLASSIFY_LIMIT, max_batches=DEFAULT_MAX_BATCHES):
        # Nothing is opened here: the factory is only called under the lock.
        self.producer_factory = producer_factory
        self.lock = lock
        self.limit = _bounded_int(limit, "limit", MAX_CLASSIFY_LIMIT)
        self.max_batches = _bounded_int(max_batches, "max_batches", MAX_BATCHES_HARD_CAP)

    def classify_after_collection(self, *, db_path, domain_code, collection_ok, browser_closed,
                                  observation_ids=()):
        """Classify the domain of a finished collection; never before cleanup.

        The walk starts just before the oldest observation of the run so that
        the run is covered within the bounded batches; older pending history
        stays for reclassify_existing.
        """
        if collection_ok is not True or browser_closed is not True:
            return PostCollectionClassification(STATUS_SKIPPED)
        ids = _run_ids(observation_ids)
        return self._classify(db_path, domain_code, after_id=min(ids) - 1 if ids else 0, run_ids=ids)

    def reclassify_existing(self, *, db_path, domain_code, after_id=0):
        """Idempotent re-run over already stored observations; no collection."""
        if type(after_id) is not int or after_id < 0:
            raise ValueError("after_id debe ser entero >= 0")
        return self._classify(db_path, domain_code, after_id=after_id, run_ids=())

    def _classify(self, db_path, domain_code, *, after_id, run_ids):
        base = dict(after_id=after_id, next_after_id=after_id, run_observations=len(run_ids),
                    run_not_reached=len(run_ids))
        if not isinstance(domain_code, str) or not domain_code.strip():
            # The collection stored no domain link: nothing to classify.
            return PostCollectionClassification(STATUS_NO_DOMAIN, **base)
        if db_path is None or not str(db_path).strip() or not Path(db_path).is_absolute():
            return PostCollectionClassification(STATUS_INVALID_STORE, **base)
        resolved = Path(db_path).resolve()

        try:
            release = self.lock(resolved)
        except ProcessLockBusy:
            return PostCollectionClassification(STATUS_BUSY, **base)
        except Exception as error:
            logger.error("Trend post-collection lock error=%s", type(error).__name__)
            return PostCollectionClassification(STATUS_LOCK_ERROR, error_type=type(error).__name__, **base)

        try:
            return self._walk(resolved, domain_code, after_id, run_ids)
        finally:
            release()

    def _walk(self, resolved, domain_code, after_id, run_ids):
        pending = set(run_ids)
        scan = dict.fromkeys(_SCAN_COUNTERS, 0)
        run = dict.fromkeys(_RUN_COUNTERS.values(), 0)
        state = dict(status=STATUS_INCOMPLETE, domain_code=None, next_after_id=after_id, batches=0,
                     exhausted=False, missing_tables=(), error_type=None)

        try:
            producer = self.producer_factory(resolved)
            for _ in range(self.max_batches):
                result = producer.classify_pending(domain_code, after_id=state["next_after_id"],
                                                   limit=self.limit)
                state["batches"] += 1
                state["domain_code"] = result.domain_code
                state["next_after_id"] = result.next_after_id
                state["missing_tables"] = tuple(result.missing_tables)
                for name, value in zip(_SCAN_COUNTERS, (result.processed, result.classified,
                                                        result.already_classified, result.unmatched,
                                                        result.ambiguous)):
                    scan[name] += value
                for outcome in result.outcomes:
                    if outcome.observation_id in pending:
                        pending.discard(outcome.observation_id)
                        run[_RUN_COUNTERS[outcome.outcome]] += 1
                if result.status != STATUS_OK:
                    state["status"] = result.status
                    break
                if result.exhausted:
                    state.update(status=STATUS_OK, exhausted=True)
                    break
        except Exception as error:
            # Only the type: messages may echo stored captions or local paths.
            logger.error("Trend post-collection classify error=%s", type(error).__name__)
            state.update(status=STATUS_ERROR, error_type=type(error).__name__)

        return PostCollectionClassification(
            after_id=after_id,
            run_observations=len(run_ids),
            run_not_reached=len(pending),
            **state,
            **{f"scan_{name}": value for name, value in scan.items()},
            **run,
        )
