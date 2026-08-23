from tools.mercurio_lab.core.state_detector import (
    detect_mercurio_general_state,
)
from tools.mercurio_lab.core.states import (
    MercurioGeneralState,
)


def snapshot(url, elements=None):
    return {
        "page": {"url": url},
        "elements": elements or [],
    }


def test_detects_sede_extranjeria():
    state = detect_mercurio_general_state(
        snapshot(
            "https://sede.administracionespublicas.gob.es"
            "/procedimientos/index/categoria/34"
        )
    )

    assert state == (
        MercurioGeneralState.SEDE_EXTRANJERIA
    )


def test_detects_mercurio_inicio():
    state = detect_mercurio_general_state(
        snapshot(
            "https://mercurio.delegaciondelgobierno.gob.es"
            "/mercurio/inicioMercurio.html"
        )
    )

    assert state == (
        MercurioGeneralState.MERCURIO_INICIO
    )


def test_detects_entry_idle():
    state = detect_mercurio_general_state(
        snapshot(
            "https://mercurio.delegaciondelgobierno.gob.es"
            "/mercurio/entradaMercurio.html"
        )
    )

    assert state == (
        MercurioGeneralState.MERCURIO_ENTRY_IDLE
    )


def test_detects_entry_options():
    elements = [
        {
            "tag": "select",
            "id": "provincia",
            "visible": True,
        },
        {
            "tag": "input",
            "name": "opcion",
            "type": "radio",
            "value": "BI",
            "visible": True,
        },
    ]

    state = detect_mercurio_general_state(
        snapshot(
            "https://mercurio.delegaciondelgobierno.gob.es"
            "/mercurio/entradaMercurio.html#",
            elements,
        )
    )

    assert state == (
        MercurioGeneralState.MERCURIO_ENTRY_OPTIONS
    )


def test_detects_entry_selection_committed():
    elements = [
        {
            "tag": "input",
            "name": "tipoSolicitud",
            "type": "hidden",
            "value": "INI",
            "visible": False,
        },
        {
            "tag": "input",
            "name": "codProvincia",
            "type": "hidden",
            "value": "33",
            "visible": False,
        },
    ]

    state = detect_mercurio_general_state(
        snapshot(
            "https://mercurio.delegaciondelgobierno.gob.es"
            "/mercurio/entradaMercurio.html#",
            elements,
        )
    )

    assert state == (
        MercurioGeneralState
        .MERCURIO_ENTRY_SELECTION_COMMITTED
    )


def test_detects_model_selection():
    elements = [
        {
            "tag": "input",
            "name": "datosForL",
            "type": "radio",
            "value": "EX01",
            "visible": True,
        },
    ]

    state = detect_mercurio_general_state(
        snapshot(
            "https://mercurio.delegaciondelgobierno.gob.es"
            "/mercurio/seleccionModelo-33.html",
            elements,
        )
    )

    assert state == (
        MercurioGeneralState.MERCURIO_MODEL_SELECTION
    )


def test_unknown_page_returns_none():
    assert (
        detect_mercurio_general_state(
            snapshot("https://example.com/")
        )
        is None
    )


def test_detects_twin_sede_home():
    state = detect_mercurio_general_state(
        snapshot("http://127.0.0.1:8767/")
    )

    assert state == MercurioGeneralState.SEDE_HOME


def test_detects_twin_entry_options():
    state = detect_mercurio_general_state(
        snapshot(
            (
                "http://127.0.0.1:8767"
                "/mercurio/entradaMercurio.html"
            ),
            [
                {
                    "tag": "select",
                    "id": "provincia",
                    "visible": True,
                },
                {
                    "tag": "input",
                    "name": "opcion",
                    "type": "radio",
                    "value": "BI",
                    "visible": True,
                },
            ],
        )
    )

    assert state == (
        MercurioGeneralState.MERCURIO_ENTRY_OPTIONS
    )


def test_detects_twin_model_selection():
    state = detect_mercurio_general_state(
        snapshot(
            (
                "http://localhost:8767"
                "/mercurio/seleccionModelo-33.html"
            ),
            [
                {
                    "tag": "input",
                    "name": "datosForL",
                    "type": "radio",
                    "value": "EX01",
                    "visible": True,
                },
            ],
        )
    )

    assert state == (
        MercurioGeneralState.MERCURIO_MODEL_SELECTION
    )
