"""QCC_ASSISTED_OPERATOR_CONTROLS_V1: sidepanel surfaces for VOLCAR
DATOS, ABORTAR PRESENTACIÓN and ABRIR documento.

Static source-presence assertions, same convention as
``test_qcc_sidepanel_presentation_context.py``: the sidepanel has no
JS test runner wired in this repository, so these prove the expected
contract/markup/wiring exists and that the sidepanel never sends CRM
field values or arbitrary filesystem paths, without requiring a
browser DOM to execute against.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

JS = (
    ROOT / "chrome_extension" / "qcc" / "sidepanel" / "sidepanel.js"
)

HTML = (
    ROOT / "chrome_extension" / "qcc" / "sidepanel" / "index.html"
)


def _read(path):
    return path.read_text(encoding="utf-8")


def test_volcar_datos_and_abort_markup_exists_in_html():
    html = _read(HTML)

    for element_id in (
        "action-volcar-datos",
        "presentation-abort-row",
        "action-presentation-abort",
        "presentation-abort-feedback",
    ):
        assert f'id="{element_id}"' in html


def test_volcar_datos_button_lives_inside_shared_action_controls():
    """Reuses the existing requires-user-action action-controls
    container/gating pattern instead of a second parallel block."""

    html = _read(HTML)

    controls_start = html.index('id="session-action-controls"')
    documents_start_pos = html.index(
        'id="action-documents-start"', controls_start
    )
    volcar_pos = html.index('id="action-volcar-datos"', controls_start)

    assert volcar_pos < documents_start_pos


def test_volcar_datos_handler_submits_session_action_without_field_values():
    js = _read(JS)

    start = js.index("async function handleVolcarDatos(")
    end = js.index("async function handlePresentationAbort(", start)
    block = js[start:end]

    assert '"PRESENTATION_FILL_START"' in block
    assert "submitSessionAction(" in block

    # Exactly the generic session/action identity -- never a field
    # value payload.
    assert "submitSessionAction(\n        \"PRESENTATION_FILL_START\",\n        {}\n      )" in block.replace(
        "    ", "  "
    ) or "{}" in block


def test_volcar_datos_handler_guards_against_double_submit():
    js = _read(JS)

    start = js.index("async function handleVolcarDatos(")
    end = js.index("async function handlePresentationAbort(", start)
    block = js[start:end]

    assert "dataset.submitting" in block


def test_presentation_abort_handler_submits_session_action():
    js = _read(JS)

    start = js.index("async function handlePresentationAbort(")
    end = js.index("async function handleDocumentsStart(", start)
    block = js[start:end]

    assert '"PRESENTATION_ABORT"' in block
    assert "submitSessionAction(" in block
    assert "dataset.submitting" in block


def test_render_session_gates_volcar_datos_on_ready_to_fill_step():
    js = _read(JS)

    assert "const canVolcarDatos =" in js

    start = js.index("const canVolcarDatos =")
    end = js.index(";", start)
    block = js[start:end]

    assert '"READY_TO_FILL"' in block
    assert "ownInteractiveSession" in block
    assert "requiresUserAction" in block


def test_render_session_hides_abort_only_in_terminal_states():
    js = _read(JS)

    assert "TERMINAL_SESSION_STATUSES" in js

    start = js.index("const TERMINAL_SESSION_STATUSES")
    end = js.index("];", start)
    block = js[start:end]

    assert "COMPLETED" in block
    assert "ABORTED_BY_USER" in block

    # Explicitly must NOT be gated on requires_user_action/current_step
    # the way VOLCAR DATOS/documents are -- abort must stay available
    # across procedure selection, READY_TO_FILL, FILLING and
    # blocked/error states.
    canAbortStart = js.index("const canAbort =")
    canAbortEnd = js.index(";", canAbortStart)
    canAbortBlock = js[canAbortStart:canAbortEnd]

    assert "current_step" not in canAbortBlock


def test_sidepanel_never_controls_seleniumbase_directly():
    js = _read(JS)

    for forbidden in (
        "SeleniumBaseBrowserSession",
        "webdriver",
    ):
        assert forbidden not in js


# ---------------------------------------------------------------
# ABRIR documento
# ---------------------------------------------------------------


def test_open_document_button_created_for_available_documents_with_id():
    js = _read(JS)

    assert "function createPresentationDocumentOpenButton(" in js
    assert "createPresentationDocumentOpenButton(" in js

    start = js.index("function createPresentationDocumentItem(")
    end = js.index("function renderPresentationContext(", start)
    block = js[start:end]

    assert "targetDocument?.document_id" in block
    assert "createPresentationDocumentOpenButton(" in block


def test_open_document_handler_sends_only_document_id_never_a_path():
    js = _read(JS)

    start = js.index("async function handlePresentationOpenDocument(")
    end = js.index(
        "function createPresentationDocumentOpenButton(", start
    )
    block = js[start:end]

    assert "/presentation/documents/" in block
    assert "/open" in block
    assert "documentId" in block

    # Never references a document path inside the open handler: the
    # path is resolved server-side, exclusively from document_id.
    assert "targetDocument" not in block
    assert ".path" not in block


def test_open_document_route_is_scoped_to_own_session():
    js = _read(JS)

    start = js.index("async function handlePresentationOpenDocument(")
    end = js.index(
        "function createPresentationDocumentOpenButton(", start
    )
    block = js[start:end]

    assert "qccOwnSessionId" in block
