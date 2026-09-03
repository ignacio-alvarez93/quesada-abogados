from backend.automation.site_architecture.state_recognizer_registry import (
    SiteStateRecognizerRegistration,
    SiteStateRecognizerRegistry,
)
from backend.automation.site_recognizers.default_registry import (
    build_default_site_state_recognizer_registry,
)
from backend.automation.site_recognizers.mercurio import (
    resolve_mercurio_architecture_scope,
)


def _snapshot(
    url,
):
    return {
        "page": {
            "url":
                url,
        },
        "documents": [],
        "elements": [],
    }


def test_generic_registry_scope_is_optional():
    registry = (
        SiteStateRecognizerRegistry()
    )

    registry.register(
        SiteStateRecognizerRegistration(
            site_code="EXAMPLE",
            origins=(
                "https://example.com",
            ),
            recognizer=(
                lambda snapshot:
                    "PAGE"
            ),
        )
    )

    assert (
        registry.resolve_architecture_scope(
            _snapshot(
                "https://example.com/a"
            ),
            {
                "state": "PAGE",
            },
        )
        is None
    )


def test_generic_registry_can_resolve_scope():
    registry = (
        SiteStateRecognizerRegistry()
    )

    registry.register(
        SiteStateRecognizerRegistration(
            site_code="EXAMPLE",
            origins=(
                "https://example.com",
            ),
            recognizer=(
                lambda snapshot:
                    "PAGE"
            ),
        )
    )

    registry.register_retention_scope_resolver(
        site_code="EXAMPLE",
        resolver=(
            lambda snapshot, observation:
                "FORM_GENERIC"
        ),
    )

    assert (
        registry.resolve_architecture_scope(
            _snapshot(
                "https://example.com/a"
            ),
            {
                "state": "PAGE",
            },
        )
        == "FORM_GENERIC"
    )


def test_mercurio_ex01_projects_form_scope():
    assert (
        resolve_mercurio_architecture_scope(
            _snapshot(
                "http://localhost:8767/"
                "mercurio/"
                "nuevaSolicitud-EX01.html"
            ),
            {
                "state":
                    "EX01_PERSONAL",
            },
        )
        == "FORM_EX01"
    )


def test_mercurio_ex26_projects_independent_scope():
    assert (
        resolve_mercurio_architecture_scope(
            _snapshot(
                "http://localhost:8767/"
                "mercurio/"
                "nuevaSolicitud-EX26.html"
            ),
            {
                "state":
                    None,
            },
        )
        == "FORM_EX26"
    )


def test_internal_ex01_states_share_same_scope():
    snapshot = _snapshot(
        "http://localhost:8767/"
        "mercurio/"
        "nuevaSolicitud-EX01.html"
    )

    scopes = {
        resolve_mercurio_architecture_scope(
            snapshot,
            {
                "state": state,
            },
        )
        for state in (
            "EX01_AUTHORIZATION",
            "EX01_PERSONAL",
            "EX01_PRESENTER",
            "EX01_NOTIFICATION",
        )
    }

    assert scopes == {
        "FORM_EX01"
    }


def test_mercurio_common_surface_is_global():
    assert (
        resolve_mercurio_architecture_scope(
            _snapshot(
                "http://localhost:8767/"
                "mercurio/index.html"
            ),
            {
                "state":
                    "MODEL_SELECTION",
            },
        )
        == "MERCURIO_GLOBAL"
    )


def test_default_registry_installs_mercurio_scope():
    registry = (
        build_default_site_state_recognizer_registry()
    )

    assert (
        registry.resolve_architecture_scope(
            _snapshot(
                "http://localhost:8767/"
                "mercurio/"
                "nuevaSolicitud-EX01.html"
            ),
            {
                "state":
                    "EX01_AUTHORIZATION",
            },
        )
        == "FORM_EX01"
    )
