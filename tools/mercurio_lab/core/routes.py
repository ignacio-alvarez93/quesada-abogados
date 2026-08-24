SEDE_HOME_PATH = "/"

SEDE_EXTRANJERIA_PATH = (
    "/procedimientos/index/categoria/34"
)

SEDE_MERCURIO_PATH = (
    "/pagina/index/directorio/mercurio2"
)

MERCURIO_INICIO_PATH = (
    "/mercurio/inicioMercurio.html"
)

MERCURIO_MODO_ACCESO_PATH = (
    "/mercurio/modoAcceso.html"
)

MERCURIO_ENTRADA_PATH = (
    "/mercurio/entradaMercurio.html"
)

MERCURIO_MODEL_SELECTION_PREFIX = (
    "/mercurio/seleccionModelo-"
)


def model_selection_path(
    province_code: str,
) -> str:
    return (
        MERCURIO_MODEL_SELECTION_PREFIX
        + str(province_code)
        + ".html"
    )
