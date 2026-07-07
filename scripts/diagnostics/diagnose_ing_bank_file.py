from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.bank_ing_parser_service import (  # noqa: E402
    cents_to_eur,
    diagnose_ing_bank_file,
    report_to_dict,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnóstico de exportación bancaria ING."
    )
    parser.add_argument("file")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--jsonl-out", default="")
    parser.add_argument("--show-rows", type=int, default=10)

    args = parser.parse_args()

    report = diagnose_ing_bank_file(args.file)

    print("")
    print("== Diagnóstico Banco ING ==")
    print(f"Archivo: {report.source_file}")
    print(f"Formato: {report.detected_format}")
    print(f"SHA256: {report.file_sha256}")
    print(f"Movimientos: {report.total_rows}")
    print(f"Válidos: {report.valid_rows}")
    print(f"Cuarentena: {report.quarantine_rows}")
    print(f"Ingresos: {report.income_rows}")
    print(f"Gastos/cargos: {report.expense_rows}")
    print(f"Rango fechas: {report.first_operation_date or '-'} -> {report.last_operation_date or '-'}")
    print("")
    print("Totales:")
    print(f"  Ingresos: {cents_to_eur(report.total_income_centimos)} €")
    print(f"  Gastos:   {cents_to_eur(report.total_expense_centimos)} €")
    print(f"  Neto:     {cents_to_eur(report.net_amount_centimos)} €")

    print("")
    print("Tipos:")
    for key, value in report.by_type.items():
        print(f"  - {key}: {value}")

    print("")
    print("Estados:")
    for key, value in report.by_status.items():
        print(f"  - {key}: {value}")

    print("")
    print("Muestra movimientos:")
    for row in report.rows[: max(0, args.show_rows)]:
        print(
            f"  - fila={row.row_number} fecha={row.operation_date} "
            f"importe={cents_to_eur(row.amount_centimos)} € "
            f"tipo={row.movement_type} estado={row.movement_status} "
            f"concepto={row.concept[:120]}"
        )

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(
            json.dumps(report_to_dict(report, include_rows=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON escrito en: {args.json_out}")

    if args.jsonl_out:
        Path(args.jsonl_out).parent.mkdir(parents=True, exist_ok=True)
        with Path(args.jsonl_out).open("w", encoding="utf-8") as fh:
            for row in report.rows:
                fh.write(json.dumps(row.__dict__, ensure_ascii=False) + "\n")
        print(f"JSONL escrito en: {args.jsonl_out}")

    print("")
    print("Política:")
    print("  ING se diagnostica como movimiento bancario bruto. No crea cobros, facturas ni vínculos automáticos.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
