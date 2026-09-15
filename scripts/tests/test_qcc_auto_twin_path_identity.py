from backend.qcc.auto_twin.automatic_materialization import (
    _identity,
    _renderer_refresh_capture_for_identity,
)


def test_identity_strips_volatile_jsessionid():
    first = _identity(
        (
            "/mercurio/modoAcceso.html;"
            "jsessionid=SESSION_A.node01"
        ),
        None,
    )

    second = _identity(
        (
            "/mercurio/modoAcceso.html;"
            "jsessionid=SESSION_B.node99"
        ),
        None,
    )

    canonical = _identity(
        "/mercurio/modoAcceso.html",
        None,
    )

    assert first == canonical
    assert second == canonical

    assert canonical == (
        "/mercurio/modoAcceso.html",
        None,
    )


def test_identity_jsessionid_is_case_insensitive():
    assert _identity(
        "/mercurio/modoAcceso.html;JSESSIONID=ABC.node",
        None,
    ) == (
        "/mercurio/modoAcceso.html",
        None,
    )


def test_identity_preserves_other_path_parameters():
    assert _identity(
        "/example;language=es",
        None,
    ) == (
        "/example;language=es",
        None,
    )


def test_identity_preserves_functional_state():
    assert _identity(
        (
            "/mercurio/modoAcceso.html;"
            "jsessionid=ABC.node"
        ),
        "MERCURIO_MODO_ACCESO",
    ) == (
        "/mercurio/modoAcceso.html",
        "MERCURIO_MODO_ACCESO",
    )


def test_renderer_refresh_matches_same_state_across_jsessionid():
    previous_identity = _identity(
        (
            "/mercurio/modoAcceso.html;"
            "jsessionid=OLD_SESSION.node01"
        ),
        None,
    )

    observed_states = {
        "fresh": {
            "pathname":
                (
                    "/mercurio/modoAcceso.html;"
                    "jsessionid=NEW_SESSION.node02"
                ),

            "functional_state":
                None,

            "last_capture_id":
                "cap-fresh",
        },
    }

    result = (
        _renderer_refresh_capture_for_identity(
            renderer_refresh=True,
            observed_states=observed_states,
            identity=previous_identity,
            trigger_capture_id="cap-fresh",
        )
    )

    assert result == "cap-fresh"


def test_renderer_refresh_still_requires_exact_functional_state():
    previous_identity = _identity(
        (
            "/mercurio/modoAcceso.html;"
            "jsessionid=OLD_SESSION.node01"
        ),
        None,
    )

    observed_states = {
        "fresh": {
            "pathname":
                (
                    "/mercurio/modoAcceso.html;"
                    "jsessionid=NEW_SESSION.node02"
                ),

            "functional_state":
                "DIFFERENT_FUNCTIONAL_STATE",

            "last_capture_id":
                "cap-fresh",
        },
    }

    result = (
        _renderer_refresh_capture_for_identity(
            renderer_refresh=True,
            observed_states=observed_states,
            identity=previous_identity,
            trigger_capture_id="cap-fresh",
        )
    )

    assert result is None
