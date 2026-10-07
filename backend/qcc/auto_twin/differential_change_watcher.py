"""QCC AUTO TWIN — Differential Change Watcher (UWT-9).

Work Order UWT-9 asks for a bounded slice that compares a newly observed
REAL contract/evidence against the ACTIVE Twin revision and classifies
the resulting drift into structural / interaction / resource /
state-transition categories.

Canonical source audit
-----------------------

Everything this capability needs to *compare* and *persist* already
exists and is explicitly reused, never duplicated:

- ``AutoTwinObservationStore`` already tracks, per ``(twin_key,
  state_key)``, the ACTIVE Twin revision (``baseline_capture_id`` /
  ``baseline_fingerprint`` — set once, only on first discovery, never
  auto-advanced; see its own module docstring and
  ``candidate_revision_store``'s "La revisión ACTIVE permanece intacta")
  and the latest REAL observation (``last_capture_id``).
- ``contract_watcher`` (1A) already produces deterministic, PII-safe,
  idempotent evidence (``evidence_id`` content-addressed, never
  recomputed from incidental metadata) comparing two normalized Site
  Contracts, including a pairwise diff (``elements`` / ``catalog_diff``
  / ``page_changed`` / ``fingerprint_changed``) and a severity/
  watch-state classification that already fails closed to UNKNOWN /
  VALIDATION_REQUIRED on inconclusive evidence.
- ``contract_watcher_persisted_adapter`` (1D) already resolves a
  persisted ``capture_id`` into the normalized Site Contract 1A
  consumes, and ``contract_watcher_observation_selector``'s
  ``contract_watcher_observation_contract_key`` already defines the one
  deterministic ``(twin_key, state_key) -> contract_key`` identity
  convention this slice reuses verbatim.
- ``run_contract_watcher_persisted_cycle`` (1C+1D) already owns
  persistence, baseline-identity pinning and idempotent replay.

What does not exist yet, and is the entire contribution of this module,
is the AUTO-TWIN-specific bridge that:

1. resolves exactly one ``(twin_key, state_key)``'s ACTIVE baseline and
   latest REAL observation pointers (scoped, read-only — never a second
   writer of ``AutoTwinObservationStore``);
2. classifies the resulting Contract Watcher evidence into the
   STRUCTURAL / INTERACTION / RESOURCE / STATE_TRANSITION drift
   categories this Work Order requires, which 1A's severity axis
   (COSMETIC/NON_BREAKING/CONTRACT_CHANGE/BREAKING/UNKNOWN) does not
   express — WHAT changed, not HOW breaking it is.

Category mapping (deliberately minimal, invents no new comparator):

``STRUCTURAL``
    ``page_changed``, element ADDED/REMOVED, or an element CHANGED via
    ``SEMANTICS_CHANGED``/``SELECTOR_CHANGED``/``GEOMETRY_CHANGED`` —
    the element/page identity ``diff_site_architecture`` already
    computes.

``INTERACTION``
    An element CHANGED via ``INTERACTION_CHANGED`` — visibility/
    disabled/readonly/hidden state ``diff_site_architecture`` already
    computes.

``RESOURCE``
    A catalog/option inventory change (``catalog_diff.catalogs_added``/
    ``catalogs_removed``/``option_changes``) — the same catalog/option
    evolution 1A already computes and the rest of this package already
    treats as an external dependent-resource inventory (see
    ``catalog_dependency_store``).

``STATE_TRANSITION``
    ``fingerprint_changed`` — the same functional-state identity
    ``backend.automation.site_architecture.state_transition`` already
    uses to decide ``FUNCTIONAL_STATE_CHANGED``.

These categories are not mutually exclusive (a single observation may
exhibit several at once) and are derived purely from fields 1A's
evidence record already carries — classification never re-reads a Site
Contract, a capture or any other raw evidence.

Governance this module preserves (never violates)
----------------------------------------------------

- No automatic ACTIVE promotion: this module never writes to
  ``AutoTwinObservationStore`` and never calls
  ``AutoTwinCandidateRevisionStore``/``AutoTwinMaterializedRevisionStore``.
  A detected drift is reported, never promoted.
- No mutation of REAL: only reads already-persisted captures via 1D's
  existing loader.
- No duplicate source of truth: the category classification is a pure,
  read-only projection recomputed from the one evidence record 1A/1C/1D
  already persist; no second copy of the Site Contract or of Contract
  Watcher evidence is ever stored by this module.
- Idempotent re-observation: delegates entirely to 1C/1D's own
  idempotent, content-addressed evidence identity and replay behavior.
- Stable identity/version linkage: reuses
  ``contract_watcher_observation_contract_key`` (never redefines a
  second ``(twin_key, state_key)`` identity convention) plus 1A's own
  ``evidence_id``.
- UNKNOWN / insufficient evidence stays explicit: an inconclusive
  comparison (unmatched elements/catalogs) yields an explicit
  ``DIFFERENTIAL_CHANGE_RESULT_UNKNOWN`` result with no categories ever
  asserted from ambiguous evidence; a state not yet baselined or with
  nothing new to compare is reported as an explicit skip (same skip
  vocabulary 1E already uses), never silently treated as "no drift".
"""

from __future__ import annotations

from backend.automation.site_architecture.contract_diff import (
    ContractChange,
    GEOMETRY_CHANGED,
    INTERACTION_CHANGED,
    SELECTOR_CHANGED,
    SEMANTICS_CHANGED,
)
from backend.qcc.site_architecture.ingestor import (
    DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
)

from .contract_watcher_lifecycle import (
    get_default_contract_watcher_evidence_store,
    get_default_contract_watcher_history_store,
)
from .contract_watcher_observation_selector import (
    CONTRACT_WATCHER_SELECTOR_SKIP_NOTHING_TO_COMPARE,
    CONTRACT_WATCHER_SELECTOR_SKIP_STATE_NOT_BASELINED,
    contract_watcher_observation_contract_key,
)
from .contract_watcher_persisted_adapter import (
    ContractWatcherCycleError,
    ContractWatcherPersistedCaptureRef,
    ContractWatcherPersistedWatchRequest,
    run_contract_watcher_persisted_cycle,
)
from .contract_watcher_pipeline import DEFAULT_GEOMETRY_TOLERANCE_PX
from .observation_store import AutoTwinObservationStore


DIFFERENTIAL_CHANGE_WATCHER_SCHEMA_VERSION = 1

DIFFERENTIAL_CHANGE_CATEGORY_STRUCTURAL = "STRUCTURAL"
DIFFERENTIAL_CHANGE_CATEGORY_INTERACTION = "INTERACTION"
DIFFERENTIAL_CHANGE_CATEGORY_RESOURCE = "RESOURCE"
DIFFERENTIAL_CHANGE_CATEGORY_STATE_TRANSITION = "STATE_TRANSITION"

# Canonical, deterministic reporting order. Never alphabetical-by-accident:
# explicitly pinned so two equal category sets always serialize identically.
DIFFERENTIAL_CHANGE_CATEGORIES = (
    DIFFERENTIAL_CHANGE_CATEGORY_STRUCTURAL,
    DIFFERENTIAL_CHANGE_CATEGORY_INTERACTION,
    DIFFERENTIAL_CHANGE_CATEGORY_RESOURCE,
    DIFFERENTIAL_CHANGE_CATEGORY_STATE_TRANSITION,
)

_STRUCTURAL_ELEMENT_REASONS = frozenset({
    SEMANTICS_CHANGED,
    SELECTOR_CHANGED,
    GEOMETRY_CHANGED,
})

DIFFERENTIAL_CHANGE_RESULT_CLASSIFIED = "CLASSIFIED"
DIFFERENTIAL_CHANGE_RESULT_NO_DRIFT = "NO_DRIFT"
DIFFERENTIAL_CHANGE_RESULT_UNKNOWN = "UNKNOWN"
DIFFERENTIAL_CHANGE_RESULT_SKIPPED = "SKIPPED"

_REQUIRED_EVIDENCE_FIELDS = (
    "inconclusive",
    "elements",
    "catalog_diff",
    "fingerprint_changed",
    "page_changed",
)


def _text(value) -> str:
    return str(value or "").strip()


def _required_text(value, *, error) -> str:
    result = _text(value)

    if not result:
        raise ValueError(error)

    return result


def classify_differential_change_categories(evidence):
    """Pure, deterministic STRUCTURAL/INTERACTION/RESOURCE/STATE_TRANSITION
    classification over an already-built Contract Watcher evidence record
    (or the bare dict returned by ``compare_site_contract_revision`` —
    both carry the same diff fields).

    Never re-reads a Site Contract or a capture: every signal consulted
    here is already present on ``evidence``. Fails closed (raises) on a
    structurally malformed input instead of guessing; reports an explicit
    ``DIFFERENTIAL_CHANGE_RESULT_UNKNOWN`` (no categories ever asserted)
    when the underlying comparison itself was inconclusive.
    """

    if not isinstance(evidence, dict):
        raise TypeError("QCC_DIFFERENTIAL_CHANGE_WATCHER_EVIDENCE_INVALID")

    for field in _REQUIRED_EVIDENCE_FIELDS:
        if field not in evidence:
            raise ValueError(
                "QCC_DIFFERENTIAL_CHANGE_WATCHER_EVIDENCE_FIELD_MISSING"
            )

    if evidence["inconclusive"]:
        return {
            "result": DIFFERENTIAL_CHANGE_RESULT_UNKNOWN,
            "categories": (),
            "category_evidence": {},
        }

    elements = evidence["elements"] or ()

    structural_added = sum(
        1 for item in elements if item.get("change") == ContractChange.ADDED.value
    )

    structural_removed = sum(
        1 for item in elements if item.get("change") == ContractChange.REMOVED.value
    )

    structural_changed = sum(
        1
        for item in elements
        if item.get("change") == ContractChange.CHANGED.value
        and any(
            reason in _STRUCTURAL_ELEMENT_REASONS
            for reason in (item.get("changes") or ())
        )
    )

    interaction_changed = sum(
        1
        for item in elements
        if item.get("change") == ContractChange.CHANGED.value
        and INTERACTION_CHANGED in (item.get("changes") or ())
    )

    catalog_diff = evidence["catalog_diff"] or {}

    catalogs_added = len(catalog_diff.get("catalogs_added") or ())
    catalogs_removed = len(catalog_diff.get("catalogs_removed") or ())
    option_changes = len(catalog_diff.get("option_changes") or ())

    category_evidence = {}

    if evidence["page_changed"] or structural_added or structural_removed or structural_changed:
        category_evidence[DIFFERENTIAL_CHANGE_CATEGORY_STRUCTURAL] = {
            "page_changed": bool(evidence["page_changed"]),
            "elements_added": structural_added,
            "elements_removed": structural_removed,
            "elements_changed": structural_changed,
        }

    if interaction_changed:
        category_evidence[DIFFERENTIAL_CHANGE_CATEGORY_INTERACTION] = {
            "elements_changed": interaction_changed,
        }

    if catalogs_added or catalogs_removed or option_changes:
        category_evidence[DIFFERENTIAL_CHANGE_CATEGORY_RESOURCE] = {
            "catalogs_added": catalogs_added,
            "catalogs_removed": catalogs_removed,
            "option_changes": option_changes,
        }

    if evidence["fingerprint_changed"]:
        category_evidence[DIFFERENTIAL_CHANGE_CATEGORY_STATE_TRANSITION] = {
            "before_functional_fingerprint": evidence.get(
                "before_functional_fingerprint"
            ),
            "after_functional_fingerprint": evidence.get(
                "after_functional_fingerprint"
            ),
        }

    categories = tuple(
        category
        for category in DIFFERENTIAL_CHANGE_CATEGORIES
        if category in category_evidence
    )

    result = (
        DIFFERENTIAL_CHANGE_RESULT_CLASSIFIED
        if categories
        else DIFFERENTIAL_CHANGE_RESULT_NO_DRIFT
    )

    return {
        "result": result,
        "categories": categories,
        "category_evidence": category_evidence,
    }


def _resolve_twin_state(observation_store, *, twin_key, state_key):
    snapshot = observation_store.snapshot(twin_key)

    if not snapshot["found"]:
        return None

    states = snapshot["twin"].get("states")

    if not isinstance(states, dict):
        raise ValueError(
            "QCC_DIFFERENTIAL_CHANGE_WATCHER_SNAPSHOT_STATES_INVALID"
        )

    state = states.get(state_key)

    return state if isinstance(state, dict) else None


def build_differential_change_evidence_for_twin_state(
    observation_store,
    *,
    twin_key,
    state_key,
    confirmation_policy,
    capture_root=DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
    geometry_tolerance_px=DEFAULT_GEOMETRY_TOLERANCE_PX,
    evidence_store=None,
    history_store=None,
):
    """The UWT-9 bridge: REAL observation vs ACTIVE Twin revision.

    ``twin_key``/``state_key`` are AUTO TWIN's own stable identity
    (``AutoTwinObservationStore``'s ``state_key`` convention — never
    redefined here). The ACTIVE Twin revision is read, never mutated,
    straight from that store's ``baseline_capture_id``; the newly
    observed REAL evidence is that same state's ``last_capture_id``,
    also read-only.

    Delegates the entire comparison/persistence/idempotency contract to
    the already-governed Contract Watcher pipeline
    (``run_contract_watcher_persisted_cycle`` — 1A+1C+1D combined) and
    adds only the drift-category classification that does not already
    exist. Never promotes ACTIVE, never mutates REAL evidence, never
    persists a second copy of the Site Contract or of the Contract
    Watcher evidence.

    Returns an explicit, fail-closed result for every legitimate
    business state (not yet baselined, nothing new to compare, or a
    structurally inconclusive comparison) instead of ever reporting a
    false "no drift". Calling this again for the exact same
    ``last_capture_id`` is idempotent: it replays 1C's own idempotent
    evidence identity instead of creating a second one.
    """

    if not isinstance(observation_store, AutoTwinObservationStore):
        raise TypeError(
            "QCC_DIFFERENTIAL_CHANGE_WATCHER_OBSERVATION_STORE_INVALID"
        )

    twin_key = _required_text(
        twin_key,
        error="QCC_DIFFERENTIAL_CHANGE_WATCHER_TWIN_KEY_REQUIRED",
    )

    state_key = _required_text(
        state_key,
        error="QCC_DIFFERENTIAL_CHANGE_WATCHER_STATE_KEY_REQUIRED",
    )

    contract_key = contract_watcher_observation_contract_key(twin_key, state_key)

    state = _resolve_twin_state(
        observation_store, twin_key=twin_key, state_key=state_key
    )

    if state is None:
        return {
            "result": DIFFERENTIAL_CHANGE_RESULT_SKIPPED,
            "twin_key": twin_key,
            "state_key": state_key,
            "contract_key": contract_key,
            "reason": CONTRACT_WATCHER_SELECTOR_SKIP_STATE_NOT_BASELINED,
        }

    baseline_capture_id = _text(state.get("baseline_capture_id"))
    last_capture_id = _text(state.get("last_capture_id"))

    if not baseline_capture_id or not last_capture_id:
        return {
            "result": DIFFERENTIAL_CHANGE_RESULT_SKIPPED,
            "twin_key": twin_key,
            "state_key": state_key,
            "contract_key": contract_key,
            "reason": CONTRACT_WATCHER_SELECTOR_SKIP_STATE_NOT_BASELINED,
        }

    if baseline_capture_id == last_capture_id:
        return {
            "result": DIFFERENTIAL_CHANGE_RESULT_SKIPPED,
            "twin_key": twin_key,
            "state_key": state_key,
            "contract_key": contract_key,
            "reason": CONTRACT_WATCHER_SELECTOR_SKIP_NOTHING_TO_COMPARE,
        }

    request = ContractWatcherPersistedWatchRequest(
        contract_key=contract_key,
        baseline_capture=ContractWatcherPersistedCaptureRef(
            capture_id=baseline_capture_id, root=capture_root
        ),
        observation_capture=ContractWatcherPersistedCaptureRef(
            capture_id=last_capture_id, root=capture_root
        ),
        confirmation_policy=confirmation_policy,
        geometry_tolerance_px=geometry_tolerance_px,
        observed_at=_text(state.get("last_seen_at")) or None,
        request_id=contract_key,
    )

    resolved_evidence_store = (
        evidence_store or get_default_contract_watcher_evidence_store()
    )

    resolved_history_store = (
        history_store or get_default_contract_watcher_history_store()
    )

    receipt = run_contract_watcher_persisted_cycle(
        request,
        evidence_store=resolved_evidence_store,
        history_store=resolved_history_store,
    )

    full_evidence = resolved_evidence_store.get(
        contract_key=contract_key,
        evidence_id=receipt["evidence_id"],
    )

    if full_evidence is None:
        raise ContractWatcherCycleError(
            "QCC_DIFFERENTIAL_CHANGE_WATCHER_EVIDENCE_MISSING"
        )

    classification = classify_differential_change_categories(full_evidence)

    return {
        "result": classification["result"],
        "twin_key": twin_key,
        "state_key": state_key,
        "contract_key": contract_key,
        "baseline_capture_id": baseline_capture_id,
        "observation_capture_id": last_capture_id,
        "evidence_id": receipt["evidence_id"],
        "watch_state": receipt["watch_state"],
        "severity": receipt["severity"],
        "lifecycle_state": receipt["lifecycle_state"],
        "cycle_outcome": receipt["outcome"],
        "categories": classification["categories"],
        "category_evidence": classification["category_evidence"],
    }
