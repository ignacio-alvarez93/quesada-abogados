"""UWT-2 signal classification contracts.

Provider-neutral, site-neutral classification of normalized evidence
signals used to explain a FunctionalDelta classification.

This module does not decide SAME/CHANGED by itself. It only names and
classifies the signals that ``functional_delta`` inspects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


STATE_SIGNAL_SCHEMA_VERSION = 1


class SignalCategory(str, Enum):
    """Conceptual classification of a normalized evidence signal."""

    FUNCTIONAL = "FUNCTIONAL"
    NON_FUNCTIONAL = "NON_FUNCTIONAL"
    UNKNOWN = "UNKNOWN"


# Documented catalog of conceptually volatile/non-functional evidence.
#
# UWT-2 does not need to actively strip these: the Site Architecture
# functional payload (backend.automation.site_architecture.state_fingerprint)
# already excludes them from functional identity upstream. This registry
# exists so the classification contract required by the work order is
# explicit and testable, not merely implicit in upstream normalization.
KNOWN_NON_FUNCTIONAL_SIGNAL_NAMES = frozenset(
    {
        "captured_at",
        "timestamp",
        "session_id",
        "request_id",
        "analytics_id",
        "random_dom_id",
        "cosmetic_style",
        "counter",
    }
)

# Documented catalog of the normalized sections this detector treats as
# functionally authoritative evidence. See functional_delta.py for how
# these are used to decide SAME_FUNCTIONAL_STATE / FUNCTIONAL_STATE_CHANGED.
KNOWN_FUNCTIONAL_SIGNAL_NAMES = frozenset(
    {
        "page_identity",
        "actions",
        "active_ui_regions",
        "catalogs",
        "catalog_relations",
    }
)


@dataclass(frozen=True, slots=True)
class StateSignal:
    """A single named, classified, normalized evidence signal."""

    schema_version: int
    name: str
    category: str
    changed: bool
    decisive: bool


def build_state_signal(
    *,
    name,
    category,
    changed,
    decisive=False,
) -> StateSignal:
    """Constructs a StateSignal with explicit validation."""

    signal_name = str(name or "").strip()

    if not signal_name:
        raise ValueError(
            "QCC_UWT_STATE_SIGNAL_NAME_INVALID"
        )

    category_value = (
        category.value
        if isinstance(category, SignalCategory)
        else str(category or "").strip()
    )

    if category_value not in {
        item.value
        for item in SignalCategory
    }:
        raise ValueError(
            "QCC_UWT_STATE_SIGNAL_CATEGORY_INVALID"
        )

    return StateSignal(
        schema_version=STATE_SIGNAL_SCHEMA_VERSION,
        name=signal_name,
        category=category_value,
        changed=bool(changed),
        decisive=bool(decisive),
    )
