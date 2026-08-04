"""
Aplicación transaccional del consolidado de nóminas al EX02.

Este servicio:
- recalcula dentro de la misma transacción;
- evita aplicar resultados obsoletos;
- guarda el ingreso mensual computable;
- marca las propuestas confirmadas como APLICADA;
- registra la aplicación;
- no recalcula todavía el diagnóstico IPREM completo.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.services import (
    family_reunification_economic_diagnosis_service
    as economic_diagnosis,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = (
    PROJECT_ROOT
    / "database"
    / "quesada.db"
)

MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "20260804_create_expedient_payroll_applications.sql"
)

INCOME_FIELD_CODE = (
    "ingresos_mensuales_"
    "computables_centimos"
)

STATUS_CONFIRMED = "CONFIRMADA"
STATUS_APPLIED = "APLICADA"


def _now() -> str:
    return datetime.now().isoformat(
        timespec="seconds"
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
    )


def _json_loads(
    value: Any,
    default=None,
):
    if not value:
        return default

    try:
        return json.loads(value)
    except Exception:
        return default


def _connect(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(
        "PRAGMA foreign_keys = ON"
    )
    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )
    return conn


def ensure_schema(
    conn: sqlite3.Connection | None = None,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    owns_connection = conn is None
    connection = conn or _connect(db_path)

    try:
        if not MIGRATION_PATH.exists():
            raise FileNotFoundError(
                f"No existe la migración: "
                f"{MIGRATION_PATH}"
            )

        connection.executescript(
            MIGRATION_PATH.read_text(
                encoding="utf-8"
            )
        )

        if owns_connection:
            connection.commit()
    finally:
        if owns_connection:
            connection.close()


def _require_expedient(
    conn: sqlite3.Connection,
    expediente_id: int,
) -> None:
    row = conn.execute(
        """
        SELECT id
        FROM expedientes
        WHERE id = ?
        """,
        (int(expediente_id),),
    ).fetchone()

    if not row:
        raise ValueError(
            "No existe el expediente indicado"
        )


def _require_form(
    conn: sqlite3.Connection,
    formulario_id: int,
) -> None:
    row = conn.execute(
        """
        SELECT id
        FROM config_formularios_expediente
        WHERE id = ?
        """,
        (int(formulario_id),),
    ).fetchone()

    if not row:
        raise ValueError(
            "No existe el formulario indicado"
        )


def _get_or_create_field_id(
    conn: sqlite3.Connection,
    formulario_id: int,
    field_code: str,
) -> int:
    row = conn.execute(
        """
        SELECT id
        FROM config_campos_formulario_expediente
        WHERE formulario_id = ?
          AND codigo = ?
        LIMIT 1
        """,
        (
            int(formulario_id),
            str(field_code),
        ),
    ).fetchone()

    if row:
        return int(row["id"])

    cursor = conn.execute(
        """
        INSERT INTO config_campos_formulario_expediente (
            formulario_id,
            codigo,
            etiqueta,
            tipo_campo,
            obligatorio,
            opciones_json,
            placeholder,
            ayuda,
            valor_defecto,
            orden,
            activo
        )
        VALUES (
            ?, ?, ?, ?, 0, '', '', ?, '', 9999, 0
        )
        """,
        (
            int(formulario_id),
            str(field_code),
            str(field_code),
            "tecnico_economico",
            (
                "Campo técnico generado para "
                "aplicación de nóminas confirmadas."
            ),
        ),
    )

    return int(cursor.lastrowid)


def _current_specific_value(
    conn: sqlite3.Connection,
    expediente_id: int,
    formulario_id: int,
    field_code: str,
) -> int | None:
    row = conn.execute(
        """
        SELECT valor
        FROM expediente_datos_especificos
        WHERE expediente_id = ?
          AND formulario_id = ?
          AND codigo = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (
            int(expediente_id),
            int(formulario_id),
            str(field_code),
        ),
    ).fetchone()

    if not row:
        return None

    raw = str(
        row["valor"] or ""
    ).strip()

    if not raw:
        return None

    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            "El valor económico actual del EX02 "
            "no contiene un número válido"
        )



def _specific_value(
    conn: sqlite3.Connection,
    expediente_id: int,
    formulario_id: int,
    field_code: str,
    *,
    required: bool = False,
    default: str = "",
) -> str:
    row = conn.execute(
        """
        SELECT valor
        FROM expediente_datos_especificos
        WHERE expediente_id = ?
          AND formulario_id = ?
          AND codigo = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (
            int(expediente_id),
            int(formulario_id),
            str(field_code),
        ),
    ).fetchone()

    value = (
        str(row["valor"] or "").strip()
        if row
        else str(default or "").strip()
    )

    if required and not value:
        raise ValueError(
            "Falta el dato económico obligatorio: "
            + str(field_code)
        )

    return value


def _upsert_specific_value(
    conn: sqlite3.Connection,
    expediente_id: int,
    formulario_id: int,
    field_code: str,
    value: Any,
) -> None:
    field_id = _get_or_create_field_id(
        conn,
        formulario_id,
        field_code,
    )

    conn.execute(
        """
        INSERT INTO expediente_datos_especificos (
            expediente_id,
            formulario_id,
            campo_id,
            codigo,
            valor,
            updated_at
        )
        VALUES (
            ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
        )
        ON CONFLICT(
            expediente_id,
            campo_id
        )
        DO UPDATE SET
            formulario_id = excluded.formulario_id,
            codigo = excluded.codigo,
            valor = excluded.valor,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            int(expediente_id),
            int(formulario_id),
            int(field_id),
            str(field_code),
            str(value if value is not None else ""),
        ),
    )


def _calculate_and_store_diagnosis(
    conn: sqlite3.Connection,
    expediente_id: int,
    formulario_id: int,
    income_centimos: int,
) -> dict:
    iprem = _specific_value(
        conn,
        expediente_id,
        formulario_id,
        "iprem_mensual_referencia_centimos",
        required=True,
    )
    people = _specific_value(
        conn,
        expediente_id,
        formulario_id,
        "numero_personas_reagrupadas",
        required=True,
    )
    minors = _specific_value(
        conn,
        expediente_id,
        formulario_id,
        "numero_reagrupados_menores",
        default="0",
    )
    criterion = _specific_value(
        conn,
        expediente_id,
        formulario_id,
        "criterio_economico",
        default="GENERAL_IPREM",
    )

    result = (
        economic_diagnosis
        .evaluate_family_reunification_economic_diagnosis(
            iprem_mensual_centimos=int(iprem),
            numero_personas_reagrupadas=int(people),
            numero_reagrupados_menores=int(minors or 0),
            ingresos_mensuales_computables_centimos=(
                int(income_centimos)
            ),
            criterio=(
                criterion
                or "GENERAL_IPREM"
            ),
        )
    )

    values = {
        "ingresos_mensuales_computables_centimos": (
            int(income_centimos)
        ),
        "diagnostico_economico_estado": (
            result["estado"]
        ),
        "diagnostico_economico_porcentaje_iprem": (
            result["porcentaje_iprem_requerido"]
        ),
        (
            "diagnostico_economico_"
            "importe_referencia_centimos"
        ): result["importe_referencia_centimos"],
        (
            "diagnostico_economico_"
            "diferencia_centimos"
        ): (
            ""
            if result["diferencia_centimos"] is None
            else result["diferencia_centimos"]
        ),
        (
            "diagnostico_economico_"
            "porcentaje_cobertura"
        ): (
            ""
            if result["porcentaje_cobertura"] is None
            else result["porcentaje_cobertura"]
        ),
        (
            "diagnostico_economico_"
            "nivel_advertencia"
        ): result["nivel_advertencia"],
        (
            "diagnostico_economico_"
            "requiere_revision"
        ): (
            "Sí"
            if result[
                "requiere_revision_profesional"
            ]
            else "No"
        ),
        (
            "diagnostico_economico_"
            "bloquea_presentacion"
        ): "No",
    }

    for field_code, value in values.items():
        _upsert_specific_value(
            conn,
            expediente_id,
            formulario_id,
            field_code,
            value,
        )

    return result


def _confirmed_rows(
    conn: sqlite3.Connection,
    expediente_id: int,
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            p.id,
            p.document_id,
            p.period_year,
            p.period_month,
            p.period_key,
            p.net_pay_centimos,
            p.review_status
        FROM expedient_payroll_proposals p
        JOIN expedient_income_evidence_documents d
          ON d.id = p.document_id
        WHERE d.expediente_id = ?
          AND p.review_status = ?
        ORDER BY
            p.period_year,
            p.period_month,
            p.id
        """,
        (
            int(expediente_id),
            STATUS_CONFIRMED,
        ),
    ).fetchall()


def _build_consolidation(
    rows: list[sqlite3.Row],
    expediente_id: int,
) -> dict:
    if not rows:
        raise ValueError(
            "No hay nóminas confirmadas "
            "para aplicar"
        )

    periods = []
    period_counts = {}
    proposal_ids = []
    net_values = []

    for row in rows:
        proposal_ids.append(
            int(row["id"])
        )

        year = row["period_year"]
        month = row["period_month"]
        net_value = row[
            "net_pay_centimos"
        ]

        if year is None or month is None:
            raise ValueError(
                "Hay nóminas confirmadas "
                "sin periodo"
            )

        if net_value is None:
            raise ValueError(
                "Hay nóminas confirmadas sin "
                "líquido a percibir"
            )

        period = (
            f"{int(year):04d}-"
            f"{int(month):02d}"
        )

        periods.append(period)
        period_counts[period] = (
            period_counts.get(period, 0)
            + 1
        )
        net_values.append(
            int(net_value)
        )

    duplicate_periods = sorted(
        period
        for period, count
        in period_counts.items()
        if count > 1
    )

    if duplicate_periods:
        raise ValueError(
            "No se puede aplicar: existen "
            "periodos duplicados: "
            + ", ".join(duplicate_periods)
        )

    suggested = round(
        sum(net_values)
        / len(net_values)
    )

    return {
        "expediente_id": int(
            expediente_id
        ),
        "proposal_ids": proposal_ids,
        "confirmed_payroll_count": len(
            rows
        ),
        "periods": sorted(periods),
        "average_net_centimos": (
            suggested
        ),
        "minimum_net_centimos": min(
            net_values
        ),
        "maximum_net_centimos": max(
            net_values
        ),
        (
            "suggested_monthly_"
            "income_centimos"
        ): suggested,
        "ready_for_application": True,
    }


def _active_application(
    conn: sqlite3.Connection,
    expediente_id: int,
    formulario_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM expedient_payroll_applications
        WHERE expediente_id = ?
          AND formulario_id = ?
          AND field_code = ?
          AND application_status = 'APPLIED'
        LIMIT 1
        """,
        (
            int(expediente_id),
            int(formulario_id),
            INCOME_FIELD_CODE,
        ),
    ).fetchone()


def _application_to_dict(
    row: sqlite3.Row | None,
) -> dict | None:
    if not row:
        return None

    data = dict(row)
    data["proposal_ids"] = (
        _json_loads(
            data.get(
                "proposal_ids_json"
            ),
            [],
        )
    )
    data["periods"] = _json_loads(
        data.get("periods_json"),
        [],
    )
    data["consolidation"] = (
        _json_loads(
            data.get(
                "consolidation_json"
            ),
            {},
        )
    )

    return data


def get_active_application(
    expediente_id: int,
    formulario_id: int,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict | None:
    conn = _connect(db_path)

    try:
        ensure_schema(conn)

        row = _active_application(
            conn,
            expediente_id,
            formulario_id,
        )

        return _application_to_dict(row)
    finally:
        conn.close()


def apply_payroll_consolidation_to_expedient(
    expediente_id: int,
    formulario_id: int,
    *,
    expected_amount_centimos: int,
    overwrite_existing: bool = False,
    applied_by: str = "",
    notes: str = "",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    expected = int(
        expected_amount_centimos
    )

    if expected < 0:
        raise ValueError(
            "El importe esperado no puede "
            "ser negativo"
        )

    conn = _connect(db_path)

    try:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")

        _require_expedient(
            conn,
            expediente_id,
        )
        _require_form(
            conn,
            formulario_id,
        )

        existing_application = (
            _active_application(
                conn,
                expediente_id,
                formulario_id,
            )
        )

        if existing_application:
            raise ValueError(
                "Ya existe una aplicación activa "
                "de nóminas para este EX02"
            )

        rows = _confirmed_rows(
            conn,
            expediente_id,
        )

        consolidation = (
            _build_consolidation(
                rows,
                expediente_id,
            )
        )

        calculated = int(
            consolidation[
                "suggested_monthly_"
                "income_centimos"
            ]
        )

        if calculated != expected:
            raise ValueError(
                "El consolidado ha cambiado. "
                f"Esperado: {expected}; "
                f"actual: {calculated}"
            )

        previous_value = (
            _current_specific_value(
                conn,
                expediente_id,
                formulario_id,
                INCOME_FIELD_CODE,
            )
        )

        if (
            previous_value is not None
            and previous_value != calculated
            and not overwrite_existing
        ):
            raise ValueError(
                "El EX02 ya contiene un ingreso "
                "mensual diferente. Confirma "
                "expresamente la sobrescritura."
            )

        diagnosis = _calculate_and_store_diagnosis(
            conn,
            expediente_id,
            formulario_id,
            calculated,
        )

        consolidation["diagnosis"] = diagnosis
        consolidation["applied_to_diagnosis"] = True

        applied_at = _now()
        proposal_ids = consolidation[
            "proposal_ids"
        ]

        placeholders = ", ".join(
            "?"
            for _ in proposal_ids
        )

        cursor = conn.execute(
            f"""
            UPDATE expedient_payroll_proposals
            SET review_status = ?,
                applied_at = ?,
                requires_manual_review = 0,
                updated_at = ?
            WHERE id IN ({placeholders})
              AND review_status = ?
            """,
            [
                STATUS_APPLIED,
                applied_at,
                applied_at,
                *proposal_ids,
                STATUS_CONFIRMED,
            ],
        )

        if cursor.rowcount != len(
            proposal_ids
        ):
            raise RuntimeError(
                "No se pudieron marcar todas "
                "las nóminas como aplicadas"
            )

        application_cursor = conn.execute(
            """
            INSERT INTO expedient_payroll_applications (
                expediente_id,
                formulario_id,
                field_code,
                previous_value_centimos,
                applied_value_centimos,
                confirmed_payroll_count,
                proposal_ids_json,
                periods_json,
                consolidation_json,
                application_status,
                applied_by,
                notes,
                applied_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                'APPLIED', ?, ?, ?, ?
            )
            """,
            (
                int(expediente_id),
                int(formulario_id),
                INCOME_FIELD_CODE,
                previous_value,
                calculated,
                int(
                    consolidation[
                        "confirmed_payroll_count"
                    ]
                ),
                _json_dumps(
                    proposal_ids
                ),
                _json_dumps(
                    consolidation["periods"]
                ),
                _json_dumps(
                    consolidation
                ),
                str(applied_by or ""),
                str(notes or ""),
                applied_at,
                applied_at,
            ),
        )

        application_id = int(
            application_cursor.lastrowid
        )

        conn.commit()

        result_row = conn.execute(
            """
            SELECT *
            FROM expedient_payroll_applications
            WHERE id = ?
            """,
            (application_id,),
        ).fetchone()

        result = _application_to_dict(
            result_row
        )
        result["applied_to_diagnosis"] = (
            True
        )

        return result

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
