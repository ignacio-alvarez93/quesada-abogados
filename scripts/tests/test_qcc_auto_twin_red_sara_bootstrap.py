from pathlib import Path

from backend.services.twin_discovery_runtime_service import (
    DISCOVERY_TARGETS,
    RED_SARA_DISCOVERY_URL,
)

from backend.services.twin_management_service import (
    TWIN_CATALOG,
)


def test_red_sara_is_discovery_target():
    assert (
        RED_SARA_DISCOVERY_URL
        == "https://reg.redsara.es/es/"
    )

    target = DISCOVERY_TARGETS[
        "red_sara"
    ]

    assert (
        target[
            "site_code"
        ]
        == "RED_SARA"
    )

    assert (
        target[
            "profile_key"
        ]
        == "twin_discovery"
    )


def test_red_sara_is_enabled_in_crm():
    item = next(
        item
        for item in TWIN_CATALOG
        if item[
            "twin_key"
        ]
        == "red_sara"
    )

    assert (
        item[
            "enabled"
        ]
        is True
    )


def test_discovery_runtime_enforces_single_profile_owner():
    source = Path(
        "backend/services/"
        "twin_discovery_runtime_service.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_AUTO_TWIN_DISCOVERY_PROFILE_BUSY"
        in source
    )
