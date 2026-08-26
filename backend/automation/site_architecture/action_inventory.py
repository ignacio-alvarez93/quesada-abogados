"""Inventario pasivo de acciones de QCC Site Architecture."""

from __future__ import annotations


ACTION_INVENTORY_SCHEMA_VERSION = 1

ACTION_POLICY_VALUE_CHANGE = (
    "VALUE_CHANGE_CANDIDATE"
)
ACTION_POLICY_STATE_CHANGE = (
    "STATE_CHANGE_CANDIDATE"
)
ACTION_POLICY_NAVIGATION = (
    "NAVIGATION_CANDIDATE"
)
ACTION_POLICY_REQUIRES_POLICY = (
    "REQUIRES_POLICY"
)


def _semantics(element):
    return {
        str(value).strip().upper()
        for value in (
            element.get("semantics")
            or ()
        )
        if str(value).strip()
    }


def _attributes(element):
    value = (
        element.get("attributes")
        or {}
    )

    if not isinstance(value, dict):
        return {}

    return value


def _primary_selector(element):
    selectors = (
        element.get("selectors")
        or {}
    )

    if not isinstance(selectors, dict):
        return None

    primary = (
        selectors.get("primary")
        or {}
    )

    if not isinstance(primary, dict):
        return None

    value = str(
        primary.get("selector")
        or ""
    ).strip()

    return value or None


def _action_kind(element):
    semantics = _semantics(element)

    tag = str(
        element.get("tag")
        or ""
    ).lower()

    role = str(
        element.get("role")
        or ""
    ).lower()

    input_type = str(
        element.get("type")
        or ""
    ).lower()

    attributes = _attributes(element)

    if role == "tab":
        return "TAB"

    if "SUBMIT" in semantics:
        return "SUBMIT"

    if "FILE_INPUT" in semantics:
        return "FILE_UPLOAD"

    if "RADIO" in semantics:
        return "RADIO"

    if "CHECKBOX" in semantics:
        return "CHECKBOX"

    if "SELECT" in semantics:
        return "SELECT"

    if (
        "TEXT_INPUT" in semantics
        or "TEXTAREA" in semantics
    ):
        return "INPUT_VALUE"

    if (
        "LINK" in semantics
        or (
            tag == "a"
            and str(
                attributes.get("href")
                or ""
            ).strip()
        )
    ):
        return "LINK"

    if (
        "BUTTON" in semantics
        or tag == "button"
        or role == "button"
        or input_type in {
            "button",
            "reset",
            "image",
        }
    ):
        return "BUTTON"

    return None


def _execution_policy(kind):
    if kind in {
        "RADIO",
        "CHECKBOX",
        "SELECT",
    }:
        return (
            ACTION_POLICY_STATE_CHANGE
        )

    if kind == "INPUT_VALUE":
        return (
            ACTION_POLICY_VALUE_CHANGE
        )

    if kind in {
        "LINK",
        "TAB",
    }:
        return (
            ACTION_POLICY_NAVIGATION
        )

    # BUTTON, SUBMIT y FILE_UPLOAD no reciben
    # permiso automático. Su efecto debe ser
    # aprendido o gobernado antes de ejecutarlos.
    return (
        ACTION_POLICY_REQUIRES_POLICY
    )


def build_action_inventory(elements):
    """Deriva candidatos accionables sin ejecutar ninguno."""

    actions = []

    for position, element in enumerate(
        elements or ()
    ):
        if not isinstance(
            element,
            dict,
        ):
            continue

        kind = _action_kind(
            element
        )

        if kind is None:
            continue

        interaction = (
            element.get("interaction")
            or {}
        )

        if not isinstance(
            interaction,
            dict,
        ):
            interaction = {}

        attributes = _attributes(
            element
        )

        selectors = (
            element.get("selectors")
            or {}
        )

        if not isinstance(
            selectors,
            dict,
        ):
            selectors = {}

        actions.append({
            "schema_version":
                ACTION_INVENTORY_SCHEMA_VERSION,

            "action_index":
                len(actions),

            "element_index":
                element.get(
                    "index",
                    position,
                ),

            "frame_path":
                str(
                    element.get(
                        "frame_path"
                    )
                    or "main"
                ),

            "kind":
                kind,

            "policy":
                _execution_policy(
                    kind
                ),

            "selector":
                _primary_selector(
                    element
                ),

            "selector_confidence":
                selectors.get(
                    "confidence"
                ),

            "semantics":
                tuple(
                    sorted(
                        _semantics(
                            element
                        )
                    )
                ),

            "state_signals":
                dict(
                    element.get(
                        "state_signals"
                    )
                    or {}
                ),

            "interaction": {
                "state":
                    interaction.get(
                        "state"
                    ),

                "visible":
                    interaction.get(
                        "visible"
                    ),

                "interactable":
                    interaction.get(
                        "interactable"
                    ),

                "disabled":
                    interaction.get(
                        "disabled"
                    ),
            },

            "element": {
                "tag":
                    str(
                        element.get("tag")
                        or ""
                    ),

                "id":
                    str(
                        element.get("id")
                        or ""
                    ),

                "name":
                    str(
                        element.get("name")
                        or ""
                    ),

                "type":
                    str(
                        element.get("type")
                        or ""
                    ),

                "role":
                    str(
                        element.get("role")
                        or ""
                    ),
            },

            "navigation": {
                "href":
                    (
                        str(
                            attributes.get(
                                "href"
                            )
                            or ""
                        )
                        or None
                    ),

                "target":
                    (
                        str(
                            attributes.get(
                                "target"
                            )
                            or ""
                        )
                        or None
                    ),
            },
        })

    return tuple(actions)
