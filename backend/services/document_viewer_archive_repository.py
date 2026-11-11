"""
Solicitud persistente e idempotente de archivado en Box desde el visor (DV25-P3B3, H2).

Tres piezas, separadas para que el dominio no dependa de SQLite:

- Dominio (``ArchiveIntent``, ``run_intent``): clave de idempotencia canónica,
  adquisición del claim, ejecución de UNA operación, cierre con fencing y
  recuperación conservadora. Habla con un almacén abstracto (``claim``,
  ``finish``, ``reconcile``, ``get``); nada de SQL ni de rutas de base de datos.
- Adaptador ``SqliteArchiveIntentStore``: tabla de la migración versionada
  ``20261110_dv25_archive_claims.sql``. Solo abre bases existentes, nunca crea
  ni migra al usarse; usa las excepciones DB-API de la conexión.
- Operación ``governed_box_copy``: envuelve la copia certificada P3B1
  (``copy_inbox_item_to_expedient_box``); no hay una segunda vía física a Box.

Garantía real: exclusión mutua e idempotencia entre procesos que comparten LA
MISMA autoridad transaccional (la misma base de datos). Una base SQLite local
por equipo NO coordina equipos distintos (``MULTI_HOST_GUARANTEE = False``) y
SQLite sobre una carpeta de red no es una autoridad fiable: la habilitación
multi-equipo exige una base central compartida (DATA-008), pendiente.

DV28: ``ArchiveIntentStore`` fija el contrato que tendrá que cumplir el adaptador
de la base central (PostgreSQL/Supabase): la misma tabla, ``claim`` atómico
(UNIQUE + índice parcial), ``finish``/``reconcile`` condicionados por fence y
``multi_host_guarantee`` exactamente True solo si TODOS los puestos usan esa
misma autoridad. Ese adaptador aún no existe porque la base central no está
operativa; hasta entonces la vía real sigue en MULTI_HOST_AUTHORITY_PENDING.

Recuperación: un claim caducado nunca se reintenta solo. Si la Bandeja tiene la
copia registrada e íntegra, la solicitud se concilia como registrada; si no, pasa
a revisión humana. Nunca se borra, mueve ni sobrescribe ningún archivo.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

from database import connection


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "database" / "migrations" / "20261110_dv25_archive_claims.sql"
)
HABITUAL_DB = Path(connection.__file__).resolve().with_name("quesada.db")

# Una base SQLite por equipo no coordina equipos: no se declara capacidad multi-equipo.
MULTI_HOST_GUARANTEE = False
LEASE = timedelta(minutes=15)

# Estado persistido de una solicitud.
CLAIMED = "claimed"
REGISTERED = "registered"
REJECTED = "rejected"
NEEDS_REVIEW = "needs_review"

# Resultado de adquirir el claim.
ACQUIRED = "acquired"
ALREADY_IN_PROGRESS = "already_in_progress"
ALREADY_DONE = "already_done"
REVIEW_PENDING = "review_pending"

# Resultado de ``run_intent``.
DONE = "done"
RECOVERED = "recovered"
IN_PROGRESS = "in_progress"
REFUSED = "refused"
REVIEW_REQUIRED = "review_required"
FENCED = "fenced"
UNAVAILABLE = "unavailable"

IN_PROGRESS_MESSAGE = "El archivado de este documento ya está en curso en otra operación: no se ha copiado."
DONE_MESSAGE = "Este documento ya se archivó con esta misma solicitud: no se copia otra vez."
REVIEW_MESSAGE = "El archivado de este documento está pendiente de revisión humana: no se copia."
UNAVAILABLE_MESSAGE = "No se pudo registrar la solicitud de archivado: no se ha copiado nada."
FENCED_MESSAGE = ("La solicitud cambió de titular durante la copia: el resultado queda para revisión "
                  "humana y no se repite.")
RECOVERED_MESSAGE = "Solicitud interrumpida conciliada: la Bandeja ya tiene la copia registrada e íntegra."
STALE_REVIEW_MESSAGE = ("Solicitud interrumpida sin copia registrada: pasa a revisión humana; no se reintenta "
                        "ni se borra nada.")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ArchiveIntentError(Exception):
    """Almacén no disponible, esquema ausente o uso no permitido."""


class IntentRejected(Exception):
    """La operación se rechazó sin escribir nada en Box."""


class IntentIncomplete(Exception):
    """Puede haber un archivo en Box sin registrar (``written_path``)."""

    def __init__(self, message, written_path=""):
        super().__init__(message)
        self.written_path = str(written_path or "")


def _utc_now():
    return datetime.now(timezone.utc)


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ArchiveIntentError(f"{name} no válido.")
    return value


# ---------------------------------------------------------------------- domain


@dataclass(frozen=True)
class ArchiveIntent:
    """Petición canónica: qué documento, a qué destino y con qué contenido."""
    inbox_item_id: int
    client_id: int
    expedient_id: int
    subfolder: str
    nomenclature_key: str
    source_sha256: str
    requested_by_user_id: int

    def __post_init__(self):
        for name in ("inbox_item_id", "client_id", "expedient_id", "requested_by_user_id"):
            _positive(getattr(self, name), name)
        if not isinstance(self.subfolder, str) or not isinstance(self.nomenclature_key, str):
            raise ArchiveIntentError("Destino no válido.")
        if not isinstance(self.source_sha256, str) or not _SHA256.match(self.source_sha256):
            raise ArchiveIntentError("SHA-256 del origen no válido.")

    @property
    def key(self):
        """Clave de idempotencia; el actor no forma parte: dos personas, una sola copia."""
        payload = [self.inbox_item_id, self.client_id, self.expedient_id, self.subfolder,
                   self.nomenclature_key, self.source_sha256]
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IntentRecord:
    key: str
    inbox_item_id: int
    expedient_id: int
    source_sha256: str
    state: str
    fence: int
    owner_token: str
    heartbeat_at: datetime
    destination_path: str = ""
    result: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Claim:
    status: str
    record: IntentRecord | None


@runtime_checkable
class ArchiveIntentStore(Protocol):
    """Autoridad transaccional de las solicitudes; el dominio solo habla con esto."""

    multi_host_guarantee: bool

    def get(self, key): ...

    def claim(self, intent, owner_token, now): ...

    def finish(self, key, owner_token, fence, state, destination_path, result, now): ...

    def reconcile(self, key, fence, state, destination_path, result, now): ...


@dataclass(frozen=True)
class RunOutcome:
    status: str
    message: str
    record: IntentRecord | None = None
    destination_path: str = ""
    written_path: str = ""


def _recover(store, record, evidence, clock):
    """Claim caducado: conciliar con la Bandeja o pasar a revisión; nunca reintentar."""
    try:
        registered_path, intact = evidence(record)
    except Exception:
        registered_path, intact = "", False
    if registered_path and intact is True:
        state, destination, result = REGISTERED, str(registered_path), {"recovered": True}
        status, message = RECOVERED, RECOVERED_MESSAGE
    else:
        state, destination, result = NEEDS_REVIEW, "", {"recovered": False, "reason": "stale_claim"}
        status, message = REVIEW_REQUIRED, STALE_REVIEW_MESSAGE
    try:
        if not store.reconcile(record.key, record.fence, state, destination, result, clock()):
            # Otro proceso concilió o cerró antes: se informa sin actuar.
            return RunOutcome(IN_PROGRESS, IN_PROGRESS_MESSAGE, store.get(record.key))
        return RunOutcome(status, message, store.get(record.key), destination_path=destination)
    except ArchiveIntentError:
        return RunOutcome(UNAVAILABLE, UNAVAILABLE_MESSAGE, record)


def run_intent(store, intent, operation, *, evidence, now=None, lease=LEASE):
    """Ejecuta ``operation`` como mucho una vez por solicitud canónica.

    ``operation()`` devuelve un dict con ``destination_path`` o lanza
    ``IntentRejected`` (nada escrito) / ``IntentIncomplete`` (posible archivo).
    ``evidence(record)`` devuelve (ruta registrada en Bandeja, íntegra: bool) y
    solo se usa para conciliar claims caducados.
    """
    clock = now or _utc_now
    token = uuid4().hex
    try:
        claim = store.claim(intent, token, clock())
    except ArchiveIntentError:
        return RunOutcome(UNAVAILABLE, UNAVAILABLE_MESSAGE)
    record = claim.record
    if claim.status == ALREADY_DONE:
        return RunOutcome(ALREADY_DONE, DONE_MESSAGE, record, destination_path=record.destination_path)
    if claim.status == REVIEW_PENDING:
        return RunOutcome(REVIEW_REQUIRED, REVIEW_MESSAGE, record)
    if claim.status == ALREADY_IN_PROGRESS:
        if record is not None and record.state == CLAIMED and clock() - record.heartbeat_at > lease:
            return _recover(store, record, evidence, clock)
        return RunOutcome(IN_PROGRESS, IN_PROGRESS_MESSAGE, record)

    def close(state, destination, result):
        return store.finish(intent.key, token, record.fence, state, destination, result, clock())

    try:
        payload = operation()
    except IntentRejected as exc:
        try:
            close(REJECTED, "", {"error": str(exc)})
        except ArchiveIntentError:
            pass  # Sin escritura en Box; el claim caducará y se conciliará.
        return RunOutcome(REFUSED, str(exc), record)
    except IntentIncomplete as exc:
        try:
            close(NEEDS_REVIEW, exc.written_path, {"error": str(exc), "written_path": exc.written_path})
        except ArchiveIntentError:
            pass
        return RunOutcome(REVIEW_REQUIRED, str(exc), record, written_path=exc.written_path)
    except Exception as exc:
        try:
            close(NEEDS_REVIEW, "", {"error": type(exc).__name__})
        except ArchiveIntentError:
            pass
        return RunOutcome(REVIEW_REQUIRED, REVIEW_MESSAGE, record)

    payload = payload if isinstance(payload, dict) else {}
    destination = str(payload.get("destination_path") or "")
    try:
        closed = close(REGISTERED, destination, payload)
    except ArchiveIntentError:
        # La copia está registrada en Bandeja; la solicitud se conciliará al caducar.
        return RunOutcome(REVIEW_REQUIRED, UNAVAILABLE_MESSAGE, record, destination_path=destination)
    if not closed:
        return RunOutcome(FENCED, FENCED_MESSAGE, store.get(intent.key), destination_path=destination)
    return RunOutcome(DONE, "", store.get(intent.key), destination_path=destination)


# ---------------------------------------------------------------------- P3B1 operation and evidence


def governed_box_copy(intent, *, copy=None):
    """Operación para ``run_intent`` sobre la copia certificada P3B1 (única vía física)."""
    from backend.services import document_inbox_service as inbox

    def operation():
        run = copy or inbox.copy_inbox_item_to_expedient_box
        try:
            updated = run(intent.inbox_item_id, expedient_id=intent.expedient_id,
                          subfolder=intent.subfolder, nomenclature_key=intent.nomenclature_key)
        except inbox.BoxCopyIncomplete as exc:
            raise IntentIncomplete(str(exc), exc.written_path) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise IntentRejected(str(exc)) from exc
        updated = updated if isinstance(updated, dict) else {}
        trace = updated.get("box_copy") if isinstance(updated.get("box_copy"), dict) else {}
        destination = str(updated.get("copied_to_box_path") or "")
        if updated.get("status") != "copied_to_box" or not destination:
            raise IntentIncomplete("La Bandeja no confirmó la copia.", destination)
        if trace.get("source_sha256") != intent.source_sha256:
            raise IntentIncomplete("La copia no corresponde al contenido revisado.", destination)
        return {"destination_path": destination, "result": trace.get("result", ""),
                "provenance": trace.get("provenance", ""), "source_sha256": intent.source_sha256}

    return operation


def registered_copy_evidence(db_path):
    """``evidence`` para ``run_intent``: copia registrada en Bandeja e íntegra (solo lectura)."""
    def evidence(record):
        with closing(connection.get_readonly_connection(db_path)) as conn:
            row = conn.execute(
                "SELECT status, expedient_id, copied_to_box_path FROM document_inbox_items WHERE id = ?",
                (int(record.inbox_item_id),),
            ).fetchone()
        if not row or row["status"] != "copied_to_box" or row["expedient_id"] != record.expedient_id:
            return "", False
        path = Path(str(row["copied_to_box_path"] or ""))
        if not str(row["copied_to_box_path"] or "") or not path.is_file():
            return "", False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return str(path), digest.hexdigest() == record.source_sha256

    return evidence


# ---------------------------------------------------------------------- SQLite adapter


def _refuse_habitual(db_path):
    if db_path is None:
        raise ArchiveIntentError("Hay que indicar explícitamente la base de datos.")
    try:
        target = Path(db_path).resolve()
    except (OSError, RuntimeError, TypeError):
        raise ArchiveIntentError("Ruta de base de datos no válida.") from None
    if target == HABITUAL_DB:
        raise ArchiveIntentError("La base de datos habitual solo se migra con el proceso aprobado por Dirección.")
    return target


def apply_schema(db_path):
    """Bootstrap explícito de la migración (tests y proceso aprobado); nunca desde la UI.

    En P3B3 rechaza la base habitual: solo bases temporales.
    """
    target = _refuse_habitual(db_path)
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    try:
        with closing(connection.get_existing_connection(target)) as conn:
            conn.executescript(sql)
            conn.commit()
    except Exception as exc:
        raise ArchiveIntentError("No se pudo aplicar la migración de solicitudes de archivado.") from exc


_COLUMNS = ("idempotency_key, inbox_item_id, expedient_id, source_sha256, state, fence, owner_token, "
            "heartbeat_at, destination_path, result_json")


def _record(row):
    if not row:
        return None
    try:
        result = json.loads(row["result_json"] or "{}")
    except ValueError:
        result = {}
    return IntentRecord(
        key=row["idempotency_key"], inbox_item_id=row["inbox_item_id"], expedient_id=row["expedient_id"],
        source_sha256=row["source_sha256"], state=row["state"], fence=row["fence"],
        owner_token=row["owner_token"], heartbeat_at=datetime.fromisoformat(row["heartbeat_at"]),
        destination_path=row["destination_path"] or "", result=result if isinstance(result, dict) else {})


class SqliteArchiveIntentStore:
    """Almacén de solicitudes sobre una base EXISTENTE con la migración aplicada."""

    multi_host_guarantee = MULTI_HOST_GUARANTEE

    def __init__(self, db_path):
        self.db_path = _refuse_habitual(db_path)

    def _connect(self):
        try:
            conn = connection.get_existing_connection(self.db_path)
            conn.execute("PRAGMA busy_timeout = 30000")
        except Exception as exc:
            raise ArchiveIntentError(UNAVAILABLE_MESSAGE) from exc
        return conn

    @staticmethod
    def _select(conn, key):
        return _record(conn.execute(
            f"SELECT {_COLUMNS} FROM document_viewer_archive_intents WHERE idempotency_key = ?",
            (key,)).fetchone())

    def get(self, key):
        with closing(self._connect()) as conn:
            try:
                return self._select(conn, key)
            except conn.Error as exc:
                raise ArchiveIntentError(UNAVAILABLE_MESSAGE) from exc

    def claim(self, intent, owner_token, now):
        """Adquisición atómica: BEGIN IMMEDIATE + UNIQUE + índice parcial por ítem."""
        stamp = now.isoformat()
        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                current = self._select(conn, intent.key)
                if current is None:
                    conn.execute(
                        "INSERT INTO document_viewer_archive_intents (idempotency_key, inbox_item_id, "
                        "client_id, expedient_id, subfolder, nomenclature_key, source_sha256, "
                        "requested_by_user_id, state, fence, owner_token, claimed_at, heartbeat_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'claimed', 1, ?, ?, ?)",
                        (intent.key, intent.inbox_item_id, intent.client_id, intent.expedient_id,
                         intent.subfolder, intent.nomenclature_key, intent.source_sha256,
                         intent.requested_by_user_id, owner_token, stamp, stamp))
                    status = ACQUIRED
                elif current.state == REJECTED:
                    # Rechazada sin escribir nada: se puede volver a intentar con otro fence.
                    conn.execute(
                        "UPDATE document_viewer_archive_intents SET state = 'claimed', fence = fence + 1, "
                        "owner_token = ?, claimed_at = ?, heartbeat_at = ?, finished_at = NULL, "
                        "destination_path = NULL, result_json = NULL "
                        "WHERE idempotency_key = ? AND state = 'rejected'",
                        (owner_token, stamp, stamp, intent.key))
                    status = ACQUIRED
                else:
                    status = {CLAIMED: ALREADY_IN_PROGRESS, REGISTERED: ALREADY_DONE,
                              NEEDS_REVIEW: REVIEW_PENDING}[current.state]
                conn.commit()
                return Claim(status, self._select(conn, intent.key))
            except conn.IntegrityError:
                # Otra solicitud activa para el mismo ítem (otra clave): en curso o en revisión.
                conn.rollback()
                active = _record(conn.execute(
                    f"SELECT {_COLUMNS} FROM document_viewer_archive_intents "
                    "WHERE inbox_item_id = ? AND state IN ('claimed', 'needs_review')",
                    (intent.inbox_item_id,)).fetchone())
                return Claim(ALREADY_IN_PROGRESS, active)
            except conn.Error as exc:
                conn.rollback()
                raise ArchiveIntentError(UNAVAILABLE_MESSAGE) from exc

    def _update(self, sql, params):
        with closing(self._connect()) as conn:
            try:
                cursor = conn.execute(sql, params)
                conn.commit()
                return cursor.rowcount == 1
            except conn.Error as exc:
                conn.rollback()
                raise ArchiveIntentError(UNAVAILABLE_MESSAGE) from exc

    def finish(self, key, owner_token, fence, state, destination_path, result, now):
        """Cierra la solicitud solo si este titular y este fence siguen vigentes."""
        stamp = now.isoformat()
        return self._update(
            "UPDATE document_viewer_archive_intents SET state = ?, finished_at = ?, heartbeat_at = ?, "
            "destination_path = ?, result_json = ? "
            "WHERE idempotency_key = ? AND owner_token = ? AND fence = ? AND state = 'claimed'",
            (state, stamp, stamp, destination_path or None, json.dumps(result, default=str), key,
             owner_token, fence))

    def reconcile(self, key, fence, state, destination_path, result, now):
        """Conciliación de un claim caducado; compare-and-set sobre el fence observado."""
        stamp = now.isoformat()
        return self._update(
            "UPDATE document_viewer_archive_intents SET state = ?, fence = fence + 1, finished_at = ?, "
            "heartbeat_at = ?, destination_path = ?, result_json = ? "
            "WHERE idempotency_key = ? AND fence = ? AND state = 'claimed'",
            (state, stamp, stamp, destination_path or None, json.dumps(result, default=str), key, fence))
