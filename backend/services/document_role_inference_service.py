"""
Inferencia conservadora de roles documentales.

Principios:
- una regla explícita gana sobre cualquier inferencia;
- no se asigna rol cuando existen evidencias contradictorias;
- no se infiere por el tipo de expediente;
- se conserva la evidencia usada;
- el servicio es puro y no escribe en base de datos ni en Box.
"""

import re
import unicodedata


ROLE_GENERAL = None

KNOWN_ROLES = {
    "REAGRUPANTE",
    "REAGRUPADO",
    "REPRESENTANTE",
    "TITULAR",
    "SOLICITANTE",
    "HIJOS_MENORES",
    "PADRE",
    "MADRE",
    "CONYUGE",
}


ROLE_PATTERNS = {
    "REAGRUPANTE": (
        r"\bREAGRUPANTE\b",
        r"\bDEL\s+REAGRUPANTE\b",
    ),
    "REAGRUPADO": (
        r"\bREAGRUPADO\b",
        r"\bREAGRUPADA\b",
        r"\bDEL\s+REAGRUPADO\b",
        r"\bDE\s+LA\s+REAGRUPADA\b",
    ),
    "REPRESENTANTE": (
        r"\bREPRESENTANTE\b",
        r"\bAPODERADO\b",
        r"\bAPODERADA\b",
        r"\bMANDATARIO\b",
        r"\bMANDATARIA\b",
    ),
    "TITULAR": (
        r"\bTITULAR\b",
        r"\bDEL\s+TITULAR\b",
    ),
    "SOLICITANTE": (
        r"\bSOLICITANTE\b",
        r"\bDEL\s+SOLICITANTE\b",
    ),
    "HIJOS_MENORES": (
        r"\bHIJO\s+MENOR\b",
        r"\bHIJA\s+MENOR\b",
        r"\bMENOR\b",
        r"\bHIJO\b",
        r"\bHIJA\b",
    ),
    "PADRE": (
        r"\bPADRE\b",
        r"\bDEL\s+PADRE\b",
    ),
    "MADRE": (
        r"\bMADRE\b",
        r"\bDE\s+LA\s+MADRE\b",
    ),
    "CONYUGE": (
        r"\bCONYUGE\b",
        r"\bESPOSO\b",
        r"\bESPOSA\b",
    ),
}


def _normalize(value):
    text = str(value or "").strip().upper()

    text = unicodedata.normalize(
        "NFKD",
        text,
    )
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    text = re.sub(
        r"[_./\\\-]+",
        " ",
        text,
    )
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def normalize_role(value):
    role = _normalize(value).replace(" ", "_")

    aliases = {
        "REAGRUPADA": "REAGRUPADO",
        "APODERADO": "REPRESENTANTE",
        "APODERADA": "REPRESENTANTE",
        "MANDATARIO": "REPRESENTANTE",
        "MANDATARIA": "REPRESENTANTE",
        "HIJO": "HIJOS_MENORES",
        "HIJA": "HIJOS_MENORES",
        "MENOR": "HIJOS_MENORES",
        "HIJO_MENOR": "HIJOS_MENORES",
        "HIJA_MENOR": "HIJOS_MENORES",
        "HIJOS_MENORES": "HIJOS_MENORES",
        "ESPOSO": "CONYUGE",
        "ESPOSA": "CONYUGE",
    }

    role = aliases.get(role, role)

    if role in KNOWN_ROLES:
        return role

    return None


def _roles_from_text(value):
    normalized = _normalize(value)

    if not normalized:
        return set()

    roles = set()

    for role, patterns in ROLE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, normalized):
                roles.add(role)
                break

    return roles


def infer_document_role(
    *,
    explicit_role=None,
    filename=None,
    path=None,
    nomenclature_pattern=None,
):
    """
    Devuelve:
    {
        rol_documental,
        estado,
        evidencias,
        roles_candidatos,
    }

    Estados:
    - EXPLICITO
    - INFERIDO
    - SIN_EVIDENCIA
    - AMBIGUO
    """

    normalized_explicit = normalize_role(
        explicit_role
    )

    if explicit_role and not normalized_explicit:
        return {
            "rol_documental": None,
            "estado": "AMBIGUO",
            "evidencias": [
                {
                    "fuente": "rol_explicito",
                    "valor": explicit_role,
                    "motivo": "ROL_NO_RECONOCIDO",
                }
            ],
            "roles_candidatos": [],
        }

    if normalized_explicit:
        return {
            "rol_documental": normalized_explicit,
            "estado": "EXPLICITO",
            "evidencias": [
                {
                    "fuente": "rol_explicito",
                    "valor": explicit_role,
                    "roles": [normalized_explicit],
                }
            ],
            "roles_candidatos": [
                normalized_explicit
            ],
        }

    sources = [
        ("nombre_archivo", filename),
        ("ruta", path),
        (
            "patron_nomenclatura",
            nomenclature_pattern,
        ),
    ]

    evidences = []
    all_roles = set()

    for source, value in sources:
        roles = _roles_from_text(value)

        if not roles:
            continue

        all_roles.update(roles)
        evidences.append(
            {
                "fuente": source,
                "valor": value,
                "roles": sorted(roles),
            }
        )

    if not all_roles:
        return {
            "rol_documental": None,
            "estado": "SIN_EVIDENCIA",
            "evidencias": [],
            "roles_candidatos": [],
        }

    if len(all_roles) > 1:
        return {
            "rol_documental": None,
            "estado": "AMBIGUO",
            "evidencias": evidences,
            "roles_candidatos": sorted(all_roles),
        }

    role = next(iter(all_roles))

    return {
        "rol_documental": role,
        "estado": "INFERIDO",
        "evidencias": evidences,
        "roles_candidatos": [role],
    }
