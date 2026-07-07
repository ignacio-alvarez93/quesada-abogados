from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zipfile import ZipFile
import re
import xml.etree.ElementTree as ET


CAJA_RURAL_EXPECTED_HEADERS = [
    "Fecha de la operación",
    "Fecha valor",
    "Tipo movimiento",
    "Importe",
    "Saldo",
    "Nro. Apunte",
]


@dataclass(frozen=True)
class CajaRuralBankDiagnosticRow:
    row_number: int
    operation_date: str
    value_date: str
    concept: str
    amount_centimos: int
    balance_centimos: int
    statement_number: str
    movement_type: str
    movement_status: str
    row_hash: str
    warnings: list[str]


@dataclass(frozen=True)
class CajaRuralBankDiagnosticReport:
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
    rows: list[CajaRuralBankDiagnosticRow]


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


def parse_money_to_centimos(value: Any) -> int:
    if isinstance(value, int):
        return value * 100

    if isinstance(value, float):
        amount = Decimal(str(value))
    else:
        text = clean_text(value)
        if not text:
            return 0

        text = text.replace("€", "").replace("EUR", "").replace(" ", "")

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


def parse_excel_date(value: Any) -> str:
    if isinstance(value, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).strftime("%Y-%m-%d")

    text = clean_text(value)
    if not text:
        return ""

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return ""


def _xlsx_col(ref: str) -> str:
    match = re.match(r"([A-Z]+)", ref)
    return match.group(1) if match else ""


def _load_shared_strings(zip_file: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []

    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    values: list[str] = []

    for si in root.findall("a:si", ns):
        texts = [t.text or "" for t in si.findall(".//a:t", ns)]
        values.append("".join(texts))

    return values


def _read_xlsx_first_sheet(path: Path) -> list[list[Any]]:
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    with ZipFile(path) as zf:
        shared_strings = _load_shared_strings(zf)

        sheet_names = [name for name in zf.namelist() if name.startswith("xl/worksheets/sheet")]
        if not sheet_names:
            raise ValueError("No se encontró ninguna hoja en el XLSX Caja Rural.")

        sheet_xml = sorted(sheet_names)[0]
        root = ET.fromstring(zf.read(sheet_xml))

        rows: list[list[Any]] = []
        max_col = 0
        raw_rows: list[dict[str, Any]] = []

        for row in root.findall(".//a:sheetData/a:row", ns):
            parsed: dict[str, Any] = {}
            for cell in row.findall("a:c", ns):
                ref = cell.attrib.get("r", "")
                col = _xlsx_col(ref)
                value_node = cell.find("a:v", ns)

                if not col:
                    continue

                if value_node is None:
                    value: Any = None
                elif cell.attrib.get("t") == "s":
                    value = shared_strings[int(value_node.text or "0")]
                else:
                    raw = value_node.text or ""
                    try:
                        value = float(raw)
                        if value.is_integer():
                            value = int(value)
                    except Exception:
                        value = raw

                parsed[col] = value
                max_col = max(max_col, _col_to_index(col))

            raw_rows.append(parsed)

        for parsed in raw_rows:
            row_values = []
            for index in range(1, max_col + 1):
                row_values.append(parsed.get(_index_to_col(index)))
            rows.append(row_values)

        return rows


def _col_to_index(col: str) -> int:
    result = 0
    for char in col:
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result


def _index_to_col(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def read_caja_rural_sheet_rows(path: str | Path) -> tuple[list[list[Any]], str]:
    path = Path(path)

    if path.suffix.lower() != ".xlsx":
        raise ValueError(f"Formato Caja Rural no soportado: {path.suffix}. Esperado .xlsx")

    return _read_xlsx_first_sheet(path), "xlsx"


def _find_header_index(rows: list[list[Any]]) -> int:
    expected = [x.upper() for x in CAJA_RURAL_EXPECTED_HEADERS]

    for idx, row in enumerate(rows):
        normalized = [clean_text(x).upper() for x in row[:6]]
        if normalized == expected:
            return idx

    raise ValueError(
        "No se encontró cabecera Caja Rural esperada: "
        f"{CAJA_RURAL_EXPECTED_HEADERS}"
    )


def classify_caja_rural_movement(
    concept: str,
    amount_centimos: int,
) -> tuple[str, str, list[str]]:
    concept_clean = clean_text(concept)
    concept_upper = concept_clean.upper()
    warnings: list[str] = []

    if not concept_clean:
        return "UNKNOWN", "QUARANTINE", ["Concepto vacío"]

    if amount_centimos == 0:
        warnings.append("Importe cero")

    if concept_upper.startswith("TRF."):
        movement_type = "BANK_TRANSFER_IN" if amount_centimos > 0 else "BANK_TRANSFER_OUT"
    elif "FACTURACION COMERCIO" in concept_upper:
        movement_type = "CAJA_RURAL_CARD_SETTLEMENT_INCOME"
    elif "DESCUENTOS COMERCIO" in concept_upper:
        movement_type = "CAJA_RURAL_CARD_FEE"
    elif concept_upper.startswith("RCBO."):
        movement_type = "BANK_DIRECT_DEBIT"
    elif "REGULARISACION" in concept_upper or "REGULARIZACION" in concept_upper:
        movement_type = "BANK_REGULARIZATION"
    elif concept_upper.startswith("ABONO"):
        movement_type = "BANK_OTHER_INCOME"
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


def diagnose_caja_rural_bank_file(path: str | Path) -> CajaRuralBankDiagnosticReport:
    path = Path(path)
    rows_raw, detected_format = read_caja_rural_sheet_rows(path)
    header_idx = _find_header_index(rows_raw)

    parsed_rows: list[CajaRuralBankDiagnosticRow] = []

    total_income = 0
    total_expense = 0
    income_rows = 0
    expense_rows = 0
    quarantine_rows = 0
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    operation_dates: list[str] = []

    for idx, raw in enumerate(rows_raw[header_idx + 1 :], start=header_idx + 2):
        padded = [*raw, None, None, None, None, None, None][:6]

        if not any(clean_text(x) for x in padded):
            continue

        operation_date = parse_excel_date(padded[0])
        value_date = parse_excel_date(padded[1])
        concept = clean_text(padded[2])
        statement_number = clean_text(padded[5])

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

        movement_type, movement_status, type_warnings = classify_caja_rural_movement(
            concept,
            amount_centimos,
        )
        warnings.extend(type_warnings)

        if not statement_number:
            warnings.append("Nro. Apunte vacío")

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
            "bank_name": "CAJA_RURAL",
            "operation_date": operation_date,
            "value_date": value_date,
            "statement_number": statement_number,
            "concept": concept,
            "amount_centimos": amount_centimos,
            "balance_centimos": balance_centimos,
        }

        parsed_rows.append(
            CajaRuralBankDiagnosticRow(
                row_number=idx,
                operation_date=operation_date,
                value_date=value_date,
                concept=concept,
                amount_centimos=amount_centimos,
                balance_centimos=balance_centimos,
                statement_number=statement_number,
                movement_type=movement_type,
                movement_status=movement_status,
                row_hash=_row_hash(hash_payload),
                warnings=warnings,
            )
        )

    return CajaRuralBankDiagnosticReport(
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


def report_to_dict(report: CajaRuralBankDiagnosticReport, include_rows: bool = False) -> dict[str, Any]:
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
