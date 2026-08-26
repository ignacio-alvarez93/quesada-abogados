from backend.automation.site_architecture.state_observer import (
    STATE_RECOGNITION_RECOGNIZED,
    observe_site_state,
)
from backend.automation.site_recognizers.default_registry import (
    build_default_site_state_recognizer_registry,
)
from backend.automation.site_recognizers.mercurio import (
    MERCURIO_LAB_LOCALHOST_ORIGIN,
    MERCURIO_SEDE_ORIGIN,
    build_mercurio_state_registration,
    recognize_mercurio_state,
)
from backend.automation.site_policies.mercurio import (
    MERCURIO_LAB_ORIGIN,
    MERCURIO_REAL_ORIGIN,
    MERCURIO_SITE_CODE,
)
from tools.mercurio_lab.core.routes import (
    MERCURIO_INICIO_PATH,
    SEDE_HOME_PATH,
)


def _snapshot(
    *,
    origin,
    pathname,
):
    return {
        "schema_version":
            1,

        "page": {
            "url":
                origin
                + pathname,

            "origin":
                origin,

            "pathname":
                pathname,
        },

        "elements":
            [],

        "actions":
            [],

        "catalogs":
            [],

        "catalog_relations":
            [],
    }


def test_mercurio_registration_has_single_site_identity():
    registration = (
        build_mercurio_state_registration()
    )

    assert (
        registration.site_code
        == MERCURIO_SITE_CODE
    )

    assert set(
        registration.origins
    ) == {
        MERCURIO_REAL_ORIGIN,
        MERCURIO_SEDE_ORIGIN,
        MERCURIO_LAB_ORIGIN,
        MERCURIO_LAB_LOCALHOST_ORIGIN,
    }


def test_registry_resolves_mercurio_real():
    registry = (
        build_default_site_state_recognizer_registry()
    )

    registration = (
        registry.resolve_url(
            MERCURIO_REAL_ORIGIN
            + MERCURIO_INICIO_PATH
        )
    )

    assert registration is not None

    assert (
        registration.site_code
        == MERCURIO_SITE_CODE
    )


def test_registry_resolves_mercurio_sede():
    registry = (
        build_default_site_state_recognizer_registry()
    )

    registration = (
        registry.resolve_url(
            MERCURIO_SEDE_ORIGIN
            + SEDE_HOME_PATH
        )
    )

    assert registration is not None

    assert (
        registration.site_code
        == MERCURIO_SITE_CODE
    )


def test_registry_resolves_mercurio_lab():
    registry = (
        build_default_site_state_recognizer_registry()
    )

    for origin in (
        MERCURIO_LAB_ORIGIN,
        MERCURIO_LAB_LOCALHOST_ORIGIN,
    ):
        registration = (
            registry.resolve_url(
                origin
                + MERCURIO_INICIO_PATH
            )
        )

        assert registration is not None

        assert (
            registration.site_code
            == MERCURIO_SITE_CODE
        )


def test_recognizer_detects_real_mercurio_state():
    state = recognize_mercurio_state(
        _snapshot(
            origin=(
                MERCURIO_REAL_ORIGIN
            ),
            pathname=(
                MERCURIO_INICIO_PATH
            ),
        )
    )

    assert (
        state
        == "MERCURIO_INICIO"
    )


def test_recognizer_detects_same_state_in_lab():
    state = recognize_mercurio_state(
        _snapshot(
            origin=(
                MERCURIO_LAB_ORIGIN
            ),
            pathname=(
                MERCURIO_INICIO_PATH
            ),
        )
    )

    assert (
        state
        == "MERCURIO_INICIO"
    )


def test_recognizer_detects_sede_state():
    state = recognize_mercurio_state(
        _snapshot(
            origin=(
                MERCURIO_SEDE_ORIGIN
            ),
            pathname=(
                SEDE_HOME_PATH
            ),
        )
    )

    assert (
        state
        == "SEDE_HOME"
    )


def test_generic_observer_uses_registered_mercurio_recognizer():
    registry = (
        build_default_site_state_recognizer_registry()
    )

    snapshot = _snapshot(
        origin=(
            MERCURIO_REAL_ORIGIN
        ),
        pathname=(
            MERCURIO_INICIO_PATH
        ),
    )

    registration = (
        registry.resolve_snapshot(
            snapshot
        )
    )

    assert registration is not None

    observation = observe_site_state(
        snapshot,
        recognizer=(
            registration.recognizer
        ),
    )

    assert (
        observation[
            "recognition_status"
        ]
        == STATE_RECOGNITION_RECOGNIZED
    )

    assert (
        observation["recognized"]
        is True
    )

    assert (
        observation["state"]
        == "MERCURIO_INICIO"
    )

    assert (
        len(
            observation[
                "fingerprint"
            ]
        )
        == 64
    )


def test_lab_and_real_share_same_semantic_state():
    real = observe_site_state(
        _snapshot(
            origin=(
                MERCURIO_REAL_ORIGIN
            ),
            pathname=(
                MERCURIO_INICIO_PATH
            ),
        ),
        recognizer=(
            recognize_mercurio_state
        ),
    )

    lab = observe_site_state(
        _snapshot(
            origin=(
                MERCURIO_LAB_ORIGIN
            ),
            pathname=(
                MERCURIO_INICIO_PATH
            ),
        ),
        recognizer=(
            recognize_mercurio_state
        ),
    )

    assert (
        real["state"]
        == lab["state"]
        == "MERCURIO_INICIO"
    )


def test_recognizer_does_not_govern_actions():
    from pathlib import Path

    source = Path(
        "backend/automation/"
        "site_recognizers/"
        "mercurio.py"
    ).read_text(
        encoding="utf-8"
    )

    forbidden = (
        "govern_navigation_plan",
        "evaluate_site_interaction",
        "AUTOMATION_ALLOWED",
        "HUMAN_ONLY",
        "click(",
        "click_js",
    )

    for token in forbidden:
        assert token not in source
