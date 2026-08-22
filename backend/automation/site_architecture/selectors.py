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
    ROLE = "ROLE"
    TAG_TYPE_NAME = "TAG_TYPE_NAME"


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


def _selector_occurrences(
    selector,
    *,
    frame_path,
    elements,
):
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
