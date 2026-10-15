"""Manual operator CLI: on-demand Trend Intelligence producer run (TI-4C.2A).

TI4C2A_ON_DEMAND_PRODUCER_RUN_V1

Single synchronous run, in its own process, outside the CRM UI/browser.
No scheduler, no background thread, no config fallback, no network. This
is the ONLY place where the concrete producer is composed (over an
EXISTING store, opened mode=rw, never created) and injected into
backend.services.trend_producer_run_service.TrendProducerRunService.

Dates are UTC collection dates (observed_at), not publication dates.
Windows are [from-date, to-date) at 00:00 UTC; the current UTC day is
never processed. The classification cursor is NOT persisted: resume
manually with --after-id <classification.next_after_id> from the report.
Restarting from --after-id 0 on long histories may keep returning
CLASSIFY_INCOMPLETE; resume from the reported cursor instead.

Usage (Git Bash / PowerShell):

    python scripts/trend_producer_run.py \\
        --db-path C:/ruta/absoluta/store.db --domain-code IT_DOMAIN \\
        --topic ARRAIGO --topic NACIONALIDAD \\
        --from-date 2026-10-01 --to-date 2026-10-08 --execute

The known operational store (database/quesada.db) additionally requires
--allow-operational-db, which needs explicit operational authorization.

Inter-process lock (TI-4C.2B): after validation, --execute and the
operational guard, and before composing the producer or opening the store,
a non-blocking OS advisory lock is taken for the canonical --db-path
(resolve + normcase) and held across classification AND windows. A second
invocation on the same store gets BUSY immediately without touching SQLite;
if the lock cannot be prepared it fails closed with LOCK_ERROR. The lock
file lives in a per-user local runtime dir (Windows %LOCALAPPDATA%, POSIX
$XDG_RUNTIME_DIR, else $XDG_CACHE_HOME or ~/.cache) under a SHA-256 name of
the path; it may persist harmlessly. The OS frees the lock when the process
dies. Scope: only invocations by the same user on the same host (same lock
dir) exclude each other; other users, hosts or path aliases (hard links,
mapped drives) are NOT covered. Platforms without msvcrt/fcntl fail closed.

Exit codes: 0 OK/EMPTY · 1 operational failure (NO_STORE, SCHEMA_INCOMPLETE,
UNKNOWN_DOMAIN, DOMAIN_INACTIVE, INVALID_TOPIC, PARTIAL, ERROR, BUSY,
LOCK_ERROR) · 2 invalid arguments or refused (missing --execute /
operational guard) · 3 CLASSIFY_INCOMPLETE (resume with --after-id).
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import errno
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from backend.services.trend_producer_run_service import (  # noqa: E402
    DEFAULT_CLASSIFY_LIMIT,
    DEFAULT_MAX_CLASSIFY_BATCHES,
    DEFAULT_MAX_WINDOWS,
    STATUS_BUSY,
    STATUS_CLASSIFY_INCOMPLETE,
    TrendProducerRunService,
)

CONTRACT = "TI4C2A_ON_DEMAND_PRODUCER_RUN_V1"
DATE_SEMANTICS = "UTC_COLLECTION_DATE"

STATUS_INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
STATUS_EXECUTE_REQUIRED = "EXECUTE_REQUIRED"
STATUS_OPERATIONAL_DB_REFUSED = "OPERATIONAL_DB_REFUSED"
STATUS_LOCK_ERROR = "LOCK_ERROR"

LOCK_SCOPE = "SAME_USER_SAME_HOST"
_LOCK_BUSY_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK})

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_REFUSED = 2
EXIT_INCOMPLETE = 3

OPERATIONAL_DB_PATH = ROOT / "database" / "quesada.db"
OPERATIONAL_DB_NAME = "quesada.db"

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgumentError(message)


def _parse_args(argv):
    parser = _Parser(
        description="Ejecución manual y síncrona del productor Trend Intelligence.",
    )
    parser.add_argument("--db-path", required=True, help="Ruta ABSOLUTA de una base existente.")
    parser.add_argument("--domain-code", required=True)
    parser.add_argument("--topic", action="append", required=True, dest="topics",
                        help="topic_key explícito (repetible).")
    parser.add_argument("--from-date", required=True, help="YYYY-MM-DD, 00:00 UTC inclusive.")
    parser.add_argument("--to-date", required=True, help="YYYY-MM-DD, 00:00 UTC exclusive.")
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--classify-limit", type=int, default=DEFAULT_CLASSIFY_LIMIT)
    parser.add_argument("--max-classify-batches", type=int, default=DEFAULT_MAX_CLASSIFY_BATCHES)
    parser.add_argument("--max-windows", type=int, default=DEFAULT_MAX_WINDOWS)
    parser.add_argument("--execute", action="store_true",
                        help="Obligatorio para escribir en la base indicada.")
    parser.add_argument("--allow-operational-db", action="store_true",
                        help="Necesario además de --execute para la base operativa conocida.")
    return parser.parse_args(argv)


def _utc_date(value, name):
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise ValueError(f"{name} debe tener formato YYYY-MM-DD")

    parsed = date.fromisoformat(value)
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)


def _is_operational_db(path):
    """Known operational store: exact path, its file name or the same file."""
    if os.path.normcase(str(path)) == os.path.normcase(str(OPERATIONAL_DB_PATH.resolve())):
        return True

    if path.name.lower() == OPERATIONAL_DB_NAME:
        return True

    try:
        return OPERATIONAL_DB_PATH.exists() and path.exists() and os.path.samefile(path, OPERATIONAL_DB_PATH)
    except OSError:
        return True


class _LockBusy(Exception):
    pass


def _lock_dir():
    """Per-user local runtime dir: never the repository nor the store's folder."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "")
    else:
        base = (os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("XDG_CACHE_HOME")
                or str(Path.home() / ".cache"))

    if not base.strip() or not Path(base).is_absolute():
        raise OSError("sin directorio local por usuario para el lock")

    return Path(base) / "quesada-abogados" / "locks" / "trend-producer"


def _acquire_process_lock(db_path):
    """Non-blocking OS lock for one canonical store path -> release callable.

    Raises _LockBusy if another process holds it; any other error must be
    treated as fail-closed by the caller. Opens no SQLite connection.
    """
    if os.name == "nt":
        import msvcrt

        def lock(fd):
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

        def unlock(fd):
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        def lock(fd):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def unlock(fd):
            fcntl.flock(fd, fcntl.LOCK_UN)

    # Hashed name: no path (PII) on disk, no naming collisions.
    key = hashlib.sha256(os.path.normcase(str(db_path)).encode("utf-8")).hexdigest()
    directory = _lock_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory / f"{key}.lock",
                 os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)

    try:
        lock(fd)
    except BaseException as error:
        os.close(fd)
        if isinstance(error, OSError) and error.errno in _LOCK_BUSY_ERRNOS:
            raise _LockBusy() from None
        raise

    def release():
        try:
            unlock(fd)
        except OSError:
            pass  # Closing the handle frees the lock anyway.
        finally:
            os.close(fd)

    return release


def _window_item(item):
    error = getattr(item, "error", None)
    return {
        "topic_key": item.topic_key,
        "window_start": item.window_start,
        "window_end": item.window_end,
        "status": item.status,
        # Only the exception type: messages may echo stored content.
        "error_type": error.split(":", 1)[0] if error else None,
    }


def _report(status, *, executed=False, request=None, result=None, error=None):
    report = {
        "contract": CONTRACT,
        "status": status,
        "executed": executed,
        "date_semantics": DATE_SEMANTICS,
        "error": error,
    }

    if request is not None:
        report["request"] = {
            "domain_code": request.domain_code,
            "topic_keys": list(request.topic_keys),
            "window_from": request.window_from.isoformat(),
            "window_to": request.window_to.isoformat(),
            "after_id": request.after_id,
            "classify_limit": request.classify_limit,
            "max_classify_batches": request.max_classify_batches,
            "max_windows": request.max_windows,
        }

    if result is not None:
        report["classification"] = {
            "status": result.classification_status,
            "after_id": result.after_id,
            "next_after_id": result.next_after_id,
            "batches": result.classify_batches,
            "exhausted": result.classify_exhausted,
            "processed": result.processed,
            "classified": result.classified,
            "already_classified": result.already_classified,
            "unmatched": result.unmatched,
            "ambiguous": result.ambiguous,
        }
        report["windows"] = {
            "attempted": result.windows_attempted,
            "status": result.windows_status,
            "lookback_windows": result.lookback_windows,
            "ok": result.windows_ok,
            "failed": result.windows_failed,
            "not_attempted": result.windows_not_attempted,
            "skipped_no_data": result.windows_skipped,
            "invalid_topics": list(result.invalid_topics),
            "items": [_window_item(item) for item in result.windows],
        }
        report["failed_phase"] = result.failed_phase
        report["missing_tables"] = list(result.missing_tables)
        report["error_type"] = result.error_type
        report["retry"] = {
            "recommended": result.retryable,
            "resume_after_id": result.next_after_id,
        }

    return report


def _exit_code(status, result):
    if result is None:
        return EXIT_REFUSED
    if result.succeeded:
        return EXIT_OK
    if status == STATUS_CLASSIFY_INCOMPLETE:
        return EXIT_INCOMPLETE
    return EXIT_FAILURE


def run(argv=None):
    """(exit_code, report dict). Never executed on import."""
    try:
        args = _parse_args(argv)
        db_path = Path(args.db_path)

        if not str(args.db_path).strip() or not db_path.is_absolute():
            raise ValueError("--db-path debe ser una ruta absoluta")

        window_from = _utc_date(args.from_date, "--from-date")
        window_to = _utc_date(args.to_date, "--to-date")
    except (_ArgumentError, ValueError) as error:
        return EXIT_REFUSED, _report(STATUS_INVALID_ARGUMENTS, error=str(error))

    clock = lambda: datetime.now(timezone.utc)  # noqa: E731
    kwargs = dict(
        domain_code=args.domain_code,
        topic_keys=tuple(args.topics),
        window_from=window_from,
        window_to=window_to,
        after_id=args.after_id,
        classify_limit=args.classify_limit,
        max_classify_batches=args.max_classify_batches,
        max_windows=args.max_windows,
    )

    # Pure prevalidation with a producer-less service: nothing is opened.
    try:
        request = TrendProducerRunService(_NoProducer(), clock=clock).validate(**kwargs)
    except ValueError as error:
        return EXIT_REFUSED, _report(STATUS_INVALID_ARGUMENTS, error=str(error))

    if not args.execute:
        return EXIT_REFUSED, _report(
            STATUS_EXECUTE_REQUIRED, request=request, error="--execute obligatorio para escribir",
        )

    resolved = db_path.resolve()
    if _is_operational_db(resolved) and not args.allow_operational_db:
        return EXIT_REFUSED, _report(
            STATUS_OPERATIONAL_DB_REFUSED, request=request,
            error="Base operativa: requiere --allow-operational-db con autorización explícita",
        )

    # One critical section per canonical store across processes (classify + windows).
    try:
        release_lock = _acquire_process_lock(resolved)
    except _LockBusy:
        return EXIT_FAILURE, _lock_report(
            STATUS_BUSY, request, "Otra ejecución mantiene el lock de esta base; reintentar al terminar",
        )
    except Exception as error:
        # Fail closed. Only the type: OS messages may carry local paths.
        return EXIT_FAILURE, _lock_report(
            STATUS_LOCK_ERROR, request,
            f"No se pudo preparar el lock entre procesos ({type(error).__name__}); no se ejecutó",
        )

    try:
        # Only composition point: scripts/ CLI, explicit path, existing-only store.
        from backend.trend_intelligence.producer import create_trend_producer

        service = TrendProducerRunService(create_trend_producer(resolved, clock=clock), clock=clock)

        try:
            result = service.run_once(**kwargs)
        except ValueError as error:
            return EXIT_REFUSED, _report(STATUS_INVALID_ARGUMENTS, request=request, error=str(error))

        return _exit_code(result.status, result), _report(
            result.status, executed=True, request=request, result=result,
        )
    finally:
        release_lock()


def _lock_report(status, request, error):
    report = _report(status, request=request, error=error)
    report["lock_scope"] = LOCK_SCOPE
    return report


class _NoProducer:
    """Placeholder used only for argument validation; never invoked."""

    def classify_pending(self, *args, **kwargs):
        raise AssertionError("validation only")

    def process_windows(self, *args, **kwargs):
        raise AssertionError("validation only")


def main(argv=None):
    code, report = run(argv)
    sys.stdout.write(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
