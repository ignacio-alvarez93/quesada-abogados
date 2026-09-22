"""Evidence-based execution decision gate (V1).

QCC_EVIDENCE_EXECUTION_GATE_V1

A single, provider-neutral decision point that answers ONE question:

    "May SeleniumBase be asked to execute this action right now?"

This module NEVER executes anything itself. It is a pure function of an
explicit, fully-resolved context: the gate decides, SeleniumBase (or any
other runtime) executes separately, elsewhere.

Fail-closed by construction:

- HUMAN_ONLY always resolves to WAIT_FOR_HUMAN, never to execution;
- an UNKNOWN/unrecognized interaction policy never defaults to
  automation;
- stale or ambiguous evidence never passes;
- contract drift (an expected transition diverging from what was
  observed, or an unstable Contract Watcher) blocks execution;
- missing optional signals (Contract Watcher health, Twin validation,
  transition confidence/observation count, expected-graph
  classification) are treated as "not available" and simply skipped,
  they never count as a positive signal.

No provider-specific (e.g. Mercurio) branching lives in this module.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
)


EXECUTION_GATE_SCHEMA_VERSION = 1

EXECUTION_GATE_EXECUTE_ALLOWED = "EXECUTE_ALLOWED"
EXECUTION_GATE_WAIT_FOR_HUMAN = "WAIT_FOR_HUMAN"
EXECUTION_GATE_BLOCKED_AMBIGUOUS = "BLOCKED_AMBIGUOUS"
EXECUTION_GATE_BLOCKED_STALE_EVIDENCE = "BLOCKED_STALE_EVIDENCE"
EXECUTION_GATE_BLOCKED_POLICY = "BLOCKED_POLICY"
EXECUTION_GATE_BLOCKED_UNKNOWN_STATE = "BLOCKED_UNKNOWN_STATE"
EXECUTION_GATE_BLOCKED_CONTRACT_DRIFT = "BLOCKED_CONTRACT_DRIFT"
EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE = (
    "BLOCKED_INSUFFICIENT_EVIDENCE"
)

_VALID_DECISIONS = frozenset({
    EXECUTION_GATE_EXECUTE_ALLOWED,
    EXECUTION_GATE_WAIT_FOR_HUMAN,
    EXECUTION_GATE_BLOCKED_AMBIGUOUS,
    EXECUTION_GATE_BLOCKED_STALE_EVIDENCE,
    EXECUTION_GATE_BLOCKED_POLICY,
    EXECUTION_GATE_BLOCKED_UNKNOWN_STATE,
    EXECUTION_GATE_BLOCKED_CONTRACT_DRIFT,
    EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE,
})

INTERACTION_POLICY_AUTOMATION_ALLOWED = "AUTOMATION_ALLOWED"
INTERACTION_POLICY_HUMAN_ONLY = "HUMAN_ONLY"
INTERACTION_POLICY_DENY = "DENY"

SELECTOR_RESOLUTION_PRIMARY_OK = "PRIMARY_OK"
SELECTOR_RESOLUTION_HEALED = "HEALED"
SELECTOR_RESOLUTION_AMBIGUOUS = "AMBIGUOUS"
SELECTOR_RESOLUTION_UNRESOLVED = "UNRESOLVED"

_VALID_SELECTOR_RESOLUTIONS = frozenset({
    SELECTOR_RESOLUTION_PRIMARY_OK,
    SELECTOR_RESOLUTION_HEALED,
    SELECTOR_RESOLUTION_AMBIGUOUS,
    SELECTOR_RESOLUTION_UNRESOLVED,
})

SELECTOR_CONFIDENCE_HIGH = "HIGH"
SELECTOR_CONFIDENCE_MEDIUM = "MEDIUM"
SELECTOR_CONFIDENCE_LOW = "LOW"

GRAPH_EXPECTATION_MATCH = "MATCH"
GRAPH_EXPECTATION_DIVERGENT_TARGET = "DIVERGENT_TARGET"
GRAPH_EXPECTATION_MISSING_EXPECTED_TRANSITION = (
    "MISSING_EXPECTED_TRANSITION"
)
GRAPH_EXPECTATION_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
GRAPH_EXPECTATION_NEW_TRANSITION = "NEW_TRANSITION"
GRAPH_EXPECTATION_NEW_STATE = "NEW_STATE"
GRAPH_EXPECTATION_MISSING_EXPECTED_STATE = "MISSING_EXPECTED_STATE"

_VALID_GRAPH_EXPECTATIONS = frozenset({
    GRAPH_EXPECTATION_MATCH,
    GRAPH_EXPECTATION_DIVERGENT_TARGET,
    GRAPH_EXPECTATION_MISSING_EXPECTED_TRANSITION,
    GRAPH_EXPECTATION_INSUFFICIENT_EVIDENCE,
    GRAPH_EXPECTATION_NEW_TRANSITION,
    GRAPH_EXPECTATION_NEW_STATE,
    GRAPH_EXPECTATION_MISSING_EXPECTED_STATE,
})

CONTRACT_WATCHER_HEALTH_STABLE = "STABLE"
CONTRACT_WATCHER_HEALTH_UNSTABLE = "UNSTABLE"

TWIN_VALIDATION_VALIDATED = "TWIN_VALIDATED"
TWIN_VALIDATION_NOT_VALIDATED = "NOT_VALIDATED"

TRANSITION_CONFIDENCE_HIGH = "HIGH"
TRANSITION_CONFIDENCE_MEDIUM = "MEDIUM"
TRANSITION_CONFIDENCE_LOW = "LOW"

_MIN_OBSERVATION_COUNT = 1


def _text(value):
    return str(value or "").strip().upper()


@dataclass(
    frozen=True,
    slots=True,
)
class ExecutionGateContext:
    """Fully-resolved, explicit inputs to one gate decision.

    Every field the caller cannot or did not resolve is passed as
    ``None`` ("not available") rather than omitted: this keeps the
    contract explicit at every call site and prevents accidental
    positional drift.
    """

    site_gate_authorized: bool

    # None means "functional state unknown" (UNKNOWN policy of state).
    functional_state: str | None

    interaction_policy: str

    action_kind: str
    action_selector: str
    action_frame_path: str

    selector_resolution: str
    selector_confidence: str | None = None

    evidence_stale: bool = False

    # Optional signals. None means "not available", never a positive
    # or negative signal by itself.
    expected_graph_classification: str | None = None
    contract_watcher_health: str | None = None
    twin_validation_status: str | None = None
    transition_confidence: str | None = None
    observation_count: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.site_gate_authorized, bool):
            raise TypeError(
                "QCC_EXECUTION_GATE_SITE_GATE_INVALID"
            )

        object.__setattr__(
            self,
            "functional_state",
            _text(self.functional_state) or None,
        )

        interaction_policy = _text(self.interaction_policy)

        if not interaction_policy:
            raise ValueError(
                "QCC_EXECUTION_GATE_INTERACTION_POLICY_REQUIRED"
            )

        object.__setattr__(
            self,
            "interaction_policy",
            interaction_policy,
        )

        action_kind = _text(self.action_kind)
        action_selector = str(self.action_selector or "").strip()

        if not action_kind or not action_selector:
            raise ValueError(
                "QCC_EXECUTION_GATE_ACTION_IDENTITY_REQUIRED"
            )

        object.__setattr__(self, "action_kind", action_kind)
        object.__setattr__(self, "action_selector", action_selector)

        object.__setattr__(
            self,
            "action_frame_path",
            str(self.action_frame_path or "main").strip() or "main",
        )

        selector_resolution = _text(self.selector_resolution)

        if selector_resolution not in _VALID_SELECTOR_RESOLUTIONS:
            raise ValueError(
                "QCC_EXECUTION_GATE_SELECTOR_RESOLUTION_INVALID"
            )

        object.__setattr__(
            self,
            "selector_resolution",
            selector_resolution,
        )

        object.__setattr__(
            self,
            "selector_confidence",
            _text(self.selector_confidence) or None,
        )

        if not isinstance(self.evidence_stale, bool):
            raise TypeError(
                "QCC_EXECUTION_GATE_EVIDENCE_STALE_INVALID"
            )

        expected_graph_classification = (
            _text(self.expected_graph_classification) or None
        )

        if (
            expected_graph_classification is not None
            and expected_graph_classification
            not in _VALID_GRAPH_EXPECTATIONS
        ):
            raise ValueError(
                "QCC_EXECUTION_GATE_GRAPH_CLASSIFICATION_INVALID"
            )

        object.__setattr__(
            self,
            "expected_graph_classification",
            expected_graph_classification,
        )

        object.__setattr__(
            self,
            "contract_watcher_health",
            _text(self.contract_watcher_health) or None,
        )

        object.__setattr__(
            self,
            "twin_validation_status",
            _text(self.twin_validation_status) or None,
        )

        object.__setattr__(
            self,
            "transition_confidence",
            _text(self.transition_confidence) or None,
        )

        if (
            self.observation_count is not None
            and not isinstance(self.observation_count, int)
        ):
            raise TypeError(
                "QCC_EXECUTION_GATE_OBSERVATION_COUNT_INVALID"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class ExecutionGateDecision:
    schema_version: int
    decision: str
    reason: str
    action_kind: str
    action_selector: str
    action_frame_path: str


def _decision(context, decision, reason) -> ExecutionGateDecision:
    if decision not in _VALID_DECISIONS:
        raise ValueError(
            "QCC_EXECUTION_GATE_DECISION_INVALID"
        )

    return ExecutionGateDecision(
        schema_version=EXECUTION_GATE_SCHEMA_VERSION,
        decision=decision,
        reason=reason,
        action_kind=context.action_kind,
        action_selector=context.action_selector,
        action_frame_path=context.action_frame_path,
    )


def evaluate_execution_gate(
    context: ExecutionGateContext,
) -> ExecutionGateDecision:
    if not isinstance(context, ExecutionGateContext):
        raise TypeError(
            "QCC_EXECUTION_GATE_CONTEXT_INVALID"
        )

    if not context.site_gate_authorized:
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_POLICY,
            "SITE_GATE_NOT_AUTHORIZED",
        )

    if context.functional_state is None:
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_UNKNOWN_STATE,
            "FUNCTIONAL_STATE_UNKNOWN",
        )

    policy = context.interaction_policy

    if policy == INTERACTION_POLICY_HUMAN_ONLY:
        return _decision(
            context,
            EXECUTION_GATE_WAIT_FOR_HUMAN,
            "INTERACTION_POLICY_HUMAN_ONLY",
        )

    if policy != INTERACTION_POLICY_AUTOMATION_ALLOWED:
        # Covers DENY and any UNKNOWN/unrecognized policy value: never
        # defaults to automation.
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_POLICY,
            (
                "INTERACTION_POLICY_DENY"
                if policy == INTERACTION_POLICY_DENY
                else "INTERACTION_POLICY_NOT_AUTOMATION_ALLOWED"
            ),
        )

    if context.evidence_stale:
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_STALE_EVIDENCE,
            "EVIDENCE_STALE",
        )

    if context.selector_resolution == SELECTOR_RESOLUTION_AMBIGUOUS:
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_AMBIGUOUS,
            "SELECTOR_RESOLUTION_AMBIGUOUS",
        )

    if context.selector_resolution == SELECTOR_RESOLUTION_UNRESOLVED:
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE,
            "SELECTOR_UNRESOLVED",
        )

    if (
        context.selector_resolution == SELECTOR_RESOLUTION_HEALED
        and context.selector_confidence != SELECTOR_CONFIDENCE_HIGH
    ):
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE,
            "HEALED_SELECTOR_CONFIDENCE_BELOW_HIGH",
        )

    classification = context.expected_graph_classification

    if classification == GRAPH_EXPECTATION_DIVERGENT_TARGET:
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_CONTRACT_DRIFT,
            "EXPECTED_TRANSITION_DIVERGENT_TARGET",
        )

    if classification in {
        GRAPH_EXPECTATION_MISSING_EXPECTED_TRANSITION,
        GRAPH_EXPECTATION_INSUFFICIENT_EVIDENCE,
        GRAPH_EXPECTATION_NEW_TRANSITION,
        GRAPH_EXPECTATION_NEW_STATE,
        GRAPH_EXPECTATION_MISSING_EXPECTED_STATE,
    }:
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE,
            "EXPECTED_TRANSITION_NOT_CONFIRMED",
        )

    if (
        context.contract_watcher_health is not None
        and context.contract_watcher_health
        != CONTRACT_WATCHER_HEALTH_STABLE
    ):
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_CONTRACT_DRIFT,
            "CONTRACT_WATCHER_UNSTABLE",
        )

    if (
        context.twin_validation_status is not None
        and context.twin_validation_status
        != TWIN_VALIDATION_VALIDATED
    ):
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE,
            "TWIN_VALIDATION_NOT_CONFIRMED",
        )

    if (
        context.transition_confidence is not None
        and context.transition_confidence != TRANSITION_CONFIDENCE_HIGH
    ):
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE,
            "TRANSITION_CONFIDENCE_BELOW_HIGH",
        )

    if (
        context.observation_count is not None
        and context.observation_count < _MIN_OBSERVATION_COUNT
    ):
        return _decision(
            context,
            EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE,
            "OBSERVATION_COUNT_INSUFFICIENT",
        )

    return _decision(
        context,
        EXECUTION_GATE_EXECUTE_ALLOWED,
        "ALL_GATE_CONDITIONS_SATISFIED",
    )
