from backend.automation.site_architecture import (
    diff_site_architecture,
)


def _element(
    selector,
    *,
    fallback=None,
    semantics=("BUTTON",),
    rect=None,
):
    candidates = [{
        "strategy": "ID",
        "selector": selector,
        "confidence": "HIGH",
        "unique": True,
    }]

    fallbacks = []

    if fallback:
        candidates.append({
            "strategy": "NAME",
            "selector": fallback,
            "confidence": "HIGH",
            "unique": True,
        })

        fallbacks.append(
            candidates[-1]
        )

    return {
        "frame_path": "main",
        "semantics": semantics,
        "selectors": {
            "frame_path": "main",
            "primary": candidates[0],
            "fallbacks": tuple(
                fallbacks
            ),
            "candidates": tuple(
                candidates
            ),
            "confidence": "HIGH",
        },
        "interaction": {
            "state": "INTERACTABLE",
            "visible": True,
            "in_viewport": True,
            "disabled": False,
            "readonly": False,
            "pointer_events": "auto",
        },
        "geometry": {
            "coordinate_space":
                "TOP_LEVEL_VIEWPORT",
            "frame_path":
                "main",
            "viewport_rect":
                rect,
        },
    }


def _snapshot(elements):
    return {
        "schema_version": 1,
        "elements": tuple(elements),
    }


def test_inserted_element_does_not_shift_existing_identity():
    before = _snapshot([
        _element("#a"),
        _element("#b"),
    ])

    after = _snapshot([
        _element("#new"),
        _element("#a"),
        _element("#b"),
    ])

    result = diff_site_architecture(
        before,
        after,
    )

    assert result["counts"]["ADDED"] == 1
    assert result["counts"]["REMOVED"] == 0
    assert result["counts"]["CHANGED"] == 0
    assert result["counts"]["UNCHANGED"] == 2


def test_stable_fallback_matches_element_when_primary_changes():
    before = _snapshot([
        _element(
            "#old-id",
            fallback='[name="continuar"]',
        ),
    ])

    after = _snapshot([
        _element(
            "#new-id",
            fallback='[name="continuar"]',
        ),
    ])

    result = diff_site_architecture(
        before,
        after,
    )

    assert result["counts"]["CHANGED"] == 1
    assert result["counts"]["ADDED"] == 0
    assert result["counts"]["REMOVED"] == 0

    assert (
        result["elements"][0]["changes"]
        == ("SELECTOR_CHANGED",)
    )


def test_semantic_change_is_classified():
    before = _snapshot([
        _element("#action"),
    ])

    after = _snapshot([
        _element(
            "#action",
            semantics=("LINK",),
        ),
    ])

    result = diff_site_architecture(
        before,
        after,
    )

    assert (
        "SEMANTICS_CHANGED"
        in result["elements"][0]["changes"]
    )


def test_element_without_unique_identity_is_not_guessed():
    before = _snapshot([{
        "frame_path": "main",
        "selectors": {
            "frame_path": "main",
            "primary": None,
            "fallbacks": (),
            "candidates": (),
        },
    }])

    after = _snapshot([])

    result = diff_site_architecture(
        before,
        after,
    )

    assert result["counts"]["REMOVED"] == 0
    assert result["unmatched_before"] == (0,)


def test_small_geometry_shift_is_not_contract_change():
    before = _snapshot([
        _element(
            "#action",
            rect={
                "x": 100,
                "y": 200,
                "width": 100,
                "height": 40,
            },
        ),
    ])

    after = _snapshot([
        _element(
            "#action",
            rect={
                "x": 104,
                "y": 205,
                "width": 100,
                "height": 40,
            },
        ),
    ])

    result = diff_site_architecture(
        before,
        after,
    )

    assert result["counts"]["UNCHANGED"] == 1
    assert result["contract_changed"] is False


def test_large_geometry_shift_is_classified():
    before = _snapshot([
        _element(
            "#action",
            rect={
                "x": 100,
                "y": 200,
                "width": 100,
                "height": 40,
            },
        ),
    ])

    after = _snapshot([
        _element(
            "#action",
            rect={
                "x": 160,
                "y": 260,
                "width": 100,
                "height": 40,
            },
        ),
    ])

    result = diff_site_architecture(
        before,
        after,
    )

    assert result["counts"]["CHANGED"] == 1
    assert (
        "GEOMETRY_CHANGED"
        in result["elements"][0]["changes"]
    )
    assert result["contract_changed"] is True


def test_viewport_only_interaction_change_is_ignored():
    before_element = _element("#action")
    after_element = _element("#action")

    after_element["interaction"] = dict(
        after_element["interaction"],
        state="OFF_VIEWPORT",
        in_viewport=False,
    )

    result = diff_site_architecture(
        _snapshot([before_element]),
        _snapshot([after_element]),
    )

    assert result["counts"]["UNCHANGED"] == 1
    assert result["contract_changed"] is False


def test_page_identity_change_is_reported():
    before = _snapshot([])
    after = _snapshot([])

    before["page"] = {
        "pathname": "/step/1",
    }
    after["page"] = {
        "pathname": "/step/2",
    }

    result = diff_site_architecture(
        before,
        after,
    )

    assert result["page"]["changed"] is True
    assert (
        result["page"]["changes"]
        == ("PAGE_CHANGED",)
    )
    assert result["contract_changed"] is True


def test_unmatched_identity_marks_diff_inconclusive():
    before = _snapshot([{
        "frame_path": "main",
        "selectors": {
            "frame_path": "main",
            "candidates": (),
        },
    }])

    result = diff_site_architecture(
        before,
        _snapshot([]),
    )

    assert result["contract_changed"] is False
    assert result["inconclusive"] is True
