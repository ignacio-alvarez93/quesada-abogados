from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ING_EXPECTED_HEADERS = [
    "F. VALOR",
    "CATEGORÍA",
    "SUBCATEGORÍA",
    "DESCRIPCIÓN",
    "COMENTARIO",
    "IMPORTE (€)",
    "SALDO (€)",
]


@dataclass(frozen=True)
class IngBankDiagnosticRow:
    row_number: int
    operation_date: str
    value_date: str
    category: str
    subcategory: str
    description: str
    comment: str
    concept: str
    amount_centimos: int
    balance_centimos: int
    movement_type: str
    movement_status: str
    row_hash: str
    warnings: list[str]


@dataclass(frozen=True)
class IngBankDiagnosticReport:
    source_file: str
    detected_format: str
    file_sha256: str
    total_rows: int
    valid_rows: int
    quarantine_rows: int
    income_rows: int
    expense_rows: int
    first_operation_date: str | None
    last_operation_date: str | None
    total_income_centimos: int
    total_expense_centimos: int
    net_amount_centimos: int
    by_type: dict[str, int]
    by_status: dict[str, int]
    rows: list[IngBankDiagnosticRow]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\xa0", " ").strip()


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cents_to_eur(value: int | None) -> float:
    return round((int(value or 0) / 100), 2)


def parse_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return ""


def parse_money_to_centimos(value: Any) -> int:
    text = clean_text(value)
    if not text:
        return 0

    text = text.replace("€", "").replace("EUR", "").strip()
    text = text.replace(" ", "")

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")

    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Importe inválido: {value!r}") from exc

    cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _find_soffice() -> str:
    candidate = shutil.which("soffice") or shutil.which("libreoffice")
    if not candidate:
        raise RuntimeError(
            "No se encontró LibreOffice/soffice para convertir .xls ING. "
            "Exporta ING en CSV o instala LibreOffice."
        )
    return candidate


def _convert_xls_to_csv(path: Path) -> Path:
    soffice = _find_soffice()

    tmpdir = Path(tempfile.mkdtemp(prefix="ing_xls_"))
    completed = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "csv",
            "--outdir",
            str(tmpdir),
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "No se pudo convertir .xls ING a CSV. "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )

    csv_files = list(tmpdir.glob("*.csv"))
    if not csv_files:
        raise RuntimeError(
            "LibreOffice no generó CSV al convertir ING. "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )

    return csv_files[0]


def _read_xls_with_xlrd(path: Path) -> list[list[str]]:
    try:
        import xlrd  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "No está instalado xlrd. Ejecuta: python -m pip install xlrd"
        ) from exc

    workbook = xlrd.open_workbook(str(path))
    sheet = workbook.sheet_by_index(0)

    rows: list[list[str]] = []
    for r in range(sheet.nrows):
        row: list[str] = []
        for c in range(sheet.ncols):
            cell = sheet.cell(r, c)
            value = cell.value

            if cell.ctype == xlrd.XL_CELL_DATE:
                try:
                    dt = xlrd.xldate_as_datetime(value, workbook.datemode)
                    row.append(dt.strftime("%d/%m/%Y"))
                except Exception:
                    row.append(clean_text(value))
            elif cell.ctype == xlrd.XL_CELL_NUMBER:
                if float(value).is_integer():
                    row.append(str(int(value)))
                else:
                    row.append(str(value))
            else:
                row.append(clean_text(value))
        rows.append(row)

    return rows


def read_ing_sheet_rows(path: str | Path) -> tuple[list[list[str]], str]:
    path = Path(path)

    if path.suffix.lower() == ".csv":
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with path.open("r", encoding=encoding, newline="") as fh:
                    return list(csv.reader(fh)), "csv"
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError("ing", b"", 0, 1, "No se pudo decodificar archivo ING")

    if path.suffix.lower() == ".xls":
        try:
            return _read_xls_with_xlrd(path), "xls"
        except RuntimeError:
            csv_path = _convert_xls_to_csv(path)
            for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                try:
                    with csv_path.open("r", encoding=encoding, newline="") as fh:
                        return list(csv.reader(fh)), "xls"
                except UnicodeDecodeError:
                    continue
            raise UnicodeDecodeError("ing", b"", 0, 1, "No se pudo decodificar CSV convertido")

    raise ValueError(f"Formato ING no soportado: {path.suffix}")


def _find_header_index(rows: list[list[str]]) -> int:
    expected = [x.upper() for x in ING_EXPECTED_HEADERS]

    for idx, row in enumerate(rows):
        normalized = [clean_text(x).upper() for x in row[:7]]
        if normalized == expected:
            return idx

    raise ValueError(f"No se encontró cabecera ING esperada: {ING_EXPECTED_HEADERS}")


def classify_ing_movement(
    concept: str,
    category: str,
    subcategory: str,
    amount_centimos: int,
) -> tuple[str, str, list[str]]:
    concept_clean = clean_text(concept)
    category_upper = clean_text(category).upper()
    subcategory_upper = clean_text(subcategory).upper()
    concept_upper = concept_clean.upper()

    warnings: list[str] = []

    if not concept_clean:
        return "UNKNOWN", "QUARANTINE", ["Concepto vacío"]

    if amount_centimos == 0:
        warnings.append("Importe cero")

    if "TRANSFERENCIA RECIBIDA STRIPE" in concept_upper or "STRIPE" in concept_upper:
        movement_type = "ING_STRIPE_TRANSFER_IN"
    elif "TRANSFERENCIA RECIBIDA" in concept_upper:
        movement_type = "BANK_TRANSFER_IN"
    elif "TRANSFERENCIA EMITIDA" in concept_upper or "TRANSFERENCIA ENVIADA" in concept_upper:
        movement_type = "BANK_TRANSFER_OUT"
    elif concept_upper.startswith("RECIBO") or "RECIBOS" in category_upper:
        movement_type = "BANK_DIRECT_DEBIT"
    elif concept_upper.startswith("BIZUM ENVIADO"):
        movement_type = "BIZUM_OUT"
    elif concept_upper.startswith("BIZUM RECIBIDO"):
        movement_type = "BIZUM_IN"
    elif concept_upper.startswith("PAGO EN") or "TARJETA" in category_upper:
        movement_type = "CARD_PURCHASE" if amount_centimos < 0 else "CARD_REFUND_OR_INCOME"
    elif "COMISION" in concept_upper or "COMISIÓN" in concept_upper:
        movement_type = "BANK_FEE"
    elif amount_centimos > 0:
        movement_type = "BANK_OTHER_INCOME"
    else:
        movement_type = "BANK_OTHER_EXPENSE"

    if amount_centimos > 0:
        movement_status = "BANK_INCOME_REVIEW_REQUIRED"
    elif amount_centimos < 0:
        movement_status = "BANK_EXPENSE_REVIEW_REQUIRED"
    else:
        movement_status = "BANK_ZERO_AMOUNT_REVIEW_REQUIRED"

    return movement_type, movement_status, warnings


def _row_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def diagnose_ing_bank_file(path: str | Path) -> IngBankDiagnosticReport:
    path = Path(path)
    rows_raw, detected_format = read_ing_sheet_rows(path)
    header_idx = _find_header_index(rows_raw)

    parsed_rows: list[IngBankDiagnosticRow] = []

    total_income = 0
    total_expense = 0
    income_rows = 0
    expense_rows = 0
    quarantine_rows = 0
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    operation_dates: list[str] = []

    for idx, raw in enumerate(rows_raw[header_idx + 1 :], start=header_idx + 2):
        padded = [*raw, "", "", "", "", "", "", ""][:7]

        if not any(clean_text(x) for x in padded):
            continue

        value_date = parse_date(padded[0])
        operation_date = value_date
        category = clean_text(padded[1])
        subcategory = clean_text(padded[2])
        description = clean_text(padded[3])
        comment = clean_text(padded[4])

        concept_parts = [description]
        if comment:
            concept_parts.append(comment)
        if category or subcategory:
            concept_parts.append(f"[{category} / {subcategory}]")
        concept = " ".join(x for x in concept_parts if x).strip()

        warnings: list[str] = []

        if not operation_date:
            warnings.append(f"Fecha valor inválida: {padded[0]!r}")

        try:
            amount_centimos = parse_money_to_centimos(padded[5])
        except ValueError as exc:
            amount_centimos = 0
            warnings.append(str(exc))

        try:
            balance_centimos = parse_money_to_centimos(padded[6])
        except ValueError as exc:
            balance_centimos = 0
            warnings.append(str(exc))

        movement_type, movement_status, type_warnings = classify_ing_movement(
            concept,
            category,
            subcategory,
            amount_centimos,
        )
        warnings.extend(type_warnings)

        if warnings:
            movement_status = "QUARANTINE"

        if movement_status == "QUARANTINE":
            quarantine_rows += 1

        if amount_centimos > 0:
            income_rows += 1
            total_income += amount_centimos
        elif amount_centimos < 0:
            expense_rows += 1
            total_expense += amount_centimos

        if operation_date:
            operation_dates.append(operation_date)

        by_type[movement_type] = by_type.get(movement_type, 0) + 1
        by_status[movement_status] = by_status.get(movement_status, 0) + 1

        hash_payload = {
            "bank_name": "ING",
            "operation_date": operation_date,
            "value_date": value_date,
            "category": category,
            "subcategory": subcategory,
            "description": description,
            "comment": comment,
            "amount_centimos": amount_centimos,
            "balance_centimos": balance_centimos,
        }

        parsed_rows.append(
            IngBankDiagnosticRow(
                row_number=idx,
                operation_date=operation_date,
                value_date=value_date,
                category=category,
                subcategory=subcategory,
                description=description,
                comment=comment,
                concept=concept,
                amount_centimos=amount_centimos,
                balance_centimos=balance_centimos,
                movement_type=movement_type,
                movement_status=movement_status,
                row_hash=_row_hash(hash_payload),
                warnings=warnings,
            )
        )

    return IngBankDiagnosticReport(
        source_file=path.name,
        detected_format=detected_format,
        file_sha256=file_sha256(path),
        total_rows=len(parsed_rows),
        valid_rows=len(parsed_rows) - quarantine_rows,
        quarantine_rows=quarantine_rows,
        income_rows=income_rows,
        expense_rows=expense_rows,
        first_operation_date=min(operation_dates) if operation_dates else None,
        last_operation_date=max(operation_dates) if operation_dates else None,
        total_income_centimos=total_income,
        total_expense_centimos=total_expense,
        net_amount_centimos=total_income + total_expense,
        by_type=dict(sorted(by_type.items())),
        by_status=dict(sorted(by_status.items())),
        rows=parsed_rows,
    )


def report_to_dict(report: IngBankDiagnosticReport, include_rows: bool = False) -> dict[str, Any]:
    data = asdict(report)
    data["total_income_eur"] = cents_to_eur(report.total_income_centimos)
    data["total_expense_eur"] = cents_to_eur(report.total_expense_centimos)
    data["net_amount_eur"] = cents_to_eur(report.net_amount_centimos)

    if not include_rows:
        data.pop("rows", None)
    else:
        for row in data["rows"]:
            row["amount_eur"] = cents_to_eur(row["amount_centimos"])
            row["balance_eur"] = cents_to_eur(row["balance_centimos"])

    return data
