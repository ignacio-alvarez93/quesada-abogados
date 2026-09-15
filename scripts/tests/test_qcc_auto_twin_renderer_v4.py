from pathlib import Path


from backend.qcc.auto_twin.materialization_builder import (
    AUTO_TWIN_RUNTIME_RENDERER_V4_VERSION,
)

from backend.qcc.auto_twin.catalog_runtime_adapter import (
    AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_V1_VERSION,
)


ROOT = Path(__file__).resolve().parents[2]

BUILDER = (
    ROOT
    / "backend"
    / "qcc"
    / "auto_twin"
    / "materialization_builder.py"
)


def test_renderer_v4_is_explicit():
    assert (
        AUTO_TWIN_RUNTIME_RENDERER_V4_VERSION
        == 4
    )


def test_renderer_v4_contains_static_catalog_runtime_capability():
    source = BUILDER.read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_AUTO_TWIN_STATIC_CATALOG_RUNTIME_ADAPTER"
        in source
    )

    assert (
        '"catalog_runtime_adapter_version"'
        in source
    )

    assert (
        '"catalog_runtime_adapter_mode"'
        in source
    )


def test_renderer_v4_uses_catalog_adapter_v1():
    assert (
        AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_V1_VERSION
        == 1
    )
