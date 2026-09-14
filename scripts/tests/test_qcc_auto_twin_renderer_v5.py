from pathlib import Path


from backend.qcc.auto_twin.catalog_runtime_adapter import (
    AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_VERSION,
    catalog_runtime_adapter_source,
)

from backend.qcc.auto_twin.materialization_builder import (
    AUTO_TWIN_RUNTIME_RENDERER_V5_VERSION,
)


ROOT = Path(__file__).resolve().parents[2]

BUILDER = (
    ROOT
    / "backend"
    / "qcc"
    / "auto_twin"
    / "materialization_builder.py"
)


def test_renderer_v5_is_current():
    assert (
        AUTO_TWIN_RUNTIME_RENDERER_V5_VERSION
        == 5
    )


def test_renderer_v5_uses_catalog_adapter_v2():
    assert (
        AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_VERSION
        == 2
    )


def test_adapter_v2_has_generic_runtime_option_fallback():
    source = (
        catalog_runtime_adapter_source()
    )

    assert (
        "ensureFallbackPopup"
        in source
    )

    assert (
        "fallbackOptionNodes"
        in source
    )

    assert (
        "data-qcc-auto-twin-catalog-popup"
        in source
    )

    assert (
        "capturedOptions.length"
        in source
    )


def test_fallback_remains_provider_neutral():
    source = (
        catalog_runtime_adapter_source()
        .lower()
    )

    for forbidden in (
        "red_sara",
        "redsara",
        "mercurio",
        "dnt-select",
        "#country",
        "#tipodoc",
    ):
        assert (
            forbidden
            not in source
        )


def test_builder_records_current_adapter_version():
    source = BUILDER.read_text(
        encoding="utf-8"
    )

    assert (
        '"catalog_runtime_adapter_version"'
        in source
    )

    assert (
        "AUTO_TWIN_CATALOG_RUNTIME_ADAPTER_VERSION"
        in source
    )
