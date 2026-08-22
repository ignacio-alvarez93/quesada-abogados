from backend.automation.site_architecture.selectors import (
    build_selector_occurrence_index,
    resolve_selector_profile,
)


def _element(
    *,
    element_id="",
    name="",
    frame_path="main",
):
    return {
        "tag": "input",
        "id": element_id,
        "name": name,
        "type": "text",
        "role": "",
        "attributes": {},
        "frame_path": frame_path,
    }


def test_indexed_resolution_matches_legacy_resolution():
    elements = [
        _element(
            element_id="first",
            name="shared",
        ),
        _element(
            element_id="second",
            name="shared",
        ),
        _element(
            element_id="third",
            name="unique",
        ),
    ]

    index = (
        build_selector_occurrence_index(
            elements
        )
    )

    for element in elements:
        legacy = resolve_selector_profile(
            element,
            elements,
        )

        indexed = resolve_selector_profile(
            element,
            elements,
            occurrence_index=index,
        )

        assert (
            indexed.to_dict()
            == legacy.to_dict()
        )


def test_selector_uniqueness_is_scoped_by_frame():
    elements = [
        _element(
            element_id="same",
            frame_path="main",
        ),
        _element(
            element_id="same",
            frame_path="qcc-frame:7",
        ),
    ]

    index = (
        build_selector_occurrence_index(
            elements
        )
    )

    for element in elements:
        profile = resolve_selector_profile(
            element,
            elements,
            occurrence_index=index,
        )

        assert profile.primary is not None
        assert profile.primary.unique is True
        assert (
            profile.primary.selector
            == "#same"
        )


def test_duplicate_selector_in_same_frame_is_not_unique():
    elements = [
        _element(
            name="duplicated",
        ),
        _element(
            name="duplicated",
        ),
    ]

    index = (
        build_selector_occurrence_index(
            elements
        )
    )

    profile = resolve_selector_profile(
        elements[0],
        elements,
        occurrence_index=index,
    )

    name_candidates = [
        item
        for item in profile.candidates
        if (
            item.selector
            == '[name="duplicated"]'
        )
    ]

    assert name_candidates
    assert (
        name_candidates[0].unique
        is False
    )
