from pathlib import Path


WORKER = Path(
    "chrome_extension/qcc/background/service_worker.js"
)


def _source():
    return WORKER.read_text(
        encoding="utf-8"
    )


def _automatic_block():
    source = _source()

    start = source.index(
        "QCC_AUTOMATIC_SITE_ARCHITECTURE_V1"
    )

    end = source.index(
        "chrome.runtime.onMessage.addListener(",
        start,
    )

    return source[start:end]


def test_auto_capture_lives_in_service_worker():
    source = _source()

    assert (
        "QCC_AUTOMATIC_SITE_ARCHITECTURE_V1"
        in source
    )

    assert (
        "runAutomaticSiteArchitectureCapture("
        in source
    )


def test_navigation_events_schedule_capture():
    block = _automatic_block()

    assert (
        "chrome.tabs.onUpdated.addListener"
        in block
    )

    assert (
        'changeInfo?.status !== "complete"'
        in block
    )

    assert (
        "chrome.tabs.onActivated.addListener"
        in block
    )

    assert (
        "scheduleAutomaticSiteArchitectureCapture("
        in block
    )


def test_auto_capture_is_passive():
    block = _automatic_block()

    forbidden = (
        "scrollTo(",
        "scrollBy(",
        ".click(",
        "chrome.tabs.update(",
        "chrome.windows.update(",
        "chrome.debugger.attach",
        "chrome.debugger.sendCommand",
    )

    for token in forbidden:
        assert token not in block


def test_auto_capture_never_requests_permission():
    block = _automatic_block()

    assert (
        "chrome.permissions.contains"
        in block
    )

    assert (
        "chrome.permissions.request"
        not in block
    )

    assert (
        '"<all_urls>"'
        in block
    )

    assert (
        '"pageCapture"'
        in block
    )


def test_auto_capture_targets_exact_tab():
    block = _automatic_block()

    assert (
        "async function inspectSpecificTabDom("
        in block
    )

    assert (
        "chrome.tabs.get("
        in block
    )

    assert (
        "tabId:"
        in block
    )

    assert (
        "allFrames:"
        in block
    )


def test_auto_capture_dedupes_by_document_id():
    block = _automatic_block()

    assert (
        "QCC_AUTO_CAPTURE_STORAGE_PREFIX"
        in block
    )

    assert (
        "document_id"
        in block
    )

    assert (
        "chrome.storage.session.get"
        in block
    )

    assert (
        "chrome.storage.session.set"
        in block
    )

    assert (
        "DOCUMENT_ALREADY_CAPTURED"
        in block
    )


def test_auto_capture_uses_backend_as_authority():
    block = _automatic_block()

    assert (
        "/qcc/site-architecture/capture"
        in block
    )

    assert (
        "qccSubmitAutomaticDomCapture("
        in block
    )

    # Browser no calcula fingerprint canónico.
    assert (
        "build_functional_state_fingerprint"
        not in block
    )


def test_auto_capture_persists_viewport_and_mhtml():
    block = _automatic_block()

    required = (
        "chrome.tabs.captureVisibleTab",
        "chrome.pageCapture.saveAsMHTML",
        "/qcc/site-architecture/visual-artifact",
        "/qcc/site-architecture/page-artifact",
        '"viewport"',
        '"mhtml"',
    )

    for token in required:
        assert token in block


def test_auto_capture_only_marks_document_after_backend_success():
    block = _automatic_block()

    backend_pos = block.index(
        "await qccSubmitAutomaticDomCapture("
    )

    remember_pos = block.index(
        "await qccRememberAutomaticCapture("
    )

    assert (
        remember_pos
        > backend_pos
    )


def test_auto_capture_requires_active_complete_http_tab():
    block = _automatic_block()

    assert (
        "tab.active !== true"
        in block
    )

    assert (
        'tab.status !== "complete"'
        in block
    )

    assert (
        'url.protocol === "http:"'
        in block
    )

    assert (
        'url.protocol === "https:"'
        in block
    )


def test_navigation_capture_rearms_human_listener_from_exact_new_document():
    source = _source()

    start = source.index(
        "async function "
        "runAutomaticSiteArchitectureCapture("
    )

    end = source.index(
        "function "
        "scheduleAutomaticSiteArchitectureCapture(",
        start,
    )

    block = source[
        start:end
    ]

    backend_position = block.index(
        "await qccSubmitAutomaticDomCapture("
    )

    arm_position = block.index(
        "await autoArmDiscoveryHumanListener("
    )

    remember_position = block.index(
        "await qccRememberAutomaticCapture("
    )

    assert (
        backend_position
        < arm_position
        < remember_position
    )

    arm_call = block[
        arm_position:
        arm_position + 300
    ]

    assert (
        "backendResult"
        in arm_call
    )

    assert (
        "normalizedTabId"
        in arm_call
    )

    assert (
        "capture"
        in arm_call
    )


def test_navigation_capture_retries_if_previous_document_is_in_flight():
    source = _source()

    start = source.index(
        "async function "
        "runAutomaticSiteArchitectureCapture("
    )

    end = source.index(
        "function "
        "scheduleAutomaticSiteArchitectureCapture(",
        start,
    )

    block = source[start:end]

    collision = block.index(
        "qccAutomaticCaptureInFlight.has("
    )

    retry = block.index(
        '"CAPTURE_RETRY_AFTER_IN_FLIGHT"',
        collision,
    )

    add_lock = block.index(
        "qccAutomaticCaptureInFlight.add(",
        collision,
    )

    assert collision < retry < add_lock


def test_navigation_capture_arms_before_waiting_for_heavy_artifacts():
    source = _source()

    start = source.index(
        "async function "
        "runAutomaticSiteArchitectureCapture("
    )

    end = source.index(
        "function "
        "scheduleAutomaticSiteArchitectureCapture(",
        start,
    )

    block = source[start:end]

    backend = block.index(
        "await qccSubmitAutomaticDomCapture("
    )

    arm = block.index(
        "await autoArmDiscoveryHumanListener("
    )

    artifact_wait = block.index(
        "await Promise.all(["
    )

    assert backend < arm < artifact_wait

    assert (
        "await qccCaptureAutomaticViewport("
        not in block[:arm]
    )

    assert (
        "await qccCaptureAutomaticMhtml("
        not in block[:arm]
    )


def test_navigation_capture_releases_tab_after_listener_handoff():
    source = _source()

    start = source.index(
        "async function "
        "runAutomaticSiteArchitectureCapture("
    )

    end = source.index(
        "function "
        "scheduleAutomaticSiteArchitectureCapture(",
        start,
    )

    block = source[start:end]

    arm = block.index(
        "await autoArmDiscoveryHumanListener("
    )

    remember = block.index(
        "await qccRememberAutomaticCapture("
    )

    release = block.index(
        "qccAutomaticCaptureInFlight.delete(",
        remember,
    )

    artifact_wait = block.index(
        "await Promise.all(["
    )

    assert (
        arm
        < remember
        < release
        < artifact_wait
    )
