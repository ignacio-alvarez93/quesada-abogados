"""AUTO TWIN navigation transition materialization contracts.

This module projects trusted REAL causal navigation evidence into
provider-neutral transition candidates that are eligible for controlled
Twin materialization/replay.

Important:

- One trusted REAL causal observation is sufficient for TWIN_ELIGIBLE.
- TWIN_ELIGIBLE does not grant REAL automation authority.
- No provider-specific behavior belongs here.
- Event IDs are deliberately not exported into the Twin artifact.
"""

from __future__ import annotations

import hashlib
import json
import re

from backend.qcc.context.navigation_context import (
    derive_navigation_discriminator_keys,
    navigation_context_signature,
    navigation_context_to_json,
    project_navigation_context,
)

from backend.qcc.context.observed_human_transition import (
    normalize_utc_datetime,
)



AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION = 1

AUTO_TWIN_NAVIGATION_TRANSITION_TYPE = (
    "QCC_AUTO_TWIN_NAVIGATION_TRANSITION"
)

AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE = (
    "TRUSTED_DOM_HUMAN_CAUSAL_JOIN"
)

AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE = (
    "TWIN_ELIGIBLE"
)

AUTO_TWIN_NAVIGATION_ACTION_GROUP_SCHEMA_VERSION = 1

AUTO_TWIN_NAVIGATION_ACTION_GROUP_TYPE = (
    "QCC_AUTO_TWIN_NAVIGATION_ACTION_GROUP"
)

AUTO_TWIN_NAVIGATION_OUTCOME_DETERMINISTIC = (
    "DETERMINISTIC"
)

AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED = (
    "CONTEXTUAL_RESOLVED"
)

AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_OPAQUE = (
    "CONTEXTUAL_OPAQUE"
)

_FINGERPRINT_RE = re.compile(
    r"^[0-9a-fA-F]{64}$"
)


def _text(value):
    result = str(
        value
        or ""
    ).strip()

    return (
        result
        or None
    )


def _fingerprint(
    value,
    *,
    error,
):
    result = _text(
        value
    )

    if (
        result is None
        or not _FINGERPRINT_RE.fullmatch(
            result
        )
    ):
        raise ValueError(
            error
        )

    return result.lower()


def _safe_action(
    value,
):
    if not isinstance(
        value,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_ACTION_INVALID"
        )

    kind = _text(
        value.get(
            "kind"
        )
    )

    policy = _text(
        value.get(
            "policy"
        )
    )

    selector = _text(
        value.get(
            "selector"
        )
    )

    frame_path = (
        _text(
            value.get(
                "frame_path"
            )
        )
        or "main"
    )

    if not kind:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_ACTION_KIND_REQUIRED"
        )

    if not policy:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_ACTION_POLICY_REQUIRED"
        )

    if not selector:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_ACTION_SELECTOR_REQUIRED"
        )

    return {
        "kind":
            kind,

        "policy":
            policy,

        "selector":
            selector,

        "frame_path":
            frame_path,
    }



def normalize_twin_navigation_transitions(
    transitions,
):
    """Normalize immutable TWIN_ELIGIBLE transition evidence."""

    if not isinstance(
        transitions,
        (list, tuple),
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_TRANSITIONS_INVALID"
        )

    normalized = []

    for transition in transitions:
        if not isinstance(
            transition,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_TRANSITION_INVALID"
            )

        if (
            transition.get(
                "schema_version"
            )
            != AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_SCHEMA_INVALID"
            )

        if (
            transition.get(
                "transition_type"
            )
            != AUTO_TWIN_NAVIGATION_TRANSITION_TYPE
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_TYPE_INVALID"
            )

        if (
            _text(
                transition.get(
                    "eligibility"
                )
            )
            != AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_NOT_TWIN_ELIGIBLE"
            )

        if (
            _text(
                transition.get(
                    "evidence_source"
                )
            )
            != AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE_INVALID"
            )

        candidate_id = _text(
            transition.get(
                "candidate_id"
            )
        )

        if not candidate_id:
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_CANDIDATE_ID_REQUIRED"
            )

        observation_count = int(
            transition.get(
                "real_observation_count"
            )
            or 0
        )

        if observation_count < 1:
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_REAL_EVIDENCE_REQUIRED"
            )

        normalized.append({
            "schema_version":
                AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,

            "transition_type":
                AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,

            "candidate_id":
                candidate_id,

            "eligibility":
                AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,

            "evidence_source":
                AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,

            "real_observation_count":
                observation_count,

            "candidate_status":
                (
                    _text(
                        transition.get(
                            "candidate_status"
                        )
                    )
                    or "UNKNOWN"
                ),

            "navigation_context":
                navigation_context_to_json(
                    transition.get(
                        "navigation_context"
                    )
                    or ()
                ),

            "context_signature":
                navigation_context_signature(
                    transition.get(
                        "navigation_context"
                    )
                    or ()
                ),

            "before_fingerprint":
                _fingerprint(
                    transition.get(
                        "before_fingerprint"
                    ),
                    error=(
                        "QCC_AUTO_TWIN_NAVIGATION_BEFORE_FINGERPRINT_INVALID"
                    ),
                ),

            "after_fingerprint":
                _fingerprint(
                    transition.get(
                        "after_fingerprint"
                    ),
                    error=(
                        "QCC_AUTO_TWIN_NAVIGATION_AFTER_FINGERPRINT_INVALID"
                    ),
                ),

            "action":
                _safe_action(
                    transition.get(
                        "action"
                    )
                ),
        })

    normalized.sort(
        key=lambda item: (
            item[
                "before_fingerprint"
            ],
            item[
                "action"
            ][
                "frame_path"
            ],
            item[
                "action"
            ][
                "selector"
            ],
            item[
                "after_fingerprint"
            ],
            item[
                "candidate_id"
            ],
        )
    )

    return tuple(
        json.loads(
            json.dumps(
                item
            )
        )
        for item in normalized
    )

def _navigation_action_group_id(
    *,
    before_fingerprint,
    action,
):
    identity = {
        "before_fingerprint":
            before_fingerprint,

        "action":
            action,
    }

    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()



def classify_twin_navigation_transition_outcomes(
    transitions,
):
    """Classify REAL causal evidence by source action.

    DETERMINISTIC:
        one target.

    CONTEXTUAL_RESOLVED:
        multiple targets whose discriminator can be derived from
        pre-action discrete selection context.

    CONTEXTUAL_OPAQUE:
        multiple targets without sufficient branch evidence.
    """

    normalized = (
        normalize_twin_navigation_transitions(
            transitions
        )
    )

    groups = {}

    for transition in normalized:
        before_fingerprint = transition[
            "before_fingerprint"
        ]

        action = transition[
            "action"
        ]

        action_group_id = (
            _navigation_action_group_id(
                before_fingerprint=
                    before_fingerprint,
                action=action,
            )
        )

        group = groups.setdefault(
            action_group_id,
            {
                "action_group_id":
                    action_group_id,

                "before_fingerprint":
                    before_fingerprint,

                "action":
                    json.loads(
                        json.dumps(
                            action
                        )
                    ),

                "outcomes":
                    {},

                "transitions":
                    [],
            },
        )

        group[
            "transitions"
        ].append(
            transition
        )

        after_fingerprint = transition[
            "after_fingerprint"
        ]

        outcome = group[
            "outcomes"
        ].setdefault(
            after_fingerprint,
            {
                "after_fingerprint":
                    after_fingerprint,

                "candidates":
                    {},
            },
        )

        candidate_id = transition[
            "candidate_id"
        ]

        observation_count = int(
            transition.get(
                "real_observation_count"
            )
            or 0
        )

        previous_count = outcome[
            "candidates"
        ].get(
            candidate_id,
            0,
        )

        outcome[
            "candidates"
        ][
            candidate_id
        ] = max(
            previous_count,
            observation_count,
        )

    result = []

    for group in groups.values():
        outcomes = []

        for (
            after_fingerprint,
            details,
        ) in group[
            "outcomes"
        ].items():
            candidate_counts = details[
                "candidates"
            ]

            candidate_ids = sorted(
                candidate_counts
            )

            outcomes.append({
                "after_fingerprint":
                    after_fingerprint,

                "candidate_ids":
                    candidate_ids,

                "real_observation_count":
                    sum(
                        candidate_counts.values()
                    ),
            })

        outcomes.sort(
            key=lambda item:
                item[
                    "after_fingerprint"
                ]
        )

        discriminator_keys = ()
        branches = []

        if len(
            outcomes
        ) == 1:
            outcome_mode = (
                AUTO_TWIN_NAVIGATION_OUTCOME_DETERMINISTIC
            )

        else:
            discriminator_keys = (
                derive_navigation_discriminator_keys(
                    group[
                        "transitions"
                    ]
                )
            )

            if discriminator_keys:
                branch_index = {}
                valid = True

                for transition in group[
                    "transitions"
                ]:
                    projected = (
                        navigation_context_to_json(
                            project_navigation_context(
                                transition.get(
                                    "navigation_context"
                                )
                                or (),
                                discriminator_keys,
                            )
                        )
                    )

                    context_signature = (
                        navigation_context_signature(
                            projected
                        )
                    )

                    if not context_signature:
                        valid = False
                        break

                    after_fingerprint = (
                        transition[
                            "after_fingerprint"
                        ]
                    )

                    branch = (
                        branch_index
                        .setdefault(
                            context_signature,
                            {
                                "context_signature":
                                    context_signature,

                                "navigation_context":
                                    projected,

                                "after_fingerprint":
                                    after_fingerprint,

                                "candidate_counts":
                                    {},
                            },
                        )
                    )

                    if (
                        branch[
                            "after_fingerprint"
                        ]
                        != after_fingerprint
                    ):
                        valid = False
                        break

                    candidate_id = transition[
                        "candidate_id"
                    ]

                    count = int(
                        transition.get(
                            "real_observation_count"
                        )
                        or 0
                    )

                    branch[
                        "candidate_counts"
                    ][
                        candidate_id
                    ] = max(
                        branch[
                            "candidate_counts"
                        ].get(
                            candidate_id,
                            0,
                        ),
                        count,
                    )

                if valid:
                    for branch in (
                        branch_index.values()
                    ):
                        candidate_counts = branch.pop(
                            "candidate_counts"
                        )

                        branch[
                            "candidate_ids"
                        ] = sorted(
                            candidate_counts
                        )

                        branch[
                            "real_observation_count"
                        ] = sum(
                            candidate_counts.values()
                        )

                        branches.append(
                            branch
                        )

                    branches.sort(
                        key=lambda item:
                            item[
                                "context_signature"
                            ]
                    )

                    if (
                        len({
                            branch[
                                "after_fingerprint"
                            ]
                            for branch
                            in branches
                        })
                        == len(
                            outcomes
                        )
                    ):
                        outcome_mode = (
                            AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED
                        )

                    else:
                        outcome_mode = (
                            AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_OPAQUE
                        )
                        branches = []
                        discriminator_keys = ()

                else:
                    outcome_mode = (
                        AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_OPAQUE
                    )
                    branches = []
                    discriminator_keys = ()

            else:
                outcome_mode = (
                    AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_OPAQUE
                )

        result.append({
            "schema_version":
                AUTO_TWIN_NAVIGATION_ACTION_GROUP_SCHEMA_VERSION,

            "record_type":
                AUTO_TWIN_NAVIGATION_ACTION_GROUP_TYPE,

            "action_group_id":
                group[
                    "action_group_id"
                ],

            "outcome_mode":
                outcome_mode,

            "outcome_count":
                len(
                    outcomes
                ),

            "before_fingerprint":
                group[
                    "before_fingerprint"
                ],

            "action":
                group[
                    "action"
                ],

            "discriminator_keys":
                list(
                    discriminator_keys
                ),

            "branches":
                branches,

            "outcomes":
                outcomes,
        })

    result.sort(
        key=lambda item: (
            item[
                "before_fingerprint"
            ],
            item[
                "action"
            ][
                "frame_path"
            ],
            item[
                "action"
            ][
                "selector"
            ],
            item[
                "action_group_id"
            ],
        )
    )

    return tuple(
        json.loads(
            json.dumps(
                item
            )
        )
        for item in result
    )



def project_twin_eligible_navigation_candidates(
    candidate_snapshot,
):
    """Project trusted REAL causal candidates for Twin validation.

    Eligibility is deliberately weaker than NavigationKnowledge
    promotion:

        >= 1 trusted REAL causal observation
            -> TWIN_ELIGIBLE

    This says only that the transition may be materialized and tested
    inside the controlled local Twin.
    """

    if not isinstance(
        candidate_snapshot,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_CANDIDATE_SNAPSHOT_INVALID"
        )

    candidates = candidate_snapshot.get(
        "candidates"
    )

    if not isinstance(
        candidates,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_CANDIDATES_INVALID"
        )

    projected = []

    for candidate in candidates:
        if not isinstance(
            candidate,
            dict,
        ):
            continue

        if (
            _text(
                candidate.get(
                    "evidence_source"
                )
            )
            != AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE
        ):
            continue

        observation_count = int(
            candidate.get(
                "observation_count"
            )
            or 0
        )

        if observation_count < 1:
            continue

        candidate_id = _text(
            candidate.get(
                "candidate_id"
            )
        )

        if not candidate_id:
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_CANDIDATE_ID_REQUIRED"
            )

        projected.append({
            "schema_version":
                AUTO_TWIN_NAVIGATION_TRANSITION_SCHEMA_VERSION,

            "transition_type":
                AUTO_TWIN_NAVIGATION_TRANSITION_TYPE,

            "candidate_id":
                candidate_id,

            "eligibility":
                AUTO_TWIN_NAVIGATION_EVIDENCE_TWIN_ELIGIBLE,

            "evidence_source":
                AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,

            "real_observation_count":
                observation_count,

            "candidate_status":
                (
                    _text(
                        candidate.get(
                            "status"
                        )
                    )
                    or "UNKNOWN"
                ),

            "navigation_context":
                navigation_context_to_json(
                    candidate.get(
                        "navigation_context"
                    )
                    or ()
                ),

            "context_signature":
                navigation_context_signature(
                    candidate.get(
                        "navigation_context"
                    )
                    or ()
                ),

            "before_fingerprint":
                _fingerprint(
                    candidate.get(
                        "before_fingerprint"
                    ),
                    error=(
                        "QCC_AUTO_TWIN_NAVIGATION_BEFORE_FINGERPRINT_INVALID"
                    ),
                ),

            "after_fingerprint":
                _fingerprint(
                    candidate.get(
                        "after_fingerprint"
                    ),
                    error=(
                        "QCC_AUTO_TWIN_NAVIGATION_AFTER_FINGERPRINT_INVALID"
                    ),
                ),

            "action":
                _safe_action(
                    candidate.get(
                        "action"
                    )
                ),
        })

    projected.sort(
        key=lambda item: (
            item[
                "before_fingerprint"
            ],
            item[
                "action"
            ][
                "frame_path"
            ],
            item[
                "action"
            ][
                "selector"
            ],
            item[
                "after_fingerprint"
            ],
            item[
                "candidate_id"
            ],
        )
    )

    # Defensive JSON roundtrip: this contract is persisted later.
    return tuple(
        json.loads(
            json.dumps(
                item
            )
        )
        for item in projected
    )


# QCC_AUTO_TWIN_CONTEXTUAL_SUPERSESSION_TARGET_REBIND_V1 (2D-20R)
#
# A governed observation supersession (AutoTwinObservationStore.
# supersede(), 2D-20K) may replace one old_state_key with TWO OR MORE
# replacement_state_keys (a 1->N split). A historical human navigation
# candidate recorded before the split still targets the old, now-stale
# content fingerprint and can never be replayed against it again.
#
# Raw branch codes/navigation_context NEVER define physical state
# identity (see 2D-20H/2D-20J). This resolver therefore never inspects
# candidate.navigation_context values directly. It only recognizes a
# governed, already-persisted, per-replacement corroboration recorded
# on the supersession record itself at PROVENANCE_CORROBORATION_KEY --
# CURRENT evidence, immutable once written, exactly like the rest of
# the supersession record.
#
# A candidate's target is rebound from the stale fingerprint to a
# replacement's CURRENT fingerprint only when ALL of the following
# hold simultaneously:
#
# - the stale fingerprint historically belonged to exactly one
#   old_state_key that is itself the subject of exactly one governed
#   supersession record;
# - that supersession is genuinely 1->N (>= 2 replacement_state_keys);
# - the candidate carries a non-empty normalized navigation
#   context_signature;
# - the supersession's provenance corroboration declares, for exactly
#   one of its declared replacements, the SAME context_signature;
# - that same corroboration entry's recorded fingerprint matches the
#   replacement's actual CURRENT observed fingerprint (capability
#   identity double-check against provenance drift).
#
# Zero or multiple qualifying replacements -- or any missing input --
# fail closed: the candidate is returned unchanged, which leaves its
# stale fingerprint unresolved and lets the existing conservative
# fingerprint-existence gate in automatic_materialization.py exclude
# it, exactly as it already does today. Historical candidate evidence
# in HumanNavigationCandidateStore is never rewritten; only this
# pass's in-memory projected transition list is affected.
PROVENANCE_CORROBORATION_KEY = (
    "replacement_navigation_context_signatures"
)


def _contextual_supersession_corroboration(record):
    """Read the governed per-replacement corroboration off one record.

    Returns {replacement_state_key: (context_signature, fingerprint)},
    dropping any entry that is not a well-formed pair of hex strings.
    Absent/malformed provenance is a no-op (empty dict), never a crash
    -- provenance is an optional, caller-supplied dict per
    AutoTwinObservationStore.supersede().
    """

    if not isinstance(record, dict):
        return {}

    provenance = record.get("provenance")

    if not isinstance(provenance, dict):
        return {}

    entries = provenance.get(PROVENANCE_CORROBORATION_KEY)

    if not isinstance(entries, dict):
        return {}

    result = {}

    for replacement_key, entry in entries.items():
        key = _text(replacement_key)

        if not key or not isinstance(entry, dict):
            continue

        signature = _text(entry.get("context_signature"))
        fingerprint = _text(entry.get("fingerprint"))

        if not signature or not fingerprint:
            continue

        result[key] = (signature.lower(), fingerprint.lower())

    return result


def _contextual_supersession_fingerprint_owners(historical_states):
    """Map each historically-observed content fingerprint to its
    owning state_key(s).

    Built from the UNFILTERED (historical) observation snapshot --
    a superseded state_key is deliberately absent from any CURRENT
    view, but its fingerprint must still be recognized here so a
    stale candidate can be matched to the supersession that replaced
    it.
    """

    index = {}

    for state_key, state in (
        historical_states.items()
        if isinstance(historical_states, dict)
        else ()
    ):
        if not isinstance(state, dict):
            continue

        key = _text(state_key)

        fingerprint = _text(
            state.get("last_fingerprint")
        )

        if not key or not fingerprint:
            continue

        index.setdefault(
            fingerprint.lower(), set()
        ).add(key)

    return index


def resolve_contextual_supersession_navigation_target(
    *,
    after_fingerprint,
    context_signature,
    twin_supersessions,
    fingerprint_owners,
    current_states,
):
    """Resolve one stale 1->N-superseded target fingerprint.

    Returns the corroborated replacement's CURRENT fingerprint, or
    None when the candidate does not qualify -- see the module-level
    QCC_AUTO_TWIN_CONTEXTUAL_SUPERSESSION_TARGET_REBIND_V1 note for
    the exact fail-closed contract.
    """

    stale_fingerprint = _text(after_fingerprint)
    signature = _text(context_signature)

    if not stale_fingerprint or not signature:
        return None

    if not isinstance(twin_supersessions, dict):
        return None

    owners = (fingerprint_owners or {}).get(
        stale_fingerprint.lower(), ()
    )

    if len(owners) != 1:
        return None

    old_state_key = next(iter(owners))

    record = twin_supersessions.get(old_state_key)

    if not isinstance(record, dict):
        return None

    replacement_keys = [
        key
        for key in (
            _text(candidate)
            for candidate in (
                record.get("replacement_state_keys") or ()
            )
        )
        if key
    ]

    # This mechanism is exclusively for a governed 1->N split. A
    # single-replacement supersession is a different, already-handled
    # shape and is deliberately left untouched here.
    if len(replacement_keys) < 2:
        return None

    corroboration = _contextual_supersession_corroboration(record)

    current_states = (
        current_states
        if isinstance(current_states, dict)
        else {}
    )

    matched_fingerprints = set()

    for replacement_key in replacement_keys:
        entry = corroboration.get(replacement_key)

        if entry is None:
            continue

        entry_signature, entry_fingerprint = entry

        if entry_signature != signature.lower():
            continue

        current_state = current_states.get(replacement_key)

        if not isinstance(current_state, dict):
            continue

        current_fingerprint = _text(
            current_state.get("last_fingerprint")
        )

        if not current_fingerprint:
            continue

        # Capability-identity double-check: the corroboration record
        # must still agree with what is CURRENTLY observed, not only
        # with what was true when the supersession was recorded.
        if current_fingerprint.lower() != entry_fingerprint:
            continue

        matched_fingerprints.add(current_fingerprint.lower())

    if len(matched_fingerprints) != 1:
        return None

    return next(iter(matched_fingerprints))


def rebind_contextual_supersession_navigation_targets(
    candidates,
    *,
    twin_supersessions,
    historical_states,
    current_states,
):
    """Rebind stale 1->N-superseded targets on already-projected
    candidates.

    Never mutates before_fingerprint, never invents a new candidate,
    never touches a candidate that does not qualify -- see
    resolve_contextual_supersession_navigation_target().
    """

    fingerprint_owners = (
        _contextual_supersession_fingerprint_owners(
            historical_states
        )
    )

    rebound = []

    for candidate in candidates or ():
        if not isinstance(candidate, dict):
            rebound.append(candidate)
            continue

        replacement_fingerprint = (
            resolve_contextual_supersession_navigation_target(
                after_fingerprint=candidate.get(
                    "after_fingerprint"
                ),
                context_signature=candidate.get(
                    "context_signature"
                ),
                twin_supersessions=twin_supersessions,
                fingerprint_owners=fingerprint_owners,
                current_states=current_states,
            )
        )

        if replacement_fingerprint is None:
            rebound.append(candidate)
            continue

        rebound.append({
            **candidate,
            "after_fingerprint": replacement_fingerprint,
        })

    return tuple(rebound)


# QCC_AUTO_TWIN_SUPERSESSION_PROVENANCE_CORROBORATION_CORRELATION_V1
# (WO 2D-20S)
#
# Derives the PROVENANCE_CORROBORATION_KEY entries consumed by
# resolve_contextual_supersession_navigation_target() above, from two
# disjoint pieces of ALREADY-recorded, immutable evidence -- never
# from raw navigation-context content or branch/context literal
# values such as 130/131:
#
# - one ANCHOR instant per replacement_state_key: the moment that
#   replacement's own reprojected evidence was last observed (e.g.
#   AutoTwinObservationStore state.last_seen_at). This anchor carries
#   no navigation_context/branch information whatsoever -- it is pure
#   capture provenance.
# - a set of independently recorded HumanNavigationCandidateStore
#   candidates, each an immutable causal observation carrying its own
#   context_signature (an OPAQUE hash -- its underlying
#   selected_values are never inspected here) and an observed_at
#   time.
#
# A candidate corroborates the replacement whose anchor is the
# closest one at-or-before the candidate's own observed_at (a capture
# group necessarily precedes, and a human causal transition
# necessarily follows shortly after, the same physical navigation
# event), provided the gap does not exceed max_gap_seconds.
#
# Fails closed -- returns {}, writing no partial corroboration --
# unless EVERY declared replacement receives EXACTLY one qualifying
# candidate (zero is a missing correlation, more than one is
# ambiguous), all resulting context_signatures are pairwise DISTINCT
# across replacements (a shared signature could never let the
# resolver uniquely pick between them -- conflicting evidence), and
# every replacement's CURRENT fingerprint is known.
def correlate_supersession_replacement_navigation_context_signatures(
    *,
    stale_fingerprint,
    replacement_anchors,
    candidates,
    current_states,
    max_gap_seconds=120,
):
    """Derive governed replacement_navigation_context_signatures.

    Returns {replacement_state_key: {"context_signature":, "fingerprint":}}
    -- the exact shape consumed by
    resolve_contextual_supersession_navigation_target() -- or {} when
    the recorded evidence does not unambiguously and uniquely
    corroborate every declared replacement.
    """

    stale = _text(stale_fingerprint)

    if not stale:
        return {}

    if (
        not isinstance(replacement_anchors, dict)
        or not replacement_anchors
    ):
        return {}

    anchors = []

    for replacement_key, anchor_value in (
        replacement_anchors.items()
    ):
        key = _text(replacement_key)

        if not key:
            return {}

        try:
            anchor_time = normalize_utc_datetime(
                anchor_value,
                "QCC_AUTO_TWIN_SUPERSESSION_CORROBORATION_"
                "ANCHOR_INVALID",
            )
        except ValueError:
            return {}

        anchors.append((key, anchor_time))

    current_states = (
        current_states
        if isinstance(current_states, dict)
        else {}
    )

    assignments = {
        key: []
        for key, _ in anchors
    }

    for candidate in candidates or ():
        if not isinstance(candidate, dict):
            continue

        after_fingerprint = _text(
            candidate.get("after_fingerprint")
        )

        if (
            not after_fingerprint
            or after_fingerprint.lower() != stale.lower()
        ):
            continue

        signature = _text(
            candidate.get("context_signature")
        )

        if not signature:
            continue

        try:
            observed_at = normalize_utc_datetime(
                candidate.get("observed_at"),
                "QCC_AUTO_TWIN_SUPERSESSION_CORROBORATION_"
                "CANDIDATE_TIME_INVALID",
            )
        except ValueError:
            continue

        best_key = None
        best_anchor_time = None

        for key, anchor_time in anchors:
            if anchor_time > observed_at:
                continue

            if (
                best_anchor_time is None
                or anchor_time > best_anchor_time
            ):
                best_key = key
                best_anchor_time = anchor_time

        if best_key is None:
            continue

        gap = (
            observed_at - best_anchor_time
        ).total_seconds()

        if gap > max_gap_seconds:
            continue

        assignments[best_key].append(
            (signature.lower(), candidate)
        )

    resolved = {}

    for key, _ in anchors:
        matches = assignments.get(key) or []

        # Zero qualifying candidates is a missing correlation; more
        # than one is ambiguous. Both fail the whole enrichment
        # closed -- no partial corroboration is ever written.
        if len(matches) != 1:
            return {}

        resolved[key] = matches[0][0]

    signatures_seen = list(resolved.values())

    if len(set(signatures_seen)) != len(signatures_seen):
        return {}

    corroboration = {}

    for key, signature in resolved.items():
        current_state = current_states.get(key)

        if not isinstance(current_state, dict):
            return {}

        fingerprint = _text(
            current_state.get("last_fingerprint")
        )

        if not fingerprint:
            return {}

        corroboration[key] = {
            "context_signature": signature,
            "fingerprint": fingerprint.lower(),
        }

    return corroboration
