"""QCC AUTO TWIN — Multi-Site Certification Foundation (UWT-12A).

Work Order UWT-12A asks for the non-destructive *foundation* a future
per-site certification flow (Mercurio, Red SARA, DEHú, Nacionalidad,
and any future managed site) can be built on, without ever building a
site-specific certification engine itself.

Canonical source audit
-----------------------

Everything this capability needs to *judge* already exists and is
explicitly reused, never duplicated or re-executed:

- ``AutoTwinManagedSite`` (``managed_site_registry``) already owns site
  identity (``twin_key``/``site_code``/origins/path scopes). This
  module never redefines a second site identity.
- ``AutoTwinCandidateRevisionStore`` already owns Twin candidate
  revision identity (``candidate_id``/``candidate_revision``/status).
- ``run_auto_twin_validation_suite`` (UWT-10) already combines
  structural/geometry/visual/catalog/behavior fidelity evidence
  (UWT-9's differential lineage feeds the Contract Watcher evidence it
  is built on), governed navigation/transition replay evidence, and
  materialized-runtime network safety evidence (UWT-8's fictive-data
  discipline is what keeps that runtime network-sterile in the first
  place) into one deterministic ``suite_result_id``. This module calls
  it once and never re-implements any of its three sections.
- ``plan_exploration_candidates`` (UWT-11A) already produces a
  deterministic, already-governed, already-risk-classified list of
  safe next actions for a Discovery Profile Twin. This module reads
  that plan's own counts as the sole evidence for governed exploration
  readiness; it never plans, sessions or executes anything itself.
- ``AutoTwinProfilePolicy`` already defines ``active_discovery`` as the
  one capability flag that distinguishes a Discovery Profile browser;
  this module reuses it verbatim to decide whether governed exploration
  even applies to this twin at all.

What does not exist yet, and is the entire contribution of this
module, is the generic, provider-neutral composition that:

1. binds one site identity + one Twin revision identity together into
   a single deterministic certification record;
2. reduces each of the four required capability findings (structural
   fidelity, transition/behavior fidelity, network/local safety,
   governed exploration readiness) to the one explicit four-value
   vocabulary this Work Order requires: ``PASS`` / ``FAIL`` /
   ``NOT_SUPPORTED`` / ``UNRESOLVED``;
3. refuses to ever claim an overall ``PASS`` unless all four
   capabilities were themselves positively evaluated to ``PASS`` --
   missing evidence (``UNRESOLVED``) or a structurally inapplicable
   capability (``NOT_SUPPORTED``) can never be silently upgraded into a
   certification claim;
4. records full evidence provenance (the exact ``suite_result_id`` /
   ``plan_id`` / revision identifiers a reviewer would need to re-trace
   every finding) and a stable, canonical-JSON ``certification_id``.

Governance this module preserves (never violates)
----------------------------------------------------

- No automatic ACTIVE promotion: this module never writes to
  ``AutoTwinCandidateRevisionStore``/``AutoTwinMaterializedRevisionStore``
  and never changes a candidate's status, no matter the verdict.
- No REAL mutation, no live filing/submission: purely a read-only
  composition over evidence other, already-governed components already
  produced; no browser, no network call, no form interaction anywhere
  in this module.
- Provider-neutral, site-neutral: every input is a generic identity or
  evidence object (``AutoTwinManagedSite``, stores, a validation suite
  result, an exploration plan); no site-specific rule, selector or
  URL is ever referenced by name.
- Deterministic: the same inputs always yield the same
  ``certification_id`` (stable sha256 digest over canonical JSON),
  independent of dict/set iteration order.
- Fail closed: any evidence that cannot be positively resolved
  (missing, malformed, or bound to a different twin/site/revision)
  always yields ``UNRESOLVED``, never a guessed ``PASS``.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from backend.services.twin_browser_runtime_service import (
    DEFAULT_MATERIALIZED_ROOT,
)

from .candidate_revision_store import AutoTwinCandidateRevisionStore
from .exploration_candidate_planner import (
    AUTO_TWIN_EXPLORATION_CANDIDATE_PLAN_TYPE,
)
from .managed_site_registry import AutoTwinManagedSite
from .profile_policy import AutoTwinProfilePolicy
from .validation_evidence_store import AutoTwinValidationEvidenceStore
from .validation_suite import (
    AUTO_TWIN_VALIDATION_SUITE_SECTION_EVALUATED,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_FIDELITY,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_NAVIGATION,
    AUTO_TWIN_VALIDATION_SUITE_SECTION_NETWORK_SAFETY,
    AUTO_TWIN_VALIDATION_SUITE_TYPE,
    run_auto_twin_validation_suite,
)
from .validation_evidence import (
    AUTO_TWIN_VALIDATION_CHECK_FAIL,
    AUTO_TWIN_VALIDATION_CHECK_PASS,
)


AUTO_TWIN_MULTI_SITE_CERTIFICATION_SCHEMA_VERSION = 1

AUTO_TWIN_MULTI_SITE_CERTIFICATION_TYPE = (
    "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION"
)

# The one, fixed, explicit four-value status vocabulary this Work
# Order requires -- used for every capability finding and for the
# overall roll-up alike.
AUTO_TWIN_CERTIFICATION_STATUS_PASS = "PASS"
AUTO_TWIN_CERTIFICATION_STATUS_FAIL = "FAIL"
AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED = "NOT_SUPPORTED"
AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED = "UNRESOLVED"

AUTO_TWIN_CERTIFICATION_STATUSES = frozenset(
    {
        AUTO_TWIN_CERTIFICATION_STATUS_PASS,
        AUTO_TWIN_CERTIFICATION_STATUS_FAIL,
        AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED,
        AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
    }
)

# Fixed capability vocabulary (the required capability matrix rows).
# Order is pinned so two equal findings always serialize identically.
AUTO_TWIN_CAPABILITY_STRUCTURAL_FIDELITY = "STRUCTURAL_FIDELITY"
AUTO_TWIN_CAPABILITY_TRANSITION_BEHAVIOR_FIDELITY = (
    "TRANSITION_BEHAVIOR_FIDELITY"
)
AUTO_TWIN_CAPABILITY_NETWORK_LOCAL_SAFETY = "NETWORK_LOCAL_SAFETY"
AUTO_TWIN_CAPABILITY_GOVERNED_EXPLORATION_READINESS = (
    "GOVERNED_EXPLORATION_READINESS"
)

AUTO_TWIN_CERTIFICATION_CAPABILITIES = (
    AUTO_TWIN_CAPABILITY_STRUCTURAL_FIDELITY,
    AUTO_TWIN_CAPABILITY_TRANSITION_BEHAVIOR_FIDELITY,
    AUTO_TWIN_CAPABILITY_NETWORK_LOCAL_SAFETY,
    AUTO_TWIN_CAPABILITY_GOVERNED_EXPLORATION_READINESS,
)

_SUITE_SECTION_BY_CAPABILITY = {
    AUTO_TWIN_CAPABILITY_STRUCTURAL_FIDELITY: (
        AUTO_TWIN_VALIDATION_SUITE_SECTION_FIDELITY
    ),
    AUTO_TWIN_CAPABILITY_TRANSITION_BEHAVIOR_FIDELITY: (
        AUTO_TWIN_VALIDATION_SUITE_SECTION_NAVIGATION
    ),
    AUTO_TWIN_CAPABILITY_NETWORK_LOCAL_SAFETY: (
        AUTO_TWIN_VALIDATION_SUITE_SECTION_NETWORK_SAFETY
    ),
}


def _text(value) -> str:
    return str(value or "").strip()


def _required_text(value, *, error) -> str:
    result = _text(value)

    if not result:
        raise ValueError(error)

    return result


def _canonical_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def _capability(*, status, reason, references=None):
    if status not in AUTO_TWIN_CERTIFICATION_STATUSES:
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_STATUS_INVALID"
        )

    return {
        "status": status,
        "reason": _text(reason) or None,
        "references": dict(references or {}),
    }


def _capability_from_suite_section(suite_result, *, capability):
    section_name = _SUITE_SECTION_BY_CAPABILITY[capability]
    section = (suite_result.get("sections") or {}).get(section_name)

    if not isinstance(section, dict):
        return _capability(
            status=AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
            reason="VALIDATION_SUITE_SECTION_MISSING",
            references={"suite_section": section_name},
        )

    status = section.get("status")

    references = {
        "suite_result_id": suite_result.get("suite_result_id"),
        "suite_section": section_name,
        **(section.get("references") or {}),
    }

    if status == AUTO_TWIN_VALIDATION_SUITE_SECTION_EVALUATED:
        verdict = section.get("verdict")

        if verdict == AUTO_TWIN_VALIDATION_CHECK_PASS:
            return _capability(
                status=AUTO_TWIN_CERTIFICATION_STATUS_PASS,
                reason=section.get("reason"),
                references=references,
            )

        if verdict == AUTO_TWIN_VALIDATION_CHECK_FAIL:
            return _capability(
                status=AUTO_TWIN_CERTIFICATION_STATUS_FAIL,
                reason=section.get("reason"),
                references=references,
            )

        return _capability(
            status=AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
            reason="VALIDATION_SUITE_SECTION_VERDICT_UNRECOGNIZED",
            references=references,
        )

    # SKIPPED ("no evidence yet") and UNRESOLVED ("evidence exists but
    # cannot be safely applied to this revision") both mean the required
    # evidence this capability needs is not actually available: never a
    # silent PASS, always an explicit UNRESOLVED.
    return _capability(
        status=AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
        reason=section.get("reason") or f"SUITE_SECTION_{status}",
        references=references,
    )


def _exploration_readiness_capability(
    *, profile_policy, exploration_plan, twin_key
):
    if not isinstance(profile_policy, AutoTwinProfilePolicy):
        raise TypeError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_PROFILE_POLICY_INVALID"
        )

    if not profile_policy.active_discovery:
        return _capability(
            status=AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED,
            reason="DISCOVERY_PROFILE_NOT_ACTIVE",
            references={"profile_key": profile_policy.profile_key},
        )

    if exploration_plan is None:
        return _capability(
            status=AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
            reason="NO_EXPLORATION_PLAN_EVIDENCE",
        )

    if (
        not isinstance(exploration_plan, dict)
        or exploration_plan.get("result_type")
        != AUTO_TWIN_EXPLORATION_CANDIDATE_PLAN_TYPE
    ):
        return _capability(
            status=AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
            reason="EXPLORATION_PLAN_EVIDENCE_INVALID",
        )

    if exploration_plan.get("twin_key") != twin_key:
        return _capability(
            status=AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
            reason="EXPLORATION_PLAN_TWIN_MISMATCH",
            references={
                "plan_twin_key": exploration_plan.get("twin_key"),
                "twin_key": twin_key,
            },
        )

    candidate_count = exploration_plan.get("candidate_count")

    if isinstance(candidate_count, bool) or not isinstance(
        candidate_count, int
    ):
        return _capability(
            status=AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
            reason="EXPLORATION_PLAN_CANDIDATE_COUNT_INVALID",
        )

    references = {
        "plan_id": exploration_plan.get("plan_id"),
        "source_fingerprint": exploration_plan.get("source_fingerprint"),
        "candidate_count": candidate_count,
        "rejected_count": exploration_plan.get("rejected_count"),
    }

    if candidate_count > 0:
        return _capability(
            status=AUTO_TWIN_CERTIFICATION_STATUS_PASS,
            reason="GOVERNED_SAFE_CANDIDATES_AVAILABLE",
            references=references,
        )

    return _capability(
        status=AUTO_TWIN_CERTIFICATION_STATUS_FAIL,
        reason="NO_GOVERNED_SAFE_CANDIDATES_AVAILABLE",
        references=references,
    )


def _overall_verdict(capability_matrix) -> str:
    statuses = tuple(
        capability_matrix[name]["status"]
        for name in AUTO_TWIN_CERTIFICATION_CAPABILITIES
    )

    if AUTO_TWIN_CERTIFICATION_STATUS_FAIL in statuses:
        return AUTO_TWIN_CERTIFICATION_STATUS_FAIL

    if AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED in statuses:
        return AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED

    if AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED in statuses:
        return AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED

    return AUTO_TWIN_CERTIFICATION_STATUS_PASS


def _certification_id(record) -> str:
    payload = deepcopy(record)
    payload.pop("certification_id", None)

    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def build_multi_site_certification(
    *,
    managed_site,
    twin_key,
    candidate_id,
    candidate_store,
    evidence_store,
    profile_policy,
    navigation_validation_store=None,
    materialized_revision_id=None,
    materialized_root=None,
    exploration_plan=None,
    suite_result=None,
):
    """Builds the UWT-12A multi-site certification foundation record.

    Reuses ``run_auto_twin_validation_suite`` (UWT-10) once -- or, if
    the caller already has a fresh one, the already-computed
    ``suite_result`` -- as the evidence for structural fidelity,
    transition/behavior fidelity and network/local safety, and
    ``exploration_plan`` (UWT-11A's own deterministic output, or
    ``None``) as the evidence for governed exploration readiness.
    Never executes a browser, never plans or runs an exploration
    session, never mutates ``candidate_store``/materialization and
    never promotes anything ACTIVE: this is purely a read-only
    composition over evidence those already-governed components
    already produced.

    Reusable verbatim across every managed site (Mercurio, Red SARA,
    DEHú, Nacionalidad, and any future one): every input is a generic
    identity or evidence object, never a site-specific rule.
    """

    if not isinstance(managed_site, AutoTwinManagedSite):
        raise TypeError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_MANAGED_SITE_INVALID"
        )

    if not isinstance(candidate_store, AutoTwinCandidateRevisionStore):
        raise TypeError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_CANDIDATE_STORE_INVALID"
        )

    if not isinstance(evidence_store, AutoTwinValidationEvidenceStore):
        raise TypeError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_EVIDENCE_STORE_INVALID"
        )

    if not isinstance(profile_policy, AutoTwinProfilePolicy):
        raise TypeError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_PROFILE_POLICY_INVALID"
        )

    normalized_twin_key = _required_text(
        twin_key, error="QCC_AUTO_TWIN_KEY_REQUIRED"
    )

    if managed_site.twin_key != normalized_twin_key:
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_SITE_TWIN_MISMATCH"
        )

    normalized_candidate_id = _required_text(
        candidate_id,
        error="QCC_AUTO_TWIN_CANDIDATE_ID_REQUIRED",
    )

    normalized_revision_id = (
        _text(materialized_revision_id) or None
    )

    if suite_result is None:
        suite_result = run_auto_twin_validation_suite(
            twin_key=normalized_twin_key,
            candidate_id=normalized_candidate_id,
            candidate_store=candidate_store,
            evidence_store=evidence_store,
            navigation_validation_store=navigation_validation_store,
            materialized_revision_id=normalized_revision_id,
            materialized_root=(
                materialized_root
                if materialized_root is not None
                else DEFAULT_MATERIALIZED_ROOT
            ),
        )

    if (
        not isinstance(suite_result, dict)
        or suite_result.get("result_type") != AUTO_TWIN_VALIDATION_SUITE_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_SUITE_RESULT_INVALID"
        )

    if suite_result.get("twin_key") != normalized_twin_key:
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_SUITE_RESULT_TWIN_MISMATCH"
        )

    if suite_result.get("candidate_id") != normalized_candidate_id:
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_SUITE_RESULT_CANDIDATE_MISMATCH"
        )

    capability_matrix = {
        AUTO_TWIN_CAPABILITY_STRUCTURAL_FIDELITY: (
            _capability_from_suite_section(
                suite_result,
                capability=AUTO_TWIN_CAPABILITY_STRUCTURAL_FIDELITY,
            )
        ),
        AUTO_TWIN_CAPABILITY_TRANSITION_BEHAVIOR_FIDELITY: (
            _capability_from_suite_section(
                suite_result,
                capability=(
                    AUTO_TWIN_CAPABILITY_TRANSITION_BEHAVIOR_FIDELITY
                ),
            )
        ),
        AUTO_TWIN_CAPABILITY_NETWORK_LOCAL_SAFETY: (
            _capability_from_suite_section(
                suite_result,
                capability=AUTO_TWIN_CAPABILITY_NETWORK_LOCAL_SAFETY,
            )
        ),
        AUTO_TWIN_CAPABILITY_GOVERNED_EXPLORATION_READINESS: (
            _exploration_readiness_capability(
                profile_policy=profile_policy,
                exploration_plan=exploration_plan,
                twin_key=normalized_twin_key,
            )
        ),
    }

    verdict = _overall_verdict(capability_matrix)

    record = {
        "schema_version": (
            AUTO_TWIN_MULTI_SITE_CERTIFICATION_SCHEMA_VERSION
        ),
        "result_type": AUTO_TWIN_MULTI_SITE_CERTIFICATION_TYPE,

        "site_identity": managed_site.to_dict(),

        "twin_revision_identity": {
            "twin_key": normalized_twin_key,
            "candidate_id": normalized_candidate_id,
            "candidate_revision": suite_result.get("candidate_revision"),
            "candidate_status": suite_result.get("candidate_status"),
            "materialized_revision_id": normalized_revision_id,
        },

        "capability_matrix": capability_matrix,

        "structural_fidelity_status": capability_matrix[
            AUTO_TWIN_CAPABILITY_STRUCTURAL_FIDELITY
        ]["status"],
        "transition_behavior_fidelity_status": capability_matrix[
            AUTO_TWIN_CAPABILITY_TRANSITION_BEHAVIOR_FIDELITY
        ]["status"],
        "network_local_safety_status": capability_matrix[
            AUTO_TWIN_CAPABILITY_NETWORK_LOCAL_SAFETY
        ]["status"],
        "governed_exploration_readiness_status": capability_matrix[
            AUTO_TWIN_CAPABILITY_GOVERNED_EXPLORATION_READINESS
        ]["status"],

        "certification_verdict": verdict,

        # Deliberately strict, mirroring UWT-10's own ``certifiable``:
        # only an overall PASS -- i.e. every required capability was
        # itself positively evaluated to PASS, none UNRESOLVED/
        # NOT_SUPPORTED/FAIL -- is ever treated as a certification
        # claim. This flag never promotes anything ACTIVE by itself.
        "certifiable": verdict == AUTO_TWIN_CERTIFICATION_STATUS_PASS,

        "evidence": {
            "suite_result_id": suite_result.get("suite_result_id"),
            "exploration_plan_id": (
                exploration_plan.get("plan_id")
                if isinstance(exploration_plan, dict)
                else None
            ),
        },
    }

    record["certification_id"] = _certification_id(record)

    return record
