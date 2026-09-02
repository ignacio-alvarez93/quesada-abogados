from pathlib import Path


WORKER = Path(
    "chrome_extension/qcc/background/service_worker.js"
)


def _source():
    return WORKER.read_text(
        encoding="utf-8"
    )


def _mutation_block():
    text = WORKER.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "QCC_SAME_DOCUMENT_MUTATION_CAPTURE_V1"
    )

    # El Generic Harvest es un subsistema posterior
    # e independiente del observer pasivo.
    sentinels = (
        "QCC_GENERIC_DOM_HARVEST_V1",
        "QCC_GENERIC_DYNAMIC_HARVEST_V1",
        "chrome.runtime.onInstalled.addListener",
    )

    ends = [
        position
        for marker in sentinels
        if (
            position := text.find(
                marker,
                start + 1,
            )
        ) >= 0
    ]

    if not ends:
        raise AssertionError(
            "MUTATION_RUNTIME_END_SENTINEL_NOT_FOUND"
        )

    end = min(
        ends
    )

    return text[
        start:end
    ]


def test_same_document_mutation_runtime_exists():
    block = _mutation_block()

    required = (
        "installQccAutomaticMutationObserverFrame(",
        "MutationObserver(",
        "QCC_SITE_ARCHITECTURE_DIRTY",
        "runAutomaticSameDocumentObservation(",
        "scheduleAutomaticSameDocumentObservation(",
    )

    for token in required:
        assert token in block


def test_browser_only_emits_minimal_dirty_signal():
    source = _source()

    start = source.index(
        "const emitDirtySignal"
    )

    end = source.index(
        "const scheduleDirtySignal",
        start,

    )
    block = source[
        start:end
    ]

    assert (
        "QCC_SITE_ARCHITECTURE_DIRTY"
        in block
    )

    forbidden = (
        "fingerprint",
        "capture_id",
        "policy",
        "environment",
        "html:",
        "frames:",
    )

    for token in forbidden:
        assert token not in block


def test_mutation_gate_uses_backend_observe_before_persistence():
    block = _mutation_block()

    assert (
        "/qcc/site-architecture/observe"
        in block
    )

    observe_pos = block.index(
        "await qccSubmitAutomaticDomObservation("
    )

    capture_pos = block.index(
        "await qccSubmitAutomaticDomCapture(",
        observe_pos,
    )

    assert (
        observe_pos
        < capture_pos
    )


def test_unchanged_fingerprint_does_not_persist():
    block = _mutation_block()

    compare_pos = block.index(
        "candidateFingerprint"
    )

    unchanged_pos = block.index(
        "FUNCTIONAL_STATE_UNCHANGED",
        compare_pos,
    )

    persist_pos = block.index(
        "await qccSubmitAutomaticDomCapture(",
        unchanged_pos,
    )

    assert (
        unchanged_pos
        < persist_pos
    )

    assert (
        "candidateFingerprint"
        in block
    )

    assert (
        "backendChanged"
        in block
    )

    assert (
        "baselineFingerprint"
        not in block
    )


def test_navigation_capture_seeds_backend_fingerprint():
    source = _source()

    assert (
        "backendResult"
        in source
    )

    assert (
        "backendResult"
        in source
    )

    assert (
        "state_observation"
        in source
    )

    assert (
        "fingerprint:"
        in source
    )

    assert (
        "qccRememberAutomaticCapture("
        in source
    )


def test_mutation_runtime_is_passive():
    block = _mutation_block()

    forbidden = (
        "scrollTo(",
        "scrollBy(",
        ".click(",
        "chrome.tabs.update(",
        "chrome.windows.update(",
        "chrome.debugger.attach",
        "chrome.debugger.sendCommand",
        "chrome.permissions.request",
    )

    for token in forbidden:
        assert token not in block


def test_mutation_observer_is_debounced_twice():
    block = _mutation_block()

    assert (
        "QCC_AUTO_MUTATION_FRAME_DEBOUNCE_MS"
        in block
    )

    assert (
        "QCC_AUTO_MUTATION_DEBOUNCE_MS"
        in block
    )

    assert (
        "qccAutomaticMutationTimers"
        in block
    )


def test_same_document_gate_requires_same_document_id():
    block = _mutation_block()

    assert (
        "baselineDocumentId"
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


def test_observer_targets_all_frames_without_focus_change():
    block = _mutation_block()

    assert (
        "allFrames:"
        in block
    )

    assert (
        "world:"
        in block
    )

    assert (
        '"ISOLATED"'
        in block
    )


def test_visual_evidence_only_after_fingerprint_change_gate():
    block = _mutation_block()

    unchanged_pos = block.index(
        "FUNCTIONAL_STATE_UNCHANGED"
    )

    viewport_pos = block.index(
        "qccCaptureAutomaticViewport(",
        unchanged_pos,
    )

    mhtml_pos = block.index(
        "qccCaptureAutomaticMhtml(",
        unchanged_pos,
    )

    assert (
        viewport_pos
        > unchanged_pos
    )

    assert (
        mhtml_pos
        > unchanged_pos
    )



def test_backend_is_authority_for_mutation_dedupe():
    block = _mutation_block()

    assert (
        "baseline_capture_id:"
        in block
    )

    assert (
        "backendChanged === false"
        in block
    )

    assert (
        "backendChanged !== true"
        in block
    )

    assert (
        "QCC_AUTO_OBSERVE_CHANGE_DECISION_MISSING"
        in block
    )

    # El fingerprint local puede conservarse como
    # metadata/cache, pero no decide persistencia.
    assert (
        "baselineFingerprint"
        not in block
    )
