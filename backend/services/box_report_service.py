"""
Servicio de reporting documental Box.

Solo lectura:
- No escanea.
- No modifica Box.
- No recalcula clasificación.
- Lee el inventario SQLite existente de Box Watch.
"""

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
        "total_archivos": total_archivos,
        "total_carpetas": total_carpetas,
        "total_bytes": total_bytes,
        "sin_clasificar": sin_clasificar,
        "ultimo_escaneo": ultimo_escaneo,
        "ultimos_archivos_escaneados": ultimos_archivos_escaneados,
        "ultimas_carpetas_escaneadas": ultimas_carpetas_escaneadas,
        "pasaportes": type_map.get("PASAPORTE", 0) + type_map.get("PASAPORTE_ACTUAL", 0) + type_map.get("PASAPORTE_ANTERIOR", 0),
        "justificantes_presentacion": type_map.get("JUSTIFICANTE_PRESENTACION", 0),
        "justificantes_tasa": type_map.get("JUSTIFICANTE_TASA", 0),
        "tasas": type_map.get("TASA", 0),
        "formularios_ex": type_map.get("FORMULARIO_EXTRANJERIA", 0),
        "padrones": type_map.get("EMPADRONAMIENTO", 0),
        "nies": type_map.get("NIE", 0),
        "dnis": type_map.get("DNI", 0),
        "resoluciones_favorables": type_map.get("RESOLUCION_FAVORABLE", 0),
    }


def get_document_type_counts(limit=50):
    """Conteo global por tipo documental detectado."""
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT COALESCE(NULLIF(TRIM(tipo_detectado), ''), estado, 'SIN CLASIFICAR') AS tipo_documento,
                   COUNT(*) AS total,
                   COALESCE(SUM(tamano_bytes), 0) AS total_bytes
            FROM box_watch_items
            WHERE {_active_condition()}
            GROUP BY COALESCE(NULLIF(TRIM(tipo_detectado), ''), estado, 'SIN CLASIFICAR')
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

    return {
        "tipo_expediente": route.get("tipo_expediente_nombre") or "—",
        "ruta_box": route.get("ruta_box") or "—",
        "ruta_resuelta": resolved,
        "total_carpetas": total_carpetas,
        "total_archivos": total_archivos,
        "total_bytes": total_bytes,
        "pasaportes": type_map.get("PASAPORTE", 0) + type_map.get("PASAPORTE_ACTUAL", 0) + type_map.get("PASAPORTE_ANTERIOR", 0),
        "justificantes_presentacion": type_map.get("JUSTIFICANTE_PRESENTACION", 0),
        "justificantes_tasa": type_map.get("JUSTIFICANTE_TASA", 0),
        "tasas": type_map.get("TASA", 0),
        "formularios_ex": type_map.get("FORMULARIO_EXTRANJERIA", 0),
        "sin_clasificar": type_map.get("SIN CLASIFICAR", 0),
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
              AND COALESCE(NULLIF(TRIM(tipo_detectado), ''), estado, 'SIN CLASIFICAR') IN ({placeholders})
            ORDER BY fecha_modificacion DESC, updated_at DESC, nombre_archivo ASC
            LIMIT ?
            """,
            list(focus) + [int(limit or 80)],
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
