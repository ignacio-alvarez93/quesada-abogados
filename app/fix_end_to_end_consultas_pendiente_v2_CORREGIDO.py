from pathlib import Path

PATH = Path("backend/services/economic_service.py")

PATCH = r'''

# --- FIX CONSULTAS / PENDIENTE ---

def _ensure_consultas_schema_local(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS eco_consultas_aplicadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cobro_id INTEGER NOT NULL,
            cliente_id INTEGER NOT NULL,
            expediente_id INTEGER,
            hoja_encargo_id INTEGER,
            importe_aplicado REAL NOT NULL DEFAULT 0,
            fecha_aplicacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            observaciones TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(cobro_id, expediente_id, hoja_encargo_id)
        )
        """
    )


def aplicar_cobro_consulta_a_hoja(
    cobro_id,
    expediente_id,
    hoja_encargo_id,
    importe_aplicado=None,
    observaciones=""
):
    with _connect() as conn:

        _ensure_consultas_schema_local(conn)

        cobro = _dict(
            conn.execute(
                "SELECT * FROM eco_cobros WHERE id = ? AND activo = 1",
                (int(cobro_id),),
            ).fetchone()
        )

        if not cobro:
            raise ValueError("Cobro no encontrado")

        if cobro.get("tipo_cobro") != "CONSULTA":
            raise ValueError("El cobro no es una CONSULTA")

        hoja = _dict(
            conn.execute(
                "SELECT * FROM eco_hojas_encargo WHERE id = ?",
                (int(hoja_encargo_id),),
            ).fetchone()
        )

        if not hoja:
            raise ValueError("Hoja no encontrada")

        expediente_id = expediente_id or hoja.get("expediente_id")

        importe = _float(
            importe_aplicado
            if importe_aplicado not in (None, "")
            else cobro.get("importe")
        )

        conn.execute(
            """
            INSERT INTO eco_consultas_aplicadas (
                cobro_id,
                cliente_id,
                expediente_id,
                hoja_encargo_id,
                importe_aplicado,
                observaciones,
                activo
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                int(cobro_id),
                int(cobro["cliente_id"]),
                expediente_id,
                int(hoja_encargo_id),
                importe,
                observaciones,
            ),
        )

        nuevo_descuento = (
            float(hoja.get("descuento_consultas_previas") or 0)
            + importe
        )

        nuevo_neto = max(
            0.0,
            float(hoja.get("importe_bruto") or 0)
            - float(hoja.get("descuento_manual") or 0)
            - nuevo_descuento,
        )

        conn.execute(
            """
            UPDATE eco_hojas_encargo
            SET descuento_consultas_previas = ?,
                importe_neto = ?
            WHERE id = ?
            """,
            (
                nuevo_descuento,
                nuevo_neto,
                int(hoja_encargo_id),
            ),
        )

        conn.execute(
            """
            UPDATE eco_cobros
            SET expediente_id = ?,
                hoja_encargo_id = ?
            WHERE id = ?
            """,
            (
                expediente_id,
                int(hoja_encargo_id),
                int(cobro_id),
            ),
        )

        conn.commit()

    return True

'''

text = PATH.read_text(encoding="utf-8")

marker = "# --- FIX CONSULTAS / PENDIENTE ---"

if marker in text:
    text = text.split(marker)[0].rstrip() + "\n"

text += "\n\n" + PATCH

PATH.write_text(text, encoding="utf-8")

print("economic_service.py corregido correctamente.")
