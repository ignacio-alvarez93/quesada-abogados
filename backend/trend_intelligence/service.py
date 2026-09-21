"""
Trend Intelligence application service.

Domain-neutral.
Provider-neutral.
Storage-neutral.

Los verticales se registran mediante TrendDomain.
"""


import hashlib
import json
import re
from datetime import (
    datetime,
    timezone,
)

from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.models import (
    canonical_time,
    canonical_window,
    canonical_country,
    canonical_language,

    ObservationDomain,
    ObservationTopic,
    TopicDomain,
    Trend,
    TrendDomain,
    TrendEvidence,
    TrendObservation,
    TrendSignal,
    TrendSource,
    TrendTopic,
    TrendTopicAlias,
    VALID_COLLECTION_MODES,
    VALID_SIGNAL_TYPES,
)
from backend.trend_intelligence.scoring import (
    score_trend,
    signal_weight,
)


_KEY_PATTERN = re.compile(
    r"[^A-Z0-9]+"
)


def _text(value):
    return str(
        value
        or ""
    ).strip()


def _optional_text(value):
    value = _text(
        value
    )

    return value or None


def _normalize_key(value):
    value = (
        _KEY_PATTERN
        .sub(
            "_",
            _text(
                value
            ).upper(),
        )
        .strip("_")
    )

    if not value:
        raise ValueError(
            "Clave vacía"
        )

    return value


def _normalize_datetime(value, *, required=True):
    if value in (None, ""):
        if not required:
            return None
        value = datetime.now(timezone.utc)
    return canonical_time(value)


def _content_hash(
    *,
    observation_type,
    url,
    title,
    body_text,
    author,
    published_at,
):
    payload = {
        "observation_type":
            _normalize_key(
                observation_type
            ),
        "url":
            _text(
                url
            ),
        "title":
            " ".join(
                _text(
                    title
                ).split()
            ),
        "body_text":
            " ".join(
                _text(
                    body_text
                ).split()
            ),
        "author":
            " ".join(
                _text(
                    author
                ).split()
            ),
        "published_at":
            _normalize_datetime(published_at, required=False),
    }

    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )
    ).hexdigest()


class TrendIntelligenceService:
    def __init__(
        self,
        repository=None,
    ):
        self.repository = (
            repository
            or SQLiteTrendIntelligenceRepository()
        )

    def ensure_schema(self):
        self.repository.ensure_schema()

    def create_domain(
        self,
        *,
        code,
        name,
        description=None,
        metadata=None,
        is_active=True,
    ):
        clean_name = _text(
            name
        )

        if not clean_name:
            raise ValueError(
                "name obligatorio"
            )

        return self.repository.save_domain(
            TrendDomain(
                id=None,
                code=_normalize_key(
                    code
                ),
                name=clean_name,
                description=(
                    _optional_text(
                        description
                    )
                ),
                is_active=bool(
                    is_active
                ),
                metadata=metadata,
            )
        )

    def create_source(
        self,
        *,
        code,
        name,
        source_type,
        provider=None,
        base_url=None,
        collection_mode="MANUAL",
        country=None,
        language=None,
        configuration=None,
        is_active=True,
    ):
        mode = _normalize_key(
            collection_mode
        )

        if (
            mode
            not in VALID_COLLECTION_MODES
        ):
            raise ValueError(
                (
                    "collection_mode inválido: "
                    f"{mode}"
                )
            )

        return self.repository.save_source(
            TrendSource(
                id=None,
                code=_normalize_key(
                    code
                ),
                name=_text(
                    name
                ),
                source_type=(
                    _normalize_key(
                        source_type
                    )
                ),
                provider=(
                    _optional_text(
                        provider
                    )
                ),
                base_url=(
                    _optional_text(
                        base_url
                    )
                ),
                collection_mode=mode,
                country=(
                    _optional_text(
                        country
                    )
                ),
                language=(
                    _optional_text(
                        language
                    )
                ),
                is_active=bool(
                    is_active
                ),
                configuration=(
                    configuration
                ),
            )
        )

    def create_topic(
        self,
        *,
        topic_key,
        name,
        category=None,
        description=None,
        parent_topic_key=None,
        domain_codes=(),
        metadata=None,
    ):
        parent_id = None

        if parent_topic_key:
            parent = (
                self.repository
                .get_topic_by_key(
                    _normalize_key(
                        parent_topic_key
                    )
                )
            )

            if parent is None:
                raise ValueError(
                    "Topic padre inexistente"
                )

            parent_id = (
                parent.id
            )

        topic = (
            self.repository
            .save_topic(
                TrendTopic(
                    id=None,
                    topic_key=(
                        _normalize_key(
                            topic_key
                        )
                    ),
                    name=_text(
                        name
                    ),
                    description=(
                        _optional_text(
                            description
                        )
                    ),
                    category=(
                        _optional_text(
                            category
                        )
                    ),
                    parent_topic_id=(
                        parent_id
                    ),
                    metadata=metadata,
                )
            )
        )

        for domain_code in (
            domain_codes
            or ()
        ):
            self.assign_topic_domain(
                topic.topic_key,
                domain_code,
            )

        return topic

    def register_topic_alias(
        self,
        topic_key,
        alias_text,
        *,
        language="",
        country="",
        confidence=1.0,
        metadata=None,
        is_active=True,
    ):
        topic = (
            self.repository
            .get_topic_by_key(
                _normalize_key(
                    topic_key
                )
            )
        )

        if topic is None:
            raise ValueError(
                "Topic inexistente"
            )

        clean_alias_text = _text(
            alias_text
        )

        if not clean_alias_text:
            raise ValueError(
                "alias_text obligatorio"
            )

        confidence = float(
            confidence
        )

        if not (
            0.0
            <= confidence
            <= 1.0
        ):
            raise ValueError(
                "confidence inválido"
            )

        return (
            self.repository
            .save_topic_alias(
                TrendTopicAlias(
                    id=None,
                    topic_id=(
                        topic.id
                    ),
                    alias_key=(
                        _normalize_key(
                            clean_alias_text
                        )
                    ),
                    alias_text=(
                        clean_alias_text
                    ),
                    language=(
                        _text(
                            language
                        ).lower()
                    ),
                    country=(
                        _text(
                            country
                        ).upper()
                    ),
                    confidence=(
                        confidence
                    ),
                    is_active=bool(
                        is_active
                    ),
                    metadata=metadata,
                )
            )
        )

    def resolve_topic(
        self,
        value,
        *,
        language="",
        country="",
    ):
        normalized = (
            _normalize_key(
                value
            )
        )

        direct = (
            self.repository
            .get_topic_by_key(
                normalized
            )
        )

        if direct is not None:
            return direct

        return (
            self.repository
            .resolve_topic_alias(
                normalized,
                language=(
                    _text(
                        language
                    ).lower()
                ),
                country=(
                    _text(
                        country
                    ).upper()
                ),
            )
        )

    def list_domain_topics(
        self,
        domain_code,
        *,
        active_only=True,
    ):
        domain = (
            self.repository
            .get_domain_by_code(
                _normalize_key(
                    domain_code
                )
            )
        )

        if domain is None:
            raise ValueError(
                "Dominio inexistente"
            )

        return (
            self.repository
            .list_topics_for_domain(
                domain.id,
                active_only=(
                    active_only
                ),
            )
        )

    def assign_topic_domain(
        self,
        topic_key,
        domain_code,
        *,
        relevance=1.0,
    ):
        topic = (
            self.repository
            .get_topic_by_key(
                _normalize_key(
                    topic_key
                )
            )
        )

        domain = (
            self.repository
            .get_domain_by_code(
                _normalize_key(
                    domain_code
                )
            )
        )

        if topic is None:
            raise ValueError(
                "Topic inexistente"
            )

        if domain is None:
            raise ValueError(
                "Dominio inexistente"
            )

        relevance = float(
            relevance
        )

        if not (
            0.0
            <= relevance
            <= 1.0
        ):
            raise ValueError(
                (
                    "relevance debe estar "
                    "entre 0 y 1"
                )
            )

        return (
            self.repository
            .link_topic_domain(
                TopicDomain(
                    topic_id=topic.id,
                    domain_id=(
                        domain.id
                    ),
                    relevance=(
                        relevance
                    ),
                )
            )
        )

    def assign_observation_domain(
        self,
        observation_id,
        domain_code,
        *,
        confidence=1.0,
        detection_method="MANUAL",
    ):
        observation = (
            self.repository
            .get_observation(
                int(
                    observation_id
                )
            )
        )

        domain = (
            self.repository
            .get_domain_by_code(
                _normalize_key(
                    domain_code
                )
            )
        )

        if observation is None:
            raise ValueError(
                "Observación inexistente"
            )

        if domain is None:
            raise ValueError(
                "Dominio inexistente"
            )

        confidence = float(
            confidence
        )

        if not (
            0.0
            <= confidence
            <= 1.0
        ):
            raise ValueError(
                "confidence inválido"
            )

        return (
            self.repository
            .link_observation_domain(
                ObservationDomain(
                    observation_id=(
                        observation.id
                    ),
                    domain_id=(
                        domain.id
                    ),
                    confidence=(
                        confidence
                    ),
                    detection_method=(
                        _normalize_key(
                            detection_method
                        )
                    ),
                )
            )
        )

    def record_observation(
        self,
        *,
        source_code,
        observation_type,
        external_id=None,
        url=None,
        title=None,
        body_text=None,
        author=None,
        published_at=None,
        observed_at=None,
        language=None,
        country=None,
        metadata=None,
        content_hash=None,
    ):
        source = (
            self.repository
            .get_source_by_code(
                _normalize_key(
                    source_code
                )
            )
        )

        if source is None:
            raise ValueError(
                "Fuente inexistente"
            )

        published_at = (
            _normalize_datetime(
                published_at,
                required=False,
            )
        )

        observed_at = (
            _normalize_datetime(
                observed_at,
                required=True,
            )
        )

        content_hash = (
            _optional_text(
                content_hash
            )
            or _content_hash(
                observation_type=(
                    observation_type
                ),
                url=url,
                title=title,
                body_text=body_text,
                author=author,
                published_at=(
                    published_at
                ),
            )
        )

        return (
            self.repository
            .get_or_create_observation_with_status(
                TrendObservation(
                    id=None,
                    source_id=(
                        source.id
                    ),
                    external_id=(
                        _optional_text(
                            external_id
                        )
                    ),
                    observation_type=(
                        _normalize_key(
                            observation_type
                        )
                    ),
                    url=_optional_text(
                        url
                    ),
                    title=_optional_text(
                        title
                    ),
                    body_text=(
                        _optional_text(
                            body_text
                        )
                    ),
                    author=_optional_text(
                        author
                    ),
                    published_at=(
                        published_at
                    ),
                    observed_at=(
                        observed_at
                    ),
                    language=(
                        _optional_text(
                            language
                        )
                        or source.language
                    ),
                    country=(
                        _optional_text(
                            country
                        )
                        or source.country
                    ),
                    content_hash=(
                        content_hash
                    ),
                    metadata=metadata,
                )
            )
        )

    def classify_observation(
        self,
        observation_id,
        *,
        domain_code,
        topic_key,
        confidence=1.0,
        detection_method="MANUAL",
    ):
        observation = (
            self.repository
            .get_observation(
                int(
                    observation_id
                )
            )
        )

        domain = (
            self.repository
            .get_domain_by_code(
                _normalize_key(
                    domain_code
                )
            )
        )

        topic = (
            self.repository
            .get_topic_by_key(
                _normalize_key(
                    topic_key
                )
            )
        )

        if observation is None:
            raise ValueError(
                "Observación inexistente"
            )

        if domain is None:
            raise ValueError(
                "Dominio inexistente"
            )

        if topic is None:
            raise ValueError(
                "Topic inexistente"
            )

        topic_domain_ids = {
            item.domain_id
            for item
            in self.repository
            .list_topic_domains(
                topic.id
            )
        }

        if (
            domain.id
            not in topic_domain_ids
        ):
            raise ValueError(
                (
                    "El topic no pertenece "
                    "al dominio solicitado"
                )
            )

        confidence = float(
            confidence
        )

        if not (
            0.0
            <= confidence
            <= 1.0
        ):
            raise ValueError(
                "confidence inválido"
            )

        self.assign_observation_domain(
            observation.id,
            domain.code,
            confidence=confidence,
            detection_method=(
                detection_method
            ),
        )

        return (
            self.repository
            .link_observation_topic(
                ObservationTopic(
                    observation_id=(
                        observation.id
                    ),
                    topic_id=topic.id,
                    confidence=(
                        confidence
                    ),
                    detection_method=(
                        _normalize_key(
                            detection_method
                        )
                    ),
                )
            )
        )

    def create_signal(
        self,
        *,
        observation_id,
        domain_code,
        topic_key,
        signal_type,
        strength,
        confidence=1.0,
        numeric_value=None,
        text_value=None,
        detected_at=None,
        metadata=None,
    ):
        observation = (
            self.repository
            .get_observation(
                int(
                    observation_id
                )
            )
        )

        domain = (
            self.repository
            .get_domain_by_code(
                _normalize_key(
                    domain_code
                )
            )
        )

        topic = (
            self.repository
            .get_topic_by_key(
                _normalize_key(
                    topic_key
                )
            )
        )

        if observation is None:
            raise ValueError(
                "Observación inexistente"
            )

        if domain is None:
            raise ValueError(
                "Dominio inexistente"
            )

        if topic is None:
            raise ValueError(
                "Topic inexistente"
            )

        topic_domain_ids = {
            item.domain_id
            for item
            in self.repository
            .list_topic_domains(
                topic.id
            )
        }

        if (
            domain.id
            not in topic_domain_ids
        ):
            raise ValueError(
                (
                    "Topic fuera del dominio "
                    "solicitado"
                )
            )

        observation_domain_ids = {
            item.domain_id
            for item
            in self.repository
            .list_observation_domains(
                observation.id
            )
        }

        if (
            domain.id
            not in observation_domain_ids
        ):
            raise ValueError(
                (
                    "Observación fuera del dominio "
                    "solicitado"
                )
            )

        signal_type = (
            _normalize_key(
                signal_type
            )
        )

        if (
            signal_type
            not in VALID_SIGNAL_TYPES
        ):
            raise ValueError(
                "signal_type inválido"
            )

        strength = float(
            strength
        )

        confidence = float(
            confidence
        )

        if not (
            0.0
            <= strength
            <= 100.0
        ):
            raise ValueError(
                "strength inválido"
            )

        if not (
            0.0
            <= confidence
            <= 1.0
        ):
            raise ValueError(
                "confidence inválido"
            )

        return (
            self.repository
            .save_signal_with_status(
                TrendSignal(
                    id=None,
                    observation_id=(
                        observation.id
                    ),
                    topic_id=topic.id,
                    signal_type=(
                        signal_type
                    ),
                    strength=(
                        strength
                    ),
                    confidence=(
                        confidence
                    ),
                    numeric_value=(
                        float(
                            numeric_value
                        )
                        if numeric_value
                        is not None
                        else None
                    ),
                    text_value=(
                        _optional_text(
                            text_value
                        )
                    ),
                    detected_at=(
                        _normalize_datetime(
                            detected_at
                        )
                    ),
                    metadata=metadata,
                )
            )
        )

    def recalculate_trend(
        self,
        *,
        domain_code,
        topic_key,
        window_start,
        window_end,
        country="",
        language="",
        metadata=None,
    ):
        domain = (
            self.repository
            .get_domain_by_code(
                _normalize_key(
                    domain_code
                )
            )
        )

        topic = (
            self.repository
            .get_topic_by_key(
                _normalize_key(
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

        linked_domains = {
            item.domain_id
            for item
            in self.repository
            .list_topic_domains(
                topic.id
            )
        }

        if (
            domain.id
            not in linked_domains
        ):
            raise ValueError(
                (
                    "El topic no pertenece "
                    "al dominio solicitado"
                )
            )

        window_start, window_end = canonical_window(window_start, window_end)
        country = canonical_country(country)

        language = canonical_language(language)

        signals = (
            self.repository
            .list_signals_for_topic(
                domain.id,
                topic.id,
                country=country, language=language,
                window_start=(
                    window_start
                ),
                window_end=(
                    window_end
                ),
            )
        )

        stats = (
            self.repository
            .get_topic_window_stats(
                domain.id,
                topic.id,
                country=country, language=language,
                window_start=(
                    window_start
                ),
                window_end=(
                    window_end
                ),
            )
        )

        previous = (
            self.repository
            .get_latest_trend_before(
                domain.id,
                topic.id,
                country=country,
                language=language,
                before_window_start=(
                    window_start
                ),
            )
        )

        score = score_trend(
            signals,
            previous_score=(
                previous.score
                if previous
                else None
            ),
        )

        evidence = [
            TrendEvidence(
                id=None,
                trend_id=None,
                signal_id=(
                    signal.id
                ),
                weight=signal_weight(
                    signal.signal_type
                ),
                reason=(
                    f"{signal.signal_type}:"
                    f"strength={signal.strength:.2f};"
                    f"confidence={signal.confidence:.2f}"
                ),
            )
            for signal
            in signals
        ]

        trend = Trend(
            id=None,
            domain_id=(
                domain.id
            ),
            topic_id=topic.id,
            status=score.status,
            score=score.score,
            velocity=(
                score.velocity
            ),
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
            window_start=(
                window_start
            ),
            window_end=(
                window_end
            ),
            country=country,
            language=language,
            first_seen_at=(
                stats[
                    "first_seen_at"
                ]
            ),
            last_seen_at=(
                stats[
                    "last_seen_at"
                ]
            ),
            metadata=metadata,
        )

        stored = (
            self.repository
            .save_trend_with_evidence(
                trend,
                evidence,
            )
        )

        return {
            "trend":
                stored,
            "signals":
                signals,
            "evidence":
                self.repository
                .list_trend_evidence(
                    stored.id
                ),
            "previous_trend":
                previous,
        }

    def list_domain_trends(
        self,
        domain_code,
        *,
        status=None,
        limit=100,
    ):
        domain = (
            self.repository
            .get_domain_by_code(
                _normalize_key(
                    domain_code
                )
            )
        )

        if domain is None:
            raise ValueError(
                "Dominio inexistente"
            )

        normalized_status = (
            _normalize_key(
                status
            )
            if status
            else None
        )

        return (
            self.repository
            .list_trends(
                domain_id=(
                    domain.id
                ),
                status=(
                    normalized_status
                ),
                limit=limit,
            )
        )

    def get_trend_evidence(
        self,
        trend_id,
    ):
        trend = (
            self.repository
            .get_trend(
                int(
                    trend_id
                )
            )
        )

        if trend is None:
            raise ValueError(
                "Trend inexistente"
            )

        return (
            self.repository
            .list_trend_evidence(
                trend.id
            )
        )
