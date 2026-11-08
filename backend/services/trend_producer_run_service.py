"""
Trend Intelligence · ejecución bajo demanda del productor (TI-4C.2A).

Orquestación síncrona y acotada de un productor INYECTADO: este módulo no
lo construye, no conoce rutas ni abre almacenamiento. Solo un operador
manual (CLI bajo scripts/) compone el productor concreto y lo inyecta. Sin
scheduler, cola, hilo de fondo, hook del Collector ni arranque en app/main.

Contrato del productor (duck typing):
- classify_pending(domain_code, *, after_id, limit) -> status, next_after_id,
  exhausted y contadores; el cursor devuelto es siempre seguro.
- process_windows(domain_code, topic_keys, window_from, window_to, *,
  max_windows) -> status, windows y contadores; cada ventana usa su propia
  transacción y sus fallos (PARTIAL) quedan visibles.

Flujo de run_once: prevalidación pura (sin I/O) -> fase A (classify_pending
como máximo N lotes, hasta exhausted) -> fase B (process_windows UNA vez)
solo si la clasificación terminó en OK y exhausted. El cursor nunca se
persiste: se devuelve next_after_id para reanudar manualmente.

Las fechas de las ventanas son fechas de RECOLECCIÓN (observed_at), no de
publicación; un snapshot sin baseline suficiente no es una tendencia.
"""

from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
    timezone,
)
import re
import threading


STATUS_OK = "OK"
STATUS_EMPTY = "EMPTY"
STATUS_PARTIAL = "PARTIAL"
STATUS_BUSY = "BUSY"
STATUS_CLASSIFY_INCOMPLETE = "CLASSIFY_INCOMPLETE"
STATUS_ERROR = "ERROR"

PHASE_CLASSIFY = "CLASSIFY"
PHASE_WINDOWS = "WINDOWS"

DEFAULT_CLASSIFY_LIMIT = 100
MAX_CLASSIFY_LIMIT = 200
DEFAULT_MAX_CLASSIFY_BATCHES = 10
MAX_CLASSIFY_BATCHES_HARD_CAP = 20
DEFAULT_MAX_WINDOWS = 28
MAX_WINDOWS_HARD_CAP = 28

# Statuses after which a manual retry (same range, resume cursor) makes sense.
RETRYABLE_STATUSES = frozenset({
    STATUS_BUSY,
    STATUS_CLASSIFY_INCOMPLETE,
    STATUS_ERROR,
    STATUS_PARTIAL,
    "NO_STORE",
})

# Canonical topic_key form (same alphabet the domain catalogue stores).
_TOPIC_KEY = re.compile(r"[A-Z0-9]+(?:_[A-Z0-9]+)*")


@dataclass(frozen=True, slots=True)
class TrendProducerRunRequest:
    domain_code: str
    topic_keys: tuple[str, ...]
    window_from: datetime
    window_to: datetime
    after_id: int = 0
    classify_limit: int = DEFAULT_CLASSIFY_LIMIT
    max_classify_batches: int = DEFAULT_MAX_CLASSIFY_BATCHES
    max_windows: int = DEFAULT_MAX_WINDOWS

    @property
    def days(self):
        return (self.window_to - self.window_from).days


@dataclass(frozen=True, slots=True)
class TrendProducerRunResult:
    status: str
    domain_code: str
    topic_keys: tuple[str, ...]
    window_from: str
    window_to: str
    after_id: int
    next_after_id: int
    failed_phase: str | None = None
    classification_status: str | None = None
    classify_batches: int = 0
    classify_exhausted: bool = False
    processed: int = 0
    classified: int = 0
    already_classified: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    windows_attempted: bool = False
    windows_status: str | None = None
    windows: tuple = ()
    windows_ok: int = 0
    windows_failed: int = 0
    windows_not_attempted: int = 0
    windows_skipped: int = 0
    lookback_windows: int | None = None
    invalid_topics: tuple[str, ...] = ()
    missing_tables: tuple[str, ...] = ()
    error_type: str | None = None

    @property
    def succeeded(self):
        return self.status in (STATUS_OK, STATUS_EMPTY)

    @property
    def retryable(self):
        return self.status in RETRYABLE_STATUSES


def _plain_int(value, name, minimum, maximum):
    if type(value) is not int:
        raise ValueError(f"{name} debe ser entero")

    if not minimum <= value <= maximum:
        raise ValueError(f"{name} debe estar entre {minimum} y {maximum}")

    return value


def _utc_midnight(value, name):
    if not isinstance(value, datetime):
        raise ValueError(f"{name} debe ser datetime UTC")

    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} debe ser UTC explícito")

    value = value.astimezone(timezone.utc)

    if (value.hour, value.minute, value.second, value.microsecond) != (0, 0, 0, 0):
        raise ValueError(f"{name} debe estar alineado a 00:00 UTC")

    return value


def _topic_keys(values):
    if isinstance(values, (str, bytes)) or values is None:
        raise ValueError("topic_keys debe ser una colección explícita")

    keys = []

    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("topic_key vacío o no textual")

        key = value.strip().upper()

        if not _TOPIC_KEY.fullmatch(key):
            raise ValueError(f"topic_key no canónico: {value!r}")

        if key in keys:
            raise ValueError(f"topic_key duplicado: {key}")

        keys.append(key)

    if not keys:
        raise ValueError("topic_keys obligatorio")

    return tuple(keys)


class TrendProducerRunService:
    def __init__(self, producer, *, clock=None):
        for method in ("classify_pending", "process_windows"):
            if not callable(getattr(producer, method, None)):
                raise ValueError(f"producer debe exponer {method}")

        self.producer = producer
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # Same-object, same-process exclusion only; no cross-process claim.
        self._lock = threading.Lock()

    def validate(
        self,
        *,
        domain_code,
        topic_keys,
        window_from,
        window_to,
        after_id=0,
        classify_limit=DEFAULT_CLASSIFY_LIMIT,
        max_classify_batches=DEFAULT_MAX_CLASSIFY_BATCHES,
        max_windows=DEFAULT_MAX_WINDOWS,
    ):
        """Pure validation (no producer call, no I/O) -> TrendProducerRunRequest."""
        if not isinstance(domain_code, str) or not domain_code.strip():
            raise ValueError("domain_code obligatorio")

        keys = _topic_keys(topic_keys)
        start = _utc_midnight(window_from, "window_from")
        end = _utc_midnight(window_to, "window_to")

        if start >= end:
            raise ValueError("Se requiere window_from < window_to")

        # window_to is a midnight: <= now means every day is already complete.
        if end > self.clock():
            raise ValueError("window_to no puede incluir el día UTC en curso")

        request = TrendProducerRunRequest(
            domain_code=domain_code.strip(),
            topic_keys=keys,
            window_from=start,
            window_to=end,
            after_id=_plain_int(after_id, "after_id", 0, 2 ** 63 - 1),
            classify_limit=_plain_int(classify_limit, "classify_limit", 1, MAX_CLASSIFY_LIMIT),
            max_classify_batches=_plain_int(
                max_classify_batches, "max_classify_batches", 1, MAX_CLASSIFY_BATCHES_HARD_CAP,
            ),
            max_windows=_plain_int(max_windows, "max_windows", 1, MAX_WINDOWS_HARD_CAP),
        )

        pairs = len(keys) * request.days
        if pairs > request.max_windows:
            raise ValueError(f"{pairs} pares topic-ventana superan max_windows={request.max_windows}")

        return request

    def run_once(self, **kwargs):
        request = self.validate(**kwargs)

        if not self._lock.acquire(blocking=False):
            return self._result(request, STATUS_BUSY, next_after_id=request.after_id)

        try:
            return self._run(request)
        finally:
            self._lock.release()

    # ------------------------------------------------------------------

    def _run(self, request):
        cursor = request.after_id
        totals = dict(processed=0, classified=0, already_classified=0, unmatched=0, ambiguous=0)
        batches = 0
        classification = None

        while batches < request.max_classify_batches:
            try:
                classification = self.producer.classify_pending(
                    request.domain_code,
                    after_id=cursor,
                    limit=request.classify_limit,
                )
            except Exception as error:
                # Cursor stays on the last completed batch: safe to resume.
                return self._result(
                    request, STATUS_ERROR, next_after_id=cursor, failed_phase=PHASE_CLASSIFY,
                    classify_batches=batches, error_type=type(error).__name__, **totals,
                )

            batches += 1

            for name in totals:
                totals[name] += getattr(classification, name)

            cursor = classification.next_after_id

            if classification.status != STATUS_OK:
                return self._result(
                    request, classification.status, next_after_id=cursor,
                    failed_phase=PHASE_CLASSIFY, classification_status=classification.status,
                    classify_batches=batches, missing_tables=tuple(classification.missing_tables),
                    **totals,
                )

            if classification.exhausted:
                break
        else:
            # Batch budget consumed with observations possibly pending:
            # windows are NOT processed over an incomplete classification.
            return self._result(
                request, STATUS_CLASSIFY_INCOMPLETE, next_after_id=cursor,
                failed_phase=PHASE_CLASSIFY, classification_status=classification.status,
                classify_batches=batches, **totals,
            )

        classified = dict(
            next_after_id=cursor,
            classification_status=classification.status,
            classify_batches=batches,
            classify_exhausted=True,
            **totals,
        )

        try:
            windows = self.producer.process_windows(
                request.domain_code,
                request.topic_keys,
                request.window_from,
                request.window_to,
                max_windows=request.max_windows,
            )
        except Exception as error:
            return self._result(
                request, STATUS_ERROR, failed_phase=PHASE_WINDOWS, windows_attempted=True,
                error_type=type(error).__name__, **classified,
            )

        status = windows.status
        if status == STATUS_OK and windows.ok == 0:
            # Nothing materialized (no data in range): correct, not a failure.
            status = STATUS_EMPTY

        return self._result(
            request,
            status,
            failed_phase=None if status in (STATUS_OK, STATUS_EMPTY) else PHASE_WINDOWS,
            windows_attempted=True,
            windows_status=windows.status,
            windows=tuple(windows.windows),
            windows_ok=windows.ok,
            windows_failed=windows.failed,
            windows_not_attempted=windows.not_attempted,
            windows_skipped=windows.skipped,
            lookback_windows=getattr(windows, "lookback_windows", None),
            invalid_topics=tuple(windows.invalid_topics),
            missing_tables=tuple(windows.missing_tables),
            **classified,
        )

    @staticmethod
    def _result(request, status, **fields):
        return TrendProducerRunResult(
            status=status,
            domain_code=request.domain_code,
            topic_keys=request.topic_keys,
            window_from=request.window_from.isoformat(),
            window_to=request.window_to.isoformat(),
            after_id=request.after_id,
            **fields,
        )
