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


ACCESS_MODES = (
    (
        "IN",
        "INDIVIDUAL",
        "Acceso a los ciudadanos en virtud de la "
        "Ley 39/2015 del Procedimiento Administrativo "
        "Común de las Administraciones Públicas.",
    ),
    (
        "RP",
        "REPRESENTACIÓN",
        "Acceso para representación acreditada mediante "
        "apoderamiento notarial o apud acta.",
    ),
    (
        "RC",
        "COLABORADOR",
        "Acceso para sindicatos representativos y "
        "entidades sin ánimo de lucro inscritos en el "
        "Registro de Colaboradores.",
    ),
    (
        "GA",
        "GESTORÍA",
        "Acceso para Gestores Administrativos según "
        "convenio de colaboración con la "
        "Administración General del Estado.",
    ),
    (
        "GS",
        "GRADUADO",
        "Acceso para Graduados Sociales según convenio "
        "de colaboración con la Administración General "
        "del Estado.",
    ),
    (
        "AB",
        "ABOGACÍA",
        "Acceso para Abogados según convenio de "
        "colaboración con la Administración General "
        "del Estado.",
    ),
    (
        "FH",
        "FUNCIONARIO",
        "Acceso para funcionarios habilitados que "
        "pueden realizar labores de identificación y "
        "firma en nombre de las personas interesadas.",
    ),
    (
        "PC",
        "CORREOS",
        "Acceso para personal de Correos habilitado para "
        "la presentación de solicitudes.",
    ),
)


def _entry_options_contract() -> dict:
    return json.loads(
        ENTRY_OPTIONS_CONTRACT.read_text(
            encoding="utf-8"
        )
    )


def _modo_acceso_page() -> bytes:
    access_rows = "\n".join(
        f"""
<article
    class="mercurio-access-row"
    data-access-mode="{escape(code)}"
>
    <p class="mercurio-access-description">
        {escape(description)}
    </p>

    <a
        class="mercurio-button mercurio-access-button"
        href="{MERCURIO_ENTRADA_PATH}"
        data-access-mode="{escape(code)}"
    >
        <span>CONTINUAR</span>
        <strong>{escape(label)}</strong>
    </a>
</article>
"""
        for code, label, description
        in ACCESS_MODES
    )

    return _page(
        title="Autorizaciones de Extranjería",
        state=(
            MercurioGeneralState
            .MERCURIO_MODO_ACCESO
        ),
        body=f"""
<p class="mercurio-version">
    V. 4.1.4
</p>

<div class="mercurio-heading-row">
    <div>
        <h1 class="mercurio-title">
            Autorizaciones de Extranjería
        </h1>

        <h2 class="mercurio-section-title">
            Presentación con certificado digital
        </h2>
    </div>

    <a
        class="mercurio-button mercurio-back"
        href="{MERCURIO_INICIO_PATH}"
    >
        VOLVER
    </a>
</div>

<section class="mercurio-content">
    <p>
        A continuación puede acceder a la cumplimentación
        de su solicitud de Autorización de Extranjería y
        presentarla de forma electrónica si posee
        certificado electrónico.
    </p>

    <p>
        Por favor, asegúrese de que tiene correctamente
        instalado y funcionando el Certificado Digital.
    </p>

    <p>
        <a href="#">
            Información sobre certificados electrónicos.
        </a>
    </p>

    <p>
        <a href="#">
            Requisitos Técnicos
        </a>
    </p>

    <div class="mercurio-warning">
        <p class="mercurio-warning__title">
            <span class="mercurio-warning__symbol">!</span>
            PLATAFORMA MERCURIO (EXTRANJERÍA)
        </p>

        <p>
            Las nuevas direcciones web de Mercurio e
            Infoext son las siguientes:
        </p>

        <p>
            - Mercurio:
            https://mercurio.delegaciondelgobierno.gob.es/mercurio/
            <br>
            - Infoext:
            https://infoext2.delegaciondelgobierno.gob.es/infoext2/
        </p>
    </div>

    <div class="mercurio-access-list">
        {{access_rows}}
    </div>
</section>
""".replace(
            "{access_rows}",
            access_rows,
        ),
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
<p class="mercurio-version">
    V. 4.1.4
</p>

<div class="mercurio-heading-row">
    <div>
        <h1 class="mercurio-title">
            Autorizaciones de Extranjería
        </h1>

        <p
            class="mercurio-entry-user"
            data-lab-redacted="1"
        >
            AB. ABOGADO - USUARIO LAB
        </p>
    </div>

    <a
        class="mercurio-button mercurio-back"
        href="{MERCURIO_MODO_ACCESO_PATH}"
    >
        VOLVER
    </a>
</div>

<section class="mercurio-content">
    <p class="mercurio-entry-prompt">
        Seleccione la operación que desea realizar:
    </p>

    <div
        id="twinEntryInitial"
        class="mercurio-entry-choice-list"
    >
        <article class="mercurio-entry-choice">
            <div class="mercurio-entry-choice__description">
                <p>
                    Esta opción permite obtener el número
                    de expediente de una solicitud nueva
                    presentada por el procedimiento de
                    solicitudes telemáticas de
                    autorizaciones de extranjería cuando
                    haya sido recibida por la oficina de
                    tramitación.
                </p>

                <p>
                    <a href="#">
                        Información sobre el estado de
                        tramitación de los expedientes de
                        Extranjería.
                    </a>
                </p>
            </div>

            <a
                class="
                    mercurio-button
                    mercurio-entry-choice__button
                "
                href="#"
                aria-label="CONTINUAR CONSULTA DE SOLICITUD EXISTENTE"
                onclick="entrar('C')"
            >
                <span>CONTINUAR</span>
                <strong>
                    CONSULTA DE SOLICITUD EXISTENTE
                </strong>
            </a>
        </article>

        <article class="mercurio-entry-choice">
            <div class="mercurio-entry-choice__description">
                <p>
                    Esta opción permite crear una solicitud
                    inicial nueva o realizar una renovación.
                    Podrán acceder al sistema los ciudadanos
                    extranjeros que deseen iniciar la
                    solicitud de una autorización.
                </p>

                <p>
                    Asimismo, este servicio permite adjuntar
                    documentación a procedimientos de
                    extranjería que estén en trámite.
                </p>

                <p>
                    Para presentar electrónicamente o aportar
                    documentación, asegúrese de tener instalada
                    y actualizada la aplicación AUTOFIRMA.
                </p>
            </div>

            <a
                class="
                    mercurio-button
                    mercurio-entry-choice__button
                "
                href="#"
                aria-label="CONTINUAR PRESENTACIÓN"
                onclick="mostrarOpcion()"
            >
                <span>CONTINUAR</span>
                <strong>PRESENTACIÓN</strong>
            </a>
        </article>
    </div>
</section>

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
    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >
    <title>{escape(title)}</title>
    <link
        rel="stylesheet"
        href="/mercurio/resources/lab/mercurio_general.css"
    >
</head>
<body
    data-mercurio-twin="1"
    data-mercurio-state="{state.value}"
>
<header class="mercurio-top">
    <div class="mercurio-top__inner">
        <nav
            class="mercurio-nav"
            aria-label="Navegación principal"
        >
            <a href="/">INICIO</a>
            <a href="/procedimientos/index/categoria/34">
                PROCEDIMIENTOS
            </a>
            <a href="#">MIS EXPEDIENTES</a>
            <a href="#">MIS NOTIFICACIONES</a>
            <a href="#">AYUDA</a>
        </nav>
    </div>
</header>

<main
    id="container"
    class="mercurio-page"
>
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
<p class="mercurio-version">
    V. 4.1.4
</p>

<div class="mercurio-heading-row">
    <h1 class="mercurio-title">
        Autorizaciones de Extranjería
    </h1>

    <a
        class="mercurio-button mercurio-back"
        href="/pagina/index/directorio/mercurio2"
    >
        VOLVER
    </a>
</div>

<section class="mercurio-content">
    <h2 class="mercurio-section-title">
        INICIO
    </h2>

    <p>
        Podrán acceder al sistema, los ciudadanos
        extranjeros que deseen iniciar la solicitud
        de una autorización o una renovación.
    </p>

    <p>
        Asimismo, usted tiene la posibilidad de aportar
        documentación a expedientes de extranjería que
        se encuentren en trámite, independientemente de
        que el procedimiento se haya iniciado por vía
        telemática o por vía presencial.
    </p>

    <p>
        Consulte la información sobre
        <a href="#">
            presentación de solicitudes iniciales y de
            renovaciones de autorizaciones de extranjería
        </a>
    </p>

    <p>
        Puede consultar el manual de usuario pulsando
        <a href="#">aquí</a>.
    </p>

    <p>
        No olvide consultar la información adicional que
        contienen los modelos oficiales de solicitud de
        los trámites a presentar.
        Puede descargarse los Modelos Oficiales accediendo a:
        <a href="#">
            Modelos Oficiales de Solicitudes de Extranjería
        </a>
    </p>

    <p>
        Si desea más información sobre las Oficinas de
        Extranjería, acceda a este enlace:
        <a href="#">
            Información Oficinas
        </a>
    </p>

    <div class="mercurio-warning">
        <p class="mercurio-warning__title">
            <span class="mercurio-warning__symbol">!</span>
            PLATAFORMA MERCURIO (EXTRANJERÍA)
        </p>

        <p>
            Las nuevas direcciones web de Mercurio e
            Infoext son las siguientes:
        </p>

        <p>
            - Mercurio:
            https://mercurio.delegaciondelgobierno.gob.es/mercurio/
            <br>
            - Infoext:
            https://infoext2.delegaciondelgobierno.gob.es/infoext2/
        </p>
    </div>

    <div class="mercurio-actions">
        <a
            class="mercurio-button"
            href="{MERCURIO_MODO_ACCESO_PATH}"
        >
            CONTINUAR
        </a>
    </div>

    <a class="mercurio-footer-link" href="#">
        CONSULTAS Y SUGERENCIAS
    </a>
</section>
""",
        )

    if path == MERCURIO_MODO_ACCESO_PATH:
        return _modo_acceso_page()

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
