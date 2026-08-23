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


_EX01_OBSERVED_TEXT_CLASSES = {
    "extApellido1": ('mf-input__m', 'merval-upletter'),
    "extApellido2": ('mf-input__m', 'merval-upletter'),
    "extBloque": ('mf-input__m', 'merval-upper'),
    "extCodigoPostal": ('mf-input__m', 'merval-number', 'merval-cp'),
    "extDomicilio": ('mf-input__m', 'merval-upletter'),
    "extEmail": ('mf-input__m', 'merval-mail'),
    "extFechaNacimiento": ('fecha', 'mf-datepicker', 'mf-input__m', 'Obliga', 'hasDatepicker', 'merval-date'),
    "extHectometro": ('mf-input__xs', 'merval-number'),
    "extKilometro": ('mf-input__xs', 'merval-number'),
    "extLetra": ('mf-input__m', 'merval-upper'),
    "extLugarNacimiento": ('mf-input__l', 'input_ll', 'merval-upper'),
    "extMadre": ('mf-input__m', 'merval-upletter'),
    "extNie": ('mf-input__m', 'cajaModf', 'merval-nie', 'merval-upper'),
    "extNieRepresentante": ('mf-input__s', 'merval-upper'),
    "extNombre": ('mf-input__m', 'merval-upletter'),
    "extNombreRepresentante": ('mf-input__l', 'input_ll', 'merval-upper'),
    "extNumero": ('mf-input__m', 'merval-upper', 'merval-number-dom'),
    "extPadre": ('mf-input__m', 'merval-upletter'),
    "extPasaporte": ('mf-input__m', 'cajaModf', 'merval-upper'),
    "extTelefono": ('mf-input__m', 'merval-number'),
    "extTelefonoMovil": ('mf-input__m', 'merval-tlf'),
    "extTituloRepresentante": ('mf-input__l', 'input_ll', 'merval-upper'),
}


_EX01_OBSERVED_SELECT_CLASSES = {
    "extCatalogoNacional": ('mf-input__m',),
    "extCodigoLocalidad": ('mf-input__m', 'clConLoc'),
    "extCodigoMunicipio": ('mf-input__m', 'clConMun'),
    "extCodigoNacionalidad": ('mf-input__m',),
    "extCodigoPaisNacimiento": ('mf-input__m',),
    "extCodigoProvincia": ('mf-input__m', 'clConPrv', 'disableLnk'),
    "extEscalera": ('mf-input__m',),
    "extEstadoCivil": ('mf-input__m',),
    "extPiso": ('mf-input__m',),
    "extSexo": ('paises', 'mf-input__m'),
    "extTipoVia": ('mf-input__m',),
    "extTipodocumentoRepresentante": ('mf-input__s',),
}


def _class_attr(
    classes: tuple[str, ...],
) -> str:
    if not classes:
        return ""

    value = escape(
        " ".join(classes)
    )

    return f' class="{value}"'


def _text(
    field_id: str,
    *,
    input_type: str = "text",
) -> str:
    class_attr = _class_attr(
        _EX01_OBSERVED_TEXT_CLASSES.get(
            field_id,
            (),
        )
    )

    return (
        f'<input id="{field_id}"'
        f'{class_attr} '
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

    class_attr = _class_attr(
        _EX01_OBSERVED_SELECT_CLASSES.get(
            field_id,
            (),
        )
    )

    return (
        f'<select id="{field_id}"'
        f'{class_attr} '
        f'name="{field_id}">'
        + "".join(rendered)
        + "</select>"
    )


def _personal_field(
    field_id: str,
    label: str,
    control: str,
    *,
    label_id: str | None = None,
) -> str:
    id_attr = (
        f' id="{escape(label_id)}"'
        if label_id
        else ""
    )

    return (
        '<div class="ex01-field">'
        f'<label{id_attr} '
        f'for="{escape(field_id)}">'
        f'{escape(label)}'
        '</label>'
        f'{control}'
        '</div>'
    )


def _personal_fields() -> str:
    fields = (
        _personal_field(
            "extPasaporte",
            "Pasaporte",
            _text("extPasaporte"),
        ),
        _personal_field(
            "extNie",
            "N.I.E.",
            _text("extNie"),
            label_id="extNieSinToolTip",
        ),
        _personal_field(
            "extApellido1",
            "1º Apellido",
            _text("extApellido1"),
        ),
        _personal_field(
            "extApellido2",
            "2º Apellido",
            _text("extApellido2"),
        ),
        _personal_field(
            "extNombre",
            "Nombre",
            _text("extNombre"),
        ),
        _personal_field(
            "extSexo",
            "Sexo",
            _select(
                "extSexo",
                (
                    "HOMBRE",
                    "MUJER",
                    "INDEFINIDO",
                ),
            ),
        ),
        _personal_field(
            "extFechaNacimiento",
            "Fecha de nacimiento",
            _text("extFechaNacimiento"),
        ),
        _personal_field(
            "extEstadoCivil",
            "Estado civil",
            _select(
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
            ),
        ),
        _personal_field(
            "extLugarNacimiento",
            "Lugar de nacimiento",
            _text("extLugarNacimiento"),
        ),
        _personal_field(
            "extCodigoPaisNacimiento",
            "País de nacimiento",
            _select(
                "extCodigoPaisNacimiento",
                (
                    "MARRUECOS",
                    "ESPAÑA",
                ),
            ),
        ),
        _personal_field(
            "extCodigoNacionalidad",
            "Nacionalidad",
            _select(
                "extCodigoNacionalidad",
                (
                    "MARRUECOS",
                    "ESPAÑA",
                ),
            ),
        ),
        _personal_field(
            "extPadre",
            "Nombre del padre",
            _text("extPadre"),
        ),
        _personal_field(
            "extMadre",
            "Nombre de la madre",
            _text("extMadre"),
        ),
        _personal_field(
            "extTipoVia",
            "Tipo de vía",
            _select(
                "extTipoVia",
                (
                    "CALLE",
                    "AVENIDA",
                    "PLAZA",
                    "CARRETERA",
                ),
            ),
        ),
        _personal_field(
            "extDomicilio",
            "Domicilio",
            _text("extDomicilio"),
        ),
        _personal_field(
            "extNumero",
            "Número",
            _text("extNumero"),
        ),
        _personal_field(
            "extPiso",
            "Piso",
            _select(
                "extPiso",
                tuple(
                    f"{n:02d}"
                    for n in range(1, 21)
                ),
            ),
        ),
        _personal_field(
            "extLetra",
            "Letra",
            _text("extLetra"),
        ),
        _personal_field(
            "extBloque",
            "Bloque",
            _text("extBloque"),
        ),
        _personal_field(
            "extCodigoProvincia",
            "Provincia",
            _select(
                "extCodigoProvincia",
                ("33",),
            ),
        ),
        _personal_field(
            "extCodigoMunicipio",
            "Municipio",
            _select(
                "extCodigoMunicipio",
                ("44",),
            ),
        ),
        _personal_field(
            "extCodigoLocalidad",
            "Localidad",
            _select(
                "extCodigoLocalidad",
                ("190100",),
            ),
        ),
        _personal_field(
            "extCodigoPostal",
            "Código Postal",
            _text("extCodigoPostal"),
        ),
        _personal_field(
            "extTelefono",
            "Teléfono",
            _text("extTelefono"),
        ),
        _personal_field(
            "extTelefonoMovil",
            "Teléfono móvil",
            _text("extTelefonoMovil"),
        ),
        _personal_field(
            "extEmail",
            "Email",
            _text(
                "extEmail",
                input_type="email",
            ),
        ),
    )

    return (
        '<div class="ex01-grid">'
        + "\n".join(fields)
        + """
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
    )


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
<header
    class="ex01-header ex01-flow-anchor"
    aria-hidden="true"
>
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
    <h1
        class="
            mf-app-title
            ex01-real-sede-title
        "
    >
        Sede electrónica
    </h1>

    <div
        class="
            mf-window-header
            ex01-real-window-header
        "
    >
        <div
            class="
                mf-app-title--container
                ex01-real-identity
            "
        >
            <span>
                V. 4.1.4
            </span>

            <span data-lab-redacted="1">
                AB. ABOGADO - USUARIO LAB
            </span>
        </div>

        <div
            id="btVolver"
            class="
                mf-app-title--container
                ex01-real-app-title
            "
        >
            <div
                class="
                    left
                    mf-window-header--title
                "
            >
                Solicitud inicial
            </div>

            <div class="right">
                VOLVER
            </div>
        </div>
    </div>

    <form
        name="autorizacionMercurio"
        action="/mercurio/salvarSolicitud.html"
        method="post"
        onsubmit="return false;"
    >
        {_hidden_fields()}

        <div
            class="
                mf-layout--row
                ex01-real-request-heading
            "
        >
            <div
                class="
                    mf-layout--module__xl
                    mf-layout--column
                "
            >
                <h4
                    class="
                        mf-paragraph-header
                        subgrupo
                    "
                >
                    <span>
                        SOLICITUD INICIAL:
                    </span>
                    EX01 - Solicitud de autorización de
                    residencia temporal no lucrativa.
                </h4>
            </div>
        </div>

        <div
            class="ex01-shell-flow-spacer"
            aria-hidden="true"
        ></div>

        <ul
            id="merPestanero"
            class="r-tabs-nav ex01-tabs"
        >
            <li
                class="
                    r-tabs-tab
                    r-tabs-state-active
                "
            >
                <a
                    id="d-li-autorizacionSup"
                    class="r-tabs-anchor"
                    href="#tab-datos_autorizacion"
                >
                    TIPO DE AUTORIZACIÓN
                </a>
            </li>

            <li
                class="
                    r-tabs-tab
                    r-tabs-state-disabled
                "
            >
                <a
                    id="d-li-personales"
                    class="r-tabs-anchor"
                    href="#tab-datos_personales"
                >
                    DATOS DEL EXTRANJERO/A
                </a>
            </li>

            <li
                id="pestPresentador"
                class="
                    r-tabs-tab
                    r-tabs-state-disabled
                "
            >
                <a
                    id="d-li-presentador"
                    class="r-tabs-anchor"
                    href="#tab-datos_presentador"
                >
                    DATOS DEL PRESENTADOR
                </a>
            </li>

            <li
                class="
                    r-tabs-tab
                    r-tabs-state-disabled
                "
            >
                <a
                    id="d-li-notificacion"
                    class="r-tabs-anchor"
                    href="#tab-datos_notificacion"
                >
                    DOMICILIO DE NOTIFICACIÓN
                </a>
            </li>
        </ul>

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
