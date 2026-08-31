from pathlib import Path

from backend.automation.site_architecture.normalizer import (
    normalize_dom_capture,
)
from backend.automation.site_architecture.qcc_capture_adapter import (
    adapt_qcc_extension_capture,
)


WORKER = Path(
    "chrome_extension/qcc/background/service_worker.js"
)


def _capture(
    *,
    include_viewport=True,
):
    element = {
        "index":
            0,

        "tag":
            "a",

        "id":
            "",

        "name":
            "",

        "type":
            "",

        "role":
            "",

        "visible":
            True,

        "disabled":
            False,

        "attributes": {
            "aria-label":
                "CONTINUAR PRESENTACIÓN",

            "href":
                "#",
        },
    }

    if include_viewport:
        element.update({
            "in_viewport":
                True,

            "opacity":
                "1",

            "pointer_events":
                "auto",
        })

    return {
        "capture_type":
            "QCC_EXTENSION_DOM_CAPTURE",

        "schema_version":
            1,

        "captured_at":
            "2026-08-31T10:00:00+00:00",

        "frames": [{
            "frame_id":
                0,

            "document_id":
                "main-document",

            "result": {
                "schema_version":
                    1,

                "url":
                    (
                        "http://127.0.0.1:8767/"
                        "mercurio/"
                        "entradaMercurio.html"
                    ),

                "origin":
                    "http://127.0.0.1:8767",

                "pathname":
                    (
                        "/mercurio/"
                        "entradaMercurio.html"
                    ),

                "title":
                    "Mercurio Twin",

                "ready_state":
                    "complete",

                "content_type":
                    "text/html",

                "character_set":
                    "UTF-8",

                "counts":
                    {},

                "elements": [
                    element,
                ],

                "catalog_probe": {
                    "elements":
                        [],
                },

                "shadow_roots":
                    [],
            },
        }],
    }


def test_extension_source_captures_interaction_signals():
    source = WORKER.read_text(
        encoding="utf-8"
    )

    required = (
        "function interactionSignalsOf(",
        "in_viewport:",
        "opacity:",
        "pointer_events:",
        "style.pointerEvents",
        "getBoundingClientRect()",
    )

    for token in required:
        assert token in source


def test_qcc_adapter_preserves_interaction_signals():
    raw = adapt_qcc_extension_capture(
        _capture()
    )

    element = raw["elements"][0]

    signals = element[
        "interaction_signals"
    ]

    assert (
        signals["in_viewport"]
        is True
    )

    assert (
        signals["opacity"]
        == "1"
    )

    assert (
        signals["pointer_events"]
        == "auto"
    )


def test_qcc_signals_produce_interactable_element():
    raw = adapt_qcc_extension_capture(
        _capture()
    )

    snapshot = normalize_dom_capture(
        raw
    )

    interaction = (
        snapshot.elements[0][
            "interaction"
        ]
    )

    assert (
        interaction["visible"]
        is True
    )

    assert (
        interaction["disabled"]
        is False
    )

    assert (
        interaction["interactable"]
        is True
    )


def test_missing_viewport_signal_remains_fail_closed():
    raw = adapt_qcc_extension_capture(
        _capture(
            include_viewport=False
        )
    )

    snapshot = normalize_dom_capture(
        raw
    )

    interaction = (
        snapshot.elements[0][
            "interaction"
        ]
    )

    assert (
        interaction["interactable"]
        is False
    )
