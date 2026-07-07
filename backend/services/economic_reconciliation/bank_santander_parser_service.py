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


SANTANDER_EXPECTED_HEADERS = [
    "FECHA OPERACIÓN",
    "FECHA VALOR",
    "CONCEPTO",
    "IMPORTE EUR",
    "SALDO",
]


@dataclass(frozen=True)
class SantanderBankDiagnosticRow:
    row_number: int
    operation_date: str
    value_date: str
    concept: str
    amount_centimos: int
    balance_centimos: int
    movement_type: str
    movement_status: str
    row_hash: str
    warnings: list[str]


@dataclass(frozen=True)
class SantanderBankDiagnosticReport:
    source_file: str
    detected_format: str
    file_sha256: str
    export_timestamp: str | None
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
    rows: list[SantanderBankDiagnosticRow]


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


def parse_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
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

    # Soporta tanto "1.234,56" como "1234.56".
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


def cents_to_eur(value: int) -> float:
    return round(value / 100, 2)


def _find_soffice() -> str:
    candidate = shutil.which("soffice") or shutil.which("libreoffice")
    if not candidate:
        raise RuntimeError(
            "No se encontró LibreOffice/soffice para convertir .xls Santander. "
            "Instala LibreOffice, instala xlrd con `python -m pip install xlrd`, "
            "o exporta el movimiento bancario en CSV."
        )
    return candidate


def _read_xls_with_xlrd(path: Path) -> list[list[str]]:
    """Lee .xls Santander directamente sin LibreOffice.

    Santander exporta en formato Excel antiguo BIFF. xlrd sigue siendo
    adecuado para .xls y evita depender de soffice en Windows.
    """
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
                # Evita "123.0" en campos visuales cuando sea entero.
                if float(value).is_integer():
                    row.append(str(int(value)))
                else:
                    row.append(str(value))
            else:
                row.append(clean_text(value))
        rows.append(row)

    return rows


def _convert_xls_to_csv(path: Path) -> Path:
    soffice = _find_soffice()

    tmpdir = Path(tempfile.mkdtemp(prefix="santander_xls_"))
    cmd = [
        soffice,
        "--headless",
        "--convert-to",
        "csv",
        "--outdir",
        str(tmpdir),
        str(path),
    ]

    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "No se pudo convertir .xls Santander a CSV. "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )

    csv_files = list(tmpdir.glob("*.csv"))
    if not csv_files:
        raise RuntimeError(
            "LibreOffice no generó CSV al convertir Santander. "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )

    return csv_files[0]


def read_santander_sheet_rows(path: str | Path) -> tuple[list[list[str]], str]:
    path = Path(path)

    if path.suffix.lower() == ".csv":
        csv_path = path
        detected_format = "csv"

        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with csv_path.open("r", encoding=encoding, newline="") as fh:
                    rows = list(csv.reader(fh))
                return rows, detected_format
            except UnicodeDecodeError:
                continue

        raise UnicodeDecodeError("santander", b"", 0, 1, "No se pudo decodificar archivo Santander")

    if path.suffix.lower() == ".xls":
        try:
            return _read_xls_with_xlrd(path), "xls"
        except RuntimeError:
            # Fallback si xlrd no está disponible.
            csv_path = _convert_xls_to_csv(path)
            for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                try:
                    with csv_path.open("r", encoding=encoding, newline="") as fh:
                        rows = list(csv.reader(fh))
                    return rows, "xls"
                except UnicodeDecodeError:
                    continue
            raise UnicodeDecodeError("santander", b"", 0, 1, "No se pudo decodificar CSV convertido")

    if path.suffix.lower() == ".xlsx":
        csv_path = _convert_xls_to_csv(path)
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with csv_path.open("r", encoding=encoding, newline="") as fh:
                    rows = list(csv.reader(fh))
                return rows, "xlsx"
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError("santander", b"", 0, 1, "No se pudo decodificar CSV convertido")

    raise ValueError(f"Formato Santander no soportado: {path.suffix}")


def _find_header_index(rows: list[list[str]]) -> int:
    expected = [x.upper() for x in SANTANDER_EXPECTED_HEADERS]

    for idx, row in enumerate(rows):
        normalized = [clean_text(x).upper() for x in row[:5]]
        if normalized == expected:
            return idx

    raise ValueError(
        "No se encontró cabecera Santander esperada: "
        f"{SANTANDER_EXPECTED_HEADERS}"
    )


def _extract_export_timestamp(rows: list[list[str]]) -> str | None:
    for row in rows[:8]:
        for cell in row:
            text = clean_text(cell)
            if "|" in text:
                return text
    return None


def classify_santander_movement(concept: str, amount_centimos: int) -> tuple[str, str, list[str]]:
    concept_clean = clean_text(concept)
    concept_upper = concept_clean.upper()
    warnings: list[str] = []

    if not concept_clean:
        return "UNKNOWN", "QUARANTINE", ["Concepto vacío"]

    if amount_centimos == 0:
        warnings.append("Importe cero")

    if concept_upper.startswith("LIQUIDACION EFECTUADA"):
        movement_type = "SANTANDER_SETTLEMENT_INCOME"
    elif concept_upper.startswith("TRANSFERENCIA A FAVOR"):
        movement_type = "BANK_TRANSFER_OUT"
    elif concept_upper.startswith("TRANSFERENCIA"):
        movement_type = "BANK_TRANSFER"
    elif concept_upper.startswith("COBRO TARIFA"):
        movement_type = "BANK_FEE"
    elif concept_upper.startswith("COMPRA"):
        movement_type = "CARD_PURCHASE"
    elif concept_upper.startswith("ANUL COMPRA"):
        movement_type = "CARD_PURCHASE_REFUND"
    elif "REGULARIZACION CUENTA DE INCIDENCIAS" in concept_upper:
        movement_type = "BANK_INCIDENT_REGULARIZATION"
    else:
        movement_type = "BANK_OTHER_INCOME" if amount_centimos > 0 else "BANK_OTHER_EXPENSE"

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


def diagnose_santander_bank_file(path: str | Path) -> SantanderBankDiagnosticReport:
    path = Path(path)
    rows_raw, detected_format = read_santander_sheet_rows(path)
    header_idx = _find_header_index(rows_raw)
    export_timestamp = _extract_export_timestamp(rows_raw)

    parsed_rows: list[SantanderBankDiagnosticRow] = []

    total_income = 0
    total_expense = 0
    income_rows = 0
    expense_rows = 0
    quarantine_rows = 0
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    operation_dates: list[str] = []

    for idx, raw in enumerate(rows_raw[header_idx + 1 :], start=header_idx + 2):
        padded = [*raw, "", "", "", "", ""][:5]

        operation_date = parse_date(padded[0])
        value_date = parse_date(padded[1])
        concept = clean_text(padded[2])

        # Saltar líneas completamente vacías.
        if not any(clean_text(x) for x in padded):
            continue

        warnings: list[str] = []

        if not operation_date:
            warnings.append(f"Fecha operación inválida: {padded[0]!r}")
        if not value_date:
            warnings.append(f"Fecha valor inválida: {padded[1]!r}")

        try:
            amount_centimos = parse_money_to_centimos(padded[3])
        except ValueError as exc:
            amount_centimos = 0
            warnings.append(str(exc))

        try:
            balance_centimos = parse_money_to_centimos(padded[4])
        except ValueError as exc:
            balance_centimos = 0
            warnings.append(str(exc))

        movement_type, movement_status, type_warnings = classify_santander_movement(
            concept,
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
            "operation_date": operation_date,
            "value_date": value_date,
            "concept": concept,
            "amount_centimos": amount_centimos,
            "balance_centimos": balance_centimos,
        }

        parsed_rows.append(
            SantanderBankDiagnosticRow(
                row_number=idx,
                operation_date=operation_date,
                value_date=value_date,
                concept=concept,
                amount_centimos=amount_centimos,
                balance_centimos=balance_centimos,
                movement_type=movement_type,
                movement_status=movement_status,
                row_hash=_row_hash(hash_payload),
                warnings=warnings,
            )
        )

    return SantanderBankDiagnosticReport(
        source_file=path.name,
        detected_format=detected_format,
        file_sha256=file_sha256(path),
        export_timestamp=export_timestamp,
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


def report_to_dict(report: SantanderBankDiagnosticReport, include_rows: bool = False) -> dict[str, Any]:
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
