from pathlib import Path

import pytest

from backend.automation.site_architecture.state_recognizer_registry import (
    SiteStateRecognizerRegistration,
    SiteStateRecognizerRegistry,
)


def _recognizer(
    _snapshot,
):
    return "SITE_HOME"


def test_registry_resolves_recognizer_by_origin():
    registry = (
        SiteStateRecognizerRegistry()
    )

    registration = (
        SiteStateRecognizerRegistration(
            site_code="EXAMPLE",
            origins=(
                "https://example.test",
            ),
            recognizer=_recognizer,
        )
    )

    registry.register(
        registration
    )

    resolved = (
        registry.resolve_url(
            "https://example.test/path?q=1"
        )
    )

    assert resolved is not None

    assert (
        resolved.site_code
        == "EXAMPLE"
    )

    assert (
        resolved.recognizer(
            {}
        )
        == "SITE_HOME"
    )


def test_registry_supports_multiple_origins_for_same_site():
    registry = (
        SiteStateRecognizerRegistry()
    )

    registry.register(
        SiteStateRecognizerRegistration(
            site_code="EXAMPLE",
            origins=(
                "https://example.test",
                "http://127.0.0.1:9999",
            ),
            recognizer=_recognizer,
        )
    )

    assert (
        registry.resolve_url(
            "https://example.test/a"
        ).site_code
        == "EXAMPLE"
    )

    assert (
        registry.resolve_url(
            "http://127.0.0.1:9999/a"
        ).site_code
        == "EXAMPLE"
    )


def test_unknown_origin_is_unrecognized():
    registry = (
        SiteStateRecognizerRegistry()
    )

    assert (
        registry.resolve_url(
            "https://unknown.test/"
        )
        is None
    )


def test_registry_resolves_dict_snapshot():
    registry = (
        SiteStateRecognizerRegistry()
    )

    registry.register(
        SiteStateRecognizerRegistration(
            site_code="EXAMPLE",
            origins=(
                "https://example.test",
            ),
            recognizer=_recognizer,
        )
    )

    snapshot = {
        "page": {
            "url":
                "https://example.test/profile",
        },
    }

    assert (
        registry.resolve_snapshot(
            snapshot
        ).site_code
        == "EXAMPLE"
    )


def test_duplicate_site_code_is_rejected():
    registry = (
        SiteStateRecognizerRegistry()
    )

    registration = (
        SiteStateRecognizerRegistration(
            site_code="EXAMPLE",
            origins=(
                "https://example.test",
            ),
            recognizer=_recognizer,
        )
    )

    registry.register(
        registration
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_STATE_RECOGNIZER_SITE_ALREADY_REGISTERED"
        ),
    ):
        registry.register(
            registration
        )


def test_duplicate_origin_is_rejected():
    registry = (
        SiteStateRecognizerRegistry()
    )

    registry.register(
        SiteStateRecognizerRegistration(
            site_code="SITE_A",
            origins=(
                "https://example.test",
            ),
            recognizer=_recognizer,
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_STATE_RECOGNIZER_ORIGIN_ALREADY_REGISTERED"
        ),
    ):
        registry.register(
            SiteStateRecognizerRegistration(
                site_code="SITE_B",
                origins=(
                    "https://example.test",
                ),
                recognizer=_recognizer,
            )
        )


def test_registry_is_site_agnostic():
    source = Path(
        "backend/automation/"
        "site_architecture/"
        "state_recognizer_registry.py"
    ).read_text(
        encoding="utf-8"
    ).upper()

    forbidden = (
        "MERCURIO",
        "INSTAGRAM",
        "YOUTUBE",
        "DEHU",
        "ICP_PLUS",
    )

    for token in forbidden:
        assert token not in source
