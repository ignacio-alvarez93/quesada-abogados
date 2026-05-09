"""
Fix definitivo de columnas runtime de Vigilancia Box.

Ejecutar:
python -m app.fix_box_watch_total_carpetas

Qué hace:
- Añade total_carpetas a box_watch_scan_runs si falta.
- Añade columnas defensivas a folders/items/runs.
- Recalcula contadores.
- Verifica rutas configuradas.

No toca Box.
"""

from backend.services import box_watch_service


def main():
    box_watch_service.ensure_box_watch_runtime_columns()
    box_watch_service.recalculate_box_folder_counters()

    summary = box_watch_service.get_box_dashboard_summary()
    print("Vigilancia Box corregida.")
    print(f"Total carpetas: {summary.get('total_carpetas')}")
    print(f"Total archivos: {summary.get('total_archivos')}")
    print("Rutas configuradas:")
    for route in box_watch_service.get_configured_box_routes(active_only=True):
        status = "OK" if route.get("ruta_existe") else "NO ENCONTRADA"
        print(f"- {route.get('id')} | {route.get('ruta_box')} -> {route.get('ruta_resuelta')} [{status}]")


if __name__ == "__main__":
    main()
