"""Tests for the state-aware governed execution orchestrator.

Covers the QCC V2 STATE-AWARE SELENIUMBASE + SAFE RECOVERY mission
required scenarios: governed execution, HUMAN_ONLY monotonicity,
selector healing governance, expected/observed classification, bounded
safe recovery and no-duplicate-mutation safety, execution evidence,
and provider neutrality.

All fixtures are synthetic (no real browser). ``snapshot_provider``
and ``executor`` are injected test doubles, exactly the two points of
contact the orchestrator is designed to delegate to.
"""

import json
from datetime import datetime, timezone

from backend.automation.site_architecture.execution_evidence import (
    build_execution_evidence,
)
from backend.automation.site_architecture.expected_observed_graph import (
    ExpectedGraph,
    ExpectedGraphState,
)
from backend.automation.site_architecture.managed_execution import (
    ManagedSiteProfile,
)
from backend.automation.site_architecture.outcome_classification import (
    OUTCOME_HUMAN_HANDOFF,
)
from backend.automation.site_architecture.safe_recovery import (
    RECOVERY_LEVEL_BOUNDED_SAFE_RETRY,
    RECOVERY_LEVEL_RE_RESOLVE,
    RecoveryBudget,
)
from backend.automation.site_architecture.selector_healing import (
    TargetDescriptor,
)
from backend.automation.site_architecture.seleniumbase_executor import (
    default_transient_error_classifier,
)
from backend.automation.site_architecture.site_interaction_policy import (
    SiteInteractionPolicy,
)
from backend.automation.site_architecture.site_target import (
    SiteEnvironment,
    SiteTarget,
    SiteTargetMode,
)
from backend.automation.site_architecture.state_fingerprint import (
    build_functional_state_fingerprint,
)
from backend.automation.site_architecture.state_aware_execution import (
    ActionIntent,
    CapturedSnapshot,
    STATE_AWARE_EXECUTION_ALLOWED,
    STATE_AWARE_EXECUTION_BLOCKED_POLICY,
    STATE_AWARE_EXECUTION_BLOCKED_SELECTOR,
    STATE_AWARE_EXECUTION_BLOCKED_STATE,
    STATE_AWARE_EXECUTION_BLOCKED_EVIDENCE,
    STATE_AWARE_EXECUTION_REQUIRES_HUMAN,
    STATE_AWARE_RESULT_DIVERGED,
    STATE_AWARE_RESULT_HUMAN_HANDOFF,
    STATE_AWARE_RESULT_SUCCESS,
    StateAwareExecutionRequest,
    execute_state_aware_action,
)


SITE_CODE = "EXAMPLE"
ORIGIN = "https://example.test"

_KIND_POLICY = {
    "SELECT": "STATE_CHANGE_CANDIDATE",
    "RADIO": "STATE_CHANGE_CANDIDATE",
    "CHECKBOX": "STATE_CHANGE_CANDIDATE",
    "INPUT_VALUE": "VALUE_CHANGE_CANDIDATE",
    "TAB": "NAVIGATION_CANDIDATE",
    "LINK": "NAVIGATION_CANDIDATE",
    "BUTTON": "REQUIRES_POLICY",
    "SUBMIT": "REQUIRES_POLICY",
    "FILE_UPLOAD": "REQUIRES_POLICY",
}


def _target():
    return SiteTarget(
        url=ORIGIN + "/app/page",
        mode=SiteTargetMode.MANAGED_EXECUTION,
        site_code=SITE_CODE,
        environment=SiteEnvironment.LAB,
    )


def _profile():
    return ManagedSiteProfile(
        site_code=SITE_CODE,
        environment=SiteEnvironment.LAB,
        allowed_origins=(ORIGIN,),
        allowed_path_prefixes=("/app",),
        interaction_policy="EXAMPLE_POLICY_V1",
        capabilities=("FORM_FILL",),
    )


def _policy(rules=None):
    rules = rules or {
        "BUTTON": "AUTOMATION_ALLOWED",
        "SUBMIT": "HUMAN_ONLY",
    }

    return SiteInteractionPolicy(
        policy_code="EXAMPLE_POLICY_V1",
        site_code=SITE_CODE,
        action_kind_rules=rules,
    )


def _action(
    kind="BUTTON",
    selector="#go",
    frame_path="main",
    visible=True,
    interactable=True,
    disabled=False,
    tag="button",
    element_id="go",
    name="",
    role="",
    element_type="",
    policy=None,
):
    return {
        "kind": kind,
        "policy": policy or _KIND_POLICY.get(kind, "REQUIRES_POLICY"),
        "selector": selector,
        "frame_path": frame_path,
        "interaction": {
            "state": "INTERACTABLE",
            "visible": visible,
            "interactable": interactable,
            "disabled": disabled,
        },
        "element": {
            "tag": tag,
            "id": element_id,
            "name": name,
            "type": element_type,
            "role": role,
        },
    }


def _snapshot(*, state, pathname="/app/page", actions=()):
    return {
        "schema_version": 1,
        "page": {"origin": ORIGIN, "pathname": pathname},
        "actions": list(actions),
        "catalogs": (),
        "catalog_relations": (),
        "elements": [],
        "documents": [],
        "_test_state": state,
    }


def _recognizer(snapshot):
    return snapshot.get("_test_state")


class _QueueSnapshotProvider:
    def __init__(self, snapshots):
        self._queue = list(snapshots)

    def __call__(self):
        if not self._queue:
            raise AssertionError(
                "snapshot queue exhausted: orchestrator called "
                "snapshot_provider more times than the test expected"
            )

        item = self._queue.pop(0)

        if isinstance(item, Exception):
            raise item

        return CapturedSnapshot(
            snapshot=item,
            captured_at=datetime.now(timezone.utc),
        )


class _Executor:
    def __init__(self, behaviors=None):
        self._behaviors = list(behaviors or [])
        self.calls = []

    def __call__(self, *, action_kind, selector, frame_path="main", value=None):
        self.calls.append((action_kind, selector, frame_path, value))

        if self._behaviors:
            behavior = self._behaviors.pop(0)

            if isinstance(behavior, Exception):
                raise behavior


def _request(
    action_intent,
    *,
    policy=None,
    expected_graph=None,
    known_fingerprints=frozenset(),
    recovery_budget=None,
    max_evidence_age_seconds=None,
    twin_validation_status=None,
    expected_graph_classification=None,
):
    return StateAwareExecutionRequest(
        target=_target(),
        profile=_profile(),
        policy=policy or _policy(),
        action_intent=action_intent,
        expected_graph=expected_graph,
        known_fingerprints=known_fingerprints,
        recovery_budget=(
            recovery_budget
            or RecoveryBudget(
                max_recognize_attempts=1,
                max_reresolve_attempts=1,
                max_bounded_safe_retries=1,
            )
        ),
        max_evidence_age_seconds=max_evidence_age_seconds,
        state_recognizer=_recognizer,
        twin_validation_status=twin_validation_status,
        expected_graph_classification=expected_graph_classification,
        session_id="sess-1",
        provider="EXAMPLE",
    )


# 1. allowed canonical action executes exactly once.
def test_allowed_action_executes_exactly_once():
    action = _action()
    snap_before = _snapshot(state="LIST", actions=[action])
    snap_after = _snapshot(
        state="DETAIL", actions=[action], pathname="/app/page/detail"
    )

    provider = _QueueSnapshotProvider([snap_before, snap_after])
    executor = _Executor()

    request = _request(ActionIntent(action_kind="BUTTON", action_selector="#go"))

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_ALLOWED
    assert result.executed is True
    assert result.attempt_count == 1
    assert len(executor.calls) == 1
    assert result.result_status == STATE_AWARE_RESULT_SUCCESS


# 2. HUMAN_ONLY never executes.
def test_human_only_never_executes():
    action = _action(kind="SUBMIT", selector="#send")
    snap = _snapshot(state="FORM", actions=[action])

    provider = _QueueSnapshotProvider([snap])
    executor = _Executor()

    request = _request(
        ActionIntent(action_kind="SUBMIT", action_selector="#send")
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_REQUIRES_HUMAN
    assert result.executed is False
    assert executor.calls == []


# 3. OBSERVATION_ONLY / non-automatable kind never mutates.
def test_action_kind_without_explicit_site_rule_never_executes():
    action = _action(kind="TAB", selector="#tab1", tag="a")
    snap = _snapshot(state="FORM", actions=[action])

    provider = _QueueSnapshotProvider([snap])
    executor = _Executor()

    request = _request(
        ActionIntent(action_kind="TAB", action_selector="#tab1"),
        recovery_budget=RecoveryBudget(0, 0, 0),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_BLOCKED_POLICY
    assert executor.calls == []


# 4. stale state blocks execution, even after bounded recovery.
def test_stale_unrecognized_state_blocks_execution_after_recovery_budget():
    action = _action()
    snap = _snapshot(state=None, actions=[action])

    provider = _QueueSnapshotProvider([snap, snap, snap])
    executor = _Executor()

    request = _request(
        ActionIntent(action_kind="BUTTON", action_selector="#go"),
        recovery_budget=RecoveryBudget(
            max_recognize_attempts=2,
            max_reresolve_attempts=1,
            max_bounded_safe_retries=1,
        ),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_BLOCKED_STATE
    assert executor.calls == []
    assert len(result.recovery_attempts) == 2


# 5. stale evidence blocks execution.
def test_stale_evidence_blocks_execution():
    action = _action()
    snap = _snapshot(state="LIST", actions=[action])

    provider = _QueueSnapshotProvider([snap, snap])
    executor = _Executor()

    request = _request(
        ActionIntent(action_kind="BUTTON", action_selector="#go"),
        recovery_budget=RecoveryBudget(
            max_recognize_attempts=1,
            max_reresolve_attempts=1,
            max_bounded_safe_retries=1,
        ),
        max_evidence_age_seconds=0,
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_BLOCKED_EVIDENCE
    assert executor.calls == []


# 6. unknown state fails closed (single-shot, no recovery budget).
def test_unknown_state_fails_closed():
    action = _action()
    snap = _snapshot(state=None, actions=[action])

    provider = _QueueSnapshotProvider([snap])
    executor = _Executor()

    request = _request(
        ActionIntent(action_kind="BUTTON", action_selector="#go"),
        recovery_budget=RecoveryBudget(0, 0, 0),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_BLOCKED_STATE
    assert executor.calls == []


# 7. missing selector fails closed.
def test_missing_selector_fails_closed():
    other_action = _action(selector="#other")
    snap = _snapshot(state="LIST", actions=[other_action])

    provider = _QueueSnapshotProvider([snap])
    executor = _Executor()

    request = _request(
        ActionIntent(action_kind="BUTTON", action_selector="#missing"),
        recovery_budget=RecoveryBudget(0, 0, 0),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_BLOCKED_SELECTOR
    assert executor.calls == []


# 8. ambiguous healed selector does not execute.
def test_ambiguous_healed_selector_never_executes():
    target_descriptor = TargetDescriptor(
        element_id="submitBtn", identifier_stable=True
    )

    candidate1 = _action(selector="#new1", element_id="submitBtn")
    candidate2 = _action(selector="#new2", element_id="submitBtn")
    snap = _snapshot(state="LIST", actions=[candidate1, candidate2])

    provider = _QueueSnapshotProvider([snap])
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="BUTTON",
            action_selector="#old-missing",
            target_descriptor=target_descriptor,
        ),
        recovery_budget=RecoveryBudget(0, 0, 0),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_BLOCKED_SELECTOR
    assert executor.calls == []


# 9. strong healed candidate still passes Execution Gate.
def test_strong_healed_candidate_passes_gate_and_executes():
    target_descriptor = TargetDescriptor(
        element_id="go2", name="goName", role="button", identifier_stable=True
    )

    healed_action = _action(
        selector="#go2-new", element_id="go2", name="goName", role="button"
    )

    snap_before = _snapshot(state="LIST", actions=[healed_action])
    snap_after = _snapshot(
        state="DETAIL", actions=[healed_action], pathname="/app/page/x"
    )

    provider = _QueueSnapshotProvider([snap_before, snap_after])
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="BUTTON",
            action_selector="#go2-old-missing",
            target_descriptor=target_descriptor,
        ),
        recovery_budget=RecoveryBudget(0, 0, 0),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_ALLOWED
    assert result.executed is True
    assert len(executor.calls) == 1
    assert result.evidence.selector_healed is True
    assert result.evidence.selector_confidence == "HIGH"


# 10. expected successor observed -> success.
def test_expected_successor_observed_is_success():
    action = _action()
    snap_before = _snapshot(state="LIST", actions=[action])
    snap_after = _snapshot(
        state="DETAIL", actions=[action], pathname="/app/page/detail"
    )

    expected_fp = build_functional_state_fingerprint(snap_after)
    expected_graph = ExpectedGraph(
        states=(
            ExpectedGraphState(
                state_id="DETAIL_STATE", fingerprint=expected_fp
            ),
        ),
        transitions=(),
    )

    provider = _QueueSnapshotProvider([snap_before, snap_after])
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="BUTTON",
            action_selector="#go",
            expected_successor_state_id="DETAIL_STATE",
        ),
        expected_graph=expected_graph,
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.outcome == "EXPECTED"
    assert result.result_status == STATE_AWARE_RESULT_SUCCESS


# 11. known different successor -> divergence classification.
def test_known_different_successor_is_diverged():
    action = _action()
    snap_before = _snapshot(state="LIST", actions=[action])
    snap_after = _snapshot(
        state="OTHER", actions=[action], pathname="/app/page/other"
    )
    snap_hypothetical_expected = _snapshot(
        state="DETAIL", actions=[action], pathname="/app/page/detail"
    )

    expected_fp = build_functional_state_fingerprint(
        snap_hypothetical_expected
    )
    after_fp = build_functional_state_fingerprint(snap_after)

    expected_graph = ExpectedGraph(
        states=(
            ExpectedGraphState(
                state_id="DETAIL_STATE", fingerprint=expected_fp
            ),
        ),
        transitions=(),
    )

    provider = _QueueSnapshotProvider([snap_before, snap_after])
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="BUTTON",
            action_selector="#go",
            expected_successor_state_id="DETAIL_STATE",
        ),
        expected_graph=expected_graph,
        known_fingerprints=frozenset({after_fp}),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.outcome == "OBSERVED_DIFFERENT_KNOWN"
    assert result.result_status == STATE_AWARE_RESULT_DIVERGED


# 12. unknown successor -> safe recovery / handoff.
def test_unknown_successor_triggers_human_handoff():
    action = _action()
    snap_before = _snapshot(state="LIST", actions=[action])
    snap_after = _snapshot(
        state="OTHER", actions=[action], pathname="/app/page/other"
    )
    snap_hypothetical_expected = _snapshot(
        state="DETAIL", actions=[action], pathname="/app/page/detail"
    )

    expected_fp = build_functional_state_fingerprint(
        snap_hypothetical_expected
    )

    expected_graph = ExpectedGraph(
        states=(
            ExpectedGraphState(
                state_id="DETAIL_STATE", fingerprint=expected_fp
            ),
        ),
        transitions=(),
    )

    provider = _QueueSnapshotProvider([snap_before, snap_after])
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="BUTTON",
            action_selector="#go",
            expected_successor_state_id="DETAIL_STATE",
        ),
        expected_graph=expected_graph,
        known_fingerprints=frozenset(),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.outcome == OUTCOME_HUMAN_HANDOFF
    assert result.result_status == STATE_AWARE_RESULT_HUMAN_HANDOFF


# 13. transient stale-element condition can recover boundedly.
def test_transient_stale_element_recovers_boundedly():
    class StaleElementReferenceException(Exception):
        pass

    action = _action()
    snap_before = _snapshot(state="LIST", actions=[action])
    snap_retry_before = _snapshot(state="LIST", actions=[action])
    snap_after = _snapshot(
        state="DETAIL", actions=[action], pathname="/app/page/detail"
    )

    provider = _QueueSnapshotProvider(
        [snap_before, snap_retry_before, snap_after]
    )
    executor = _Executor(
        behaviors=[StaleElementReferenceException("stale")]
    )

    request = _request(
        ActionIntent(
            action_kind="BUTTON", action_selector="#go", idempotent=True
        ),
        recovery_budget=RecoveryBudget(
            max_recognize_attempts=1,
            max_reresolve_attempts=1,
            max_bounded_safe_retries=1,
        ),
    )

    result = execute_state_aware_action(
        request,
        snapshot_provider=provider,
        executor=executor,
        transient_error_classifier=default_transient_error_classifier,
    )

    assert result.executed is True
    assert len(executor.calls) == 2
    assert result.outcome == "EXPECTED"
    assert any(
        attempt.level == RECOVERY_LEVEL_RE_RESOLVE
        and attempt.reason == "StaleElementReferenceException"
        for attempt in result.recovery_attempts
    )


# 14. selector re-resolution recovery works.
def test_selector_reresolution_recovery_works():
    late_action = _action(selector="#late")
    snap_missing = _snapshot(state="LIST", actions=[])
    snap_present = _snapshot(state="LIST", actions=[late_action])
    snap_after = _snapshot(
        state="DETAIL", actions=[late_action], pathname="/app/page/detail"
    )

    provider = _QueueSnapshotProvider(
        [snap_missing, snap_present, snap_after]
    )
    executor = _Executor()

    request = _request(
        ActionIntent(action_kind="BUTTON", action_selector="#late"),
        recovery_budget=RecoveryBudget(
            max_recognize_attempts=1,
            max_reresolve_attempts=1,
            max_bounded_safe_retries=1,
        ),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_ALLOWED
    assert result.executed is True
    assert any(
        attempt.level == RECOVERY_LEVEL_RE_RESOLVE
        for attempt in result.recovery_attempts
    )


# 15. recovery budget is bounded.
def test_recovery_budget_is_bounded():
    snap_missing = _snapshot(state="LIST", actions=[])

    provider = _QueueSnapshotProvider(
        [snap_missing, snap_missing, snap_missing]
    )
    executor = _Executor()

    budget = RecoveryBudget(
        max_recognize_attempts=0,
        max_reresolve_attempts=2,
        max_bounded_safe_retries=0,
    )

    request = _request(
        ActionIntent(action_kind="BUTTON", action_selector="#never"),
        recovery_budget=budget,
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_BLOCKED_SELECTOR
    assert len(result.recovery_attempts) == 2
    assert executor.calls == []


# 16. non-idempotent action is never blindly retried.
def test_non_idempotent_no_observed_change_is_not_retried():
    action = _action()
    snap_before = _snapshot(state="LIST", actions=[action])
    snap_after_unchanged = _snapshot(state="LIST", actions=[action])

    provider = _QueueSnapshotProvider([snap_before, snap_after_unchanged])
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="BUTTON", action_selector="#go", idempotent=False
        ),
        recovery_budget=RecoveryBudget(
            max_recognize_attempts=0,
            max_reresolve_attempts=0,
            max_bounded_safe_retries=3,
        ),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.executed is True
    assert len(executor.calls) == 1
    assert result.result_status == STATE_AWARE_RESULT_HUMAN_HANDOFF


# 17. action effect unknown prevents duplicate mutation.
def test_non_idempotent_execution_error_prevents_duplicate_mutation():
    action = _action()
    snap_before = _snapshot(state="LIST", actions=[action])
    snap_after_unchanged = _snapshot(state="LIST", actions=[action])

    provider = _QueueSnapshotProvider([snap_before, snap_after_unchanged])
    executor = _Executor(behaviors=[RuntimeError("boom")])

    request = _request(
        ActionIntent(
            action_kind="BUTTON", action_selector="#go", idempotent=False
        ),
        recovery_budget=RecoveryBudget(
            max_recognize_attempts=0,
            max_reresolve_attempts=0,
            max_bounded_safe_retries=3,
        ),
    )

    result = execute_state_aware_action(
        request,
        snapshot_provider=provider,
        executor=executor,
        transient_error_classifier=lambda exc: False,
    )

    assert len(executor.calls) == 1
    assert result.disposition == "ACTION_EXECUTION_EFFECT_UNKNOWN"
    assert result.result_status == STATE_AWARE_RESULT_HUMAN_HANDOFF


# 18. explicitly idempotent action may retry within budget.
def test_idempotent_action_retries_within_budget_when_no_change_observed():
    action = _action()
    snap_before = _snapshot(state="LIST", actions=[action])
    snap_unchanged = _snapshot(state="LIST", actions=[action])
    snap_changed = _snapshot(
        state="DETAIL", actions=[action], pathname="/app/page/detail"
    )

    provider = _QueueSnapshotProvider(
        [snap_before, snap_unchanged, snap_unchanged, snap_changed]
    )
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="BUTTON", action_selector="#go", idempotent=True
        ),
        recovery_budget=RecoveryBudget(
            max_recognize_attempts=0,
            max_reresolve_attempts=0,
            max_bounded_safe_retries=1,
        ),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert len(executor.calls) == 2
    assert result.outcome == "EXPECTED"
    assert result.result_status == STATE_AWARE_RESULT_SUCCESS


# 18b. state-preserving idempotent action (expects_state_transition=
# False) never blindly retries on an unchanged fingerprint, and
# mutates exactly once.
def test_state_preserving_idempotent_action_does_not_retry_unchanged_fingerprint():
    action = _action(kind="INPUT_VALUE", selector="#dni")
    snap_before = _snapshot(state="FORM", actions=[action])
    snap_after_unchanged = _snapshot(state="FORM", actions=[action])

    policy = _policy({"INPUT_VALUE": "AUTOMATION_ALLOWED"})

    # Only two snapshots are queued: if the orchestrator blindly
    # retried a state-preserving action on an unchanged fingerprint,
    # it would call snapshot_provider a third time and fail here.
    provider = _QueueSnapshotProvider([snap_before, snap_after_unchanged])
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="INPUT_VALUE",
            action_selector="#dni",
            idempotent=True,
            expects_state_transition=False,
            action_value="12345678Z",
        ),
        policy=policy,
        recovery_budget=RecoveryBudget(
            max_recognize_attempts=0,
            max_reresolve_attempts=0,
            max_bounded_safe_retries=3,
        ),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.executed is True
    assert len(executor.calls) == 1
    assert not any(
        attempt.level == RECOVERY_LEVEL_BOUNDED_SAFE_RETRY
        for attempt in result.recovery_attempts
    )


# 18c. default expects_state_transition=True behavior is unaffected:
# an idempotent action with an unchanged fingerprint still retries
# within budget (same as test 18, made explicit against regression).
def test_default_expects_state_transition_still_retries_unchanged_fingerprint():
    action = _action()
    snap_before = _snapshot(state="LIST", actions=[action])
    snap_unchanged = _snapshot(state="LIST", actions=[action])
    snap_changed = _snapshot(
        state="DETAIL", actions=[action], pathname="/app/page/detail"
    )

    provider = _QueueSnapshotProvider(
        [snap_before, snap_unchanged, snap_unchanged, snap_changed]
    )
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="BUTTON",
            action_selector="#go",
            idempotent=True,
            # expects_state_transition intentionally left at default.
        ),
        recovery_budget=RecoveryBudget(
            max_recognize_attempts=0,
            max_reresolve_attempts=0,
            max_bounded_safe_retries=1,
        ),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert len(executor.calls) == 2
    assert result.outcome == "EXPECTED"
    assert result.result_status == STATE_AWARE_RESULT_SUCCESS


# 19. graph edge / expected-graph classification does not itself
# authorize execution: HUMAN_ONLY still wins.
def test_expected_graph_match_does_not_override_human_only():
    action = _action(kind="SUBMIT", selector="#send")
    snap = _snapshot(state="FORM", actions=[action])

    provider = _QueueSnapshotProvider([snap])
    executor = _Executor()

    request = _request(
        ActionIntent(action_kind="SUBMIT", action_selector="#send"),
        recovery_budget=RecoveryBudget(0, 0, 0),
        expected_graph_classification="MATCH",
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_REQUIRES_HUMAN
    assert executor.calls == []


# 20. Twin knowledge does not itself authorize REAL execution.
def test_twin_validation_alone_does_not_authorize_execution():
    action = _action()
    snap = _snapshot(state=None, actions=[action])

    provider = _QueueSnapshotProvider([snap])
    executor = _Executor()

    request = _request(
        ActionIntent(action_kind="BUTTON", action_selector="#go"),
        recovery_budget=RecoveryBudget(0, 0, 0),
        twin_validation_status="TWIN_VALIDATED",
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_BLOCKED_STATE
    assert executor.calls == []


# 21. provider-neutral contract: works for an arbitrary, non-Mercurio
# site using only the generic contracts.
def test_provider_neutral_contract_works_for_arbitrary_site():
    site_code = "RED_SARA"
    origin = "https://redsara.test"

    target = SiteTarget(
        url=origin + "/tramite",
        mode=SiteTargetMode.MANAGED_EXECUTION,
        site_code=site_code,
        environment=SiteEnvironment.LAB,
    )

    profile = ManagedSiteProfile(
        site_code=site_code,
        environment=SiteEnvironment.LAB,
        allowed_origins=(origin,),
        allowed_path_prefixes=("/tramite",),
        interaction_policy="RED_SARA_V1",
    )

    policy = SiteInteractionPolicy(
        policy_code="RED_SARA_V1",
        site_code=site_code,
        action_kind_rules={"BUTTON": "AUTOMATION_ALLOWED"},
    )

    action = _action()
    snap_before = {
        "schema_version": 1,
        "page": {"origin": origin, "pathname": "/tramite"},
        "actions": [action],
        "catalogs": (),
        "catalog_relations": (),
        "elements": [],
        "documents": [],
        "_test_state": "LIST",
    }
    snap_after = dict(snap_before)
    snap_after["page"] = {"origin": origin, "pathname": "/tramite/detalle"}
    snap_after["_test_state"] = "DETAIL"

    provider = _QueueSnapshotProvider([snap_before, snap_after])
    executor = _Executor()

    request = StateAwareExecutionRequest(
        target=target,
        profile=profile,
        policy=policy,
        action_intent=ActionIntent(
            action_kind="BUTTON", action_selector="#go"
        ),
        state_recognizer=_recognizer,
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_ALLOWED
    assert result.executed is True


# 22. execution evidence is deterministic.
def test_execution_evidence_is_deterministic():
    kwargs = dict(
        session_id="s1",
        provider="EXAMPLE",
        site_code="EXAMPLE",
        environment="LAB",
        action_kind="BUTTON",
        action_selector="#go",
        action_frame_path="main",
        interaction_policy="AUTOMATION_ALLOWED",
        selector_source="PRIMARY",
        selector_healed=False,
        gate_decision="EXECUTE_ALLOWED",
        gate_reason="ALL_GATE_CONDITIONS_SATISFIED",
        attempt_count=1,
        result_status="SUCCESS",
    )

    evidence1 = build_execution_evidence(**kwargs)
    evidence2 = build_execution_evidence(**kwargs)

    assert evidence1.to_public_dict() == evidence2.to_public_dict()


# 23. no sensitive raw input values in ordinary evidence.
def test_evidence_never_leaks_raw_action_value():
    policy = _policy({"INPUT_VALUE": "AUTOMATION_ALLOWED"})
    action = _action(kind="INPUT_VALUE", selector="#dni")
    snap_before = _snapshot(state="FORM", actions=[action])
    snap_after = _snapshot(
        state="FORM", actions=[action], pathname="/app/page/x"
    )

    provider = _QueueSnapshotProvider([snap_before, snap_after])
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="INPUT_VALUE",
            action_selector="#dni",
            action_value="12345678Z",
        ),
        policy=policy,
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    payload = json.dumps(result.evidence.to_public_dict())

    assert "12345678Z" not in payload
    assert executor.calls[0][3] == "12345678Z"


# 24. existing HUMAN_ONLY teaching remains monotonic even through the
# new selector-healing governance path.
def test_human_only_wins_even_with_high_confidence_healed_selector():
    policy = _policy({"BUTTON": "HUMAN_ONLY"})

    target_descriptor = TargetDescriptor(
        element_id="go2", name="goName", role="button", identifier_stable=True
    )

    healed_action = _action(
        selector="#go2-new", element_id="go2", name="goName", role="button"
    )
    snap = _snapshot(state="LIST", actions=[healed_action])

    provider = _QueueSnapshotProvider([snap])
    executor = _Executor()

    request = _request(
        ActionIntent(
            action_kind="BUTTON",
            action_selector="#missing",
            target_descriptor=target_descriptor,
        ),
        policy=policy,
        recovery_budget=RecoveryBudget(0, 0, 0),
    )

    result = execute_state_aware_action(
        request, snapshot_provider=provider, executor=executor
    )

    assert result.decision == STATE_AWARE_EXECUTION_REQUIRES_HUMAN
    assert executor.calls == []
