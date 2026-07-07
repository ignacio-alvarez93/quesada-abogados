from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.bank_import_service import (  # noqa: E402
    get_bank_import_summary,
    import_santander_bank_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importa exportación bancaria Santander a staging económico."
    )
    parser.add_argument("file")
    parser.add_argument("--db", default="database/quesada.db")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--summary", action="store_true")

    args = parser.parse_args()

    result = import_santander_bank_file(args.file, db_path=args.db)

    print("")
    print("== Importación Banco Santander ==")
    print(f"DB: {args.db}")
    print(f"Archivo: {args.file}")
    print(f"SHA256: {result.file_sha256}")
    print(f"Batch ID: {result.batch_id}")
    print(f"Batch nuevo: {'sí' if result.batch_created else 'no'}")
    print(f"Movimientos archivo: {result.total_rows}")
    print(f"Movimientos insertados: {result.inserted_rows}")
    print(f"Duplicados/ignorados: {result.duplicate_rows}")
    print(f"Ingresos: {result.income_rows}")
    print(f"Gastos/cargos: {result.expense_rows}")
    print(f"Cuarentena: {result.quarantine_rows}")
    print("")
    print("Política:")
    print(f"  {result.manual_linking_policy}")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON escrito en: {args.json_out}")

    if args.summary:
        print("")
        print("== Resumen acumulado Banco ==")
        print(json.dumps(get_bank_import_summary(db_path=args.db), ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
