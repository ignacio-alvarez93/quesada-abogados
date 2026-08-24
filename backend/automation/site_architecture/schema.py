"""Contrato versionado de QCC Site Architecture."""

from __future__ import annotations


SITE_ARCHITECTURE_SCHEMA_VERSION = 1

SITE_ARCHITECTURE_SOURCE_DOM_CAPTURE = (
    "DOM_CAPTURE"
)

SITE_ARCHITECTURE_TOP_LEVEL_KEYS = (
    "schema_version",
    "source",
    "captured_at",
    "page",
    "viewport",
    "documents",
    "elements",
    "frames",
    "shadow_roots",
    "catalogs",
    "catalog_relations",
    "counts",
    "diagnostics",
)


def require_supported_schema_version(
    value,
):
    version = int(value)

    if (
        version
        != SITE_ARCHITECTURE_SCHEMA_VERSION
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_SCHEMA_VERSION_UNSUPPORTED"
        )

    return version
