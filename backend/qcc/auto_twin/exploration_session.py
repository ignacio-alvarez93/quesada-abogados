"""QCC AUTO TWIN — Governed Exploration Session (UWT-11B).

Work Order UWT-11B asks for a bounded exploration session/application
service built on top of the UWT-11A candidate planner
(``exploration_candidate_planner.plan_exploration_candidates``). It is
governed Discovery infrastructure, not unrestricted autonomous
browsing: a session proposes exactly one governed transition at a
time, never executes anything itself, and stops for one of a fixed,
explicit set of reasons.

Canonical source audit
-----------------------

- ``plan_exploration_candidates`` (UWT-11A) already walks observed
  transitions, classifies every candidate action by risk and returns a
  deterministic, already-capped, already-excluded candidate list. This
  module never re-implements that walk or that risk classification: it
  calls the planner once per step and only adds session-level memory
  and budget bookkeeping on top.
- ``AutoTwinObservationStore`` already owns twin/site identity and
  per-state branch/state context (``state_key``, ``pathname``,
  ``functional_state``, ``branch_context_id``). This module reuses the
  planner's own private resolution helpers
  (``_twin_states``/``_state_context_for_fingerprint``) instead of
  deriving a second copy of that lookup.
- ``AutoTwinProfilePolicy.active_discovery`` remains the one capability
  flag gating active exploration, exactly as UWT-11A already requires.

What this module contributes
-----------------------------

A stateful session wrapper around the stateless planner that:

1. owns explicit session identity (``session_id``, ``twin_key``,
   ``site_code``/``revision`` resolved from the observation store at
   construction time);
2. owns an explicit exploration budget (total executed transitions)
   and an explicit maximum step count (total decision cycles), each
   independently bounding the session;
3. tracks the session's current branch/state context and a
   session-level visited-state / visited-transition memory, distinct
   from the planner's own per-call frontier walk;
4. selects, deterministically, at most one next transition per
   ``step()`` call -- never more than one -- from the planner's
   already-governed, already-risk-classified accepted candidates;
5. stops for exactly one of a fixed vocabulary of reasons
   (``BUDGET_EXHAUSTED``, ``NO_SAFE_CANDIDATES``,
   ``HUMAN_ONLY_BOUNDARY``, ``UNKNOWN_STATE``, ``LOOP_PROTECTION``,
   ``RUNTIME_UNAVAILABLE``);
6. records one evidence entry for every planned, executed or skipped
   transition, forming a complete, append-only audit trail of the
   session.

Governance this module preserves (never violates)
----------------------------------------------------

- No browser, no SeleniumBase, no network call anywhere in this
  module: every input (``navigation_graph``,
  ``action_inventory_by_fingerprint``) is evidence already captured by
  other components, passed in by the caller. This module never creates
  a second browser runtime; any actual execution of a selected
  candidate must go through the one already-governed SeleniumBase
  runtime elsewhere (e.g. ``state_aware_execution``,
  ``TwinDiscoveryRuntimeService``) and is reported back to this
  session via ``record_outcome`` -- never performed here.
- No form submission, no signature, no CAPTCHA solving, no production
  administrative filing: structurally impossible, since the only
  candidates this session can ever select are the planner's accepted
  ``REVERSIBLE``/``READ_ONLY_NAVIGATION`` candidates, and the planner
  already excludes those categories (and ``HUMAN_ONLY``,
  ``IRREVERSIBLE``, ``UNKNOWN``) before this module ever sees them.
- Fail closed: unusable outside an ``active_discovery`` Discovery
  Profile, unusable without a twin already known to the observation
  store, unusable without live evidence for the current step.
- One transition at a time: ``step()`` never returns more than one
  selected candidate, and refuses to plan a new step while a prior
  selection's outcome has not yet been reported.
- Deterministic: the selected candidate is always the planner's own
  deterministically ordered first remaining accepted candidate.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .exploration_candidate_planner import (
    AUTO_TWIN_EXPLORATION_RISK_HUMAN_ONLY,
    _state_context_for_fingerprint,
    _twin_states,
    plan_exploration_candidates,
)
from .observation_store import AutoTwinObservationStore
from .profile_policy import AutoTwinProfilePolicy


AUTO_TWIN_EXPLORATION_SESSION_SCHEMA_VERSION = 1
AUTO_TWIN_EXPLORATION_SESSION_EVIDENCE_TYPE = (
    "QCC_AUTO_TWIN_EXPLORATION_SESSION_EVIDENCE"
)

AUTO_TWIN_EXPLORATION_SESSION_ACTIVE = "ACTIVE"
AUTO_TWIN_EXPLORATION_SESSION_STOPPED = "STOPPED"

# Evidence record status: one per planned/executed/skipped transition,
# plus one terminal SESSION_STOPPED record.
AUTO_TWIN_EXPLORATION_EVIDENCE_PLANNED = "PLANNED"
AUTO_TWIN_EXPLORATION_EVIDENCE_EXECUTED = "EXECUTED"
AUTO_TWIN_EXPLORATION_EVIDENCE_SKIPPED = "SKIPPED"
AUTO_TWIN_EXPLORATION_EVIDENCE_SESSION_STOPPED = "SESSION_STOPPED"

# Fixed, exhaustive STOP reason vocabulary.
AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
AUTO_TWIN_EXPLORATION_STOP_NO_SAFE_CANDIDATES = "NO_SAFE_CANDIDATES"
AUTO_TWIN_EXPLORATION_STOP_HUMAN_ONLY_BOUNDARY = "HUMAN_ONLY_BOUNDARY"
AUTO_TWIN_EXPLORATION_STOP_UNKNOWN_STATE = "UNKNOWN_STATE"
AUTO_TWIN_EXPLORATION_STOP_LOOP_PROTECTION = "LOOP_PROTECTION"
AUTO_TWIN_EXPLORATION_STOP_RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"

AUTO_TWIN_EXPLORATION_STOP_REASONS = frozenset(
    {
        AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED,
        AUTO_TWIN_EXPLORATION_STOP_NO_SAFE_CANDIDATES,
        AUTO_TWIN_EXPLORATION_STOP_HUMAN_ONLY_BOUNDARY,
        AUTO_TWIN_EXPLORATION_STOP_UNKNOWN_STATE,
        AUTO_TWIN_EXPLORATION_STOP_LOOP_PROTECTION,
        AUTO_TWIN_EXPLORATION_STOP_RUNTIME_UNAVAILABLE,
    }
)

# ``step()`` decisions.
AUTO_TWIN_EXPLORATION_STEP_SELECTED = "TRANSITION_SELECTED"
AUTO_TWIN_EXPLORATION_STEP_STOPPED = "SESSION_STOPPED"

DEFAULT_AUTO_TWIN_EXPLORATION_SESSION_MAX_FRONTIER_STEPS = 1
DEFAULT_AUTO_TWIN_EXPLORATION_SESSION_MAX_CANDIDATES_PER_PLAN = 20


def _text(value) -> str:
    return str(value or "").strip()


def _required_text(value, *, error) -> str:
    result = _text(value)

    if not result:
        raise ValueError(error)

    return result


def _positive_int(value, *, error) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(error)

    return value


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _action_identity_from_candidate(candidate) -> tuple:
    action = candidate["action"]

    return (
        action["kind"],
        action["policy"],
        action["selector"],
        action["frame_path"],
    )


def _transition_key(candidate) -> tuple:
    return (
        candidate["state_fingerprint"],
    ) + _action_identity_from_candidate(candidate)


def _fingerprint_known(
    fingerprint, *, navigation_graph, action_inventory_by_fingerprint
) -> bool:
    if fingerprint in action_inventory_by_fingerprint:
        return True

    edges = navigation_graph.get("edges")

    if not isinstance(edges, (list, tuple)):
        return False

    return any(
        isinstance(edge, dict)
        and fingerprint
        in (edge.get("source_fingerprint"), edge.get("target_fingerprint"))
        for edge in edges
    )


class AutoTwinExplorationSession:
    """Bounded governed exploration session (UWT-11B).

    Usable only for a Discovery Profile (``profile_policy
    .active_discovery``) and only for a twin already known to
    ``observation_store``; every other construction fails closed.
    """

    def __init__(
        self,
        *,
        session_id,
        observation_store,
        profile_policy,
        twin_key,
        source_fingerprint,
        max_steps=1,
        exploration_budget=20,
        max_frontier_steps=(
            DEFAULT_AUTO_TWIN_EXPLORATION_SESSION_MAX_FRONTIER_STEPS
        ),
        max_candidates_per_plan=(
            DEFAULT_AUTO_TWIN_EXPLORATION_SESSION_MAX_CANDIDATES_PER_PLAN
        ),
        clock=None,
    ):
        if not isinstance(observation_store, AutoTwinObservationStore):
            raise TypeError(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_OBSERVATION_STORE_INVALID"
            )

        if not isinstance(profile_policy, AutoTwinProfilePolicy):
            raise TypeError(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_PROFILE_POLICY_INVALID"
            )

        if not profile_policy.active_discovery:
            raise ValueError(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_DISCOVERY_PROFILE_REQUIRED"
            )

        self._session_id = _required_text(
            session_id,
            error="QCC_AUTO_TWIN_EXPLORATION_SESSION_ID_REQUIRED",
        )

        self._observation_store = observation_store
        self._profile_policy = profile_policy

        self._twin_key = _required_text(
            twin_key, error="QCC_AUTO_TWIN_KEY_REQUIRED"
        )

        snapshot = observation_store.snapshot(
            self._twin_key, current_only=True
        )

        if not snapshot["found"]:
            raise ValueError(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_TWIN_NOT_FOUND"
            )

        twin = snapshot["twin"] or {}

        self._site_code = _text(twin.get("site_code")) or None
        self._revision = snapshot["revision"]

        self._max_steps = _positive_int(
            max_steps,
            error="QCC_AUTO_TWIN_EXPLORATION_SESSION_MAX_STEPS_INVALID",
        )

        self._exploration_budget = _positive_int(
            exploration_budget,
            error="QCC_AUTO_TWIN_EXPLORATION_SESSION_BUDGET_INVALID",
        )

        self._max_frontier_steps = _positive_int(
            max_frontier_steps,
            error=(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_FRONTIER_STEPS_INVALID"
            ),
        )

        self._max_candidates_per_plan = _positive_int(
            max_candidates_per_plan,
            error=(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_MAX_CANDIDATES_INVALID"
            ),
        )

        self._clock = clock or _default_clock

        self._status = AUTO_TWIN_EXPLORATION_SESSION_ACTIVE
        self._stop_reason = None

        self._step_index = 0
        self._steps_taken = 0

        self._current_fingerprint = _required_text(
            source_fingerprint,
            error=(
                "QCC_AUTO_TWIN_EXPLORATION_PLANNER_SOURCE_FINGERPRINT_REQUIRED"
            ),
        )

        # Session-level memory, distinct from the planner's per-call
        # frontier walk: fingerprints we have already left behind via
        # an EXECUTED transition, and exact (fingerprint, action)
        # transitions already resolved (executed or declined) this
        # session, so neither is ever re-proposed.
        self._visited_fingerprints = set()
        self._visited_transition_keys = set()

        self._pending_candidate = None

        self._evidence = []

    # -- identity / state (read-only) -----------------------------

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def twin_key(self) -> str:
        return self._twin_key

    @property
    def site_code(self):
        return self._site_code

    @property
    def revision(self):
        return self._revision

    @property
    def status(self) -> str:
        return self._status

    @property
    def stop_reason(self):
        return self._stop_reason

    @property
    def current_fingerprint(self) -> str:
        return self._current_fingerprint

    @property
    def exploration_budget(self) -> int:
        return self._exploration_budget

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @property
    def steps_taken(self) -> int:
        return self._steps_taken

    @property
    def step_index(self) -> int:
        return self._step_index

    @property
    def evidence(self) -> tuple:
        return tuple(self._evidence)

    def current_state_context(self) -> dict:
        """Best-effort branch/state context for the current position,
        re-resolved fresh against the observation store every call."""

        states, _site_code = _twin_states(
            self._observation_store, self._twin_key
        )

        return _state_context_for_fingerprint(
            states, self._current_fingerprint
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": AUTO_TWIN_EXPLORATION_SESSION_SCHEMA_VERSION,
            "session_id": self._session_id,
            "twin_key": self._twin_key,
            "site_code": self._site_code,
            "revision": self._revision,
            "profile_key": self._profile_policy.profile_key,
            "policy_code": self._profile_policy.policy_code,
            "status": self._status,
            "stop_reason": self._stop_reason,
            "current_fingerprint": self._current_fingerprint,
            "current_state_context": self.current_state_context(),
            "exploration_budget": self._exploration_budget,
            "steps_taken": self._steps_taken,
            "max_steps": self._max_steps,
            "step_index": self._step_index,
            "max_frontier_steps": self._max_frontier_steps,
            "max_candidates_per_plan": self._max_candidates_per_plan,
            "visited_fingerprint_count": len(self._visited_fingerprints),
            "visited_transition_count": len(self._visited_transition_keys),
            "pending_candidate_id": (
                self._pending_candidate["candidate_id"]
                if self._pending_candidate is not None
                else None
            ),
        }

    # -- evidence ---------------------------------------------------

    def _record_evidence(self, *, status, candidate=None, reason=None, extra=None):
        if candidate is not None:
            context = {
                "candidate_id": candidate.get("candidate_id"),
                "state_fingerprint": candidate.get("state_fingerprint"),
                "step_depth": candidate.get("step_depth"),
                "action": candidate.get("action"),
                "risk_tier": candidate.get("risk_tier"),
                "state_key": candidate.get("state_key"),
                "pathname": candidate.get("pathname"),
                "functional_state": candidate.get("functional_state"),
                "branch_context_id": candidate.get("branch_context_id"),
            }
        else:
            context = {
                "candidate_id": None,
                "state_fingerprint": self._current_fingerprint,
                "step_depth": None,
                "action": None,
                "risk_tier": None,
                **self.current_state_context(),
            }

        entry = {
            "schema_version": AUTO_TWIN_EXPLORATION_SESSION_SCHEMA_VERSION,
            "evidence_type": AUTO_TWIN_EXPLORATION_SESSION_EVIDENCE_TYPE,
            "session_id": self._session_id,
            "twin_key": self._twin_key,
            "site_code": self._site_code,
            "revision": self._revision,
            "step_index": self._step_index,
            "status": status,
            "reason": reason,
            "recorded_at": self._clock().isoformat(),
            **context,
        }

        if extra:
            entry.update(extra)

        self._evidence.append(entry)

        return entry

    def _stop(self, reason, *, note=None):
        self._status = AUTO_TWIN_EXPLORATION_SESSION_STOPPED
        self._stop_reason = reason

        entry = self._record_evidence(
            status=AUTO_TWIN_EXPLORATION_EVIDENCE_SESSION_STOPPED,
            reason=reason,
            extra={"note": note} if note else None,
        )

        return {
            "decision": AUTO_TWIN_EXPLORATION_STEP_STOPPED,
            "session_id": self._session_id,
            "status": self._status,
            "stop_reason": reason,
            "evidence": entry,
        }

    # -- core loop ----------------------------------------------------

    def step(
        self,
        *,
        navigation_graph=None,
        action_inventory_by_fingerprint=None,
        human_only_action_keys=(),
    ):
        """Plans and selects at most one next transition.

        ``navigation_graph`` and ``action_inventory_by_fingerprint``
        are the same live evidence ``plan_exploration_candidates``
        already consumes; this session never caches or recaptures
        them. Missing evidence is treated as ``RUNTIME_UNAVAILABLE``,
        never silently skipped.
        """

        if not self._profile_policy.active_discovery:
            raise ValueError(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_DISCOVERY_PROFILE_REQUIRED"
            )

        if self._pending_candidate is not None:
            raise RuntimeError(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_OUTCOME_PENDING"
            )

        if self._status != AUTO_TWIN_EXPLORATION_SESSION_ACTIVE:
            return {
                "decision": AUTO_TWIN_EXPLORATION_STEP_STOPPED,
                "session_id": self._session_id,
                "status": self._status,
                "stop_reason": self._stop_reason,
                "evidence": None,
            }

        if self._step_index >= self._max_steps:
            return self._stop(
                AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED,
                note="MAX_STEPS_REACHED",
            )

        self._step_index += 1

        if self._steps_taken >= self._exploration_budget:
            return self._stop(
                AUTO_TWIN_EXPLORATION_STOP_BUDGET_EXHAUSTED,
                note="EXPLORATION_BUDGET_EXHAUSTED",
            )

        if navigation_graph is None or action_inventory_by_fingerprint is None:
            return self._stop(
                AUTO_TWIN_EXPLORATION_STOP_RUNTIME_UNAVAILABLE,
                note="EVIDENCE_UNAVAILABLE",
            )

        if not isinstance(navigation_graph, dict) or not isinstance(
            action_inventory_by_fingerprint, dict
        ):
            return self._stop(
                AUTO_TWIN_EXPLORATION_STOP_RUNTIME_UNAVAILABLE,
                note="EVIDENCE_MALFORMED",
            )

        fingerprint = self._current_fingerprint

        if fingerprint in self._visited_fingerprints:
            return self._stop(AUTO_TWIN_EXPLORATION_STOP_LOOP_PROTECTION)

        if not _fingerprint_known(
            fingerprint,
            navigation_graph=navigation_graph,
            action_inventory_by_fingerprint=action_inventory_by_fingerprint,
        ):
            return self._stop(AUTO_TWIN_EXPLORATION_STOP_UNKNOWN_STATE)

        try:
            plan = plan_exploration_candidates(
                observation_store=self._observation_store,
                twin_key=self._twin_key,
                profile_policy=self._profile_policy,
                navigation_graph=navigation_graph,
                action_inventory_by_fingerprint=(
                    action_inventory_by_fingerprint
                ),
                source_fingerprint=fingerprint,
                max_steps=self._max_frontier_steps,
                max_candidates=self._max_candidates_per_plan,
                human_only_action_keys=human_only_action_keys,
            )
        except (TypeError, ValueError) as exc:
            return self._stop(
                AUTO_TWIN_EXPLORATION_STOP_RUNTIME_UNAVAILABLE,
                note=str(exc),
            )

        already_resolved = [
            candidate
            for candidate in plan["candidates"]
            if _transition_key(candidate) in self._visited_transition_keys
        ]

        accepted = [
            candidate
            for candidate in plan["candidates"]
            if _transition_key(candidate)
            not in self._visited_transition_keys
        ]

        for candidate in already_resolved:
            self._record_evidence(
                status=AUTO_TWIN_EXPLORATION_EVIDENCE_SKIPPED,
                candidate=candidate,
                reason="ALREADY_RESOLVED_THIS_SESSION",
            )

        if not accepted:
            rejected = plan["rejected_candidates"]

            for candidate in rejected:
                self._record_evidence(
                    status=AUTO_TWIN_EXPLORATION_EVIDENCE_SKIPPED,
                    candidate=candidate,
                    reason=candidate.get("rejection_reason"),
                )

            if rejected and all(
                candidate["risk_tier"]
                == AUTO_TWIN_EXPLORATION_RISK_HUMAN_ONLY
                for candidate in rejected
            ):
                return self._stop(
                    AUTO_TWIN_EXPLORATION_STOP_HUMAN_ONLY_BOUNDARY
                )

            return self._stop(
                AUTO_TWIN_EXPLORATION_STOP_NO_SAFE_CANDIDATES
            )

        selected = accepted[0]

        for candidate in accepted[1:]:
            self._record_evidence(
                status=AUTO_TWIN_EXPLORATION_EVIDENCE_SKIPPED,
                candidate=candidate,
                reason="NOT_SELECTED_THIS_STEP",
            )

        for candidate in plan["rejected_candidates"]:
            self._record_evidence(
                status=AUTO_TWIN_EXPLORATION_EVIDENCE_SKIPPED,
                candidate=candidate,
                reason=candidate.get("rejection_reason"),
            )

        planned_entry = self._record_evidence(
            status=AUTO_TWIN_EXPLORATION_EVIDENCE_PLANNED,
            candidate=selected,
            reason=selected.get("acceptance_reason"),
        )

        self._pending_candidate = selected

        return {
            "decision": AUTO_TWIN_EXPLORATION_STEP_SELECTED,
            "session_id": self._session_id,
            "status": self._status,
            "candidate": selected,
            "evidence": planned_entry,
        }

    def record_outcome(
        self, *, candidate_id, executed, resulting_fingerprint=None, note=None
    ):
        """Reports the outcome of the single candidate ``step()`` last
        selected. This session never executes anything itself: a real
        execution, if any, must already have happened through the
        existing governed SeleniumBase runtime before calling this.
        """

        if self._pending_candidate is None:
            raise RuntimeError(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_NO_PENDING_CANDIDATE"
            )

        candidate_id = _required_text(
            candidate_id,
            error="QCC_AUTO_TWIN_EXPLORATION_SESSION_CANDIDATE_ID_REQUIRED",
        )

        if candidate_id != self._pending_candidate["candidate_id"]:
            raise ValueError(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_CANDIDATE_MISMATCH"
            )

        if not isinstance(executed, bool):
            raise TypeError(
                "QCC_AUTO_TWIN_EXPLORATION_SESSION_EXECUTED_FLAG_INVALID"
            )

        candidate = self._pending_candidate
        self._pending_candidate = None

        # Whether executed or declined, this exact (fingerprint, action)
        # transition is now resolved and must never be re-proposed again
        # this session -- a decline is not "undecided", it is final.
        self._visited_transition_keys.add(_transition_key(candidate))

        if not executed:
            return self._record_evidence(
                status=AUTO_TWIN_EXPLORATION_EVIDENCE_SKIPPED,
                candidate=candidate,
                reason=note or "CALLER_DECLINED_EXECUTION",
            )

        self._steps_taken += 1
        self._visited_fingerprints.add(candidate["state_fingerprint"])

        resolved_fingerprint = (
            _text(resulting_fingerprint) or candidate["state_fingerprint"]
        )

        self._current_fingerprint = resolved_fingerprint

        return self._record_evidence(
            status=AUTO_TWIN_EXPLORATION_EVIDENCE_EXECUTED,
            candidate=candidate,
            reason=note or "EXECUTED_BY_CALLER",
            extra={"resulting_fingerprint": resolved_fingerprint},
        )
