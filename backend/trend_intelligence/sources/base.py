"""
Contratos de proveedores de Trend Intelligence.

Un adapter produce observaciones normalizadas.

No:
- persiste;
- clasifica topics;
- genera trends;
- decide reglas de negocio.
"""

from dataclasses import dataclass
from typing import (
    Any,
    Iterable,
    Protocol,
)


@dataclass(
    frozen=True,
    slots=True,
)
class TrendObservationInput:
    observation_type: str

    external_id: str | None = None
    url: str | None = None

    title: str | None = None
    body_text: str | None = None
    author: str | None = None

    published_at: str | None = None
    observed_at: str | None = None

    language: str | None = None
    country: str | None = None

    content_hash: str | None = None

    metadata: dict[
        str,
        Any,
    ] | None = None


class TrendSourceAdapter(
    Protocol
):
    @property
    def source_code(
        self,
    ) -> str:
        ...

    def collect(
        self,
    ) -> Iterable[
        TrendObservationInput
    ]:
        ...
