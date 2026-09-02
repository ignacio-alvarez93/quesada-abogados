from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

WORKER = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "background"
    / "service_worker.js"
)


def _text():
    return WORKER.read_text(
        encoding="utf-8"
    )


def _block(
    text,
    start,
    end,
):
    begin = text.index(start)
    finish = text.index(
        end,
        begin,
    )

    return text[
        begin:finish
    ]


def test_vis2a_dom_capture_does_not_require_active_tab():
    text = _text()

    block = _block(
        text,
        "async function runAutomaticSiteArchitectureCapture(",
        "function scheduleAutomaticSiteArchitectureCapture(",
    )

    assert (
        "tab.active !== true"
        not in block
    )

    assert (
        'tab.status !== "complete"'
        in block
    )


def test_vis2b_dom_observation_does_not_require_active_tab():
    text = _text()

    block = _block(
        text,
        "async function runAutomaticSameDocumentObservation(",
        "async function runAutomaticSiteArchitectureCapture(",
    )

    assert (
        "tab.active !== true"
        not in block
    )

    assert (
        'tab.status !== "complete"'
        in block
    )


def test_viewport_still_requires_exact_active_tab():
    text = _text()

    block = _block(
        text,
        "async function qccCaptureAutomaticViewport(",
        "async function qccCaptureAutomaticMhtml(",
    )

    assert (
        "tab.active !== true"
        in block
    )

    assert (
        "activeTab.id !== tab.id"
        in block
    )


def test_navigation_complete_is_not_filtered_by_active_tab():
    text = _text()

    block = _block(
        text,
        "chrome.tabs.onUpdated.addListener(",
        "chrome.tabs.onActivated.addListener(",
    )

    assert (
        'changeInfo?.status !== "complete"'
        in block
    )

    assert (
        "tab?.active !== true"
        not in block
    )


def test_missing_baseline_self_heals_through_vis2a():
    text = _text()

    block = _block(
        text,
        "async function runAutomaticSameDocumentObservation(",
        "async function runAutomaticSiteArchitectureCapture(",
    )

    assert (
        '"MUTATION_BASELINE_MISSING"'
        in block
    )

    assert (
        '"BASELINE_RESEED_SCHEDULED"'
        in block
    )

    assert (
        '"MUTATION_BASELINE_MISMATCH"'
        in block
    )

    assert (
        '"DOCUMENT_BASELINE_RESEED_SCHEDULED"'
        in block
    )

    assert (
        "scheduleAutomaticSiteArchitectureCapture("
        in block
    )
