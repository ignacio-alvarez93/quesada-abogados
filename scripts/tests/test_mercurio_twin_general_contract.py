from tools.mercurio_lab.core.catalog import (
    ASTURIAS_PROVINCE_CODE,
    observed_models_for_province,
)
from tools.mercurio_lab.core.routes import (
    MERCURIO_ENTRADA_PATH,
    model_selection_path,
)
from tools.mercurio_lab.core.states import (
    GENERAL_TRANSITIONS,
    MercurioGeneralState,
)


def test_general_entry_states_are_not_url_states():
    states = (
        MercurioGeneralState.MERCURIO_ENTRY_IDLE,
        MercurioGeneralState.MERCURIO_ENTRY_OPTIONS,
        MercurioGeneralState.MERCURIO_ENTRY_SELECTION_COMMITTED,
    )

    assert len(set(states)) == 3

    assert MERCURIO_ENTRADA_PATH == (
        "/mercurio/entradaMercurio.html"
    )


def test_asturias_model_selection_route():
    assert model_selection_path(
        ASTURIAS_PROVINCE_CODE
    ) == "/mercurio/seleccionModelo-33.html"


def test_asturias_observed_model_catalog():
    models = observed_models_for_province("33")

    assert "EX01" in models
    assert "EX02" in models
    assert "EX26" in models
    assert len(models) == 17


def test_entry_transition_reaches_model_selection():
    state = MercurioGeneralState.MERCURIO_ENTRY_IDLE

    state = GENERAL_TRANSITIONS[state]

    assert (
        state
        == MercurioGeneralState.MERCURIO_ENTRY_OPTIONS
    )

    state = GENERAL_TRANSITIONS[state]

    assert state == (
        MercurioGeneralState
        .MERCURIO_ENTRY_SELECTION_COMMITTED
    )

    state = GENERAL_TRANSITIONS[state]

    assert (
        state
        == MercurioGeneralState.MERCURIO_MODEL_SELECTION
    )


def test_model_catalog_is_shared_across_provinces():
    from tools.mercurio_lab.core.catalog import (
        models_for_province,
    )

    asturias = models_for_province("33")
    madrid = models_for_province("28")
    barcelona = models_for_province("8")

    assert asturias == madrid
    assert madrid == barcelona

    assert len(asturias) == 17
    assert "EX01" in madrid
    assert "EX26" in barcelona
