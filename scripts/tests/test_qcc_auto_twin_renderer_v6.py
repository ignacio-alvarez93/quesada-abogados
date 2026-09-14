from pathlib import Path


from backend.qcc.auto_twin.materialization_builder import (
    AUTO_TWIN_RUNTIME_RENDERER_VERSION,
)

from backend.qcc.auto_twin.runtime_network_sterilization import (
    AUTO_TWIN_NETWORK_STERILIZER_VERSION,
)


ROOT = Path(__file__).resolve().parents[2]

BUILDER = (
    ROOT
    / "backend"
    / "qcc"
    / "auto_twin"
    / "materialization_builder.py"
)


def test_renderer_v6_is_current():
    assert (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION
        == 6
    )


def test_renderer_v6_has_network_sterilization():
    assert (
        AUTO_TWIN_NETWORK_STERILIZER_VERSION
        == 1
    )

    source = BUILDER.read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_AUTO_TWIN_NETWORK_STERILIZATION"
        in source
    )

    assert (
        "network_sterilization.json"
        in source
    )

    assert (
        '"network_sterilization_mode"'
        in source
    )
