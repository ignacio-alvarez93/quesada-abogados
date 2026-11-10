"""
Vinculación lógica de documentos del visor a expedientes (DV24-P3).

Servicio de aplicación sobre ``document_inbox_service.link_inbox_item``, que
no se modifica. Vincular es lógico: el ítem de Bandeja recibe cliente,
expediente y estado ``linked`` y su evento ``linked``. Nunca se copia a Box,
se mueve, renombra o importa un archivo, ni se crea un ítem de Bandeja.

Reglas que el servicio canónico no aplica y se resuelven aquí:
- el expediente existe, está activo y pertenece al cliente elegido; al
  servicio canónico se le pasa siempre ese cliente propietario;
- el ítem existe y la ruta que muestra el visor es su archivo vigente;
- un ítem ya vinculado a ese expediente no se reescribe (idempotente);
- un ítem vinculado a otro expediente o asignado a otro cliente no se
  traslada sin confirmación especial; uno descartado, duplicado o ya
  copiado a Box no se revincula;
- un documento sin ID de Bandeja (carpeta de expediente/Box) no es
  vinculable directamente: no se importa ni se inventa una asignación.

Lotes: ``link_inbox_item`` confirma cada ítem por separado, así que un lote
NO es atómico. Cada documento tiene su propio resultado y un fallo no deshace
los demás. Justo antes de escribir se relee cada ítem; si cambió desde la
revisión, se omite. Las notas del visor no se tocan.

Actor y permisos: el usuario de sesión se verifica como en las notas
(``users``: existe y está activo). El CRM no tiene permisos por expediente;
no se inventan.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

from backend.services import document_inbox_service
from backend.services import document_viewer_notes_service as notes_service


NOT_LINKABLE_MESSAGE = "No vinculable directamente; requiere flujo de incorporación gobernado"
NO_ACTOR = "No hay un usuario autenticado: la vinculación no está disponible."
NOT_AUTHORIZED = "El usuario no está autorizado para vincular documentos."
DB_UNAVAILABLE = "La base de datos no está disponible."
INBOX_UNAVAILABLE = "No se pudo consultar la Bandeja documental."
ITEM_MISSING = "El documento ya no existe en Bandeja."
WRONG_FILE = "El archivo mostrado no corresponde al documento de Bandeja indicado."
REPEATED = "Repetido en la selección: se vincula una sola vez."
STALE = "El documento cambió desde la revisión: no se ha modificado. Revisa de nuevo la vinculación."
LINK_FAILED = "No se pudo vincular el documento."
NOT_CONFIRMED = "Confirma la vinculación antes de continuar."
BATCH_POLICY = ("Cada documento se vincula y confirma por separado: el lote no es atómico y un "
                "fallo no deshace los documentos ya vinculados.")

# Outcome of the review (plan) of one document.
READY = "ready"
UNCHANGED = "unchanged"
TRANSFER = "transfer"
NOT_LINKABLE = "not_linkable"
REJECTED = "rejected"
# Final status of one document after the operation.
LINKED = "linked"
FAILED = "failed"


class DocumentLinkError(ValueError):
    """Error visible para la persona usuaria; se lanza antes de cualquier escritura."""


@dataclass(frozen=True)
class LinkTarget:
    client_id: int
    expedient_id: int
    label: str


@dataclass(frozen=True)
class DocumentCheck:
    """Estado leído de un documento y lo que la vinculación haría con él."""
    key: str
    name: str
    path: str
    inbox_item_id: int | None
    outcome: str
    message: str = ""
    client_id: int | None = None
    expedient_id: int | None = None
    status: str = ""
    duplicate_of: int | None = None
    # Campos del ítem que no deben cambiar entre la revisión y la escritura.
    snapshot: tuple = ()

    def request(self):
        return {"key": self.key, "name": self.name, "path": self.path,
                "inbox_item_id": self.inbox_item_id}


@dataclass(frozen=True)
class LinkOutcome:
    key: str
    name: str
    inbox_item_id: int | None
    status: str
    message: str


@dataclass(frozen=True)
class LinkResult:
    target: LinkTarget
    user: dict
    items: tuple
    # link_inbox_item hace un commit por ítem: nunca se declara atómico.
    atomic: bool = False
    policy: str = BATCH_POLICY

    def count(self, status):
        return sum(1 for item in self.items if item.status == status)

    @property
    def linked(self):
        return self.count(LINKED)

    @property
    def problems(self):
        return sum(1 for item in self.items if item.status not in (LINKED, UNCHANGED))

    @property
    def partial(self):
        return bool(self.problems) and self.problems < len(self.items)

    @property
    def summary(self):
        parts = [f"{self.linked} vinculado(s)", f"{self.count(UNCHANGED)} sin cambios"]
        for status, label in ((NOT_LINKABLE, "no vinculable(s)"), (REJECTED, "rechazado(s)"),
                              (FAILED, "fallido(s)")):
            if self.count(status):
                parts.append(f"{self.count(status)} {label}")
        return " · ".join(parts)


@dataclass
class LinkPlan:
    """Revisión previa de una vinculación; se ejecuta una sola vez."""
    actor: object
    user: dict
    target: LinkTarget
    checks: tuple
    db_path: object = None
    result: LinkResult | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def with_outcome(self, *outcomes):
        return [check for check in self.checks if check.outcome in outcomes]

    def actionable(self, allow_transfer=False):
        return len(self.with_outcome(READY, TRANSFER) if allow_transfer else self.with_outcome(READY))


# ---------------------------------------------------------------------- helpers


def _positive_id(value):
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


def _inactive(value):
    if value in (None, ""):
        return False
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return False


def _snapshot(item):
    return tuple(str(item.get(key) or "") for key in (
        "stored_path", "linked_document_path", "client_id", "expedient_id", "status", "updated_at"))


def verified_user(actor, *, db_path=None):
    """Usuario de sesión verificado en ``users`` (mismo criterio que las notas DV24)."""
    try:
        return notes_service.authenticated_actor(actor, db_path=db_path)
    except notes_service.DocumentNotesError as exc:
        message = {notes_service.NO_ACTOR: NO_ACTOR,
                   notes_service.NOT_AUTHORIZED: NOT_AUTHORIZED}.get(str(exc), DB_UNAVAILABLE)
        raise DocumentLinkError(message) from None


def resolve_target(client_id, expedient_id):
    """Expediente real, activo y del cliente elegido."""
    client_id = _positive_id(client_id)
    if client_id is None:
        raise DocumentLinkError("Selecciona un cliente.")
    expedient_id = _positive_id(expedient_id)
    if expedient_id is None:
        raise DocumentLinkError("Selecciona un expediente.")
    try:
        expedient = document_inbox_service.get_expedient(expedient_id) or {}
    except Exception:
        raise DocumentLinkError("No se pudo consultar el expediente.") from None
    if _positive_id(expedient.get("id")) != expedient_id:
        raise DocumentLinkError(f"El expediente #{expedient_id} no existe.")
    owner = _positive_id(expedient.get("cliente_id"))
    if owner is None:
        raise DocumentLinkError(f"El expediente #{expedient_id} no tiene cliente asignado.")
    if owner != client_id:
        raise DocumentLinkError(f"El expediente #{expedient_id} no pertenece al cliente seleccionado.")
    if _inactive(expedient.get("activo")):
        raise DocumentLinkError(f"El expediente #{expedient_id} está archivado: no admite vinculaciones.")
    number = str(expedient.get("numero_expediente") or "").strip()
    label = f"{number} (#{expedient_id})" if number else f"#{expedient_id}"
    return LinkTarget(client_id, expedient_id, label)


def check_document(document):
    """Lee el ítem de Bandeja del documento; nunca escribe."""
    document = document if isinstance(document, dict) else {}
    path = str(document.get("path") or "").strip()
    base = dict(
        key=str(document.get("key") or "") or f"path:{path}",
        name=str(document.get("name") or "").strip() or (Path(path).name if path else "Documento"),
        path=path,
        inbox_item_id=_positive_id(document.get("inbox_item_id")),
    )
    if base["inbox_item_id"] is None:
        # Carpeta de expediente/Box: no se importa ni se crea un ítem para poder vincular.
        return DocumentCheck(**base, outcome=NOT_LINKABLE, message=NOT_LINKABLE_MESSAGE)
    try:
        item = document_inbox_service.get_inbox_item(base["inbox_item_id"])
    except ValueError:
        return DocumentCheck(**base, outcome=REJECTED, message=ITEM_MISSING)
    except Exception:
        return DocumentCheck(**base, outcome=REJECTED, message=INBOX_UNAVAILABLE)
    if not item or _positive_id(item.get("id")) != base["inbox_item_id"]:
        return DocumentCheck(**base, outcome=REJECTED, message=ITEM_MISSING)
    registered = {_resolved(item.get(key)) for key in ("stored_path", "linked_document_path")} - {None}
    requested = _resolved(path)
    if requested is None or requested not in registered:
        return DocumentCheck(**base, outcome=REJECTED, message=WRONG_FILE)
    return DocumentCheck(
        **base, outcome=READY,
        client_id=_positive_id(item.get("client_id")),
        expedient_id=_positive_id(item.get("expedient_id")),
        status=str(item.get("status") or ""),
        duplicate_of=_positive_id(item.get("duplicate_of_id")) if item.get("is_duplicate") else None,
        snapshot=_snapshot(item),
    )


def decide(check, target):
    """Qué haría la vinculación con un documento ya leído."""
    if check.outcome != READY:
        return check
    if check.status == "discarded":
        return replace(check, outcome=REJECTED,
                       message="Descartado en Bandeja: restáuralo antes de vincularlo.")
    if check.status == "duplicate" or check.duplicate_of:
        principal = f" del documento #{check.duplicate_of}" if check.duplicate_of else ""
        return replace(check, outcome=REJECTED,
                       message=f"Es un duplicado{principal}: vincula el documento principal.")
    if check.expedient_id == target.expedient_id and check.client_id == target.client_id:
        return replace(check, outcome=UNCHANGED, message="Ya vinculado a este expediente: sin cambios.")
    if check.status == "copied_to_box":
        return replace(check, outcome=REJECTED, message=(
            "Ya copiado a Box de otro expediente: su vinculación no se cambia desde el visor."))
    if check.expedient_id and check.expedient_id != target.expedient_id:
        return replace(check, outcome=TRANSFER, message=(
            f"Vinculado al expediente #{check.expedient_id}: trasladarlo requiere confirmación especial."))
    if check.client_id and check.client_id != target.client_id:
        return replace(check, outcome=TRANSFER, message=(
            f"Asignado al cliente #{check.client_id}: reasignarlo requiere confirmación especial."))
    return replace(check, outcome=READY, message=f"Se vinculará al expediente {target.label}.")


# ---------------------------------------------------------------------- public API


def client_options():
    """Clientes activos con el componente de selección de Bandeja ({"id", "label"})."""
    return document_inbox_service.client_autocomplete_options()


def expedient_options(client_id):
    """Expedientes del cliente, con la etiqueta de Bandeja ({"id", "label"})."""
    client_id = _positive_id(client_id)
    if client_id is None:
        return []
    return document_inbox_service.expedient_autocomplete_options_for_client(client_id)


def inspect_documents(actor, documents, *, db_path=None):
    """Estado actual (cliente, expediente) de cada documento; solo lectura."""
    verified_user(actor, db_path=db_path)
    return tuple(check_document(document) for document in documents or ())


def prepare_link(actor, documents, *, client_id, expedient_id, db_path=None):
    """Revisión documento a documento; no escribe nada."""
    user = verified_user(actor, db_path=db_path)
    target = resolve_target(client_id, expedient_id)
    checks, seen = [], set()
    for document in documents or ():
        check = decide(check_document(document), target)
        if check.inbox_item_id in seen:
            check = replace(check, outcome=REJECTED, message=REPEATED)
        elif check.inbox_item_id is not None:
            seen.add(check.inbox_item_id)
        checks.append(check)
    return LinkPlan(actor=actor, user=user, target=target, checks=tuple(checks), db_path=db_path)


def _outcome(check, status, message):
    return LinkOutcome(check.key, check.name, check.inbox_item_id, status, message)


def _execute_one(check, target, allow_transfer):
    if check.outcome in (NOT_LINKABLE, REJECTED):
        return _outcome(check, check.outcome, check.message)
    if check.outcome == TRANSFER and not allow_transfer:
        return _outcome(check, REJECTED, f"{check.message} No confirmado: no se ha modificado.")
    current = decide(check_document(check.request()), target)
    if current.outcome == REJECTED and current.snapshot == ():
        return _outcome(check, REJECTED, current.message)
    if current.snapshot != check.snapshot or current.outcome != check.outcome:
        return _outcome(check, REJECTED, STALE)
    if check.outcome == UNCHANGED:
        return _outcome(check, UNCHANGED, check.message)
    try:
        # Siempre con el cliente propietario: el servicio canónico no lo comprueba.
        updated = document_inbox_service.link_inbox_item(
            check.inbox_item_id, client_id=target.client_id, expedient_id=target.expedient_id)
    except ValueError as exc:
        return _outcome(check, FAILED, str(exc) or LINK_FAILED)
    except Exception:
        return _outcome(check, FAILED, LINK_FAILED)
    updated = updated or {}
    if (_positive_id(updated.get("expedient_id")) != target.expedient_id
            or _positive_id(updated.get("client_id")) != target.client_id):
        return _outcome(check, FAILED, "La Bandeja no confirmó la vinculación: revisa el documento.")
    return _outcome(check, LINKED, f"Vinculado al expediente {target.label}.")


def execute_link(plan, *, confirmed, allow_transfer=False):
    """Vincula los documentos revisados; cada uno se confirma por separado.

    Repetir la ejecución del mismo plan (doble clic, reintento) devuelve el
    mismo resultado sin volver a escribir.
    """
    if not isinstance(plan, LinkPlan):
        raise DocumentLinkError("Solicitud de vinculación no válida.")
    if confirmed is not True:
        raise DocumentLinkError(NOT_CONFIRMED)
    with plan._lock:
        if plan.result is not None:
            return plan.result
        user = verified_user(plan.actor, db_path=plan.db_path)
        if user["id"] != plan.user["id"]:
            raise DocumentLinkError(NOT_AUTHORIZED)
        # El expediente puede haberse borrado, archivado o cambiado de cliente.
        target = resolve_target(plan.target.client_id, plan.target.expedient_id)
        items = tuple(_execute_one(check, target, bool(allow_transfer)) for check in plan.checks)
        plan.result = LinkResult(target=target, user=user, items=items)
        return plan.result


def link_documents(actor, documents, *, client_id, expedient_id, confirmed,
                   allow_transfer=False, db_path=None):
    """Revisión y vinculación en un paso (mismas reglas que el diálogo)."""
    plan = prepare_link(actor, documents, client_id=client_id, expedient_id=expedient_id,
                        db_path=db_path)
    return execute_link(plan, confirmed=confirmed, allow_transfer=allow_transfer)
