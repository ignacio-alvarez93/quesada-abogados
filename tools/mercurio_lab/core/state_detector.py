from urllib.parse import urlsplit

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


SEDE_HOST = "sede.administracionespublicas.gob.es"
MERCURIO_HOST = (
    "mercurio.delegaciondelgobierno.gob.es"
)

TWIN_HOSTS = {
    "127.0.0.1",
    "localhost",
}


def _elements(snapshot: dict) -> list[dict]:
    elements = list(snapshot.get("elements") or [])

    if elements:
        return elements

    for document in snapshot.get("documents") or []:
        elements.extend(
            document.get("elements") or []
        )

    return elements


def _field(element: dict, key: str):
    value = element.get(key)

    if value not in (None, ""):
        return value

    return (
        element.get("attributes")
        or {}
    ).get(key)


def _visible(element: dict) -> bool:
    return element.get("visible") is True


def _has_visible(
    elements: list[dict],
    *,
    tag: str,
    element_id: str | None = None,
    name: str | None = None,
    element_type: str | None = None,
) -> bool:
    for element in elements:
        if str(
            element.get("tag") or ""
        ).lower() != tag:
            continue

        if not _visible(element):
            continue

        if (
            element_id is not None
            and _field(element, "id")
            != element_id
        ):
            continue

        if (
            name is not None
            and _field(element, "name")
            != name
        ):
            continue

        if (
            element_type is not None
            and _field(element, "type")
            != element_type
        ):
            continue

        return True

    return False


def _input_values(
    elements: list[dict],
    *,
    name: str,
) -> set[str]:
    values = set()

    for element in elements:
        if str(
            element.get("tag") or ""
        ).lower() != "input":
            continue

        if _field(element, "name") != name:
            continue

        value = _field(element, "value")

        if value is not None:
            values.add(str(value).strip())

    return values


def _has_model_radio(
    elements: list[dict],
) -> bool:
    for element in elements:
        if str(
            element.get("tag") or ""
        ).lower() != "input":
            continue

        if _field(element, "name") != "datosForL":
            continue

        value = str(
            _field(element, "value") or ""
        )

        if value.startswith("EX"):
            return True

    return False


def detect_mercurio_general_state(
    snapshot: dict,
) -> MercurioGeneralState | None:
    page = snapshot.get("page") or {}

    parsed = urlsplit(
        str(page.get("url") or "")
    )

    host = parsed.hostname or ""
    path = parsed.path or "/"

    is_twin = host in TWIN_HOSTS

    if host == SEDE_HOST or is_twin:
        if path == SEDE_HOME_PATH:
            return MercurioGeneralState.SEDE_HOME

        if path == SEDE_EXTRANJERIA_PATH:
            return (
                MercurioGeneralState
                .SEDE_EXTRANJERIA
            )

        if path == SEDE_MERCURIO_PATH:
            return MercurioGeneralState.SEDE_MERCURIO

        if host == SEDE_HOST:
            return None

    if host != MERCURIO_HOST and not is_twin:
        return None

    if path == MERCURIO_INICIO_PATH:
        return MercurioGeneralState.MERCURIO_INICIO

    if path == MERCURIO_MODO_ACCESO_PATH:
        return (
            MercurioGeneralState
            .MERCURIO_MODO_ACCESO
        )

    elements = _elements(snapshot)

    if path == MERCURIO_ENTRADA_PATH:
        has_province_selector = _has_visible(
            elements,
            tag="select",
            element_id="provincia",
        )

        has_operation_radios = _has_visible(
            elements,
            tag="input",
            name="opcion",
            element_type="radio",
        )

        if (
            has_province_selector
            and has_operation_radios
        ):
            return (
                MercurioGeneralState
                .MERCURIO_ENTRY_OPTIONS
            )

        tipo_values = _input_values(
            elements,
            name="tipoSolicitud",
        )

        province_values = _input_values(
            elements,
            name="codProvincia",
        )

        committed = (
            "INI" in tipo_values
            and any(province_values)
            and "" not in province_values
        )

        if not committed:
            committed = (
                "INI" in tipo_values
                and any(
                    value
                    for value in province_values
                    if value
                )
            )

        if committed:
            return (
                MercurioGeneralState
                .MERCURIO_ENTRY_SELECTION_COMMITTED
            )

        return (
            MercurioGeneralState
            .MERCURIO_ENTRY_IDLE
        )

    if (
        path.startswith(
            MERCURIO_MODEL_SELECTION_PREFIX
        )
        and _has_model_radio(elements)
    ):
        return (
            MercurioGeneralState
            .MERCURIO_MODEL_SELECTION
        )

    return None
