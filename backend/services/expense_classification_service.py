from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any


DB_PATH = Path("database/quesada.db")
MIGRATION_PATH = Path(
    "database/migrations/"
    "20260715_create_expense_classification.sql"
)


EXPENSE_COLUMNS = {
    "counterparty_id": "INTEGER",
    "counterparty_type": "TEXT",
    "counterparty_name_snapshot": "TEXT",
    "expense_category_id": "INTEGER",
    "expense_subcategory_id": "INTEGER",
    "expense_category_code": "TEXT",
    "expense_subcategory_code": "TEXT",
    "classification_source": (
        "TEXT NOT NULL DEFAULT 'MANUAL'"
    ),
    "classification_rule_id": "INTEGER",
    "classification_confidence": (
        "REAL NOT NULL DEFAULT 0"
    ),
    "tax_model": "TEXT",
    "tax_reference": "TEXT",
}


CATEGORIES = [
    ("TRIBUTOS", "Tributos e impuestos", 10),
    ("PERSONAL", "Personal", 20),
    (
        "GASTOS_FINANCIEROS",
        "Gastos financieros",
        30,
    ),
    (
        "SERVICIOS_PROFESIONALES",
        "Servicios profesionales",
        40,
    ),
    ("SUMINISTROS", "Suministros", 50),
    ("SOFTWARE", "Software y servicios digitales", 60),
    ("ALQUILERES", "Alquileres", 70),
    (
        "CUOTAS_PROFESIONALES",
        "Cuotas profesionales",
        80,
    ),
    ("OTROS", "Otros gastos", 900),
    (
        "PENDIENTE_CLASIFICACION",
        "Pendiente de clasificación",
        999,
    ),
]


SUBCATEGORIES = [
    ("TRIBUTOS", "MODELO_100", "Modelo 100", 10),
    ("TRIBUTOS", "MODELO_111", "Modelo 111", 20),
    ("TRIBUTOS", "MODELO_130", "Modelo 130", 30),
    ("TRIBUTOS", "MODELO_303", "Modelo 303", 40),
    (
        "TRIBUTOS",
        "OTROS_TRIBUTOS",
        "Otros tributos",
        90,
    ),
    (
        "PERSONAL",
        "SEGURIDAD_SOCIAL_EMPRESA",
        "Seguridad Social empresa",
        10,
    ),
    (
        "PERSONAL",
        "SEGURIDAD_SOCIAL_OTROS",
        "Otras cotizaciones",
        20,
    ),
    ("PERSONAL", "NOMINAS", "Nóminas", 30),
    (
        "PERSONAL",
        "OTROS_COSTES_PERSONAL",
        "Otros costes de personal",
        90,
    ),
    (
        "GASTOS_FINANCIEROS",
        "COMISIONES_BANCARIAS",
        "Comisiones bancarias",
        10,
    ),
    (
        "GASTOS_FINANCIEROS",
        "COMISIONES_TARJETA",
        "Comisiones de tarjeta",
        20,
    ),
    (
        "GASTOS_FINANCIEROS",
        "INTERESES",
        "Intereses",
        30,
    ),
    (
        "GASTOS_FINANCIEROS",
        "OTROS_GASTOS_FINANCIEROS",
        "Otros gastos financieros",
        90,
    ),
    (
        "PENDIENTE_CLASIFICACION",
        "PENDIENTE_REVISION",
        "Pendiente de revisión",
        999,
    ),
]


COUNTERPARTIES = [
    (
        "AEAT",
        "ORGANISMO_PUBLICO",
        "Agencia Estatal de Administración Tributaria",
        "AEAT",
        "",
    ),
    (
        "TGSS",
        "ORGANISMO_PUBLICO",
        "Tesorería General de la Seguridad Social",
        "TGSS",
        "",
    ),
    (
        "CAJA_RURAL",
        "ENTIDAD_FINANCIERA",
        "Caja Rural",
        "Caja Rural",
        "CAJA_RURAL",
    ),
    (
        "SANTANDER",
        "ENTIDAD_FINANCIERA",
        "Banco Santander",
        "Santander",
        "SANTANDER",
    ),
    (
        "ING",
        "ENTIDAD_FINANCIERA",
        "ING",
        "ING",
        "ING",
    ),
]


RULES = [
    (
        "AEAT_111_ADEUDO",
        None,
        "ADEUDO 111",
        10,
        "AEAT",
        "TRIBUTOS",
        "MODELO_111",
        "Pago AEAT · Modelo 111",
        "111",
        1.0,
    ),
    (
        "AEAT_111_MODELO",
        None,
        "MODELO 111",
        11,
        "AEAT",
        "TRIBUTOS",
        "MODELO_111",
        "Pago AEAT · Modelo 111",
        "111",
        1.0,
    ),
    (
        "AEAT_130_ADEUDO",
        None,
        "ADEUDO 130",
        20,
        "AEAT",
        "TRIBUTOS",
        "MODELO_130",
        "Pago AEAT · Modelo 130",
        "130",
        1.0,
    ),
    (
        "AEAT_130_MODELO",
        None,
        "MODELO 130",
        21,
        "AEAT",
        "TRIBUTOS",
        "MODELO_130",
        "Pago AEAT · Modelo 130",
        "130",
        1.0,
    ),
    (
        "AEAT_303_ADEUDO",
        None,
        "ADEUDO 303",
        30,
        "AEAT",
        "TRIBUTOS",
        "MODELO_303",
        "Pago AEAT · Modelo 303",
        "303",
        1.0,
    ),
    (
        "AEAT_303_MODELO",
        None,
        "MODELO 303",
        31,
        "AEAT",
        "TRIBUTOS",
        "MODELO_303",
        "Pago AEAT · Modelo 303",
        "303",
        1.0,
    ),
    (
        "AEAT_100_ADEUDO",
        None,
        "ADEUDO 100",
        40,
        "AEAT",
        "TRIBUTOS",
        "MODELO_100",
        "Pago AEAT · Modelo 100",
        "100",
        1.0,
    ),
    (
        "AEAT_100_MODELO",
        None,
        "MODELO 100",
        41,
        "AEAT",
        "TRIBUTOS",
        "MODELO_100",
        "Pago AEAT · Modelo 100",
        "100",
        1.0,
    ),
    (
        "TGSS_REGIMEN_GENERAL",
        None,
        "COTIZACION 001 REGIMEN GENERAL",
        50,
        "TGSS",
        "PERSONAL",
        "SEGURIDAD_SOCIAL_EMPRESA",
        "Cotización TGSS · Régimen General",
        None,
        1.0,
    ),
    (
        "TGSS_GENERAL",
        None,
        "TGSS",
        60,
        "TGSS",
        "PERSONAL",
        "SEGURIDAD_SOCIAL_OTROS",
        "Cotización TGSS",
        None,
        0.95,
    ),
    (
        "CAJA_RURAL_DESCUENTOS_COMERCIO",
        "CAJA_RURAL",
        "DESCUENTOS COMERCIO",
        70,
        "CAJA_RURAL",
        "GASTOS_FINANCIEROS",
        "COMISIONES_BANCARIAS",
        "Comisión bancaria · Caja Rural",
        None,
        1.0,
    ),
]


def _connect(
    db_path: str | Path = DB_PATH,
) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _normalize(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", text)


def ensure_schema(
    db_path: str | Path = DB_PATH,
) -> None:
    if not MIGRATION_PATH.exists():
        raise RuntimeError(
            f"No existe la migración {MIGRATION_PATH}"
        )

    with _connect(db_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

        if "eco_gastos" not in tables:
            raise RuntimeError(
                "No existe la tabla eco_gastos."
            )

        if "suppliers" not in tables:
            raise RuntimeError(
                "No existe la tabla suppliers."
            )

        conn.executescript(
            MIGRATION_PATH.read_text(
                encoding="utf-8"
            )
        )

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(eco_gastos)"
            ).fetchall()
        }

        for column, definition in (
            EXPENSE_COLUMNS.items()
        ):
            if column not in columns:
                conn.execute(
                    f"""
                    ALTER TABLE eco_gastos
                    ADD COLUMN {column} {definition}
                    """
                )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_eco_gastos_counterparty
            ON eco_gastos(counterparty_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_eco_gastos_expense_category
            ON eco_gastos(expense_category_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_eco_gastos_expense_subcategory
            ON eco_gastos(expense_subcategory_id)
            """
        )

        conn.commit()


def seed_catalogs(
    db_path: str | Path = DB_PATH,
) -> None:
    ensure_schema(db_path)

    with _connect(db_path) as conn:
        for code, name, order in CATEGORIES:
            conn.execute(
                """
                INSERT INTO economic_expense_categories (
                    code,
                    name,
                    sort_order,
                    active
                )
                VALUES (?, ?, ?, 1)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    sort_order = excluded.sort_order,
                    active = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (code, name, order),
            )

        category_ids = {
            row["code"]: int(row["id"])
            for row in conn.execute(
                """
                SELECT id, code
                FROM economic_expense_categories
                """
            ).fetchall()
        }

        for (
            category_code,
            code,
            name,
            order,
        ) in SUBCATEGORIES:
            conn.execute(
                """
                INSERT INTO
                economic_expense_subcategories (
                    category_id,
                    code,
                    name,
                    sort_order,
                    active
                )
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(code) DO UPDATE SET
                    category_id = excluded.category_id,
                    name = excluded.name,
                    sort_order = excluded.sort_order,
                    active = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    category_ids[category_code],
                    code,
                    name,
                    order,
                ),
            )

        for (
            code,
            counterparty_type,
            legal_name,
            trade_name,
            bank_name,
        ) in COUNTERPARTIES:
            conn.execute(
                """
                INSERT INTO economic_counterparties (
                    code,
                    counterparty_type,
                    legal_name,
                    trade_name,
                    bank_name,
                    active
                )
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(code) DO UPDATE SET
                    counterparty_type =
                        excluded.counterparty_type,
                    legal_name = excluded.legal_name,
                    trade_name = excluded.trade_name,
                    bank_name = excluded.bank_name,
                    active = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    code,
                    counterparty_type,
                    legal_name,
                    trade_name,
                    bank_name,
                ),
            )

        category_ids = {
            row["code"]: int(row["id"])
            for row in conn.execute(
                """
                SELECT id, code
                FROM economic_expense_categories
                """
            ).fetchall()
        }
        subcategory_ids = {
            row["code"]: int(row["id"])
            for row in conn.execute(
                """
                SELECT id, code
                FROM economic_expense_subcategories
                """
            ).fetchall()
        }
        counterparty_ids = {
            row["code"]: int(row["id"])
            for row in conn.execute(
                """
                SELECT id, code
                FROM economic_counterparties
                """
            ).fetchall()
        }

        for (
            code,
            bank_name,
            pattern,
            priority,
            counterparty_code,
            category_code,
            subcategory_code,
            suggested_concept,
            tax_model,
            confidence,
        ) in RULES:
            conn.execute(
                """
                INSERT INTO
                economic_movement_classification_rules (
                    code,
                    source_type,
                    bank_name,
                    match_type,
                    pattern,
                    priority,
                    counterparty_id,
                    category_id,
                    subcategory_id,
                    suggested_concept,
                    tax_model,
                    confidence,
                    requires_confirmation,
                    active
                )
                VALUES (
                    ?, 'bank', ?, 'CONTAINS', ?, ?,
                    ?, ?, ?, ?, ?, ?, 1, 1
                )
                ON CONFLICT(code) DO UPDATE SET
                    bank_name = excluded.bank_name,
                    pattern = excluded.pattern,
                    priority = excluded.priority,
                    counterparty_id =
                        excluded.counterparty_id,
                    category_id = excluded.category_id,
                    subcategory_id =
                        excluded.subcategory_id,
                    suggested_concept =
                        excluded.suggested_concept,
                    tax_model = excluded.tax_model,
                    confidence = excluded.confidence,
                    active = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    code,
                    bank_name,
                    pattern,
                    priority,
                    counterparty_ids[
                        counterparty_code
                    ],
                    category_ids[category_code],
                    subcategory_ids[
                        subcategory_code
                    ],
                    suggested_concept,
                    tax_model,
                    confidence,
                ),
            )

        conn.commit()


def list_rules(
    db_path: str | Path = DB_PATH,
) -> list[dict[str, Any]]:
    seed_catalogs(db_path)

    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                r.*,
                cp.code AS counterparty_code,
                cp.legal_name AS counterparty_name,
                cp.counterparty_type,
                c.code AS category_code,
                c.name AS category_name,
                s.code AS subcategory_code,
                s.name AS subcategory_name
            FROM economic_movement_classification_rules r
            LEFT JOIN economic_counterparties cp
              ON cp.id = r.counterparty_id
            JOIN economic_expense_categories c
              ON c.id = r.category_id
            JOIN economic_expense_subcategories s
              ON s.id = r.subcategory_id
            WHERE r.active = 1
            ORDER BY r.priority, r.id
            """
        ).fetchall()

    return [dict(row) for row in rows]


def suggest_for_movement(
    *,
    bank_name: str,
    concept: str,
    db_path: str | Path = DB_PATH,
) -> dict[str, Any] | None:
    normalized_bank = _normalize(bank_name)
    normalized_concept = _normalize(concept)

    if not normalized_concept:
        return None

    for rule in list_rules(db_path):
        rule_bank = _normalize(
            rule.get("bank_name")
        )

        if rule_bank and rule_bank != normalized_bank:
            continue

        pattern = _normalize(rule.get("pattern"))

        if pattern not in normalized_concept:
            continue

        result = dict(rule)
        result["classification_source"] = "RULE"
        result["matched"] = True
        return result

    return None


def classification_summary(
    db_path: str | Path = DB_PATH,
) -> dict[str, int]:
    seed_catalogs(db_path)

    with _connect(db_path) as conn:
        return {
            "categories": conn.execute(
                """
                SELECT COUNT(*)
                FROM economic_expense_categories
                WHERE active = 1
                """
            ).fetchone()[0],
            "subcategories": conn.execute(
                """
                SELECT COUNT(*)
                FROM economic_expense_subcategories
                WHERE active = 1
                """
            ).fetchone()[0],
            "counterparties": conn.execute(
                """
                SELECT COUNT(*)
                FROM economic_counterparties
                WHERE active = 1
                """
            ).fetchone()[0],
            "rules": conn.execute(
                """
                SELECT COUNT(*)
                FROM economic_movement_classification_rules
                WHERE active = 1
                """
            ).fetchone()[0],
        }
