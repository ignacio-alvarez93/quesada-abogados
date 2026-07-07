from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.cashmatic_parser_service import (  # noqa: E402
    cents_to_eur,
    diagnose_cashmatic_file,
    report_to_dict,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnóstico seguro de exportaciones Cashmatic CSV/XLSX. No toca DB ni vistas."
    )
    parser.add_argument("file", help="Ruta al archivo Cashmatic .csv o .xlsx")
    parser.add_argument(
        "--json-out",
        default="",
        help="Ruta opcional para guardar resumen JSON",
    )
    parser.add_argument(
        "--rows-jsonl-out",
        default="",
        help="Ruta opcional para guardar filas normalizadas JSONL",
    )

    args = parser.parse_args()

    report, rows = diagnose_cashmatic_file(args.file)
    report_dict = report_to_dict(report)

    print("")
    print("== Diagnóstico Cashmatic ==")
    print(f"Archivo: {report.file_name}")
    print(f"Formato: {report.detected_format}")
    print(f"SHA256: {report.file_sha256}")
    print(f"Filas totales: {report.total_rows}")
    print(f"Filas válidas: {report.valid_rows}")
    print(f"Filas cuarentena: {report.quarantine_rows}")
    print(f"Candidatos a cobro manual: {report.candidate_payment_rows}")
    print(f"Rango fechas: {report.first_start_time or '-'} -> {report.last_start_time or '-'}")
    print("")
    print("Operaciones:")
    for key, value in report.operations_count.items():
        print(f"  - {key}: {value}")
    print("")
    print("Estados:")
    for key, value in report.status_count.items():
        print(f"  - {key}: {value}")
    print("")
    print("Totales candidatos:")
    print(f"  REQUESTED: {cents_to_eur(report.total_candidate_requested_centimos)} €")
    print(f"  INSERTED:  {cents_to_eur(report.total_candidate_inserted_centimos)} €")
    print(f"  DISPENSED: {cents_to_eur(report.total_candidate_dispensed_centimos)} €")
    print(f"  NETO:      {cents_to_eur(report.total_candidate_net_centimos)} €")
    print("")
    print("Política:")
    print(f"  {report.manual_linking_policy}")

    if report.sample_quarantine:
        print("")
        print("Muestra cuarentena:")
        for row in report.sample_quarantine[:5]:
            print(
                "  - "
                f"fila={row.get('row_number')} "
                f"id={row.get('cashmatic_id')} "
                f"operation={row.get('operation')} "
                f"reason={row.get('reason_raw')}"
            )

    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(report_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("")
        print(f"Resumen JSON guardado en: {json_path}")

    if args.rows_jsonl_out:
        rows_path = Path(args.rows_jsonl_out)
        rows_path.parent.mkdir(parents=True, exist_ok=True)
        with rows_path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
        print(f"Filas normalizadas JSONL guardadas en: {rows_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
