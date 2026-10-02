"""QCC_BRANCH_CONTEXT_CAPTURE_V1 AUTO TWIN BranchContext resolver.

Pure, read-only resolution of a UWT-4 BranchContext for ONE specific
governed HumanNavigationCandidateStore candidate.

Reuses, without duplicating, the existing governed evidence pipeline:

    HumanNavigationCandidateStore.snapshot()
        -> project_twin_eligible_navigation_candidates()
        -> classify_twin_navigation_transition_outcomes()

A BranchContext is produced only when the candidate's own action group
is classified CONTEXTUAL_RESOLVED and the candidate belongs to exactly
one branch of that group. DETERMINISTIC, CONTEXTUAL_OPAQUE, an absent
candidate, or an ambiguous match all resolve to None: this module never
manufactures branch identity (section 2/6 of the work order).
"""

from __future__ import annotations

from backend.qcc.navigation_learning.human_candidate_store import (
    HumanNavigationCandidateStore,
)

from .navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED,
    classify_twin_navigation_transition_outcomes,
    project_twin_eligible_navigation_candidates,
)

from backend.qcc.universal_web.branch_context_capture import (
    build_branch_context_from_resolved_navigation_branch,
)


def _text(value):
    if not isinstance(value, str):
        return None

    value = value.strip()

    return value or None


def resolve_auto_twin_branch_context_for_candidate(
    candidate_store,
    *,
    site_code,
    environment,
    candidate_id,
):
    """Resolve a BranchContext for one governed navigation candidate.

    Returns None (fail closed) whenever the candidate is absent, its
    action group is not CONTEXTUAL_RESOLVED, or its branch match is
    ambiguous. Never raises on malformed/missing governed evidence.
    """

    if not isinstance(
        candidate_store,
        HumanNavigationCandidateStore,
    ):
        return None

    normalized_candidate_id = _text(candidate_id)

    if not normalized_candidate_id:
        return None

    normalized_site_code = _text(site_code)
    normalized_environment = _text(environment)

    if not normalized_site_code or not normalized_environment:
        return None

    try:
        snapshot = candidate_store.snapshot(
            normalized_site_code,
            environment=normalized_environment,
        )

        projected_candidates = (
            project_twin_eligible_navigation_candidates(
                snapshot
            )
        )

        action_groups = (
            classify_twin_navigation_transition_outcomes(
                projected_candidates
            )
        )
    except (TypeError, ValueError):
        return None

    matched_branches = []

    for action_group in action_groups:
        if (
            action_group.get("outcome_mode")
            != AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED
        ):
            continue

        for branch in action_group.get("branches") or ():
            candidate_ids = branch.get("candidate_ids") or ()

            if normalized_candidate_id in candidate_ids:
                matched_branches.append(branch)

    # Zero matches: candidate absent from any CONTEXTUAL_RESOLVED
    # branch. More than one match: ambiguous evidence. Both fail
    # closed rather than guessing.
    if len(matched_branches) != 1:
        return None

    return build_branch_context_from_resolved_navigation_branch(
        matched_branches[0]
    )
