"""
Diagnóstico de carga de carpetas raíz de Vigilancia Box.

Ejecutar:
python -m app.diagnose_box_watch_loading

No modifica Box.
No modifica archivos.
Solo lee SQLite y configuración.
"""

import sqlite3
from pathlib import Path

from backend.services import config_service


DB_PATH = Path(__file__).resolve().parents[1] / "database" / "quesada.db"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def norm(path):
    return str(path or "").replace("\\", "/").rstrip("/")


def main():
    print("=" * 80)
    print("DIAGNOSTICO VIGILANCIA BOX - CARGA DE CARPETAS RAIZ")
    print("=" * 80)
    print(f"DB: {DB_PATH}")
    print()

    config_service.initialize_config_schema()
    routes = config_service.get_box_rutas(active_only=True, include_resolved=True)

    if not routes:
        print("NO HAY RUTAS BOX ACTIVAS EN CONFIGURACION.")
        print("Ve a Configuración > Rutas Box y crea una ruta activa.")
        return

    with connect() as conn:
        tables = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]

        print("TABLAS BOX:")
        for t in tables:
            if t.startswith("box_watch"):
                print(f"- {t}")
        print()

        for table in ["box_watch_folders", "box_watch_items", "box_watch_scan_runs"]:
            if table not in tables:
                print(f"FALTA TABLA: {table}")
                continue
            count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            print(f"{table}: {count} registros")
        print()

        print("RUTAS CONFIGURADAS Y COINCIDENCIAS")
        print("-" * 80)

        for route in routes:
            ruta_relativa = route.get("ruta_box")
            ruta_resuelta = norm(route.get("ruta_resuelta"))
            exists = "SI" if route.get("ruta_existe") else "NO"

            print(f"ID: {route.get('id')}")
            print(f"Tipo: {route.get('tipo_expediente_nombre')}")
            print(f"Relativa: {ruta_relativa}")
            print(f"Resuelta: {ruta_resuelta}")
            print(f"Existe en disco: {exists}")

            folders_like = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM box_watch_folders
                WHERE REPLACE(ruta, '\\', '/') LIKE ?
                """,
                (ruta_resuelta + "/%",),
            ).fetchone()["n"]

            root_folders = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM box_watch_folders
                WHERE REPLACE(ruta, '\\', '/') LIKE ?
                  AND INSTR(SUBSTR(REPLACE(ruta, '\\', '/'), LENGTH(?) + 2), '/') = 0
                """,
                (ruta_resuelta + "/%", ruta_resuelta),
            ).fetchone()["n"]

            files_like = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM box_watch_items
                WHERE REPLACE(ruta, '\\', '/') LIKE ?
                """,
                (ruta_resuelta + "/%",),
            ).fetchone()["n"]

            print(f"Carpetas bajo esta ruta en SQLite: {folders_like}")
            print(f"Carpetas raíz directas bajo esta ruta: {root_folders}")
            print(f"Archivos bajo esta ruta en SQLite: {files_like}")

            if folders_like == 0 and files_like == 0:
                print("PROBLEMA: No hay registros guardados con esta ruta resuelta.")
                print("Posibles causas:")
                print("- El escaneo no se ejecutó sobre esta ruta resuelta.")
                print("- La ruta se resolvió de forma distinta durante el escaneo.")
                print("- La ruta en configuración no apunta a la carpeta real.")
            elif root_folders == 0:
                print("PROBLEMA: Hay datos bajo la ruta, pero no hay carpetas raíz directas.")
                print("Muestro las primeras rutas guardadas para comparar:")

                sample = conn.execute(
                    """
                    SELECT ruta, nombre_carpeta, nivel
                    FROM box_watch_folders
                    WHERE REPLACE(ruta, '\\', '/') LIKE ?
                    ORDER BY ruta ASC
                    LIMIT 10
                    """,
                    (ruta_resuelta + "/%",),
                ).fetchall()

                for s in sample:
                    print(f"  - nivel={s['nivel']} | {s['ruta']}")
            else:
                print("OK: esta ruta debería cargar carpetas raíz.")

                sample = conn.execute(
                    """
                    SELECT ruta, nombre_carpeta, total_archivos, total_subcarpetas
                    FROM box_watch_folders
                    WHERE REPLACE(ruta, '\\', '/') LIKE ?
                      AND INSTR(SUBSTR(REPLACE(ruta, '\\', '/'), LENGTH(?) + 2), '/') = 0
                    ORDER BY nombre_carpeta ASC
                    LIMIT 10
                    """,
                    (ruta_resuelta + "/%", ruta_resuelta),
                ).fetchall()

                print("Primeras carpetas raíz:")
                for s in sample:
                    print(
                        f"  - {s['nombre_carpeta']} | archivos={s['total_archivos']} "
                        f"subcarpetas={s['total_subcarpetas']} | {s['ruta']}"
                    )

            print("-" * 80)

        print()
        print("ULTIMOS ESCANEOS")
        print("-" * 80)
        if "box_watch_scan_runs" in tables:
            rows = conn.execute(
                """
                SELECT *
                FROM box_watch_scan_runs
                ORDER BY id DESC
                LIMIT 10
                """
            ).fetchall()
            for r in rows:
                d = dict(r)
                print(d)

    print()
    print("FIN DIAGNOSTICO")


if __name__ == "__main__":
    main()
