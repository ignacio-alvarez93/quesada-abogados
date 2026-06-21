import hashlib
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from backend.services.box_classifier import classify_file, classify_folder
from backend.services import config_service

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "database" / "box_watch_schema.sql"

ESTADO_OK = "OK"
ESTADO_SIN_CLASIFICAR = "SIN CLASIFICAR"
ESTADO_PENDIENTE = "PENDIENTE REVISION"
ESTADO_DUPLICADO = "DUPLICADO"
ESTADO_FALTANTE = "FALTANTE"
ESTADO_ERROR = "ERROR"

EXTENSIONES_SOSPECHOSAS = {"exe", "bat", "cmd", "scr", "js", "vbs", "ps1", "com"}
NOMBRES_SOSPECHOSOS = ("copia de copia", "sin titulo", "sin título", "nuevo documento", "desktop.ini", "~$")


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _dict(row):
    return dict(row) if row else None


def _now():
    return datetime.now().isoformat(timespec="seconds")


def initialize_box_watch_schema():
    with _connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    ensure_box_watch_indexes()
    sync_rules_from_config()




def ensure_box_watch_indexes():
    """
    Crea índices para acelerar la apertura y los filtros de Vigilancia Box.
    No accede a Box. Solo optimiza SQLite.
    """
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_box_watch_items_activo ON box_watch_items(activo)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_items_ruta ON box_watch_items(ruta)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_items_nombre ON box_watch_items(nombre_archivo)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_items_estado ON box_watch_items(estado)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_items_tipo ON box_watch_items(tipo_detectado)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_items_extension ON box_watch_items(extension)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_items_updated ON box_watch_items(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_items_fecha_mod ON box_watch_items(fecha_modificacion)",

        "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_activo ON box_watch_folders(activo)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_ruta ON box_watch_folders(ruta)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_nombre ON box_watch_folders(nombre_carpeta)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_tipo ON box_watch_folders(tipo_detectado)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_nivel ON box_watch_folders(nivel)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_folders_actividad ON box_watch_folders(fecha_ultima_actividad)",

        "CREATE INDEX IF NOT EXISTS idx_box_watch_alerts_estado ON box_watch_alerts(estado)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_alerts_severidad ON box_watch_alerts(severidad)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_alerts_created ON box_watch_alerts(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_box_watch_runs_id ON box_watch_scan_runs(id)",
    ]

    with _connect() as conn:
        for sql in statements:
            conn.execute(sql)
        conn.commit()


def sync_rules_from_config():
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                n.tipo_expediente_id,
                d.codigo_documento,
                n.patron_nombre,
                n.extension_permitida,
                d.obligatorio,
                n.activo
            FROM config_nomenclaturas_documentales n
            JOIN config_documentos_requeridos d ON d.id = n.documento_id
            WHERE COALESCE(n.activo, 1) = 1
            """
        ).fetchall()
        inserted = 0
        for row in rows:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO box_watch_rules
                (tipo_expediente_id, codigo_documento, patron_nombre, extension_permitida, obligatorio, activo)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row["tipo_expediente_id"],
                    row["codigo_documento"],
                    row["patron_nombre"],
                    row["extension_permitida"] or "pdf,jpg,jpeg,png",
                    int(row["obligatorio"] or 0),
                    int(row["activo"] or 1),
                ),
            )
            inserted += cur.rowcount
        conn.commit()
        return inserted


def _safe_path(ruta_base):
    ruta = Path((ruta_base or "").strip()).expanduser()
    if not ruta_base or not ruta.exists() or not ruta.is_dir():
        raise ValueError("La ruta base de Box Drive no existe o no es una carpeta accesible.")
    return ruta


def _file_hash(path, max_bytes=None):
    digest = hashlib.sha256()
    read_total = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
            read_total += len(chunk)
            if max_bytes and read_total >= max_bytes:
                break
    return digest.hexdigest()


def detect_document_type(filename):
    """
    Compatibilidad con versiones anteriores.
    Usa el clasificador documental conservador.
    """
    try:
        result = classify_file(filename)
        return result.get("tipo_documento") or "SIN CLASIFICAR"
    except Exception:
        return "SIN CLASIFICAR"


def detect_folder_type(folder_name):
    """
    Compatibilidad con versiones anteriores.
    Usa el clasificador de fases documentales.
    """
    try:
        result = classify_folder(folder_name)
        categoria = result.get("categoria") or "OTROS"
        # Mantener clasificación de carpetas raíz de áreas cuando procede.
        name = (folder_name or "").lower()
        if any(x in name for x in ("nacionalidad", "nacionalidades")):
            return "NACIONALIDAD"
        if "arraigo" in name:
            return "ARRAIGO"
        if "recurso" in name:
            return "RECURSO"
        if any(x in name for x in ("renovacion", "renovación")):
            return "RENOVACION"
        if any(x in name for x in ("familiar", "comunitario")):
            return "FAMILIAR_COMUNITARIO"
        return categoria
    except Exception:
        return "OTROS"


def _load_rules(conn):
    return [
        _dict(r)
        for r in conn.execute(
            """
            SELECT r.*, t.nombre AS tipo_expediente_nombre
            FROM box_watch_rules r
            LEFT JOIN config_tipos_expediente t ON t.id = r.tipo_expediente_id
            WHERE COALESCE(r.activo, 1) = 1
            ORDER BY t.nombre ASC, r.codigo_documento ASC
            """
        ).fetchall()
    ]


def _allowed_extensions(rule):
    raw = (rule.get("extension_permitida") or "").lower().replace(";", ",")
    return {x.strip().lstrip(".") for x in raw.split(",") if x.strip()}


def _matches_rule(filename, extension, rule):
    name = (filename or "").lower()
    pattern = (rule.get("patron_nombre") or "").lower().strip()
    allowed = _allowed_extensions(rule)
    extension_ok = not allowed or extension.lower() in allowed
    if not extension_ok or not pattern:
        return False
    return pattern in name or re.search(re.escape(pattern).replace(r"\*", ".*"), name) is not None


def match_item_to_expedient(item):
    ruta = (item.get("ruta") or "").lower()
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT e.id AS expediente_id, e.cliente_id, e.tipo_expediente_id, e.box_folder_path
                FROM expedientes e
                WHERE COALESCE(e.activo, 1) = 1
                  AND e.box_folder_path IS NOT NULL
                  AND TRIM(e.box_folder_path) <> ''
                """
            ).fetchall()
    except Exception:
        return {"expediente_id": None, "cliente_id": None, "tipo_expediente_id": None}
    for row in rows:
        folder = (row["box_folder_path"] or "").lower().replace("\\", "/")
        comparable = ruta.replace("\\", "/")
        if folder and folder in comparable:
            return {"expediente_id": row["expediente_id"], "cliente_id": row["cliente_id"], "tipo_expediente_id": row["tipo_expediente_id"]}
    return {"expediente_id": None, "cliente_id": None, "tipo_expediente_id": None}


def _open_alert_exists(conn, item_id, tipo_alerta, mensaje):
    return conn.execute(
        """
        SELECT id FROM box_watch_alerts
        WHERE item_id IS ? AND tipo_alerta = ? AND mensaje = ? AND estado = 'ABIERTA'
        LIMIT 1
        """,
        (item_id, tipo_alerta, mensaje),
    ).fetchone()


def _create_alert(conn, item_id, expediente_id, cliente_id, tipo_alerta, severidad, mensaje):
    if _open_alert_exists(conn, item_id, tipo_alerta, mensaje):
        return 0
    conn.execute(
        """
        INSERT INTO box_watch_alerts
        (item_id, expediente_id, cliente_id, tipo_alerta, severidad, mensaje, estado)
        VALUES (?, ?, ?, ?, ?, ?, 'ABIERTA')
        """,
        (item_id, expediente_id, cliente_id, tipo_alerta, severidad, mensaje),
    )
    return 1


def _evaluate_item_alerts(conn, item_id, filename, extension, tipo_detectado, hash_archivo, expediente_id, cliente_id, rules):
    alerts = 0
    lowered = filename.lower()
    if tipo_detectado == "SIN CLASIFICAR":
        alerts += _create_alert(conn, item_id, expediente_id, cliente_id, "ARCHIVO_SIN_CLASIFICAR", "MEDIA", f"Archivo sin clasificar: {filename}")
    if not expediente_id:
        alerts += _create_alert(conn, item_id, expediente_id, cliente_id, "SIN_EXPEDIENTE_ASOCIADO", "ALTA", f"Archivo sin expediente asociado: {filename}")
    if extension.lower() in EXTENSIONES_SOSPECHOSAS or any(token in lowered for token in NOMBRES_SOSPECHOSOS):
        alerts += _create_alert(conn, item_id, expediente_id, cliente_id, "ARCHIVO_SOSPECHOSO", "CRITICA", f"Revisar archivo sospechoso por nombre o extensión: {filename}")
    if hash_archivo:
        duplicates = conn.execute(
            """
            SELECT id, nombre_archivo FROM box_watch_items
            WHERE hash_archivo = ? AND id <> ? AND COALESCE(activo, 1) = 1
            LIMIT 1
            """,
            (hash_archivo, item_id),
        ).fetchone()
        if duplicates:
            conn.execute("UPDATE box_watch_items SET estado = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (ESTADO_DUPLICADO, item_id))
            alerts += _create_alert(conn, item_id, expediente_id, cliente_id, "DUPLICADO_HASH", "ALTA", f"Posible duplicado de {duplicates['nombre_archivo']}: {filename}")
    for rule in rules:
        pattern = (rule.get("patron_nombre") or "").lower().strip()
        if pattern and (pattern in lowered) and extension.lower() not in _allowed_extensions(rule):
            alerts += _create_alert(conn, item_id, expediente_id, cliente_id, "EXTENSION_NO_PERMITIDA", "ALTA", f"Extensión no permitida para regla {rule.get('codigo_documento')}: {filename}")
    return alerts


def _evaluate_missing_required(conn, rules):
    alerts = 0
    try:
        active_expedients = conn.execute(
            """
            SELECT id, cliente_id, tipo_expediente_id, numero_expediente
            FROM expedientes
            WHERE COALESCE(activo, 1) = 1 AND tipo_expediente_id IS NOT NULL
            """
        ).fetchall()
    except Exception:
        return 0
    for exp in active_expedients:
        exp_rules = [r for r in rules if r.get("tipo_expediente_id") == exp["tipo_expediente_id"] and int(r.get("obligatorio") or 0) == 1]
        for rule in exp_rules:
            matches = conn.execute(
                """
                SELECT COUNT(*) AS total FROM box_watch_items
                WHERE expediente_id = ?
                  AND COALESCE(activo, 1) = 1
                  AND tipo_detectado = ?
                """,
                (exp["id"], rule.get("codigo_documento")),
            ).fetchone()["total"]
            if matches == 0:
                msg = f"Documento obligatorio faltante en {exp['numero_expediente']}: {rule.get('codigo_documento')}"
                alerts += _create_alert(conn, None, exp["id"], exp["cliente_id"], "DOCUMENTO_OBLIGATORIO_FALTANTE", "ALTA", msg)
    return alerts


def _iter_tree(base):
    for root, dirs, files in os.walk(base):
        yield Path(root), dirs, files


def _count_tree(base):
    carpetas = 0
    archivos = 0
    for _, dirs, files in _iter_tree(base):
        carpetas += 1
        archivos += len(files)
    return carpetas, archivos


def _folder_stats(root, dirs, files):
    total_archivos = 0
    total_bytes = 0
    last_activity = None
    for file_name in files:
        full_path = root / file_name
        try:
            if not full_path.is_file():
                continue
            stat = full_path.stat()
            total_archivos += 1
            total_bytes += stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            if not last_activity or modified > last_activity:
                last_activity = modified
        except Exception:
            continue
    return total_archivos, len(dirs), total_bytes, last_activity


def _upsert_folder(conn, base, root, dirs, files):
    total_archivos, total_subcarpetas, tamano_total, last_activity = _folder_stats(root, dirs, files)
    rel = root.relative_to(base) if root != base else Path("")
    nivel = 0 if str(rel) in ("", ".") else len(rel.parts)
    ruta = str(root)
    ruta_padre = str(root.parent) if root != base else ""
    nombre = root.name or str(root)
    tipo = detect_folder_type(nombre)
    match = match_item_to_expedient({"ruta": ruta})

    existing = conn.execute("SELECT id FROM box_watch_folders WHERE ruta = ?", (ruta,)).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE box_watch_folders
            SET nombre_carpeta = ?, ruta_padre = ?, nivel = ?, total_archivos = ?,
                total_subcarpetas = ?, tamano_total_bytes = ?, fecha_ultima_actividad = ?,
                cliente_id = COALESCE(?, cliente_id), expediente_id = COALESCE(?, expediente_id),
                tipo_detectado = ?, estado = ?, activo = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (nombre, ruta_padre, nivel, total_archivos, total_subcarpetas, tamano_total, last_activity,
             match.get("cliente_id"), match.get("expediente_id"), tipo, ESTADO_OK, existing["id"]),
        )
        return 0

    conn.execute(
        """
        INSERT INTO box_watch_folders
        (ruta, nombre_carpeta, ruta_padre, nivel, total_archivos, total_subcarpetas,
         tamano_total_bytes, fecha_ultima_actividad, cliente_id, expediente_id,
         tipo_detectado, estado, observaciones, activo, last_seen_scan_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (ruta, nombre, ruta_padre, nivel, total_archivos, total_subcarpetas, tamano_total, last_activity,
         match.get("cliente_id"), match.get("expediente_id"), tipo, ESTADO_OK, "Carpeta detectada en escaneo local"),
    )
    return 1


def scan_local_box_path(ruta_base, progress_callback=None, calculate_hash=False):
    """
    Escaneo local de Box Drive en modo SOLO LECTURA.
    Modo inventario por defecto: calcula carpetas + metadata básica de archivos, sin hash pesado.
    """
    initialize_box_watch_schema()
    base = _safe_path(ruta_base)
    start = _now()
    total_carpetas_estimadas, total_archivos_estimados = _count_tree(base)
    total_archivos = total_carpetas = nuevos = modificados = sin_clasificar = alertas = 0
    carpetas_nuevas = 0
    final_state = ESTADO_OK

    def report(processed_files, processed_folders, current=""):
        if not progress_callback:
            return
        try:
            total_units = total_archivos_estimados + total_carpetas_estimadas
            processed_units = processed_files + processed_folders
            percent = round((processed_units / total_units) * 100, 2) if total_units else 0
            progress_callback({
                "processed": processed_files,
                "processed_folders": processed_folders,
                "total": total_archivos_estimados,
                "total_folders": total_carpetas_estimadas,
                "percent": percent,
                "current_file": current,
            })
        except Exception:
            pass

    report(0, 0, "Preparando escaneo")

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO box_watch_scan_runs (fecha_inicio, ruta_base, estado, observaciones)
            VALUES (?, ?, 'EN CURSO', 'Escaneo local de inventario: carpetas y archivos. Solo lectura.')
            """,
            (start, str(base)),
        )
        run_id = cur.lastrowid
        rules = _load_rules(conn)

        try:
            for root, dirs, files in _iter_tree(base):
                total_carpetas += 1
                carpetas_nuevas += _upsert_folder(conn, base, root, dirs, files)
                report(total_archivos, total_carpetas, f"Carpeta: {root.name}")

                for file_name in files:
                    full_path = root / file_name
                    total_archivos += 1
                    if total_archivos % 50 == 0:
                        report(total_archivos, total_carpetas, file_name)

                    try:
                        if not full_path.is_file():
                            continue
                        stat = full_path.stat()
                    except Exception:
                        alertas += _create_alert(conn, None, None, None, "ERROR_LECTURA", "MEDIA", f"No se pudo leer metadata: {full_path}")
                        continue

                    extension = full_path.suffix.lower().lstrip(".")
                    modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
                    tipo_detectado = detect_document_type(file_name)
                    match = match_item_to_expedient({"ruta": str(root), "nombre_archivo": file_name})
                    if tipo_detectado == "SIN CLASIFICAR":
                        for rule in rules:
                            if _matches_rule(file_name, extension, rule):
                                tipo_detectado = rule.get("codigo_documento") or tipo_detectado
                                break

                    estado = ESTADO_OK if tipo_detectado != "SIN CLASIFICAR" else ESTADO_SIN_CLASIFICAR
                    if estado == ESTADO_SIN_CLASIFICAR:
                        sin_clasificar += 1

                    existing = conn.execute(
                        "SELECT * FROM box_watch_items WHERE ruta = ? AND nombre_archivo = ?",
                        (str(root), file_name),
                    ).fetchone()

                    hash_archivo = existing["hash_archivo"] if existing else None
                    needs_hash = False
                    if calculate_hash:
                        if not existing:
                            needs_hash = True
                        else:
                            needs_hash = (existing["tamano_bytes"] != stat.st_size) or (existing["fecha_modificacion"] != modified) or not existing["hash_archivo"]
                    if needs_hash:
                        try:
                            hash_archivo = _file_hash(full_path)
                        except Exception:
                            hash_archivo = None

                    if not existing:
                        cur_item = conn.execute(
                            """
                            INSERT INTO box_watch_items
                            (ruta, nombre_archivo, extension, tipo_detectado, cliente_id, expediente_id,
                             tamano_bytes, fecha_modificacion, hash_archivo, estado, observaciones, activo, last_seen_scan_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                            """,
                            (str(root), file_name, extension, tipo_detectado, match.get("cliente_id"), match.get("expediente_id"),
                             stat.st_size, modified, hash_archivo, estado, "Detectado en escaneo local"),
                        )
                        item_id = cur_item.lastrowid
                        nuevos += 1
                    else:
                        item_id = existing["id"]
                        changed = (existing["tamano_bytes"] != stat.st_size) or (existing["fecha_modificacion"] != modified)
                        if hash_archivo and existing["hash_archivo"] and existing["hash_archivo"] != hash_archivo:
                            changed = True
                        if changed:
                            modificados += 1
                        conn.execute(
                            """
                            UPDATE box_watch_items
                            SET extension = ?, tipo_detectado = ?, cliente_id = COALESCE(?, cliente_id),
                                expediente_id = COALESCE(?, expediente_id), tamano_bytes = ?,
                                fecha_modificacion = ?, hash_archivo = ?, estado = ?, activo = 1,
                                last_seen_scan_id = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (extension, tipo_detectado, match.get("cliente_id"), match.get("expediente_id"), stat.st_size,
                             modified, hash_archivo, estado, item_id),
                        )

                    alertas += _evaluate_item_alerts(conn, item_id, file_name, extension, tipo_detectado, hash_archivo, match.get("expediente_id"), match.get("cliente_id"), rules)

                    if total_archivos % 500 == 0:
                        conn.commit()

                if total_carpetas % 100 == 0:
                    conn.commit()

            alertas += _evaluate_missing_required(conn, rules)
            final_state = ESTADO_OK if alertas == 0 else ESTADO_PENDIENTE
            conn.execute(
                """
                UPDATE box_watch_scan_runs
                SET fecha_fin = ?, total_archivos = ?, total_carpetas = ?, nuevos = ?, modificados = ?,
                    sin_clasificar = ?, alertas = ?, estado = ?, observaciones = ?
                WHERE id = ?
                """,
                (_now(), total_archivos, total_carpetas, nuevos, modificados, sin_clasificar, alertas, final_state,
                 f"Escaneo completado sin modificar Box. Carpetas nuevas: {carpetas_nuevas}. Hash activo: {calculate_hash}", run_id),
            )
            conn.commit()
            report(total_archivos_estimados, total_carpetas_estimadas, "Escaneo completado")
        except Exception as exc:
            conn.execute(
                "UPDATE box_watch_scan_runs SET fecha_fin = ?, estado = ?, observaciones = ? WHERE id = ?",
                (_now(), ESTADO_ERROR, str(exc), run_id),
            )
            conn.commit()
            raise

    return {
        "run_id": run_id,
        "total_archivos": total_archivos,
        "total_carpetas": total_carpetas,
        "carpetas_nuevas": carpetas_nuevas,
        "nuevos": nuevos,
        "modificados": modificados,
        "sin_clasificar": sin_clasificar,
        "alertas": alertas,
        "estado": final_state,
    }


def _append_filter(where_parts, params, clause, value):
    if value is not None and str(value).strip() != "":
        where_parts.append(clause)
        params.append(value)


def list_box_folders(
    limit=500,
    ruta_contains=None,
    tipo_detectado=None,
    nivel=None,
    only_with_files=False,
):
    """
    Lista carpetas inventariadas con filtros seguros.
    No accede a Box. Solo consulta SQLite.
    """
    initialize_box_watch_schema()
    where_parts = ["COALESCE(f.activo, 1) = 1"]
    params = []

    if ruta_contains:
        where_parts.append("(LOWER(f.ruta) LIKE ? OR LOWER(f.nombre_carpeta) LIKE ?)")
        text = f"%{str(ruta_contains).lower().strip()}%"
        params.extend([text, text])

    if tipo_detectado:
        where_parts.append("f.tipo_detectado = ?")
        params.append(str(tipo_detectado).strip())

    if nivel not in (None, "", "Todos"):
        try:
            where_parts.append("f.nivel = ?")
            params.append(int(nivel))
        except Exception:
            pass

    if only_with_files:
        where_parts.append("COALESCE(f.total_archivos, 0) > 0")

    where_sql = " AND ".join(where_parts)

    with _connect() as conn:
        return [_dict(r) for r in conn.execute(
            f"""
            SELECT f.*, c.nombre AS cliente_nombre, c.primer_apellido, e.numero_expediente
            FROM box_watch_folders f
            LEFT JOIN clientes c ON c.id = f.cliente_id
            LEFT JOIN expedientes e ON e.id = f.expediente_id
            WHERE {where_sql}
            ORDER BY f.nivel ASC, f.ruta ASC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()]


def list_box_items(
    limit=500,
    ruta_contains=None,
    folder_exact=None,
    tipo_detectado=None,
    estado=None,
    extension=None,
):
    """
    Lista archivos inventariados con filtros seguros.
    No accede a Box. Solo consulta SQLite.
    """
    initialize_box_watch_schema()
    where_parts = ["COALESCE(i.activo, 1) = 1"]
    params = []

    if folder_exact:
        where_parts.append("i.ruta = ?")
        params.append(str(folder_exact).strip())

    if ruta_contains:
        where_parts.append("(LOWER(i.ruta) LIKE ? OR LOWER(i.nombre_archivo) LIKE ?)")
        text = f"%{str(ruta_contains).lower().strip()}%"
        params.extend([text, text])

    if tipo_detectado:
        where_parts.append("i.tipo_detectado = ?")
        params.append(str(tipo_detectado).strip())

    if estado:
        where_parts.append("i.estado = ?")
        params.append(str(estado).strip())

    if extension:
        where_parts.append("LOWER(i.extension) = ?")
        params.append(str(extension).lower().strip().lstrip("."))

    where_sql = " AND ".join(where_parts)

    with _connect() as conn:
        return [_dict(r) for r in conn.execute(
            f"""
            SELECT i.*, c.nombre AS cliente_nombre, c.primer_apellido, e.numero_expediente
            FROM box_watch_items i
            LEFT JOIN clientes c ON c.id = i.cliente_id
            LEFT JOIN expedientes e ON e.id = i.expediente_id
            WHERE {where_sql}
            ORDER BY i.updated_at DESC, i.id DESC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()]


def get_box_filter_options():
    """
    Opciones para filtros de la vista.
    No accede a Box. Solo consulta el inventario ya guardado.
    """
    initialize_box_watch_schema()
    with _connect() as conn:
        folder_types = [
            r["tipo_detectado"] for r in conn.execute(
                """
                SELECT DISTINCT tipo_detectado
                FROM box_watch_folders
                WHERE COALESCE(activo, 1) = 1
                  AND tipo_detectado IS NOT NULL
                  AND TRIM(tipo_detectado) <> ''
                ORDER BY tipo_detectado ASC
                """
            ).fetchall()
        ]
        folder_levels = [
            r["nivel"] for r in conn.execute(
                """
                SELECT DISTINCT nivel
                FROM box_watch_folders
                WHERE COALESCE(activo, 1) = 1
                ORDER BY nivel ASC
                """
            ).fetchall()
        ]
        document_types = [
            r["tipo_detectado"] for r in conn.execute(
                """
                SELECT DISTINCT tipo_detectado
                FROM box_watch_items
                WHERE COALESCE(activo, 1) = 1
                  AND tipo_detectado IS NOT NULL
                  AND TRIM(tipo_detectado) <> ''
                ORDER BY tipo_detectado ASC
                """
            ).fetchall()
        ]
        item_states = [
            r["estado"] for r in conn.execute(
                """
                SELECT DISTINCT estado
                FROM box_watch_items
                WHERE COALESCE(activo, 1) = 1
                  AND estado IS NOT NULL
                  AND TRIM(estado) <> ''
                ORDER BY estado ASC
                """
            ).fetchall()
        ]
        extensions = [
            r["extension"] for r in conn.execute(
                """
                SELECT DISTINCT LOWER(extension) AS extension
                FROM box_watch_items
                WHERE COALESCE(activo, 1) = 1
                  AND extension IS NOT NULL
                  AND TRIM(extension) <> ''
                ORDER BY extension ASC
                """
            ).fetchall()
        ]

    return {
        "folder_types": folder_types,
        "folder_levels": folder_levels,
        "document_types": document_types,
        "item_states": item_states,
        "extensions": extensions,
    }


def list_box_alerts(include_resolved=False, limit=500):
    initialize_box_watch_schema()
    where = "" if include_resolved else "WHERE a.estado <> 'RESUELTA'"
    with _connect() as conn:
        return [_dict(r) for r in conn.execute(
            f"""
            SELECT a.*, i.nombre_archivo, c.nombre AS cliente_nombre, c.primer_apellido, e.numero_expediente
            FROM box_watch_alerts a
            LEFT JOIN box_watch_items i ON i.id = a.item_id
            LEFT JOIN clientes c ON c.id = a.cliente_id
            LEFT JOIN expedientes e ON e.id = a.expediente_id
            {where}
            ORDER BY CASE a.severidad WHEN 'CRITICA' THEN 1 WHEN 'ALTA' THEN 2 WHEN 'MEDIA' THEN 3 ELSE 4 END,
                     a.created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()]


def resolve_alert(alert_id):
    initialize_box_watch_schema()
    with _connect() as conn:
        conn.execute(
            "UPDATE box_watch_alerts SET estado = 'RESUELTA', resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(alert_id),),
        )
        conn.commit()


def get_box_dashboard_summary():
    """
    Resumen robusto del módulo Box.

    No depende de que existan columnas nuevas en box_watch_scan_runs.
    Primero asegura columnas runtime.
    """
    ensure_box_watch_runtime_columns()

    with _connect() as conn:
        total_archivos = conn.execute(
            "SELECT COUNT(*) AS n FROM box_watch_items WHERE COALESCE(activo, 1) = 1"
        ).fetchone()["n"]

        total_carpetas = conn.execute(
            "SELECT COUNT(*) AS n FROM box_watch_folders WHERE COALESCE(activo, 1) = 1"
        ).fetchone()["n"]

        sin_clasificar = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM box_watch_items
            WHERE COALESCE(activo, 1) = 1
              AND (
                    estado = 'SIN CLASIFICAR'
                    OR tipo_detectado IS NULL
                    OR TRIM(tipo_detectado) = ''
                    OR tipo_detectado = 'SIN CLASIFICAR'
                  )
            """
        ).fetchone()["n"]

        alertas_criticas = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM box_watch_alerts
            WHERE COALESCE(estado, 'ABIERTA') != 'RESUELTA'
              AND COALESCE(severidad, '') IN ('CRITICA', 'ALTA')
            """
        ).fetchone()["n"]

        last_run = conn.execute(
            """
            SELECT *
            FROM box_watch_scan_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    if last_run:
        last = dict(last_run)
        ultimo_escaneo = last.get("fecha_fin") or last.get("fecha_inicio") or last.get("created_at") or "Sin escaneos"
        nuevos = last.get("nuevos") or 0
        modificados = last.get("modificados") or 0
        alertas = last.get("alertas") or 0
        total_carpetas_run = last.get("total_carpetas") or 0
    else:
        ultimo_escaneo = "Sin escaneos"
        nuevos = 0
        modificados = 0
        alertas = 0
        total_carpetas_run = 0

    return {
        "total_carpetas": total_carpetas,
        "total_archivos": total_archivos,
        "total_carpetas_ultimo_escaneo": total_carpetas_run,
        "nuevos": nuevos,
        "modificados": modificados,
        "sin_clasificar": sin_clasificar,
        "alertas": alertas,
        "alertas_criticas": alertas_criticas,
        "ultimo_escaneo": ultimo_escaneo,
    }



def list_box_rules():
    initialize_box_watch_schema()
    with _connect() as conn:
        return [_dict(r) for r in conn.execute(
            """
            SELECT r.*, t.nombre AS tipo_expediente_nombre
            FROM box_watch_rules r
            LEFT JOIN config_tipos_expediente t ON t.id = r.tipo_expediente_id
            ORDER BY t.nombre ASC, r.codigo_documento ASC
            """
        ).fetchall()]


def list_box_root_client_folders(ruta_base=None, ruta_contains=None, limit=500):
    """
    Lista solo carpetas de primer nivel bajo ruta_base.

    Ejemplo:
    ruta_base = C:/Users/Nacho/Box/NACIONALIDADES/2019
    devuelve:
    C:/Users/Nacho/Box/NACIONALIDADES/2019/CLIENTE 1
    pero no:
    C:/Users/Nacho/Box/NACIONALIDADES/2019/CLIENTE 1/PARA PRESENTAR
    """
    ensure_box_watch_runtime_columns()

    where_parts = ["COALESCE(activo, 1) = 1"]
    params = []

    if ruta_base:
        base_path = str(ruta_base).strip().replace("\\", "/").rstrip("/")
        where_parts.append("REPLACE(ruta, '\\', '/') LIKE ?")
        params.append(base_path + "/%")

        # Primer nivel bajo la raíz: trozo relativo sin otra barra.
        where_parts.append("INSTR(SUBSTR(REPLACE(ruta, '\\', '/'), LENGTH(?) + 2), '/') = 0")
        params.append(base_path)
    else:
        where_parts.append("COALESCE(nivel, 0) <= 1")

    if ruta_contains:
        text = f"%{str(ruta_contains).lower().strip()}%"
        where_parts.append("(LOWER(nombre_carpeta) LIKE ? OR LOWER(ruta) LIKE ?)")
        params.extend([text, text])

    where_sql = " AND ".join(where_parts)

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM box_watch_folders
            WHERE {where_sql}
            ORDER BY nombre_carpeta ASC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()

    return [_dict(r) for r in rows]



def get_box_folder_inspection(folder_path):
    """
    Devuelve inspección de una carpeta concreta:
    - datos de la carpeta
    - subcarpetas directas
    - archivos directos
    - resumen por fases/categorías
    No accede a Box. Solo consulta SQLite.
    """
    initialize_box_watch_schema()
    if not folder_path:
        return {
            "folder": None,
            "subfolders": [],
            "files": [],
            "summary": {
                "total_subcarpetas": 0,
                "total_archivos": 0,
                "fases": {},
                "documentos": {},
            },
        }

    target = str(folder_path).strip().replace("\\", "/").rstrip("/")

    with _connect() as conn:
        folder = conn.execute(
            """
            SELECT *
            FROM box_watch_folders
            WHERE REPLACE(ruta, '\\', '/') = ?
            LIMIT 1
            """,
            (target,),
        ).fetchone()

        subfolders = conn.execute(
            """
            SELECT *
            FROM box_watch_folders
            WHERE COALESCE(activo, 1) = 1
              AND REPLACE(ruta, '\\', '/') LIKE ?
              AND INSTR(SUBSTR(REPLACE(ruta, '\\', '/'), LENGTH(?) + 2), '/') = 0
            ORDER BY nombre_carpeta ASC
            """,
            (target + "/%", target),
        ).fetchall()

        files = conn.execute(
            """
            SELECT *
            FROM box_watch_items
            WHERE COALESCE(activo, 1) = 1
              AND REPLACE(ruta, '\\', '/') = ?
            ORDER BY nombre_archivo ASC
            """,
            (target,),
        ).fetchall()

        fases = conn.execute(
            """
            SELECT COALESCE(tipo_detectado, 'OTROS') AS categoria, COUNT(*) AS total
            FROM box_watch_folders
            WHERE COALESCE(activo, 1) = 1
              AND REPLACE(ruta, '\\', '/') LIKE ?
            GROUP BY COALESCE(tipo_detectado, 'OTROS')
            ORDER BY total DESC
            """,
            (target + "/%",),
        ).fetchall()

        documentos = conn.execute(
            """
            SELECT COALESCE(tipo_detectado, 'SIN CLASIFICAR') AS tipo, COUNT(*) AS total
            FROM box_watch_items
            WHERE COALESCE(activo, 1) = 1
              AND (
                    REPLACE(ruta, '\\', '/') = ?
                    OR REPLACE(ruta, '\\', '/') LIKE ?
                  )
            GROUP BY COALESCE(tipo_detectado, 'SIN CLASIFICAR')
            ORDER BY total DESC
            """,
            (target, target + "/%"),
        ).fetchall()

    return {
        "folder": _dict(folder) if folder else None,
        "subfolders": [_dict(r) for r in subfolders],
        "files": [_dict(r) for r in files],
        "summary": {
            "total_subcarpetas": len(subfolders),
            "total_archivos": len(files),
            "fases": {r["categoria"]: r["total"] for r in fases},
            "documentos": {r["tipo"]: r["total"] for r in documentos},
        },
    }



def ensure_box_watch_runtime_columns():
    """
    Migración defensiva del módulo Box.

    Soluciona errores tipo:
    - no such column: total_archivos
    - no such column: total_subcarpetas
    - no such column: tamano_total_bytes
    - no such column: fecha_ultima_actividad

    No toca Box. Solo ajusta SQLite para que la vista y el servicio sean compatibles.
    """
    initialize_box_watch_schema()

    required = {
        "box_watch_folders": {
            "nombre_carpeta": "TEXT",
            "ruta": "TEXT",
            "ruta_padre": "TEXT",
            "tipo_detectado": "TEXT",
            "nivel": "INTEGER DEFAULT 0",
            "cliente_id": "INTEGER",
            "expediente_id": "INTEGER",
            "total_archivos": "INTEGER DEFAULT 0",
            "total_subcarpetas": "INTEGER DEFAULT 0",
            "tamano_total_bytes": "INTEGER DEFAULT 0",
            "fecha_ultima_actividad": "TEXT",
            "estado": "TEXT DEFAULT 'OK'",
            "observaciones": "TEXT",
            "activo": "INTEGER DEFAULT 1",
            "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
            "last_seen_scan_id": "INTEGER",
        },
        "box_watch_scan_runs": {
            "fecha_inicio": "TEXT",
            "fecha_fin": "TEXT",
            "ruta_base": "TEXT",
            "total_carpetas": "INTEGER DEFAULT 0",
            "total_archivos": "INTEGER DEFAULT 0",
            "nuevos": "INTEGER DEFAULT 0",
            "modificados": "INTEGER DEFAULT 0",
            "sin_clasificar": "INTEGER DEFAULT 0",
            "alertas": "INTEGER DEFAULT 0",
            "estado": "TEXT DEFAULT 'OK'",
            "observaciones": "TEXT",
            "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
        },
        "box_watch_items": {
            "ruta": "TEXT",
            "nombre_archivo": "TEXT",
            "extension": "TEXT",
            "tipo_detectado": "TEXT",
            "cliente_id": "INTEGER",
            "expediente_id": "INTEGER",
            "hoja_encargo_id": "INTEGER",
            "tamano_bytes": "INTEGER DEFAULT 0",
            "fecha_modificacion": "TEXT",
            "hash_archivo": "TEXT",
            "estado": "TEXT DEFAULT 'OK'",
            "observaciones": "TEXT",
            "activo": "INTEGER DEFAULT 1",
            "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
            "last_seen_scan_id": "INTEGER",
        },
    }

    with _connect() as conn:
        for table, columns in required.items():
            existing = {
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.commit()

    try:
        ensure_box_watch_indexes()
    except Exception:
        pass


def recalculate_box_folder_counters():
    """
    Recalcula contadores de carpetas ya inventariadas.

    Útil después de una migración de columnas o de un escaneo antiguo.
    No accede a Box; solo usa los datos ya guardados en SQLite.
    """
    ensure_box_watch_runtime_columns()

    with _connect() as conn:
        folders = conn.execute(
            """
            SELECT id, REPLACE(ruta, '\\', '/') AS ruta
            FROM box_watch_folders
            WHERE COALESCE(activo, 1) = 1
            """
        ).fetchall()

        for folder in folders:
            ruta = folder["ruta"].rstrip("/")

            direct_files = conn.execute(
                """
                SELECT COUNT(*) AS total, COALESCE(SUM(tamano_bytes), 0) AS size, MAX(fecha_modificacion) AS last_mod
                FROM box_watch_items
                WHERE COALESCE(activo, 1) = 1
                  AND REPLACE(ruta, '\\', '/') = ?
                """,
                (ruta,),
            ).fetchone()

            direct_folders = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM box_watch_folders
                WHERE COALESCE(activo, 1) = 1
                  AND REPLACE(ruta, '\\', '/') LIKE ?
                  AND INSTR(SUBSTR(REPLACE(ruta, '\\', '/'), LENGTH(?) + 2), '/') = 0
                """,
                (ruta + "/%", ruta),
            ).fetchone()

            conn.execute(
                """
                UPDATE box_watch_folders
                SET total_archivos = ?,
                    total_subcarpetas = ?,
                    tamano_total_bytes = ?,
                    fecha_ultima_actividad = COALESCE(?, fecha_ultima_actividad),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    int(direct_files["total"] or 0),
                    int(direct_folders["total"] or 0),
                    int(direct_files["size"] or 0),
                    direct_files["last_mod"],
                    folder["id"],
                ),
            )

        conn.commit()



def get_configured_box_routes(active_only=True):
    """
    Rutas Box configuradas en Configuración.
    Devuelve rutas relativas y resueltas para el ordenador actual.
    """
    config_service.initialize_config_schema()
    return config_service.get_box_rutas(active_only=active_only, include_resolved=True)


def get_configured_box_route(record_id):
    config_service.initialize_config_schema()
    return config_service.get_box_ruta(record_id, include_resolved=True)


def list_root_folders_for_configured_route(route_id, ruta_contains=None, limit=500):
    """
    Carga carpetas raíz de una ruta configurada.

    Versión robusta:
    - resuelve ruta configurada
    - normaliza barras
    - devuelve solo primer nivel
    """
    ensure_box_watch_runtime_columns()
    route = get_configured_box_route(route_id)
    if not route:
        return []

    ruta_base = route.get("ruta_resuelta")
    rows = list_box_root_client_folders(
        ruta_base=ruta_base,
        ruta_contains=ruta_contains,
        limit=limit,
    )

    for folder in rows:
        folder["config_route_id"] = route.get("id")
        folder["config_route_label"] = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"
        folder["config_route_relative"] = route.get("ruta_box")
        folder["config_route_resolved"] = route.get("ruta_resuelta")

    return rows


def list_root_folders_for_all_configured_routes(ruta_contains=None, limit_per_route=500):
    ensure_box_watch_runtime_columns()
    routes = get_configured_box_routes(active_only=True)
    result = []

    for route in routes:
        rows = list_box_root_client_folders(
            ruta_base=route.get("ruta_resuelta"),
            ruta_contains=ruta_contains,
            limit=limit_per_route,
        )
        for folder in rows:
            folder["config_route_id"] = route.get("id")
            folder["config_route_label"] = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"
            folder["config_route_relative"] = route.get("ruta_box")
            folder["config_route_resolved"] = route.get("ruta_resuelta")
        result.extend(rows)

    return result


def scan_configured_routes(route_ids=None, progress_callback=None, calculate_hash=False):
    """
    Reescanea rutas configuradas.
    route_ids=None => todas las rutas activas.
    """
    ensure_box_watch_runtime_columns()

    routes = get_configured_box_routes(active_only=True)
    if route_ids:
        wanted = {int(x) for x in route_ids}
        routes = [r for r in routes if int(r.get("id")) in wanted]

    results = []
    total_routes = len(routes)

    for index, route in enumerate(routes, start=1):
        resolved = route.get("ruta_resuelta")
        if not resolved:
            continue

        if progress_callback:
            progress_callback({
                "route_index": index,
                "total_routes": total_routes,
                "route_label": f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}",
                "current_file": f"Escaneando ruta {index}/{total_routes}: {route.get('ruta_box')}",
                "processed": 0,
                "processed_folders": 0,
                "total": 0,
                "total_folders": 0,
                "percent": 0,
            })

        result = scan_local_box_path(
            resolved,
            progress_callback=progress_callback,
            calculate_hash=calculate_hash,
        )
        result["config_route_id"] = route.get("id")
        result["config_route_relative"] = route.get("ruta_box")
        result["config_route_resolved"] = resolved
        results.append(result)

    try:
        recalculate_box_folder_counters()
    except Exception:
        pass

    return results

def list_root_folders_exact_for_route_id(route_id, ruta_contains=None, limit=500):
    """
    Carga carpetas raíz usando exactamente la lógica validada por el diagnóstico.

    Esta función evita depender de estados de la vista o de filtros intermedios.
    Si diagnose_box_watch_loading dice que hay 3 carpetas raíz, esta función debe devolver esas 3.
    """
    ensure_box_watch_runtime_columns()

    route = get_configured_box_route(route_id)
    if not route:
        return []

    ruta_resuelta = str(route.get("ruta_resuelta") or "").replace("\\", "/").rstrip("/")
    if not ruta_resuelta:
        return []

    where_parts = [
        "COALESCE(activo, 1) = 1",
        "REPLACE(ruta, '\\', '/') LIKE ?",
        "INSTR(SUBSTR(REPLACE(ruta, '\\', '/'), LENGTH(?) + 2), '/') = 0",
    ]
    params = [ruta_resuelta + "/%", ruta_resuelta]

    if ruta_contains:
        text = f"%{str(ruta_contains).lower().strip()}%"
        where_parts.append("(LOWER(nombre_carpeta) LIKE ? OR LOWER(ruta) LIKE ?)")
        params.extend([text, text])

    where_sql = " AND ".join(where_parts)

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM box_watch_folders
            WHERE {where_sql}
            ORDER BY nombre_carpeta ASC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()

    result = [_dict(r) for r in rows]
    for folder in result:
        folder["config_route_id"] = route.get("id")
        folder["config_route_label"] = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"
        folder["config_route_relative"] = route.get("ruta_box")
        folder["config_route_resolved"] = route.get("ruta_resuelta")

    return result


def list_root_folders_exact_for_all_routes(ruta_contains=None, limit_per_route=500):
    """
    Carga carpetas raíz de todas las rutas activas usando la consulta exacta.
    """
    routes = get_configured_box_routes(active_only=True)
    result = []
    for route in routes:
        result.extend(
            list_root_folders_exact_for_route_id(
                route.get("id"),
                ruta_contains=ruta_contains,
                limit=limit_per_route,
            )
        )
    return result


def debug_box_route_counts(route_id):
    """
    Diagnóstico compacto para mostrar desde la vista si una carga devuelve 0.
    """
    ensure_box_watch_runtime_columns()
    route = get_configured_box_route(route_id)
    if not route:
        return {"error": "Ruta no encontrada"}

    ruta_resuelta = str(route.get("ruta_resuelta") or "").replace("\\", "/").rstrip("/")

    with _connect() as conn:
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

    return {
        "route_id": route_id,
        "ruta_relativa": route.get("ruta_box"),
        "ruta_resuelta": ruta_resuelta,
        "ruta_existe": route.get("ruta_existe"),
        "folders_like": folders_like,
        "root_folders": root_folders,
    }


def list_root_folders_python_fallback_for_route_id(route_id, ruta_contains=None, limit=500):
    """
    Fallback ultra robusto:
    - trae carpetas bajo la ruta configurada
    - normaliza rutas en Python
    - detecta primer nivel en Python

    Evita errores por diferencias de barras Windows en SQLite.
    """
    ensure_box_watch_runtime_columns()

    route = get_configured_box_route(route_id)
    if not route:
        return []

    base_path = str(route.get("ruta_resuelta") or "").replace("\\", "/").rstrip("/")
    text = str(ruta_contains or "").lower().strip()

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
    prefix = base_path + "/"

    for row in rows:
        folder = _dict(row)
        ruta = str(folder.get("ruta") or "").replace("\\", "/").rstrip("/")

        if not ruta.startswith(prefix):
            continue

        relative = ruta[len(prefix):]
        if "/" in relative:
            continue

        if text:
            haystack = (str(folder.get("nombre_carpeta") or "") + " " + ruta).lower()
            if text not in haystack:
                continue

        folder["config_route_id"] = route.get("id")
        folder["config_route_label"] = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"
        folder["config_route_relative"] = route.get("ruta_box")
        folder["config_route_resolved"] = route.get("ruta_resuelta")
        result.append(folder)

        if len(result) >= int(limit):
            break

    return result


def list_root_folders_python_fallback_for_all_routes(ruta_contains=None, limit_per_route=500):
    routes = get_configured_box_routes(active_only=True)
    result = []
    for route in routes:
        result.extend(
            list_root_folders_python_fallback_for_route_id(
                route.get("id"),
                ruta_contains=ruta_contains,
                limit=limit_per_route,
            )
        )
    return result

# === QUESADA BOX PROFESSIONAL SAFE OVERRIDE START ===

def _qa_norm_path(value):
    return str(value or "").replace("\\", "/").rstrip("/")


def get_last_scan_for_folder_path(folder_path):
    """
    Último escaneo que cubre una carpeta.
    No toca Box.
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
    output = []
    for folder in folders or []:
        item = dict(folder)
        value = get_last_scan_for_folder_path(item.get("ruta"))
        item["last_scan"] = value
        item["ultimo_escaneo"] = value
        output.append(item)
    return output


def list_root_folders_python_fallback_for_route_id(route_id, ruta_contains=None, limit=500):
    """
    Carga carpetas raíz de una ruta configurada.
    Filtrado en Python para evitar problemas con barras Windows.
    """
    ensure_box_watch_runtime_columns()

    route = get_configured_box_route(route_id)
    if not route:
        return []

    base_path = _qa_norm_path(route.get("ruta_resuelta"))
    if not base_path:
        return []

    text = str(ruta_contains or "").lower().strip()
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
        ruta = _qa_norm_path(folder.get("ruta"))

        if not ruta.startswith(prefix):
            continue

        relative = ruta[len(prefix):]
        if "/" in relative:
            continue

        if text:
            haystack = (str(folder.get("nombre_carpeta") or "") + " " + ruta).lower()
            if text not in haystack:
                continue

        folder["config_route_id"] = route.get("id")
        folder["config_route_label"] = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"
        folder["config_route_relative"] = route.get("ruta_box")
        folder["config_route_resolved"] = route.get("ruta_resuelta")

        result.append(folder)

        if len(result) >= int(limit or 500):
            break

    return attach_last_scan_to_folders(result)


def list_root_folders_python_fallback_for_all_routes(ruta_contains=None, limit_per_route=500):
    routes = get_configured_box_routes(active_only=True)
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


def build_folder_tree_text(folder_path, max_depth=6, max_items=5000):
    """
    Construye árbol textual desde SQLite.
    No toca Box ni lee disco.
    """
    ensure_box_watch_runtime_columns()

    root = _qa_norm_path(folder_path)
    if not root:
        raise ValueError("No hay carpeta seleccionada")

    max_depth = int(max_depth or 6)
    max_items = int(max_items or 5000)

    with _connect() as conn:
        folder_rows = conn.execute(
            """
            SELECT *
            FROM box_watch_folders
            WHERE COALESCE(activo, 1) = 1
              AND (
                    REPLACE(ruta, '\\', '/') = ?
                    OR REPLACE(ruta, '\\', '/') LIKE ?
                  )
            ORDER BY ruta ASC
            LIMIT ?
            """,
            (root, root + "/%", max_items),
        ).fetchall()

        file_rows = conn.execute(
            """
            SELECT *
            FROM box_watch_items
            WHERE COALESCE(activo, 1) = 1
              AND (
                    REPLACE(ruta, '\\', '/') = ?
                    OR REPLACE(ruta, '\\', '/') LIKE ?
                  )
            ORDER BY ruta ASC, nombre_archivo ASC
            LIMIT ?
            """,
            (root, root + "/%", max_items),
        ).fetchall()

    root_name = root.split("/")[-1]
    folders_by_parent = {}
    files_by_parent = {}

    for row in folder_rows:
        d = _dict(row)
        ruta = _qa_norm_path(d.get("ruta"))
        if ruta == root:
            continue
        rel = ruta[len(root):].strip("/")
        depth = len([p for p in rel.split("/") if p])
        if depth > max_depth:
            continue
        parent = "/".join(ruta.split("/")[:-1])
        folders_by_parent.setdefault(parent, []).append(d)

    for row in file_rows:
        d = _dict(row)
        ruta = _qa_norm_path(d.get("ruta"))
        rel_parent = ruta[len(root):].strip("/")
        depth = len([p for p in rel_parent.split("/") if p])
        if depth > max_depth:
            continue
        files_by_parent.setdefault(ruta, []).append(d)

    lines = [
        "ARBOL DOCUMENTAL BOX",
        "=" * 80,
        f"Carpeta: {root_name}",
        f"Ruta: {root}",
        "",
        root_name,
    ]

    count = {"folders": 0, "files": 0}

    def walk(parent_path, indent):
        if count["folders"] + count["files"] >= max_items:
            lines.append("  " * indent + "... limite de elementos alcanzado")
            return

        for folder in folders_by_parent.get(parent_path, []):
            folder_name = folder.get("nombre_carpeta") or _qa_norm_path(folder.get("ruta")).split("/")[-1]
            categoria = folder.get("tipo_detectado") or "OTROS"
            lines.append("  " * indent + f"[CARPETA] {folder_name} [{categoria}]")
            count["folders"] += 1
            walk(_qa_norm_path(folder.get("ruta")), indent + 1)

        for item in files_by_parent.get(parent_path, []):
            name = item.get("nombre_archivo") or "archivo"
            tipo = item.get("tipo_detectado") or "SIN CLASIFICAR"
            ext = item.get("extension") or ""
            lines.append("  " * indent + f"[ARCHIVO] {name} [{tipo}] [{ext}]")
            count["files"] += 1

    walk(root, 1)

    lines.extend([
        "",
        "=" * 80,
        f"Total carpetas listadas: {count['folders']}",
        f"Total archivos listados: {count['files']}",
        "Nota: generado desde inventario SQLite. No modifica Box.",
    ])

    return "\n".join(lines)


def export_folder_tree_to_txt(folder_path, output_dir=None):
    from pathlib import Path
    import re

    tree = build_folder_tree_text(folder_path)
    safe_name = _qa_norm_path(folder_path).split("/")[-1] or "carpeta"
    safe_name = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ _.-]+", "_", safe_name).strip() or "carpeta"

    out_dir = Path(output_dir) if output_dir else Path(__file__).resolve().parents[2] / "exports" / "box_trees"
    out_dir.mkdir(parents=True, exist_ok=True)

    output_path = out_dir / f"arbol_box_{safe_name}.txt"
    output_path.write_text(tree, encoding="utf-8")
    return str(output_path)


def export_multiple_folder_trees_to_txt(folder_paths, output_name="arbol_box_seleccion.txt"):
    from pathlib import Path
    import re

    paths = [p for p in (folder_paths or []) if p]
    if not paths:
        raise ValueError("No hay carpetas seleccionadas para exportar")

    out_dir = Path(__file__).resolve().parents[2] / "exports" / "box_trees"
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ _.-]+", "_", output_name or "arbol_box_seleccion.txt")
    if not safe_name.lower().endswith(".txt"):
        safe_name += ".txt"

    output_path = out_dir / safe_name

    chunks = []
    for index, folder_path in enumerate(paths, start=1):
        chunks.append("#" * 100)
        chunks.append(f"ARBOL {index}/{len(paths)}")
        chunks.append("#" * 100)
        chunks.append(build_folder_tree_text(folder_path))
        chunks.append("")

    output_path.write_text("\n".join(chunks), encoding="utf-8")
    return str(output_path)


def open_path_in_explorer(path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    target = Path(str(path or "").strip())
    if not target.exists():
        raise FileNotFoundError(f"No existe: {target}")

    if sys.platform.startswith("win"):
        os.startfile(str(target))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])

    return True


def open_export_folder_for_file(file_path):
    from pathlib import Path
    p = Path(str(file_path or "").strip())
    if not p.exists():
        raise FileNotFoundError(f"No existe el archivo exportado: {p}")
    return open_path_in_explorer(p.parent)

# === QUESADA BOX PROFESSIONAL SAFE OVERRIDE END ===

# === QUESADA BOX RECURSIVE TOTALS OVERRIDE START ===

def attach_recursive_totals_to_folders(folders):
    """
    Añade totales recursivos por carpeta:
    - total_archivos_directos
    - total_subcarpetas_directas
    - total_archivos_recursivos
    - total_subcarpetas_recursivas

    No toca Box. Solo consulta SQLite.
    """
    ensure_box_watch_runtime_columns()

    output = []

    with _connect() as conn:
        for folder in folders or []:
            item = dict(folder)
            ruta = str(item.get("ruta") or "").replace("\\", "/").rstrip("/")

            direct_files = int(item.get("total_archivos") or 0)
            direct_folders = int(item.get("total_subcarpetas") or 0)

            recursive_files = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM box_watch_items
                WHERE COALESCE(activo, 1) = 1
                  AND (
                        REPLACE(ruta, '\\', '/') = ?
                        OR REPLACE(ruta, '\\', '/') LIKE ?
                      )
                """,
                (ruta, ruta + "/%"),
            ).fetchone()["n"]

            recursive_folders = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM box_watch_folders
                WHERE COALESCE(activo, 1) = 1
                  AND REPLACE(ruta, '\\', '/') LIKE ?
                """,
                (ruta + "/%",),
            ).fetchone()["n"]

            item["total_archivos_directos"] = direct_files
            item["total_subcarpetas_directas"] = direct_folders
            item["total_archivos_recursivos"] = int(recursive_files or 0)
            item["total_subcarpetas_recursivas"] = int(recursive_folders or 0)

            output.append(item)

    return output


# Guardamos referencias si existen para no perder last_scan.
try:
    _qa_previous_attach_last_scan_to_folders = attach_last_scan_to_folders
except Exception:
    _qa_previous_attach_last_scan_to_folders = None


def attach_last_scan_to_folders(folders):
    """
    Compatibilidad:
    1) añade last_scan/ultimo_escaneo si existe helper previo
    2) añade totales recursivos
    """
    base = folders or []

    if _qa_previous_attach_last_scan_to_folders:
        try:
            base = _qa_previous_attach_last_scan_to_folders(base)
        except Exception:
            base = folders or []

    # Si no había helper previo, intentamos añadir last_scan aquí.
    enriched = []
    for folder in base or []:
        item = dict(folder)
        if "last_scan" not in item:
            try:
                value = get_last_scan_for_folder_path(item.get("ruta"))
            except Exception:
                value = None
            item["last_scan"] = value
            item["ultimo_escaneo"] = value
        enriched.append(item)

    return attach_recursive_totals_to_folders(enriched)


# Sobrescribimos las funciones de carga para garantizar totales recursivos.
try:
    _qa_previous_list_route = list_root_folders_python_fallback_for_route_id
except Exception:
    _qa_previous_list_route = None

try:
    _qa_previous_list_all = list_root_folders_python_fallback_for_all_routes
except Exception:
    _qa_previous_list_all = None


def list_root_folders_python_fallback_for_route_id(route_id, ruta_contains=None, limit=500):
    if _qa_previous_list_route:
        rows = _qa_previous_list_route(route_id, ruta_contains=ruta_contains, limit=limit)
        return attach_last_scan_to_folders(rows)

    return []


def list_root_folders_python_fallback_for_all_routes(ruta_contains=None, limit_per_route=500):
    if _qa_previous_list_all:
        rows = _qa_previous_list_all(ruta_contains=ruta_contains, limit_per_route=limit_per_route)
        return attach_last_scan_to_folders(rows)

    routes = get_configured_box_routes(active_only=True)
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

# === QUESADA BOX RECURSIVE TOTALS OVERRIDE END ===


# === QUESADA BOX CANDIDATES EXPEDIENTE V6 START ===

def _qa_normalize_match_text(value):
    import re
    import unicodedata

    value = str(value or "").upper().strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("Ñ", "N")
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _qa_get_expediente_candidate_context(expediente_id):
    expediente_id = int(expediente_id)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                e.id,
                e.numero_expediente,
                e.tipo_expediente_id,
                e.subtipo_expediente_id,
                e.subtipo_expediente,
                e.fecha_apertura,
                e.box_folder_path,
                c.id AS cliente_id,
                c.nombre AS cliente_nombre,
                c.primer_apellido AS cliente_primer_apellido,
                c.segundo_apellido AS cliente_segundo_apellido,
                c.nie AS cliente_nie,
                c.pasaporte AS cliente_pasaporte,
                c.dni AS cliente_dni,
                te.nombre AS tipo_expediente_nombre,
                te.codigo AS tipo_expediente_codigo,
                st.nombre AS subtipo_expediente_nombre,
                st.codigo AS subtipo_expediente_codigo
            FROM expedientes e
            JOIN clientes c ON c.id = e.cliente_id
            LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
            LEFT JOIN config_subtipos_expediente st ON st.id = e.subtipo_expediente_id
            WHERE e.id = ?
            """,
            (expediente_id,),
        ).fetchone()

    if not row:
        raise ValueError("Expediente no encontrado")

    return _dict(row)


def _qa_candidate_year(ctx):
    from datetime import date

    fecha = str(ctx.get("fecha_apertura") or "").strip()
    if len(fecha) >= 4 and fecha[:4].isdigit():
        return fecha[:4]
    return str(date.today().year)


def _qa_candidate_terms(ctx):
    nombre = ctx.get("cliente_nombre") or ""
    apellido1 = ctx.get("cliente_primer_apellido") or ""
    apellido2 = ctx.get("cliente_segundo_apellido") or ""

    full_name = " ".join([nombre, apellido1, apellido2]).strip()
    name_pairs = [
        full_name,
        " ".join([nombre, apellido1]).strip(),
        " ".join([apellido1, apellido2]).strip(),
        apellido1,
        apellido2,
        nombre,
        ctx.get("cliente_nie") or "",
        ctx.get("cliente_pasaporte") or "",
        ctx.get("cliente_dni") or "",
        ctx.get("numero_expediente") or "",
    ]

    result = []
    seen = set()
    for term in name_pairs:
        norm = _qa_normalize_match_text(term)
        if len(norm) < 3:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        result.append({
            "raw": str(term or "").strip(),
            "norm": norm,
            "parts": [p for p in norm.split(" ") if len(p) >= 3],
        })

    return result


def _qa_routes_for_expediente_candidates(ctx):
    routes = get_configured_box_routes(active_only=True)
    tipo_id = ctx.get("tipo_expediente_id")
    year = _qa_candidate_year(ctx)

    if tipo_id:
        typed_routes = [r for r in routes if int(r.get("tipo_expediente_id") or 0) == int(tipo_id)]
    else:
        typed_routes = []

    selected = typed_routes or routes

    # Si hay rutas del mismo tipo que contienen el año del expediente, priorizarlas.
    year_routes = [
        r for r in selected
        if year and (
            year in str(r.get("ruta_box") or "")
            or year in str(r.get("ruta_resuelta") or "")
        )
    ]
    if year_routes:
        selected = year_routes

    return selected


def _qa_score_box_candidate(folder, ctx, terms, route):
    ruta = folder.get("ruta") or folder.get("ruta_norm") or ""
    nombre = folder.get("nombre_carpeta") or ""
    haystack = _qa_normalize_match_text(" ".join([ruta, nombre]))

    score = 0
    reasons = []

    full_name = _qa_normalize_match_text(" ".join([
        ctx.get("cliente_nombre") or "",
        ctx.get("cliente_primer_apellido") or "",
        ctx.get("cliente_segundo_apellido") or "",
    ]))
    if full_name and full_name in haystack:
        score += 120
        reasons.append("nombre completo")

    for term in terms:
        norm = term["norm"]
        parts = term.get("parts") or []
        if norm and norm in haystack:
            score += 60
            reasons.append(term["raw"])
        elif parts and all(part in haystack for part in parts):
            score += 45
            reasons.append("coincidencia parcial " + term["raw"])

    for doc_key in ["cliente_nie", "cliente_pasaporte", "cliente_dni"]:
        doc = _qa_normalize_match_text(ctx.get(doc_key) or "")
        if doc and doc in haystack:
            score += 80
            reasons.append(doc_key)

    if route and int(route.get("tipo_expediente_id") or 0) == int(ctx.get("tipo_expediente_id") or 0):
        score += 25
        reasons.append("ruta del tipo expediente")

    folder_expediente_id = folder.get("expediente_id")
    if folder_expediente_id and int(folder_expediente_id) != int(ctx["id"]):
        score -= 70
        reasons.append("ya vinculada a otro expediente")

    if folder.get("fecha_ultima_actividad"):
        score += 5

    return score, reasons


def _qa_collect_indexed_candidates_for_route(ctx, terms, route, limit=20):
    collected = {}
    route_id = route.get("id")

    search_terms = []
    for term in terms:
        if term.get("raw"):
            search_terms.append(term["raw"])
        for part in term.get("parts") or []:
            if len(part) >= 4:
                search_terms.append(part)

    # Evitar explosion de consultas: los mejores terminos suelen ser nombre+apellido y documentos.
    dedup_terms = []
    seen = set()
    for term in search_terms:
        norm = _qa_normalize_match_text(term)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        dedup_terms.append(term)
        if len(dedup_terms) >= 8:
            break

    for term in dedup_terms:
        try:
            rows = list_root_folders_for_configured_route(
                route_id,
                ruta_contains=term,
                limit=max(limit * 3, 30),
            )
        except Exception:
            rows = []

        for row in rows:
            ruta = row.get("ruta") or row.get("ruta_norm") or ""
            if not ruta:
                continue
            score, reasons = _qa_score_box_candidate(row, ctx, terms, route)
            if score <= 0:
                continue
            previous = collected.get(ruta)
            item = dict(row)
            item["score"] = score
            item["match_reasons"] = sorted(set(reasons))
            item["config_route_id"] = route.get("id")
            item["config_route_label"] = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"
            item["config_route_relative"] = route.get("ruta_box")
            item["config_route_resolved"] = route.get("ruta_resuelta")
            if not previous or score > previous.get("score", 0):
                collected[ruta] = item

    return list(collected.values())


def find_box_folder_candidates_for_expediente(expediente_id, force_scan=False, limit=20):
    """
    Busca carpetas Box candidatas para un expediente.

    Modo rapido:
    - consulta el indice SQLite de Box Watch.

    Modo force_scan:
    - escanea solo las rutas configuradas compatibles con el tipo/anio del expediente,
      no todo Box;
    - vuelve a consultar el indice.

    Seguridad:
    - no modifica Box;
    - no mueve, borra ni renombra archivos;
    - solo actualiza el indice local si force_scan=True.
    """
    ensure_box_watch_runtime_columns()

    ctx = _qa_get_expediente_candidate_context(expediente_id)
    terms = _qa_candidate_terms(ctx)
    routes = _qa_routes_for_expediente_candidates(ctx)

    if force_scan:
        route_ids = [int(r.get("id")) for r in routes if r.get("id")]
        if route_ids:
            scan_configured_routes(route_ids=route_ids, progress_callback=None, calculate_hash=False)

    candidates = []
    for route in routes:
        candidates.extend(_qa_collect_indexed_candidates_for_route(ctx, terms, route, limit=limit))

    by_path = {}
    for item in candidates:
        ruta = item.get("ruta") or item.get("ruta_norm") or ""
        if not ruta:
            continue
        previous = by_path.get(ruta)
        if not previous or int(item.get("score") or 0) > int(previous.get("score") or 0):
            by_path[ruta] = item

    result = sorted(
        by_path.values(),
        key=lambda x: (int(x.get("score") or 0), str(x.get("fecha_ultima_actividad") or "")),
        reverse=True,
    )

    return {
        "expediente_id": int(expediente_id),
        "cliente_id": int(ctx.get("cliente_id")),
        "cliente_nombre": " ".join([
            ctx.get("cliente_nombre") or "",
            ctx.get("cliente_primer_apellido") or "",
            ctx.get("cliente_segundo_apellido") or "",
        ]).strip(),
        "tipo_expediente_id": ctx.get("tipo_expediente_id"),
        "tipo_expediente_nombre": ctx.get("tipo_expediente_nombre"),
        "force_scan": bool(force_scan),
        "routes": [
            {
                "id": r.get("id"),
                "tipo_expediente_id": r.get("tipo_expediente_id"),
                "tipo_expediente_nombre": r.get("tipo_expediente_nombre"),
                "ruta_box": r.get("ruta_box"),
                "ruta_resuelta": r.get("ruta_resuelta"),
                "ruta_existe": r.get("ruta_existe"),
            }
            for r in routes
        ],
        "terms": [t["raw"] for t in terms],
        "candidates": result[:limit],
    }

# === QUESADA BOX CANDIDATES EXPEDIENTE V6 END ===


# === QUESADA BOX FOLDER OPTIONS EXPEDIENTE V6 START ===

def _qa_folder_options_context(expediente_id):
    """
    Contexto mínimo de expediente y cliente para selector manual-asistido.
    """
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                e.id,
                e.numero_expediente,
                e.tipo_expediente_id,
                e.subtipo_expediente_id,
                e.box_folder_path,
                c.id AS cliente_id,
                c.nombre AS cliente_nombre,
                c.primer_apellido AS cliente_primer_apellido,
                c.segundo_apellido AS cliente_segundo_apellido,
                c.nie AS cliente_nie,
                c.pasaporte AS cliente_pasaporte,
                c.dni AS cliente_dni,
                te.nombre AS tipo_expediente_nombre,
                te.codigo AS tipo_expediente_codigo
            FROM expedientes e
            JOIN clientes c ON c.id = e.cliente_id
            LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
            WHERE e.id = ?
            """,
            (int(expediente_id),),
        ).fetchone()

    if not row:
        raise ValueError("Expediente no encontrado")

    return _dict(row)


def _qa_safe_norm(value):
    import re
    import unicodedata

    value = str(value or "")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.upper().replace("Ñ", "N")
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return " ".join(value.split())


def _qa_folder_option_score(folder, ctx):
    """
    Puntuación orientativa. No excluye resultados.
    Sirve solo para ordenar.
    """
    haystack = _qa_safe_norm(f"{folder.get('nombre_carpeta') or ''} {folder.get('ruta') or ''}")

    nombre = _qa_safe_norm(ctx.get("cliente_nombre"))
    ap1 = _qa_safe_norm(ctx.get("cliente_primer_apellido"))
    ap2 = _qa_safe_norm(ctx.get("cliente_segundo_apellido"))
    nie = _qa_safe_norm(ctx.get("cliente_nie"))
    pasaporte = _qa_safe_norm(ctx.get("cliente_pasaporte"))
    dni = _qa_safe_norm(ctx.get("cliente_dni"))

    score = 0
    reasons = []

    full = " ".join(x for x in [nombre, ap1, ap2] if x).strip()
    name_ap1 = " ".join(x for x in [nombre, ap1] if x).strip()
    apellidos = " ".join(x for x in [ap1, ap2] if x).strip()

    checks = [
        (full, 120, "nombre completo"),
        (name_ap1, 90, "nombre y primer apellido"),
        (apellidos, 80, "apellidos"),
        (ap1, 30, "primer apellido"),
        (nombre, 15, "nombre"),
    ]

    for term, points, label in checks:
        if term and len(term) >= 3 and term in haystack:
            score += points
            reasons.append(label)

    for doc_label, doc in [("NIE", nie), ("pasaporte", pasaporte), ("DNI", dni)]:
        if doc and len(doc) >= 5 and doc in haystack:
            score += 150
            reasons.append(doc_label)

    linked_exp = folder.get("expediente_id")
    if linked_exp:
        try:
            if int(linked_exp) == int(ctx.get("id")):
                score += 200
                reasons.append("ya vinculado a este expediente")
            else:
                score -= 100
                reasons.append(f"vinculado a expediente {linked_exp}")
        except Exception:
            pass

    return score, reasons


def _qa_routes_for_folder_options(ctx, include_all_if_missing=True):
    routes = get_configured_box_routes(active_only=True)
    tipo_id = ctx.get("tipo_expediente_id")

    exact = []
    if tipo_id:
        exact = [
            route for route in routes
            if int(route.get("tipo_expediente_id") or 0) == int(tipo_id)
        ]

    if exact:
        for route in exact:
            route["candidate_route_strategy"] = "tipo_expediente"
        return exact

    if include_all_if_missing:
        for route in routes:
            route["candidate_route_strategy"] = "todas_las_rutas_configuradas"
        return routes

    return []


def list_box_folder_options_for_expediente(expediente_id, force_scan=False, limit_per_route=500):
    """
    Selector manual-asistido de carpetas Box para un expediente.

    - Carga todas las carpetas raiz de la ruta configurada del tipo.
    - Si el tipo no tiene ruta configurada, carga todas las rutas activas.
    - Si force_scan=True, escanea primero esas rutas.
    - No manipula Box; solo lee e indexa en SQLite.
    """
    ensure_box_watch_runtime_columns()

    ctx = _qa_folder_options_context(expediente_id)
    routes = _qa_routes_for_folder_options(ctx, include_all_if_missing=True)

    scanned_route_ids = []
    scan_error = ""

    if force_scan and routes:
        route_ids = [
            int(route.get("id"))
            for route in routes
            if route.get("id") and int(route.get("ruta_existe") or 0) == 1
        ]

        if route_ids:
            scan_configured_routes(
                route_ids=route_ids,
                progress_callback=None,
                calculate_hash=False,
            )
            scanned_route_ids = route_ids
        else:
            scan_error = "No hay rutas existentes en este equipo para escanear."

    options = []
    for route in routes:
        route_id = route.get("id")
        if not route_id:
            continue

        try:
            folders = list_root_folders_for_configured_route(
                route_id,
                ruta_contains=None,
                limit=limit_per_route,
            )
        except Exception:
            folders = []

        for folder in folders:
            item = dict(folder)
            score, reasons = _qa_folder_option_score(item, ctx)
            item["score"] = score
            item["match_reasons"] = reasons
            item["config_route_id"] = route.get("id")
            item["config_route_label"] = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"
            item["config_route_relative"] = route.get("ruta_box")
            item["config_route_resolved"] = route.get("ruta_resuelta")
            item["candidate_route_strategy"] = route.get("candidate_route_strategy")
            options.append(item)

    options.sort(
        key=lambda x: (
            -int(x.get("score") or 0),
            str(x.get("config_route_label") or ""),
            str(x.get("nombre_carpeta") or ""),
        )
    )

    return {
        "expediente_id": int(expediente_id),
        "cliente_id": ctx.get("cliente_id"),
        "cliente_nombre": " ".join([
            ctx.get("cliente_nombre") or "",
            ctx.get("cliente_primer_apellido") or "",
            ctx.get("cliente_segundo_apellido") or "",
        ]).strip(),
        "tipo_expediente_id": ctx.get("tipo_expediente_id"),
        "tipo_expediente_nombre": ctx.get("tipo_expediente_nombre"),
        "routes": routes,
        "options": options,
        "total_options": len(options),
        "force_scan": bool(force_scan),
        "scanned_route_ids": scanned_route_ids,
        "scan_error": scan_error,
    }

# === QUESADA BOX FOLDER OPTIONS EXPEDIENTE V6 END ===


# === QUESADA BOX LINK EXPEDIENTE OVERRIDE START ===

def get_expedientes_for_box_link():
    """
    Expedientes activos para vincular carpeta Box.
    No modifica nada.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                e.id,
                e.numero_expediente,
                e.cliente_id,
                e.tipo_expediente_id,
                e.box_folder_path,
                c.nombre AS cliente_nombre,
                c.primer_apellido AS cliente_primer_apellido,
                c.segundo_apellido AS cliente_segundo_apellido,
                c.nie AS cliente_nie,
                c.pasaporte AS cliente_pasaporte,
                te.nombre AS tipo_expediente_nombre
            FROM expedientes e
            JOIN clientes c ON c.id = e.cliente_id
            LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
            WHERE COALESCE(e.activo, 1) = 1
            ORDER BY e.created_at DESC, e.id DESC
            """
        ).fetchall()

    result = []
    for row in rows:
        item = _dict(row)
        nombre = " ".join([
            item.get("cliente_nombre") or "",
            item.get("cliente_primer_apellido") or "",
            item.get("cliente_segundo_apellido") or "",
        ]).strip()
        documento = item.get("cliente_nie") or item.get("cliente_pasaporte") or ""
        tipo = item.get("tipo_expediente_nombre") or "EXPEDIENTE"
        numero = item.get("numero_expediente") or f"EXP-{item.get('id')}"
        item["display"] = f"{item['id']} - {numero} · {nombre} · {tipo}" + (f" · {documento}" if documento else "")
        result.append(item)

    return result


def get_expediente_for_box_link(expediente_id):
    expediente_id = int(expediente_id)
    for item in get_expedientes_for_box_link():
        if int(item["id"]) == expediente_id:
            return item
    return None


def link_box_folder_to_expediente(folder_path, expediente_id):
    """
    Vincula una carpeta Box observada a un expediente existente.

    Seguridad:
    - No toca Box.
    - No mueve archivos.
    - No renombra archivos.
    - Solo actualiza SQLite.
    """
    ensure_box_watch_runtime_columns()

    ruta = str(folder_path or "").strip()
    if not ruta:
        raise ValueError("No hay carpeta Box seleccionada")

    expediente = get_expediente_for_box_link(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    cliente_id = int(expediente["cliente_id"])
    expediente_id = int(expediente["id"])

    with _connect() as conn:
        conn.execute(
            """
            UPDATE box_watch_folders
            SET expediente_id = ?,
                cliente_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE REPLACE(ruta, '\\', '/') = REPLACE(?, '\\', '/')
               OR REPLACE(ruta, '\\', '/') LIKE REPLACE(?, '\\', '/') || '/%'
            """,
            (expediente_id, cliente_id, ruta, ruta),
        )

        conn.execute(
            """
            UPDATE box_watch_items
            SET expediente_id = ?,
                cliente_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE REPLACE(ruta, '\\', '/') = REPLACE(?, '\\', '/')
               OR REPLACE(ruta, '\\', '/') LIKE REPLACE(?, '\\', '/') || '/%'
            """,
            (expediente_id, cliente_id, ruta, ruta),
        )

        conn.execute(
            """
            UPDATE expedientes
            SET box_folder_path = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (ruta, expediente_id),
        )

        conn.commit()

    return {
        "expediente_id": expediente_id,
        "cliente_id": cliente_id,
        "ruta": ruta,
        "display": expediente.get("display"),
    }


def open_folder_in_explorer(folder_path):
    """
    Abre una carpeta en el explorador del sistema.
    No modifica Box.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    path = Path(str(folder_path or "").strip())
    if not path.exists():
        raise FileNotFoundError(f"No existe la carpeta: {path}")

    if sys.platform.startswith("win"):
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])

    return True

# === QUESADA BOX LINK EXPEDIENTE OVERRIDE END ===

# === QUESADA BOX ROOT CHECK OVERRIDE START ===

def is_box_root_client_folder(folder_path):
    """
    Comprueba si folder_path es carpeta principal de alguna ruta Box configurada.
    No toca Box.
    """
    target = str(folder_path or "").replace("\\", "/").rstrip("/")
    if not target:
        return False

    routes = get_configured_box_routes(active_only=True)
    for route in routes:
        base = str(route.get("ruta_resuelta") or "").replace("\\", "/").rstrip("/")
        prefix = base + "/"
        if not target.startswith(prefix):
            continue
        relative = target[len(prefix):]
        if relative and "/" not in relative:
            return True
    return False

# === QUESADA BOX ROOT CHECK OVERRIDE END ===



# === QUESADA DOCUMENT ROOT MODEL START ===

def get_document_route_label(folder):
    """
    Construye la etiqueta documental desde la ruta configurada.
    """
    folder = folder or {}

    ruta_relativa = str(folder.get("ruta_relativa") or "").replace("\\", "/").strip("/")
    if ruta_relativa:
        parts = [p.strip() for p in ruta_relativa.split("/") if p.strip()]
        if parts and parts[0].upper() == "BOX":
            parts = parts[1:]
        return " > ".join(parts)

    ruta = str(folder.get("ruta") or "").replace("\\", "/")
    return ruta

# === QUESADA DOCUMENT ROOT MODEL END ===

# === QUESADA BOX SQL PAGINATION OPTIMIZATION START ===

def _qa_sql_order_clause(sort_by="Última actividad", sort_dir="Descendente"):
    """
    Orden seguro para listados raíz. No interpola valores libres.
    """
    reverse = str(sort_dir or "Descendente") == "Descendente"
    direction = "DESC" if reverse else "ASC"
    mapping = {
        "Cliente": f"f.nombre_carpeta COLLATE NOCASE {direction}, f.id ASC",
        "Año": f"COALESCE(f.config_route_relative, '') COLLATE NOCASE {direction}, f.nombre_carpeta COLLATE NOCASE ASC",
        "Trámite": f"COALESCE(f.tipo_detectado, '') COLLATE NOCASE {direction}, f.nombre_carpeta COLLATE NOCASE ASC",
        "Última actividad": f"COALESCE(f.fecha_ultima_actividad, '') {direction}, f.nombre_carpeta COLLATE NOCASE ASC",
        "Último escaneo": f"COALESCE(f.updated_at, '') {direction}, f.nombre_carpeta COLLATE NOCASE ASC",
        "Archivos": f"COALESCE(f.total_archivos, 0) {direction}, f.nombre_carpeta COLLATE NOCASE ASC",
        "Subcarpetas": f"COALESCE(f.total_subcarpetas, 0) {direction}, f.nombre_carpeta COLLATE NOCASE ASC",
    }
    return mapping.get(sort_by or "Última actividad", mapping["Última actividad"])


def ensure_box_watch_fast_columns():
    """
    Columnas/índices de rendimiento para carga paginada.
    No toca Box. Solo SQLite.
    """
    ensure_box_watch_runtime_columns()
    with _connect() as conn:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(box_watch_folders)").fetchall()}
        if "ruta_norm" not in existing:
            conn.execute("ALTER TABLE box_watch_folders ADD COLUMN ruta_norm TEXT")
        if "config_route_relative" not in existing:
            conn.execute("ALTER TABLE box_watch_folders ADD COLUMN config_route_relative TEXT")
        if "config_route_id" not in existing:
            conn.execute("ALTER TABLE box_watch_folders ADD COLUMN config_route_id INTEGER")

        conn.execute("UPDATE box_watch_folders SET ruta_norm = REPLACE(ruta, '\\\\', '/') WHERE ruta_norm IS NULL OR ruta_norm = ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_box_watch_folders_fast_active_norm ON box_watch_folders(activo, ruta_norm)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_box_watch_folders_fast_activity ON box_watch_folders(activo, fecha_ultima_actividad)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_box_watch_folders_fast_name ON box_watch_folders(activo, nombre_carpeta)")
        conn.commit()


def _qa_root_where_for_base(base_path, ruta_contains=None):
    base_norm = _qa_norm_path(base_path)
    prefix = base_norm + "/"
    where = [
        "COALESCE(f.activo, 1) = 1",
        "COALESCE(f.ruta_norm, REPLACE(f.ruta, '\\\\', '/')) LIKE ?",
        "INSTR(SUBSTR(COALESCE(f.ruta_norm, REPLACE(f.ruta, '\\\\', '/')), LENGTH(?) + 2), '/') = 0",
    ]
    params = [prefix + "%", base_norm]
    if ruta_contains:
        text = f"%{str(ruta_contains).lower().strip()}%"
        where.append("(LOWER(f.nombre_carpeta) LIKE ? OR LOWER(COALESCE(f.ruta_norm, f.ruta)) LIKE ?)")
        params.extend([text, text])
    return " AND ".join(where), params


def list_root_folders_sql_page_for_route_id(route_id, ruta_contains=None, page=1, page_size=100, sort_by="Última actividad", sort_dir="Descendente"):
    """
    Carga una página SQL real de carpetas raíz de una ruta.
    Evita:
    - SELECT * masivo
    - filtrado Python de todas las carpetas
    - totales recursivos N+1
    - last_scan N+1
    """
    ensure_box_watch_fast_columns()
    route = get_configured_box_route(route_id)
    if not route:
        return {"rows": [], "total": 0, "page": 1, "page_size": int(page_size or 100)}

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 100), 500))
    offset = (page - 1) * page_size
    where_sql, params = _qa_root_where_for_base(route.get("ruta_resuelta"), ruta_contains=ruta_contains)
    order_sql = _qa_sql_order_clause(sort_by, sort_dir)

    with _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM box_watch_folders f WHERE {where_sql}", params).fetchone()["n"]
        rows = conn.execute(
            f"""
            SELECT
                f.*,
                c.nombre AS cliente_nombre,
                c.primer_apellido AS cliente_primer_apellido,
                c.segundo_apellido AS cliente_segundo_apellido,
                e.numero_expediente AS numero_expediente,
                e.id AS expediente_id,
                f.cliente_id AS cliente_id,
                ? AS config_route_id,
                ? AS config_route_label,
                ? AS config_route_relative,
                ? AS config_route_resolved,
                (
                    SELECT COALESCE(sr.fecha_fin, sr.fecha_inicio, sr.created_at)
                    FROM box_watch_scan_runs sr
                    WHERE sr.estado = 'OK'
                      AND (? = REPLACE(sr.ruta_base, '\\\\', '/') OR ? LIKE REPLACE(sr.ruta_base, '\\\\', '/') || '/%')
                    ORDER BY sr.id DESC
                    LIMIT 1
                ) AS last_scan
            FROM box_watch_folders f
            LEFT JOIN clientes c ON c.id = f.cliente_id
            LEFT JOIN expedientes e ON e.id = f.expediente_id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            [
                route.get("id"),
                f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}",
                route.get("ruta_box"),
                route.get("ruta_resuelta"),
                _qa_norm_path(route.get("ruta_resuelta")),
                _qa_norm_path(route.get("ruta_resuelta")),
            ] + params + [page_size, offset],
        ).fetchall()

    result = []
    for row in rows:
        item = _dict(row)
        item["ultimo_escaneo"] = item.get("last_scan")
        item["total_archivos_directos"] = int(item.get("total_archivos") or 0)
        item["total_subcarpetas_directas"] = int(item.get("total_subcarpetas") or 0)
        # En tabla principal, los recursivos se igualan a directos para evitar N+1.
        # Los recursivos profundos se consultan bajo demanda en inspección/exportación.
        item["total_archivos_recursivos"] = int(item.get("total_archivos") or 0)
        item["total_subcarpetas_recursivas"] = int(item.get("total_subcarpetas") or 0)
        result.append(item)

    return {"rows": result, "total": int(total or 0), "page": page, "page_size": page_size}


def _qa_all_order_clause(sort_by="Última actividad", sort_dir="Descendente"):
    direction = "DESC" if str(sort_dir or "Descendente") == "Descendente" else "ASC"
    mapping = {
        "Cliente": f"nombre_carpeta COLLATE NOCASE {direction}, config_route_relative COLLATE NOCASE ASC",
        "Año": f"config_route_relative COLLATE NOCASE {direction}, nombre_carpeta COLLATE NOCASE ASC",
        "Trámite": f"COALESCE(tipo_detectado, '') COLLATE NOCASE {direction}, nombre_carpeta COLLATE NOCASE ASC",
        "Última actividad": f"COALESCE(fecha_ultima_actividad, '') {direction}, nombre_carpeta COLLATE NOCASE ASC",
        "Último escaneo": f"COALESCE(updated_at, '') {direction}, nombre_carpeta COLLATE NOCASE ASC",
        "Archivos": f"COALESCE(total_archivos, 0) {direction}, nombre_carpeta COLLATE NOCASE ASC",
        "Subcarpetas": f"COALESCE(total_subcarpetas, 0) {direction}, nombre_carpeta COLLATE NOCASE ASC",
    }
    return mapping.get(sort_by or "Última actividad", mapping["Última actividad"])


def list_root_folders_sql_page_for_all_routes(ruta_contains=None, page=1, page_size=100, sort_by="Última actividad", sort_dir="Descendente"):
    """
    Página SQL real para TODAS las rutas activas mediante UNION ALL.
    No carga 10k en memoria: SQLite aplica ORDER/LIMIT/OFFSET.
    """
    ensure_box_watch_fast_columns()
    routes = get_configured_box_routes(active_only=True)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 100), 500))
    offset = (page - 1) * page_size
    if not routes:
        return {"rows": [], "total": 0, "page": page, "page_size": page_size}

    selects = []
    params = []
    count_selects = []
    count_params = []
    for route in routes:
        where_sql, where_params = _qa_root_where_for_base(route.get("ruta_resuelta"), ruta_contains=ruta_contains)
        label = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"
        selects.append(
            f"""
            SELECT
                f.*,
                c.nombre AS cliente_nombre,
                c.primer_apellido AS cliente_primer_apellido,
                c.segundo_apellido AS cliente_segundo_apellido,
                e.numero_expediente AS numero_expediente,
                e.id AS expediente_id,
                f.cliente_id AS cliente_id,
                ? AS config_route_id,
                ? AS config_route_label,
                ? AS config_route_relative,
                ? AS config_route_resolved,
                (
                    SELECT COALESCE(sr.fecha_fin, sr.fecha_inicio, sr.created_at)
                    FROM box_watch_scan_runs sr
                    WHERE sr.estado = 'OK'
                      AND (? = REPLACE(sr.ruta_base, '\\', '/') OR ? LIKE REPLACE(sr.ruta_base, '\\', '/') || '/%')
                    ORDER BY sr.id DESC
                    LIMIT 1
                ) AS last_scan
            FROM box_watch_folders f
            LEFT JOIN clientes c ON c.id = f.cliente_id
            LEFT JOIN expedientes e ON e.id = f.expediente_id
            WHERE {where_sql}
            """
        )
        params.extend([
            route.get("id"),
            label,
            route.get("ruta_box"),
            route.get("ruta_resuelta"),
            _qa_norm_path(route.get("ruta_resuelta")),
            _qa_norm_path(route.get("ruta_resuelta")),
        ] + where_params)
        count_selects.append(f"SELECT f.id FROM box_watch_folders f WHERE {where_sql}")
        count_params.extend(where_params)

    union_sql = " UNION ALL ".join(selects)
    count_union = " UNION ALL ".join(count_selects)
    order_sql = _qa_all_order_clause(sort_by, sort_dir)

    with _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM ({count_union}) q", count_params).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM ({union_sql}) q ORDER BY {order_sql} LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

    result = []
    for row in rows:
        item = _dict(row)
        item["ultimo_escaneo"] = item.get("last_scan")
        item["total_archivos_directos"] = int(item.get("total_archivos") or 0)
        item["total_subcarpetas_directas"] = int(item.get("total_subcarpetas") or 0)
        item["total_archivos_recursivos"] = int(item.get("total_archivos") or 0)
        item["total_subcarpetas_recursivas"] = int(item.get("total_subcarpetas") or 0)
        result.append(item)

    return {"rows": result, "total": int(total or 0), "page": page, "page_size": page_size}


# Compatibilidad: las funciones antiguas ahora delegan en SQL page y devuelven solo filas.
def list_root_folders_python_fallback_for_route_id(route_id, ruta_contains=None, limit=500):
    data = list_root_folders_sql_page_for_route_id(route_id, ruta_contains=ruta_contains, page=1, page_size=limit)
    return data.get("rows") or []


def list_root_folders_python_fallback_for_all_routes(ruta_contains=None, limit_per_route=500):
    data = list_root_folders_sql_page_for_all_routes(ruta_contains=ruta_contains, page=1, page_size=limit_per_route)
    return data.get("rows") or []

# === QUESADA BOX SQL PAGINATION OPTIMIZATION END ===

# === QUESADA BOX SQL PAGINATION FIX V2 START ===
# Motivo: la primera versión SQL podía devolver 0 carpetas en Windows si SQLite no
# normalizaba bien las barras invertidas. Usamos char(92), que es '\\' en SQLite,
# y añadimos fallback por ruta relativa guardada en Configuración.


def _qa_sql_norm_expr(column="f.ruta"):
    return f"REPLACE({column}, char(92), '/')"


def ensure_box_watch_fast_columns():
    """
    Columnas e índices ligeros para carga rápida.
    No toca Box. Solo SQLite.
    """
    ensure_box_watch_runtime_columns()
    with _connect() as conn:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(box_watch_folders)").fetchall()}
        if "ruta_norm" not in existing:
            conn.execute("ALTER TABLE box_watch_folders ADD COLUMN ruta_norm TEXT")
        if "config_route_relative" not in existing:
            conn.execute("ALTER TABLE box_watch_folders ADD COLUMN config_route_relative TEXT")
        if "config_route_id" not in existing:
            conn.execute("ALTER TABLE box_watch_folders ADD COLUMN config_route_id INTEGER")

        conn.execute("UPDATE box_watch_folders SET ruta_norm = REPLACE(ruta, char(92), '/') WHERE ruta_norm IS NULL OR ruta_norm = ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_box_watch_folders_fast_active_norm ON box_watch_folders(activo, ruta_norm)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_box_watch_folders_fast_activity ON box_watch_folders(activo, fecha_ultima_actividad)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_box_watch_folders_fast_name ON box_watch_folders(activo, nombre_carpeta)")
        conn.commit()


def _qa_root_where_for_base(base_path, ruta_contains=None):
    base_norm = _qa_norm_path(base_path)
    prefix = base_norm + "/"
    norm = "COALESCE(f.ruta_norm, REPLACE(f.ruta, char(92), '/'))"
    where = [
        "COALESCE(f.activo, 1) = 1",
        f"{norm} LIKE ?",
        f"INSTR(SUBSTR({norm}, LENGTH(?) + 2), '/') = 0",
    ]
    params = [prefix + "%", base_norm]
    if ruta_contains:
        text = f"%{str(ruta_contains).lower().strip()}%"
        where.append(f"(LOWER(f.nombre_carpeta) LIKE ? OR LOWER({norm}) LIKE ?)")
        params.extend([text, text])
    return " AND ".join(where), params


def _qa_root_where_for_relative_token(relative_path, ruta_contains=None):
    """
    Fallback cuando la ruta absoluta resuelta no coincide con la ruta guardada en DB.
    Ejemplo: DB con C:/Users/Otro/Box/NACIONALIDADES/2019 y config actual Box/NACIONALIDADES/2019.
    """
    token = str(relative_path or "").replace("\\", "/").strip("/")
    norm = "COALESCE(f.ruta_norm, REPLACE(f.ruta, char(92), '/'))"
    if not token:
        return None, []

    where = [
        "COALESCE(f.activo, 1) = 1",
        f"{norm} LIKE ?",
        f"INSTR({norm}, ?) > 0",
        # Parte posterior al token + '/'. Si contiene otra '/', no es carpeta raíz de cliente.
        f"INSTR(SUBSTR({norm}, INSTR({norm}, ?) + LENGTH(?) + 1), '/') = 0",
    ]
    params = ["%" + token + "/%", token, token, token]
    if ruta_contains:
        text = f"%{str(ruta_contains).lower().strip()}%"
        where.append(f"(LOWER(f.nombre_carpeta) LIKE ? OR LOWER({norm}) LIKE ?)")
        params.extend([text, text])
    return " AND ".join(where), params


def _qa_folder_select_sql(where_sql, order_sql):
    return f"""
        SELECT
            f.*,
            c.nombre AS cliente_nombre,
            c.primer_apellido AS cliente_primer_apellido,
            c.segundo_apellido AS cliente_segundo_apellido,
            e.numero_expediente AS numero_expediente,
            e.id AS expediente_id,
            f.cliente_id AS cliente_id,
            ? AS config_route_id,
            ? AS config_route_label,
            ? AS config_route_relative,
            ? AS config_route_resolved,
            (
                SELECT COALESCE(sr.fecha_fin, sr.fecha_inicio, sr.created_at)
                FROM box_watch_scan_runs sr
                WHERE sr.estado = 'OK'
                  AND (? = REPLACE(sr.ruta_base, char(92), '/') OR ? LIKE REPLACE(sr.ruta_base, char(92), '/') || '/%')
                ORDER BY sr.id DESC
                LIMIT 1
            ) AS last_scan
        FROM box_watch_folders f
        LEFT JOIN clientes c ON c.id = f.cliente_id
        LEFT JOIN expedientes e ON e.id = f.expediente_id
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """


def _qa_format_root_rows(rows):
    result = []
    for row in rows or []:
        item = _dict(row)
        item["ultimo_escaneo"] = item.get("last_scan")
        item["total_archivos_directos"] = int(item.get("total_archivos") or 0)
        item["total_subcarpetas_directas"] = int(item.get("total_subcarpetas") or 0)
        # En tabla principal evitamos recursivos N+1. Profundidad solo bajo demanda.
        item["total_archivos_recursivos"] = int(item.get("total_archivos") or 0)
        item["total_subcarpetas_recursivas"] = int(item.get("total_subcarpetas") or 0)
        result.append(item)
    return result


def _qa_query_route_page(route, where_sql, params, page, page_size, sort_by, sort_dir):
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 100), 500))
    offset = (page - 1) * page_size
    order_sql = _qa_sql_order_clause(sort_by, sort_dir)
    label = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"
    base_norm = _qa_norm_path(route.get("ruta_resuelta"))

    with _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM box_watch_folders f WHERE {where_sql}", params).fetchone()["n"]
        rows = conn.execute(
            _qa_folder_select_sql(where_sql, order_sql),
            [
                route.get("id"),
                label,
                route.get("ruta_box"),
                route.get("ruta_resuelta"),
                base_norm,
                base_norm,
            ] + params + [page_size, offset],
        ).fetchall()

    return {
        "rows": _qa_format_root_rows(rows),
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


def list_root_folders_sql_page_for_route_id(route_id, ruta_contains=None, page=1, page_size=100, sort_by="Última actividad", sort_dir="Descendente"):
    """
    Carga rápida paginada para una ruta.
    1) intenta ruta absoluta normalizada con char(92)
    2) si no encuentra nada, fallback por ruta relativa Box/... para no dejar la vista vacía
    """
    ensure_box_watch_fast_columns()
    route = get_configured_box_route(route_id)
    if not route:
        return {"rows": [], "total": 0, "page": 1, "page_size": int(page_size or 100)}

    where_sql, params = _qa_root_where_for_base(route.get("ruta_resuelta"), ruta_contains=ruta_contains)
    data = _qa_query_route_page(route, where_sql, params, page, page_size, sort_by, sort_dir)
    if data.get("total", 0) > 0 or ruta_contains:
        return data

    # Fallback solo cuando la carga vacía sería sospechosa.
    loose_where, loose_params = _qa_root_where_for_relative_token(route.get("ruta_box"), ruta_contains=ruta_contains)
    if not loose_where:
        return data
    loose = _qa_query_route_page(route, loose_where, loose_params, page, page_size, sort_by, sort_dir)
    return loose if loose.get("total", 0) > 0 else data


def list_root_folders_sql_page_for_all_routes(ruta_contains=None, page=1, page_size=100, sort_by="Última actividad", sort_dir="Descendente"):
    """
    TODAS las rutas activas. Para máxima compatibilidad evita UNION complejo si hay
    rutas con path absoluto distinto: recoge páginas candidatas por ruta y pagina en Python
    sobre las carpetas raíz ya filtradas por SQL. Sigue evitando recursivos N+1.
    """
    ensure_box_watch_fast_columns()
    routes = get_configured_box_routes(active_only=True)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 100), 500))
    if not routes:
        return {"rows": [], "total": 0, "page": page, "page_size": page_size}

    # Para una sola ruta usamos la ruta rápida pura.
    if len(routes) == 1:
        return list_root_folders_sql_page_for_route_id(
            routes[0].get("id"),
            ruta_contains=ruta_contains,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    # Compatibilidad: pedimos todas las raíces de cada ruta sin recursivos y paginamos global.
    # Normalmente el número de carpetas raíz es mucho menor que todo el inventario profundo.
    collected = []
    total = 0
    for route in routes:
        # Límite alto por ruta para ordenar globalmente sin tocar subcarpetas.
        data = list_root_folders_sql_page_for_route_id(
            route.get("id"),
            ruta_contains=ruta_contains,
            page=1,
            page_size=10000,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        rows = data.get("rows") or []
        collected.extend(rows)
        total += int(data.get("total") or len(rows))

    reverse = str(sort_dir or "Descendente") == "Descendente"
    try:
        collected = sorted(collected, key=lambda r: _sort_key_for_folder(r, sort_by), reverse=reverse)
    except Exception:
        pass

    start = (page - 1) * page_size
    end = start + page_size
    return {"rows": collected[start:end], "total": len(collected), "page": page, "page_size": page_size}


# Compatibilidad: las funciones antiguas ahora devuelven filas desde la ruta SQL corregida.
def list_root_folders_python_fallback_for_route_id(route_id, ruta_contains=None, limit=500):
    data = list_root_folders_sql_page_for_route_id(route_id, ruta_contains=ruta_contains, page=1, page_size=limit)
    return data.get("rows") or []


def list_root_folders_python_fallback_for_all_routes(ruta_contains=None, limit_per_route=500):
    data = list_root_folders_sql_page_for_all_routes(ruta_contains=ruta_contains, page=1, page_size=limit_per_route)
    return data.get("rows") or []

# === QUESADA BOX SQL PAGINATION FIX V2 END ===

# === QUESADA BOX SQL PAGINATION FIX V3 ROBUST FALLBACK START ===


def _qa_root_candidates_for_route(route):
    """
    Candidatos de comparación para rutas reales guardadas en SQLite.
    Motivo: según el escaneo, la tabla puede tener rutas absolutas Windows,
    rutas normalizadas con '/', o incluso rutas relativas tipo Box/...
    """
    candidates = []
    for value in (
        (route or {}).get("ruta_resuelta"),
        (route or {}).get("ruta_box"),
    ):
        norm = _qa_norm_path(value)
        if norm and norm not in candidates:
            candidates.append(norm)

        # Si es absoluta y contiene /Box/, añadimos también desde Box/...
        marker = "/Box/"
        if marker in norm:
            rel = "Box/" + norm.split(marker, 1)[1]
            if rel and rel not in candidates:
                candidates.append(rel)

    return candidates


def _qa_is_direct_child_of_any_base(ruta, candidates):
    ruta = _qa_norm_path(ruta)
    if not ruta:
        return False

    for base in candidates or []:
        base = _qa_norm_path(base)
        if not base:
            continue

        prefix = base + "/"
        if ruta.startswith(prefix):
            relative = ruta[len(prefix):].strip("/")
            return bool(relative) and "/" not in relative

        # Fallback interno: buscar token Box/... dentro de una ruta absoluta.
        # Ejemplo ruta SQLite: C:/Users/Nacho/Box/NACIONALIDADES/2019/CLIENTE
        # base config: Box/NACIONALIDADES/2019
        if base.startswith("Box/"):
            token = "/" + base + "/"
            idx = ruta.find(token)
            if idx >= 0:
                relative = ruta[idx + len(token):].strip("/")
                return bool(relative) and "/" not in relative

    return False


def _qa_fast_last_scan_by_route_base(route):
    """
    Una sola consulta por ruta. Evita last_scan N+1.
    """
    try:
        base = _qa_norm_path((route or {}).get("ruta_resuelta"))
        if not base:
            return None
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT fecha_fin, fecha_inicio, created_at
                FROM box_watch_scan_runs
                WHERE (
                    ? = REPLACE(ruta_base, char(92), '/')
                    OR ? LIKE REPLACE(ruta_base, char(92), '/') || '/%'
                    OR REPLACE(ruta_base, char(92), '/') LIKE ? || '/%'
                )
                ORDER BY id DESC
                LIMIT 1
                """,
                (base, base, base),
            ).fetchone()
        if not row:
            return None
        d = _dict(row)
        return d.get("fecha_fin") or d.get("fecha_inicio") or d.get("created_at")
    except Exception:
        return None


def _qa_lightweight_root_rows_python(route, ruta_contains=None, sort_by="Última actividad", sort_dir="Descendente"):
    """
    Fallback robusto pero ligero:
    - lee carpetas una vez desde SQLite
    - NO calcula recursivos
    - NO llama last_scan por carpeta
    - detecta raíz con Python normalizado
    Esto recupera la compatibilidad sin volver al N+1 lento.
    """
    ensure_box_watch_fast_columns()
    candidates = _qa_root_candidates_for_route(route)
    text = str(ruta_contains or "").lower().strip()
    label = f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}"
    last_scan = _qa_fast_last_scan_by_route_base(route)

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
        ruta = _qa_norm_path(folder.get("ruta"))
        if not _qa_is_direct_child_of_any_base(ruta, candidates):
            continue

        if text:
            haystack = " ".join([
                str(folder.get("nombre_carpeta") or ""),
                str(folder.get("ruta") or ""),
                str(folder.get("tipo_detectado") or ""),
            ]).lower()
            if text not in haystack:
                continue

        folder["config_route_id"] = route.get("id")
        folder["config_route_label"] = label
        folder["config_route_relative"] = route.get("ruta_box")
        folder["config_route_resolved"] = route.get("ruta_resuelta")
        folder["last_scan"] = last_scan
        folder["ultimo_escaneo"] = last_scan

        # Tabla principal: directos. Los recursivos profundos se calculan bajo demanda.
        folder["total_archivos_directos"] = int(folder.get("total_archivos") or 0)
        folder["total_subcarpetas_directas"] = int(folder.get("total_subcarpetas") or 0)
        folder["total_archivos_recursivos"] = int(folder.get("total_archivos") or 0)
        folder["total_subcarpetas_recursivas"] = int(folder.get("total_subcarpetas") or 0)
        result.append(folder)

    reverse = str(sort_dir or "Descendente") == "Descendente"
    try:
        result = sorted(result, key=lambda r: _sort_key_for_folder(r, sort_by), reverse=reverse)
    except Exception:
        pass
    return result


def list_root_folders_sql_page_for_route_id(route_id, ruta_contains=None, page=1, page_size=100, sort_by="Última actividad", sort_dir="Descendente"):
    """
    V3: SQL rápido + fallback robusto ligero.
    Si el SQL no encuentra carpetas por diferencias de ruta, no devuelve vacío:
    usa detección Python normalizada SIN recursivos N+1.
    """
    ensure_box_watch_fast_columns()
    route = get_configured_box_route(route_id)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 100), 500))
    if not route:
        return {"rows": [], "total": 0, "page": page, "page_size": page_size}

    # 1) Intento SQL optimizado.
    try:
        where_sql, params = _qa_root_where_for_base(route.get("ruta_resuelta"), ruta_contains=ruta_contains)
        data = _qa_query_route_page(route, where_sql, params, page, page_size, sort_by, sort_dir)
        if int(data.get("total") or 0) > 0:
            return data

        loose_where, loose_params = _qa_root_where_for_relative_token(route.get("ruta_box"), ruta_contains=ruta_contains)
        if loose_where:
            loose = _qa_query_route_page(route, loose_where, loose_params, page, page_size, sort_by, sort_dir)
            if int(loose.get("total") or 0) > 0:
                return loose
    except Exception:
        pass

    # 2) Fallback compatible y ligero.
    rows = _qa_lightweight_root_rows_python(route, ruta_contains=ruta_contains, sort_by=sort_by, sort_dir=sort_dir)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "rows": rows[start:end],
        "total": len(rows),
        "page": page,
        "page_size": page_size,
        "mode": "python_light_fallback",
    }


def list_root_folders_sql_page_for_all_routes(ruta_contains=None, page=1, page_size=100, sort_by="Última actividad", sort_dir="Descendente"):
    ensure_box_watch_fast_columns()
    routes = get_configured_box_routes(active_only=True)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 100), 500))
    if not routes:
        return {"rows": [], "total": 0, "page": page, "page_size": page_size}

    collected = []
    for route in routes:
        rows = _qa_lightweight_root_rows_python(route, ruta_contains=ruta_contains, sort_by=sort_by, sort_dir=sort_dir)
        collected.extend(rows)

    reverse = str(sort_dir or "Descendente") == "Descendente"
    try:
        collected = sorted(collected, key=lambda r: _sort_key_for_folder(r, sort_by), reverse=reverse)
    except Exception:
        pass

    start = (page - 1) * page_size
    end = start + page_size
    return {"rows": collected[start:end], "total": len(collected), "page": page, "page_size": page_size}


def debug_box_watch_route_loading(route_id=None):
    """
    Diagnóstico para ver qué rutas hay realmente en SQLite.
    Se puede llamar desde consola Python si vuelve a fallar.
    """
    ensure_box_watch_fast_columns()
    routes = get_configured_box_routes(active_only=True)
    if route_id:
        routes = [r for r in routes if int(r.get("id")) == int(route_id)]

    with _connect() as conn:
        total_folders = conn.execute(
            "SELECT COUNT(*) AS n FROM box_watch_folders WHERE COALESCE(activo, 1) = 1"
        ).fetchone()["n"]
        samples = [
            _dict(r) for r in conn.execute(
                """
                SELECT id, ruta, nombre_carpeta, nivel
                FROM box_watch_folders
                WHERE COALESCE(activo, 1) = 1
                ORDER BY id ASC
                LIMIT 20
                """
            ).fetchall()
        ]

    route_info = []
    for route in routes:
        rows = _qa_lightweight_root_rows_python(route, page_size if False else None)
        route_info.append({
            "id": route.get("id"),
            "ruta_box": route.get("ruta_box"),
            "ruta_resuelta": route.get("ruta_resuelta"),
            "ruta_existe": route.get("ruta_existe"),
            "candidates": _qa_root_candidates_for_route(route),
            "root_detected": len(rows),
            "first_roots": [r.get("ruta") for r in rows[:5]],
        })

    return {"total_folders": total_folders, "routes": route_info, "samples": samples}


# Compatibilidad funciones antiguas.
def list_root_folders_python_fallback_for_route_id(route_id, ruta_contains=None, limit=500):
    data = list_root_folders_sql_page_for_route_id(route_id, ruta_contains=ruta_contains, page=1, page_size=limit)
    return data.get("rows") or []


def list_root_folders_python_fallback_for_all_routes(ruta_contains=None, limit_per_route=500):
    data = list_root_folders_sql_page_for_all_routes(ruta_contains=ruta_contains, page=1, page_size=limit_per_route)
    return data.get("rows") or []

# === QUESADA BOX SQL PAGINATION FIX V3 ROBUST FALLBACK END ===

# === QUESADA BOX INCREMENTAL SCAN OVERRIDE START ===


def _qa_load_expedient_links(conn):
    """
    Carga vínculos expediente -> carpeta Box una sola vez por escaneo.
    Evita hacer una query por cada archivo/carpeta.
    """
    try:
        rows = conn.execute(
            """
            SELECT id AS expediente_id, cliente_id, tipo_expediente_id, box_folder_path
            FROM expedientes
            WHERE COALESCE(activo, 1) = 1
              AND box_folder_path IS NOT NULL
              AND TRIM(box_folder_path) <> ''
            """
        ).fetchall()
    except Exception:
        return []

    links = []
    for row in rows:
        folder = str(row["box_folder_path"] or "").replace("\\", "/").rstrip("/").lower()
        if not folder:
            continue
        links.append({
            "folder": folder,
            "expediente_id": row["expediente_id"],
            "cliente_id": row["cliente_id"],
            "tipo_expediente_id": row["tipo_expediente_id"],
        })
    # Primero rutas largas para que gane el vínculo más específico.
    links.sort(key=lambda item: len(item["folder"]), reverse=True)
    return links


def _qa_match_loaded_expedient(ruta, links):
    comparable = str(ruta or "").replace("\\", "/").rstrip("/").lower()
    for link in links or []:
        folder = link.get("folder") or ""
        if folder and (comparable == folder or comparable.startswith(folder + "/")):
            return {
                "expediente_id": link.get("expediente_id"),
                "cliente_id": link.get("cliente_id"),
                "tipo_expediente_id": link.get("tipo_expediente_id"),
            }
    return {"expediente_id": None, "cliente_id": None, "tipo_expediente_id": None}


def _qa_load_existing_folders(conn, base):
    base_norm = str(base).replace("\\", "/").rstrip("/")
    rows = conn.execute(
        """
        SELECT id, ruta, total_archivos, total_subcarpetas, tamano_total_bytes, fecha_ultima_actividad
        FROM box_watch_folders
        WHERE REPLACE(ruta, char(92), '/') = ?
           OR REPLACE(ruta, char(92), '/') LIKE ?
        """,
        (base_norm, base_norm + "/%"),
    ).fetchall()
    output = {}
    for row in rows:
        output[str(row["ruta"] or "")] = row
        output[str(row["ruta"] or "").replace("\\", "/").rstrip("/")] = row
    return output


def _qa_load_existing_items(conn, base):
    base_norm = str(base).replace("\\", "/").rstrip("/")
    rows = conn.execute(
        """
        SELECT id, ruta, nombre_archivo, tamano_bytes, fecha_modificacion, hash_archivo, tipo_detectado, estado
        FROM box_watch_items
        WHERE REPLACE(ruta, char(92), '/') = ?
           OR REPLACE(ruta, char(92), '/') LIKE ?
        """,
        (base_norm, base_norm + "/%"),
    ).fetchall()
    output = {}
    for row in rows:
        ruta = str(row["ruta"] or "")
        name = str(row["nombre_archivo"] or "")
        output[(ruta, name)] = row
        output[(ruta.replace("\\", "/").rstrip("/"), name)] = row
    return output


def _qa_detect_file_type_fast(file_name, extension, rules):
    tipo_detectado = detect_document_type(file_name)
    if tipo_detectado == "SIN CLASIFICAR":
        for rule in rules:
            try:
                if _matches_rule(file_name, extension, rule):
                    tipo_detectado = rule.get("codigo_documento") or tipo_detectado
                    break
            except Exception:
                continue
    return tipo_detectado


def _qa_folder_stats_fast(root, dirs, files):
    total_archivos = 0
    total_bytes = 0
    last_activity = None
    stable_files = []

    for file_name in files:
        full_path = root / file_name
        try:
            if not full_path.is_file():
                continue
            stat = full_path.stat()
        except Exception:
            continue

        total_archivos += 1
        total_bytes += int(stat.st_size or 0)
        modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        if not last_activity or modified > last_activity:
            last_activity = modified
        stable_files.append((file_name, full_path, stat, modified))

    return total_archivos, len(dirs), total_bytes, last_activity, stable_files



def _qa_mark_missing_after_scan(conn, base, run_id):
    """
    Autolimpieza segura tras escaneo incremental.

    Marca como FALTANTE/inactivo solo registros bajo la ruta escaneada que:
    - estaban activos en SQLite;
    - no han sido vistos en este escaneo;
    - y ya no existen físicamente en Box Drive.

    No borra registros.
    No modifica Box.
    Solo actualiza SQLite.
    """
    base_norm = str(base).replace("\\", "/").rstrip("/")
    if not base_norm:
        return {"folders": 0, "files": 0}

    folders = conn.execute(
        """
        SELECT id, ruta
        FROM box_watch_folders
        WHERE COALESCE(activo, 1) = 1
          AND (
                REPLACE(ruta, char(92), '/') = ?
                OR REPLACE(ruta, char(92), '/') LIKE ?
              )
          AND COALESCE(last_seen_scan_id, 0) != ?
        """,
        (base_norm, base_norm + "/%", int(run_id)),
    ).fetchall()

    missing_folder_ids = []
    for row in folders:
        ruta = str(row["ruta"] or "")
        try:
            if not Path(ruta).exists() or not Path(ruta).is_dir():
                missing_folder_ids.append(row["id"])
        except Exception:
            missing_folder_ids.append(row["id"])

    if missing_folder_ids:
        conn.executemany(
            """
            UPDATE box_watch_folders
            SET activo = 0,
                estado = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [(ESTADO_FALTANTE, folder_id) for folder_id in missing_folder_ids],
        )

    items = conn.execute(
        """
        SELECT id, ruta, nombre_archivo
        FROM box_watch_items
        WHERE COALESCE(activo, 1) = 1
          AND (
                REPLACE(ruta, char(92), '/') = ?
                OR REPLACE(ruta, char(92), '/') LIKE ?
              )
          AND COALESCE(last_seen_scan_id, 0) != ?
        """,
        (base_norm, base_norm + "/%", int(run_id)),
    ).fetchall()

    missing_item_ids = []
    for row in items:
        ruta = str(row["ruta"] or "")
        nombre = str(row["nombre_archivo"] or "")
        try:
            file_path = Path(ruta) / nombre
            if not file_path.exists() or not file_path.is_file():
                missing_item_ids.append(row["id"])
        except Exception:
            missing_item_ids.append(row["id"])

    if missing_item_ids:
        conn.executemany(
            """
            UPDATE box_watch_items
            SET activo = 0,
                estado = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [(ESTADO_FALTANTE, item_id) for item_id in missing_item_ids],
        )

    return {"folders": len(missing_folder_ids), "files": len(missing_item_ids)}

def _qa_upsert_folder_incremental(conn, existing_folders, expedient_links, base, root, dirs, files, run_id=None):
    total_archivos, total_subcarpetas, tamano_total, last_activity, stable_files = _qa_folder_stats_fast(root, dirs, files)
    rel = root.relative_to(base) if root != base else Path("")
    nivel = 0 if str(rel) in ("", ".") else len(rel.parts)
    ruta = str(root)
    ruta_norm = ruta.replace("\\", "/").rstrip("/")
    ruta_padre = str(root.parent) if root != base else ""
    nombre = root.name or str(root)
    match = _qa_match_loaded_expedient(ruta, expedient_links)

    existing = existing_folders.get(ruta) or existing_folders.get(ruta_norm)
    changed = True
    if existing:
        try:
            changed = (
                int(existing["total_archivos"] or 0) != int(total_archivos or 0)
                or int(existing["total_subcarpetas"] or 0) != int(total_subcarpetas or 0)
                or int(existing["tamano_total_bytes"] or 0) != int(tamano_total or 0)
                or str(existing["fecha_ultima_actividad"] or "") != str(last_activity or "")
            )
        except Exception:
            changed = True

        if changed:
            conn.execute(
                """
                UPDATE box_watch_folders
                SET nombre_carpeta = ?, ruta_padre = ?, nivel = ?, total_archivos = ?,
                    total_subcarpetas = ?, tamano_total_bytes = ?, fecha_ultima_actividad = ?,
                    cliente_id = COALESCE(?, cliente_id), expediente_id = COALESCE(?, expediente_id),
                    activo = 1, last_seen_scan_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    nombre,
                    ruta_padre,
                    nivel,
                    total_archivos,
                    total_subcarpetas,
                    tamano_total,
                    last_activity,
                    match.get("cliente_id"),
                    match.get("expediente_id"),
                    int(run_id or 0),
                    existing["id"],
                ),
            )
            return 0, 1, stable_files
        conn.execute(
            """
            UPDATE box_watch_folders
            SET activo = 1,
                estado = ?,
                last_seen_scan_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (ESTADO_OK, int(run_id or 0), existing["id"]),
        )
        return 0, 0, stable_files

    tipo = detect_folder_type(nombre)
    cur = conn.execute(
        """
        INSERT INTO box_watch_folders
        (ruta, nombre_carpeta, ruta_padre, nivel, total_archivos, total_subcarpetas,
         tamano_total_bytes, fecha_ultima_actividad, cliente_id, expediente_id,
         tipo_detectado, estado, observaciones, activo, last_seen_scan_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            ruta,
            nombre,
            ruta_padre,
            nivel,
            total_archivos,
            total_subcarpetas,
            tamano_total,
            last_activity,
            match.get("cliente_id"),
            match.get("expediente_id"),
            tipo,
            ESTADO_OK,
            "Carpeta detectada en escaneo incremental local",
            int(run_id or 0),
        ),
    )
    row_id = cur.lastrowid
    fake_row = {"id": row_id, "ruta": ruta, "total_archivos": total_archivos, "total_subcarpetas": total_subcarpetas, "tamano_total_bytes": tamano_total, "fecha_ultima_actividad": last_activity, "last_seen_scan_id": int(run_id or 0)}
    existing_folders[ruta] = fake_row
    existing_folders[ruta_norm] = fake_row
    return 1, 0, stable_files


def scan_local_box_path(ruta_base, progress_callback=None, calculate_hash=False):
    """
    Escaneo incremental local de Box Drive en modo SOLO LECTURA.

    Optimización aplicada:
    - elimina preconteo completo _count_tree() antes de escanear;
    - precarga archivos/carpetas existentes de SQLite una sola vez;
    - precarga vínculos de expedientes una sola vez;
    - si ruta + nombre + tamaño + fecha no cambiaron, NO reclasifica y NO actualiza;
    - commits por lotes;
    - no recalcula totales recursivos al terminar.

    Seguridad:
    - no mueve, no borra, no renombra, no escribe en Box.
    """
    initialize_box_watch_schema()
    base = _safe_path(ruta_base)
    start = _now()
    total_archivos = 0
    total_carpetas = 0
    nuevos = 0
    modificados = 0
    sin_clasificar = 0
    alertas = 0
    carpetas_nuevas = 0
    carpetas_modificadas = 0
    archivos_sin_cambios = 0
    carpetas_sin_cambios = 0
    faltantes_carpetas = 0
    faltantes_archivos = 0
    final_state = ESTADO_OK

    def report(current=""):
        if not progress_callback:
            return
        try:
            progress_callback({
                "processed": total_archivos,
                "processed_folders": total_carpetas,
                "total": 0,
                "total_folders": 0,
                "percent": 0,
                "current_file": current,
            })
        except Exception:
            pass

    report("Preparando escaneo incremental")

    with _connect() as conn:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA temp_store = MEMORY")
        except Exception:
            pass

        cur = conn.execute(
            """
            INSERT INTO box_watch_scan_runs (fecha_inicio, ruta_base, estado, observaciones)
            VALUES (?, ?, 'EN CURSO', 'Escaneo incremental local. Solo lectura. Sin preconteo y sin recursivos N+1.')
            """,
            (start, str(base)),
        )
        run_id = cur.lastrowid
        rules = _load_rules(conn)
        expedient_links = _qa_load_expedient_links(conn)
        existing_folders = _qa_load_existing_folders(conn, base)
        existing_items = _qa_load_existing_items(conn, base)

        try:
            for root, dirs, files in _iter_tree(base):
                total_carpetas += 1
                new_folder, changed_folder, stable_files = _qa_upsert_folder_incremental(
                    conn, existing_folders, expedient_links, base, root, dirs, files, run_id=run_id
                )
                carpetas_nuevas += new_folder
                carpetas_modificadas += changed_folder
                if not new_folder and not changed_folder:
                    carpetas_sin_cambios += 1

                if total_carpetas == 1 or total_carpetas % 100 == 0:
                    report(f"Carpeta: {root.name}")

                for file_name, full_path, stat, modified in stable_files:
                    total_archivos += 1
                    ruta = str(root)
                    ruta_norm = ruta.replace("\\", "/").rstrip("/")
                    existing = existing_items.get((ruta, file_name)) or existing_items.get((ruta_norm, file_name))

                    try:
                        size = int(stat.st_size or 0)
                    except Exception:
                        size = 0

                    # Punto clave: archivo idéntico => no clasificar, no alertas.
                    # Aun así marcamos last_seen_scan_id para que la autolimpieza no lo marque como FALTANTE.
                    if existing and int(existing["tamano_bytes"] or 0) == size and str(existing["fecha_modificacion"] or "") == str(modified):
                        archivos_sin_cambios += 1
                        if str(existing["estado"] or "") == ESTADO_SIN_CLASIFICAR or str(existing["tipo_detectado"] or "") == ESTADO_SIN_CLASIFICAR:
                            sin_clasificar += 1
                        conn.execute(
                            """
                            UPDATE box_watch_items
                            SET activo = 1,
                                last_seen_scan_id = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (int(run_id or 0), existing["id"]),
                        )
                        if total_archivos % 1000 == 0:
                            report(file_name)
                        continue

                    extension = full_path.suffix.lower().lstrip(".")
                    tipo_detectado = _qa_detect_file_type_fast(file_name, extension, rules)
                    match = _qa_match_loaded_expedient(ruta, expedient_links)
                    estado = ESTADO_OK if tipo_detectado != ESTADO_SIN_CLASIFICAR else ESTADO_SIN_CLASIFICAR
                    if estado == ESTADO_SIN_CLASIFICAR:
                        sin_clasificar += 1

                    hash_archivo = existing["hash_archivo"] if existing else None
                    if calculate_hash:
                        needs_hash = True
                        if existing and hash_archivo and int(existing["tamano_bytes"] or 0) == size and str(existing["fecha_modificacion"] or "") == str(modified):
                            needs_hash = False
                        if needs_hash:
                            try:
                                hash_archivo = _file_hash(full_path)
                            except Exception:
                                hash_archivo = None

                    if not existing:
                        cur_item = conn.execute(
                            """
                            INSERT INTO box_watch_items
                            (ruta, nombre_archivo, extension, tipo_detectado, cliente_id, expediente_id,
                             tamano_bytes, fecha_modificacion, hash_archivo, estado, observaciones, activo, last_seen_scan_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                            """,
                            (
                                ruta,
                                file_name,
                                extension,
                                tipo_detectado,
                                match.get("cliente_id"),
                                match.get("expediente_id"),
                                size,
                                modified,
                                hash_archivo,
                                estado,
                                "Detectado en escaneo incremental local",
                                int(run_id or 0),
                            ),
                        )
                        item_id = cur_item.lastrowid
                        existing_items[(ruta, file_name)] = {
                            "id": item_id,
                            "ruta": ruta,
                            "nombre_archivo": file_name,
                            "tamano_bytes": size,
                            "fecha_modificacion": modified,
                            "hash_archivo": hash_archivo,
                            "tipo_detectado": tipo_detectado,
                            "estado": estado,
                        }
                        existing_items[(ruta_norm, file_name)] = existing_items[(ruta, file_name)]
                        nuevos += 1
                    else:
                        item_id = existing["id"]
                        conn.execute(
                            """
                            UPDATE box_watch_items
                            SET extension = ?, tipo_detectado = ?, cliente_id = COALESCE(?, cliente_id),
                                expediente_id = COALESCE(?, expediente_id), tamano_bytes = ?,
                                fecha_modificacion = ?, hash_archivo = ?, estado = ?, activo = 1,
                                last_seen_scan_id = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                extension,
                                tipo_detectado,
                                match.get("cliente_id"),
                                match.get("expediente_id"),
                                size,
                                modified,
                                hash_archivo,
                                estado,
                                int(run_id or 0),
                                item_id,
                            ),
                        )
                        modificados += 1

                    # Solo evaluamos alertas de archivos nuevos/modificados.
                    alertas += _evaluate_item_alerts(
                        conn,
                        item_id,
                        file_name,
                        extension,
                        tipo_detectado,
                        hash_archivo,
                        match.get("expediente_id"),
                        match.get("cliente_id"),
                        rules,
                    )

                    if total_archivos % 1000 == 0:
                        conn.commit()
                        report(file_name)

                if total_carpetas % 300 == 0:
                    conn.commit()

            # Autolimpieza segura: registros activos que no reaparecen y ya no existen físicamente.
            missing_result = _qa_mark_missing_after_scan(conn, base, run_id)
            faltantes_carpetas = int(missing_result.get("folders") or 0)
            faltantes_archivos = int(missing_result.get("files") or 0)

            # No ejecutamos _evaluate_missing_required en cada escaneo incremental.
            # Es costoso y debe pasar a una revisión documental separada/profunda.
            final_state = ESTADO_OK if alertas == 0 else ESTADO_PENDIENTE
            conn.execute(
                """
                UPDATE box_watch_scan_runs
                SET fecha_fin = ?, total_archivos = ?, total_carpetas = ?, nuevos = ?, modificados = ?,
                    sin_clasificar = ?, alertas = ?, estado = ?, observaciones = ?
                WHERE id = ?
                """,
                (
                    _now(),
                    total_archivos,
                    total_carpetas,
                    nuevos,
                    modificados,
                    sin_clasificar,
                    alertas,
                    final_state,
                    (
                        "Escaneo incremental completado. "
                        f"Carpetas nuevas: {carpetas_nuevas}. "
                        f"Carpetas modificadas: {carpetas_modificadas}. "
                        f"Carpetas sin cambios: {carpetas_sin_cambios}. "
                        f"Archivos sin cambios omitidos: {archivos_sin_cambios}. "
                        f"Carpetas marcadas FALTANTE: {faltantes_carpetas}. "
                        f"Archivos marcados FALTANTE: {faltantes_archivos}. "
                        f"Hash activo: {calculate_hash}. "
                        "No modifica Box. No recalcula recursivos N+1."
                    ),
                    run_id,
                ),
            )
            conn.commit()
            report("Escaneo incremental completado")
        except Exception as exc:
            conn.execute(
                "UPDATE box_watch_scan_runs SET fecha_fin = ?, estado = ?, observaciones = ? WHERE id = ?",
                (_now(), ESTADO_ERROR, str(exc), run_id),
            )
            conn.commit()
            raise

    return {
        "run_id": run_id,
        "total_archivos": total_archivos,
        "total_carpetas": total_carpetas,
        "carpetas_nuevas": carpetas_nuevas,
        "carpetas_modificadas": carpetas_modificadas,
        "carpetas_sin_cambios": carpetas_sin_cambios,
        "faltantes_carpetas": faltantes_carpetas,
        "faltantes_archivos": faltantes_archivos,
        "nuevos": nuevos,
        "modificados": modificados,
        "archivos_sin_cambios": archivos_sin_cambios,
        "sin_clasificar": sin_clasificar,
        "alertas": alertas,
        "estado": final_state,
    }


def scan_configured_routes(route_ids=None, progress_callback=None, calculate_hash=False):
    """
    Reescanea rutas configuradas con motor incremental.
    route_ids=None => todas las rutas activas.
    """
    ensure_box_watch_runtime_columns()

    routes = get_configured_box_routes(active_only=True)
    if route_ids:
        wanted = {int(x) for x in route_ids}
        routes = [r for r in routes if int(r.get("id")) in wanted]

    results = []
    total_routes = len(routes)

    for index, route in enumerate(routes, start=1):
        resolved = route.get("ruta_resuelta")
        if not resolved:
            continue

        if progress_callback:
            progress_callback({
                "route_index": index,
                "total_routes": total_routes,
                "route_label": f"{route.get('tipo_expediente_nombre')} · {route.get('ruta_box')}",
                "current_file": f"Escaneo incremental ruta {index}/{total_routes}: {route.get('ruta_box')}",
                "processed": 0,
                "processed_folders": 0,
                "total": 0,
                "total_folders": 0,
                "percent": 0,
            })

        result = scan_local_box_path(
            resolved,
            progress_callback=progress_callback,
            calculate_hash=calculate_hash,
        )
        result["config_route_id"] = route.get("id")
        result["config_route_relative"] = route.get("ruta_box")
        result["config_route_resolved"] = resolved
        results.append(result)

    # Importante: no llamar aquí a recalculate_box_folder_counters().
    # Era otro N+1 masivo al finalizar el escaneo.
    return results



def refresh_box_folder_before_inspection(folder_path, calculate_hash=False):
    """
    Refresca una carpeta concreta antes de inspeccionarla.

    Uso previsto:
    - Inspeccionar carpeta en Box Watch.
    - Actualizar archivos/directorios de esa ruta concreta.
    - Detectar renombrados/eliminados sin escanear todo Box.

    Seguridad:
    - No modifica Box.
    - No mueve, borra ni renombra archivos.
    - Solo actualiza SQLite.
    - La autolimpieza existente marca como FALTANTE lo que ya no existe físicamente.
    """
    ensure_box_watch_runtime_columns()

    ruta = str(folder_path or "").strip()
    if not ruta:
        raise ValueError("No hay carpeta seleccionada para refrescar.")

    path = Path(ruta)
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"No existe la carpeta: {ruta}")

    return scan_local_box_path(
        ruta,
        progress_callback=None,
        calculate_hash=calculate_hash,
    )


# === QUESADA BOX INCREMENTAL SCAN OVERRIDE END ===
