import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

import backend.qcc.bridge.server as bridge_server
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
    QccPresentationSession,
    QccPresentationStatus,
)


SERVER_SOURCE = Path(
    __file__
).resolve().parents[2] / "backend" / "qcc" / "bridge" / "server.py"


@pytest.fixture
def bridge():
    server = QccBridgeServer(port=0)
    server.start()

    try:
        yield server
    finally:
        server.close()


def _get_json(url: str) -> tuple[int, dict]:
    try:
        response = urlopen(url, timeout=2)
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return (exc.code, json.loads(body))

    with response:
        body = response.read().decode("utf-8")
        return (response.status, json.loads(body))


def _activate_session(
    store,
    *,
    expedient_id=1842,
    session_id="qcc-presentation-001",
):
    session = QccPresentationSession(
        session_id=session_id,
        expedient_id=expedient_id,
        client_id=321,
        procedure="REAGRUPACION_FAMILIAR_INICIAL",
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
        started_at=datetime(
            2026, 8, 22, 8, 30, tzinfo=timezone.utc
        ),
        status=QccPresentationStatus.AUTOMATING,
    )
    store.set_active_session(session)
    return session


def _complete_context_resolution():
    context = QccPresentationContext(
        client=QccPresentationClient(
            client_id=321,
            display_name="Juan Pérez García",
        ),
        expediente=QccPresentationExpediente(
            expediente_id=1842,
            display_name="EXP-1842",
        ),
        subexpediente=QccPresentationSubexpediente(
            status=QccSubexpedienteResolutionStatus.AVAILABLE,
            subexpediente_id=7,
            procedure_code="REAGRUPACION_FAMILIAR_INICIAL",
            display_name="Reagrupación familiar inicial",
        ),
        target_documents=QccPresentationTargetDocuments(
            status=QccTargetDocumentsResolutionStatus.AVAILABLE,
            folder_path="/box/EXP-1842/PARA PRESENTAR",
            documents=(
                QccTargetDocument(
                    filename="pasaporte.pdf",
                    document_id="doc-1",
                    path="/box/EXP-1842/PARA PRESENTAR/pasaporte.pdf",
                    availability=(
                        QccTargetDocumentAvailability.AVAILABLE
                    ),
                ),
                QccTargetDocument(
                    filename="empadronamiento.pdf",
                    document_id=None,
                    path=None,
                    availability=(
                        QccTargetDocumentAvailability.UNAVAILABLE
                    ),
                ),
            ),
        ),
    )

    return QccPresentationContextResolution(
        status=QccPresentationContextStatus.AVAILABLE,
        context=context,
    )


def test_no_active_session_state(bridge):
    status, payload = _get_json(
        f"http://{bridge.host}:{bridge.port}"
        "/qcc/presentation-context"
    )

    assert status == 200
    assert payload == {
        "protocol_version": 1,
        "status": "NO_ACTIVE_SESSION",
        "presentation_context": None,
        "error": None,
    }


def test_complete_context_renders_client_expediente_subexpediente_documents(
    bridge,
    monkeypatch,
):
    _activate_session(bridge.context_store, expedient_id=1842)

    resolution = _complete_context_resolution()

    captured = {}

    def fake_resolve(expediente_id, **kwargs):
        captured["expediente_id"] = expediente_id
        captured["kwargs"] = kwargs
        return resolution

    monkeypatch.setattr(
        bridge_server,
        "resolve_presentation_context",
        fake_resolve,
    )

    status, payload = _get_json(
        f"http://{bridge.host}:{bridge.port}"
        "/qcc/presentation-context"
    )

    assert status == 200
    assert payload["status"] == "AVAILABLE"

    context = payload["presentation_context"]
    assert context == resolution.context.to_payload()

    assert context["client"]["display_name"] == (
        "Juan Pérez García"
    )
    assert context["expediente"]["display_name"] == "EXP-1842"
    assert context["subexpediente"]["display_name"] == (
        "Reagrupación familiar inicial"
    )

    filenames = [
        doc["filename"]
        for doc in context["target_documents"]["documents"]
    ]
    assert filenames == [
        "pasaporte.pdf",
        "empadronamiento.pdf",
    ]

    # Exact backend path preserved, never reconstructed.
    assert context["target_documents"]["documents"][0][
        "path"
    ] == "/box/EXP-1842/PARA PRESENTAR/pasaporte.pdf"

    # Bridge delegated resolution exactly once with the
    # session's expedient_id; it never resolved client/
    # expediente/subexpediente/document logic itself.
    assert captured["expediente_id"] == 1842


def test_bridge_does_not_duplicate_business_resolution_logic():
    source = SERVER_SOURCE.read_text(encoding="utf-8")

    for forbidden_token in (
        "client_service",
        "expedient_service",
        "box_directory_service",
        "list_expediente_box_directory",
    ):
        assert forbidden_token not in source


def test_empty_target_documents_state(bridge, monkeypatch):
    _activate_session(bridge.context_store, expedient_id=1842)

    context = QccPresentationContext(
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
            documents=(),
        ),
    )

    resolution = QccPresentationContextResolution(
        status=QccPresentationContextStatus.AVAILABLE,
        context=context,
    )

    monkeypatch.setattr(
        bridge_server,
        "resolve_presentation_context",
        lambda expediente_id, **kwargs: resolution,
    )

    status, payload = _get_json(
        f"http://{bridge.host}:{bridge.port}"
        "/qcc/presentation-context"
    )

    assert status == 200
    assert payload["status"] == "AVAILABLE"
    assert (
        payload["presentation_context"]["target_documents"][
            "documents"
        ]
        == []
    )


@pytest.mark.parametrize(
    "resolution_status,error_message",
    [
        (
            QccPresentationContextStatus.EXPEDIENTE_NOT_FOUND,
            "No existe el expediente indicado: 1842",
        ),
        (
            QccPresentationContextStatus.CLIENT_NOT_FOUND,
            "No existe el cliente vinculado al expediente: 321",
        ),
    ],
)
def test_missing_context_states(
    bridge,
    monkeypatch,
    resolution_status,
    error_message,
):
    _activate_session(bridge.context_store, expedient_id=1842)

    resolution = QccPresentationContextResolution(
        status=resolution_status,
        error=error_message,
    )

    monkeypatch.setattr(
        bridge_server,
        "resolve_presentation_context",
        lambda expediente_id, **kwargs: resolution,
    )

    status, payload = _get_json(
        f"http://{bridge.host}:{bridge.port}"
        "/qcc/presentation-context"
    )

    assert status == 200
    assert payload["status"] == resolution_status.value
    assert payload["presentation_context"] is None
    assert payload["error"] == error_message


def test_resolution_error_state_does_not_leak_previous_data(
    bridge,
    monkeypatch,
):
    _activate_session(bridge.context_store, expedient_id=1842)

    monkeypatch.setattr(
        bridge_server,
        "resolve_presentation_context",
        lambda expediente_id, **kwargs: (
            1 / 0
        ),
    )

    status, payload = _get_json(
        f"http://{bridge.host}:{bridge.port}"
        "/qcc/presentation-context"
    )

    assert status == 500
    assert payload["status"] == "RESOLUTION_ERROR"
    assert payload["presentation_context"] is None
    assert payload["error"]


def test_browser_profile_key_routes_to_exact_profile_session(
    bridge,
    monkeypatch,
):
    store = bridge.browser_registry.get_or_create_store(
        "profile-A"
    )

    _activate_session(store, expedient_id=5555)

    resolution = _complete_context_resolution()

    captured = {}

    def fake_resolve(expediente_id, **kwargs):
        captured["expediente_id"] = expediente_id
        return resolution

    monkeypatch.setattr(
        bridge_server,
        "resolve_presentation_context",
        fake_resolve,
    )

    status, payload = _get_json(
        f"http://{bridge.host}:{bridge.port}"
        "/qcc/presentation-context?browser_profile_key=profile-A"
    )

    assert status == 200
    assert payload["status"] == "AVAILABLE"
    assert captured["expediente_id"] == 5555


def test_unknown_browser_profile_key_is_no_active_session(
    bridge,
):
    status, payload = _get_json(
        f"http://{bridge.host}:{bridge.port}"
        "/qcc/presentation-context?browser_profile_key=unknown-profile"
    )

    assert status == 200
    assert payload["status"] == "NO_ACTIVE_SESSION"
    assert payload["presentation_context"] is None
