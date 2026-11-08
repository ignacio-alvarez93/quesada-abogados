import pytest

from backend.qcc.context.presentation_context import (
    QccPresentationClient,
    QccPresentationContext,
    QccPresentationExpediente,
    QccPresentationSubexpediente,
    QccPresentationTargetDocuments,
    QccSubexpedienteResolutionStatus,
    QccTargetDocument,
    QccTargetDocumentAvailability,
    QccTargetDocumentsResolutionStatus,
)
from backend.qcc.documents.opener import (
    QccDocumentOpenError,
    open_target_document,
    resolve_target_document,
)


def _context(documents):
    return QccPresentationContext(
        client=QccPresentationClient(
            client_id=321,
            display_name="Juan Pérez García",
        ),
        expediente=QccPresentationExpediente(
            expediente_id=1842,
            display_name="EXP-1842",
        ),
        subexpediente=QccPresentationSubexpediente(
            status=QccSubexpedienteResolutionStatus.NOT_CONFIGURED,
        ),
        target_documents=QccPresentationTargetDocuments(
            status=QccTargetDocumentsResolutionStatus.AVAILABLE,
            folder_path="/box/EXP-1842/PARA PRESENTAR",
            documents=tuple(documents),
        ),
    )


def _available_document(document_id="doc-1", path="/box/pasaporte.pdf"):
    return QccTargetDocument(
        filename="pasaporte.pdf",
        document_id=document_id,
        path=path,
        availability=QccTargetDocumentAvailability.AVAILABLE,
    )


def test_resolve_target_document_finds_exact_match():
    document = _available_document()
    context = _context([document])

    resolved = resolve_target_document(context, "doc-1")

    assert resolved is document


def test_resolve_target_document_rejects_unknown_id():
    context = _context([_available_document()])

    with pytest.raises(QccDocumentOpenError) as exc:
        resolve_target_document(context, "doc-unknown")

    assert exc.value.code == "QCC_DOCUMENT_NOT_FOUND"


def test_resolve_target_document_rejects_missing_context():
    with pytest.raises(QccDocumentOpenError) as exc:
        resolve_target_document(None, "doc-1")

    assert exc.value.code == "QCC_DOCUMENT_NOT_FOUND"


def test_resolve_target_document_rejects_empty_document_id():
    context = _context([_available_document()])

    with pytest.raises(QccDocumentOpenError) as exc:
        resolve_target_document(context, "")

    assert exc.value.code == "QCC_DOCUMENT_ID_REQUIRED"


def test_open_target_document_calls_os_opener_with_canonical_path():
    document = _available_document(path="/box/pasaporte.pdf")
    context = _context([document])

    opened_paths = []

    opened = open_target_document(
        context,
        "doc-1",
        os_opener=opened_paths.append,
        path_exists=lambda path: True,
    )

    assert opened is document
    assert opened_paths == ["/box/pasaporte.pdf"]


def test_open_target_document_rejects_unavailable_document():
    document = QccTargetDocument(
        filename="padron.pdf",
        document_id="doc-2",
        path=None,
        availability=QccTargetDocumentAvailability.UNAVAILABLE,
    )
    context = _context([document])

    with pytest.raises(QccDocumentOpenError) as exc:
        open_target_document(
            context,
            "doc-2",
            os_opener=lambda path: pytest.fail("must never open"),
        )

    assert exc.value.code == "QCC_DOCUMENT_UNAVAILABLE"


def test_open_target_document_rejects_missing_path():
    document = QccTargetDocument(
        filename="sin-ruta.pdf",
        document_id="doc-3",
        path=None,
        availability=QccTargetDocumentAvailability.AVAILABLE,
    )
    context = _context([document])

    with pytest.raises(QccDocumentOpenError) as exc:
        open_target_document(
            context,
            "doc-3",
            os_opener=lambda path: pytest.fail("must never open"),
        )

    assert exc.value.code == "QCC_DOCUMENT_PATH_MISSING"


def test_open_target_document_rejects_nonexistent_file():
    document = _available_document(document_id="doc-4", path="/box/no-existe.pdf")
    context = _context([document])

    with pytest.raises(QccDocumentOpenError) as exc:
        open_target_document(
            context,
            "doc-4",
            os_opener=lambda path: pytest.fail("must never open"),
            path_exists=lambda path: False,
        )

    assert exc.value.code == "QCC_DOCUMENT_FILE_NOT_FOUND"


def test_open_target_document_never_accepts_arbitrary_path_outside_context():
    """The caller cannot supply a path at all -- only a document_id --
    so a document outside the active target_documents set can never
    be opened through this function, regardless of what the extension
    might claim."""

    context = _context([_available_document(document_id="doc-1")])

    with pytest.raises(QccDocumentOpenError) as exc:
        open_target_document(
            context,
            "/etc/passwd",
            os_opener=lambda path: pytest.fail("must never open"),
        )

    assert exc.value.code == "QCC_DOCUMENT_NOT_FOUND"
