"""
FIX REAL last_scan - Vigilancia Box

Ejecutar:
python -m app.fix_box_watch_last_scan_real_v2
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW_PATH = ROOT / "frontend" / "views" / "box_watch_view.py"
SERVICE_PATH = ROOT / "backend" / "services" / "box_watch_service.py"

MARKER_START = "# === QUESADA LAST_SCAN SAFE OVERRIDE START ==="
MARKER_END = "# === QUESADA LAST_SCAN SAFE OVERRIDE END ==="


def build_override():
    lines = []
    lines.append(MARKER_START)
    lines.append("")
    lines.append("def _qa_norm_path(value):")
    lines.append("    return str(value or '').replace('\\\\', '/').rstrip('/')")
    lines.append("")
    lines.append("")
    lines.append("def get_last_scan_for_folder_path(folder_path):")
    lines.append("    ensure_box_watch_runtime_columns()")
    lines.append("    target = _qa_norm_path(folder_path)")
    lines.append("    if not target:")
    lines.append("        return None")
    lines.append("    with _connect() as conn:")
    lines.append("        row = conn.execute(")
    lines.append("            \"\"\"")
    lines.append("            SELECT fecha_fin, fecha_inicio, created_at")
    lines.append("            FROM box_watch_scan_runs")
    lines.append("            WHERE estado = 'OK'")
    lines.append("              AND (")
    lines.append("                    ? = REPLACE(ruta_base, '\\\\', '/')")
    lines.append("                    OR ? LIKE REPLACE(ruta_base, '\\\\', '/') || '/%'")
    lines.append("                  )")
    lines.append("            ORDER BY id DESC")
    lines.append("            LIMIT 1")
    lines.append("            \"\"\"")
    lines.append("            , (target, target),")
    lines.append("        ).fetchone()")
    lines.append("    if not row:")
    lines.append("        return None")
    lines.append("    d = _dict(row)")
    lines.append("    return d.get('fecha_fin') or d.get('fecha_inicio') or d.get('created_at')")
    lines.append("")
    lines.append("")
    lines.append("def attach_last_scan_to_folders(folders):")
    lines.append("    output = []")
    lines.append("    for folder in folders or []:")
    lines.append("        item = dict(folder)")
    lines.append("        value = get_last_scan_for_folder_path(item.get('ruta'))")
    lines.append("        item['last_scan'] = value")
    lines.append("        item['ultimo_escaneo'] = value")
    lines.append("        output.append(item)")
    lines.append("    return output")
    lines.append("")
    lines.append("")
    lines.append("def list_root_folders_python_fallback_for_route_id(route_id, ruta_contains=None, limit=500):")
    lines.append("    ensure_box_watch_runtime_columns()")
    lines.append("    route = get_configured_box_route(route_id)")
    lines.append("    if not route:")
    lines.append("        return []")
    lines.append("    base_path = _qa_norm_path(route.get('ruta_resuelta'))")
    lines.append("    if not base_path:")
    lines.append("        return []")
    lines.append("    text = str(ruta_contains or '').lower().strip()")
    lines.append("    prefix = base_path + '/'")
    lines.append("    with _connect() as conn:")
    lines.append("        rows = conn.execute(")
    lines.append("            \"\"\"")
    lines.append("            SELECT *")
    lines.append("            FROM box_watch_folders")
    lines.append("            WHERE COALESCE(activo, 1) = 1")
    lines.append("            ORDER BY nombre_carpeta ASC")
    lines.append("            \"\"\"")
    lines.append("        ).fetchall()")
    lines.append("    result = []")
    lines.append("    for row in rows:")
    lines.append("        folder = _dict(row)")
    lines.append("        ruta = _qa_norm_path(folder.get('ruta'))")
    lines.append("        if not ruta.startswith(prefix):")
    lines.append("            continue")
    lines.append("        relative = ruta[len(prefix):]")
    lines.append("        if '/' in relative:")
    lines.append("            continue")
    lines.append("        if text:")
    lines.append("            haystack = (str(folder.get('nombre_carpeta') or '') + ' ' + ruta).lower()")
    lines.append("            if text not in haystack:")
    lines.append("                continue")
    lines.append("        folder['config_route_id'] = route.get('id')")
    lines.append("        folder['config_route_label'] = f\"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}\"")
    lines.append("        folder['config_route_relative'] = route.get('ruta_box')")
    lines.append("        folder['config_route_resolved'] = route.get('ruta_resuelta')")
    lines.append("        result.append(folder)")
    lines.append("        if len(result) >= int(limit or 500):")
    lines.append("            break")
    lines.append("    return attach_last_scan_to_folders(result)")
    lines.append("")
    lines.append("")
    lines.append("def list_root_folders_python_fallback_for_all_routes(ruta_contains=None, limit_per_route=500):")
    lines.append("    routes = get_configured_box_routes(active_only=True)")
    lines.append("    result = []")
    lines.append("    for route in routes:")
    lines.append("        result.extend(")
    lines.append("            list_root_folders_python_fallback_for_route_id(")
    lines.append("                route.get('id'),")
    lines.append("                ruta_contains=ruta_contains,")
    lines.append("                limit=limit_per_route,")
    lines.append("            )")
    lines.append("        )")
    lines.append("    return attach_last_scan_to_folders(result)")
    lines.append("")
    lines.append(MARKER_END)
    return "\n".join(lines) + "\n"


def patch_view():
    text = VIEW_PATH.read_text(encoding="utf-8")
    text = text.replace("last_scan,", "_datetime_label(folder.get('last_scan') or folder.get('ultimo_escaneo')),")
    text = text.replace("last_scan)", "_datetime_label(folder.get('last_scan') or folder.get('ultimo_escaneo'))")
    text = text.replace('row.get("ultimo_escaneo") or ""', 'row.get("last_scan") or row.get("ultimo_escaneo") or ""')
    text = text.replace('_datetime_label(folder.get("ultimo_escaneo"))', '_datetime_label(folder.get("last_scan") or folder.get("ultimo_escaneo"))')
    text = text.replace('_datetime_label(folder.get("last_scan"))', '_datetime_label(folder.get("last_scan") or folder.get("ultimo_escaneo"))')
    text = text.replace('            last_scan = _format_datetime(folder.get("last_scan"))\n', "")
    text = text.replace('            last_scan = _datetime_label(folder.get("last_scan"))\n', "")
    VIEW_PATH.write_text(text, encoding="utf-8")
    print(f"Vista corregida: {VIEW_PATH}")


def patch_service():
    text = SERVICE_PATH.read_text(encoding="utf-8")
    override = build_override()
    if MARKER_START in text and MARKER_END in text:
        before = text.split(MARKER_START, 1)[0].rstrip()
        after = text.split(MARKER_END, 1)[1].lstrip()
        text = before + "\n\n" + override.strip() + "\n\n" + after
    else:
        text = text.rstrip() + "\n\n" + override
    SERVICE_PATH.write_text(text, encoding="utf-8")
    print(f"Servicio corregido: {SERVICE_PATH}")


def main():
    patch_view()
    patch_service()
    print("")
    print("FIX aplicado.")
    print("Ahora ejecuta: python -m app.main")


if __name__ == "__main__":
    main()
