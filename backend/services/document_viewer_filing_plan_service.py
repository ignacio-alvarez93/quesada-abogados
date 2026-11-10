"""
Destino y nomenclatura de archivo propuestos desde el visor (DV25-P3A).

Previsualización pura: nada de lo que se calcula aquí se reserva ni se
persiste. No se copia, mueve, renombra, crea ni borra ningún archivo o
carpeta, no se escribe en la base de datos y no se llama a las copias de
Bandeja/Box (eso es P3B, tras la verificación de copia segura).

Fuentes reutilizadas (sin catálogo duplicado):
- expediente y cliente: ``document_viewer_link_service.resolve_target``
  (mismas reglas que la vinculación) y ``document_inbox_service.get_expedient``
  para ``box_folder_path``;
- carpetas: ``list_expediente_box_directory`` (explorador readonly);
- nomenclaturas: los lectores de ``document_classification_catalog_service``
  (específicas primero, después transversales, mismos IDs/códigos/roles).

``list_options_for_expedient`` no se llama: ejecuta ``ensure_schema``, que
aplica una migración (CREATE TABLE / INSERT OR IGNORE). P3A no migra; se leen
las mismas consultas sobre una conexión de solo lectura y, si falta una tabla
del catálogo, se informa del bloqueo en lugar de crearla.

DV25-P3B1: ``check_subfolder``, ``check_filename``, ``nomenclature_option`` y
``nomenclature_filename`` son validadores puros que la copia gobernada de
Bandeja reutiliza en backend; siguen sin escribir nada.

DV25-P3B3 (H8): una sola política de destino para previsualizar y copiar. La
raíz y cada carpeta ofrecida pasan el mismo filtro que la copia P3B1
(``reparse_redirects``, sin rutas de red, ``check_subfolder``): nunca se ofrece
un destino que la copia rechazaría.
"""

from __future__ import annotations

import re
import sqlite3
import stat as _stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from backend.services import document_classification_catalog_service as catalog_service
from backend.services import document_inbox_service
from backend.services import document_viewer_link_service as link_service
from backend.services.list_expediente_box_directory import list_expediente_box_directory
from database import connection


PREVIEW_ONLY = ("Previsualización de archivo sin reserva ni persistencia hasta P3B: no se copia, "
                "crea, renombra ni escribe nada en Box ni en el CRM.")
ARCHIVE_PENDING = "Pendiente de verificación de copia segura P3B"
NO_BOX = ("Sin carpeta Box local asociada al expediente: el destino de archivo queda bloqueado. "
          "La vinculación lógica sigue disponible.")
NO_FOLDERS = "La carpeta Box del expediente no contiene subcarpetas: solo puede elegirse la raíz."
CATALOG_UNAVAILABLE = "No se pudo leer el catálogo de nomenclaturas."
SCHEMA_PENDING = ("Nomenclaturas {kind} no disponibles: el esquema del catálogo no está migrado en "
                  "esta base de datos (P3A no migra).")
# "<" es un carácter reservado: ninguna carpeta real puede tener esta etiqueta.
ROOT_LABEL = "<raíz del expediente>"

# Estado de cada fila de la previsualización.
PROPOSED = "propuesto"
COLLISION = "colision_proyectada"
PENDING = "sin_nomenclatura"
NO_INBOX = "sin_bandeja"
BLOCKED = "bloqueado"

SPECIFIC = "EXPEDIENTE"
PROCEDURAL = "PROCEDIMIENTO"

MAX_DEPTH = 4
MAX_FOLDERS = 500
MAX_STEM = 120
_RESERVED = '<>:"/\\|?*'
_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
                    *(f"LPT{n}" for n in range(1, 10))}
_EXTENSION = re.compile(r"^\.[A-Za-z0-9]{1,10}$")

# Copia gobernada (P3B1): límites de lo que se acepta como destino en Box.
MAX_SUBFOLDER_DEPTH = 8
MAX_RELATIVE = 200
MAX_NAME = 200
_DEVICE_NAMES = _WINDOWS_DEVICES | {"CONIN$", "CONOUT$", *(f"COM{d}" for d in "¹²³"),
                                    *(f"LPT{d}" for d in "¹²³")}
UNSAFE_FOLDER = ("Subcarpeta destino no válida: debe ser relativa a la carpeta Box del expediente, "
                 "sin '..', unidades, rutas de red ni nombres reservados de Windows.")
UNSAFE_NAME = ("Nombre de archivo no válido: sin rutas, caracteres reservados, nombres de dispositivo "
               "ni espacio o punto final.")
BAD_SOURCE_EXTENSION = "El origen no tiene una extensión válida."
INCOHERENT_EXTENSION = "La extensión del nombre no coincide con la del documento de origen."
UNKNOWN_NOMENCLATURE = "La nomenclatura indicada no pertenece al catálogo de este expediente."
EMPTY_NOMENCLATURE = "La nomenclatura no produce un nombre de archivo válido."

# Enlaces y reparse points (P3A y P3B1). Los marcadores de la Cloud Files API (Box Drive,
# OneDrive) no redirigen la ruta; cualquier otro reparse point sí.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_IO_REPARSE_TAG_CLOUD = 0x9000001A
_IO_REPARSE_TAG_CLOUD_MASK = 0xFFFF0FFF
_NETWORK_PREFIXES = ("\\\\", "//", "\\/", "/\\")


class FilingPlanError(ValueError):
    """Error visible para la persona usuaria; nunca hay escritura que deshacer."""


@dataclass(frozen=True)
class FilingRoot:
    path: Path | None
    available: bool
    message: str = ""


@dataclass(frozen=True)
class FolderOption:
    relative: str  # POSIX, relativa a la raíz; "" es la raíz
    label: str


@dataclass(frozen=True)
class NomenclatureOption:
    key: str
    label: str
    expedient_id: int
    documento_catalogo_id: int
    codigo: str
    nombre: str
    rol_documental: str | None
    origen: str
    categoria: str = ""

    @property
    def subtitle(self):
        group = "Específica del expediente" if self.origen == SPECIFIC else "Transversal"
        return f"{group} · {self.codigo}" if self.codigo else group

    @property
    def stem(self):
        return f"{self.nombre} {self.rol_documental}".strip() if self.rol_documental else self.nombre


@dataclass(frozen=True)
class FilingContext:
    """Contexto leído para un expediente; cambia de expediente = contexto nuevo."""
    target: object
    root: FilingRoot
    folders: tuple = ()
    options: tuple = ()
    notices: tuple = ()

    def folder(self, relative):
        return next((folder for folder in self.folders if folder.relative == relative), None)

    def option(self, key):
        return next((option for option in self.options if option.key == key), None)


@dataclass(frozen=True)
class PreviewRow:
    key: str
    source_name: str
    inbox_item_id: int | None
    nomenclature: str
    folder: str
    proposed_name: str
    status: str
    message: str


# ---------------------------------------------------------------------- root and folders


def reparse_redirects(st):
    """Enlace simbólico, unión o reparse point que no sea un marcador de nube."""
    if _stat.S_ISLNK(st.st_mode):
        return True
    if not getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    tag = getattr(st, "st_reparse_tag", 0)
    return (tag & _IO_REPARSE_TAG_CLOUD_MASK) != _IO_REPARSE_TAG_CLOUD


def _redirects(path):
    try:
        return reparse_redirects(path.lstat())
    except OSError:
        return True


def expedient_root(expedient_id):
    """Carpeta Box local del expediente; no se crea si falta."""
    try:
        expedient = document_inbox_service.get_expedient(expedient_id) or {}
    except Exception:
        return FilingRoot(None, False, NO_BOX)
    raw = str(expedient.get("box_folder_path") or "").strip()
    if not raw or "\x00" in raw or raw.startswith(_NETWORK_PREFIXES):
        return FilingRoot(None, False, NO_BOX)
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute() or _redirects(path) or not path.is_dir():
            return FilingRoot(None, False, NO_BOX)
        return FilingRoot(path.resolve(strict=True), True)
    except (OSError, RuntimeError):
        return FilingRoot(None, False, NO_BOX)


def _eligible(relative):
    """La copia P3B1 aceptaría esta subcarpeta tal cual."""
    try:
        return check_subfolder(relative) == relative
    except FilingPlanError:
        return False


def _inside(root, relative):
    """Carpeta real bajo la raíz: sin enlaces, uniones ni salidas de la raíz."""
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        try:
            if _redirects(current) or not current.is_dir():
                return False
            if current.resolve(strict=True) != current:  # unión/reparse point de Windows
                return False
        except (OSError, RuntimeError):
            return False
    return True


def clean_relative(value):
    """Ruta relativa POSIX inequívoca o None (absolutas, unidades, '..', vacíos)."""
    if not isinstance(value, str) or "\x00" in value:
        return None
    text = value.replace("\\", "/")
    if text == "":
        return ""
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return None
    parts = text.split("/")
    if any(part in ("", ".", "..") or part != part.strip() or any(c in part for c in _RESERVED)
           for part in parts):
        return None
    return "/".join(parts)


def list_folders(root):
    """Subcarpetas existentes (relativas), en orden; nunca crea ni sigue enlaces."""
    if not root.available:
        return ()
    folders, pending = [FolderOption("", ROOT_LABEL)], [("", 0)]
    while pending and len(folders) < MAX_FOLDERS:
        relative, depth = pending.pop(0)
        if depth >= MAX_DEPTH:
            continue
        try:
            listing = list_expediente_box_directory(str(root.path / relative), relative_base=str(root.path))
        except (OSError, ValueError):
            continue
        for entry in listing.get("folders") or ():
            name = str(entry.get("name") or "")
            if not name or name.startswith((".", "~")):
                continue
            child = clean_relative(f"{relative}/{name}" if relative else name)
            if child is None or not _eligible(child) or not _inside(root.path, child):
                continue
            folders.append(FolderOption(child, child))
            pending.append((child, depth + 1))
            if len(folders) >= MAX_FOLDERS:
                break
    return tuple(folders)


def verify_folder(context, relative):
    """La carpeta elegida, si sigue siendo una de las listadas y existe ahora."""
    relative = clean_relative(relative)
    if (relative is None or not _eligible(relative) or not context.root.available
            or context.folder(relative) is None):
        return None
    return relative if _inside(context.root.path, relative) else None


# ---------------------------------------------------------------------- catalog


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _unique_labels(options):
    seen, result = set(), []
    for option in options:
        label = option["label"] or option["codigo"] or f"#{option['documento_catalogo_id']}"
        for candidate in (label, f"{label} ({option['codigo']})",
                          f"{label} ({option['codigo']}) · {option['origen']}"):
            if candidate not in seen:
                label = candidate
                break
        else:
            label = f"{label} · #{option['documento_catalogo_id']}"
        seen.add(label)
        result.append(label)
    return result


def catalog_options(expedient_id, *, db_path=None):
    """(opciones, avisos) del catálogo del expediente, en solo lectura.

    Mismo orden y contenido que ``list_options_for_expedient`` (específicas y
    después transversales); ``db_path`` solo para pruebas aisladas.
    """
    notices = []
    try:
        with closing(connection.get_readonly_connection(db_path)) as conn:
            tables = _tables(conn)
            expediente = catalog_service._get_expedient(conn, expedient_id)
            specific, procedural = [], []
            if {"config_nomenclaturas_catalogo", "config_documentos_catalogo"} <= tables:
                specific = catalog_service._specific_options(conn, expediente)
            else:
                notices.append(SCHEMA_PENDING.format(kind="específicas"))
            if {"config_nomenclaturas_procedimentales", "config_documentos_catalogo"} <= tables:
                procedural = catalog_service._procedural_options(conn)
            else:
                notices.append(SCHEMA_PENDING.format(kind="transversales"))
    except (sqlite3.Error, ValueError, TypeError):
        return (), (CATALOG_UNAVAILABLE,)
    if int(expediente["id"]) != int(expedient_id):
        return (), (CATALOG_UNAVAILABLE,)
    raw = [*specific, *procedural]
    options = []
    for option, label in zip(raw, _unique_labels(raw)):
        rol = option.get("rol_documental") or None
        options.append(NomenclatureOption(
            key=f"{option['origen']}:{option['documento_catalogo_id']}:{rol or ''}",
            label=label,
            expedient_id=int(expedient_id),
            documento_catalogo_id=int(option["documento_catalogo_id"]),
            codigo=option.get("codigo") or "",
            nombre=option.get("nombre") or option.get("codigo") or "",
            rol_documental=rol,
            origen=option["origen"],
            categoria=option.get("categoria") or "",
        ))
    return tuple(options), tuple(notices)


# ---------------------------------------------------------------------- context and preview


def load_context(client_id, expedient_id, *, db_path=None):
    """Raíz, carpetas y nomenclaturas del expediente elegido; solo lectura."""
    try:
        target = link_service.resolve_target(client_id, expedient_id)
    except link_service.DocumentLinkError as exc:
        raise FilingPlanError(str(exc)) from None
    root = expedient_root(target.expedient_id)
    folders = list_folders(root)
    options, notices = catalog_options(target.expedient_id, db_path=db_path)
    notices = list(notices)
    if not root.available:
        notices.insert(0, root.message)
    elif len(folders) == 1:
        notices.insert(0, NO_FOLDERS)
    return FilingContext(target=target, root=root, folders=folders, options=options,
                         notices=tuple(notices))


def safe_stem(value):
    """Nombre sin caracteres reservados de Windows/Box ni nombres de dispositivo."""
    text = "".join("_" if c in _RESERVED or ord(c) < 32 else c for c in str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" ._")[:MAX_STEM].strip(" ._")
    if text.split(".")[0].upper() in _WINDOWS_DEVICES:
        text = f"{text}_"
    return text


def _existing_names(context, relative):
    try:
        listing = list_expediente_box_directory(str(context.root.path / relative),
                                                relative_base=str(context.root.path))
    except (OSError, ValueError):
        return None
    return {str(entry.get("name") or "").casefold()
            for entry in [*(listing.get("files") or ()), *(listing.get("folders") or ())]}


def blocker(context, check):
    """Por qué un documento no admite propuesta de archivo, o "" si la admite.

    Reutiliza las reglas de la vinculación (``decide``): descartados,
    duplicados o ya copiados a Box no reciben nombre propuesto.
    """
    if check.inbox_item_id is None:
        return "Sin documento de Bandeja: no se asocia ni se archiva."
    if check.outcome != link_service.READY:
        return check.message or "No archivable."
    if check.status == "copied_to_box":
        return "Ya copiado a Box: no se propone otra copia."
    decided = link_service.decide(check, context.target)
    if decided.outcome == link_service.REJECTED:
        return decided.message
    return ""


def _row(check, status, message, *, nomenclature="", folder="", proposed=""):
    return PreviewRow(key=check.key, source_name=check.name, inbox_item_id=check.inbox_item_id,
                      nomenclature=nomenclature, folder=folder, proposed_name=proposed,
                      status=status, message=message)


def build_preview(context, checks, *, folder, choices):
    """Una fila por documento; nombres y colisiones solo proyectados.

    ``checks``: ``DocumentCheck`` leídos por el servicio de vinculación (la
    ruta de los READY ya se verificó contra Bandeja). ``choices``: clave de
    documento -> clave de opción del catálogo de ESTE contexto.
    """
    relative = verify_folder(context, folder) if folder is not None else None
    existing = _existing_names(context, relative) if relative is not None else None
    taken = set(existing or ())
    shown = ROOT_LABEL if relative == "" else (relative or "")
    rows = []
    for check in checks:
        reason = blocker(context, check)
        if reason:
            rows.append(_row(check, NO_INBOX if check.inbox_item_id is None else BLOCKED, reason))
            continue
        if not context.root.available:
            rows.append(_row(check, BLOCKED, NO_BOX))
            continue
        option = context.option((choices or {}).get(check.key))
        if option is None or option.expedient_id != context.target.expedient_id:
            rows.append(_row(check, PENDING, "Elige una nomenclatura del catálogo del expediente.",
                             folder=shown))
            continue
        if relative is None:
            rows.append(_row(check, PENDING, "Elige una carpeta existente del expediente.",
                             nomenclature=option.label))
            continue
        if existing is None:
            rows.append(_row(check, BLOCKED, "Sin acceso a la carpeta destino.",
                             nomenclature=option.label, folder=shown))
            continue
        extension = Path(check.path).suffix
        stem = safe_stem(option.stem)
        if not _EXTENSION.match(extension or "") or not stem:
            message = ("El origen no tiene una extensión válida." if stem
                       else "La nomenclatura no produce un nombre de archivo válido.")
            rows.append(_row(check, BLOCKED, message, nomenclature=option.label, folder=shown))
            continue
        # Extensión real del origen, tal cual; la colisión se compara sin mayúsculas (Windows).
        proposed, counter = f"{stem}{extension}", 2
        while proposed.casefold() in taken:
            proposed, counter = f"{stem}_{counter}{extension}", counter + 1
        status, message = PROPOSED, "Propuesta sin reservar."
        if counter > 2:
            status, message = COLLISION, ("El nombre ya existe en la carpeta o en el lote: se propone "
                                          "otro (sin reservar).")
        taken.add(proposed.casefold())
        rows.append(_row(check, status, message, nomenclature=option.label, folder=shown,
                         proposed=proposed))
    return tuple(rows)


# ---------------------------------------------------------------------- P3B1: validated copy target


def _unsafe_component(part):
    """Componente que Windows/Box no tomaría tal cual: vacío, '.', '..', espacio o punto
    final, espacio inicial, controles, reservados (separadores y ':' incluidos) o dispositivo."""
    return (not part or part != part.strip() or part.endswith(".")
            or any(c in _RESERVED or ord(c) < 32 for c in part)
            or part.split(".")[0].rstrip(" ").upper() in _DEVICE_NAMES)


def check_subfolder(value):
    """Subcarpeta relativa POSIX para copiar ("" es la raíz) o ``FilingPlanError``.

    Como ``clean_relative`` y además sin componentes ambiguos en Windows ni rutas
    abusivas. Compatibilidad con Bandeja: se ignoran espacios exteriores y separadores
    finales, y "." es la raíz.
    """
    if not isinstance(value, str):
        raise FilingPlanError(UNSAFE_FOLDER)
    text = value.strip()
    if text in ("", "."):
        return ""
    trimmed = text.rstrip("/\\")
    relative = clean_relative(trimmed) if trimmed else None
    if (not relative or len(relative) > MAX_RELATIVE
            or len(relative.split("/")) > MAX_SUBFOLDER_DEPTH
            or any(_unsafe_component(part) for part in relative.split("/"))):
        raise FilingPlanError(UNSAFE_FOLDER)
    return relative


def check_filename(name, extension):
    """Nombre final validado (nunca saneado en silencio) o ``FilingPlanError``.

    ``extension`` es la extensión real del origen. Un nombre sin extensión recibe la
    del origen; una extensión distinta se rechaza.
    """
    if not isinstance(extension, str) or not _EXTENSION.match(extension):
        raise FilingPlanError(BAD_SOURCE_EXTENSION)
    if not isinstance(name, str) or name.startswith(".") or _unsafe_component(name):
        raise FilingPlanError(UNSAFE_NAME)
    suffix = PurePosixPath(name).suffix
    if suffix.casefold() != extension.casefold():
        if _EXTENSION.match(suffix):
            raise FilingPlanError(INCOHERENT_EXTENSION)
        name = f"{name}{extension}"
    if len(name) > MAX_NAME or _unsafe_component(name):
        raise FilingPlanError(UNSAFE_NAME)
    return name


def nomenclature_option(expedient_id, key, *, db_path=None):
    """Opción del catálogo de ESE expediente con esa clave, o ``FilingPlanError``."""
    options, _notices = catalog_options(expedient_id, db_path=db_path)
    option = next((option for option in options if option.key == key), None)
    if option is None or option.expedient_id != int(expedient_id):
        raise FilingPlanError(UNKNOWN_NOMENCLATURE)
    return option


def nomenclature_filename(option, extension):
    """Mismo nombre base que ``build_preview`` (tipo/subtipo/rol), validado para copiar."""
    stem = safe_stem(option.stem)
    if not stem:
        raise FilingPlanError(EMPTY_NOMENCLATURE)
    return check_filename(f"{stem}{extension}", extension)
