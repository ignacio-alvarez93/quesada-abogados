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
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.services import document_viewer_link_service as link_service


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
