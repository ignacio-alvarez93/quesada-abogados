"""
Dominio puro del desglose de cobros en líneas (ECO-ML-01).

Un cobro (`eco_cobros`) es la unidad de numeración, conciliación, caja,
banco, informes y recibo. Puede tener 1..N líneas de desglose
(`eco_cobro_lineas`) cuyo importe en céntimos suma exactamente el importe
global del cobro.

Este módulo no ejecuta SQL ni depende de Flet. Toda la aritmética se hace
con Decimal y céntimos enteros, sin redondeos implícitos.

Separación de conceptos:
- `tipo_economico` es una etiqueta económica (PROVISION, TASA, HONORARIOS,
  OTRO). No es una calificación tributaria.
- `tipo_fiscal` es la naturaleza fiscal de la línea (PROVISION / SUPLIDO).
  Es obligatoria y explícita: TASA no implica SUPLIDO.

Mapeo documentado de cobros legacy (sin filas de detalle) a línea lógica:
    tipo_cobro TASA               -> tipo_economico TASA
    tipo_cobro CONSULTA           -> tipo_economico HONORARIOS
    tipo_cobro SUPLIDO_ADELANTADO -> tipo_economico OTRO
    resto (PAGO_EXPEDIENTE, ...)  -> tipo_economico PROVISION
    tipo_fiscal SUPLIDO -> SUPLIDO; cualquier otro valor -> PROVISION
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


TIPOS_ECONOMICOS = ("PROVISION", "TASA", "HONORARIOS", "OTRO")
TIPOS_FISCALES_LINEA = ("PROVISION", "SUPLIDO")
RESUMEN_FISCAL_MIXTO = "MIXTO"

# Tipos de cobro de cabecera que no exigen hoja de encargo (regla legacy).
TIPOS_COBRO_SIN_HOJA = frozenset({"CONSULTA", "SUPLIDO_ADELANTADO", "TASA"})

CONCEPTO_MAX_LEN = 400

_DIGITS = re.compile(r"\d+")
_GROUPED_DOT = re.compile(r"\d{1,3}(\.\d{3})+")
_GROUPED_COMMA = re.compile(r"\d{1,3}(,\d{3})+")


def _strip_accents(value):
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )


def _norm_code(value):
    return _strip_accents(str(value or "")).strip().upper()


# ============================================================
# Importes
# ============================================================

def _parse_decimal_text(text, campo):
    sign = ""
    if text[:1] in ("-", "+"):
        sign, text = text[:1], text[1:]

    has_comma = "," in text
    has_dot = "." in text

    if has_comma and has_dot:
        # El último separador es el decimal; el otro agrupa miles.
        if text.rfind(",") > text.rfind("."):
            integer, _, decimals = text.rpartition(",")
            grouped = _GROUPED_DOT
        else:
            integer, _, decimals = text.rpartition(".")
            grouped = _GROUPED_COMMA
        if not grouped.fullmatch(integer) or not _DIGITS.fullmatch(decimals):
            raise ValueError(f"{campo}: formato de importe no válido ({sign}{text})")
        integer = integer.replace(".", "").replace(",", "")
    elif has_comma:
        if text.count(",") > 1:
            raise ValueError(f"{campo}: formato de importe no válido ({sign}{text})")
        integer, _, decimals = text.partition(",")
    elif has_dot:
        if text.count(".") > 1:
            # Solo separadores de miles al estilo español: 1.234.567
            if not _GROUPED_DOT.fullmatch(text):
                raise ValueError(f"{campo}: formato de importe no válido ({sign}{text})")
            integer, decimals = text.replace(".", ""), ""
        else:
            integer, _, decimals = text.partition(".")
    else:
        integer, decimals = text, ""

    integer = integer or "0"
    if not _DIGITS.fullmatch(integer) or (decimals and not _DIGITS.fullmatch(decimals)):
        raise ValueError(f"{campo}: formato de importe no válido ({sign}{text})")

    return Decimal(f"{sign}{integer}.{decimals or '0'}")


def parse_importe_centimos(value, campo="Importe", permitir_no_positivo=False):
    """
    Convierte un importe a céntimos enteros sin redondeo.

    Acepta int, Decimal, float finito y texto en formato español
    ("1.234,56", "138,28") o con punto decimal ("138.28").
    Rechaza más de dos decimales, valores vacíos y, salvo indicación,
    cero o negativos.
    """
    if value is None or isinstance(value, bool):
        raise ValueError(f"{campo}: importe obligatorio")

    if isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, Decimal):
        amount = value
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{campo}: importe no válido")
        amount = Decimal(repr(value))
    else:
        text = (
            str(value)
            .replace("€", "")
            .replace(" ", "")
            .replace(" ", "")
            .strip()
        )
        if not text:
            raise ValueError(f"{campo}: importe obligatorio")
        try:
            amount = _parse_decimal_text(text, campo)
        except InvalidOperation:
            raise ValueError(f"{campo}: formato de importe no válido ({text})")

    if not amount.is_finite():
        raise ValueError(f"{campo}: importe no válido")

    centimos = amount * 100
    if centimos != centimos.to_integral_value():
        raise ValueError(
            f"{campo}: el importe no puede tener más de dos decimales"
        )

    centimos = int(centimos)

    if not permitir_no_positivo and centimos <= 0:
        raise ValueError(f"{campo}: el importe debe ser mayor que cero")

    return centimos


def centimos_desde_importe_legacy(importe):
    """
    Céntimos de un importe REAL ya persistido (solo lectura de legacy).

    Los cobros antiguos se guardaron como REAL; aquí se normalizan al
    céntimo para presentarlos como línea lógica, nunca para escribir.
    """
    if importe is None or importe == "":
        return 0
    try:
        amount = Decimal(str(importe))
    except InvalidOperation:
        return 0
    if not amount.is_finite():
        return 0
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


def centimos_a_euros(centimos):
    """Valor para la columna REAL `eco_cobros.importe`."""
    return float(Decimal(int(centimos)) / Decimal(100))


def format_centimos_es(centimos):
    """13828 -> '138,28'; 123456 -> '1.234,56'."""
    centimos = int(centimos)
    sign = "-" if centimos < 0 else ""
    euros, cents = divmod(abs(centimos), 100)
    return f"{sign}{euros:,}".replace(",", ".") + f",{cents:02d}"


# ============================================================
# Clasificación
# ============================================================

def normalize_tipo_fiscal_linea(value, campo="Naturaleza fiscal"):
    code = _norm_code(value)
    if not code:
        raise ValueError(
            f"{campo}: indique expresamente PROVISION o SUPLIDO"
        )
    if code not in TIPOS_FISCALES_LINEA:
        raise ValueError(f"{campo}: valor no admitido ({value})")
    return code


def normalize_tipo_economico(value, campo="Tipo económico"):
    code = _norm_code(value)
    if not code:
        raise ValueError(
            f"{campo}: indique PROVISION, TASA, HONORARIOS u OTRO"
        )
    if code not in TIPOS_ECONOMICOS:
        raise ValueError(f"{campo}: valor no admitido ({value})")
    return code


def tipo_economico_desde_tipo_cobro(tipo_cobro):
    code = _norm_code(tipo_cobro)
    if code == "TASA":
        return "TASA"
    if code == "CONSULTA":
        return "HONORARIOS"
    if code == "SUPLIDO_ADELANTADO":
        return "OTRO"
    return "PROVISION"


def tipo_fiscal_legacy(value):
    """Regla legacy de cabecera: SUPLIDO o, en otro caso, PROVISION."""
    return "SUPLIDO" if _norm_code(value) == "SUPLIDO" else "PROVISION"


# ============================================================
# Líneas
# ============================================================

def validate_lineas(lineas):
    """
    Valida y normaliza el desglose recibido.

    Cada línea es un dict con `concepto`, `tipo_economico`, `tipo_fiscal`
    y `importe` (texto/Decimal/int en euros) o `importe_centimos` (int).
    La posición se asigna por orden (1..N).
    """
    if lineas is None or isinstance(lineas, (str, bytes, dict)):
        raise ValueError("El desglose del cobro debe ser una lista de líneas")

    lineas = list(lineas)
    if not lineas:
        raise ValueError("El cobro debe tener al menos una línea")

    result = []
    for posicion, raw in enumerate(lineas, start=1):
        prefix = f"Línea {posicion}"
        if not isinstance(raw, dict):
            raise ValueError(f"{prefix}: formato no válido")

        concepto = " ".join(str(raw.get("concepto") or "").split())
        if not concepto:
            raise ValueError(f"{prefix}: el concepto es obligatorio")
        if len(concepto) > CONCEPTO_MAX_LEN:
            raise ValueError(
                f"{prefix}: el concepto supera {CONCEPTO_MAX_LEN} caracteres"
            )

        if raw.get("importe_centimos") not in (None, ""):
            raw_centimos = raw.get("importe_centimos")
            if isinstance(raw_centimos, bool) or not isinstance(raw_centimos, int):
                raise ValueError(f"{prefix}: importe_centimos debe ser entero")
            if raw_centimos <= 0:
                raise ValueError(f"{prefix}: el importe debe ser mayor que cero")
            importe_centimos = raw_centimos
        else:
            importe_centimos = parse_importe_centimos(raw.get("importe"), campo=prefix)

        result.append(
            {
                "posicion": posicion,
                "concepto": concepto,
                "tipo_economico": normalize_tipo_economico(
                    raw.get("tipo_economico"), campo=f"{prefix} · tipo económico"
                ),
                "tipo_fiscal": normalize_tipo_fiscal_linea(
                    raw.get("tipo_fiscal"), campo=f"{prefix} · naturaleza fiscal"
                ),
                "importe_centimos": importe_centimos,
            }
        )

    return result


def total_centimos(lineas):
    return sum(int(linea["importe_centimos"]) for linea in lineas)


def desglose_fiscal_centimos(lineas):
    desglose = {tipo: 0 for tipo in TIPOS_FISCALES_LINEA}
    for linea in lineas:
        desglose[linea["tipo_fiscal"]] += int(linea["importe_centimos"])
    return desglose


def resumen_fiscal(lineas):
    """PROVISION, SUPLIDO o MIXTO según las naturalezas presentes."""
    tipos = {linea["tipo_fiscal"] for linea in lineas}
    if len(tipos) > 1:
        return RESUMEN_FISCAL_MIXTO
    return next(iter(tipos)) if tipos else "PROVISION"


def calcular_fiscal_factura(
    lineas,
    iva_porcentaje,
    irpf_porcentaje,
    calcular_desde_total,
):
    """
    Importes de factura de un cobro según la naturaleza de cada línea.

    `calcular_desde_total` es la fórmula legacy de facturación
    (economic_service._calculate_invoice_from_total) y se aplica SOLO a
    la suma de las líneas PROVISION, que es importe bruto cobrado. Las
    líneas SUPLIDO pasan íntegras a `suplidos`, sin IVA ni IRPF.

    Para un cobro homogéneo el resultado coincide con la regla legacy:
    PROVISION -> calcular_desde_total(total); SUPLIDO -> solo suplidos.
    """
    desglose = desglose_fiscal_centimos(lineas)
    provision = desglose["PROVISION"]
    suplidos = desglose["SUPLIDO"]
    total = provision + suplidos

    if provision:
        fiscal = calcular_desde_total(
            centimos_a_euros(provision),
            iva_porcentaje,
            irpf_porcentaje,
        )
        base = centimos_desde_importe_legacy(fiscal["base_imponible"])
        iva = centimos_desde_importe_legacy(fiscal["iva"])
        irpf = centimos_desde_importe_legacy(fiscal["irpf"])
    else:
        base = iva = irpf = 0

    if base + iva - irpf != provision or base + iva - irpf + suplidos != total:
        raise ValueError(
            "No se pudo cuadrar el cálculo fiscal con el total cobrado "
            f"({format_centimos_es(total)} €)"
        )

    return {
        "base_imponible": centimos_a_euros(base),
        "iva": centimos_a_euros(iva),
        "irpf": centimos_a_euros(irpf),
        "suplidos": centimos_a_euros(suplidos),
        "total": centimos_a_euros(total),
        "tipo_fiscal": resumen_fiscal(lineas),
    }


def assert_total_coincide(lineas, importe_declarado):
    """
    Si el caller declara un importe global (p. ej. el de un movimiento
    bancario), debe coincidir exactamente con la suma de líneas.
    """
    if importe_declarado in (None, ""):
        return
    declarado = parse_importe_centimos(importe_declarado, campo="Importe del cobro")
    total = total_centimos(lineas)
    if declarado != total:
        raise ValueError(
            "El importe del cobro "
            f"({format_centimos_es(declarado)} €) no coincide con la suma "
            f"de sus líneas ({format_centimos_es(total)} €)"
        )


def concepto_cabecera(lineas):
    return " + ".join(linea["concepto"] for linea in lineas)[:CONCEPTO_MAX_LEN]


def linea_legacy_desde_cobro(cobro):
    """Línea lógica derivada para cobros sin filas de detalle."""
    return {
        "id": None,
        "posicion": 1,
        "concepto": str(cobro.get("concepto") or "").strip(),
        "tipo_economico": tipo_economico_desde_tipo_cobro(cobro.get("tipo_cobro")),
        "tipo_fiscal": tipo_fiscal_legacy(cobro.get("tipo_fiscal")),
        "importe_centimos": centimos_desde_importe_legacy(cobro.get("importe")),
        "sintetica": True,
    }


# ============================================================
# Reglas de cabecera (expediente / hoja)
# ============================================================

def validar_reglas_vinculacion(tipo_cobro, expediente_id, hoja_id, lineas, desglose_explicito=True):
    """
    Reglas legacy extendidas a líneas:
    - TASA (cabecera o línea) exige expediente.
    - Un cobro cuyo tipo de cabecera no está exento exige hoja de encargo
      si contiene alguna línea de provisión fiscal que no sea TASA.
    - Con desglose explícito, un SUPLIDO_ADELANTADO solo puede contener
      líneas SUPLIDO, porque la recuperación de suplidos opera sobre el
      importe global del cobro. La línea sintética legacy no se somete a
      esta regla para no alterar el comportamiento previo.
    """
    tipo_cobro = _norm_code(tipo_cobro)

    if (
        tipo_cobro == "TASA"
        or any(linea["tipo_economico"] == "TASA" for linea in lineas)
    ) and not expediente_id:
        raise ValueError(
            "Los cobros de tipo TASA deben estar "
            "asociados a un expediente"
        )

    if tipo_cobro == "SUPLIDO_ADELANTADO" and desglose_explicito:
        if any(linea["tipo_fiscal"] != "SUPLIDO" for linea in lineas):
            raise ValueError(
                "Un cobro SUPLIDO_ADELANTADO solo puede contener "
                "líneas de naturaleza SUPLIDO"
            )

    requiere_hoja = tipo_cobro not in TIPOS_COBRO_SIN_HOJA and any(
        linea["tipo_fiscal"] != "SUPLIDO" and linea["tipo_economico"] != "TASA"
        for linea in lineas
    )
    if requiere_hoja and not hoja_id:
        raise ValueError(
            "Los cobros ordinarios de expediente "
            "deben estar asociados a una hoja "
            "de encargo"
        )


# ============================================================
# Serialización
# ============================================================

def serializar_linea(linea):
    centimos = int(linea.get("importe_centimos") or 0)
    return {
        "id": linea.get("id"),
        "posicion": int(linea.get("posicion") or 0),
        "concepto": linea.get("concepto") or "",
        "tipo_economico": linea.get("tipo_economico"),
        "tipo_fiscal": linea.get("tipo_fiscal"),
        "importe_centimos": centimos,
        "importe": centimos_a_euros(centimos),
        "importe_formateado": format_centimos_es(centimos),
        "sintetica": bool(linea.get("sintetica")),
    }


def resumen_desglose(cobro, lineas_persistidas):
    """
    Campos derivados que se añaden a la lectura de un cobro.

    Si no hay filas de detalle se devuelve una única línea sintética
    construida a partir de la cabecera legacy.
    """
    if lineas_persistidas:
        lineas = list(lineas_persistidas)
        sinteticas = False
    else:
        lineas = [linea_legacy_desde_cobro(cobro)]
        sinteticas = True

    num = len(lineas)
    return {
        "lineas": [serializar_linea(linea) for linea in lineas],
        "num_lineas": num,
        "lineas_sinteticas": sinteticas,
        "resumen_lineas": "1 concepto" if num == 1 else f"{num} conceptos",
        "resumen_fiscal": resumen_fiscal(lineas),
        "desglose_fiscal_centimos": desglose_fiscal_centimos(lineas),
        "importe_centimos": total_centimos(lineas),
    }
