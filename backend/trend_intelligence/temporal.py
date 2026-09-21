"""
Trend Intelligence · temporal intelligence.

Responsabilidades:
- materializar métricas por ventana;
- consultar historia;
- calcular baseline histórico;
- calcular desviación respecto a baseline.

No:
- crea señales automáticas;
- decide estados de tendencia;
- depende de collectors;
- depende de un vertical concreto.
"""

from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
from statistics import (
    mean,
    pstdev,
)

from backend.trend_intelligence.models import (
    TrendTemporalBaseline,
    TrendTemporalMetric,
)


def _text(
    value,
):
    return str(
        value
        or ""
    ).strip()


def _key(
    value,
):
    value = (
        _text(
            value
        )
        .upper()
        .replace(
            "-",
            "_",
        )
        .replace(
            " ",
            "_",
        )
    )

    if not value:
        raise ValueError(
            "Clave obligatoria"
        )

    return value


def _datetime(
    value,
):
    if isinstance(
        value,
        datetime,
    ):
        parsed = value

    else:
        raw = _text(
            value
        )

        if not raw:
            raise ValueError(
                "Fecha obligatoria"
            )

        parsed = (
            datetime.fromisoformat(
                raw.replace(
                    "Z",
                    "+00:00",
                )
            )
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return (
        parsed
        .replace(
            microsecond=0
        )
        .isoformat()
    )


def _safe_mean(
    values,
):
    if not values:
        return 0.0

    return round(
        float(
            mean(
                values
            )
        ),
        6,
    )


def _safe_stddev(
    values,
):
    if len(
        values
    ) <= 1:
        return 0.0

    return round(
        float(
            pstdev(
                values
            )
        ),
        6,
    )


def _growth_percent(
    current,
    baseline,
):
    current = float(
        current
    )

    baseline = float(
        baseline
    )

    if baseline <= 0:
        return (
            None
            if current <= 0
            else 100.0
        )

    return round(
        (
            (
                current
                - baseline
            )
            / baseline
        )
        * 100.0,
        4,
    )


def _z_score(
    current,
    baseline_mean,
    baseline_stddev,
):
    current = float(
        current
    )

    baseline_mean = float(
        baseline_mean
    )

    baseline_stddev = float(
        baseline_stddev
    )

    if baseline_stddev <= 0:
        if current == baseline_mean:
            return 0.0

        return (
            1.0
            if current > baseline_mean
            else -1.0
        )

    return round(
        (
            current
            - baseline_mean
        )
        / baseline_stddev,
        6,
    )


@dataclass(
    frozen=True,
    slots=True,
)
class TemporalWindowAnalysis:
    metric: TrendTemporalMetric
    baseline: TrendTemporalBaseline

    observation_growth_percent: float | None
    source_growth_percent: float | None
    signal_growth_percent: float | None

    observation_z_score: float
    source_z_score: float
    signal_z_score: float


class TrendTemporalIntelligenceService:
    def __init__(
        self,
        repository,
    ):
        self.repository = (
            repository
        )

    def _resolve_scope(
        self,
        *,
        domain_code,
        topic_key,
    ):
        domain = (
            self.repository
            .get_domain_by_code(
                _key(
                    domain_code
                )
            )
        )

        topic = (
            self.repository
            .get_topic_by_key(
                _key(
                    topic_key
                )
            )
        )

        if domain is None:
            raise ValueError(
                "Dominio inexistente"
            )

        if topic is None:
            raise ValueError(
                "Topic inexistente"
            )

        domain_ids = {
            item.domain_id
            for item
            in self.repository
            .list_topic_domains(
                topic.id
            )
        }

        if (
            domain.id
            not in domain_ids
        ):
            raise ValueError(
                (
                    "Topic fuera del dominio "
                    "solicitado"
                )
            )

        return (
            domain,
            topic,
        )

    def materialize_window(
        self,
        *,
        domain_code,
        topic_key,
        window_start,
        window_end,
        country="",
        language="",
    ):
        domain, topic = (
            self._resolve_scope(
                domain_code=(
                    domain_code
                ),
                topic_key=(
                    topic_key
                ),
            )
        )

        window_start = (
            _datetime(
                window_start
            )
        )

        window_end = (
            _datetime(
                window_end
            )
        )

        if (
            window_end
            < window_start
        ):
            raise ValueError(
                "Ventana temporal inválida"
            )

        country = (
            _text(
                country
            )
            .upper()
        )

        language = (
            _text(
                language
            )
            .lower()
        )

        stats = (
            self.repository
            .get_temporal_window_stats(
                domain.id,
                topic.id,
                window_start=(
                    window_start
                ),
                window_end=(
                    window_end
                ),
                country=country,
                language=language,
            )
        )

        return (
            self.repository
            .save_temporal_metric(
                TrendTemporalMetric(
                    id=None,
                    domain_id=(
                        domain.id
                    ),
                    topic_id=(
                        topic.id
                    ),
                    window_start=(
                        window_start
                    ),
                    window_end=(
                        window_end
                    ),
                    country=country,
                    language=language,
                    observation_count=(
                        stats[
                            "observation_count"
                        ]
                    ),
                    source_count=(
                        stats[
                            "source_count"
                        ]
                    ),
                    signal_count=(
                        stats[
                            "signal_count"
                        ]
                    ),
                )
            )
        )

    def calculate_baseline(
        self,
        *,
        domain_code,
        topic_key,
        reference_window_start,
        reference_window_end,
        lookback_windows=7,
        country="",
        language="",
    ):
        domain, topic = (
            self._resolve_scope(
                domain_code=(
                    domain_code
                ),
                topic_key=(
                    topic_key
                ),
            )
        )

        reference_window_start = (
            _datetime(
                reference_window_start
            )
        )

        reference_window_end = (
            _datetime(
                reference_window_end
            )
        )

        if (
            reference_window_end
            < reference_window_start
        ):
            raise ValueError(
                "Ventana de referencia inválida"
            )

        lookback_windows = int(
            lookback_windows
        )

        if lookback_windows < 1:
            raise ValueError(
                (
                    "lookback_windows debe "
                    "ser >= 1"
                )
            )

        country = (
            _text(
                country
            )
            .upper()
        )

        language = (
            _text(
                language
            )
            .lower()
        )

        history = (
            self.repository
            .list_temporal_metrics_before(
                domain.id,
                topic.id,
                before_window_start=(
                    reference_window_start
                ),
                country=country,
                language=language,
                limit=(
                    lookback_windows
                ),
            )
        )

        observation_values = [
            item.observation_count
            for item
            in history
        ]

        source_values = [
            item.source_count
            for item
            in history
        ]

        signal_values = [
            item.signal_count
            for item
            in history
        ]

        baseline = (
            TrendTemporalBaseline(
                id=None,
                domain_id=(
                    domain.id
                ),
                topic_id=(
                    topic.id
                ),
                reference_window_start=(
                    reference_window_start
                ),
                reference_window_end=(
                    reference_window_end
                ),
                lookback_windows=(
                    lookback_windows
                ),
                sample_count=len(
                    history
                ),
                country=country,
                language=language,
                observation_mean=(
                    _safe_mean(
                        observation_values
                    )
                ),
                observation_stddev=(
                    _safe_stddev(
                        observation_values
                    )
                ),
                source_mean=(
                    _safe_mean(
                        source_values
                    )
                ),
                source_stddev=(
                    _safe_stddev(
                        source_values
                    )
                ),
                signal_mean=(
                    _safe_mean(
                        signal_values
                    )
                ),
                signal_stddev=(
                    _safe_stddev(
                        signal_values
                    )
                ),
            )
        )

        return (
            self.repository
            .save_temporal_baseline(
                baseline
            )
        )

    def analyze_window(
        self,
        *,
        domain_code,
        topic_key,
        window_start,
        window_end,
        lookback_windows=7,
        country="",
        language="",
    ):
        metric = (
            self.materialize_window(
                domain_code=(
                    domain_code
                ),
                topic_key=(
                    topic_key
                ),
                window_start=(
                    window_start
                ),
                window_end=(
                    window_end
                ),
                country=country,
                language=language,
            )
        )

        baseline = (
            self.calculate_baseline(
                domain_code=(
                    domain_code
                ),
                topic_key=(
                    topic_key
                ),
                reference_window_start=(
                    window_start
                ),
                reference_window_end=(
                    window_end
                ),
                lookback_windows=(
                    lookback_windows
                ),
                country=country,
                language=language,
            )
        )

        return (
            TemporalWindowAnalysis(
                metric=metric,
                baseline=baseline,

                observation_growth_percent=(
                    _growth_percent(
                        metric.observation_count,
                        baseline.observation_mean,
                    )
                ),

                source_growth_percent=(
                    _growth_percent(
                        metric.source_count,
                        baseline.source_mean,
                    )
                ),

                signal_growth_percent=(
                    _growth_percent(
                        metric.signal_count,
                        baseline.signal_mean,
                    )
                ),

                observation_z_score=(
                    _z_score(
                        metric.observation_count,
                        baseline.observation_mean,
                        baseline.observation_stddev,
                    )
                ),

                source_z_score=(
                    _z_score(
                        metric.source_count,
                        baseline.source_mean,
                        baseline.source_stddev,
                    )
                ),

                signal_z_score=(
                    _z_score(
                        metric.signal_count,
                        baseline.signal_mean,
                        baseline.signal_stddev,
                    )
                ),
            )
        )
