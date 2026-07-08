from __future__ import annotations

import inspect
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DB_PATH = PROJECT_ROOT / "database" / "quesada.db"


def print_section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def table_count(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()
        return int(row["total"] or 0)
    except Exception as exc:
        print(f"{table}: ERROR {exc}")
        return None


def latest_rows(conn: sqlite3.Connection, table: str, limit: int = 10) -> None:
    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM {table}
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    except Exception as exc:
        print(f"{table}: ERROR leyendo últimas filas: {exc}")
        return

    for row in rows:
        d = dict(row)
        compact = {
            k: d.get(k)
            for k in [
                "id",
                "bank_name",
                "account_label",
                "operation_date",
                "value_date",
                "amount_centimos",
                "concept",
                "movement_status",
                "review_status",
                "created_at",
            ]
            if k in d
        }
        print(compact)


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print_section("DB bank tables")
    for table in ["bank_import_batches", "bank_movements", "cashmatic_movements"]:
        print(table, table_count(conn, table))

    print_section("Últimos batches bancarios")
    try:
        batch_cols = [r["name"] for r in conn.execute("PRAGMA table_info(economic_import_batches)").fetchall()]
        print("economic_import_batches columns:", batch_cols)

        select_cols = [
            c for c in [
                "id",
                "source_type",
                "source_file_name",
                "source_file",
                "file_sha256",
                "source_file_sha256",
                "total_rows",
                "imported_rows",
                "inserted_rows",
                "candidate_payment_rows",
                "quarantine_rows",
                "created_at",
            ]
            if c in batch_cols
        ]

        if not select_cols:
            print("No hay columnas reconocidas en economic_import_batches.")
        else:
            rows = conn.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM economic_import_batches
                WHERE source_type LIKE 'BANK_%'
                ORDER BY id DESC
                LIMIT 20
                """
            ).fetchall()

            for row in rows:
                print(dict(row))

    except Exception as exc:
        print("ERROR leyendo economic_import_batches:", exc)

    print_section("Últimos movimientos bancarios")
    latest_rows(conn, "bank_movements", 15)

    print_section("Servicios import bancario")
    try:
        import backend.services.economic_reconciliation.bank_import_service as svc
        print("bank_import_service:", svc.__file__)
        names = [n for n in dir(svc) if "import" in n.lower() or "parse" in n.lower() or "bank" in n.lower()]
        print("funciones candidatas:", names)

        for name in names:
            obj = getattr(svc, name, None)
            if callable(obj):
                try:
                    sig = inspect.signature(obj)
                except Exception:
                    sig = "?"
                print(f"- {name}{sig}")
    except Exception as exc:
        print("ERROR importando bank_import_service:", repr(exc))

    print_section("Referencias UI import")
    try:
        text = Path("frontend/views/economic_view.py").read_text(encoding="utf-8")
        for needle in [
            "bank_import",
            "import_bank",
            "bank_import_service",
            "import_selected",
            "file_picker",
            "FilePicker",
            "bank_movements",
            "Santander",
            "Caja Rural",
            "ING",
        ]:
            print(needle, text.find(needle))
    except Exception as exc:
        print("ERROR leyendo economic_view.py:", exc)

    conn.close()


if __name__ == "__main__":
    main()
