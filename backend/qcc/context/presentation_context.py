"""Contrato de contexto de presentación QCC.

QCC nunca es fuente de verdad. Esta estructura es exclusivamente
una proyección de autoridades canónicas (cliente, expediente,
subexpediente/procedimiento y target documental) ya resueltas por
la capa de aplicación (ver ``qcc_presentation_context_service``).

Ninguna ruta física se reconstruye aquí: toda ruta proviene ya
resuelta de la autoridad canónica correspondiente.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


QCC_PRESENTATION_CONTEXT_SCHEMA_VERSION = 1
QCC_PRESENTATION_CONTEXT_TYPE = "QCC_PRESENTATION_CONTEXT"


def _assert_required_text(
    value: Any,
    *,
    code: str,
) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
    ):
        raise ValueError(code)


def _assert_optional_text(
    value: Any,
    *,
    code: str,
) -> None:
    if value is None:
        return

    if not isinstance(value, str) or not value.strip():
        raise ValueError(code)


def _assert_positive_int(
    value: Any,
    *,
    code: str,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValueError(code)


class QccSubexpedienteResolutionStatus(
    str,
    Enum,
):
    """Estado de resolución del subexpediente/procedimiento."""

    AVAILABLE = "AVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class QccTargetDocumentAvailability(
    str,
    Enum,
):
    """Disponibilidad explícita de un documento objetivo."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class QccTargetDocumentsResolutionStatus(
    str,
    Enum,
):
    """Estado de resolución del conjunto de documentos objetivo."""

    AVAILABLE = "AVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    RESOLUTION_ERROR = "RESOLUTION_ERROR"


class QccPresentationContextStatus(
    str,
    Enum,
):
    """Estado de resolución del contexto de presentación completo."""

    AVAILABLE = "AVAILABLE"
    EXPEDIENTE_NOT_FOUND = "EXPEDIENTE_NOT_FOUND"
    CLIENT_NOT_FOUND = "CLIENT_NOT_FOUND"


@dataclass(
    frozen=True,
    slots=True,
)
class QccPresentationClient:
    """Identidad mínima del cliente para presentación."""

    client_id: int
    display_name: str

    def __post_init__(self) -> None:
        _assert_positive_int(
            self.client_id,
            code="QCC_PRESENTATION_CONTEXT_CLIENT_ID_INVALID",
        )
        _assert_required_text(
            self.display_name,
            code="QCC_PRESENTATION_CONTEXT_CLIENT_DISPLAY_NAME_REQUIRED",
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "display_name": self.display_name,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class QccPresentationExpediente:
    """Identidad mínima del expediente para presentación."""

    expediente_id: int
    display_name: str

    def __post_init__(self) -> None:
        _assert_positive_int(
            self.expediente_id,
            code="QCC_PRESENTATION_CONTEXT_EXPEDIENTE_ID_INVALID",
        )
        _assert_required_text(
            self.display_name,
            code="QCC_PRESENTATION_CONTEXT_EXPEDIENTE_DISPLAY_NAME_REQUIRED",
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "expediente_id": self.expediente_id,
            "display_name": self.display_name,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class QccPresentationSubexpediente:
    """Subexpediente/procedimiento (subtipo de expediente).

    Es legítimamente opcional: no todo expediente tiene un
    subtipo/procedimiento asignado. ``NOT_CONFIGURED`` nunca debe
    confundirse con un error de resolución.
    """

    status: QccSubexpedienteResolutionStatus
    subexpediente_id: int | None = None
    procedure_code: str | None = None
    display_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.status,
            QccSubexpedienteResolutionStatus,
        ):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_SUBEXPEDIENTE_STATUS_INVALID"
            )

        if (
            self.status
            == QccSubexpedienteResolutionStatus.AVAILABLE
        ):
            _assert_positive_int(
                self.subexpediente_id,
                code=(
                    "QCC_PRESENTATION_CONTEXT_SUBEXPEDIENTE_ID_INVALID"
                ),
            )
            _assert_required_text(
                self.display_name,
                code=(
                    "QCC_PRESENTATION_CONTEXT_SUBEXPEDIENTE_"
                    "DISPLAY_NAME_REQUIRED"
                ),
            )
            _assert_optional_text(
                self.procedure_code,
                code=(
                    "QCC_PRESENTATION_CONTEXT_PROCEDURE_CODE_INVALID"
                ),
            )
        else:
            if (
                self.subexpediente_id is not None
                or self.procedure_code is not None
                or self.display_name is not None
            ):
                raise ValueError(
                    "QCC_PRESENTATION_CONTEXT_SUBEXPEDIENTE_"
                    "NOT_CONFIGURED_MUST_BE_EMPTY"
                )

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "subexpediente_id": self.subexpediente_id,
            "procedure_code": self.procedure_code,
            "display_name": self.display_name,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class QccTargetDocument:
    """Documento concreto seleccionado para ESTA presentación.

    No representa el inventario documental completo del expediente.
    """

    filename: str
    document_id: str | None = None
    path: str | None = None
    availability: QccTargetDocumentAvailability = (
        QccTargetDocumentAvailability.AVAILABLE
    )

    def __post_init__(self) -> None:
        _assert_required_text(
            self.filename,
            code="QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENT_FILENAME_REQUIRED",
        )
        _assert_optional_text(
            self.document_id,
            code="QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENT_ID_INVALID",
        )
        _assert_optional_text(
            self.path,
            code="QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENT_PATH_INVALID",
        )

        if not isinstance(
            self.availability,
            QccTargetDocumentAvailability,
        ):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENT_"
                "AVAILABILITY_INVALID"
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "path": self.path,
            "availability": self.availability.value,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class QccPresentationTargetDocuments:
    """Sección de documentos objetivo de la presentación concreta."""

    status: QccTargetDocumentsResolutionStatus
    documents: tuple[QccTargetDocument, ...] = ()
    folder_path: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.status,
            QccTargetDocumentsResolutionStatus,
        ):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENTS_"
                "STATUS_INVALID"
            )

        if not isinstance(self.documents, tuple):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENTS_"
                "MUST_BE_TUPLE"
            )

        if any(
            not isinstance(document, QccTargetDocument)
            for document in self.documents
        ):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENT_INVALID"
            )

        if (
            self.status
            != QccTargetDocumentsResolutionStatus.AVAILABLE
            and self.documents
        ):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENTS_"
                "MUST_BE_EMPTY"
            )

        _assert_optional_text(
            self.folder_path,
            code="QCC_PRESENTATION_CONTEXT_FOLDER_PATH_INVALID",
        )

        if (
            self.status
            == QccTargetDocumentsResolutionStatus.RESOLUTION_ERROR
        ):
            _assert_required_text(
                self.error,
                code=(
                    "QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENTS_"
                    "ERROR_REQUIRED"
                ),
            )
        elif self.error is not None:
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENTS_"
                "ERROR_MUST_BE_EMPTY"
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "folder_path": self.folder_path,
            "documents": [
                document.to_payload()
                for document in self.documents
            ],
            "error": self.error,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class QccPresentationContext:
    """Proyección completa: cliente + expediente + subexpediente +
    documentos objetivo de una presentación administrativa concreta.
    """

    client: QccPresentationClient
    expediente: QccPresentationExpediente
    subexpediente: QccPresentationSubexpediente
    target_documents: QccPresentationTargetDocuments

    def __post_init__(self) -> None:
        if not isinstance(self.client, QccPresentationClient):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_CLIENT_INVALID"
            )

        if not isinstance(
            self.expediente,
            QccPresentationExpediente,
        ):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_EXPEDIENTE_INVALID"
            )

        if not isinstance(
            self.subexpediente,
            QccPresentationSubexpediente,
        ):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_SUBEXPEDIENTE_INVALID"
            )

        if not isinstance(
            self.target_documents,
            QccPresentationTargetDocuments,
        ):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_TARGET_DOCUMENTS_INVALID"
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version":
                QCC_PRESENTATION_CONTEXT_SCHEMA_VERSION,

            "context_type":
                QCC_PRESENTATION_CONTEXT_TYPE,

            "client":
                self.client.to_payload(),

            "expediente":
                self.expediente.to_payload(),

            "subexpediente":
                self.subexpediente.to_payload(),

            "target_documents":
                self.target_documents.to_payload(),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class QccPresentationContextResolution:
    """Resultado de la resolución de nivel superior.

    Un contexto incompleto (cliente o expediente no resueltos) nunca
    se expone como contexto parcial: es un fallo explícito, nunca una
    sustitución silenciosa.
    """

    status: QccPresentationContextStatus
    context: QccPresentationContext | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.status,
            QccPresentationContextStatus,
        ):
            raise ValueError(
                "QCC_PRESENTATION_CONTEXT_RESOLUTION_STATUS_INVALID"
            )

        if (
            self.status
            == QccPresentationContextStatus.AVAILABLE
        ):
            if not isinstance(
                self.context,
                QccPresentationContext,
            ):
                raise ValueError(
                    "QCC_PRESENTATION_CONTEXT_RESOLUTION_"
                    "CONTEXT_REQUIRED"
                )

            if self.error is not None:
                raise ValueError(
                    "QCC_PRESENTATION_CONTEXT_RESOLUTION_"
                    "ERROR_MUST_BE_EMPTY"
                )
        else:
            if self.context is not None:
                raise ValueError(
                    "QCC_PRESENTATION_CONTEXT_RESOLUTION_"
                    "CONTEXT_MUST_BE_EMPTY"
                )

            _assert_required_text(
                self.error,
                code=(
                    "QCC_PRESENTATION_CONTEXT_RESOLUTION_"
                    "ERROR_REQUIRED"
                ),
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "context": (
                self.context.to_payload()
                if self.context is not None
                else None
            ),
            "error": self.error,
        }
