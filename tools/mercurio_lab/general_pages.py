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

MODEL_LABELS = {
    "EX00":
        "Solicitud de autorización de estancia de larga duración",

    "EX01":
        "Solicitud de autorización de residencia temporal no lucrativa.",

    "EX02":
        "Solicitud de autorización de residencia temporal por reagrupación familiar",

    "EX03":
        "Solicitud de autorización de residencia temporal y trabajo por cuenta "
        "ajena o autorización de trabajo por cuenta ajena",

    "EX04":
        "Solicitud de autorización de residencia para prácticas",

    "EX06":
        "Solicitud de autorización de residencia y trabajo para actividades "
        "de temporada",

    "EX07":
        "Solicitud de autorización de residencia temporal y trabajo por "
        "cuenta propia",

    "EX09":
        "Solicitud de autorización de residencia temporal con excepción de "
        "la autorización de trabajo",

    "EX10":
        "Solicitud de autorización de residencia por circunstancias excepcionales",

    "EX11":
        "Solicitud de autorización de residencia de larga duración o de "
        "larga duración-UE",

    "EX19":
        "Solicitud de tarjeta de residencia de familiar de ciudadano de la UE",

    "EX20":
        "Documento de residencia Artículo 50 TUE para nacionales del Reino "
        "Unido (emitido de conformidad con el artículo 18.4 del Acuerdo de retirada)",

    "EX21":
        "Documento de residencia Artículo 50 TUE para familiares de nacionales "
        "del Reino Unido (emitido de conformidad con el artículo 18.4 del "
        "Acuerdo de retirada)",

    "EX22":
        "Documento Artículo 50 TUE para trabajador fronterizo nacional del "
        "Reino Unido (emitido de conformidad con el artículo 26 del Acuerdo "
        "de retirada)",

    "EX24":
        "Solicitud de autorización de residencia temporal de familiares de "
        "personas con nacionalidad española",

    "EX25":
        "Solicitud de autorización de residencia y desplazamiento temporales "
        "de menores extranjeros",

    "EX26":
        "Solicitud de modificación de autorización de residencia o estancia",
}



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

    province_options = "\n".join(
        (
            f'<option value="{escape(item["value"])}">'
            f'{escape(item["label"])}'
            '</option>'
        )
        for item in contract["provinces"]
    )


    operation_rows = []

    for item in contract["operations"]:
        province_control = ""

        if item["value"] == "BI":
            province_control = f"""
<div class="mercurio-option__province">
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
</div>
"""

        operation_rows.append(
            f"""
<div
    class="mercurio-option"
    data-option-value="{escape(item["value"])}"
>
    <p class="mercurio-option__label">
        <input
            id="{escape(item["id"])}"
            name="opcion"
            type="radio"
            value="{escape(item["value"])}"
        >
        <label for="{escape(item["id"])}">
            {escape(item["label"])}
        </label>
    </p>
    {province_control}
</div>
"""
        )

    operations = "\n".join(
        operation_rows
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
    class="mercurio-options-overlay"
    aria-label="Opciones"
    hidden
>
    <div
        class="mercurio-options-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="twinOptionsTitle"
    >
        <header class="mercurio-options-dialog__header">
            <span
                id="twinOptionsTitle"
                class="mercurio-options-dialog__title"
            >
                Opciones
            </span>

            <button
                class="mercurio-options-dialog__close"
                type="button"
                onclick="cerrarOpcion()"
            >
                Cerrar
            </button>
        </header>

        <div class="mercurio-options-dialog__body">
            <p class="mercurio-options-dialog__prompt">
                Seleccione la opción que quiere realizar
            </p>

            {operations}
        </div>

        <footer class="mercurio-options-dialog__footer">
            <button
                class="mercurio-button"
                type="button"
                onclick="irOpcion()"
            >
                {escape(contract["continue_control"]["text"])}
            </button>
        </footer>
    </div>
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
<div class="mercurio-sede-brand">
    <div class="mercurio-sede-brand__inner">
        <div>
            <h1>Sede electrónica</h1>
            <p>Administraciones Públicas</p>
        </div>
    </div>
</div>

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

    contract = _entry_options_contract()

    province_label = next(
        (
            item["label"]
            for item in contract["provinces"]
            if str(item["value"])
            == str(province_code)
        ),
        province_code,
    )

    radios = "\n".join(
        f"""
<div
    class="mercurio-model-option"
    data-model="{escape(model)}"
>
    <input
        id="tini_{escape(model)}"
        name="datosForL"
        type="radio"
        value="{escape(model)}"
        onclick="ocultaError()"
    >

    <label for="tini_{escape(model)}">
        <strong>{escape(model)}</strong>
        -
        {escape(MODEL_LABELS.get(model, model))}
    </label>
</div>
"""
        for model in models
    )

    return _page(
        title="Autorizaciones de Extranjería",
        state=(
            MercurioGeneralState
            .MERCURIO_MODEL_SELECTION
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
    <div class="mercurio-autofirma-notice">
        <p>
            Si desea presentar la solicitud de forma
            electrónica es necesario que se asegure de
            tener instalada la aplicación AUTOFIRMA.
            Si no es así NO PODRÁ PRESENTAR la solicitud.
        </p>

        <p>
            Dispone de diferentes versiones de Autofirma
            para Windows, Linux y Mac. Puede descargarla
            desde el
            <a href="#">
                Portal de Administración Electrónica
            </a>.
        </p>
    </div>

    <h2 class="mercurio-model-heading">
        Solicitudes permitidas en la provincia de
        <strong>{escape(str(province_label).upper())}</strong>
    </h2>

    <div
        id="modelosSolicitud"
        class="mercurio-model-list"
        data-province="{escape(province_code)}"
    >
        {radios}
    </div>

    <div class="mercurio-model-actions">
        <a
            id="btncont"
            class="mercurio-button"
            href="#"
            onclick="continuar('INI');"
        >
            CONTINUAR
        </a>
    </div>

    <p
        id="twinEntryNotice"
        role="status"
        hidden
    ></p>
</section>

<script
    src="/mercurio/resources/lab/mercurio_general.js"
></script>
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



def _sede_utilities() -> str:
    return """
<aside
    id="sedeUtilities"
    class="sede-utils"
>
    <h2 class="sede-utils__title">
        Utilidades
    </h2>

    <a href="#">Calendario de días inhábiles</a>
    <a href="#">
        Información y verificación de los certificados
    </a>
    <a href="#">Requisitos técnicos</a>
    <a href="#">Notificaciones electrónicas</a>
    <a href="#">
        Validación de documentos electrónicos (CVE)
    </a>
    <a href="#">Oficinas de registro - Cl@ve</a>
    <a href="#">Oficinas de registro</a>
    <a href="#">
        Registro Electrónico General de la AGE
    </a>
    <a href="#">
        Consulta de unidades y oficinas en DIR3
    </a>
    <a href="#">
        Consultas dirigidas a las Oficinas de Extranjería
    </a>
</aside>
"""


def _sede_page(
    *,
    title: str,
    state: MercurioGeneralState,
    content: str,
    breadcrumb: str = "",
    show_utilities: bool = True,
    layout_class: str = "",
) -> bytes:
    utilities = (
        _sede_utilities()
        if show_utilities
        else ""
    )

    breadcrumb_html = ""

    if breadcrumb:
        breadcrumb_html = f"""
<div
    id="sedeBreadcrumb"
    class="sede-breadcrumb"
>
    {escape(breadcrumb)}
</div>
"""

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
    class="sede-twin"
    data-mercurio-twin="1"
    data-mercurio-state="{state.value}"
>
<header
    id="sedeHeader"
    class="sede-header"
>
    <div class="sede-brandline">
        <div class="sede-brandline__inner">
            <div class="sede-government-mark">
                Gobierno de España
            </div>

            <div class="sede-government-name">
                Administraciones Públicas
            </div>
        </div>
    </div>

    <div class="sede-nav">
        <div class="sede-nav__inner">
            <a
                class="sede-nav__brand"
                href="{SEDE_HOME_PATH}"
            >
                Sede electrónica
            </a>

            <nav
                id="sedeTopNav"
                class="sede-nav__links"
                aria-label="Navegación principal"
            >
                <a href="{SEDE_HOME_PATH}">
                    INICIO
                </a>

                <a href="{SEDE_HOME_PATH}">
                    PROCEDIMIENTOS
                    <span aria-hidden="true">▼</span>
                </a>

                <a href="#">
                    MIS EXPEDIENTES
                </a>

                <a href="#">
                    MIS NOTIFICACIONES
                </a>

                <a href="#">
                    AYUDA
                </a>
            </nav>
        </div>
    </div>
</header>

<div
    id="sedePage"
    class="sede-page"
>
    {breadcrumb_html}

    <div class="sede-layout {escape(layout_class)}">
        <main
            id="sedeMainContent"
            class="sede-main"
        >
            {content}
        </main>

        {utilities}
    </div>
</div>
</body>
</html>
"""

    return html.encode("utf-8")



def _sede_home_page() -> bytes:
    procedures = (
        (
            "Empleados públicos",
            "Funcionarios de admón. local con habilitación "
            "de carácter nacional",
            "#",
        ),
        (
            "Autorizaciones Administrativas",
            "Autorizaciones tramitadas en Delegaciones "
            "y Subdelegaciones",
            "#",
        ),
        (
            "Cooperación Transfronteriza y Territorial",
            "",
            "#",
        ),
        (
            "Calidad en las AA.PP.",
            "Programa de reconocimiento: Premios y "
            "Certificaciones",
            "#",
        ),
        (
            "Entidades Locales",
            "",
            "#",
        ),
        (
            "Justiprecios",
            "",
            "#",
        ),
        (
            "Régimen de Incompatibilidades",
            "Solicitudes de régimen de incompatibilidades",
            "#",
        ),
        (
            "Tasas",
            "",
            "#",
        ),
        (
            "Subvenciones",
            "",
            "#",
        ),
        (
            "Sanciones Administrativas",
            "",
            "#",
        ),
        (
            "Extranjería",
            "Procedimientos tramitados en las Oficinas "
            "de Extranjería en cada provincia.",
            SEDE_EXTRANJERIA_PATH,
        ),
        (
            "Bibliotecas y Archivos",
            "Bibliotecas y Archivos",
            "#",
        ),
        (
            "Otros Trabajo e Inmigración",
            "Salarios de Tramitación, Certificado "
            "de Emigrante Retornado,",
            "#",
        ),
        (
            "Altos cargos",
            "Las declaraciones y comunicaciones "
            "de altos cargos",
            "#",
        ),
        (
            "Derecho de reunión y manifestación",
            "",
            "#",
        ),
        (
            "Quejas y sugerencias",
            "",
            "#",
        ),
        (
            "Recursos, reclamaciones y peticiones",
            "",
            "#",
        ),
        (
            "Accesibilidad web",
            "",
            "#",
        ),
        (
            "Memoria Democrática",
            "",
            "#",
        ),
    )

    cards = "\n".join(
        f"""
<article class="sede-procedure-card">
    <div
        class="sede-procedure-card__icon"
        aria-hidden="true"
    >
        ●
    </div>

    <div>
        <a
            class="sede-procedure-card__title"
            href="{escape(href)}"
        >
            {escape(title)}
        </a>

        {
            (
                '<p class="sede-procedure-card__description">'
                + escape(description)
                + '</p>'
            )
            if description
            else ''
        }
    </div>
</article>
"""
        for title, description, href in procedures
    )

    utilities = _sede_utilities()

    return _sede_page(
        title="Sede electrónica",
        state=MercurioGeneralState.SEDE_HOME,
        show_utilities=False,
        layout_class="sede-layout--home",
        content=f"""
<div class="sede-home-shell">

    <section class="sede-home-top">

        <section
            class="sede-home-carousel"
            aria-label="Información de la Sede"
        >
            <div
                class="sede-home-carousel__visual"
                aria-hidden="true"
            ></div>

            <div class="sede-home-carousel__caption">
                <h2>
                    Bienvenido a la Sede Electrónica
                </h2>

                <p>
                    Puede realizar todos sus trámites
                    administrativos sólo con un
                    certificado digital o su
                    DNI electrónico
                </p>
            </div>

            <div
                class="sede-home-carousel__pager"
                aria-hidden="true"
            >
                1 2 3 4 5 6 7
            </div>
        </section>

        <section class="sede-home-highlights">
            <h2>
                Destacados
            </h2>

            <div
                class="sede-home-highlights__body"
                aria-hidden="true"
            ></div>
        </section>

        <div class="sede-home-side">
            <section class="sede-home-side-card">
                <h2>
                    <a href="/expedientes/">
                        Mis expedientes
                    </a>
                </h2>

                <p>
                    Acceda aquí a su área de usuario.
                    Descargue notificaciones,
                    gestione expedientes,
                    realice solicitudes...
                </p>
            </section>

            <section class="sede-home-side-card">
                <h2>
                    <a
                        href="/pagina/index/directorio/ayuda_de_navegacion"
                    >
                        ¿Necesitas ayuda?
                    </a>
                </h2>

                <p>
                    Consulte nuestra sección de preguntas
                    frecuentes, envíe una incidencia
                    a nuestro servicio técnico
                </p>
            </section>
        </div>
    </section>

    <section class="sede-home-bottom">

        <section
            id="sedeProcedureGrid"
            class="sede-home-procedures"
        >
            <h2>Procedimientos</h2>

            <div class="sede-procedure-grid">
                {cards}
            </div>
        </section>

        {utilities}
    </section>
</div>
""",
    )



def _sede_extranjeria_page() -> bytes:
    items = (
        (
            "Cita Previa de Extranjería",
            "/pagina/index/directorio/icpplus",
        ),
        (
            "Información sobre el estado de tramitación "
            "de los expedientes de extranjería",
            "/pagina/index/directorio/infoext2",
        ),
        (
            "Pago de tasas de Extranjería",
            "/procedimientos/index/categoria/33",
        ),
        (
            "MERCURIO – Solicitudes de autorizaciones "
            "de Extranjería y Aportación de documentación: "
            "Presentación Telemática y aportación de "
            "documentación a expedientes de extranjería.",
            SEDE_MERCURIO_PATH,
        ),
        (
            "Consultas dirigidas a las Oficinas "
            "de Extranjería",
            (
                "https://sede.administracionespublicas.gob.es/"
                "ayuda/consulta/ExtranjeriaCG"
            ),
        ),
        (
            "Aportación de Informes de Extranjería "
            "desde las CC.AA. y EE.LL. (SIA: 200406)",
            "/pagina/index/directorio/Informes_Extranjeria",
        ),
        (
            "Solicitudes para la gestión colectiva "
            "de contrataciones en origen GECCO",
            (
                "https://mptmd.sede.gob.es/"
                "procedimiento/ambitos?idProc=134541"
            ),
        ),
    )

    rows = []

    for label, href in items:
        extra_class = ""

        if href == SEDE_MERCURIO_PATH:
            extra_class = (
                " sede-category-item--mercurio"
            )

        rows.append(
            f"""
<article
    class="sede-category-item{extra_class}"
>
    <a
        href="{escape(href)}"
        class="sede-category-item__title"
    >
        {escape(label)}
    </a>

    <span
        class="sede-category-item__plus"
        aria-hidden="true"
    >
        +
    </span>
</article>
"""
        )

    return _sede_page(
        title="Extranjería",
        state=MercurioGeneralState.SEDE_EXTRANJERIA,
        breadcrumb="Inicio / Extranjería",
        content=f"""
<header class="sede-category-header">
    <h1>Extranjería</h1>

    <p>
        Procedimientos tramitados en las Oficinas
        de Extranjería en cada provincia.
    </p>
</header>

<section class="sede-category-list">
    <header class="sede-category-list__header">
        <strong>
            Procedimientos de la categoría Extranjería
        </strong>

        <span>7 procedimientos</span>
    </header>

    <div class="sede-category-list__items">
        {"".join(rows)}
    </div>
</section>
""",
    )



def _sede_mercurio_page() -> bytes:
    initial_requests = (
        "Solicitud de autorización de estancia y "
        "prórrogas (EX00)",
        "Solicitud de autorización de residencia "
        "temporal no lucrativa (EX01)",
        "Solicitud de autorización de residencia "
        "temporal por reagrupación familiar (EX02)",
        "Solicitud de autorización de residencia "
        "temporal y trabajo por cuenta ajena. (EX03)",
        "Solicitud de autorización de residencia "
        "para prácticas. (EX04)",
        "Solicitud de autorización de residencia "
        "temporal y trabajo por cuenta propia(EX07)",
        "Solicitud de autorización de residencia "
        "o residencia y trabajo por circunstancias "
        "excepcionales (EX10)",
        "Solicitud de autorización de residencia "
        "de larga duración o de larga duración-UE (EX11)",
        "Solicitud de autorización para trabajar (EX12)",
        "Solicitud de tarjeta de residencia de familiar "
        "de ciudadano de la UE (EX19)",
        "Documento de residencia Artículo 50 TUE para "
        "nacionales del Reino Unido (emitido de "
        "conformidad con el artículo 18.4 del Acuerdo "
        "de retirada) (EX20)",
        "Documento de residencia Artículo 50 TUE para "
        "familiares de nacionales del Reino Unido "
        "(emitido de conformidad con el artículo 18.4 "
        "del Acuerdo de retirada) (EX21)",
        "Solicitud de permiso Artículo 50 TUE para "
        "trabajador fronterizo del Reino Unido (EX22)",
    )

    renewals = (
        "Solicitud de Autorización de Residencia de "
        "Larga Duración por supuesto general de 5 años "
        "de residencia continuada en España. "
        "(art 148.1 RD 557/2011)",
        "Renovaciones de autorización de residencia "
        "temporal y trabajo por cuenta ajena",
        "Renovaciones de autorización de residencia "
        "temporal y trabajo por cuenta propia",
        "Renovaciones de autorización de residencia "
        "no lucrativa",
        "Renovaciones de autorización de residencia "
        "por reagrupación familiar",
        "Renovaciones de autorización de residencia y "
        "trabajo como trabajador altamente cualificado "
        "(Tarjeta azul)",
        "Renovaciones de autorización de residencia y "
        "trabajo de investigadores",
        "Renovaciones de autorización de residencia "
        "con exceptuación a la autorización de trabajo",
        "Modificación de autorización de residencia por "
        "circunstancias excepcionales por razones de "
        "arraigo laboral, social con habilitación para "
        "trabajar, y familiar, o cualquier otro caso en "
        "el que el titular haya obtenido autorización "
        "para trabajar, a autorización de residencia y "
        "trabajo por cuenta ajena",
        "Prórroga de Autorización de Estancia por "
        "Estudios, Movilidad de Alumnos, Prácticas no "
        "laborales o servicios de voluntariado",
        "Prórroga de Autorización de Estancia de "
        "familiares de titular de Autorización de "
        "Estancia por Estudios, Movilidad de Alumnos, "
        "Prácticas no laborales o Servicios de "
        "Voluntariado",
        "Modificación de Autorización de Estancia de "
        "familiares de titular de Autorización de "
        "Estancia por Estudios, Movilidad de Alumnos, "
        "Prácticas no laborales o Servicios de "
        "Voluntariado a Residencia por Reagrupación "
        "familiar",
        "TARJETA DE RESIDENCIA PERMANENTE DE FAMILIAR "
        "DE CIUDADANO DE LA UE",
    )

    initial_items = "".join(
        f"<li>{escape(item)}</li>"
        for item in initial_requests
    )

    renewal_items = "".join(
        f"<li>{escape(item)}</li>"
        for item in renewals
    )

    return _sede_page(
        title=(
            "Solicitudes Telemáticas de "
            "Autorizaciones de Extranjería"
        ),
        state=MercurioGeneralState.SEDE_MERCURIO,
        breadcrumb=(
            "Inicio / Solicitudes Telemáticas "
            "de Autorizaciones de Extranjería"
        ),
        content=f"""
<header class="sede-window-header">
    <h1>
        Solicitudes Telemáticas de
        Autorizaciones de Extranjería
    </h1>

    <p>
        Solicitudes Telemáticas de
        Autorizaciones de Extranjería
    </p>
</header>

<article class="sede-mercurio-information">

    <p>
        <strong>
            TÍTULO DEL PROCEDIMIENTO:
        </strong>
    </p>

    <p>
        Solicitudes Telemáticas de Autorizaciones
        Nuevas y Renovaciones de Extranjería.
        Aportación de documentación a expedientes
        de extranjería
    </p>

    <p>
        <strong>SUMARIO:</strong>
    </p>

    <p>
        Este procedimiento ofrece la posibilidad de
        presentar la solicitud de las autorizaciones
        nuevas y renovaciones de extranjería a través
        de la sede electrónica del ministerio.
        Asimismo, puede adjuntar documentación a
        procedimientos de extranjería que estén
        en trámite.
    </p>

    <p>
        <strong>ÓRGANO RESPONSABLE:</strong>
    </p>

    <p>
        Delegaciones y Subdelegaciones del Gobierno
    </p>

    <p>
        <strong>AYUDA:</strong>
    </p>

    <p>
        Si necesita ayuda, por favor, acceda al
        siguiente
        <a
            href="https://sede.administracionespublicas.gob.es/pagina/index/directorio/ayuda_extranjeria"
        >
            enlace
        </a>.
    </p>

    <section class="sede-mercurio-instructions">
        <p>
            <strong>
                INSTRUCCIONES DEL PROCEDIMIENTO:
            </strong>
        </p>

        <p>
            Usted tiene la posibilidad de presentar
            telemáticamente la solicitud nueva o de
            renovación de su autorización de extranjería.
        </p>

        <p>
            Las autorizaciones iniciales para su
            presentación telemática son:
        </p>

        <ul class="sede-mercurio-list">
            {initial_items}
        </ul>

        <p>
            Las renovaciones admitidas para su
            presentación telemática son:
        </p>

        <ul class="sede-mercurio-list">
            {renewal_items}
        </ul>

        <p>
            Pasos a seguir:
        </p>

        <ul class="sede-mercurio-list">
            <li>
                Acceda desde un puesto informático con
                impresora (necesaria si quiere imprimir
                el justificante de la presentación) y
                acceso a Internet.
            </li>

            <li>
                Deberá disponer de un certificado digital
                reconocido por cualquiera de las
                entidades oficiales de certificación
                nacionales, o del DNI electrónico.
            </li>

            <li>
                En el caso de pertenecer a un de los
                siguientes colecitvos: Graduados Sociales,
                Gestores Administrativos, Abogacía; podrá
                usar los accesos correspondientes para
                poder realizar la solicitud, para ello
                deberá estar dado de alta en el Consejo
                General correspondiente.
            </li>

            <li>
                Una vez seleccionada la opción que desea
                realizar (autorización nueva/ renovación)
                deberá cumplimentar los datos del
                formulario así como adjuntar la
                documentación necesaria.
            </li>

            <li>
                Para finalizar la presentación,
                previamente al registro de su solicitud
                se le pedirá que firme con su certificado
                digital el formulario y la documentación
                adjuntada. Para ello deberá tener
                instalado el programa Autofirma.
                Una vez registrada la solicitud usted
                podrá obtener un resguardo electrónico.
            </li>

            <li>
                El pago de las tasas es necesario para
                continuar con la tramitación de la
                solicitud. Por ello, es conveniente que
                junto con la solicitud y el resto de la
                documentación adjunta a su presentación
                telemática se incluya el justificante de
                pago de las tasas. El abono de la tasa
                puede realizarse:

                <ul>
                    <li>
                        a través de la pasarela de pago
                        del Ministerio de Hacienda y
                        Administraciones Públicas.
                    </li>

                    <li>
                        a través de una entidad bancaria
                        previa descarga e impresión de
                        la tasa a pagar.
                    </li>
                </ul>
            </li>
        </ul>

        <p>
            Tanto el acceso a la pasarela de pago de la
            tasa como a la descarga del impreso de la
            tasa se encuentra en el siguiente enlace:
            <a
                href="/procedimientos/index/categoria/33"
            >
                Enlace a tasas
            </a>
        </p>

        <p>
            Si no adjunta el justificante del pago de la
            tasa durante la presentación telemática de la
            solicitud se recomienda que presente dicho
            justificante de pago en la oficina de
            extranjería correspondiente por vía
            ordinaria, lo que puede motivar un retraso
            en la tramitación de su solicitud
        </p>

        <ul class="sede-mercurio-list">
            <li>
                La solicitud seguirá su tramitación
                normal y una vez resuelta se le
                notificará el resultado de la misma.
            </li>
        </ul>
    </section>

    <section class="sede-mercurio-requirements">
        <p>
            <strong>
                REQUISITOS TÉCNICOS DEL PROCEDIMIENTO:
            </strong>
        </p>

        <ul class="sede-mercurio-list">
            <li>
                Sistema Operativo: Windows 2000 / XP /
                Vista / 7 / Server 2003 / Server 2008
                y superiores.
            </li>

            <li>
                Navegador web: Internet Explorer 7 o
                superior, en 32 y 64 bits (incluido
                Internet Explorer 9).
            </li>

            <li>
                JRE: JRE 6 update 17 y superiores ó
                JRE 7 instalado en el navegador
                (1.6 update 25 recomendada)
            </li>

            <li>
                Certificado digital de usuario instalado
                en el navegador / sistema operativo o
                disponible a través de un módulo PKCS#11
                o CSP instalado en el navegador
                (caso del DNI-e).
            </li>

            <li>
                Tener instalado el programa Autofirma
                https://firmaelectronica.gob.es/Home/Descargas.html
            </li>

            <li>
                <a
                    href="https://sede.administracionespublicas.gob.es/pagina/index/directorio/adae_navegador"
                >
                    Resolución de problemas con el
                    navegador
                </a>
            </li>

            <li>
                <a
                    href="https://sede.administracionespublicas.gob.es/pagina/index/directorio/problemas_acceso"
                >
                    Resolución de problemas con Java
                </a>
            </li>
        </ul>
    </section>

    <fieldset class="sede-mercurio-rgpd">
        <strong>
            En cumplimiento del artículo 13 del
            Reglamento (UE) 2016/679 general de
            protección de datos, de 27 de abril de 2016
            (RGPD) se informa de que los datos personales
            facilitados corresponden al tratamiento de
            datos de la Actividad Extranjería.
        </strong>

        <p>
            Puede ejercitar sus derechos de acceso,
            rectificación, supresión y portabilidad
            de sus datos, de limitación y oposición
            a su tratamiento.
        </p>
    </fieldset>

    <form
        class="sede-mercurio-access-form"
        action="{MERCURIO_INICIO_PATH}"
        method="get"
    >
        <input
            id="submit"
            class="uppercase button_next sede-mercurio-access"
            type="submit"
            value="Acceder a Solicitudes Telemáticas de Autorizaciones de Extranjería"
        >
    </form>
</article>
""",
    )


def render_general_page(
    path: str,
) -> bytes | None:
    if path == SEDE_HOME_PATH:
        return _sede_home_page()

    if path == SEDE_EXTRANJERIA_PATH:
        return _sede_extranjeria_page()

    if path == SEDE_MERCURIO_PATH:
        return _sede_mercurio_page()

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
