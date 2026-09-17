"""QCC Contract Watcher — governed historical confirmation policy (1B).

This module is deliberately storage-free and does not reimplement the
pairwise diff engine in ``contract_watcher.py``. It adds only the two
missing pieces needed to turn a single pairwise comparison into a
trustworthy multi-observation confirmation decision:

``ContractWatcherConfirmationPolicy``
    An explicit, immutable, inspectable governance value: how many
    consecutive comparable observations of the *same* semantic change
    are required before ``CHANGE_CONFIRMED`` may be emitted. There is no
    hidden default: callers must state the threshold explicitly, so a
    later reviewer can always see exactly which policy produced a given
    lifecycle decision (it is persisted alongside the decision by
    ``contract_watcher_history_store``).

``compute_semantic_change_signature``
    A deterministic identity for "the meaningful comparison result" of
    one ``build_contract_watcher_evidence`` record, stable across
    incidental ``created_at`` timestamps, ``evidence_id`` and opaque
    ``before_reference``/``after_reference`` capture pointers, but
    sensitive to any actual change in the structural comparison
    (severity, watch_state, elements, catalog_diff, fingerprints, ...).

``apply_confirmation_step``
    The pure, single-step confirmation algorithm:

    - NO_CHANGE resolves/breaks any pending confirmation streak and is
      always reported as NO_CHANGE for that step.
    - VALIDATION_REQUIRED represents an untrusted/inconclusive
      observation and therefore breaks trust continuity: it resets any
      pending streak (never increments, never confirms, never lets an
      observation before the gap count as consecutive with one after
      it) and is always reported as VALIDATION_REQUIRED for that step.
    - CHANGE_SUSPECTED with the same semantic signature as the current
      streak increments it; a different signature starts a new streak
      at 1. Reaching the configured threshold is the *only* way
      CHANGE_CONFIRMED may be emitted. Structural severity is never
      consulted here and can therefore never shorten or bypass the
      threshold. Because the minimum configurable threshold is 2, the
      first valid comparable changed observation of a given semantic
      signature can never by itself produce CHANGE_CONFIRMED — it is
      always reported as CHANGE_SUSPECTED.

``CHANGE_CONFIRMED`` is the only lifecycle state this module may
produce beyond the three raw pairwise states. ``REBUILD_REQUIRED``
remains an explicit downstream policy decision outside this Work
Order's scope and is never emitted here, even for a BREAKING confirmed
change.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .contract_watcher import ContractWatchState, validate_contract_watcher_evidence


CONTRACT_WATCHER_CONFIRMATION_POLICY_SCHEMA_VERSION = 1

CONTRACT_WATCHER_CONFIRMATION_POLICY_TYPE = (
    "QCC_CONTRACT_WATCHER_CONFIRMATION_POLICY"
)

CONTRACT_WATCHER_SEMANTIC_SIGNATURE_PREFIX = "cwsig-"

# Fields deliberately excluded from the semantic change signature because
# they are incidental to the comparison result itself: opaque identifiers,
# capture references and timestamps must never make the same structural
# change look different, nor make a different change look the same.
_SEMANTIC_SIGNATURE_EXCLUDED_KEYS = frozenset({
    "schema_version",
    "evidence_type",
    "contract_key",
    "before_reference",
    "after_reference",
    "evidence_id",
    "created_at",
})

# The only watch_state values a single pairwise comparison
# (compare_site_contract_revision / build_contract_watcher_evidence) may
# ever produce. CHANGE_CONFIRMED and REBUILD_REQUIRED are lifecycle-only
# outcomes and are never valid *input* to the historical layer.
RAW_OBSERVATION_WATCH_STATES = frozenset({
    ContractWatchState.NO_CHANGE.value,
    ContractWatchState.CHANGE_SUSPECTED.value,
    ContractWatchState.VALIDATION_REQUIRED.value,
})


@dataclass(frozen=True)
class ContractWatcherConfirmationPolicy:
    """Explicit, immutable confirmation governance.

    ``required_consecutive_observations`` must be supplied explicitly by
    the caller (no hidden repository-wide default): it is the number of
    consecutive CHANGE_SUSPECTED observations carrying the *same*
    semantic change signature required before CHANGE_CONFIRMED may be
    emitted. This is an evidence-based confirmation layer: a single
    observation is architecturally never sufficient evidence of a
    confirmed change, regardless of severity, so a threshold below 2 is
    rejected. The first valid comparable changed observation of a given
    semantic signature always yields CHANGE_SUSPECTED.
    """

    required_consecutive_observations: int

    schema_version: int = CONTRACT_WATCHER_CONFIRMATION_POLICY_SCHEMA_VERSION

    def __post_init__(self):
        value = self.required_consecutive_observations

        if isinstance(value, bool) or not isinstance(value, int) or value < 2:
            raise ValueError(
                "QCC_CONTRACT_WATCHER_CONFIRMATION_POLICY_THRESHOLD_INVALID"
            )

    def to_dict(self):
        return {
            "schema_version": self.schema_version,
            "policy_type": CONTRACT_WATCHER_CONFIRMATION_POLICY_TYPE,
            "required_consecutive_observations": (
                self.required_consecutive_observations
            ),
        }


def confirmation_policy_from_dict(payload):
    """Rebuilds a policy from its persisted ``to_dict()`` representation."""

    if not isinstance(payload, dict):
        raise TypeError("QCC_CONTRACT_WATCHER_CONFIRMATION_POLICY_INVALID")

    if (
        payload.get("policy_type")
        != CONTRACT_WATCHER_CONFIRMATION_POLICY_TYPE
    ):
        raise ValueError(
            "QCC_CONTRACT_WATCHER_CONFIRMATION_POLICY_TYPE_INVALID"
        )

    return ContractWatcherConfirmationPolicy(
        required_consecutive_observations=payload.get(
            "required_consecutive_observations"
        ),
    )


@dataclass(frozen=True)
class ContractWatcherConfirmationState:
    """Minimal accumulated state needed to continue a confirmation streak."""

    streak_signature: str | None = None
    streak_count: int = 0

    def to_dict(self):
        return {
            "streak_signature": self.streak_signature,
            "streak_count": self.streak_count,
        }


INITIAL_CONFIRMATION_STATE = ContractWatcherConfirmationState()


def compute_semantic_change_signature(evidence):
    """Deterministic identity of the meaningful comparison result.

    Requires ``evidence`` to be valid, persisted-shape Contract Watcher
    evidence (fails closed via ``validate_contract_watcher_evidence`` on
    anything malformed, tampered or unsupported); never accepts raw
    HTML/screenshots/browser state, only the already-canonical evidence
    record produced by ``build_contract_watcher_evidence``.
    """

    canonical = validate_contract_watcher_evidence(evidence)

    payload = {
        key: value
        for key, value in canonical.items()
        if key not in _SEMANTIC_SIGNATURE_EXCLUDED_KEYS
    }

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    digest = hashlib.sha256(
        b"QCC_CONTRACT_WATCHER_SEMANTIC_SIGNATURE_V1\0" + encoded
    ).hexdigest()

    return CONTRACT_WATCHER_SEMANTIC_SIGNATURE_PREFIX + digest[:24]


def apply_confirmation_step(*, state, watch_state, semantic_signature, policy):
    """Applies exactly one observation to an accumulated confirmation state.

    Returns ``(next_state, lifecycle_state)``. Pure and storage-free: the
    same inputs always produce the same outputs, which is what makes
    durable-history replay (and therefore restart-safe reconstruction)
    possible.
    """

    if not isinstance(state, ContractWatcherConfirmationState):
        raise TypeError("QCC_CONTRACT_WATCHER_CONFIRMATION_STATE_INVALID")

    if not isinstance(policy, ContractWatcherConfirmationPolicy):
        raise TypeError("QCC_CONTRACT_WATCHER_CONFIRMATION_POLICY_REQUIRED")

    if watch_state not in RAW_OBSERVATION_WATCH_STATES:
        raise ValueError(
            "QCC_CONTRACT_WATCHER_CONFIRMATION_WATCH_STATE_UNSUPPORTED"
        )

    if watch_state == ContractWatchState.NO_CHANGE.value:
        return ContractWatcherConfirmationState(), ContractWatchState.NO_CHANGE.value

    if watch_state == ContractWatchState.VALIDATION_REQUIRED.value:
        # Fails closed: an untrusted/inconclusive observation breaks
        # trust continuity, so any pending streak is reset instead of
        # preserved. This prevents a valid observation before the gap
        # and a valid observation after it from ever being counted as
        # consecutive with each other.
        return (
            ContractWatcherConfirmationState(),
            ContractWatchState.VALIDATION_REQUIRED.value,
        )

    # watch_state == CHANGE_SUSPECTED.
    if not semantic_signature:
        raise ValueError(
            "QCC_CONTRACT_WATCHER_CONFIRMATION_SEMANTIC_SIGNATURE_REQUIRED"
        )

    if state.streak_signature == semantic_signature and state.streak_count > 0:
        next_count = state.streak_count + 1
    else:
        next_count = 1

    next_state = ContractWatcherConfirmationState(
        streak_signature=semantic_signature,
        streak_count=next_count,
    )

    if next_count >= policy.required_consecutive_observations:
        lifecycle_state = ContractWatchState.CHANGE_CONFIRMED.value
    else:
        lifecycle_state = ContractWatchState.CHANGE_SUSPECTED.value

    return next_state, lifecycle_state
