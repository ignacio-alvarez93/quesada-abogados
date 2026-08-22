"""Clasificación semántica genérica de elementos web."""

from __future__ import annotations

from enum import Enum


class SiteElementSemantic(str, Enum):
    FORM = "FORM"
    TEXT_INPUT = "TEXT_INPUT"
    FILE_INPUT = "FILE_INPUT"
    HIDDEN_INPUT = "HIDDEN_INPUT"
    CHECKBOX = "CHECKBOX"
    RADIO = "RADIO"
    SELECT = "SELECT"
    TEXTAREA = "TEXTAREA"
    BUTTON = "BUTTON"
    SUBMIT = "SUBMIT"
    LINK = "LINK"
    TABLE = "TABLE"
    FRAME = "FRAME"
    LABEL = "LABEL"
    DIALOG = "DIALOG"


def classify_element_semantics(
    element,
):
    """Devuelve semánticas genéricas inferidas del DOM observable."""

    if not isinstance(element, dict):
        return ()

    tag = str(
        element.get("tag")
        or ""
    ).strip().lower()

    input_type = str(
        element.get("type")
        or ""
    ).strip().lower()

    role = str(
        element.get("role")
        or ""
    ).strip().lower()

    semantics = []

    if tag == "form":
        semantics.append(
            SiteElementSemantic.FORM
        )

    if tag == "input":
        if input_type == "file":
            semantics.append(
                SiteElementSemantic.FILE_INPUT
            )
        elif input_type == "hidden":
            semantics.append(
                SiteElementSemantic.HIDDEN_INPUT
            )
        elif input_type == "checkbox":
            semantics.append(
                SiteElementSemantic.CHECKBOX
            )
        elif input_type == "radio":
            semantics.append(
                SiteElementSemantic.RADIO
            )
        elif input_type == "submit":
            semantics.extend((
                SiteElementSemantic.BUTTON,
                SiteElementSemantic.SUBMIT,
            ))
        elif input_type == "button":
            semantics.append(
                SiteElementSemantic.BUTTON
            )
        else:
            semantics.append(
                SiteElementSemantic.TEXT_INPUT
            )

    if tag == "select":
        semantics.append(
            SiteElementSemantic.SELECT
        )

    if tag == "textarea":
        semantics.append(
            SiteElementSemantic.TEXTAREA
        )

    if tag == "button":
        semantics.append(
            SiteElementSemantic.BUTTON
        )

        if input_type == "submit":
            semantics.append(
                SiteElementSemantic.SUBMIT
            )

    if tag == "a":
        semantics.append(
            SiteElementSemantic.LINK
        )

    if tag == "table":
        semantics.append(
            SiteElementSemantic.TABLE
        )

    if tag in ("iframe", "frame"):
        semantics.append(
            SiteElementSemantic.FRAME
        )

    if tag == "label":
        semantics.append(
            SiteElementSemantic.LABEL
        )

    role_mapping = {
        "button":
            SiteElementSemantic.BUTTON,
        "link":
            SiteElementSemantic.LINK,
        "checkbox":
            SiteElementSemantic.CHECKBOX,
        "radio":
            SiteElementSemantic.RADIO,
        "dialog":
            SiteElementSemantic.DIALOG,
    }

    role_semantic = role_mapping.get(
        role
    )

    if (
        role_semantic
        and role_semantic
        not in semantics
    ):
        semantics.append(
            role_semantic
        )

    return tuple(
        semantic.value
        for semantic in semantics
    )
