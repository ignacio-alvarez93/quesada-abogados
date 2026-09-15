"""Fingerprint funcional PII-safe de QCC Site Architecture."""

from __future__ import annotations

import hashlib
import json
import re

from .models import (
    SiteArchitectureSnapshot,
)
from .schema import (
    require_supported_schema_version,
)
from .snapshot import (
    build_normalized_snapshot_payload,
)


FUNCTIONAL_STATE_SCHEMA_VERSION = 3
FUNCTIONAL_STATE_TYPE = "QCC_FUNCTIONAL_STATE"
FUNCTIONAL_STATE_HASH_ALGORITHM = "sha256"

_VOLATILE_PATH_SESSION_PARAMETER = re.compile(
    r";jsessionid=[^/?#;]*",
    re.IGNORECASE,
)

# QCC_FUNCTIONAL_ACTIVE_UI_REGIONS_V3
#
# El fingerprint funcional debe distinguir superficies físicas
# distintas aunque compartan pathname y catálogo de acciones.
#
# Sólo se proyectan señales estructurales explícitas de estado
# activo/seleccionado. Deliberadamente NO se incorporan:
#
# - visible / displayed / interactable;
# - value / text / labels;
# - checked / selected de controles de formulario;
# - selected_value de catálogos.
#
# Así, por ejemplo:
#
#   panel A: r-tabs-state-active
#   panel B: r-tabs-state-default
#
# sí representa cambio funcional, mientras seleccionar un radio
# de un formulario sigue perteneciendo a navigation_context.
_FUNCTIONAL_ACTIVE_CLASS_TOKEN_PATTERN = re.compile(
    r"(?:^|[-_:])"
    r"(?:active|selected|current|expanded|open)"
    r"(?:$|[-_:])",
    re.IGNORECASE,
)

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


def _functional_pathname(value):
    """Normaliza identidad de ruta sin sesión transportada en URL."""

    pathname = _text(value)

    if pathname is None:
        return None

    normalized = (
        _VOLATILE_PATH_SESSION_PARAMETER.sub(
            "",
            pathname,
        )
    )

    return normalized or None


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


def _element_field(
    element,
    key,
):
    if not isinstance(
        element,
        dict,
    ):
        return None

    direct = element.get(
        key
    )

    if direct not in (
        None,
        "",
    ):
        return direct

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
        return None

    return attributes.get(
        key
    )


def _snapshot_elements(
    source,
):
    """Itera elementos DOM normalizados con frame_path estable."""

    for element in (
        source.get(
            "elements"
        )
        or ()
    ):
        if isinstance(
            element,
            dict,
        ):
            yield (
                "main",
                element,
            )

    for document in (
        source.get(
            "documents"
        )
        or ()
    ):
        if not isinstance(
            document,
            dict,
        ):
            continue

        frame_path = str(
            document.get(
                "frame_path"
            )
            or "main"
        )

        for element in (
            document.get(
                "elements"
            )
            or ()
        ):
            if isinstance(
                element,
                dict,
            ):
                yield (
                    frame_path,
                    element,
                )


def _active_ui_region_signature(
    frame_path,
    element,
):
    """Proyecta únicamente estado estructural activo PII-safe."""

    class_value = _text(
        _element_field(
            element,
            "class",
        )
    )

    active_class_tokens = []

    for token in str(
        class_value
        or ""
    ).split():

        if (
            _FUNCTIONAL_ACTIVE_CLASS_TOKEN_PATTERN
            .search(
                token
            )
        ):
            active_class_tokens.append(
                token.lower()
            )

    state_signals = (
        element.get(
            "state_signals"
        )
        or {}
    )

    if not isinstance(
        state_signals,
        dict,
    ):
        state_signals = {}

    positive_ui_state = {}

    for key in (
        "aria_selected",
        "aria_expanded",
        "aria_pressed",
    ):
        if (
            _bool_or_none(
                state_signals.get(
                    key
                )
            )
            is True
        ):
            positive_ui_state[
                key
            ] = True

    aria_current = _text(
        state_signals.get(
            "aria_current"
        )
    )

    if (
        aria_current is not None
        and aria_current.lower()
        not in {
            "false",
            "none",
        }
    ):
        positive_ui_state[
            "aria_current"
        ] = aria_current

    if (
        not active_class_tokens
        and not positive_ui_state
    ):
        return None

    element_id = _text(
        _element_field(
            element,
            "id",
        )
    )

    selector = _text(
        element.get(
            "selector"
        )
        or element.get(
            "primary_selector"
        )
    )

    # Fail closed: una señal activa sin identidad estructural
    # estable no entra en el fingerprint.
    if (
        element_id is None
        and selector is None
    ):
        return None

    return {
        "frame_path":
            str(
                frame_path
                or "main"
            ),

        "selector":
            selector,

        "element": {
            "tag":
                _text(
                    _element_field(
                        element,
                        "tag",
                    )
                ),

            "id":
                element_id,

            "name":
                _text(
                    _element_field(
                        element,
                        "name",
                    )
                ),

            "type":
                _text(
                    _element_field(
                        element,
                        "type",
                    )
                ),

            "role":
                _text(
                    _element_field(
                        element,
                        "role",
                    )
                ),
        },

        "active_class_tokens":
            tuple(
                sorted(
                    set(
                        active_class_tokens
                    )
                )
            ),

        "ui_state":
            positive_ui_state,
    }


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
        # interaction.state, interactable ni visible.
        #
        # Son propiedades físicas/runtime que pueden variar
        # por viewport, scroll o responsive layout sin que
        # cambie el estado funcional de la página.
        "interaction": {
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
        # QCC_COMPOSED_ACTION_ADDRESSABILITY_V1
        #
        # Esta evidencia amplía addressability del mismo
        # DOM físico observado, pero no redefine la identidad
        # de QCC_FUNCTIONAL_STATE_V2.
        #
        # Una futura inclusión en identidad funcional exigiría
        # una versión explícita del contrato.
        if (
            isinstance(
                action,
                dict,
            )
            and str(
                action.get(
                    "locator_basis"
                )
                or ""
            ).strip().upper()
            == "COMPOSED_PATH_HOST"
        ):
            continue

        signature = (
            _action_signature(
                action
            )
        )

        if signature is not None:
            actions.append(
                signature
            )

    active_ui_regions = []

    for (
        frame_path,
        element,
    ) in _snapshot_elements(
        source
    ):
        signature = (
            _active_ui_region_signature(
                frame_path,
                element,
            )
        )

        if signature is not None:
            active_ui_regions.append(
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
                _functional_pathname(
                    page.get("pathname")
                ),
        },

        "actions":
            _canonical_sort(
                actions
            ),

        # Estado estructural de regiones activas.
        #
        # No usa visibilidad física ni valores de formulario.
        "active_ui_regions":
            _canonical_sort(
                active_ui_regions
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
        "QCC_FUNCTIONAL_STATE_V3\\0"
        + canonical
    )

    return hashlib.sha256(
        namespaced.encode("utf-8")
    ).hexdigest()
