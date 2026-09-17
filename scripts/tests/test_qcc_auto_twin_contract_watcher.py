import pytest

from backend.qcc.auto_twin.contract_watcher import (
    ContractWatchSeverity,
    ContractWatchState,
    build_contract_watcher_evidence,
    compare_site_contract_revision,
    validate_contract_watcher_evidence,
)


def _element(
    selector,
    *,
    fallback=None,
    semantics=("BUTTON",),
    rect=None,
    disabled=False,
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

        fallbacks.append(candidates[-1])

    return {
        "frame_path": "main",
        "semantics": semantics,
        "selectors": {
            "frame_path": "main",
            "primary": candidates[0],
            "fallbacks": tuple(fallbacks),
            "candidates": tuple(candidates),
            "confidence": "HIGH",
        },
        "interaction": {
            "state": "INTERACTABLE",
            "visible": True,
            "in_viewport": True,
            "disabled": disabled,
            "readonly": False,
            "pointer_events": "auto",
        },
        "geometry": {
            "coordinate_space": "TOP_LEVEL_VIEWPORT",
            "frame_path": "main",
            "viewport_rect": rect,
        },
    }


def _catalog(key, *, options):
    return {
        "frame_path": "main",
        "catalog_type": "native_select",
        "selector": "#" + key,
        "catalog_key": "main::#" + key,
        "options": list(options),
    }


def _snapshot(elements=(), catalogs=(), pathname="/step/1"):
    return {
        "schema_version": 1,
        "page": {"pathname": pathname},
        "elements": tuple(elements),
        "catalogs": tuple(catalogs),
    }


def test_identical_contract_reports_no_change():
    snapshot = _snapshot(
        elements=[_element("#a")],
        catalogs=[_catalog("prov", options=[{"value": "1", "label": "One"}])],
    )

    result = compare_site_contract_revision(snapshot, snapshot)

    assert result["watch_state"] == ContractWatchState.NO_CHANGE.value
    assert result["fingerprint_changed"] is False
    assert result["inconclusive"] is False
    assert result["counts"] == {
        "ADDED": 0,
        "REMOVED": 0,
        "CHANGED": 0,
        "UNCHANGED": 1,
    }
    assert result["catalog_diff"]["option_changes"] == []


def test_repeated_comparison_of_same_pair_is_idempotent():
    before = _snapshot(elements=[_element("#a")])
    after = _snapshot(elements=[_element("#a"), _element("#b")])

    first = compare_site_contract_revision(before, after)
    second = compare_site_contract_revision(before, after)

    assert first == second


def test_element_addition_is_non_breaking_and_confirmed():
    before = _snapshot(elements=[_element("#a")])
    after = _snapshot(elements=[_element("#a"), _element("#b")])

    result = compare_site_contract_revision(before, after)

    assert result["counts"]["ADDED"] == 1
    assert result["severity"] == ContractWatchSeverity.NON_BREAKING.value
    assert result["watch_state"] == ContractWatchState.CHANGE_CONFIRMED.value


def test_element_removal_is_breaking_and_requires_rebuild():
    before = _snapshot(elements=[_element("#a"), _element("#b")])
    after = _snapshot(elements=[_element("#a")])

    result = compare_site_contract_revision(before, after)

    assert result["counts"]["REMOVED"] == 1
    assert result["severity"] == ContractWatchSeverity.BREAKING.value
    assert result["watch_state"] == ContractWatchState.REBUILD_REQUIRED.value


def test_selector_identity_change_is_contract_change():
    before = _snapshot(
        elements=[_element("#old", fallback='[name="continuar"]')]
    )
    after = _snapshot(
        elements=[_element("#new", fallback='[name="continuar"]')]
    )

    result = compare_site_contract_revision(before, after)

    assert result["counts"]["CHANGED"] == 1
    assert "SELECTOR_CHANGED" in result["elements"][0]["changes"]
    assert result["severity"] == ContractWatchSeverity.CONTRACT_CHANGE.value
    assert result["watch_state"] == ContractWatchState.CHANGE_CONFIRMED.value


def test_catalog_option_removal_is_breaking():
    before = _snapshot(catalogs=[_catalog("province", options=[
        {"value": "1", "label": "Madrid"},
        {"value": "2", "label": "Barcelona"},
    ])])
    after = _snapshot(catalogs=[_catalog("province", options=[
        {"value": "1", "label": "Madrid"},
    ])])

    result = compare_site_contract_revision(before, after)

    assert result["catalog_diff"]["option_changes"] == [{
        "catalog_key": "main::#province",
        "options_added": [],
        "options_removed": [["2", "Barcelona", False]],
    }]
    assert result["severity"] == ContractWatchSeverity.BREAKING.value
    assert result["watch_state"] == ContractWatchState.REBUILD_REQUIRED.value


def test_catalog_option_addition_is_non_breaking():
    before = _snapshot(catalogs=[_catalog("province", options=[
        {"value": "1", "label": "Madrid"},
    ])])
    after = _snapshot(catalogs=[_catalog("province", options=[
        {"value": "1", "label": "Madrid"},
        {"value": "2", "label": "Barcelona"},
    ])])

    result = compare_site_contract_revision(before, after)

    assert result["catalog_diff"]["option_changes"] == [{
        "catalog_key": "main::#province",
        "options_added": [["2", "Barcelona", False]],
        "options_removed": [],
    }]
    assert result["severity"] == ContractWatchSeverity.NON_BREAKING.value
    assert result["watch_state"] == ContractWatchState.CHANGE_CONFIRMED.value


def test_interaction_disabled_change_is_contract_change():
    before = _snapshot(elements=[_element("#submit", disabled=False)])
    after = _snapshot(elements=[_element("#submit", disabled=True)])

    result = compare_site_contract_revision(before, after)

    assert "INTERACTION_CHANGED" in result["elements"][0]["changes"]
    assert result["severity"] == ContractWatchSeverity.CONTRACT_CHANGE.value
    assert result["watch_state"] == ContractWatchState.CHANGE_CONFIRMED.value


def test_page_navigation_change_is_breaking():
    before = _snapshot(pathname="/step/1")
    after = _snapshot(pathname="/step/2")

    result = compare_site_contract_revision(before, after)

    assert result["page_changed"] is True
    assert result["severity"] == ContractWatchSeverity.BREAKING.value
    assert result["watch_state"] == ContractWatchState.REBUILD_REQUIRED.value


def test_geometry_change_beyond_tolerance_is_cosmetic_and_suspected():
    before = _snapshot(elements=[_element(
        "#a",
        rect={"x": 100, "y": 200, "width": 100, "height": 40},
    )])
    after = _snapshot(elements=[_element(
        "#a",
        rect={"x": 160, "y": 260, "width": 100, "height": 40},
    )])

    result = compare_site_contract_revision(before, after)

    assert "GEOMETRY_CHANGED" in result["elements"][0]["changes"]
    assert result["severity"] == ContractWatchSeverity.COSMETIC.value
    assert result["watch_state"] == ContractWatchState.CHANGE_SUSPECTED.value


def test_unmatched_identity_requires_validation_not_no_change():
    before = _snapshot(elements=[{
        "frame_path": "main",
        "selectors": {"frame_path": "main", "candidates": ()},
    }])
    after = _snapshot(elements=[])

    result = compare_site_contract_revision(before, after)

    assert result["inconclusive"] is True
    assert result["severity"] == ContractWatchSeverity.UNKNOWN.value
    assert result["watch_state"] == ContractWatchState.VALIDATION_REQUIRED.value


def test_unmatched_catalog_identity_requires_validation():
    before = _snapshot(catalogs=[{
        "frame_path": "main",
        "catalog_type": "native_select",
        "options": [{"value": "1", "label": "One"}],
    }])
    after = _snapshot(catalogs=[])

    result = compare_site_contract_revision(before, after)

    assert result["inconclusive"] is True
    assert result["watch_state"] == ContractWatchState.VALIDATION_REQUIRED.value


def test_element_order_is_preserved_in_evidence():
    element_a = _element("#a")
    element_b = _element("#b")

    before = _snapshot(elements=[element_a, element_b])
    after = _snapshot(elements=[element_b, element_a])

    result = compare_site_contract_revision(before, after)

    # Both elements are matched by stable identity regardless of position,
    # but the DOM order captured by each observation is preserved verbatim
    # in the evidence instead of being canonicalized away.
    assert [item["identity"][1] for item in result["elements"]] == [
        "#a",
        "#b",
    ]
    assert [item["after_index"] for item in result["elements"]] == [1, 0]
    assert result["counts"]["UNCHANGED"] == 2


def test_malformed_contract_fails_closed():
    # Missing schema_version is rejected by the same shared
    # require_supported_schema_version() used across Site Architecture;
    # it can surface as TypeError or ValueError, but never as a silent
    # NO_CHANGE.
    with pytest.raises((TypeError, ValueError)):
        compare_site_contract_revision({"not": "a contract"}, _snapshot())


def test_non_dict_contract_fails_closed():
    with pytest.raises(ValueError):
        compare_site_contract_revision(None, _snapshot())


def test_unsupported_schema_version_fails_closed():
    before = dict(_snapshot())
    before["schema_version"] = 999

    with pytest.raises(ValueError):
        compare_site_contract_revision(before, _snapshot())


def test_evidence_id_is_deterministic_across_catalog_list_reordering():
    catalog_a = _catalog("a", options=[{"value": "1", "label": "One"}])
    catalog_b = _catalog("b", options=[{"value": "2", "label": "Two"}])

    after = _snapshot(catalogs=[catalog_a, catalog_b])

    ordered_before = _snapshot(catalogs=[catalog_a, catalog_b])
    reordered_before = _snapshot(catalogs=[catalog_b, catalog_a])

    evidence_ordered = build_contract_watcher_evidence(
        contract_key="ctr",
        before=ordered_before,
        after=after,
    )

    evidence_reordered = build_contract_watcher_evidence(
        contract_key="ctr",
        before=reordered_before,
        after=after,
    )

    assert (
        evidence_ordered["evidence_id"]
        == evidence_reordered["evidence_id"]
    )


def test_evidence_id_is_independent_of_dict_key_order():
    element = _element("#a")

    before_first = {
        "schema_version": 1,
        "page": {"pathname": "/step/1"},
        "elements": (element,),
        "catalogs": (),
    }

    before_second = {
        "elements": (element,),
        "catalogs": (),
        "schema_version": 1,
        "page": {"pathname": "/step/1"},
    }

    after = _snapshot(elements=[element])

    evidence_first = build_contract_watcher_evidence(
        contract_key="ctr",
        before=before_first,
        after=after,
    )

    evidence_second = build_contract_watcher_evidence(
        contract_key="ctr",
        before=before_second,
        after=after,
    )

    assert (
        evidence_first["evidence_id"]
        == evidence_second["evidence_id"]
    )


def test_build_and_validate_evidence_round_trip():
    before = _snapshot(elements=[_element("#a")])
    after = _snapshot(elements=[_element("#a"), _element("#b")])

    evidence = build_contract_watcher_evidence(
        contract_key="mercurio-ex01-personal",
        before=before,
        after=after,
        before_reference="capture-1",
        after_reference="capture-2",
    )

    validated = validate_contract_watcher_evidence(evidence)

    assert validated == evidence
    assert evidence["evidence_id"].startswith("cwev-")


def test_build_contract_watcher_evidence_requires_contract_key():
    with pytest.raises(ValueError):
        build_contract_watcher_evidence(
            contract_key="",
            before=_snapshot(),
            after=_snapshot(),
        )


def test_validate_contract_watcher_evidence_detects_tampering():
    evidence = build_contract_watcher_evidence(
        contract_key="ctr",
        before=_snapshot(),
        after=_snapshot(),
    )

    tampered = dict(evidence)
    tampered["watch_state"] = ContractWatchState.REBUILD_REQUIRED.value

    with pytest.raises(ValueError):
        validate_contract_watcher_evidence(tampered)
