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
