import json
from pathlib import Path


MANIFEST = Path(
    "chrome_extension/qcc/manifest.json"
)

SIDEPANEL = Path(
    "chrome_extension/qcc/sidepanel/sidepanel.js"
)


def _source():
    return SIDEPANEL.read_text(
        encoding="utf-8"
    )


def test_page_capture_is_optional():
    manifest = json.loads(
        MANIFEST.read_text(
            encoding="utf-8"
        )
    )

    assert (
        "pageCapture"
        in manifest.get(
            "optional_permissions",
            [],
        )
    )

    assert (
        "pageCapture"
        not in manifest.get(
            "permissions",
            [],
        )
    )


def test_page_capture_requested_from_dom_inspection_gesture():
    source = _source()

    start = source.index(
        "async function requestDomInspectionPermission()"
    )

    end = source.index(
        "async function handleDomInspect()"
    )

    block = source[start:end]

    assert (
        '"pageCapture"'
        in block
    )

    assert (
        "chrome.permissions.request"
        in block
    )


def test_mhtml_capture_uses_page_capture_without_scroll():
    source = _source()

    start = source.index(
        "QCC_PAGE_MHTML_CAPTURE_V1"
    )

    end = source.index(
        "QCC_PAGE_MHTML_UPLOAD_V1"
    )

    block = source[start:end]

    assert (
        "chrome.pageCapture"
        in block
    )

    assert (
        ".saveAsMHTML({"
        in block
    )

    assert (
        "scrollTo("
        not in block
    )

    # Prohibimos uso real de la API debugger.
    # Una mención documental en comentarios no cuenta.
    assert (
        "chrome.debugger.attach"
        not in block
    )

    assert (
        "chrome.debugger.sendCommand"
        not in block
    )

    assert (
        "chrome.debugger.detach"
        not in block
    )


def test_mhtml_upload_contract():
    source = _source()

    required = (
        "QCC_SITE_ARCHITECTURE_PAGE_ARTIFACT_URL",
        "QCC_PAGE_MHTML_UPLOAD_V1",
        '"X-QCC-Page-Kind"',
        '"multipart/related"',
        "submitPageArchiveArtifact(",
    )

    for token in required:
        assert token in source


def test_mhtml_bridge_offline_fallback():
    source = _source()

    required = (
        "QCC_PAGE_MHTML_LOCAL_FALLBACK_V1",
        "QCC_PAGE_MHTML_LOCAL_DOWNLOAD_WIRED_V1",
        "downloadPageArchive(",
        '".mhtml"',
        "mhtml: DESCARGADO",
    )

    for token in required:
        assert token in source


def test_mhtml_status_visible_in_dom_feedback():
    source = _source()

    start = source.index(
        "async function handleDomInspect()"
    )

    block = source[start:]

    assert (
        "pageArchiveStatus"
        in block
    )

    assert (
        "mhtml: GUARDADO"
        in block
    )

    assert (
        "+ pageArchiveStatus"
        in block
    )



def test_mhtml_protocol_version_is_defined():
    source = _source()

    assert (
        "const QCC_PROTOCOL_VERSION = 1;"
        in source
    )

    start = source.index(
        "QCC_PAGE_MHTML_UPLOAD_V1"
    )

    end = source.index(
        "QCC_PAGE_MHTML_LOCAL_FALLBACK_V1"
    )

    block = source[start:end]

    assert (
        "String("
        in block
    )

    assert (
        "QCC_PROTOCOL_VERSION"
        in block
    )
