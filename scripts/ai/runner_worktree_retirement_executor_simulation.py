"""FCP-4F-01: simulated retirement executor kernel (SIMULATION ONLY, NOT LIVE).

Models ONE attempt to retire ONE synthetic worktree checkout as an explicit,
ordered state machine, driven against an in-memory simulation port. Nothing
here retires anything: no `git worktree remove`, prune or branch deletion,
no file or directory removal, no process, no network, no key, no lease or
queue lock of the Runner and no ledger write exists in this module. A
"simulated effect" is ONE in-memory event appended by the in-memory port to
its own list. `RETIREMENT_AUTHORIZATION_LIVE` and
`RETIREMENT_EXECUTION_CAPABLE` are constant False and `SIMULATION_ONLY` is
constant True. Every outcome carries `authorizes_action=False`,
`deletion_authorized=False`, `branch_deletion_authorized=False`,
`issued=False`, `consumed=False`, `host_identity_authenticated=False`,
`queue_scope_attested=False` and `human_approval_present=False` as
REAL-WORLD claims (fixed, not constructor arguments). Simulated progress is
reported only in distinctly named `simulated_*` fields.

Inputs (all synthetic, all untrusted)
-------------------------------------
* `SyntheticRetirementTarget`: a target whose worktree and queue labels live
  in the `sim://fcp4f01/` namespace. A filesystem path (absolute, drive,
  UNC or relative) is refused, and so is a real FCP-4E-02a
  `RetirementTargetIdentity`: the simulator never operates on a real
  checkout path.
* `SimulatedHumanDecisionFixture`: an in-memory stand-in for a future human
  decision. Its seal is a SHA-256 digest (integrity of the fixture only,
  never a signature or authentication); it is NOT a human approval and NOT a
  permit. A 4D `CANDIDATE_FOR_HUMAN_REVIEW` assessment or report, a 02a
  proposal, a 02b command or verification and a 4E-02d
  `DRY_RUN_EVIDENCE_CONSISTENT` composition are refused in its place with
  their own stable codes: informational evidence never becomes authority.
* `clock`: the caller's callable returning an exact UTC datetime, read at
  every gate; a value behind a previous read is SIM_CLOCK_REGRESSION.
* `port`: exactly an `InMemoryRetirementSimulationPort` (its exact type, not
  a subclass or a look-alike). Faults are injected through its frozen
  `SimulationFaults`, never through a callable hook.

Ordered gates and states (`STATES`, `TRANSITIONS`)
-------------------------------------------------
CREATED -> CHECKED (1: marker and synthetic target, 2: decision fixture and
its in-memory acknowledgement) -> LEASE_SIMULATED (3: exclusive simulated
lease) -> FRESH_REVALIDATED_SIMULATED (4: fresh simulated inventory, equal
worktree label, branch, head and base SHA, host label and queue
attestations, decision re-acknowledged, lease still valid) ->
CONSUMED_SIMULATED (5: single use consumed BEFORE the effect) ->
EFFECT_SIMULATED (6: ONE simulated effect call) -> POSTCHECK_SIMULATED (7:
postcondition read) -> COMPLETED_SIMULATED (8). Any failure before the
effect ends REFUSED_SIMULATED and no later gate runs. Once the effect call
has started, anything but a confirmed effect and a matching postcondition
ends UNCERTAIN_SIMULATED: never a second effect call, never a retry. The
lease is released on every path where it was obtained. Missing, malformed
or contradictory evidence is never success.

What a simulation cannot prove (`SIMULATION_UNPROVEN`)
-----------------------------------------------------
Fixture acknowledgements, host labels, queue attestations, leases and the
consumption record are in-memory fixtures: they model the ORDER and the
fail-closed semantics only. Real human authentication, host identity, queue
scope, a durable single-use ledger, OS-level leases, Git worktree removal
semantics, crash recovery, cross-process concurrency and a trusted clock
remain UNPROVEN, and human retirement policy D-1..D-12 is pending. The
exact-type port check prevents accidentally passing another adapter through
the public entry point; it is not a security sandbox against code that
patches this module. `execute_live` refuses at once, before reading any
argument, the host or the filesystem.
"""

from __future__ import annotations

import dataclasses
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Protocol

try:
    from scripts.ai import claude_runner
    from scripts.ai import runner_worktree_retirement as wr
    from scripts.ai import runner_worktree_retirement_authorization as wra
    from scripts.ai import runner_worktree_retirement_host_authority as rha
    from scripts.ai import runner_worktree_retirement_host_composition as rcm
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import claude_runner  # type: ignore[no-redef]
    import runner_worktree_retirement as wr  # type: ignore[no-redef]
    import runner_worktree_retirement_authorization as wra  # type: ignore[no-redef]
    import runner_worktree_retirement_host_authority as rha  # type: ignore[no-redef]
    import runner_worktree_retirement_host_composition as rcm  # type: ignore[no-redef]


RETIREMENT_AUTHORIZATION_LIVE = False
RETIREMENT_EXECUTION_CAPABLE = False
SIMULATION_ONLY = True

SIMULATION_MARKER = "FCP4F01_SIMULATION_ONLY_NOT_A_PERMIT"
PORT_KIND_IN_MEMORY_SIMULATION = "FCP4F01_IN_MEMORY_RETIREMENT_SIMULATION"
SYNTHETIC_LABEL_PREFIX = "sim://fcp4f01/"
ACTION_SIMULATE_RETIRE_ONE_CHECKOUT = "SIMULATE_RETIRE_ONE_WORKTREE_CHECKOUT"
NOT_LIVE = "NOT_LIVE"

TARGET_SCHEMA = "fcp4f01-synthetic-retirement-target-v1"
REQUEST_SCHEMA = "fcp4f01-simulated-retirement-request-v1"
ATTEMPT_SCHEMA = "fcp4f01-simulated-attempt-id-v1"
DECISION_SCHEMA = "fcp4f01-simulated-human-decision-fixture-v1"
DECISION_SEAL_SCHEMA = "fcp4f01-simulated-decision-seal-v1"
ACK_SCHEMA = "fcp4f01-simulated-decision-ack-v1"
LEASE_SCHEMA = "fcp4f01-simulated-lease-v1"
QUEUE_SCHEMA = "fcp4f01-simulated-queue-attestation-v1"
FRESH_SCHEMA = "fcp4f01-simulated-inventory-snapshot-v1"
CONSUMPTION_SCHEMA = "fcp4f01-simulated-consumption-v1"
EFFECT_SCHEMA = "fcp4f01-simulated-effect-report-v1"
POST_SCHEMA = "fcp4f01-simulated-postcondition-v1"
OUTCOME_SCHEMA = "fcp4f01-simulated-retirement-outcome-v1"

MAX_DECISION_TTL_SECONDS = 300
MAX_LEASE_SECONDS = 120
MAX_FRESHNESS_SECONDS = 30
MAX_QUEUE_LABELS = 16
PAUSE_TIMEOUT_SECONDS = 10

# States of one attempt, in their only order.
CREATED = "CREATED"
CHECKED = "CHECKED"
LEASE_SIMULATED = "LEASE_SIMULATED"
FRESH_REVALIDATED_SIMULATED = "FRESH_REVALIDATED_SIMULATED"
CONSUMED_SIMULATED = "CONSUMED_SIMULATED"
EFFECT_SIMULATED = "EFFECT_SIMULATED"
POSTCHECK_SIMULATED = "POSTCHECK_SIMULATED"
COMPLETED_SIMULATED = "COMPLETED_SIMULATED"
REFUSED_SIMULATED = "REFUSED_SIMULATED"
UNCERTAIN_SIMULATED = "UNCERTAIN_SIMULATED"
STATES = (CREATED, CHECKED, LEASE_SIMULATED, FRESH_REVALIDATED_SIMULATED, CONSUMED_SIMULATED, EFFECT_SIMULATED,
          POSTCHECK_SIMULATED, COMPLETED_SIMULATED, REFUSED_SIMULATED, UNCERTAIN_SIMULATED)
TERMINAL_STATES = (COMPLETED_SIMULATED, REFUSED_SIMULATED, UNCERTAIN_SIMULATED)
_START = None
TRANSITIONS = {
    _START: (CREATED,),
    CREATED: (CHECKED, REFUSED_SIMULATED),
    CHECKED: (LEASE_SIMULATED, REFUSED_SIMULATED),
    LEASE_SIMULATED: (FRESH_REVALIDATED_SIMULATED, REFUSED_SIMULATED),
    FRESH_REVALIDATED_SIMULATED: (CONSUMED_SIMULATED, REFUSED_SIMULATED),
    CONSUMED_SIMULATED: (EFFECT_SIMULATED, REFUSED_SIMULATED),
    EFFECT_SIMULATED: (POSTCHECK_SIMULATED, UNCERTAIN_SIMULATED),
    POSTCHECK_SIMULATED: (COMPLETED_SIMULATED, UNCERTAIN_SIMULATED),
}

# Steps of the trace, in the only order they may occur.
STEP_VALIDATE_REQUEST = "VALIDATE_REQUEST"
STEP_CHECK_DECISION = "CHECK_DECISION_FIXTURE"
STEP_ACQUIRE_LEASE = "ACQUIRE_SIMULATED_LEASE"
STEP_FRESH_REVALIDATE = "FRESH_REVALIDATE_SIMULATED"
STEP_RECHECK_DECISION = "RECHECK_DECISION_FIXTURE"
STEP_CONSUME = "CONSUME_SIMULATED_SINGLE_USE"
STEP_EFFECT = "APPLY_SIMULATED_EFFECT"
STEP_POSTCHECK = "READ_SIMULATED_POSTCONDITION"
STEP_RELEASE_LEASE = "RELEASE_SIMULATED_LEASE"
STEP_ORDER = (STEP_VALIDATE_REQUEST, STEP_CHECK_DECISION, STEP_ACQUIRE_LEASE, STEP_FRESH_REVALIDATE,
              STEP_RECHECK_DECISION, STEP_CONSUME, STEP_EFFECT, STEP_POSTCHECK, STEP_RELEASE_LEASE)
STEP_OK = "OK"
# Fault point of the in-memory port: the effect is recorded, then the call fails.
FAULT_AFTER_EFFECT = "AFTER_SIMULATED_EFFECT"
FAULT_POINTS = STEP_ORDER[1:] + (FAULT_AFTER_EFFECT,)

# Port answer vocabularies.
ACK_ACCEPTED = "FIXTURE_ACKNOWLEDGED_SIMULATED"
ACK_UNKNOWN = "FIXTURE_UNKNOWN"
ACK_REVOKED = "FIXTURE_REVOKED"
ACK_ALREADY_CONSUMED = "FIXTURE_ALREADY_CONSUMED"
ACK_STATUSES = (ACK_ACCEPTED, ACK_UNKNOWN, ACK_REVOKED, ACK_ALREADY_CONSUMED)
CONSUMPTION_RECORDED = "CONSUMED_SIMULATED"
CONSUMPTION_REPLAY = "ALREADY_CONSUMED_SIMULATED"
CONSUMPTION_STATUSES = (CONSUMPTION_RECORDED, CONSUMPTION_REPLAY)
EFFECT_RECORDED = "EFFECT_RECORDED_SIMULATED"
EFFECT_REFUSED = "EFFECT_REFUSED_SIMULATED"
EFFECT_UNKNOWN = "EFFECT_OUTCOME_UNKNOWN"
EFFECT_STATUSES = (EFFECT_RECORDED, EFFECT_REFUSED, EFFECT_UNKNOWN)

# Reason codes: request and target (gate 1).
SIM_REQUEST_MALFORMED = "SIM_REQUEST_MALFORMED"
SIM_MARKER_MISSING = "SIM_MARKER_MISSING"
SIM_REQUEST_TAMPERED = "SIM_REQUEST_TAMPERED"
SIM_TARGET_MALFORMED = "SIM_TARGET_MALFORMED"
SIM_TARGET_REAL_IDENTITY_REFUSED = "SIM_TARGET_REAL_IDENTITY_REFUSED"
SIM_TARGET_NOT_SYNTHETIC = "SIM_TARGET_NOT_SYNTHETIC"
SIM_TARGET_DIGEST_MISMATCH = "SIM_TARGET_DIGEST_MISMATCH"
SIM_TARGET_PROTECTED_BRANCH = "SIM_TARGET_PROTECTED_BRANCH"
SIM_TARGET_SHA_INVALID = "SIM_TARGET_SHA_INVALID"
SIM_PORT_NOT_IN_MEMORY_SIMULATION = "SIM_PORT_NOT_IN_MEMORY_SIMULATION"
SIM_CLOCK_INVALID = "SIM_CLOCK_INVALID"
SIM_CLOCK_REGRESSION = "SIM_CLOCK_REGRESSION"
# Decision fixture (gate 2).
SIM_DECISION_ABSENT = "SIM_DECISION_ABSENT"
SIM_DECISION_NOT_SIMULATION_FIXTURE = "SIM_DECISION_NOT_SIMULATION_FIXTURE"
SIM_4D_ASSESSMENT_NOT_AUTHORITY = "SIM_4D_ASSESSMENT_NOT_AUTHORITY"
SIM_4E_PROPOSAL_NOT_AUTHORITY = "SIM_4E_PROPOSAL_NOT_AUTHORITY"
SIM_4E_VERIFICATION_NOT_AUTHORITY = "SIM_4E_VERIFICATION_NOT_AUTHORITY"
SIM_4E_DRY_RUN_EVIDENCE_NOT_AUTHORITY = "SIM_4E_DRY_RUN_EVIDENCE_NOT_AUTHORITY"
SIM_DECISION_MALFORMED = "SIM_DECISION_MALFORMED"
SIM_DECISION_FORGED_CLAIM = "SIM_DECISION_FORGED_CLAIM"
SIM_DECISION_UNSEALED = "SIM_DECISION_UNSEALED"
SIM_DECISION_BINDING_MISMATCH = "SIM_DECISION_BINDING_MISMATCH"
SIM_DECISION_TIMESTAMP_INVALID = "SIM_DECISION_TIMESTAMP_INVALID"
SIM_DECISION_TTL_TOO_LONG = "SIM_DECISION_TTL_TOO_LONG"
SIM_DECISION_NOT_YET_VALID = "SIM_DECISION_NOT_YET_VALID"
SIM_DECISION_EXPIRED = "SIM_DECISION_EXPIRED"
SIM_DECISION_NOT_ACKNOWLEDGED = "SIM_DECISION_NOT_ACKNOWLEDGED"
SIM_DECISION_REVOKED = "SIM_DECISION_REVOKED"
SIM_DECISION_ALREADY_CONSUMED = "SIM_DECISION_ALREADY_CONSUMED"
SIM_DECISION_ACK_MALFORMED = "SIM_DECISION_ACK_MALFORMED"
# Lease (gate 3).
SIM_LEASE_UNAVAILABLE = "SIM_LEASE_UNAVAILABLE"
SIM_LEASE_INVALID = "SIM_LEASE_INVALID"
SIM_LEASE_EXPIRED = "SIM_LEASE_EXPIRED"
SIM_LEASE_RELEASE_FAILED = "SIM_LEASE_RELEASE_FAILED"
# Fresh revalidation (gate 4).
SIM_FRESH_MALFORMED = "SIM_FRESH_MALFORMED"
SIM_FRESH_BINDING_MISMATCH = "SIM_FRESH_BINDING_MISMATCH"
SIM_FRESH_STALE = "SIM_FRESH_STALE"
SIM_FRESH_FROM_FUTURE = "SIM_FRESH_FROM_FUTURE"
SIM_FRESH_WORKTREE_MISMATCH = "SIM_FRESH_WORKTREE_MISMATCH"
SIM_FRESH_BRANCH_MISMATCH = "SIM_FRESH_BRANCH_MISMATCH"
SIM_FRESH_HEAD_SHA_MISMATCH = "SIM_FRESH_HEAD_SHA_MISMATCH"
SIM_FRESH_BASE_MISMATCH = "SIM_FRESH_BASE_MISMATCH"
SIM_FRESH_BASE_SHA_MISMATCH = "SIM_FRESH_BASE_SHA_MISMATCH"
SIM_FRESH_TARGET_NOT_REGISTERED = "SIM_FRESH_TARGET_NOT_REGISTERED"
SIM_FRESH_TARGET_DIRTY = "SIM_FRESH_TARGET_DIRTY"
SIM_FRESH_TARGET_LOCKED = "SIM_FRESH_TARGET_LOCKED"
SIM_HOST_IDENTITY_ABSENT = "SIM_HOST_IDENTITY_ABSENT"
SIM_HOST_IDENTITY_MISMATCH = "SIM_HOST_IDENTITY_MISMATCH"
SIM_HOST_IDENTITY_NOT_ATTESTED_SIMULATED = "SIM_HOST_IDENTITY_NOT_ATTESTED_SIMULATED"
SIM_QUEUE_ATTESTATION_ABSENT = "SIM_QUEUE_ATTESTATION_ABSENT"
SIM_QUEUE_ATTESTATION_MALFORMED = "SIM_QUEUE_ATTESTATION_MALFORMED"
SIM_QUEUE_ATTESTATION_INCOMPLETE = "SIM_QUEUE_ATTESTATION_INCOMPLETE"
SIM_QUEUE_NOT_EMPTY = "SIM_QUEUE_NOT_EMPTY"
# Single use (gate 5).
SIM_CONSUMPTION_FAILED = "SIM_CONSUMPTION_FAILED"
SIM_REPLAY_DETECTED = "SIM_REPLAY_DETECTED"
# Effect and postcondition (gates 6-7).
SIM_EFFECT_OUTCOME_UNKNOWN = "SIM_EFFECT_OUTCOME_UNKNOWN"
SIM_EFFECT_REFUSED_BY_PORT = "SIM_EFFECT_REFUSED_BY_PORT"
SIM_POSTCHECK_UNREAD = "SIM_POSTCHECK_UNREAD"
SIM_POSTCHECK_MISMATCH = "SIM_POSTCHECK_MISMATCH"
SIM_NO_RETRY_AFTER_UNCERTAINTY = "SIM_NO_RETRY_AFTER_UNCERTAINTY"
SIM_COMPLETED_SIMULATED_ONLY = "SIM_COMPLETED_SIMULATED_ONLY"
# Ports and internals.
SIM_PORT_FAILED = "SIM_PORT_FAILED"
SIM_INTERNAL_ERROR = "SIM_INTERNAL_ERROR"
# Always present.
SIM_SIMULATION_ONLY_NOT_A_RETIREMENT = "SIM_SIMULATION_ONLY_NOT_A_RETIREMENT"
SIM_NO_REAL_AUTHORIZATION = "SIM_NO_REAL_AUTHORIZATION"
SIM_LIVE_EXECUTION_BLOCKED = "SIM_LIVE_EXECUTION_BLOCKED"
ALWAYS_CODES = (SIM_SIMULATION_ONLY_NOT_A_RETIREMENT, SIM_NO_REAL_AUTHORIZATION, SIM_LIVE_EXECUTION_BLOCKED)

REASON_CODES = (
    SIM_REQUEST_MALFORMED, SIM_MARKER_MISSING, SIM_REQUEST_TAMPERED, SIM_TARGET_MALFORMED,
    SIM_TARGET_REAL_IDENTITY_REFUSED, SIM_TARGET_NOT_SYNTHETIC, SIM_TARGET_DIGEST_MISMATCH,
    SIM_TARGET_PROTECTED_BRANCH, SIM_TARGET_SHA_INVALID, SIM_PORT_NOT_IN_MEMORY_SIMULATION, SIM_CLOCK_INVALID,
    SIM_CLOCK_REGRESSION, SIM_DECISION_ABSENT, SIM_DECISION_NOT_SIMULATION_FIXTURE, SIM_4D_ASSESSMENT_NOT_AUTHORITY,
    SIM_4E_PROPOSAL_NOT_AUTHORITY, SIM_4E_VERIFICATION_NOT_AUTHORITY, SIM_4E_DRY_RUN_EVIDENCE_NOT_AUTHORITY,
    SIM_DECISION_MALFORMED, SIM_DECISION_FORGED_CLAIM, SIM_DECISION_UNSEALED, SIM_DECISION_BINDING_MISMATCH,
    SIM_DECISION_TIMESTAMP_INVALID, SIM_DECISION_TTL_TOO_LONG, SIM_DECISION_NOT_YET_VALID, SIM_DECISION_EXPIRED,
    SIM_DECISION_NOT_ACKNOWLEDGED, SIM_DECISION_REVOKED, SIM_DECISION_ALREADY_CONSUMED, SIM_DECISION_ACK_MALFORMED,
    SIM_LEASE_UNAVAILABLE, SIM_LEASE_INVALID, SIM_LEASE_EXPIRED, SIM_LEASE_RELEASE_FAILED, SIM_FRESH_MALFORMED,
    SIM_FRESH_BINDING_MISMATCH, SIM_FRESH_STALE, SIM_FRESH_FROM_FUTURE, SIM_FRESH_WORKTREE_MISMATCH,
    SIM_FRESH_BRANCH_MISMATCH, SIM_FRESH_HEAD_SHA_MISMATCH, SIM_FRESH_BASE_MISMATCH, SIM_FRESH_BASE_SHA_MISMATCH,
    SIM_FRESH_TARGET_NOT_REGISTERED, SIM_FRESH_TARGET_DIRTY, SIM_FRESH_TARGET_LOCKED, SIM_HOST_IDENTITY_ABSENT,
    SIM_HOST_IDENTITY_MISMATCH, SIM_HOST_IDENTITY_NOT_ATTESTED_SIMULATED, SIM_QUEUE_ATTESTATION_ABSENT,
    SIM_QUEUE_ATTESTATION_MALFORMED, SIM_QUEUE_ATTESTATION_INCOMPLETE, SIM_QUEUE_NOT_EMPTY, SIM_CONSUMPTION_FAILED,
    SIM_REPLAY_DETECTED, SIM_EFFECT_OUTCOME_UNKNOWN, SIM_EFFECT_REFUSED_BY_PORT, SIM_POSTCHECK_UNREAD,
    SIM_POSTCHECK_MISMATCH, SIM_NO_RETRY_AFTER_UNCERTAINTY, SIM_COMPLETED_SIMULATED_ONLY, SIM_PORT_FAILED,
    SIM_INTERNAL_ERROR,
) + ALWAYS_CODES

# What no simulation can establish; carried by every outcome.
SIMULATION_UNPROVEN = (
    "REAL_HUMAN_AUTHENTICATION_UNPROVEN",
    "HUMAN_RETIREMENT_POLICY_D1_D12_PENDING",
    "REAL_HOST_IDENTITY_UNPROVEN",
    "REAL_QUEUE_SCOPE_UNPROVEN",
    "REAL_DURABLE_SINGLE_USE_LEDGER_UNPROVEN",
    "REAL_OS_LEASE_UNPROVEN",
    "REAL_GIT_WORKTREE_REMOVAL_SEMANTICS_UNPROVEN",
    "CRASH_RECOVERY_UNPROVEN",
    "CROSS_PROCESS_CONCURRENCY_UNPROVEN",
    "TRUSTED_CLOCK_UNPROVEN",
    "FIXTURE_SEAL_IS_NOT_A_SIGNATURE",
    "PORT_TYPE_CHECK_IS_NOT_A_SANDBOX",
    "LIVE_ACTIVATION_BLOCKED",
)
LIVE_ACTIVATION_BLOCKER = "FCP4F01_SIMULATION_ONLY_PERMANENT"

_HEADS = "refs/heads/"
_FAILED = object()   # sentinel: a port raised; no detail is kept


class RetirementSimulationNotLive(RuntimeError):
    """Raised by `execute_live`, always. Carries only the stable code."""

    def __init__(self):
        super().__init__(NOT_LIVE)
        self.code = NOT_LIVE


# ---------------------------------------------------------------------------
# Inputs (immutable, synthetic)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SyntheticRetirementTarget:
    """ONE synthetic checkout, named only by `sim://fcp4f01/` labels."""

    schema: str
    simulation_marker: str
    target_id: str
    worktree_label: str
    head_ref: str
    head_sha: str
    base_ref: str
    base_sha: str
    object_format: str
    queue_labels: tuple
    identity_digest: str
    is_real_checkout: bool = field(default=False, init=False)


@dataclass(frozen=True)
class SimulatedRetirementRequest:
    """ONE simulated attempt. `attempt_id` is a digest of its identity,
    computed by `build_simulation_request`, never supplied."""

    schema: str
    simulation_marker: str
    action: str
    target: SyntheticRetirementTarget
    host_label: str
    attempt_id: str
    authorizes_action: bool = field(default=False, init=False)


@dataclass(frozen=True)
class SimulatedHumanDecisionFixture:
    """In-memory stand-in for a future human decision. NOT a human approval,
    NOT a permit, NOT authenticated: the seal is a digest, not a signature."""

    schema: str
    simulation_marker: str
    fixture_id: str
    attempt_id: str
    target_digest: str
    action: str
    head_sha: str
    base_sha: str
    issued_at: str
    expires_at: str
    fixture_seal: str
    is_human_approval: bool = field(default=False, init=False)
    is_real_permit: bool = field(default=False, init=False)
    authenticated: bool = field(default=False, init=False)
    authorizes_action: bool = field(default=False, init=False)
    deletion_authorized: bool = field(default=False, init=False)


_DECISION_FLAGS = (("is_human_approval", False), ("is_real_permit", False), ("authenticated", False),
                   ("authorizes_action", False), ("deletion_authorized", False))


# ---------------------------------------------------------------------------
# Port answers (immutable, produced by the in-memory port; still checked)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimulatedDecisionAck:
    status: str
    attempt_id: str
    fixture_id: str
    schema: str = ACK_SCHEMA


@dataclass(frozen=True)
class SimulatedLease:
    lease_id: str
    attempt_id: str
    resource: str
    acquired_at: str
    expires_at: str
    schema: str = LEASE_SCHEMA


@dataclass(frozen=True)
class SimulatedQueueAttestation:
    """A fixture's statement about ONE synthetic queue. Not a real attestation."""

    queue_label: str
    pending_items: int
    attested_simulated: bool
    schema: str = QUEUE_SCHEMA


@dataclass(frozen=True)
class SimulatedInventorySnapshot:
    attempt_id: str
    target_id: str
    observed_at: str
    host_label: Optional[str]
    host_identity_attested_simulated: bool
    worktree_label: str
    registered: bool
    clean: bool
    locked: bool
    head_ref: str
    head_sha: str
    base_ref: str
    base_sha: str
    queue_attestations: tuple
    queue_attestations_complete_simulated: bool
    other_worktrees_digest: str
    schema: str = FRESH_SCHEMA


@dataclass(frozen=True)
class SimulatedConsumption:
    status: str
    consumption_id: str
    attempt_id: str
    fixture_id: str
    schema: str = CONSUMPTION_SCHEMA


@dataclass(frozen=True)
class SimulatedEffectReport:
    status: str
    effect_id: Optional[str]
    attempt_id: str
    target_id: str
    schema: str = EFFECT_SCHEMA


@dataclass(frozen=True)
class SimulatedPostcondition:
    attempt_id: str
    target_id: str
    worktree_label: str
    registered: bool
    branch_ref_present: bool
    branch_head_sha: str
    other_worktrees_digest: str
    effect_events_for_target: int
    schema: str = POST_SCHEMA


@dataclass(frozen=True)
class SimulatedEffectEvent:
    """The ONLY thing a simulated effect produces: this in-memory record."""

    effect_id: str
    attempt_id: str
    target_id: str
    worktree_label: str
    consumption_id: str
    lease_id: str


@dataclass(frozen=True)
class SimulatedWorktree:
    """One entry of the in-memory port's synthetic registry."""

    target_id: str
    worktree_label: str
    head_ref: str
    head_sha: str
    base_ref: str
    base_sha: str
    registered: bool = True
    clean: bool = True
    locked: bool = False


@dataclass(frozen=True)
class SimulationFaults:
    """Declarative faults for the in-memory port. `raise_at` names steps of
    STEP_ORDER (or FAULT_AFTER_EFFECT) at which the port raises; `*_overrides`
    are (field, value) pairs applied to the port's answers. `pause_after_lease`
    is (granted, resume) threading.Event objects for deterministic races."""

    raise_at: tuple = ()
    lease_unavailable: bool = False
    lease_ttl_seconds: int = 60
    observation_age_seconds: int = 0
    revoke_on_recheck: bool = False
    effect_status: str = EFFECT_RECORDED
    fresh_overrides: tuple = ()
    post_overrides: tuple = ()
    pause_after_lease: Optional[tuple] = None


# ---------------------------------------------------------------------------
# Port contract and its ONLY accepted implementation (in memory)
# ---------------------------------------------------------------------------

class SimulatedRetirementPort(Protocol):
    """Typed contract of the simulated host. Every method answers with a
    frozen value or raises; no method may touch the OS, Git or a host."""

    port_kind: str

    def acknowledge_decision_fixture(self, attempt_id: str, fixture_id: str) -> SimulatedDecisionAck: ...

    def recheck_decision_fixture(self, attempt_id: str, fixture_id: str) -> SimulatedDecisionAck: ...

    def acquire_simulated_lease(self, attempt_id: str, resource: str) -> Optional[SimulatedLease]: ...

    def release_simulated_lease(self, lease_id: str) -> None: ...

    def read_simulated_inventory(self, attempt_id: str, target_id: str) -> SimulatedInventorySnapshot: ...

    def consume_simulated_single_use(self, attempt_id: str, fixture_id: str) -> SimulatedConsumption: ...

    def apply_simulated_effect(self, attempt_id: str, target_id: str, consumption_id: str,
                               lease_id: str) -> SimulatedEffectReport: ...

    def read_simulated_postcondition(self, attempt_id: str, target_id: str) -> SimulatedPostcondition: ...


class InMemoryRetirementSimulationPort:
    """The only port `simulate_retirement` accepts (exact type). All state is
    in this object, guarded by one lock: the registry, leases, acknowledged,
    revoked and consumed fixture ids and the list of simulated effect events.
    It retires nothing: an "effect" flips `registered` in its own registry and
    appends one SimulatedEffectEvent. Not a security sandbox."""

    port_kind = PORT_KIND_IN_MEMORY_SIMULATION

    def __init__(self, worktrees, *, host_label, clock, acknowledged_fixture_ids=(), revoked_fixture_ids=(),
                 queue_attestations=(), queue_attestations_complete=True, host_identity_attested=True,
                 faults=None):
        self._lock = threading.Lock()
        self._world = {w.target_id: w for w in worktrees}
        self._host_label = host_label
        self._clock = clock
        self._acknowledged = frozenset(acknowledged_fixture_ids)
        self._revoked = set(revoked_fixture_ids)
        self._queues = tuple(queue_attestations)
        self._queues_complete = queue_attestations_complete
        self._host_attested = host_identity_attested
        self._faults = SimulationFaults() if faults is None else faults
        self._leases = {}
        self._consumed = {}
        self._effects = []
        self._calls = []
        self._counter = 0

    # Observation helpers for tests and audits (read only).
    def effect_events(self) -> tuple:
        with self._lock:
            return tuple(self._effects)

    def call_log(self) -> tuple:
        with self._lock:
            return tuple(self._calls)

    def consumed_fixture_ids(self) -> tuple:
        with self._lock:
            return tuple(sorted(self._consumed))

    def held_leases(self) -> tuple:
        with self._lock:
            return tuple(sorted(self._leases))

    # Internals.
    def _enter(self, step: str, attempt_id: str) -> None:
        self._calls.append((step, attempt_id))
        if step in self._faults.raise_at:
            raise RuntimeError("simulated port fault")

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return "%s-%d" % (prefix, self._counter)

    def _stamp(self, seconds: int = 0) -> str:
        return (self._clock() + timedelta(seconds=seconds)).strftime(rha._TIMESTAMP_FORMAT)

    def _others_digest(self, target_id: str) -> str:
        others = sorted(dataclasses.astuple(w) for t, w in self._world.items() if t != target_id)
        return wra._digest({"schema": FRESH_SCHEMA, "others": tuple(others)})

    @staticmethod
    def _override(value, pairs):
        return dataclasses.replace(value, **dict(pairs)) if pairs else value

    # The port contract.
    def _ack(self, step, attempt_id, fixture_id):
        with self._lock:
            self._enter(step, attempt_id)
            if step == STEP_RECHECK_DECISION and self._faults.revoke_on_recheck:
                self._revoked.add(fixture_id)
            if fixture_id in self._consumed:
                status = ACK_ALREADY_CONSUMED
            elif fixture_id in self._revoked:
                status = ACK_REVOKED
            elif fixture_id in self._acknowledged:
                status = ACK_ACCEPTED
            else:
                status = ACK_UNKNOWN
            return SimulatedDecisionAck(status, attempt_id, fixture_id)

    def acknowledge_decision_fixture(self, attempt_id, fixture_id):
        return self._ack(STEP_CHECK_DECISION, attempt_id, fixture_id)

    def recheck_decision_fixture(self, attempt_id, fixture_id):
        return self._ack(STEP_RECHECK_DECISION, attempt_id, fixture_id)

    def acquire_simulated_lease(self, attempt_id, resource):
        with self._lock:
            self._enter(STEP_ACQUIRE_LEASE, attempt_id)
            if self._faults.lease_unavailable or any(r == resource for r, _ in self._leases.values()):
                return None
            lease = SimulatedLease(self._next_id("sim-lease"), attempt_id, resource, self._stamp(),
                                   self._stamp(self._faults.lease_ttl_seconds))
            self._leases[lease.lease_id] = (resource, attempt_id)
        pause = self._faults.pause_after_lease
        if pause is not None:
            granted, resume = pause
            granted.set()
            resume.wait(PAUSE_TIMEOUT_SECONDS)
        return lease

    def release_simulated_lease(self, lease_id):
        with self._lock:
            owner = self._leases.get(lease_id, (None, None))[1]
            self._enter(STEP_RELEASE_LEASE, owner)
            self._leases.pop(lease_id, None)

    def read_simulated_inventory(self, attempt_id, target_id):
        with self._lock:
            self._enter(STEP_FRESH_REVALIDATE, attempt_id)
            w = self._world[target_id]
            snapshot = SimulatedInventorySnapshot(
                attempt_id=attempt_id, target_id=target_id,
                observed_at=self._stamp(-self._faults.observation_age_seconds), host_label=self._host_label,
                host_identity_attested_simulated=self._host_attested, worktree_label=w.worktree_label,
                registered=w.registered, clean=w.clean, locked=w.locked, head_ref=w.head_ref, head_sha=w.head_sha,
                base_ref=w.base_ref, base_sha=w.base_sha, queue_attestations=self._queues,
                queue_attestations_complete_simulated=self._queues_complete,
                other_worktrees_digest=self._others_digest(target_id))
            return self._override(snapshot, self._faults.fresh_overrides)

    def consume_simulated_single_use(self, attempt_id, fixture_id):
        with self._lock:
            self._enter(STEP_CONSUME, attempt_id)
            if fixture_id in self._consumed:
                return SimulatedConsumption(CONSUMPTION_REPLAY, self._consumed[fixture_id][0], attempt_id, fixture_id)
            consumption_id = self._next_id("sim-consumption")
            self._consumed[fixture_id] = (consumption_id, attempt_id)
            return SimulatedConsumption(CONSUMPTION_RECORDED, consumption_id, attempt_id, fixture_id)

    def apply_simulated_effect(self, attempt_id, target_id, consumption_id, lease_id):
        with self._lock:
            self._enter(STEP_EFFECT, attempt_id)
            w = self._world.get(target_id)
            consumed = any(c == (consumption_id, attempt_id) for c in self._consumed.values())
            if w is None or not w.registered or not consumed or self._leases.get(lease_id, (None, None))[1] \
                    != attempt_id:
                return SimulatedEffectReport(EFFECT_REFUSED, None, attempt_id, target_id)
            event = SimulatedEffectEvent(self._next_id("sim-effect"), attempt_id, target_id, w.worktree_label,
                                         consumption_id, lease_id)
            self._effects.append(event)
            self._world[target_id] = dataclasses.replace(w, registered=False)
            if FAULT_AFTER_EFFECT in self._faults.raise_at:
                self._calls.append((FAULT_AFTER_EFFECT, attempt_id))
                raise RuntimeError("simulated port fault after the simulated effect")
            effect_id = event.effect_id if self._faults.effect_status == EFFECT_RECORDED else None
            return SimulatedEffectReport(self._faults.effect_status, effect_id, attempt_id, target_id)

    def read_simulated_postcondition(self, attempt_id, target_id):
        with self._lock:
            self._enter(STEP_POSTCHECK, attempt_id)
            w = self._world[target_id]
            post = SimulatedPostcondition(
                attempt_id=attempt_id, target_id=target_id, worktree_label=w.worktree_label,
                registered=w.registered, branch_ref_present=True, branch_head_sha=w.head_sha,
                other_worktrees_digest=self._others_digest(target_id),
                effect_events_for_target=sum(1 for e in self._effects if e.target_id == target_id))
            return self._override(post, self._faults.post_overrides)


# ---------------------------------------------------------------------------
# Outcome (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimulationStep:
    """One traced step: its name and `OK` or a stable reason code."""

    step: str
    result: str


@dataclass(frozen=True)
class SimulatedRetirementOutcome:
    """The result of ONE simulated attempt. Even COMPLETED_SIMULATED is an
    in-memory event: every real-world flag below is fixed False."""

    schema: str
    state: str
    reason_codes: tuple
    state_trace: tuple
    step_trace: tuple
    attempt_id: Optional[str]
    target_id: Optional[str]
    fixture_id: Optional[str]
    lease_id: Optional[str]
    consumption_id: Optional[str]
    effect_id: Optional[str]
    simulated_effect_calls: int
    simulated_decision_checked: bool
    simulated_lease_held: bool
    simulated_fresh_revalidated: bool
    simulated_consumed: bool
    simulated_effect_recorded: bool
    simulated_postcheck_confirmed: bool
    human_reconciliation_required: bool
    fingerprint: str
    unproven: tuple = field(default=SIMULATION_UNPROVEN, init=False)
    live_activation_blocker: str = field(default=LIVE_ACTIVATION_BLOCKER, init=False)
    simulation_only: bool = field(default=True, init=False)
    retirement_authorization_live: bool = field(default=False, init=False)
    retirement_execution_capable: bool = field(default=False, init=False)
    authorizes_action: bool = field(default=False, init=False)
    deletion_authorized: bool = field(default=False, init=False)
    branch_deletion_authorized: bool = field(default=False, init=False)
    issued: bool = field(default=False, init=False)
    consumed: bool = field(default=False, init=False)
    host_identity_authenticated: bool = field(default=False, init=False)
    queue_scope_attested: bool = field(default=False, init=False)
    human_approval_present: bool = field(default=False, init=False)
    retry_allowed: bool = field(default=False, init=False)


_FIXED_OUTCOME_FLAGS = (
    ("simulation_only", True), ("retirement_authorization_live", False), ("retirement_execution_capable", False),
    ("authorizes_action", False), ("deletion_authorized", False), ("branch_deletion_authorized", False),
    ("issued", False), ("consumed", False), ("host_identity_authenticated", False),
    ("queue_scope_attested", False), ("human_approval_present", False), ("retry_allowed", False),
)


# ---------------------------------------------------------------------------
# Pure helpers (digests reuse the 02a canonical JSON digest)
# ---------------------------------------------------------------------------

def _material(obj, skip: str) -> dict:
    out = {}
    for f in dataclasses.fields(obj):
        if f.name == skip:
            continue
        value = getattr(obj, f.name)
        if type(value) is SyntheticRetirementTarget:
            value = value.identity_digest
        elif type(value) is tuple:
            value = tuple(dataclasses.asdict(v) if dataclasses.is_dataclass(v) else v for v in value)
        out[f.name] = value
    return out


def target_digest(target: SyntheticRetirementTarget) -> str:
    return wra._digest({"schema": TARGET_SCHEMA, **_material(target, "identity_digest")})


def _attempt_id(target: SyntheticRetirementTarget, host_label: str) -> str:
    return wra._digest({"schema": ATTEMPT_SCHEMA, "marker": SIMULATION_MARKER,
                        "action": ACTION_SIMULATE_RETIRE_ONE_CHECKOUT, "target": target.identity_digest,
                        "host_label": host_label})


def decision_seal(fixture: SimulatedHumanDecisionFixture) -> str:
    """Integrity digest of a fixture. A digest anyone can compute: never a
    signature, never authentication."""
    return wra._digest({"schema": DECISION_SEAL_SCHEMA, **_material(fixture, "fixture_seal")})


def outcome_fingerprint(outcome: SimulatedRetirementOutcome) -> str:
    """Canonical digest of an outcome (audit and immutability, not authentication)."""
    return wra._digest({"schema": OUTCOME_SCHEMA, **_material(outcome, "fingerprint")})


def is_synthetic_label(value) -> bool:
    """True only for a `sim://fcp4f01/<name>` label: never a filesystem path
    (no drive, separator alias, dot component or absolute form)."""
    if not rha._is_text(value, 256) or not value.startswith(SYNTHETIC_LABEL_PREFIX):
        return False
    rest = value[len(SYNTHETIC_LABEL_PREFIX):]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*", rest):
        return False
    if any(part in (".", "..") for part in rest.split("/")) or "\\" in value:
        return False
    return not os.path.isabs(value) and os.path.splitdrive(value)[0] == ""


def _sha_ok(value, object_format) -> bool:
    pattern = rha._SHA_RE.get(object_format) if type(object_format) is str else None
    return pattern is not None and type(value) is str and pattern.fullmatch(value) is not None


def _branch(ref) -> Optional[str]:
    if type(ref) is not str or not ref.startswith(_HEADS) or not rha._is_text(ref):
        return None
    name = ref[len(_HEADS):]
    return name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", name) and ".." not in name else None


def build_synthetic_target(*, target_id, worktree_label, head_ref, head_sha, base_ref, base_sha,
                           queue_labels, object_format="sha1") -> SyntheticRetirementTarget:
    """A synthetic target with its digest computed. Pure; validation happens
    in `target_errors` (a built target may still be refused)."""
    staged = SyntheticRetirementTarget(
        schema=TARGET_SCHEMA, simulation_marker=SIMULATION_MARKER, target_id=target_id,
        worktree_label=worktree_label, head_ref=head_ref, head_sha=head_sha, base_ref=base_ref, base_sha=base_sha,
        object_format=object_format, queue_labels=tuple(queue_labels), identity_digest="")
    return dataclasses.replace(staged, identity_digest=target_digest(staged))


def build_simulation_request(target, *, host_label) -> SimulatedRetirementRequest:
    """The request for ONE simulated attempt on `target`. Pure; refusals are
    reported by `simulate_retirement`, never raised here."""
    attempt = _attempt_id(target, host_label) if type(target) is SyntheticRetirementTarget else ""
    return SimulatedRetirementRequest(schema=REQUEST_SCHEMA, simulation_marker=SIMULATION_MARKER,
                                      action=ACTION_SIMULATE_RETIRE_ONE_CHECKOUT, target=target,
                                      host_label=host_label, attempt_id=attempt)


def build_decision_fixture(request, *, fixture_id, issued_at, expires_at) -> SimulatedHumanDecisionFixture:
    """A sealed in-memory decision fixture bound to `request`. Simulation
    only: it is not a human approval and carries no permission."""
    t = request.target
    staged = SimulatedHumanDecisionFixture(
        schema=DECISION_SCHEMA, simulation_marker=SIMULATION_MARKER, fixture_id=fixture_id,
        attempt_id=request.attempt_id, target_digest=t.identity_digest, action=request.action,
        head_sha=t.head_sha, base_sha=t.base_sha, issued_at=issued_at, expires_at=expires_at, fixture_seal="")
    return dataclasses.replace(staged, fixture_seal=decision_seal(staged))


def target_errors(target) -> list:
    """Gate 1 (target): stable codes; empty when the target is a well-formed,
    self-consistent synthetic target on an unprotected branch."""
    if type(target) is wra.RetirementTargetIdentity:
        return [SIM_TARGET_REAL_IDENTITY_REFUSED]
    if type(target) is not SyntheticRetirementTarget:
        return [SIM_TARGET_MALFORMED]
    if target.simulation_marker != SIMULATION_MARKER:
        return [SIM_MARKER_MISSING]
    if target.schema != TARGET_SCHEMA or target.is_real_checkout is not False \
            or type(target.target_id) is not str or not rha._LABEL_RE.fullmatch(target.target_id) \
            or type(target.queue_labels) is not tuple:
        return [SIM_TARGET_MALFORMED]
    labels = (target.worktree_label,) + target.queue_labels
    if not all(is_synthetic_label(v) for v in labels):
        return [SIM_TARGET_NOT_SYNTHETIC]
    q = target.queue_labels
    if not 0 < len(q) <= MAX_QUEUE_LABELS or list(q) != sorted(set(q)) or target.worktree_label in q:
        return [SIM_TARGET_MALFORMED]
    errors = []
    branch, base = _branch(target.head_ref), _branch(target.base_ref)
    if branch is None or base is None or branch == base:
        errors.append(SIM_TARGET_MALFORMED)
    elif branch in claude_runner.PROTECTED_BRANCHES:
        errors.append(SIM_TARGET_PROTECTED_BRANCH)
    if not _sha_ok(target.head_sha, target.object_format) or not _sha_ok(target.base_sha, target.object_format):
        errors.append(SIM_TARGET_SHA_INVALID)
    try:
        if target.identity_digest != target_digest(target):
            errors.append(SIM_TARGET_DIGEST_MISMATCH)
    except (TypeError, ValueError):
        errors.append(SIM_TARGET_DIGEST_MISMATCH)
    return errors


def request_errors(request) -> list:
    """Gate 1: the request must carry the marker, a valid synthetic target and
    the attempt id re-derived from them."""
    if type(request) is not SimulatedRetirementRequest:
        return [SIM_REQUEST_MALFORMED]
    if request.simulation_marker != SIMULATION_MARKER:
        return [SIM_MARKER_MISSING]
    if request.schema != REQUEST_SCHEMA or request.action != ACTION_SIMULATE_RETIRE_ONE_CHECKOUT \
            or request.authorizes_action is not False or type(request.host_label) is not str \
            or not rha._LABEL_RE.fullmatch(request.host_label):
        return [SIM_REQUEST_MALFORMED]
    errors = target_errors(request.target)
    if errors:
        return errors
    return [] if request.attempt_id == _attempt_id(request.target, request.host_label) else [SIM_REQUEST_TAMPERED]


def _not_a_fixture_code(decision) -> str:
    """Upstream evidence offered as a decision keeps its own refusal code."""
    kind = type(decision)
    if kind in (wr.WorktreeRetirementAssessment, wr.RetirementReport, wr.RetirementFacts):
        return SIM_4D_ASSESSMENT_NOT_AUTHORITY
    if kind in (wra.RetirementProposal, wra.RetirementTargetIdentity, wra.RetirementScope):
        return SIM_4E_PROPOSAL_NOT_AUTHORITY
    if kind in (rha.RetirementCommandVerification, rha.RetirementCommand, rha.SignedRetirementCommand, bytes):
        return SIM_4E_VERIFICATION_NOT_AUTHORITY
    if kind in (rcm.RetirementEvidenceComposition, rcm.QueueScopeManifestVerification):
        return SIM_4E_DRY_RUN_EVIDENCE_NOT_AUTHORITY
    return SIM_DECISION_NOT_SIMULATION_FIXTURE


def decision_errors(decision, request, now) -> list:
    """Gate 2 (pure part): an exact, sealed, unforged, in-window fixture bound
    to exactly this request. Never more than a simulation fixture."""
    if decision is None:
        return [SIM_DECISION_ABSENT]
    if type(decision) is not SimulatedHumanDecisionFixture:
        return [_not_a_fixture_code(decision)]
    if any(getattr(decision, name) is not value for name, value in _DECISION_FLAGS):
        return [SIM_DECISION_FORGED_CLAIM]
    if decision.simulation_marker != SIMULATION_MARKER:
        return [SIM_MARKER_MISSING]
    if decision.schema != DECISION_SCHEMA or type(decision.fixture_id) is not str \
            or not rha._LABEL_RE.fullmatch(decision.fixture_id):
        return [SIM_DECISION_MALFORMED]
    try:
        sealed = type(decision.fixture_seal) is str and decision.fixture_seal == decision_seal(decision)
    except (TypeError, ValueError):
        sealed = False
    if not sealed:
        return [SIM_DECISION_UNSEALED]
    t = request.target
    errors = []
    if (decision.attempt_id, decision.target_digest, decision.action, decision.head_sha, decision.base_sha) != (
            request.attempt_id, t.identity_digest, request.action, t.head_sha, t.base_sha):
        errors.append(SIM_DECISION_BINDING_MISMATCH)
    problem = _window(decision.issued_at, decision.expires_at, now, MAX_DECISION_TTL_SECONDS)
    if problem:
        errors.append({"timestamp": SIM_DECISION_TIMESTAMP_INVALID, "ttl": SIM_DECISION_TTL_TOO_LONG,
                       "future": SIM_DECISION_NOT_YET_VALID, "expired": SIM_DECISION_EXPIRED}[problem])
    return errors


def _window(start, end, now, max_seconds) -> Optional[str]:
    issued, expires = rha._timestamp(start), rha._timestamp(end)
    if issued is None or expires is None or expires <= issued:
        return "timestamp"
    if expires - issued > timedelta(seconds=max_seconds):
        return "ttl"
    if issued > now:
        return "future"
    return "expired" if now >= expires else None


def _value_ok(value, cls) -> bool:
    if type(value) is not cls or value.schema != dataclasses.fields(cls)[-1].default:
        return False
    for f in dataclasses.fields(value):
        item = getattr(value, f.name)
        if f.type in ("bool",) and type(item) is not bool:
            return False
        if f.type == "int" and type(item) is not int:
            return False
        if f.type == "str" and type(item) is not str:
            return False
        if f.type == "Optional[str]" and item is not None and type(item) is not str:
            return False
        if f.type == "tuple" and type(item) is not tuple:
            return False
    return True


def _ack_errors(ack, request, fixture_id) -> list:
    if not _value_ok(ack, SimulatedDecisionAck) or ack.status not in ACK_STATUSES \
            or (ack.attempt_id, ack.fixture_id) != (request.attempt_id, fixture_id):
        return [SIM_DECISION_ACK_MALFORMED]
    return {ACK_ACCEPTED: [], ACK_UNKNOWN: [SIM_DECISION_NOT_ACKNOWLEDGED], ACK_REVOKED: [SIM_DECISION_REVOKED],
            ACK_ALREADY_CONSUMED: [SIM_DECISION_ALREADY_CONSUMED]}[ack.status]


def _lease_resource(request) -> str:
    return "sim-lease:" + request.target.target_id


def _lease_errors(lease, request, now) -> list:
    if not _value_ok(lease, SimulatedLease) or not rha._LABEL_RE.fullmatch(lease.lease_id) \
            or (lease.attempt_id, lease.resource) != (request.attempt_id, _lease_resource(request)):
        return [SIM_LEASE_INVALID]
    problem = _window(lease.acquired_at, lease.expires_at, now, MAX_LEASE_SECONDS)
    return [] if problem is None else [SIM_LEASE_EXPIRED if problem == "expired" else SIM_LEASE_INVALID]


def fresh_errors(snapshot, request, now) -> list:
    """Gate 4: the fresh simulated inventory must name exactly the target,
    unchanged, registered, clean and unlocked, under the request's host label
    with complete, empty simulated queue attestations, observed recently."""
    if not _value_ok(snapshot, SimulatedInventorySnapshot):
        return [SIM_FRESH_MALFORMED]
    t = request.target
    if (snapshot.attempt_id, snapshot.target_id) != (request.attempt_id, t.target_id):
        return [SIM_FRESH_BINDING_MISMATCH]
    errors = []
    observed = rha._timestamp(snapshot.observed_at)
    if observed is None:
        errors.append(SIM_FRESH_MALFORMED)
    elif observed > now:
        errors.append(SIM_FRESH_FROM_FUTURE)
    elif now - observed > timedelta(seconds=MAX_FRESHNESS_SECONDS):
        errors.append(SIM_FRESH_STALE)
    if snapshot.host_label is None:
        errors.append(SIM_HOST_IDENTITY_ABSENT)
    elif type(snapshot.host_label) is not str or snapshot.host_label != request.host_label:
        errors.append(SIM_HOST_IDENTITY_MISMATCH)
    if snapshot.host_identity_attested_simulated is not True:
        errors.append(SIM_HOST_IDENTITY_NOT_ATTESTED_SIMULATED)
    for name, code in (("worktree_label", SIM_FRESH_WORKTREE_MISMATCH), ("head_ref", SIM_FRESH_BRANCH_MISMATCH),
                       ("head_sha", SIM_FRESH_HEAD_SHA_MISMATCH), ("base_ref", SIM_FRESH_BASE_MISMATCH),
                       ("base_sha", SIM_FRESH_BASE_SHA_MISMATCH)):
        if getattr(snapshot, name) != getattr(t, name):
            errors.append(code)
    if snapshot.registered is not True:
        errors.append(SIM_FRESH_TARGET_NOT_REGISTERED)
    if snapshot.clean is not True:
        errors.append(SIM_FRESH_TARGET_DIRTY)
    if snapshot.locked is not False:
        errors.append(SIM_FRESH_TARGET_LOCKED)
    if not rha._DIGEST_RE.fullmatch(snapshot.other_worktrees_digest):
        errors.append(SIM_FRESH_MALFORMED)
    errors += _queue_errors(snapshot, t)
    return list(dict.fromkeys(errors))


def _queue_errors(snapshot, target) -> list:
    queues = snapshot.queue_attestations
    if not queues:
        return [SIM_QUEUE_ATTESTATION_ABSENT]
    if not all(_value_ok(q, SimulatedQueueAttestation) and is_synthetic_label(q.queue_label)
               and q.pending_items >= 0 for q in queues):
        return [SIM_QUEUE_ATTESTATION_MALFORMED]
    labels = [q.queue_label for q in queues]
    errors = []
    if len(set(labels)) != len(labels) or snapshot.queue_attestations_complete_simulated is not True \
            or not set(target.queue_labels) <= set(labels) or any(q.attested_simulated is not True for q in queues):
        errors.append(SIM_QUEUE_ATTESTATION_INCOMPLETE)
    if any(q.pending_items for q in queues):
        errors.append(SIM_QUEUE_NOT_EMPTY)
    return errors


def _consumption_status(receipt, request, fixture_id) -> Optional[str]:
    if not _value_ok(receipt, SimulatedConsumption) or receipt.status not in CONSUMPTION_STATUSES \
            or not rha._LABEL_RE.fullmatch(receipt.consumption_id) \
            or (receipt.attempt_id, receipt.fixture_id) != (request.attempt_id, fixture_id):
        return None
    return receipt.status


def _effect_status(report, request) -> Optional[str]:
    if not _value_ok(report, SimulatedEffectReport) or report.status not in EFFECT_STATUSES \
            or (report.attempt_id, report.target_id) != (request.attempt_id, request.target.target_id):
        return None
    if report.status == EFFECT_RECORDED:
        return report.status if type(report.effect_id) is str and rha._LABEL_RE.fullmatch(report.effect_id) else None
    return report.status if report.effect_id is None else None


def _postcheck_ok(post, request, others_digest) -> bool:
    t = request.target
    return (_value_ok(post, SimulatedPostcondition)
            and (post.attempt_id, post.target_id, post.worktree_label) == (request.attempt_id, t.target_id,
                                                                          t.worktree_label)
            and post.registered is False and post.branch_ref_present is True and post.branch_head_sha == t.head_sha
            and post.other_worktrees_digest == others_digest and post.effect_events_for_target == 1)


# ---------------------------------------------------------------------------
# The attempt (one request, at most one simulated effect call)
# ---------------------------------------------------------------------------

class _Attempt:
    def __init__(self, request, decision, port, clock):
        self.request, self.decision, self.port, self.clock = request, decision, port, clock
        self.states, self.steps, self.codes = [CREATED], [], []
        self.fixture_id = self.lease_id = self.consumption_id = self.effect_id = None
        self.lease = None
        self.last_now = None
        self.effect_calls = 0
        self.flags = dict(decision=False, lease=False, fresh=False, consumed=False, effect=False, postcheck=False)

    def _step(self, step, result=STEP_OK):
        self.steps.append(SimulationStep(step, result))

    def _port(self, step, call):
        """Calls one port method; any exception becomes _FAILED, without detail."""
        try:
            return call()
        except Exception:  # noqa: BLE001 - no port detail is ever kept
            self._step(step, SIM_PORT_FAILED)
            self.codes.append(SIM_PORT_FAILED)
            return _FAILED

    def _now(self):
        """The caller's clock: exact UTC, plausible, never behind a previous read."""
        try:
            now = rcm._exact_utc(self.clock())
        except Exception:  # noqa: BLE001
            now = None
        if now is None:
            return None, SIM_CLOCK_INVALID
        if self.last_now is not None and now < self.last_now:
            return None, SIM_CLOCK_REGRESSION
        self.last_now = now
        return now, None

    def _refuse(self, step, codes):
        if not self.steps or self.steps[-1].step != step:
            self._step(step, codes[0])
        self.codes += codes
        return REFUSED_SIMULATED

    def run(self):
        self._step(STEP_VALIDATE_REQUEST)
        try:
            terminal = self._drive()
        except Exception:  # noqa: BLE001 - never escape; uncertainty once the effect call started
            self.codes.append(SIM_INTERNAL_ERROR)
            terminal = UNCERTAIN_SIMULATED if self.effect_calls else REFUSED_SIMULATED
        self._release()
        if terminal == UNCERTAIN_SIMULATED:
            self.codes.append(SIM_NO_RETRY_AFTER_UNCERTAINTY)
        if terminal == COMPLETED_SIMULATED:
            self.codes.append(SIM_COMPLETED_SIMULATED_ONLY)
        else:
            self.flags["postcheck"] = False
        self.states.append(terminal)
        return terminal

    def _drive(self):
        r, port, op = self.request, self.port, self.request.attempt_id
        target = r.target

        # Gate 2: the decision fixture, then its in-memory acknowledgement.
        now, problem = self._now()
        if now is None:
            return self._refuse(STEP_CHECK_DECISION, [problem])
        errors = decision_errors(self.decision, r, now)
        if errors:
            return self._refuse(STEP_CHECK_DECISION, errors)
        self.fixture_id = self.decision.fixture_id
        ack = self._port(STEP_CHECK_DECISION, lambda: port.acknowledge_decision_fixture(op, self.fixture_id))
        if ack is _FAILED:
            return self._refuse(STEP_CHECK_DECISION, [SIM_DECISION_NOT_ACKNOWLEDGED])
        errors = _ack_errors(ack, r, self.fixture_id)
        if errors:
            return self._refuse(STEP_CHECK_DECISION, errors)
        self.flags["decision"] = True
        self._step(STEP_CHECK_DECISION)
        self.states.append(CHECKED)

        # Gate 3: exclusive simulated lease (released on every path from here).
        lease = self._port(STEP_ACQUIRE_LEASE, lambda: port.acquire_simulated_lease(op, _lease_resource(r)))
        if lease is _FAILED or lease is None:
            return self._refuse(STEP_ACQUIRE_LEASE, [SIM_LEASE_UNAVAILABLE])
        if type(lease) is SimulatedLease and type(lease.lease_id) is str:
            self.lease_id = lease.lease_id
        now, problem = self._now()
        if now is None:
            return self._refuse(STEP_ACQUIRE_LEASE, [problem])
        errors = _lease_errors(lease, r, now)
        if errors:
            return self._refuse(STEP_ACQUIRE_LEASE, errors)
        self.lease = lease
        self.flags["lease"] = True
        self._step(STEP_ACQUIRE_LEASE)
        self.states.append(LEASE_SIMULATED)

        # Gate 4: fresh simulated revalidation, decision re-acknowledged, lease still valid.
        snapshot = self._port(STEP_FRESH_REVALIDATE, lambda: port.read_simulated_inventory(op, target.target_id))
        now, problem = self._now()
        if snapshot is _FAILED:
            return self._refuse(STEP_FRESH_REVALIDATE, [SIM_FRESH_MALFORMED])
        if now is None:
            return self._refuse(STEP_FRESH_REVALIDATE, [problem])
        errors = fresh_errors(snapshot, r, now)
        if errors:
            return self._refuse(STEP_FRESH_REVALIDATE, errors)
        others_digest = snapshot.other_worktrees_digest
        self._step(STEP_FRESH_REVALIDATE)
        again = self._port(STEP_RECHECK_DECISION, lambda: port.recheck_decision_fixture(op, self.fixture_id))
        now, problem = self._now()
        if again is _FAILED:
            return self._refuse(STEP_RECHECK_DECISION, [SIM_DECISION_NOT_ACKNOWLEDGED])
        if now is None:
            return self._refuse(STEP_RECHECK_DECISION, [problem])
        errors = _ack_errors(again, r, self.fixture_id) or decision_errors(self.decision, r, now)
        if not errors and _window(self.lease.acquired_at, self.lease.expires_at, now, MAX_LEASE_SECONDS):
            errors = [SIM_LEASE_EXPIRED]
        if errors:
            return self._refuse(STEP_RECHECK_DECISION, errors)
        self.flags["fresh"] = True
        self._step(STEP_RECHECK_DECISION)
        self.states.append(FRESH_REVALIDATED_SIMULATED)

        # Gate 5: single use consumed BEFORE the effect; a failure burns it.
        receipt = self._port(STEP_CONSUME, lambda: port.consume_simulated_single_use(op, self.fixture_id))
        status = None if receipt is _FAILED else _consumption_status(receipt, r, self.fixture_id)
        if status == CONSUMPTION_REPLAY:
            return self._refuse(STEP_CONSUME, [SIM_REPLAY_DETECTED])
        if status != CONSUMPTION_RECORDED:
            return self._refuse(STEP_CONSUME, [SIM_CONSUMPTION_FAILED])
        self.consumption_id = receipt.consumption_id
        self.flags["consumed"] = True
        self._step(STEP_CONSUME)
        self.states.append(CONSUMED_SIMULATED)
        now, problem = self._now()
        if now is None or _window(self.lease.acquired_at, self.lease.expires_at, now, MAX_LEASE_SECONDS):
            return self._refuse(STEP_EFFECT, [problem or SIM_LEASE_EXPIRED])

        # Gate 6: the ONE simulated effect call. From here on: no refusal, no retry.
        self.states.append(EFFECT_SIMULATED)
        self.effect_calls += 1
        report = self._port(STEP_EFFECT, lambda: port.apply_simulated_effect(
            op, target.target_id, self.consumption_id, self.lease_id))
        effect = None if report is _FAILED else _effect_status(report, r)
        if report is not _FAILED:
            self._step(STEP_EFFECT, STEP_OK if effect == EFFECT_RECORDED else
                       SIM_EFFECT_REFUSED_BY_PORT if effect == EFFECT_REFUSED else SIM_EFFECT_OUTCOME_UNKNOWN)

        # Gate 7: postcondition, read whatever the effect answer was.
        post = self._port(STEP_POSTCHECK, lambda: port.read_simulated_postcondition(op, target.target_id))
        confirmed = post is not _FAILED and _postcheck_ok(post, r, others_digest)
        if post is not _FAILED:
            self._step(STEP_POSTCHECK, STEP_OK if confirmed else SIM_POSTCHECK_MISMATCH)
        if not confirmed:
            self.codes.append(SIM_POSTCHECK_UNREAD if post is _FAILED else SIM_POSTCHECK_MISMATCH)
        if effect != EFFECT_RECORDED:
            # Even a postcondition that looks retired is not a claimed effect.
            self.codes.append(SIM_EFFECT_REFUSED_BY_PORT if effect == EFFECT_REFUSED else SIM_EFFECT_OUTCOME_UNKNOWN)
            return UNCERTAIN_SIMULATED
        self.effect_id = report.effect_id
        self.flags["effect"] = True
        if not confirmed:
            return UNCERTAIN_SIMULATED
        self.states.append(POSTCHECK_SIMULATED)
        self.flags["postcheck"] = True
        return COMPLETED_SIMULATED

    def _release(self):
        if self.lease_id is None:
            return
        done = self._port(STEP_RELEASE_LEASE, lambda: self.port.release_simulated_lease(self.lease_id))
        if done is _FAILED:
            self.codes.append(SIM_LEASE_RELEASE_FAILED)
        else:
            self._step(STEP_RELEASE_LEASE)


# ---------------------------------------------------------------------------
# Outcomes and entry points
# ---------------------------------------------------------------------------

def _outcome(state, request, attempt=None, codes=()) -> SimulatedRetirementOutcome:
    a = attempt
    try:
        bound = type(request) is SimulatedRetirementRequest and not request_errors(request)
    except Exception:  # noqa: BLE001 - an unverifiable request binds nothing
        bound = False
    reasons = list(codes) + (a.codes if a else []) + list(ALWAYS_CODES)
    draft = SimulatedRetirementOutcome(
        schema=OUTCOME_SCHEMA, state=state, reason_codes=tuple(dict.fromkeys(reasons)),
        state_trace=tuple(a.states) if a else (CREATED, state),
        step_trace=tuple(a.steps) if a else (SimulationStep(STEP_VALIDATE_REQUEST, codes[0]),),
        attempt_id=request.attempt_id if bound else None, target_id=request.target.target_id if bound else None,
        fixture_id=a.fixture_id if a else None, lease_id=a.lease_id if a else None,
        consumption_id=a.consumption_id if a else None, effect_id=a.effect_id if a else None,
        simulated_effect_calls=a.effect_calls if a else 0,
        simulated_decision_checked=a.flags["decision"] if a else False,
        simulated_lease_held=a.flags["lease"] if a else False,
        simulated_fresh_revalidated=a.flags["fresh"] if a else False,
        simulated_consumed=a.flags["consumed"] if a else False,
        simulated_effect_recorded=a.flags["effect"] if a else False,
        simulated_postcheck_confirmed=a.flags["postcheck"] if a else False,
        human_reconciliation_required=state == UNCERTAIN_SIMULATED, fingerprint="")
    return dataclasses.replace(draft, fingerprint=outcome_fingerprint(draft))


def simulate_retirement(request, decision, port, *, clock) -> SimulatedRetirementOutcome:
    """Drives ONE simulated attempt. The request and the port type are checked
    before the port is touched. Never raises; at most one simulated effect
    call; the outcome is never a real retirement or a real authorization."""
    try:
        errors = request_errors(request)
    except Exception:  # noqa: BLE001
        errors = [SIM_REQUEST_MALFORMED]
    if errors:
        return _outcome(REFUSED_SIMULATED, request, codes=errors)
    if type(port) is not InMemoryRetirementSimulationPort or port.port_kind != PORT_KIND_IN_MEMORY_SIMULATION:
        return _outcome(REFUSED_SIMULATED, request, codes=[SIM_PORT_NOT_IN_MEMORY_SIMULATION])
    if not callable(clock):
        return _outcome(REFUSED_SIMULATED, request, codes=[SIM_CLOCK_INVALID])
    attempt = _Attempt(request, decision, port, clock)
    state = attempt.run()
    return _outcome(state, request, attempt=attempt)


def execute_live(*_args, **_kwargs):
    """Permanent guard: there is no live retirement in FCP-4F-01. Raises
    NOT_LIVE at once, without reading any argument, the host or a file."""
    raise RetirementSimulationNotLive()


# ---------------------------------------------------------------------------
# Outcome invariants
# ---------------------------------------------------------------------------

def _trace_ok(trace, final) -> bool:
    if type(trace) is not tuple or not trace or trace[-1] != final:
        return False
    previous = _START
    for state in trace:
        if state not in TRANSITIONS.get(previous, ()):
            return False
        previous = state
    return True


def outcome_invariant_errors(outcome) -> tuple:
    """Stable codes of every violated outcome invariant (empty when sound)."""
    if type(outcome) is not SimulatedRetirementOutcome or type(outcome.step_trace) is not tuple \
            or not all(type(s) is SimulationStep for s in outcome.step_trace):
        return ("INV_MALFORMED",)
    o, errors = outcome, []
    try:
        if o.fingerprint != outcome_fingerprint(o):
            errors.append("INV_FINGERPRINT")
    except Exception:  # noqa: BLE001
        errors.append("INV_FINGERPRINT")
    trace = o.state_trace if type(o.state_trace) is tuple else ()
    if o.schema != OUTCOME_SCHEMA or o.state not in TERMINAL_STATES or not _trace_ok(o.state_trace, o.state):
        errors.append("INV_STATE")
    if any(getattr(o, name) is not value for name, value in _FIXED_OUTCOME_FLAGS) \
            or o.unproven != SIMULATION_UNPROVEN or o.live_activation_blocker != LIVE_ACTIVATION_BLOCKER:
        errors.append("INV_NOT_LIVE")
    codes = o.reason_codes
    if type(codes) is not tuple or len(set(codes)) != len(codes) or not set(codes) <= set(REASON_CODES) \
            or not set(ALWAYS_CODES) <= set(codes):
        errors.append("INV_REASON_CODES")
    steps = [s.step for s in o.step_trace]
    positions = [STEP_ORDER.index(s) if s in STEP_ORDER else -1 for s in steps]
    if -1 in positions or positions != sorted(positions) or len(set(steps)) != len(steps):
        errors.append("INV_STEP_ORDER")
    attempted = EFFECT_SIMULATED in trace
    if o.simulated_effect_calls not in (0, 1) or (o.simulated_effect_calls == 1) != attempted:
        errors.append("INV_EFFECT_CALLS")
    if o.state == REFUSED_SIMULATED and (o.simulated_effect_calls or o.simulated_effect_recorded):
        errors.append("INV_REFUSAL_WITH_EFFECT")
    if attempted and (CONSUMED_SIMULATED not in trace or trace.index(CONSUMED_SIMULATED) > trace.index(
            EFFECT_SIMULATED) or o.simulated_consumed is not True or o.consumption_id is None
            or STEP_CONSUME not in steps or (STEP_EFFECT in steps and steps.index(STEP_CONSUME)
                                             > steps.index(STEP_EFFECT))):
        errors.append("INV_CONSUME_BEFORE_EFFECT")
    if (o.state == UNCERTAIN_SIMULATED) != (o.human_reconciliation_required is True) \
            or (o.state == UNCERTAIN_SIMULATED and (o.simulated_effect_calls != 1
                                                    or SIM_NO_RETRY_AFTER_UNCERTAINTY not in codes)):
        errors.append("INV_UNCERTAIN")
    completed = o.state == COMPLETED_SIMULATED
    if o.simulated_postcheck_confirmed is not completed or (completed and not (
            o.simulated_decision_checked and o.simulated_lease_held and o.simulated_fresh_revalidated
            and o.simulated_consumed and o.simulated_effect_recorded and o.effect_id is not None
            and o.simulated_effect_calls == 1 and SIM_COMPLETED_SIMULATED_ONLY in codes)):
        errors.append("INV_COMPLETED_EVIDENCE")
    return tuple(errors)


def verify_outcome(outcome) -> bool:
    """True only if every outcome invariant holds."""
    return outcome_invariant_errors(outcome) == ()
