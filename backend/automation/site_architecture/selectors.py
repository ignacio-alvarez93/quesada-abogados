"""Generación de candidatos de selector para Site Architecture."""

from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
    replace,
)
from enum import Enum
import re


class SelectorStrategy(str, Enum):
    ID = "ID"
    NAME = "NAME"
    DATA_TESTID = "DATA_TESTID"
    ARIA_LABEL = "ARIA_LABEL"
    ONCLICK = "ONCLICK"
    ROLE = "ROLE"
    TAG_TYPE_NAME = "TAG_TYPE_NAME"
    STRUCTURAL_ATTRIBUTE = "STRUCTURAL_ATTRIBUTE"


class SelectorConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class SelectorCandidate:
    strategy: SelectorStrategy
    selector: str
    confidence: SelectorConfidence
    unique: bool | None = None

    def to_dict(self):
        result = asdict(self)
        result["strategy"] = self.strategy.value
        result["confidence"] = self.confidence.value
        return result


_SAFE_CSS_ID = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_-]*$"
)


# QCC_ONCLICK_LITERAL_SELECTOR_IDENTITY_V1
#
# Solo sirve para IDENTIFICAR el elemento.
# No ejecuta JavaScript ni concede autoridad.
_SAFE_ONCLICK_LITERAL = (
    r"(?:"
    r"'[A-Za-z0-9_ .:/-]{0,128}'"
    r'|"[A-Za-z0-9_ .:/-]{0,128}"'
    r"|-?[0-9]+(?:\.[0-9]+)?"
    r"|true"
    r"|false"
    r"|null"
    r")"
)

_SAFE_ONCLICK_HANDLER = re.compile(
    r"^(?:return\s+)?"
    r"(?:window\.)?"
    r"[A-Za-z_$][A-Za-z0-9_$]*"
    r"\(\s*"
    r"(?:"
    + _SAFE_ONCLICK_LITERAL
    + r"(?:\s*,\s*"
    + _SAFE_ONCLICK_LITERAL
    + r")*"
    + r")?"
    r"\s*\)\s*;?$"
)


_ONCLICK_HANDLER_NAME = re.compile(
    r"^(?:return\s+)?"
    r"(?:window\.)?"
    r"([A-Za-z_$][A-Za-z0-9_$]*)"
    r"\s*\("
)

_UNSAFE_ONCLICK_HANDLER_NAMES = {
    "alert",
    "confirm",
    "prompt",
    "eval",
    "function",
    "settimeout",
    "setinterval",
}


def _safe_onclick_handler(
    value,
):
    if not _SAFE_ONCLICK_HANDLER.fullmatch(
        value
    ):
        return False

    match = _ONCLICK_HANDLER_NAME.match(
        value
    )

    if match is None:
        return False

    return (
        match.group(1).lower()
        not in _UNSAFE_ONCLICK_HANDLER_NAMES
    )


# QCC_ONCLICK_STRUCTURAL_SIGNATURE_V1
#
# Ruling A (Project Direction, 2D-25): un literal onclick observado
# puede contener PII, identificadores o valores dinamicos y NUNCA se
# persiste tal cual como identidad de addressability durable. Esta
# funcion deriva la firma estructural minima (handler + aridad),
# preservando semantica de handler/funcion/interaccion y excluyendo
# siempre los valores literales de los argumentos.
def _onclick_structural_signature(
    value,
):
    if not _safe_onclick_handler(
        value
    ):
        return None

    match = _ONCLICK_HANDLER_NAME.match(
        value
    )

    if match is None:
        return None

    trailing_semicolon = (
        value.rstrip().endswith(";")
    )

    return (
        match.group(0)
        + ")"
        + (
            ";"
            if trailing_semicolon
            else ""
        )
    )


_STRUCTURAL_ATTRIBUTE_NAME = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}$"
)

_STRUCTURAL_ATTRIBUTE_VALUE = re.compile(
    r"^[A-Za-z0-9_.:-]{1,64}$"
)

# Campos visuales, variables, navegacionales o potencialmente
# sensibles nunca se usan como locator estructural genérico.
_STRUCTURAL_ATTRIBUTE_DENYLIST = {
    "active",
    "alt",
    "aria-label",
    "checked",
    "class",
    "data-testid",
    "dir",
    "disabled",
    "hidden",
    "href",
    "icon",
    "icon-position",
    "id",
    "lang",
    "name",
    "onclick",
    "placeholder",
    "readonly",
    "role",
    "routerlink",
    "selected",
    "size",
    "src",
    "srcset",
    "style",
    "tabindex",
    "text",
    "title",
    "to",
    "value",
}


def _css_attribute_value(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )


def _id_selector(value):
    value = str(value or "")

    if _SAFE_CSS_ID.fullmatch(value):
        return f"#{value}"

    return (
        '[id="'
        + _css_attribute_value(value)
        + '"]'
    )


def _attribute(
    element,
    name,
):
    attributes = (
        element.get("attributes")
        if isinstance(element, dict)
        else {}
    )

    if not isinstance(attributes, dict):
        attributes = {}

    return str(
        attributes.get(name)
        or ""
    ).strip()


def build_selector_candidates(
    element,
):
    """Genera selectores candidatos sin inventar unicidad."""

    if not isinstance(element, dict):
        return ()

    tag = str(
        element.get("tag")
        or ""
    ).strip().lower()

    element_id = str(
        element.get("id")
        or ""
    ).strip()

    name = str(
        element.get("name")
        or ""
    ).strip()

    input_type = str(
        element.get("type")
        or ""
    ).strip()

    role = str(
        element.get("role")
        or ""
    ).strip()

    data_testid = _attribute(
        element,
        "data-testid",
    )

    aria_label = _attribute(
        element,
        "aria-label",
    )

    onclick = _attribute(
        element,
        "onclick",
    )

    candidates = []

    if element_id:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.ID,
                selector=_id_selector(
                    element_id
                ),
                confidence=(
                    SelectorConfidence.HIGH
                ),
            )
        )

    if name:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.NAME,
                selector=(
                    '[name="'
                    + _css_attribute_value(name)
                    + '"]'
                ),
                confidence=(
                    SelectorConfidence.HIGH
                ),
            )
        )

    if data_testid:
        candidates.append(
            SelectorCandidate(
                strategy=(
                    SelectorStrategy.DATA_TESTID
                ),
                selector=(
                    '[data-testid="'
                    + _css_attribute_value(
                        data_testid
                    )
                    + '"]'
                ),
                confidence=(
                    SelectorConfidence.HIGH
                ),
            )
        )

    if aria_label:
        candidates.append(
            SelectorCandidate(
                strategy=(
                    SelectorStrategy.ARIA_LABEL
                ),
                selector=(
                    '[aria-label="'
                    + _css_attribute_value(
                        aria_label
                    )
                    + '"]'
                ),
                confidence=(
                    SelectorConfidence.MEDIUM
                ),
            )
        )

    onclick_structural = (
        _onclick_structural_signature(
            onclick
        )
        if (tag and onclick)
        else None
    )

    if onclick_structural is not None:
        candidates.append(
            SelectorCandidate(
                strategy=(
                    SelectorStrategy.ONCLICK
                ),
                selector=(
                    tag
                    + '[onclick="'
                    + _css_attribute_value(
                        onclick_structural
                    )
                    + '"]'
                ),
                confidence=(
                    SelectorConfidence.MEDIUM
                ),
            )
        )

    if role:
        candidates.append(
            SelectorCandidate(
                strategy=SelectorStrategy.ROLE,
                selector=(
                    '[role="'
                    + _css_attribute_value(role)
                    + '"]'
                ),
                confidence=(
                    SelectorConfidence.LOW
                ),
            )
        )

    if (
        tag
        and input_type
        and name
    ):
        candidates.append(
            SelectorCandidate(
                strategy=(
                    SelectorStrategy.TAG_TYPE_NAME
                ),
                selector=(
                    tag
                    + '[type="'
                    + _css_attribute_value(
                        input_type
                    )
                    + '"][name="'
                    + _css_attribute_value(name)
                    + '"]'
                ),
                confidence=(
                    SelectorConfidence.MEDIUM
                ),
            )
        )

    composed_surface = (
        element.get(
            "composed_action_surface"
        )
        or {}
    )

    if (
        isinstance(
            composed_surface,
            dict,
        )
        and str(
            composed_surface.get(
                "locator_basis"
            )
            or ""
        ).strip().upper()
        == "COMPOSED_PATH_HOST"
        and tag
        and "-" in tag
    ):
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
            for attribute_name in sorted(
                attributes
            ):
                normalized_name = str(
                    attribute_name
                    or ""
                ).strip().lower()

                if (
                    not normalized_name
                    or normalized_name
                    in _STRUCTURAL_ATTRIBUTE_DENYLIST
                    or normalized_name.startswith(
                        "_"
                    )
                    or normalized_name.startswith(
                        "aria-"
                    )
                    or not _STRUCTURAL_ATTRIBUTE_NAME.fullmatch(
                        normalized_name
                    )
                ):
                    continue

                normalized_value = str(
                    attributes.get(
                        attribute_name
                    )
                    or ""
                ).strip()

                if (
                    not normalized_value
                    or not _STRUCTURAL_ATTRIBUTE_VALUE.fullmatch(
                        normalized_value
                    )
                ):
                    continue

                selector = (
                    tag
                    + "["
                    + normalized_name
                    + '="'
                    + _css_attribute_value(
                        normalized_value
                    )
                    + '"]'
                )

                if any(
                    candidate.selector
                    == selector
                    for candidate
                    in candidates
                ):
                    continue

                candidates.append(
                    SelectorCandidate(
                        strategy=(
                            SelectorStrategy
                            .STRUCTURAL_ATTRIBUTE
                        ),
                        selector=selector,
                        confidence=(
                            SelectorConfidence.LOW
                        ),
                    )
                )

    return tuple(candidates)


@dataclass(frozen=True, slots=True)
class SelectorProfile:
    frame_path: str
    primary: SelectorCandidate | None
    fallbacks: tuple[SelectorCandidate, ...]
    candidates: tuple[SelectorCandidate, ...]
    confidence: SelectorConfidence | None

    def to_dict(self):
        return {
            "frame_path": self.frame_path,
            "primary": (
                self.primary.to_dict()
                if self.primary
                else None
            ),
            "fallbacks": tuple(
                item.to_dict()
                for item in self.fallbacks
            ),
            "candidates": tuple(
                item.to_dict()
                for item in self.candidates
            ),
            "confidence": (
                self.confidence.value
                if self.confidence
                else None
            ),
        }


def _element_frame_path(
    element,
):
    if not isinstance(element, dict):
        return "main"

    return str(
        element.get("frame_path")
        or "main"
    )


def build_selector_occurrence_index(
    elements,
):
    """Precalcula ocurrencias por frame y selector en una sola pasada."""

    occurrences = {}

    for item in elements:
        if not isinstance(item, dict):
            continue

        frame_path = _element_frame_path(
            item
        )

        selectors = {
            candidate.selector
            for candidate
            in build_selector_candidates(
                item
            )
        }

        for selector in selectors:
            key = (
                frame_path,
                selector,
            )

            occurrences[key] = (
                occurrences.get(
                    key,
                    0,
                )
                + 1
            )

    return occurrences


def _selector_occurrences(
    selector,
    *,
    frame_path,
    elements,
    occurrence_index=None,
):
    if occurrence_index is not None:
        return int(
            occurrence_index.get(
                (
                    frame_path,
                    selector,
                ),
                0,
            )
        )

    occurrences = 0

    for item in elements:
        if not isinstance(item, dict):
            continue

        if (
            _element_frame_path(item)
            != frame_path
        ):
            continue

        candidates = build_selector_candidates(
            item
        )

        if any(
            candidate.selector == selector
            for candidate in candidates
        ):
            occurrences += 1

    return occurrences


def resolve_selector_profile(
    element,
    elements,
    *,
    occurrence_index=None,
):
    """Resuelve unicidad y selecciona locator primario seguro."""

    frame_path = _element_frame_path(
        element
    )

    candidates = (
        build_selector_candidates(
            element
        )
    )

    resolved = tuple(
        replace(
            candidate,
            unique=(
                _selector_occurrences(
                    candidate.selector,
                    frame_path=frame_path,
                    elements=elements,
                    occurrence_index=(
                        occurrence_index
                    ),
                )
                == 1
            ),
        )
        for candidate in candidates
    )

    unique_candidates = tuple(
        candidate
        for candidate in resolved
        if candidate.unique
    )

    primary = (
        unique_candidates[0]
        if unique_candidates
        else None
    )

    fallbacks = (
        unique_candidates[1:]
        if primary
        else ()
    )

    return SelectorProfile(
        frame_path=frame_path,
        primary=primary,
        fallbacks=fallbacks,
        candidates=resolved,
        confidence=(
            primary.confidence
            if primary
            else None
        ),
    )
