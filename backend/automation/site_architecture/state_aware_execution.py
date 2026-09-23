"""State-aware governed execution orchestrator (V1).

QCC_STATE_AWARE_EXECUTION_V1

Single, provider-neutral chain:

    SITE ARCHITECTURE
    -> STATE RECOGNITION
    -> ACTION INTENT
    -> SELECTOR RESOLUTION (+ governed healing)
    -> POLICY RESOLUTION
    -> EVIDENCE RESOLUTION
    -> EXECUTION GATE                  (already-certified, untouched)
    -> EXECUTOR                        (injected, e.g. SeleniumBase)
    -> POST-ACTION OBSERVATION
    -> EXPECTED vs OBSERVED            (already-certified building
                                         blocks + outcome_classification)
    -> SAFE RECOVERY (bounded)
    -> EXECUTION EVIDENCE

This module NEVER redesigns the certified kernel: it calls
``evaluate_execution_gate`` exactly as-is and never overrides its
precedence (e.g. it never short-circuits HUMAN_ONLY ahead of an
unknown-state block, because the certified gate itself checks
functional-state before policy).

It never executes DOM interaction itself: execution is always
delegated to an injected ``executor`` callable. A ``None``-returning,
non-raising ``executor`` call is never treated as success; success is
always derived from post-action observation via
``outcome_classification``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping

from .execution_evidence import (
    build_execution_evidence,
)
from .execution_gate import (
    EXECUTION_GATE_BLOCKED_AMBIGUOUS,
    EXECUTION_GATE_BLOCKED_CONTRACT_DRIFT,
    EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE,
    EXECUTION_GATE_BLOCKED_POLICY,
    EXECUTION_GATE_BLOCKED_STALE_EVIDENCE,
    EXECUTION_GATE_BLOCKED_UNKNOWN_STATE,
    EXECUTION_GATE_EXECUTE_ALLOWED,
    EXECUTION_GATE_WAIT_FOR_HUMAN,
    SELECTOR_RESOLUTION_AMBIGUOUS,
    SELECTOR_RESOLUTION_HEALED,
    SELECTOR_RESOLUTION_PRIMARY_OK,
    SELECTOR_RESOLUTION_UNRESOLVED,
    ExecutionGateContext,
    evaluate_execution_gate,
)
from .expected_observed_graph import (
    ExpectedGraph,
)
from .managed_execution import (
    ManagedSiteProfile,
    authorize_managed_target,
)
from .outcome_classification import (
    ACTION_DISPOSITION_CONFIRMED_NOT_EXECUTED,
    ACTION_DISPOSITION_EFFECT_UNKNOWN,
    ACTION_DISPOSITION_EXECUTION_ATTEMPTED,
    OUTCOME_EXPECTED,
    OUTCOME_HUMAN_HANDOFF,
    OUTCOME_OBSERVED_DIFFERENT_KNOWN,
    classify_post_action_outcome,
)
from .safe_recovery import (
    RECOVERY_LEVEL_BOUNDED_SAFE_RETRY,
    RECOVERY_LEVEL_RECOGNIZE,
    RECOVERY_LEVEL_RE_RESOLVE,
    RecoveryBudget,
    budget_allows,
    build_recovery_attempt,
)
from .selector_healing import (
    ElementDescriptor,
    SELECTOR_HEALING_STATUS_HEALED,
    TargetDescriptor,
    evaluate_selector_healing,
)
from .site_interaction_policy import (
    SITE_INTERACTION_DENY,
    SiteInteractionPolicy,
    evaluate_site_interaction,
)
from .site_target import (
    SiteTarget,
)
from .state_observer import (
    observe_site_state,
)


STATE_AWARE_EXECUTION_SCHEMA_VERSION = 1

STATE_AWARE_EXECUTION_ALLOWED = "EXECUTION_ALLOWED"
STATE_AWARE_EXECUTION_BLOCKED_POLICY = "EXECUTION_BLOCKED_POLICY"
STATE_AWARE_EXECUTION_BLOCKED_STATE = "EXECUTION_BLOCKED_STATE"
STATE_AWARE_EXECUTION_BLOCKED_EVIDENCE = "EXECUTION_BLOCKED_EVIDENCE"
STATE_AWARE_EXECUTION_BLOCKED_SELECTOR = "EXECUTION_BLOCKED_SELECTOR"
STATE_AWARE_EXECUTION_REQUIRES_HUMAN = "EXECUTION_REQUIRES_HUMAN"
STATE_AWARE_EXECUTION_NOT_READY = "EXECUTION_NOT_READY"

_VALID_DECISIONS = frozenset({
    STATE_AWARE_EXECUTION_ALLOWED,
    STATE_AWARE_EXECUTION_BLOCKED_POLICY,
    STATE_AWARE_EXECUTION_BLOCKED_STATE,
    STATE_AWARE_EXECUTION_BLOCKED_EVIDENCE,
    STATE_AWARE_EXECUTION_BLOCKED_SELECTOR,
    STATE_AWARE_EXECUTION_REQUIRES_HUMAN,
    STATE_AWARE_EXECUTION_NOT_READY,
})

STATE_AWARE_RESULT_SUCCESS = "SUCCESS"
STATE_AWARE_RESULT_DIVERGED = "DIVERGED"
STATE_AWARE_RESULT_HUMAN_HANDOFF = "HUMAN_HANDOFF"
STATE_AWARE_RESULT_BLOCKED = "BLOCKED"

_SELECTOR_INSUFFICIENT_EVIDENCE_REASONS = frozenset({
    "SELECTOR_UNRESOLVED",
    "HEALED_SELECTOR_CONFIDENCE_BELOW_HIGH",
})

_GATE_DECISION_MAP = {
    EXECUTION_GATE_EXECUTE_ALLOWED: STATE_AWARE_EXECUTION_ALLOWED,
    EXECUTION_GATE_WAIT_FOR_HUMAN: (
        STATE_AWARE_EXECUTION_REQUIRES_HUMAN
    ),
    EXECUTION_GATE_BLOCKED_POLICY: (
        STATE_AWARE_EXECUTION_BLOCKED_POLICY
    ),
    EXECUTION_GATE_BLOCKED_UNKNOWN_STATE: (
        STATE_AWARE_EXECUTION_BLOCKED_STATE
    ),
    EXECUTION_GATE_BLOCKED_STALE_EVIDENCE: (
        STATE_AWARE_EXECUTION_BLOCKED_EVIDENCE
    ),
    EXECUTION_GATE_BLOCKED_CONTRACT_DRIFT: (
        STATE_AWARE_EXECUTION_BLOCKED_EVIDENCE
    ),
    EXECUTION_GATE_BLOCKED_AMBIGUOUS: (
        STATE_AWARE_EXECUTION_BLOCKED_SELECTOR
    ),
    EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE: (
        STATE_AWARE_EXECUTION_BLOCKED_EVIDENCE
    ),
}

_MAX_TOTAL_ITERATIONS_SAFETY_MARGIN = 5


def _text(value):
    value = str(value or "").strip()
    return value or None


def _map_gate_decision(gate_decision):
    if (
        gate_decision.decision
        == EXECUTION_GATE_BLOCKED_INSUFFICIENT_EVIDENCE
        and gate_decision.reason
        in _SELECTOR_INSUFFICIENT_EVIDENCE_REASONS
    ):
        return STATE_AWARE_EXECUTION_BLOCKED_SELECTOR

    return _GATE_DECISION_MAP.get(
        gate_decision.decision,
        STATE_AWARE_EXECUTION_BLOCKED_EVIDENCE,
    )


@dataclass(
    frozen=True,
    slots=True,
)
class ActionIntent:
    """Canonical action intent: what QCC wants to do, and how safe a
    blind repeat of it would be. ``idempotent`` defaults to ``False``:
    callers must explicitly opt an action in, never the other way
    round.

    ``expects_state_transition`` defaults to ``True`` (the prior,
    still-certified behavior): a successful action is assumed to
    produce a new functional state. State-preserving actions (e.g.
    ``INPUT_VALUE``, ``FOCUS``) must explicitly opt OUT by passing
    ``False``, since typing a value or focusing an element can
    legitimately leave the functional-state fingerprint unchanged
    even though the action itself succeeded. This module never infers
    this from ``action_kind``: the caller, which knows the concrete
    site semantics, decides."""

    action_kind: str
    action_selector: str
    action_frame_path: str = "main"
    idempotent: bool = False
    expects_state_transition: bool = True
    expected_successor_state_id: str | None = None
    target_descriptor: TargetDescriptor | None = None
    # Runtime-only payload (e.g. a value to type/select). Deliberately
    # NEVER read by evidence building: see execution_evidence.py.
    action_value: object = None

    def __post_init__(self) -> None:
        kind = _text(self.action_kind)
        selector = _text(self.action_selector)

        if not kind or not selector:
            raise ValueError(
                "QCC_ACTION_INTENT_IDENTITY_REQUIRED"
            )

        object.__setattr__(self, "action_kind", kind.upper())
        object.__setattr__(self, "action_selector", selector)

        object.__setattr__(
            self,
            "action_frame_path",
            _text(self.action_frame_path) or "main",
        )

        if not isinstance(self.idempotent, bool):
            raise TypeError(
                "QCC_ACTION_INTENT_IDEMPOTENT_INVALID"
            )

        object.__setattr__(
            self,
            "expected_successor_state_id",
            _text(self.expected_successor_state_id),
        )

        if (
            self.target_descriptor is not None
            and not isinstance(
                self.target_descriptor, TargetDescriptor
            )
        ):
            raise TypeError(
                "QCC_ACTION_INTENT_TARGET_DESCRIPTOR_INVALID"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class CapturedSnapshot:
    """One state observation: a normalized Site Architecture snapshot
    payload plus its capture time, used for evidence-freshness."""

    snapshot: Mapping
    captured_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, Mapping):
            raise TypeError(
                "QCC_CAPTURED_SNAPSHOT_PAYLOAD_INVALID"
            )

        if not isinstance(self.captured_at, datetime):
            raise TypeError(
                "QCC_CAPTURED_SNAPSHOT_TIMESTAMP_INVALID"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class StateAwareExecutionRequest:
    target: SiteTarget
    profile: ManagedSiteProfile
    policy: SiteInteractionPolicy
    action_intent: ActionIntent

    expected_graph: ExpectedGraph | None = None
    known_fingerprints: frozenset = field(
        default_factory=frozenset,
    )

    twin_validation_status: str | None = None
    contract_watcher_health: str | None = None
    transition_confidence: str | None = None
    observation_count: int | None = None
    expected_graph_classification: str | None = None

    recovery_budget: RecoveryBudget = field(
        default_factory=RecoveryBudget,
    )
    max_evidence_age_seconds: float | None = None

    state_recognizer: Callable | None = None

    session_id: str | None = None
    provider: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, SiteTarget):
            raise TypeError(
                "QCC_STATE_AWARE_REQUEST_TARGET_INVALID"
            )

        if not isinstance(self.profile, ManagedSiteProfile):
            raise TypeError(
                "QCC_STATE_AWARE_REQUEST_PROFILE_INVALID"
            )

        if not isinstance(self.policy, SiteInteractionPolicy):
            raise TypeError(
                "QCC_STATE_AWARE_REQUEST_POLICY_INVALID"
            )

        if not isinstance(self.action_intent, ActionIntent):
            raise TypeError(
                "QCC_STATE_AWARE_REQUEST_ACTION_INTENT_INVALID"
            )

        if not isinstance(self.recovery_budget, RecoveryBudget):
            raise TypeError(
                "QCC_STATE_AWARE_REQUEST_RECOVERY_BUDGET_INVALID"
            )

        object.__setattr__(
            self,
            "known_fingerprints",
            frozenset(self.known_fingerprints or ()),
        )


@dataclass(
    frozen=True,
    slots=True,
)
class StateAwareExecutionResult:
    schema_version: int
    decision: str
    result_status: str
    outcome: str | None
    disposition: str
    executed: bool
    attempt_count: int
    recovery_attempts: tuple
    gate_decision: str | None
    gate_reason: str | None
    reason: str
    evidence: object

    def __post_init__(self) -> None:
        if self.decision not in _VALID_DECISIONS:
            raise ValueError(
                "QCC_STATE_AWARE_EXECUTION_DECISION_INVALID"
            )


class _SelectorResolution:
    __slots__ = (
        "status",
        "action_dict",
        "confidence",
        "healed",
    )

    def __init__(
        self, status, action_dict, confidence, healed
    ):
        self.status = status
        self.action_dict = action_dict
        self.confidence = confidence
        self.healed = healed


def _live_actions(snapshot):
    actions = snapshot.get("actions")

    if not isinstance(actions, (list, tuple)):
        return ()

    return tuple(
        action
        for action in actions
        if isinstance(action, dict)
    )


def _action_frame_path(action):
    return _text(action.get("frame_path")) or "main"


def _action_kind(action):
    return str(action.get("kind") or "").strip().upper()


def _resolve_action(snapshot, action_intent):
    actions = _live_actions(snapshot)

    kind = action_intent.action_kind
    selector = action_intent.action_selector
    frame_path = action_intent.action_frame_path

    matches = [
        action
        for action in actions
        if _action_kind(action) == kind
        and _text(action.get("selector")) == selector
        and _action_frame_path(action) == frame_path
    ]

    if len(matches) == 1:
        return _SelectorResolution(
            SELECTOR_RESOLUTION_PRIMARY_OK,
            matches[0],
            None,
            False,
        )

    if len(matches) > 1:
        return _SelectorResolution(
            SELECTOR_RESOLUTION_AMBIGUOUS, None, None, False
        )

    if action_intent.target_descriptor is None:
        return _SelectorResolution(
            SELECTOR_RESOLUTION_UNRESOLVED, None, None, False
        )

    candidates = []
    candidate_actions = {}

    for action in actions:
        if _action_kind(action) != kind:
            continue

        candidate_selector = _text(action.get("selector"))

        if not candidate_selector:
            continue

        candidate_frame_path = _action_frame_path(action)
        element = action.get("element") or {}

        if not isinstance(element, dict):
            element = {}

        descriptor = ElementDescriptor(
            selector=candidate_selector,
            frame_path=candidate_frame_path,
            tag=element.get("tag") or None,
            element_id=element.get("id") or None,
            name=element.get("name") or None,
            role=element.get("role") or None,
            element_type=element.get("type") or None,
        )

        candidates.append(descriptor)
        candidate_actions[
            (candidate_selector, candidate_frame_path)
        ] = action

    healing_result = evaluate_selector_healing(
        target=action_intent.target_descriptor,
        candidates=candidates,
    )

    if healing_result.status != SELECTOR_HEALING_STATUS_HEALED:
        return _SelectorResolution(
            SELECTOR_RESOLUTION_UNRESOLVED, None, None, False
        )

    healed = healing_result.healed_candidate

    matched_action = candidate_actions.get(
        (healed.candidate_selector, healed.frame_path)
    )

    if matched_action is None:
        return _SelectorResolution(
            SELECTOR_RESOLUTION_UNRESOLVED, None, None, False
        )

    return _SelectorResolution(
        SELECTOR_RESOLUTION_HEALED,
        matched_action,
        healed.confidence,
        True,
    )


def _resolve_interaction_policy(
    *, target, profile, policy, action_intent, resolution
):
    """Returns (interaction_policy_str, safety_dict_or_none)."""

    if resolution.action_dict is not None:
        interaction = evaluate_site_interaction(
            target=target,
            profile=profile,
            policy=policy,
            action=resolution.action_dict,
        )

        return interaction["decision"], interaction

    kind_rule = policy.action_kind_rules.get(
        action_intent.action_kind
    )

    return (kind_rule or SITE_INTERACTION_DENY), None


def _is_evidence_stale(captured_at, max_age_seconds):
    # ``max_age_seconds`` may be ``0``: an explicit zero-tolerance
    # limit, distinct from ``None`` (no constraint). ``>=`` is required
    # instead of ``>`` because sub-clock-resolution execution can
    # legitimately measure an elapsed age of exactly ``0.0`` seconds;
    # with a zero-second budget that must still fail closed as stale.
    if max_age_seconds is None:
        return False

    now = datetime.now(timezone.utc)

    reference = captured_at

    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    age = (now - reference).total_seconds()

    return age >= max_age_seconds


def _fingerprint_and_state(snapshot, recognizer):
    observation = observe_site_state(
        snapshot, recognizer=recognizer
    )

    return observation["fingerprint"], observation["state"]


def execute_state_aware_action(
    request: StateAwareExecutionRequest,
    *,
    snapshot_provider: Callable[[], CapturedSnapshot],
    executor: Callable[..., None],
    transient_error_classifier: Callable[[Exception], bool]
    | None = None,
) -> StateAwareExecutionResult:
    """Run the full governed chain for exactly one action intent.

    ``snapshot_provider`` and ``executor`` are the only two points of
    contact with a real runtime (e.g. SeleniumBase). Both are called
    zero or more times, always bounded by ``request.recovery_budget``.
    """

    if not isinstance(request, StateAwareExecutionRequest):
        raise TypeError(
            "QCC_STATE_AWARE_EXECUTION_REQUEST_INVALID"
        )

    if not callable(snapshot_provider):
        raise TypeError(
            "QCC_STATE_AWARE_EXECUTION_SNAPSHOT_PROVIDER_INVALID"
        )

    if not callable(executor):
        raise TypeError(
            "QCC_STATE_AWARE_EXECUTION_EXECUTOR_INVALID"
        )

    classify_transient = (
        transient_error_classifier
        or (lambda exc: False)
    )

    budget = request.recovery_budget
    action_intent = request.action_intent

    counters = {
        "recognize": 0,
        "reresolve": 0,
        "bounded_retry": 0,
    }

    recovery_attempts = []
    attempt_count = 0
    disposition = ACTION_DISPOSITION_CONFIRMED_NOT_EXECUTED
    fingerprint_before = None
    state_before = None

    hard_cap = (
        budget.total_bound()
        + _MAX_TOTAL_ITERATIONS_SAFETY_MARGIN
    )

    def _finish(
        *,
        decision,
        result_status,
        outcome,
        gate_decision=None,
        gate_reason=None,
        reason,
        executed,
        interaction_policy=None,
        selector_source=None,
        selector_healed=False,
        selector_confidence=None,
        fingerprint_after=None,
        state_after=None,
    ):
        evidence = build_execution_evidence(
            session_id=request.session_id,
            provider=request.provider,
            site_code=request.target.site_code,
            environment=(
                request.target.environment.value
                if request.target.environment is not None
                else None
            ),
            canonical_state_before=fingerprint_before,
            canonical_state_after=fingerprint_after,
            recognized_state_before=state_before,
            recognized_state_after=state_after,
            action_kind=action_intent.action_kind,
            action_selector=action_intent.action_selector,
            action_frame_path=action_intent.action_frame_path,
            interaction_policy=interaction_policy,
            selector_source=selector_source,
            selector_healed=selector_healed,
            selector_confidence=selector_confidence,
            gate_decision=gate_decision,
            gate_reason=gate_reason,
            expected_successor_state_id=(
                action_intent.expected_successor_state_id
            ),
            observed_outcome=outcome,
            attempt_count=attempt_count,
            recovery_attempts=tuple(recovery_attempts),
            final_disposition=disposition,
            result_status=result_status,
        )

        return StateAwareExecutionResult(
            schema_version=(
                STATE_AWARE_EXECUTION_SCHEMA_VERSION
            ),
            decision=decision,
            result_status=result_status,
            outcome=outcome,
            disposition=disposition,
            executed=executed,
            attempt_count=attempt_count,
            recovery_attempts=tuple(recovery_attempts),
            gate_decision=gate_decision,
            gate_reason=gate_reason,
            reason=reason,
            evidence=evidence,
        )

    for _ in range(hard_cap):
        # LEVEL 0: RECOGNIZE.
        try:
            captured = snapshot_provider()
        except Exception:
            if budget_allows(
                counters, budget, RECOVERY_LEVEL_RECOGNIZE
            ):
                counters["recognize"] += 1

                recovery_attempts.append(
                    build_recovery_attempt(
                        RECOVERY_LEVEL_RECOGNIZE,
                        "SNAPSHOT_UNAVAILABLE",
                        retried=True,
                    )
                )
                continue

            return _finish(
                decision=STATE_AWARE_EXECUTION_NOT_READY,
                result_status=STATE_AWARE_RESULT_HUMAN_HANDOFF,
                outcome=None,
                reason="SNAPSHOT_UNAVAILABLE_BUDGET_EXHAUSTED",
                executed=False,
            )

        if not isinstance(captured, CapturedSnapshot):
            raise TypeError(
                "QCC_STATE_AWARE_EXECUTION_SNAPSHOT_RESULT_INVALID"
            )

        fingerprint_before, state_before = (
            _fingerprint_and_state(
                captured.snapshot, request.state_recognizer
            )
        )

        # LEVEL 1: RE-RESOLVE selector.
        resolution = _resolve_action(
            captured.snapshot, action_intent
        )

        if resolution.status in (
            SELECTOR_RESOLUTION_UNRESOLVED,
            SELECTOR_RESOLUTION_AMBIGUOUS,
        ) and budget_allows(
            counters, budget, RECOVERY_LEVEL_RE_RESOLVE
        ):
            counters["reresolve"] += 1

            recovery_attempts.append(
                build_recovery_attempt(
                    RECOVERY_LEVEL_RE_RESOLVE,
                    (
                        "SELECTOR_AMBIGUOUS"
                        if resolution.status
                        == SELECTOR_RESOLUTION_AMBIGUOUS
                        else "SELECTOR_UNRESOLVED"
                    ),
                    retried=True,
                )
            )
            continue

        interaction_policy, _interaction_detail = (
            _resolve_interaction_policy(
                target=request.target,
                profile=request.profile,
                policy=request.policy,
                action_intent=action_intent,
                resolution=resolution,
            )
        )

        evidence_stale = _is_evidence_stale(
            captured.captured_at,
            request.max_evidence_age_seconds,
        )

        site_gate_authorized = authorize_managed_target(
            request.target, request.profile
        )["authorized"]

        gate_context = ExecutionGateContext(
            site_gate_authorized=site_gate_authorized,
            functional_state=state_before,
            interaction_policy=interaction_policy,
            action_kind=action_intent.action_kind,
            action_selector=action_intent.action_selector,
            action_frame_path=action_intent.action_frame_path,
            selector_resolution=resolution.status,
            selector_confidence=resolution.confidence,
            evidence_stale=evidence_stale,
            expected_graph_classification=(
                request.expected_graph_classification
            ),
            contract_watcher_health=(
                request.contract_watcher_health
            ),
            twin_validation_status=(
                request.twin_validation_status
            ),
            transition_confidence=(
                request.transition_confidence
            ),
            observation_count=request.observation_count,
        )

        # LEVEL 2: REVALIDATE (the certified gate, called fresh).
        gate_decision = evaluate_execution_gate(gate_context)

        selector_source = (
            "HEALED"
            if resolution.healed
            else (
                "PRIMARY"
                if resolution.status
                == SELECTOR_RESOLUTION_PRIMARY_OK
                else None
            )
        )

        if (
            gate_decision.decision
            != EXECUTION_GATE_EXECUTE_ALLOWED
        ):
            retryable_state = (
                gate_decision.decision
                == EXECUTION_GATE_BLOCKED_UNKNOWN_STATE
            )

            retryable_evidence = (
                gate_decision.decision
                == EXECUTION_GATE_BLOCKED_STALE_EVIDENCE
            )

            if (
                retryable_state or retryable_evidence
            ) and budget_allows(
                counters, budget, RECOVERY_LEVEL_RECOGNIZE
            ):
                counters["recognize"] += 1

                recovery_attempts.append(
                    build_recovery_attempt(
                        RECOVERY_LEVEL_RECOGNIZE,
                        gate_decision.reason,
                        retried=True,
                    )
                )
                continue

            return _finish(
                decision=_map_gate_decision(gate_decision),
                result_status=(
                    STATE_AWARE_RESULT_HUMAN_HANDOFF
                    if gate_decision.decision
                    == EXECUTION_GATE_WAIT_FOR_HUMAN
                    else STATE_AWARE_RESULT_BLOCKED
                ),
                outcome=None,
                gate_decision=gate_decision.decision,
                gate_reason=gate_decision.reason,
                reason=gate_decision.reason,
                executed=False,
                interaction_policy=interaction_policy,
                selector_source=selector_source,
                selector_healed=resolution.healed,
                selector_confidence=resolution.confidence,
            )

        # EXECUTION GATE ALLOWED: delegate to the injected executor.
        attempt_count += 1
        disposition = ACTION_DISPOSITION_EXECUTION_ATTEMPTED

        execution_error = None

        try:
            executor(
                action_kind=action_intent.action_kind,
                selector=(
                    resolution.action_dict.get("selector")
                ),
                frame_path=(
                    resolution.action_dict.get("frame_path")
                    or "main"
                ),
                value=action_intent.action_value,
            )
        except Exception as exc:  # noqa: BLE001 - classified below
            execution_error = exc

        if (
            execution_error is not None
            and classify_transient(execution_error)
        ):
            # A transient SeleniumBase condition (stale element,
            # detached node, re-render race...). Safe to re-resolve
            # and retry ONLY because the action is explicitly
            # idempotent: the previous attempt's effect, if any, is
            # unknown and must never be blindly repeated otherwise.
            if action_intent.idempotent and budget_allows(
                counters, budget, RECOVERY_LEVEL_RE_RESOLVE
            ):
                counters["reresolve"] += 1
                disposition = ACTION_DISPOSITION_EFFECT_UNKNOWN

                recovery_attempts.append(
                    build_recovery_attempt(
                        RECOVERY_LEVEL_RE_RESOLVE,
                        type(execution_error).__name__,
                        retried=True,
                    )
                )
                continue

        # POST-ACTION OBSERVATION.
        try:
            captured_after = snapshot_provider()
            fingerprint_after, state_after = (
                _fingerprint_and_state(
                    captured_after.snapshot,
                    request.state_recognizer,
                )
            )
        except Exception:
            fingerprint_after, state_after = None, None

        expected_successor_fingerprint = None

        if (
            action_intent.expected_successor_state_id
            and request.expected_graph is not None
        ):
            expected_successor_fingerprint = (
                request.expected_graph.fingerprint_by_state_id()
                .get(
                    action_intent.expected_successor_state_id
                )
            )

        classification = classify_post_action_outcome(
            execution_error=execution_error,
            fingerprint_before=fingerprint_before,
            fingerprint_after=fingerprint_after,
            expected_successor_fingerprint=(
                expected_successor_fingerprint
            ),
            known_fingerprints=request.known_fingerprints,
            idempotent=action_intent.idempotent,
        )

        disposition = classification.disposition

        if classification.retry_eligible and budget_allows(
            counters, budget, RECOVERY_LEVEL_BOUNDED_SAFE_RETRY
        ):
            counters["bounded_retry"] += 1

            recovery_attempts.append(
                build_recovery_attempt(
                    RECOVERY_LEVEL_BOUNDED_SAFE_RETRY,
                    classification.classification,
                    retried=True,
                )
            )
            continue

        if classification.classification == OUTCOME_EXPECTED:
            result_status = STATE_AWARE_RESULT_SUCCESS
        elif (
            classification.classification
            == OUTCOME_OBSERVED_DIFFERENT_KNOWN
        ):
            result_status = STATE_AWARE_RESULT_DIVERGED
        else:
            result_status = STATE_AWARE_RESULT_HUMAN_HANDOFF

        final_outcome = (
            classification.classification
            if classification.classification == OUTCOME_EXPECTED
            else (
                classification.classification
                if result_status == STATE_AWARE_RESULT_DIVERGED
                else OUTCOME_HUMAN_HANDOFF
            )
        )

        return _finish(
            decision=STATE_AWARE_EXECUTION_ALLOWED,
            result_status=result_status,
            outcome=final_outcome,
            gate_decision=gate_decision.decision,
            gate_reason=gate_decision.reason,
            reason=classification.classification,
            executed=True,
            interaction_policy=interaction_policy,
            selector_source=selector_source,
            selector_healed=resolution.healed,
            selector_confidence=resolution.confidence,
            fingerprint_after=fingerprint_after,
            state_after=state_after,
        )

    return _finish(
        decision=STATE_AWARE_EXECUTION_NOT_READY,
        result_status=STATE_AWARE_RESULT_HUMAN_HANDOFF,
        outcome=None,
        reason="RECOVERY_HARD_CAP_EXHAUSTED",
        executed=attempt_count > 0,
    )
