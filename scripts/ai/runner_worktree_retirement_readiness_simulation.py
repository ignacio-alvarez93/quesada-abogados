"""FCP-4F-02: retirement host readiness matrix (PURE ANALYSIS, SIMULATION ONLY, NOT LIVE).

Answers ONE question: after one FCP-4F-01 simulated attempt, which retirement
guarantees remain unproven? It reads a `SimulatedRetirementOutcome` (checked
with the 4F-01 `verify_outcome`, never re-run) and a synthetic, declarative
`SyntheticReadinessInventory`, and returns a typed, immutable, deterministic
`RetirementReadinessReport`: one row per obligation registered by the 4E-02e
audit (policy and approval, host and filesystem identity, clock, queues,
external lease, revalidation, single use, uncertainty and postconditions,
retention, ACL, separation of duties and disposable scope), each with an
informational status, stable codes, causal dependencies and missing proofs.

Nothing here retires, authorizes or attests anything. No state machine, no
port, no adapter, no Git, no file, no process, no network, no key, no ledger
and no real clock exist in this module. The verdict is always
`LIVE_NOT_AUTHORIZED` / `NOT_LIVE`; `RETIREMENT_AUTHORIZATION_LIVE`,
`RETIREMENT_EXECUTION_CAPABLE` and every real-world flag of the report and of
its rows are constant False and are not constructor arguments. No status
means ready: `STATUSES` has no "ready" value and no input can supply one.

Statuses (informational only)
-----------------------------
* SIMULATED_ONLY: the 4F-01 simulation exercised the gate in memory. It says
  nothing about a real host.
* UNPROVEN: not modeled by the simulation, or its gate was not reached.
  Every obligation that cannot be proven locally stays UNPROVEN by design.
* POLICY_PENDING: human retirement policy D-1..D-12 is a proposal NOT
  approved by Direccion; no reference, test or comment approves it.
* REFUSED: the simulation refused at this gate, or the inventory asserted a
  real-world fact (host attested, ACL verified, queue complete, human or
  policy approved...) that no simulation can verify. An unverifiable
  assertion lowers confidence; it never raises it.
* UNCERTAIN_RECONCILIATION_REQUIRED: the simulated effect ended uncertain.
  A destructive retry is forbidden now and in any future plan.
* BLOCKED_BY_DEPENDENCY: a causal dependency is refused, blocked or uncertain.

`SIMULATION_PRECONDITIONS_MODELED` only means a COMPLETED_SIMULATED outcome
verified by 4F-01 and no refused row: it is not host accreditation
(`host_accreditation` is fixed HOST_ACCREDITATION_ABSENT) and not policy
approval (`policy_status` is fixed D1_D12_PENDING_NOT_APPROVED).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from scripts.ai import runner_worktree_retirement_authorization as wra
from scripts.ai import runner_worktree_retirement_executor_simulation as sim
from scripts.ai import runner_worktree_retirement_host_authority as rha


RETIREMENT_AUTHORIZATION_LIVE = False
RETIREMENT_EXECUTION_CAPABLE = False
SIMULATION_ONLY = True

READINESS_MARKER = "FCP4F02_READINESS_SIMULATION_ONLY_NOT_A_PERMIT"
INVENTORY_SCHEMA = "fcp4f02-synthetic-readiness-inventory-v1"
DECLARATION_SCHEMA = "fcp4f02-synthetic-evidence-declaration-v1"
POLICY_REFERENCE_SCHEMA = "fcp4f02-synthetic-policy-reference-v1"
ROW_SCHEMA = "fcp4f02-readiness-row-v1"
REPORT_SCHEMA = "fcp4f02-retirement-readiness-report-v1"

MAX_DECLARATIONS = 64
MIN_DECLARED_AT = datetime(2020, 1, 1, tzinfo=timezone.utc)
MAX_DECLARED_AT = datetime(2100, 1, 1, tzinfo=timezone.utc)

# Fixed verdicts: no other value exists.
LIVE_NOT_AUTHORIZED = "LIVE_NOT_AUTHORIZED"
NOT_LIVE = sim.NOT_LIVE
HOST_ACCREDITATION_ABSENT = "HOST_ACCREDITATION_ABSENT"
POLICY_D1_D12_PENDING_NOT_APPROVED = "D1_D12_PENDING_NOT_APPROVED"

# Simulation assessment (what the 4F-01 outcome and the inventory model).
SIMULATION_PRECONDITIONS_MODELED = "SIMULATION_PRECONDITIONS_MODELED"
SIMULATION_GAPS_REFUSED = "SIMULATION_GAPS_REFUSED"
SIMULATION_REFUSED = "SIMULATION_REFUSED"
SIMULATION_UNCERTAIN = "SIMULATION_UNCERTAIN"
INPUT_REFUSED = "INPUT_REFUSED"
ASSESSMENTS = (SIMULATION_PRECONDITIONS_MODELED, SIMULATION_GAPS_REFUSED, SIMULATION_REFUSED, SIMULATION_UNCERTAIN,
               INPUT_REFUSED)

# Row statuses (informational; none of them is a permission).
SIMULATED_ONLY = "SIMULATED_ONLY"
UNPROVEN = "UNPROVEN"
POLICY_PENDING = "POLICY_PENDING"
REFUSED = "REFUSED"
UNCERTAIN_RECONCILIATION_REQUIRED = "UNCERTAIN_RECONCILIATION_REQUIRED"
BLOCKED_BY_DEPENDENCY = "BLOCKED_BY_DEPENDENCY"
STATUSES = (SIMULATED_ONLY, UNPROVEN, POLICY_PENDING, REFUSED, UNCERTAIN_RECONCILIATION_REQUIRED,
            BLOCKED_BY_DEPENDENCY)
_BLOCKING_STATUSES = (REFUSED, UNCERTAIN_RECONCILIATION_REQUIRED, BLOCKED_BY_DEPENDENCY)

COVERAGE_MODELED = "MODELED_BY_FCP4F01_SIMULATION"
COVERAGE_NOT_MODELED = "NOT_MODELED_BY_SIMULATION"

# Obligations registered by the 4E-02e audit, in causal (topological) order.
REQ_POLICY_D1_D12 = "POLICY_D1_D12"
REQ_SEPARATION_OF_DUTIES = "SEPARATION_OF_DUTIES"
REQ_HUMAN_APPROVAL = "HUMAN_APPROVAL"
REQ_DISPOSABLE_SCOPE = "DISPOSABLE_SCOPE"
REQ_HOST_IDENTITY = "HOST_IDENTITY"
REQ_FILESYSTEM_IDENTITY = "FILESYSTEM_IDENTITY"
REQ_FILE_ACL = "FILE_ACL"
REQ_TRUSTED_CLOCK = "TRUSTED_CLOCK"
REQ_QUEUE_SCOPE = "QUEUE_SCOPE"
REQ_EXTERNAL_LEASE = "EXTERNAL_LEASE"
REQ_FRESH_REVALIDATION = "FRESH_REVALIDATION"
REQ_SINGLE_USE_CONSUMPTION = "SINGLE_USE_CONSUMPTION"
REQ_UNCERTAINTY_AND_POSTCONDITION = "UNCERTAINTY_AND_POSTCONDITION"
REQ_RETENTION = "RETENTION"
REQUIREMENTS = (REQ_POLICY_D1_D12, REQ_SEPARATION_OF_DUTIES, REQ_HUMAN_APPROVAL, REQ_DISPOSABLE_SCOPE,
                REQ_HOST_IDENTITY, REQ_FILESYSTEM_IDENTITY, REQ_FILE_ACL, REQ_TRUSTED_CLOCK, REQ_QUEUE_SCOPE,
                REQ_EXTERNAL_LEASE, REQ_FRESH_REVALIDATION, REQ_SINGLE_USE_CONSUMPTION,
                REQ_UNCERTAINTY_AND_POSTCONDITION, REQ_RETENTION)

DEPENDENCIES = {
    REQ_POLICY_D1_D12: (),
    REQ_SEPARATION_OF_DUTIES: (REQ_POLICY_D1_D12,),
    REQ_HUMAN_APPROVAL: (REQ_POLICY_D1_D12, REQ_SEPARATION_OF_DUTIES),
    REQ_DISPOSABLE_SCOPE: (REQ_POLICY_D1_D12,),
    REQ_HOST_IDENTITY: (),
    REQ_FILESYSTEM_IDENTITY: (REQ_HOST_IDENTITY,),
    REQ_FILE_ACL: (REQ_HOST_IDENTITY, REQ_FILESYSTEM_IDENTITY),
    REQ_TRUSTED_CLOCK: (REQ_HOST_IDENTITY,),
    REQ_QUEUE_SCOPE: (REQ_DISPOSABLE_SCOPE, REQ_HOST_IDENTITY),
    REQ_EXTERNAL_LEASE: (REQ_HOST_IDENTITY, REQ_TRUSTED_CLOCK),
    REQ_FRESH_REVALIDATION: (REQ_HUMAN_APPROVAL, REQ_FILESYSTEM_IDENTITY, REQ_TRUSTED_CLOCK, REQ_QUEUE_SCOPE,
                             REQ_EXTERNAL_LEASE),
    REQ_SINGLE_USE_CONSUMPTION: (REQ_HUMAN_APPROVAL, REQ_FRESH_REVALIDATION),
    REQ_UNCERTAINTY_AND_POSTCONDITION: (REQ_FILE_ACL, REQ_SINGLE_USE_CONSUMPTION),
    REQ_RETENTION: (REQ_POLICY_D1_D12, REQ_UNCERTAINTY_AND_POSTCONDITION),
}

POLICY_DECISION_IDS = tuple("D-%d" % i for i in range(1, 13))

# What only a real, approved host could prove; never satisfied here.
MISSING_PROOFS = {
    REQ_POLICY_D1_D12: tuple("PROOF_DIRECCION_APPROVAL_D%d" % i for i in range(1, 13)),
    REQ_SEPARATION_OF_DUTIES: ("PROOF_REQUESTER_APPROVER_EXECUTOR_DISTINCT",
                               "PROOF_DUTY_ASSIGNMENT_RECORDED_BY_DIRECCION"),
    REQ_HUMAN_APPROVAL: ("PROOF_AUTHENTICATED_HUMAN_DECISION", "PROOF_DECISION_SIGNATURE_VERIFIED_ON_HOST",
                         "PROOF_DECISION_BOUND_TO_TARGET_AND_HOST"),
    REQ_DISPOSABLE_SCOPE: ("PROOF_TARGET_DECLARED_DISPOSABLE_BY_POLICY", "PROOF_NO_UNIQUE_WORK_IN_TARGET"),
    REQ_HOST_IDENTITY: ("PROOF_HOST_IDENTITY_ATTESTED_ON_HOST01", "PROOF_HOST_KEY_BOUND_TO_HOST"),
    REQ_FILESYSTEM_IDENTITY: ("PROOF_WORKTREE_PATH_IDENTITY_ON_HOST", "PROOF_NO_REPARSE_OR_ALIAS_PATH"),
    REQ_FILE_ACL: ("PROOF_FILE_ACL_INSPECTED_ON_HOST", "PROOF_NO_FOREIGN_WRITER"),
    REQ_TRUSTED_CLOCK: ("PROOF_TRUSTED_TIME_SOURCE", "PROOF_CLOCK_MONOTONIC_ACROSS_PROCESSES"),
    REQ_QUEUE_SCOPE: ("PROOF_EXTERNAL_QUEUE_INVENTORY_COMPLETE", "PROOF_QUEUE_MANIFEST_SIGNED_AND_VERIFIED",
                      "PROOF_NO_PENDING_WORK_FOR_TARGET"),
    REQ_EXTERNAL_LEASE: ("PROOF_OS_LEVEL_EXCLUSIVE_LEASE", "PROOF_LEASE_FENCING_ACROSS_PROCESSES"),
    REQ_FRESH_REVALIDATION: ("PROOF_FRESH_LIVE_INVENTORY_UNDER_LEASE", "PROOF_REVALIDATION_BOUND_TO_DECISION"),
    REQ_SINGLE_USE_CONSUMPTION: ("PROOF_DURABLE_SINGLE_USE_LEDGER", "PROOF_CRASH_SAFE_CONSUMPTION"),
    REQ_UNCERTAINTY_AND_POSTCONDITION: ("PROOF_REAL_POSTCONDITION_READ", "PROOF_CRASH_RECOVERY_RECONCILIATION",
                                        "PROOF_GIT_WORKTREE_REMOVAL_SEMANTICS"),
    REQ_RETENTION: ("PROOF_RETENTION_POLICY_APPROVED", "PROOF_EVIDENCE_RETAINED_DURABLY"),
}

# Declaration claims. Neutral claims describe a gap; asserted claims state a
# real-world fact that no simulation can verify and are refused.
CLAIM_NOT_INSPECTED = "DECLARED_NOT_INSPECTED"
CLAIM_ABSENT = "DECLARED_ABSENT"
CLAIM_HOST_ID_LABEL_ONLY = "HOST_ID_LABEL_WITHOUT_ATTESTATION"
CLAIM_EXTERNAL_QUEUE_UNCOVERED = "EXTERNAL_QUEUE_NOT_COVERED"
NEUTRAL_CLAIMS = {CLAIM_NOT_INSPECTED: None, CLAIM_ABSENT: None, CLAIM_HOST_ID_LABEL_ONLY: REQ_HOST_IDENTITY,
                  CLAIM_EXTERNAL_QUEUE_UNCOVERED: REQ_QUEUE_SCOPE}
ASSERTED_CLAIMS = {
    "POLICY_APPROVED": REQ_POLICY_D1_D12,
    "DUTIES_SEPARATED": REQ_SEPARATION_OF_DUTIES,
    "HUMAN_APPROVED": REQ_HUMAN_APPROVAL,
    "SCOPE_DISPOSABLE_CONFIRMED": REQ_DISPOSABLE_SCOPE,
    "HOST_ATTESTED": REQ_HOST_IDENTITY,
    "FILESYSTEM_IDENTITY_VERIFIED": REQ_FILESYSTEM_IDENTITY,
    "ACL_VERIFIED": REQ_FILE_ACL,
    "CLOCK_ATTESTED": REQ_TRUSTED_CLOCK,
    "QUEUE_COMPLETE": REQ_QUEUE_SCOPE,
    "MANIFEST_COMPLETE": REQ_QUEUE_SCOPE,
    "EXTERNAL_LEASE_HELD": REQ_EXTERNAL_LEASE,
    "REVALIDATED_LIVE": REQ_FRESH_REVALIDATION,
    "SINGLE_USE_DURABLE": REQ_SINGLE_USE_CONSUMPTION,
    "POSTCONDITION_CONFIRMED_LIVE": REQ_UNCERTAINTY_AND_POSTCONDITION,
    "RETENTION_SATISFIED": REQ_RETENTION,
}
CLAIMS = tuple(NEUTRAL_CLAIMS) + tuple(ASSERTED_CLAIMS)

POLICY_STANCE_PROPOSED = "PROPOSED_NOT_APPROVED_BY_DIRECCION"
POLICY_STANCE_CLAIMED_APPROVED = "CLAIMED_APPROVED_UNVERIFIABLE"
POLICY_STANCES = (POLICY_STANCE_PROPOSED, POLICY_STANCE_CLAIMED_APPROVED)

# Reason codes: input (any of them refuses the whole input).
READINESS_OUTCOME_UNVERIFIED = "READINESS_OUTCOME_UNVERIFIED"
READINESS_UPSTREAM_EVIDENCE_NOT_OUTCOME = "READINESS_UPSTREAM_EVIDENCE_NOT_OUTCOME"
READINESS_INVENTORY_MALFORMED = "READINESS_INVENTORY_MALFORMED"
READINESS_INVENTORY_MARKER_MISSING = "READINESS_INVENTORY_MARKER_MISSING"
READINESS_INVENTORY_UNKNOWN_FIELD = "READINESS_INVENTORY_UNKNOWN_FIELD"
READINESS_INVENTORY_FORGED_FLAG = "READINESS_INVENTORY_FORGED_FLAG"
READINESS_INVENTORY_BINDING_MISMATCH = "READINESS_INVENTORY_BINDING_MISMATCH"
READINESS_INVENTORY_TIMESTAMP_INVALID = "READINESS_INVENTORY_TIMESTAMP_INVALID"
READINESS_INVENTORY_TOO_LARGE = "READINESS_INVENTORY_TOO_LARGE"
READINESS_INVENTORY_NOT_CANONICAL = "READINESS_INVENTORY_NOT_CANONICAL"
READINESS_DECLARATION_MALFORMED = "READINESS_DECLARATION_MALFORMED"
READINESS_DECLARATION_UNKNOWN_VOCABULARY = "READINESS_DECLARATION_UNKNOWN_VOCABULARY"
READINESS_DECLARATION_REQUIREMENT_MISMATCH = "READINESS_DECLARATION_REQUIREMENT_MISMATCH"
READINESS_DECLARATION_NOT_SYNTHETIC = "READINESS_DECLARATION_NOT_SYNTHETIC"
READINESS_DECLARATION_DUPLICATE = "READINESS_DECLARATION_DUPLICATE"
READINESS_POLICY_REFERENCE_MALFORMED = "READINESS_POLICY_REFERENCE_MALFORMED"
READINESS_INTERNAL_ERROR = "READINESS_INTERNAL_ERROR"
READINESS_INPUT_REFUSED = "READINESS_INPUT_REFUSED"
INPUT_CODES = (
    READINESS_OUTCOME_UNVERIFIED, READINESS_UPSTREAM_EVIDENCE_NOT_OUTCOME, READINESS_INVENTORY_MALFORMED,
    READINESS_INVENTORY_MARKER_MISSING, READINESS_INVENTORY_UNKNOWN_FIELD, READINESS_INVENTORY_FORGED_FLAG,
    READINESS_INVENTORY_BINDING_MISMATCH, READINESS_INVENTORY_TIMESTAMP_INVALID, READINESS_INVENTORY_TOO_LARGE,
    READINESS_INVENTORY_NOT_CANONICAL, READINESS_DECLARATION_MALFORMED, READINESS_DECLARATION_UNKNOWN_VOCABULARY,
    READINESS_DECLARATION_REQUIREMENT_MISMATCH, READINESS_DECLARATION_NOT_SYNTHETIC,
    READINESS_DECLARATION_DUPLICATE, READINESS_POLICY_REFERENCE_MALFORMED, READINESS_INTERNAL_ERROR,
    READINESS_INPUT_REFUSED,
)
# Row codes.
READINESS_SIMULATED_BY_4F01_ONLY = "READINESS_SIMULATED_BY_4F01_ONLY"
READINESS_NOT_MODELED_BY_SIMULATION = "READINESS_NOT_MODELED_BY_SIMULATION"
READINESS_GATE_NOT_REACHED_IN_SIMULATION = "READINESS_GATE_NOT_REACHED_IN_SIMULATION"
READINESS_REFUSED_BY_SIMULATION = "READINESS_REFUSED_BY_SIMULATION"
READINESS_UNVERIFIABLE_CLAIM_REFUSED = "READINESS_UNVERIFIABLE_CLAIM_REFUSED"
READINESS_DECLARED_NOT_INSPECTED = "READINESS_DECLARED_NOT_INSPECTED"
READINESS_DECLARED_ABSENT = "READINESS_DECLARED_ABSENT"
READINESS_HOST_ID_WITHOUT_ATTESTATION = "READINESS_HOST_ID_WITHOUT_ATTESTATION"
READINESS_EXTERNAL_QUEUES_NOT_COVERED = "READINESS_EXTERNAL_QUEUES_NOT_COVERED"
READINESS_CALLER_CLOCK_NOT_TRUSTED = "READINESS_CALLER_CLOCK_NOT_TRUSTED"
READINESS_POLICY_D1_D12_PENDING = "READINESS_POLICY_D1_D12_PENDING"
READINESS_POLICY_REFERENCES_INCOMPLETE = "READINESS_POLICY_REFERENCES_INCOMPLETE"
READINESS_POLICY_PROPOSAL_NOT_APPROVAL = "READINESS_POLICY_PROPOSAL_NOT_APPROVAL"
READINESS_DEPENDENCY_BLOCKED = "READINESS_DEPENDENCY_BLOCKED"
READINESS_UNCERTAIN_RECONCILIATION_REQUIRED = "READINESS_UNCERTAIN_RECONCILIATION_REQUIRED"
READINESS_NO_DESTRUCTIVE_RETRY_AFTER_UNCERTAINTY = "READINESS_NO_DESTRUCTIVE_RETRY_AFTER_UNCERTAINTY"
ROW_CODES = (
    READINESS_SIMULATED_BY_4F01_ONLY, READINESS_NOT_MODELED_BY_SIMULATION, READINESS_GATE_NOT_REACHED_IN_SIMULATION,
    READINESS_REFUSED_BY_SIMULATION, READINESS_UNVERIFIABLE_CLAIM_REFUSED, READINESS_DECLARED_NOT_INSPECTED,
    READINESS_DECLARED_ABSENT, READINESS_HOST_ID_WITHOUT_ATTESTATION, READINESS_EXTERNAL_QUEUES_NOT_COVERED,
    READINESS_CALLER_CLOCK_NOT_TRUSTED, READINESS_POLICY_D1_D12_PENDING, READINESS_POLICY_REFERENCES_INCOMPLETE,
    READINESS_POLICY_PROPOSAL_NOT_APPROVAL, READINESS_DEPENDENCY_BLOCKED, READINESS_UNCERTAIN_RECONCILIATION_REQUIRED,
    READINESS_NO_DESTRUCTIVE_RETRY_AFTER_UNCERTAINTY,
)
# Always present on every report.
READINESS_LIVE_NOT_AUTHORIZED = "READINESS_LIVE_NOT_AUTHORIZED"
READINESS_SIMULATION_IS_NOT_HOST_ACCREDITATION = "READINESS_SIMULATION_IS_NOT_HOST_ACCREDITATION"
READINESS_NO_REAL_AUTHORIZATION = "READINESS_NO_REAL_AUTHORIZATION"
ALWAYS_CODES = (READINESS_LIVE_NOT_AUTHORIZED, READINESS_SIMULATION_IS_NOT_HOST_ACCREDITATION,
                READINESS_NO_REAL_AUTHORIZATION)
REASON_CODES = INPUT_CODES + ROW_CODES + ALWAYS_CODES

# Why live retirement stays blocked, whatever the inputs: carried by every report.
LIVE_BLOCKERS = (
    "HUMAN_RETIREMENT_POLICY_D1_D12_PENDING_NOT_APPROVED",
    "HOST01_ACCREDITATION_ABSENT",
    "REAL_HUMAN_AUTHENTICATION_ABSENT",
    "FCP4F_LIVE_ACTIVATION_OUT_OF_SCOPE",
    "FCP4F02_READINESS_SIMULATION_ONLY_PERMANENT",
)

# Which obligation a 4F-01 reason code speaks about (None: see the traced step).
SIM_CODE_REQUIREMENT = {
    sim.SIM_REQUEST_MALFORMED: REQ_DISPOSABLE_SCOPE, sim.SIM_MARKER_MISSING: None,
    sim.SIM_REQUEST_TAMPERED: REQ_DISPOSABLE_SCOPE, sim.SIM_TARGET_MALFORMED: REQ_DISPOSABLE_SCOPE,
    sim.SIM_TARGET_REAL_IDENTITY_REFUSED: REQ_DISPOSABLE_SCOPE, sim.SIM_TARGET_NOT_SYNTHETIC: REQ_DISPOSABLE_SCOPE,
    sim.SIM_TARGET_DIGEST_MISMATCH: REQ_DISPOSABLE_SCOPE, sim.SIM_TARGET_PROTECTED_BRANCH: REQ_DISPOSABLE_SCOPE,
    sim.SIM_TARGET_SHA_INVALID: REQ_DISPOSABLE_SCOPE, sim.SIM_PORT_NOT_IN_MEMORY_SIMULATION: REQ_DISPOSABLE_SCOPE,
    sim.SIM_CLOCK_INVALID: REQ_TRUSTED_CLOCK, sim.SIM_CLOCK_REGRESSION: REQ_TRUSTED_CLOCK,
    sim.SIM_DECISION_ABSENT: REQ_HUMAN_APPROVAL, sim.SIM_DECISION_NOT_SIMULATION_FIXTURE: REQ_HUMAN_APPROVAL,
    sim.SIM_4D_ASSESSMENT_NOT_AUTHORITY: REQ_HUMAN_APPROVAL, sim.SIM_4E_PROPOSAL_NOT_AUTHORITY: REQ_HUMAN_APPROVAL,
    sim.SIM_4E_VERIFICATION_NOT_AUTHORITY: REQ_HUMAN_APPROVAL,
    sim.SIM_4E_DRY_RUN_EVIDENCE_NOT_AUTHORITY: REQ_HUMAN_APPROVAL,
    sim.SIM_DECISION_MALFORMED: REQ_HUMAN_APPROVAL, sim.SIM_DECISION_FORGED_CLAIM: REQ_HUMAN_APPROVAL,
    sim.SIM_DECISION_UNSEALED: REQ_HUMAN_APPROVAL, sim.SIM_DECISION_BINDING_MISMATCH: REQ_HUMAN_APPROVAL,
    sim.SIM_DECISION_TIMESTAMP_INVALID: REQ_HUMAN_APPROVAL, sim.SIM_DECISION_TTL_TOO_LONG: REQ_HUMAN_APPROVAL,
    sim.SIM_DECISION_NOT_YET_VALID: REQ_HUMAN_APPROVAL, sim.SIM_DECISION_EXPIRED: REQ_HUMAN_APPROVAL,
    sim.SIM_DECISION_NOT_ACKNOWLEDGED: REQ_HUMAN_APPROVAL, sim.SIM_DECISION_REVOKED: REQ_HUMAN_APPROVAL,
    sim.SIM_DECISION_ALREADY_CONSUMED: REQ_SINGLE_USE_CONSUMPTION, sim.SIM_DECISION_ACK_MALFORMED: REQ_HUMAN_APPROVAL,
    sim.SIM_LEASE_UNAVAILABLE: REQ_EXTERNAL_LEASE, sim.SIM_LEASE_INVALID: REQ_EXTERNAL_LEASE,
    sim.SIM_LEASE_EXPIRED: REQ_EXTERNAL_LEASE, sim.SIM_LEASE_RELEASE_FAILED: REQ_EXTERNAL_LEASE,
    sim.SIM_FRESH_MALFORMED: REQ_FRESH_REVALIDATION, sim.SIM_FRESH_BINDING_MISMATCH: REQ_FRESH_REVALIDATION,
    sim.SIM_FRESH_STALE: REQ_FRESH_REVALIDATION, sim.SIM_FRESH_FROM_FUTURE: REQ_FRESH_REVALIDATION,
    sim.SIM_FRESH_WORKTREE_MISMATCH: REQ_FRESH_REVALIDATION, sim.SIM_FRESH_BRANCH_MISMATCH: REQ_FRESH_REVALIDATION,
    sim.SIM_FRESH_HEAD_SHA_MISMATCH: REQ_FRESH_REVALIDATION, sim.SIM_FRESH_BASE_MISMATCH: REQ_FRESH_REVALIDATION,
    sim.SIM_FRESH_BASE_SHA_MISMATCH: REQ_FRESH_REVALIDATION,
    sim.SIM_FRESH_TARGET_NOT_REGISTERED: REQ_FRESH_REVALIDATION, sim.SIM_FRESH_TARGET_DIRTY: REQ_FRESH_REVALIDATION,
    sim.SIM_FRESH_TARGET_LOCKED: REQ_FRESH_REVALIDATION,
    sim.SIM_HOST_IDENTITY_ABSENT: REQ_HOST_IDENTITY, sim.SIM_HOST_IDENTITY_MISMATCH: REQ_HOST_IDENTITY,
    sim.SIM_HOST_IDENTITY_NOT_ATTESTED_SIMULATED: REQ_HOST_IDENTITY,
    sim.SIM_QUEUE_ATTESTATION_ABSENT: REQ_QUEUE_SCOPE, sim.SIM_QUEUE_ATTESTATION_MALFORMED: REQ_QUEUE_SCOPE,
    sim.SIM_QUEUE_ATTESTATION_INCOMPLETE: REQ_QUEUE_SCOPE, sim.SIM_QUEUE_NOT_EMPTY: REQ_QUEUE_SCOPE,
    sim.SIM_CONSUMPTION_FAILED: REQ_SINGLE_USE_CONSUMPTION, sim.SIM_REPLAY_DETECTED: REQ_SINGLE_USE_CONSUMPTION,
    sim.SIM_EFFECT_OUTCOME_UNKNOWN: REQ_UNCERTAINTY_AND_POSTCONDITION,
    sim.SIM_EFFECT_REFUSED_BY_PORT: REQ_UNCERTAINTY_AND_POSTCONDITION,
    sim.SIM_POSTCHECK_UNREAD: REQ_UNCERTAINTY_AND_POSTCONDITION,
    sim.SIM_POSTCHECK_MISMATCH: REQ_UNCERTAINTY_AND_POSTCONDITION,
    sim.SIM_NO_RETRY_AFTER_UNCERTAINTY: REQ_UNCERTAINTY_AND_POSTCONDITION,
    sim.SIM_COMPLETED_SIMULATED_ONLY: None, sim.SIM_PORT_FAILED: None, sim.SIM_INTERNAL_ERROR: None,
    sim.SIM_SIMULATION_ONLY_NOT_A_RETIREMENT: None, sim.SIM_NO_REAL_AUTHORIZATION: None,
    sim.SIM_LIVE_EXECUTION_BLOCKED: None,
}
# Which obligation a failed 4F-01 step speaks about.
SIM_STEP_REQUIREMENT = {
    sim.STEP_VALIDATE_REQUEST: REQ_DISPOSABLE_SCOPE, sim.STEP_CHECK_DECISION: REQ_HUMAN_APPROVAL,
    sim.STEP_ACQUIRE_LEASE: REQ_EXTERNAL_LEASE, sim.STEP_FRESH_REVALIDATE: REQ_FRESH_REVALIDATION,
    sim.STEP_RECHECK_DECISION: REQ_FRESH_REVALIDATION, sim.STEP_CONSUME: REQ_SINGLE_USE_CONSUMPTION,
    sim.STEP_EFFECT: REQ_UNCERTAINTY_AND_POSTCONDITION, sim.STEP_POSTCHECK: REQ_UNCERTAINTY_AND_POSTCONDITION,
    sim.STEP_RELEASE_LEASE: REQ_EXTERNAL_LEASE,
}
# Which simulated outcome field shows that 4F-01 exercised the obligation in memory.
SIMULATED_BY = {
    REQ_HUMAN_APPROVAL: "simulated_decision_checked",
    REQ_DISPOSABLE_SCOPE: "attempt_id",
    REQ_HOST_IDENTITY: "simulated_fresh_revalidated",
    REQ_QUEUE_SCOPE: "simulated_fresh_revalidated",
    REQ_EXTERNAL_LEASE: "simulated_lease_held",
    REQ_FRESH_REVALIDATION: "simulated_fresh_revalidated",
    REQ_SINGLE_USE_CONSUMPTION: "simulated_consumed",
    REQ_UNCERTAINTY_AND_POSTCONDITION: "simulated_postcheck_confirmed",
}
_NEUTRAL_CODES = {CLAIM_NOT_INSPECTED: READINESS_DECLARED_NOT_INSPECTED, CLAIM_ABSENT: READINESS_DECLARED_ABSENT,
                  CLAIM_HOST_ID_LABEL_ONLY: READINESS_HOST_ID_WITHOUT_ATTESTATION,
                  CLAIM_EXTERNAL_QUEUE_UNCOVERED: READINESS_EXTERNAL_QUEUES_NOT_COVERED}


# ---------------------------------------------------------------------------
# Inputs (immutable, synthetic, declarative)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SyntheticEvidenceDeclaration:
    """ONE caller statement about ONE obligation, named by a `sim://fcp4f01/`
    label. A statement, never evidence: it can only add a gap or a refusal."""

    requirement: str
    claim: str
    evidence_label: str
    schema: str = DECLARATION_SCHEMA
    proves_live: bool = field(default=False, init=False)


@dataclass(frozen=True)
class SyntheticPolicyReference:
    """A reference to ONE of the proposed policies D-1..D-12. Never an approval."""

    decision_id: str
    stance: str
    schema: str = POLICY_REFERENCE_SCHEMA
    approved_by_direccion: bool = field(default=False, init=False)


@dataclass(frozen=True)
class SyntheticReadinessInventory:
    """The caller's synthetic inventory, bound to ONE 4F-01 outcome by its
    fingerprint. `declared_at` is the caller's clock: checked for form only,
    never trusted."""

    schema: str
    simulation_marker: str
    inventory_id: str
    outcome_fingerprint: str
    declared_at: str
    declarations: tuple
    policy_references: tuple
    is_host_evidence: bool = field(default=False, init=False)


_INPUT_FLAGS = {SyntheticEvidenceDeclaration: (("proves_live", False),),
                SyntheticPolicyReference: (("approved_by_direccion", False),),
                SyntheticReadinessInventory: (("is_host_evidence", False),)}


# ---------------------------------------------------------------------------
# Report (immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadinessRow:
    """ONE obligation. Even SIMULATED_ONLY is not proven for a real host."""

    requirement: str
    status: str
    simulation_coverage: str
    reason_codes: tuple
    depends_on: tuple
    blocking_dependencies: tuple
    missing_proofs: tuple
    declared_evidence: tuple
    schema: str = ROW_SCHEMA
    live_proven: bool = field(default=False, init=False)
    satisfied_for_live: bool = field(default=False, init=False)


@dataclass(frozen=True)
class RetirementReadinessReport:
    """The readiness matrix. Every real-world flag below is fixed: the report
    informs about gaps and never authorizes, issues or attests anything."""

    schema: str
    simulation_assessment: str
    outcome_state: Optional[str]
    outcome_fingerprint: Optional[str]
    outcome_verified: bool
    outcome_invariant_codes: tuple
    inventory_digest: Optional[str]
    rows: tuple
    reason_codes: tuple
    human_reconciliation_required: bool
    fingerprint: str
    verdict: str = field(default=LIVE_NOT_AUTHORIZED, init=False)
    live_status: str = field(default=NOT_LIVE, init=False)
    host_accreditation: str = field(default=HOST_ACCREDITATION_ABSENT, init=False)
    policy_status: str = field(default=POLICY_D1_D12_PENDING_NOT_APPROVED, init=False)
    live_blockers: tuple = field(default=LIVE_BLOCKERS, init=False)
    unproven: tuple = field(default=sim.SIMULATION_UNPROVEN, init=False)
    simulation_only: bool = field(default=True, init=False)
    destructive_retry_forbidden: bool = field(default=True, init=False)
    ready_for_live: bool = field(default=False, init=False)
    retirement_authorization_live: bool = field(default=False, init=False)
    retirement_execution_capable: bool = field(default=False, init=False)
    authorizes_action: bool = field(default=False, init=False)
    deletion_authorized: bool = field(default=False, init=False)
    branch_deletion_authorized: bool = field(default=False, init=False)
    issued: bool = field(default=False, init=False)
    consumed: bool = field(default=False, init=False)
    host_identity_authenticated: bool = field(default=False, init=False)
    queue_scope_attested: bool = field(default=False, init=False)
    file_acl_verified: bool = field(default=False, init=False)
    clock_attested: bool = field(default=False, init=False)
    policy_approved: bool = field(default=False, init=False)
    human_approval_present: bool = field(default=False, init=False)
    retry_allowed: bool = field(default=False, init=False)


_FIXED_REPORT_FIELDS = (
    ("verdict", LIVE_NOT_AUTHORIZED), ("live_status", NOT_LIVE), ("host_accreditation", HOST_ACCREDITATION_ABSENT),
    ("policy_status", POLICY_D1_D12_PENDING_NOT_APPROVED), ("live_blockers", LIVE_BLOCKERS),
    ("unproven", sim.SIMULATION_UNPROVEN), ("simulation_only", True), ("destructive_retry_forbidden", True),
    ("ready_for_live", False), ("retirement_authorization_live", False), ("retirement_execution_capable", False),
    ("authorizes_action", False), ("deletion_authorized", False), ("branch_deletion_authorized", False),
    ("issued", False), ("consumed", False), ("host_identity_authenticated", False), ("queue_scope_attested", False),
    ("file_acl_verified", False), ("clock_attested", False), ("policy_approved", False),
    ("human_approval_present", False), ("retry_allowed", False),
)
_FIXED_ROW_FLAGS = (("schema", ROW_SCHEMA), ("live_proven", False), ("satisfied_for_live", False))


# ---------------------------------------------------------------------------
# Pure helpers (digests reuse the 02a canonical JSON digest via 4F-01)
# ---------------------------------------------------------------------------

def _exact_fields(value) -> bool:
    """Every constructor field and no attribute beyond the declared fields
    (nothing smuggled in; fixed fields are checked by value elsewhere)."""
    try:
        fields = dataclasses.fields(value)
        own = set(vars(value))
    except TypeError:
        return False
    return {f.name for f in fields if f.init} <= own <= {f.name for f in fields}


def _flags_forged(value) -> bool:
    return any(getattr(value, name) is not fixed for name, fixed in _INPUT_FLAGS[type(value)])


def _declaration_key(d: SyntheticEvidenceDeclaration) -> tuple:
    return (REQUIREMENTS.index(d.requirement), d.claim, d.evidence_label)


def inventory_digest(inventory: SyntheticReadinessInventory) -> str:
    """Canonical digest of an inventory (integrity of the fixture only)."""
    return wra._digest({"schema": INVENTORY_SCHEMA, **sim._material(inventory, "")})


def report_fingerprint(report: RetirementReadinessReport) -> str:
    """Canonical digest of a report (audit and immutability, not authentication)."""
    return wra._digest({"schema": REPORT_SCHEMA, **sim._material(report, "fingerprint")})


def canonical_report_json(report: RetirementReadinessReport) -> str:
    """Deterministic serialization of a report (sorted keys, no whitespace)."""
    return json.dumps(wra._jsonable(dataclasses.asdict(report)), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def build_readiness_inventory(outcome, *, inventory_id, declared_at, declarations=(),
                              policy_references=()) -> SyntheticReadinessInventory:
    """An inventory bound to `outcome` with its declarations in canonical
    order. Pure; validation happens in `inventory_errors`."""
    bound = outcome.fingerprint if type(outcome) is sim.SimulatedRetirementOutcome else ""
    decls = tuple(declarations)
    try:
        decls = tuple(sorted(decls, key=_declaration_key))
    except (AttributeError, TypeError, ValueError):
        pass   # left as given; refused as malformed
    refs = tuple(policy_references)
    try:
        refs = tuple(sorted(refs, key=lambda r: POLICY_DECISION_IDS.index(r.decision_id)))
    except (AttributeError, TypeError, ValueError):
        pass
    return SyntheticReadinessInventory(schema=INVENTORY_SCHEMA, simulation_marker=READINESS_MARKER,
                                       inventory_id=inventory_id, outcome_fingerprint=bound,
                                       declared_at=declared_at, declarations=decls, policy_references=refs)


def outcome_errors(outcome) -> tuple:
    """The outcome must be a 4F-01 outcome that its own verifier accepts."""
    if type(outcome) is not sim.SimulatedRetirementOutcome:
        upstream = sim._not_a_fixture_code(outcome) != sim.SIM_DECISION_NOT_SIMULATION_FIXTURE
        return (READINESS_UPSTREAM_EVIDENCE_NOT_OUTCOME if upstream else READINESS_OUTCOME_UNVERIFIED,)
    return () if sim.verify_outcome(outcome) else (READINESS_OUTCOME_UNVERIFIED,)


def _declaration_errors(d) -> list:
    if type(d) is not SyntheticEvidenceDeclaration or not _exact_fields(d) or d.schema != DECLARATION_SCHEMA:
        return [READINESS_DECLARATION_MALFORMED]
    if _flags_forged(d):
        return [READINESS_INVENTORY_FORGED_FLAG]
    if type(d.requirement) is not str or type(d.claim) is not str or type(d.evidence_label) is not str:
        return [READINESS_DECLARATION_MALFORMED]
    if d.requirement not in REQUIREMENTS or d.claim not in CLAIMS:
        return [READINESS_DECLARATION_UNKNOWN_VOCABULARY]
    owner = ASSERTED_CLAIMS.get(d.claim, NEUTRAL_CLAIMS.get(d.claim))
    errors = []
    if owner is not None and owner != d.requirement:
        errors.append(READINESS_DECLARATION_REQUIREMENT_MISMATCH)
    if not sim.is_synthetic_label(d.evidence_label):
        errors.append(READINESS_DECLARATION_NOT_SYNTHETIC)
    return errors


def _policy_reference_errors(r) -> list:
    if type(r) is not SyntheticPolicyReference or not _exact_fields(r) or r.schema != POLICY_REFERENCE_SCHEMA:
        return [READINESS_POLICY_REFERENCE_MALFORMED]
    if _flags_forged(r):
        return [READINESS_INVENTORY_FORGED_FLAG]
    if type(r.decision_id) is not str or r.decision_id not in POLICY_DECISION_IDS \
            or type(r.stance) is not str or r.stance not in POLICY_STANCES:
        return [READINESS_POLICY_REFERENCE_MALFORMED]
    return []


def inventory_errors(inventory, outcome) -> tuple:
    """Stable codes; empty when the inventory is exact, canonical, bounded,
    synthetic and bound to `outcome`."""
    if type(inventory) is not SyntheticReadinessInventory:
        return (READINESS_INVENTORY_MALFORMED,)
    if not _exact_fields(inventory):
        return (READINESS_INVENTORY_UNKNOWN_FIELD,)
    if _flags_forged(inventory):
        return (READINESS_INVENTORY_FORGED_FLAG,)
    if inventory.simulation_marker != READINESS_MARKER:
        return (READINESS_INVENTORY_MARKER_MISSING,)
    if inventory.schema != INVENTORY_SCHEMA or type(inventory.inventory_id) is not str \
            or not rha._LABEL_RE.fullmatch(inventory.inventory_id) or type(inventory.declarations) is not tuple \
            or type(inventory.policy_references) is not tuple:
        return (READINESS_INVENTORY_MALFORMED,)
    if len(inventory.declarations) > MAX_DECLARATIONS or len(inventory.policy_references) > len(POLICY_DECISION_IDS):
        return (READINESS_INVENTORY_TOO_LARGE,)
    errors = []
    if type(outcome) is not sim.SimulatedRetirementOutcome or type(inventory.outcome_fingerprint) is not str \
            or inventory.outcome_fingerprint != outcome.fingerprint:
        errors.append(READINESS_INVENTORY_BINDING_MISMATCH)
    declared = rha._timestamp(inventory.declared_at)
    if declared is None or not MIN_DECLARED_AT <= declared < MAX_DECLARED_AT:
        errors.append(READINESS_INVENTORY_TIMESTAMP_INVALID)
    for item in inventory.declarations:
        errors += _declaration_errors(item)
    for item in inventory.policy_references:
        errors += _policy_reference_errors(item)
    if errors:
        return tuple(dict.fromkeys(errors))
    decls, refs = inventory.declarations, inventory.policy_references
    labels = [d.evidence_label for d in decls]
    if len(set(labels)) != len(labels) or len({(d.requirement, d.claim) for d in decls}) != len(decls) \
            or len({r.decision_id for r in refs}) != len(refs):
        return (READINESS_DECLARATION_DUPLICATE,)
    if list(decls) != sorted(decls, key=_declaration_key) \
            or [r.decision_id for r in refs] != sorted((r.decision_id for r in refs), key=POLICY_DECISION_IDS.index):
        return (READINESS_INVENTORY_NOT_CANONICAL,)
    return ()


# ---------------------------------------------------------------------------
# The matrix (pure; one pass in causal order)
# ---------------------------------------------------------------------------

def _implicated(outcome) -> set:
    """Obligations a verified 4F-01 outcome refused at or left uncertain."""
    found = {SIM_CODE_REQUIREMENT[c] for c in outcome.reason_codes if SIM_CODE_REQUIREMENT[c] is not None}
    for step in outcome.step_trace:
        if step.result != sim.STEP_OK:
            found.add(SIM_CODE_REQUIREMENT.get(step.result) or SIM_STEP_REQUIREMENT[step.step])
    return found


def _simulated(outcome, requirement) -> bool:
    value = getattr(outcome, SIMULATED_BY[requirement])
    return value is True or (type(value) is str and value != "")


def _rows(outcome, inventory) -> tuple:
    implicated = _implicated(outcome)
    uncertain = outcome.state == sim.UNCERTAIN_SIMULATED
    refs = inventory.policy_references
    rows, status_of = [], {}
    for req in REQUIREMENTS:
        modeled = req in SIMULATED_BY
        if req == REQ_POLICY_D1_D12:
            status, codes = POLICY_PENDING, [READINESS_POLICY_D1_D12_PENDING]
            if len(refs) != len(POLICY_DECISION_IDS):
                codes.append(READINESS_POLICY_REFERENCES_INCOMPLETE)
            if any(r.stance == POLICY_STANCE_PROPOSED for r in refs):
                codes.append(READINESS_POLICY_PROPOSAL_NOT_APPROVAL)
            if any(r.stance == POLICY_STANCE_CLAIMED_APPROVED for r in refs):
                status = REFUSED
                codes.append(READINESS_UNVERIFIABLE_CLAIM_REFUSED)
        elif modeled and _simulated(outcome, req):
            status, codes = SIMULATED_ONLY, [READINESS_SIMULATED_BY_4F01_ONLY]
        elif modeled:
            status, codes = UNPROVEN, [READINESS_GATE_NOT_REACHED_IN_SIMULATION]
        else:
            status, codes = UNPROVEN, [READINESS_NOT_MODELED_BY_SIMULATION]
        if req == REQ_TRUSTED_CLOCK:
            codes.append(READINESS_CALLER_CLOCK_NOT_TRUSTED)
        if req == REQ_UNCERTAINTY_AND_POSTCONDITION and uncertain:
            # The effect gate was reached and its outcome is unknown: never retried.
            status = UNCERTAIN_RECONCILIATION_REQUIRED
            codes = [READINESS_UNCERTAIN_RECONCILIATION_REQUIRED, READINESS_NO_DESTRUCTIVE_RETRY_AFTER_UNCERTAINTY]
        elif req in implicated:
            status = REFUSED
            codes.append(READINESS_REFUSED_BY_SIMULATION)
        declared = [d for d in inventory.declarations if d.requirement == req]
        for d in declared:
            if d.claim in ASSERTED_CLAIMS:
                # Uncertainty stays uncertain: no claim can replace a reconciliation.
                status = status if status == UNCERTAIN_RECONCILIATION_REQUIRED else REFUSED
                codes.append(READINESS_UNVERIFIABLE_CLAIM_REFUSED)
            else:
                codes.append(_NEUTRAL_CODES[d.claim])
        blocking = tuple(dep for dep in DEPENDENCIES[req] if status_of[dep] in _BLOCKING_STATUSES)
        if blocking and status not in (REFUSED, UNCERTAIN_RECONCILIATION_REQUIRED):
            status = BLOCKED_BY_DEPENDENCY
            codes.append(READINESS_DEPENDENCY_BLOCKED)
        status_of[req] = status
        rows.append(ReadinessRow(
            requirement=req, status=status, simulation_coverage=COVERAGE_MODELED if modeled else COVERAGE_NOT_MODELED,
            reason_codes=tuple(dict.fromkeys(codes)), depends_on=DEPENDENCIES[req], blocking_dependencies=blocking,
            missing_proofs=MISSING_PROOFS[req], declared_evidence=tuple(d.evidence_label for d in declared)))
    return tuple(rows)


def _refused_rows(codes) -> tuple:
    return tuple(ReadinessRow(
        requirement=req, status=REFUSED, simulation_coverage=COVERAGE_MODELED if req in SIMULATED_BY
        else COVERAGE_NOT_MODELED, reason_codes=(READINESS_INPUT_REFUSED,) + tuple(codes),
        depends_on=DEPENDENCIES[req], blocking_dependencies=(), missing_proofs=MISSING_PROOFS[req],
        declared_evidence=()) for req in REQUIREMENTS)


def _report(assessment, outcome, verified, invariant_codes, digest, rows, codes) -> RetirementReadinessReport:
    draft = RetirementReadinessReport(
        schema=REPORT_SCHEMA, simulation_assessment=assessment,
        outcome_state=outcome.state if verified else None,
        outcome_fingerprint=outcome.fingerprint if verified else None, outcome_verified=verified,
        outcome_invariant_codes=tuple(invariant_codes), inventory_digest=digest, rows=rows,
        reason_codes=tuple(dict.fromkeys(list(codes) + list(ALWAYS_CODES))),
        human_reconciliation_required=verified and outcome.state == sim.UNCERTAIN_SIMULATED, fingerprint="")
    return dataclasses.replace(draft, fingerprint=report_fingerprint(draft))


def _refused_report(codes, outcome=None, verified=False, invariant_codes=()) -> RetirementReadinessReport:
    codes = (READINESS_INPUT_REFUSED,) + tuple(c for c in dict.fromkeys(codes) if c != READINESS_INPUT_REFUSED)
    return _report(INPUT_REFUSED, outcome, verified, invariant_codes, None, _refused_rows(codes[1:]), codes)


def evaluate_readiness(outcome, inventory) -> RetirementReadinessReport:
    """The readiness matrix for ONE verified 4F-01 outcome and ONE synthetic
    inventory. Pure and deterministic; never raises; always NOT_LIVE."""
    try:
        errors = outcome_errors(outcome)
        if errors:
            invariants = sim.outcome_invariant_errors(outcome) if type(outcome) is sim.SimulatedRetirementOutcome \
                else ()
            return _refused_report(errors, invariant_codes=invariants)
        errors = inventory_errors(inventory, outcome)
        if errors:
            return _refused_report(errors, outcome, True)
        rows = _rows(outcome, inventory)
        codes = [c for row in rows for c in row.reason_codes]
        if outcome.state == sim.REFUSED_SIMULATED:
            assessment = SIMULATION_REFUSED
        elif outcome.state == sim.UNCERTAIN_SIMULATED:
            assessment = SIMULATION_UNCERTAIN
        elif any(row.status in _BLOCKING_STATUSES for row in rows):
            assessment = SIMULATION_GAPS_REFUSED
        else:
            assessment = SIMULATION_PRECONDITIONS_MODELED
        return _report(assessment, outcome, True, (), inventory_digest(inventory), rows, codes)
    except Exception:  # noqa: BLE001 - never escape; an unexplained input is refused
        return _refused_report((READINESS_INTERNAL_ERROR,))


# ---------------------------------------------------------------------------
# Report invariants
# ---------------------------------------------------------------------------

def readiness_report_invariant_errors(report) -> tuple:
    """Stable codes of every violated report invariant (empty when sound)."""
    if type(report) is not RetirementReadinessReport or not _exact_fields(report) or type(report.rows) is not tuple \
            or not all(type(r) is ReadinessRow and _exact_fields(r) for r in report.rows):
        return ("RINV_MALFORMED",)
    r, errors = report, []
    try:
        if r.fingerprint != report_fingerprint(r):
            errors.append("RINV_FINGERPRINT")
    except Exception:  # noqa: BLE001
        errors.append("RINV_FINGERPRINT")
    if r.schema != REPORT_SCHEMA or r.simulation_assessment not in ASSESSMENTS:
        errors.append("RINV_SCHEMA")
    if any(getattr(r, name) != value or type(getattr(r, name)) is not type(value) for name, value in
           _FIXED_REPORT_FIELDS) or any(getattr(row, name) != value or type(getattr(row, name)) is not type(value)
                                        for row in r.rows for name, value in _FIXED_ROW_FLAGS):
        errors.append("RINV_NOT_LIVE")
    if tuple(row.requirement for row in r.rows) != REQUIREMENTS or any(
            row.status not in STATUSES or row.depends_on != DEPENDENCIES[row.requirement]
            or row.missing_proofs != MISSING_PROOFS[row.requirement] or not row.missing_proofs
            or type(row.reason_codes) is not tuple or not set(row.reason_codes) <= set(REASON_CODES)
            or type(row.blocking_dependencies) is not tuple
            or not set(row.blocking_dependencies) <= set(row.depends_on) for row in r.rows):
        errors.append("RINV_MATRIX")
    codes = r.reason_codes
    if type(codes) is not tuple or len(set(codes)) != len(codes) or not set(codes) <= set(REASON_CODES) \
            or not set(ALWAYS_CODES) <= set(codes):
        errors.append("RINV_REASON_CODES")
    if r.simulation_assessment == INPUT_REFUSED:
        if any(row.status != REFUSED for row in r.rows) or READINESS_INPUT_REFUSED not in codes:
            errors.append("RINV_INPUT_REFUSED")
    elif r.outcome_verified is not True or r.outcome_state not in sim.TERMINAL_STATES:
        errors.append("RINV_OUTCOME")
    status = {row.requirement: row.status for row in r.rows} if not errors else {}
    if status and status[REQ_POLICY_D1_D12] not in (POLICY_PENDING, REFUSED):
        errors.append("RINV_POLICY")
    uncertain = r.outcome_state == sim.UNCERTAIN_SIMULATED
    if r.human_reconciliation_required is not uncertain or (
            uncertain and status and r.simulation_assessment != INPUT_REFUSED
            and status[REQ_UNCERTAINTY_AND_POSTCONDITION] != UNCERTAIN_RECONCILIATION_REQUIRED):
        errors.append("RINV_UNCERTAIN")
    if r.simulation_assessment == SIMULATION_PRECONDITIONS_MODELED and (
            r.outcome_state != sim.COMPLETED_SIMULATED or any(s in _BLOCKING_STATUSES for s in status.values())):
        errors.append("RINV_ASSESSMENT")
    return tuple(errors)


def verify_readiness_report(report) -> bool:
    """True only if every report invariant holds. A sound report is still NOT_LIVE."""
    return readiness_report_invariant_errors(report) == ()
