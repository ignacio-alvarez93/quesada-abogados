"""Governed HUMAN_CONFIRMED registration of a historical transition.

QCC_HUMAN_CONFIRMED_BACKFILL_V1

Historical gap this closes
---------------------------

Live teaching (right-click CONTEXTMENU identification, or the
contextmenu-independent primary-click arm) always resolves a signal
against CURRENT/LiveActionEvidence captured in real time. Some trusted
causal transitions are only discovered AFTER the fact: a BEFORE
observation and an AFTER observation both exist, the causal DOM action
is known, but no live signal was ever captured for it (REAL was never
revisited to get one).

This module lets an operator explicitly ATTEST that exact causal fact
and feed it into the SAME canonical pipeline live teaching uses
(``backend.qcc.navigation_learning.runtime
.process_observed_human_navigation_learning``):

    QccObservedHumanTransition
        -> HumanNavigationCandidateStore (corroboration)
        -> promotion -> NavigationKnowledgeStore

It never fabricates causality on its own (no inference, no scoring) and
never bypasses the existing corroboration/promotion safety mechanism:
an explicit human attestation is registered as
``HUMAN_NAVIGATION_CANDIDATE_CONFIRMATION_COUNT`` deterministic,
idempotent corroboration slots, all derived from the SAME attested
identity, so a single governed call reaches the SAME "CONFIRMED and
promoted" state live teaching would reach after that many independent
observations -- without inventing a second storage schema or a second
promotion path.

Re-registering the exact same attested fact is a no-op: deterministic
event ids make every slot a duplicate once accepted.
"""

from __future__ import annotations

import hashlib

from backend.qcc.context.observed_human_transition import (
    QccObservedHumanTransition,
    normalize_utc_datetime,
)
from backend.qcc.navigation_learning.human_candidate_store import (
    HUMAN_NAVIGATION_CANDIDATE_CONFIRMATION_COUNT,
)
from backend.qcc.navigation_learning.runtime import (
    process_observed_human_navigation_learning,
)


QCC_HUMAN_CONFIRMED_BACKFILL_SOURCE = (
    "HUMAN_CONFIRMED"
)

QCC_HUMAN_CONFIRMED_BACKFILL_SESSION_ID = (
    "HUMAN_CONFIRMED_BACKFILL"
)

_EVENT_ID_NAMESPACE = (
    "QCC_HUMAN_CONFIRMED_BACKFILL"
)


def _required_text(
    value,
    error,
):
    text = str(
        value
        or ""
    ).strip()

    if not text:
        raise ValueError(
            error
        )

    return text


def _identity_component(
    value,
    *,
    upper=False,
):
    text = str(
        value
        or ""
    ).strip()

    return (
        text.upper()
        if upper
        else text
    )


def _confirmation_identity_key(
    *,
    site_code,
    environment,
    before_state,
    before_fingerprint,
    action_kind,
    action_selector,
    action_frame_path,
    after_state,
    after_fingerprint,
):
    return "|".join(
        [
            _identity_component(
                site_code,
                upper=True,
            ),
            _identity_component(
                environment,
                upper=True,
            ),
            _identity_component(
                before_state,
                upper=True,
            ),
            _identity_component(
                before_fingerprint
            ).lower(),
            _identity_component(
                action_kind,
                upper=True,
            ),
            _identity_component(
                action_selector
            ),
            (
                _identity_component(
                    action_frame_path
                )
                or "main"
            ),
            _identity_component(
                after_state,
                upper=True,
            ),
            _identity_component(
                after_fingerprint
            ).lower(),
        ]
    )


def _confirmation_event_id(
    *,
    identity_key,
    slot,
):
    digest = hashlib.sha256(
        (
            _EVENT_ID_NAMESPACE
            + ":"
            + identity_key
            + ":"
            + str(slot)
        ).encode(
            "utf-8"
        )
    ).hexdigest()

    return (
        _EVENT_ID_NAMESPACE
        + ":"
        + digest
    )


def register_human_confirmed_transition(
    candidate_store,
    knowledge_store,
    *,
    site_code,
    environment,
    before_state,
    before_fingerprint,
    action_kind,
    action_selector,
    action_frame_path,
    after_state,
    after_fingerprint,
    action_observed_at,
    after_observed_at,
    confirmed_by,
    action_policy="NAVIGATION_CANDIDATE",
    navigation_context=(),
):
    """Register one operator-confirmed historical causal transition.

    Returns a summary dict. Calling this again with the EXACT same
    arguments is idempotent: ``idempotent`` is True and no new
    corroboration/promotion happens.
    """

    confirmed_by = _required_text(
        confirmed_by,
        "QCC_HUMAN_CONFIRMED_BACKFILL_CONFIRMED_BY_REQUIRED",
    )

    normalized_action_observed_at = (
        normalize_utc_datetime(
            action_observed_at,
            "QCC_HUMAN_CONFIRMED_BACKFILL_ACTION_TIME_INVALID",
        )
    )

    normalized_after_observed_at = (
        normalize_utc_datetime(
            after_observed_at,
            "QCC_HUMAN_CONFIRMED_BACKFILL_AFTER_TIME_INVALID",
        )
    )

    identity_key = (
        _confirmation_identity_key(
            site_code=site_code,
            environment=environment,
            before_state=before_state,
            before_fingerprint=before_fingerprint,
            action_kind=action_kind,
            action_selector=action_selector,
            action_frame_path=action_frame_path,
            after_state=after_state,
            after_fingerprint=after_fingerprint,
        )
    )

    learning_results = []

    for slot in range(
        1,
        HUMAN_NAVIGATION_CANDIDATE_CONFIRMATION_COUNT
        + 1,
    ):
        transition = (
            QccObservedHumanTransition(
                event_id=(
                    _confirmation_event_id(
                        identity_key=identity_key,
                        slot=slot,
                    )
                ),
                session_id=(
                    QCC_HUMAN_CONFIRMED_BACKFILL_SESSION_ID
                ),
                site_code=site_code,
                environment=environment,
                before_state=before_state,
                before_fingerprint=before_fingerprint,
                kind=action_kind,
                policy=action_policy,
                selector=action_selector,
                frame_path=action_frame_path,
                after_state=after_state,
                after_fingerprint=after_fingerprint,
                action_observed_at=(
                    normalized_action_observed_at
                ),
                after_observed_at=(
                    normalized_after_observed_at
                ),
                navigation_context=(
                    navigation_context
                ),
            )
        )

        learning_results.append(
            process_observed_human_navigation_learning(
                candidate_store,
                knowledge_store,
                transition=transition,
            )
        )

    final = learning_results[-1]

    newly_recorded = any(
        result[
            "candidate_recorded"
        ]
        for result
        in learning_results
    )

    return {
        "source":
            QCC_HUMAN_CONFIRMED_BACKFILL_SOURCE,

        "confirmed_by":
            confirmed_by,

        "candidate_id":
            final[
                "candidate_id"
            ],

        "candidate_status":
            final[
                "candidate_status"
            ],

        "idempotent":
            not newly_recorded,

        "promotion_count":
            sum(
                result[
                    "promotion_count"
                ]
                for result
                in learning_results
            ),

        "knowledge_recorded_count":
            sum(
                result[
                    "knowledge_recorded_count"
                ]
                for result
                in learning_results
            ),

        "knowledge_already_recorded_count":
            sum(
                result[
                    "knowledge_already_recorded_count"
                ]
                for result
                in learning_results
            ),
    }
