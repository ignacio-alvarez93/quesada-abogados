from tools.mercurio_lab.core.state_context import (
    extract_mercurio_general_context,
)
from tools.mercurio_lab.core.states import (
    MercurioGeneralState,
)


BASE = (
    "https://mercurio.delegaciondelgobierno.gob.es"
)


def snapshot(url, elements):
    return {
        "page": {"url": url},
        "elements": elements,
    }


def test_extracts_entry_options_context():
    context = extract_mercurio_general_context(
        snapshot(
            BASE + "/mercurio/entradaMercurio.html#",
            [
                {
                    "tag": "input",
                    "name": "opcion",
                    "type": "radio",
                    "value": "BI",
                    "visible": True,
                },
                {
                    "tag": "select",
                    "id": "provincia",
                    "visible": True,
                },
                {
                    "tag": "option",
                    "value": "33",
                    "text": "ASTURIAS",
                    "visible": False,
                },
            ],
        )
    )

    assert context.state == (
        MercurioGeneralState.MERCURIO_ENTRY_OPTIONS
    )
    assert context.available_operations == ("BI",)
    assert context.available_provinces == (
        ("33", "ASTURIAS"),
    )


def test_extracts_committed_context():
    context = extract_mercurio_general_context(
        snapshot(
            BASE + "/mercurio/entradaMercurio.html#",
            [
                {
                    "tag": "input",
                    "name": "tipoSolicitud",
                    "value": "INI",
                    "visible": False,
                },
                {
                    "tag": "input",
                    "name": "codProvincia",
                    "value": "33",
                    "visible": False,
                },
            ],
        )
    )

    assert context.state == (
        MercurioGeneralState
        .MERCURIO_ENTRY_SELECTION_COMMITTED
    )
    assert context.request_type == "INI"
    assert context.province_code == "33"


def test_extracts_model_selection_context():
    context = extract_mercurio_general_context(
        snapshot(
            BASE + "/mercurio/seleccionModelo-33.html",
            [
                {
                    "tag": "input",
                    "name": "datosForL",
                    "value": "EX01",
                    "visible": True,
                },
                {
                    "tag": "input",
                    "name": "datosForL",
                    "value": "EX02",
                    "visible": True,
                },
            ],
        )
    )

    assert context.state == (
        MercurioGeneralState.MERCURIO_MODEL_SELECTION
    )
    assert context.province_code == "33"
    assert context.available_models == (
        "EX01",
        "EX02",
    )
