"""Controlled promotion of trusted human navigation evidence.

A confirmed candidate can be promoted into NavigationKnowledge.

Important invariants:

- CANDIDATE/CORROBORATED evidence never reaches Knowledge.
- Every trusted event becomes at most one Knowledge observation.
- interrupted promotion is safely resumable.
- learning navigation never changes action policy or grants execution.
"""

from __future__ import annotations

from backend.automation.site_architecture.state_transition import (
    STATE_TRANSITION_CHANGED,
    STATE_TRANSITION_CONFIDENCE_HIGH,
    STATE_TRANSITION_SCHEMA_VERSION,
    STATE_TRANSITION_TYPE,
)

from .human_candidate_store import (
    HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED,
)


HUMAN_NAVIGATION_PROMOTION_OBSERVATION_PREFIX = (
    "QCC_HUMAN_CAUSAL"
)


def build_human_candidate_state_transition(
    candidate,
):
    """Build the PII-safe StateTransition stored in Knowledge.

    HIGH means high confidence in the repeatedly observed functional
    causal transition. It does NOT mean automation is allowed.
    """

    if not isinstance(
        candidate,
        dict,
    ):
        raise ValueError(
            "QCC_HUMAN_NAVIGATION_PROMOTION_CANDIDATE_INVALID"
        )

    if (
        candidate.get(
            "status"
        )
        != HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED
    ):
        raise ValueError(
            "QCC_HUMAN_NAVIGATION_PROMOTION_REQUIRES_CONFIRMED"
        )

    action = candidate.get(
        "action"
    )

    if not isinstance(
        action,
        dict,
    ):
        raise ValueError(
            "QCC_HUMAN_NAVIGATION_PROMOTION_ACTION_INVALID"
        )

    return {
        "schema_version":
            STATE_TRANSITION_SCHEMA_VERSION,

        "transition_type":
            STATE_TRANSITION_TYPE,

        "changed":
            True,

        "status":
            STATE_TRANSITION_CHANGED,

        "before_fingerprint":
            candidate[
                "before_fingerprint"
            ],

        "after_fingerprint":
            candidate[
                "after_fingerprint"
            ],

        "action": {
            "kind":
                action.get(
                    "kind"
                ),

            "policy":
                action.get(
                    "policy"
                ),

            "selector":
                action.get(
                    "selector"
                ),

            "frame_path":
                action.get(
                    "frame_path"
                )
                or "main",
        },

        # Three independent trusted causal observations make the
        # functional transition high-confidence.
        #
        # This is evidence confidence, never execution authority.
        "confidence":
            STATE_TRANSITION_CONFIDENCE_HIGH,

        # Structural contract evidence is not reconstructed here.
        # Knowledge stores only the safe transition projection.
        "contract_changed":
            False,

        "inconclusive":
            False,
    }


def _promotion_observation_id(
    candidate_id,
    event_id,
):
    candidate_id = str(
        candidate_id
        or ""
    ).strip()

    event_id = str(
        event_id
        or ""
    ).strip()

    if (
        not candidate_id
        or not event_id
    ):
        raise ValueError(
            "QCC_HUMAN_NAVIGATION_PROMOTION_OBSERVATION_ID_INVALID"
        )

    return (
        HUMAN_NAVIGATION_PROMOTION_OBSERVATION_PREFIX
        + ":"
        + candidate_id
        + ":"
        + event_id
    )


def promote_confirmed_human_candidate(
    candidate_store,
    knowledge_store,
    *,
    site_code,
    environment,
    candidate_id,
):
    """Promote one confirmed candidate safely.

    Promotion is resumable:

    If execution stops after writing N observations but before the
    candidate is marked promoted, retrying the operation will skip
    those N observation IDs and write only the missing ones.
    """

    snapshot = candidate_store.snapshot(
        site_code,
        environment=environment,
    )

    candidate = next(
        (
            item
            for item
            in snapshot[
                "candidates"
            ]
            if item.get(
                "candidate_id"
            )
            == candidate_id
        ),
        None,
    )

    if candidate is None:
        raise ValueError(
            "QCC_HUMAN_NAVIGATION_PROMOTION_CANDIDATE_NOT_FOUND"
        )

    if (
        candidate.get(
            "status"
        )
        != HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED
    ):
        raise ValueError(
            "QCC_HUMAN_NAVIGATION_PROMOTION_REQUIRES_CONFIRMED"
        )

    event_ids = candidate.get(
        "event_ids"
    )

    if (
        not isinstance(
            event_ids,
            list,
        )
        or len(
            event_ids
        )
        < 3
    ):
        raise ValueError(
            "QCC_HUMAN_NAVIGATION_PROMOTION_EVIDENCE_INSUFFICIENT"
        )

    transition = (
        build_human_candidate_state_transition(
            candidate
        )
    )

    recorded_count = 0
    duplicate_count = 0

    for event_id in event_ids:
        result = (
            knowledge_store
            .record_transition_once(
                site_code,
                transition,
                observation_id=(
                    _promotion_observation_id(
                        candidate_id,
                        event_id,
                    )
                ),
                environment=environment,
                before_state=(
                    candidate[
                        "before_state"
                    ]
                ),
                after_state=(
                    candidate[
                        "after_state"
                    ]
                ),
            )
        )

        if result[
            "recorded"
        ]:
            recorded_count += 1
        else:
            duplicate_count += 1

    # Mark only after every Knowledge observation has either:
    # - been written now, or
    # - already existed from a previous partial attempt.
    promoted = (
        candidate_store
        .mark_promoted(
            site_code,
            candidate_id,
            environment=environment,
        )
    )

    return {
        "promoted":
            True,

        "candidate_id":
            candidate_id,

        "observation_count":
            len(
                event_ids
            ),

        "recorded_count":
            recorded_count,

        "already_recorded_count":
            duplicate_count,

        "promoted_at":
            promoted.get(
                "promoted_at"
            ),

        "transition":
            transition,
    }
