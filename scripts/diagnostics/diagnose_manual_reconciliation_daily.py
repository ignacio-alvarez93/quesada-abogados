from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.economic_reconciliation.manual_reconciliation_summary_service import (  # noqa: E402
    cents_to_eur,
    get_daily_manual_reconciliation_summary,
    get_daily_manual_reconciliation_summary_dict,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnóstico diario de conciliación manual por fuentes."
    )
    parser.add_argument("--db", default="database/quesada.db")
    parser.add_argument("--from", dest="date_from", default="")
    parser.add_argument("--to", dest="date_to", default="")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--json-out", default="")

    args = parser.parse_args()

    rows = get_daily_manual_reconciliation_summary(
        db_path=args.db,
        date_from=args.date_from or None,
        date_to=args.date_to or None,
        limit=args.limit,
    )

    print("")
    print("== Diagnóstico conciliación manual diaria ==")
    print(f"DB: {args.db}")
    print(f"Rango: {args.date_from or '-'} -> {args.date_to or '-'}")
    print(f"Días: {len(rows)}")
    print("")
    print("Política:")
    print("  Diagnóstico solo informativo. No crea cobros, facturas ni vínculos automáticos.")
    print("")

    for row in rows:
        print(
            f"- {row.date} | "
            f"Banco ingresos={cents_to_eur(row.bank_income_centimos)} € "
            f"gastos={cents_to_eur(row.bank_expense_centimos)} € "
            f"neto={cents_to_eur(row.bank_net_centimos)} € "
            f"movs={row.bank_movements} sin_vincular={row.bank_unlinked_movements} | "
            f"Cashmatic candidatos={cents_to_eur(row.cashmatic_candidate_centimos)} € "
            f"movs={row.cashmatic_candidate_movements} "
            f"rev={row.cashmatic_review_movements} cuar={row.cashmatic_quarantine_movements} | "
            f"dif_ingresos_banco_vs_cashmatic={cents_to_eur(row.difference_bank_income_vs_cashmatic_centimos)} €"
        )

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(
            json.dumps(
                get_daily_manual_reconciliation_summary_dict(
                    db_path=args.db,
                    date_from=args.date_from or None,
                    date_to=args.date_to or None,
                    limit=args.limit,
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("")
        print(f"JSON escrito en: {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
