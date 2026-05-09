"""
Parche runtime para corregir:
NameError: last_scan is not defined

Uso:
python -m app.patch_box_watch_last_scan_override

Qué hace:
- No toca Box.
- No reescanea.
- No borra ni mueve archivos.
- Añade al final de backend/services/box_watch_service.py funciones seguras que sustituyen
  la carga de carpetas raíz y añaden last_scan / ultimo_escaneo correctamente.
"""

from pathlib import Path


SERVICE_PATH = Path(__file__).resolve().parents[1] / "backend" / "services" / "box_watch_service.py"

MARKER_START = "# === QUESADA LAST_SCAN SAFE OVERRIDE START ==="
MARKER_END = "# === QUESADA LAST_SCAN SAFE OVERRIDE END ==="


OVERRIDE = r'''
# === QUESADA LAST_SCAN SAFE OVERRIDE START ===

def _qa_norm_path(value):
    return str(value or "").replace("\\", "/").rstrip("/")


def get_last_scan_for_folder_path(folder_path):
    """
    Devuelve el último escaneo que cubre una carpeta.
    Seguro: no toca Box, solo consulta SQLite.
    """
    ensure_box_watch_runtime_columns()

    target = _qa_norm_path(folder_path)
    if not target:
        return None

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT fecha_fin, fecha_inicio, created_at
            FROM box_watch_scan_runs
            WHERE estado = 'OK'
              AND (
                    ? = REPLACE(ruta_base, '\\', '/')
                    OR ? LIKE REPLACE(ruta_base, '\\', '/') || '/%'
                  )
            ORDER BY id DESC
            LIMIT 1
            """,
            (target, target),
        ).fetchone()

    if not row:
        return None

    d = _dict(row)
    return d.get("fecha_fin") or d.get("fecha_inicio") or d.get("created_at")


def attach_last_scan_to_folders(folders):
    """
    Añade ambas claves para evitar incompatibilidades:
    - last_scan
    - ultimo_escaneo
    """
    output = []

    for folder in folders or []:
        item = dict(folder)

        value = get_last_scan_for_folder_path(
            item.get("ruta")
        )

        item["last_scan"] = value
        item["ultimo_escaneo"] = value

        output.append(item)

    return output


def list_root_folders_python_fallback_for_route_id(
    route_id,
    ruta_contains=None,
    limit=500,
):
    """
    Carga carpetas raíz de una ruta configurada con filtrado Python.
    """

    ensure_box_watch_runtime_columns()

    route = get_configured_box_route(route_id)

    if not route:
        return []

    base_path = _qa_norm_path(
        route.get("ruta_resuelta")
    )

    if not base_path:
        return []

    text = str(
        ruta_contains or ""
    ).lower().strip()

    prefix = base_path + "/"

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM box_watch_folders
            WHERE COALESCE(activo, 1) = 1
            ORDER BY nombre_carpeta ASC
            """
        ).fetchall()

    result = []

    for row in rows:
        folder = _dict(row)

        ruta = _qa_norm_path(
            folder.get("ruta")
        )

        if not ruta.startswith(prefix):
            continue

        relative = ruta[len(prefix):]

        if "/" in relative:
            continue

        if text:
            haystack = (
                str(folder.get("nombre_carpeta") or "")
                + " "
                + ruta
            ).lower()

            if text not in haystack:
                continue

        folder["config_route_id"] = route.get("id")
        folder["config_route_label"] = (
            f"{route.get('tipo_expediente_nombre')} · "
            f"{route.get('ruta_box')}"
        )

        folder["config_route_relative"] = route.get("ruta_box")
        folder["config_route_resolved"] = route.get("ruta_resuelta")

        result.append(folder)

        if len(result) >= int(limit or 500):
            break

    return attach_last_scan_to_folders(result)


def list_root_folders_python_fallback_for_all_routes(
    ruta_contains=None,
    limit_per_route=500,
):
    """
    Carga carpetas raíz de todas las rutas activas.
    """

    routes = get_configured_box_routes(
        active_only=True
    )

    result = []

    for route in routes:
        result.extend(
            list_root_folders_python_fallback_for_route_id(
                route.get("id"),
                ruta_contains=ruta_contains,
                limit=limit_per_route,
            )
        )

    return attach_last_scan_to_folders(result)

# === QUESADA LAST_SCAN SAFE OVERRIDE END ===
'''