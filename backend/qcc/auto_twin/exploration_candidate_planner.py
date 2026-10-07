"""QCC AUTO TWIN — Governed Exploration Candidate Planner (UWT-11A).

Work Order UWT-11A asks for a deterministic, bounded planner that looks
at evidence Site Architecture already produced -- observed states,
observed transitions, and the passive action inventory of each observed
state -- and proposes a governed list of untried actions a Discovery
Profile browser *could* try next, without ever trying any of them.

Canonical source audit
-----------------------

Everything this capability needs to *identify* and *classify* a
candidate already exists and is explicitly reused, never duplicated:

- ``AutoTwinObservationStore`` already tracks, per twin, every observed
  state (``state_key``, ``pathname``, ``functional_state``,
  ``branch_context_id``, ``last_fingerprint``/``baseline_fingerprint``)
  -- the UWT-4/UWT-5 state/branch identity this module stamps onto every
  candidate instead of re-deriving it.
- ``backend.automation.site_architecture.navigation_graph`` already
  aggregates every *observed* transition (``QCC_NAVIGATION_GRAPH``
  nodes/edges) into the one authoritative record of what has already
  been visited. This module never builds a second graph: it only walks
  the one that already exists.
- ``backend.automation.site_architecture.action_inventory`` already
  derives passive, unexecuted action candidates from a captured DOM
  snapshot (``build_action_inventory``) -- the per-state action evidence
  this planner consumes, never recaptures.
- ``backend.automation.site_architecture.action_safety`` already
  classifies one action's structural safety
  (``REVERSIBLE_CANDIDATE``/``NAVIGATION_CANDIDATE``/
  ``REVIEW_REQUIRED``/``DENY``, fail-closed on anything unknown). This
  module reuses that classification verbatim as its risk-tier authority
  instead of inventing a second action taxonomy engine.
- ``AutoTwinProfilePolicy`` (``profile_policy.py``) already defines
  ``active_discovery`` as the one capability flag that distinguishes a
  Discovery Profile browser from every other QCC profile. This module
  is unusable without it.

What does not exist yet, and is the entire contribution of this module,
is the bounded frontier walk + exclusion ruleset that:

1. walks only already-observed transitions (Navigation Graph edges),
   bounded by an explicit step budget, to find every state reachable
   from one source fingerprint without ever repeating a visited state
   or a visited transition;
2. at each reached state, proposes every action from that state's
   action inventory that does NOT already have a matching Navigation
   Graph edge (an untried action -- an exploration candidate);
3. classifies each candidate by risk, excluding HUMAN_ONLY, irreversible
   actions, unknown-risk actions (fail closed by default) and the fixed
   submit/signature/CAPTCHA/payment/administrative-filing category, with
   an explicit machine-readable reason for every single exclusion;
4. caps the accepted result at an explicit candidate-count budget,
   deterministically, after prioritizing reversible/read-only
   candidates.

Governance this module preserves (never violates)
----------------------------------------------------

- No REAL interaction, no browser launching: every input is evidence
  already captured/observed by other components; this module only reads
  dicts/tuples and returns dicts/tuples.
- No automatic ACTIVE promotion: this module never writes to
  ``AutoTwinObservationStore`` and never touches
  ``AutoTwinCandidateRevisionStore``/materialization. An
  ``ExplorationCandidate`` here is wholly unrelated to the
  ``CandidateRevision`` Twin-materialization lifecycle -- it is a
  *proposal to try an action*, nothing is promoted, built or replayed.
- Fail closed: an action this module cannot positively classify as
  reversible or read-only navigation is always excluded, never
  defaulted to "allowed".
- Deterministic: the same inputs always yield the same ordering and the
  same ``candidate_id``/``plan_id`` (stable sha256 digests over
  canonical JSON), independent of dict/set iteration order.
- Provider-neutral: no selector engine, browser automation library or
  site-specific rule is referenced anywhere in this module.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
import json

from backend.automation.site_architecture.action_safety import (
    ACTION_SAFETY_DENY,
    ACTION_SAFETY_NAVIGATION_CANDIDATE,
    ACTION_SAFETY_REVERSIBLE_CANDIDATE,
    evaluate_action_safety,
)
from backend.automation.site_architecture.navigation_graph import (
    NAVIGATION_GRAPH_SCHEMA_VERSION,
    NAVIGATION_GRAPH_TYPE,
)

from .observation_store import AutoTwinObservationStore
from .profile_policy import AutoTwinProfilePolicy


AUTO_TWIN_EXPLORATION_CANDIDATE_PLAN_SCHEMA_VERSION = 1
AUTO_TWIN_EXPLORATION_CANDIDATE_PLAN_TYPE = (
    "QCC_AUTO_TWIN_EXPLORATION_CANDIDATE_PLAN"
)

# Risk tiers. Only REVERSIBLE / READ_ONLY_NAVIGATION are ever included in
# the accepted candidate list; every other tier is always excluded.
AUTO_TWIN_EXPLORATION_RISK_REVERSIBLE = "REVERSIBLE"
AUTO_TWIN_EXPLORATION_RISK_READ_ONLY_NAVIGATION = "READ_ONLY_NAVIGATION"
AUTO_TWIN_EXPLORATION_RISK_HUMAN_ONLY = "HUMAN_ONLY"
AUTO_TWIN_EXPLORATION_RISK_SENSITIVE_RESTRICTED = "SENSITIVE_RESTRICTED"
AUTO_TWIN_EXPLORATION_RISK_IRREVERSIBLE = "IRREVERSIBLE"
AUTO_TWIN_EXPLORATION_RISK_UNKNOWN = "UNKNOWN"
AUTO_TWIN_EXPLORATION_RISK_ALREADY_VISITED = "ALREADY_VISITED"

AUTO_TWIN_EXPLORATION_INCLUDED_RISK_TIERS = (
    AUTO_TWIN_EXPLORATION_RISK_REVERSIBLE,
    AUTO_TWIN_EXPLORATION_RISK_READ_ONLY_NAVIGATION,
)

# Fixed exclusion category vocabulary (submit/signature/CAPTCHA/payment/
# administrative filing). Heuristic keyword matching deliberately errs
# toward over-exclusion: a false positive only ever removes a candidate
# from a proposal list, never grants execution permission, so the safe
# failure direction is to exclude.
AUTO_TWIN_EXPLORATION_SENSITIVE_CATEGORY_CAPTCHA = "CAPTCHA"
AUTO_TWIN_EXPLORATION_SENSITIVE_CATEGORY_PAYMENT = "PAYMENT"
AUTO_TWIN_EXPLORATION_SENSITIVE_CATEGORY_SIGNATURE = "SIGNATURE"
AUTO_TWIN_EXPLORATION_SENSITIVE_CATEGORY_ADMINISTRATIVE_FILING = (
    "ADMINISTRATIVE_FILING"
)

_SENSITIVE_CATEGORY_KEYWORDS = (
    (
        AUTO_TWIN_EXPLORATION_SENSITIVE_CATEGORY_CAPTCHA,
        ("captcha",),
    ),
    (
        AUTO_TWIN_EXPLORATION_SENSITIVE_CATEGORY_PAYMENT,
        ("payment", "checkout", "billing", "pay"),
    ),
    (
        AUTO_TWIN_EXPLORATION_SENSITIVE_CATEGORY_SIGNATURE,
        ("signature", "firma", "esign", "e-sign"),
    ),
    (
        AUTO_TWIN_EXPLORATION_SENSITIVE_CATEGORY_ADMINISTRATIVE_FILING,
        (
            "filing",
            "expediente",
            "tramite",
            "trámite",
            "presentacion",
            "presentación",
            "administrative",
        ),
    ),
)

_RISK_ORDER = {
    AUTO_TWIN_EXPLORATION_RISK_REVERSIBLE: 0,
    AUTO_TWIN_EXPLORATION_RISK_READ_ONLY_NAVIGATION: 1,
}


def _text(value) -> str:
    return str(value or "").strip()


def _required_text(value, *, error) -> str:
    result = _text(value)

    if not result:
        raise ValueError(error)

    return result


def _positive_int(value, *, error, allow_zero=False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(error)

    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(error)

    return value


def _canonical_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def build_exploration_action_identity(action):
    """Stable 4-tuple action identity: ``(kind, policy, selector,
    frame_path)``, the same functional identity
    ``navigation_graph._normalize_action`` already persists on an edge.

    Exposed so callers resolving HUMAN_ONLY decisions elsewhere (e.g.
    ``site_interaction_policy.evaluate_site_interaction``) can build the
    exact keys ``human_only_action_keys`` expects, without this module
    ever re-deriving or duplicating that resolution itself.
    """

    if not isinstance(action, dict):
        raise ValueError(
            "QCC_AUTO_TWIN_EXPLORATION_PLANNER_ACTION_INVALID"
        )

    return (
        _text(action.get("kind")).upper(),
        _text(action.get("policy")).upper(),
        _text(action.get("selector")),
        _text(action.get("frame_path")) or "main",
    )


def _action_haystack(action) -> str:
    element = action.get("element")
    navigation = action.get("navigation")
    semantics = action.get("semantics") or ()

    element = element if isinstance(element, dict) else {}
    navigation = navigation if isinstance(navigation, dict) else {}

    parts = (
        action.get("selector"),
        element.get("id"),
        element.get("name"),
        element.get("type"),
        navigation.get("href"),
        " ".join(str(item) for item in semantics),
    )

    return " ".join(str(part) for part in parts if part).lower()


def _sensitive_keyword_category(action):
    haystack = _action_haystack(action)

    for category, keywords in _SENSITIVE_CATEGORY_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return category

    return None


def _classify_candidate(action, *, human_only_keys):
    """Pure risk classification for one action. Never executes, never
    mutates. ``(included, risk_tier, reason, safety)``."""

    safety = evaluate_action_safety(action)
    decision = safety["decision"]
    identity = build_exploration_action_identity(action)

    if decision == ACTION_SAFETY_DENY:
        return (
            False,
            AUTO_TWIN_EXPLORATION_RISK_UNKNOWN,
            f"ACTION_SAFETY_DENY_{safety['reason']}",
            safety,
        )

    if identity in human_only_keys:
        return (
            False,
            AUTO_TWIN_EXPLORATION_RISK_HUMAN_ONLY,
            "HUMAN_ONLY_EXCLUDED",
            safety,
        )

    kind = identity[0]

    if kind == "FILE_UPLOAD":
        return (
            False,
            AUTO_TWIN_EXPLORATION_RISK_IRREVERSIBLE,
            "IRREVERSIBLE_ACTION_EXCLUDED",
            safety,
        )

    if kind == "SUBMIT":
        return (
            False,
            AUTO_TWIN_EXPLORATION_RISK_SENSITIVE_RESTRICTED,
            "SUBMIT_ACTION_EXCLUDED",
            safety,
        )

    sensitive_category = _sensitive_keyword_category(action)

    if sensitive_category is not None:
        return (
            False,
            AUTO_TWIN_EXPLORATION_RISK_SENSITIVE_RESTRICTED,
            f"{sensitive_category}_ACTION_EXCLUDED",
            safety,
        )

    if decision == ACTION_SAFETY_REVERSIBLE_CANDIDATE:
        return (
            True,
            AUTO_TWIN_EXPLORATION_RISK_REVERSIBLE,
            "REVERSIBLE_EXPLORATION_CANDIDATE",
            safety,
        )

    if decision == ACTION_SAFETY_NAVIGATION_CANDIDATE:
        return (
            True,
            AUTO_TWIN_EXPLORATION_RISK_READ_ONLY_NAVIGATION,
            "READ_ONLY_NAVIGATION_EXPLORATION_CANDIDATE",
            safety,
        )

    # ACTION_SAFETY_REVIEW_REQUIRED (BUTTON / INPUT_VALUE) with no
    # sensitive keyword match: an active, effect-unknown action. Fails
    # closed -- never defaulted to included.
    return (
        False,
        AUTO_TWIN_EXPLORATION_RISK_UNKNOWN,
        "UNKNOWN_RISK_ACTION_EXCLUDED_BY_DEFAULT",
        safety,
    )


def _validate_navigation_graph(navigation_graph):
    if not isinstance(navigation_graph, dict):
        raise ValueError(
            "QCC_AUTO_TWIN_EXPLORATION_PLANNER_GRAPH_INVALID"
        )

    if (
        navigation_graph.get("schema_version")
        != NAVIGATION_GRAPH_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_EXPLORATION_PLANNER_GRAPH_SCHEMA_INVALID"
        )

    if navigation_graph.get("graph_type") != NAVIGATION_GRAPH_TYPE:
        raise ValueError(
            "QCC_AUTO_TWIN_EXPLORATION_PLANNER_GRAPH_TYPE_INVALID"
        )

    raw_edges = navigation_graph.get("edges")

    if not isinstance(raw_edges, (list, tuple)):
        raise ValueError(
            "QCC_AUTO_TWIN_EXPLORATION_PLANNER_GRAPH_EDGES_INVALID"
        )

    edges = []

    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            raise ValueError(
                "QCC_AUTO_TWIN_EXPLORATION_PLANNER_GRAPH_EDGE_INVALID"
            )

        source = _text(raw_edge.get("source_fingerprint"))
        target = _text(raw_edge.get("target_fingerprint"))

        if not source or not target:
            raise ValueError(
                "QCC_AUTO_TWIN_EXPLORATION_PLANNER_GRAPH_EDGE_INVALID"
            )

        action = raw_edge.get("action")

        if not isinstance(action, dict):
            raise ValueError(
                "QCC_AUTO_TWIN_EXPLORATION_PLANNER_GRAPH_EDGE_INVALID"
            )

        edges.append(
            {
                "source_fingerprint": source,
                "target_fingerprint": target,
                "action": action,
            }
        )

    return tuple(edges)


def _edge_sort_key(edge):
    identity = build_exploration_action_identity(edge["action"])

    return (edge["target_fingerprint"],) + identity


def _walk_frontier(edges, *, source_fingerprint, max_steps):
    """Bounded BFS over already-observed transitions only.

    Visited-state protection: a fingerprint is enqueued/expanded at most
    once. Visited-transition protection: an edge is only ever traversed
    once (the moment its target is first discovered); a cyclic graph
    never re-walks the same edge twice. Bounded by ``max_steps``: a
    fingerprint discovered beyond the step budget is never reached, so
    its action inventory is never consulted.
    """

    adjacency = {}

    for edge in edges:
        adjacency.setdefault(edge["source_fingerprint"], []).append(edge)

    for bucket in adjacency.values():
        bucket.sort(key=_edge_sort_key)

    visited = {source_fingerprint: (0, (source_fingerprint,))}
    order = [source_fingerprint]
    queue = deque([source_fingerprint])

    while queue:
        current = queue.popleft()
        depth, path = visited[current]

        if depth >= max_steps:
            continue

        for edge in adjacency.get(current, ()):
            target = edge["target_fingerprint"]

            if target in visited:
                continue

            visited[target] = (depth + 1, path + (target,))
            order.append(target)
            queue.append(target)

    return tuple(order), visited


def _twin_states(observation_store, twin_key):
    snapshot = observation_store.snapshot(twin_key, current_only=True)

    if not snapshot["found"]:
        return {}, None

    twin = snapshot["twin"] or {}
    states = twin.get("states")

    return (states if isinstance(states, dict) else {}), twin.get(
        "site_code"
    )


def _state_context_for_fingerprint(states, fingerprint):
    """Best-effort UWT-4/UWT-5 state/branch context lookup.

    Never fabricates: an ambiguous (more than one match) or unknown
    fingerprint yields explicit ``None`` fields instead of guessing
    which observed state it belongs to.
    """

    matches = tuple(
        state
        for state in states.values()
        if isinstance(state, dict)
        and fingerprint
        in {
            state.get("last_fingerprint"),
            state.get("baseline_fingerprint"),
        }
    )

    if len(matches) != 1:
        return {
            "state_key": None,
            "pathname": None,
            "functional_state": None,
            "branch_context_id": None,
        }

    state = matches[0]

    return {
        "state_key": state.get("state_key"),
        "pathname": state.get("pathname"),
        "functional_state": state.get("functional_state"),
        "branch_context_id": state.get("branch_context_id"),
    }


def _actions_for_fingerprint(action_inventory_by_fingerprint, fingerprint):
    raw = action_inventory_by_fingerprint.get(fingerprint) or ()

    if not isinstance(raw, (list, tuple)):
        raise ValueError(
            "QCC_AUTO_TWIN_EXPLORATION_PLANNER_ACTION_INVENTORY_INVALID"
        )

    for action in raw:
        if not isinstance(action, dict):
            raise ValueError(
                "QCC_AUTO_TWIN_EXPLORATION_PLANNER_ACTION_INVALID"
            )

    return tuple(
        sorted(raw, key=build_exploration_action_identity)
    )


def _candidate_id(*, twin_key, fingerprint, identity):
    payload = {
        "schema_version": AUTO_TWIN_EXPLORATION_CANDIDATE_PLAN_SCHEMA_VERSION,
        "twin_key": twin_key,
        "state_fingerprint": fingerprint,
        "action": {
            "kind": identity[0],
            "policy": identity[1],
            "selector": identity[2],
            "frame_path": identity[3],
        },
    }

    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _candidate_sort_key(candidate):
    return (
        candidate["step_depth"],
        _RISK_ORDER.get(candidate["risk_tier"], 99),
        candidate["state_fingerprint"],
        candidate["action"]["kind"],
        candidate["action"]["policy"],
        candidate["action"]["selector"],
        candidate["action"]["frame_path"],
    )


def _rejected_sort_key(candidate):
    return (
        candidate["step_depth"],
        candidate["state_fingerprint"],
        candidate["action"]["kind"],
        candidate["action"]["policy"],
        candidate["action"]["selector"],
        candidate["action"]["frame_path"],
    )


def plan_exploration_candidates(
    *,
    observation_store,
    twin_key,
    profile_policy,
    navigation_graph,
    action_inventory_by_fingerprint,
    source_fingerprint,
    max_steps=1,
    max_candidates=20,
    human_only_action_keys=(),
):
    """Builds the UWT-11A governed exploration candidate plan.

    Walks ``navigation_graph`` (already-observed transitions only) from
    ``source_fingerprint`` up to ``max_steps`` hops, and at every state
    reached proposes every action in
    ``action_inventory_by_fingerprint`` that does not already have a
    matching edge (an untried action). Every candidate is classified and
    either accepted (REVERSIBLE/READ_ONLY_NAVIGATION, capped at
    ``max_candidates``) or rejected with an explicit machine-readable
    reason. Never executes an action, never launches a browser, never
    promotes anything ACTIVE.

    Only usable for a Discovery Profile (``profile_policy
    .active_discovery``); every other AUTO TWIN profile is rejected
    outright.
    """

    if not isinstance(observation_store, AutoTwinObservationStore):
        raise TypeError(
            "QCC_AUTO_TWIN_EXPLORATION_PLANNER_OBSERVATION_STORE_INVALID"
        )

    if not isinstance(profile_policy, AutoTwinProfilePolicy):
        raise TypeError(
            "QCC_AUTO_TWIN_EXPLORATION_PLANNER_PROFILE_POLICY_INVALID"
        )

    if not profile_policy.active_discovery:
        raise ValueError(
            "QCC_AUTO_TWIN_EXPLORATION_PLANNER_DISCOVERY_PROFILE_REQUIRED"
        )

    twin_key = _required_text(
        twin_key, error="QCC_AUTO_TWIN_KEY_REQUIRED"
    )

    source_fingerprint = _required_text(
        source_fingerprint,
        error="QCC_AUTO_TWIN_EXPLORATION_PLANNER_SOURCE_FINGERPRINT_REQUIRED",
    )

    max_steps = _positive_int(
        max_steps,
        error="QCC_AUTO_TWIN_EXPLORATION_PLANNER_MAX_STEPS_INVALID",
        allow_zero=True,
    )

    max_candidates = _positive_int(
        max_candidates,
        error="QCC_AUTO_TWIN_EXPLORATION_PLANNER_MAX_CANDIDATES_INVALID",
    )

    if not isinstance(action_inventory_by_fingerprint, dict):
        raise ValueError(
            "QCC_AUTO_TWIN_EXPLORATION_PLANNER_ACTION_INVENTORY_INVALID"
        )

    human_only_keys = frozenset(human_only_action_keys or ())

    edges = _validate_navigation_graph(navigation_graph)

    visited_transition_keys = {
        (edge["source_fingerprint"],)
        + build_exploration_action_identity(edge["action"])
        for edge in edges
    }

    order, visited = _walk_frontier(
        edges, source_fingerprint=source_fingerprint, max_steps=max_steps
    )

    states, site_code = _twin_states(observation_store, twin_key)

    included = []
    rejected = []

    for fingerprint in order:
        depth, path = visited[fingerprint]
        context = _state_context_for_fingerprint(states, fingerprint)
        actions = _actions_for_fingerprint(
            action_inventory_by_fingerprint, fingerprint
        )

        for action in actions:
            identity = build_exploration_action_identity(action)

            candidate_id = _candidate_id(
                twin_key=twin_key, fingerprint=fingerprint, identity=identity
            )

            base = {
                "candidate_id": candidate_id,
                "twin_key": twin_key,
                "site_code": site_code,
                "state_key": context["state_key"],
                "pathname": context["pathname"],
                "functional_state": context["functional_state"],
                "branch_context_id": context["branch_context_id"],
                "state_fingerprint": fingerprint,
                "step_depth": depth,
                "path_fingerprints": path,
                "action": {
                    "kind": identity[0],
                    "policy": identity[1],
                    "selector": identity[2],
                    "frame_path": identity[3],
                },
            }

            if (fingerprint,) + identity in visited_transition_keys:
                rejected.append(
                    {
                        **base,
                        "risk_tier": AUTO_TWIN_EXPLORATION_RISK_ALREADY_VISITED,
                        "rejection_reason": "TRANSITION_ALREADY_VISITED",
                    }
                )
                continue

            accept, risk_tier, reason, safety = _classify_candidate(
                action, human_only_keys=human_only_keys
            )

            entry = {
                **base,
                "risk_tier": risk_tier,
                "safety_decision": safety["decision"],
                "safety_reason": safety["reason"],
            }

            if accept:
                entry["acceptance_reason"] = reason
                included.append(entry)
            else:
                entry["rejection_reason"] = reason
                rejected.append(entry)

    included.sort(key=_candidate_sort_key)

    accepted = included[:max_candidates]
    overflow = included[max_candidates:]

    for entry in overflow:
        entry = dict(entry)
        entry.pop("acceptance_reason", None)
        entry["rejection_reason"] = "CANDIDATE_COUNT_BUDGET_EXCEEDED"
        rejected.append(entry)

    rejected.sort(key=_rejected_sort_key)

    result = {
        "schema_version": AUTO_TWIN_EXPLORATION_CANDIDATE_PLAN_SCHEMA_VERSION,
        "result_type": AUTO_TWIN_EXPLORATION_CANDIDATE_PLAN_TYPE,
        "twin_key": twin_key,
        "site_code": site_code,
        "source_fingerprint": source_fingerprint,
        "max_steps": max_steps,
        "max_candidates": max_candidates,
        "visited_fingerprints": order,
        "candidates": tuple(accepted),
        "rejected_candidates": tuple(rejected),
        "candidate_count": len(accepted),
        "rejected_count": len(rejected),
    }

    plan_payload = deepcopy(result)

    result["plan_id"] = hashlib.sha256(
        _canonical_json(plan_payload).encode("utf-8")
    ).hexdigest()

    return result
