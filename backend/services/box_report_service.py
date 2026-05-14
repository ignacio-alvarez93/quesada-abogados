"""
Servicio de reporting documental Box.

Solo lectura:
- No escanea.
- No modifica Box.
- No recalcula clasificación.
- Lee el inventario SQLite existente de Box Watch.
"""

import re
import sqlite3
from pathlib import Path

from backend.services import config_service

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


FOCUS_TYPES = [
    "PASAPORTE",
    "PASAPORTE_ACTUAL",
    "PASAPORTE_ANTERIOR",
    "JUSTIFICANTE_PRESENTACION",
    "JUSTIFICANTE_TASA",
    "TASA",
    "REQUERIMIENTO_TASA",
    "FORMULARIO_EXTRANJERIA",
    "EMPADRONAMIENTO",
    "NIE",
    "DNI",
    "PODER",
    "RESOLUCION_FAVORABLE",
    "SIN CLASIFICAR",
]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row):
    return dict(row) if row else None


def _norm_path(value):
    return str(value or "").replace("\\", "/").rstrip("/")


def _scalar(conn, sql, params=None, default=0):
    row = conn.execute(sql, params or []).fetchone()
    if not row:
        return default
    value = row[0]
    return default if value is None else value


def _active_condition(alias=""):
    prefix = f"{alias}." if alias else ""
    return f"COALESCE({prefix}activo, 1) = 1"


def _path_filter_sql(column="ruta"):
    return f"(REPLACE({column}, char(92), '/') = ? OR REPLACE({column}, char(92), '/') LIKE ?)"


def _route_params(path):
    base = _norm_path(path)
    return [base, base + "/%"]


def _percent(numerator, denominator):
    try:
        denominator = int(denominator or 0)
        if denominator <= 0:
            return 0.0
        return round((int(numerator or 0) / denominator) * 100, 1)
    except Exception:
        return 0.0


def _count_root_folders(conn, route_base):
    """
    Cuenta carpetas raíz/expedientes dentro de una ruta configurada.

    Ejemplo:
    C:/Box/.../A SOCIOLABORAL/2026/CLIENTE A
    C:/Box/.../A SOCIOLABORAL/2026/CLIENTE A/JUSTIFICANTE

    cuenta solo CLIENTE A una vez.
    """
    base = _norm_path(route_base or "")
    if not base:
        return 0

    norm_ruta = "REPLACE(ruta, char(92), '/')"
    relative = f"SUBSTR({norm_ruta}, LENGTH(?) + 2)"
    root_expr = f"""
        CASE
            WHEN INSTR({relative}, '/') = 0 THEN {relative}
            ELSE SUBSTR({relative}, 1, INSTR({relative}, '/') - 1)
        END
    """

    sql = f"""
        SELECT COUNT(DISTINCT {root_expr})
        FROM box_watch_folders
        WHERE {_active_condition()}
          AND ({norm_ruta} = ? OR {norm_ruta} LIKE ?)
          AND TRIM({relative}) <> ''
    """

    # root_expr usa relative 4 veces + filtro relative final
    params = [base, base, base, base, base, base + "/%", base]
    return _scalar(conn, sql, params)


def _normalize_sql_text(column):
    return f"LOWER(REPLACE(REPLACE(REPLACE(REPLACE({column}, '_', ' '), '-', ' '), '.', ' '), char(92), '/'))"


def _valid_official_justificante_name_sql(column="nombre_archivo"):
    """
    Justificante oficial válido según resolución Extranjería:
    justificante_23010047L... normalizado a 'justificante 23010047l...'.
    """
    nombre = _normalize_sql_text(column)
    return f"{nombre} LIKE 'justificante 23010047l%'"


def _presentation_context_sql():
    ruta = _normalize_sql_text("ruta")
    return f"""
    (
        {ruta} NOT LIKE '%/tasa%'
        AND {ruta} NOT LIKE '%/tasas%'
        AND {ruta} NOT LIKE '%/req tasa%'
        AND {ruta} NOT LIKE '%/req tasas%'
        AND {ruta} NOT LIKE '%/requerimiento tasa%'
        AND {ruta} NOT LIKE '%/requerimiento tasas%'
        AND {ruta} NOT LIKE '%/requerimiento%'
        AND {ruta} NOT LIKE '%/req doc%'
        AND {ruta} NOT LIKE '%/aportar%'
        AND {ruta} NOT LIKE '%/subsanar%'
        AND {ruta} NOT LIKE '%/subir%'
        AND {ruta} NOT LIKE '%/adjuntar%'
        AND {ruta} NOT LIKE '%/anexo%'
        AND {ruta} NOT LIKE '%/concesion%'
        AND {ruta} NOT LIKE '%/denegacion%'
        AND {ruta} NOT LIKE '%/archivo%'
        AND {ruta} NOT LIKE '%/desistimiento%'
        AND {ruta} NOT LIKE '%ccse%'
        AND {ruta} NOT LIKE '%titulo%'
    )
    """


def _tasa_context_sql():
    ruta = _normalize_sql_text("ruta")
    return f"""
    (
        {ruta} LIKE '%/tasa%'
        OR {ruta} LIKE '%/tasas%'
        OR {ruta} LIKE '%/req tasa%'
        OR {ruta} LIKE '%/req tasas%'
        OR {ruta} LIKE '%/requerimiento tasa%'
        OR {ruta} LIKE '%/requerimiento tasas%'
        OR {ruta} LIKE '%/admision y tasa%'
        OR {ruta} LIKE '%/admision tasa%'
        OR {ruta} LIKE '%/req doc y tasa%'
    )
    """


def _requerimiento_context_sql():
    ruta = _normalize_sql_text("ruta")
    return f"""
    (
        {ruta} LIKE '%/req doc%'
        OR {ruta} LIKE '%/requerimiento%'
        OR {ruta} LIKE '%/req%'
        OR {ruta} LIKE '%/req doc y tasa%'
    )
    """


def _subsanacion_context_sql():
    ruta = _normalize_sql_text("ruta")
    return f"""
    (
        {ruta} LIKE '%/subsanar%'
        OR {ruta} LIKE '%/subsanacion%'
        OR {ruta} LIKE '%/subir%'
        OR {ruta} LIKE '%/aportar%'
    )
    """



def _justificante_presentacion_sql():
    """
    Presentación válida según resolución Extranjería:
    - justificante oficial tipo justificante_23010047L...
    - en raíz del cliente o contexto PARA PRESENTAR/PRESENTAR/PRESENTACION
    - excluye tasa, requerimientos, subsanaciones, concesión, denegación y archivo.
    """
    nombre = _normalize_sql_text("nombre_archivo")
    ruta = _normalize_sql_text("ruta")

    return f"""
    (
        {_valid_official_justificante_name_sql("nombre_archivo")}
        AND {nombre} NOT LIKE '%resguardo%'
        AND {_presentation_context_sql()}
    )
    """


def _justificante_tasa_sql():
    """
    Justificante de tasa válido según resolución Extranjería:
    - debe estar en contexto TASA / REQ TASA / ADMISION Y TASA;
    - puede ser justificante_23010047L... o nombres de abono/pago de tasa;
    - excluye resguardos.
    """
    nombre = _normalize_sql_text("nombre_archivo")

    return f"""
    (
        {_tasa_context_sql()}
        AND {nombre} NOT LIKE '%resguardo%'
        AND (
            {_valid_official_justificante_name_sql("nombre_archivo")}
            OR COALESCE(NULLIF(TRIM(tipo_detectado), ''), estado, 'SIN CLASIFICAR') = 'JUSTIFICANTE_TASA'
            OR {nombre} LIKE '%just abono tasa%'
            OR {nombre} LIKE '%juts abono tasa%'
            OR {nombre} LIKE '%justificante abono tasa%'
            OR {nombre} LIKE '%justificante pago tasa%'
            OR {nombre} LIKE '%tasa pagada%'
            OR {nombre} LIKE '%tasa empresa%'
            OR {nombre} LIKE '%pago tasa%'
            OR {nombre} LIKE '%abono tasa%'
        )
    )
    """


def _count_matching_items(conn, condition_sql, extra_where="", params=None, route_base=None, distinct_root=False):
    """
    Cuenta documentos de reporting.

    Modo normal:
    - cuenta archivos.

    Modo distinct_root=True:
    - cuenta carpetas raíz de expediente con al menos un documento válido.
    - evita inflar métricas cuando un expediente tiene varios justificantes/anexos.
    """
    where = [_active_condition(), condition_sql]
    query_params = list(params or [])

    if extra_where:
        where.append(extra_where)

    if not distinct_root:
        sql = f"""
            SELECT COUNT(*)
            FROM box_watch_items
            WHERE {' AND '.join(where)}
        """
        return _scalar(conn, sql, query_params)

    base = _norm_path(route_base or "")
    if not base:
        sql = f"""
            SELECT COUNT(DISTINCT REPLACE(ruta, char(92), '/'))
            FROM box_watch_items
            WHERE {' AND '.join(where)}
        """
        return _scalar(conn, sql, query_params)

    norm_ruta = "REPLACE(ruta, char(92), '/')"
    relative = f"SUBSTR({norm_ruta}, LENGTH(?) + 2)"
    root_expr = f"""
        CASE
            WHEN INSTR({relative}, '/') = 0 THEN {relative}
            ELSE SUBSTR({relative}, 1, INSTR({relative}, '/') - 1)
        END
    """

    sql = f"""
        SELECT COUNT(DISTINCT {root_expr})
        FROM box_watch_items
        WHERE {' AND '.join(where)}
          AND ({norm_ruta} = ? OR {norm_ruta} LIKE ?)
          AND TRIM({relative}) <> ''
    """

    # root_expr usa relative 4 veces: LENGTH(?) dentro de cada relative.
    # Después se añaden base exacta, base LIKE y relative final.
    final_params = [base, base, base, base] + query_params + [base, base + "/%", base]
    return _scalar(conn, sql, final_params)


def _count_justificantes_presentacion(conn, extra_where="", params=None, route_base=None, distinct_root=False):
    return _count_matching_items(
        conn,
        _justificante_presentacion_sql(),
        extra_where=extra_where,
        params=params,
        route_base=route_base,
        distinct_root=distinct_root,
    )


def _count_justificantes_tasa(conn, extra_where="", params=None, route_base=None, distinct_root=False):
    return _count_matching_items(
        conn,
        _justificante_tasa_sql(),
        extra_where=extra_where,
        params=params,
        route_base=route_base,
        distinct_root=distinct_root,
    )


def get_global_report():
    """Resumen global del inventario documental Box."""
    with _connect() as conn:
        total_archivos = _scalar(conn, f"SELECT COUNT(*) FROM box_watch_items WHERE {_active_condition()}")
        total_carpetas = _scalar(conn, f"SELECT COUNT(*) FROM box_watch_folders WHERE {_active_condition()}")
        total_bytes = _scalar(conn, f"SELECT COALESCE(SUM(tamano_bytes), 0) FROM box_watch_items WHERE {_active_condition()}")
        sin_clasificar = _scalar(
            conn,
            f"""
            SELECT COUNT(*)
            FROM box_watch_items
            WHERE {_active_condition()}
              AND COALESCE(NULLIF(TRIM(tipo_detectado), ''), estado, 'SIN CLASIFICAR') = 'SIN CLASIFICAR'
            """,
        )
        ultimo_escaneo = _scalar(
            conn,
            "SELECT COALESCE(MAX(fecha_fin), MAX(fecha_inicio)) FROM box_watch_scan_runs",
            default="Sin escaneos",
        )
        ultimos_archivos_escaneados = _scalar(
            conn,
            "SELECT COALESCE(total_archivos, 0) FROM box_watch_scan_runs ORDER BY id DESC LIMIT 1",
        )
        ultimas_carpetas_escaneadas = _scalar(
            conn,
            "SELECT COALESCE(total_carpetas, 0) FROM box_watch_scan_runs ORDER BY id DESC LIMIT 1",
        )

        by_type = get_document_type_counts(limit=200)
        type_map = {row["tipo_documento"]: int(row["total"] or 0) for row in by_type}

    return {
        "total_archivos": int(total_archivos or 0),
        "total_carpetas": int(total_carpetas or 0),
        "total_bytes": int(total_bytes or 0),
        "sin_clasificar": int(sin_clasificar or 0),
        "ultimo_escaneo": ultimo_escaneo,
        "ultimos_archivos_escaneados": int(ultimos_archivos_escaneados or 0),
        "ultimas_carpetas_escaneadas": int(ultimas_carpetas_escaneadas or 0),
        "pasaportes": int(type_map.get("PASAPORTE", 0) or 0) + int(type_map.get("PASAPORTE_ACTUAL", 0) or 0) + int(type_map.get("PASAPORTE_ANTERIOR", 0) or 0),
        "justificantes_presentacion": int(_count_justificantes_presentacion(conn) or 0),
        "justificantes_tasa": int(_count_justificantes_tasa(conn) or 0),
        "requerimientos": int(type_map.get("REQUERIMIENTO", 0) or 0),
        "tasas": int(type_map.get("TASA", 0) or 0),
        "formularios_ex": int(type_map.get("FORMULARIO_EXTRANJERIA", 0) or 0),
        "padrones": int(type_map.get("EMPADRONAMIENTO", 0) or 0),
        "nies": int(type_map.get("NIE", 0) or 0),
        "dnis": int(type_map.get("DNI", 0) or 0),
        "resoluciones_favorables": int(type_map.get("RESOLUCION_FAVORABLE", 0) or 0),
    }


def get_document_type_counts(limit=50):
    """Conteo global por tipo documental detectado."""
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                   CASE
                       WHEN LOWER(REPLACE(REPLACE(REPLACE(nombre_archivo, '_', ' '), '-', ' '), '.', ' ')) LIKE 'justificante 23010047l%'
                            AND (
                                LOWER(REPLACE(REPLACE(REPLACE(REPLACE(ruta, '_', ' '), '-', ' '), '.', ' '), char(92), '/')) LIKE '%/tasa%'
                                OR LOWER(REPLACE(REPLACE(REPLACE(REPLACE(ruta, '_', ' '), '-', ' '), '.', ' '), char(92), '/')) LIKE '%/req tasa%'
                                OR LOWER(REPLACE(REPLACE(REPLACE(REPLACE(ruta, '_', ' '), '-', ' '), '.', ' '), char(92), '/')) LIKE '%/admision y tasa%'
                                OR LOWER(REPLACE(REPLACE(REPLACE(REPLACE(ruta, '_', ' '), '-', ' '), '.', ' '), char(92), '/')) LIKE '%/req doc y tasa%'
                            )
                       THEN 'JUSTIFICANTE_TASA'
                       WHEN LOWER(REPLACE(REPLACE(REPLACE(nombre_archivo, '_', ' '), '-', ' '), '.', ' ')) LIKE 'justificante 23010047l%'
                       THEN 'JUSTIFICANTE_PRESENTACION'
                       ELSE COALESCE(NULLIF(TRIM(tipo_detectado), ''), estado, 'SIN CLASIFICAR')
                   END AS tipo_documento,
                   COUNT(*) AS total,
                   COALESCE(SUM(tamano_bytes), 0) AS total_bytes
            FROM box_watch_items
            WHERE {_active_condition()}
            GROUP BY
                   CASE
                       WHEN LOWER(REPLACE(REPLACE(REPLACE(nombre_archivo, '_', ' '), '-', ' '), '.', ' ')) LIKE 'justificante 23010047l%'
                            AND (
                                LOWER(REPLACE(REPLACE(REPLACE(REPLACE(ruta, '_', ' '), '-', ' '), '.', ' '), char(92), '/')) LIKE '%/tasa%'
                                OR LOWER(REPLACE(REPLACE(REPLACE(REPLACE(ruta, '_', ' '), '-', ' '), '.', ' '), char(92), '/')) LIKE '%/req tasa%'
                                OR LOWER(REPLACE(REPLACE(REPLACE(REPLACE(ruta, '_', ' '), '-', ' '), '.', ' '), char(92), '/')) LIKE '%/admision y tasa%'
                                OR LOWER(REPLACE(REPLACE(REPLACE(REPLACE(ruta, '_', ' '), '-', ' '), '.', ' '), char(92), '/')) LIKE '%/req doc y tasa%'
                            )
                       THEN 'JUSTIFICANTE_TASA'
                       WHEN LOWER(REPLACE(REPLACE(REPLACE(nombre_archivo, '_', ' '), '-', ' '), '.', ' ')) LIKE 'justificante 23010047l%'
                       THEN 'JUSTIFICANTE_PRESENTACION'
                       ELSE COALESCE(NULLIF(TRIM(tipo_detectado), ''), estado, 'SIN CLASIFICAR')
                   END
            ORDER BY total DESC, tipo_documento ASC
            LIMIT ?
            """,
            (int(limit or 50),),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def _route_report_for(conn, route):
    resolved = _norm_path(route.get("ruta_resuelta") or "")
    if not resolved:
        return None

    item_filter = _path_filter_sql("ruta")
    folder_filter = _path_filter_sql("ruta")
    item_params = _route_params(resolved)
    folder_params = _route_params(resolved)

    total_archivos = _scalar(conn, f"SELECT COUNT(*) FROM box_watch_items WHERE {_active_condition()} AND {item_filter}", item_params)
    total_carpetas = _scalar(conn, f"SELECT COUNT(*) FROM box_watch_folders WHERE {_active_condition()} AND {folder_filter}", folder_params)
    carpetas_raiz = _count_root_folders(conn, resolved)
    total_bytes = _scalar(conn, f"SELECT COALESCE(SUM(tamano_bytes), 0) FROM box_watch_items WHERE {_active_condition()} AND {item_filter}", item_params)

    rows = conn.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM(tipo_detectado), ''), estado, 'SIN CLASIFICAR') AS tipo_documento,
               COUNT(*) AS total
        FROM box_watch_items
        WHERE {_active_condition()}
          AND {item_filter}
        GROUP BY COALESCE(NULLIF(TRIM(tipo_detectado), ''), estado, 'SIN CLASIFICAR')
        """,
        item_params,
    ).fetchall()
    type_map = {r["tipo_documento"]: int(r["total"] or 0) for r in rows}

    last_scan = _scalar(
        conn,
        """
        SELECT COALESCE(MAX(fecha_fin), MAX(fecha_inicio))
        FROM box_watch_scan_runs
        WHERE REPLACE(ruta_base, char(92), '/') = ?
           OR REPLACE(ruta_base, char(92), '/') LIKE ?
        """,
        _route_params(resolved),
        default="Sin escaneos",
    )

    justificantes_presentacion = _count_justificantes_presentacion(
        conn,
        item_filter,
        item_params,
        route_base=resolved,
        distinct_root=True,
    )
    justificantes_tasa = _count_justificantes_tasa(
        conn,
        item_filter,
        item_params,
        route_base=resolved,
        distinct_root=True,
    )
    requerimientos = _count_matching_items(
        conn,
        _requerimiento_sql(),
        item_filter,
        item_params,
        route_base=resolved,
        distinct_root=True,
    )

    return {
        "tipo_expediente": route.get("tipo_expediente_nombre") or "—",
        "ruta_box": route.get("ruta_box") or "—",
        "ruta_resuelta": resolved,
        "total_carpetas": total_carpetas,
        "carpetas_raiz": carpetas_raiz,
        "total_archivos": total_archivos,
        "total_bytes": total_bytes,
        "pasaportes": type_map.get("PASAPORTE", 0) + type_map.get("PASAPORTE_ACTUAL", 0) + type_map.get("PASAPORTE_ANTERIOR", 0),
        "justificantes_presentacion": justificantes_presentacion,
        "justificantes_tasa": justificantes_tasa,
        "requerimientos": requerimientos,
        "tasas": type_map.get("TASA", 0),
        "formularios_ex": type_map.get("FORMULARIO_EXTRANJERIA", 0),
        "sin_clasificar": type_map.get("SIN CLASIFICAR", 0),
        "porcentaje_presentados": _percent(justificantes_presentacion, carpetas_raiz),
        "porcentaje_requerimientos": _percent(requerimientos, carpetas_raiz),
        "ultimo_escaneo": last_scan,
    }


def get_routes_report():
    """Resumen por rutas Box configuradas."""
    try:
        routes = config_service.get_box_rutas(active_only=True, include_resolved=True)
    except Exception:
        routes = []

    with _connect() as conn:
        result = []
        for route in routes:
            item = _route_report_for(conn, route)
            if item:
                result.append(item)
        return result


def get_recent_scan_runs(limit=20):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, fecha_inicio, fecha_fin, ruta_base, total_archivos, total_carpetas,
                   nuevos, modificados, sin_clasificar, alertas, estado, observaciones
            FROM box_watch_scan_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit or 20),),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_focus_documents(limit=80):
    """Documentos de interés para reporting: justificantes, tasas y pasaportes."""
    focus = tuple(FOCUS_TYPES)
    placeholders = ",".join(["?"] * len(focus))
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT nombre_archivo, extension, tipo_detectado, ruta, tamano_bytes, fecha_modificacion, estado
            FROM box_watch_items
            WHERE {_active_condition()}
              AND (
                    COALESCE(NULLIF(TRIM(tipo_detectado), ''), estado, 'SIN CLASIFICAR') IN ({placeholders})
                    OR LOWER(REPLACE(REPLACE(REPLACE(nombre_archivo, '_', ' '), '-', ' '), '.', ' ')) LIKE 'justificante 23010047l%'
                  )
            ORDER BY fecha_modificacion DESC, updated_at DESC, nombre_archivo ASC
            LIMIT ?
            """,
            list(focus) + [int(limit or 80)],
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

def _reporting_filter_text(value):
    text = str(value or "").replace("\\", "/").replace("·", " ").lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _route_matches_filter(route, route_filter=None):
    """
    Filtro tolerante:
    - acepta texto libre;
    - acepta opción de autocomplete tipo 'TRÁMITE · Box/...';
    - no depende de coincidencia exacta.
    """
    query = _reporting_filter_text(route_filter)
    if not query:
        return True

    haystack = _reporting_filter_text(" ".join([
        str((route or {}).get("tipo_expediente_nombre") or ""),
        str((route or {}).get("ruta_box") or ""),
        str((route or {}).get("ruta_resuelta") or ""),
    ]))

    tokens = [t for t in re.split(r"[\s/>]+", query) if len(t) >= 2]
    if not tokens:
        return True

    # Coincidencia flexible: basta con que todos los tokens significativos estén.
    return all(token in haystack for token in tokens)


def _root_folder_rows_for_route(conn, route, limit=500):
    """
    Devuelve carpetas raíz usando la lógica robusta ya validada en Box Watch.
    Motivo: las rutas Windows/Box pueden estar guardadas de varias formas en SQLite.
    """
    try:
        from backend.services.box_watch_service import list_root_folders_sql_page_for_route_id

        data = list_root_folders_sql_page_for_route_id(
            route.get("id"),
            ruta_contains=None,
            page=1,
            page_size=min(int(limit or 500), 500),
            sort_by="Cliente",
            sort_dir="Ascendente",
        )
        rows = data.get("rows") or []
    except Exception:
        rows = []

    result = []
    for row in rows:
        item = dict(row)
        item["ruta_box"] = route.get("ruta_box") or item.get("config_route_relative") or "—"
        item["tipo_expediente"] = route.get("tipo_expediente_nombre") or "—"
        item["ruta_resuelta"] = route.get("ruta_resuelta") or item.get("config_route_resolved") or ""
        result.append(item)

    return result[: int(limit or 500)]




def _root_folder_rows_for_route_full(conn, route, limit=10000):
    """
    Compatibilidad para reporting avanzado.

    Devuelve todas las carpetas raíz de una ruta usando el motor paginado de Box Watch
    si está disponible, y cae al motor anterior si no.
    No escanea Box. No modifica SQLite.
    """
    try:
        from backend.services.box_watch_service import list_root_folders_sql_page_for_route_id

        page_size = 500
        page = 1
        rows = []
        total = None

        while len(rows) < int(limit or 10000):
            data = list_root_folders_sql_page_for_route_id(
                route.get("id"),
                ruta_contains=None,
                page=page,
                page_size=page_size,
                sort_by="Cliente",
                sort_dir="Ascendente",
            )
            chunk = list(data.get("rows") or [])
            if total is None:
                total = int(data.get("total") or len(chunk))

            if not chunk:
                break

            rows.extend(chunk)

            if len(rows) >= total:
                break

            page += 1

    except Exception:
        rows = _root_folder_rows_for_route(conn, route, limit=limit)

    result = []
    seen = set()

    for row in rows[: int(limit or 10000)]:
        item = dict(row)
        ruta = _norm_path(item.get("ruta"))

        if not ruta or ruta in seen:
            continue

        seen.add(ruta)

        item["ruta_box"] = route.get("ruta_box") or item.get("config_route_relative") or "—"
        item["tipo_expediente"] = route.get("tipo_expediente_nombre") or "—"
        item["ruta_resuelta"] = route.get("ruta_resuelta") or item.get("config_route_resolved") or ""

        result.append(item)

    return result

def _root_has_matching_item(conn, root_path, condition_sql):
    root = _norm_path(root_path or "")
    if not root:
        return False

    norm_ruta = "REPLACE(ruta, char(92), '/')"
    sql = f"""
        SELECT 1
        FROM box_watch_items
        WHERE {_active_condition()}
          AND ({norm_ruta} = ? OR {norm_ruta} LIKE ?)
          AND {condition_sql}
        LIMIT 1
    """
    return conn.execute(sql, (root, root + "/%")).fetchone() is not None


def get_missing_presentation_report(route_filter=None, limit=300):
    """
    Carpetas raíz sin justificante de presentación principal.

    Carga bajo demanda:
    - no se ejecuta al abrir Reporting;
    - usa carpetas raíz robustas de Box Watch;
    - no escanea;
    - no modifica SQLite ni Box.
    """
    try:
        routes = config_service.get_box_rutas(active_only=True, include_resolved=True)
    except Exception:
        routes = []

    max_rows = int(limit or 300)
    result = []

    with _connect() as conn:
        for route in routes:
            if not _route_matches_filter(route, route_filter):
                continue

            roots = _root_folder_rows_for_route(conn, route, limit=10000)
            for root in roots:
                root_path = root.get("ruta")
                if not root_path:
                    continue

                if _root_has_matching_item(conn, root_path, _justificante_presentacion_sql()):
                    continue

                item = dict(root)
                item["tiene_justificante_presentacion"] = False
                item["ultimo_escaneo"] = item.get("ultimo_escaneo") or item.get("last_scan") or _scalar(
                    conn,
                    """
                    SELECT COALESCE(MAX(fecha_fin), MAX(fecha_inicio))
                    FROM box_watch_scan_runs
                    WHERE REPLACE(ruta_base, char(92), '/') = ?
                       OR ? LIKE REPLACE(ruta_base, char(92), '/') || '/%'
                    """,
                    [_norm_path(item.get("ruta_resuelta")), _norm_path(root_path)],
                    default="Sin escaneos",
                )
                result.append(item)

                if len(result) >= max_rows:
                    return result

    return result




def _req_tasa_folder_sql():
    """Carpeta/contexto de tasa según resolución Extranjería."""
    return _tasa_context_sql()



def _requerimiento_sql():
    """
    Requerimiento general según resolución Extranjería:
    exige justificante oficial dentro de REQ DOC / REQUERIMIENTO / REQ.
    Las carpetas REQ DOC Y TASA computan como requerimiento y tasa.
    """
    nombre = _normalize_sql_text("nombre_archivo")
    ruta = _normalize_sql_text("ruta")

    return f"""
    (
        {_valid_official_justificante_name_sql("nombre_archivo")}
        AND {nombre} NOT LIKE '%resguardo%'
        AND {_requerimiento_context_sql()}
        AND (
            {ruta} LIKE '%/req doc y tasa%'
            OR (
                {ruta} NOT LIKE '%/req tasa%'
                AND {ruta} NOT LIKE '%/req tasas%'
                AND {ruta} NOT LIKE '%/requerimiento tasa%'
                AND {ruta} NOT LIKE '%/requerimiento tasas%'
                AND {ruta} NOT LIKE '%/tasa%'
                AND {ruta} NOT LIKE '%/tasas%'
            )
        )
    )
    """



def _subsanacion_sql():
    """
    Subsanación según resolución Extranjería:
    exige justificante oficial dentro de SUBSANAR / SUBIR / APORTAR.
    """
    nombre = _normalize_sql_text("nombre_archivo")
    return f"""
    (
        {_valid_official_justificante_name_sql("nombre_archivo")}
        AND {nombre} NOT LIKE '%resguardo%'
        AND {_subsanacion_context_sql()}
    )
    """


def _build_root_folder_report(route_filter=None, limit=10000, include_when=None):
    """
    Constructor común eficiente para tablas reporting por carpeta raíz.
    No escanea ni modifica Box/SQLite.
    """
    try:
        routes = config_service.get_box_rutas(active_only=True, include_resolved=True)
    except Exception:
        routes = []

    max_rows = int(limit or 10000)
    result = []

    with _connect() as conn:
        for route in routes:
            if not _route_matches_filter(route, route_filter):
                continue

            roots = _root_folder_rows_for_route_full(conn, route, limit=10000)
            for root in roots:
                root_path = root.get("ruta")
                if not root_path:
                    continue

                try:
                    include = bool(include_when(conn, root_path)) if include_when else True
                except Exception:
                    include = False

                if not include:
                    continue

                item = dict(root)
                item["ultimo_escaneo"] = item.get("ultimo_escaneo") or item.get("last_scan") or _scalar(
                    conn,
                    """
                    SELECT COALESCE(MAX(fecha_fin), MAX(fecha_inicio))
                    FROM box_watch_scan_runs
                    WHERE REPLACE(ruta_base, char(92), '/') = ?
                       OR ? LIKE REPLACE(ruta_base, char(92), '/') || '/%'
                    """,
                    [_norm_path(item.get("ruta_resuelta")), _norm_path(root_path)],
                    default="Sin escaneos",
                )
                result.append(item)

                if len(result) >= max_rows:
                    return result

    return result


def get_presented_report(route_filter=None, limit=10000):
    """Carpetas raíz con justificante de presentación válido."""
    return _build_root_folder_report(
        route_filter=route_filter,
        limit=limit,
        include_when=lambda conn, root_path: _root_has_matching_item(conn, root_path, _justificante_presentacion_sql()),
    )


def get_req_tasa_without_justificante_report(route_filter=None, limit=10000):
    """Carpetas raíz con REQ/TASA pero sin justificante de tasa."""
    return _build_root_folder_report(
        route_filter=route_filter,
        limit=limit,
        include_when=lambda conn, root_path: (
            _root_has_matching_item(conn, root_path, _req_tasa_folder_sql())
            and not _root_has_matching_item(conn, root_path, _justificante_tasa_sql())
        ),
    )


def get_requirements_report(route_filter=None, limit=10000):
    """Carpetas raíz con requerimientos detectados."""
    return _build_root_folder_report(
        route_filter=route_filter,
        limit=limit,
        include_when=lambda conn, root_path: _root_has_matching_item(conn, root_path, _requerimiento_sql()),
    )
