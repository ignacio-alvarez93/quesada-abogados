from html import escape

from .contract import (
    EX01_SUPUESTOS,
    EX01_TECHNICAL_VALUES,
)
from .routes import EX01_NEW_REQUEST_PATH
from .states import Ex01TwinState


def _hidden_fields() -> str:
    return "\n".join(
        (
            f'<input type="hidden" '
            f'id="{escape(field_id)}" '
            f'name="{escape(field_id)}" '
            f'value="{escape(value)}">'
        )
        for field_id, value
        in EX01_TECHNICAL_VALUES.items()
    )


def _supuestos() -> str:
    rows = []

    for item in EX01_SUPUESTOS:
        disabled = (
            ""
            if item["enabled"]
            else " disabled"
        )

        rows.append(
            f"""
<label class="ex01-option">
    <input
        id="{item['id']}"
        name="datosForAut"
        type="radio"
        value="{item['value']}"
        {disabled}
    >
    <span>{item['id']}</span>
</label>
"""
        )

    return "\n".join(rows)


def _text(
    field_id: str,
    *,
    input_type: str = "text",
) -> str:
    return (
        f'<input id="{field_id}" '
        f'name="{field_id}" '
        f'type="{input_type}">'
    )


def _select(
    field_id: str,
    options: tuple[str, ...],
) -> str:
    rendered = [
        '<option value="">-----</option>'
    ]

    rendered.extend(
        (
            f'<option value="{escape(value)}">'
            f'{escape(value)}</option>'
        )
        for value in options
    )

    return (
        f'<select id="{field_id}" '
        f'name="{field_id}">'
        + "".join(rendered)
        + "</select>"
    )


def _personal_fields() -> str:
    return f"""
<div class="ex01-grid">
    <label>
        Pasaporte
        {_text("extPasaporte")}
    </label>

    <label>
        N.I.E.
        {_text("extNie")}
    </label>

    <label>
        1º Apellido
        {_text("extApellido1")}
    </label>

    <label>
        2º Apellido
        {_text("extApellido2")}
    </label>

    <label>
        Nombre
        {_text("extNombre")}
    </label>

    <label>
        Sexo
        {_select(
            "extSexo",
            ("HOMBRE", "MUJER", "INDEFINIDO"),
        )}
    </label>

    <label>
        Fecha de nacimiento
        {_text("extFechaNacimiento")}
    </label>

    <label>
        Estado civil
        {_select(
            "extEstadoCivil",
            (
                "CASADO/A",
                "DESCONOCIDO",
                "DIVORCIADO/A",
                "SEPARADO/A",
                "SOLTERO/A",
                "UNIÓN DE HECHO",
                "VIUDO/A",
            ),
        )}
    </label>

    <label>
        Lugar de nacimiento
        {_text("extLugarNacimiento")}
    </label>

    <label>
        País de nacimiento
        {_select(
            "extCodigoPaisNacimiento",
            ("MARRUECOS", "ESPAÑA"),
        )}
    </label>

    <label>
        Nacionalidad
        {_select(
            "extCodigoNacionalidad",
            ("MARRUECOS", "ESPAÑA"),
        )}
    </label>

    <label>
        Padre
        {_text("extPadre")}
    </label>

    <label>
        Madre
        {_text("extMadre")}
    </label>

    <label>
        Tipo de vía
        {_select(
            "extTipoVia",
            (
                "CALLE",
                "AVENIDA",
                "PLAZA",
                "CARRETERA",
            ),
        )}
    </label>

    <label>
        Domicilio
        {_text("extDomicilio")}
    </label>

    <label>
        Número
        {_text("extNumero")}
    </label>

    <label>
        Piso
        {_select(
            "extPiso",
            tuple(
                f"{n:02d}"
                for n in range(1, 21)
            ),
        )}
    </label>

    <label>
        Letra
        {_text("extLetra")}
    </label>

    <label>
        Bloque
        {_text("extBloque")}
    </label>

    <label>
        Provincia
        {_select(
            "extCodigoProvincia",
            ("33",),
        )}
    </label>

    <label>
        Municipio
        {_select(
            "extCodigoMunicipio",
            ("44",),
        )}
    </label>

    <label>
        Localidad
        {_select(
            "extCodigoLocalidad",
            ("190100",),
        )}
    </label>

    <label>
        Código postal
        {_text("extCodigoPostal")}
    </label>

    <label>
        Teléfono
        {_text("extTelefono")}
    </label>

    <label>
        Teléfono móvil
        {_text("extTelefonoMovil")}
    </label>

    <label>
        Email
        {_text(
            "extEmail",
            input_type="email",
        )}
    </label>
</div>

<input
    id="chkIncapacidad"
    name="chkIncapacidad"
    type="checkbox"
    value="true"
>

<input
    id="chkDecla4"
    name="chkDecla4"
    type="checkbox"
    value="true"
>
"""


def _presenter_fields() -> str:
    return f"""
<div class="ex01-grid">
    <label class="ex01-wide">
        Nombre/Razón Social
        {_text("preNombrePresentador")}
    </label>

    <label>
        DNI/NIE/PAS
        {_select(
            "preTipodocumentoPresentador",
            ("DNI", "NIE", "Pasaporte"),
        )}
    </label>

    <label>
        Número
        {_text("preNiePresentador")}
    </label>

    <label>
        Tipo de vía
        {_select(
            "preTipoViaPresentador",
            (
                "CALLE",
                "AVENIDA",
                "PLAZA",
            ),
        )}
    </label>

    <label>
        Domicilio
        {_text("preDomicilioPresentador")}
    </label>

    <label>
        Número
        {_text("preNumeroPresentador")}
    </label>

    <label>
        Piso
        {_select(
            "prePisoPresentador",
            tuple(
                f"{n:02d}"
                for n in range(1, 21)
            ),
        )}
    </label>

    <label>
        Provincia
        {_select(
            "preCodigoProvinciaPresentador",
            ("33",),
        )}
    </label>

    <label>
        Municipio
        {_select(
            "preCodigoMunicipioPresentador",
            ("44",),
        )}
    </label>

    <label>
        Localidad
        {_select(
            "preCodigoLocalidadPresentador",
            ("190100",),
        )}
    </label>

    <label>
        Código postal
        {_text("preCodigoPostalPresentador")}
    </label>

    <label>
        Teléfono
        {_text("preTelefonoPresentador")}
    </label>

    <label>
        Teléfono móvil
        {_text("preTelefonoMovilPresentador")}
    </label>

    <label>
        Email
        {_text("preEmailPresentador")}
    </label>
</div>
"""


def _notification_fields() -> str:
    return f"""
<div class="ex01-grid">
    <label>
        Nombre/Razón Social
        {_text("notNombreNotificacion")}
    </label>

    <label>
        DNI/NIE/PAS
        {_select(
            "notTipodocumentoNotificacion",
            ("NIF/DNI", "NIE", "Pasaporte"),
        )}
    </label>

    <label>
        Número
        {_text("notNieNotificacion")}
    </label>

    <label>
        E-mail
        {_text("notEmailNotificacion")}
    </label>

    <label>
        Teléfono móvil
        {_text("notTelefonoMovilNotificacion")}
    </label>
</div>

<label class="ex01-check">
    <input
        id="chkConsentimientoNotificacion"
        name="chkConsentimientoNotificacion"
        type="checkbox"
        value="true"
    >
    Consiento la notificación electrónica
</label>
"""


def render_ex01_page(
    path: str,
) -> bytes | None:
    if path != EX01_NEW_REQUEST_PATH:
        return None

    body = f"""<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>
        EX01 - Residencia temporal no lucrativa
    </title>

    <link
        rel="stylesheet"
        href="/mercurio/resources/lab/mercurio_general.css"
    >

    <link
        rel="stylesheet"
        href="/mercurio/resources/lab/mercurio_ex01.css"
    >
</head>

<body
    data-mercurio-twin="1"
    data-ex01-twin="1"
    data-ex01-state="{Ex01TwinState.AUTHORIZATION.value}"
>
<header class="ex01-header">
    <div>
        Sede electrónica · Administraciones Públicas
    </div>

    <div class="ex01-version">
        V. 4.1.4
    </div>

    <div data-lab-redacted="1">
        AB. ABOGADO - USUARIO LAB
    </div>
</header>

<main class="ex01-main">
    <h1>
        Autorizaciones de Extranjería
    </h1>

    <form
        name="autorizacionMercurio"
        action="/mercurio/salvarSolicitud.html"
        method="post"
        onsubmit="return false;"
    >
        {_hidden_fields()}

        <h2>
            SOLICITUD INICIAL:
            EX01 - Solicitud de autorización de
            residencia temporal no lucrativa.
        </h2>

        <nav class="ex01-tabs">
            <a
                id="d-li-autorizacionSup"
                class="r-tabs-anchor"
                href="#tab-datos_autorizacion"
            >
                TIPO DE AUTORIZACIÓN
            </a>

            <a
                href="#tab-datos_personales"
                class="r-tabs-anchor"
            >
                DATOS DEL EXTRANJERO/A
            </a>

            <a
                href="#tab-datos_presentador"
                class="r-tabs-anchor"
            >
                DATOS DEL PRESENTADOR
            </a>

            <a
                href="#tab-datos_notificacion"
                class="r-tabs-anchor"
            >
                NOTIFICACIÓN
            </a>
        </nav>

        <div
            id="tab-datos_autorizacion"
            class="
                mf-tabs--tab-content
                r-tabs-panel
                r-tabs-state-active
            "
        >
            <h3>
                TIPO DE AUTORIZACIÓN SOLICITADA
            </h3>

            <div id="ex01AuthorizationOptions">
                {_supuestos()}
            </div>

            <label class="ex01-check">
                <input
                    id="chkConsientoConsultaDocumentos"
                    name="chkConsientoConsultaDocumentos"
                    type="checkbox"
                    value="true"
                    onclick="controlCheckExcludes(this)"
                >
                Consiento consulta de documentos
            </label>

            <button
                id="btnConfirmar"
                class="mf-button mf-dialog-confirm-nav"
                type="button"
                hidden
            >
                Confirmar
            </button>

            <div class="mf-layout--row tc">
                <a
                    id="continuaPer"
                    class="simbutton mbbuttton"
                    href="#"
                    onclick="
                        continuarTab('autorizacionSup');
                        return false;
                    "
                >
                    CONTINUAR
                </a>
            </div>
        </div>

        <div
            id="tab-datos_personales"
            class="
                mf-tabs--tab-content
                mer-tab-content
                r-tabs-panel
                r-tabs-state-default
            "
        >
            {_personal_fields()}

            <div class="mf-layout--row tc">
                <a
                    id="continuaPer"
                    class="simbutton mbbuttton"
                    href="#"
                    onclick="
                        continuarTab('personales');
                        return false;
                    "
                >
                    CONTINUAR
                </a>
            </div>
        </div>

        <div
            id="tab-datos_familiar"
            class="
                mf-tabs--tab-content
                mer-tab-content
                r-tabs-panel
                r-tabs-state-default
            "
        >
            <a
                id="continuaFam"
                class="simbutton mbbuttton"
                href="#"
                onclick="
                    continuarTab('familiar');
                    return false;
                "
            >
                CONTINUAR
            </a>
        </div>

        <div
            id="tab-datos_presentador"
            class="
                mf-tabs--tab-content
                mer-tab-content
                r-tabs-panel
                r-tabs-state-default
            "
        >
            <h3>
                DATOS DEL REPRESENTANTE A EFECTOS
                DE PRESENTACIÓN DE LA SOLICITUD
            </h3>

            {_presenter_fields()}

            <div class="mf-layout--row tc">
                <a
                    id="continuaPre"
                    class="simbutton mbbuttton"
                    href="#"
                    onclick="
                        continuarTab('presentador');
                        return false;
                    "
                >
                    CONTINUAR
                </a>
            </div>
        </div>

        <div
            id="tab-datos_notificacion"
            class="
                mf-tabs--tab-content
                r-tabs-panel
                r-tabs-state-default
            "
        >
            <h3>
                DOMICILIO A EFECTOS DE NOTIFICACIONES
            </h3>

            {_notification_fields()}

            <div
                id="botoneraNot"
                class="mf-layout--row mf-btn"
            ></div>

            <button
                id="btnConfirmarSup"
                class="mf-button mf-dialog-confirm-nav"
                type="button"
                hidden
            >
                Confirmar
            </button>

            <div class="mf-layout--row tc">
                <button
                    id="btnConcluirSup"
                    class="simbutton mbbuttton"
                    type="button"
                    onclick="enviaDatosSup();"
                >
                    CONCLUIR
                </button>
            </div>
        </div>
    </form>
</main>

<script
    src="/mercurio/resources/lab/mercurio_ex01.js"
></script>
</body>
</html>
"""

    return body.encode("utf-8")
