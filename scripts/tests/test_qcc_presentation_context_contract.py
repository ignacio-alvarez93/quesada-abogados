import pytest

from backend.qcc.context.presentation_context import (
    QCC_PRESENTATION_CONTEXT_SCHEMA_VERSION,
    QCC_PRESENTATION_CONTEXT_TYPE,
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


def _client():
    return QccPresentationClient(
        client_id=1,
        display_name="Cliente Fictício",
    )


def _expediente():
    return QccPresentationExpediente(
        expediente_id=10,
        display_name="EXP-2026-001",
    )


def _subexpediente_available():
    return QccPresentationSubexpediente(
        status=QccSubexpedienteResolutionStatus.AVAILABLE,
        subexpediente_id=5,
        procedure_code="ARRAIGO",
        display_name="Arraigo social",
    )


def _target_documents_available(documents=()):
    return QccPresentationTargetDocuments(
        status=QccTargetDocumentsResolutionStatus.AVAILABLE,
        documents=tuple(documents),
        folder_path="/synthetic/para-presentar",
    )


def test_complete_context_payload_contains_all_sections():
    document = QccTargetDocument(
        filename="pasaporte.pdf",
        document_id="doc-1",
        path="/synthetic/para-presentar/pasaporte.pdf",
        availability=QccTargetDocumentAvailability.AVAILABLE,
    )

    context = QccPresentationContext(
        client=_client(),
        expediente=_expediente(),
        subexpediente=_subexpediente_available(),
        target_documents=_target_documents_available([document]),
    )

    payload = context.to_payload()

    assert payload["schema_version"] == (
        QCC_PRESENTATION_CONTEXT_SCHEMA_VERSION
    )
    assert payload["context_type"] == QCC_PRESENTATION_CONTEXT_TYPE
    assert payload["client"]["client_id"] == 1
    assert payload["expediente"]["expediente_id"] == 10
    assert payload["subexpediente"]["subexpediente_id"] == 5
    assert payload["subexpediente"]["procedure_code"] == "ARRAIGO"
    assert len(payload["target_documents"]["documents"]) == 1
    assert (
        payload["target_documents"]["documents"][0]["filename"]
        == "pasaporte.pdf"
    )


def test_empty_target_documents_is_valid():
    target_documents = _target_documents_available([])

    assert (
        target_documents.status
        == QccTargetDocumentsResolutionStatus.AVAILABLE
    )
    assert target_documents.documents == ()

    payload = target_documents.to_payload()
    assert payload["documents"] == []
    assert payload["error"] is None


def test_target_documents_not_configured_rejects_documents():
    with pytest.raises(ValueError):
        QccPresentationTargetDocuments(
            status=QccTargetDocumentsResolutionStatus.NOT_CONFIGURED,
            documents=(
                QccTargetDocument(filename="x.pdf"),
            ),
        )


def test_target_documents_resolution_error_requires_message():
    with pytest.raises(ValueError):
        QccPresentationTargetDocuments(
            status=(
                QccTargetDocumentsResolutionStatus.RESOLUTION_ERROR
            ),
        )

    target_documents = QccPresentationTargetDocuments(
        status=QccTargetDocumentsResolutionStatus.RESOLUTION_ERROR,
        error="No se puede acceder a la carpeta",
    )
    assert target_documents.error == (
        "No se puede acceder a la carpeta"
    )


def test_target_document_unavailable_is_representable():
    document = QccTargetDocument(
        filename="tasa.pdf",
        availability=QccTargetDocumentAvailability.UNAVAILABLE,
    )

    assert (
        document.availability
        == QccTargetDocumentAvailability.UNAVAILABLE
    )
    assert document.to_payload()["availability"] == "UNAVAILABLE"


def test_subexpediente_not_configured_rejects_fields():
    with pytest.raises(ValueError):
        QccPresentationSubexpediente(
            status=QccSubexpedienteResolutionStatus.NOT_CONFIGURED,
            display_name="No debería permitirse",
        )


def test_subexpediente_available_requires_display_name():
    with pytest.raises(ValueError):
        QccPresentationSubexpediente(
            status=QccSubexpedienteResolutionStatus.AVAILABLE,
            subexpediente_id=1,
        )


def test_missing_client_is_explicit_resolution_failure():
    resolution = QccPresentationContextResolution(
        status=QccPresentationContextStatus.CLIENT_NOT_FOUND,
        error="No existe el cliente vinculado al expediente: 999",
    )

    assert resolution.context is None
    assert resolution.to_payload()["status"] == "CLIENT_NOT_FOUND"
    assert resolution.to_payload()["context"] is None


def test_missing_expediente_is_explicit_resolution_failure():
    resolution = QccPresentationContextResolution(
        status=QccPresentationContextStatus.EXPEDIENTE_NOT_FOUND,
        error="No existe el expediente indicado: 999",
    )

    assert resolution.context is None
    assert (
        resolution.to_payload()["status"]
        == "EXPEDIENTE_NOT_FOUND"
    )


def test_resolution_available_requires_context():
    with pytest.raises(ValueError):
        QccPresentationContextResolution(
            status=QccPresentationContextStatus.AVAILABLE,
        )


def test_resolution_failure_rejects_context():
    with pytest.raises(ValueError):
        QccPresentationContextResolution(
            status=QccPresentationContextStatus.CLIENT_NOT_FOUND,
            context=QccPresentationContext(
                client=_client(),
                expediente=_expediente(),
                subexpediente=_subexpediente_available(),
                target_documents=_target_documents_available(),
            ),
            error="irrelevante",
        )


def test_serialization_is_deterministic_for_same_inputs():
    def build():
        return QccPresentationContext(
            client=_client(),
            expediente=_expediente(),
            subexpediente=_subexpediente_available(),
            target_documents=_target_documents_available(
                [
                    QccTargetDocument(
                        filename="pasaporte.pdf",
                        document_id="doc-1",
                        path="/synthetic/para-presentar/pasaporte.pdf",
                    ),
                ]
            ),
        )

    assert build().to_payload() == build().to_payload()


def test_no_upload_capability_exists_on_contract_module():
    import backend.qcc.context.presentation_context as module

    forbidden_tokens = ("upload", "subir")
    exported_names = [
        name
        for name in dir(module)
        if not name.startswith("_")
    ]

    for name in exported_names:
        lowered = name.lower()
        assert not any(
            token in lowered for token in forbidden_tokens
        )
