ASTURIAS_PROVINCE_CODE = "33"

MODEL_CATALOG_SOURCE_PROVINCE_CODE = (
    ASTURIAS_PROVINCE_CODE
)

MERCURIO_GENERAL_MODELS = (
    "EX00",
    "EX01",
    "EX02",
    "EX03",
    "EX04",
    "EX06",
    "EX07",
    "EX09",
    "EX10",
    "EX11",
    "EX19",
    "EX20",
    "EX21",
    "EX22",
    "EX24",
    "EX25",
    "EX26",
)


def models_for_province(
    province_code: str,
) -> tuple[str, ...]:
    if not str(province_code).strip():
        return ()

    return MERCURIO_GENERAL_MODELS


def observed_models_for_province(
    province_code: str,
) -> tuple[str, ...]:
    """
    Compatibilidad con el contrato V1.

    El catálogo fue observado originalmente en
    Asturias (33), pero funcionalmente es común
    a las provincias Mercurio.
    """
    return models_for_province(
        province_code
    )
