"""
Notas persistentes por documento del visor documental (DV24-P2).

Las notas pertenecen al CRM: nunca se escriben en el PDF, en Bandeja
(document_inbox_items.notes es otro campo, descriptivo) ni en Box.

Identidad documental, resuelta siempre aquí y nunca aceptada de la UI:
- Bandeja: ID inmutable del ítem, validado contra su archivo vigente
  (stored_path o linked_document_path canonicalizados).
- Expediente: ruta relativa canonicalizada bajo la raíz documental del
  expediente (symlinks resueltos, sin ``..`` ni escapes) más el SHA-256 del
  contenido, para no atribuir notas a un archivo reemplazado.
Si no hay identidad fiable se lanza DocumentNotesError sin escribir nada.

Autoría: el actor llega de la sesión autenticada (frontera de aplicación) y
se verifica contra ``users``; el nombre guardado es el de la base, no el de
la UI. El CRM no tiene permisos por documento: está autorizado un usuario
activo sobre un documento resuelto dentro de su ámbito (ítem de Bandeja
existente o archivo bajo la raíz del expediente).

Actividad: solo fuentes existentes en lectura (get_inbox_events de Bandeja;
fecha de modificación del archivo en expedientes). Nunca se crean eventos.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.repositories import document_viewer_notes_repository as repository
from backend.services import document_inbox_service, document_viewer_service


INBOX = "inbox"
EXPEDIENT = "expedient"
MAX_NOTE_LENGTH = 4000

NO_IDENTITY = "No se puede establecer una identidad fiable para este documento: las notas no están disponibles."
NO_ACTOR = "No hay un usuario autenticado: las notas no están disponibles."
NOT_AUTHORIZED = "El usuario no está autorizado para consultar o anotar este documento."
DB_UNAVAILABLE = "La base de datos de notas no está disponible."
NOT_REGISTERED = "El archivo no es un documento registrado del expediente."
OUTSIDE_ROOT = "El archivo no pertenece a la carpeta documental del expediente."
INVALID_PATH = "La ruta del documento no es válida."
CHANGED = "El documento ha cambiado desde que se abrió; recarga las notas antes de añadir otra."

_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_schema_ready = set()
_schema_lock = threading.Lock()


class DocumentNotesError(ValueError):
    """Error visible para la persona usuaria; nunca deja escrituras parciales."""


@dataclass(frozen=True)
class DocumentIdentity:
    kind: str
    ref: str
    path: str
    name: str
    content_sha256: str
    size_bytes: int
    modified_at: str = ""
    inbox_item_id: int | None = None
    expediente_id: int | None = None
    relative_path: str = ""
    # Campo descriptivo ``notes`` del ítem de Bandeja: solo lectura.
    description: str = ""

    @property
    def label(self):
        if self.kind == INBOX:
            return f"Bandeja · documento #{self.inbox_item_id}"
        return f"Expediente {self.expediente_id} · {self.relative_path}"


# ---------------------------------------------------------------------- helpers


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _positive_int(value, message):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise DocumentNotesError(message) from None
    if number <= 0:
        raise DocumentNotesError(message)
    return number


def _input_path(value):
    """Ruta recibida, rechazando vacías, NUL y cualquier componente ``..``."""
    raw = str(value or "").strip()
    if not raw or "\x00" in raw:
        raise DocumentNotesError(INVALID_PATH)
    if ".." in raw.replace("\\", "/").split("/"):
        raise DocumentNotesError(INVALID_PATH)
    return Path(raw)


def _existing_file(path):
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise DocumentNotesError("El documento no existe.") from None
    if not resolved.is_file():
        raise DocumentNotesError("El documento no existe.")
    return resolved


def _fingerprint(path):
    digest = hashlib.sha256()
    try:
        stat = path.stat()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise DocumentNotesError("No se pudo leer el documento.") from None
    modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    return digest.hexdigest(), stat.st_size, modified


def _ensure_schema(db_path):
    key = str(Path(db_path).resolve()) if db_path else None
    with _schema_lock:
        if key in _schema_ready:
            return
        try:
            repository.ensure_schema(db_path=db_path)
        except repository.NotesStorageError:
            raise DocumentNotesError(DB_UNAVAILABLE) from None
        _schema_ready.add(key)


# ---------------------------------------------------------------------- identity


def resolve_inbox_identity(item_id, path):
    item_id = _positive_int(item_id, NO_IDENTITY)
    requested = _input_path(path)
    if not requested.is_absolute():
        raise DocumentNotesError(INVALID_PATH)
    try:
        item = document_inbox_service.get_inbox_item(item_id)
    except ValueError:
        raise DocumentNotesError("El documento de Bandeja no existe.") from None
    except Exception:
        raise DocumentNotesError("No se pudo consultar la Bandeja documental.") from None
    resolved = _existing_file(requested)
    registered = set()
    for key in ("stored_path", "linked_document_path"):
        value = str((item or {}).get(key) or "").strip()
        if value:
            try:
                registered.add(Path(value).resolve(strict=True))
            except (OSError, RuntimeError):
                pass
    if resolved not in registered:
        raise DocumentNotesError("El archivo no corresponde al documento de Bandeja indicado.")
    digest, size, modified = _fingerprint(resolved)
    return DocumentIdentity(
        kind=INBOX, ref=f"inbox:{item_id}", path=str(resolved),
        name=str(item.get("original_filename") or resolved.name),
        content_sha256=digest, size_bytes=size, modified_at=modified,
        inbox_item_id=item_id, description=str(item.get("notes") or "").strip(),
    )


def resolve_expedient_identity(expediente_id, path):
    expediente_id = _positive_int(expediente_id, NO_IDENTITY)
    requested = _input_path(path)
    try:
        root_info = document_viewer_service.get_expediente_document_root(expediente_id)
    except ValueError as exc:
        raise DocumentNotesError(str(exc) or NO_IDENTITY) from None
    except Exception:
        raise DocumentNotesError("No se pudo consultar la carpeta documental del expediente.") from None
    if not root_info.get("exists") or not root_info.get("root_path"):
        raise DocumentNotesError(root_info.get("message") or "La carpeta documental no está disponible.")
    try:
        root = Path(root_info["root_path"]).resolve(strict=True)
    except (OSError, RuntimeError):
        raise DocumentNotesError("La carpeta documental no está disponible.") from None
    resolved = _existing_file(requested if requested.is_absolute() else root / requested)
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        raise DocumentNotesError(OUTSIDE_ROOT) from None
    # Same filter as list_expediente_documents: only listable documents.
    if (not relative.parts
            or any(part.startswith((".", "~")) for part in relative.parts)
            or resolved.suffix.lower() not in document_viewer_service.DOCUMENT_EXTENSIONS):
        raise DocumentNotesError(NOT_REGISTERED)
    relative_key = os.path.normcase(str(relative)).replace("\\", "/")
    digest, size, modified = _fingerprint(resolved)
    return DocumentIdentity(
        kind=EXPEDIENT, ref=f"expedient:{expediente_id}:{relative_key}", path=str(resolved),
        name=resolved.name, content_sha256=digest, size_bytes=size, modified_at=modified,
        expediente_id=expediente_id, relative_path=relative.as_posix(),
    )


def resolve_identity(target):
    """``target``: {"inbox_item_id", "path"} o {"expediente_id", "path"}."""
    target = target if isinstance(target, dict) else {}
    if target.get("inbox_item_id") not in (None, ""):
        return resolve_inbox_identity(target["inbox_item_id"], target.get("path"))
    if target.get("expediente_id") not in (None, ""):
        return resolve_expedient_identity(target["expediente_id"], target.get("path"))
    raise DocumentNotesError(NO_IDENTITY)


# ---------------------------------------------------------------------- actor and content


def authenticated_actor(actor, *, db_path=None):
    """Usuario de sesión verificado en ``users``: activo y con el mismo nombre."""
    if not isinstance(actor, dict) or actor.get("id") in (None, ""):
        raise DocumentNotesError(NO_ACTOR)
    user_id = _positive_int(actor.get("id"), NO_ACTOR)
    try:
        row = repository.get_user(user_id, db_path=db_path)
    except repository.NotesStorageError:
        raise DocumentNotesError(DB_UNAVAILABLE) from None
    if not row or int(row.get("is_active") or 0) != 1:
        raise DocumentNotesError(NOT_AUTHORIZED)
    claimed = actor.get("username")
    if claimed is not None and str(claimed) != str(row["username"]):
        raise DocumentNotesError(NOT_AUTHORIZED)
    return {"id": int(row["id"]), "username": str(row["username"])}


def clean_note_body(body):
    if not isinstance(body, str):
        raise DocumentNotesError("La nota está vacía.")
    text = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise DocumentNotesError("La nota está vacía.")
    if len(text) > MAX_NOTE_LENGTH:
        raise DocumentNotesError(f"La nota supera el máximo de {MAX_NOTE_LENGTH} caracteres.")
    if any(unicodedata.category(char) == "Cc" and char not in "\n\t" for char in text):
        raise DocumentNotesError("La nota contiene caracteres de control no permitidos.")
    return text


# ---------------------------------------------------------------------- activity


def document_activity(identity):
    """(eventos, error) de fuentes reales y en solo lectura."""
    if identity.kind == INBOX:
        try:
            events = document_inbox_service.get_inbox_events(identity.inbox_item_id)
        except Exception:
            return [], "No se pudo leer la actividad de Bandeja."
        return [{
            "at": str(event.get("event_at") or ""),
            "type": str(event.get("event_type") or ""),
            "message": str(event.get("message") or ""),
            "source": "Bandeja",
        } for event in events or ()], None
    if not identity.modified_at:
        return [], None
    return [{
        "at": identity.modified_at,
        "type": "file_modified",
        "message": "Última modificación del archivo",
        "source": "Sistema de archivos",
    }], None


# ---------------------------------------------------------------------- public API


def load_document_notes(actor, target, *, db_path=None):
    """Notas y actividad del documento ``target`` para el usuario de sesión."""
    user = authenticated_actor(actor, db_path=db_path)
    identity = resolve_identity(target)
    _ensure_schema(db_path)
    try:
        if identity.kind == INBOX:
            notes = repository.list_notes(identity.ref, db_path=db_path)
            other_revisions = 0
        else:
            notes = repository.list_notes(identity.ref, content_sha256=identity.content_sha256,
                                          db_path=db_path)
            other_revisions = repository.count_other_revisions(
                identity.ref, identity.content_sha256, db_path=db_path)
    except repository.NotesStorageError:
        raise DocumentNotesError(DB_UNAVAILABLE) from None
    activity, activity_error = document_activity(identity)
    return {
        "identity": identity,
        "user": user,
        "notes": notes,
        "other_revisions": other_revisions,
        "activity": activity,
        "activity_error": activity_error,
    }


def add_document_note(actor, target, body, *, request_id, expected_sha256=None, db_path=None):
    """Guarda una nota del usuario de sesión sobre el documento ``target``.

    ``request_id`` identifica el envío: repetirlo (doble clic, reintento)
    devuelve la misma nota sin otra fila. ``expected_sha256`` es la revisión
    que la persona estaba viendo; si el archivo cambió, no se escribe.
    """
    text = clean_note_body(body)
    request_id = str(request_id or "").strip()
    if not _REQUEST_ID.match(request_id):
        raise DocumentNotesError("Solicitud de nota no válida.")
    user = authenticated_actor(actor, db_path=db_path)
    identity = resolve_identity(target)
    if expected_sha256 is not None and expected_sha256 != identity.content_sha256:
        raise DocumentNotesError(CHANGED)
    _ensure_schema(db_path)
    try:
        note, created = repository.insert_note({
            "document_kind": identity.kind,
            "document_ref": identity.ref,
            "inbox_item_id": identity.inbox_item_id,
            "expediente_id": identity.expediente_id,
            "relative_path": identity.relative_path if identity.kind == EXPEDIENT else None,
            "content_sha256": identity.content_sha256,
            "size_bytes": identity.size_bytes,
            "body": text,
            "author_user_id": user["id"],
            "author_username": user["username"],
            "request_id": request_id,
            "created_at": _utc_now(),
        }, db_path=db_path)
    except repository.NotesStorageError:
        raise DocumentNotesError(DB_UNAVAILABLE) from None
    if (not note or note["document_ref"] != identity.ref
            or int(note["author_user_id"]) != user["id"] or note["body"] != text):
        raise DocumentNotesError("La solicitud ya se usó para otra nota; vuelve a enviarla.")
    return {**note, "created": created}
