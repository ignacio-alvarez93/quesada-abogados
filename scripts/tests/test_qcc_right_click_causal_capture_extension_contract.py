from pathlib import Path


SERVICE_WORKER = Path(
    "chrome_extension/qcc/background/service_worker.js"
)


def _source():
    return SERVICE_WORKER.read_text(
        encoding="utf-8"
    )


def test_twin_discovery_auto_arm_uses_contextmenu():
    source = _source()

    assert (
        "QCC_RIGHT_CLICK_CAUSAL_CAPTURE_V1"
        in source
    )

    assert (
        'event_mode:\n          "CONTEXTMENU"'
        in source
    )

    assert (
        '=== "CONTEXTMENU"\n      ? "contextmenu"'
        in source
    )

    assert (
        "event.preventDefault();"
        in source
    )

    assert (
        "event.stopPropagation();"
        in source
    )


def test_legacy_human_listener_keeps_pointerdown_default():
    source = _source()

    assert (
        'request?.event_mode\n      || "POINTERDOWN"'
        in source
    )

    assert (
        'eventMode !== "POINTERDOWN"'
        in source
    )

    assert (
        'eventMode !== "CONTEXTMENU"'
        in source
    )

    assert (
        '"QCC_HUMAN_LISTENER_EVENT_MODE_INVALID"'
        in source
    )


def test_exact_document_listener_receives_event_mode():
    source = _source()

    assert (
        "installQccHumanClickListenerInFrame("
        in source
    )

    assert (
        "ttlMs,\n  eventMode\n)"
        in source
    )

    assert (
        "QCC_HUMAN_LISTENER_TTL_MS,\n"
        "            eventMode"
        in source
    )

def test_right_click_forces_fresh_backend_evidence_before_signal():
    source = _source()

    assert (
        "QCC_RIGHT_CLICK_FRESH_EVIDENCE_V1"
        in source
    )

    assert (
        "qccCaptureFreshRightClickCausalEvidence("
        in source
    )

    assert (
        "await inspectSpecificTabDom("
        in source
    )

    assert (
        "await qccSubmitAutomaticDomCapture("
        in source
    )

    assert (
        "human_listener_evidence_id"
        in source
    )

    assert (
        "QCC_RIGHT_CLICK_FRESH_TARGET_NOT_CANONICAL"
        in source
    )

    assert (
        "effectiveEvidenceId"
        in source
    )

    assert (
        "effectiveObservedAt"
        in source
    )


def test_right_click_fresh_capture_is_exact_document_bound():
    source = _source()

    assert (
        "QCC_RIGHT_CLICK_DOCUMENT_CHANGED"
        in source
    )

    assert (
        "qccAutomaticMainDocumentId("
        in source
    )

    assert (
        "expectedDocumentId"
        in source
    )


def test_pointerdown_legacy_does_not_require_fresh_capture():
    source = _source()

    # Browser arm keeps POINTERDOWN as the compatibility default.
    assert (
        "arm?.event_mode"
        in source
    )

    assert (
        '|| "POINTERDOWN"'
        in source
    )

    # Existing arm evidence is the default effective evidence.
    assert (
        "let effectiveEvidenceId"
        in source
    )

    assert (
        "arm?.evidence_id"
        in source
    )

    # Fresh capture is opt-in exclusively for CONTEXTMENU.
    assert (
        "armEventMode"
        in source
    )

    assert (
        '=== "CONTEXTMENU"'
        in source
    )

    assert (
        "await qccCaptureFreshRightClickCausalEvidence("
        in source
    )

def test_right_click_page_timestamp_stays_physical():
    import re

    source = _source()

    start = source.index(
        "function installQccHumanClickListenerInFrame("
    )

    end = source.index(
        "function qccHumanFrameIdFromPath",
        start,
    )

    block = source[start:end]

    assert re.search(
        r"observed_at:\s*observedAt\b",
        block,
    )

    assert (
        "effectiveObservedAt"
        not in block
    )

def test_fresh_evidence_post_uses_effective_timestamp_and_evidence():
    import re

    source = _source()

    start = source.index(
        "async function forwardQccHumanDomActionSignal("
    )

    end = source.index(
        "function captureDomFrame()",
        start,
    )

    block = source[start:end]

    assert (
        "effectiveEvidenceId"
        in block
    )

    assert (
        "effectiveObservedAt"
        in block
    )

    assert re.search(
        r"evidence_id:\s*effectiveEvidenceId\b",
        block,
    )

    assert re.search(
        r"observed_at:\s*effectiveObservedAt\b",
        block,
    )

def test_right_click_waits_for_bridge_ack_before_left_click():
    source = _source()

    assert (
        "QCC_RIGHT_CLICK_CAUSAL_ACK_V2"
        in source
    )

    assert (
        "QCC_HUMAN_DOM_ACTION_ACK"
        in source
    )

    assert (
        "QCC_HUMAN_DOM_ACTION_ACK_TIMEOUT"
        in source
    )

    assert (
        "waitForAck"
        in source
    )

    assert (
        "AUTO TWIN · acción capturada"
        in source
    )


def test_legacy_pointerdown_remains_fire_and_forget():
    source = _source()

    assert (
        "waitForAck !== true"
        in source
    )

    assert (
        "Legacy POINTERDOWN"
        in source
    )

    assert (
        "queued:"
        in source
    )
