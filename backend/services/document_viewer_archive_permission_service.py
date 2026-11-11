"""
Puerta de permiso para archivar copias en Box desde el visor (DV25-P3B3, H1).

Estado real del CRM: ``users`` solo tiene ``id``, ``username`` e ``is_active``.
No hay roles, permisos ni RBAC. Un usuario activo con su nombre correcto está
AUTENTICADO, pero eso no acredita que pueda archivar en Box.

Regla: sin un contrato de permiso aprobado por Dirección, la respuesta es
DENIED. Aquí no se crean roles, no se infieren permisos del nombre de usuario
ni se aceptan los que declare el cliente (claves ``role``, ``permissions``...
del actor se ignoran). Un contrato aprobado se instala en ``APPROVED_CONTRACT``
(en código, nunca desde la UI): un objeto con ``grants(user, *, db_path)`` que
devuelve exactamente True para conceder. Cualquier otro valor o excepción
deniega.

Solo lectura: la verificación del actor reutiliza la de la vinculación (DV24).

DV28 (H1): ``PersistedGrantContract`` es el contrato candidato. Concede solo con
una concesión explícita, vigente y no revocada del permiso ``document.box_copy``
en ``user_permission_grants`` (migración aditiva
``20261111_dv28_box_permissions.sql``: sin concesiones por defecto, sin borrado,
revocación auditada) para el usuario verificado, activo y con el mismo nombre
que cuando se le concedió. NO está instalado: ``APPROVED_CONTRACT`` sigue None
hasta que Dirección apruebe quién puede archivar y se aplique la migración por
el procedimiento con copia de seguridad (DV28-P2).
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass

from backend.services import document_viewer_link_service as link_service
from database import connection


ALLOWED = "allowed"
DENIED = "denied"

# Motivos (código estable para trazas y tests).
NO_ACTOR = "no_actor"
NOT_AUTHENTICATED = "not_authenticated"
CONTRACT_MISSING = "permission_contract_missing"
NOT_GRANTED = "permission_not_granted"
CONTRACT_ERROR = "permission_contract_error"
GRANTED = "granted"

CONTRACT_MISSING_MESSAGE = ("El CRM no tiene un permiso aprobado para archivar en Box: estar activo no "
                            "basta. Requiere decisión de Dirección.")
NOT_GRANTED_MESSAGE = "El usuario no tiene permiso para archivar documentos en Box."
CONTRACT_ERROR_MESSAGE = "No se pudo comprobar el permiso de archivado: se deniega."

# Contrato de permiso aprobado. None = ninguno aprobado = DENIED para todos.
APPROVED_CONTRACT = None

# Permiso canónico de archivar copias en Box (DV28).
BOX_COPY_PERMISSION = "document.box_copy"


class PersistedGrantContract:
    """Concesión explícita persistida de ``document.box_copy``; solo lectura (DV28, H1).

    Candidato a ``APPROVED_CONTRACT``; no instalado. Sin la tabla o ante cualquier
    error lanza, y ``authorize_archive`` lo convierte en DENIED.
    """

    permission = BOX_COPY_PERMISSION

    def grants(self, user, *, db_path=None):
        with closing(connection.get_readonly_connection(db_path)) as conn:
            row = conn.execute(
                "SELECT g.id FROM user_permission_grants AS g JOIN users AS u ON u.id = g.user_id "
                "WHERE g.user_id = ? AND u.username = ? AND g.username = u.username AND u.is_active = 1 "
                "AND g.permission = ? AND g.revoked_at IS NULL AND g.granted_at <= datetime('now') "
                "AND (g.expires_at IS NULL OR g.expires_at > datetime('now')) LIMIT 1",
                (int(user["id"]), str(user["username"]), self.permission),
            ).fetchone()
        return row is not None


@dataclass(frozen=True)
class PermissionDecision:
    outcome: str
    reason: str
    message: str
    user: dict | None = None

    @property
    def allowed(self):
        return self.outcome == ALLOWED


def _deny(reason, message, user=None):
    return PermissionDecision(DENIED, reason, message, user)


def authorize_archive(actor, *, db_path=None):
    """Decisión de permiso para archivar en Box; nunca lanza ni escribe."""
    if not isinstance(actor, dict) or actor.get("id") in (None, ""):
        return _deny(NO_ACTOR, link_service.NO_ACTOR)
    try:
        user = link_service.verified_user(actor, db_path=db_path)
    except link_service.DocumentLinkError as exc:
        return _deny(NOT_AUTHENTICATED, str(exc))
    except Exception:
        return _deny(NOT_AUTHENTICATED, link_service.DB_UNAVAILABLE)
    contract = APPROVED_CONTRACT
    if contract is None:
        return _deny(CONTRACT_MISSING, CONTRACT_MISSING_MESSAGE, user)
    try:
        granted = contract.grants(dict(user), db_path=db_path)
    except Exception:
        return _deny(CONTRACT_ERROR, CONTRACT_ERROR_MESSAGE, user)
    if granted is not True:
        return _deny(NOT_GRANTED, NOT_GRANTED_MESSAGE, user)
    return PermissionDecision(ALLOWED, GRANTED, "", user)
