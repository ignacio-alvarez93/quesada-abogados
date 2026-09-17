"""QCC Contract Watcher — persisted AUTO TWIN capture adapter (1D).

Bridges the already-durable AUTO TWIN persisted capture artifacts
(``data/qcc/site_architecture/<capture_id>/`` — read exclusively through
the existing ``load_auto_twin_persisted_capture_bundle`` loader) into the
already-accepted 1C governed cycle
(``contract_watcher_pipeline.run_contract_watcher_cycle``), so a caller
can identify one persisted trusted baseline and one persisted current
observation by opaque ``capture_id`` alone, without manually
reconstructing a ``SiteArchitectureSnapshot``.

Canonical source audit (Work Order QCC-CONTRACT-WATCHER-1D)
-------------------------------------------------------------

Three existing AUTO TWIN persistence surfaces were inspected:

- ``observation_store.AutoTwinObservationStore`` — durable TWIN
  identity/classification bookkeeping (``state_key``,
  ``baseline_fingerprint``, UNKNOWN/KNOWN/CHANGED). It references a
  ``capture_id`` for provenance but never stores the normalized Site
  Contract itself.
- ``candidate_revision_store.AutoTwinCandidateRevisionStore`` and
  ``materialized_revision_store.AutoTwinMaterializedRevisionStore`` —
  govern the TWIN candidate/materialization lifecycle (fingerprints,
  manifests, content hashes). Neither persists a normalized Site
  Architecture payload either; both exist one layer above the raw
  contract.
- ``persisted_capture_bundle.load_auto_twin_persisted_capture_bundle`` —
  the sole existing reader of a persisted capture directory
  (``qcc_capture.json`` / ``site_architecture.json`` /
  ``state_observation.json`` / ``metadata.json``) that returns the full
  normalized Site Architecture snapshot (``site_architecture.json``,
  the exact contract ``diff_site_architecture`` /
  ``build_functional_state_fingerprint`` already consume) together with
  cross-validated capture identity.

``capture_id`` (already assigned by
``backend.qcc.site_architecture.ingestor.QccSiteArchitectureIngestor.ingest``)
is therefore the only durable, opaque identifier that can safely serve
as a 1C ``baseline_reference``/``observation_reference``: it is the
existing locator for the one artifact that actually carries a
normalized Site Contract. This module adds no second capture store, no
second Site Architecture model and no second observation/revision
system — it only adapts ``capture_id -> normalized Site Contract`` for
1C and lets 1C's own baseline/history/confirmation machinery run
unchanged.

``contract_key`` (the watched logical contract identity) is
deliberately NOT derived here from capture metadata: exactly like bare
1C, it must be supplied explicitly by the caller, so a trusted baseline
is always an explicit governance decision and never an incidental
side effect of persisted-capture bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contract_watcher_pipeline import (
    DEFAULT_GEOMETRY_TOLERANCE_PX,
    ContractWatcherConfirmationPolicy,
    ContractWatcherCycleError,
    ContractWatcherObservationInput,
    ContractWatcherWatchTarget,
    run_contract_watcher_cycle,
)
from .contract_watcher_lifecycle import (
    get_default_contract_watcher_evidence_store,
    get_default_contract_watcher_history_store,
)
from .persisted_capture_bundle import (
    load_auto_twin_persisted_capture_bundle,
)

from backend.qcc.site_architecture.ingestor import (
    DEFAULT_QCC_SITE_ARCHITECTURE_ROOT,
)


def _required_text(value, *, error):
    result = str(value or "").strip()

    if not result:
        raise ValueError(error)

    return result


class ContractWatcherPersistedCaptureError(ContractWatcherCycleError):
    """Raised when a referenced persisted capture cannot be resolved.

    Wraps (never masks) the specific failure already raised by
    ``load_auto_twin_persisted_capture_bundle`` — missing capture
    directory, malformed/incomplete artifact set, id/state cross-check
    mismatch — as a ``ContractWatcherCycleError`` subclass so it composes
    with the existing 1C governed-rejection batch policy instead of
    aborting an entire persisted watch-plan run.
    """


class ContractWatcherPersistedCrossContractMismatchError(ContractWatcherCycleError):
    """Raised when baseline/current persisted captures are not comparable.

    Fires when existing, already-cross-validated capture metadata
    (``site_code`` / ``pathname`` / ``functional_state``) proves the two
    referenced captures do not describe the same logical Site Contract
    surface — for example a caller accidentally pairing captures of two
    different pages. This never inspects raw HTML/DOM content; it only
    reuses identity fields ``load_auto_twin_persisted_capture_bundle``
    already validated.
    """


@dataclass(frozen=True)
class ContractWatcherPersistedCaptureRef:
    """Immutable, opaque reference to one persisted AUTO TWIN capture.

    ``capture_id`` is the existing, durable identifier already assigned
    by ``QccSiteArchitectureIngestor.ingest`` — never a new invented id.
    ``root`` is dependency-injectable so tests (and any future caller
    with an isolated persisted-capture root) never depend on the process
    default filesystem location.
    """

    capture_id: str
    root: object = DEFAULT_QCC_SITE_ARCHITECTURE_ROOT

    def __post_init__(self):
        object.__setattr__(
            self,
            "capture_id",
            _required_text(
                self.capture_id,
                error="QCC_CONTRACT_WATCHER_PERSISTED_CAPTURE_ID_REQUIRED",
            ),
        )


def resolve_persisted_site_contract(ref):
    """Loads the normalized Site Contract behind one persisted capture.

    Reuses ``load_auto_twin_persisted_capture_bundle`` — the existing
    canonical reader — as the sole source of truth. Deliberately calls it
    with ``require_viewport_image=False``: Contract Watcher compares
    structural/functional contract identity, never visual fidelity, so a
    missing/undeclared screenshot must never block a governed structural
    comparison.

    Fails closed with ``ContractWatcherPersistedCaptureError`` for any
    resolution failure (missing capture, malformed/incomplete artifact
    set, id/state cross-check mismatch) — never returns a partial or
    synthetic contract.
    """

    if not isinstance(ref, ContractWatcherPersistedCaptureRef):
        raise TypeError("QCC_CONTRACT_WATCHER_PERSISTED_CAPTURE_REF_INVALID")

    try:
        bundle = load_auto_twin_persisted_capture_bundle(
            capture_id=ref.capture_id,
            root=ref.root,
            require_viewport_image=False,
        )
    except ValueError as exc:
        raise ContractWatcherPersistedCaptureError(str(exc)) from exc

    return {
        "capture_id": bundle["capture_id"],
        "site_contract": bundle["snapshot"],
        "pathname": bundle["capture"]["pathname"],
        "functional_state": bundle["capture"]["functional_state"],
        "fingerprint": bundle["fingerprint"],
        "site_code": bundle["site_code"],
    }


def _require_compatible_persisted_artifacts(*, baseline_artifact, observation_artifact):
    if (
        baseline_artifact["site_code"] != observation_artifact["site_code"]
        or baseline_artifact["pathname"] != observation_artifact["pathname"]
        or baseline_artifact["functional_state"]
        != observation_artifact["functional_state"]
    ):
        raise ContractWatcherPersistedCrossContractMismatchError(
            "QCC_CONTRACT_WATCHER_PERSISTED_CROSS_CONTRACT_MISMATCH"
        )


@dataclass(frozen=True)
class ContractWatcherPersistedWatchRequest:
    """One independent unit of persisted-capture Contract Watcher work.

    ``contract_key`` remains an explicit, caller-governed identity
    (exactly as bare 1C requires): a trusted baseline is never inferred
    from persisted-capture bookkeeping.
    """

    contract_key: str
    baseline_capture: ContractWatcherPersistedCaptureRef
    observation_capture: ContractWatcherPersistedCaptureRef
    confirmation_policy: ContractWatcherConfirmationPolicy
    geometry_tolerance_px: float = DEFAULT_GEOMETRY_TOLERANCE_PX
    observed_at: str | None = None
    request_id: str | None = None

    def __post_init__(self):
        object.__setattr__(
            self,
            "contract_key",
            _required_text(
                self.contract_key,
                error="QCC_CONTRACT_WATCHER_PERSISTED_CONTRACT_KEY_REQUIRED",
            ),
        )

        if not isinstance(
            self.baseline_capture, ContractWatcherPersistedCaptureRef
        ):
            raise TypeError(
                "QCC_CONTRACT_WATCHER_PERSISTED_BASELINE_CAPTURE_INVALID"
            )

        if not isinstance(
            self.observation_capture, ContractWatcherPersistedCaptureRef
        ):
            raise TypeError(
                "QCC_CONTRACT_WATCHER_PERSISTED_OBSERVATION_CAPTURE_INVALID"
            )

        if not isinstance(
            self.confirmation_policy, ContractWatcherConfirmationPolicy
        ):
            raise TypeError(
                "QCC_CONTRACT_WATCHER_PERSISTED_CONFIRMATION_POLICY_REQUIRED"
            )


def resolve_contract_watcher_persisted_cycle_inputs(request):
    """Resolves one persisted watch request into 1C cycle inputs.

    Returns ``(target, observation, baseline_artifact, observation_artifact)``.
    Never mutates or replays a browser; only loads two already-persisted,
    already-normalized Site Contracts and checks (via already-validated
    capture metadata) that they describe the same logical contract
    surface before handing them to 1C.
    """

    if not isinstance(request, ContractWatcherPersistedWatchRequest):
        raise TypeError("QCC_CONTRACT_WATCHER_PERSISTED_REQUEST_INVALID")

    baseline_artifact = resolve_persisted_site_contract(request.baseline_capture)
    observation_artifact = resolve_persisted_site_contract(request.observation_capture)

    _require_compatible_persisted_artifacts(
        baseline_artifact=baseline_artifact,
        observation_artifact=observation_artifact,
    )

    target = ContractWatcherWatchTarget(
        contract_key=request.contract_key,
        baseline_reference=baseline_artifact["capture_id"],
        baseline_contract=baseline_artifact["site_contract"],
        confirmation_policy=request.confirmation_policy,
        geometry_tolerance_px=request.geometry_tolerance_px,
    )

    observation = ContractWatcherObservationInput(
        observation_reference=observation_artifact["capture_id"],
        observation_contract=observation_artifact["site_contract"],
        observed_at=request.observed_at,
    )

    return target, observation, baseline_artifact, observation_artifact


def run_contract_watcher_persisted_cycle(
    request,
    *,
    evidence_store=None,
    history_store=None,
):
    """Resolves one persisted watch request and runs its governed 1C cycle.

    Delegates the actual comparison/lifecycle decision entirely to
    ``run_contract_watcher_cycle`` (1C) — this function only adds the
    persisted-artifact resolution step and minimal, PII-safe provenance
    (capture ids, pathname, functional_state, site_code) to the returned
    receipt. Never duplicates the raw Site Contract in the receipt.
    """

    if not isinstance(request, ContractWatcherPersistedWatchRequest):
        raise TypeError("QCC_CONTRACT_WATCHER_PERSISTED_REQUEST_INVALID")

    target, observation, baseline_artifact, observation_artifact = (
        resolve_contract_watcher_persisted_cycle_inputs(request)
    )

    receipt = run_contract_watcher_cycle(
        target,
        observation,
        evidence_store=evidence_store,
        history_store=history_store,
    )

    return {
        **receipt,
        "baseline_capture_id": baseline_artifact["capture_id"],
        "observation_capture_id": observation_artifact["capture_id"],
        "pathname": observation_artifact["pathname"],
        "functional_state": observation_artifact["functional_state"],
        "site_code": observation_artifact["site_code"],
    }


def run_contract_watcher_persisted_cycle_batch(
    requests,
    *,
    evidence_store=None,
    history_store=None,
):
    """Runs a finite, caller-supplied collection of independent persisted cycles.

    Composition, not a second orchestration hierarchy: processes
    ``requests`` sequentially in stable input order and delegates every
    single unit of work to ``run_contract_watcher_persisted_cycle``,
    mirroring the exact failure policy already established by 1C's
    ``run_contract_watcher_cycle_batch`` — a governed, expected rejection
    (``ContractWatcherCycleError`` and subclasses, including persisted
    resolution/cross-contract failures) is recorded as a per-target
    failure and processing continues; anything else (a structurally
    invalid ``requests`` collection/item) aborts immediately. Never
    sleeps, polls, retries, spawns workers or accesses the network.
    """

    if not isinstance(requests, (list, tuple)):
        raise TypeError("QCC_CONTRACT_WATCHER_PERSISTED_BATCH_REQUESTS_INVALID")

    resolved_evidence_store = (
        evidence_store or get_default_contract_watcher_evidence_store()
    )

    resolved_history_store = (
        history_store or get_default_contract_watcher_history_store()
    )

    results = []
    failures = []
    lifecycle_counts = {}

    for index, request in enumerate(requests):
        if not isinstance(request, ContractWatcherPersistedWatchRequest):
            raise TypeError("QCC_CONTRACT_WATCHER_PERSISTED_BATCH_REQUEST_INVALID")

        request_id = request.request_id or request.contract_key

        try:
            receipt = run_contract_watcher_persisted_cycle(
                request,
                evidence_store=resolved_evidence_store,
                history_store=resolved_history_store,
            )
        except ContractWatcherCycleError as exc:
            failures.append({
                "index": index,
                "request_id": request_id,
                "contract_key": request.contract_key,
                "error": str(exc),
            })
            continue

        lifecycle_counts[receipt["lifecycle_state"]] = (
            lifecycle_counts.get(receipt["lifecycle_state"], 0) + 1
        )

        results.append(receipt)

    return {
        "requested": len(requests),
        "processed": len(results),
        "failed": len(failures),
        "results": results,
        "failures": failures,
        "lifecycle_counts": lifecycle_counts,
    }
