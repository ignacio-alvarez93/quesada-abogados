"""
Diagnóstico económico orientativo para reagrupación familiar.

Este servicio:
- no accede a la base de datos;
- no modifica expedientes;
- no bloquea la presentación;
- calcula una referencia económica general basada en IPREM;
- devuelve un diagnóstico graduado;
- no sustituye la valoración profesional.
"""

from decimal import Decimal, ROUND_HALF_UP


CRITERION_GENERAL_IPREM = "GENERAL_IPREM"

STATUS_NO_DATA = "SIN_DATOS"
STATUS_SUFFICIENT = "SUFICIENTE"
STATUS_NEAR_THRESHOLD = "PROXIMO_AL_UMBRAL"
STATUS_BELOW_WITH_ASSESSMENT = "INFERIOR_CON_VALORACION"
STATUS_VERY_LOW = "MUY_INFERIOR"

VALID_STATUSES = {
    STATUS_NO_DATA,
    STATUS_SUFFICIENT,
    STATUS_NEAR_THRESHOLD,
    STATUS_BELOW_WITH_ASSESSMENT,
    STATUS_VERY_LOW,
}


def _integer(value, default=0):
    if value in (None, "", "None"):
        return int(default)

    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"Se esperaba un número entero: {value!r}"
        )


def _positive_integer(value, field_name):
    result = _integer(value)

    if result <= 0:
        raise ValueError(
            f"{field_name} debe ser mayor que cero"
        )

    return result


def _non_negative_integer(value, field_name):
    result = _integer(value)

    if result < 0:
        raise ValueError(
            f"{field_name} no puede ser negativo"
        )

    return result


def calculate_required_iprem_percentage(
    numero_personas_reagrupadas,
):
    """
    Calcula el porcentaje general de IPREM.

    Primera persona reagrupada:
        150 %

    Cada persona adicional:
        +50 %
    """
    people = _positive_integer(
        numero_personas_reagrupadas,
        "numero_personas_reagrupadas",
    )

    return 150 + max(people - 1, 0) * 50


def calculate_reference_amount_centimos(
    iprem_mensual_centimos,
    numero_personas_reagrupadas,
):
    iprem = _positive_integer(
        iprem_mensual_centimos,
        "iprem_mensual_centimos",
    )

    percentage = calculate_required_iprem_percentage(
        numero_personas_reagrupadas
    )

    amount = (
        Decimal(iprem)
        * Decimal(percentage)
        / Decimal(100)
    )

    return int(
        amount.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def _coverage_percentage(
    income_centimos,
    reference_centimos,
):
    if reference_centimos <= 0:
        return None

    coverage = (
        Decimal(income_centimos)
        * Decimal(100)
        / Decimal(reference_centimos)
    )

    return float(
        coverage.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )


def _diagnosis_status(coverage_percentage):
    if coverage_percentage is None:
        return STATUS_NO_DATA

    if coverage_percentage >= 100:
        return STATUS_SUFFICIENT

    if coverage_percentage >= 90:
        return STATUS_NEAR_THRESHOLD

    if coverage_percentage >= 70:
        return STATUS_BELOW_WITH_ASSESSMENT

    return STATUS_VERY_LOW


def evaluate_family_reunification_economic_diagnosis(
    iprem_mensual_centimos,
    numero_personas_reagrupadas,
    ingresos_mensuales_computables_centimos=None,
    numero_reagrupados_menores=0,
    criterio=CRITERION_GENERAL_IPREM,
):
    """
    Devuelve un diagnóstico económico orientativo.

    El resultado nunca bloquea automáticamente la presentación.
    """
    criterion = str(
        criterio or CRITERION_GENERAL_IPREM
    ).strip().upper()

    if criterion != CRITERION_GENERAL_IPREM:
        raise ValueError(
            f"Criterio económico no soportado: {criterion}"
        )

    people = _positive_integer(
        numero_personas_reagrupadas,
        "numero_personas_reagrupadas",
    )

    minors = _non_negative_integer(
        numero_reagrupados_menores,
        "numero_reagrupados_menores",
    )

    if minors > people:
        raise ValueError(
            "El número de menores no puede superar "
            "el número total de personas reagrupadas"
        )

    iprem = _positive_integer(
        iprem_mensual_centimos,
        "iprem_mensual_centimos",
    )

    required_percentage = (
        calculate_required_iprem_percentage(
            people
        )
    )

    reference_amount = (
        calculate_reference_amount_centimos(
            iprem,
            people,
        )
    )

    income_provided = (
        ingresos_mensuales_computables_centimos
        not in (None, "", "None")
    )

    income = (
        _non_negative_integer(
            ingresos_mensuales_computables_centimos,
            (
                "ingresos_mensuales_"
                "computables_centimos"
            ),
        )
        if income_provided
        else None
    )

    difference = (
        income - reference_amount
        if income is not None
        else None
    )

    coverage = (
        _coverage_percentage(
            income,
            reference_amount,
        )
        if income is not None
        else None
    )

    status = _diagnosis_status(coverage)

    requires_review = status in {
        STATUS_NEAR_THRESHOLD,
        STATUS_BELOW_WITH_ASSESSMENT,
        STATUS_VERY_LOW,
    }

    warning_level = {
        STATUS_NO_DATA: "INFO",
        STATUS_SUFFICIENT: "NONE",
        STATUS_NEAR_THRESHOLD: "LOW",
        STATUS_BELOW_WITH_ASSESSMENT: "MEDIUM",
        STATUS_VERY_LOW: "HIGH",
    }[status]

    return {
        "criterio": criterion,
        "iprem_mensual_centimos": iprem,
        "numero_personas_reagrupadas": people,
        "numero_reagrupados_menores": minors,
        "numero_reagrupados_adultos": (
            people - minors
        ),
        "porcentaje_iprem_requerido": (
            required_percentage
        ),
        "importe_referencia_centimos": (
            reference_amount
        ),
        "ingresos_mensuales_computables_centimos": (
            income
        ),
        "diferencia_centimos": difference,
        "porcentaje_cobertura": coverage,
        "estado": status,
        "bloquea_presentacion": False,
        "requiere_revision_profesional": (
            requires_review
        ),
        "nivel_advertencia": warning_level,
        "diagnostico_orientativo": True,
        "valoracion_profesional_requerida": (
            status
            in {
                STATUS_BELOW_WITH_ASSESSMENT,
                STATUS_VERY_LOW,
            }
        ),
    }
