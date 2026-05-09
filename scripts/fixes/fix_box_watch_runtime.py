"""
Fix defensivo para Vigilancia Box.

Ejecutar:
python -m app.fix_box_watch_runtime

Qué hace:
- Añade columnas que falten en SQLite.
- Recalcula contadores de carpetas.
- Verifica resolución de rutas configuradas.

No toca Box. No borra, no mueve, no renombra.
"""

from backend.services import box_watch_service


def main():
    box_watch_service.ensure_box_watch_runtime_columns()
    box_watch_service.recalculate_box_folder_counters()

    print("Columnas y contadores de Vigilancia Box verificados.")
    print("Rutas Box configuradas:")
    for route in box_watch_service.get_configured_box_routes(active_only=True):
        status = "OK" if route.get("ruta_existe") else "NO ENCONTRADA"
        print(f"- {route.get('id')} | {route.get('ruta_box')} -> {route.get('ruta_resuelta')} [{status}]")


if __name__ == "__main__":
    main()
