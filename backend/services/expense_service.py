from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DB_PATH = Path("database/quesada.db")


_SCHEMA_COLUMNS: dict[str, str] = {
    "supplier_id": "INTEGER",
    "supplier_name_snapshot": "TEXT",
    "supplier_tax_id_snapshot": "TEXT",
    "numero_factura": "TEXT",
    "fecha_factura": "TEXT",
    "tipo_justificante": "TEXT NOT NULL DEFAULT 'INVOICE'",
    "base_imponible_centimos": "INTEGER NOT NULL DEFAULT 0",
    "iva_centimos": "INTEGER NOT NULL DEFAULT 0",
    "irpf_centimos": "INTEGER NOT NULL DEFAULT 0",
    "otros_impuestos_centimos": "INTEGER NOT NULL DEFAULT 0",
    "total_centimos": "INTEGER NOT NULL DEFAULT 0",
    "iva_porcentaje": "REAL NOT NULL DEFAULT 0",
    "irpf_porcentaje": "REAL NOT NULL DEFAULT 0",
    "porcentaje_deducible": "REAL NOT NULL DEFAULT 100",
    "estado_documental": "TEXT NOT NULL DEFAULT 'SIN_JUSTIFICANTE'",
    "estado_fiscal": "TEXT NOT NULL DEFAULT 'PENDIENTE_REVISION'",
    "iva_deducible": "INTEGER NOT NULL DEFAULT 1",
    "deducible_irpf": "INTEGER NOT NULL DEFAULT 1",
    "periodo_desde": "TEXT",
    "periodo_hasta": "TEXT",
    "fecha_vencimiento": "TEXT",
    "bank_movement_id": "INTEGER",
    "client_id": "INTEGER",
    "documento_ruta": "TEXT",
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def ensure_schema() -> None:
    with _connect() as conn:
        table = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'eco_gastos'
            """
        ).fetchone()

        if table is None:
            raise RuntimeError("No existe la tabla eco_gastos.")

        current_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(eco_gastos)"
            ).fetchall()
        }

        for column_name, column_type in _SCHEMA_COLUMNS.items():
            if column_name not in current_columns:
                conn.execute(
                    f"""
                    ALTER TABLE eco_gastos
                    ADD COLUMN {column_name} {column_type}
                    """
                )

        conn.execute(
            """
            UPDATE eco_gastos
            SET total_centimos = CAST(
                ROUND(COALESCE(importe, 0) * 100)
                AS INTEGER
            )
            WHERE COALESCE(total_centimos, 0) = 0
              AND COALESCE(importe, 0) <> 0
            """
        )

        conn.execute(
            """
            UPDATE eco_gastos
            SET supplier_name_snapshot = proveedor
            WHERE supplier_name_snapshot IS NULL
              AND proveedor IS NOT NULL
              AND TRIM(proveedor) <> ''
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_eco_gastos_supplier_id
            ON eco_gastos(supplier_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_eco_gastos_estado_documental
            ON eco_gastos(estado_documental)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_eco_gastos_estado_fiscal
            ON eco_gastos(estado_fiscal)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_eco_gastos_estado_conciliacion
            ON eco_gastos(estado_conciliacion)
            """
        )

        conn.commit()


def list_expenses(
    *,
    search: str = "",
    active: bool | None = True,
    quick_filter: str = "ALL",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    ensure_schema()

    conditions: list[str] = []
    params: list[Any] = []

    if active is not None:
        conditions.append("g.activo = ?")
        params.append(1 if active else 0)

    search = str(search or "").strip()

    if search:
        like = f"%{search}%"
        conditions.append(
            """
            (
                COALESCE(g.proveedor, '') LIKE ?
                OR COALESCE(g.supplier_name_snapshot, '') LIKE ?
                OR COALESCE(g.concepto, '') LIKE ?
                OR COALESCE(g.categoria, '') LIKE ?
                OR COALESCE(g.numero_factura, '') LIKE ?
                OR CAST(g.id AS TEXT) LIKE ?
            )
            """
        )
        params.extend([like, like, like, like, like, like])

    if date_from:
        conditions.append("g.fecha_gasto >= ?")
        params.append(date_from)

    if date_to:
        conditions.append("g.fecha_gasto <= ?")
        params.append(date_to)

    quick_filter = str(quick_filter or "ALL").upper()

    if quick_filter == "PENDING":
        conditions.append(
            """
            COALESCE(g.estado_conciliacion, 'PENDIENTE')
            IN ('PENDIENTE', 'PARCIAL')
            """
        )
    elif quick_filter == "WITHOUT_DOCUMENT":
        conditions.append(
            """
            COALESCE(g.estado_documental, 'SIN_JUSTIFICANTE')
            = 'SIN_JUSTIFICANTE'
            """
        )
    elif quick_filter == "WITH_INVOICE":
        conditions.append(
            """
            COALESCE(g.estado_documental, '')
            IN ('FACTURA_RECIBIDA', 'DOCUMENTO_REVISADO')
            """
        )
    elif quick_filter == "RECONCILED":
        conditions.append(
            """
            COALESCE(g.estado_conciliacion, '')
            IN ('CONCILIADO', 'NO_REQUIERE_CONCILIACION')
            """
        )
    elif quick_filter == "DEDUCTIBLE":
        conditions.append(
            """
            (
                COALESCE(g.deducible_irpf, g.deducible, 0) = 1
                OR COALESCE(g.iva_deducible, 0) = 1
            )
            """
        )
    elif quick_filter == "NON_DEDUCTIBLE":
        conditions.append(
            """
            COALESCE(g.deducible_irpf, g.deducible, 0) = 0
            AND COALESCE(g.iva_deducible, 0) = 0
            """
        )

    where_sql = ""

    if conditions:
        where_sql = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT
            g.*,
            COALESCE(
                NULLIF(g.supplier_name_snapshot, ''),
                NULLIF(g.proveedor, ''),
                s.legal_name,
                'Sin proveedor'
            ) AS supplier_display_name,
            s.supplier_code,
            s.tax_id AS supplier_tax_id,
            e.numero_expediente,
            CASE
                WHEN COALESCE(g.total_centimos, 0) <> 0
                    THEN g.total_centimos
                ELSE CAST(
                    ROUND(COALESCE(g.importe, 0) * 100)
                    AS INTEGER
                )
            END AS effective_total_centimos
        FROM eco_gastos g
        LEFT JOIN suppliers s
          ON s.id = g.supplier_id
        LEFT JOIN expedientes e
          ON e.id = g.expediente_id
        {where_sql}
        ORDER BY g.fecha_gasto DESC, g.id DESC
        LIMIT ?
        OFFSET ?
    """

    params.extend([max(1, int(limit)), max(0, int(offset))])

    with _connect() as conn:
        return [
            dict(row)
            for row in conn.execute(sql, params).fetchall()
        ]


def count_expenses(
    *,
    search: str = "",
    active: bool | None = True,
    quick_filter: str = "ALL",
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    rows = list_expenses(
        search=search,
        active=active,
        quick_filter=quick_filter,
        date_from=date_from,
        date_to=date_to,
        limit=1_000_000,
        offset=0,
    )
    return len(rows)


def expense_metrics(
    *,
    search: str = "",
    active: bool | None = True,
    quick_filter: str = "ALL",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, int]:
    rows = list_expenses(
        search=search,
        active=active,
        quick_filter=quick_filter,
        date_from=date_from,
        date_to=date_to,
        limit=1_000_000,
        offset=0,
    )

    total = sum(
        int(row.get("effective_total_centimos") or 0)
        for row in rows
    )
    base = sum(
        int(row.get("base_imponible_centimos") or 0)
        for row in rows
    )
    iva = sum(
        int(row.get("iva_centimos") or 0)
        for row in rows
    )
    pending = sum(
        int(row.get("effective_total_centimos") or 0)
        for row in rows
        if str(
            row.get("estado_conciliacion") or "PENDIENTE"
        ).upper()
        in {"PENDIENTE", "PARCIAL"}
    )

    return {
        "count": len(rows),
        "total_centimos": total,
        "base_centimos": base,
        "iva_centimos": iva,
        "pending_centimos": pending,
    }


def get_expense(expense_id: int) -> dict[str, Any] | None:
    ensure_schema()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                g.*,
                COALESCE(
                    NULLIF(g.supplier_name_snapshot, ''),
                    NULLIF(g.proveedor, ''),
                    s.legal_name,
                    'Sin proveedor'
                ) AS supplier_display_name,
                s.tax_id AS supplier_tax_id,
                e.numero_expediente
            FROM eco_gastos g
            LEFT JOIN suppliers s
              ON s.id = g.supplier_id
            LEFT JOIN expedientes e
              ON e.id = g.expediente_id
            WHERE g.id = ?
            """,
            (int(expense_id),),
        ).fetchone()

    return _dict(row)


def set_expense_active(
    expense_id: int,
    active: bool,
) -> None:
    ensure_schema()

    with _connect() as conn:
        conn.execute(
            """
            UPDATE eco_gastos
            SET activo = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if active else 0, int(expense_id)),
        )
        conn.commit()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(
            str(value or "")
            .strip()
            .replace(",", ".")
        )
    except (TypeError, ValueError):
        return float(default)


def _supplier_snapshot(
    conn: sqlite3.Connection,
    supplier_id: int | None,
) -> dict[str, Any]:
    if supplier_id is None:
        return {
            "supplier_id": None,
            "supplier_name": "",
            "supplier_tax_id": "",
        }

    row = conn.execute(
        """
        SELECT
            id,
            legal_name,
            tax_id
        FROM suppliers
        WHERE id = ?
        """,
        (int(supplier_id),),
    ).fetchone()

    if row is None:
        raise ValueError(
            "El proveedor seleccionado ya no existe."
        )

    return {
        "supplier_id": int(row["id"]),
        "supplier_name": _text(row["legal_name"]),
        "supplier_tax_id": _text(row["tax_id"]),
    }


def _normalize_expense_payload(
    conn: sqlite3.Connection,
    data: dict[str, Any],
) -> dict[str, Any]:
    supplier_id = _optional_int(
        data.get("supplier_id")
    )

    supplier = _supplier_snapshot(
        conn,
        supplier_id,
    )

    fecha_gasto = _text(data.get("fecha_gasto"))
    concepto = _text(data.get("concepto"))

    if not fecha_gasto:
        raise ValueError(
            "La fecha del gasto es obligatoria."
        )

    if not concepto:
        raise ValueError(
            "El concepto del gasto es obligatorio."
        )

    base_centimos = max(
        0,
        _integer(
            data.get("base_imponible_centimos")
        ),
    )
    iva_centimos = max(
        0,
        _integer(data.get("iva_centimos")),
    )
    irpf_centimos = max(
        0,
        _integer(data.get("irpf_centimos")),
    )
    otros_centimos = _integer(
        data.get("otros_impuestos_centimos")
    )
    total_centimos = _integer(
        data.get("total_centimos")
    )

    calculated_total = (
        base_centimos
        + iva_centimos
        - irpf_centimos
        + otros_centimos
    )

    if total_centimos <= 0:
        total_centimos = calculated_total

    if total_centimos < 0:
        raise ValueError(
            "El total del gasto no puede ser negativo."
        )

    document_path = _text(
        data.get("documento_ruta")
        or data.get("factura_recibida_ruta")
    )

    document_status = _text(
        data.get("estado_documental")
        or (
            "JUSTIFICANTE_ADJUNTO"
            if document_path
            else "SIN_JUSTIFICANTE"
        )
    ).upper()

    deductible_irpf = 1 if bool(
        data.get("deducible_irpf")
    ) else 0

    iva_deducible = 1 if bool(
        data.get("iva_deducible")
    ) else 0

    return {
        "fecha_gasto": fecha_gasto,
        "fecha_factura": (
            _text(data.get("fecha_factura"))
            or fecha_gasto
        ),
        "supplier_id": supplier["supplier_id"],
        "supplier_name_snapshot": (
            supplier["supplier_name"]
        ),
        "supplier_tax_id_snapshot": (
            supplier["supplier_tax_id"]
        ),
        "proveedor": supplier["supplier_name"],
        "concepto": concepto,
        "categoria": _text(data.get("categoria")),
        "numero_factura": _text(
            data.get("numero_factura")
        ),
        "tipo_justificante": _text(
            data.get("tipo_justificante")
            or "INVOICE"
        ).upper(),
        "forma_pago": _text(
            data.get("forma_pago")
        ).upper(),
        "base_imponible_centimos": base_centimos,
        "iva_centimos": iva_centimos,
        "irpf_centimos": irpf_centimos,
        "otros_impuestos_centimos": otros_centimos,
        "total_centimos": total_centimos,
        "importe": round(total_centimos / 100, 2),
        "iva_porcentaje": _float_value(
            data.get("iva_porcentaje")
        ),
        "irpf_porcentaje": _float_value(
            data.get("irpf_porcentaje")
        ),
        "porcentaje_deducible": max(
            0.0,
            min(
                100.0,
                _float_value(
                    data.get(
                        "porcentaje_deducible"
                    ),
                    100,
                ),
            ),
        ),
        "deducible_irpf": deductible_irpf,
        "iva_deducible": iva_deducible,
        "deducible": deductible_irpf,
        "estado_documental": document_status,
        "estado_fiscal": _text(
            data.get("estado_fiscal")
            or "PENDIENTE_REVISION"
        ).upper(),
        "estado_conciliacion": _text(
            data.get("estado_conciliacion")
            or "PENDIENTE"
        ).upper(),
        "documento_ruta": document_path,
        "factura_recibida_ruta": document_path,
        "periodo_desde": (
            _text(data.get("periodo_desde"))
            or None
        ),
        "periodo_hasta": (
            _text(data.get("periodo_hasta"))
            or None
        ),
        "fecha_vencimiento": (
            _text(data.get("fecha_vencimiento"))
            or None
        ),
        "expediente_id": _optional_int(
            data.get("expediente_id")
        ),
        "client_id": _optional_int(
            data.get("client_id")
        ),
        "bank_movement_id": _optional_int(
            data.get("bank_movement_id")
        ),
        "observaciones": _text(
            data.get("observaciones")
        ),
    }


def create_expense(
    data: dict[str, Any],
) -> dict[str, Any]:
    ensure_schema()

    with _connect() as conn:
        payload = _normalize_expense_payload(
            conn,
            data,
        )

        cursor = conn.execute(
            """
            INSERT INTO eco_gastos (
                fecha_gasto,
                fecha_factura,
                supplier_id,
                supplier_name_snapshot,
                supplier_tax_id_snapshot,
                proveedor,
                concepto,
                categoria,
                numero_factura,
                tipo_justificante,
                forma_pago,
                base_imponible_centimos,
                iva_centimos,
                irpf_centimos,
                otros_impuestos_centimos,
                total_centimos,
                importe,
                iva_porcentaje,
                irpf_porcentaje,
                porcentaje_deducible,
                deducible_irpf,
                iva_deducible,
                deducible,
                estado_documental,
                estado_fiscal,
                estado_conciliacion,
                documento_ruta,
                factura_recibida_ruta,
                periodo_desde,
                periodo_hasta,
                fecha_vencimiento,
                expediente_id,
                client_id,
                bank_movement_id,
                observaciones,
                activo
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, 1
            )
            """,
            tuple(payload[key] for key in [
                "fecha_gasto",
                "fecha_factura",
                "supplier_id",
                "supplier_name_snapshot",
                "supplier_tax_id_snapshot",
                "proveedor",
                "concepto",
                "categoria",
                "numero_factura",
                "tipo_justificante",
                "forma_pago",
                "base_imponible_centimos",
                "iva_centimos",
                "irpf_centimos",
                "otros_impuestos_centimos",
                "total_centimos",
                "importe",
                "iva_porcentaje",
                "irpf_porcentaje",
                "porcentaje_deducible",
                "deducible_irpf",
                "iva_deducible",
                "deducible",
                "estado_documental",
                "estado_fiscal",
                "estado_conciliacion",
                "documento_ruta",
                "factura_recibida_ruta",
                "periodo_desde",
                "periodo_hasta",
                "fecha_vencimiento",
                "expediente_id",
                "client_id",
                "bank_movement_id",
                "observaciones",
            ]),
        )

        expense_id = int(cursor.lastrowid)
        conn.commit()

    result = get_expense(expense_id)

    if result is None:
        raise RuntimeError(
            "No se pudo recuperar el gasto creado."
        )

    return result


def update_expense(
    expense_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    ensure_schema()

    with _connect() as conn:
        exists = conn.execute(
            """
            SELECT id
            FROM eco_gastos
            WHERE id = ?
            """,
            (int(expense_id),),
        ).fetchone()

        if exists is None:
            raise ValueError(
                "El gasto que intentas editar no existe."
            )

        payload = _normalize_expense_payload(
            conn,
            data,
        )

        conn.execute(
            """
            UPDATE eco_gastos
            SET fecha_gasto = ?,
                fecha_factura = ?,
                supplier_id = ?,
                supplier_name_snapshot = ?,
                supplier_tax_id_snapshot = ?,
                proveedor = ?,
                concepto = ?,
                categoria = ?,
                numero_factura = ?,
                tipo_justificante = ?,
                forma_pago = ?,
                base_imponible_centimos = ?,
                iva_centimos = ?,
                irpf_centimos = ?,
                otros_impuestos_centimos = ?,
                total_centimos = ?,
                importe = ?,
                iva_porcentaje = ?,
                irpf_porcentaje = ?,
                porcentaje_deducible = ?,
                deducible_irpf = ?,
                iva_deducible = ?,
                deducible = ?,
                estado_documental = ?,
                estado_fiscal = ?,
                estado_conciliacion = ?,
                documento_ruta = ?,
                factura_recibida_ruta = ?,
                periodo_desde = ?,
                periodo_hasta = ?,
                fecha_vencimiento = ?,
                expediente_id = ?,
                client_id = ?,
                bank_movement_id = ?,
                observaciones = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            tuple(payload[key] for key in [
                "fecha_gasto",
                "fecha_factura",
                "supplier_id",
                "supplier_name_snapshot",
                "supplier_tax_id_snapshot",
                "proveedor",
                "concepto",
                "categoria",
                "numero_factura",
                "tipo_justificante",
                "forma_pago",
                "base_imponible_centimos",
                "iva_centimos",
                "irpf_centimos",
                "otros_impuestos_centimos",
                "total_centimos",
                "importe",
                "iva_porcentaje",
                "irpf_porcentaje",
                "porcentaje_deducible",
                "deducible_irpf",
                "iva_deducible",
                "deducible",
                "estado_documental",
                "estado_fiscal",
                "estado_conciliacion",
                "documento_ruta",
                "factura_recibida_ruta",
                "periodo_desde",
                "periodo_hasta",
                "fecha_vencimiento",
                "expediente_id",
                "client_id",
                "bank_movement_id",
                "observaciones",
            ]) + (int(expense_id),),
        )

        conn.commit()

    result = get_expense(int(expense_id))

    if result is None:
        raise RuntimeError(
            "No se pudo recuperar el gasto actualizado."
        )

    return result
