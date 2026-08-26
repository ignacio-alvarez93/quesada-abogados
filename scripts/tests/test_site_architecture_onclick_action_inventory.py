from backend.automation.site_architecture.normalizer import (
    normalize_dom_capture,
)


def _payload():
    return {
        "schema_version":
            1,

        "captured_at":
            "2026-08-26T14:15:00Z",

        "metadata": {
            "url":
                "https://example.test/app",

            "origin":
                "https://example.test",

            "pathname":
                "/app",

            "title":
                "Test",

            "ready_state":
                "complete",
        },

        "viewport":
            {},

        "documents":
            [],

        "elements": [{
            "index":
                0,

            "frame_path":
                "main",

            "tag":
                "button",

            "id":
                "",

            "name":
                "",

            "type":
                "button",

            "role":
                "",

            "attributes": {
                "onclick":
                    "irOpcion()",
            },

            "visible":
                True,

            "disabled":
                False,

            "interactable":
                True,
        }],

        "frames":
            [],

        "shadows":
            [],

        "catalogs":
            [],

        "counts": {
            "elements":
                1,
        },
    }


def test_normalizer_projects_safe_onclick_into_action_identity():
    snapshot = normalize_dom_capture(
        _payload()
    )

    assert len(
        snapshot.actions
    ) == 1

    action = (
        snapshot.actions[0]
    )

    assert (
        action["kind"]
        == "BUTTON"
    )

    assert (
        action["policy"]
        == "REQUIRES_POLICY"
    )

    assert (
        action["selector"]
        == (
            'button['
            'onclick="irOpcion()"]'
        )
    )

    assert (
        action["frame_path"]
        == "main"
    )
