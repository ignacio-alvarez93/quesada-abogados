from enum import StrEnum
from pathlib import Path

import pytest

from backend.automation.site_architecture.state_observer import (
    SITE_STATE_OBSERVATION_SCHEMA_VERSION,
    SITE_STATE_OBSERVATION_TYPE,
    STATE_RECOGNITION_ERROR,
    STATE_RECOGNITION_RECOGNIZED,
    STATE_RECOGNITION_UNRECOGNIZED,
    observe_site_state,
)


def _snapshot(
    *,
    pathname="/start",
):
    return {
        "schema_version":
            1,

        "page": {
            "origin":
                "https://example.test",

            "pathname":
                pathname,
        },

        "actions":
            [],

        "catalogs":
            [],

        "catalog_relations":
            [],
    }


class ExampleState(
    StrEnum,
):
    HOME = "SITE_HOME"


def test_observer_always_builds_functional_fingerprint():
    result = observe_site_state(
        _snapshot()
    )

    assert (
        result["schema_version"]
        == SITE_STATE_OBSERVATION_SCHEMA_VERSION
    )

    assert (
        result["observation_type"]
        == SITE_STATE_OBSERVATION_TYPE
    )

    assert (
        result["recognition_status"]
        == STATE_RECOGNITION_UNRECOGNIZED
    )

    assert result["recognized"] is False
    assert result["state"] is None

    fingerprint = result[
        "fingerprint"
    ]

    assert isinstance(
        fingerprint,
        str,
    )

    assert len(
        fingerprint
    ) == 64


def test_observer_supports_string_recognizer():
    result = observe_site_state(
        _snapshot(),
        recognizer=(
            lambda _snapshot:
                "site_profile"
        ),
    )

    assert (
        result["recognition_status"]
        == STATE_RECOGNITION_RECOGNIZED
    )

    assert result["recognized"] is True

    assert (
        result["state"]
        == "SITE_PROFILE"
    )


def test_observer_supports_enum_recognizer():
    result = observe_site_state(
        _snapshot(),
        recognizer=(
            lambda _snapshot:
                ExampleState.HOME
        ),
    )

    assert result["recognized"] is True

    assert (
        result["state"]
        == "SITE_HOME"
    )


def test_observer_allows_unrecognized_site_state():
    result = observe_site_state(
        _snapshot(),
        recognizer=(
            lambda _snapshot:
                None
        ),
    )

    assert (
        result["recognition_status"]
        == STATE_RECOGNITION_UNRECOGNIZED
    )

    assert result["recognized"] is False
    assert result["state"] is None


def test_recognizer_failure_is_fail_open():
    def broken(
        _snapshot,
    ):
        raise RuntimeError(
            "provider-specific internal failure"
        )

    result = observe_site_state(
        _snapshot(),
        recognizer=broken,
    )

    assert (
        result["recognition_status"]
        == STATE_RECOGNITION_ERROR
    )

    assert result["recognized"] is False
    assert result["state"] is None

    assert len(
        result["fingerprint"]
    ) == 64


def test_invalid_recognizer_type_is_rejected():
    with pytest.raises(
        TypeError,
        match=(
            "QCC_SITE_STATE_RECOGNIZER_INVALID"
        ),
    ):
        observe_site_state(
            _snapshot(),
            recognizer=object(),
        )


def test_invalid_semantic_state_is_contained():
    result = observe_site_state(
        _snapshot(),
        recognizer=(
            lambda _snapshot:
                "nombre de cliente 123"
        ),
    )

    assert (
        result["recognition_status"]
        == STATE_RECOGNITION_ERROR
    )

    assert result["state"] is None

    assert (
        result["recognized"]
        is False
    )


def test_different_functional_paths_have_different_fingerprints():
    first = observe_site_state(
        _snapshot(
            pathname="/start",
        )
    )

    second = observe_site_state(
        _snapshot(
            pathname="/other",
        )
    )

    assert (
        first["fingerprint"]
        != second["fingerprint"]
    )


def test_observation_payload_has_no_raw_dom_fields():
    result = observe_site_state(
        _snapshot(),
        recognizer=(
            lambda _snapshot:
                "SITE_HOME"
        ),
    )

    assert set(
        result
    ) == {
        "schema_version",
        "observation_type",
        "recognition_status",
        "recognized",
        "state",
        "fingerprint",
    }


def test_generic_observer_has_no_site_coupling():
    source = Path(
        "backend/automation/"
        "site_architecture/"
        "state_observer.py"
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
