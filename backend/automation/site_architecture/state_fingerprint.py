"""Fingerprint funcional PII-safe de QCC Site Architecture."""

from __future__ import annotations

import hashlib
import json

from .models import (
    SiteArchitectureSnapshot,
)
from .schema import (
    require_supported_schema_version,
)
from .snapshot import (
    build_normalized_snapshot_payload,
)


FUNCTIONAL_STATE_SCHEMA_VERSION = 1
FUNCTIONAL_STATE_TYPE = "QCC_FUNCTIONAL_STATE"
FUNCTIONAL_STATE_HASH_ALGORITHM = "sha256"

_FUNCTIONAL_UI_STATE_KEYS = (
    "aria_selected",
    "aria_expanded",
    "aria_pressed",
    "aria_current",
)


def _snapshot_payload(value):
    if isinstance(
        value,
        SiteArchitectureSnapshot,
    ):
        return build_normalized_snapshot_payload(
            value
        )

    if not isinstance(value, dict):
        raise ValueError(
            "SITE_ARCHITECTURE_STATE_INPUT_INVALID"
        )

    require_supported_schema_version(
        value.get("schema_version")
    )

    return value


def _text(value):
    value = str(
        value
        or ""
    ).strip()

    return value or None


def _bool_or_none(value):
    if value is True:
        return True

    if value is False:
        return False

    normalized = str(
        value
        or ""
    ).strip().lower()

    if normalized == "true":
        return True

    if normalized == "false":
        return False

    return None


def _canonical_sort(records):
    return tuple(
        sorted(
            records,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    )


def _action_signature(action):
    if not isinstance(action, dict):
        return None

    interaction = (
        action.get("interaction")
        or {}
    )

    if not isinstance(
        interaction,
        dict,
    ):
        interaction = {}

    state_signals = (
        action.get("state_signals")
        or {}
    )

    if not isinstance(
        state_signals,
        dict,
    ):
        state_signals = {}

    element = (
        action.get("element")
        or {}
    )

    if not isinstance(
        element,
        dict,
    ):
        element = {}

    ui_state = {}

    for key in _FUNCTIONAL_UI_STATE_KEYS:
        value = state_signals.get(
            key
        )

        if key == "aria_current":
            ui_state[key] = _text(
                value
            )
        else:
            ui_state[key] = (
                _bool_or_none(
                    value
                )
            )

    return {
        "frame_path":
            str(
                action.get("frame_path")
                or "main"
            ),

        "kind":
            _text(
                action.get("kind")
            ),

        "policy":
            _text(
                action.get("policy")
            ),

        "selector":
            _text(
                action.get("selector")
            ),

        "semantics":
            tuple(
                sorted(
                    str(value)
                    for value in (
                        action.get("semantics")
                        or ()
                    )
                )
            ),

        # Deliberadamente no usamos
        # interaction.state ni interactable,
        # porque pueden variar por viewport/scroll.
        "interaction": {
            "visible":
                _bool_or_none(
                    interaction.get(
                        "visible"
                    )
                ),

            "disabled":
                _bool_or_none(
                    interaction.get(
                        "disabled"
                    )
                ),
        },

        "ui_state":
            ui_state,

        "element": {
            "tag":
                _text(
                    element.get("tag")
                ),

            "id":
                _text(
                    element.get("id")
                ),

            "name":
                _text(
                    element.get("name")
                ),

            "type":
                _text(
                    element.get("type")
                ),

            "role":
                _text(
                    element.get("role")
                ),
        },
    }


def _catalog_signature(catalog):
    if not isinstance(
        catalog,
        dict,
    ):
        return None

    return {
        "frame_path":
            str(
                catalog.get("frame_path")
                or "main"
            ),

        "catalog_type":
            _text(
                catalog.get(
                    "catalog_type"
                )
            ),

        "selector":
            _text(
                catalog.get(
                    "selector"
                )
            ),
    }


def _catalog_relation_signature(
    relation,
):
    if not isinstance(
        relation,
        dict,
    ):
        return None

    return {
        "relation":
            _text(
                relation.get("relation")
            ),

        "source":
            _text(
                relation.get("source")
            ),

        "target":
            _text(
                relation.get("target")
            ),
    }


def build_functional_state_payload(
    snapshot,
):
    """Construye identidad funcional estable y PII-safe."""

    source = _snapshot_payload(
        snapshot
    )

    page = source.get("page")

    if not isinstance(page, dict):
        page = {}

    actions = []

    for action in (
        source.get("actions")
        or ()
    ):
        signature = (
            _action_signature(
                action
            )
        )

        if signature is not None:
            actions.append(
                signature
            )

    catalogs = []

    for catalog in (
        source.get("catalogs")
        or ()
    ):
        signature = (
            _catalog_signature(
                catalog
            )
        )

        if signature is not None:
            catalogs.append(
                signature
            )

    catalog_relations = []

    for relation in (
        source.get(
            "catalog_relations"
        )
        or ()
    ):
        signature = (
            _catalog_relation_signature(
                relation
            )
        )

        if signature is not None:
            catalog_relations.append(
                signature
            )

    return {
        "schema_version":
            FUNCTIONAL_STATE_SCHEMA_VERSION,

        "state_type":
            FUNCTIONAL_STATE_TYPE,

        # query, title, URL completa y page.signature
        # quedan fuera deliberadamente.
        "page": {
            "origin":
                _text(
                    page.get("origin")
                ),

            "pathname":
                _text(
                    page.get("pathname")
                ),
        },

        "actions":
            _canonical_sort(
                actions
            ),

        # No incluimos opciones, labels,
        # selected_value ni option_count.
        "catalogs":
            _canonical_sort(
                catalogs
            ),

        "catalog_relations":
            _canonical_sort(
                catalog_relations
            ),
    }


def canonicalize_functional_state(
    snapshot,
):
    payload = (
        build_functional_state_payload(
            snapshot
        )
    )

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def build_functional_state_fingerprint(
    snapshot,
):
    canonical = (
        canonicalize_functional_state(
            snapshot
        )
    )

    namespaced = (
        "QCC_FUNCTIONAL_STATE_V1\\0"
        + canonical
    )

    return hashlib.sha256(
        namespaced.encode("utf-8")
    ).hexdigest()
