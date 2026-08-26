from copy import deepcopy
from pathlib import Path

from backend.automation.site_architecture import (
    build_functional_state_fingerprint,
    build_navigation_graph,
    detect_state_transition,
)
from tools.mercurio_lab.core.state_detector import (
    detect_mercurio_general_state,
)
from tools.mercurio_lab.core.states import (
    MercurioGeneralState,
)


BASE = (
    "https://mercurio.delegaciondelgobierno.gob.es"
)

ENTRY_PATH = (
    "/mercurio/entradaMercurio.html"
)

MODEL_PATH = (
    "/mercurio/seleccionModelo-33.html"
)


def _action(
    *,
    kind,
    policy,
    selector,
    visible,
    tag,
    element_id="",
    name="",
    element_type="",
    role="",
):
    return {
        "frame_path":
            "main",

        "kind":
            kind,

        "policy":
            policy,

        "selector":
            selector,

        "semantics":
            (),

        "interaction": {
            "state":
                (
                    "INTERACTABLE"
                    if visible
                    else "HIDDEN"
                ),

            "visible":
                visible,

            "interactable":
                visible,

            "disabled":
                False,
        },

        "state_signals": {
            "aria_selected":
                None,

            "aria_expanded":
                None,

            "aria_pressed":
                None,

            "aria_current":
                None,
        },

        "element": {
            "tag":
                tag,

            "id":
                element_id,

            "name":
                name,

            "type":
                element_type,

            "role":
                role,
        },
    }


def _entry_actions(
    options_visible,
):
    return (
        _action(
            kind="BUTTON",
            policy="REQUIRES_POLICY",
            selector=(
                '[aria-label='
                '"CONTINUAR PRESENTACIÓN"]'
            ),
            visible=True,
            tag="a",
        ),

        _action(
            kind="RADIO",
            policy="STATE_CHANGE_CANDIDATE",
            selector="#bscIniciales",
            visible=options_visible,
            tag="input",
            element_id="bscIniciales",
            name="opcion",
            element_type="radio",
        ),

        _action(
            kind="SELECT",
            policy="STATE_CHANGE_CANDIDATE",
            selector="#provincia",
            visible=options_visible,
            tag="select",
            element_id="provincia",
            name="provincia",
        ),

        _action(
            kind="BUTTON",
            policy="REQUIRES_POLICY",
            selector=(
                'button[onclick="irOpcion()"]'
            ),
            visible=options_visible,
            tag="button",
            element_type="button",
        ),
    )


def _entry_elements(
    *,
    options_visible,
    committed=False,
):
    elements = [
        {
            "tag":
                "input",

            "id":
                "bscIniciales",

            "name":
                "opcion",

            "type":
                "radio",

            "value":
                "BI",

            "visible":
                options_visible,
        },

        {
            "tag":
                "select",

            "id":
                "provincia",

            "name":
                "provincia",

            "visible":
                options_visible,
        },
    ]

    if committed:
        elements.extend([
            {
                "tag":
                    "input",

                "name":
                    "tipoSolicitud",

                "type":
                    "hidden",

                "value":
                    "INI",

                "visible":
                    False,
            },

            {
                "tag":
                    "input",

                "name":
                    "codProvincia",

                "type":
                    "hidden",

                "value":
                    "33",

                "visible":
                    False,
            },
        ])

    return tuple(elements)


def _entry_snapshot(
    *,
    options_visible=False,
    committed=False,
):
    return {
        "schema_version":
            1,

        "page": {
            "url":
                BASE + ENTRY_PATH,

            "origin":
                BASE,

            "pathname":
                ENTRY_PATH,

            "query":
                "",

            "title":
                "Autorizaciones de Extranjería",

            "signature":
                None,
        },

        "elements":
            _entry_elements(
                options_visible=options_visible,
                committed=committed,
            ),

        "actions":
            _entry_actions(
                options_visible
            ),

        "catalogs":
            (),

        "catalog_relations":
            (),
    }


def _model_snapshot():
    return {
        "schema_version":
            1,

        "page": {
            "url":
                BASE + MODEL_PATH,

            "origin":
                BASE,

            "pathname":
                MODEL_PATH,

            "query":
                "",

            "title":
                "Autorizaciones de Extranjería",

            "signature":
                None,
        },

        "elements": (
            {
                "tag":
                    "input",

                "name":
                    "datosForL",

                "type":
                    "radio",

                "value":
                    "EX01",

                "visible":
                    True,
            },
        ),

        "actions": (
            _action(
                kind="RADIO",
                policy=(
                    "STATE_CHANGE_CANDIDATE"
                ),
                selector="#tini_EX01",
                visible=True,
                tag="input",
                element_id="tini_EX01",
                name="datosForL",
                element_type="radio",
            ),

            _action(
                kind="BUTTON",
                policy="REQUIRES_POLICY",
                selector="#btncont",
                visible=True,
                tag="a",
                element_id="btncont",
            ),
        ),

        "catalogs":
            (),

        "catalog_relations":
            (),
    }


def _for_transition(
    snapshot,
):
    """
    El detector simbólico usa elements.

    El fingerprint/grafo no necesita transportar
    esos valores DOM y contract_diff tampoco los
    necesita para esta prueba de proyección.
    """

    result = deepcopy(
        snapshot
    )

    result["elements"] = ()

    return result


def test_mercurio_symbolic_states_are_detected():
    idle = _entry_snapshot()

    options = _entry_snapshot(
        options_visible=True
    )

    committed = _entry_snapshot(
        committed=True
    )

    model = _model_snapshot()

    assert (
        detect_mercurio_general_state(
            idle
        )
        == MercurioGeneralState
        .MERCURIO_ENTRY_IDLE
    )

    assert (
        detect_mercurio_general_state(
            options
        )
        == MercurioGeneralState
        .MERCURIO_ENTRY_OPTIONS
    )

    assert (
        detect_mercurio_general_state(
            committed
        )
        == MercurioGeneralState
        .MERCURIO_ENTRY_SELECTION_COMMITTED
    )

    assert (
        detect_mercurio_general_state(
            model
        )
        == MercurioGeneralState
        .MERCURIO_MODEL_SELECTION
    )


def test_committed_symbolic_state_collapses_to_idle_fingerprint():
    idle = (
        build_functional_state_fingerprint(
            _entry_snapshot()
        )
    )

    options = (
        build_functional_state_fingerprint(
            _entry_snapshot(
                options_visible=True
            )
        )
    )

    committed = (
        build_functional_state_fingerprint(
            _entry_snapshot(
                committed=True
            )
        )
    )

    model = (
        build_functional_state_fingerprint(
            _model_snapshot()
        )
    )

    assert idle != options

    # El estado committed solo cambia valores
    # de formulario/dataset internos.
    assert committed == idle

    assert model != idle
    assert model != options


def test_mercurio_projection_builds_three_functional_nodes():
    idle = _entry_snapshot()

    options = _entry_snapshot(
        options_visible=True
    )

    committed = _entry_snapshot(
        committed=True
    )

    model = _model_snapshot()

    open_options = (
        detect_state_transition(
            _for_transition(idle),
            _for_transition(options),
            action={
                "kind":
                    "BUTTON",

                "policy":
                    "REQUIRES_POLICY",

                "selector":
                    (
                        '[aria-label='
                        '"CONTINUAR PRESENTACIÓN"]'
                    ),

                "frame_path":
                    "main",
            },
        )
    )

    commit_selection = (
        detect_state_transition(
            _for_transition(options),
            _for_transition(committed),
            action={
                "kind":
                    "BUTTON",

                "policy":
                    "REQUIRES_POLICY",

                "selector":
                    (
                        'button['
                        'onclick="irOpcion()"]'
                    ),

                "frame_path":
                    "main",
            },
        )
    )

    automatic_redirect = (
        detect_state_transition(
            _for_transition(committed),
            _for_transition(model),
            action=None,
        )
    )

    assert open_options["changed"] is True
    assert commit_selection["changed"] is True

    assert (
        automatic_redirect["changed"]
        is True
    )

    graph = build_navigation_graph(
        (
            open_options,
            commit_selection,
            automatic_redirect,
        )
    )

    # Cuatro estados simbólicos Mercurio
    # proyectan sobre tres estados funcionales QCC.
    assert graph["node_count"] == 3

    assert graph["edge_count"] == 3

    assert (
        graph["changed_observation_count"]
        == 3
    )


def test_projection_keeps_execution_policy_outside_graph():
    transition = (
        detect_state_transition(
            _for_transition(
                _entry_snapshot()
            ),
            _for_transition(
                _entry_snapshot(
                    options_visible=True
                )
            ),
            action={
                "kind":
                    "BUTTON",

                # Política estructural del inventario.
                # No es autorización de ejecución.
                "policy":
                    "REQUIRES_POLICY",

                "selector":
                    "#presentation",

                "frame_path":
                    "main",
            },
        )
    )

    graph = build_navigation_graph(
        [transition]
    )

    edge = graph["edges"][0]

    assert (
        edge["action"]["policy"]
        == "REQUIRES_POLICY"
    )

    assert (
        "AUTOMATION_ALLOWED"
        not in str(graph)
    )

    assert (
        "HUMAN_ONLY"
        not in str(graph)
    )


def test_generic_navigation_graph_contains_no_mercurio_coupling():
    source = Path(
        "backend/automation/"
        "site_architecture/"
        "navigation_graph.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "MERCURIO" not in source.upper()
