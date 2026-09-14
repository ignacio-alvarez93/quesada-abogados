from backend.qcc.auto_twin.materialization_builder import (
    _canonical_carry_forward_pathname,
)


def test_builder_strips_jsessionid_from_path_identity():
    left = (
        "/mercurio/modoAcceso.html;"
        "jsessionid=AAA.mercurion_poolB1_101"
    )

    right = (
        "/mercurio/modoAcceso.html;"
        "jsessionid=BBB.mercurion_poolB1_102"
    )

    assert (
        _canonical_carry_forward_pathname(
            left
        )
        == "/mercurio/modoAcceso.html"
    )

    assert (
        _canonical_carry_forward_pathname(
            left
        )
        == _canonical_carry_forward_pathname(
            right
        )
    )


def test_builder_jsessionid_is_case_insensitive():
    assert (
        _canonical_carry_forward_pathname(
            "/x/a.html;JSESSIONID=ABC"
        )
        == "/x/a.html"
    )


def test_builder_preserves_other_path_parameters():
    assert (
        _canonical_carry_forward_pathname(
            "/x/a.html;foo=1;jsessionid=ABC;bar=2"
        )
        == "/x/a.html;foo=1;bar=2"
    )


def test_builder_does_not_merge_distinct_paths():
    assert (
        _canonical_carry_forward_pathname(
            "/mercurio/modoAcceso.html"
        )
        != _canonical_carry_forward_pathname(
            "/mercurio/entradaMercurio.html"
        )
    )
