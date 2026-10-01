"""UWT-4 branch discriminators.

A discriminator is one generic, provider-neutral observation of a
branch-relevant control: which member of a logical control family is
currently active. It is deliberately *not* a raw control value: building
a discriminator is an explicit act (section 5 of the work order), never
an automatic conversion of HTML/control value into branch topology.

Supported generic control families (section 9): RADIO, CHECKBOX, SELECT,
TAB, TOGGLE. No site-specific, provider-specific or framework-specific
semantics are encoded here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


BRANCH_DISCRIMINATOR_SCHEMA_VERSION = 1

DISCRIMINATOR_KIND_RADIO = "RADIO"
DISCRIMINATOR_KIND_CHECKBOX = "CHECKBOX"
DISCRIMINATOR_KIND_SELECT = "SELECT"
DISCRIMINATOR_KIND_TAB = "TAB"
DISCRIMINATOR_KIND_TOGGLE = "TOGGLE"

DISCRIMINATOR_KINDS = frozenset(
    {
        DISCRIMINATOR_KIND_RADIO,
        DISCRIMINATOR_KIND_CHECKBOX,
        DISCRIMINATOR_KIND_SELECT,
        DISCRIMINATOR_KIND_TAB,
        DISCRIMINATOR_KIND_TOGGLE,
    }
)

# Control families whose active value is an open, caller-normalized
# identity (which member/option/tab is active): the string itself is not
# interpreted, only required to be present and stable.
_IDENTITY_VALUE_KINDS = frozenset(
    {
        DISCRIMINATOR_KIND_RADIO,
        DISCRIMINATOR_KIND_SELECT,
        DISCRIMINATOR_KIND_TAB,
    }
)

# Control families whose active value is a generic binary active state.
_BINARY_VALUE_TOKENS = {
    DISCRIMINATOR_KIND_CHECKBOX: ("CHECKED", "UNCHECKED"),
    DISCRIMINATOR_KIND_TOGGLE: ("ON", "OFF"),
}

_TRUE_TOKENS = frozenset({"TRUE", "1", "YES"})
_FALSE_TOKENS = frozenset({"FALSE", "0", "NO"})

_BRANCH_DISCRIMINATOR_NAMESPACE = "QCC_UWT_BRANCH_DISCRIMINATOR_V1\0"


class BranchDiscriminatorError(ValueError):
    """Raised when a branch discriminator cannot be built deterministically
    (missing identity, unknown kind, malformed active value). Fail closed
    rather than guessing branch-relevant semantics."""


def _text(value):
    if value is None:
        return None

    value = str(value).strip()

    return value or None


def _canonical_json(payload):
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalize_binary_active_value(kind, active_value):
    on_token, off_token = _BINARY_VALUE_TOKENS[kind]

    if isinstance(active_value, bool):
        return on_token if active_value else off_token

    text = _text(active_value)

    if not text:
        raise BranchDiscriminatorError(
            "QCC_UWT_BRANCH_DISCRIMINATOR_ACTIVE_VALUE_REQUIRED"
        )

    normalized = text.upper()

    if normalized == on_token or normalized in _TRUE_TOKENS:
        return on_token

    if normalized == off_token or normalized in _FALSE_TOKENS:
        return off_token

    raise BranchDiscriminatorError(
        "QCC_UWT_BRANCH_DISCRIMINATOR_ACTIVE_VALUE_INVALID"
    )


def _normalize_active_value(kind, active_value):
    if kind in _IDENTITY_VALUE_KINDS:
        text = _text(active_value)

        if not text:
            raise BranchDiscriminatorError(
                "QCC_UWT_BRANCH_DISCRIMINATOR_ACTIVE_VALUE_REQUIRED"
            )

        return text

    return _normalize_binary_active_value(kind, active_value)


def _derive_discriminator_id(kind, control_id, active_value):
    canonical = _canonical_json(
        {
            "kind": kind,
            "control_id": control_id,
            "active_value": active_value,
        }
    )

    return hashlib.sha256(
        (
            _BRANCH_DISCRIMINATOR_NAMESPACE
            + canonical
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class BranchDiscriminator:
    """One generic, deterministic branch-relevant control observation."""

    schema_version: int
    discriminator_id: str
    kind: str
    control_id: str
    active_value: str

    def as_dict(self) -> dict:
        return {
            "discriminator_id": self.discriminator_id,
            "kind": self.kind,
            "control_id": self.control_id,
            "active_value": self.active_value,
        }


def build_branch_discriminator(
    *,
    kind,
    control_id,
    active_value,
) -> BranchDiscriminator:
    """Builds a BranchDiscriminator with explicit validation.

    Fails closed on an unknown/malformed kind, a missing control identity
    or a malformed active value instead of inventing branch semantics.
    """

    normalized_kind = _text(kind)

    if not normalized_kind:
        raise BranchDiscriminatorError(
            "QCC_UWT_BRANCH_DISCRIMINATOR_KIND_REQUIRED"
        )

    normalized_kind = normalized_kind.upper()

    if normalized_kind not in DISCRIMINATOR_KINDS:
        raise BranchDiscriminatorError(
            "QCC_UWT_BRANCH_DISCRIMINATOR_KIND_INVALID"
        )

    normalized_control_id = _text(control_id)

    if not normalized_control_id:
        raise BranchDiscriminatorError(
            "QCC_UWT_BRANCH_DISCRIMINATOR_CONTROL_ID_REQUIRED"
        )

    normalized_active_value = _normalize_active_value(
        normalized_kind,
        active_value,
    )

    discriminator_id = _derive_discriminator_id(
        normalized_kind,
        normalized_control_id,
        normalized_active_value,
    )

    return BranchDiscriminator(
        schema_version=BRANCH_DISCRIMINATOR_SCHEMA_VERSION,
        discriminator_id=discriminator_id,
        kind=normalized_kind,
        control_id=normalized_control_id,
        active_value=normalized_active_value,
    )
