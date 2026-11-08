import json
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import backend.qcc.bridge.server as bridge_server
import backend.qcc.documents.opener as document_opener
from backend.qcc.bridge.server import QccBridgeServer
from backend.qcc.context.presentation_context import (
    QccPresentationClient,
    QccPresentationContext,
    QccPresentationContextResolution,
    QccPresentationContextStatus,
    QccPresentationExpediente,
    QccPresentationSubexpediente,
    QccPresentationTargetDocuments,
    QccSubexpedienteResolutionStatus,
    QccTargetDocument,
    QccTargetDocumentAvailability,
    QccTargetDocumentsResolutionStatus,
)
from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)


@pytest.fixture
def bridge():
    server = QccBridgeServer(port=0)
    server.start()

    try:
        yield server
    finally:
        server.close()


def _post(url, payload):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        response = urlopen(request, timeout=2)
    except HTTPError as exc:
        return (exc.code, json.loads(exc.read().decode("utf-8")))

    with response:
        return (response.status, json.loads(response.read().decode("utf-8")))


def _activate_session(store, *, expedient_id=1842, session_id="qcc-doc-open-001"):
    session = QccPresentationSession(
        session_id=session_id,
        expedient_id=expedient_id,
        client_id=321,
        procedure="EX01",
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime(2026, 8, 22, 8, 30, tzinfo=timezone.utc),
        status=QccPresentationStatus.WAITING_USER,
        current_step="READY_TO_FILL",
        progress=35,
        requires_user_action=True,
    )
    store.set_active_session(session)
    return session


def _resolution_with_documents(documents):
    context = QccPresentationContext(
        client=QccPresentationClient(client_id=321, display_name="Juan Pérez"),
        expediente=QccPresentationExpediente(expediente_id=1842, display_name="EXP-1842"),
        subexpediente=QccPresentationSubexpediente(
            status=QccSubexpedienteResolutionStatus.NOT_CONFIGURED,
        ),
        target_documents=QccPresentationTargetDocuments(
            status=QccTargetDocumentsResolutionStatus.AVAILABLE,
            folder_path="/box/EXP-1842/PARA PRESENTAR",
            documents=tuple(documents),
        ),
    )

    return QccPresentationContextResolution(
        status=QccPresentationContextStatus.AVAILABLE,
        context=context,
    )


def _open_url(session_id, document_id, server):
    return (
        f"http://{server.host}:{server.port}"
        f"/qcc/session/{session_id}/presentation/documents/{document_id}/open"
    )


def test_open_document_requires_active_session(bridge):
    status, payload = _post(
        _open_url("qcc-doc-open-001", "doc-1", bridge),
        {"protocol_version": QCC_PROTOCOL_VERSION},
    )

    assert status == 409
    assert payload["error"] == "QCC_DOCUMENT_SESSION_NOT_ACTIVE"


def test_open_document_rejects_wrong_session(bridge):
    _activate_session(bridge.context_store)

    status, payload = _post(
        _open_url("other-session", "doc-1", bridge),
        {"protocol_version": QCC_PROTOCOL_VERSION},
    )

    assert status == 409
    assert payload["error"] == "QCC_DOCUMENT_SESSION_NOT_ACTIVE"


def test_open_document_opens_available_document(bridge, monkeypatch, tmp_path):
    _activate_session(bridge.context_store)

    pasaporte = tmp_path / "pasaporte.pdf"
    pasaporte.write_bytes(b"%PDF-1.4")

    resolution = _resolution_with_documents(
        [
            QccTargetDocument(
                filename="pasaporte.pdf",
                document_id="doc-1",
                path=str(pasaporte),
                availability=QccTargetDocumentAvailability.AVAILABLE,
            )
        ]
    )

    monkeypatch.setattr(
        bridge_server,
        "resolve_presentation_context",
        lambda expediente_id, **kwargs: resolution,
    )

    opened = []

    with patch.object(
        document_opener.os,
        "startfile",
        create=True,
        new=lambda path: opened.append(path),
    ):
        status, payload = _post(
            _open_url("qcc-doc-open-001", "doc-1", bridge),
            {"protocol_version": QCC_PROTOCOL_VERSION},
        )

    assert status == 200
    assert payload == {"ok": True, "document_id": "doc-1", "filename": "pasaporte.pdf"}
    assert opened == [str(pasaporte)]


def test_open_document_rejects_unknown_document_id(bridge, monkeypatch, tmp_path):
    _activate_session(bridge.context_store)

    resolution = _resolution_with_documents(
        [
            QccTargetDocument(
                filename="pasaporte.pdf",
                document_id="doc-1",
                path=str(tmp_path / "pasaporte.pdf"),
                availability=QccTargetDocumentAvailability.AVAILABLE,
            )
        ]
    )

    monkeypatch.setattr(
        bridge_server,
        "resolve_presentation_context",
        lambda expediente_id, **kwargs: resolution,
    )

    status, payload = _post(
        _open_url("qcc-doc-open-001", "doc-does-not-exist", bridge),
        {"protocol_version": QCC_PROTOCOL_VERSION},
    )

    assert status == 404
    assert payload["error"] == "QCC_DOCUMENT_NOT_FOUND"


def test_open_document_rejects_unavailable_document(bridge, monkeypatch):
    _activate_session(bridge.context_store)

    resolution = _resolution_with_documents(
        [
            QccTargetDocument(
                filename="padron.pdf",
                document_id="doc-2",
                path=None,
                availability=QccTargetDocumentAvailability.UNAVAILABLE,
            )
        ]
    )

    monkeypatch.setattr(
        bridge_server,
        "resolve_presentation_context",
        lambda expediente_id, **kwargs: resolution,
    )

    status, payload = _post(
        _open_url("qcc-doc-open-001", "doc-2", bridge),
        {"protocol_version": QCC_PROTOCOL_VERSION},
    )

    assert status == 409
    assert payload["error"] == "QCC_DOCUMENT_UNAVAILABLE"


def test_open_document_rejects_nonexistent_file_on_disk(bridge, monkeypatch, tmp_path):
    _activate_session(bridge.context_store)

    missing = tmp_path / "no-existe.pdf"

    resolution = _resolution_with_documents(
        [
            QccTargetDocument(
                filename="no-existe.pdf",
                document_id="doc-3",
                path=str(missing),
                availability=QccTargetDocumentAvailability.AVAILABLE,
            )
        ]
    )

    monkeypatch.setattr(
        bridge_server,
        "resolve_presentation_context",
        lambda expediente_id, **kwargs: resolution,
    )

    status, payload = _post(
        _open_url("qcc-doc-open-001", "doc-3", bridge),
        {"protocol_version": QCC_PROTOCOL_VERSION},
    )

    assert status == 404
    assert payload["error"] == "QCC_DOCUMENT_FILE_NOT_FOUND"


def test_open_document_fails_closed_on_context_mismatch(bridge, monkeypatch):
    _activate_session(bridge.context_store)

    resolution = QccPresentationContextResolution(
        status=QccPresentationContextStatus.EXPEDIENTE_NOT_FOUND,
        error="No existe el expediente indicado: 1842",
    )

    monkeypatch.setattr(
        bridge_server,
        "resolve_presentation_context",
        lambda expediente_id, **kwargs: resolution,
    )

    status, payload = _post(
        _open_url("qcc-doc-open-001", "doc-1", bridge),
        {"protocol_version": QCC_PROTOCOL_VERSION},
    )

    assert status == 409
    assert payload["error"] == "QCC_DOCUMENT_CONTEXT_MISMATCH"


def test_open_document_never_sends_arbitrary_path(bridge):
    """The route contract only ever carries document_id in the URL --
    there is no request body field through which a path could be
    supplied, even if the extension tried to."""

    import inspect

    source = inspect.getsource(bridge_server)

    start = source.index("is_document_open_route = (")
    end = source.index("# ---------------------------------------------\n        # Side Panel -> Bridge:")

    block = source[start:end]

    assert "payload.get(\"path\")" not in block
    assert "payload[\"path\"]" not in block
