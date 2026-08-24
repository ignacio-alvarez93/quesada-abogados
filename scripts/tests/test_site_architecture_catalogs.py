from backend.automation.site_architecture import (
    CATALOG_RELATION_DOM_REFERENCE,
    build_catalog_reference_graph,
    normalize_catalogs,
)


def _catalog(
    element_id,
    *,
    frame_path="main",
    hints=None,
):
    return {
        "catalog_type":
            "native_select",
        "selector":
            f"#{element_id}",
        "frame_path":
            frame_path,
        "element": {
            "tag":
                "select",
            "id":
                element_id,
            "name":
                element_id,
        },
        "dependency_hints":
            hints or {},
        "options":
            [],
        "options_count":
            0,
    }


def test_normalize_catalogs_adds_stable_key():
    catalogs = normalize_catalogs([
        _catalog(
            "province"
        ),
    ])

    assert len(catalogs) == 1

    assert (
        catalogs[0]["catalog_key"]
        == "main::#province"
    )


def test_normalize_catalogs_removes_old_self_hint_noise():
    catalogs = normalize_catalogs([
        _catalog(
            "province",
            hints={
                "id": "province",
                "name": "province",
                "data-child": "municipality",
            },
        ),
    ])

    assert (
        catalogs[0]["dependency_hints"]
        == {
            "data-child":
                "municipality",
        }
    )


def test_catalog_graph_records_literal_dom_references():
    catalogs = normalize_catalogs([
        _catalog(
            "province",
            hints={
                "datmu":
                    "municipality",
                "datlo":
                    "locality",
            },
        ),
        _catalog(
            "municipality",
            hints={
                "datpr":
                    "province",
                "datlo":
                    "locality",
            },
        ),
        _catalog(
            "locality",
            hints={
                "datpr":
                    "province",
                "datmu":
                    "municipality",
            },
        ),
    ])

    relations = (
        build_catalog_reference_graph(
            catalogs
        )
    )

    assert len(relations) == 6

    assert all(
        relation["relation"]
        == CATALOG_RELATION_DOM_REFERENCE
        for relation in relations
    )

    assert {
        (
            relation["source"],
            relation["target"],
            relation["evidence"][
                "attribute"
            ],
        )
        for relation in relations
    } == {
        (
            "main::#province",
            "main::#municipality",
            "datmu",
        ),
        (
            "main::#province",
            "main::#locality",
            "datlo",
        ),
        (
            "main::#municipality",
            "main::#province",
            "datpr",
        ),
        (
            "main::#municipality",
            "main::#locality",
            "datlo",
        ),
        (
            "main::#locality",
            "main::#province",
            "datpr",
        ),
        (
            "main::#locality",
            "main::#municipality",
            "datmu",
        ),
    }


def test_catalog_graph_supports_aria_idref_lists():
    catalogs = normalize_catalogs([
        _catalog(
            "country",
            hints={
                "aria-controls":
                    "province municipality",
            },
        ),
        _catalog(
            "province"
        ),
        _catalog(
            "municipality"
        ),
    ])

    relations = (
        build_catalog_reference_graph(
            catalogs
        )
    )

    assert {
        relation["target"]
        for relation in relations
    } == {
        "main::#province",
        "main::#municipality",
    }


def test_catalog_graph_never_crosses_frames():
    catalogs = normalize_catalogs([
        _catalog(
            "parent",
            frame_path="main",
            hints={
                "data-target":
                    "child",
            },
        ),
        _catalog(
            "child",
            frame_path="qcc-frame:7",
        ),
    ])

    relations = (
        build_catalog_reference_graph(
            catalogs
        )
    )

    assert relations == ()


def test_catalog_graph_does_not_invent_causality():
    catalogs = normalize_catalogs([
        _catalog(
            "province",
            hints={
                "data-target":
                    "municipality",
            },
        ),
        _catalog(
            "municipality"
        ),
    ])

    relations = (
        build_catalog_reference_graph(
            catalogs
        )
    )

    assert len(relations) == 1

    serialized = repr(
        relations
    )

    assert "INFLUENCES" not in serialized
    assert "DEPENDS_ON" not in serialized
