import json
from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

QCC_DIR = (
    ROOT
    / "chrome_extension"
    / "qcc"
)

SERVICE_WORKER = (
    QCC_DIR
    / "background"
    / "service_worker.js"
)

SIDEPANEL = (
    QCC_DIR
    / "sidepanel"
    / "sidepanel.js"
)


def _source(
    path,
):
    return path.read_text(
        encoding="utf-8"
    )


def _block(
    source,
    start,
    end,
):
    start_index = source.index(
        start
    )

    end_index = source.index(
        end,
        start_index,
    )

    return source[
        start_index:
        end_index
    ]


def test_manifest_still_has_no_static_content_scripts():
    manifest = json.loads(
        (
            QCC_DIR
            / "manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        "content_scripts"
        not in manifest
    )


def test_listener_is_injected_on_demand():
    source = _source(
        SERVICE_WORKER
    )

    assert (
        "installQccHumanClickListenerInFrame"
        in source
    )

    assert (
        "QCC_ARM_HUMAN_LISTENER"
        in source
    )

    assert (
        "chrome.scripting.executeScript"
        in source
    )

    assert (
        "documentIds:"
        in source
    )


def test_listener_requires_trusted_event_and_preserves_legacy_pointerdown_default():
    source = _source(
        SERVICE_WORKER
    )

    block = _block(
        source,
        (
            "function "
            "installQccHumanClickListenerInFrame"
        ),
        (
            "function "
            "qccHumanFrameIdFromPath"
        ),
    )

    # Every causal signal must still come from a real
    # physical browser interaction.
    assert (
        "event.isTrusted !== true"
        in block
    )

    # Legacy/default callers remain POINTERDOWN.
    assert (
        'eventMode\n      || "POINTERDOWN"'
        in block
    )

    # Twin Discovery may explicitly opt into CONTEXTMENU.
    assert (
        'normalizedEventMode\n'
        '      === "CONTEXTMENU"'
        in block
    )

    assert (
        '? "contextmenu"\n'
        '      : "pointerdown"'
        in block
    )

    assert (
        "document.addEventListener(\n"
        "    listenerEventName,"
        in block
    )

    # CONTEXTMENU is the explicit causal declaration.
    # Only that mode suppresses the browser/page menu.
    assert (
        'normalizedEventMode\n'
        '      === "CONTEXTMENU"'
        in block
    )

    assert (
        "event.preventDefault();"
        in block
    )

    assert (
        "event.stopPropagation();"
        in block
    )

    # Observation never executes the site action itself.
    assert (
        ".click("
        not in block
    )

    assert (
        "dispatchEvent"
        not in block
    )


def test_page_listener_has_no_action_authority():
    source = _source(
        SERVICE_WORKER
    )

    block = _block(
        source,
        (
            "function "
            "installQccHumanClickListenerInFrame"
        ),
        (
            "function "
            "qccHumanFrameIdFromPath"
        ),
    )

    for forbidden in (
        "policy",
        "kind",
        "environment",
        "site_code",
        "fingerprint",
        "before_state",
        "before_fingerprint",
        "session_id",
    ):
        assert (
            forbidden
            not in block
        )


def test_listener_is_single_shot_and_ttl_bounded():
    source = _source(
        SERVICE_WORKER
    )

    block = _block(
        source,
        (
            "function "
            "installQccHumanClickListenerInFrame"
        ),
        (
            "function "
            "qccHumanFrameIdFromPath"
        ),
    )

    assert (
        "cleanup();"
        in block
    )

    assert (
        "setTimeout("
        in block
    )

    assert (
        "document.removeEventListener"
        in block
    )


def test_service_worker_validates_chrome_sender_document_identity():
    source = _source(
        SERVICE_WORKER
    )

    block = _block(
        source,
        (
            "async function "
            "forwardQccHumanDomActionSignal"
        ),
        (
            "async function "
            "inspectActiveTabDom"
        ),
    )

    required = (
        "sender?.tab?.id",
        "sender?.documentId",
        "sender?.frameId",
        "QCC_HUMAN_SIGNAL_TAB_MISMATCH",
        "QCC_HUMAN_SIGNAL_DOCUMENT_MISMATCH",
        "QCC_HUMAN_SIGNAL_FRAME_MISMATCH",
    )

    for token in required:
        assert token in block


def test_http_signal_contains_only_minimal_backend_contract():
    source = _source(
        SERVICE_WORKER
    )

    block = _block(
        source,
        (
            "async function "
            "forwardQccHumanDomActionSignal"
        ),
        (
            "function "
            "captureDomFrame"
        ),
    )

    required = (
        "/human-dom-action",
        "protocol_version:",
        "event_id:",
        "selector:",
        "frame_path:",
        "observed_at:",
    )

    for token in required:
        assert token in block

    for forbidden in (
        "policy:",
        "kind:",
        "environment:",
        "site_code:",
        "before_state:",
        "before_fingerprint:",
    ):
        assert (
            forbidden
            not in block
        )


def test_service_worker_never_falls_back_from_document_to_frame():
    source = _source(
        SERVICE_WORKER
    )

    arm_block = _block(
        source,
        (
            "async function "
            "armQccHumanClickListeners"
        ),
        (
            "async function "
            "forwardQccHumanDomActionSignal"
        ),
    )

    assert (
        "documentIds:"
        in arm_block
    )

    assert (
        "frameIds:"
        not in arm_block
    )

    assert (
        "QCC_HUMAN_LISTENER_DOCUMENT_UNAVAILABLE"
        in arm_block
    )


def test_sidepanel_uses_exact_capture_tab_and_documents():
    source = _source(
        SIDEPANEL
    )

    block = _block(
        source,
        (
            "async function "
            "armHumanListenerFromCapture"
        ),
        (
            "function buildActionIdentityKey"
        ),
    )

    required = (
        "capture?.tab_id",
        "frame?.frame_id",
        "frame?.document_id",
        "backendResult?.session_id",
        "backendResult?.human_listener_plan",
        "QCC_ARM_HUMAN_LISTENER",
    )

    for token in required:
        assert token in block


def test_sidepanel_arms_only_after_backend_capture_success():
    source = _source(
        SIDEPANEL
    )

    start = source.index(
        "async function handleDomInspect()"
    )

    block = source[
        start:
    ]

    backend_position = (
        block.index(
            "await submitSiteArchitectureCapture"
        )
    )

    arm_position = (
        block.index(
            "await armHumanListenerFromCapture"
        )
    )

    assert (
        backend_position
        < arm_position
    )
