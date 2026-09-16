"""Estructura jurídica canónica provider-neutral.

KnowledgeItem representa la pieza documental observada.

Esta capa representa su estructura jurídica interna:

    KnowledgeItem
        -> KnowledgeBlock
            -> KnowledgeBlockVersion

No realiza persistencia, HTTP, UI ni procesamiento IA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
from typing import Mapping

from .items import (
    compute_content_sha256,
    normalize_knowledge_text,
    normalize_metadata,
)
from .source_registry import (
    get_knowledge_source,
    normalize_source_key,
)


def _normalized_identifier(
    value: object,
    *,
    field_name: str,
) -> str:
    result = str(
        value or ""
    ).strip()

    if not result:
        raise ValueError(
            f"{field_name} no puede estar vacío"
        )

    return result


def compute_block_version_key(
    *,
    source_key: str,
    external_id: str,
    block_id: str,
    modifier_external_id: str,
    published_on: date | None,
    effective_from: date | None,
    content_text: str,
) -> str:
    """Identidad determinista de una versión estructural.

    No depende de ``version_position``: la posición ordena la
    cronología observada, pero no forma parte de la identidad
    jurídica estable de la versión.

    Tampoco depende de un id upstream porque algunos providers,
    incluido BOE Consolidado, no exponen uno de forma uniforme.
    """

    payload = {
        "source_key": (
            normalize_source_key(
                source_key
            )
        ),
        "external_id": str(
            external_id or ""
        ).strip(),
        "block_id": str(
            block_id or ""
        ).strip(),
        "modifier_external_id": str(
            modifier_external_id or ""
        ).strip(),
        "published_on": (
            published_on.isoformat()
            if published_on
            else None
        ),
        "effective_from": (
            effective_from.isoformat()
            if effective_from
            else None
        ),
        "content_sha256": (
            compute_content_sha256(
                content_text
            )
        ),
    }

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return sha256(
        serialized.encode(
            "utf-8"
        )
    ).hexdigest()


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeBlockVersion:
    """Una versión histórica o vigente de un bloque jurídico."""

    source_key: str
    external_id: str
    block_id: str

    version_key: str
    version_position: int

    content_text: str

    modifier_external_id: str = ""

    published_on: date | None = None
    effective_from: date | None = None

    is_current: bool = False

    metadata: tuple[
        tuple[str, str],
        ...,
    ] = ()

    content_sha256: str = field(
        init=False
    )

    def __post_init__(
        self,
    ) -> None:
        source_key = normalize_source_key(
            self.source_key
        )

        get_knowledge_source(
            source_key
        )

        external_id = (
            _normalized_identifier(
                self.external_id,
                field_name=(
                    "KnowledgeBlockVersion "
                    "external_id"
                ),
            )
        )

        block_id = (
            _normalized_identifier(
                self.block_id,
                field_name=(
                    "KnowledgeBlockVersion "
                    "block_id"
                ),
            )
        )

        version_key = (
            _normalized_identifier(
                self.version_key,
                field_name=(
                    "KnowledgeBlockVersion "
                    "version_key"
                ),
            )
        )

        if (
            not isinstance(
                self.version_position,
                int,
            )
            or isinstance(
                self.version_position,
                bool,
            )
            or self.version_position < 1
        ):
            raise ValueError(
                "version_position debe ser entero >= 1"
            )

        if not isinstance(
            self.is_current,
            bool,
        ):
            raise TypeError(
                "is_current debe ser bool"
            )

        content_text = (
            normalize_knowledge_text(
                self.content_text
            )
        )

        modifier_external_id = str(
            self.modifier_external_id
            or ""
        ).strip()

        metadata = normalize_metadata(
            dict(
                self.metadata
            )
        )

        object.__setattr__(
            self,
            "source_key",
            source_key,
        )
        object.__setattr__(
            self,
            "external_id",
            external_id,
        )
        object.__setattr__(
            self,
            "block_id",
            block_id,
        )
        object.__setattr__(
            self,
            "version_key",
            version_key,
        )
        object.__setattr__(
            self,
            "content_text",
            content_text,
        )
        object.__setattr__(
            self,
            "modifier_external_id",
            modifier_external_id,
        )
        object.__setattr__(
            self,
            "metadata",
            metadata,
        )
        object.__setattr__(
            self,
            "content_sha256",
            compute_content_sha256(
                content_text
            ),
        )

    @property
    def block_canonical_key(
        self,
    ) -> str:
        return (
            f"{self.source_key}:"
            f"{self.external_id}"
            f"#block:{self.block_id}"
        )

    @property
    def canonical_key(
        self,
    ) -> str:
        return (
            f"{self.block_canonical_key}"
            f"@version:{self.version_key}"
        )


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeBlock:
    """Bloque estructural estable dentro de una KnowledgeItem."""

    source_key: str
    external_id: str

    block_id: str
    position: int

    title: str = ""
    canonical_uri: str = ""

    current_version_key: str = ""

    metadata: tuple[
        tuple[str, str],
        ...,
    ] = ()

    def __post_init__(
        self,
    ) -> None:
        source_key = normalize_source_key(
            self.source_key
        )

        get_knowledge_source(
            source_key
        )

        external_id = (
            _normalized_identifier(
                self.external_id,
                field_name=(
                    "KnowledgeBlock external_id"
                ),
            )
        )

        block_id = (
            _normalized_identifier(
                self.block_id,
                field_name=(
                    "KnowledgeBlock block_id"
                ),
            )
        )

        if (
            not isinstance(
                self.position,
                int,
            )
            or isinstance(
                self.position,
                bool,
            )
            or self.position < 1
        ):
            raise ValueError(
                "KnowledgeBlock position "
                "debe ser entero >= 1"
            )

        object.__setattr__(
            self,
            "source_key",
            source_key,
        )
        object.__setattr__(
            self,
            "external_id",
            external_id,
        )
        object.__setattr__(
            self,
            "block_id",
            block_id,
        )
        object.__setattr__(
            self,
            "title",
            str(
                self.title or ""
            ).strip(),
        )
        object.__setattr__(
            self,
            "canonical_uri",
            str(
                self.canonical_uri
                or ""
            ).strip(),
        )
        object.__setattr__(
            self,
            "current_version_key",
            str(
                self.current_version_key
                or ""
            ).strip(),
        )
        object.__setattr__(
            self,
            "metadata",
            normalize_metadata(
                dict(
                    self.metadata
                )
            ),
        )

    @property
    def canonical_key(
        self,
    ) -> str:
        return (
            f"{self.source_key}:"
            f"{self.external_id}"
            f"#block:{self.block_id}"
        )


@dataclass(
    frozen=True,
    slots=True,
)
class KnowledgeStructuredDocument:
    """Estructura interna completa de una pieza jurídica."""

    source_key: str
    external_id: str

    blocks: tuple[
        KnowledgeBlock,
        ...,
    ]

    versions: tuple[
        KnowledgeBlockVersion,
        ...,
    ]

    def __post_init__(
        self,
    ) -> None:
        source_key = normalize_source_key(
            self.source_key
        )

        get_knowledge_source(
            source_key
        )

        external_id = (
            _normalized_identifier(
                self.external_id,
                field_name=(
                    "KnowledgeStructuredDocument "
                    "external_id"
                ),
            )
        )

        if not self.blocks:
            raise ValueError(
                "KnowledgeStructuredDocument "
                "requiere al menos un bloque"
            )

        block_ids = set()

        for block in self.blocks:
            if not isinstance(
                block,
                KnowledgeBlock,
            ):
                raise TypeError(
                    "blocks debe contener "
                    "KnowledgeBlock"
                )

            if (
                block.source_key
                != source_key
                or block.external_id
                != external_id
            ):
                raise ValueError(
                    "KnowledgeBlock pertenece "
                    "a otra KnowledgeItem"
                )

            if block.block_id in block_ids:
                raise ValueError(
                    "block_id duplicado: "
                    f"{block.block_id}"
                )

            block_ids.add(
                block.block_id
            )

        current_counts = {
            block_id: 0
            for block_id
            in block_ids
        }

        versions_by_block = {
            block_id: 0
            for block_id
            in block_ids
        }

        version_keys = set()

        for version in self.versions:
            if not isinstance(
                version,
                KnowledgeBlockVersion,
            ):
                raise TypeError(
                    "versions debe contener "
                    "KnowledgeBlockVersion"
                )

            if (
                version.source_key
                != source_key
                or version.external_id
                != external_id
            ):
                raise ValueError(
                    "KnowledgeBlockVersion "
                    "pertenece a otra KnowledgeItem"
                )

            if (
                version.block_id
                not in block_ids
            ):
                raise ValueError(
                    "Versión referencia bloque "
                    "inexistente: "
                    f"{version.block_id}"
                )

            if (
                version.canonical_key
                in version_keys
            ):
                raise ValueError(
                    "KnowledgeBlockVersion duplicada: "
                    f"{version.canonical_key}"
                )

            version_keys.add(
                version.canonical_key
            )

            versions_by_block[
                version.block_id
            ] += 1

            if version.is_current:
                current_counts[
                    version.block_id
                ] += 1

        for block in self.blocks:
            if (
                versions_by_block[
                    block.block_id
                ]
                < 1
            ):
                raise ValueError(
                    "Bloque sin versiones: "
                    f"{block.block_id}"
                )

            if (
                current_counts[
                    block.block_id
                ]
                != 1
            ):
                raise ValueError(
                    "Cada bloque requiere exactamente "
                    "una versión vigente: "
                    f"{block.block_id}"
                )

            current = (
                self.current_version(
                    block.block_id
                )
            )

            if (
                block.current_version_key
                and block.current_version_key
                != current.version_key
            ):
                raise ValueError(
                    "current_version_key "
                    "no coincide con versión vigente"
                )

        object.__setattr__(
            self,
            "source_key",
            source_key,
        )
        object.__setattr__(
            self,
            "external_id",
            external_id,
        )

    @property
    def canonical_key(
        self,
    ) -> str:
        return (
            f"{self.source_key}:"
            f"{self.external_id}"
        )

    def versions_for_block(
        self,
        block_id: str,
    ) -> tuple[
        KnowledgeBlockVersion,
        ...,
    ]:
        identifier = str(
            block_id or ""
        ).strip()

        return tuple(
            sorted(
                (
                    version
                    for version
                    in self.versions
                    if (
                        version.block_id
                        == identifier
                    )
                ),
                key=lambda version: (
                    version.version_position
                ),
            )
        )

    def current_version(
        self,
        block_id: str,
    ) -> KnowledgeBlockVersion:
        matches = tuple(
            version
            for version
            in self.versions
            if (
                version.block_id
                == block_id
                and version.is_current
            )
        )

        if len(matches) != 1:
            raise LookupError(
                "No existe una única versión "
                f"vigente para {block_id}"
            )

        return matches[0]

    @property
    def current_content_text(
        self,
    ) -> str:
        parts = []

        for block in sorted(
            self.blocks,
            key=lambda item: item.position,
        ):
            current = self.current_version(
                block.block_id
            )

            if current.content_text:
                parts.append(
                    current.content_text
                )

        return "\n\n".join(
            parts
        ).strip()


def build_knowledge_block_version(
    *,
    source_key: str,
    external_id: str,
    block_id: str,
    version_position: int,
    content_text: str,
    modifier_external_id: str = "",
    published_on: date | None = None,
    effective_from: date | None = None,
    is_current: bool = False,
    metadata: Mapping[
        str,
        object,
    ] | None = None,
) -> KnowledgeBlockVersion:
    version_key = (
        compute_block_version_key(
            source_key=source_key,
            external_id=external_id,
            block_id=block_id,
            modifier_external_id=(
                modifier_external_id
            ),
            published_on=published_on,
            effective_from=effective_from,
            content_text=content_text,
        )
    )

    return KnowledgeBlockVersion(
        source_key=source_key,
        external_id=external_id,
        block_id=block_id,
        version_key=version_key,
        version_position=(
            version_position
        ),
        content_text=content_text,
        modifier_external_id=(
            modifier_external_id
        ),
        published_on=published_on,
        effective_from=effective_from,
        is_current=is_current,
        metadata=normalize_metadata(
            metadata
        ),
    )
