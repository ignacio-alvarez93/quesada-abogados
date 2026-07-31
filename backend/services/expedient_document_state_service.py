"""
Motor de diagnóstico documental de expedientes.

Fase 1:
- NO modifica expedientes.
- NO toca Box.
- Solo lee SQLite:
  - expedientes
  - box_watch_folders
  - box_watch_items
  - config_documentos_requeridos

Objetivo:
- devolver estado documental sugerido;
- listar documentos detectados;
- listar obligatorios faltantes;
- detectar señales fuertes: presentación, requerimiento, concesión, denegación.

Uso:
    from backend.services import expedient_document_state_service as doc_state
    result = doc_state.diagnose_expediente_document_state(expediente_id)
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime

from backend.services import (
    document_requirement_readiness_service as semantic_readiness_service,
)
from backend.services import (
    document_role_inference_service as role_inference_service,
)
from backend.services import (
    document_semantic_state_service as semantic_state_service,
)

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


ESTADO_SIN_DIAGNOSTICO = "SIN_DIAGNOSTICO"
ESTADO_PENDIENTE_DOCUMENTACION = "PENDIENTE_DOCUMENTACION"
ESTADO_COMPLETO_SIN_PRESENTAR = "COMPLETO_SIN_PRESENTAR"
ESTADO_PRESENTADO = "PRESENTADO"
ESTADO_REQUERIDO = "REQUERIDO"
ESTADO_CONCEDIDO = "CONCEDIDO"
ESTADO_DENEGADO = "DENEGADO"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dict(row):
    return dict(row) if row else None


def _norm(value):
    return str(value or "").strip().upper()


def _norm_path(value):
    return str(value or "").replace("\\", "/").rstrip("/")


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn, table_name, column_name):
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(row["name"] == column_name for row in rows)
    except Exception:
        return False


def _get_expediente(conn, expediente_id):
    if not _table_exists(conn, "expedientes"):
        raise ValueError("No existe la tabla expedientes")

    return _dict(
        conn.execute(
            """
            SELECT
                e.*,
                te.nombre AS tipo_expediente_nombre,
                te.codigo AS tipo_expediente_codigo,
                st.nombre AS subtipo_expediente_nombre,
                st.codigo AS subtipo_expediente_codigo
            FROM expedientes e
            LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
            LEFT JOIN config_subtipos_expediente st ON st.id = e.subtipo_expediente_id
            WHERE e.id = ?
            """,
            (int(expediente_id),),
        ).fetchone()
    )


def _get_box_inventory(conn, box_folder_path):
    """
    Devuelve carpetas y archivos bajo la ruta vinculada.
    No accede al disco. Solo SQLite.
    """
    if not box_folder_path:
        return [], []

    if not _table_exists(conn, "box_watch_folders") or not _table_exists(conn, "box_watch_items"):
        return [], []

    root = _norm_path(box_folder_path)

    folders = [
        _dict(r)
        for r in conn.execute(
            """
            SELECT *
            FROM box_watch_folders
            WHERE COALESCE(activo, 1) = 1
              AND (
                    REPLACE(ruta, '\\', '/') = ?
                    OR REPLACE(ruta, '\\', '/') LIKE ?
                  )
            ORDER BY ruta ASC
            """,
            (root, root + "/%"),
        ).fetchall()
    ]

    items = [
        _dict(r)
        for r in conn.execute(
            """
            SELECT *
            FROM box_watch_items
            WHERE COALESCE(activo, 1) = 1
              AND (
                    REPLACE(ruta, '\\', '/') = ?
                    OR REPLACE(ruta, '\\', '/') LIKE ?
                  )
            ORDER BY ruta ASC, nombre_archivo ASC
            """,
            (root, root + "/%"),
        ).fetchall()
    ]

    return folders, items


def _get_required_documents(conn, expediente):
    """
    Documentos obligatorios configurados.

    Regla:
    - trae documentos generales del tipo;
    - si hay subtipo, trae además documentos de ese subtipo;
    - solo obligatorio = 1 y activo = 1.
    """
    if not _table_exists(conn, "config_documentos_requeridos"):
        return []

    tipo_id = expediente.get("tipo_expediente_id")
    subtipo_id = expediente.get("subtipo_expediente_id")

    if not tipo_id:
        return []

    has_subtipo_col = _column_exists(conn, "config_documentos_requeridos", "subtipo_expediente_id")

    if has_subtipo_col:
        sql = """
            SELECT *
            FROM config_documentos_requeridos
            WHERE tipo_expediente_id = ?
              AND COALESCE(obligatorio, 1) = 1
              AND COALESCE(activo, 1) = 1
              AND (
                    subtipo_expediente_id IS NULL
                    OR subtipo_expediente_id = ?
                  )
            ORDER BY orden ASC, nombre_documento ASC
        """
        params = (int(tipo_id), int(subtipo_id) if subtipo_id else -1)
    else:
        sql = """
            SELECT *
            FROM config_documentos_requeridos
            WHERE tipo_expediente_id = ?
              AND COALESCE(obligatorio, 1) = 1
              AND COALESCE(activo, 1) = 1
            ORDER BY orden ASC, nombre_documento ASC
        """
        params = (int(tipo_id),)

    rows = conn.execute(sql, params).fetchall()
    return [_dict(r) for r in rows]



def _get_legacy_nomenclatures(
    conn,
    expediente,
):
    """
    Carga nomenclaturas legacy todavía no sustituidas por una
    nomenclatura canónica vinculada mediante origen_legacy_id.
    """
    if not _table_exists(
        conn,
        "config_nomenclaturas_documentales",
    ):
        return []

    tipo_id = expediente.get("tipo_expediente_id")
    subtipo_id = expediente.get("subtipo_expediente_id")

    if not tipo_id:
        return []

    migrated_legacy_ids = set()

    if _table_exists(
        conn,
        "config_nomenclaturas_catalogo",
    ):
        migrated_legacy_ids = {
            int(row["origen_legacy_id"])
            for row in conn.execute(
                """
                SELECT origen_legacy_id
                FROM config_nomenclaturas_catalogo
                WHERE origen_legacy_id IS NOT NULL
                  AND COALESCE(activo, 1) = 1
                """
            ).fetchall()
        }

    has_subtipo_col = _column_exists(
        conn,
        "config_nomenclaturas_documentales",
        "subtipo_expediente_id",
    )

    if has_subtipo_col:
        sql = """
            SELECT
                n.*,
                d.codigo_documento,
                d.nombre_documento,
                NULL AS rol_documental,
                'LEGACY' AS fuente_nomenclatura,
                1000 AS prioridad
            FROM config_nomenclaturas_documentales n
            JOIN config_documentos_requeridos d
              ON d.id = n.documento_id
            WHERE n.tipo_expediente_id = ?
              AND COALESCE(n.activo, 1) = 1
              AND COALESCE(d.activo, 1) = 1
              AND (
                    n.subtipo_expediente_id IS NULL
                    OR n.subtipo_expediente_id = ?
              )
            ORDER BY n.id
        """
        params = (
            int(tipo_id),
            int(subtipo_id) if subtipo_id else -1,
        )
    else:
        sql = """
            SELECT
                n.*,
                d.codigo_documento,
                d.nombre_documento,
                NULL AS rol_documental,
                'LEGACY' AS fuente_nomenclatura,
                1000 AS prioridad
            FROM config_nomenclaturas_documentales n
            JOIN config_documentos_requeridos d
              ON d.id = n.documento_id
            WHERE n.tipo_expediente_id = ?
              AND COALESCE(n.activo, 1) = 1
              AND COALESCE(d.activo, 1) = 1
            ORDER BY n.id
        """
        params = (int(tipo_id),)

    rows = []

    for row in conn.execute(sql, params).fetchall():
        data = _dict(row)

        if int(data["id"]) in migrated_legacy_ids:
            continue

        rows.append(data)

    return rows


def _get_canonical_nomenclatures(
    conn,
    expediente,
):
    """
    Carga nomenclaturas vinculadas al catálogo documental canónico.
    """
    if not _table_exists(
        conn,
        "config_nomenclaturas_catalogo",
    ):
        return []

    tipo_id = expediente.get("tipo_expediente_id")
    subtipo_id = expediente.get("subtipo_expediente_id")

    if not tipo_id:
        return []

    rows = conn.execute(
        """
        SELECT
            n.id,
            n.tipo_expediente_id,
            n.subtipo_expediente_id,
            n.documento_catalogo_id,
            n.rol_documental,
            n.patron_nombre,
            n.extension_permitida,
            n.prioridad,
            n.activo,
            n.origen_legacy_id,
            d.codigo AS codigo_documento,
            d.nombre AS nombre_documento,
            'CANONICAL' AS fuente_nomenclatura
        FROM config_nomenclaturas_catalogo n
        JOIN config_documentos_catalogo d
          ON d.id = n.documento_catalogo_id
        WHERE n.tipo_expediente_id = ?
          AND COALESCE(n.activo, 1) = 1
          AND COALESCE(d.activo, 1) = 1
          AND (
                n.subtipo_expediente_id IS NULL
                OR n.subtipo_expediente_id = ?
          )
        ORDER BY
            COALESCE(n.prioridad, 100),
            n.id
        """,
        (
            int(tipo_id),
            int(subtipo_id) if subtipo_id else -1,
        ),
    ).fetchall()

    return [_dict(row) for row in rows]


def _get_nomenclatures(conn, expediente):
    """
    Devuelve nomenclaturas canónicas y legacy de respaldo.

    Prioridad:
    - primero nomenclaturas canónicas;
    - después nomenclaturas legacy que todavía no tengan migración
      canónica activa.
    """
    canonical = _get_canonical_nomenclatures(
        conn,
        expediente,
    )
    legacy = _get_legacy_nomenclatures(
        conn,
        expediente,
    )

    return canonical + legacy



def _norm_filename(value):
    value = _norm(value)
    return (
        value
        .replace("_", " ")
        .replace("-", " ")
        .replace(".", " ")
        .replace("Á", "A")
        .replace("É", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ú", "U")
    )


def _pattern_matches_filename(pattern, filename):
    pattern = _norm_filename(pattern)
    filename = _norm_filename(filename)

    if not pattern or not filename:
        return False

    # Coincidencia directa.
    if pattern in filename:
        return True

    # Permitir patrones con * de forma simple.
    if "*" in pattern:
        import re
        regex = "^" + re.escape(pattern).replace("\\*", ".*") + "$"
        return re.search(regex, filename) is not None

    return False


def _doc_codes_from_nomenclatures(items, nomenclatures):
    """
    Segunda capa de detección por patrones configurados.

    Recorre TODOS los archivos bajo la ruta del expediente, estén en raíz,
    PARA PRESENTAR, APORTAR, REQ o cualquier subdirectorio.
    """
    codes = set()
    detected = []

    for item in items or []:
        filename = item.get("nombre_archivo") or ""
        extension = _norm(item.get("extension")).lower().lstrip(".")

        for rule in nomenclatures or []:
            pattern = rule.get("patron_nombre") or ""
            allowed_raw = str(rule.get("extension_permitida") or "").lower().replace(";", ",")
            allowed = {x.strip().lstrip(".") for x in allowed_raw.split(",") if x.strip()}

            if allowed and extension and extension not in allowed:
                continue

            if _pattern_matches_filename(pattern, filename):
                code = _norm(rule.get("codigo_documento"))
                if not code:
                    continue

                codes.add(code)
                source = _norm(
                    rule.get("fuente_nomenclatura")
                )

                detected.append(
                    {
                        "codigo": code,
                        "rol_documental": (
                            _norm(
                                rule.get(
                                    "rol_documental"
                                )
                            )
                            or None
                        ),
                        "archivo": filename,
                        "ruta": item.get("ruta"),
                        "patron": pattern,
                        "nomenclatura_id": rule.get("id"),
                        "fuente_nomenclatura": (
                            source or "LEGACY"
                        ),
                        "origen": (
                            "nomenclatura_canónica"
                            if source == "CANONICAL"
                            else "nomenclatura_legacy"
                        ),
                    }
                )

    return codes, detected



def _doc_codes_from_items(items):
    codes = set()
    detected = []

    for item in items or []:
        code = _norm(item.get("tipo_detectado"))
        if not code or code == "SIN CLASIFICAR":
            continue

        codes.add(code)
        detected.append(
            {
                "codigo": code,
                "archivo": item.get("nombre_archivo"),
                "ruta": item.get("ruta"),
                "estado": item.get("estado"),
            }
        )

    return codes, detected


def _folder_codes_from_folders(folders):
    codes = set()
    detected = []

    for folder in folders or []:
        code = _norm(folder.get("tipo_detectado"))
        if not code or code == "OTROS":
            continue

        codes.add(code)
        detected.append(
            {
                "codigo": code,
                "carpeta": folder.get("nombre_carpeta"),
                "ruta": folder.get("ruta"),
            }
        )

    return codes, detected


def _hay_presentacion(doc_codes, items):
    """
    Señales fuertes de presentación:
    - RESUMEN_EXPEDIENTE
    - JUSTIFICANTE_PRESENTACION
    - archivos que empiecen por COL
    - resguardo / justificante / registro detectado por nombre.
    """
    if "RESUMEN_EXPEDIENTE" in doc_codes:
        return True, "Existe RESUMEN_EXPEDIENTE"
    if "JUSTIFICANTE_PRESENTACION" in doc_codes:
        return True, "Existe JUSTIFICANTE_PRESENTACION"

    for item in items or []:
        name = _norm(item.get("nombre_archivo"))
        if name.startswith("COL"):
            return True, f"Archivo tipo COL detectado: {item.get('nombre_archivo')}"
        if "RESGUARDO" in name:
            return True, f"Resguardo detectado: {item.get('nombre_archivo')}"
        if "JUSTIFICANTE" in name and ("PRESENTACION" in name or "SOLICITUD" in name or "ANEXO" in name):
            return True, f"Justificante detectado: {item.get('nombre_archivo')}"
        if "RESUMEN EXPEDIENTE" in name:
            return True, f"Resumen expediente detectado: {item.get('nombre_archivo')}"

    return False, ""


def _hay_concesion(doc_codes, folder_codes, folders, items):
    if "RESOLUCION_FAVORABLE" in doc_codes or "RESOLUCION_FAVORABLE" in folder_codes:
        return True, "Existe RESOLUCION_FAVORABLE"

    for folder in folders or []:
        text = _norm((folder.get("nombre_carpeta") or "") + " " + (folder.get("ruta") or ""))
        if "CONCESION" in text or "CONCEDIDO" in text or "RES CONCESION" in text:
            return True, f"Carpeta de concesión: {folder.get('nombre_carpeta')}"

    for item in items or []:
        text = _norm(item.get("nombre_archivo"))
        if "CONCESION" in text or "CONCEDIDO" in text or "RESCONCESION" in text or "RES CONCESION" in text:
            return True, f"Documento de concesión: {item.get('nombre_archivo')}"

    return False, ""


def _hay_denegacion(doc_codes, folder_codes, folders, items):
    if "RESOLUCION_DENEGADA" in doc_codes or "RESOLUCION_DENEGADA" in folder_codes:
        return True, "Existe RESOLUCION_DENEGADA"

    for folder in folders or []:
        text = _norm((folder.get("nombre_carpeta") or "") + " " + (folder.get("ruta") or ""))
        if "DENEGACION" in text or "DENEGADA" in text or "RES DENEGACION" in text:
            return True, f"Carpeta de denegación: {folder.get('nombre_carpeta')}"

    for item in items or []:
        text = _norm(item.get("nombre_archivo"))
        if "DENEGACION" in text or "DENEGADA" in text or "RES DENEGACION" in text:
            return True, f"Documento de denegación: {item.get('nombre_archivo')}"

    return False, ""


def _hay_requerimiento(doc_codes, folder_codes, folders, items):
    if "REQUERIMIENTO" in doc_codes or "REQUERIMIENTO" in folder_codes:
        return True, "Existe REQUERIMIENTO"

    for folder in folders or []:
        text = _norm((folder.get("nombre_carpeta") or "") + " " + (folder.get("ruta") or ""))
        if "REQUERIMIENTO" in text or "SUBSANACION" in text or text in ("REQ", "REQ DOC"):
            return True, f"Carpeta de requerimiento: {folder.get('nombre_carpeta')}"

    for item in items or []:
        text = _norm(item.get("nombre_archivo"))
        if "REQUERIMIENTO" in text or text.startswith("REQ ") or text == "REQ PDF":
            return True, f"Documento de requerimiento: {item.get('nombre_archivo')}"

    return False, ""



DOCUMENT_CODE_ALIASES = {
    # Nacionalidad: equivalencias frecuentes entre configuración y clasificador.
    "ACTA_DE_NACIMIENTO_DEL_PAIS_DE_ORIGEN": {"ACTA_NACIMIENTO", "ACTA_NAC", "CERTIFICADO_NACIMIENTO"},
    "ACTA_DE_NACIMIENTO_DE_LOS_HIJOS_MENORES_DE_EDAD": {"ACTA_NACIMIENTO", "ACTA_NAC"},
    "TASA_790016": {"TASA", "TASA_PAGADA", "FORMULARIO_PAGO_TASAS", "FORMULARIO_TASA", "790", "790016"},
    "PODER_O_MANDATO_ACREDITATIVO_DE_REPRESENTACION": {"PODER", "DESIGNACION", "PODER_REPRESENTACION", "MANDATO_REPRESENTACION"},
    "DNI_DE_REPRESENTANTE": {"DNI"},
    "ANTECEDENTES_ESPANA": {"ANTECEDENTES", "AAPP", "REGISTRO_CENTRAL_PENADOS"},
    "ANTECEDENTES": {"ANTECEDENTES_ESPANA", "AAPP", "REGISTRO_CENTRAL_PENADOS"},
    "AAPP": {"ANTECEDENTES", "ANTECEDENTES_ESPANA"},

    "TIE": {"NIE"},
    "NIE": {"TIE", "TARJETA_RESIDENCIA"},
    "TARJETA_RESIDENCIA": {"NIE", "TIE"},

    "PODER_REPRESENTACION": {"PODER", "DESIGNACION", "DESIGNACION_REPRESENTANTE"},
    "DESIGNACION": {"PODER", "PODER_REPRESENTACION"},
    "PODER": {"PODER_REPRESENTACION", "DESIGNACION", "DESIGNACION_REPRESENTANTE"},

    "EMPADRONAMIENTO_HISTORICO": {"EMPADRONAMIENTO", "PADRON"},
    "PADRON": {"EMPADRONAMIENTO", "EMPADRONAMIENTO_HISTORICO"},
    "EMPADRONAMIENTO": {"PADRON", "EMPADRONAMIENTO_HISTORICO"},

    "TASA_PAGADA": {"TASA", "FORMULARIO_TASA", "FORMULARIO_PAGO_TASAS"},
    "FORMULARIO_TASA": {"TASA", "TASA_PAGADA"},
    "FORMULARIO_PAGO_TASAS": {"TASA", "TASA_PAGADA"},
    "TASA": {"TASA_PAGADA", "FORMULARIO_TASA", "FORMULARIO_PAGO_TASAS"},

    "ACTA_NAC": {"ACTA_NACIMIENTO"},
    "ACTA_NACIMIENTO": {"ACTA_NAC"},
    "CERTIFICADO_NACIMIENTO": {"ACTA_NACIMIENTO"},
    "ACTA_MAT": {"ACTA_MATRIMONIO"},
    "ACTA_MATRIMONIO": {"ACTA_MAT", "CERTIFICADO_MATRIMONIO"},

    "CCSE_CERTIFICADO": {"CCSE"},
    "DELE_CERTIFICADO": {"DELE"},

    "PASAP": {"PASAPORTE"},
    "PASAPORTE_ACTUAL": {"PASAPORTE"},
    "PASAPORTE_COMPLETO": {"PASAPORTE"},
}


def _expanded_doc_codes(code):
    code = _norm(code)
    if not code:
        return set()

    expanded = {code}
    pending = [code]

    # Expansión corta y segura para alias de alias.
    while pending:
        current = pending.pop()
        for alias in DOCUMENT_CODE_ALIASES.get(current, set()):
            alias = _norm(alias)
            if alias and alias not in expanded:
                expanded.add(alias)
                pending.append(alias)

    return expanded


def _required_is_detected(required_code, detected_codes):
    required_expanded = _expanded_doc_codes(required_code)

    for detected in detected_codes or set():
        detected_expanded = _expanded_doc_codes(detected)
        if required_expanded.intersection(detected_expanded):
            return True

    return False




def _required_regex_patterns(required_code, required_name):
    """
    Regex de apoyo para documentos obligatorios configurados con códigos largos.

    Se aplica contra:
    - nombre_archivo normalizado
    - tipo_detectado normalizado
    - ruta normalizada

    No sustituye al clasificador: solo evita falsos faltantes.
    """
    code = _norm(required_code)
    name = _norm(required_name)
    combined = f"{code} {name}"

    patterns = []

    if "ACTA" in combined and ("NAC" in combined or "NACIMIENTO" in combined):
        patterns.extend([
            r"\bACTA\s*_?\s*NAC",
            r"\bACTANAC",
            r"NACIMIENTO",
            r"CERTIFICADO\s*_?\s*NAC",
            r"CERTIF\s*_?\s*NAC",
        ])

    if "TASA" in combined or "790" in combined:
        patterns.extend([
            r"\bTASA\b",
            r"TASA\s*_?\s*PAGADA",
            r"FORMULARIO\s*_?\s*PAGO\s*_?\s*TASAS",
            r"\b790\s*_?\s*016\b",
            r"\b790016\b",
        ])

    if "PODER" in combined or "MANDATO" in combined or "REPRESENTACION" in combined:
        patterns.extend([
            r"\bPODER\b",
            r"DESIGNACION",
            r"DESRPRSNT",
            r"MANDATO",
            r"REPRESENTANTE",
            r"REPRESENTACION",
        ])

    if "DNI" in combined:
        patterns.extend([
            r"\bDNI\b",
            r"DNI\s*_?\s*REPRESENTANTE",
            r"PODER\s*_?\s*DNI",
        ])

    if "AAPP" in combined or "ANTECEDENTE" in combined or "PENADO" in combined:
        patterns.extend([
            r"\bAAPP\b",
            r"ANTECEDENTE",
            r"PENALES",
            r"REGISTRO\s*_?\s*PENADOS",
            r"REGISTROPENADOS",
        ])

    if "EMPADRONAMIENTO" in combined or "PADRON" in combined:
        patterns.extend([
            r"EMPADRONAMIENTO",
            r"\bPADRON\b",
            r"PADRON\s*_?\s*HIST",
            r"PADRON\s*_?\s*COLECT",
        ])

    if "PASAPORTE" in combined or "PASAP" in combined:
        patterns.extend([
            r"PASAPORTE",
            r"\bPASAP\b",
            r"PASSPORT",
        ])

    if "NIE" in combined or "TIE" in combined:
        patterns.extend([
            r"\bNIE\b",
            r"\bTIE\b",
            r"TARJETA",
        ])

    if "CCSE" in combined:
        patterns.append(r"\bCCSE\b")

    if "DELE" in combined:
        patterns.append(r"\bDELE\b")

    return patterns


def _required_matches_items_by_regex(required_doc, items):
    import re

    code = required_doc.get("codigo_documento")
    name = required_doc.get("nombre_documento")
    patterns = _required_regex_patterns(code, name)

    if not patterns:
        return None

    for item in items or []:
        haystack = _norm_filename(
            " ".join(
                [
                    str(item.get("nombre_archivo") or ""),
                    str(item.get("tipo_detectado") or ""),
                    str(item.get("ruta") or ""),
                ]
            )
        )

        for pattern in patterns:
            try:
                if re.search(pattern, haystack, flags=re.IGNORECASE):
                    return {
                        "archivo": item.get("nombre_archivo"),
                        "ruta": item.get("ruta"),
                        "pattern": pattern,
                        "matched_by": "regex_obligatorio",
                    }
            except re.error:
                continue

    return None



def _match_required_documents(required_docs, doc_codes, items=None):
    """
    Compara obligatorios con documentos detectados por código.

    Usa coincidencia flexible:
    - código exacto;
    - alias documentales;
    - códigos procedentes de box_classifier.py;
    - códigos procedentes de nomenclaturas configuradas.

    Esto evita falsos faltantes cuando, por ejemplo:
    - obligatorio = ANTECEDENTES_ESPANA
    - detectado = ANTECEDENTES por archivo AAPP.pdf
    """
    faltantes = []
    encontrados = []
    detected_codes = {_norm(c) for c in (doc_codes or set()) if _norm(c)}

    for doc in required_docs or []:
        code = _norm(doc.get("codigo_documento"))
        name = doc.get("nombre_documento") or code

        if not code:
            continue

        regex_match = None

        if _required_is_detected(code, detected_codes):
            encontrados.append(
                {
                    "codigo": code,
                    "nombre": name,
                    "documento_id": doc.get("id"),
                    "matched_by": "codigo_o_alias",
                }
            )
        else:
            regex_match = _required_matches_items_by_regex(doc, items or [])
            if regex_match:
                encontrados.append(
                    {
                        "codigo": code,
                        "nombre": name,
                        "documento_id": doc.get("id"),
                        "matched_by": regex_match.get("matched_by"),
                        "archivo": regex_match.get("archivo"),
                        "pattern": regex_match.get("pattern"),
                    }
                )
            else:
                faltantes.append(
                    {
                        "codigo": code,
                        "nombre": name,
                        "documento_id": doc.get("id"),
                    }
                )

    return encontrados, faltantes


def _confidence(base, required_docs, faltantes, signals):
    if not required_docs:
        return min(0.65, base)

    total = len(required_docs)
    missing = len(faltantes or [])
    completeness = max(0.0, (total - missing) / total)

    signal_bonus = min(0.20, len(signals or []) * 0.04)
    value = (base * 0.55) + (completeness * 0.35) + signal_bonus
    return round(min(0.98, max(0.10, value)), 2)


def _build_semantic_detections(detected_documents):
    """
    Convierte las detecciones actuales en entradas estructuradas
    para el evaluador semántico.

    El rol se obtiene de forma conservadora:
    - rol explícito de la nomenclatura;
    - nombre del archivo;
    - ruta;
    - patrón de nomenclatura.

    Las inferencias ambiguas no asignan rol.
    """
    normalized = []
    seen = set()

    for detection in detected_documents or []:
        code = _norm(detection.get("codigo"))

        if not code:
            continue

        inference = (
            role_inference_service
            .infer_document_role(
                explicit_role=detection.get(
                    "rol_documental"
                ),
                filename=detection.get("archivo"),
                path=detection.get("ruta"),
                nomenclature_pattern=detection.get(
                    "patron"
                ),
            )
        )

        role = inference.get(
            "rol_documental"
        )

        origin = (
            detection.get("origen")
            or (
                "nomenclatura_configurada"
                if detection.get("patron")
                else "box_classifier"
            )
        )

        structured = {
            "codigo": code,
            "rol_documental": role,
            "estado_inferencia_rol": inference.get(
                "estado"
            ),
            "evidencias_rol": inference.get(
                "evidencias",
                [],
            ),
            "roles_candidatos": inference.get(
                "roles_candidatos",
                [],
            ),
            "archivo": detection.get("archivo"),
            "ruta": detection.get("ruta"),
            "origen": origin,
        }

        if detection.get("patron"):
            structured["patron"] = detection.get(
                "patron"
            )

        if detection.get("estado"):
            structured["estado"] = detection.get(
                "estado"
            )

        if detection.get("nomenclatura_id"):
            structured["nomenclatura_id"] = (
                detection.get("nomenclatura_id")
            )

        if detection.get(
            "fuente_nomenclatura"
        ):
            structured["fuente_nomenclatura"] = (
                detection.get(
                    "fuente_nomenclatura"
                )
            )

        identity = (
            structured["codigo"],
            structured["rol_documental"],
            structured.get("archivo"),
            structured.get("ruta"),
            structured["origen"],
        )

        if identity in seen:
            continue

        seen.add(identity)
        normalized.append(structured)

    return normalized



def _summarize_role_inferences(detections):
    """
    Resume los resultados de inferencia de rol sin afectar
    al estado legacy del expediente.
    """
    summary = {
        "total_detecciones": len(detections or []),
        "roles_explicitos": 0,
        "roles_inferidos": 0,
        "sin_evidencia": 0,
        "ambiguos": 0,
        "con_rol": 0,
        "sin_rol": 0,
        "por_rol": {},
        "detecciones_ambiguas": [],
    }

    for detection in detections or []:
        status = (
            detection.get("estado_inferencia_rol")
            or "SIN_EVIDENCIA"
        )
        role = detection.get("rol_documental")

        if status == "EXPLICITO":
            summary["roles_explicitos"] += 1
        elif status == "INFERIDO":
            summary["roles_inferidos"] += 1
        elif status == "AMBIGUO":
            summary["ambiguos"] += 1
            summary["detecciones_ambiguas"].append(
                {
                    "codigo": detection.get("codigo"),
                    "archivo": detection.get("archivo"),
                    "ruta": detection.get("ruta"),
                    "roles_candidatos": detection.get(
                        "roles_candidatos",
                        [],
                    ),
                    "evidencias_rol": detection.get(
                        "evidencias_rol",
                        [],
                    ),
                }
            )
        else:
            summary["sin_evidencia"] += 1

        if role:
            summary["con_rol"] += 1
            summary["por_rol"][role] = (
                summary["por_rol"].get(role, 0)
                + 1
            )
        else:
            summary["sin_rol"] += 1

    summary["por_rol"] = dict(
        sorted(summary["por_rol"].items())
    )

    return summary


def _evaluate_semantic_readiness_safe(
    expediente,
    detections,
):
    """
    Ejecuta el motor semántico sin permitir que sus errores rompan
    el diagnóstico documental legacy.
    """
    try:
        result = (
            semantic_readiness_service
            .evaluate_semantic_requirement_readiness(
                expediente.get("tipo_expediente_id"),
                expediente.get("subtipo_expediente_id"),
                detections,
            )
        )

        return {
            "disponible": True,
            "modo": "PARALELO_NO_VINCULANTE",
            **result,
        }

    except Exception as exc:
        return {
            "disponible": False,
            "modo": "PARALELO_NO_VINCULANTE",
            "completo": None,
            "grupos": [],
            "grupos_bloqueantes": None,
            "opciones_ambiguas_por_rol": [],
            "detecciones": detections,
            "error": str(exc),
        }


def diagnose_expediente_document_state(expediente_id):
    """
    Diagnóstico principal.

    Devuelve:
    {
        estado_sugerido,
        confianza,
        expediente,
        obligatorios,
        detectados,
        faltantes,
        senales,
        resumen
    }
    """
    with closing(_connect()) as conn:
        expediente = _get_expediente(conn, expediente_id)
        if not expediente:
            raise ValueError("Expediente no encontrado")

        root = expediente.get("box_folder_path")
        if not root:
            semantic_result = (
                _evaluate_semantic_readiness_safe(
                    expediente,
                    [],
                )
            )

            decision_semantica = (
                semantic_state_service
                .semantic_document_state(
                    semantic_result
                )
            )
            comparacion_motores = (
                semantic_state_service
                .compare_document_states(
                    ESTADO_SIN_DIAGNOSTICO,
                    decision_semantica,
                )
            )

            return {
                "estado_sugerido": ESTADO_SIN_DIAGNOSTICO,
                "motor_estado_activo": "LEGACY",
                "decision_semantica": decision_semantica,
                "comparacion_motores": comparacion_motores,
                "confianza": 0.10,
                "expediente_id": int(expediente_id),
                "expediente": expediente,
                "obligatorios": [],
                "detectados": [],
                "faltantes": [],
                "semantic_readiness": semantic_result,
                "resumen_inferencia_roles": (
                    _summarize_role_inferences([])
                ),
                "senales": ["El expediente no tiene ruta Box vinculada"],
                "resumen": {
                    "total_archivos": 0,
                    "total_carpetas": 0,
                    "total_obligatorios": 0,
                    "total_faltantes": 0,
                },
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            }

        folders, items = _get_box_inventory(conn, root)
        required_docs = _get_required_documents(conn, expediente)
        nomenclatures = _get_nomenclatures(conn, expediente)

    doc_codes, detected_docs = _doc_codes_from_items(items)
    nomenclature_codes, detected_by_nomenclature = _doc_codes_from_nomenclatures(items, nomenclatures)
    doc_codes = set(doc_codes) | set(nomenclature_codes)
    detected_docs = (
        list(detected_docs or [])
        + list(detected_by_nomenclature or [])
    )

    semantic_detections = _build_semantic_detections(
        detected_docs
    )
    semantic_result = _evaluate_semantic_readiness_safe(
        expediente,
        semantic_detections,
    )
    role_inference_summary = (
        _summarize_role_inferences(
            semantic_detections
        )
    )

    folder_codes, detected_folders = _folder_codes_from_folders(folders)
    encontrados, faltantes = _match_required_documents(required_docs, doc_codes, items=items)

    senales = []

    hay_denegado, motivo_denegado = _hay_denegacion(doc_codes, folder_codes, folders, items)
    hay_concedido, motivo_concedido = _hay_concesion(doc_codes, folder_codes, folders, items)
    hay_req, motivo_req = _hay_requerimiento(doc_codes, folder_codes, folders, items)
    hay_presentado, motivo_presentado = _hay_presentacion(doc_codes, items)

    if motivo_denegado:
        senales.append(motivo_denegado)
    if motivo_concedido:
        senales.append(motivo_concedido)
    if motivo_req:
        senales.append(motivo_req)
    if motivo_presentado:
        senales.append(motivo_presentado)

    decision_semantica = (
        semantic_state_service
        .semantic_document_state(
            semantic_result,
            has_presentacion=hay_presentado,
            has_requerimiento=hay_req,
            has_concesion=hay_concedido,
            has_denegacion=hay_denegado,
        )
    )

    if not required_docs:
        senales.append("No hay documentos obligatorios configurados para este tipo/subtipo")

    # Prioridad: estados finales y señales fuertes ganan sobre faltantes.
    if hay_denegado:
        estado = ESTADO_DENEGADO
        base_conf = 0.92
    elif hay_concedido:
        estado = ESTADO_CONCEDIDO
        base_conf = 0.92
    elif hay_req:
        estado = ESTADO_REQUERIDO
        base_conf = 0.82
    elif hay_presentado:
        estado = ESTADO_PRESENTADO
        base_conf = 0.80
    elif required_docs and not faltantes:
        estado = ESTADO_COMPLETO_SIN_PRESENTAR
        base_conf = 0.78
        senales.append("Todos los documentos obligatorios configurados están detectados")
    elif required_docs and faltantes:
        estado = ESTADO_PENDIENTE_DOCUMENTACION
        base_conf = 0.72
        senales.append(f"Faltan {len(faltantes)} documento(s) obligatorio(s)")
    elif items:
        estado = ESTADO_SIN_DIAGNOSTICO
        base_conf = 0.35
        senales.append("Hay archivos inventariados, pero no hay reglas suficientes para diagnosticar")
    else:
        estado = ESTADO_SIN_DIAGNOSTICO
        base_conf = 0.20
        senales.append("No hay archivos inventariados bajo la ruta Box vinculada")

    comparacion_motores = (
        semantic_state_service
        .compare_document_states(
            estado,
            decision_semantica,
        )
    )

    detectados = {
        "documentos": detected_docs,
        "carpetas": detected_folders,
        "codigos_documento": sorted(doc_codes),
        "codigos_documento_expandidos": sorted({alias for c in doc_codes for alias in _expanded_doc_codes(c)}),
        "codigos_carpeta": sorted(folder_codes),
    }

    return {
        "estado_sugerido": estado,
        "motor_estado_activo": "LEGACY",
        "decision_semantica": decision_semantica,
        "comparacion_motores": comparacion_motores,
        "confianza": _confidence(base_conf, required_docs, faltantes, senales),
        "expediente_id": int(expediente_id),
        "expediente": expediente,
        "obligatorios": required_docs,
        "encontrados": encontrados,
        "detectados": detectados,
        "nomenclaturas_usadas": len(nomenclatures),
        "semantic_readiness": semantic_result,
        "resumen_inferencia_roles": (
            role_inference_summary
        ),
        "faltantes": faltantes,
        "senales": senales,
        "resumen": {
            "total_archivos": len(items),
            "total_carpetas": len(folders),
            "total_obligatorios": len(required_docs),
            "total_encontrados": len(encontrados),
            "total_faltantes": len(faltantes),
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def diagnose_many_expedientes(expediente_ids):
    return [diagnose_expediente_document_state(eid) for eid in expediente_ids or []]


def diagnose_all_active_expedientes(limit=200):
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM expedientes
            WHERE COALESCE(activo, 1) = 1
              AND COALESCE(box_folder_path, '') <> ''
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

    return [diagnose_expediente_document_state(row["id"]) for row in rows]
