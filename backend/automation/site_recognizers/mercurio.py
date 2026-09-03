"""Adaptador de reconocimiento funcional de estados Mercurio.

Este módulo conecta el detector específico de Mercurio
con la infraestructura genérica Site Architecture.

No ejecuta acciones y no concede permisos.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from backend.automation.site_architecture.snapshot import (
    build_normalized_snapshot_payload,
)
from backend.automation.site_architecture.state_recognizer_registry import (
    SiteStateRecognizerRegistration,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_LAB_ORIGIN,
    MERCURIO_REAL_ORIGIN,
    MERCURIO_SITE_CODE,
)
from tools.mercurio_lab.core.state_detector import (
    detect_mercurio_general_state,
)


MERCURIO_SEDE_ORIGIN = (
    "https://sede.administracionespublicas.gob.es"
)

MERCURIO_LAB_LOCALHOST_ORIGIN = (
    "http://localhost:8767"
)



MERCURIO_EX01_NEW_REQUEST_PATH = (
    "/mercurio/nuevaSolicitud-EX01.html"
)


_MERCURIO_FORM_PATH_PATTERN = re.compile(
    r"^/mercurio/nuevaSolicitud-(EX[0-9]{2})\.html$",
    re.IGNORECASE,
)


_EX01_ACTIVE_PANEL_STATES = {
    "tab-datos_autorizacion":
        "EX01_AUTHORIZATION",

    "tab-datos_personales":
        "EX01_PERSONAL",

    "tab-datos_presentador":
        "EX01_PRESENTER",

    "tab-datos_notificacion":
        "EX01_NOTIFICATION",
}


def _elements(
    snapshot,
):
    elements = list(
        snapshot.get("elements")
        or ()
    )

    if elements:
        return elements

    for document in (
        snapshot.get("documents")
        or ()
    ):
        if not isinstance(
            document,
            dict,
        ):
            continue

        elements.extend(
            document.get("elements")
            or ()
        )

    return elements


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
        element.get("attributes")
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


def _class_tokens(
    element,
):
    return {
        token
        for token in str(
            _element_field(
                element,
                "class",
            )
            or ""
        ).split()
        if token
    }


def _page_origin_and_path(
    snapshot,
):
    page = (
        snapshot.get("page")
        or {}
    )

    if not isinstance(
        page,
        dict,
    ):
        return None, None

    parsed = urlsplit(
        str(
            page.get("url")
            or ""
        )
    )

    origin = str(
        page.get("origin")
        or ""
    ).strip()

    if (
        not origin
        and parsed.scheme
        and parsed.netloc
    ):
        origin = (
            parsed.scheme
            + "://"
            + parsed.netloc
        )

    pathname = str(
        page.get("pathname")
        or ""
    ).strip()

    if not pathname:
        pathname = (
            parsed.path
            or "/"
        )

    return (
        origin or None,
        pathname or None,
    )


def _recognize_mercurio_ex01_state(
    snapshot,
):
    """Reconoce EX01 mediante el panel funcional activo.

    No depende de marcadores artificiales
    exclusivos del TWIN.
    """

    origin, pathname = (
        _page_origin_and_path(
            snapshot
        )
    )

    allowed_origins = {
        MERCURIO_REAL_ORIGIN,
        MERCURIO_LAB_ORIGIN,
        MERCURIO_LAB_LOCALHOST_ORIGIN,
    }

    if (
        origin not in allowed_origins
        or pathname
        != MERCURIO_EX01_NEW_REQUEST_PATH
    ):
        return None

    recognized = set()

    for element in _elements(
        snapshot
    ):
        element_id = str(
            _element_field(
                element,
                "id",
            )
            or ""
        ).strip()

        state = (
            _EX01_ACTIVE_PANEL_STATES
            .get(
                element_id
            )
        )

        if state is None:
            continue

        if (
            "r-tabs-state-active"
            in _class_tokens(
                element
            )
        ):
            recognized.add(
                state
            )

    # Fail closed ante ausencia o ambigüedad.
    if len(recognized) != 1:
        return None

    return next(
        iter(
            recognized
        )
    )


def _snapshot_payload(
    snapshot,
):
    if isinstance(
        snapshot,
        dict,
    ):
        return snapshot

    return (
        build_normalized_snapshot_payload(
            snapshot
        )
    )


def resolve_mercurio_architecture_scope(
    snapshot,
    observation,
):
    """
    Proyecta únicamente identidad de retención.

    No ejecuta acciones y no decide fingerprint.

    Ejemplos:
      nuevaSolicitud-EX01.html -> FORM_EX01
      nuevaSolicitud-EX26.html -> FORM_EX26
      superficies comunes      -> MERCURIO_GLOBAL

    El estado interno (EX01_PERSONAL, etc.) permanece
    independiente y se usa como functional_state.
    """

    payload = _snapshot_payload(
        snapshot
    )

    origin, pathname = (
        _page_origin_and_path(
            payload
        )
    )

    allowed_origins = {
        MERCURIO_REAL_ORIGIN,
        MERCURIO_LAB_ORIGIN,
        MERCURIO_LAB_LOCALHOST_ORIGIN,
    }

    if origin not in allowed_origins:
        return None

    match = (
        _MERCURIO_FORM_PATH_PATTERN
        .fullmatch(
            str(
                pathname
                or ""
            )
        )
    )

    if match is not None:
        return (
            "FORM_"
            + match.group(1).upper()
        )

    return "MERCURIO_GLOBAL"


def recognize_mercurio_state(
    snapshot,
):
    """Traduce Site Architecture a estado semántico Mercurio.

    General primero.
    Después, estados funcionales específicos conocidos.
    """

    payload = _snapshot_payload(
        snapshot
    )

    state = (
        detect_mercurio_general_state(
            payload
        )
    )

    if state is not None:
        return state.value

    return (
        _recognize_mercurio_ex01_state(
            payload
        )
    )



def build_mercurio_state_registration():
    """Registro común para navegación Mercurio LAB/REAL."""

    return SiteStateRecognizerRegistration(
        site_code=MERCURIO_SITE_CODE,
        origins=(
            MERCURIO_REAL_ORIGIN,
            MERCURIO_SEDE_ORIGIN,
            MERCURIO_LAB_ORIGIN,
            MERCURIO_LAB_LOCALHOST_ORIGIN,
        ),
        recognizer=(
            recognize_mercurio_state
        ),
    )
