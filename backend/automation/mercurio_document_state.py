"""
Estado documental genérico de Mercurio.

Este módulo es deliberadamente puro:
- no conoce SeleniumBase;
- no controla Chrome;
- no hace clicks;
- no accede a Mercurio;
- no conoce QCC;
- no conoce SQLite/Supabase.

Recibe un snapshot estructural ya extraído del DOM y determina:
- documentos obligatorios;
- documentos aportados;
- obligatorios pendientes;
- completitud documental;
- confirmación individual de una subida.

Contrato observado en Mercurio V1:
- #listaIdsDocOb
- .listaObligatoria [iddocob]
- #docAdjuntarAdjuntos
- #tabla_datos_adj tbody tr
- #tbAdjuntos input[type=file]
- #continuaNot
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


DOCUMENT_PAGE_FRAGMENT = (
    "presentacionTelematicaDocumentacion.html"
)

REQUIRED_CONTRACT_MARKERS = (
    "required_codes_field",
    "document_type_select",
    "uploaded_table",
    "file_input",
    "continue_button",
)


def _text(value: Any) -> str:
    return str(
        value
        if value is not None
        else ""
    ).strip()


def _filename(value: Any) -> str:
    raw = _text(value).replace(
        "\\",
        "/",
    )

    if not raw:
        return ""

    return raw.rsplit(
        "/",
        1,
    )[-1]


def parse_required_codes(
    raw_value: Any,
) -> tuple[str, ...]:
    """Parsea la lista dinámica que publica Mercurio.

    Ejemplo:
        "1|39|47" -> ("1", "39", "47")

    Conserva orden y elimina duplicados.
    """

    raw = _text(
        raw_value
    )

    if not raw:
        return ()

    result = []

    for part in raw.split("|"):
        code = _text(
            part
        )

        if (
            code
            and code not in result
        ):
            result.append(
                code
            )

    return tuple(
        result
    )


@dataclass(
    frozen=True,
)
class MercurioRequiredDocument:
    code: str
    label: str


@dataclass(
    frozen=True,
)
class MercurioUploadedDocument:
    filename: str
    description: str
    hash_value: str
    code: str
    row_id: str = ""

    @property
    def has_hash(
        self,
    ) -> bool:
        return bool(
            self.hash_value
        )


@dataclass(
    frozen=True,
)
class MercurioDocumentState:
    url: str
    page_detected: bool
    contract_compatible: bool

    required_documents: tuple[
        MercurioRequiredDocument,
        ...
    ]

    uploaded_documents: tuple[
        MercurioUploadedDocument,
        ...
    ]

    missing_required_codes: tuple[
        str,
        ...
    ]

    required_count: int
    uploaded_required_count: int

    documentation_complete: bool

    def is_uploaded(
        self,
        *,
        filename: str,
        code: str,
        require_hash: bool = True,
    ) -> bool:
        """Confirma una subida por nombre + código + hash."""

        expected_filename = (
            _filename(
                filename
            )
            .casefold()
        )

        expected_code = _text(
            code
        )

        if (
            not expected_filename
            or not expected_code
        ):
            return False

        for document in (
            self.uploaded_documents
        ):
            if (
                document.code
                != expected_code
            ):
                continue

            if (
                document.filename.casefold()
                != expected_filename
            ):
                continue

            if (
                require_hash
                and not document.has_hash
            ):
                continue

            return True

        return False

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "url":
                self.url,
            "page_detected":
                self.page_detected,
            "contract_compatible":
                self.contract_compatible,
            "required_documents": [
                {
                    "code":
                        item.code,
                    "label":
                        item.label,
                }
                for item
                in self.required_documents
            ],
            "uploaded_documents": [
                {
                    "filename":
                        item.filename,
                    "description":
                        item.description,
                    "hash":
                        item.hash_value,
                    "code":
                        item.code,
                    "row_id":
                        item.row_id,
                }
                for item
                in self.uploaded_documents
            ],
            "missing_required_codes":
                list(
                    self.missing_required_codes
                ),
            "required_count":
                self.required_count,
            "uploaded_required_count":
                self.uploaded_required_count,
            "documentation_complete":
                self.documentation_complete,
        }


def build_mercurio_document_state(
    snapshot: Mapping[str, Any],
) -> MercurioDocumentState:
    """Construye estado documental desde snapshot DOM normalizado."""

    if not isinstance(
        snapshot,
        Mapping,
    ):
        raise TypeError(
            "snapshot debe ser Mapping"
        )

    url = _text(
        snapshot.get(
            "url"
        )
    )

    page_detected = (
        DOCUMENT_PAGE_FRAGMENT
        in url
    )

    markers = snapshot.get(
        "markers"
    )

    if not isinstance(
        markers,
        Mapping,
    ):
        markers = {}

    contract_compatible = bool(
        page_detected
        and all(
            bool(
                markers.get(
                    marker
                )
            )
            for marker
            in REQUIRED_CONTRACT_MARKERS
        )
    )

    required_codes = (
        parse_required_codes(
            snapshot.get(
                "required_codes_raw"
            )
        )
    )

    required_items_raw = (
        snapshot.get(
            "required_items"
        )
        or []
    )

    labels_by_code = {}

    for item in required_items_raw:
        if not isinstance(
            item,
            Mapping,
        ):
            continue

        code = _text(
            item.get(
                "code"
            )
        )

        if not code:
            continue

        label = _text(
            item.get(
                "label"
            )
        )

        labels_by_code[
            code
        ] = label

    required_documents = tuple(
        MercurioRequiredDocument(
            code=code,
            label=(
                labels_by_code.get(
                    code
                )
                or (
                    "Documento Mercurio "
                    f"{code}"
                )
            ),
        )
        for code
        in required_codes
    )

    uploaded_rows = (
        snapshot.get(
            "uploaded_rows"
        )
        or []
    )

    uploaded_documents = []

    for row in uploaded_rows:
        if not isinstance(
            row,
            Mapping,
        ):
            continue

        code = _text(
            row.get(
                "code"
            )
        )

        filename = _filename(
            row.get(
                "filename"
            )
        )

        if (
            not code
            or not filename
        ):
            continue

        uploaded_documents.append(
            MercurioUploadedDocument(
                filename=filename,
                description=_text(
                    row.get(
                        "description"
                    )
                ),
                hash_value=_text(
                    row.get(
                        "hash"
                    )
                ),
                code=code,
                row_id=_text(
                    row.get(
                        "row_id"
                    )
                ),
            )
        )

    uploaded_documents_tuple = tuple(
        uploaded_documents
    )

    uploaded_codes = {
        document.code
        for document
        in uploaded_documents_tuple
    }

    missing_required_codes = tuple(
        code
        for code
        in required_codes
        if code not in uploaded_codes
    )

    uploaded_required_count = sum(
        1
        for code
        in required_codes
        if code in uploaded_codes
    )

    documentation_complete = bool(
        contract_compatible
        and not missing_required_codes
    )

    return MercurioDocumentState(
        url=url,
        page_detected=page_detected,
        contract_compatible=(
            contract_compatible
        ),
        required_documents=(
            required_documents
        ),
        uploaded_documents=(
            uploaded_documents_tuple
        ),
        missing_required_codes=(
            missing_required_codes
        ),
        required_count=len(
            required_codes
        ),
        uploaded_required_count=(
            uploaded_required_count
        ),
        documentation_complete=(
            documentation_complete
        ),
    )
