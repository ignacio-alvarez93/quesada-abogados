"""
Tareas y avisos creados desde el visor documental (DV30-03).

Adaptador de aplicación: no hay tabla ni outbox propias. La tarea es una
TASK canónica (calendar_task_application_service.create_calendar_task) y el
aviso una alerta del Calendario (calendar_alert_application_service
.create_calendar_alert); cada uno crea su planificación de notificaciones en
la misma transacción. Nunca se envía nada directamente.

Contexto, resuelto siempre aquí y nunca aceptado de la UI:
- actor: usuario de sesión verificado en ``users`` (como las notas DV24);
- documento: identidad de document_viewer_notes_service.resolve_identity
  (ítem de Bandeja con su archivo vigente o archivo bajo la raíz del
  expediente);
- expediente: el del ítem de Bandeja según la Bandeja, o el de la carpeta
  documental verificada; debe existir. Un ítem de Bandeja sin expediente no
  admite acciones: nunca se asigna un expediente por intuición.

``origen_tipo`` es ``DOCUMENTO`` y ``origen_id`` la referencia estable del
documento (``inbox:<id>`` o ``expedient:<id>:<ruta relativa>``): nunca una
ruta absoluta, que tampoco aparece en descripciones.

Idempotencia: ``request_id`` identifica un envío humano; repetirlo (doble
clic, reintento) devuelve el mismo registro. Un envío posterior usa otro.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from backend.services import calendar_alert_application_service as alert_app
from backend.services import calendar_task_application_service as task_app
from backend.services import document_inbox_service
from backend.services import document_viewer_notes_service as notes_service
from backend.services import task_service


ORIGIN = "DOCUMENTO"
PRIORITIES = ("BAJA", "NORMAL", "ALTA", "URGENTE")
MAX_TITLE = 200
MAX_DESCRIPTION = 4000
MAX_RESPONSIBLE = 120

NOT_LINKED = "Vincula primero el documento a un expediente."
NO_EXPEDIENT = "El expediente del documento no existe."
EXPEDIENT_UNAVAILABLE = "No se pudo consultar el expediente del documento."
INBOX_UNAVAILABLE = "No se pudo consultar la Bandeja documental."
CONTEXT_CHANGED = ("El documento ya no está vinculado al expediente mostrado; "
                   "cierra el formulario y vuelve a abrirlo.")
INVALID_REQUEST = "Solicitud no válida; cierra el formulario y vuelve a abrirlo."
REQUEST_REUSED = "La solicitud ya se usó para otro registro; vuelve a enviarla."
TASK_FAILED = ("No se pudo crear la tarea ni planificar sus avisos: no se ha guardado nada. "
               "Revisa los datos y vuelve a intentarlo.")
ALERT_FAILED = ("No se pudo crear el aviso ni planificar su notificación: no se ha guardado nada. "
                "Revisa los datos y vuelve a intentarlo.")

NO_ACTOR = "No hay un usuario autenticado: no se pueden crear tareas ni avisos."
NO_IDENTITY = ("No se puede establecer una identidad fiable para este documento: "
               "no se pueden crear tareas ni avisos.")
NOT_AUTHORIZED = "El usuario no está autorizado para crear tareas o avisos de este documento."
_NOTES_MESSAGES = {
    notes_service.NO_ACTOR: NO_ACTOR,
    notes_service.NO_IDENTITY: NO_IDENTITY,
    notes_service.NOT_AUTHORIZED: NOT_AUTHORIZED,
    notes_service.DB_UNAVAILABLE: "La base de datos no está disponible.",
}

_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_MOMENT_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M",
                   "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M")


class DocumentActionError(ValueError):
    """Error visible para la persona usuaria; nunca deja escrituras parciales."""


@dataclass(frozen=True)
class ActionContext:
    """Documento y expediente verificados para crear una tarea o un aviso."""
    user: dict
    kind: str
    document_ref: str
    document_name: str
    expediente_id: int
    expediente_label: str
    cliente_id: int | None = None
    inbox_item_id: int | None = None
    relative_path: str = ""

    @property
    def document_label(self):
        """Referencia visible sin rutas absolutas."""
        if self.kind == notes_service.INBOX:
            return f"Bandeja #{self.inbox_item_id}"
        return self.relative_path or self.document_name


# ---------------------------------------------------------------------- helpers


def _positive(value):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clean_text(value, *, label, maximum, required=False, multiline=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise DocumentActionError(f"{label}: valor no válido.")
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if required and not text:
        raise DocumentActionError(f"{label} es obligatorio.")
    if len(text) > maximum:
        raise DocumentActionError(f"{label} supera el máximo de {maximum} caracteres.")
    allowed = "\n\t" if multiline else ""
    if any(unicodedata.category(char) == "Cc" and char not in allowed for char in text):
        raise DocumentActionError(f"{label} contiene caracteres de control no permitidos.")
    return text


def _moment(value, *, label, required=True):
    """Fecha y hora con minutos: ``YYYY-MM-DD HH:MM`` o ``dd/mm/aaaa HH:MM``."""
    if isinstance(value, datetime):
        return value.replace(second=0, microsecond=0)
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise DocumentActionError(f"{label} es obligatoria.")
        return None
    for pattern in _MOMENT_FORMATS:
        try:
            return datetime.strptime(raw, pattern).replace(second=0)
        except ValueError:
            continue
    raise DocumentActionError(f"{label} no es válida: usa dd/mm/aaaa y hh:mm.")


def _not_past(moment, label, now):
    if moment < now.replace(second=0, microsecond=0):
        raise DocumentActionError(f"{label} ya ha pasado.")


def _priority(value):
    priority = str(value or "NORMAL").strip().upper()
    if priority not in PRIORITIES or priority not in task_service.VALID_PRIORITIES:
        raise DocumentActionError("Prioridad no válida.")
    return priority


def _request_id(value):
    request_id = str(value or "").strip()
    if not _REQUEST_ID.match(request_id):
        raise DocumentActionError(INVALID_REQUEST)
    return request_id


def _description(text, context):
    origin = (f"Origen: visor documental · «{context.document_name}» "
              f"({context.document_label}) · Expediente {context.expediente_label}")
    return f"{text}\n\n{origin}" if text else origin


def _iso(moment):
    return moment.isoformat(sep=" ") if moment is not None else None


# ---------------------------------------------------------------------- context


def _from_notes_error(exc):
    """Mensaje del servicio de notas, dicho de tareas y avisos cuando nombra las notas."""
    return DocumentActionError(_NOTES_MESSAGES.get(str(exc), str(exc)))


def _verified_user(actor, db_path):
    try:
        return notes_service.authenticated_actor(actor, db_path=db_path)
    except notes_service.DocumentNotesError as exc:
        raise _from_notes_error(exc) from None


def _inbox_expedient(identity):
    try:
        item = document_inbox_service.get_inbox_item(identity.inbox_item_id) or {}
    except ValueError:
        raise DocumentActionError("El documento de Bandeja no existe.") from None
    except Exception:
        raise DocumentActionError(INBOX_UNAVAILABLE) from None
    if _positive(item.get("id")) != identity.inbox_item_id:
        raise DocumentActionError("El documento de Bandeja no existe.")
    expediente_id = _positive(item.get("expedient_id"))
    if expediente_id is None:
        raise DocumentActionError(NOT_LINKED)
    return expediente_id


def _expedient(expediente_id):
    try:
        expediente = document_inbox_service.get_expedient(expediente_id) or {}
    except Exception:
        raise DocumentActionError(EXPEDIENT_UNAVAILABLE) from None
    if _positive(expediente.get("id")) != expediente_id:
        raise DocumentActionError(NO_EXPEDIENT)
    number = str(expediente.get("numero_expediente") or "").strip()
    label = f"{number} (#{expediente_id})" if number else f"#{expediente_id}"
    return label, _positive(expediente.get("cliente_id"))


def resolve_context(actor, target, *, expected_expediente_id=None, db_path=None):
    """Actor, documento y expediente verificados; solo lecturas.

    ``target`` es la petición de identidad de la UI ({"inbox_item_id",
    "path"} o {"expediente_id", "path"}). ``expected_expediente_id`` es el
    expediente que la persona vio en el formulario: si ya no es el del
    documento, se rechaza sin escribir.
    """
    user = _verified_user(actor, db_path)
    try:
        identity = notes_service.resolve_identity(target)
    except notes_service.DocumentNotesError as exc:
        raise _from_notes_error(exc) from None
    if identity.kind == notes_service.INBOX:
        expediente_id = _inbox_expedient(identity)
    else:
        expediente_id = identity.expediente_id
    label, cliente_id = _expedient(expediente_id)
    if expected_expediente_id is not None and _positive(expected_expediente_id) != expediente_id:
        raise DocumentActionError(CONTEXT_CHANGED)
    return ActionContext(
        user=user, kind=identity.kind, document_ref=identity.ref, document_name=identity.name,
        expediente_id=expediente_id, expediente_label=label, cliente_id=cliente_id,
        inbox_item_id=identity.inbox_item_id, relative_path=identity.relative_path,
    )


def _check_reused(record, context):
    """A repeated request_id must return the record of this same document."""
    if (str(record.get("origen_tipo") or "").upper() != ORIGIN
            or str(record.get("origen_id") or "") != context.document_ref
            or _positive(record.get("expediente_id")) != context.expediente_id):
        raise DocumentActionError(REQUEST_REUSED)


# ---------------------------------------------------------------------- public API


def create_task(actor, target, *, titulo, fecha_vencimiento, descripcion="", prioridad="NORMAL",
                responsable="", request_id, expected_expediente_id=None, now=None, db_path=None):
    """TASK canónica del documento ``target`` y su planificación, en una transacción."""
    request_id = _request_id(request_id)
    title = _clean_text(titulo, label="El título", maximum=MAX_TITLE, required=True)
    text = _clean_text(descripcion, label="La descripción", maximum=MAX_DESCRIPTION, multiline=True)
    owner = _clean_text(responsable, label="El responsable", maximum=MAX_RESPONSIBLE)
    priority = _priority(prioridad)
    due = _moment(fecha_vencimiento, label="La fecha de vencimiento")
    _not_past(due, "La fecha de vencimiento", now or datetime.now())
    context = resolve_context(actor, target, expected_expediente_id=expected_expediente_id,
                              db_path=db_path)
    try:
        result = task_app.create_calendar_task(
            titulo=title, fecha_vencimiento=_iso(due), descripcion=_description(text, context),
            cliente_id=context.cliente_id, expediente_id=context.expediente_id,
            prioridad=priority, responsable=owner, origen_tipo=ORIGIN,
            origen_id=context.document_ref, source_key=f"DOCVIEWER:TASK:{request_id}",
            created_by=context.user["username"], db_path=db_path or task_app.DEFAULT_DB_PATH,
        )
    except Exception:
        raise DocumentActionError(TASK_FAILED) from None
    _check_reused(result["task"], context)
    return {**result, "context": context}


def create_alert(actor, target, *, titulo, fecha_evento, fecha_inicio_aviso=None, descripcion="",
                 prioridad="NORMAL", request_id, expected_expediente_id=None, now=None,
                 db_path=None):
    """Aviso del Calendario del documento ``target`` y su notificación, en una transacción."""
    request_id = _request_id(request_id)
    title = _clean_text(titulo, label="El título", maximum=MAX_TITLE, required=True)
    text = _clean_text(descripcion, label="La descripción", maximum=MAX_DESCRIPTION, multiline=True)
    priority = _priority(prioridad)
    event = _moment(fecha_evento, label="La fecha del evento")
    warning = _moment(fecha_inicio_aviso, label="El inicio del aviso", required=False)
    current = now or datetime.now()
    _not_past(event, "La fecha del evento", current)
    if warning is not None:
        _not_past(warning, "El inicio del aviso", current)
        if warning > event:
            raise DocumentActionError("El inicio del aviso no puede ser posterior al evento.")
    context = resolve_context(actor, target, expected_expediente_id=expected_expediente_id,
                              db_path=db_path)
    try:
        result = alert_app.create_calendar_alert(
            titulo=title, fecha_evento=_iso(event), fecha_inicio_aviso=_iso(warning),
            descripcion=_description(text, context), cliente_id=context.cliente_id,
            expediente_id=context.expediente_id, prioridad=priority, origen_tipo=ORIGIN,
            origen_id=context.document_ref, source_key=f"DOCVIEWER:ALERT:{request_id}",
            created_by=context.user["username"], db_path=db_path or alert_app.DEFAULT_DB_PATH,
        )
    except Exception:
        raise DocumentActionError(ALERT_FAILED) from None
    _check_reused(result["alert"], context)
    return {**result, "context": context}


def format_moment(value):
    """dd/mm/aaaa HH:MM de un valor ISO guardado; el texto desconocido, tal cual."""
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(text).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text
