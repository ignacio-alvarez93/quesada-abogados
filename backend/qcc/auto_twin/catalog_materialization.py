"""Materialización canónica de evidencia catalogal para AUTO TWIN.

Este módulo NO:
- navega;
- interactúa con REAL;
- selecciona opciones;
- modifica MaterializedRevision;
- decide qué capture debe utilizarse.

Recibe un qcc_capture REAL explícito y construye un artefacto
runtime/catalogs.json provider-neutral, sanitizado y determinista.

La procedencia visual del estado y la procedencia catalogal pueden
ser capturas distintas. Esa asociación se gobernará en la siguiente
capa de materialización.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.automation.site_architecture.catalogs import (
    normalize_catalogs,
)


AUTO_TWIN_CATALOG_RUNTIME_SCHEMA_VERSION = 1

AUTO_TWIN_CATALOG_RUNTIME_TYPE = (
    "QCC_AUTO_TWIN_CATALOG_RUNTIME"
)

AUTO_TWIN_CATALOG_OPTION_IDENTITY_MODE = (
    "VALUE_OR_LABEL"
)


def _text(value) -> str:
    return str(
        value
        or ""
    ).strip()


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value) -> str:
    return hashlib.sha256(
        _canonical_json(
            value
        ).encode(
            "utf-8"
        )
    ).hexdigest()


def _main_result(
    payload,
):
    if not isinstance(
        payload,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CATALOG_CAPTURE_INVALID"
        )

    frames = (
        payload.get("frames")
        or []
    )

    if not isinstance(
        frames,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_FRAMES_INVALID"
        )

    frame = next(
        (
            item
            for item in frames
            if (
                isinstance(
                    item,
                    dict,
                )
                and item.get(
                    "frame_id"
                ) == 0
            )
        ),
        None,
    )

    if frame is None:
        frame = next(
            (
                item
                for item in frames
                if isinstance(
                    item,
                    dict,
                )
            ),
            None,
        )

    if frame is None:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_MAIN_FRAME_REQUIRED"
        )

    result = (
        frame.get("result")
        or {}
    )

    if not isinstance(
        result,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_MAIN_RESULT_INVALID"
        )

    return result


def _sanitize_option(
    option,
):
    if not isinstance(
        option,
        dict,
    ):
        return None

    return {
        "value":
            _text(
                option.get(
                    "value"
                )
            ),

        "label":
            _text(
                option.get(
                    "label"
                )
            ),

        "selected":
            bool(
                option.get(
                    "selected"
                )
            ),

        "disabled":
            bool(
                option.get(
                    "disabled"
                )
            ),
    }


def _sanitize_state(
    state,
):
    if not isinstance(
        state,
        dict,
    ):
        state = {}

    raw_selected_values = (
        state.get(
            "selected_values"
        )
        or []
    )

    if not isinstance(
        raw_selected_values,
        (list, tuple),
    ):
        raw_selected_values = []

    raw_index = state.get(
        "selected_index"
    )

    try:
        selected_index = int(
            raw_index
        )
    except (
        TypeError,
        ValueError,
    ):
        selected_index = -1

    return {
        "selected_value":
            _text(
                state.get(
                    "selected_value"
                )
            ),

        "selected_label":
            _text(
                state.get(
                    "selected_label"
                )
            ),

        "selected_values": [
            _text(value)
            for value
            in raw_selected_values
        ],

        "selected_index":
            selected_index,

        "disabled":
            bool(
                state.get(
                    "disabled"
                )
            ),

        "required":
            bool(
                state.get(
                    "required"
                )
            ),

        "multiple":
            bool(
                state.get(
                    "multiple"
                )
            ),
    }


def _sanitize_element(
    element,
):
    if not isinstance(
        element,
        dict,
    ):
        element = {}

    classes = (
        element.get(
            "classes"
        )
        or []
    )

    if not isinstance(
        classes,
        (list, tuple),
    ):
        classes = []

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
        attributes = {}

    return {
        "tag":
            _text(
                element.get(
                    "tag"
                )
            ),

        "id":
            _text(
                element.get(
                    "id"
                )
            ),

        "name":
            _text(
                element.get(
                    "name"
                )
            ),

        "classes": [
            _text(value)
            for value
            in classes
            if _text(value)
        ],

        "label_text":
            _text(
                element.get(
                    "label_text"
                )
            ),

        # Solo atributos DOM observados.
        # Los probes diagnósticos temporales no llegan aquí.
        "attributes": {
            _text(name):
                _text(value)
            for name, value
            in attributes.items()
            if _text(name)
        },
    }


def _sanitize_catalog(
    catalog,
):
    if not isinstance(
        catalog,
        dict,
    ):
        return None

    options = []

    for option in (
        catalog.get(
            "options"
        )
        or []
    ):
        normalized = (
            _sanitize_option(
                option
            )
        )

        if normalized is not None:
            options.append(
                normalized
            )

    hints = (
        catalog.get(
            "dependency_hints"
        )
        or {}
    )

    if not isinstance(
        hints,
        dict,
    ):
        hints = {}

    return {
        "catalog_type":
            _text(
                catalog.get(
                    "catalog_type"
                )
            ),

        "implementation":
            _text(
                catalog.get(
                    "implementation"
                )
            ),

        "selector":
            _text(
                catalog.get(
                    "selector"
                )
            ),

        "frame_path":
            _text(
                catalog.get(
                    "frame_path"
                )
            )
            or "main",

        "element":
            _sanitize_element(
                catalog.get(
                    "element"
                )
            ),

        "state":
            _sanitize_state(
                catalog.get(
                    "state"
                )
            ),

        "options_count":
            len(
                options
            ),

        "options":
            options,

        "dependency_hints": {
            _text(name):
                _text(value)
            for name, value
            in hints.items()
            if (
                _text(name)
                and _text(value)
            )
        },
    }


def _catalog_knowledge_projection(
    *,
    pathname,
    catalogs,
):
    """Identidad estable del conocimiento de catálogo.

    La selección actual del formulario NO cambia
    la identidad funcional del catálogo.

    Se excluyen:
    - selected;
    - selected_value;
    - selected_label;
    - selected_values;
    - selected_index;
    - disabled/loading del estado vivo del control.

    Sí permanecen:
    - catálogo/control;
    - opciones;
    - value/label;
    - orden;
    - disabled por opción;
    - dependencias.
    """

    volatile_selected = {
        "selected",
        "selected_value",
        "selected_label",
        "selected_values",
        "selected_index",
    }

    volatile_live_state = {
        "disabled",
        "loading",
    }

    def sanitize(
        value,
        *,
        parent_key=None,
    ):
        if isinstance(
            value,
            dict,
        ):
            result = {}

            for key in sorted(
                value
            ):
                if key in volatile_selected:
                    continue

                if (
                    parent_key == "state"
                    and key in volatile_live_state
                ):
                    continue

                result[
                    key
                ] = sanitize(
                    value[
                        key
                    ],
                    parent_key=key,
                )

            return result

        if isinstance(
            value,
            (list, tuple),
        ):
            return [
                sanitize(
                    item,
                    parent_key=(
                        parent_key
                    ),
                )
                for item in value
            ]

        return value

    return {
        "pathname":
            _text(
                pathname
            ),

        "option_identity_mode":
            AUTO_TWIN_CATALOG_OPTION_IDENTITY_MODE,

        "catalogs":
            sanitize(
                catalogs,
                parent_key="catalogs",
            ),
    }


def build_catalog_runtime_payload(
    *,
    qcc_capture_payload,
    source_capture_id,
    expected_pathname=None,
    required_profile_key=None,
):
    """Construye catálogo runtime sin efectuar escritura."""

    source_capture_id = _text(
        source_capture_id
    )

    if not source_capture_id:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_SOURCE_CAPTURE_REQUIRED"
        )

    result = _main_result(
        qcc_capture_payload
    )

    pathname = _text(
        result.get(
            "pathname"
        )
    )

    expected_pathname = _text(
        expected_pathname
    )

    if (
        expected_pathname
        and pathname
        != expected_pathname
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_PATHNAME_MISMATCH"
        )

    profile_key = _text(
        qcc_capture_payload.get(
            "browser_profile_key"
        )
    )

    required_profile_key = _text(
        required_profile_key
    )

    if (
        required_profile_key
        and profile_key
        != required_profile_key
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_PROFILE_NOT_AUTHORIZED"
        )

    probe = (
        result.get(
            "catalog_probe"
        )
        or {}
    )

    if not isinstance(
        probe,
        dict,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_PROBE_INVALID"
        )

    raw_catalogs = (
        probe.get(
            "elements"
        )
        or []
    )

    if not isinstance(
        raw_catalogs,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_ELEMENTS_INVALID"
        )

    sanitized = []

    for raw_catalog in raw_catalogs:
        catalog = (
            _sanitize_catalog(
                raw_catalog
            )
        )

        if catalog is not None:
            sanitized.append(
                catalog
            )

    normalized = list(
        normalize_catalogs(
            sanitized
        )
    )

    option_count = sum(
        len(
            catalog.get(
                "options"
            )
            or []
        )
        for catalog in normalized
    )

    identity_payload = (
        _catalog_knowledge_projection(
            pathname=pathname,
            catalogs=normalized,
        )
    )

    return {
        "schema_version":
            AUTO_TWIN_CATALOG_RUNTIME_SCHEMA_VERSION,

        "record_type":
            AUTO_TWIN_CATALOG_RUNTIME_TYPE,

        "source_capture_id":
            source_capture_id,

        "source_profile_key":
            profile_key,

        "pathname":
            pathname,

        "option_identity_mode":
            AUTO_TWIN_CATALOG_OPTION_IDENTITY_MODE,

        "catalog_count":
            len(
                normalized
            ),

        "option_count":
            option_count,

        "catalog_fingerprint":
            _sha256_json(
                identity_payload
            ),

        "catalogs":
            normalized,
    }


def materialize_catalog_runtime_artifact(
    *,
    qcc_capture_path,
    runtime_dir,
    source_capture_id,
    expected_pathname=None,
    required_profile_key=None,
):
    """Escribe runtime/catalogs.json desde un capture explícito."""

    qcc_capture_path = Path(
        qcc_capture_path
    )

    runtime_dir = Path(
        runtime_dir
    )

    if not qcc_capture_path.is_file():
        raise FileNotFoundError(
            "QCC_AUTO_TWIN_CATALOG_CAPTURE_NOT_FOUND:"
            + str(
                qcc_capture_path
            )
        )

    try:
        payload = json.loads(
            qcc_capture_path.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_CAPTURE_JSON_INVALID"
        ) from exc

    artifact = build_catalog_runtime_payload(
        qcc_capture_payload=payload,
        source_capture_id=(
            source_capture_id
        ),
        expected_pathname=(
            expected_pathname
        ),
        required_profile_key=(
            required_profile_key
        ),
    )

    runtime_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = (
        runtime_dir
        / "catalogs.json"
    )

    target.write_text(
        json.dumps(
            artifact,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    return {
        "path":
            target,

        "payload":
            artifact,
    }
