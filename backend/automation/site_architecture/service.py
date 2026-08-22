"""Orquestación de captura y persistencia Site Architecture."""

from __future__ import annotations

from pathlib import Path

from backend.automation.dom_inspector import (
    capture_dom_snapshot,
)

from .normalizer import (
    normalize_dom_capture,
)
from .snapshot import (
    write_normalized_snapshot,
)


DEFAULT_SITE_ARCHITECTURE_FILENAME = (
    "site_architecture.json"
)


def persist_site_architecture_from_raw(
    raw_payload,
    output_dir,
    *,
    filename=DEFAULT_SITE_ARCHITECTURE_FILENAME,
):
    """Normaliza un DOM_CAPTURE RAW y persiste su contrato."""

    snapshot = normalize_dom_capture(
        raw_payload
    )

    path = (
        Path(output_dir)
        / filename
    )

    write_normalized_snapshot(
        snapshot,
        path,
    )

    return {
        "snapshot":
            snapshot,
        "snapshot_path":
            path,
    }


def capture_site_architecture(
    browser,
    output_root,
    *,
    label="site_architecture",
    timestamp=None,
):
    """Captura una vez y genera RAW + contrato normalizado."""

    capture = capture_dom_snapshot(
        browser,
        output_root,
        label=label,
        timestamp=timestamp,
        include_payload=True,
    )

    raw_payload = capture.pop(
        "raw_payload",
        None,
    )

    if not isinstance(
        raw_payload,
        dict,
    ):
        raise RuntimeError(
            "SITE_ARCHITECTURE_RAW_CAPTURE_MISSING"
        )

    normalized = (
        persist_site_architecture_from_raw(
            raw_payload,
            capture["capture_dir"],
        )
    )

    return {
        **capture,
        **normalized,
    }
