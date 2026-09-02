from pathlib import Path


SIDEPANEL = Path(
    "chrome_extension/qcc/sidepanel/sidepanel.js"
)


def _source():
    return SIDEPANEL.read_text(
        encoding="utf-8"
    )


def test_qcc_visual_evidence_captures_visible_tab_as_png():
    source = _source()

    required = (
        "QCC_VISUAL_EVIDENCE_VIEWPORT_V1",
        "captureActiveViewportScreenshot",
        "chrome.tabs.captureVisibleTab",
        'format:\n          "png"',
        "data:image/png",
    )

    for token in required:
        assert token in source


def test_qcc_visual_evidence_has_dedicated_binary_transport():
    source = _source()

    required = (
        "QCC_SITE_ARCHITECTURE_VISUAL_ARTIFACT_URL",
        "/visual-artifact",
        "submitVisualArtifact",
        "X-QCC-Protocol-Version",
        "X-QCC-Capture-Id",
        "X-QCC-Visual-Kind",
        '"image/png"',
    )

    for token in required:
        assert token in source


def test_qcc_viewport_capture_is_taken_before_backend_processing():
    source = _source()

    start = source.index(
        "async function handleDomInspect()"
    )

    block = source[start:]

    capture_position = block.index(
        "captureActiveViewportScreenshot"
    )

    backend_position = block.index(
        "submitSiteArchitectureCapture"
    )

    assert (
        capture_position
        < backend_position
    )


def test_qcc_visual_artifact_is_attached_only_after_capture_id_exists():
    source = _source()

    start = source.index(
        "async function handleDomInspect()"
    )

    block = source[start:]

    backend_position = block.index(
        "submitSiteArchitectureCapture"
    )

    upload_position = block.index(
        "submitVisualArtifact"
    )

    assert (
        backend_position
        < upload_position
    )

    assert (
        "backendResult.capture_id"
        in block
    )


def test_qcc_visual_failure_does_not_break_dom_capture():
    source = _source()

    assert (
        "QCC_VISUAL_VIEWPORT_PREPARED"
        in source
    )

    assert (
        "QCC_VISUAL_VIEWPORT_ATTACHED"
        in source
    )

    assert (
        'console.warn(\n        "[QCC] Viewport capture:"'
        in source
    )

    assert (
        'console.warn(\n            "[QCC] Visual Evidence upload:"'
        in source
    )



def test_qcc_viewport_status_is_visible_in_dom_inspect_feedback():
    source = _source()

    start = source.index(
        "async function handleDomInspect()"
    )

    block = source[start:]

    assert (
        "viewportStatus"
        in block
    )

    assert (
        '+ viewportStatus'
        in block
    )

    integrated = block.index(
        '"Site Architecture integrada · "'
    )

    viewport = block.index(
        "+ viewportStatus",
        integrated,
    )

    listener = block.index(
        "+ humanListenerStatus",
        viewport,
    )

    assert (
        integrated
        < viewport
        < listener
    )



def test_qcc_visual_capture_declares_optional_all_urls_permission():
    import json

    manifest_path = Path(
        "chrome_extension/qcc/manifest.json"
    )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    optional = manifest.get(
        "optional_host_permissions",
        [],
    )

    assert (
        "<all_urls>"
        in optional
    )


def test_qcc_visual_capture_requests_all_urls_at_runtime():
    source = _source()

    assert (
        "QCC_VISUAL_CAPTURE_PERMISSION_V1"
        in source
    )

    start = source.index(
        "const QCC_DOM_OPTIONAL_ORIGINS"
    )

    end = source.index(
        "];",
        start,
    )

    block = source[
        start:end
    ]

    assert (
        '"<all_urls>"'
        in block
    )


def test_qcc_keeps_active_tab_as_narrow_fallback():
    import json

    manifest_path = Path(
        "chrome_extension/qcc/manifest.json"
    )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        "activeTab"
        in manifest.get(
            "permissions",
            [],
        )
    )



def test_qcc_visual_evidence_has_local_download_fallback():
    source = _source()

    assert (
        "QCC_VISUAL_LOCAL_FALLBACK_V1"
        in source
    )

    assert (
        "function downloadVisualEvidence("
        in source
    )

    assert (
        "URL.createObjectURL("
        in source
    )

    assert (
        ".viewport.png"
        in source
    )

    assert (
        "Visual Evidence local fallback:"
        in source
    )

    start = source.index(
        "async function handleDomInspect()"
    )

    block = source[start:]

    backend_fallback = block.index(
        "saved ="
    )

    local_visual = block.index(
        "downloadVisualEvidence(",
        backend_fallback,
    )

    assert (
        backend_fallback
        < local_visual
    )


def test_qcc_visual_local_fallback_needs_no_downloads_permission():
    import json

    manifest = json.loads(
        Path(
            "chrome_extension/qcc/manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        "downloads"
        not in manifest.get(
            "permissions",
            [],
        )
    )
