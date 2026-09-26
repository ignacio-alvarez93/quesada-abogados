"""
Adapter manual/determinista.

Útil para:
- pruebas;
- importaciones asistidas;
- seeds controlados;
- pruebas de nuevos verticales;
- fallback operacional.
"""

from backend.trend_intelligence.sources.base import (
    TrendObservationInput,
)


class ManualTrendSourceAdapter:
    def __init__(
        self,
        source_code,
        observations,
    ):
        self._source_code = str(
            source_code
        ).strip()

        self._observations = tuple(
            observations
        )

        if not self._source_code:
            raise ValueError(
                "source_code obligatorio"
            )

        for item in (
            self._observations
        ):
            if not isinstance(
                item,
                TrendObservationInput,
            ):
                raise TypeError(
                    (
                        "ManualTrendSourceAdapter "
                        "requiere "
                        "TrendObservationInput"
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
        return iter(
            self._observations
        )
