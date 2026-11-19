"""Lectura mínima y controlada de contexto CRM para el Chat Knowledge.

Adaptador de SOLO LECTURA sobre la autoridad ERP existente
(``database/quesada.db``). Existe porque la API de servicio actual
(``expedient_service.get_expediente``) abre una conexión de escritura
y devuelve la fila completa del expediente unida al cliente (NIE,
pasaporte, DNI, observaciones...): no es una proyección segura para
un chat. Este módulo:

- abre siempre ``database.connection.get_readonly_connection`` (URI
  ``mode=ro`` + ``query_only``): nunca crea la base, nunca escribe,
  nunca ejecuta DDL ni PRAGMA propios;
- usa parámetros ligados y listas permitidas de columnas: ningún
  ``SELECT *`` y ninguna columna de ``clientes``;
- resuelve un único expediente por identidad exacta (id o número
  exacto). No ofrece listados, ``LIKE`` ni búsquedas transversales de
  personas o expedientes;
- excluye por defecto identificadores personales, contacto,
  pasaporte/NIE/DNI, datos bancarios, responsable, número de registro,
  observaciones libres, rutas Box y títulos/descripciones libres de
  eventos (pueden contener nombres de documentos o personas);
- no persiste nada: ni copia al índice Knowledge ni caché secundaria.

La autorización NO vive aquí: este adaptador solo expone lecturas
mínimas; la decisión de acceso es del servicio de aplicación.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from database.connection import get_readonly_connection


MAX_EXPEDIENT_EVENTS = 10
MAX_NUMERO_LENGTH = 64

# Lista permitida de hechos proyectables: (clave, etiqueta visible).
EXPEDIENT_FACT_FIELDS = (
    ("numero_expediente", "Número de expediente"),
    ("tipo_expediente", "Tipo de expediente"),
    ("estado_documental", "Estado documental"),
    ("estado_administrativo", "Estado administrativo"),
    ("estado_presentacion", "Estado de presentación"),
    ("fecha_apertura", "Fecha de apertura"),
    ("fecha_presentacion", "Fecha de presentación"),
    ("fecha_resolucion", "Fecha de resolución"),
    ("organo_presentacion", "Órgano de presentación"),
    ("provincia", "Provincia"),
)

EVENT_FACT_FIELDS = (
    "fecha_evento",
    "tipo_evento",
    "estado_anterior",
    "estado_nuevo",
)

_EXPEDIENT_SQL = """
    SELECT
        e.id AS expediente_id,
        e.numero_expediente AS numero_expediente,
        te.nombre AS tipo_expediente,
        ed.nombre AS estado_documental,
        ea.nombre AS estado_administrativo,
        e.estado_presentacion AS estado_presentacion,
        e.fecha_apertura AS fecha_apertura,
        e.fecha_presentacion AS fecha_presentacion,
        e.fecha_resolucion AS fecha_resolucion,
        e.organo_presentacion AS organo_presentacion,
        e.provincia AS provincia
    FROM expedientes e
    LEFT JOIN config_tipos_expediente te
        ON te.id = e.tipo_expediente_id
    LEFT JOIN config_estados_documentales ed
        ON ed.id = e.estado_documental_id
    LEFT JOIN config_estados_administrativos ea
        ON ea.id = e.estado_administrativo_id
    WHERE e.id = ?
      AND e.activo = 1
"""

_EVENTS_SQL = """
    SELECT
        fecha_evento,
        tipo_evento,
        estado_anterior,
        estado_nuevo
    FROM expediente_eventos
    WHERE expediente_id = ?
    ORDER BY fecha_evento DESC, id DESC
    LIMIT ?
"""

_EXPEDIENT_ID_BY_NUMBER_SQL = """
    SELECT id
    FROM expedientes
    WHERE numero_expediente = ?
      AND activo = 1
"""

_ACTIVE_USER_SQL = """
    SELECT id, username, is_active
    FROM users
    WHERE id = ?
"""


class KnowledgeChatContextUnavailable(RuntimeError):
    """La autoridad ERP no pudo leerse (base/esquema ausente o error).

    El mensaje es fijo: nunca incluye rutas, SQL ni datos.
    """


@dataclass(frozen=True, slots=True)
class KnowledgeChatExpedientEvent:
    fecha_evento: str
    tipo_evento: str
    estado_anterior: str = ""
    estado_nuevo: str = ""


@dataclass(frozen=True, slots=True)
class KnowledgeChatExpedientProjection:
    """Proyección mínima, de solo lectura, de un único expediente."""

    expediente_id: int

    # (clave, etiqueta, valor) solo para campos de la lista permitida
    # con valor no vacío.
    facts: tuple[tuple[str, str, str], ...] = ()

    events: tuple[KnowledgeChatExpedientEvent, ...] = ()

    events_truncated: bool = False

    @property
    def numero_expediente(self) -> str:
        for key, _label, value in self.facts:
            if key == "numero_expediente":
                return value

        return ""


def _clean(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def _positive_int(value, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} debe ser entero >= 1")

    return value


class KnowledgeChatContextRepository:
    """Lecturas mínimas sobre la autoridad ERP, en modo solo lectura."""

    def __init__(self, db_path=None, *, connect=None) -> None:
        self._db_path = db_path
        self._connect = connect or get_readonly_connection

    def _read(self, sql: str, params: tuple) -> list[sqlite3.Row]:
        try:
            connection = self._connect(self._db_path)
        except (sqlite3.Error, OSError) as exc:
            raise KnowledgeChatContextUnavailable(
                "La base del CRM no está disponible en modo lectura."
            ) from exc

        try:
            return connection.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise KnowledgeChatContextUnavailable(
                "El esquema del CRM no permite leer el contexto "
                "solicitado."
            ) from exc
        finally:
            connection.close()

    def is_active_user(self, user_id: int, username: str) -> bool:
        """True solo si id y username coinciden con un usuario activo."""

        user_id = _positive_int(user_id, field_name="user_id")
        username = str(username or "").strip()

        if not username:
            return False

        rows = self._read(_ACTIVE_USER_SQL, (user_id,))

        if not rows:
            return False

        row = rows[0]

        return (
            int(row["id"]) == user_id
            and str(row["username"] or "") == username
            and int(row["is_active"] or 0) == 1
        )

    def find_expedient_id_by_number(self, numero_expediente: str) -> int | None:
        """Identidad exacta; nunca coincidencias parciales ni listados."""

        numero = str(numero_expediente or "").strip()

        if not numero or len(numero) > MAX_NUMERO_LENGTH:
            return None

        rows = self._read(_EXPEDIENT_ID_BY_NUMBER_SQL, (numero,))

        if len(rows) != 1:
            return None

        return int(rows[0]["id"])

    def get_expedient_projection(
        self,
        expediente_id: int,
    ) -> KnowledgeChatExpedientProjection | None:
        expediente_id = _positive_int(
            expediente_id, field_name="expediente_id"
        )

        rows = self._read(_EXPEDIENT_SQL, (expediente_id,))

        if not rows:
            return None

        row = rows[0]

        facts = tuple(
            (key, label, _clean(row[key]))
            for key, label in EXPEDIENT_FACT_FIELDS
            if _clean(row[key])
        )

        try:
            event_rows = self._read(
                _EVENTS_SQL,
                (expediente_id, MAX_EXPEDIENT_EVENTS + 1),
            )
        except KnowledgeChatContextUnavailable:
            # La trazabilidad es opcional: sin tabla de eventos el
            # expediente sigue proyectándose sin actuaciones.
            event_rows = []

        events = tuple(
            KnowledgeChatExpedientEvent(
                fecha_evento=_clean(event["fecha_evento"]),
                tipo_evento=_clean(event["tipo_evento"]),
                estado_anterior=_clean(event["estado_anterior"]),
                estado_nuevo=_clean(event["estado_nuevo"]),
            )
            for event in event_rows[:MAX_EXPEDIENT_EVENTS]
        )

        return KnowledgeChatExpedientProjection(
            expediente_id=int(row["expediente_id"]),
            facts=facts,
            events=events,
            events_truncated=len(event_rows) > MAX_EXPEDIENT_EVENTS,
        )
