import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from database.connection import get_connection
from backend.services.sqlite_runtime_service import configure_sqlite_runtime


JOB_PENDING = "PENDING"
JOB_RUNNING = "RUNNING"
JOB_DONE = "DONE"
JOB_ERROR = "ERROR"
JOB_INTERRUPTED = "INTERRUPTED"


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _repo_root():
    return Path(__file__).resolve().parents[2]


def _runner_path():
    return _repo_root() / "scripts" / "runners" / "box_watch_scan_runner.py"


def _json_dumps(value):
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value, default=None):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def ensure_job_schema():
    configure_sqlite_runtime()

    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS box_watch_scan_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estado TEXT NOT NULL DEFAULT 'PENDING',
                scope TEXT NOT NULL DEFAULT 'ALL',
                route_ids_json TEXT,
                started_at TEXT,
                finished_at TEXT,
                progress_label TEXT,
                progress_percent REAL DEFAULT 0,
                total_routes INTEGER DEFAULT 0,
                completed_routes INTEGER DEFAULT 0,
                total_archivos INTEGER DEFAULT 0,
                total_carpetas INTEGER DEFAULT 0,
                total_errores INTEGER DEFAULT 0,
                result_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_box_watch_scan_jobs_estado ON box_watch_scan_jobs(estado)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_box_watch_scan_jobs_created_at ON box_watch_scan_jobs(created_at)")
        conn.commit()
    finally:
        conn.close()


def mark_stale_running_jobs_as_interrupted():
    ensure_job_schema()
    now = _now()
    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.execute(
            """
            UPDATE box_watch_scan_jobs
            SET estado = ?,
                finished_at = COALESCE(finished_at, ?),
                updated_at = ?,
                error = COALESCE(error, 'Job interrumpido: quedó RUNNING al cerrar el proceso.')
            WHERE estado = ?
            """,
            (JOB_INTERRUPTED, now, now, JOB_RUNNING),
        )
        conn.commit()
    finally:
        conn.close()


def create_scan_job(route_ids=None, scope=None):
    ensure_job_schema()

    normalized_route_ids = None
    if route_ids:
        normalized_route_ids = [int(x) for x in route_ids]

    resolved_scope = scope or ("ROUTES" if normalized_route_ids else "ALL")
    now = _now()

    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        cur = conn.execute(
            """
            INSERT INTO box_watch_scan_jobs (
                estado, scope, route_ids_json, progress_label, progress_percent,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                JOB_PENDING,
                resolved_scope,
                _json_dumps(normalized_route_ids) if normalized_route_ids else None,
                "Pendiente de ejecución",
                0,
                now,
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_job(job_id):
    ensure_job_schema()
    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        cur = conn.execute(
            """
            SELECT id, estado, scope, route_ids_json, started_at, finished_at,
                   progress_label, progress_percent, total_routes, completed_routes,
                   total_archivos, total_carpetas, total_errores, result_json,
                   error, created_at, updated_at
            FROM box_watch_scan_jobs
            WHERE id = ?
            """,
            (int(job_id),),
        )
        row = cur.fetchone()
        if not row:
            return None

        keys = [
            "id", "estado", "scope", "route_ids_json", "started_at", "finished_at",
            "progress_label", "progress_percent", "total_routes", "completed_routes",
            "total_archivos", "total_carpetas", "total_errores", "result_json",
            "error", "created_at", "updated_at",
        ]
        data = dict(zip(keys, row))
        data["route_ids"] = _json_loads(data.get("route_ids_json"), [])
        data["result"] = _json_loads(data.get("result_json"), None)
        return data
    finally:
        conn.close()


def get_latest_job():
    ensure_job_schema()
    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        cur = conn.execute("SELECT id FROM box_watch_scan_jobs ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return get_job(row[0]) if row else None
    finally:
        conn.close()


def has_running_job():
    ensure_job_schema()
    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        cur = conn.execute(
            "SELECT id FROM box_watch_scan_jobs WHERE estado = ? ORDER BY id DESC LIMIT 1",
            (JOB_RUNNING,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def get_box_watch_runtime_diagnostic():
    """
    Diagnóstico operativo rápido para Box Watch.

    No ejecuta escaneos ni toca Box. Solo consulta SQLite para saber si
    el runtime está sano y si hay jobs/runs residuales.
    """
    configure_sqlite_runtime()

    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")

        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

        running_jobs = conn.execute(
            "SELECT COUNT(*) FROM box_watch_scan_jobs WHERE estado = ?",
            (JOB_RUNNING,),
        ).fetchone()[0]

        running_scan_runs = conn.execute(
            """
            SELECT COUNT(*)
            FROM box_watch_scan_runs
            WHERE estado IN ('EN CURSO', 'RUNNING')
            """
        ).fetchone()[0]

        latest_job = get_latest_job()

        return {
            "journal_mode": journal_mode,
            "busy_timeout": int(busy_timeout or 0),
            "running_jobs": int(running_jobs or 0),
            "running_scan_runs": int(running_scan_runs or 0),
            "latest_job_id": latest_job.get("id") if latest_job else None,
            "latest_job_estado": latest_job.get("estado") if latest_job else None,
            "ok": (
                str(journal_mode).lower() == "wal"
                and int(busy_timeout or 0) >= 60000
                and int(running_scan_runs or 0) == 0
            ),
        }
    finally:
        conn.close()


def mark_job_running(job_id, total_routes=0, label=None):
    ensure_job_schema()
    now = _now()
    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.execute(
            """
            UPDATE box_watch_scan_jobs
            SET estado = ?,
                started_at = COALESCE(started_at, ?),
                progress_label = ?,
                progress_percent = 0,
                total_routes = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                JOB_RUNNING,
                now,
                label or "Escaneo iniciado",
                int(total_routes or 0),
                now,
                int(job_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_job_progress(
    job_id,
    label=None,
    percent=None,
    completed_routes=None,
    total_routes=None,
    total_archivos=None,
    total_carpetas=None,
    total_errores=None,
):
    ensure_job_schema()
    job = get_job(job_id)
    if not job:
        return

    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.execute(
            """
            UPDATE box_watch_scan_jobs
            SET progress_label = ?,
                progress_percent = ?,
                completed_routes = ?,
                total_routes = ?,
                total_archivos = ?,
                total_carpetas = ?,
                total_errores = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                label if label is not None else job.get("progress_label"),
                float(percent if percent is not None else job.get("progress_percent") or 0),
                int(completed_routes if completed_routes is not None else job.get("completed_routes") or 0),
                int(total_routes if total_routes is not None else job.get("total_routes") or 0),
                int(total_archivos if total_archivos is not None else job.get("total_archivos") or 0),
                int(total_carpetas if total_carpetas is not None else job.get("total_carpetas") or 0),
                int(total_errores if total_errores is not None else job.get("total_errores") or 0),
                _now(),
                int(job_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def finish_job(job_id, results):
    ensure_job_schema()
    results = list(results or [])

    total_routes = len(results)
    total_archivos = sum(int(r.get("total_archivos") or 0) for r in results)
    total_carpetas = sum(int(r.get("total_carpetas") or 0) for r in results)
    total_errores = sum(
        1 for r in results
        if str(r.get("estado") or "").upper() == "ERROR"
        or str(r.get("scan_mode") or "").upper() == "ERROR"
    )

    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.execute(
            """
            UPDATE box_watch_scan_jobs
            SET estado = ?,
                finished_at = ?,
                progress_label = ?,
                progress_percent = 100,
                completed_routes = ?,
                total_routes = ?,
                total_archivos = ?,
                total_carpetas = ?,
                total_errores = ?,
                result_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                JOB_DONE if total_errores == 0 else JOB_ERROR,
                _now(),
                "Escaneo finalizado",
                total_routes,
                total_routes,
                total_archivos,
                total_carpetas,
                total_errores,
                _json_dumps(results),
                _now(),
                int(job_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def fail_job(job_id, error):
    ensure_job_schema()
    conn = get_connection()
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.execute(
            """
            UPDATE box_watch_scan_jobs
            SET estado = ?,
                finished_at = ?,
                progress_label = ?,
                error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                JOB_ERROR,
                _now(),
                "Escaneo con error",
                str(error),
                _now(),
                int(job_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def launch_scan_job(job_id, keep_console_open=True):
    configure_sqlite_runtime()
    runner = _runner_path()
    if not runner.exists():
        raise FileNotFoundError(f"No existe runner Box Watch: {runner}")

    if os.name == "nt" and keep_console_open:
        cmd = [
            "cmd.exe",
            "/k",
            sys.executable,
            str(runner),
            "--job-id",
            str(int(job_id)),
        ]
        creationflags = subprocess.CREATE_NEW_CONSOLE
    else:
        cmd = [sys.executable, str(runner), "--job-id", str(int(job_id))]
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_CONSOLE

    return subprocess.Popen(
        cmd,
        cwd=str(_repo_root()),
        creationflags=creationflags,
    )
