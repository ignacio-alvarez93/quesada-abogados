"""
Normalización de teléfonos para Comunicaciones.

No contiene persistencia.
No conoce SQLite, Supabase ni Flet.
"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class NormalizedPhone:
    raw: str
    digits: str
    e164: str
    country_code: str | None
    national_number: str
    valid: bool


def _digits(value):
    return re.sub(
        r"\D+",
        "",
        str(value or ""),
    )


def normalize_phone(
    value,
    *,
    default_country_code="34",
):
    raw = str(value or "").strip()

    if not raw:
        return NormalizedPhone(
            raw="",
            digits="",
            e164="",
            country_code=None,
            national_number="",
            valid=False,
        )

    normalized = raw

    if normalized.startswith("00"):
        normalized = "+" + normalized[2:]

    digits = _digits(normalized)

    if not digits:
        return NormalizedPhone(
            raw=raw,
            digits="",
            e164="",
            country_code=None,
            national_number="",
            valid=False,
        )

    country_code = None
    national_number = digits

    if normalized.startswith("+"):
        if digits.startswith("34"):
            country_code = "34"
            national_number = digits[2:]
        else:
            country_code = None

    elif (
        len(digits) == 9
        and digits[0] in {"6", "7"}
        and default_country_code
    ):
        country_code = str(
            default_country_code
        ).strip()

        national_number = digits

        digits = (
            country_code
            + national_number
        )

    elif (
        digits.startswith("34")
        and len(digits) == 11
    ):
        country_code = "34"
        national_number = digits[2:]

    valid = bool(
        8 <= len(digits) <= 15
    )

    e164 = (
        f"+{digits}"
        if valid
        else ""
    )

    return NormalizedPhone(
        raw=raw,
        digits=digits,
        e164=e164,
        country_code=country_code,
        national_number=national_number,
        valid=valid,
    )
