"""Regression for QCC_AUTO_TWIN_NAVIGATION_ONCLICK_STRUCTURAL_IDENTITY_V1.

Work order: QCC_AUTO_TWIN_MATERIALIZATION_ACTION_TRACE_CLOSURE_V1.

Root cause:

selectors.py deliberately strips onclick literal arguments into a PII
-free structural signature before it is ever persisted as a
navigation transition's action.selector (e.g. the physical attribute
onclick="continuar('INI');" becomes the durable selector
a[onclick="continuar();"] -- see
QCC_ONCLICK_STRUCTURAL_SIGNATURE_V1 in
backend/automation/site_architecture/selectors.py).

navigation_transition_runtime.py's restore_navigation_action_identity()
compared that structural selector value against the RAW captured
onclick attribute using plain string equality. Any handler observed
with a real literal argument therefore never equals its own stripped
selector, so evidence_matches was always empty
-> QCC_AUTO_TWIN_NAVIGATION_ACTION_EVIDENCE_AMBIGUOUS
-> the transition is excluded from the materialized runtime route and
recorded in deferred_navigation_transitions.json, even though exactly
one physical element genuinely owns the action.

This reproduces the confirmed Mercurio operational failure: the
initial state's a[onclick="continuar('INI');"] causal action --
learned from three REAL human observations -- was deferred instead of
materialized, so the Twin could not be navigated from its initial
state through normal interaction.

Fix: onclick identity comparisons (both evidence-matching and the
runtime-DOM existing-attribute conflict check) now compare structural
signatures for the onclick attribute specifically, reusing the exact
same transform selectors.py used to build the selector
(onclick_structural_signature()). Every other on* attribute keeps
exact literal comparison; a genuine mismatch (different handler, or
two distinct physical elements) still fails closed exactly as before.

T4 (zero AFTER -> deferred) and T12 (ACTIVE governance) are exercised
by the existing navigation_transition_runtime / active_revision test
suites and are not duplicated here.
"""

import json
from pathlib import Path

import pytest

from backend.automation.site_architecture.selectors import (
    onclick_structural_signature,
)
from backend.qcc.auto_twin.materialization_builder import (
    AUTO_TWIN_DEFERRED_NAVIGATION_TRANSITIONS_FILENAME,
    AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    materialize_auto_twin_plan,
)
from backend.qcc.auto_twin.materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
    AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
)
from backend.qcc.auto_twin.navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,
    AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,
    AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,
)
from backend.qcc.auto_twin.navigation_transition_runtime import (
    restore_navigation_action_identity,
)


TWIN_KEY = "materialization_action_trace_v1"
SITE_CODE = "MAT_TRACE_V1"

FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64
FP_D = "d" * 64
FP_E = "e" * 64
FP_F = "f" * 64

# The real Mercurio selector/attribute pair from the confirmed
# operational evidence (see .fabric_evidence/initial_qcc_capture.json
# and human_navigation_candidates.json).
STRUCTURAL_SELECTOR = 'a[onclick="continuar();"]'
PHYSICAL_ONCLICK = "continuar('INI');"


def test_onclick_structural_signature_strips_literal_argument():
    """Sanity: the selector value is indeed the structural form."""

    assert (
        onclick_structural_signature(PHYSICAL_ONCLICK)
        == "continuar();"
    )


def test_literal_argument_onclick_is_no_longer_ambiguous():
    """T1 + T3: a single physical element carrying the real literal
    argument resolves to exactly one evidence match and its identity
    is restored, instead of being excluded as ambiguous."""

    source_html = (
        "<html><body>"
        f'<a href="#" onclick="{PHYSICAL_ONCLICK}">Continuar</a>'
        "</body></html>"
    )

    qcc_capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        {
                            "tag": "a",
                            "text": "Continuar",
                            "attributes": {
                                "href": "#",
                                "onclick": PHYSICAL_ONCLICK,
                            },
                        },
                    ],
                },
            },
        ],
    }

    transition = {
        "action": {
            "selector": STRUCTURAL_SELECTOR,
        },
    }

    result, excluded = restore_navigation_action_identity(
        source_html,
        qcc_capture_payload=qcc_capture,
        transitions=(transition,),
    )

    assert excluded == ()

    # The attribute already carries the literal argument: no conflict,
    # no fabricated rewrite, and the original literal is preserved.
    assert PHYSICAL_ONCLICK in result

    # Idempotent: re-running restoration changes nothing further.
    result_again, excluded_again = restore_navigation_action_identity(
        result,
        qcc_capture_payload=qcc_capture,
        transitions=(transition,),
    )

    assert excluded_again == ()
    assert result_again == result


def test_non_onclick_event_attribute_keeps_exact_literal_comparison():
    """Control: the structural relaxation is onclick-specific. A
    genuinely different onchange value must still be treated as a
    conflict, never silently accepted."""

    source_html = (
        '<html><body><select onchange="otraCosa();"></select>'
        "</body></html>"
    )

    qcc_capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        {
                            "tag": "select",
                            "text": "",
                            "attributes": {
                                "onchange": "otraCosa();",
                            },
                        },
                    ],
                },
            },
        ],
    }

    transition = {
        "action": {
            "selector": 'select[onchange="cambiar();"]',
        },
    }

    # The mismatched literal evidence never attributes to this
    # element for a non-onclick attribute (no structural relaxation
    # applies), so the transition is excluded -- a governed
    # non-success, not a crash.
    result, excluded = restore_navigation_action_identity(
        source_html,
        qcc_capture_payload=qcc_capture,
        transitions=(transition,),
    )

    assert result == source_html
    assert len(excluded) == 1
    assert excluded[0][1] == (
        "QCC_AUTO_TWIN_NAVIGATION_ACTION_EVIDENCE_AMBIGUOUS:"
        + 'select[onchange="cambiar();"]'
    )


def test_two_distinct_literals_sharing_one_structural_signature_stay_ambiguous():
    """T5: two physically distinct elements whose onclick literals
    collapse to the SAME structural signature but are genuinely
    different physical controls must still fail closed -- the fix
    must never fabricate uniqueness that the evidence does not
    support."""

    source_html = (
        "<html><body>"
        '<a id="go1" onclick="continuar(\'INI\');">Continuar 1</a>'
        '<a id="go2" onclick="continuar(\'OTRA\');">Continuar 2</a>'
        "</body></html>"
    )

    qcc_capture = {
        "frames": [
            {
                "frame_id": 0,
                "result": {
                    "elements": [
                        {
                            "tag": "a",
                            "text": "Continuar 1",
                            "attributes": {
                                "id": "go1",
                                "onclick": "continuar('INI');",
                            },
                        },
                        {
                            "tag": "a",
                            "text": "Continuar 2",
                            "attributes": {
                                "id": "go2",
                                "onclick": "continuar('OTRA');",
                            },
                        },
                    ],
                },
            },
        ],
    }

    transition = {
        "action": {
            "selector": STRUCTURAL_SELECTOR,
        },
    }

    result, excluded = restore_navigation_action_identity(
        source_html,
        qcc_capture_payload=qcc_capture,
        transitions=(transition,),
    )

    assert result == source_html
    assert len(excluded) == 1
    assert excluded[0][1] == (
        "QCC_AUTO_TWIN_NAVIGATION_ACTION_EVIDENCE_AMBIGUOUS:"
        + STRUCTURAL_SELECTOR
    )


def _navigation_transition(
    *,
    candidate_id,
    before_fingerprint,
    after_fingerprint,
    selector,
    policy="NAVIGATION_CANDIDATE",
):
    return {
        "schema_version":
            AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,

        "candidate_id":
            candidate_id,

        "eligibility":
            AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,

        "evidence_source":
            AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,

        "real_observation_count":
            3,

        "before_fingerprint":
            before_fingerprint,

        "after_fingerprint":
            after_fingerprint,

        "action": {
            "kind": "LINK",
            "policy": policy,
            "selector": selector,
            "frame_path": "main",
        },
    }


def _write_state(
    base,
    index,
    state_id,
    pathname,
    fingerprint,
    *,
    html_body,
    elements,
):
    state_root = base / "states" / f"{index:02d}-{state_id}"
    runtime = state_root / "runtime"
    runtime.mkdir(parents=True)

    (runtime / "state.json").write_text(
        json.dumps({
            "state_id": state_id,
            "source_capture_id": f"cap-{state_id}-0",
            "pathname": pathname,
            "functional_state": None,
            "fingerprint": fingerprint,
        }),
        encoding="utf-8",
    )

    (runtime / "index.html").write_text(
        "<html><body>" + html_body + "</body></html>",
        encoding="utf-8",
    )

    (runtime / "shadow_styles.json").write_text("{}", encoding="utf-8")

    evidence = state_root / "evidence"
    evidence.mkdir()
    (evidence / "qcc_capture.json").write_text(
        json.dumps({
            "frames": [{
                "frame_id": 0,
                "result": {"elements": elements},
            }],
        }),
        encoding="utf-8",
    )

    source = state_root / "source"
    source.mkdir()
    (source / "page.html").write_text("SRC", encoding="utf-8")


@pytest.fixture
def golden_world(tmp_path):
    (tmp_path / "captures").mkdir()

    materialized_root = tmp_path / "materialized"
    base = materialized_root / TWIN_KEY / "matrev-golden"
    (base / "runtime").mkdir(parents=True)

    (base / "runtime" / "renderer.json").write_text(
        json.dumps({
            "renderer_version": AUTO_TWIN_RUNTIME_RENDERER_VERSION,
        }),
        encoding="utf-8",
    )

    # STATE_A: the real Mercurio initial-state shape -- one physical
    # element, structural selector, literal argument in the DOM.
    _write_state(
        base, 1, "STATE_A", "/mercurio/inicioMercurio.html", FP_A,
        html_body=(
            f'<a href="#" onclick="{PHYSICAL_ONCLICK}">Continuar</a>'
        ),
        elements=[
            {
                "tag": "a",
                "text": "Continuar",
                "attributes": {
                    "href": "#",
                    "onclick": PHYSICAL_ONCLICK,
                },
            },
        ],
    )

    _write_state(
        base, 2, "STATE_B", "/mercurio/modoAcceso.html", FP_B,
        html_body="<p>after continuar</p>",
        elements=[],
    )

    # STATE_E / STATE_F: an unrelated before-state with its own
    # continuar(...) action and its own, different, after-state --
    # T2/T8: proves the fix does not cross-bind independent physical
    # states that merely share a structural signature.
    _write_state(
        base, 3, "STATE_E", "/mercurio/otraPantalla.html", FP_E,
        html_body=(
            '<a href="#" onclick="continuar(\'OTRA\');">Continuar</a>'
        ),
        elements=[
            {
                "tag": "a",
                "text": "Continuar",
                "attributes": {
                    "href": "#",
                    "onclick": "continuar('OTRA');",
                },
            },
        ],
    )

    _write_state(
        base, 4, "STATE_F", "/mercurio/otroDestino.html", FP_F,
        html_body="<p>after otra</p>",
        elements=[],
    )

    manifest = [
        {
            "state_index": index,
            "state_id": state_id,
            "source_capture_id": f"cap-{state_id}-0",
            "pathname": pathname,
            "functional_state": None,
            "rendering_profile_id": "MATERIALIZED_CARRY_FORWARD",
            "source_mode": AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
        }
        for index, state_id, pathname in (
            (1, "STATE_A", "/mercurio/inicioMercurio.html"),
            (2, "STATE_B", "/mercurio/modoAcceso.html"),
            (3, "STATE_E", "/mercurio/otraPantalla.html"),
            (4, "STATE_F", "/mercurio/otroDestino.html"),
        )
    ]

    plan = {
        "schema_version": 1,
        "plan_type": AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
        "plan_id": "matplan-materialization-action-trace-v1",
        "twin_key": TWIN_KEY,
        "materialization_mode": "BOOTSTRAP_REAL",
        "generation_source": "REAL_EVIDENCE_ONLY",
        "required_origin": "https://example.test",
        "required_profile_key": "twin_discovery",
        "base_materialized_revision_id": "matrev-golden",
        "source_capture_ids": [
            "cap-STATE_A-0",
            "cap-STATE_B-0",
            "cap-STATE_E-0",
            "cap-STATE_F-0",
        ],
        "source_evidence_sha256": "a" * 64,
        "artifact_operations": [],
        "state_manifest": manifest,
        "navigation_transitions": [
            _navigation_transition(
                candidate_id="cand-continuar-a",
                before_fingerprint=FP_A,
                after_fingerprint=FP_B,
                selector=STRUCTURAL_SELECTOR,
                # T6: HUMAN_ONLY-observed action is still TWIN_ELIGIBLE
                # / materializable -- this does not grant REAL
                # automation authority.
                policy="HUMAN_ONLY",
            ),
            _navigation_transition(
                candidate_id="cand-continuar-e",
                before_fingerprint=FP_E,
                after_fingerprint=FP_F,
                selector=STRUCTURAL_SELECTOR,
            ),
        ],
    }

    return materialized_root, plan


def _embedded_navigation_transitions(html):
    marker = "const transitions = "

    start = html.index(marker) + len(marker)
    end = html.index(";\n", start)

    return json.loads(html[start:end])


def _materialize(golden_world):
    materialized_root, plan = golden_world

    built = materialize_auto_twin_plan(
        plan=plan,
        source_root=materialized_root.parent / "captures",
        materialized_root=materialized_root,
        procedure_code=SITE_CODE,
        flow_variant="SITE_LEVEL",
    )

    return Path(built["revision_dir"])


def test_structural_onclick_action_materializes_as_executable_route(
    golden_world,
):
    """T1 + T3 + T6 + T7 + T9 + T10 + T11, at the full materialization
    level: the real Mercurio-shaped initial-state action is no longer
    deferred, is wired up as a click target, and its independent
    sibling (STATE_E -> STATE_F, sharing only the structural
    signature) resolves separately and correctly."""

    revision_dir = _materialize(golden_world)

    state_a_html = (
        revision_dir
        / "states" / "01-STATE_A" / "runtime" / "index.html"
    ).read_text(encoding="utf-8")

    state_e_html = (
        revision_dir
        / "states" / "03-STATE_E" / "runtime" / "index.html"
    ).read_text(encoding="utf-8")

    # T1/T3: materialized, wired up, and the physical literal survives
    # untouched (never fabricated, never genericized away).
    assert PHYSICAL_ONCLICK in state_a_html
    assert 'data-qcc-auto-twin-navigation="1"' in state_a_html

    state_a_transitions = _embedded_navigation_transitions(
        state_a_html
    )

    assert len(state_a_transitions) == 1
    assert (
        state_a_transitions[0]["target_runtime_entry"]
        == "states/02-STATE_B/runtime/index.html"
    )

    # T6: HUMAN_ONLY provenance is preserved through materialization
    # (learned/represented in the Twin, no REAL authority implied by
    # this local artifact).
    assert state_a_transitions[0]["candidate_id"] == "cand-continuar-a"

    # T2/T8: the independent STATE_E sibling resolves to STATE_F, not
    # to STATE_B -- no cross-state contamination from sharing one
    # structural signature.
    assert "continuar('OTRA');" in state_e_html

    state_e_transitions = _embedded_navigation_transitions(
        state_e_html
    )

    assert len(state_e_transitions) == 1
    assert (
        state_e_transitions[0]["target_runtime_entry"]
        == "states/04-STATE_F/runtime/index.html"
    )

    navigation_transitions = json.loads(
        (
            revision_dir / "runtime" / "navigation_transitions.json"
        ).read_text(encoding="utf-8")
    )

    # T11: both candidates route to their own materialized transition,
    # neither silently dropped nor merged.
    materialized_candidate_ids = {
        transition.get("candidate_id")
        for transition in navigation_transitions["transitions"]
    }

    assert materialized_candidate_ids == {
        "cand-continuar-a",
        "cand-continuar-e",
    }
    assert navigation_transitions["transition_count"] == 2

    # T10: nothing is left in the deferred sidecar for either.
    deferred_payload = json.loads(
        (
            revision_dir
            / "runtime"
            / AUTO_TWIN_DEFERRED_NAVIGATION_TRANSITIONS_FILENAME
        ).read_text(encoding="utf-8")
    )

    assert deferred_payload["deferred_navigation_transitions"] == []


def test_structural_onclick_materialization_is_deterministic(
    golden_world,
):
    """T9: re-materializing identical evidence into a fresh target
    produces the identical executable route set."""

    materialized_root, plan = golden_world

    first_root = materialized_root
    second_root = materialized_root.parent / "materialized_second"
    second_root.mkdir()

    import shutil

    shutil.copytree(
        first_root / TWIN_KEY,
        second_root / TWIN_KEY,
    )

    first_built = materialize_auto_twin_plan(
        plan=plan,
        source_root=first_root.parent / "captures",
        materialized_root=first_root,
        procedure_code=SITE_CODE,
        flow_variant="SITE_LEVEL",
    )

    second_built = materialize_auto_twin_plan(
        plan=plan,
        source_root=first_root.parent / "captures",
        materialized_root=second_root,
        procedure_code=SITE_CODE,
        flow_variant="SITE_LEVEL",
    )

    def _runtime_payload(built):
        return json.loads(
            (
                Path(built["revision_dir"])
                / "runtime" / "navigation_transitions.json"
            ).read_text(encoding="utf-8")
        )

    first_payload = _runtime_payload(first_built)
    second_payload = _runtime_payload(second_built)

    assert (
        first_payload["transition_count"]
        == second_payload["transition_count"]
        == 2
    )

    def _route_keys(payload):
        return sorted(
            (
                transition["before_state_id"],
                transition["after_state_id"],
                transition["candidate_id"],
            )
            for transition in payload["transitions"]
        )

    assert _route_keys(first_payload) == _route_keys(second_payload)
