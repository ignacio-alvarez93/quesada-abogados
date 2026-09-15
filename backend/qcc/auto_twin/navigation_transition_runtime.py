"""Local AUTO TWIN navigation transition runtime.

Consumes immutable TWIN_ELIGIBLE transition evidence already frozen in
the MaterializationPlan and resolves it exclusively against materialized
Twin states.

No REAL URL or provider-specific behavior is allowed here.
"""

from __future__ import annotations

import html as html_lib
import json
import re

from .navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_OPAQUE,
    AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED,
    AUTO_TWIN_NAVIGATION_OUTCOME_DETERMINISTIC,
    classify_twin_navigation_transition_outcomes,
    normalize_twin_navigation_transitions,
)


AUTO_TWIN_NAVIGATION_RUNTIME_SCHEMA_VERSION = 1

AUTO_TWIN_NAVIGATION_RUNTIME_TYPE = (
    "QCC_AUTO_TWIN_NAVIGATION_RUNTIME"
)

AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION = 5

AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME = (
    "navigation_transitions.json"
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


def _fingerprint(value):
    result = _text(
        value
    )

    if (
        result is None
        or not _FINGERPRINT_RE.fullmatch(
            result
        )
    ):
        return None

    return result.lower()


def _resolve_navigation_runtime_transition(
    transition,
    fingerprint_index,
):
    """Resolve one learned transition against physical Twin states."""

    before_fingerprint = transition[
        "before_fingerprint"
    ]

    after_fingerprint = transition[
        "after_fingerprint"
    ]

    before_matches = fingerprint_index.get(
        before_fingerprint,
        [],
    )

    after_matches = fingerprint_index.get(
        after_fingerprint,
        [],
    )

    if len(before_matches) != 1:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_BEFORE_STATE_UNRESOLVED:"
            + before_fingerprint
        )

    if len(after_matches) != 1:
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_AFTER_STATE_UNRESOLVED:"
            + after_fingerprint
        )

    before_state = before_matches[0]
    after_state = after_matches[0]

    action = transition[
        "action"
    ]

    frame_path = (
        _text(
            action.get(
                "frame_path"
            )
        )
        or "main"
    )

    # V1 remains fail-closed for framed actions.
    if frame_path != "main":
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_FRAME_UNSUPPORTED:"
            + frame_path
        )

    before_state_id = _text(
        before_state.get(
            "state_id"
        )
    )

    after_state_id = _text(
        after_state.get(
            "state_id"
        )
    )

    target_runtime_entry = _text(
        after_state.get(
            "runtime_entry"
        )
    )

    if (
        not before_state_id
        or not after_state_id
        or not target_runtime_entry
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_RUNTIME_STATE_IDENTITY_INVALID"
        )

    if (
        target_runtime_entry.startswith(
            "/"
        )
        or "://" in target_runtime_entry
        or ".." in target_runtime_entry.split(
            "/"
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_RUNTIME_ENTRY_INVALID"
        )

    return {
        **transition,

        "before_state_id":
            before_state_id,

        "after_state_id":
            after_state_id,

        "target_runtime_entry":
            target_runtime_entry,
    }



def _navigation_runtime_route_key(
    transition,
):
    action = transition[
        "action"
    ]

    return (
        transition[
            "before_state_id"
        ],
        (
            _text(
                action.get(
                    "frame_path"
                )
            )
            or "main"
        ),
        action[
            "selector"
        ],
        _text(
            transition.get(
                "context_signature"
            )
        ),
    )



def _register_navigation_runtime_route(
    action_routes,
    transition,
):
    route_key = (
        _navigation_runtime_route_key(
            transition
        )
    )

    previous_target = action_routes.get(
        route_key
    )

    after_state_id = transition[
        "after_state_id"
    ]

    if (
        previous_target is not None
        and previous_target
        != after_state_id
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_ACTION_AMBIGUOUS:"
            + transition[
                "before_state_id"
            ]
            + ":"
            + transition[
                "action"
            ][
                "selector"
            ]
        )

    action_routes[
        route_key
    ] = after_state_id



def _navigation_runtime_sort_key(
    item,
):
    return (
        item[
            "before_state_id"
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
        (
            _text(
                item.get(
                    "context_signature"
                )
            )
            or ""
        ),
        item[
            "after_state_id"
        ],
        item[
            "candidate_id"
        ],
    )



def _navigation_fingerprint_adjacency(
    normalized_transitions,
):
    """Build the learned functional navigation graph."""

    adjacency = {}

    for transition in normalized_transitions:
        if not isinstance(
            transition,
            dict,
        ):
            continue

        before = _fingerprint(
            transition.get(
                "before_fingerprint"
            )
        )

        after = _fingerprint(
            transition.get(
                "after_fingerprint"
            )
        )

        if (
            before is None
            or after is None
            or before == after
        ):
            continue

        adjacency.setdefault(
            before,
            set(),
        ).add(
            after
        )

    return adjacency


def _navigation_fingerprint_reachable(
    adjacency,
    start_fingerprint,
    target_fingerprint,
    *,
    blocked_fingerprint=None,
):
    """Return True when target is downstream from start.

    The contextual action source can be blocked so that a cyclic route
    back through the original source cannot manufacture causality.
    """

    start_fingerprint = _fingerprint(
        start_fingerprint
    )

    target_fingerprint = _fingerprint(
        target_fingerprint
    )

    blocked_fingerprint = _fingerprint(
        blocked_fingerprint
    )

    if (
        start_fingerprint is None
        or target_fingerprint is None
        or start_fingerprint
        == target_fingerprint
    ):
        return False

    pending = [
        start_fingerprint
    ]

    visited = set()

    while pending:
        current = pending.pop()

        if current in visited:
            continue

        visited.add(
            current
        )

        for neighbour in adjacency.get(
            current,
            (),
        ):
            if (
                blocked_fingerprint
                and neighbour
                == blocked_fingerprint
            ):
                continue

            if neighbour == target_fingerprint:
                return True

            if neighbour not in visited:
                pending.append(
                    neighbour
                )

    return False


def _contextual_default_transition(
    group,
    normalized_by_candidate_id,
    normalized_transitions,
):
    """Pick the nearest learned successor for an opaque REAL action.

    A contextual action can contain historical candidates such as:

        A -> B
        A -> C
        B -> C

    In that graph C is downstream from B, therefore A -> C is a
    transitive shortcut and B is the immediate interactive successor.

    REAL determinism is still NOT asserted. This only prevents the
    materialized Twin from skipping learned intermediate states.

    If the graph cannot establish a unique nearest successor, preserve
    the previous stable fallback rather than inventing graph evidence.
    """

    candidate_ids = {
        str(
            candidate_id
        )
        for outcome in group.get(
            "outcomes",
            ()
        )
        if isinstance(
            outcome,
            dict,
        )
        for candidate_id in outcome.get(
            "candidate_ids",
            ()
        )
    }

    candidates = [
        normalized_by_candidate_id[
            candidate_id
        ]
        for candidate_id in candidate_ids
        if candidate_id
        in normalized_by_candidate_id
    ]

    if not candidates:
        raise ValueError(
            "QCC_AUTO_TWIN_CONTEXTUAL_ACTION_CANDIDATE_UNRESOLVED:"
            + str(
                group.get(
                    "action_group_id"
                )
                or ""
            )
        )

    if len(candidates) == 1:
        return candidates[0]

    adjacency = (
        _navigation_fingerprint_adjacency(
            normalized_transitions
        )
    )

    source_fingerprint = _fingerprint(
        candidates[0].get(
            "before_fingerprint"
        )
    )

    downstream_candidate_ids = set()

    for candidate in candidates:
        candidate_after = _fingerprint(
            candidate.get(
                "after_fingerprint"
            )
        )

        if candidate_after is None:
            continue

        for other in candidates:
            if (
                other["candidate_id"]
                == candidate["candidate_id"]
            ):
                continue

            other_after = _fingerprint(
                other.get(
                    "after_fingerprint"
                )
            )

            if (
                other_after is None
                or other_after
                == candidate_after
            ):
                continue

            if _navigation_fingerprint_reachable(
                adjacency,
                other_after,
                candidate_after,
                blocked_fingerprint=(
                    source_fingerprint
                ),
            ):
                downstream_candidate_ids.add(
                    candidate[
                        "candidate_id"
                    ]
                )

                break

    immediate_candidates = [
        candidate
        for candidate in candidates
        if candidate[
            "candidate_id"
        ]
        not in downstream_candidate_ids
    ]

    # Unique graph-nearest outcome.
    if len(immediate_candidates) == 1:
        return immediate_candidates[0]

    # The graph still cannot order the alternatives.
    # Keep stable simulation behaviour, but never use this fallback
    # when transitive evidence establishes an immediate successor.
    candidates.sort(
        key=lambda item: (
            -int(
                item.get(
                    "real_observation_count"
                )
                or 0
            ),
            item[
                "candidate_id"
            ],
        )
    )

    return candidates[0]



def build_navigation_runtime_payload(
    transitions,
    runtime_states,
):
    """Build branch-aware local Twin navigation.

    Unknown/opaque branches fail closed.
    No contextual default is invented.
    """

    normalized = (
        normalize_twin_navigation_transitions(
            transitions
        )
    )

    if not isinstance(
        runtime_states,
        (list, tuple),
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_NAVIGATION_RUNTIME_STATES_INVALID"
        )

    fingerprint_index = {}

    for state in runtime_states:
        if not isinstance(
            state,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_RUNTIME_STATE_INVALID"
            )

        fingerprint = _fingerprint(
            state.get(
                "fingerprint"
            )
        )

        if fingerprint is None:
            continue

        fingerprint_index.setdefault(
            fingerprint,
            [],
        ).append(
            state
        )

    action_groups = (
        classify_twin_navigation_transition_outcomes(
            normalized
        )
    )

    # QCC_DETERMINISTIC_ACTION_GROUP_DEDUPE_V1
    #
    # Runtime routes represent physical navigation, not individual
    # evidence records. Multiple REAL candidates may corroborate the
    # same source action -> same immediate target.
    deterministic_groups = tuple(
        group
        for group in action_groups
        if group.get(
            "outcome_mode"
        )
        == AUTO_TWIN_NAVIGATION_OUTCOME_DETERMINISTIC
    )

    resolved_groups = tuple(
        group
        for group in action_groups
        if group.get(
            "outcome_mode"
        )
        == AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED
    )

    opaque_groups = tuple(
        group
        for group in action_groups
        if group.get(
            "outcome_mode"
        )
        == AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_OPAQUE
    )

    contextual_groups = (
        resolved_groups
        + opaque_groups
    )

    contextual_candidate_ids = {
        str(
            candidate_id
        )
        for group in contextual_groups
        for outcome in group.get(
            "outcomes",
            ()
        )
        if isinstance(
            outcome,
            dict,
        )
        for candidate_id in outcome.get(
            "candidate_ids",
            ()
        )
    }

    normalized_by_candidate_id = {
        transition[
            "candidate_id"
        ]:
            transition
        for transition in normalized
    }

    deterministic_resolved = []
    executable_routes = {}

    for group in deterministic_groups:
        outcomes = [
            outcome
            for outcome in group.get(
                "outcomes",
                ()
            )
            if isinstance(
                outcome,
                dict,
            )
        ]

        if len(outcomes) != 1:
            raise ValueError(
                "QCC_AUTO_TWIN_DETERMINISTIC_OUTCOME_INVALID:"
                + str(
                    group.get(
                        "action_group_id"
                    )
                    or ""
                )
            )

        outcome = outcomes[0]

        candidate_ids = sorted({
            str(
                candidate_id
            )
            for candidate_id
            in outcome.get(
                "candidate_ids",
                ()
            )
            if str(
                candidate_id
                or ""
            ).strip()
        })

        candidates = [
            normalized_by_candidate_id[
                candidate_id
            ]
            for candidate_id
            in candidate_ids
            if candidate_id
            in normalized_by_candidate_id
        ]

        if not candidates:
            raise ValueError(
                "QCC_AUTO_TWIN_DETERMINISTIC_CANDIDATE_UNRESOLVED:"
                + str(
                    group.get(
                        "action_group_id"
                    )
                    or ""
                )
            )

        target_fingerprint = (
            outcome.get(
                "after_fingerprint"
            )
        )

        if any(
            candidate[
                "after_fingerprint"
            ]
            != target_fingerprint
            for candidate in candidates
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_DETERMINISTIC_TARGET_MISMATCH:"
                + str(
                    group.get(
                        "action_group_id"
                    )
                    or ""
                )
            )

        candidates.sort(
            key=lambda item: (
                -int(
                    item.get(
                        "real_observation_count"
                    )
                    or 0
                ),
                item[
                    "candidate_id"
                ],
            )
        )

        selected = candidates[0]

        runtime_transition = (
            _resolve_navigation_runtime_transition(
                selected,
                fingerprint_index,
            )
        )

        runtime_transition = {
            **runtime_transition,

            # Scalar retained for backwards compatibility.
            "candidate_id":
                selected[
                    "candidate_id"
                ],

            # Complete REAL evidence provenance.
            "candidate_ids":
                candidate_ids,

            "real_observation_count":
                int(
                    outcome.get(
                        "real_observation_count"
                    )
                    or 0
                ),

            # Context does not discriminate a deterministic physical
            # route. 130/131 remain preserved in learning evidence.
            "navigation_context":
                [],

            "context_signature":
                None,

            "discriminator_keys":
                [],

            "interactive_execution_mode":
                "DETERMINISTIC",

            "outcome_mode":
                AUTO_TWIN_NAVIGATION_OUTCOME_DETERMINISTIC,

            "action_group_id":
                _text(
                    group.get(
                        "action_group_id"
                    )
                ),
        }

        _register_navigation_runtime_route(
            executable_routes,
            runtime_transition,
        )

        deterministic_resolved.append(
            runtime_transition
        )

    contextual_resolved = []

    for group in resolved_groups:
        discriminator_keys = list(
            group.get(
                "discriminator_keys"
            )
            or []
        )

        for branch in group.get(
            "branches",
            ()
        ):
            if not isinstance(
                branch,
                dict,
            ):
                continue

            candidate_ids = [
                str(
                    candidate_id
                )
                for candidate_id
                in branch.get(
                    "candidate_ids",
                    ()
                )
                if str(
                    candidate_id
                    or ""
                ).strip()
            ]

            candidates = [
                normalized_by_candidate_id[
                    candidate_id
                ]
                for candidate_id
                in candidate_ids
                if candidate_id
                in normalized_by_candidate_id
            ]

            if not candidates:
                raise ValueError(
                    "QCC_AUTO_TWIN_CONTEXTUAL_BRANCH_CANDIDATE_UNRESOLVED:"
                    + str(
                        branch.get(
                            "context_signature"
                        )
                        or ""
                    )
                )

            candidates.sort(
                key=lambda item: (
                    -int(
                        item.get(
                            "real_observation_count"
                        )
                        or 0
                    ),
                    item[
                        "candidate_id"
                    ],
                )
            )

            selected = candidates[
                0
            ]

            if (
                selected[
                    "after_fingerprint"
                ]
                != branch.get(
                    "after_fingerprint"
                )
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_CONTEXTUAL_BRANCH_TARGET_MISMATCH"
                )

            runtime_transition = (
                _resolve_navigation_runtime_transition(
                    selected,
                    fingerprint_index,
                )
            )

            runtime_transition = {
                **runtime_transition,

                "navigation_context":
                    json.loads(
                        json.dumps(
                            branch.get(
                                "navigation_context"
                            )
                            or []
                        )
                    ),

                "context_signature":
                    _text(
                        branch.get(
                            "context_signature"
                        )
                    ),

                "discriminator_keys":
                    discriminator_keys,

                "interactive_execution_mode":
                    "CONTEXTUAL_RESOLVED",

                "outcome_mode":
                    AUTO_TWIN_NAVIGATION_OUTCOME_CONTEXTUAL_RESOLVED,

                "action_group_id":
                    _text(
                        group.get(
                            "action_group_id"
                        )
                    ),
            }

            if not runtime_transition[
                "context_signature"
            ]:
                raise ValueError(
                    "QCC_AUTO_TWIN_CONTEXTUAL_BRANCH_SIGNATURE_REQUIRED"
                )

            _register_navigation_runtime_route(
                executable_routes,
                runtime_transition,
            )

            contextual_resolved.append(
                runtime_transition
            )

    deterministic_resolved.sort(
        key=_navigation_runtime_sort_key
    )

    contextual_resolved.sort(
        key=_navigation_runtime_sort_key
    )

    executable = (
        deterministic_resolved
        + contextual_resolved
    )

    executable.sort(
        key=_navigation_runtime_sort_key
    )

    return {
        "schema_version":
            AUTO_TWIN_NAVIGATION_RUNTIME_SCHEMA_VERSION,

        "record_type":
            AUTO_TWIN_NAVIGATION_RUNTIME_TYPE,

        "adapter_version":
            AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,

        "transition_count":
            len(
                executable
            ),

        "transitions":
            json.loads(
                json.dumps(
                    executable
                )
            ),

        "interactive_transition_count":
            len(
                executable
            ),

        "interactive_transitions":
            json.loads(
                json.dumps(
                    executable
                )
            ),

        "contextual_resolved_count":
            len(
                contextual_resolved
            ),

        "contextual_resolved":
            json.loads(
                json.dumps(
                    contextual_resolved
                )
            ),

        "contextual_unresolved_count":
            len(
                opaque_groups
            ),

        "contextual_unresolved":
            json.loads(
                json.dumps(
                    opaque_groups
                )
            ),

        "contextual_default_count":
            0,

        "contextual_defaults":
            [],

        "contextual_action_count":
            len(
                contextual_groups
            ),

        "contextual_actions":
            json.loads(
                json.dumps(
                    contextual_groups
                )
            ),
    }



def outgoing_navigation_transitions(
    runtime_payload,
    state_id,
):
    normalized_state_id = _text(
        state_id
    )

    # New materializations use the interactive contract.
    # Old revisions remain backwards-compatible.
    if "interactive_transitions" in runtime_payload:
        transitions = runtime_payload.get(
            "interactive_transitions",
            ()
        )
    else:
        transitions = runtime_payload.get(
            "transitions",
            ()
        )

    return tuple(
        transition
        for transition
        in transitions
        if transition.get(
            "before_state_id"
        )
        == normalized_state_id
    )




def _strip_navigation_runtime_adapter(
    source_html,
):
    """Remove previously materialized navigation adapters.

    Carry-forward states may already contain an adapter from the base
    revision. Re-materialization must replace it, never stack listeners.
    """

    marker = (
        '<script data-qcc-auto-twin-navigation="1">'
    )

    closing = "</script>"

    while True:
        start = source_html.find(
            marker
        )

        if start < 0:
            return source_html

        end = source_html.find(
            closing,
            start,
        )

        if end < 0:
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_ADAPTER_CORRUPT"
            )

        end += len(
            closing
        )

        if (
            end < len(
                source_html
            )
            and source_html[
                end:end + 1
            ]
            == "\n"
        ):
            end += 1

        source_html = (
            source_html[:start]
            + source_html[end:]
        )



_EVENT_ACTION_SELECTOR_RE = re.compile(
    r"""^\s*
    (?P<tag>[A-Za-z][A-Za-z0-9:_-]*)
    \s*\[
    \s*(?P<attribute>on[A-Za-z][A-Za-z0-9:_-]*)
    \s*=\s*
    (?P<quote>["'])
    (?P<value>.*?)
    (?P=quote)
    \s*\]
    \s*$""",
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

_RUNTIME_START_TAG_RE = re.compile(
    r"<(?P<tag>[A-Za-z][A-Za-z0-9:_-]*)"
    r"(?P<body>(?:\s+[^<>]*?)?)"
    r"(?P<close>/?)>",
    re.DOTALL,
)

_HTML_COMMENT_RE = re.compile(
    r"<!--.*?-->",
    re.DOTALL,
)


_RUNTIME_ATTR_RE = re.compile(
    r"""(?P<name>[^\s=/>]+)
    (?:\s*=\s*
        (?:
            (?P<quote>["'])
            (?P<quoted>.*?)
            (?P=quote)
            |
            (?P<bare>[^\s>]+)
        )
    )?""",
    re.DOTALL | re.VERBOSE,
)

_STABLE_NAVIGATION_IDENTITY_ATTRIBUTES = frozenset({
    "id",
    "name",
    "class",
    "href",
    "type",
    "role",
    "title",
    "tooltip",
    "aria-label",
})


def _runtime_tag_attributes(
    body,
):
    result = {}

    for match in _RUNTIME_ATTR_RE.finditer(
        str(
            body
            or ""
        )
    ):
        name = str(
            match.group(
                "name"
            )
            or ""
        ).strip().lower()

        if not name:
            continue

        value = (
            match.group(
                "quoted"
            )
            if match.group(
                "quoted"
            )
            is not None
            else match.group(
                "bare"
            )
        )

        result[
            name
        ] = html_lib.unescape(
            str(
                value
                or ""
            )
        )

    return result


def _main_qcc_elements(
    qcc_capture_payload,
):
    if not isinstance(
        qcc_capture_payload,
        dict,
    ):
        return []

    frames = (
        qcc_capture_payload.get(
            "frames"
        )
        or []
    )

    if not isinstance(
        frames,
        list,
    ):
        return []

    main_frame = next(
        (
            frame
            for frame in frames
            if (
                isinstance(
                    frame,
                    dict,
                )
                and frame.get(
                    "frame_id"
                ) == 0
            )
        ),
        None,
    )

    if main_frame is None:
        main_frame = next(
            (
                frame
                for frame in frames
                if isinstance(
                    frame,
                    dict,
                )
            ),
            None,
        )

    if not isinstance(
        main_frame,
        dict,
    ):
        return []

    result = (
        main_frame.get(
            "result"
        )
        or {}
    )

    if not isinstance(
        result,
        dict,
    ):
        return []

    elements = (
        result.get(
            "elements"
        )
        or []
    )

    return (
        elements
        if isinstance(
            elements,
            list,
        )
        else []
    )


def _stable_qcc_identity(
    element,
):
    attributes = (
        element.get(
            "attributes"
        )
        or {}
    )

    if not isinstance(
        attributes,
        dict,
    ):
        return {}

    result = {}

    for raw_name, raw_value in attributes.items():
        name = str(
            raw_name
            or ""
        ).strip().lower()

        if (
            not name
            or name.startswith(
                "on"
            )
            or name
            not in _STABLE_NAVIGATION_IDENTITY_ATTRIBUTES
        ):
            continue

        value = str(
            raw_value
            or ""
        ).strip()

        # External URL attributes may already have been
        # rewritten by the network sterilizer.
        if (
            name == "href"
            and (
                value.lower().startswith(
                    "http://"
                )
                or value.lower().startswith(
                    "https://"
                )
                or value.startswith(
                    "//"
                )
            )
        ):
            continue

        if value:
            result[
                name
            ] = value

    return result


def _runtime_identity_matches(
    runtime_attributes,
    evidence_identity,
):
    if not evidence_identity:
        return False

    for name, expected in evidence_identity.items():
        actual = str(
            runtime_attributes.get(
                name,
                ""
            )
            or ""
        ).strip()

        if name == "class":
            if (
                set(
                    actual.split()
                )
                != set(
                    expected.split()
                )
            ):
                return False

        elif actual != expected:
            return False

    return True


# QCC_AUTO_TWIN_RUNTIME_ACTIONABILITY_ELIGIBILITY_V1 (2D-20M)
#
# A shared selector may legitimately match more than one physical
# node when the same markup (id/class/href) is duplicated across
# tabs/panels of the SAME page -- one instance genuinely actionable,
# the other belonging to a currently inactive/hidden panel.
#
# This is evaluated against the STRUCTURED QCC evidence element (which
# carries real computed geometry/disabled state), never against the
# runtime regex-parsed tag alone -- MHTML/materialization commonly
# strips the CSS that would make an ancestor's display:none visible on
# the node's own attributes.
#
# Deliberately does NOT consult in_viewport: an off-screen but
# genuinely rendered, scrollable action remains eligible.
def _evidence_element_is_actionable(
    element,
):
    if not isinstance(
        element,
        dict,
    ):
        return False

    if element.get(
        "disabled"
    ) is True:
        return False

    if element.get(
        "hidden"
    ) not in (
        None,
        False,
        "",
    ):
        return False

    attributes = (
        element.get(
            "attributes"
        )
        or {}
    )

    if isinstance(
        attributes,
        dict,
    ):
        if attributes.get(
            "hidden"
        ) not in (
            None,
            False,
            "",
        ):
            return False

        style = str(
            attributes.get(
                "style"
            )
            or ""
        ).replace(
            " ",
            "",
        ).lower()

        if (
            "display:none"
            in style
            or "visibility:hidden"
            in style
        ):
            return False

    rect = element.get(
        "rect"
    )

    if isinstance(
        rect,
        dict,
    ):
        width = rect.get(
            "width"
        )

        height = rect.get(
            "height"
        )

        try:
            if (
                width is not None
                and height is not None
                and (
                    float(width) <= 0
                    or float(height) <= 0
                )
            ):
                return False

        except (
            TypeError,
            ValueError,
        ):
            pass

    return True


def _eligible_runtime_matches_by_actionability(
    *,
    runtime_matches,
    evidence_identity,
    qcc_capture_payload,
    tag,
):
    """Narrow runtime_matches to effectively-actionable DOM instances.

    Correlates each runtime candidate to the structured QCC evidence
    element occupying the same document-order position among elements
    sharing the exact same tag + stable identity (id/class/href/...).

    Only applied when that correlation is unambiguous (the two lists
    are the same length) -- otherwise returns runtime_matches
    unchanged, preserving prior behavior exactly (including for
    selectors with no stable identity at all).
    """

    if (
        not evidence_identity
        or len(
            runtime_matches
        )
        < 2
    ):
        return runtime_matches

    identity_matched_evidence = [
        element
        for element in _main_qcc_elements(
            qcc_capture_payload
        )
        if (
            isinstance(
                element,
                dict,
            )
            and str(
                element.get(
                    "tag"
                )
                or ""
            ).strip().lower()
            == tag
            and _stable_qcc_identity(
                element
            )
            == evidence_identity
        )
    ]

    if len(
        identity_matched_evidence
    ) != len(
        runtime_matches
    ):
        return runtime_matches

    return [
        runtime_match
        for (
            runtime_match,
            evidence_candidate,
        ) in zip(
            runtime_matches,
            identity_matched_evidence,
        )
        if _evidence_element_is_actionable(
            evidence_candidate
        )
    ]


def _normalized_runtime_text(
    value,
):
    return " ".join(
        html_lib.unescape(
            str(
                value
                or ""
            )
        ).split()
    ).casefold()


def _runtime_element_text(
    source_html,
    start_match,
):
    """Extract bounded visible text for one runtime element.

    Used only as a deterministic secondary identity when stable
    attributes do not uniquely resolve the physical MHTML node.
    """

    tag = str(
        start_match.group(
            "tag"
        )
        or ""
    ).strip().lower()

    if not tag:
        return ""

    closing = re.search(
        r"</\s*"
        + re.escape(tag)
        + r"\s*>",
        source_html[
            start_match.end():
        ],
        re.IGNORECASE,
    )

    if closing is None:
        return ""

    inner_start = (
        start_match.end()
    )

    inner_end = (
        start_match.end()
        + closing.start()
    )

    inner = source_html[
        inner_start:
        inner_end
    ]

    inner = _HTML_COMMENT_RE.sub(
        " ",
        inner,
    )

    inner = re.sub(
        r"<[^>]+>",
        " ",
        inner,
        flags=re.DOTALL,
    )

    return _normalized_runtime_text(
        inner
    )


def restore_navigation_action_identity(
    source_html,
    *,
    qcc_capture_payload,
    transitions,
):
    """Restore only event attributes owned by learned transitions.

    MHTML may omit inline event attributes that QCC observed in REAL.
    We restore them only when:

    - the transition selector explicitly depends on an on* attribute;
    - QCC contains exactly one matching source element;
    - the materialized DOM contains exactly one matching element using
      stable non-event identity.

    The navigation adapter executes in capture phase and owns the
    learned action before the original inline handler can execute.
    """

    if not isinstance(
        source_html,
        str,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_NAVIGATION_RUNTIME_HTML_INVALID"
        )

    result = source_html

    for transition in (
        transitions
        or ()
    ):
        if not isinstance(
            transition,
            dict,
        ):
            continue

        action = (
            transition.get(
                "action"
            )
            or {}
        )

        if not isinstance(
            action,
            dict,
        ):
            continue

        selector = str(
            action.get(
                "selector"
            )
            or ""
        ).strip()

        selector_match = (
            _EVENT_ACTION_SELECTOR_RE.fullmatch(
                selector
            )
        )

        # Selectors independent from an inline event attribute
        # already survive MHTML and need no restoration.
        if selector_match is None:
            continue

        tag = (
            selector_match.group(
                "tag"
            )
            .strip()
            .lower()
        )

        event_attribute = (
            selector_match.group(
                "attribute"
            )
            .strip()
            .lower()
        )

        event_value = (
            selector_match.group(
                "value"
            )
        )

        evidence_matches = []

        for element in _main_qcc_elements(
            qcc_capture_payload
        ):
            if not isinstance(
                element,
                dict,
            ):
                continue

            if (
                str(
                    element.get(
                        "tag"
                    )
                    or ""
                ).strip().lower()
                != tag
            ):
                continue

            attributes = (
                element.get(
                    "attributes"
                )
                or {}
            )

            if not isinstance(
                attributes,
                dict,
            ):
                continue

            observed_value = None

            for key, value in attributes.items():
                if (
                    str(
                        key
                    ).strip().lower()
                    == event_attribute
                ):
                    observed_value = str(
                        value
                        or ""
                    )
                    break

            if observed_value != event_value:
                continue

            evidence_matches.append(
                element
            )

        if len(
            evidence_matches
        ) != 1:
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_ACTION_EVIDENCE_AMBIGUOUS:"
                + selector
            )

        evidence_element = (
            evidence_matches[
                0
            ]
        )

        evidence_identity = (
            _stable_qcc_identity(
                evidence_element
            )
        )

        evidence_text = (
            _normalized_runtime_text(
                evidence_element.get(
                    "text"
                )
            )
        )

        runtime_candidates = []

        # QCC_AUTO_TWIN_RUNTIME_LIVE_MARKUP_ONLY_V1
        #
        # MHTML may preserve superseded/original markup inside HTML
        # comments. A regex over raw source must not treat those tags
        # as physical runtime interaction targets.
        #
        # Example:
        #   <!-- <a ... onclick="old()"> -->
        #   <a ...>
        #
        # Only live markup participates in identity resolution.
        comment_spans = tuple(
            (
                comment.start(),
                comment.end(),
            )
            for comment in _HTML_COMMENT_RE.finditer(
                result
            )
        )

        for match in _RUNTIME_START_TAG_RE.finditer(
            result
        ):
            if any(
                start
                <= match.start()
                < end
                for start, end in comment_spans
            ):
                continue

            if (
                match.group(
                    "tag"
                ).strip().lower()
                != tag
            ):
                continue

            runtime_attributes = (
                _runtime_tag_attributes(
                    match.group(
                        "body"
                    )
                )
            )

            if (
                evidence_identity
                and not _runtime_identity_matches(
                    runtime_attributes,
                    evidence_identity,
                )
            ):
                continue

            runtime_candidates.append(
                (
                    match,
                    runtime_attributes,
                )
            )

        runtime_matches = (
            runtime_candidates
        )

        # QCC_AUTO_TWIN_RUNTIME_TEXT_IDENTITY_V1
        #
        # Inline-event-only controls may have no stable attributes
        # after MHTML strips onclick/onchange/etc.
        #
        # Visible text observed by QCC is therefore a secondary,
        # provider-neutral discriminator. It never weakens fail-closed:
        # the final physical target must still be exactly one node.
        if (
            len(
                runtime_matches
            )
            != 1
            and evidence_text
        ):
            runtime_matches = [
                (
                    match,
                    runtime_attributes,
                )
                for (
                    match,
                    runtime_attributes,
                )
                in runtime_candidates
                if (
                    _runtime_element_text(
                        result,
                        match,
                    )
                    == evidence_text
                )
            ]

        # QCC_AUTO_TWIN_RUNTIME_ACTIONABILITY_ELIGIBILITY_V1 (2D-20M)
        #
        # Applied BEFORE the fail-closed exactly-one invariant below.
        # A shared selector matching one zero-size/hidden/disabled
        # duplicate and one genuinely rendered node must resolve to
        # the rendered one, not raise ambiguity. Multiple genuinely
        # actionable nodes are never ranked -- they remain ambiguous.
        runtime_matches = (
            _eligible_runtime_matches_by_actionability(
                runtime_matches=(
                    runtime_matches
                ),
                evidence_identity=(
                    evidence_identity
                ),
                qcc_capture_payload=(
                    qcc_capture_payload
                ),
                tag=tag,
            )
        )

        if len(
            runtime_matches
        ) == 0:
            # Governed non-success: no eligible runtime target for
            # this transition's action. Mirrors the existing
            # "selector_match is None" skip above -- leave this
            # transition's markup untouched and move on, rather than
            # failing the whole restoration pass.
            continue

        if len(
            runtime_matches
        ) != 1:
            raise ValueError(
                "QCC_AUTO_TWIN_NAVIGATION_RUNTIME_TARGET_AMBIGUOUS:"
                + selector
            )

        match, runtime_attributes = (
            runtime_matches[
                0
            ]
        )

        existing_value = (
            runtime_attributes.get(
                event_attribute
            )
        )

        if existing_value is not None:
            if (
                existing_value
                != event_value
            ):
                raise ValueError(
                    "QCC_AUTO_TWIN_NAVIGATION_RUNTIME_EVENT_CONFLICT:"
                    + selector
                )

            continue

        tag_text = match.group(
            0
        )

        escaped_value = html_lib.escape(
            event_value,
            quote=True,
        )

        marker = (
            ' data-qcc-auto-twin-navigation-identity="1"'
        )

        injected_attribute = (
            " "
            + event_attribute
            + '="'
            + escaped_value
            + '"'
            + marker
        )

        insertion_index = (
            len(
                tag_text
            )
            - 2
            if tag_text.endswith(
                "/>"
            )
            else len(
                tag_text
            )
            - 1
        )

        rewritten_tag = (
            tag_text[
                :insertion_index
            ]
            + injected_attribute
            + tag_text[
                insertion_index:
            ]
        )

        result = (
            result[
                :match.start()
            ]
            + rewritten_tag
            + result[
                match.end():
            ]
        )

    return result



def inject_navigation_runtime_adapter(
    source_html,
    *,
    state_id,
    transitions,
):
    """Install branch-aware local capture-phase navigation."""

    source_html = (
        _strip_navigation_runtime_adapter(
            source_html
        )
    )

    outgoing = list(
        transitions
    )

    if not outgoing:
        return source_html

    payload = json.dumps(
        outgoing,
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
    ).replace(
        "</",
        "<\\/",
    )

    script = (
        '<script data-qcc-auto-twin-navigation="1">\n'
        "(() => {\n"
        '  "use strict";\n'
        f"  const transitions = {payload};\n"
        "\n"
        "  const normalizeValue = (value) =>\n"
        "    String(value ?? \"\").trim();\n"
        "\n"
        "  const uniqueSorted = (values) =>\n"
        "    [...new Set(values.map(normalizeValue).filter(Boolean))].sort();\n"
        "\n"
        "  const selectedValues = (selector) => {\n"
        "    if (typeof selector !== \"string\" || !selector.trim()) return null;\n"
        "\n"
        "    let nodes;\n"
        "    try {\n"
        "      nodes = [...document.querySelectorAll(selector)];\n"
        "    } catch (_) {\n"
        "      return null;\n"
        "    }\n"
        "\n"
        "    if (nodes.length === 0) return null;\n"
        "\n"
        "    const values = [];\n"
        "\n"
        "    for (const node of nodes) {\n"
        "      if (node instanceof HTMLSelectElement) {\n"
        "        for (const option of node.selectedOptions) {\n"
        "          values.push(option.value || option.textContent || \"\");\n"
        "        }\n"
        "        continue;\n"
        "      }\n"
        "\n"
        "      if (node instanceof HTMLOptionElement) {\n"
        "        if (node.selected) {\n"
        "          values.push(node.value || node.textContent || \"\");\n"
        "        }\n"
        "        continue;\n"
        "      }\n"
        "\n"
        "      if (node instanceof HTMLInputElement) {\n"
        "        const type = String(node.type || \"\").toLowerCase();\n"
        "\n"
        "        if (type === \"radio\" || type === \"checkbox\") {\n"
        "          if (node.checked) {\n"
        "            values.push(node.value || \"CHECKED\");\n"
        "          }\n"
        "          continue;\n"
        "        }\n"
        "\n"
        "        if (node.value) values.push(node.value);\n"
        "        continue;\n"
        "      }\n"
        "\n"
        "      const ariaSelected = node.getAttribute?.(\"aria-selected\");\n"
        "      const ariaPressed = node.getAttribute?.(\"aria-pressed\");\n"
        "      const dataSelected = node.getAttribute?.(\"data-qcc-auto-twin-selected\");\n"
        "\n"
        "      if (\n"
        "        ariaSelected === \"true\" ||\n"
        "        ariaPressed === \"true\" ||\n"
        "        dataSelected === \"1\"\n"
        "      ) {\n"
        "        values.push(\n"
        "          node.getAttribute?.(\"value\") ||\n"
        "          node.getAttribute?.(\"data-value\") ||\n"
        "          node.textContent ||\n"
        "          \"SELECTED\"\n"
        "        );\n"
        "      }\n"
        "    }\n"
        "\n"
        "    return uniqueSorted(values);\n"
        "  };\n"
        "\n"
        "  const sameValues = (one, two) => {\n"
        "    const a = uniqueSorted(one || []);\n"
        "    const b = uniqueSorted(two || []);\n"
        "\n"
        "    if (a.length !== b.length) return false;\n"
        "\n"
        "    return a.every((value, index) => value === b[index]);\n"
        "  };\n"
        "\n"
        "  const contextMatches = (transition) => {\n"
        "    const context = transition.navigation_context;\n"
        "\n"
        "    if (!Array.isArray(context) || context.length === 0) {\n"
        "      return true;\n"
        "    }\n"
        "\n"
        "    for (const expected of context) {\n"
        "      if (!expected || typeof expected !== \"object\") return false;\n"
        "\n"
        "      const selector = expected.selector;\n"
        "      const wanted = expected.selected_values;\n"
        "\n"
        "      if (\n"
        "        typeof selector !== \"string\" ||\n"
        "        !selector.trim() ||\n"
        "        !Array.isArray(wanted)\n"
        "      ) {\n"
        "        return false;\n"
        "      }\n"
        "\n"
        "      const actual = selectedValues(selector);\n"
        "\n"
        "      if (actual === null || !sameValues(actual, wanted)) {\n"
        "        return false;\n"
        "      }\n"
        "    }\n"
        "\n"
        "    return true;\n"
        "  };\n"
        "\n"
        "  const matchesSelector = (event, selector) => {\n"
        "    const nodes = [];\n"
        "\n"
        "    if (typeof event.composedPath === \"function\") {\n"
        "      nodes.push(...event.composedPath());\n"
        "    }\n"
        "\n"
        "    if (event.target) nodes.push(event.target);\n"
        "\n"
        "    for (const node of nodes) {\n"
        "      if (!(node instanceof Element)) continue;\n"
        "\n"
        "      try {\n"
        "        if (node.matches(selector)) return true;\n"
        "        if (node.closest?.(selector)) return true;\n"
        "      } catch (_) {\n"
        "        return false;\n"
        "      }\n"
        "    }\n"
        "\n"
        "    return false;\n"
        "  };\n"
        "\n"
        "  document.addEventListener(\n"
        "    \"click\",\n"
        "    (event) => {\n"
        "      const actionMatches = transitions.filter(\n"
        "        (transition) => matchesSelector(\n"
        "          event,\n"
        "          transition.action.selector\n"
        "        )\n"
        "      );\n"
        "\n"
        "      if (actionMatches.length === 0) return;\n"
        "\n"
        "      event.preventDefault();\n"
        "      event.stopImmediatePropagation();\n"
        "\n"
        "      const matched = actionMatches.filter(contextMatches);\n"
        "\n"
        "      // Unknown or ambiguous branch: fail closed.\n"
        "      if (matched.length !== 1) return;\n"
        "\n"
        "      const entry = matched[0].target_runtime_entry;\n"
        "\n"
        "      if (\n"
        "        typeof entry !== \"string\" ||\n"
        "        entry.startsWith(\"/\") ||\n"
        "        entry.includes(\"://\") ||\n"
        "        entry.split(\"/\").includes(\"..\")\n"
        "      ) {\n"
        "        return;\n"
        "      }\n"
        "\n"
        "      window.location.assign(\"/\" + entry);\n"
        "    },\n"
        "    true\n"
        "  );\n"
        "})();\n"
        "</script>\n"
    )

    lower = source_html.lower()

    position = lower.find(
        "<head"
    )

    if position >= 0:
        close = source_html.find(
            ">",
            position,
        )

        if close >= 0:
            return (
                source_html[
                    :close + 1
                ]
                + "\n"
                + script
                + source_html[
                    close + 1:
                ]
            )

    return (
        script
        + source_html
    )
