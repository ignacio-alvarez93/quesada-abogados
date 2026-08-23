from html import escape
import json
from pathlib import Path

from tools.mercurio_lab.core.catalog import (
    models_for_province,
)
from tools.mercurio_lab.core.routes import (
    MERCURIO_ENTRADA_PATH,
    MERCURIO_INICIO_PATH,
    MERCURIO_MODEL_SELECTION_PREFIX,
    MERCURIO_MODO_ACCESO_PATH,
    SEDE_EXTRANJERIA_PATH,
    SEDE_HOME_PATH,
    SEDE_MERCURIO_PATH,
)
from tools.mercurio_lab.core.states import (
    MercurioGeneralState,
)


ROOT = Path(__file__).resolve().parent

ENTRY_OPTIONS_CONTRACT = (
    ROOT
    / "contracts"
    / "entry_options_v1.json"
)


def _entry_options_contract() -> dict:
    return json.loads(
        ENTRY_OPTIONS_CONTRACT.read_text(
            encoding="utf-8"
        )
    )


def _entry_page() -> bytes:
    contract = _entry_options_contract()

    operations = "\n".join(
        (
            '<div class="mercurio-option">'
            f'<input id="{escape(item["id"])}" '
            'name="opcion" '
            'type="radio" '
            f'value="{escape(item["value"])}">'
            f'<label for="{escape(item["id"])}">'
            f'{escape(item["label"])}'
            '</label>'
            '</div>'
        )
        for item in contract["operations"]
    )

    province_options = "\n".join(
        (
            f'<option value="{escape(item["value"])}">'
            f'{escape(item["label"])}'
            '</option>'
        )
        for item in contract["provinces"]
    )

    return _page(
        title="Autorizaciones de Extranjería",
        state=(
            MercurioGeneralState
            .MERCURIO_ENTRY_IDLE
        ),
        body=f"""
<h1>Autorizaciones de Extranjería</h1>

<div id="twinEntryInitial">
    <a
        href="#"
        onclick="entrar('C')"
    >
        CONTINUAR CONSULTA DE SOLICITUD EXISTENTE
    </a>

    <a
        href="#"
        onclick="mostrarOpcion()"
    >
        CONTINUAR PRESENTACIÓN
    </a>
</div>

<form
    id="frmEntrada"
    name="frmEntrada"
    method="post"
    onsubmit="return false;"
>
    <input
        id="tipoSolicitud"
        name="tipoSolicitud"
        type="hidden"
        value=""
    >

    <input
        id="codProvincia"
        name="codProvincia"
        type="hidden"
        value=""
    >
</form>

<section
    id="twinEntryOptions"
    hidden
>
{operations}

<label for="provincia">
    Provincia
</label>

<select
    id="provincia"
    name="provincia"
>
    <option value="">
        Seleccione provincia...
    </option>
{province_options}
</select>

<button
    type="button"
    onclick="irOpcion()"
>
    {escape(contract["continue_control"]["text"])}
</button>
</section>

<p
    id="twinEntryNotice"
    role="status"
    hidden
></p>

<script
    src="/mercurio/resources/lab/mercurio_general.js"
></script>
""",
    )


def _page(
    *,
    title: str,
    state: MercurioGeneralState,
    body: str,
) -> bytes:
    html = f"""<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>{escape(title)}</title>
</head>
<body
    class="sede"
    data-mercurio-twin="1"
    data-mercurio-state="{state.value}"
>
<header id="header" role="banner">
    <strong>Sede electrónica Administraciones Públicas</strong>
</header>

<main id="container">
{body}
</main>
</body>
</html>
"""
    return html.encode("utf-8")


def _model_selection(
    *,
    province_code: str,
) -> bytes | None:
    models = models_for_province(
        province_code
    )

    if not models:
        return None

    radios = "\n".join(
        (
            '<label>'
            f'<input id="tini_{escape(model)}" '
            'name="datosForL" '
            'type="radio" '
            f'value="{escape(model)}">'
            f'{escape(model)}'
            '</label>'
        )
        for model in models
    )

    return _page(
        title="Autorizaciones de Extranjería",
        state=(
            MercurioGeneralState
            .MERCURIO_MODEL_SELECTION
        ),
        body=f"""
<h1>Modelos de solicitud</h1>

<div
    id="modelosSolicitud"
    data-province="{escape(province_code)}"
>
{radios}
</div>
""",
    )


def _province_from_model_path(
    path: str,
) -> str | None:
    if not path.startswith(
        MERCURIO_MODEL_SELECTION_PREFIX
    ):
        return None

    if not path.endswith(".html"):
        return None

    province = path[
        len(MERCURIO_MODEL_SELECTION_PREFIX):
        -len(".html")
    ]

    return province or None


def render_general_page(
    path: str,
) -> bytes | None:
    if path == SEDE_HOME_PATH:
        return _page(
            title="Sede electrónica",
            state=MercurioGeneralState.SEDE_HOME,
            body=f"""
<h1>Procedimientos</h1>
<a href="{SEDE_EXTRANJERIA_PATH}">
    Extranjería
</a>
""",
        )

    if path == SEDE_EXTRANJERIA_PATH:
        return _page(
            title="Extranjería",
            state=(
                MercurioGeneralState
                .SEDE_EXTRANJERIA
            ),
            body=f"""
<h1>Extranjería</h1>
<a href="{SEDE_MERCURIO_PATH}">
    Solicitudes Telemáticas de
    Autorizaciones de Extranjería
</a>
""",
        )

    if path == SEDE_MERCURIO_PATH:
        return _page(
            title=(
                "Solicitudes Telemáticas de "
                "Autorizaciones de Extranjería"
            ),
            state=MercurioGeneralState.SEDE_MERCURIO,
            body=f"""
<h1>Solicitudes Telemáticas de Autorizaciones</h1>
<a href="{MERCURIO_INICIO_PATH}">
    ACCEDER
</a>
""",
        )

    if path == MERCURIO_INICIO_PATH:
        return _page(
            title="Autorizaciones de Extranjería",
            state=(
                MercurioGeneralState
                .MERCURIO_INICIO
            ),
            body=f"""
<h1>Autorizaciones de Extranjería</h1>
<a href="{MERCURIO_MODO_ACCESO_PATH}">
    INICIO
</a>
""",
        )

    if path == MERCURIO_MODO_ACCESO_PATH:
        return _page(
            title="Autorizaciones de Extranjería",
            state=(
                MercurioGeneralState
                .MERCURIO_MODO_ACCESO
            ),
            body=f"""
<h1>Modos de acceso</h1>
<a
    id="accesoCertificado"
    href="{MERCURIO_ENTRADA_PATH}"
>
    Presentación con certificado digital
</a>
""",
        )

    if path == MERCURIO_ENTRADA_PATH:
        return _entry_page()

    province_code = _province_from_model_path(
        path
    )

    if province_code is not None:
        return _model_selection(
            province_code=province_code
        )

    return None
