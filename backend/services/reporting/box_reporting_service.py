from database.connection import get_connection


def get_box_global_metrics():
    conn = get_connection()

    total_carpetas = conn.execute("""
        SELECT COUNT(*)
        FROM box_watch_folders
        WHERE COALESCE(activo, 1) = 1
    """).fetchone()[0]

    total_archivos = conn.execute("""
        SELECT COUNT(*)
        FROM box_watch_files
        WHERE COALESCE(activo, 1) = 1
    """).fetchone()[0]

    carpetas_faltantes = conn.execute("""
        SELECT COUNT(*)
        FROM box_watch_folders
        WHERE estado = 'FALTANTE'
    """).fetchone()[0]

    total_rutas = conn.execute("""
        SELECT COUNT(*)
        FROM box_watch_config
        WHERE COALESCE(activo, 1) = 1
    """).fetchone()[0]

    conn.close()

    return {
        "total_carpetas": total_carpetas,
        "total_archivos": total_archivos,
        "carpetas_faltantes": carpetas_faltantes,
        "total_rutas": total_rutas,
    }