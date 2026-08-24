from dataclasses import dataclass
from urllib.parse import urlsplit

from tools.mercurio_lab.core.state_detector import (
    detect_mercurio_general_state,
)
from tools.mercurio_lab.core.states import (
    MercurioGeneralState,
)


@dataclass(frozen=True)
class MercurioGeneralContext:
    state: MercurioGeneralState | None
    request_type: str | None = None
    province_code: str | None = None
    selected_operation: str | None = None
    available_operations: tuple[str, ...] = ()
    available_provinces: tuple[tuple[str, str], ...] = ()
    available_models: tuple[str, ...] = ()


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


def _input_value(
    elements: list[dict],
    *,
    name: str,
) -> str | None:
    values = []

    for element in elements:
        if str(
            element.get("tag") or ""
        ).lower() != "input":
            continue

        if _field(element, "name") != name:
            continue

        value = str(
            _field(element, "value") or ""
        ).strip()

        if value:
            values.append(value)

    return values[0] if values else None


def _operations(
    elements: list[dict],
) -> tuple[str, ...]:
    values = []

    for element in elements:
        if str(
            element.get("tag") or ""
        ).lower() != "input":
            continue

        if _field(element, "name") != "opcion":
            continue

        value = str(
            _field(element, "value") or ""
        ).strip()

        if value and value not in values:
            values.append(value)

    return tuple(values)


def _selected_operation(
    elements: list[dict],
) -> str | None:
    for element in elements:
        if str(
            element.get("tag") or ""
        ).lower() != "input":
            continue

        if _field(element, "name") != "opcion":
            continue

        attrs = element.get("attributes") or {}

        checked = (
            element.get("checked") is True
            or "checked" in attrs
        )

        if not checked:
            continue

        value = str(
            _field(element, "value") or ""
        ).strip()

        return value or None

    return None


def _provinces(
    elements: list[dict],
) -> tuple[tuple[str, str], ...]:
    result = []

    for element in elements:
        if str(
            element.get("tag") or ""
        ).lower() != "option":
            continue

        value = str(
            _field(element, "value") or ""
        ).strip()

        text = str(
            element.get("text") or ""
        ).strip()

        if not value or not text:
            continue

        pair = (value, text)

        if pair not in result:
            result.append(pair)

    return tuple(result)


def _models(
    elements: list[dict],
) -> tuple[str, ...]:
    result = []

    for element in elements:
        if str(
            element.get("tag") or ""
        ).lower() != "input":
            continue

        if _field(element, "name") != "datosForL":
            continue

        value = str(
            _field(element, "value") or ""
        ).strip()

        if (
            value.startswith("EX")
            and value not in result
        ):
            result.append(value)

    return tuple(result)


def _province_from_model_url(
    snapshot: dict,
) -> str | None:
    page = snapshot.get("page") or {}

    path = urlsplit(
        str(page.get("url") or "")
    ).path

    marker = "/seleccionModelo-"

    if marker not in path:
        return None

    value = path.split(
        marker,
        1,
    )[1].split(
        ".html",
        1,
    )[0]

    return value or None


def extract_mercurio_general_context(
    snapshot: dict,
) -> MercurioGeneralContext:
    state = detect_mercurio_general_state(
        snapshot
    )

    elements = _elements(snapshot)

    request_type = None
    province_code = None
    selected_operation = None
    available_operations = ()
    available_provinces = ()
    available_models = ()

    if state == (
        MercurioGeneralState.MERCURIO_ENTRY_OPTIONS
    ):
        available_operations = _operations(elements)
        selected_operation = _selected_operation(
            elements
        )
        available_provinces = _provinces(elements)

    elif state == (
        MercurioGeneralState
        .MERCURIO_ENTRY_SELECTION_COMMITTED
    ):
        request_type = _input_value(
            elements,
            name="tipoSolicitud",
        )

        province_code = _input_value(
            elements,
            name="codProvincia",
        )

    elif state == (
        MercurioGeneralState.MERCURIO_MODEL_SELECTION
    ):
        province_code = _province_from_model_url(
            snapshot
        )

        available_models = _models(elements)

    return MercurioGeneralContext(
        state=state,
        request_type=request_type,
        province_code=province_code,
        selected_operation=selected_operation,
        available_operations=available_operations,
        available_provinces=available_provinces,
        available_models=available_models,
    )
