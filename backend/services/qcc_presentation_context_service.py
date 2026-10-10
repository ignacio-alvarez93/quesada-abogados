"""
Ensamblado del QccPresentationContext.

Ensambla cliente + expediente + subexpediente (subtipo) + documentos
objetivo de UNA presentación administrativa concreta, a partir de las
autoridades canónicas ya existentes:

- backend.services.client_service          -> cliente
- backend.services.expedient_service        -> expediente/subtipo y
                                                carpeta PARA PRESENTAR
                                                (box_para_presentar_folder_path)
- backend.services.list_expediente_box_directory
                                             -> listado de documentos
                                                dentro de esa carpeta

Este servicio NO reconstruye rutas físicas, NO crea/mueve/borra
documentos, NO sube documentos automáticamente y NO accede a Box en
vivo (solo lee cachés locales y disco, igual que las autoridades que
reutiliza). No es fuente de verdad: proyecta autoridades existentes.
"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Mapping,
    Sequence,
)

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
from backend.services import client_service
from backend.services import expedient_service
from backend.services import list_expediente_box_directory as box_directory_service


PRESENTATION_TARGET_PURPOSE = "PRESENTACION"


ClientResolver = Callable[[int], Mapping[str, Any] | None]
ExpedientResolver = Callable[[int], Mapping[str, Any] | None]
TargetFolderResolver = Callable[
    [int, str],
    Mapping[str, Any] | None,
]
TargetDocumentsResolver = Callable[
    [str],
    Sequence[Mapping[str, Any]],
]


def _default_client_resolver(
    client_id: int,
) -> Mapping[str, Any] | None:
    return client_service.get_client_by_id(client_id)


def _default_expedient_resolver(
    expediente_id: int,
) -> Mapping[str, Any] | None:
    return expedient_service.get_expediente(expediente_id)


def _default_target_folder_resolver(
    expediente_id: int,
    purpose: str,
) -> Mapping[str, Any] | None:
    if purpose != PRESENTATION_TARGET_PURPOSE:
        return None

    status = expedient_service.get_expediente_mercurio_box_status(
        expediente_id,
        persist=False,
    )

    folder_path = str(
        status.get("box_para_presentar_folder_path") or ""
    ).strip()

    if (
        not status.get("tiene_carpeta_para_presentar")
        or not folder_path
    ):
        return None

    return {"absolute_path": folder_path}


def _default_target_documents_resolver(
    folder_path: str,
) -> Sequence[Mapping[str, Any]]:
    return box_directory_service.list_para_presentar_documents(
        folder_path
    )


def _client_display_name(
    client: Mapping[str, Any],
) -> str:
    explicit = str(
        client.get("display_name") or ""
    ).strip()

    if explicit:
        return explicit

    parts = [
        str(client.get("nombre") or "").strip(),
        str(client.get("primer_apellido") or "").strip(),
        str(client.get("segundo_apellido") or "").strip(),
    ]

    display_name = " ".join(
        part for part in parts if part
    )

    if not display_name:
        raise ValueError(
            "QCC_PRESENTATION_CONTEXT_CLIENT_DISPLAY_NAME_MISSING"
        )

    return display_name


def _expediente_display_name(
    expediente: Mapping[str, Any],
) -> str:
    """Nombre visible del EXPEDIENTE: su TIPO canónico.

    Nunca el número/ID interno de expediente: el operador necesita el
    tipo (p. ej. "Residencia temporal no lucrativa"), no un
    identificador opaco. El subtipo/procedimiento se proyecta por
    separado en ``_build_subexpediente``.
    """

    display_name = str(
        expediente.get("tipo_expediente_nombre")
        or expediente.get("display_name")
        or ""
    ).strip()

    if not display_name:
        raise ValueError(
            "QCC_PRESENTATION_CONTEXT_EXPEDIENTE_DISPLAY_NAME_MISSING"
        )

    return display_name


def _build_subexpediente(
    expediente: Mapping[str, Any],
) -> QccPresentationSubexpediente:
    subtipo_id = expediente.get("subtipo_expediente_id")

    if not subtipo_id:
        return QccPresentationSubexpediente(
            status=QccSubexpedienteResolutionStatus.NOT_CONFIGURED,
        )

    display_name = str(
        expediente.get("subtipo_expediente_nombre") or ""
    ).strip()

    if not display_name:
        raise ValueError(
            "QCC_PRESENTATION_CONTEXT_SUBEXPEDIENTE_"
            "DISPLAY_NAME_MISSING"
        )

    procedure_code = str(
        expediente.get("subtipo_expediente_codigo") or ""
    ).strip() or None

    return QccPresentationSubexpediente(
        status=QccSubexpedienteResolutionStatus.AVAILABLE,
        subexpediente_id=int(subtipo_id),
        procedure_code=procedure_code,
        display_name=display_name,
    )


def _build_target_document(
    raw: Mapping[str, Any],
) -> QccTargetDocument:
    filename = str(
        raw.get("filename") or raw.get("name") or ""
    ).strip()

    if not filename:
        raise ValueError(
            "QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENT_"
            "FILENAME_MISSING"
        )

    document_id = (
        raw.get("document_id")
        if raw.get("document_id") not in (None, "")
        else raw.get("box_file_id")
    )
    document_id = (
        str(document_id).strip()
        if document_id not in (None, "")
        else None
    )

    path = raw.get("path")
    path = (
        str(path).strip()
        if path not in (None, "")
        else None
    )

    available = raw.get("available", True)

    availability = (
        QccTargetDocumentAvailability.AVAILABLE
        if available
        else QccTargetDocumentAvailability.UNAVAILABLE
    )

    return QccTargetDocument(
        filename=filename,
        document_id=document_id,
        path=path,
        availability=availability,
    )


def _resolve_target_documents(
    expediente_id: int,
    purpose: str,
    target_folder_resolver: TargetFolderResolver,
    target_documents_resolver: TargetDocumentsResolver,
) -> QccPresentationTargetDocuments:
    try:
        folder = target_folder_resolver(
            int(expediente_id),
            purpose,
        )
    except (OSError, ValueError) as exc:
        return QccPresentationTargetDocuments(
            status=(
                QccTargetDocumentsResolutionStatus.RESOLUTION_ERROR
            ),
            error=str(exc),
        )

    if not folder:
        return QccPresentationTargetDocuments(
            status=QccTargetDocumentsResolutionStatus.NOT_CONFIGURED,
        )

    folder_path = str(
        folder.get("absolute_path")
        or folder.get("relative_path")
        or ""
    ).strip() or None

    try:
        raw_documents = target_documents_resolver(folder_path)
    except (OSError, ValueError) as exc:
        return QccPresentationTargetDocuments(
            status=(
                QccTargetDocumentsResolutionStatus.RESOLUTION_ERROR
            ),
            folder_path=folder_path,
            error=str(exc),
        )

    documents = tuple(
        _build_target_document(raw)
        for raw in (raw_documents or [])
    )

    return QccPresentationTargetDocuments(
        status=QccTargetDocumentsResolutionStatus.AVAILABLE,
        documents=documents,
        folder_path=folder_path,
    )


def resolve_presentation_context(
    expediente_id: int,
    *,
    purpose: str = PRESENTATION_TARGET_PURPOSE,
    client_resolver: ClientResolver = _default_client_resolver,
    expedient_resolver: ExpedientResolver = _default_expedient_resolver,
    target_folder_resolver: TargetFolderResolver = (
        _default_target_folder_resolver
    ),
    target_documents_resolver: TargetDocumentsResolver = (
        _default_target_documents_resolver
    ),
) -> QccPresentationContextResolution:
    """Resuelve el contexto de presentación para UN expediente.

    El cliente se deriva siempre del ``cliente_id`` canónico del
    expediente resuelto; nunca se acepta un cliente alternativo.
    """

    expediente = expedient_resolver(int(expediente_id))

    if not expediente:
        return QccPresentationContextResolution(
            status=(
                QccPresentationContextStatus.EXPEDIENTE_NOT_FOUND
            ),
            error=(
                "No existe el expediente indicado: "
                f"{expediente_id}"
            ),
        )

    cliente_id = expediente.get("cliente_id")
    client = (
        client_resolver(int(cliente_id))
        if cliente_id
        else None
    )

    if not client:
        return QccPresentationContextResolution(
            status=QccPresentationContextStatus.CLIENT_NOT_FOUND,
            error=(
                "No existe el cliente vinculado al expediente: "
                f"{cliente_id}"
            ),
        )

    context = QccPresentationContext(
        client=QccPresentationClient(
            client_id=int(cliente_id),
            display_name=_client_display_name(client),
        ),
        expediente=QccPresentationExpediente(
            expediente_id=int(expediente_id),
            display_name=_expediente_display_name(expediente),
        ),
        subexpediente=_build_subexpediente(expediente),
        target_documents=_resolve_target_documents(
            expediente_id,
            purpose,
            target_folder_resolver,
            target_documents_resolver,
        ),
    )

    return QccPresentationContextResolution(
        status=QccPresentationContextStatus.AVAILABLE,
        context=context,
    )
