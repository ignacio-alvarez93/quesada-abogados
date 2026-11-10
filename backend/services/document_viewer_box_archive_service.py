"""
Archivado de copias en Box desde el visor documental (DV25-P3B2).

Única puerta de orquestación y autorización del archivado DESDE EL VISOR.
La copia física la hace solo el servicio certificado en P3B1
(``document_inbox_service.copy_inbox_item_to_expedient_box``: COPY -> VERIFY ->
REGISTER, creación exclusiva, nunca mueve, borra, renombra ni sobrescribe);
aquí no hay ninguna primitiva de archivo, ``shutil``, ``mkdir`` ni SQL de
escritura. Contexto, carpetas, nomenclaturas y nombres proyectados se leen del
planificador P3A (``document_viewer_filing_plan_service``) sin modificarlo.

Flujo (firmas en docs/document_viewer_dv25_p3b2.md):
- ``inspect_archive``: solo lectura; elegibilidad de cada documento y el
  destino que ya tienen vinculado (cliente + expediente).
- ``prepare_archive``: solo lectura; carpeta existente, nomenclatura por
  documento, nombre proyectado y huella (``fingerprint``) del plan.
- ``execute_archive``: la única operación que escribe, tras consentimiento
  explícito sobre ESA huella. Revalida todo antes de empezar y cada documento
  justo antes de su copia.

Restricción por el contrato de P3B1 (que al registrar escribe
``expedient_id = destino`` y ``client_id = COALESCE(client_id, cliente)``):
solo se archivan documentos de Bandeja YA vinculados (estado ``linked``) al
mismo cliente y expediente destino, ambos IDs positivos y no NULL. Así la
copia nunca traslada ni asigna vinculaciones como efecto colateral. Un
documento no vinculado, vinculado a otro destino o ya copiado se rechaza.

Vía real cerrada: P3B1 no garantiza idempotencia entre procesos (dos equipos
sobre el mismo ítem pueden dejar una copia extra sin registrar). Mientras no
haya una resolución dedicada, ``EXECUTION_ENABLED`` es False en el código y
``execute_archive`` lo rechaza sin escribir nada; la revisión sigue disponible.
No se puede habilitar desde la UI.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from uuid import uuid4

from backend.services import document_inbox_service
from backend.services import document_viewer_filing_plan_service as filing_service
from backend.services import document_viewer_link_service as link_service
from database import connection


# Compuerta de la vía real; ver «Riesgos residuales» en docs/document_viewer_dv25_p3b2.md.
EXECUTION_ENABLED = False

EXECUTION_DISABLED = ("Archivado desde el visor pendiente de aprobación de Dirección: la copia de "
                      "Bandeja no garantiza idempotencia entre equipos. La revisión está disponible; "
                      "la copia sigue deshabilitada.")
COPY_ONLY = ("Copia controlada a la carpeta Box del expediente ya vinculado: el original de Bandeja no "
             "se mueve, renombra ni modifica y en Box nunca se sobrescribe ni borra nada.")
BATCH_POLICY = ("Cada documento se copia, verifica y registra por separado y en el orden mostrado: el "
                "lote no es atómico. Un documento rechazado o desactualizado se omite; una copia que "
                "queda sin registrar detiene el resto para revisión.")

NO_INBOX = "Sin documento de Bandeja: no se archiva desde el visor."
SOURCE_MISSING = "El archivo de Bandeja no existe o no se puede leer."
NOT_INBOX_SOURCE = "El origen no es un archivo interno de Bandeja: no se archiva."
DISCARDED = "Descartado en Bandeja: no se archiva."
DUPLICATE = "Es un duplicado: archiva el documento principal."
ALREADY_COPIED = "Ya copiado a Box: no se archiva otra copia."
NOT_LINKED = "No está vinculado a un cliente y expediente: vincúlalo antes de archivar."
OTHER_TARGET = ("Vinculado a otro cliente o expediente: el archivado no traslada vinculaciones. "
                "Vincúlalo primero al expediente destino.")
HASH_MISMATCH = "El archivo de Bandeja no coincide con el SHA-256 registrado: no se archiva."
REPEATED = "Repetido en la selección: se archiva una sola vez."
MIXED_TARGETS = ("Los documentos están vinculados a expedientes distintos: archívalos por separado, "
                 "cada uno en su expediente.")
NOTHING_TO_ARCHIVE = "Ningún documento se puede archivar desde el visor."
NOT_CONFIRMED = "Confirma el archivado de la copia antes de continuar."
INVALID_REQUEST = "Solicitud de archivado no válida."
STALE_CONSENT = "La confirmación no corresponde a la revisión vigente: revisa y confirma de nuevo."
STALE = ("Algo cambió desde la revisión (documento, vínculo, carpeta, nomenclatura o nombre): no se ha "
         "copiado nada. Revisa y confirma de nuevo.")
STALE_ITEM = "El documento cambió desde la revisión: no se ha copiado."
FOLDER_CHANGED = "La carpeta destino ya no es una carpeta existente del expediente: no se ha copiado."
IN_PROGRESS = "El archivado ya está en curso."
IN_FLIGHT = "Este documento ya se está archivando en otra operación: no se ha copiado."
REPLAYED = "Esta revisión ya se ejecutó: no se repite. Abre una revisión nueva."
NOTHING_READY = "No hay documentos listos para archivar."
OTHER_DATABASE = "La revisión no corresponde a la base de datos del CRM: no se archiva."
NO_ACTOR = "No hay un usuario autenticado: el archivado no está disponible."
NOT_AUTHORIZED = "El usuario no está autorizado para archivar documentos."
COPY_FAILED = "No se pudo archivar el documento."
NOT_CONFIRMED_BY_INBOX = "La Bandeja no confirmó la copia en la carpeta prevista: revisa el documento."
NOT_ATTEMPTED_MESSAGE = "No se intentó: el lote se detuvo por un fallo anterior."

# Revisión de un documento.
READY = "ready"
PENDING = "pending"
NOT_ARCHIVABLE = "not_archivable"
REJECTED = "rejected"
# Resultado de un documento tras la operación.
ARCHIVED = "archived"
FAILED = "failed"
INCOMPLETE = "incomplete"
NOT_ATTEMPTED = "not_attempted"

_inflight = set()
_inflight_lock = threading.Lock()
_consumed = set()
_consumed_lock = threading.Lock()


class ArchiveError(ValueError):
    """Error visible para la persona usuaria; se lanza antes de cualquier escritura."""


@dataclass(frozen=True)
class ArchiveItem:
    """Estado leído de un documento y lo que el archivado haría con él."""
    key: str
    name: str
    path: str
    inbox_item_id: int | None
    outcome: str
    message: str = ""
    client_id: int | None = None
    expedient_id: int | None = None
    status: str = ""
    source: str = ""
    extension: str = ""
    source_sha256: str = ""
    nomenclature_key: str = ""
    nomenclature_label: str = ""
    proposed_name: str = ""
    # Campos del ítem y del archivo que no deben cambiar entre la revisión y la copia.
    snapshot: tuple = ()

    def request(self):
        return {"key": self.key, "name": self.name, "path": self.path,
                "inbox_item_id": self.inbox_item_id}


@dataclass(frozen=True)
class ArchiveInspection:
    user: dict
    items: tuple
    target: link_service.LinkTarget | None
    message: str = ""


@dataclass(frozen=True)
class ArchiveOutcome:
    key: str
    name: str
    inbox_item_id: int | None
    status: str
    message: str
    final_name: str = ""
    destination: str = ""  # relativa a la raíz Box del expediente
    collision: str = ""
    written_path: str = ""  # copia sin registrar que requiere revisión (INCOMPLETE)


@dataclass(frozen=True)
class ArchiveResult:
    target: link_service.LinkTarget
    user: dict
    folder: str
    items: tuple
    # Cada copia se registra por separado: nunca se declara atómico.
    atomic: bool = False
    policy: str = BATCH_POLICY

    def count(self, status):
        return sum(1 for item in self.items if item.status == status)

    @property
    def archived(self):
        return self.count(ARCHIVED)

    @property
    def problems(self):
        return len(self.items) - self.archived

    @property
    def complete(self):
        return bool(self.items) and not self.problems

    @property
    def partial(self):
        return bool(self.archived) and bool(self.problems)

    @property
    def summary(self):
        parts = [f"{self.archived} archivado(s) de {len(self.items)}"]
        for status, label in ((REJECTED, "rechazado(s)"), (PENDING, "sin nomenclatura"),
                              (NOT_ARCHIVABLE, "sin Bandeja"), (FAILED, "fallido(s)"),
                              (INCOMPLETE, "copia(s) sin registrar"), (NOT_ATTEMPTED, "no intentado(s)")):
            if self.count(status):
                parts.append(f"{self.count(status)} {label}")
        return " · ".join(parts)


@dataclass
class ArchivePlan:
    """Revisión previa de un archivado; se ejecuta una sola vez."""
    actor: object
    user: dict
    target: link_service.LinkTarget
    context: object
    folder: str | None
    choices: tuple
    requests: tuple
    items: tuple
    fingerprint: str
    db_path: object = None
    token: str = field(default_factory=lambda: uuid4().hex)
    result: ArchiveResult | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def ready(self):
        return tuple(item for item in self.items if item.outcome == READY)

    @property
    def folder_label(self):
        if self.folder is None:
            return ""
        return filing_service.ROOT_LABEL if self.folder == "" else self.folder


# ---------------------------------------------------------------------- helpers


def _positive(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _resolved(value):
    text = str(value or "").strip()
    if not text or "\x00" in text:
        return None
    try:
        return Path(text).resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def _within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _duplicate_of(item):
    try:
        metadata = json.loads(item.get("metadata_json") or "{}")
    except (TypeError, ValueError):
        return None
    return _positive(metadata.get("duplicate_of_id")) if isinstance(metadata, dict) else None


def _item_row(item_id, db_path):
    """Ítem de Bandeja en una conexión de solo lectura (nunca migra ni crea carpetas)."""
    with closing(connection.get_readonly_connection(db_path)) as conn:
        row = conn.execute("SELECT * FROM document_inbox_items WHERE id = ?", (int(item_id),)).fetchone()
    return dict(row) if row else None


def _file_state(path):
    """(tamaño, mtime_ns, SHA-256) del origen; solo lectura."""
    before = path.stat()
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    if size != before.st_size:
        raise OSError("El archivo cambió durante la lectura.")
    return size, before.st_mtime_ns, digest.hexdigest()


def _verified_user(actor, db_path):
    try:
        return link_service.verified_user(actor, db_path=db_path)
    except link_service.DocumentLinkError as exc:
        message = {link_service.NO_ACTOR: NO_ACTOR,
                   link_service.NOT_AUTHORIZED: NOT_AUTHORIZED}.get(str(exc), str(exc))
        raise ArchiveError(message) from None


def _same_database(db_path):
    """La copia escribe en la BD del CRM: la revisión tiene que haberse leído de esa misma BD."""
    if db_path is None:
        return
    try:
        same = Path(db_path).resolve() == Path(connection.DB_PATH).resolve()
    except (OSError, RuntimeError, TypeError):
        same = False
    if not same:
        raise ArchiveError(OTHER_DATABASE)


def _claim(item_id):
    with _inflight_lock:
        if item_id in _inflight:
            return False
        _inflight.add(item_id)
        return True


def _release(item_id):
    with _inflight_lock:
        _inflight.discard(item_id)


def read_document(document, *, db_path=None):
    """Elegibilidad de un documento del visor para archivarlo; nunca escribe."""
    document = document if isinstance(document, dict) else {}
    path = str(document.get("path") or "").strip()
    base = dict(
        key=str(document.get("key") or "") or f"path:{path}",
        name=str(document.get("name") or "").strip() or (Path(path).name if path else "Documento"),
        path=path,
        inbox_item_id=_positive(document.get("inbox_item_id")),
    )
    if base["inbox_item_id"] is None:
        return ArchiveItem(**base, outcome=NOT_ARCHIVABLE, message=NO_INBOX)
    try:
        item = _item_row(base["inbox_item_id"], db_path)
    except (sqlite3.Error, OSError, ValueError):
        return ArchiveItem(**base, outcome=REJECTED, message=link_service.INBOX_UNAVAILABLE)
    if not item:
        return ArchiveItem(**base, outcome=REJECTED, message=link_service.ITEM_MISSING)
    source = _resolved(item.get("stored_path"))
    if source is None or not source.is_file():
        return ArchiveItem(**base, outcome=REJECTED, message=SOURCE_MISSING)
    if _resolved(path) != source:
        return ArchiveItem(**base, outcome=REJECTED, message=link_service.WRONG_FILE)
    inbox_root = _resolved(document_inbox_service.INBOX_ROOT)
    if inbox_root is None or not _within(source, inbox_root):
        return ArchiveItem(**base, outcome=REJECTED, message=NOT_INBOX_SOURCE)

    status = str(item.get("status") or "")
    linked = dict(client_id=_positive(item.get("client_id")), expedient_id=_positive(item.get("expedient_id")),
                  status=status, source=str(source), extension=source.suffix)
    if status == "discarded":
        return ArchiveItem(**base, outcome=REJECTED, message=DISCARDED, **linked)
    if status == "duplicate" or _duplicate_of(item):
        return ArchiveItem(**base, outcome=REJECTED, message=DUPLICATE, **linked)
    if status == "copied_to_box" or str(item.get("copied_to_box_path") or "").strip():
        return ArchiveItem(**base, outcome=REJECTED, message=ALREADY_COPIED, **linked)
    if status != "linked" or linked["client_id"] is None or linked["expedient_id"] is None:
        return ArchiveItem(**base, outcome=REJECTED, message=NOT_LINKED, **linked)
    try:
        size, mtime_ns, digest = _file_state(source)
    except OSError:
        return ArchiveItem(**base, outcome=REJECTED, message=SOURCE_MISSING, **linked)
    recorded = str(item.get("sha256") or "").strip().lower()
    if recorded and recorded != digest:
        return ArchiveItem(**base, outcome=REJECTED, message=HASH_MISMATCH, **linked)
    snapshot = (str(source), *(str(item.get(column) or "") for column in (
        "stored_path", "status", "client_id", "expedient_id", "updated_at", "copied_to_box_path",
        "linked_document_path", "sha256")), size, mtime_ns, digest)
    return ArchiveItem(**base, outcome=READY, source_sha256=digest, snapshot=snapshot, **linked)


def _once(items):
    seen, result = set(), []
    for item in items:
        if item.inbox_item_id is not None and item.inbox_item_id in seen:
            item = replace(item, outcome=REJECTED, message=REPEATED)
        elif item.inbox_item_id is not None:
            seen.add(item.inbox_item_id)
        result.append(item)
    return result


def _check(item):
    """La fila de P3A se calcula sobre el archivo real del origen (su extensión real)."""
    return link_service.DocumentCheck(
        key=item.key, name=item.name, path=item.source, inbox_item_id=item.inbox_item_id,
        outcome=link_service.READY, client_id=item.client_id, expedient_id=item.expedient_id,
        status=item.status, snapshot=item.snapshot)


def _with_row(context, item, row, choice):
    if row.status in (filing_service.PROPOSED, filing_service.COLLISION):
        option = context.option(choice)
        try:
            filing_service.nomenclature_filename(option, item.extension)
        except filing_service.FilingPlanError as exc:
            return replace(item, outcome=REJECTED, message=str(exc))
        message = (f"Se copiará como «{row.proposed_name}»." if row.status == filing_service.PROPOSED
                   else f"Nombre ocupado: se copiará como «{row.proposed_name}» (sin sobrescribir).")
        return replace(item, outcome=READY, message=message, nomenclature_key=option.key,
                       nomenclature_label=option.label, proposed_name=row.proposed_name)
    if row.status == filing_service.PENDING:
        return replace(item, outcome=PENDING, message=row.message, nomenclature_label=row.nomenclature)
    return replace(item, outcome=REJECTED, message=row.message)


def _clean_choices(choices):
    """Solo pares texto -> texto; cualquier otro valor llegado de la UI se ignora."""
    if not isinstance(choices, dict):
        return {}
    return {key: value for key, value in choices.items() if isinstance(key, str) and isinstance(value, str)}


def _review(documents, client_id, expedient_id, folder, choices, db_path):
    """(destino, contexto, carpeta verificada, documentos revisados); solo lectura."""
    try:
        context = filing_service.load_context(client_id, expedient_id, db_path=db_path)
    except filing_service.FilingPlanError as exc:
        raise ArchiveError(str(exc)) from None
    target = context.target
    items = []
    for item in _once(read_document(document, db_path=db_path) for document in documents):
        if item.outcome == READY and (item.client_id, item.expedient_id) != (target.client_id,
                                                                              target.expedient_id):
            item = replace(item, outcome=REJECTED, message=OTHER_TARGET)
        items.append(item)
    folder = folder if isinstance(folder, str) else None
    relative = filing_service.verify_folder(context, folder) if folder is not None else None
    # Nombres y colisiones proyectados por P3A, solo entre los documentos archivables.
    eligible = [index for index, item in enumerate(items) if item.outcome == READY]
    rows = filing_service.build_preview(context, [_check(items[index]) for index in eligible],
                                        folder=relative, choices=choices)
    for index, row in zip(eligible, rows):
        items[index] = _with_row(context, items[index], row, choices.get(items[index].key))
    return target, context, relative, tuple(items)


def _fingerprint(user, target, context, relative, items):
    payload = {
        "user": user["id"], "client": target.client_id, "expedient": target.expedient_id,
        "root": str(context.root.path or ""), "folder": relative,
        "items": [[item.key, item.inbox_item_id, item.outcome, [str(v) for v in item.snapshot],
                   item.nomenclature_key, item.proposed_name] for item in items],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------- public API


def execution_blocker():
    """Por qué la vía real no está disponible, o "" si lo está."""
    return "" if EXECUTION_ENABLED is True else EXECUTION_DISABLED


def inspect_archive(actor, documents, *, db_path=None):
    """Elegibilidad de cada documento y su destino ya vinculado; solo lectura."""
    user = _verified_user(actor, db_path)
    items = _once(read_document(document, db_path=db_path) for document in documents or ())
    targets = sorted({(item.client_id, item.expedient_id) for item in items if item.outcome == READY})
    target, message = None, ""
    if len(targets) == 1:
        try:
            target = link_service.resolve_target(*targets[0])
        except link_service.DocumentLinkError as exc:
            message = str(exc)
    elif targets:
        message = MIXED_TARGETS
    else:
        unarchivable = items and all(item.outcome == NOT_ARCHIVABLE for item in items)
        message = NO_INBOX if unarchivable else NOTHING_TO_ARCHIVE
    if target is None:
        items = [replace(item, outcome=REJECTED, message=message) if item.outcome == READY else item
                 for item in items]
    return ArchiveInspection(user=user, items=tuple(items), target=target, message=message)


def prepare_archive(actor, documents, *, client_id, expedient_id, folder=None, choices=None,
                    db_path=None):
    """Revisión completa (carpeta, nomenclatura, nombre, huella); no escribe nada.

    ``folder``: ruta relativa de una carpeta EXISTENTE listada para el expediente
    ("" es la raíz). ``choices``: clave de documento -> clave de nomenclatura del
    catálogo de ESE expediente. Cualquier otro valor se trata como no elegido.
    """
    user = _verified_user(actor, db_path)
    requests = tuple(dict(document) for document in documents or () if isinstance(document, dict))
    choices = _clean_choices(choices)
    target, context, relative, items = _review(requests, client_id, expedient_id, folder, choices, db_path)
    return ArchivePlan(
        actor=actor, user=user, target=target, context=context, folder=relative,
        choices=tuple(sorted(choices.items())), requests=requests, items=items,
        fingerprint=_fingerprint(user, target, context, relative, items), db_path=db_path)


def _outcome(item, status, message, **extra):
    return ArchiveOutcome(item.key, item.name, item.inbox_item_id, status, message, **extra)


def _confirmed(context, target, relative, item, updated):
    """Comprueba la respuesta real de P3B1 antes de declarar el documento archivado."""
    updated = updated if isinstance(updated, dict) else {}
    trace = updated.get("box_copy") if isinstance(updated.get("box_copy"), dict) else {}
    dest = _resolved(updated.get("copied_to_box_path"))
    folder = context.root.path.joinpath(*PurePosixPath(relative).parts) if relative else context.root.path
    if (updated.get("status") != "copied_to_box" or dest is None or dest.parent != folder
            or _positive(updated.get("client_id")) != target.client_id
            or _positive(updated.get("expedient_id")) != target.expedient_id
            or trace.get("result") not in ("copied", "reused_identical")):
        return _outcome(item, FAILED, NOT_CONFIRMED_BY_INBOX,
                        written_path=str(updated.get("copied_to_box_path") or ""))
    collision = str(trace.get("collision_decision") or "")
    message = f"Copia verificada y registrada como «{dest.name}»."
    if collision == "reused_identical":
        message = f"Ya existía «{dest.name}» idéntico (tamaño y SHA-256): se registra sin duplicarlo."
    if dest.name != item.proposed_name:
        message += f" Nombre previsto: «{item.proposed_name}»."
    return _outcome(item, ARCHIVED, message, final_name=dest.name,
                    destination=dest.relative_to(context.root.path).as_posix(), collision=collision)


def _execute_one(context, target, relative, item, db_path):
    """Un documento: se revalida justo antes de su copia y se comprueba la respuesta."""
    if item.outcome != READY:
        return _outcome(item, item.outcome, item.message)
    current = read_document(item.request(), db_path=db_path)
    if current.outcome != READY:
        return _outcome(item, REJECTED, current.message)
    if current.snapshot != item.snapshot or (current.client_id, current.expedient_id) != (
            target.client_id, target.expedient_id):
        return _outcome(item, REJECTED, STALE_ITEM)
    if relative is None or filing_service.verify_folder(context, relative) != relative:
        return _outcome(item, REJECTED, FOLDER_CHANGED)
    if not _claim(item.inbox_item_id):
        return _outcome(item, REJECTED, IN_FLIGHT)
    try:
        # Servicio certificado P3B1: COPY -> VERIFY -> REGISTER; nombre por nomenclatura del catálogo.
        updated = document_inbox_service.copy_inbox_item_to_expedient_box(
            item.inbox_item_id, expedient_id=target.expedient_id, subfolder=relative,
            nomenclature_key=item.nomenclature_key)
    except document_inbox_service.BoxCopyIncomplete as exc:
        return _outcome(item, INCOMPLETE, f"{exc} Requiere revisión humana; no se reintenta.",
                        written_path=exc.written_path)
    except (ValueError, FileNotFoundError) as exc:
        return _outcome(item, REJECTED, str(exc) or COPY_FAILED)
    except Exception:
        return _outcome(item, FAILED, COPY_FAILED)
    finally:
        _release(item.inbox_item_id)
    return _confirmed(context, target, relative, item, updated)


def execute_archive(plan, *, confirmed, fingerprint):
    """Archiva la copia de los documentos revisados, uno a uno.

    ``confirmed`` tiene que ser exactamente True y ``fingerprint`` la huella del
    plan que se mostró al confirmar. Repetir la ejecución del mismo plan (doble
    clic, reintento) devuelve el mismo resultado sin volver a escribir.
    """
    if not isinstance(plan, ArchivePlan):
        raise ArchiveError(INVALID_REQUEST)
    if confirmed is not True:
        raise ArchiveError(NOT_CONFIRMED)
    if execution_blocker():
        raise ArchiveError(EXECUTION_DISABLED)
    if not isinstance(fingerprint, str) or fingerprint != plan.fingerprint:
        raise ArchiveError(STALE_CONSENT)
    if not plan._lock.acquire(blocking=False):
        raise ArchiveError(IN_PROGRESS)
    try:
        if plan.result is not None:
            return plan.result
        with _consumed_lock:
            if plan.token in _consumed:
                raise ArchiveError(REPLAYED)
        if not plan.ready:
            raise ArchiveError(NOTHING_READY)
        _same_database(plan.db_path)
        user = _verified_user(plan.actor, plan.db_path)
        if user["id"] != plan.user["id"]:
            raise ArchiveError(NOT_AUTHORIZED)
        # Todo se revisa de nuevo: cliente, expediente, carpeta, catálogo, nombres y archivos.
        target, context, relative, items = _review(plan.requests, plan.target.client_id,
                                                   plan.target.expedient_id, plan.folder,
                                                   dict(plan.choices), plan.db_path)
        if _fingerprint(user, target, context, relative, items) != plan.fingerprint:
            raise ArchiveError(STALE)
        with _consumed_lock:
            _consumed.add(plan.token)
        # Se ejecuta lo recién revisado (idéntico a lo confirmado), nunca campos del objeto plan.
        outcomes, stopped = [], False
        for item in items:
            if stopped and item.outcome == READY:
                outcomes.append(_outcome(item, NOT_ATTEMPTED, NOT_ATTEMPTED_MESSAGE))
                continue
            outcome = _execute_one(context, target, relative, item, plan.db_path)
            outcomes.append(outcome)
            stopped = stopped or outcome.status in (INCOMPLETE, FAILED)
        folder = filing_service.ROOT_LABEL if relative == "" else relative
        plan.result = ArchiveResult(target=target, user=user, folder=folder, items=tuple(outcomes))
        return plan.result
    finally:
        plan._lock.release()
