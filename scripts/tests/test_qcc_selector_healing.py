import pytest

from backend.automation.site_architecture.selector_healing import (
    SELECTOR_HEALING_CONFIDENCE_HIGH,
    SELECTOR_HEALING_CONFIDENCE_MEDIUM,
    SELECTOR_HEALING_STATUS_AMBIGUOUS,
    SELECTOR_HEALING_STATUS_HEALED,
    SELECTOR_HEALING_STATUS_NOT_FOUND,
    ElementDescriptor,
    SelectorHealingResult,
    TargetDescriptor,
    evaluate_selector_healing,
    resolve_selector_healing_execution_eligibility,
)


def test_ambiguous_when_two_candidates_tie_for_top_score():
    target = TargetDescriptor(
        tag="button",
        element_id="continuar",
        role="button",
        label_text="Continuar",
    )

    candidates = (
        ElementDescriptor(
            selector="#continuar-1",
            element_id="continuar",
            role="button",
            label_text="Continuar",
        ),
        ElementDescriptor(
            selector="#continuar-2",
            element_id="continuar",
            role="button",
            label_text="Continuar",
        ),
    )

    result = evaluate_selector_healing(
        target=target,
        candidates=candidates,
    )

    assert result.status == SELECTOR_HEALING_STATUS_AMBIGUOUS
    assert result.healed_candidate is None
    assert result.reason == "MULTIPLE_CANDIDATES_TIED"


def test_stale_evidence_blocks_execution_eligibility():
    target = TargetDescriptor(
        previously_observed_selectors=("#enviar-old",),
        element_id="enviar",
        role="button",
    )

    candidates = (
        ElementDescriptor(
            selector="#enviar-old",
            element_id="enviar",
            role="button",
            name="enviar",
        ),
    )

    healing = evaluate_selector_healing(
        target=target,
        candidates=candidates,
    )

    assert healing.status == SELECTOR_HEALING_STATUS_HEALED

    decision = resolve_selector_healing_execution_eligibility(
        healing_result=healing,
        interaction_policy="AUTOMATION_ALLOWED",
        current_functional_state="STATE_A",
        required_functional_state="STATE_A",
        # Evidence is stale (e.g. captured before the current CURRENT):
        # the caller's evidence store says it is not fresh anymore.
        evidence_requirements_satisfied=False,
    )

    assert decision["eligible"] is False
    assert decision["reason"] == "EVIDENCE_REQUIREMENTS_NOT_SATISFIED"


def test_wrong_state_blocks_execution_eligibility():
    target = TargetDescriptor(
        previously_observed_selectors=("#enviar",),
        element_id="enviar",
        name="enviar",
        role="button",
    )

    candidates = (
        ElementDescriptor(
            selector="#enviar",
            element_id="enviar",
            name="enviar",
            role="button",
        ),
    )

    healing = evaluate_selector_healing(
        target=target,
        candidates=candidates,
    )

    assert healing.healed_candidate.confidence == (
        SELECTOR_HEALING_CONFIDENCE_HIGH
    )

    decision = resolve_selector_healing_execution_eligibility(
        healing_result=healing,
        interaction_policy="AUTOMATION_ALLOWED",
        current_functional_state="STATE_B",
        required_functional_state="STATE_A",
        evidence_requirements_satisfied=True,
    )

    assert decision["eligible"] is False
    assert decision["reason"] == "STATE_MISMATCH"


def test_human_only_never_execution_eligible_regardless_of_confidence():
    target = TargetDescriptor(
        previously_observed_selectors=("#firmar",),
        element_id="firmar",
        name="firmar",
        role="button",
    )

    candidates = (
        ElementDescriptor(
            selector="#firmar",
            element_id="firmar",
            name="firmar",
            role="button",
        ),
    )

    healing = evaluate_selector_healing(
        target=target,
        candidates=candidates,
    )

    assert healing.healed_candidate.confidence == (
        SELECTOR_HEALING_CONFIDENCE_HIGH
    )

    decision = resolve_selector_healing_execution_eligibility(
        healing_result=healing,
        interaction_policy="HUMAN_ONLY",
        current_functional_state="STATE_A",
        required_functional_state="STATE_A",
        evidence_requirements_satisfied=True,
    )

    assert decision["eligible"] is False
    assert decision["reason"] == "HUMAN_ONLY_NEVER_EXECUTION_ELIGIBLE"


def test_same_label_duplicates_are_ambiguous_not_false_positive():
    # Two structurally distinct elements coincidentally share the same
    # visible label text: label alone must never resolve to a single
    # healed candidate.
    target = TargetDescriptor(
        label_text="Aceptar",
        element_type="button",
    )

    candidates = (
        ElementDescriptor(
            selector="#dialog-1 button.accept",
            label_text="Aceptar",
            element_type="button",
        ),
        ElementDescriptor(
            selector="#dialog-2 button.accept",
            label_text="Aceptar",
            element_type="button",
        ),
    )

    result = evaluate_selector_healing(
        target=target,
        candidates=candidates,
    )

    assert result.status == SELECTOR_HEALING_STATUS_AMBIGUOUS


def test_unstable_identifier_never_contributes_to_score():
    # The id looks identical, but the target/candidate both flag it as
    # framework-generated: it must not be trusted as identity evidence.
    target = TargetDescriptor(
        element_id="r_38fa21",
        identifier_stable=False,
        label_text="Guardar",
    )

    candidates = (
        ElementDescriptor(
            selector="#r_38fa21",
            element_id="r_38fa21",
            identifier_stable=False,
        ),
    )

    result = evaluate_selector_healing(
        target=target,
        candidates=candidates,
    )

    # No other independent signal shared: nothing plausible is found.
    assert result.status == SELECTOR_HEALING_STATUS_NOT_FOUND


def test_successful_high_confidence_equivalent_is_execution_eligible():
    target = TargetDescriptor(
        previously_observed_selectors=(
            'a[onclick="continuar()"]',
        ),
        element_id="continuar",
        name="continuar",
        role="link",
        form_id="frm-main",
    )

    candidates = (
        ElementDescriptor(
            selector='a[onclick="continuar()"]',
            element_id="continuar",
            name="continuar",
            role="link",
            form_id="frm-main",
        ),
        ElementDescriptor(
            selector="#unrelated",
            element_id="unrelated",
        ),
    )

    healing = evaluate_selector_healing(
        target=target,
        candidates=candidates,
    )

    assert healing.status == SELECTOR_HEALING_STATUS_HEALED
    assert healing.healed_candidate.confidence == (
        SELECTOR_HEALING_CONFIDENCE_HIGH
    )
    assert (
        healing.healed_candidate.candidate_selector
        == 'a[onclick="continuar()"]'
    )

    decision = resolve_selector_healing_execution_eligibility(
        healing_result=healing,
        interaction_policy="AUTOMATION_ALLOWED",
        current_functional_state="STATE_A",
        required_functional_state="STATE_A",
        evidence_requirements_satisfied=True,
    )

    assert decision["eligible"] is True


def test_no_plausible_candidate_is_not_found():
    target = TargetDescriptor(element_id="ghost")

    candidates = (
        ElementDescriptor(
            selector="#other",
            element_id="other",
        ),
    )

    result = evaluate_selector_healing(
        target=target,
        candidates=candidates,
    )

    assert result.status == SELECTOR_HEALING_STATUS_NOT_FOUND
    assert result.healed_candidate is None


def test_medium_confidence_never_execution_eligible():
    target = TargetDescriptor(
        role="button",
        element_type="submit",
        label_text="Enviar",
        structural_path=("form", "div"),
    )

    candidates = (
        ElementDescriptor(
            selector="#maybe",
            role="button",
            element_type="submit",
            label_text="Enviar",
            structural_path=("form", "div"),
        ),
    )

    healing = evaluate_selector_healing(
        target=target,
        candidates=candidates,
    )

    assert healing.status == SELECTOR_HEALING_STATUS_HEALED
    assert healing.healed_candidate.confidence in {
        SELECTOR_HEALING_CONFIDENCE_MEDIUM,
    }

    decision = resolve_selector_healing_execution_eligibility(
        healing_result=healing,
        interaction_policy="AUTOMATION_ALLOWED",
        current_functional_state="STATE_A",
        required_functional_state="STATE_A",
        evidence_requirements_satisfied=True,
    )

    assert decision["eligible"] is False
    assert decision["reason"] == "CONFIDENCE_BELOW_HIGH_THRESHOLD"


def test_healing_never_promotes_or_mutates_canonical_selector():
    # The result object carries no method/attribute that could apply
    # itself; it is a pure, inert value.
    target = TargetDescriptor(element_id="x")
    candidates = (
        ElementDescriptor(selector="#x", element_id="x"),
    )

    result = evaluate_selector_healing(
        target=target,
        candidates=candidates,
    )

    assert isinstance(result, SelectorHealingResult)
    assert not hasattr(result, "apply")
    assert not hasattr(result, "promote")
    assert not hasattr(result, "commit")


def test_healing_rejects_invalid_target_and_candidate_types():
    with pytest.raises(TypeError):
        evaluate_selector_healing(
            target={"not": "a descriptor"},
            candidates=(),
        )

    with pytest.raises(TypeError):
        evaluate_selector_healing(
            target=TargetDescriptor(),
            candidates=({"not": "a descriptor"},),
        )
