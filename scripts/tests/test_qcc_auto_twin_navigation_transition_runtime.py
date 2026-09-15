import pytest

from backend.qcc.auto_twin.navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,
    AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,
    AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,
)

from backend.qcc.auto_twin.navigation_transition_runtime import (
    build_navigation_runtime_payload,
    inject_navigation_runtime_adapter,
    outgoing_navigation_transitions,
)


FP_A = "a" * 64
FP_B = "b" * 64


def _transition(
    *,
    selector='a[onclick="continuar(\'INI\');"]',
    frame_path="main",
):
    return {
        "schema_version":
            AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,

        "candidate_id":
            "candidate-1",

        "eligibility":
            AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,

        "evidence_source":
            AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,

        "real_observation_count":
            1,

        "candidate_status":
            "CANDIDATE",

        "before_fingerprint":
            FP_A,

        "after_fingerprint":
            FP_B,

        "action": {
            "kind":
                "LINK",

            "policy":
                "NAVIGATION_CANDIDATE",

            "selector":
                selector,

            "frame_path":
                frame_path,
        },
    }


def _states():
    return [
        {
            "state_id":
                "STATE_A",

            "fingerprint":
                FP_A,

            "runtime_entry":
                "states/01-STATE_A/runtime/index.html",
        },
        {
            "state_id":
                "STATE_B",

            "fingerprint":
                FP_B,

            "runtime_entry":
                "states/02-STATE_B/runtime/index.html",
        },
    ]


def test_runtime_resolves_fingerprints_to_local_states():
    payload = build_navigation_runtime_payload(
        [_transition()],
        _states(),
    )

    assert payload[
        "transition_count"
    ] == 1

    transition = payload[
        "transitions"
    ][0]

    assert (
        transition[
            "before_state_id"
        ]
        == "STATE_A"
    )

    assert (
        transition[
            "after_state_id"
        ]
        == "STATE_B"
    )

    assert (
        transition[
            "target_runtime_entry"
        ]
        == "states/02-STATE_B/runtime/index.html"
    )


def test_runtime_fails_closed_when_target_fingerprint_missing():
    states = _states()[:1]

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_AFTER_STATE_UNRESOLVED"
        ),
    ):
        build_navigation_runtime_payload(
            [_transition()],
            states,
        )


def test_runtime_fails_closed_on_ambiguous_fingerprint():
    states = _states()

    states.append({
        "state_id":
            "STATE_B_DUPLICATE",

        "fingerprint":
            FP_B,

        "runtime_entry":
            "states/03-STATE_B_DUPLICATE/runtime/index.html",
    })

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_AFTER_STATE_UNRESOLVED"
        ),
    ):
        build_navigation_runtime_payload(
            [_transition()],
            states,
        )


def test_runtime_v1_rejects_non_main_frame():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_FRAME_UNSUPPORTED"
        ),
    ):
        build_navigation_runtime_payload(
            [
                _transition(
                    frame_path="iframe:0",
                )
            ],
            _states(),
        )


def test_outgoing_transition_is_state_scoped():
    payload = build_navigation_runtime_payload(
        [_transition()],
        _states(),
    )

    assert len(
        outgoing_navigation_transitions(
            payload,
            "STATE_A",
        )
    ) == 1

    assert (
        outgoing_navigation_transitions(
            payload,
            "STATE_B",
        )
        == ()
    )


def test_adapter_intercepts_before_original_handler():
    payload = build_navigation_runtime_payload(
        [_transition()],
        _states(),
    )

    outgoing = outgoing_navigation_transitions(
        payload,
        "STATE_A",
    )

    html = """<!doctype html>
<html>
<head>
<script data-network-guard="1">
document.addEventListener("click", block, true);
</script>
</head>
<body>
<a href="#" onclick="continuar('INI');">Continuar</a>
</body>
</html>
"""

    result = inject_navigation_runtime_adapter(
        html,
        state_id="STATE_A",
        transitions=outgoing,
    )

    navigation_position = result.index(
        'data-qcc-auto-twin-navigation="1"'
    )

    guard_position = result.index(
        'data-network-guard="1"'
    )

    assert (
        navigation_position
        < guard_position
    )

    assert "event.preventDefault()" in result
    assert "event.stopImmediatePropagation()" in result

    assert (
        'window.location.assign("/" + entry)'
        in result
    )

    assert (
        "states/02-STATE_B/runtime/index.html"
        in result
    )


def test_empty_outgoing_does_not_modify_html():
    html = "<html><head></head><body>OK</body></html>"

    assert (
        inject_navigation_runtime_adapter(
            html,
            state_id="STATE_A",
            transitions=(),
        )
        == html
    )


def test_adapter_replacement_is_idempotent():
    payload = build_navigation_runtime_payload(
        [_transition()],
        _states(),
    )

    outgoing = outgoing_navigation_transitions(
        payload,
        "STATE_A",
    )

    original = (
        "<html><head></head>"
        "<body>"
        "<a onclick=\"continuar('INI');\">Continuar</a>"
        "</body></html>"
    )

    once = inject_navigation_runtime_adapter(
        original,
        state_id="STATE_A",
        transitions=outgoing,
    )

    twice = inject_navigation_runtime_adapter(
        once,
        state_id="STATE_A",
        transitions=outgoing,
    )

    assert (
        twice.count(
            'data-qcc-auto-twin-navigation="1"'
        )
        == 1
    )


def test_empty_transition_set_removes_carried_adapter():
    payload = build_navigation_runtime_payload(
        [_transition()],
        _states(),
    )

    outgoing = outgoing_navigation_transitions(
        payload,
        "STATE_A",
    )

    original = (
        "<html><head></head>"
        "<body>STATE A</body></html>"
    )

    with_adapter = inject_navigation_runtime_adapter(
        original,
        state_id="STATE_A",
        transitions=outgoing,
    )

    cleaned = inject_navigation_runtime_adapter(
        with_adapter,
        state_id="STATE_A",
        transitions=(),
    )

    assert (
        'data-qcc-auto-twin-navigation="1"'
        not in cleaned
    )

    assert "STATE A" in cleaned


def test_restore_navigation_action_identity_from_qcc_evidence():
    from backend.qcc.auto_twin.navigation_transition_runtime import (
        restore_navigation_action_identity,
    )

    source = (
        '<html><body>'
        '<a href="#" tooltip="asasd▒f" '
        'class="mbbuttton simbutton buttonAction adelanta">'
        '<span>Continuar</span>'
        '</a>'
        '</body></html>'
    )

    qcc_capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        {
                            "tag": "a",
                            "text": "CONTINUAR",
                            "attributes": {
                                "class":
                                    "mbbuttton simbutton "
                                    "buttonAction adelanta",
                                "href": "#",
                                "onclick":
                                    "continuar('INI');",
                                "tooltip":
                                    "asasd▒f",
                            },
                        },
                    ],
                },
            },
        ],
    }

    transitions = (
        {
            "action": {
                "selector":
                    'a[onclick="continuar(\'INI\');"]',
            },
        },
    )

    restored = (
        restore_navigation_action_identity(
            source,
            qcc_capture_payload=qcc_capture,
            transitions=transitions,
        )
    )

    assert (
        'onclick="continuar(&#x27;INI&#x27;);"'
        in restored
    )

    assert (
        'data-qcc-auto-twin-navigation-identity="1"'
        in restored
    )

    # Idempotent.
    restored_again = (
        restore_navigation_action_identity(
            restored,
            qcc_capture_payload=qcc_capture,
            transitions=transitions,
        )
    )

    assert restored_again == restored


def test_restore_navigation_action_identity_ignores_non_event_selector():
    from backend.qcc.auto_twin.navigation_transition_runtime import (
        restore_navigation_action_identity,
    )

    source = '<button id="continue">Continuar</button>'

    restored = (
        restore_navigation_action_identity(
            source,
            qcc_capture_payload={},
            transitions=(
                {
                    "action": {
                        "selector":
                            "#continue",
                    },
                },
            ),
        )
    )

    assert restored == source


def test_navigation_identity_ignores_commented_runtime_markup():
    from backend.qcc.auto_twin.navigation_transition_runtime import (
        restore_navigation_action_identity,
    )

    qcc_capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        {
                            "tag": "a",
                            "text": "CONTINUAR PRESENTACIÓN",
                            "attributes": {
                                "class":
                                    "simbutton mbbuttton adelanta",
                                "href":
                                    "#",
                                "onclick":
                                    "mostrarOpcion()",
                            },
                        },
                    ],
                },
            },
        ],
    }

    source_html = """
    <html>
      <body>
        <!--
        <a href="#"
           class="simbutton mbbuttton adelanta"
           onclick="entrar('N')">
        </a>
        -->

        <a href="#"
           class="simbutton mbbuttton adelanta">
          <span>Continuar</span>
          <span>presentación</span>
        </a>
      </body>
    </html>
    """

    transitions = (
        {
            "action": {
                "selector":
                    'a[onclick="mostrarOpcion()"]',
            },
        },
    )

    result = restore_navigation_action_identity(
        source_html,
        qcc_capture_payload=qcc_capture,
        transitions=transitions,
    )

    assert result.count(
        'onclick="mostrarOpcion()"'
    ) == 1

    assert result.count(
        'data-qcc-auto-twin-navigation-identity="1"'
    ) == 1

    assert "onclick=\"entrar('N')\"" in result


def test_navigation_identity_uses_visible_text_when_stable_attributes_absent():
    from backend.qcc.auto_twin.navigation_transition_runtime import (
        restore_navigation_action_identity,
    )

    qcc_capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        {
                            "tag": "button",
                            "text": "CONTINUAR",
                            "attributes": {
                                "onclick":
                                    "irOpcion()",
                            },
                        },
                    ],
                },
            },
        ],
    }

    source_html = """
    <html>
      <body>
        <button>
          Cancelar
        </button>

        <button>
          Continuar
        </button>
      </body>
    </html>
    """

    transitions = (
        {
            "action": {
                "selector":
                    'button[onclick="irOpcion()"]',
            },
        },
    )

    result = restore_navigation_action_identity(
        source_html,
        qcc_capture_payload=qcc_capture,
        transitions=transitions,
    )

    assert result.count(
        'onclick="irOpcion()"'
    ) == 1

    assert result.count(
        'data-qcc-auto-twin-navigation-identity="1"'
    ) == 1

    assert (
        "<button>\n          Cancelar"
        in result
    )



def test_contextual_opaque_action_fails_closed_without_default():
    fp_c = "c" * 64

    first = _transition()
    first["candidate_id"] = "candidate-b"
    first["after_fingerprint"] = FP_B

    second = _transition()
    second["candidate_id"] = "candidate-c"
    second["after_fingerprint"] = fp_c

    states = _states()

    states.append({
        "state_id":
            "STATE_C",

        "fingerprint":
            fp_c,

        "runtime_entry":
            "states/03-STATE_C/runtime/index.html",
    })

    payload = build_navigation_runtime_payload(
        [
            first,
            second,
        ],
        states,
    )

    assert payload[
        "transition_count"
    ] == 0

    assert payload[
        "interactive_transition_count"
    ] == 0

    assert payload[
        "contextual_default_count"
    ] == 0

    assert payload[
        "contextual_unresolved_count"
    ] == 1

    assert (
        outgoing_navigation_transitions(
            payload,
            "STATE_A",
        )
        == ()
    )





def test_contextual_opaque_action_does_not_inject_navigation_adapter():
    fp_c = "c" * 64

    first = _transition()
    first["candidate_id"] = "candidate-b"

    second = _transition()
    second["candidate_id"] = "candidate-c"
    second["after_fingerprint"] = fp_c

    states = _states()

    states.append({
        "state_id":
            "STATE_C",

        "fingerprint":
            fp_c,

        "runtime_entry":
            "states/03-STATE_C/runtime/index.html",
    })

    payload = build_navigation_runtime_payload(
        [
            first,
            second,
        ],
        states,
    )

    outgoing = outgoing_navigation_transitions(
        payload,
        "STATE_A",
    )

    assert outgoing == ()

    html = (
        "<html><head></head><body>"
        "<a href=\"#\" onclick=\"continuar('INI');\">"
        "Continuar"
        "</a>"
        "</body></html>"
    )

    result = inject_navigation_runtime_adapter(
        html,
        state_id="STATE_A",
        transitions=outgoing,
    )

    assert result == html

    assert (
        'data-qcc-auto-twin-navigation="1"'
        not in result
    )




def test_deterministic_runtime_behavior_is_unchanged():
    payload = build_navigation_runtime_payload(
        [_transition()],
        _states(),
    )

    assert payload["transition_count"] == 1
    assert payload["contextual_action_count"] == 0
    assert payload["contextual_actions"] == []

    assert (
        payload["transitions"][0][
            "after_state_id"
        ]
        == "STATE_B"
    )



def test_deterministic_same_outcome_evidence_is_one_runtime_route():
    first = _transition()
    first["candidate_id"] = "candidate-130"
    first["navigation_context"] = [
        {
            "frame_path":
                "main",

            "key":
                "name:datosForAut:RADIO",

            "kind":
                "RADIO",

            "selector":
                'input[type="radio"][name="datosForAut"]',

            "selected_values":
                ["130"],
        },
    ]

    second = _transition()
    second["candidate_id"] = "candidate-131"
    second["navigation_context"] = [
        {
            "frame_path":
                "main",

            "key":
                "name:datosForAut:RADIO",

            "kind":
                "RADIO",

            "selector":
                'input[type="radio"][name="datosForAut"]',

            "selected_values":
                ["131"],
        },
    ]

    payload = build_navigation_runtime_payload(
        [
            first,
            second,
        ],
        _states(),
    )

    assert (
        payload[
            "transition_count"
        ]
        == 1
    )

    assert (
        payload[
            "interactive_transition_count"
        ]
        == 1
    )

    assert (
        payload[
            "contextual_action_count"
        ]
        == 0
    )

    assert (
        payload[
            "contextual_resolved_count"
        ]
        == 0
    )

    assert (
        payload[
            "contextual_unresolved_count"
        ]
        == 0
    )

    transition = payload[
        "transitions"
    ][0]

    assert (
        transition[
            "before_state_id"
        ]
        == "STATE_A"
    )

    assert (
        transition[
            "after_state_id"
        ]
        == "STATE_B"
    )

    assert (
        transition[
            "interactive_execution_mode"
        ]
        == "DETERMINISTIC"
    )

    assert (
        transition[
            "navigation_context"
        ]
        == []
    )

    assert (
        transition[
            "context_signature"
        ]
        is None
    )

    assert (
        transition[
            "discriminator_keys"
        ]
        == []
    )

    assert set(
        transition[
            "candidate_ids"
        ]
    ) == {
        "candidate-130",
        "candidate-131",
    }

    assert (
        transition[
            "real_observation_count"
        ]
        == 2
    )


# --- WO 2D-20M: DOM actionability eligibility -----------------------


def _duplicate_id_qcc_capture(
    *,
    target_onclick,
    other_onclick,
    target_rect=None,
    target_in_viewport=None,
    target_hidden_style=None,
    other_rect=None,
    other_in_viewport=None,
    other_hidden_style=None,
):
    def _element(
        onclick,
        rect,
        in_viewport,
        style,
    ):
        attributes = {
            "class": "simbutton mbbuttton",
            "href": "#",
            "id": "continuaPer",
        }

        if onclick is not None:
            attributes["onclick"] = onclick

        if style is not None:
            attributes["style"] = style

        element = {
            "tag": "a",
            "text": "Continuar",
            "attributes": attributes,
        }

        if rect is not None:
            element["rect"] = rect

        if in_viewport is not None:
            element["in_viewport"] = in_viewport

        return element

    return {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        _element(
                            target_onclick,
                            target_rect,
                            target_in_viewport,
                            target_hidden_style,
                        ),
                        _element(
                            other_onclick,
                            other_rect,
                            other_in_viewport,
                            other_hidden_style,
                        ),
                    ],
                },
            },
        ],
    }


_DUPLICATE_RUNTIME_HTML = (
    "<html><body>"
    '<div id="wrap-target">'
    '<a href="#" class="simbutton mbbuttton" id="continuaPer">'
    "Continuar</a></div>"
    '<div id="wrap-other">'
    '<a href="#" class="simbutton mbbuttton" id="continuaPer">'
    "Continuar</a></div>"
    "</body></html>"
)


def _section(
    html,
    marker,
):
    start = html.index(marker)
    end = html.index(
        "</div>",
        start,
    )
    return html[start:end]


def test_duplicate_selector_zero_geometry_node_resolves_to_rendered_node():
    from backend.qcc.auto_twin.navigation_transition_runtime import (
        restore_navigation_action_identity,
    )

    qcc_capture = _duplicate_id_qcc_capture(
        target_onclick="goA();",
        other_onclick="goB();",
        target_rect={
            "width": 100,
            "height": 20,
        },
        other_rect={
            "width": 0,
            "height": 0,
        },
    )

    transitions = (
        {
            "action": {
                "selector":
                    'a[onclick="goA();"]',
            },
        },
    )

    result = restore_navigation_action_identity(
        _DUPLICATE_RUNTIME_HTML,
        qcc_capture_payload=qcc_capture,
        transitions=transitions,
    )

    target_section = _section(
        result,
        "wrap-target",
    )

    other_section = _section(
        result,
        "wrap-other",
    )

    assert 'onclick="goA();"' in target_section
    assert (
        'data-qcc-auto-twin-navigation-identity="1"'
        in target_section
    )

    assert "onclick" not in other_section


def test_rendered_but_off_screen_node_remains_eligible():
    from backend.qcc.auto_twin.navigation_transition_runtime import (
        restore_navigation_action_identity,
    )

    qcc_capture = _duplicate_id_qcc_capture(
        target_onclick="goA();",
        other_onclick="goB();",
        # Genuinely rendered (non-zero geometry) but scrolled out of
        # the current viewport -- must still be eligible.
        target_rect={
            "width": 100,
            "height": 20,
        },
        target_in_viewport=False,
        other_rect={
            "width": 0,
            "height": 0,
        },
    )

    transitions = (
        {
            "action": {
                "selector":
                    'a[onclick="goA();"]',
            },
        },
    )

    result = restore_navigation_action_identity(
        _DUPLICATE_RUNTIME_HTML,
        qcc_capture_payload=qcc_capture,
        transitions=transitions,
    )

    target_section = _section(
        result,
        "wrap-target",
    )

    assert 'onclick="goA();"' in target_section


def test_hidden_inactive_panel_duplicate_resolves_without_ambiguity():
    from backend.qcc.auto_twin.navigation_transition_runtime import (
        restore_navigation_action_identity,
    )

    qcc_capture = _duplicate_id_qcc_capture(
        target_onclick="goA();",
        other_onclick="goB();",
        target_rect={
            "width": 100,
            "height": 20,
        },
        # Provably owned by an inactive panel via its own style, not
        # geometry -- a second, independent eligibility signal.
        other_hidden_style="display: none;",
        other_rect={
            "width": 100,
            "height": 20,
        },
    )

    transitions = (
        {
            "action": {
                "selector":
                    'a[onclick="goA();"]',
            },
        },
    )

    result = restore_navigation_action_identity(
        _DUPLICATE_RUNTIME_HTML,
        qcc_capture_payload=qcc_capture,
        transitions=transitions,
    )

    target_section = _section(
        result,
        "wrap-target",
    )

    other_section = _section(
        result,
        "wrap-other",
    )

    assert 'onclick="goA();"' in target_section
    assert "onclick" not in other_section


def test_two_genuinely_actionable_indistinguishable_nodes_stay_ambiguous():
    from backend.qcc.auto_twin.navigation_transition_runtime import (
        restore_navigation_action_identity,
    )

    qcc_capture = _duplicate_id_qcc_capture(
        target_onclick="goA();",
        other_onclick="goB();",
        target_rect={
            "width": 100,
            "height": 20,
        },
        other_rect={
            "width": 100,
            "height": 20,
        },
    )

    transitions = (
        {
            "action": {
                "selector":
                    'a[onclick="goA();"]',
            },
        },
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_NAVIGATION_RUNTIME_TARGET_AMBIGUOUS"
        ),
    ):
        restore_navigation_action_identity(
            _DUPLICATE_RUNTIME_HTML,
            qcc_capture_payload=qcc_capture,
            transitions=transitions,
        )


def test_zero_eligible_nodes_is_governed_non_success_not_an_error():
    from backend.qcc.auto_twin.navigation_transition_runtime import (
        restore_navigation_action_identity,
    )

    qcc_capture = _duplicate_id_qcc_capture(
        target_onclick="goA();",
        other_onclick="goB();",
        target_rect={
            "width": 0,
            "height": 0,
        },
        other_rect={
            "width": 0,
            "height": 0,
        },
    )

    transitions = (
        {
            "action": {
                "selector":
                    'a[onclick="goA();"]',
            },
        },
    )

    result = restore_navigation_action_identity(
        _DUPLICATE_RUNTIME_HTML,
        qcc_capture_payload=qcc_capture,
        transitions=transitions,
    )

    # No exception, and the HTML is left untouched for this
    # transition -- a governed non-success, not a crash.
    assert result == _DUPLICATE_RUNTIME_HTML
