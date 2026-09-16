"""Historia temporal canónica de artículos EUR-Lex.

Convierte una secuencia de snapshots consolidados:

    EurLexArticleSnapshot
        -> artículo semántico estable
        -> runs de contenido jurídico
        -> KnowledgeBlock
        -> KnowledgeBlockVersion

Principios:

- ``block_id`` identifica el artículo jurídicamente.
- Un snapshot nuevo NO implica una versión jurídica nueva.
- Whitespace LEGACY/ELI no crea versiones falsas.
- ``version_position`` expresa orden, nunca identidad.
- ``effective_from`` es la fecha de inicio del primer snapshot
  observado para ese run semántico.
- La representación es ARTICLES_ONLY y no debe conectarse todavía
  al ingestion provider de documento completo.
- La desaparición posterior de un artículo falla cerrada:
  el contrato estructural actual no modela aún ``effective_to``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..items import (
    normalize_metadata,
)
from ..legal_structure import (
    KnowledgeBlock,
    KnowledgeBlockVersion,
    KnowledgeStructuredDocument,
    compute_block_version_key,
)
from .article_structure import (
    EurLexArticleBlock,
    EurLexArticleSnapshot,
    compute_eurlex_article_semantic_sha256,
    normalize_eurlex_article_semantic_text,
)


_SOURCE_KEY = (
    "EUR_LEX_CONSOLIDATED"
)

_HISTORY_SCOPE = (
    "ARTICLES_ONLY"
)


@dataclass(
    frozen=True,
    slots=True,
)
class EurLexArticleHistory:
    """Historia estructurada de artículos para una norma EUR-Lex."""

    original_celex: str

    revisions: tuple[
        str,
        ...,
    ]

    document: KnowledgeStructuredDocument

    @property
    def block_count(
        self,
    ) -> int:
        return len(
            self.document.blocks
        )

    @property
    def version_count(
        self,
    ) -> int:
        return len(
            self.document.versions
        )

    @property
    def current_version_count(
        self,
    ) -> int:
        return sum(
            1
            for version
            in self.document.versions
            if version.is_current
        )

    @property
    def historical_version_count(
        self,
    ) -> int:
        return (
            self.version_count
            - self.current_version_count
        )


@dataclass(
    frozen=True,
    slots=True,
)
class _ArticleObservation:
    snapshot: EurLexArticleSnapshot
    article: EurLexArticleBlock
    semantic_sha256: str


def _ordered_snapshots(
    snapshots,
) -> tuple[
    EurLexArticleSnapshot,
    ...,
]:
    values = tuple(
        snapshots
    )

    if not values:
        raise ValueError(
            "Se requiere al menos un "
            "EurLexArticleSnapshot"
        )

    for snapshot in values:
        if not isinstance(
            snapshot,
            EurLexArticleSnapshot,
        ):
            raise TypeError(
                "snapshots debe contener "
                "EurLexArticleSnapshot"
            )

    originals = {
        snapshot.original_celex
        for snapshot
        in values
    }

    if len(
        originals
    ) != 1:
        raise ValueError(
            "Los snapshots EUR-Lex pertenecen "
            "a normas originales distintas"
        )

    revisions = [
        snapshot.consolidated_celex
        for snapshot
        in values
    ]

    if (
        len(
            revisions
        )
        != len(
            set(
                revisions
            )
        )
    ):
        raise ValueError(
            "Revisión EUR-Lex consolidada duplicada"
        )

    dates = [
        snapshot.effective_from
        for snapshot
        in values
    ]

    if (
        len(
            dates
        )
        != len(
            set(
                dates
            )
        )
    ):
        raise ValueError(
            "Dos revisiones EUR-Lex tienen "
            "la misma effective_from"
        )

    return tuple(
        sorted(
            values,
            key=lambda item: (
                item.effective_from,
                item.consolidated_celex,
            ),
        )
    )


def _article_ids(
    snapshots: tuple[
        EurLexArticleSnapshot,
        ...,
    ],
) -> set[str]:
    result = set()

    for snapshot in snapshots:
        result.update(
            article.block_id
            for article
            in snapshot.articles
        )

    return result


def _observations_for_block(
    snapshots: tuple[
        EurLexArticleSnapshot,
        ...,
    ],
    block_id: str,
) -> tuple[
    _ArticleObservation,
    ...,
]:
    observations = []

    seen_present = False
    seen_absent_after_present = False

    for snapshot in snapshots:
        article = snapshot.get(
            block_id
        )

        if article is None:
            if seen_present:
                seen_absent_after_present = True
            continue

        if seen_absent_after_present:
            raise ValueError(
                "La historia EUR-Lex contiene "
                "reaparición de artículo tras ausencia: "
                f"{block_id}"
            )

        seen_present = True

        observations.append(
            _ArticleObservation(
                snapshot=snapshot,
                article=article,
                semantic_sha256=(
                    compute_eurlex_article_semantic_sha256(
                        article.content_text
                    )
                ),
            )
        )

    if not observations:
        raise ValueError(
            "No existen observaciones para "
            f"{block_id}"
        )

    last_snapshot = snapshots[
        -1
    ]

    if (
        last_snapshot.get(
            block_id
        )
        is None
    ):
        raise ValueError(
            "El artículo desaparece en una revisión "
            "posterior y el contrato actual no modela "
            f"effective_to: {block_id}"
        )

    return tuple(
        observations
    )


def _semantic_runs(
    observations: tuple[
        _ArticleObservation,
        ...,
    ],
) -> tuple[
    tuple[
        _ArticleObservation,
        ...,
    ],
    ...,
]:
    runs = []
    current = []

    previous_sha = None

    for observation in observations:
        if (
            current
            and observation.semantic_sha256
            != previous_sha
        ):
            runs.append(
                tuple(
                    current
                )
            )
            current = []

        current.append(
            observation
        )

        previous_sha = (
            observation.semantic_sha256
        )

    if current:
        runs.append(
            tuple(
                current
            )
        )

    return tuple(
        runs
    )


def _version_from_run(
    *,
    original_celex: str,
    block_id: str,
    version_position: int,
    run: tuple[
        _ArticleObservation,
        ...,
    ],
    is_current: bool,
) -> KnowledgeBlockVersion:
    first = run[
        0
    ]

    latest = run[
        -1
    ]

    representative = (
        latest.article
    )

    semantic_text = (
        normalize_eurlex_article_semantic_text(
            representative.content_text
        )
    )

    semantic_sha256 = (
        compute_eurlex_article_semantic_sha256(
            representative.content_text
        )
    )

    version_key = (
        compute_block_version_key(
            source_key=_SOURCE_KEY,
            external_id=original_celex,
            block_id=block_id,
            modifier_external_id="",
            published_on=None,
            effective_from=(
                first.snapshot.effective_from
            ),
            content_text=semantic_text,
        )
    )

    revisions = tuple(
        observation.snapshot.consolidated_celex
        for observation
        in run
    )

    renderers = tuple(
        dict.fromkeys(
            observation.article.renderer
            for observation
            in run
        )
    )

    metadata = normalize_metadata(
        {
            "history_scope": (
                _HISTORY_SCOPE
            ),
            "eurlex_semantic_sha256": (
                semantic_sha256
            ),
            "eurlex_first_revision": (
                revisions[
                    0
                ]
            ),
            "eurlex_last_revision": (
                revisions[
                    -1
                ]
            ),
            "eurlex_observed_revisions": (
                "|".join(
                    revisions
                )
            ),
            "eurlex_observed_renderers": (
                "|".join(
                    renderers
                )
            ),
            "eurlex_legal_identifier": (
                representative.legal_identifier
            ),
            "eurlex_latest_native_structural_id": (
                representative.native_structural_id
            ),
            "eurlex_latest_heading_source_id": (
                representative.heading_source_id
            ),
        }
    )

    return KnowledgeBlockVersion(
        source_key=_SOURCE_KEY,
        external_id=original_celex,
        block_id=block_id,
        version_key=version_key,
        version_position=(
            version_position
        ),
        content_text=(
            representative.content_text
        ),
        modifier_external_id="",
        published_on=None,
        effective_from=(
            first.snapshot.effective_from
        ),
        is_current=is_current,
        metadata=metadata,
    )


def build_eurlex_article_history(
    snapshots,
) -> EurLexArticleHistory:
    """Construye historia temporal de artículos EUR-Lex.

    Los snapshots pueden llegar desordenados; se ordenan por
    ``effective_from``.

    Los runs consecutivos con el mismo fingerprint semántico
    se colapsan en una única KnowledgeBlockVersion.
    """

    ordered = (
        _ordered_snapshots(
            snapshots
        )
    )

    original_celex = (
        ordered[
            0
        ].original_celex
    )

    latest_snapshot = (
        ordered[
            -1
        ]
    )

    latest_by_id = {
        article.block_id:
            article
        for article
        in latest_snapshot.articles
    }

    all_ids = (
        _article_ids(
            ordered
        )
    )

    missing_from_latest = (
        all_ids
        - set(
            latest_by_id
        )
    )

    if missing_from_latest:
        raise ValueError(
            "La historia contiene artículos que "
            "desaparecen en la revisión vigente; "
            "effective_to todavía no está modelado: "
            f"{tuple(sorted(missing_from_latest))}"
        )

    blocks = []
    versions = []

    for latest_article in (
        latest_snapshot.articles
    ):
        block_id = (
            latest_article.block_id
        )

        observations = (
            _observations_for_block(
                ordered,
                block_id,
            )
        )

        runs = (
            _semantic_runs(
                observations
            )
        )

        block_versions = []

        for index, run in enumerate(
            runs,
            start=1,
        ):
            version = (
                _version_from_run(
                    original_celex=(
                        original_celex
                    ),
                    block_id=block_id,
                    version_position=index,
                    run=run,
                    is_current=(
                        index
                        == len(
                            runs
                        )
                    ),
                )
            )

            block_versions.append(
                version
            )

        current = (
            block_versions[
                -1
            ]
        )

        blocks.append(
            KnowledgeBlock(
                source_key=_SOURCE_KEY,
                external_id=(
                    original_celex
                ),
                block_id=block_id,
                position=(
                    latest_article.position
                ),
                title=(
                    latest_article.heading
                ),
                canonical_uri="",
                current_version_key=(
                    current.version_key
                ),
                metadata=normalize_metadata(
                    {
                        "history_scope": (
                            _HISTORY_SCOPE
                        ),
                        "eurlex_legal_identifier": (
                            latest_article.legal_identifier
                        ),
                        "eurlex_latest_renderer": (
                            latest_article.renderer
                        ),
                        "eurlex_latest_native_structural_id": (
                            latest_article.native_structural_id
                        ),
                        "eurlex_latest_heading_source_id": (
                            latest_article.heading_source_id
                        ),
                        "eurlex_latest_subtitle": (
                            latest_article.title
                        ),
                    }
                ),
            )
        )

        versions.extend(
            block_versions
        )

    document = (
        KnowledgeStructuredDocument(
            source_key=_SOURCE_KEY,
            external_id=original_celex,
            blocks=tuple(
                blocks
            ),
            versions=tuple(
                versions
            ),
        )
    )

    return EurLexArticleHistory(
        original_celex=(
            original_celex
        ),
        revisions=tuple(
            snapshot.consolidated_celex
            for snapshot
            in ordered
        ),
        document=document,
    )
