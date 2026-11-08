"""
Adapter de Instagram para Trend Intelligence.

Instagram es una fuente mas (TrendSourceAdapter), no un motor nuevo.

Este modulo es deliberadamente agnostico de navegador: no importa
SeleniumBase ni conoce Chrome. Consume observaciones crudas ya
recolectadas (por un collector real o por fixtures de test) y las
normaliza al contrato existente ``TrendObservationInput``.

La recoleccion real vía navegador vive en
``backend.trend_intelligence.sources.instagram_browser``.
"""

from dataclasses import dataclass
import re

from backend.trend_intelligence.sources.base import (
    TrendObservationInput,
)


_HASHTAG_PATTERN = re.compile(r"#(\w+)")


@dataclass(
    frozen=True,
    slots=True,
)
class InstagramRawObservation:
    """Evidencia cruda de una pieza de contenido de Instagram.

    Campos obligatorios: lo minimo que el collector siempre conoce
    tras una navegacion exitosa a una cuenta/post accesible.

    Campos opcionales ausentes deben quedar en None en vez de
    inventarse (metricas no visibles, published_at no disponible...).
    """

    source_account: str
    external_id: str
    canonical_url: str
    content_type: str
    observed_at: str

    published_at: str | None = None
    caption: str | None = None
    hashtags: tuple[str, ...] = ()

    like_count: int | None = None
    comment_count: int | None = None
    view_count: int | None = None

    raw_hash: str | None = None
    collection_run_id: str | None = None

    def __post_init__(self):
        for field_name in (
            "source_account",
            "external_id",
            "canonical_url",
            "content_type",
            "observed_at",
        ):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(
                    f"InstagramRawObservation.{field_name} obligatorio"
                )


def _extract_hashtags(caption):
    if not caption:
        return ()

    return tuple(
        dict.fromkeys(
            match.lower()
            for match in _HASHTAG_PATTERN.findall(caption)
        )
    )


def normalize_instagram_post(raw):
    """Convierte una observacion cruda de Instagram en TrendObservationInput.

    No valida negocio adicional: la validacion final (p.ej. formato de
    fechas) pertenece a TrendIntelligenceService.record_observation.
    Se conserva el contrato fail-fast del pipeline del CRM.
    """

    if not isinstance(raw, InstagramRawObservation):
        raise TypeError(
            "normalize_instagram_post requiere InstagramRawObservation"
        )

    hashtags = raw.hashtags or _extract_hashtags(raw.caption)

    metadata = {
        "hashtags": list(hashtags) if hashtags else None,
        "metrics": {
            "like_count": raw.like_count,
            "comment_count": raw.comment_count,
            "view_count": raw.view_count,
        },
        "raw_hash": raw.raw_hash,
    }

    if raw.collection_run_id:
        metadata["collection_run_id"] = raw.collection_run_id

    return TrendObservationInput(
        observation_type=raw.content_type,
        external_id=raw.external_id,
        url=raw.canonical_url,
        title=None,
        body_text=raw.caption,
        author=raw.source_account,
        published_at=raw.published_at,
        observed_at=raw.observed_at,
        language=None,
        country=None,
        content_hash=None,
        metadata=metadata,
    )


class InstagramTrendSourceAdapter:
    """Adapter de solo lectura que conforma TrendSourceAdapter.

    No navega, no decide targets ni limites: solo normaliza las
    observaciones crudas que recibe.
    """

    def __init__(
        self,
        source_code,
        raw_observations,
    ):
        self._source_code = str(
            source_code
        ).strip()

        if not self._source_code:
            raise ValueError(
                "source_code obligatorio"
            )

        self._raw_observations = tuple(
            raw_observations
        )

        for item in self._raw_observations:
            if not isinstance(
                item,
                InstagramRawObservation,
            ):
                raise TypeError(
                    (
                        "InstagramTrendSourceAdapter "
                        "requiere InstagramRawObservation"
                    )
                )

    @property
    def source_code(
        self,
    ):
        return self._source_code

    def collect(
        self,
    ):
        return (
            normalize_instagram_post(raw)
            for raw in self._raw_observations
        )
