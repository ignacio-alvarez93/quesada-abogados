"""
Servicio de presentación asistida.

Nueva versión:
- Genera carpeta completa por expediente.
- Mapea expediente + cliente desde la base de datos.
- Crea datos_mercurio.json.
- Lanza proceso externo con sb_cdp.Chrome.
"""

import sqlite3
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

from backend.services import mercurio_mapper_service

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "app" / "run_presentacion_asistida.py"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dict(row):
    return dict(row) if row else None


def get_tipo_presentacion_config(tipo_expediente_id):
    if not tipo_expediente_id:
        return None

    with _connect() as conn:
        return _dict(
            conn.execute(
                """
                SELECT id, codigo, nombre, descripcion, url_presentacion, activo
                FROM config_tipos_expediente
                WHERE id = ?
                """,
                (int(tipo_expediente_id),),
            ).fetchone()
        )



def validate_cliente_mercurio_ready(expediente_id):
    """
    Validación PRO antes de iniciar Mercurio.

    Bloquea la presentación si faltan datos obligatorios del cliente
    necesarios para automatización telemática.
    """
    errores = []

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT c.sexo
            FROM expedientes e
            JOIN clientes c ON c.id = e.cliente_id
            WHERE e.id = ?
            """,
            (int(expediente_id),),
        ).fetchone()

    if not row:
        errores.append("Cliente vinculado al expediente")
        return errores

    sexo = str(row["sexo"] or "").strip().upper()

    if not sexo:
        errores.append("Sexo del cliente")
    elif sexo not in ("HOMBRE", "MUJER", "X"):
        errores.append(f"Sexo inválido ({sexo})")

    return errores


def validate_expediente_for_presentation(expediente):
    if not expediente:
        raise ValueError("No se ha seleccionado ningún expediente")

    if not expediente.get("id"):
        raise ValueError("El expediente no tiene ID")

    if not expediente.get("tipo_expediente_id"):
        raise ValueError("El expediente no tiene tipo")

    if not str(expediente.get("box_folder_path") or "").strip():
        raise ValueError("El expediente no tiene ruta Box")

    tipo = get_tipo_presentacion_config(expediente.get("tipo_expediente_id"))
    if not tipo:
        raise ValueError("Tipo no encontrado")

    url = str(tipo.get("url_presentacion") or "").strip()
    if not url:
        raise ValueError("Sin URL de presentación")

    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("La URL de presentación debe empezar por http:// o https://")

    errores_cliente = validate_cliente_mercurio_ready(expediente.get("id"))
    if errores_cliente:
        raise ValueError(
            "No se puede iniciar presentación Mercurio.\n"
            + "Faltan campos obligatorios del cliente:\n- "
            + "\n- ".join(errores_cliente)
        )

    export = mercurio_mapper_service.build_and_export(expediente.get("id"))
    datos = export["datos_mercurio"]

    return {
        "url_presentacion": url,
        "expediente_id": expediente.get("id"),
        "numero_expediente": expediente.get("numero_expediente"),
        "tipo_expediente_id": expediente.get("tipo_expediente_id"),
        "tipo_codigo": tipo.get("codigo"),
        "tipo_nombre": tipo.get("nombre"),
        "box_folder_path": expediente.get("box_folder_path"),
        "provincia_codigo": datos["presentacion"]["provincia_codigo"],
        "presentacion_folder": str(export["folder"]),
        "datos_mercurio_path": str(export["datos_mercurio_path"]),
    }


def start_presentation_external(config, auto=True):
    if not RUNNER_PATH.exists():
        raise FileNotFoundError(f"No existe el lanzador externo: {RUNNER_PATH}")

    cmd = [
        sys.executable,
        str(RUNNER_PATH),
        "--url",
        config["url_presentacion"],
        "--expediente-id",
        str(config.get("expediente_id") or ""),
        "--numero-expediente",
        str(config.get("numero_expediente") or ""),
        "--tipo",
        str(config.get("tipo_nombre") or config.get("tipo_codigo") or ""),
        "--provincia-codigo",
        str(config.get("provincia_codigo") or "33"),
        "--datos-mercurio-json",
        str(config.get("datos_mercurio_path") or ""),
        "--session-dir",
        str(config.get("presentacion_folder") or ""),
    ]

    if auto:
        cmd.append("--auto")

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_CONSOLE

    return subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        creationflags=creationflags,
    )


def start_presentation_for_expediente(expediente):
    config = validate_expediente_for_presentation(expediente)
    process = start_presentation_external(config, auto=True)

    return {
        "process": process,
        "pid": process.pid,
        "browser": None,
        "manager": None,
        "mode": "external_sb_cdp_auto_json_mercurio",
        "started_at": datetime.now(),
        "config": config,
    }


def close_presentation(context):
    if not context:
        return

    process = context.get("process")
    if process and process.poll() is None:
        process.terminate()
