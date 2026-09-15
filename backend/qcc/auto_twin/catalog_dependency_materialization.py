"""Materialización determinista de conocimiento causal catalogal AUTO TWIN.

Recibe exclusivamente evidencias CatalogDependency ya gobernadas
y construye:

    runtime/catalog_dependencies.json

No:
- consulta stores;
- ejecuta navegador;
- modifica MaterializedRevision existente;
- modifica lifecycle;
- contiene lógica de proveedor.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .catalog_dependency_probe import (
    AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE,
    AUTO_TWIN_CATALOG_DEPENDENCY_SCHEMA_VERSION,
    AUTO_TWIN_CATALOG_DEPENDENCY_TYPE,
)


AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_SCHEMA_VERSION = 1

AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_TYPE = (
    "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME"
)

AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_FILENAME = (
    "catalog_dependencies.json"
)


_SHA256_RE = re.compile(
    r"^[0-9a-f]{64}$"
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


def _required_text(
    value,
    *,
    error,
) -> str:
    result = _text(
        value
    )

    if not result:
        raise ValueError(
            error
        )

    return result


def _normalize_options(
    value,
):
    if not isinstance(
        value,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_OPTIONS_INVALID"
        )

    result = []

    for option in value:
        if not isinstance(
            option,
            dict,
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_OPTION_INVALID"
            )

        raw_value = _text(
            option.get(
                "value"
            )
        )

        label = _text(
            option.get(
                "label"
            )
        )

        if (
            not raw_value
            and not label
        ):
            raise ValueError(
                "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_OPTION_IDENTITY_INVALID"
            )

        result.append({
            "value":
                raw_value,

            "label":
                label,

            "disabled":
                bool(
                    option.get(
                        "disabled"
                    )
                ),
        })

    return result


def _normalize_dependency(
    value,
    *,
    twin_key,
    pathname,
):
    if not isinstance(
        value,
        dict,
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_RECORD_INVALID"
        )

    if (
        value.get(
            "schema_version"
        )
        != AUTO_TWIN_CATALOG_DEPENDENCY_SCHEMA_VERSION
        or value.get(
            "record_type"
        )
        != AUTO_TWIN_CATALOG_DEPENDENCY_TYPE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_RECORD_SCHEMA_INVALID"
        )

    if (
        value.get(
            "option_identity_mode"
        )
        != AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_IDENTITY_MODE_INVALID"
        )

    if (
        _text(
            value.get(
                "twin_key"
            )
        )
        != twin_key
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_TWIN_MISMATCH"
        )

    if (
        _text(
            value.get(
                "pathname"
            )
        )
        != pathname
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_PATHNAME_MISMATCH"
        )

    route = _required_text(
        value.get(
            "route"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_ROUTE_REQUIRED"
        ),
    )

    source = value.get(
        "source"
    )

    trigger = value.get(
        "trigger"
    )

    target = value.get(
        "target"
    )

    if (
        not isinstance(
            source,
            dict,
        )
        or not isinstance(
            trigger,
            dict,
        )
        or not isinstance(
            target,
            dict,
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_ENDPOINTS_INVALID"
        )

    source_key = _required_text(
        source.get(
            "catalog_key"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_SOURCE_KEY_REQUIRED"
        ),
    )

    source_selector = _required_text(
        source.get(
            "selector"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_SOURCE_SELECTOR_REQUIRED"
        ),
    )

    target_key = _required_text(
        target.get(
            "catalog_key"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_TARGET_KEY_REQUIRED"
        ),
    )

    target_selector = _required_text(
        target.get(
            "selector"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_TARGET_SELECTOR_REQUIRED"
        ),
    )

    if (
        source_key == target_key
        or source_selector
        == target_selector
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_ENDPOINTS_SAME"
        )

    trigger_value = _text(
        trigger.get(
            "value"
        )
    )

    trigger_label = _text(
        trigger.get(
            "label"
        )
    )

    if (
        not trigger_value
        and not trigger_label
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_TRIGGER_REQUIRED"
        )

    options = _normalize_options(
        target.get(
            "options"
        )
    )

    try:
        options_count = int(
            target.get(
                "options_count"
            )
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_OPTION_COUNT_INVALID"
        ) from exc

    if (
        options_count
        != len(
            options
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_OPTION_COUNT_MISMATCH"
        )

    fingerprint = _required_text(
        value.get(
            "dependency_fingerprint"
        ),
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_FINGERPRINT_REQUIRED"
        ),
    )

    if not _SHA256_RE.fullmatch(
        fingerprint
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_FINGERPRINT_INVALID"
        )

    identity = {
        "option_identity_mode":
            AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE,

        "twin_key":
            twin_key,

        "route":
            route,

        "source": {
            "catalog_key":
                source_key,

            "selector":
                source_selector,
        },

        "trigger": {
            "value":
                trigger_value,

            "label":
                trigger_label,
        },

        "target": {
            "catalog_key":
                target_key,

            "selector":
                target_selector,

            "options":
                options,
        },
    }

    if (
        _sha256_json(
            identity
        )
        != fingerprint
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_FINGERPRINT_MISMATCH"
        )

    relations = value.get(
        "causal_relations"
    )

    if not isinstance(
        relations,
        list,
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_RELATIONS_INVALID"
        )

    signatures = {
        (
            _text(
                relation.get(
                    "relation"
                )
            ),
            _text(
                relation.get(
                    "source"
                )
            ),
            _text(
                relation.get(
                    "target"
                )
            ),
        )
        for relation
        in relations
        if isinstance(
            relation,
            dict,
        )
    }

    if signatures != {
        (
            "INFLUENCES",
            source_key,
            target_key,
        ),
        (
            "DEPENDS_ON",
            target_key,
            source_key,
        ),
    }:
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_RELATIONS_INVALID"
        )

    if (
        value.get(
            "restoration_exact"
        )
        is not True
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_RESTORATION_REQUIRED"
        )

    return {
        "dependency_fingerprint":
            fingerprint,

        "route":
            route,

        "source": {
            "catalog_key":
                source_key,

            "selector":
                source_selector,
        },

        "trigger": {
            "value":
                trigger_value,

            "label":
                trigger_label,
        },

        "target": {
            "catalog_key":
                target_key,

            "selector":
                target_selector,

            "options_count":
                len(
                    options
                ),

            "options":
                options,
        },

        "causal_relations":
            deepcopy(
                relations
            ),

        "restoration_exact":
            True,

        "provenance":
            deepcopy(
                value.get(
                    "provenance"
                )
                or {}
            ),
    }


def build_catalog_dependency_runtime_payload(
    *,
    twin_key,
    pathname,
    dependencies,
):
    twin_key = _required_text(
        twin_key,
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_TWIN_REQUIRED"
        ),
    )

    pathname = _required_text(
        pathname,
        error=(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_PATHNAME_REQUIRED"
        ),
    )

    if not pathname.startswith(
        "/"
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_PATHNAME_INVALID"
        )

    if not isinstance(
        dependencies,
        (list, tuple),
    ):
        raise TypeError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_DEPENDENCIES_INVALID"
        )

    normalized = [
        _normalize_dependency(
            dependency,
            twin_key=twin_key,
            pathname=pathname,
        )
        for dependency
        in dependencies
    ]

    normalized.sort(
        key=lambda item: (
            item[
                "dependency_fingerprint"
            ]
        )
    )

    fingerprints = [
        item[
            "dependency_fingerprint"
        ]
        for item
        in normalized
    ]

    if (
        len(
            fingerprints
        )
        != len(
            set(
                fingerprints
            )
        )
    ):
        raise ValueError(
            "QCC_AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_DUPLICATE"
        )

    knowledge_identity = {
        "option_identity_mode":
            AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE,

        "twin_key":
            twin_key,

        "pathname":
            pathname,

        "dependency_fingerprints":
            fingerprints,
    }

    return {
        "schema_version":
            AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_SCHEMA_VERSION,

        "record_type":
            AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_TYPE,

        "option_identity_mode":
            AUTO_TWIN_CATALOG_DEPENDENCY_OPTION_IDENTITY_MODE,

        "twin_key":
            twin_key,

        "pathname":
            pathname,

        "dependency_count":
            len(
                normalized
            ),

        "dependency_fingerprints":
            fingerprints,

        "catalog_dependency_fingerprint":
            _sha256_json(
                knowledge_identity
            ),

        "dependencies":
            normalized,
    }


def materialize_catalog_dependency_runtime_artifact(
    *,
    runtime_dir,
    twin_key,
    pathname,
    dependencies,
):
    artifact = (
        build_catalog_dependency_runtime_payload(
            twin_key=twin_key,
            pathname=pathname,
            dependencies=dependencies,
        )
    )

    runtime_dir = Path(
        runtime_dir
    )

    runtime_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = (
        runtime_dir
        / AUTO_TWIN_CATALOG_DEPENDENCY_RUNTIME_FILENAME
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
    )

    return {
        "path":
            target,

        "payload":
            artifact,
    }
