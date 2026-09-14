"""Servicio de aplicación para la ingestión canónica de Knowledge.

Esta capa coordina providers, clasificación de revisiones y repository.
No conoce HTTP, BOE internamente, SQLite ni PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass

from .providers import (
    KnowledgeItemReference,
    KnowledgeProvider,
    validate_discovery_batch,
    validate_transformed_item,
)
from .repository import (
    KnowledgeRepository,
)
from .revisions import (
    KnowledgeRevisionStatus,
    classify_knowledge_revision,
)


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionResult:
    canonical_key: str
    status: KnowledgeRevisionStatus

    revision_number: int
    written: bool

    content_sha256: str
    source_revision: str


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionBatchResult:
    source_key: str

    discovered_count: int
    attempted_count: int
    written_count: int
    unchanged_count: int

    next_cursor: str | None

    results: tuple[
        KnowledgeIngestionResult,
        ...,
    ]


class KnowledgeIngestionService:
    """Orquestador provider-neutral de Knowledge."""

    def __init__(
        self,
        repository: KnowledgeRepository,
    ) -> None:
        if not isinstance(
            repository,
            KnowledgeRepository,
        ):
            raise TypeError(
                "repository debe implementar "
                "KnowledgeRepository"
            )

        self._repository = repository

    @property
    def repository(
        self,
    ) -> KnowledgeRepository:
        return self._repository

    def ingest_reference(
        self,
        provider: KnowledgeProvider,
        reference: KnowledgeItemReference,
    ) -> KnowledgeIngestionResult:
        payload = provider.fetch(
            reference
        )

        item = provider.to_knowledge_item(
            reference,
            payload,
        )

        validate_transformed_item(
            provider,
            reference,
            item,
        )

        previous = (
            self._repository.get_current(
                item.source_key,
                item.external_id,
            )
        )

        decision = classify_knowledge_revision(
            previous=previous,
            current=item,
        )

        write_result = (
            self._repository.persist(
                item,
                decision,
            )
        )

        if (
            write_result.status
            is not decision.status
        ):
            raise RuntimeError(
                "KnowledgeRepository devolvió "
                "un estado distinto de la decisión "
                "de revisión"
            )

        if (
            write_result.canonical_key
            != item.canonical_key
        ):
            raise RuntimeError(
                "KnowledgeRepository devolvió "
                "canonical_key incompatible"
            )

        return KnowledgeIngestionResult(
            canonical_key=item.canonical_key,
            status=decision.status,
            revision_number=(
                write_result.revision_number
            ),
            written=write_result.written,
            content_sha256=(
                item.content_sha256
            ),
            source_revision=(
                item.source_revision
            ),
        )

    def discover_and_ingest(
        self,
        provider: KnowledgeProvider,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> KnowledgeIngestionBatchResult:
        if limit is not None:
            if (
                not isinstance(limit, int)
                or isinstance(limit, bool)
                or limit <= 0
            ):
                raise ValueError(
                    "limit debe ser entero positivo"
                )

        batch = provider.discover(
            cursor=cursor
        )

        validate_discovery_batch(
            provider,
            batch,
        )

        references = tuple(
            batch.items
        )

        selected = (
            references
            if limit is None
            else references[:limit]
        )

        results = tuple(
            self.ingest_reference(
                provider,
                reference,
            )
            for reference in selected
        )

        written_count = sum(
            1
            for result in results
            if result.written
        )

        unchanged_count = sum(
            1
            for result in results
            if (
                result.status
                is KnowledgeRevisionStatus.UNCHANGED
            )
        )

        return KnowledgeIngestionBatchResult(
            source_key=provider.source_key,
            discovered_count=len(
                references
            ),
            attempted_count=len(
                selected
            ),
            written_count=written_count,
            unchanged_count=unchanged_count,
            next_cursor=batch.next_cursor,
            results=results,
        )
