import json
from pathlib import Path


QCC_DIR = Path(
    "chrome_extension/qcc"
)


def test_dom_inspect_uses_on_demand_scripting():
    manifest = json.loads(
        (
            QCC_DIR
            / "manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        "scripting"
        in manifest[
            "permissions"
        ]
    )

    assert (
        "activeTab"
        in manifest[
            "permissions"
        ]
    )

    # No inyección permanente.
    assert (
        "content_scripts"
        not in manifest
    )


def test_dom_inspect_has_no_permanent_global_site_access():
    manifest = json.loads(
        (
            QCC_DIR
            / "manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        manifest[
            "host_permissions"
        ]
        == [
            "http://127.0.0.1:8766/*"
        ]
    )

    assert (
        manifest[
            "optional_host_permissions"
        ]
        == [
            "http://*/*",
            "https://*/*",
        ]
    )

    assert (
        "<all_urls>"
        not in json.dumps(
            manifest
        )
    )


def test_service_worker_owns_dom_capture():
    source = (
        QCC_DIR
        / "background"
        / "service_worker.js"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "captureDomFrame",
        "inspectActiveTabDom",
        "chrome.tabs.query",
        "chrome.scripting.executeScript",
        "allFrames",
        'world:\n        "ISOLATED"',
        "document.documentElement",
        ".outerHTML",
        "querySelectorAll",
        "shadowRoot",
        "getBoundingClientRect",
        "rectOf",
        "viewportOf",
        "inner_width",
        "device_pixel_ratio",
        "QCC_DOM_INSPECT",
    )

    for token in required:
        assert token in source


def test_inspected_page_capture_is_read_only():
    source = (
        QCC_DIR
        / "background"
        / "service_worker.js"
    ).read_text(
        encoding="utf-8"
    )

    forbidden = (
        ".click()",
        ".click(",
        "dispatchEvent(",
        "setAttribute(",
        "removeAttribute(",
        ".value =",
        ".checked =",
        "appendChild(",
        "insertAdjacent",
        "chrome.tabs.update",
    )

    for token in forbidden:
        assert token not in source


def test_sidepanel_does_not_directly_control_target_page():
    source = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_DOM_INSPECT"
        in source
    )

    assert (
        "chrome.runtime.sendMessage"
        in source
    )

    assert (
        "chrome.scripting"
        not in source
    )

    assert (
        "executeScript"
        not in source
    )


def test_dom_tool_is_available_outside_runtime_session():
    html = (
        QCC_DIR
        / "sidepanel"
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'id="tool-dom-inspect"'
        in html
    )

    assert (
        "Arquitectura DOM"
        in html
    )

    session_close = html.index(
        "</section>",
        html.index(
            'id="qcc-session-state"'
        ),
    )

    tool_position = html.index(
        'id="dom-tools-card"'
    )

    assert (
        tool_position
        > session_close
    )


def test_dom_capture_is_downloaded_locally():
    source = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "downloadDomCapture",
        "new Blob(",
        "URL.createObjectURL",
        'document.createElement(\n      "a"',
        "qcc_dom_capture_",
        ".json",
    )

    for token in required:
        assert token in source


def test_dom_inspect_requests_optional_host_permission_from_button_flow():
    source = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "QCC_DOM_OPTIONAL_ORIGINS",
        '"http://*/*"',
        '"https://*/*"',
        "requestDomInspectionPermission",
        "chrome.permissions.request",
        "QCC_DOM_HOST_PERMISSION_DENIED",
    )

    for token in required:
        assert token in source


def test_dom_inspect_requests_permission_before_capture_message():
    source = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        "async function handleDomInspect()"
    )

    block = source[
        start:
    ]

    permission_position = (
        block.index(
            "requestDomInspectionPermission()"
        )
    )

    capture_position = (
        block.index(
            "chrome.runtime.sendMessage"
        )
    )

    assert (
        permission_position
        < capture_position
    )


def test_dom_capture_posts_to_site_architecture_bridge():
    source = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "QCC_SITE_ARCHITECTURE_CAPTURE_URL",
        "/qcc/site-architecture/capture",
        "submitSiteArchitectureCapture",
        "protocol_version: 1",
        "capture",
    )

    for token in required:
        assert token in source


def test_site_architecture_upload_has_dedicated_timeout():
    source = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_SITE_ARCHITECTURE_REQUEST_TIMEOUT_MS"
        in source
    )

    assert "30000" in source

    assert (
        "timeoutMs = QCC_REQUEST_TIMEOUT_MS"
        in source
    )


def test_dom_capture_keeps_local_download_as_fail_open_fallback():
    source = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        "async function handleDomInspect()"
    )

    block = source[start:]

    submit_position = block.index(
        "submitSiteArchitectureCapture"
    )

    download_position = block.index(
        "downloadDomCapture"
    )

    assert (
        submit_position
        < download_position
    )

    assert "backendResult" in block

    assert (
        "Bridge no disponible"
        in block
    )


def test_visual_style_probe_is_selective():
    source = (
        QCC_DIR
        / "background"
        / "service_worker.js"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "captureVisualStyleProbe",
        "inspectActiveTabVisualStyle",
        "QCC_VISUAL_STYLE_PROBE",
        "window.getComputedStyle",
        "computed_style",
        "font_family",
        "font_size",
        "background_color",
        "border_top",
        "padding_left",
    )

    for token in required:
        assert token in source

    start = source.index(
        "function captureVisualStyleProbe"
    )

    end = source.index(
        "async function inspectActiveTabVisualStyle",
        start,
    )

    block = source[start:end]

    assert "querySelectorAll" in block

    assert (
        'querySelectorAll(\n        "*"'
        not in block
    )

    assert "outerHTML" not in block


def test_visual_style_probe_uses_main_frame_only():
    source = (
        QCC_DIR
        / "background"
        / "service_worker.js"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        "async function inspectActiveTabVisualStyle"
    )

    end = source.index(
        "async function inspectActiveTabDom",
        start,
    )

    block = source[start:end]

    assert "chrome.scripting.executeScript" in block
    assert "args:" in block
    assert "allFrames" not in block


def test_sidepanel_exposes_visual_style_probe():
    html = (
        QCC_DIR
        / "sidepanel"
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    source = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert 'id="tool-visual-selectors"' in html
    assert 'id="tool-visual-style-probe"' in html
    assert 'id="visual-style-feedback"' in html

    required = (
        "handleVisualStyleProbe",
        "QCC_VISUAL_STYLE_PROBE",
        "downloadVisualStyleProbe",
        "requestDomInspectionPermission",
    )

    for token in required:
        assert token in source


def test_dom_capture_automatically_enriches_with_visual_style_probe():
    source = (
        QCC_DIR
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    start = source.index(
        "async function handleDomInspect()"
    )

    block = source[start:]

    required = (
        "buildAutomaticVisualSelectors",
        "QCC_VISUAL_STYLE_PROBE",
        "capture.visual_probe",
        "submitSiteArchitectureCapture",
    )

    for token in required:
        assert token in block

    auto_position = block.index(
        "buildAutomaticVisualSelectors"
    )

    probe_position = block.index(
        '"QCC_VISUAL_STYLE_PROBE"'
    )

    enrich_position = block.index(
        "capture.visual_probe"
    )

    submit_position = block.index(
        "submitSiteArchitectureCapture"
    )

    assert (
        auto_position
        < probe_position
        < enrich_position
        < submit_position
    )


def test_visual_probe_has_reconstruction_style_contract():
    source = (
        QCC_DIR
        / "background"
        / "service_worker.js"
    ).read_text(
        encoding="utf-8"
    )

    required = (
        "background_image",
        "background_position",
        "background_repeat",
        "background_size",
        "outline",
        "outline_offset",
        "overflow",
        "white_space",
        "vertical_align",
        "text_decoration_color",
        "text_decoration_style",
        "transform",
    )

    for token in required:
        assert token in source
