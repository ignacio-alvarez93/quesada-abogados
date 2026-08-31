"""Runtime coordination for trusted human navigation learning.

This module is the only runtime junction between:

    ObservedHumanTransition
        -> candidate evidence
        -> controlled promotion
        -> NavigationKnowledge

The coordinator never changes action policy and never grants
automation authority.

Errors intentionally propagate to the Bridge boundary, where learning
fails closed while the capture itself remains fail-open.
"""

from __future__ import annotations

from .human_candidate_promoter import (
    promote_confirmed_human_candidate,
)


HUMAN_NAVIGATION_LEARNING_RUNTIME_TYPE = (
    "QCC_HUMAN_NAVIGATION_LEARNING"
)


def process_observed_human_navigation_learning(
    candidate_store,
    knowledge_store,
    *,
    transition=None,
    site_code=None,
    environment=None,
):
    """Record causal evidence and promote confirmed candidates.

    The method also retries previously confirmed/unpromoted candidates.
    Therefore a transient persistence failure cannot strand a confirmed
    transition forever.
    """

    candidate_result = None
    current_candidate = None

    if transition is not None:
        candidate_result = (
            candidate_store
            .record_observed_transition(
                transition
            )
        )

        current_candidate = (
            candidate_result[
                "candidate"
            ]
        )

        site_code = (
            current_candidate[
                "site_code"
            ]
        )

        environment = (
            current_candidate[
                "environment"
            ]
        )

    site_code = str(
        site_code
        or ""
    ).strip()

    environment = str(
        environment
        or ""
    ).strip()

    if not site_code:
        raise ValueError(
            "QCC_HUMAN_NAVIGATION_LEARNING_SITE_REQUIRED"
        )

    if not environment:
        raise ValueError(
            "QCC_HUMAN_NAVIGATION_LEARNING_ENVIRONMENT_REQUIRED"
        )

    pending = (
        candidate_store
        .confirmed_unpromoted(
            site_code,
            environment=environment,
        )
    )

    promotions = []

    for candidate in pending:
        promotion = (
            promote_confirmed_human_candidate(
                candidate_store,
                knowledge_store,
                site_code=site_code,
                environment=environment,
                candidate_id=(
                    candidate[
                        "candidate_id"
                    ]
                ),
            )
        )

        promotions.append(
            promotion
        )

    return {
        "learning_type":
            HUMAN_NAVIGATION_LEARNING_RUNTIME_TYPE,

        "processed":
            True,

        "candidate_recorded":
            (
                candidate_result[
                    "recorded"
                ]
                if candidate_result
                is not None
                else False
            ),

        "duplicate_event":
            (
                candidate_result[
                    "duplicate_event"
                ]
                if candidate_result
                is not None
                else False
            ),

        "candidate_id":
            (
                current_candidate[
                    "candidate_id"
                ]
                if current_candidate
                is not None
                else None
            ),

        "candidate_status":
            (
                current_candidate[
                    "status"
                ]
                if current_candidate
                is not None
                else None
            ),

        "candidate_observation_count":
            (
                current_candidate[
                    "observation_count"
                ]
                if current_candidate
                is not None
                else None
            ),

        "promotion_count":
            len(
                promotions
            ),

        "knowledge_recorded_count":
            sum(
                int(
                    item[
                        "recorded_count"
                    ]
                )
                for item in promotions
            ),

        "knowledge_already_recorded_count":
            sum(
                int(
                    item[
                        "already_recorded_count"
                    ]
                )
                for item in promotions
            ),
    }
