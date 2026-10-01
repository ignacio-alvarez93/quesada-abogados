"""UWT-3 Universal State / Transition Graph.

Provider-neutral, site-neutral directed graph of observable web workflow
topology, built strictly on top of the UWT-2 Functional State foundation:

    QCC OBSERVATION
        |
        v
    UWT-2 FUNCTIONAL STATE        (functional_state.py / stable_state_fingerprint.py)
        |
        v
    UWT-3 UNIVERSAL STATE GRAPH   (this module)
        |
        v
    UWT-4 BRANCH CONTEXT          (not implemented here)

This module is topology only. It does not decide *why* a branch exists
(checkbox/radio/select semantics, procedure branching, BranchContext):
that is UWT-4. It stores only accepted graph knowledge explicitly given
to it: no auto-healing, no fuzzy matching, no inferred edges.

Node identity
-------------

A graph node represents one UWT-2 stable functional state. Node identity
is derived deterministically from ``(site_identity, fingerprint.
operative_value)`` — the same decisive, page-independent evidence
``functional_delta.compare_functional_state`` already uses to decide
SAME_FUNCTIONAL_STATE. This means:

- repeated observations of the same functional state resolve to the same
  node, regardless of DOM noise (already excluded upstream by UWT-2);
- the same URL may back multiple functional nodes (operative evidence
  differs);
- different URLs may collapse onto the same functional node when UWT-2
  says the operative evidence is equivalent (page identity excluded by
  design, see stable_state_fingerprint.py);
- no UUID, no raw URL, no raw HTML, no Python hash() is ever graph
  identity authority.

Transition identity
--------------------

A transition is SOURCE_STATE + ACTION -> TARGET_STATE. Its deterministic
identity is derived from ``(source_node_id, action_identity)`` only —
deliberately *not* including the target. This is what allows UWT-3 to
fail closed (section 9 of the work order) when the same source state and
the same action are later observed to lead to an incompatible target,
instead of silently multiplying ambiguous edges.

Action identity (``ActionIdentity``) is a generic (kind, selector,
frame_path) triple. It carries no provider-specific or site-specific
semantics; branch interpretation of *why* an action differs belongs to
UWT-4.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from .functional_state import FunctionalState


STATE_GRAPH_SCHEMA_VERSION = 1
STATE_GRAPH_TYPE = "QCC_UWT_STATE_GRAPH"

STATE_NODE_SCHEMA_VERSION = 1
STATE_TRANSITION_SCHEMA_VERSION = 1

_GRAPH_NODE_NAMESPACE = "QCC_UWT_GRAPH_NODE_V1\0"
_GRAPH_TRANSITION_NAMESPACE = "QCC_UWT_GRAPH_TRANSITION_V1\0"


class GraphInvariantError(ValueError):
    """Raised when a graph operation would violate a UWT-3 fail-closed
    invariant (missing endpoint, identity collision, malformed data)."""


def _text(value):
    value = str(
        value
        or ""
    ).strip()

    return value or None


def _canonical_json(payload):
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalize_provenance(provenance):
    if provenance is None:
        items = ()
    elif isinstance(provenance, str):
        items = (provenance,)
    else:
        items = tuple(provenance)

    normalized = {
        _text(item)
        for item in items
        if _text(item)
    }

    return tuple(sorted(normalized))


def _merge_provenance(existing, new):
    if not new:
        return existing

    merged = set(existing) | set(new)

    return tuple(sorted(merged))


# ---------------------------------------------------------------------------
# Action identity
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ActionIdentity:
    """Provider-neutral action identity: (kind, selector, frame_path)."""

    kind: str
    selector: str
    frame_path: str = "main"

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "selector": self.selector,
            "frame_path": self.frame_path,
        }


def build_action_identity(
    *,
    kind,
    selector,
    frame_path="main",
) -> ActionIdentity:
    normalized_kind = _text(kind)

    if not normalized_kind:
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_ACTION_KIND_REQUIRED"
        )

    normalized_selector = _text(selector)

    if not normalized_selector:
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_ACTION_SELECTOR_REQUIRED"
        )

    normalized_frame_path = _text(frame_path) or "main"

    return ActionIdentity(
        kind=normalized_kind.upper(),
        selector=normalized_selector,
        frame_path=normalized_frame_path,
    )


# ---------------------------------------------------------------------------
# Deterministic identity derivation
# ---------------------------------------------------------------------------

def _derive_graph_node_id(site_identity, operative_value):
    operative_text = _text(operative_value)

    if not operative_text:
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_NODE_OPERATIVE_VALUE_REQUIRED"
        )

    canonical = _canonical_json(
        {
            "site_identity": _text(site_identity),
            "operative_value": operative_text,
        }
    )

    return hashlib.sha256(
        (
            _GRAPH_NODE_NAMESPACE
            + canonical
        ).encode("utf-8")
    ).hexdigest()


def derive_state_node_id(functional_state) -> str:
    """Deterministic UWT-3 node identity for a UWT-2 FunctionalState.

    Fails closed (raises) for states that cannot be represented as a
    stable DOM node: missing evidence or an external UI boundary.
    """

    if not isinstance(functional_state, FunctionalState):
        raise TypeError(
            "QCC_UWT_GRAPH_STATE_INPUT_INVALID"
        )

    if functional_state.external_ui_boundary is not None:
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_STATE_EXTERNAL_BOUNDARY_UNREPRESENTABLE"
        )

    if (
        not functional_state.evidence_available
        or functional_state.fingerprint is None
    ):
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_STATE_EVIDENCE_UNAVAILABLE"
        )

    return _derive_graph_node_id(
        functional_state.site_identity,
        functional_state.fingerprint.operative_value,
    )


def derive_transition_id(source_node_id, action) -> str:
    """Deterministic transition identity from (source, action) only.

    Target is deliberately excluded: this is what lets StateGraph detect
    an incompatible-target collision instead of silently branching.
    """

    if not isinstance(action, ActionIdentity):
        raise TypeError(
            "QCC_UWT_GRAPH_TRANSITION_ACTION_INVALID"
        )

    source_id = _text(source_node_id)

    if not source_id:
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_TRANSITION_SOURCE_INVALID"
        )

    canonical = _canonical_json(
        {
            "source_node_id": source_id,
            "action": action.as_dict(),
        }
    )

    return hashlib.sha256(
        (
            _GRAPH_TRANSITION_NAMESPACE
            + canonical
        ).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Node / transition records
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class StateNode:
    """One graph node: a stable UWT-2 functional state, graph-addressed."""

    schema_version: int
    node_id: str
    site_identity: str | None
    fingerprint_value: str
    fingerprint_operative_value: str
    operative_payload: MappingProxyType
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StateTransition:
    """One directed edge: SOURCE_STATE + ACTION -> TARGET_STATE."""

    schema_version: int
    transition_id: str
    source_node_id: str
    target_node_id: str
    action: ActionIdentity
    provenance: tuple[str, ...] = ()
    metadata: MappingProxyType = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class GraphValidationResult:
    """Read-only integrity diagnostic. Disconnected components are not
    an error: a universal web graph may have several known entry points
    or partially observed areas (work order section 15/16)."""

    ok: bool
    errors: tuple[str, ...] = ()


def _node_to_dict(node: StateNode) -> dict:
    return {
        "node_id": node.node_id,
        "site_identity": node.site_identity,
        "fingerprint_value": node.fingerprint_value,
        "fingerprint_operative_value": node.fingerprint_operative_value,
        "operative_payload": dict(node.operative_payload),
        "provenance": list(node.provenance),
    }


def _node_from_dict(raw) -> StateNode:
    if not isinstance(raw, dict):
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_NODE_MALFORMED"
        )

    node_id = _text(raw.get("node_id"))
    site_identity = _text(raw.get("site_identity"))
    fingerprint_value = _text(raw.get("fingerprint_value"))
    fingerprint_operative_value = _text(
        raw.get("fingerprint_operative_value")
    )
    operative_payload = raw.get("operative_payload")
    provenance = _normalize_provenance(raw.get("provenance"))

    if (
        not node_id
        or not fingerprint_value
        or not fingerprint_operative_value
    ):
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_NODE_MALFORMED"
        )

    if not isinstance(operative_payload, dict):
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_NODE_MALFORMED"
        )

    expected_node_id = _derive_graph_node_id(
        site_identity,
        fingerprint_operative_value,
    )

    if expected_node_id != node_id:
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_NODE_IDENTITY_MISMATCH"
        )

    return StateNode(
        schema_version=STATE_NODE_SCHEMA_VERSION,
        node_id=node_id,
        site_identity=site_identity,
        fingerprint_value=fingerprint_value,
        fingerprint_operative_value=fingerprint_operative_value,
        operative_payload=MappingProxyType(
            dict(operative_payload)
        ),
        provenance=provenance,
    )


def _transition_to_dict(transition: StateTransition) -> dict:
    return {
        "transition_id": transition.transition_id,
        "source_node_id": transition.source_node_id,
        "target_node_id": transition.target_node_id,
        "action": transition.action.as_dict(),
        "provenance": list(transition.provenance),
        "metadata": dict(transition.metadata),
    }


def _transition_from_dict(raw) -> StateTransition:
    if not isinstance(raw, dict):
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_TRANSITION_MALFORMED"
        )

    transition_id = _text(raw.get("transition_id"))
    source_node_id = _text(raw.get("source_node_id"))
    target_node_id = _text(raw.get("target_node_id"))
    raw_action = raw.get("action")
    metadata = raw.get("metadata") or {}
    provenance = _normalize_provenance(raw.get("provenance"))

    if (
        not transition_id
        or not source_node_id
        or not target_node_id
        or not isinstance(raw_action, dict)
        or not isinstance(metadata, dict)
    ):
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_TRANSITION_MALFORMED"
        )

    action = build_action_identity(
        kind=raw_action.get("kind"),
        selector=raw_action.get("selector"),
        frame_path=raw_action.get("frame_path"),
    )

    expected_transition_id = derive_transition_id(
        source_node_id,
        action,
    )

    if expected_transition_id != transition_id:
        raise GraphInvariantError(
            "QCC_UWT_GRAPH_TRANSITION_IDENTITY_MISMATCH"
        )

    return StateTransition(
        schema_version=STATE_TRANSITION_SCHEMA_VERSION,
        transition_id=transition_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        action=action,
        provenance=provenance,
        metadata=MappingProxyType(dict(metadata)),
    )


def _transition_sort_key_outgoing(transition: StateTransition):
    return (
        transition.action.kind,
        transition.action.selector,
        transition.action.frame_path,
        transition.target_node_id,
    )


def _transition_sort_key_incoming(transition: StateTransition):
    return (
        transition.action.kind,
        transition.action.selector,
        transition.action.frame_path,
        transition.source_node_id,
    )


# ---------------------------------------------------------------------------
# StateGraph
# ---------------------------------------------------------------------------

class StateGraph:
    """Directed, provider-neutral universal state/transition graph.

    Topology only (work order section 13): no branch-cause semantics, no
    auto-healing, no fuzzy matching. Supports linear flows, bifurcation,
    convergence, loops/self-loops and partial/incomplete knowledge.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, StateNode] = {}
        self._transitions: dict[str, StateTransition] = {}
        self._by_source: dict[str, set[str]] = {}
        self._by_target: dict[str, set[str]] = {}

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def transition_count(self) -> int:
        return len(self._transitions)

    # -- mutation ------------------------------------------------------

    def add_state(
        self,
        functional_state,
        *,
        provenance=None,
    ) -> StateNode:
        """Idempotently adds a UWT-2 FunctionalState as a graph node.

        Fails closed when the same deterministic node identity already
        exists with incompatible operative evidence (work order
        section 9) instead of silently overwriting it.
        """

        node_id = derive_state_node_id(functional_state)

        operative_payload = dict(
            functional_state.operative_payload
        )

        provenance_entries = _normalize_provenance(provenance)

        existing = self._nodes.get(node_id)

        if existing is not None:
            if (
                existing.operative_payload != operative_payload
                or existing.fingerprint_operative_value
                != functional_state.fingerprint.operative_value
            ):
                raise GraphInvariantError(
                    "QCC_UWT_GRAPH_NODE_IDENTITY_COLLISION_INCOMPATIBLE"
                )

            merged_provenance = _merge_provenance(
                existing.provenance,
                provenance_entries,
            )

            if merged_provenance == existing.provenance:
                return existing

            updated = replace(
                existing,
                provenance=merged_provenance,
            )

            self._nodes[node_id] = updated

            return updated

        node = StateNode(
            schema_version=STATE_NODE_SCHEMA_VERSION,
            node_id=node_id,
            site_identity=functional_state.site_identity,
            fingerprint_value=functional_state.fingerprint.value,
            fingerprint_operative_value=(
                functional_state.fingerprint.operative_value
            ),
            operative_payload=MappingProxyType(operative_payload),
            provenance=provenance_entries,
        )

        self._nodes[node_id] = node

        return node

    def add_transition(
        self,
        *,
        source_node_id,
        action,
        target_node_id,
        provenance=None,
        metadata=None,
    ) -> StateTransition:
        """Strict edge insertion: both endpoints must already be known
        graph nodes. Fails closed on a missing endpoint or on an
        incompatible-target collision for the same (source, action)
        (work order sections 6, 9). Idempotent for repeated identical
        insertion (provenance accumulates)."""

        source_id = _text(source_node_id)
        target_id = _text(target_node_id)

        if not source_id or not target_id:
            raise GraphInvariantError(
                "QCC_UWT_GRAPH_TRANSITION_ENDPOINT_INVALID"
            )

        if not isinstance(action, ActionIdentity):
            raise TypeError(
                "QCC_UWT_GRAPH_TRANSITION_ACTION_INVALID"
            )

        if source_id not in self._nodes:
            raise GraphInvariantError(
                "QCC_UWT_GRAPH_TRANSITION_SOURCE_MISSING"
            )

        if target_id not in self._nodes:
            raise GraphInvariantError(
                "QCC_UWT_GRAPH_TRANSITION_TARGET_MISSING"
            )

        transition_id = derive_transition_id(source_id, action)
        provenance_entries = _normalize_provenance(provenance)
        metadata_payload = MappingProxyType(dict(metadata or {}))

        existing = self._transitions.get(transition_id)

        if existing is not None:
            if existing.target_node_id != target_id:
                raise GraphInvariantError(
                    "QCC_UWT_GRAPH_TRANSITION_IDENTITY_COLLISION_INCOMPATIBLE"
                )

            merged_provenance = _merge_provenance(
                existing.provenance,
                provenance_entries,
            )

            if merged_provenance == existing.provenance:
                return existing

            updated = replace(
                existing,
                provenance=merged_provenance,
            )

            self._transitions[transition_id] = updated

            return updated

        transition = StateTransition(
            schema_version=STATE_TRANSITION_SCHEMA_VERSION,
            transition_id=transition_id,
            source_node_id=source_id,
            target_node_id=target_id,
            action=action,
            provenance=provenance_entries,
            metadata=metadata_payload,
        )

        self._transitions[transition_id] = transition
        self._by_source.setdefault(source_id, set()).add(transition_id)
        self._by_target.setdefault(target_id, set()).add(transition_id)

        return transition

    def add_observed_transition(
        self,
        *,
        source_state,
        action,
        target_state,
        provenance=None,
        metadata=None,
    ) -> StateTransition:
        """Atomic builder: ensures both endpoint states exist as nodes
        (adding them if necessary) and then records the transition. This
        is the intentional path allowed by work order section 9 for
        creating source/target nodes as part of recording a transition."""

        source_node = self.add_state(
            source_state,
            provenance=provenance,
        )

        target_node = self.add_state(
            target_state,
            provenance=provenance,
        )

        return self.add_transition(
            source_node_id=source_node.node_id,
            action=action,
            target_node_id=target_node.node_id,
            provenance=provenance,
            metadata=metadata,
        )

    # -- queries ---------------------------------------------------------

    def get_state(self, node_id) -> StateNode | None:
        return self._nodes.get(_text(node_id))

    def outgoing(self, node_id) -> tuple[StateTransition, ...]:
        ids = self._by_source.get(_text(node_id)) or ()

        return tuple(
            sorted(
                (self._transitions[tid] for tid in ids),
                key=_transition_sort_key_outgoing,
            )
        )

    def incoming(self, node_id) -> tuple[StateTransition, ...]:
        ids = self._by_target.get(_text(node_id)) or ()

        return tuple(
            sorted(
                (self._transitions[tid] for tid in ids),
                key=_transition_sort_key_incoming,
            )
        )

    def successors(self, node_id) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    transition.target_node_id
                    for transition in self.outgoing(node_id)
                }
            )
        )

    def predecessors(self, node_id) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    transition.source_node_id
                    for transition in self.incoming(node_id)
                }
            )
        )

    def has_transition(
        self,
        *,
        source_node_id,
        action,
        target_node_id,
    ) -> bool:
        if not isinstance(action, ActionIdentity):
            return False

        source_id = _text(source_node_id)
        target_id = _text(target_node_id)

        if not source_id or not target_id:
            return False

        transition = self._transitions.get(
            derive_transition_id(source_id, action)
        )

        return (
            transition is not None
            and transition.target_node_id == target_id
        )

    def is_reachable(self, source_node_id, target_node_id) -> bool:
        source_id = _text(source_node_id)
        target_id = _text(target_node_id)

        if (
            not source_id
            or not target_id
            or source_id not in self._nodes
            or target_id not in self._nodes
        ):
            return False

        if source_id == target_id:
            return True

        return self.find_path(source_id, target_id) is not None

    def find_path(
        self,
        source_node_id,
        target_node_id,
    ) -> tuple[str, ...] | None:
        """Deterministic shortest-path BFS. Terminates on cyclic graphs
        via visited-node tracking (work order section 11)."""

        source_id = _text(source_node_id)
        target_id = _text(target_node_id)

        if (
            not source_id
            or not target_id
            or source_id not in self._nodes
            or target_id not in self._nodes
        ):
            return None

        if source_id == target_id:
            return (source_id,)

        visited = {source_id}
        queue = deque([(source_id,)])

        while queue:
            path = queue.popleft()
            current = path[-1]

            for neighbor in self.successors(current):
                if neighbor in visited:
                    continue

                new_path = path + (neighbor,)

                if neighbor == target_id:
                    return new_path

                visited.add(neighbor)
                queue.append(new_path)

        return None

    # -- integrity ---------------------------------------------------------

    def validate(self) -> GraphValidationResult:
        errors = []

        for transition in self._transitions.values():
            if transition.source_node_id not in self._nodes:
                errors.append(
                    "DANGLING_SOURCE:" + transition.transition_id
                )

            if transition.target_node_id not in self._nodes:
                errors.append(
                    "DANGLING_TARGET:" + transition.transition_id
                )

        return GraphValidationResult(
            ok=not errors,
            errors=tuple(sorted(errors)),
        )

    # -- serialization -------------------------------------------------

    def to_dict(self) -> dict:
        nodes = tuple(
            sorted(
                (
                    _node_to_dict(node)
                    for node in self._nodes.values()
                ),
                key=lambda item: item["node_id"],
            )
        )

        transitions = tuple(
            sorted(
                (
                    _transition_to_dict(transition)
                    for transition in self._transitions.values()
                ),
                key=lambda item: item["transition_id"],
            )
        )

        return {
            "schema_version": STATE_GRAPH_SCHEMA_VERSION,
            "graph_type": STATE_GRAPH_TYPE,
            "node_count": len(nodes),
            "transition_count": len(transitions),
            "nodes": nodes,
            "transitions": transitions,
        }

    @staticmethod
    def from_dict(data) -> "StateGraph":
        if not isinstance(data, dict):
            raise GraphInvariantError(
                "QCC_UWT_GRAPH_SERIALIZED_PAYLOAD_INVALID"
            )

        if data.get("schema_version") != STATE_GRAPH_SCHEMA_VERSION:
            raise GraphInvariantError(
                "QCC_UWT_GRAPH_SCHEMA_VERSION_INVALID"
            )

        if data.get("graph_type") != STATE_GRAPH_TYPE:
            raise GraphInvariantError(
                "QCC_UWT_GRAPH_TYPE_INVALID"
            )

        graph = StateGraph()

        for raw_node in data.get("nodes") or ():
            node = _node_from_dict(raw_node)

            if node.node_id in graph._nodes:
                raise GraphInvariantError(
                    "QCC_UWT_GRAPH_NODE_DUPLICATE_IN_SERIALIZED_DATA"
                )

            graph._nodes[node.node_id] = node

        for raw_transition in data.get("transitions") or ():
            transition = _transition_from_dict(raw_transition)

            if transition.transition_id in graph._transitions:
                raise GraphInvariantError(
                    "QCC_UWT_GRAPH_TRANSITION_DUPLICATE_IN_SERIALIZED_DATA"
                )

            if transition.source_node_id not in graph._nodes:
                raise GraphInvariantError(
                    "QCC_UWT_GRAPH_TRANSITION_SOURCE_MISSING"
                )

            if transition.target_node_id not in graph._nodes:
                raise GraphInvariantError(
                    "QCC_UWT_GRAPH_TRANSITION_TARGET_MISSING"
                )

            graph._transitions[transition.transition_id] = transition
            graph._by_source.setdefault(
                transition.source_node_id, set()
            ).add(transition.transition_id)
            graph._by_target.setdefault(
                transition.target_node_id, set()
            ).add(transition.transition_id)

        return graph
