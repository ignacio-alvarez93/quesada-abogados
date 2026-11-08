"""Apertura local gobernada de un documento objetivo QCC.

QCC nunca envía una ruta de archivo: envía únicamente
``document_id``. Esta capa resuelve dicho identificador
EXCLUSIVAMENTE dentro de los ``target_documents`` del
``QccPresentationContext`` activo, nunca contra una ruta arbitraria
recibida de la extensión.

No sube documentos, no selecciona inputs de archivo y no automatiza
ningún envío documental: solo invoca el abridor por defecto del
sistema operativo sobre una ruta ya validada.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from backend.qcc.context.presentation_context import (
    QccPresentationContext,
    QccTargetDocument,
    QccTargetDocumentAvailability,
)


class QccDocumentOpenError(Exception):
    """Fallo fail-closed de apertura: nunca abre nada en este caso."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def default_os_opener(path: str) -> None:
    """Abridor por defecto del sistema operativo (Windows)."""

    opener = getattr(os, "startfile", None)

    if opener is None:
        raise QccDocumentOpenError(
            "QCC_DOCUMENT_OPENER_UNAVAILABLE"
        )

    opener(path)


def _default_path_exists(path: str) -> bool:
    return Path(path).is_file()


def resolve_target_document(
    context: QccPresentationContext | None,
    document_id: str,
) -> QccTargetDocument:
    """Localiza ``document_id`` dentro del contexto activo.

    Nunca acepta un documento fuera de ``target_documents``: un
    ``document_id`` desconocido o un contexto ausente siempre
    resuelven en ``QCC_DOCUMENT_NOT_FOUND``.
    """

    normalized_document_id = str(
        document_id or ""
    ).strip()

    if not normalized_document_id:
        raise QccDocumentOpenError(
            "QCC_DOCUMENT_ID_REQUIRED"
        )

    documents = (
        context.target_documents.documents
        if context is not None
        else ()
    )

    for document in documents:
        if document.document_id == normalized_document_id:
            return document

    raise QccDocumentOpenError(
        "QCC_DOCUMENT_NOT_FOUND"
    )


def open_target_document(
    context: QccPresentationContext | None,
    document_id: str,
    *,
    os_opener: Callable[[str], None] = default_os_opener,
    path_exists: Callable[[str], bool] = _default_path_exists,
) -> QccTargetDocument:
    """Valida y abre EXACTAMENTE un documento del contexto activo.

    Orden de validación (fail-closed en cada paso):
    1. el documento existe dentro del contexto activo;
    2. está marcado como disponible;
    3. tiene una ruta canónica resuelta por la autoridad existente;
    4. esa ruta existe realmente en disco;
    5. solo entonces se invoca el abridor por defecto del sistema.
    """

    document = resolve_target_document(
        context,
        document_id,
    )

    if (
        document.availability
        != QccTargetDocumentAvailability.AVAILABLE
    ):
        raise QccDocumentOpenError(
            "QCC_DOCUMENT_UNAVAILABLE"
        )

    path = str(document.path or "").strip()

    if not path:
        raise QccDocumentOpenError(
            "QCC_DOCUMENT_PATH_MISSING"
        )

    if not path_exists(path):
        raise QccDocumentOpenError(
            "QCC_DOCUMENT_FILE_NOT_FOUND"
        )

    os_opener(path)

    return document
