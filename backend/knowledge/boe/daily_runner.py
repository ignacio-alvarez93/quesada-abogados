"""Ejecución diaria gobernada para el BOE.

Responsabilidades:
- fecha explícita y determinista;
- dry-run real;
- apply explícito;
- límite opcional;
- aislamiento de errores por publicación;
- métricas finales.

No conoce SQLite ni PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..ingestion import (
    KnowledgeIngestionService,
)
from ..providers import (
    KnowledgeProvider,
    validate_discovery_batch,
)
from ..revisions import (
    KnowledgeRevisionStatus,
)


@dataclass(frozen=True, slots=True)
class BoeDailyItemResult:
    external_id: str
    canonical_key: str

    status: KnowledgeRevisionStatus | None

    written: bool
    revision_number: int | None

    error: str | None


@dataclass(frozen=True, slots=True)
class BoeDailyRunResult:
    publication_date: str
    dry_run: bool

    discovered_count: int
    attempted_count: int

    new_count: int
    unchanged_count: int
    metadata_revised_count: int
    content_revised_count: int

    written_count: int
    failed_count: int

    next_cursor: str | None

    results: tuple[
        BoeDailyItemResult,
        ...,
    ]


def normalize_boe_publication_date(
    value: str,
) -> str:
    normalized = str(
        value or ""
    ).strip()

    if (
        len(normalized) != 8
        or not normalized.isdigit()
    ):
        raise ValueError(
            "BOE publication_date "
            "debe usar AAAAMMDD"
        )

    try:
        datetime.strptime(
            normalized,
            "%Y%m%d",
        )
    except ValueError as exc:
        raise ValueError(
            "BOE publication_date "
            "no es válida"
        ) from exc

    return normalized


def _validate_limit(
    limit: int | None,
) -> None:
    if limit is None:
        return

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
    ):
        raise ValueError(
            "limit debe ser entero positivo"
        )


class BoeDailyIngestionRunner:
    """Orquestador operacional diario del BOE."""

    def __init__(
        self,
        *,
        provider: KnowledgeProvider,
        service: KnowledgeIngestionService,
    ) -> None:
        if provider.source_key != "BOE":
            raise ValueError(
                "BoeDailyIngestionRunner "
                "requiere provider BOE"
            )

        self._provider = provider
        self._service = service

    def run(
        self,
        *,
        publication_date: str,
        dry_run: bool = True,
        limit: int | None = None,
    ) -> BoeDailyRunResult:
        publication_date = (
            normalize_boe_publication_date(
                publication_date
            )
        )

        if not isinstance(
            dry_run,
            bool,
        ):
            raise TypeError(
                "dry_run debe ser bool"
            )

        _validate_limit(
            limit
        )

        batch = self._provider.discover(
            cursor=publication_date
        )

        validate_discovery_batch(
            self._provider,
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

        results: list[
            BoeDailyItemResult
        ] = []

        for reference in selected:
            try:
                if dry_run:
                    preview = (
                        self._service.preview_reference(
                            self._provider,
                            reference,
                        )
                    )

                    results.append(
                        BoeDailyItemResult(
                            external_id=(
                                reference.external_id
                            ),
                            canonical_key=(
                                preview.canonical_key
                            ),
                            status=preview.status,
                            written=False,
                            revision_number=None,
                            error=None,
                        )
                    )

                else:
                    ingestion = (
                        self._service.ingest_reference(
                            self._provider,
                            reference,
                        )
                    )

                    results.append(
                        BoeDailyItemResult(
                            external_id=(
                                reference.external_id
                            ),
                            canonical_key=(
                                ingestion.canonical_key
                            ),
                            status=ingestion.status,
                            written=(
                                ingestion.written
                            ),
                            revision_number=(
                                ingestion.revision_number
                            ),
                            error=None,
                        )
                    )

            except Exception as exc:
                results.append(
                    BoeDailyItemResult(
                        external_id=(
                            reference.external_id
                        ),
                        canonical_key=(
                            reference.canonical_key
                        ),
                        status=None,
                        written=False,
                        revision_number=None,
                        error=(
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        ),
                    )
                )

        frozen_results = tuple(
            results
        )

        def count_status(
            status: KnowledgeRevisionStatus,
        ) -> int:
            return sum(
                1
                for result in frozen_results
                if result.status is status
            )

        return BoeDailyRunResult(
            publication_date=publication_date,
            dry_run=dry_run,
            discovered_count=len(
                references
            ),
            attempted_count=len(
                selected
            ),
            new_count=count_status(
                KnowledgeRevisionStatus.NEW
            ),
            unchanged_count=count_status(
                KnowledgeRevisionStatus.UNCHANGED
            ),
            metadata_revised_count=count_status(
                KnowledgeRevisionStatus.METADATA_REVISED
            ),
            content_revised_count=count_status(
                KnowledgeRevisionStatus.CONTENT_REVISED
            ),
            written_count=sum(
                1
                for result in frozen_results
                if result.written
            ),
            failed_count=sum(
                1
                for result in frozen_results
                if result.error is not None
            ),
            next_cursor=batch.next_cursor,
            results=frozen_results,
        )
