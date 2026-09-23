"""Runner V2.1 (R21-D) factory governance: ownership, module lifecycle and
handoff contracts, layered on top of the R21-C factory ledger.

This is provider-neutral policy plumbing for a future multi-module "Fabric":
nothing here decides WHICH provider owns/builds/closes a module, or WHICH
class a module belongs to - that is `OwnershipPolicy`, supplied by the
caller (manifest/policy), never invented here. The engine only knows about
generic roles (`OWNER`/`BUILDER`/`CONTRIBUTOR`/`AUDITOR`/`CLOSER`) and a
generic lifecycle (`PLANNED` .. `CLOSED`); "role=BUILDER provider=codex" is
the shape everywhere, never a state named e.g. `BUILDING_CODEX`.

Why this does not extend `runner_factory_ledger`'s own schema
---------------------------------------------------------------
The ledger's top-level `state`/`state_reason` fields are already owned by
worker-attempt outcomes (`WorkerState` values written by
`runner_pipeline.PipelineRunner`, e.g. SUCCESS/FAILED/PARTIAL - see that
module's `MODULE_STATE_CHANGED` usage). A module going through this
lifecycle can simultaneously have ordinary worker attempts recorded against
it, so this module deliberately never writes lifecycle values into the
ledger's shared `state` field - that would let an unrelated worker attempt's
outcome silently clobber (or be clobbered by) a lifecycle transition when
`materialize_modules` folds them in append order. Instead every lifecycle
transition is carried in `extra["lifecycle_state"]`, a namespace the ledger
never reads itself, and is read back here via `materialize_module_governance`
- a completely separate, deterministic fold, mirroring
`runner_factory_ledger.materialize_modules` but never touching it or its
output. The ledger's own event types/fields are reused as-is (`role`,
`provider`, `certification_status`, `closer`, ...) with zero schema changes.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    from scripts.ai import runner_factory_ledger as flog
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_factory_ledger as flog  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Roles (provider-neutral; providers are policy data, not state names)
# ---------------------------------------------------------------------------

class Role(str, Enum):
    OWNER = "OWNER"
    BUILDER = "BUILDER"
    CONTRIBUTOR = "CONTRIBUTOR"
    AUDITOR = "AUDITOR"
    CLOSER = "CLOSER"


ROLES = frozenset(r.value for r in Role)


# ---------------------------------------------------------------------------
# Module classification - policy data, never decided by this engine.
# ---------------------------------------------------------------------------

MODULE_CLASS_BUSINESS = "BUSINESS"
MODULE_CLASS_PLATFORM = "PLATFORM"
MODULE_CLASS_SAFETY_CRITICAL = "SAFETY_CRITICAL"


# ---------------------------------------------------------------------------
# Module lifecycle (provider-neutral; distinct from `runner_pipeline
# .WorkerState`, which is worker-attempt runtime state, not module lifecycle)
# ---------------------------------------------------------------------------

class ModuleLifecycleState(str, Enum):
    PLANNED = "PLANNED"
    ARCHITECTED = "ARCHITECTED"
    BUILDING = "BUILDING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    AUDITING = "AUDITING"
    CERTIFYING = "CERTIFYING"
    CLOSED = "CLOSED"
    REWORK_REQUIRED = "REWORK_REQUIRED"


_L = ModuleLifecycleState

TERMINAL_LIFECYCLE_STATES = frozenset({_L.CLOSED})

# What a module may become next. `None` (no lifecycle event yet) may only
# move to PLANNED. CLOSED is reachable ONLY from CERTIFYING - a successful
# builder handoff (READY_FOR_REVIEW) or a passed audit (CERTIFYING) never
# implies closure by itself; closure is always its own explicit event.
LIFECYCLE_TRANSITIONS = {
    _L.PLANNED: frozenset({_L.ARCHITECTED}),
    _L.ARCHITECTED: frozenset({_L.BUILDING}),
    _L.BUILDING: frozenset({_L.READY_FOR_REVIEW, _L.REWORK_REQUIRED}),
    _L.READY_FOR_REVIEW: frozenset({_L.AUDITING, _L.REWORK_REQUIRED}),
    _L.AUDITING: frozenset({_L.CERTIFYING, _L.REWORK_REQUIRED}),
    _L.CERTIFYING: frozenset({_L.CLOSED, _L.REWORK_REQUIRED}),
    _L.REWORK_REQUIRED: frozenset({_L.BUILDING}),
    _L.CLOSED: frozenset(),
}

# Which role(s) may DRIVE a given transition. Fixed lifecycle semantics (the
# same for every module/provider - not product policy): a BUILDER builds, an
# AUDITOR audits, a CLOSER closes. `OwnershipPolicy` separately decides WHICH
# provider may hold each role for a given module.
_TRANSITION_ROLES = {
    (None, _L.PLANNED): frozenset({Role.OWNER.value}),
    (_L.PLANNED, _L.ARCHITECTED): frozenset({Role.OWNER.value}),
    (_L.ARCHITECTED, _L.BUILDING): frozenset({Role.OWNER.value, Role.BUILDER.value}),
    (_L.BUILDING, _L.READY_FOR_REVIEW): frozenset({Role.BUILDER.value}),
    (_L.BUILDING, _L.REWORK_REQUIRED): frozenset({Role.BUILDER.value, Role.OWNER.value}),
    (_L.READY_FOR_REVIEW, _L.AUDITING): frozenset({Role.AUDITOR.value, Role.OWNER.value}),
    (_L.READY_FOR_REVIEW, _L.REWORK_REQUIRED): frozenset({Role.AUDITOR.value, Role.OWNER.value}),
    (_L.AUDITING, _L.CERTIFYING): frozenset({Role.AUDITOR.value}),
    (_L.AUDITING, _L.REWORK_REQUIRED): frozenset({Role.AUDITOR.value}),
    (_L.CERTIFYING, _L.CLOSED): frozenset({Role.CLOSER.value}),
    (_L.CERTIFYING, _L.REWORK_REQUIRED): frozenset({Role.AUDITOR.value, Role.OWNER.value}),
    (_L.REWORK_REQUIRED, _L.BUILDING): frozenset({Role.BUILDER.value, Role.OWNER.value}),
}

# Ledger event family used to carry each lifecycle transition. Reuses R21-C's
# existing event types (no ledger schema change); CLOSED is the only state
# that also sets the ledger's own `closer` field, matching R21-C's existing
# MODULE_CLOSED contract.
_EVENT_TYPE_FOR_STATE = {
    _L.PLANNED: flog.MODULE_STATE_CHANGED,
    _L.ARCHITECTED: flog.MODULE_STATE_CHANGED,
    _L.BUILDING: flog.MODULE_STATE_CHANGED,
    _L.READY_FOR_REVIEW: flog.MODULE_STATE_CHANGED,
    _L.AUDITING: flog.CERTIFICATION_STARTED,
    _L.CERTIFYING: flog.CERTIFICATION_FINISHED,
    _L.REWORK_REQUIRED: flog.MODULE_STATE_CHANGED,
    _L.CLOSED: flog.MODULE_CLOSED,
}

_MAX_REF_LEN = 300
_MAX_REFS = 20


class ModuleGovernanceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Ownership contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OwnershipPolicy:
    """Per-module governance policy. Entirely caller-supplied (manifest/
    Fabric policy): this engine never decides these values, only enforces
    them. `owner_provider`/`builder_provider`/`closer_provider` name the
    single provider permitted to hold that role; unset means "nobody" for
    OWNER/CLOSER (both must be explicitly designated) and "unrestricted" for
    BUILDER/AUDITOR (no policy opinion = no restriction).
    """

    module: str
    module_version: Optional[str] = None
    module_class: Optional[str] = None
    owner_provider: Optional[str] = None
    builder_provider: Optional[str] = None
    closer_provider: Optional[str] = None
    allowed_contributors: tuple = ()
    allowed_auditors: tuple = ()

    def __post_init__(self):
        if not isinstance(self.module, str) or not self.module.strip():
            raise ModuleGovernanceError("INVALID_MODULE", "module must be a non-empty string")

    def permitted_providers(self, role: str) -> Optional[frozenset]:
        """`None` = policy does not restrict this role (any provider
        permitted). A `frozenset` (possibly empty) = an explicit allow-list;
        empty means nobody is currently permitted."""
        if role == Role.OWNER.value:
            return frozenset({self.owner_provider}) if self.owner_provider else frozenset()
        if role == Role.CLOSER.value:
            return frozenset({self.closer_provider}) if self.closer_provider else frozenset()
        if role == Role.BUILDER.value:
            return frozenset({self.builder_provider}) if self.builder_provider else None
        if role == Role.CONTRIBUTOR.value:
            return frozenset(self.allowed_contributors)
        if role == Role.AUDITOR.value:
            return frozenset(self.allowed_auditors) if self.allowed_auditors else None
        return None


def is_role_permitted(policy: OwnershipPolicy, provider: str, role: str) -> bool:
    if role not in ROLES:
        raise ModuleGovernanceError("UNKNOWN_ROLE", f"unknown role {role!r}")
    permitted = policy.permitted_providers(role)
    return permitted is None or provider in permitted


# ---------------------------------------------------------------------------
# Handoff contract (versioned, reference-only payload)
# ---------------------------------------------------------------------------

HANDOFF_SCHEMA_VERSION = 1


def _validate_short_ref_list(name: str, values) -> tuple:
    if not isinstance(values, (list, tuple)):
        raise ModuleGovernanceError("INVALID_HANDOFF_FIELD", f"{name} must be a list of short strings")
    if len(values) > _MAX_REFS:
        raise ModuleGovernanceError("TOO_MANY_HANDOFF_REFS", f"{name} exceeds {_MAX_REFS} entries")
    cleaned = []
    for v in values:
        if not isinstance(v, str) or not v.strip():
            raise ModuleGovernanceError("INVALID_HANDOFF_FIELD", f"{name} entries must be non-empty strings")
        if len(v) > _MAX_REF_LEN:
            raise ModuleGovernanceError(
                "HANDOFF_REF_TOO_LARGE",
                f"{name} entry exceeds {_MAX_REF_LEN} chars - a handoff carries references, not transcripts",
            )
        cleaned.append(v)
    return tuple(cleaned)


@dataclass(frozen=True)
class HandoffRecord:
    """Versioned BUILDER -> READY_FOR_REVIEW -> AUDITOR/CLOSER handoff.
    Carries references (a commit, short evidence pointers, short debt notes)
    - never prompts/transcripts/stdout."""

    schema_version: int
    module: str
    module_version: Optional[str]
    pipeline_id: Optional[str]
    worker_id: Optional[str]
    from_role: str
    to_role: str
    checkpoint_commit: Optional[str]
    evidence_refs: tuple
    known_debt: tuple
    requested_next_role: str
    created_at_utc: str

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version, "module": self.module, "module_version": self.module_version,
            "pipeline_id": self.pipeline_id, "worker_id": self.worker_id, "from_role": self.from_role,
            "to_role": self.to_role, "checkpoint_commit": self.checkpoint_commit,
            "evidence_refs": list(self.evidence_refs), "known_debt": list(self.known_debt),
            "requested_next_role": self.requested_next_role, "created_at_utc": self.created_at_utc,
        }


def build_handoff(
    *, module: str, from_role: str, to_role: str, requested_next_role: str, created_at_utc: str,
    module_version: Optional[str] = None, pipeline_id: Optional[str] = None, worker_id: Optional[str] = None,
    checkpoint_commit: Optional[str] = None, evidence_refs=(), known_debt=(),
) -> HandoffRecord:
    for label, role in (("from_role", from_role), ("to_role", to_role), ("requested_next_role", requested_next_role)):
        if role not in ROLES:
            raise ModuleGovernanceError("UNKNOWN_ROLE", f"unknown {label} {role!r}")
    if not isinstance(module, str) or not module.strip():
        raise ModuleGovernanceError("INVALID_MODULE", "module must be a non-empty string")
    return HandoffRecord(
        schema_version=HANDOFF_SCHEMA_VERSION, module=module, module_version=module_version,
        pipeline_id=pipeline_id, worker_id=worker_id, from_role=from_role, to_role=to_role,
        checkpoint_commit=checkpoint_commit,
        evidence_refs=_validate_short_ref_list("evidence_refs", evidence_refs),
        known_debt=_validate_short_ref_list("known_debt", known_debt),
        requested_next_role=requested_next_role, created_at_utc=created_at_utc,
    )


# ---------------------------------------------------------------------------
# Governance engine: ownership-checked lifecycle transitions over a
# `FactoryLedger`, integrating with the R21-C factory history.
# ---------------------------------------------------------------------------

class ModuleGovernance:
    def __init__(self, ledger: "flog.FactoryLedger", *, clock=None):
        self.ledger = ledger
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- reads ----------------------------------------------------------

    def _module_events(self, module: str, module_version: Optional[str]) -> list:
        events = self.ledger.events(module=module)
        return [e for e in events if e.get("module_version") == module_version]

    def current_lifecycle_state(self, module: str, module_version: Optional[str] = None) -> Optional[ModuleLifecycleState]:
        value = None
        for event in self._module_events(module, module_version):
            extra = event.get("extra") or {}
            lifecycle_state = extra.get("lifecycle_state")
            if lifecycle_state is not None:
                value = lifecycle_state
        return ModuleLifecycleState(value) if value else None

    def history(self, module: str, module_version: Optional[str] = None) -> list:
        return self._module_events(module, module_version)

    def status(self, module: str, module_version: Optional[str] = None) -> dict:
        events = self._module_events(module, module_version)
        return materialize_module_governance(events).get(
            _governance_key(module, module_version),
            {"module": module, "module_version": module_version, "lifecycle_state": None},
        )

    # -- writes -----------------------------------------------------------

    def _transition(
        self, policy: OwnershipPolicy, *, provider: str, role: str, to_state: ModuleLifecycleState,
        module_version: Optional[str] = None, pipeline_id: Optional[str] = None, worker_id: Optional[str] = None,
        reason: Optional[str] = None, certification_status: Optional[str] = None, closer: Optional[str] = None,
        extra_overrides: Optional[dict] = None,
    ) -> dict:
        if module_version is None:
            module_version = policy.module_version
        if role not in ROLES:
            raise ModuleGovernanceError("UNKNOWN_ROLE", f"unknown role {role!r}")
        if not is_role_permitted(policy, provider, role):
            raise ModuleGovernanceError(
                "ROLE_NOT_PERMITTED",
                f"provider {provider!r} is not permitted to act as {role} for module {policy.module!r}",
            )
        current = self.current_lifecycle_state(policy.module, module_version)
        allowed_targets = LIFECYCLE_TRANSITIONS[current] if current is not None else frozenset({_L.PLANNED})
        if to_state not in allowed_targets:
            raise ModuleGovernanceError(
                "ILLEGAL_LIFECYCLE_TRANSITION",
                f"module {policy.module!r}: {current.value if current else 'NONE'} -> {to_state.value} "
                "is not a valid lifecycle transition",
            )
        allowed_roles = _TRANSITION_ROLES.get((current, to_state))
        if allowed_roles is not None and role not in allowed_roles:
            raise ModuleGovernanceError(
                "ROLE_NOT_PERMITTED_FOR_TRANSITION",
                f"role {role} may not drive {current.value if current else 'NONE'} -> {to_state.value} "
                f"(requires one of {sorted(allowed_roles)})",
            )

        extra = {
            "lifecycle_state": to_state.value,
            "module_class": policy.module_class,
            "owner_provider": policy.owner_provider,
            "builder_provider": policy.builder_provider,
            "closer_provider": policy.closer_provider,
        }
        if policy.allowed_contributors:
            extra["allowed_contributors"] = list(policy.allowed_contributors)
        if reason:
            extra["lifecycle_reason"] = reason
        if extra_overrides:
            extra.update(extra_overrides)
        extra = {k: v for k, v in extra.items() if v is not None}

        fields = dict(
            module=policy.module, module_version=module_version, provider=provider, role=role,
            pipeline_id=pipeline_id, worker_id=worker_id,
        )
        if to_state == _L.CERTIFYING:
            fields["certification_status"] = certification_status or "PASSED"
        if to_state == _L.CLOSED:
            fields["closer"] = closer or provider

        return self.ledger.append(_EVENT_TYPE_FOR_STATE[to_state], extra=extra, **fields)

    def plan(self, policy: OwnershipPolicy, *, provider: str, role: str = Role.OWNER.value, **kw) -> dict:
        return self._transition(policy, provider=provider, role=role, to_state=_L.PLANNED, **kw)

    def architect(self, policy: OwnershipPolicy, *, provider: str, role: str = Role.OWNER.value, **kw) -> dict:
        return self._transition(policy, provider=provider, role=role, to_state=_L.ARCHITECTED, **kw)

    def start_building(self, policy: OwnershipPolicy, *, provider: str, role: str = Role.BUILDER.value, **kw) -> dict:
        return self._transition(policy, provider=provider, role=role, to_state=_L.BUILDING, **kw)

    def start_audit(self, policy: OwnershipPolicy, *, provider: str, role: str = Role.AUDITOR.value, **kw) -> dict:
        return self._transition(policy, provider=provider, role=role, to_state=_L.AUDITING, **kw)

    def certify(
        self, policy: OwnershipPolicy, *, provider: str, role: str = Role.AUDITOR.value,
        certification_status: str = "PASSED", **kw,
    ) -> dict:
        return self._transition(
            policy, provider=provider, role=role, to_state=_L.CERTIFYING,
            certification_status=certification_status, **kw,
        )

    def close(self, policy: OwnershipPolicy, *, provider: str, role: str = Role.CLOSER.value, closer: Optional[str] = None, **kw) -> dict:
        return self._transition(policy, provider=provider, role=role, to_state=_L.CLOSED, closer=closer, **kw)

    def request_rework(self, policy: OwnershipPolicy, *, provider: str, role: str, reason: Optional[str] = None, **kw) -> dict:
        return self._transition(policy, provider=provider, role=role, to_state=_L.REWORK_REQUIRED, reason=reason, **kw)

    def request_handoff(
        self, policy: OwnershipPolicy, *, provider: str, from_role: str = Role.BUILDER.value,
        to_role: str = Role.AUDITOR.value, requested_next_role: str = Role.AUDITOR.value,
        module_version: Optional[str] = None, pipeline_id: Optional[str] = None, worker_id: Optional[str] = None,
        checkpoint_commit: Optional[str] = None, evidence_refs=(), known_debt=(),
    ) -> HandoffRecord:
        """BUILDER -> READY_FOR_REVIEW -> AUDITOR/CLOSER: records a versioned
        handoff (references only) as part of the READY_FOR_REVIEW transition
        so the ledger's event chain and the handoff record share one event."""
        if module_version is None:
            module_version = policy.module_version
        handoff = build_handoff(
            module=policy.module, module_version=module_version, pipeline_id=pipeline_id, worker_id=worker_id,
            from_role=from_role, to_role=to_role, checkpoint_commit=checkpoint_commit,
            evidence_refs=evidence_refs, known_debt=known_debt, requested_next_role=requested_next_role,
            created_at_utc=_iso(self._clock()),
        )
        self._transition(
            policy, provider=provider, role=from_role, to_state=_L.READY_FOR_REVIEW,
            module_version=module_version, pipeline_id=pipeline_id, worker_id=worker_id,
            extra_overrides={"handoff": handoff.to_dict()},
        )
        return handoff


# ---------------------------------------------------------------------------
# Pure read-side fold (mirrors `runner_factory_ledger.materialize_modules`
# in spirit; deliberately separate output/namespace - see module docstring).
# ---------------------------------------------------------------------------

def _governance_key(module: str, module_version: Optional[str]) -> str:
    return f"{module}@{module_version}" if module_version else module


def materialize_module_governance(events: list) -> dict:
    """Deterministic module governance state folded from events IN ORDER.
    Events without `module` or without `extra.lifecycle_state` contribute no
    lifecycle change, but non-lifecycle governance fields (certification
    status, closer) are still folded when present."""
    modules: dict = {}
    for event in events:
        module = event.get("module")
        if not module:
            continue
        key = _governance_key(module, event.get("module_version"))
        slot = modules.setdefault(key, {
            "module": module, "module_version": event.get("module_version"), "lifecycle_state": None,
            "module_class": None, "owner_provider": None, "builder_provider": None, "closer_provider": None,
            "allowed_contributors": [], "certification_status": None, "closer": None,
            "last_event_utc": None, "last_event_type": None, "event_count": 0,
        })
        slot["event_count"] += 1
        slot["last_event_utc"] = event.get("timestamp_utc")
        slot["last_event_type"] = event.get("event_type")
        extra = event.get("extra") or {}
        lifecycle_state = extra.get("lifecycle_state")
        if lifecycle_state is not None:
            slot["lifecycle_state"] = lifecycle_state
        for name in ("module_class", "owner_provider", "builder_provider", "closer_provider"):
            if extra.get(name) is not None:
                slot[name] = extra[name]
        if extra.get("allowed_contributors") is not None:
            slot["allowed_contributors"] = list(extra["allowed_contributors"])
        if event.get("certification_status") is not None:
            slot["certification_status"] = event["certification_status"]
        if event.get("closer") is not None:
            slot["closer"] = event["closer"]
    return modules
