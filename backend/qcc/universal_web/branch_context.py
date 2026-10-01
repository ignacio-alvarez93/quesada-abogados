"""UWT-4 Universal Branch Context.

Provider-neutral, site-neutral representation of the branch-relevant
context active for a functional navigation context, built strictly on
top of the UWT-2/UWT-3 foundation:

    UWT-2 FUNCTIONAL STATE        (functional_state.py)
        |
        v
    UWT-3 UNIVERSAL STATE GRAPH   (state_graph.py)
        |
        v
    UWT-4 BRANCH CONTEXT          (this module)

Core rule (work order section 1): do not branch by value, branch by
observable behavior. A BranchContext is an explicit set of
BranchDiscriminator observations (branch_discriminators.py) that have
already been established as branch-relevant; this module never infers
branch relevance from a raw control value, FunctionalState or snapshot.

This module does not replace UWT-2 state identity/comparison, nor does
it build a second graph: it is additional topology/context information
suitable for later attachment/scoping of UWT-3 states/transitions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .branch_discriminators import (
    BranchDiscriminator,
    BranchDiscriminatorError,
    build_branch_discriminator,
)


BRANCH_CONTEXT_SCHEMA_VERSION = 1
BRANCH_CONTEXT_TYPE = "QCC_UWT_BRANCH_CONTEXT"

_BRANCH_CONTEXT_NAMESPACE = "QCC_UWT_BRANCH_CONTEXT_V1\0"


class BranchContextError(ValueError):
    """Raised when a BranchContext cannot be built/parsed deterministically
    (conflicting discriminators, malformed data, identity mismatch). Fail
    closed rather than silently overwriting or inventing context."""


def _text(value):
    """Strict string normalization: trims an actual `str`.

    Deliberately does not call `str(value)` on arbitrary input: a
    serialized identity field (context_id, discriminator_id) must be an
    actual string before it is ever compared, never a coerced
    representation of a bool/dict/list/int/object.
    """

    if not isinstance(value, str):
        return None

    value = value.strip()

    return value or None


def _canonical_json(payload):
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _discriminator_sort_key(discriminator: BranchDiscriminator):
    return (
        discriminator.kind,
        discriminator.control_id,
        discriminator.active_value,
    )


def _derive_branch_context_id(discriminators):
    canonical = _canonical_json(
        [
            discriminator.as_dict()
            for discriminator in discriminators
        ]
    )

    return hashlib.sha256(
        (
            _BRANCH_CONTEXT_NAMESPACE
            + canonical
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class BranchContext:
    """Immutable, deterministic set of branch-relevant discriminators."""

    schema_version: int
    context_id: str
    discriminators: tuple[BranchDiscriminator, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.discriminators

    def to_dict(self) -> dict:
        return {
            "schema_version": BRANCH_CONTEXT_SCHEMA_VERSION,
            "context_type": BRANCH_CONTEXT_TYPE,
            "context_id": self.context_id,
            "discriminator_count": len(self.discriminators),
            "discriminators": [
                discriminator.as_dict()
                for discriminator in self.discriminators
            ],
        }

    @staticmethod
    def from_dict(data) -> "BranchContext":
        if not isinstance(data, dict):
            raise BranchContextError(
                "QCC_UWT_BRANCH_CONTEXT_SERIALIZED_PAYLOAD_INVALID"
            )

        if data.get("schema_version") != BRANCH_CONTEXT_SCHEMA_VERSION:
            raise BranchContextError(
                "QCC_UWT_BRANCH_CONTEXT_SCHEMA_VERSION_INVALID"
            )

        if data.get("context_type") != BRANCH_CONTEXT_TYPE:
            raise BranchContextError(
                "QCC_UWT_BRANCH_CONTEXT_TYPE_INVALID"
            )

        raw_discriminator_count = data.get("discriminator_count")

        # bool is a subclass of int: reject it explicitly first so that
        # True/False can never be accepted as a count (section 3, Finding
        # B). A malformed falsey count (None, "", 0.0, ...) must fail
        # closed rather than being treated as a legitimate zero.
        if isinstance(raw_discriminator_count, bool) or not isinstance(
            raw_discriminator_count, int
        ):
            raise BranchContextError(
                "QCC_UWT_BRANCH_CONTEXT_DISCRIMINATOR_COUNT_INVALID"
            )

        raw_discriminators = data.get("discriminators")

        # The expected serialized collection type is a list (as produced
        # by to_dict()). A malformed falsey value (None, 0, "", False)
        # must never be silently treated as an empty collection.
        if not isinstance(raw_discriminators, list):
            raise BranchContextError(
                "QCC_UWT_BRANCH_CONTEXT_DISCRIMINATORS_INVALID"
            )

        if raw_discriminator_count != len(raw_discriminators):
            raise BranchContextError(
                "QCC_UWT_BRANCH_CONTEXT_DISCRIMINATOR_COUNT_MISMATCH"
            )

        discriminators = []

        for raw in raw_discriminators:
            if not isinstance(raw, dict):
                raise BranchContextError(
                    "QCC_UWT_BRANCH_CONTEXT_DISCRIMINATOR_MALFORMED"
                )

            try:
                discriminator = build_branch_discriminator(
                    kind=raw.get("kind"),
                    control_id=raw.get("control_id"),
                    active_value=raw.get("active_value"),
                )
            except BranchDiscriminatorError as exc:
                raise BranchContextError(
                    "QCC_UWT_BRANCH_CONTEXT_DISCRIMINATOR_MALFORMED"
                ) from exc

            serialized_discriminator_id = _text(raw.get("discriminator_id"))

            if (
                serialized_discriminator_id is None
                or discriminator.discriminator_id != serialized_discriminator_id
            ):
                raise BranchContextError(
                    "QCC_UWT_BRANCH_CONTEXT_DISCRIMINATOR_IDENTITY_MISMATCH"
                )

            discriminators.append(discriminator)

        context = build_branch_context(discriminators)

        serialized_context_id = _text(data.get("context_id"))

        if (
            serialized_context_id is None
            or context.context_id != serialized_context_id
        ):
            raise BranchContextError(
                "QCC_UWT_BRANCH_CONTEXT_IDENTITY_MISMATCH"
            )

        return context


def build_branch_context(discriminators=()) -> BranchContext:
    """Builds a BranchContext from explicit BranchDiscriminator instances.

    Deterministic regardless of input order (section 4): equivalent
    discriminator sets yield the same stable context_id. An exact
    repeated discriminator is deduplicated; a discriminator sharing a
    control identity with a different kind/active_value is an ambiguous
    duplicate and is rejected (fail closed, section 8) instead of being
    silently overwritten.
    """

    items = tuple(discriminators or ())
    by_control_id: dict[str, BranchDiscriminator] = {}

    for item in items:
        if not isinstance(item, BranchDiscriminator):
            raise TypeError(
                "QCC_UWT_BRANCH_CONTEXT_DISCRIMINATOR_INVALID"
            )

        existing = by_control_id.get(item.control_id)

        if existing is None:
            by_control_id[item.control_id] = item
            continue

        if existing.discriminator_id == item.discriminator_id:
            continue

        raise BranchContextError(
            "QCC_UWT_BRANCH_CONTEXT_CONFLICTING_DISCRIMINATOR:"
            + item.control_id
        )

    deduped = tuple(
        sorted(
            by_control_id.values(),
            key=_discriminator_sort_key,
        )
    )

    context_id = _derive_branch_context_id(deduped)

    return BranchContext(
        schema_version=BRANCH_CONTEXT_SCHEMA_VERSION,
        context_id=context_id,
        discriminators=deduped,
    )
