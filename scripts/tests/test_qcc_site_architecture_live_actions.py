import json
from types import SimpleNamespace

from backend.qcc.site_architecture import (
    QccSiteArchitectureIngestor,
)


def _capture():
    return {
        "ok":
            True,

        "capture_type":
            "QCC_EXTENSION_DOM_CAPTURE",

        "schema_version":
            1,

        "captured_at":
            "2026-08-26T13:45:00Z",

        "tab_id":
            1,

        "captured_frames":
            1,

        "frames": [{
            "frame_id":
                0,

            "document_id":
                "main-doc",

            "result": {
                "schema_version":
                    1,

                "captured_at":
                    "2026-08-26T13:45:00Z",

                "url":
                    "https://example.test/form",

                "origin":
                    "https://example.test",

                "pathname":
                    "/form",

                "hostname":
                    "example.test",

                "title":
                    "Test",

                "ready_state":
                    "complete",

                "content_type":
                    "text/html",

                "character_set":
                    "UTF-8",

                "html":
                    "<html><body></body></html>",

                "counts": {
                    "elements":
                        0,
                },

                "elements":
                    [],

                "shadow_roots":
                    [],
            },
        }],
    }


def test_live_action_evidence_is_minimal_allowlist():
    snapshot = SimpleNamespace(
        actions=({
            "schema_version":
                1,

            "action_index":
                0,

            "element_index":
                9,

            "kind":
                "BUTTON",

            "policy":
                "REQUIRES_POLICY",

            "selector":
                "#continue",

            "frame_path":
                "main",

            "selector_confidence":
                1.0,

            "semantics":
                ("BUTTON",),

            "state_signals": {
                "checked":
                    False,
            },

            "interaction": {
                "state":
                    "INTERACTABLE",

                "visible":
                    True,

                "disabled":
                    False,

                "interactable":
                    True,
            },

            "element": {
                "tag":
                    "button",

                "id":
                    "continue",

                "name":
                    "SECRET-NAME",
            },

            "navigation": {
                "href":
                    "https://example.test/?secret=1",
            },

            # Nunca deben sobrevivir aunque aparezcan
            # accidentalmente en una versión futura.
            "text":
                "PERSONAL DATA",

            "value":
                "SECRET VALUE",

            "html":
                "<button>SECRET</button>",

            "payload": {
                "secret":
                    True,
            },
        },),
    )

    evidence = (
        QccSiteArchitectureIngestor
        ._live_action_evidence(
            snapshot
        )
    )

    assert len(
        evidence
    ) == 1

    action = evidence[0]

    assert set(
        action
    ) == {
        "kind",
        "policy",
        "selector",
        "frame_path",
        "interaction",
    }

    assert set(
        action["interaction"]
    ) == {
        "visible",
        "disabled",
        "interactable",
    }

    assert action == {
        "kind":
            "BUTTON",

        "policy":
            "REQUIRES_POLICY",

        "selector":
            "#continue",

        "frame_path":
            "main",

        "interaction": {
            "visible":
                True,

            "disabled":
                False,

            "interactable":
                True,
        },
    }

    serialized = json.dumps(
        evidence,
        ensure_ascii=False,
    ).lower()

    for forbidden in (
        "personal data",
        "secret value",
        "secret-name",
        "?secret=1",
        "<button>",
        '"payload"',
        '"element"',
        '"navigation"',
        '"semantics"',
        '"state_signals"',
        '"selector_confidence"',
    ):
        assert forbidden not in serialized


def test_live_action_evidence_preserves_safety_state():
    snapshot = SimpleNamespace(
        actions=({
            "kind":
                "SELECT",

            "policy":
                "STATE_CHANGE_CANDIDATE",

            "selector":
                "#province",

            "frame_path":
                "frame-1",

            "interaction": {
                "visible":
                    False,

                "disabled":
                    True,

                "interactable":
                    False,
            },
        },),
    )

    action = (
        QccSiteArchitectureIngestor
        ._live_action_evidence(
            snapshot
        )[0]
    )

    assert (
        action["interaction"]["visible"]
        is False
    )

    assert (
        action["interaction"]["disabled"]
        is True
    )

    assert (
        action[
            "interaction"
        ][
            "interactable"
        ]
        is False
    )


def test_empty_snapshot_produces_no_live_actions():
    snapshot = SimpleNamespace(
        actions=()
    )

    assert (
        QccSiteArchitectureIngestor
        ._live_action_evidence(
            snapshot
        )
        == ()
    )


def test_ingest_returns_ephemeral_actions_but_does_not_persist_them(
    tmp_path,
):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path
        )
    )

    result = ingestor.ingest(
        _capture()
    )

    assert (
        result["live_actions"]
        == ()
    )

    metadata_path = (
        tmp_path
        / result["capture_id"]
        / "metadata.json"
    )

    metadata = json.loads(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        "live_actions"
        not in metadata
    )


def test_runtime_live_actions_are_not_part_of_context_contract(
    tmp_path,
):
    ingestor = (
        QccSiteArchitectureIngestor(
            output_root=tmp_path
        )
    )

    result = ingestor.ingest(
        _capture()
    )

    metadata_path = (
        tmp_path
        / result["capture_id"]
        / "metadata.json"
    )

    serialized = (
        metadata_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        '"live_actions"'
        not in serialized
    )
