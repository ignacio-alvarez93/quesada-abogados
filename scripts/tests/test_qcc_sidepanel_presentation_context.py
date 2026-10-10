from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

JS = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "sidepanel.js"
)

HTML = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "sidepanel"
    / "index.html"
)

MANIFEST = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "manifest.json"
)

SERVICE_WORKER = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "background"
    / "service_worker.js"
)


def _read(path):
    return path.read_text(
        encoding="utf-8"
    )


def test_presentation_context_surface_exists_in_html():
    html = _read(HTML)

    for element_id in (
        "presentation-context-loading",
        "presentation-context-unavailable",
        "presentation-context-unavailable-title",
        "presentation-context-unavailable-description",
        "presentation-context-error",
        "presentation-context-error-description",
        "presentation-context-ready",
        "presentation-client",
        "presentation-expediente",
        "presentation-subexpediente",
        "presentation-folder-row",
        "presentation-folder-path",
        "presentation-copy-folder",
        "presentation-documents-empty",
        "presentation-documents-list",
    ):
        assert (
            f'id="{element_id}"'
            in html
        )


def test_presentation_context_endpoint_is_known():
    js = _read(JS)

    assert (
        "/qcc/presentation-context"
        in js
    )

    assert (
        "function qccPresentationContextUrl("
        in js
    )

    assert (
        "encodeURIComponent("
        in js
    )


def test_refresh_presentation_context_handles_all_bridge_states():
    js = _read(JS)

    start = js.index(
        "async function refreshPresentationContext("
    )

    end = js.index(
        "function hideTeachHumanOnlyPanel(",
        start,
    )

    block = js[start:end]

    assert '"AVAILABLE"' in block
    assert '"NO_ACTIVE_SESSION"' in block
    assert '"EXPEDIENTE_NOT_FOUND"' in block
    assert '"CLIENT_NOT_FOUND"' in block

    assert "renderPresentationContext(" in block
    assert "showPresentationUnavailable(" in block
    assert "showPresentationError(" in block


def test_render_presentation_context_projects_client_expediente_subexpediente():
    js = _read(JS)

    start = js.index(
        "function renderPresentationContext("
    )

    end = js.index(
        "async function refreshPresentationContext(",
        start,
    )

    block = js[start:end]

    assert "context?.client?.display_name" in block
    assert "context?.expediente?.display_name" in block
    assert "context?.subexpediente" in block
    assert "presentation-client" in block
    assert "presentation-expediente" in block
    assert "presentation-subexpediente" in block


def test_render_presentation_context_projects_target_documents():
    js = _read(JS)

    start = js.index(
        "function renderPresentationContext("
    )

    end = js.index(
        "async function refreshPresentationContext(",
        start,
    )

    block = js[start:end]

    assert "targetDocuments.documents" in block
    assert "presentation-documents-list" in block
    assert "presentation-documents-empty" in block
    assert "createPresentationDocumentItem(" in block


def test_document_item_renders_filename_as_text_content():
    js = _read(JS)

    start = js.index(
        "function createPresentationDocumentItem("
    )

    end = js.index(
        "function renderPresentationContext(",
        start,
    )

    block = js[start:end]

    assert "targetDocument?.filename" in block
    assert ".textContent =" in block

    # Backend values are never injected through unsafe HTML.
    assert "innerHTML" not in block


def test_document_item_adds_copy_button_only_when_path_available():
    js = _read(JS)

    start = js.index(
        "function createPresentationDocumentItem("
    )

    end = js.index(
        "function renderPresentationContext(",
        start,
    )

    block = js[start:end]

    assert "targetDocument?.path" in block
    assert "if (path) {" in block
    assert "createPresentationDocumentCopyButton(" in block


def test_copy_button_copies_exact_backend_path_via_clipboard():
    js = _read(JS)

    start = js.index(
        "async function handlePresentationCopyPath("
    )

    end = js.index(
        "function createPresentationDocumentCopyButton(",
        start,
    )

    block = js[start:end]

    assert "navigator.clipboard.writeText(" in block
    assert "path" in block

    # Never reconstructed/altered: the exact argument is copied.
    assert "path +" not in block
    assert "+ path" not in block


def test_copy_button_fails_visibly_without_throwing():
    js = _read(JS)

    start = js.index(
        "async function handlePresentationCopyPath("
    )

    end = js.index(
        "function createPresentationDocumentCopyButton(",
        start,
    )

    block = js[start:end]

    assert "try {" in block
    assert "} catch (_) {" in block
    assert "qcc-presentation-document-copy--failed" in block
    assert "qcc-presentation-document-copy--done" in block


def test_folder_copy_button_is_wired_from_backend_value():
    js = _read(JS)

    start = js.index(
        "async function initializeQccShell("
    )

    end = js.index(
        "qccOwnBrowserProfileKey =",
        start,
    )

    block = js[start:end]

    assert '"presentation-copy-folder"' in block
    assert "qccPresentationFolderPath" in block
    assert "handlePresentationCopyPath(" in block


def test_stale_presentation_context_is_cleared_on_unavailable_and_error():
    js = _read(JS)

    unavailable_start = js.index(
        "function showPresentationUnavailable("
    )

    unavailable_end = js.index(
        "function showPresentationError(",
        unavailable_start,
    )

    unavailable_block = js[
        unavailable_start:unavailable_end
    ]

    assert (
        "qccPresentationFolderPath = null"
        in unavailable_block
    )

    assert (
        "clearPresentationDocumentsList()"
        in unavailable_block
    )

    error_start = unavailable_end
    error_end = js.index(
        "async function handlePresentationCopyPath(",
        error_start,
    )

    error_block = js[error_start:error_end]

    assert (
        "qccPresentationFolderPath = null"
        in error_block
    )

    assert (
        "clearPresentationDocumentsList()"
        in error_block
    )


def test_check_context_refreshes_presentation_context_with_viewed_profile():
    js = _read(JS)

    start = js.index(
        "async function checkContext("
    )

    end = js.index(
        "async function checkBridgeHealth(",
        start,
    )

    block = js[start:end]

    assert "refreshPresentationContext(" in block
    assert "qccViewedBrowserProfileKey" in block
    assert "showPresentationError(" in block
    assert "showPresentationUnavailable(" in block


def test_bridge_down_clears_presentation_context():
    js = _read(JS)

    start = js.index(
        "async function checkBridgeHealth("
    )

    end = js.index(
        "async function handleDocumentsStart(",
        start,
    )

    block = js[start:end]

    assert "showPresentationUnavailable(" in block


def test_no_automatic_upload_controls_added():
    html = _read(HTML)

    assert 'type="file"' not in html

    js = _read(JS)

    for forbidden_token in (
        "showOpenFilePicker",
        "showPicker(",
        "webkitdirectory",
    ):
        assert forbidden_token not in js


def test_sidepanel_has_no_direct_db_or_box_logic():
    js = _read(JS)

    for forbidden_token in (
        "client_service",
        "expedient_service",
        "box_directory_service",
        "SELECT ",
        "box.com",
    ):
        assert forbidden_token not in js


def test_service_worker_is_not_modified_by_this_feature():
    assert SERVICE_WORKER.is_file()

    js = _read(SERVICE_WORKER)

    assert "presentation-context" not in js
    assert "qccPresentationContextUrl" not in js
    assert "QccPresentationFolderPath" not in js


def test_manifest_is_not_modified_by_this_feature():
    manifest = _read(MANIFEST)

    assert "clipboardWrite" not in manifest
    assert "clipboard-write" not in manifest
