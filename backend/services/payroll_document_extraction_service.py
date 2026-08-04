"""
Extracción estructurada orientativa de nóminas españolas.

Este servicio:
- analiza texto ya extraído;
- no realiza OCR;
- no accede a base de datos;
- no modifica expedientes;
- devuelve propuestas que requieren revisión manual.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


DOCUMENT_TYPE_PAYROLL = "PAYROLL"
DOCUMENT_TYPE_UNKNOWN = "UNKNOWN"

REVIEW_STATUS_PENDING = "PENDIENTE_REVISION"

MONTHS = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}


def _strip_accents(value):
    normalized = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )
    return "".join(
        char
        for char in normalized
        if not unicodedata.combining(char)
    )


def _compact_spaces(value):
    return re.sub(
        r"[ \t]+",
        " ",
        str(value or ""),
    ).strip()


def _normalized_text(value):
    return _strip_accents(
        _compact_spaces(value)
    ).upper()


def _normalize_line(value):
    return _compact_spaces(
        str(value or "").strip(" \t|;:")
    )


def _lines(text):
    return [
        _normalize_line(line)
        for line in str(text or "").splitlines()
        if _normalize_line(line)
    ]


def _money_to_centimos(value):
    raw = str(value or "").strip()

    if not raw:
        return None

    raw = (
        raw.replace("€", "")
        .replace("EUR", "")
        .replace(" ", "")
    )

    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")

    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None

    if amount < 0:
        return None

    return int(
        (
            amount * Decimal("100")
        ).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def _first_match(patterns, text, flags=re.IGNORECASE):
    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags,
        )
        if match:
            return _normalize_line(
                match.group(1)
            )
    return ""


def _extract_money_after_labels(
    text,
    labels,
):
    escaped_labels = "|".join(
        re.escape(label)
        for label in labels
    )

    patterns = [
        (
            rf"(?:{escaped_labels})"
            r"\s*[:\-]?\s*"
            r"([0-9][0-9.\s]*,[0-9]{2})"
        ),
        (
            rf"(?:{escaped_labels})"
            r"\s*[:\-]?\s*"
            r"([0-9][0-9,\s]*\.[0-9]{2})"
        ),
    ]

    value = _first_match(
        patterns,
        text,
    )
    return _money_to_centimos(value)


def _extract_period(text):
    normalized = _normalized_text(text)

    for month_name, month_number in MONTHS.items():
        match = re.search(
            rf"\b{month_name}\b"
            r"(?:\s+DE)?\s+"
            r"(20\d{2})",
            normalized,
        )
        if match:
            return month_number, int(match.group(1))

    match = re.search(
        r"\b(?:PERIODO|MES)"
        r"\s*[:\-]?\s*"
        r"(0?[1-9]|1[0-2])"
        r"[\/\-]"
        r"(20\d{2})\b",
        normalized,
    )
    if match:
        return (
            int(match.group(1)),
            int(match.group(2)),
        )

    match = re.search(
        r"\b(?:DEL|DESDE)\s+"
        r"\d{1,2}[\/\-]\d{1,2}[\/\-](20\d{2})"
        r"\s+(?:AL|HASTA)\s+"
        r"\d{1,2}[\/\-](0?[1-9]|1[0-2])"
        r"[\/\-](20\d{2})",
        normalized,
    )
    if match:
        return (
            int(match.group(2)),
            int(match.group(3)),
        )

    return None, None


def _extract_identity(text):
    return _first_match(
        [
            r"\b(?:NIF|DNI|NIE)"
            r"\s*[:\-]?\s*"
            r"([XYZ]?\d{7,8}[A-Z])\b",
            r"\b([XYZ]\d{7}[A-Z])\b",
            r"\b(\d{8}[A-Z])\b",
        ],
        _normalized_text(text),
    )


def _extract_employee_name(text):
    return _first_match(
        [
            r"(?:TRABAJADOR|EMPLEADO|PERCEPTOR)"
            r"\s*[:\-]\s*"
            r"([^\n]{4,100})",
            r"(?:APELLIDOS Y NOMBRE|NOMBRE Y APELLIDOS)"
            r"\s*[:\-]\s*"
            r"([^\n]{4,100})",
        ],
        text,
    )


def _extract_company_name(text):
    return _first_match(
        [
            r"(?:EMPRESA|RAZ[ÓO]N SOCIAL)"
            r"\s*[:\-]\s*"
            r"([^\n]{3,120})",
        ],
        text,
    )


def _extract_company_tax_id(text):
    return _first_match(
        [
            r"(?:CIF|NIF EMPRESA|NIF DE LA EMPRESA)"
            r"\s*[:\-]?\s*"
            r"([ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J])",
        ],
        _normalized_text(text),
    )


def _detect_payroll_document(text):
    normalized = _normalized_text(text)

    indicators = [
        "NOMINA",
        "RECIBO DE SALARIOS",
        "LIQUIDO A PERCIBIR",
        "TOTAL DEVENGADO",
        "TOTAL DEDUCCIONES",
        "BASE DE COTIZACION",
    ]

    matches = sum(
        1
        for indicator in indicators
        if indicator in normalized
    )

    return matches >= 2, matches


def _field_confidence(value, high=0.95):
    return high if value not in (None, "", []) else 0.0


def extract_payroll_text(
    text,
    source_path=None,
):
    text = str(text or "")
    lines = _lines(text)
    is_payroll, indicator_count = (
        _detect_payroll_document(text)
    )

    employee_name = _extract_employee_name(text)
    employee_identity = _extract_identity(text)
    company_name = _extract_company_name(text)
    company_tax_id = _extract_company_tax_id(text)
    period_month, period_year = _extract_period(text)

    total_accrued_centimos = (
        _extract_money_after_labels(
            text,
            [
                "TOTAL DEVENGADO",
                "TOTAL DEVENGOS",
            ],
        )
    )

    total_deductions_centimos = (
        _extract_money_after_labels(
            text,
            [
                "TOTAL DEDUCCIONES",
                "TOTAL A DEDUCIR",
            ],
        )
    )

    net_pay_centimos = (
        _extract_money_after_labels(
            text,
            [
                "LIQUIDO A PERCIBIR",
                "LÍQUIDO A PERCIBIR",
                "LIQUIDO",
                "NETO A PERCIBIR",
                "TOTAL LIQUIDO",
            ],
        )
    )

    contribution_base_centimos = (
        _extract_money_after_labels(
            text,
            [
                "BASE DE COTIZACION",
                "BASE DE COTIZACIÓN",
                "BASE CONTINGENCIAS COMUNES",
                "BASE C.C.",
            ],
        )
    )

    irpf_centimos = _extract_money_after_labels(
        text,
        [
            "RETENCION IRPF",
            "RETENCIÓN IRPF",
            "I.R.P.F.",
            "IRPF",
        ],
    )

    warnings = []

    if not is_payroll:
        warnings.append(
            "El texto no contiene suficientes "
            "indicadores de nómina."
        )

    if net_pay_centimos is None:
        warnings.append(
            "No se ha detectado el líquido "
            "a percibir."
        )

    if period_month is None or period_year is None:
        warnings.append(
            "No se ha podido determinar el "
            "periodo de la nómina."
        )

    if not employee_name:
        warnings.append(
            "No se ha detectado de forma fiable "
            "el nombre del trabajador."
        )

    if (
        total_accrued_centimos is not None
        and total_deductions_centimos is not None
        and net_pay_centimos is not None
    ):
        calculated_net = (
            total_accrued_centimos
            - total_deductions_centimos
        )
        difference = abs(
            calculated_net - net_pay_centimos
        )

        if difference > 5:
            warnings.append(
                "El líquido detectado no coincide "
                "con devengos menos deducciones."
            )

    field_confidence = {
        "employee_name": _field_confidence(
            employee_name,
            0.75,
        ),
        "employee_identity": _field_confidence(
            employee_identity,
            0.9,
        ),
        "company_name": _field_confidence(
            company_name,
            0.75,
        ),
        "company_tax_id": _field_confidence(
            company_tax_id,
            0.9,
        ),
        "period_month": _field_confidence(
            period_month,
            0.9,
        ),
        "period_year": _field_confidence(
            period_year,
            0.9,
        ),
        "total_accrued_centimos": _field_confidence(
            total_accrued_centimos,
            0.9,
        ),
        "total_deductions_centimos": _field_confidence(
            total_deductions_centimos,
            0.9,
        ),
        "net_pay_centimos": _field_confidence(
            net_pay_centimos,
            0.95,
        ),
        "contribution_base_centimos": (
            _field_confidence(
                contribution_base_centimos,
                0.85,
            )
        ),
        "irpf_centimos": _field_confidence(
            irpf_centimos,
            0.8,
        ),
    }

    relevant_confidences = [
        field_confidence["period_month"],
        field_confidence["period_year"],
        field_confidence["net_pay_centimos"],
        field_confidence["total_accrued_centimos"],
        field_confidence["employee_name"],
    ]

    confidence = round(
        sum(relevant_confidences)
        / len(relevant_confidences),
        2,
    )

    return {
        "document_type": (
            DOCUMENT_TYPE_PAYROLL
            if is_payroll
            else DOCUMENT_TYPE_UNKNOWN
        ),
        "document_indicator_count": indicator_count,
        "employee_name": employee_name,
        "employee_identity": employee_identity,
        "company_name": company_name,
        "company_tax_id": company_tax_id,
        "period_month": period_month,
        "period_year": period_year,
        "total_accrued_centimos": (
            total_accrued_centimos
        ),
        "total_deductions_centimos": (
            total_deductions_centimos
        ),
        "net_pay_centimos": net_pay_centimos,
        "contribution_base_centimos": (
            contribution_base_centimos
        ),
        "irpf_centimos": irpf_centimos,
        "confidence": confidence,
        "field_confidence": field_confidence,
        "warnings": warnings,
        "requires_manual_review": True,
        "review_status": REVIEW_STATUS_PENDING,
        "source_path": (
            str(source_path)
            if source_path
            else None
        ),
        "source_text_length": len(text),
        "source_line_count": len(lines),
    }


def extract_payroll_data(
    text,
    source_path=None,
):
    return extract_payroll_text(
        text,
        source_path=source_path,
    )
