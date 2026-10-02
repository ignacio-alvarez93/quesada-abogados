"""QCC_BRANCH_CONTEXT_CAPTURE_V1 core translator.

Translates ONE already-governed CONTEXTUAL_RESOLVED navigation branch
record (as produced by
backend.qcc.auto_twin.navigation_transition_materialization.
classify_twin_navigation_transition_outcomes) into a UWT-4 BranchContext.

This module never decides whether a branch is relevant. That decision
(DETERMINISTIC vs CONTEXTUAL_RESOLVED vs CONTEXTUAL_OPAQUE) is made
upstream, strictly from observable behavior (section 2, NO RAMIFICAR
POR VALOR). A raw navigation_context entry can never create a
BranchContext by itself: every branch handed to this translator must
already belong to a CONTEXTUAL_RESOLVED action group.

Fails closed (returns None) on any unsupported control kind, missing
or ambiguous active value, or conflicting discriminator, rather than
inventing branch identity.
"""

from __future__ import annotations

import json

from .branch_context import (
    BranchContextError,
    build_branch_context,
)
from .branch_discriminators import (
    BranchDiscriminatorError,
    DISCRIMINATOR_KINDS,
    build_branch_discriminator,
)


def _text(value):
    if not isinstance(value, str):
        return None

    value = value.strip()

    return value or None


def _control_id(*, frame_path, key):
    """Deterministic, site-neutral control identity.

    Includes frame_path so that two same-named controls living in
    different frames are never conflated into one discriminator
    identity (section 5).
    """

    normalized_key = _text(key)

    if not normalized_key:
        return None

    normalized_frame_path = (
        _text(frame_path)
        or "main"
    )

    return json.dumps(
        [normalized_frame_path, normalized_key],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _discriminator_from_navigation_context_entry(entry):
    if not isinstance(entry, dict):
        return None

    kind = _text(entry.get("kind"))

    if kind is None:
        return None

    kind = kind.upper()

    # Unsupported/default DISCRETE kinds never fabricate a
    # discriminator (section 5, section 9).
    if kind not in DISCRIMINATOR_KINDS:
        return None

    control_id = _control_id(
        frame_path=entry.get("frame_path"),
        key=entry.get("key"),
    )

    if control_id is None:
        return None

    selected_values = entry.get("selected_values")

    if not isinstance(selected_values, (list, tuple)):
        return None

    values = [
        value
        for value in (
            _text(value)
            if isinstance(value, str)
            else value
            for value in selected_values
        )
        if value is not None
    ]

    # RADIO/SELECT/TAB require exactly one active identity value.
    # CHECKBOX/TOGGLE require exactly one unambiguous value that
    # build_branch_discriminator() can normalize to its binary
    # contract. Either way, zero or multiple active values is
    # ambiguous/missing evidence: fail closed (section 5).
    if len(values) != 1:
        return None

    try:
        return build_branch_discriminator(
            kind=kind,
            control_id=control_id,
            active_value=values[0],
        )
    except BranchDiscriminatorError:
        return None


def build_branch_context_from_resolved_navigation_branch(
    branch,
):
    """Build a BranchContext from one already-resolved branch record.

    `branch` must be one entry of a CONTEXTUAL_RESOLVED action group's
    `branches` list (that classification decision is the caller's
    responsibility, not this function's). Returns None whenever the
    branch's navigation_context cannot be translated deterministically
    and unambiguously -- never a fabricated/partial BranchContext.
    """

    if not isinstance(branch, dict):
        return None

    navigation_context = branch.get("navigation_context")

    if (
        not isinstance(navigation_context, (list, tuple))
        or not navigation_context
    ):
        return None

    discriminators = []

    for entry in navigation_context:
        discriminator = (
            _discriminator_from_navigation_context_entry(entry)
        )

        if discriminator is None:
            return None

        discriminators.append(discriminator)

    try:
        context = build_branch_context(discriminators)
    except BranchContextError:
        return None

    if context.is_empty:
        return None

    return context
