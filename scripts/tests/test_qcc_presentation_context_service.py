from backend.qcc.context.presentation_context import (
    QccPresentationContextStatus,
    QccSubexpedienteResolutionStatus,
    QccTargetDocumentAvailability,
    QccTargetDocumentsResolutionStatus,
)
from backend.services import qcc_presentation_context_service as service


SYNTHETIC_EXPEDIENTE = {
    "id": 10,
    "cliente_id": 1,
    "numero_expediente": "EXP-2026-001",
    "tipo_expediente_nombre": "Residencia temporal no lucrativa",
    "subtipo_expediente_id": 5,
    "subtipo_expediente_codigo": "ARRAIGO",
    "subtipo_expediente_nombre": "Arraigo social",
}

SYNTHETIC_CLIENT = {
    "id": 1,
    "nombre": "Juan",
    "primer_apellido": "Fictício",
    "segundo_apellido": "Ejemplo",
}


def _expedient_resolver(rows):
    def resolver(expediente_id):
        return rows.get(int(expediente_id))

    return resolver


def _client_resolver(rows):
    def resolver(client_id):
        return rows.get(int(client_id))

    return resolver


def _folder_resolver(folder):
    def resolver(expediente_id, purpose):
        return folder

    return resolver


def _documents_resolver(documents):
    def resolver(folder_path):
        return documents

    return resolver


def _resolve(
    expediente_id=10,
    *,
    expedientes=None,
    clientes=None,
    folder=None,
    documents=(),
):
    return service.resolve_presentation_context(
        expediente_id,
        client_resolver=_client_resolver(
            clientes
            if clientes is not None
            else {1: SYNTHETIC_CLIENT}
        ),
        expedient_resolver=_expedient_resolver(
            expedientes
            if expedientes is not None
            else {10: SYNTHETIC_EXPEDIENTE}
        ),
        target_folder_resolver=_folder_resolver(folder),
        target_documents_resolver=_documents_resolver(documents),
    )


def test_complete_context_resolves_client_expediente_subexpediente_and_targets():
    resolution = _resolve(
        folder={"absolute_path": "/synthetic/para-presentar"},
        documents=[
            {"name": "pasaporte.pdf", "path": "/synthetic/para-presentar/pasaporte.pdf"},
            {"name": "padron.pdf", "path": "/synthetic/para-presentar/padron.pdf"},
        ],
    )

    assert resolution.status == QccPresentationContextStatus.AVAILABLE
    context = resolution.context
    assert context is not None

    assert context.client.client_id == 1
    assert context.client.display_name == "Juan Fictício Ejemplo"

    assert context.expediente.expediente_id == 10
    assert (
        context.expediente.display_name
        == "Residencia temporal no lucrativa"
    )
    assert (
        context.expediente.display_name
        != SYNTHETIC_EXPEDIENTE["numero_expediente"]
    )

    assert (
        context.subexpediente.status
        == QccSubexpedienteResolutionStatus.AVAILABLE
    )
    assert context.subexpediente.subexpediente_id == 5
    assert context.subexpediente.procedure_code == "ARRAIGO"
    assert context.subexpediente.display_name == "Arraigo social"

    assert (
        context.target_documents.status
        == QccTargetDocumentsResolutionStatus.AVAILABLE
    )
    assert len(context.target_documents.documents) == 2
    filenames = {
        document.filename
        for document in context.target_documents.documents
    }
    assert filenames == {"pasaporte.pdf", "padron.pdf"}


def test_empty_target_documents_is_valid_available_context():
    resolution = _resolve(
        folder={"absolute_path": "/synthetic/para-presentar"},
        documents=[],
    )

    assert resolution.status == QccPresentationContextStatus.AVAILABLE
    target_documents = resolution.context.target_documents
    assert (
        target_documents.status
        == QccTargetDocumentsResolutionStatus.AVAILABLE
    )
    assert target_documents.documents == ()


def test_missing_client_is_explicit_resolution_failure():
    resolution = _resolve(clientes={})

    assert (
        resolution.status
        == QccPresentationContextStatus.CLIENT_NOT_FOUND
    )
    assert resolution.context is None
    assert "cliente" in resolution.error.lower()


def test_missing_expediente_is_explicit_resolution_failure():
    resolution = _resolve(expedientes={})

    assert (
        resolution.status
        == QccPresentationContextStatus.EXPEDIENTE_NOT_FOUND
    )
    assert resolution.context is None
    assert "expediente" in resolution.error.lower()


def test_missing_subexpediente_is_not_configured_not_an_error():
    expediente = dict(SYNTHETIC_EXPEDIENTE)
    expediente["subtipo_expediente_id"] = None
    expediente["subtipo_expediente_codigo"] = None
    expediente["subtipo_expediente_nombre"] = None

    resolution = _resolve(expedientes={10: expediente})

    assert resolution.status == QccPresentationContextStatus.AVAILABLE
    assert (
        resolution.context.subexpediente.status
        == QccSubexpedienteResolutionStatus.NOT_CONFIGURED
    )
    assert resolution.context.subexpediente.subexpediente_id is None


def test_target_document_can_be_marked_unavailable():
    resolution = _resolve(
        folder={"absolute_path": "/synthetic/para-presentar"},
        documents=[
            {
                "name": "tasa.pdf",
                "path": "/synthetic/para-presentar/tasa.pdf",
                "available": False,
            },
        ],
    )

    documents = resolution.context.target_documents.documents
    assert len(documents) == 1
    assert (
        documents[0].availability
        == QccTargetDocumentAvailability.UNAVAILABLE
    )


def test_no_target_folder_configured_is_distinct_from_empty():
    resolution = _resolve(folder=None, documents=[])

    target_documents = resolution.context.target_documents
    assert (
        target_documents.status
        == QccTargetDocumentsResolutionStatus.NOT_CONFIGURED
    )
    assert target_documents.documents == ()


def test_target_folder_resolution_error_is_explicit():
    def failing_folder_resolver(expediente_id, purpose):
        raise FileNotFoundError("La carpeta PARA PRESENTAR no existe")

    resolution = service.resolve_presentation_context(
        10,
        client_resolver=_client_resolver({1: SYNTHETIC_CLIENT}),
        expedient_resolver=_expedient_resolver(
            {10: SYNTHETIC_EXPEDIENTE}
        ),
        target_folder_resolver=failing_folder_resolver,
        target_documents_resolver=_documents_resolver([]),
    )

    target_documents = resolution.context.target_documents
    assert (
        target_documents.status
        == QccTargetDocumentsResolutionStatus.RESOLUTION_ERROR
    )
    assert target_documents.error


def test_only_target_documents_are_projected_not_full_inventory():
    """Documentos fuera de la carpeta target no deben aparecer nunca.

    El resolver de documentos solo recibe la carpeta ya resuelta por
    el resolver de target; documentos de otras carpetas del expediente
    no son ni siquiera visibles para el servicio.
    """

    seen_folder_paths = []

    def recording_documents_resolver(folder_path):
        seen_folder_paths.append(folder_path)
        return [
            {"name": "solo_de_la_carpeta_target.pdf", "path": folder_path},
        ]

    resolution = service.resolve_presentation_context(
        10,
        client_resolver=_client_resolver({1: SYNTHETIC_CLIENT}),
        expedient_resolver=_expedient_resolver(
            {10: SYNTHETIC_EXPEDIENTE}
        ),
        target_folder_resolver=_folder_resolver(
            {"absolute_path": "/synthetic/para-presentar"}
        ),
        target_documents_resolver=recording_documents_resolver,
    )

    documents = resolution.context.target_documents.documents
    assert len(documents) == 1
    assert documents[0].filename == "solo_de_la_carpeta_target.pdf"
    assert seen_folder_paths == ["/synthetic/para-presentar"]


def test_paths_come_from_injected_resolver_not_reconstructed():
    canonical_path = "/synthetic/already-resolved/para-presentar"

    resolution = _resolve(
        folder={"absolute_path": canonical_path},
        documents=[
            {"name": "doc.pdf", "path": f"{canonical_path}/doc.pdf"},
        ],
    )

    target_documents = resolution.context.target_documents
    assert target_documents.folder_path == canonical_path
    assert (
        target_documents.documents[0].path
        == f"{canonical_path}/doc.pdf"
    )


def test_serialization_is_deterministic_for_same_canonical_inputs():
    first = _resolve(
        folder={"absolute_path": "/synthetic/para-presentar"},
        documents=[{"name": "doc.pdf", "path": "/synthetic/para-presentar/doc.pdf"}],
    )
    second = _resolve(
        folder={"absolute_path": "/synthetic/para-presentar"},
        documents=[{"name": "doc.pdf", "path": "/synthetic/para-presentar/doc.pdf"}],
    )

    assert first.to_payload() == second.to_payload()


def test_expediente_visible_label_is_canonical_type_not_number_or_id():
    """K/M. EXPEDIENTE visible = tipo canónico, nunca número/ID interno."""

    resolution = _resolve()
    expediente = resolution.context.expediente

    assert expediente.display_name == "Residencia temporal no lucrativa"
    assert expediente.display_name != SYNTHETIC_EXPEDIENTE["numero_expediente"]
    assert expediente.display_name != str(expediente.expediente_id)


def test_subexpediente_visible_label_is_canonical_subtype():
    """L. SUBEXPEDIENTE visible = subtipo/procedimiento canónico."""

    resolution = _resolve()
    subexpediente = resolution.context.subexpediente

    assert subexpediente.display_name == "Arraigo social"
    assert subexpediente.display_name != str(
        subexpediente.subexpediente_id
    )


def test_missing_tipo_expediente_nombre_is_explicit_failure_not_fallback_to_id():
    """El tipo canónico ausente falla de forma explícita: nunca se
    sustituye silenciosamente por el número/ID de expediente."""

    expediente = dict(SYNTHETIC_EXPEDIENTE)
    expediente["tipo_expediente_nombre"] = None

    try:
        _resolve(expedientes={10: expediente})
        raised = False
    except ValueError as exc:
        raised = True
        assert "DISPLAY_NAME_MISSING" in str(exc)

    assert raised


def test_no_automatic_upload_capability_exists_on_service_module():
    forbidden_tokens = ("upload", "subir")
    exported_names = [
        name
        for name in dir(service)
        if not name.startswith("_")
    ]

    for name in exported_names:
        lowered = name.lower()
        assert not any(
            token in lowered for token in forbidden_tokens
        )
