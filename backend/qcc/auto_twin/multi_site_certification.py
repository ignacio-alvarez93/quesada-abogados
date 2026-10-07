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

Multi-site certification batch (UWT-12B)
-----------------------------------------

UWT-12B extends this same module -- it never introduces a second
certification engine -- with the generic, provider-neutral
composition that reduces *multiple* already-built UWT-12A
certification records (one per managed site, produced by
``build_multi_site_certification`` above) into one deterministic
batch:

- ``build_multi_site_certification_batch`` consumes a list of batch
  member requests, each binding a ``site_code`` identity slot to
  either an existing UWT-12A record or ``None`` (a required slot
  whose evidence has not been produced yet);
- member order never affects the result: members are always
  re-sorted by ``site_code`` before the batch is built, and the
  batch's own ``certification_batch_id`` is a stable sha256 digest
  over canonical JSON, exactly like ``certification_id`` above;
- every member keeps its own site identity and candidate/revision
  identity (``twin_key``/``candidate_id``/``candidate_revision``)
  verbatim from its UWT-12A record -- this module never recomputes
  or re-derives them;
- a missing member (``certification_record is None``), a malformed
  record (wrong ``result_type``/``schema_version``) and a record
  whose ``site_identity`` does not match the declared ``site_code``
  are all rejected or explicitly surfaced as ``UNRESOLVED`` -- never
  silently dropped;
- duplicate ``site_code`` slots and duplicate
  (``twin_key``, ``candidate_id``, ``candidate_revision``) identities
  across different slots are both rejected;
- the overall ``batch_verdict`` is ``PASS`` only when every *required*
  member's own ``certification_verdict`` is itself ``PASS``; any
  required member that is ``FAIL``/``UNRESOLVED``/``NOT_SUPPORTED``
  (or missing) is reflected both in ``batch_verdict`` and in the
  explicit ``unresolved_members`` list this batch carries;
- ``evidence.member_certification_ids`` is the exact provenance a
  reviewer needs to re-trace every member back to its own UWT-12A
  record;
- same governance as UWT-12A: purely a read-only composition over
  already-built records, no browser, no network, no REAL mutation,
  no candidate store access, no ACTIVE promotion, no site-specific
  rule.

Cross-site certification matrix (UWT-12C)
------------------------------------------

UWT-12C extends this same module once more -- it never introduces a
second certification engine, and it never replaces UWT-12B's own
batch roll-up -- with the generic, provider-neutral composition that
reduces a UWT-12B-shaped batch of member requests into one
deterministic *capability matrix* plus the diagnostics a reviewer
needs to triage a certification wave at a glance:

- ``build_cross_site_certification_matrix`` calls
  ``build_multi_site_certification_batch`` once, verbatim, to get the
  exact same validated, deduplicated, deterministically-ordered
  member list, ``batch_verdict`` and ``certifiable`` flag -- it never
  re-implements that validation or ordering;
- every matrix row re-exposes one member's own site identity, Twin
  revision/candidate identity, overall ``certification_verdict`` and,
  additionally, the per-capability status/reason already recorded on
  that member's own UWT-12A ``capability_matrix`` -- read directly
  from the caller-supplied ``certification_record``, never
  recomputed; a required slot whose record is still missing reduces
  to ``UNRESOLVED`` on every capability, exactly like UWT-12B's own
  missing-member handling;
- rows are always in the same site-code order as the underlying
  batch, so matrix serialization is deterministic independent of
  input order, exactly like ``certification_batch_id``;
- diagnostics summarize, without adding any new judgment: which
  sites are fully ``PASS``, which are ``FAIL``, which are
  ``UNRESOLVED`` (by overall verdict); which sites hit
  ``NOT_SUPPORTED`` for each capability; and, grouped by capability,
  every site/reason pair whose evidence for that capability is still
  an evidence gap (``UNRESOLVED``);
- same governance as UWT-12A/B: purely a read-only composition over
  already-built records and the already-built batch, no browser, no
  network, no REAL mutation, no candidate store access, no ACTIVE
  promotion, no site-specific rule, and it never weakens
  ``HUMAN_ONLY`` or any other governed boundary those upstream
  components already enforce.
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

AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_SCHEMA_VERSION = 1

AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_TYPE = (
    "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH"
)

# Explicit reason used for a declared batch member slot whose UWT-12A
# certification record has not been produced yet -- always surfaced
# as UNRESOLVED, never silently skipped or upgraded.
AUTO_TWIN_CERTIFICATION_BATCH_MEMBER_REASON_RECORD_MISSING = (
    "CERTIFICATION_RECORD_MISSING"
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


def _certification_batch_id(record) -> str:
    payload = deepcopy(record)
    payload.pop("certification_batch_id", None)

    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _batch_member(*, site_code, certification_record, required):
    normalized_site_code = _required_text(
        site_code,
        error=(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_MEMBER_SITE_CODE_"
            "REQUIRED"
        ),
    )
    normalized_required = bool(required)

    if certification_record is None:
        return {
            "site_code": normalized_site_code,
            "twin_key": None,
            "candidate_id": None,
            "candidate_revision": None,
            "required": normalized_required,
            "status": AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
            "reason": (
                AUTO_TWIN_CERTIFICATION_BATCH_MEMBER_REASON_RECORD_MISSING
            ),
            "certification_id": None,
        }

    if (
        not isinstance(certification_record, dict)
        or certification_record.get("result_type")
        != AUTO_TWIN_MULTI_SITE_CERTIFICATION_TYPE
        or certification_record.get("schema_version")
        != AUTO_TWIN_MULTI_SITE_CERTIFICATION_SCHEMA_VERSION
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_MEMBER_RECORD_"
            "INVALID"
        )

    site_identity = certification_record.get("site_identity")
    revision_identity = certification_record.get("twin_revision_identity")

    if not isinstance(site_identity, dict) or not isinstance(
        revision_identity, dict
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_MEMBER_RECORD_"
            "INVALID"
        )

    if _text(site_identity.get("site_code")) != normalized_site_code:
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_MEMBER_SITE_CODE_"
            "MISMATCH"
        )

    verdict = certification_record.get("certification_verdict")

    if verdict not in AUTO_TWIN_CERTIFICATION_STATUSES:
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_MEMBER_VERDICT_"
            "INVALID"
        )

    reason = (
        None
        if verdict == AUTO_TWIN_CERTIFICATION_STATUS_PASS
        else f"MEMBER_CERTIFICATION_VERDICT_{verdict}"
    )

    return {
        "site_code": normalized_site_code,
        "twin_key": _text(revision_identity.get("twin_key")) or None,
        "candidate_id": _text(revision_identity.get("candidate_id")) or None,
        "candidate_revision": revision_identity.get("candidate_revision"),
        "required": normalized_required,
        "status": verdict,
        "reason": reason,
        "certification_id": certification_record.get("certification_id"),
    }


def _batch_verdict(members) -> str:
    required_statuses = tuple(
        member["status"] for member in members if member["required"]
    )

    if not required_statuses:
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_NO_REQUIRED_"
            "MEMBERS"
        )

    if AUTO_TWIN_CERTIFICATION_STATUS_FAIL in required_statuses:
        return AUTO_TWIN_CERTIFICATION_STATUS_FAIL

    if AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED in required_statuses:
        return AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED

    if AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED in required_statuses:
        return AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED

    return AUTO_TWIN_CERTIFICATION_STATUS_PASS


def build_multi_site_certification_batch(*, members):
    """Builds the UWT-12B deterministic multi-site certification batch.

    ``members`` is a non-empty list of batch member requests, each a
    mapping with:

    - ``site_code`` (required): the stable identity slot for this
      member, independent of whether its evidence already exists;
    - ``certification_record``: an existing UWT-12A record (the exact
      ``dict`` returned by ``build_multi_site_certification``), or
      ``None`` if that site's certification has not been produced
      yet -- always surfaced as an explicit ``UNRESOLVED`` member,
      never silently skipped;
    - ``required`` (defaults to ``True``): whether this member must
      itself be ``PASS`` for the batch's overall ``batch_verdict`` to
      ever be ``PASS``.

    Never calls ``build_multi_site_certification`` itself, never reads
    any store, never mutates anything: purely a read-only composition
    over already-built UWT-12A records, reusable verbatim for any
    combination of managed sites.
    """

    if not isinstance(members, (list, tuple)) or not members:
        raise ValueError(
            "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_MEMBERS_REQUIRED"
        )

    built_members = []
    seen_site_codes = set()
    seen_revision_identities = set()

    for entry in members:
        if not isinstance(entry, dict):
            raise TypeError(
                "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_MEMBER_ENTRY_"
                "INVALID"
            )

        built = _batch_member(
            site_code=entry.get("site_code"),
            certification_record=entry.get("certification_record"),
            required=entry.get("required", True),
        )

        if built["site_code"] in seen_site_codes:
            raise ValueError(
                "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_DUPLICATE_"
                "SITE_CODE"
            )

        seen_site_codes.add(built["site_code"])

        revision_identity = (
            built["twin_key"],
            built["candidate_id"],
            built["candidate_revision"],
        )

        if revision_identity != (None, None, None):
            if revision_identity in seen_revision_identities:
                raise ValueError(
                    "QCC_AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_"
                    "DUPLICATE_REVISION_IDENTITY"
                )

            seen_revision_identities.add(revision_identity)

        built_members.append(built)

    ordered_members = tuple(
        sorted(built_members, key=lambda member: member["site_code"])
    )

    verdict = _batch_verdict(ordered_members)

    unresolved_members = tuple(
        {
            "site_code": member["site_code"],
            "twin_key": member["twin_key"],
            "candidate_id": member["candidate_id"],
            "required": member["required"],
            "status": member["status"],
            "reason": member["reason"],
        }
        for member in ordered_members
        if member["status"] != AUTO_TWIN_CERTIFICATION_STATUS_PASS
    )

    record = {
        "schema_version": (
            AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_SCHEMA_VERSION
        ),
        "result_type": AUTO_TWIN_MULTI_SITE_CERTIFICATION_BATCH_TYPE,

        "members": ordered_members,
        "member_count": len(ordered_members),
        "required_member_count": sum(
            1 for member in ordered_members if member["required"]
        ),

        "batch_verdict": verdict,

        # Mirrors UWT-12A's own ``certifiable``: only an overall PASS
        # -- every required member itself PASS -- is ever treated as
        # a batch certification claim.
        "certifiable": verdict == AUTO_TWIN_CERTIFICATION_STATUS_PASS,

        "unresolved_members": unresolved_members,

        "evidence": {
            "member_certification_ids": tuple(
                member["certification_id"] for member in ordered_members
            ),
        },
    }

    record["certification_batch_id"] = _certification_batch_id(record)

    return record


AUTO_TWIN_CROSS_SITE_CERTIFICATION_MATRIX_SCHEMA_VERSION = 1

AUTO_TWIN_CROSS_SITE_CERTIFICATION_MATRIX_TYPE = (
    "QCC_AUTO_TWIN_CROSS_SITE_CERTIFICATION_MATRIX"
)


def _matrix_id(record) -> str:
    payload = deepcopy(record)
    payload.pop("certification_matrix_id", None)

    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _matrix_capability_statuses(certification_record):
    if certification_record is None:
        return {
            capability: {
                "status": AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED,
                "reason": (
                    AUTO_TWIN_CERTIFICATION_BATCH_MEMBER_REASON_RECORD_MISSING
                ),
            }
            for capability in AUTO_TWIN_CERTIFICATION_CAPABILITIES
        }

    capability_matrix = certification_record.get("capability_matrix") or {}

    return {
        capability: {
            "status": (capability_matrix.get(capability) or {}).get(
                "status"
            ),
            "reason": (capability_matrix.get(capability) or {}).get(
                "reason"
            ),
        }
        for capability in AUTO_TWIN_CERTIFICATION_CAPABILITIES
    }


def build_cross_site_certification_matrix(*, members):
    """Builds the UWT-12C deterministic cross-site capability matrix.

    ``members`` has the exact same shape
    ``build_multi_site_certification_batch`` already accepts: a
    non-empty list of ``{"site_code", "certification_record",
    "required"}`` mappings, one per managed site. This function calls
    that batch builder once, verbatim, to get the validated,
    deduplicated, deterministically-ordered member list and the
    overall ``batch_verdict`` -- it never re-implements that
    validation -- and additionally reduces each member's own already-
    built UWT-12A ``capability_matrix`` into one matrix row plus the
    fixed diagnostics this Work Order requires.

    Purely read-only evidence: never promotes a Twin, never writes
    any store, never mutates ACTIVE, never executes a browser/network
    operation, never weakens ``HUMAN_ONLY``, never introduces a
    provider- or site-specific rule.
    """

    if not isinstance(members, (list, tuple)) or not members:
        raise ValueError(
            "QCC_AUTO_TWIN_CROSS_SITE_CERTIFICATION_MATRIX_MEMBERS_REQUIRED"
        )

    records_by_site_code = {}

    for entry in members:
        if not isinstance(entry, dict):
            raise TypeError(
                "QCC_AUTO_TWIN_CROSS_SITE_CERTIFICATION_MATRIX_MEMBER_"
                "ENTRY_INVALID"
            )

        site_code = _text(entry.get("site_code"))

        if site_code and site_code not in records_by_site_code:
            records_by_site_code[site_code] = entry.get(
                "certification_record"
            )

    batch = build_multi_site_certification_batch(members=members)

    rows = tuple(
        {
            "site_code": member["site_code"],
            "twin_key": member["twin_key"],
            "candidate_id": member["candidate_id"],
            "candidate_revision": member["candidate_revision"],
            "required": member["required"],
            "capability_matrix": _matrix_capability_statuses(
                records_by_site_code.get(member["site_code"])
            ),
            "certification_verdict": member["status"],
            "certification_id": member["certification_id"],
        }
        for member in batch["members"]
    )

    sites_fully_pass = tuple(
        row["site_code"]
        for row in rows
        if row["certification_verdict"] == AUTO_TWIN_CERTIFICATION_STATUS_PASS
    )
    sites_fail = tuple(
        row["site_code"]
        for row in rows
        if row["certification_verdict"] == AUTO_TWIN_CERTIFICATION_STATUS_FAIL
    )
    sites_unresolved = tuple(
        row["site_code"]
        for row in rows
        if row["certification_verdict"]
        == AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED
    )

    capabilities_not_supported = {
        capability: tuple(
            row["site_code"]
            for row in rows
            if row["capability_matrix"][capability]["status"]
            == AUTO_TWIN_CERTIFICATION_STATUS_NOT_SUPPORTED
        )
        for capability in AUTO_TWIN_CERTIFICATION_CAPABILITIES
    }

    evidence_gaps_by_capability = {
        capability: tuple(
            {
                "site_code": row["site_code"],
                "reason": row["capability_matrix"][capability]["reason"],
            }
            for row in rows
            if row["capability_matrix"][capability]["status"]
            == AUTO_TWIN_CERTIFICATION_STATUS_UNRESOLVED
        )
        for capability in AUTO_TWIN_CERTIFICATION_CAPABILITIES
    }

    record = {
        "schema_version": (
            AUTO_TWIN_CROSS_SITE_CERTIFICATION_MATRIX_SCHEMA_VERSION
        ),
        "result_type": AUTO_TWIN_CROSS_SITE_CERTIFICATION_MATRIX_TYPE,

        "matrix": rows,
        "row_count": len(rows),

        "certification_batch_id": batch["certification_batch_id"],
        "batch_verdict": batch["batch_verdict"],
        "certifiable": batch["certifiable"],

        "diagnostics": {
            "sites_fully_pass": sites_fully_pass,
            "sites_fail": sites_fail,
            "sites_unresolved": sites_unresolved,
            "capabilities_not_supported": capabilities_not_supported,
            "evidence_gaps_by_capability": evidence_gaps_by_capability,
        },

        "evidence": {
            "member_certification_ids": batch["evidence"][
                "member_certification_ids"
            ],
        },
    }

    record["certification_matrix_id"] = _matrix_id(record)

    return record
