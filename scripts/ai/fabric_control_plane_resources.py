"""FCP-11E-05: Fabric Control Plane view of providers, quota, cost and capacity -
read-only, bounded, deterministic, fail-closed, CONSULTATIVE / OBSERVATION-ONLY.

Composes ONE FCP-11B-02 `ControlPlaneSnapshot` (what the Runner recorded per
worker: state, provider, `provider_condition`, `next_eligible_utc`) with, at
most, ONE FCP-10D-01 quota report (`fabric_resource_quota_report`): either an
already-produced, sealed report dict, or the governed `run_report` over one
explicit input document the operator already holds (same admission /
`read_input_bytes` / strict JSON discipline, same engines A02 / C02 / B02).
Nothing is probed, priced, estimated, retried, switched, bought or written.

Public schema (`ControlPlaneResources.to_dict`)
-----------------------------------------------
Per worker (`WorkerResource`): `pipeline_id`, `worker_id`, `provider_id` /
`requested_provider_id` (opaque labels), `lifecycle` / `runner_outcome` (the
contract's derivation), `agreement` (FCP-11B-02), `hold` (QUOTA_WAIT /
AUTH_HOLD / NONE / UNKNOWN), `recorded_provider_condition`,
`condition_scope` (ACTIVE_HOLD / RECORDED_ONLY / None),
`recorded_next_eligible_utc` and `anomalies`.
Per provider (`ProviderResource`): `provider_id`, `worker_refs`,
`quota_wait_workers` / `auth_hold_workers` / `unknown_hold_workers`, `quota`
(the report's A02 view, allowlisted, or None), `capacity_condition`
(KNOWN / UNKNOWN), `capacity`, `proven_slots`, `capacity_reasons`,
`advisory` (the report's C02 decision: status / actor / action / reasons -
information, never a permit), `cost_condition`, `cost_reasons`, `costs`.
Per cost (`CostView`): `limit_id`, `scope`, `provider_id`, `currency`,
`condition`, `basis` (OBSERVED / INCLUDES_HOST_ESTIMATE / None), the exact
decimal strings `maximum` / `observed` / `estimated_low` / `estimated_high` /
`accounted` / `uncertainty` / `remaining` (only when KNOWN), `reasons`,
`evidence_ids` (receipt ids) and `provenance` (the B02 schema / fingerprint
/ sha256 and the report's sha256).
Top level: `snapshot_revision`, `observed_at_utc`, `snapshot_complete`,
`report_condition` / `report_cause` / `report_code` / `report_actor`,
`report_sha256`, `report_as_of_utc`, `report_status`, `report_anomalies`,
`rejected_report_entries`, `unattributed_workers`, `providers`, `workers`,
`global_cost_condition`, `global_cost_reasons`, `global_costs`,
`not_authorized_actions`, the zero-authority flags and `revision`.
Never public: any path (the report file's included), provider prose,
messages, tariffs / rates, receipts' quantities, execution ids, the report's
`next_safe_step(s)` and every other native field.

Decisions
---------
* Director and Runner keep ALL execution, recovery, authorization, Git,
  process and resource authority. No clock (the instant is the snapshot's
  `observed_at_utc`), environment, network, provider API, process, Git or
  store; FCP-11A-01 zero-authority flags plus `provider_api_called`,
  `remote_probe_made`, `charge_made`, `purchase_allowed`, `price_generated`
  and `time_estimated`, all False.
* Reuse, never redefine: worker facts are the contract's `WorkerView` (only
  validated, allowlisted fields), holds are the Runner's own hold states
  (`WAITING_PROVIDER_QUOTA` / `BLOCKED_PROVIDER_AUTH`) and conditions
  (`ProviderCondition`), quota / capacity / freshness / certainty are A02's,
  advice is C02's (`ACTORS` / `ACTIONS` / report `STATUSES`), money is B02's
  (`_money_text`, exact contexts) and the report is FCP-10D-01's
  (`run_report`, `verify_report`, `SCHEMA`, `NOT_AUTHORIZED_ACTIONS`).
* Separate axes, never merged: a worker's `runner_outcome` is never lowered by
  a quota condition (a SUCCESS worker that once hit quota stays SUCCESS with
  `condition_scope` RECORDED_ONLY) and a provider's quota never raises a
  worker. `hold` is shown only from a PRESENT worker state whose FCP-11B-02
  `agreement` is CONSISTENT; otherwise UNKNOWN.
* Capacity is KNOWN only for a PRESENT report whose A02 view of the provider
  is CERTAIN, FRESH and AVAILABLE / FULL, and whose `as_of_utc` is not after
  the snapshot (nor older than `max_report_age_seconds` when given). Stale or
  doubtful evidence is UNKNOWN and `proven_slots` is withheld (A02 itself
  still lists the slots of stale evidence).
* Cost is KNOWN only per B02 COST account with no doubt reason whose decimal
  strings re-parse exactly, sit on the policy granularity and satisfy B02's
  own relations (accounted = observed + estimated_high, uncertainty =
  high - low, remaining = max(maximum - accounted, 0)); otherwise UNKNOWN with
  the reasons (TARIFF_MISSING, USAGE_UNKNOWN, NO_COST_EVIDENCE ...). Money is
  never a float, never converted, never apportioned: GLOBAL accounts stay
  global and a provider without a provider-scoped COST account is UNKNOWN.
* Time is never estimated: `next_eligible_utc` values are the Runner's / A02's
  recorded instants, verbatim, and are never compared with the observation
  instant to claim eligibility, an ETA or a remaining wait.
* Provider labels are opaque: only ids matching the scheduler's provider-id
  shape and not credential-shaped are shown; others are counted, never named.
* Absence is never success: no report is MISSING / SOURCE_ABSENT, a refused
  one is UNAVAILABLE or CORRUPT with its fixed FCP-10D-01 `REPORT_*` code.

Limitations (documented, not implemented here)
----------------------------------------------
* Token / unit budgets (non-COST B02 accounts) and the report's reservation
  figures are not projected; only money is presented as cost.
* Workers present on disk but absent from `pipeline_result.json` carry no
  provider fields in the contract and are only counted
  (`unattributed_workers`), as are listed workers with no provider id.
* The report's input document is the operator's; its correspondence with the
  snapshot's Runner root is not proven (only instants are compared).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

try:
    from scripts.ai import fabric_control_plane_contract as cp
    from scripts.ai import fabric_control_plane_snapshot as snap
    from scripts.ai import fabric_resource_quota_budget as bg
    from scripts.ai import fabric_resource_quota_contract as qc
    from scripts.ai import fabric_resource_quota_observation as qo
    from scripts.ai import fabric_resource_quota_recovery as rq
    from scripts.ai import fabric_resource_quota_report as qrep
    from scripts.ai import fabric_scheduler_contract as sc
    from scripts.ai import runner_pipeline as rp
    from scripts.ai import runner_provider_availability as availability
except ImportError:  # pragma: no cover - direct script execution
    import fabric_control_plane_contract as cp  # type: ignore[no-redef]
    import fabric_control_plane_snapshot as snap  # type: ignore[no-redef]
    import fabric_resource_quota_budget as bg  # type: ignore[no-redef]
    import fabric_resource_quota_contract as qc  # type: ignore[no-redef]
    import fabric_resource_quota_observation as qo  # type: ignore[no-redef]
    import fabric_resource_quota_recovery as rq  # type: ignore[no-redef]
    import fabric_resource_quota_report as qrep  # type: ignore[no-redef]
    import fabric_scheduler_contract as sc  # type: ignore[no-redef]
    import runner_pipeline as rp  # type: ignore[no-redef]
    import runner_provider_availability as availability  # type: ignore[no-redef]

SCHEMA = "fcp11e05-control-plane-resources-v1"
SCHEMA_VERSION = 1

MAX_PROVIDERS = qo.MAX_PROVIDERS
MAX_REPORT_AGE_SECONDS = qo.MAX_AGE_SECONDS
MAX_MONEY_CHARS = 40

KNOWN, UNKNOWN = "KNOWN", cp.OUTCOME_UNKNOWN
KNOWLEDGE = (KNOWN, UNKNOWN)

HOLD_QUOTA_WAIT = "QUOTA_WAIT"
HOLD_AUTH = "AUTH_HOLD"
HOLD_NONE = "NONE"
HOLD_UNKNOWN = UNKNOWN
HOLDS = (HOLD_QUOTA_WAIT, HOLD_AUTH, HOLD_NONE, HOLD_UNKNOWN)
# The Runner's own hold states and the condition each one is recorded with.
_HOLD_OF_STATE = {rp.WorkerState.WAITING_PROVIDER_QUOTA.value: HOLD_QUOTA_WAIT,
                  rp.WorkerState.BLOCKED_PROVIDER_AUTH.value: HOLD_AUTH}
_CONDITION_OF_HOLD = {HOLD_QUOTA_WAIT: availability.ProviderCondition.QUOTA_EXHAUSTED.value,
                      HOLD_AUTH: availability.ProviderCondition.AUTH_BLOCKED.value}

SCOPE_ACTIVE_HOLD = "ACTIVE_HOLD"
SCOPE_RECORDED_ONLY = "RECORDED_ONLY"

BASIS_OBSERVED = "OBSERVED"
BASIS_INCLUDES_HOST_ESTIMATE = "INCLUDES_HOST_ESTIMATE"

# Local reason / anomaly codes (everything else is an engine's own code).
HOLD_CONDITION_MISMATCH = "HOLD_CONDITION_MISMATCH"
WORKER_STATUS_DIVERGENT = "WORKER_STATUS_DIVERGENT"
WORKER_ANOMALIES = (HOLD_CONDITION_MISMATCH, WORKER_STATUS_DIVERGENT)
REPORT_ABSENT = "REPORT_ABSENT"
REPORT_AFTER_OBSERVATION = "REPORT_AFTER_OBSERVATION"
REPORT_STALE = "REPORT_STALE"
REPORT_ANOMALIES = (REPORT_AFTER_OBSERVATION, REPORT_STALE)
QUOTA_EVIDENCE_ABSENT = "QUOTA_EVIDENCE_ABSENT"
NO_COST_EVIDENCE = "NO_COST_EVIDENCE"
NO_COST_LIMIT = "NO_COST_LIMIT"
COST_FIGURES_INCONSISTENT = "COST_FIGURES_INCONSISTENT"

COST_SOURCE = "FCP10B02_BUDGET_EVALUATION"
NOT_AUTHORIZED_ACTIONS = qrep.NOT_AUTHORIZED_ACTIONS

_MONEY_RE = re.compile(r"(0|[1-9][0-9]*)(\.[0-9]+)?")
_MONEY_FIELDS = ("maximum", "observed", "estimated_low", "estimated_high", "accounted", "uncertainty", "remaining")
_QUOTA_FIELDS = ("availability", "capacity", "certainty", "freshness", "proven_slots", "next_eligible_utc",
                 "eligibility_source", "reasons", "evidence_ids")
_KNOWN_CAPACITY = ("AVAILABLE", "FULL")
_REPORT_KEYS = frozenset({"quota", "budget", "decisions", "sources", "status", "as_of_utc", "authority"})

# FCP-10D-01 refusal code -> contract cause (the path / read ones are
# FCP-11B-02's mapping; parse / schema / engine refusals are CORRUPT).
_REPORT_CAUSES = {
    **snap._REFUSAL_CAUSES,
    "REPORT_INPUT_NOT_UTF8": cp.SOURCE_NOT_JSON, "REPORT_INPUT_JSON_INVALID": cp.SOURCE_NOT_JSON,
    "REPORT_INPUT_DUPLICATE_KEY": cp.SOURCE_NOT_JSON, "REPORT_INPUT_NUMBER_FORBIDDEN": cp.SOURCE_NOT_JSON,
    "REPORT_INPUT_STRING_INVALID": cp.SOURCE_NOT_JSON, "REPORT_OUTPUT_TOO_LARGE": cp.SOURCE_TOO_LARGE,
    "REPORT_INPUT_SCHEMA_UNSUPPORTED": cp.SCHEMA_UNSUPPORTED, "REPORT_INPUT_FIELD_UNKNOWN": cp.SCHEMA_UNSUPPORTED,
    "REPORT_INPUT_FIELD_MISSING": cp.SCHEMA_UNSUPPORTED, "REPORT_INPUT_SHAPE_INVALID": cp.SCHEMA_UNSUPPORTED,
    "REPORT_QUOTA_REFUSED": cp.FIELD_MALFORMED, "REPORT_RECOVERY_REFUSED": cp.FIELD_MALFORMED,
    "REPORT_BUDGET_REFUSED": cp.FIELD_MALFORMED, "REPORT_INTERNAL_ERROR": cp.SOURCE_UNREADABLE,
}


def valid_provider_label(value) -> bool:
    """An opaque provider label: scheduler provider-id shape, not credential-shaped."""
    return sc._valid_provider_id(value) and not cp._secret_shaped(value)


def _codes(values) -> Optional[tuple]:
    if type(values) is not list or not all(cp.valid_code(v) for v in values):
        return None
    return tuple(values)


def _ids(values) -> Optional[tuple]:
    if type(values) is not list or not all(qc._valid_id(v) and not qc._secret_shaped(v) for v in values):
        return None
    return tuple(sorted(set(values)))


# ---------------------------------------------------------------------------
# Guarantees
# ---------------------------------------------------------------------------

class _ResourceGuarantees(cp._ControlPlaneGuarantees):
    """FCP-11A-01 flags plus: no provider API / probe, charge, purchase,
    generated price or time estimate."""

    @property
    def provider_api_called(self) -> bool:
        return False

    @property
    def remote_probe_made(self) -> bool:
        return False

    @property
    def charge_made(self) -> bool:
        return False

    @property
    def purchase_allowed(self) -> bool:
        return False

    @property
    def price_generated(self) -> bool:
        return False

    @property
    def time_estimated(self) -> bool:
        return False

    @staticmethod
    def _guarantees() -> dict:
        guarantees = cp._ControlPlaneGuarantees._guarantees()
        guarantees.update(provider_api_called=False, remote_probe_made=False, charge_made=False,
                          purchase_allowed=False, price_generated=False, time_estimated=False)
        return guarantees


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkerResource(_ResourceGuarantees):
    """One listed worker's provider facts as the Runner recorded them."""
    pipeline_id: str
    worker_id: str
    status: cp.StatusView
    agreement: str
    hold: str
    provider_id: Optional[str] = None
    requested_provider_id: Optional[str] = None
    recorded_provider_condition: Optional[str] = None
    recorded_next_eligible_utc: Optional[str] = None
    anomalies: tuple = ()

    def __post_init__(self):
        if not (cp.valid_id(self.pipeline_id) and cp.valid_id(self.worker_id)):
            raise ValueError("worker identity must be valid ids")
        if type(self.status) is not cp.StatusView or self.status.source_kind != cp.SOURCE_WORKER_STATE:
            raise ValueError("status must be a worker StatusView")
        if not (cp._in(self.agreement, snap.AGREEMENTS) and cp._in(self.hold, HOLDS)):
            raise ValueError("agreement / hold outside vocabulary")
        if self.hold != HOLD_UNKNOWN and (self.status.condition != cp.PRESENT
                                          or self.agreement != snap.AGREEMENT_CONSISTENT
                                          or self.hold != _HOLD_OF_STATE.get(self.status.source_value, HOLD_NONE)):
            raise ValueError("a hold is shown only from a consistent PRESENT state")
        if not all(cp._optional(v, valid_provider_label) for v in (self.provider_id, self.requested_provider_id)):
            raise ValueError("provider labels must be opaque provider ids")
        if not cp._optional(self.recorded_provider_condition, lambda v: cp._in(v, cp.PROVIDER_CONDITIONS)):
            raise ValueError("recorded_provider_condition outside vocabulary")
        if not cp._optional(self.recorded_next_eligible_utc, lambda v: cp.normalized_utc(v) == v):
            raise ValueError("recorded_next_eligible_utc must be normalized UTC")
        if not (type(self.anomalies) is tuple and self.anomalies == sc._ordered(self.anomalies, WORKER_ANOMALIES)):
            raise ValueError("anomalies must be ordered worker anomaly codes")

    @property
    def attributed_provider(self) -> Optional[str]:
        return self.provider_id or self.requested_provider_id

    @property
    def condition_scope(self) -> Optional[str]:
        if self.recorded_provider_condition is None:
            return None
        if _CONDITION_OF_HOLD.get(self.hold) == self.recorded_provider_condition:
            return SCOPE_ACTIVE_HOLD
        return SCOPE_RECORDED_ONLY

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id, "worker_id": self.worker_id, "provider_id": self.provider_id,
            "requested_provider_id": self.requested_provider_id, "lifecycle": self.status.lifecycle,
            "runner_outcome": self.status.runner_outcome, "agreement": self.agreement, "hold": self.hold,
            "recorded_provider_condition": self.recorded_provider_condition,
            "condition_scope": self.condition_scope, "recorded_next_eligible_utc": self.recorded_next_eligible_utc,
            "anomalies": list(self.anomalies),
        }


@dataclass(frozen=True)
class CostView(_ResourceGuarantees):
    """One B02 COST account. Amounts (exact decimal strings) only when KNOWN."""
    limit_id: str
    scope: str
    provider_id: Optional[str]
    currency: Optional[str]
    condition: str
    reasons: tuple = ()
    evidence_ids: tuple = ()
    amounts: tuple = ()  # ((field, decimal text), ...) in _MONEY_FIELDS order, KNOWN only
    provenance: tuple = ()  # ((key, value), ...)

    def __post_init__(self):
        if not (qc._valid_id(self.limit_id) and cp._in(self.scope, qc.LIMIT_SCOPES)):
            raise ValueError("limit_id / scope invalid")
        if not cp._in(self.condition, KNOWLEDGE):
            raise ValueError("condition outside vocabulary")
        names = tuple(name for name, _ in self.amounts)
        if self.condition == KNOWN and (names != _MONEY_FIELDS or self.reasons):
            raise ValueError("a KNOWN cost carries every amount and no doubt")
        if self.condition == UNKNOWN and (self.amounts or not self.reasons):
            raise ValueError("an UNKNOWN cost carries no amount and at least one reason")

    @property
    def basis(self) -> Optional[str]:
        if self.condition != KNOWN:
            return None
        values = dict(self.amounts)
        estimated = Decimal(values["estimated_high"]) or Decimal(values["uncertainty"])
        return BASIS_INCLUDES_HOST_ESTIMATE if estimated else BASIS_OBSERVED

    def to_dict(self) -> dict:
        values = dict(self.amounts)
        return {
            "limit_id": self.limit_id, "scope": self.scope, "provider_id": self.provider_id,
            "currency": self.currency, "condition": self.condition, "basis": self.basis,
            **{name: values.get(name) for name in _MONEY_FIELDS},
            "reasons": list(self.reasons), "evidence_ids": list(self.evidence_ids),
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class ProviderResource(_ResourceGuarantees):
    """One opaque provider: Runner-recorded holds, A02 quota / capacity, C02
    advice and B02 provider-scoped cost, each on its own axis."""
    provider_id: str
    worker_refs: tuple = ()
    quota_wait_workers: int = 0
    auth_hold_workers: int = 0
    unknown_hold_workers: int = 0
    quota: tuple = ()  # allowlisted A02 view items, () when absent
    capacity_condition: str = UNKNOWN
    capacity: Optional[str] = None
    proven_slots: Optional[int] = None
    capacity_reasons: tuple = ()
    advisory: tuple = ()  # allowlisted C02 decision items, () when absent
    cost_reasons: tuple = ()
    costs: tuple = ()

    def __post_init__(self):
        if not valid_provider_label(self.provider_id):
            raise ValueError("provider_id must be an opaque provider label")
        if self.capacity_condition == KNOWN:
            if not (cp._in(self.capacity, _KNOWN_CAPACITY) and not self.capacity_reasons
                    and cp._optional(self.proven_slots, lambda v: sc._is_int(v) and v >= 0)):
                raise ValueError("a KNOWN capacity is AVAILABLE / FULL without doubt")
        elif self.capacity_condition != UNKNOWN or self.capacity is not None or self.proven_slots is not None \
                or not self.capacity_reasons:
            raise ValueError("an UNKNOWN capacity carries no value and at least one reason")
        if not all(type(c) is CostView and c.provider_id == self.provider_id for c in self.costs):
            raise ValueError("costs must be this provider's CostViews")

    @property
    def cost_condition(self) -> str:
        return KNOWN if self.costs and all(c.condition == KNOWN for c in self.costs) else UNKNOWN

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id, "worker_refs": [list(r) for r in self.worker_refs],
            "quota_wait_workers": self.quota_wait_workers, "auth_hold_workers": self.auth_hold_workers,
            "unknown_hold_workers": self.unknown_hold_workers, "quota": dict(self.quota) or None,
            "capacity_condition": self.capacity_condition, "capacity": self.capacity,
            "proven_slots": self.proven_slots, "capacity_reasons": list(self.capacity_reasons),
            "advisory": dict(self.advisory) or None, "cost_condition": self.cost_condition,
            "cost_reasons": list(self.cost_reasons), "costs": [c.to_dict() for c in self.costs],
        }


@dataclass(frozen=True)
class ControlPlaneResources(_ResourceGuarantees):
    """Sealed resources view of one snapshot and at most one quota report."""
    snapshot_revision: str
    observed_at_utc: str
    snapshot_complete: bool
    report_condition: str
    report_cause: Optional[str] = None
    report_code: Optional[str] = None
    report_sha256: Optional[str] = None
    report_as_of_utc: Optional[str] = None
    report_status: Optional[str] = None
    report_anomalies: tuple = ()
    rejected_report_entries: int = 0
    unattributed_workers: int = 0
    providers: tuple = ()
    workers: tuple = ()
    global_cost_reasons: tuple = ()
    global_costs: tuple = ()

    def __post_init__(self):
        if not (type(self.snapshot_revision) is str and sc._FINGERPRINT_RE.fullmatch(self.snapshot_revision)):
            raise ValueError("snapshot_revision must be a sha256")
        cp._check_condition(self.report_condition, self.report_cause)
        if self.report_code is not None and self.report_code not in qrep._REFUSAL_MESSAGES:
            raise ValueError("report_code must be an FCP-10D-01 refusal code")
        if self.report_condition != cp.PRESENT and (self.report_sha256 or self.report_status or self.global_costs):
            raise ValueError("an absent report contributes nothing")
        if not (len(self.providers) <= MAX_PROVIDERS and all(type(p) is ProviderResource for p in self.providers)
                and [p.provider_id for p in self.providers] == sorted({p.provider_id for p in self.providers})):
            raise ValueError("providers must be sorted unique ProviderResources")
        if not all(type(w) is WorkerResource for w in self.workers):
            raise ValueError("workers must be WorkerResources")

    @property
    def global_cost_condition(self) -> str:
        return KNOWN if self.global_costs and all(c.condition == KNOWN for c in self.global_costs) else UNKNOWN

    def _body(self) -> dict:
        return {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "snapshot_revision": self.snapshot_revision,
            "observed_at_utc": self.observed_at_utc, "snapshot_complete": self.snapshot_complete,
            "report_condition": self.report_condition, "report_cause": self.report_cause,
            "report_code": self.report_code, "report_actor": cp.CONDITION_ACTOR[self.report_condition],
            "report_sha256": self.report_sha256, "report_as_of_utc": self.report_as_of_utc,
            "report_status": self.report_status, "report_anomalies": list(self.report_anomalies),
            "rejected_report_entries": self.rejected_report_entries,
            "unattributed_workers": self.unattributed_workers,
            "providers": [p.to_dict() for p in self.providers], "workers": [w.to_dict() for w in self.workers],
            "global_cost_condition": self.global_cost_condition,
            "global_cost_reasons": list(self.global_cost_reasons),
            "global_costs": [c.to_dict() for c in self.global_costs],
            "not_authorized_actions": list(NOT_AUTHORIZED_ACTIONS), **_ResourceGuarantees._guarantees(),
        }

    @property
    def revision(self) -> str:
        return hashlib.sha256(sc._canonical(self._body()).encode("ascii")).hexdigest()

    def to_dict(self) -> dict:
        return {**self._body(), "revision": self.revision}


def canonical_json(resources: ControlPlaneResources) -> str:
    """Stable, sorted, compact, size-bounded serialization of the exact type."""
    if type(resources) is not ControlPlaneResources:
        raise TypeError("canonical_json accepts only a ControlPlaneResources")
    text = sc._canonical(ControlPlaneResources.to_dict(resources))
    if len(text) > cp.MAX_CANONICAL_JSON_BYTES:
        raise ValueError("canonical resources exceed MAX_CANONICAL_JSON_BYTES")
    return text


# ---------------------------------------------------------------------------
# Workers (FCP-11B-02 snapshot)
# ---------------------------------------------------------------------------

def _worker(view: cp.WorkerView, agreement: str) -> WorkerResource:
    status = view.status
    hold = HOLD_UNKNOWN
    if status.condition == cp.PRESENT and agreement == snap.AGREEMENT_CONSISTENT:
        hold = _HOLD_OF_STATE.get(status.source_value, HOLD_NONE)
    anomalies = []
    if hold in _CONDITION_OF_HOLD and view.provider_condition != _CONDITION_OF_HOLD[hold]:
        anomalies.append(HOLD_CONDITION_MISMATCH)
    if agreement == snap.AGREEMENT_DIVERGENT:
        anomalies.append(WORKER_STATUS_DIVERGENT)
    labels = [v if valid_provider_label(v) else None for v in (view.provider_id, view.requested_provider_id)]
    return WorkerResource(view.pipeline_id, view.worker_id, status, agreement, hold, *labels,
                          recorded_provider_condition=view.provider_condition,
                          recorded_next_eligible_utc=view.next_eligible_utc,
                          anomalies=sc._ordered(anomalies, WORKER_ANOMALIES))


def _snapshot_workers(snapshot) -> tuple:
    """`(workers, unattributed, complete)` of a snapshot."""
    agreements = {(w.pipeline_id, w.worker_id): w.agreement for p in snapshot.pipelines for w in p.workers}
    workers = tuple(_worker(v, agreements.get((v.pipeline_id, v.worker_id), snap.AGREEMENT_UNVERIFIABLE))
                    for p in snapshot.observation.pipelines for v in p.workers)
    listed = {(w.pipeline_id, w.worker_id) for w in workers}
    unattributed = sum(1 for w in workers if w.attributed_provider is None) + sum(
        1 for key in agreements if key not in listed)
    complete = (snapshot.root_condition == cp.PRESENT and snapshot.pipelines_omitted == 0
                and all(p.workers_omitted == 0 and p.workers_condition == cp.PRESENT
                        and p.view.status.condition == cp.PRESENT and not p.view.rejected_workers
                        for p in snapshot.pipelines))
    return workers, unattributed, complete


# ---------------------------------------------------------------------------
# Report (FCP-10D-01)
# ---------------------------------------------------------------------------

def _verified_report(report) -> Optional[str]:
    """None when `report` is an untampered FCP-10D-01 report; else the cause."""
    if type(report) is not dict:
        return cp.SOURCE_NOT_JSON
    if (report.get("schema"), report.get("schema_version"), report.get("marker")) != (
            qrep.SCHEMA, qrep.SCHEMA_VERSION, qrep.REPORT_MARKER) or not _REPORT_KEYS <= set(report):
        return cp.SCHEMA_UNSUPPORTED
    try:
        if len(qrep.render_json(report)) > qrep.MAX_REPORT_BYTES:
            return cp.SOURCE_TOO_LARGE
    except qrep.ReportError:
        return cp.SOURCE_TOO_LARGE
    except (TypeError, ValueError, RecursionError):
        return cp.SOURCE_NOT_JSON
    if not qrep.verify_report(report):
        return cp.FIELD_MALFORMED
    if report["authority"] != qrep.AUTHORITY or any(report.get(f) is not False for f in qrep.AUTHORITY_FLAGS):
        return cp.FIELD_MALFORMED
    if cp.normalized_utc(report["as_of_utc"]) != report["as_of_utc"] or report["status"] not in qrep.STATUSES:
        return cp.FIELD_MALFORMED
    return None


def _load_report(report, report_file) -> tuple:
    """`(report or None, condition, cause, code)`. Never raises, never echoes."""
    if report is not None and report_file is not None:
        raise ValueError("pass a report or a report_file, not both")
    code = None
    if report_file is not None:
        try:
            report = qrep.run_report(report_file)
        except qrep.ReportError as exc:
            code = exc.code if exc.code in qrep._REFUSAL_MESSAGES else "REPORT_INTERNAL_ERROR"
            cause = _REPORT_CAUSES.get(code, cp.SOURCE_UNREADABLE)
            return None, cp.CAUSE_CONDITION[cause], cause, code
        except Exception:  # noqa: BLE001 - fail closed without a traceback or leaked bytes
            return None, cp.UNAVAILABLE, cp.SOURCE_UNREADABLE, "REPORT_INTERNAL_ERROR"
    if report is None:
        return None, cp.MISSING, cp.SOURCE_ABSENT, None
    cause = _verified_report(report)
    if cause is not None:
        return None, cp.CAUSE_CONDITION[cause], cause, None
    return report, cp.PRESENT, None, None


def _quota_items(entry) -> Optional[tuple]:
    """Allowlisted, validated A02 provider view, or None."""
    if type(entry) is not dict:
        return None
    reasons, evidence = _codes(entry.get("reasons")), _ids(entry.get("evidence_ids"))
    checks = (
        cp._in(entry.get("availability"), qo.AVAILABILITY_STATES), cp._in(entry.get("capacity"), qo.CAPACITY_STATES),
        cp._in(entry.get("certainty"), qo.CERTAINTIES), cp._optional(entry.get("freshness"),
                                                                     lambda v: cp._in(v, qo.FRESHNESS)),
        cp._optional(entry.get("proven_slots"), lambda v: sc._is_int(v) and v >= 0),
        cp._optional(entry.get("next_eligible_utc"), lambda v: cp.normalized_utc(v) == v),
        cp._optional(entry.get("eligibility_source"), cp.valid_code), reasons is not None, evidence is not None,
    )
    if not all(checks):
        return None
    values = {**entry, "reasons": list(reasons), "evidence_ids": list(evidence)}
    return tuple((name, values.get(name)) for name in _QUOTA_FIELDS)


def _advisory_items(decision) -> Optional[tuple]:
    """Allowlisted C02 decision (information only), or None."""
    reasons = _codes(decision.get("reasons"))
    if not (cp._in(decision.get("status"), qrep.STATUSES) and cp._in(decision.get("actor"), rq.ACTORS)
            and cp._in(decision.get("action"), rq.ACTIONS) and reasons is not None):
        return None
    return (("status", decision["status"]), ("actor", decision["actor"]), ("action", decision["action"]),
            ("reasons", list(reasons)))


def _money(text, exponent: int) -> Optional[Decimal]:
    """An exact decimal string on the policy grid, or None (never a float)."""
    if type(text) is not str or len(text) > MAX_MONEY_CHARS or not _MONEY_RE.fullmatch(text):
        return None
    value = Decimal(text)
    if bg._money_text(value) != text or value.as_tuple().exponent != exponent:
        return None
    return value


def _cost(account, currency, exponent, provenance, doubts) -> Optional[CostView]:
    """A CostView of one B02 COST account; None when unidentifiable."""
    provider = account.get("provider_id")
    reasons, evidence = _codes(account.get("reasons")), _ids(account.get("evidence_ids"))
    if not (qc._valid_id(account.get("limit_id")) and cp._in(account.get("scope"), qc.LIMIT_SCOPES)
            and cp._optional(provider, valid_provider_label) and reasons is not None and evidence is not None):
        return None
    common = dict(limit_id=account["limit_id"], scope=account["scope"], provider_id=provider, currency=currency,
                  evidence_ids=evidence, provenance=provenance)
    doubt = tuple(r for r in reasons if r in bg.LIMIT_UNKNOWN_REASONS) + tuple(doubts)
    values = {name: _money(account.get(name), exponent) for name in _MONEY_FIELDS}
    if not doubt:
        if exponent is None or None in values.values() or (
                values["accounted"] != bg._plus(values["observed"], values["estimated_high"])
                or values["uncertainty"] != bg._minus(values["estimated_high"], values["estimated_low"])
                or values["remaining"] != max(bg._minus(values["maximum"], values["accounted"]), Decimal(0))):
            doubt = (COST_FIGURES_INCONSISTENT,)
    if doubt:
        return CostView(condition=UNKNOWN, reasons=tuple(dict.fromkeys(doubt)), **common)
    return CostView(condition=KNOWN, amounts=tuple((n, account[n]) for n in _MONEY_FIELDS), **common)


def _report_costs(report, doubts: tuple) -> tuple:
    """`(costs, global_reasons, rejected)` of the report's budget section."""
    budget = report.get("budget")
    if budget is None:
        return (), (NO_COST_EVIDENCE,), 0
    if type(budget) is not dict or type(budget.get("accounts")) is not list:
        return (), (COST_FIGURES_INCONSISTENT,), 1
    granularity = budget.get("granularity")
    exponent = Decimal(granularity).as_tuple().exponent if (
        type(granularity) is str and _MONEY_RE.fullmatch(granularity)
        and bg.granularity_ok(Decimal(granularity))) else None
    currency = budget.get("currency") if type(budget.get("currency")) is str and re.fullmatch(
        r"[A-Z]{3}", budget["currency"]) else None
    source = report["sources"].get("budget") if type(report["sources"]) is dict else None
    source = source if type(source) is dict else {}
    provenance = (("source", COST_SOURCE), ("schema", source.get("schema")),
                  ("fingerprint", source.get("fingerprint")), ("sha256", source.get("sha256")),
                  ("report_sha256", report["report_sha256"]))
    costs, rejected = [], 0
    for account in budget["accounts"]:
        if type(account) is not dict or account.get("unit") != bg.UNIT_COST:
            rejected += type(account) is not dict
            continue
        view = _cost(account, currency, exponent, provenance, doubts)
        if view is None:
            rejected += 1
        else:
            costs.append(view)
    reasons = () if costs else (NO_COST_LIMIT,)
    return tuple(sorted(costs, key=lambda c: c.limit_id)), reasons, rejected


def _report_anomalies(report, observed_at_utc: str, max_age) -> tuple:
    as_of, observed = qc.parse_utc(report["as_of_utc"]), qc.parse_utc(observed_at_utc)
    if as_of > observed:
        return (REPORT_AFTER_OBSERVATION,)
    if max_age is not None and (observed - as_of).total_seconds() > max_age:
        return (REPORT_STALE,)
    return ()


def _capacity(quota: dict, doubts: tuple) -> tuple:
    """`(condition, capacity, proven_slots, reasons)` of one A02 view."""
    if not quota:
        return UNKNOWN, None, None, doubts or (QUOTA_EVIDENCE_ABSENT,)
    reasons = list(doubts) + [r for r in quota["reasons"] if r in qo.UNCERTAIN_REASONS]
    if quota["freshness"] != qo.FRESH:
        reasons.append({qo.STALE: qo.EVIDENCE_STALE, qo.FROM_FUTURE: qo.EVIDENCE_FROM_FUTURE}.get(
            quota["freshness"], qo.NO_EVIDENCE))
    if quota["capacity"] not in _KNOWN_CAPACITY:
        reasons.append(qo.CAPACITY_UNKNOWN)
    if quota["certainty"] != qo.CERTAIN and not reasons:
        reasons.append(qo.UNCERTAIN)
    if reasons:
        return UNKNOWN, None, None, tuple(dict.fromkeys(reasons))
    return KNOWN, quota["capacity"], quota["proven_slots"], ()


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def observe_resources(snapshot, *, report=None, report_file=None,
                      max_report_age_seconds: Optional[int] = None) -> ControlPlaneResources:
    """Consultative resources view of `snapshot` (an FCP-11B-02
    `ControlPlaneSnapshot`) and at most one FCP-10D-01 report: an
    already-produced report dict, or `report_file` run through the governed
    `run_report`. Raises `ValueError` / `TypeError` only for caller errors;
    every problem with the report is reported, never raised nor echoed."""
    if type(snapshot) is not snap.ControlPlaneSnapshot:
        raise TypeError("snapshot must be a ControlPlaneSnapshot")
    if max_report_age_seconds is not None and not (
            cp._bounded_int(max_report_age_seconds, MAX_REPORT_AGE_SECONDS)):
        raise ValueError("max_report_age_seconds must be an int in 0..MAX_REPORT_AGE_SECONDS")
    observed_at = snapshot.observation.observed_at_utc
    workers, unattributed, complete = _snapshot_workers(snapshot)
    loaded, condition, cause, code = _load_report(report, report_file)

    quotas, advice, costs, rejected = {}, {}, (), 0
    anomalies, global_reasons = (), (REPORT_ABSENT,)
    if loaded is not None:
        anomalies = _report_anomalies(loaded, observed_at, max_report_age_seconds)
        quota_section = loaded["quota"] if type(loaded["quota"]) is dict else {}
        entries = quota_section.get("providers") if type(quota_section.get("providers")) is list else []
        for entry in entries[:MAX_PROVIDERS]:
            items = _quota_items(entry)
            if items is None or not valid_provider_label(entry.get("provider_id")) \
                    or entry["provider_id"] in quotas:
                rejected += 1
            else:
                quotas[entry["provider_id"]] = dict(items)
        rejected += max(len(entries) - MAX_PROVIDERS, 0)
        for decision in loaded["decisions"] if type(loaded["decisions"]) is list else ():
            if type(decision) is not dict or decision.get("subject") != qrep.SUBJECT_PROVIDER:
                continue
            items = _advisory_items(decision)
            if items is None or not valid_provider_label(decision.get("id")):
                rejected += 1
            else:
                advice[decision["id"]] = items
        costs, global_reasons, cost_rejected = _report_costs(loaded, anomalies)
        rejected += cost_rejected

    by_provider: dict = {}
    for worker in workers:
        if worker.attributed_provider is not None:
            by_provider.setdefault(worker.attributed_provider, []).append(worker)
    names = sorted(set(by_provider) | set(quotas) | set(advice) | {c.provider_id for c in costs if c.provider_id})
    providers = []
    for name in names[:MAX_PROVIDERS]:
        owned = by_provider.get(name, [])
        doubts = anomalies if loaded is not None else (REPORT_ABSENT,)
        capacity = _capacity(quotas.get(name, {}), doubts)
        own_costs = tuple(c for c in costs if c.provider_id == name)
        providers.append(ProviderResource(
            name, worker_refs=tuple((w.pipeline_id, w.worker_id) for w in owned),
            quota_wait_workers=sum(w.hold == HOLD_QUOTA_WAIT for w in owned),
            auth_hold_workers=sum(w.hold == HOLD_AUTH for w in owned),
            unknown_hold_workers=sum(w.hold == HOLD_UNKNOWN for w in owned),
            quota=tuple(quotas.get(name, {}).items()), capacity_condition=capacity[0], capacity=capacity[1],
            proven_slots=capacity[2], capacity_reasons=capacity[3], advisory=advice.get(name, ()),
            cost_reasons=() if own_costs else ((NO_COST_LIMIT,) if loaded is not None and loaded.get("budget")
                                               else global_reasons),
            costs=own_costs,
        ))
    global_costs = tuple(c for c in costs if c.provider_id is None)
    return ControlPlaneResources(
        snapshot.revision, observed_at, complete, condition, cause, code,
        report_sha256=loaded["report_sha256"] if loaded else None,
        report_as_of_utc=loaded["as_of_utc"] if loaded else None,
        report_status=loaded["status"] if loaded else None, report_anomalies=anomalies,
        rejected_report_entries=rejected, unattributed_workers=unattributed + max(len(names) - MAX_PROVIDERS, 0),
        providers=tuple(providers), workers=workers,
        global_cost_reasons=global_reasons if not global_costs else (),
        global_costs=global_costs,
    )
