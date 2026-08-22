"""Serialización del snapshot canónico de Site Architecture."""

from __future__ import annotations

import json
from pathlib import Path

from .models import (
    SiteArchitectureSnapshot,
)
from .schema import (
    SITE_ARCHITECTURE_TOP_LEVEL_KEYS,
    require_supported_schema_version,
)


def build_normalized_snapshot_payload(
    snapshot,
):
    """Construye la representación pública estable del snapshot."""

    if not isinstance(
        snapshot,
        SiteArchitectureSnapshot,
    ):
        raise ValueError(
            "SITE_ARCHITECTURE_SNAPSHOT_INVALID"
        )

    source = snapshot.to_dict()

    require_supported_schema_version(
        source.get("schema_version")
    )

    return {
        key: source.get(key)
        for key
        in SITE_ARCHITECTURE_TOP_LEVEL_KEYS
    }


def write_normalized_snapshot(
    snapshot,
    output_path,
):
    """Persiste un snapshot normalizado en JSON UTF-8."""

    path = Path(
        output_path
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = (
        build_normalized_snapshot_payload(
            snapshot
        )
    )

    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return path
