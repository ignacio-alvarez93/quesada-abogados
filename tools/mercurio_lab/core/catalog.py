ASTURIAS_PROVINCE_CODE = "33"


OBSERVED_MODELS_BY_PROVINCE = {
    ASTURIAS_PROVINCE_CODE: (
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
    ),
}


def observed_models_for_province(
    province_code: str,
) -> tuple[str, ...]:
    return OBSERVED_MODELS_BY_PROVINCE.get(
        str(province_code),
        (),
    )
