from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.cashmatic_import_service import (  # noqa: E402
    DEFAULT_DB_PATH,
    get_cashmatic_import_summary,
    import_cashmatic_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Importa exportaciones Cashmatic a staging SQLite. "
            "No vincula automáticamente clientes, expedientes ni cobros."
        )
    )
    parser.add_argument("file", help="Ruta al archivo Cashmatic .csv o .xlsx")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"Ruta SQLite. Por defecto: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Ruta opcional para guardar el resultado JSON",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Muestra resumen acumulado tras importar",
    )

    args = parser.parse_args()

    result = import_cashmatic_file(args.file, db_path=args.db)
    data = asdict(result)

    print("")
    print("== Importación Cashmatic ==")
    print(f"DB: {result.db_path}")
    print(f"Archivo: {result.file_path}")
    print(f"SHA256: {result.file_sha256}")
    print(f"Batch ID: {result.batch_id}")
    print(f"Batch nuevo: {'sí' if result.batch_created else 'no'}")
    print(f"Filas archivo: {result.total_rows}")
    print(f"Filas insertadas: {result.inserted_rows}")
    print(f"Filas duplicadas/ignoradas: {result.duplicate_rows}")
    print(f"Candidatos a cobro manual: {result.candidate_payment_rows}")
    print(f"Cuarentena: {result.quarantine_rows}")
    print("")
    print("Política:")
    print(f"  {result.manual_linking_policy}")

    if args.summary:
        summary = get_cashmatic_import_summary(db_path=args.db)
        print("")
        print("== Resumen acumulado Cashmatic ==")
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("")
        print(f"Resultado JSON guardado en: {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
