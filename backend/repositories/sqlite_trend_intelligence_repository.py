"""
SQLite repository para Trend Intelligence.

Toda dependencia SQLite queda encapsulada aquí.
"""

from dataclasses import replace, fields
from threading import local

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.trend_intelligence.models import (
    canonical_time,
    canonical_window,
    canonical_country,
    canonical_language,
    time_key,
    finite_number,

    ObservationDomain,
    ObservationTopic,
    TopicDomain,
    Trend,
    TrendAggregateSignal,
    TrendDomain,
    TrendEvidence,
    TrendObservation,
    TrendSignal,
    TrendSource,
    TrendSnapshot,
    TrendTemporalBaseline,
    TrendTemporalMetric,
    TrendTopic,
    TrendTopicAlias,
)


PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)

DEFAULT_DB_PATH = (
    PROJECT_ROOT
    / "database"
    / "quesada.db"
)

MIGRATION_PATHS = (
    (
        PROJECT_ROOT
        / "database"
        / "migrations"
        / "20260920_01_create_trend_intelligence_core.sql"
    ),
    (
        PROJECT_ROOT
        / "database"
        / "migrations"
        / "20260921_01_create_trend_intelligence_temporal.sql"
    ),
    (
        PROJECT_ROOT
        / "database"
        / "migrations"
        / "20260921_02_create_trend_intelligence_aggregate_signals.sql"
    ),
    (
        PROJECT_ROOT
        / "database"
        / "migrations"
        / "20260921_03_create_trend_intelligence_snapshots.sql"
    ),
)


def _json_dump(value):
    if value is None:
        return None

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
    )


def _json_load(value):
    if not value:
        return None

    try:
        return json.loads(
            value
        )
    except Exception:
        return None


def _optional_text(value):
    value = str(
        value
        or ""
    ).strip()

    return value or None


class SQLiteTrendIntelligenceRepository:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
    ):
        self._window_local = local()
        self.db_path = Path(
            db_path
        )

    @contextmanager
    def window_transaction(self):
        if getattr(self._window_local, "connection", None) is not None:
            yield
            return
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._window_local.connection = conn
            try:
                yield
            finally:
                self._window_local.connection = None

    @contextmanager
    def _connection(self):
        active = getattr(self._window_local, "connection", None)
        if active is not None:
            yield active
            return
        conn = sqlite3.connect(
            str(
                self.db_path
            ),
            timeout=30,
        )

        from datetime import datetime, timezone
        conn.create_function("current_timestamp", 0, lambda: canonical_time(datetime.now(timezone.utc)))
        conn.create_collation("TI_TIME", lambda a, b: (time_key(a) > time_key(b)) - (time_key(a) < time_key(b)))
        conn.create_function("ti_source_identity", 3, _physical_source_identity)
        conn.row_factory = (
            sqlite3.Row
        )

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        conn.execute(
            "PRAGMA busy_timeout = 30000"
        )

        try:
            yield conn
            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def ensure_schema(self):
        for migration_path in MIGRATION_PATHS:
            if not migration_path.exists():
                raise FileNotFoundError(
                    str(
                        migration_path
                    )
                )

        with self._connection() as conn:
            for migration_path in MIGRATION_PATHS:
                conn.executescript(
                    migration_path.read_text(
                        encoding="utf-8"
                    )
                )

    @staticmethod
    def _domain_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendDomain(
            id=int(
                row["id"]
            ),
            code=row["code"],
            name=row["name"],
            description=(
                row["description"]
            ),
            is_active=bool(
                row["is_active"]
            ),
            metadata=_json_load(
                row["metadata_json"]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _source_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendSource(
            id=int(
                row["id"]
            ),
            code=row["code"],
            name=row["name"],
            source_type=(
                row["source_type"]
            ),
            provider=row["provider"],
            base_url=row["base_url"],
            collection_mode=(
                row["collection_mode"]
            ),
            country=row["country"],
            language=row["language"],
            is_active=bool(
                row["is_active"]
            ),
            configuration=_json_load(
                row[
                    "configuration_json"
                ]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _topic_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendTopic(
            id=int(
                row["id"]
            ),
            topic_key=(
                row["topic_key"]
            ),
            name=row["name"],
            description=(
                row["description"]
            ),
            category=(
                row["category"]
            ),
            parent_topic_id=(
                int(
                    row[
                        "parent_topic_id"
                    ]
                )
                if row[
                    "parent_topic_id"
                ] is not None
                else None
            ),
            is_active=bool(
                row["is_active"]
            ),
            metadata=_json_load(
                row["metadata_json"]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _topic_alias_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendTopicAlias(
            id=int(
                row["id"]
            ),
            topic_id=int(
                row["topic_id"]
            ),
            alias_key=(
                row["alias_key"]
            ),
            alias_text=(
                row["alias_text"]
            ),
            language=(
                row["language"]
            ),
            country=(
                row["country"]
            ),
            confidence=float(
                row["confidence"]
            ),
            is_active=bool(
                row["is_active"]
            ),
            metadata=_json_load(
                row["metadata_json"]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _topic_domain_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TopicDomain(
            topic_id=int(
                row["topic_id"]
            ),
            domain_id=int(
                row["domain_id"]
            ),
            relevance=float(
                row["relevance"]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _observation_domain_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return ObservationDomain(
            observation_id=int(
                row["observation_id"]
            ),
            domain_id=int(
                row["domain_id"]
            ),
            confidence=float(
                row["confidence"]
            ),
            detection_method=(
                row["detection_method"]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _observation_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendObservation(
            id=int(
                row["id"]
            ),
            source_id=int(
                row["source_id"]
            ),
            external_id=(
                row["external_id"]
            ),
            observation_type=(
                row[
                    "observation_type"
                ]
            ),
            url=row["url"],
            title=row["title"],
            body_text=(
                row["body_text"]
            ),
            author=row["author"],
            published_at=(
                row["published_at"]
            ),
            observed_at=(
                row["observed_at"]
            ),
            language=row["language"],
            country=row["country"],
            content_hash=(
                row["content_hash"]
            ),
            metadata=_json_load(
                row["metadata_json"]
            ),
            created_at=(
                row["created_at"]
            ),
        )

    @staticmethod
    def _signal_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendSignal(
            id=int(
                row["id"]
            ),
            observation_id=int(
                row["observation_id"]
            ),
            topic_id=int(
                row["topic_id"]
            ),
            signal_type=(
                row["signal_type"]
            ),
            strength=float(
                row["strength"]
            ),
            confidence=float(
                row["confidence"]
            ),
            numeric_value=(
                float(
                    row[
                        "numeric_value"
                    ]
                )
                if row[
                    "numeric_value"
                ] is not None
                else None
            ),
            text_value=(
                row["text_value"]
            ),
            detected_at=(
                row["detected_at"]
            ),
            metadata=_json_load(
                row["metadata_json"]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _trend_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return Trend(
            id=int(
                row["id"]
            ),
            domain_id=int(
                row["domain_id"]
            ),
            topic_id=int(
                row["topic_id"]
            ),
            status=row["status"],
            score=float(
                row["score"]
            ),
            velocity=float(
                row["velocity"]
            ),
            observation_count=int(
                row[
                    "observation_count"
                ]
            ),
            source_count=int(
                row["source_count"]
            ),
            signal_count=int(
                row["signal_count"]
            ),
            window_start=(
                row["window_start"]
            ),
            window_end=(
                row["window_end"]
            ),
            country=row["country"],
            language=(
                row["language"]
            ),
            first_seen_at=(
                row["first_seen_at"]
            ),
            last_seen_at=(
                row["last_seen_at"]
            ),
            metadata=_json_load(
                row["metadata_json"]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _aggregate_signal_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendAggregateSignal(
            id=int(row["id"]),
            domain_id=int(row["domain_id"]),
            topic_id=int(row["topic_id"]),
            signal_type=row["signal_type"],
            window_start=row["window_start"],
            window_end=row["window_end"],
            country=row["country"],
            language=row["language"],
            strength=float(row["strength"]),
            confidence=float(row["confidence"]),
            numeric_value=(
                float(row["numeric_value"])
                if row["numeric_value"] is not None
                else None
            ),
            text_value=row["text_value"],
            detector_key=row["detector_key"],
            detector_version=row["detector_version"],
            reason=row["reason"],
            metadata=_json_load(
                row["metadata_json"]
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _trend_snapshot_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendSnapshot(
            id=int(
                row["id"]
            ),
            domain_id=int(
                row["domain_id"]
            ),
            topic_id=int(
                row["topic_id"]
            ),
            window_start=(
                row["window_start"]
            ),
            window_end=(
                row["window_end"]
            ),
            country=(
                row["country"]
            ),
            language=(
                row["language"]
            ),
            status=(
                row["status"]
            ),
            score=float(
                row["score"]
            ),
            velocity=float(
                row["velocity"]
            ),
            aggregate_signal_count=int(
                row[
                    "aggregate_signal_count"
                ]
            ),
            observation_count=int(
                row[
                    "observation_count"
                ]
            ),
            source_count=int(
                row["source_count"]
            ),
            baseline_observation_mean=float(
                row[
                    "baseline_observation_mean"
                ]
            ),
            metadata=_json_load(
                row["metadata_json"]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _temporal_metric_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendTemporalMetric(
            id=int(
                row["id"]
            ),
            domain_id=int(
                row["domain_id"]
            ),
            topic_id=int(
                row["topic_id"]
            ),
            window_start=(
                row["window_start"]
            ),
            window_end=(
                row["window_end"]
            ),
            country=(
                row["country"]
            ),
            language=(
                row["language"]
            ),
            observation_count=int(
                row["observation_count"]
            ),
            source_count=int(
                row["source_count"]
            ),
            signal_count=int(
                row["signal_count"]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _temporal_baseline_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendTemporalBaseline(
            id=int(
                row["id"]
            ),
            domain_id=int(
                row["domain_id"]
            ),
            topic_id=int(
                row["topic_id"]
            ),
            reference_window_start=(
                row[
                    "reference_window_start"
                ]
            ),
            reference_window_end=(
                row[
                    "reference_window_end"
                ]
            ),
            lookback_windows=int(
                row["lookback_windows"]
            ),
            sample_count=int(
                row["sample_count"]
            ),
            country=(
                row["country"]
            ),
            language=(
                row["language"]
            ),
            observation_mean=float(
                row["observation_mean"]
            ),
            observation_stddev=float(
                row[
                    "observation_stddev"
                ]
            ),
            source_mean=float(
                row["source_mean"]
            ),
            source_stddev=float(
                row["source_stddev"]
            ),
            signal_mean=float(
                row["signal_mean"]
            ),
            signal_stddev=float(
                row["signal_stddev"]
            ),
            created_at=(
                row["created_at"]
            ),
            updated_at=(
                row["updated_at"]
            ),
        )

    @staticmethod
    def _evidence_from_row(
        row,
    ):
        if not row:
            return None
        row = _canonical_row(row)

        return TrendEvidence(
            id=int(
                row["id"]
            ),
            trend_id=int(
                row["trend_id"]
            ),
            signal_id=int(
                row["signal_id"]
            ),
            weight=float(
                row["weight"]
            ),
            reason=row["reason"],
            created_at=(
                row["created_at"]
            ),
        )

    def save_domain(
        self,
        domain: TrendDomain,
    ) -> TrendDomain:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO ti_domains (
                    code,
                    name,
                    description,
                    is_active,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(code)
                DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    is_active = excluded.is_active,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    domain.code,
                    domain.name,
                    domain.description,
                    1
                    if domain.is_active
                    else 0,
                    _json_dump(
                        domain.metadata
                    ),
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_domains
                WHERE code = ?
                """,
                (
                    domain.code,
                ),
            ).fetchone()

            return self._domain_from_row(
                row
            )

    def get_domain_by_code(
        self,
        code: str,
    ) -> TrendDomain | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM ti_domains
                WHERE code = ?
                """,
                (
                    str(
                        code
                    ),
                ),
            ).fetchone()

            return self._domain_from_row(
                row
            )

    def list_domains(
        self,
        *,
        active_only=False,
    ):
        sql = """
            SELECT *
            FROM ti_domains
        """

        if active_only:
            sql += """
                WHERE is_active = 1
            """

        sql += """
            ORDER BY name, id
        """

        with self._connection() as conn:
            return [
                self._domain_from_row(
                    row
                )
                for row
                in conn.execute(
                    sql
                ).fetchall()
            ]

    def save_source(
        self,
        source: TrendSource,
    ):
        source = _canonical_record(source)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO ti_sources (
                    code,
                    name,
                    source_type,
                    provider,
                    base_url,
                    collection_mode,
                    country,
                    language,
                    is_active,
                    configuration_json
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(code)
                DO UPDATE SET
                    name = excluded.name,
                    source_type = excluded.source_type,
                    provider = excluded.provider,
                    base_url = excluded.base_url,
                    collection_mode = excluded.collection_mode,
                    country = excluded.country,
                    language = excluded.language,
                    is_active = excluded.is_active,
                    configuration_json = excluded.configuration_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    source.code,
                    source.name,
                    source.source_type,
                    source.provider,
                    source.base_url,
                    source.collection_mode,
                    source.country,
                    source.language,
                    1
                    if source.is_active
                    else 0,
                    _json_dump(
                        source.configuration
                    ),
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_sources
                WHERE code = ?
                """,
                (
                    source.code,
                ),
            ).fetchone()

            return self._source_from_row(
                row
            )

    def get_source_by_code(
        self,
        code,
    ):
        with self._connection() as conn:
            return self._source_from_row(
                conn.execute(
                    """
                    SELECT *
                    FROM ti_sources
                    WHERE code = ?
                    """,
                    (
                        str(
                            code
                        ),
                    ),
                ).fetchone()
            )

    def save_topic(
        self,
        topic: TrendTopic,
    ):
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO ti_topics (
                    topic_key,
                    name,
                    description,
                    category,
                    parent_topic_id,
                    is_active,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_key)
                DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    category = excluded.category,
                    parent_topic_id = excluded.parent_topic_id,
                    is_active = excluded.is_active,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    topic.topic_key,
                    topic.name,
                    topic.description,
                    topic.category,
                    topic.parent_topic_id,
                    1
                    if topic.is_active
                    else 0,
                    _json_dump(
                        topic.metadata
                    ),
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_topics
                WHERE topic_key = ?
                """,
                (
                    topic.topic_key,
                ),
            ).fetchone()

            return self._topic_from_row(
                row
            )

    def get_topic_by_key(
        self,
        topic_key,
    ):
        with self._connection() as conn:
            return self._topic_from_row(
                conn.execute(
                    """
                    SELECT *
                    FROM ti_topics
                    WHERE topic_key = ?
                    """,
                    (
                        str(
                            topic_key
                        ),
                    ),
                ).fetchone()
            )

    def link_topic_domain(
        self,
        link: TopicDomain,
    ):
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO ti_topic_domains (
                    topic_id,
                    domain_id,
                    relevance
                )
                VALUES (?, ?, ?)
                ON CONFLICT(
                    topic_id,
                    domain_id
                )
                DO UPDATE SET
                    relevance = excluded.relevance,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    link.topic_id,
                    link.domain_id,
                    link.relevance,
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_topic_domains
                WHERE topic_id = ?
                  AND domain_id = ?
                """,
                (
                    link.topic_id,
                    link.domain_id,
                ),
            ).fetchone()

            return (
                self._topic_domain_from_row(
                    row
                )
            )

    def list_topic_domains(
        self,
        topic_id,
    ):
        with self._connection() as conn:
            return [
                self._topic_domain_from_row(
                    row
                )
                for row
                in conn.execute(
                    """
                    SELECT *
                    FROM ti_topic_domains
                    WHERE topic_id = ?
                    ORDER BY domain_id
                    """,
                    (
                        int(
                            topic_id
                        ),
                    ),
                ).fetchall()
            ]

    def list_topics_for_domain(
        self,
        domain_id,
        *,
        active_only=True,
    ):
        sql = """
            SELECT t.*
            FROM ti_topics t

            JOIN ti_topic_domains td
              ON td.topic_id = t.id

            WHERE td.domain_id = ?
        """

        params = [
            int(
                domain_id
            )
        ]

        if active_only:
            sql += """
                AND t.is_active = 1
            """

        sql += """
            ORDER BY
                t.category,
                t.name,
                t.id
        """

        with self._connection() as conn:
            return [
                self._topic_from_row(
                    row
                )
                for row
                in conn.execute(
                    sql,
                    params,
                ).fetchall()
            ]

    def save_topic_alias(
        self,
        alias: TrendTopicAlias,
    ):
        alias = _canonical_record(alias)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO ti_topic_aliases (
                    topic_id,
                    alias_key,
                    alias_text,
                    language,
                    country,
                    confidence,
                    is_active,
                    metadata_json
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(
                    alias_key,
                    language,
                    country
                )
                DO UPDATE SET
                    topic_id = excluded.topic_id,
                    alias_text = excluded.alias_text,
                    confidence = excluded.confidence,
                    is_active = excluded.is_active,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    alias.topic_id,
                    alias.alias_key,
                    alias.alias_text,
                    alias.language,
                    alias.country,
                    alias.confidence,
                    (
                        1
                        if alias.is_active
                        else 0
                    ),
                    _json_dump(
                        alias.metadata
                    ),
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_topic_aliases
                WHERE alias_key = ?
                  AND language = ?
                  AND country = ?
                """,
                (
                    alias.alias_key,
                    alias.language,
                    alias.country,
                ),
            ).fetchone()

            return (
                self._topic_alias_from_row(
                    row
                )
            )

    def resolve_topic_alias(
        self,
        alias_key,
        *,
        language="",
        country="",
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT t.*
                FROM ti_topic_aliases a

                JOIN ti_topics t
                  ON t.id = a.topic_id

                WHERE a.alias_key = ?
                  AND a.is_active = 1
                  AND t.is_active = 1
                  AND (
                        a.language = ?
                        OR a.language = ''
                  )
                  AND (
                        a.country = ?
                        OR a.country = ''
                  )

                ORDER BY
                    CASE
                        WHEN a.language = ?
                        THEN 0
                        ELSE 1
                    END,

                    CASE
                        WHEN a.country = ?
                        THEN 0
                        ELSE 1
                    END,

                    a.confidence DESC,
                    a.id ASC

                LIMIT 1
                """,
                (
                    str(
                        alias_key
                    ),
                    str(
                        language
                        or ""
                    ),
                    str(
                        country
                        or ""
                    ),
                    str(
                        language
                        or ""
                    ),
                    str(
                        country
                        or ""
                    ),
                ),
            ).fetchone()

            return self._topic_from_row(
                row
            )

    def list_topic_aliases(
        self,
        topic_id,
        *,
        active_only=True,
    ):
        sql = """
            SELECT *
            FROM ti_topic_aliases
            WHERE topic_id = ?
        """

        params = [
            int(
                topic_id
            )
        ]

        if active_only:
            sql += """
                AND is_active = 1
            """

        sql += """
            ORDER BY
                language,
                country,
                alias_text,
                id
        """

        with self._connection() as conn:
            return [
                self._topic_alias_from_row(
                    row
                )
                for row
                in conn.execute(
                    sql,
                    params,
                ).fetchall()
            ]

    def link_observation_domain(
        self,
        link: ObservationDomain,
    ):
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO ti_observation_domains (
                    observation_id,
                    domain_id,
                    confidence,
                    detection_method
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(
                    observation_id,
                    domain_id
                )
                DO UPDATE SET
                    confidence = excluded.confidence,
                    detection_method = excluded.detection_method,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    link.observation_id,
                    link.domain_id,
                    link.confidence,
                    link.detection_method,
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_observation_domains
                WHERE observation_id = ?
                  AND domain_id = ?
                """,
                (
                    link.observation_id,
                    link.domain_id,
                ),
            ).fetchone()

            return (
                self._observation_domain_from_row(
                    row
                )
            )

    def list_observation_domains(
        self,
        observation_id,
    ):
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ti_observation_domains
                WHERE observation_id = ?
                ORDER BY domain_id
                """,
                (
                    int(
                        observation_id
                    ),
                ),
            ).fetchall()

            return [
                self._observation_domain_from_row(
                    row
                )
                for row
                in rows
            ]

    def _find_observation(
        self,
        conn,
        observation,
    ):
        external_id = (
            _optional_text(
                observation.external_id
            )
        )

        if external_id:
            row = conn.execute(
                """
                SELECT *
                FROM ti_observations
                WHERE source_id = ?
                  AND external_id = ?
                """,
                (
                    observation.source_id,
                    external_id,
                ),
            ).fetchone()

            if row:
                return row

        content_hash = (
            _optional_text(
                observation.content_hash
            )
        )

        if content_hash:
            return conn.execute(
                """
                SELECT *
                FROM ti_observations
                WHERE source_id = ?
                  AND content_hash = ?
                """,
                (
                    observation.source_id,
                    content_hash,
                ),
            ).fetchone()

        return None

    def get_or_create_observation_with_status(
        self,
        observation,
    ):
        observation = _canonical_record(observation)
        with self._connection() as conn:
            existing = self._find_observation(
                conn,
                observation,
            )

            if existing:
                return (
                    self._observation_from_row(
                        existing
                    ),
                    False,
                )

            try:
                cursor = conn.execute(
                    """
                    INSERT INTO ti_observations (
                        source_id,
                        external_id,
                        observation_type,
                        url,
                        title,
                        body_text,
                        author,
                        published_at,
                        observed_at,
                        language,
                        country,
                        content_hash,
                        metadata_json
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        observation.source_id,
                        _optional_text(
                            observation.external_id
                        ),
                        observation.observation_type,
                        observation.url,
                        observation.title,
                        observation.body_text,
                        observation.author,
                        observation.published_at,
                        observation.observed_at,
                        observation.language,
                        observation.country,
                        _optional_text(
                            observation.content_hash
                        ),
                        _json_dump(
                            observation.metadata
                        ),
                    ),
                )

            except sqlite3.IntegrityError:
                existing = self._find_observation(
                    conn,
                    observation,
                )

                if existing:
                    return (
                        self._observation_from_row(
                            existing
                        ),
                        False,
                    )

                raise

            row = conn.execute(
                """
                SELECT *
                FROM ti_observations
                WHERE id = ?
                """,
                (
                    int(
                        cursor.lastrowid
                    ),
                ),
            ).fetchone()

            return (
                self._observation_from_row(
                    row
                ),
                True,
            )

    def get_observation(
        self,
        observation_id,
    ):
        with self._connection() as conn:
            return self._observation_from_row(
                conn.execute(
                    """
                    SELECT *
                    FROM ti_observations
                    WHERE id = ?
                    """,
                    (
                        int(
                            observation_id
                        ),
                    ),
                ).fetchone()
            )

    def link_observation_topic(
        self,
        link,
    ):
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO ti_observation_topics (
                    observation_id,
                    topic_id,
                    confidence,
                    detection_method
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(
                    observation_id,
                    topic_id
                )
                DO UPDATE SET
                    confidence = excluded.confidence,
                    detection_method = excluded.detection_method,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    link.observation_id,
                    link.topic_id,
                    link.confidence,
                    link.detection_method,
                ),
            )

            return link

    def save_signal_with_status(
        self,
        signal,
    ):
        signal = _canonical_record(signal)
        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT id
                FROM ti_signals
                WHERE observation_id = ?
                  AND topic_id = ?
                  AND signal_type = ?
                """,
                (
                    signal.observation_id,
                    signal.topic_id,
                    signal.signal_type,
                ),
            ).fetchone()

            created = existing is None

            conn.execute(
                """
                INSERT INTO ti_signals (
                    observation_id,
                    topic_id,
                    signal_type,
                    strength,
                    confidence,
                    numeric_value,
                    text_value,
                    detected_at,
                    metadata_json
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(
                    observation_id,
                    topic_id,
                    signal_type
                )
                DO UPDATE SET
                    strength = excluded.strength,
                    confidence = excluded.confidence,
                    numeric_value = excluded.numeric_value,
                    text_value = excluded.text_value,
                    detected_at = excluded.detected_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    signal.observation_id,
                    signal.topic_id,
                    signal.signal_type,
                    signal.strength,
                    signal.confidence,
                    signal.numeric_value,
                    signal.text_value,
                    signal.detected_at,
                    _json_dump(
                        signal.metadata
                    ),
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_signals
                WHERE observation_id = ?
                  AND topic_id = ?
                  AND signal_type = ?
                """,
                (
                    signal.observation_id,
                    signal.topic_id,
                    signal.signal_type,
                ),
            ).fetchone()

            return (
                self._signal_from_row(
                    row
                ),
                created,
            )

    def list_signals_for_topic(
        self,
        domain_id,
        topic_id,
        *,
        window_start,
        window_end,
        country="",
        language="",
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        window_start = canonical_time(window_start) if window_start is not None else None
        window_end = canonical_time(window_end) if window_end is not None else None
        if window_start is not None and window_end is not None: canonical_window(window_start, window_end)
        with self._connection() as conn:
            return [
                self._signal_from_row(
                    row
                )
                for row
                in conn.execute(
                    """
                    SELECT s.*
                    FROM ti_signals s JOIN ti_observations o ON o.id = s.observation_id
                JOIN ti_sources src ON src.id = o.source_id

                    JOIN ti_observation_domains od
                      ON od.observation_id =
                         s.observation_id

                    WHERE od.domain_id = ?
                      AND s.topic_id = ?
                      AND s.detected_at COLLATE TI_TIME >= ?
                      AND s.detected_at COLLATE TI_TIME < ?
                  AND (? = '' OR UPPER(TRIM(o.country)) = ?)
                  AND (? = '' OR LOWER(TRIM(o.language)) = ?)

                    ORDER BY
                        s.detected_at COLLATE TI_TIME,
                        s.signal_type, o.content_hash, s.strength, s.confidence
                    """,
                    (
                        int(
                            domain_id
                        ),
                        int(
                            topic_id
                        ),
                        window_start,
                        window_end,
                        country, country, language, language,
                    ),
                ).fetchall()
            ]

    def get_topic_window_stats(
        self,
        domain_id,
        topic_id,
        *,
        window_start,
        window_end,
        country="",
        language="",
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        window_start = canonical_time(window_start) if window_start is not None else None
        window_end = canonical_time(window_end) if window_end is not None else None
        if window_start is not None and window_end is not None: canonical_window(window_start, window_end)
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(
                        DISTINCT s.id
                    )
                        AS signal_count,

                    COUNT(
                        DISTINCT s.observation_id
                    )
                        AS observation_count,

                    COUNT(
                        DISTINCT ti_source_identity(src.provider, src.base_url, src.code)
                    )
                        AS source_count,

                    MIN(
                        s.detected_at COLLATE TI_TIME
                    )
                        AS first_seen_at,

                    MAX(
                        s.detected_at COLLATE TI_TIME
                    )
                        AS last_seen_at

                FROM ti_signals s

                JOIN ti_observations o
                  ON o.id = s.observation_id
                JOIN ti_sources src ON src.id = o.source_id

                JOIN ti_observation_domains od
                  ON od.observation_id =
                     s.observation_id

                WHERE od.domain_id = ?
                  AND s.topic_id = ?
                  AND s.detected_at COLLATE TI_TIME >= ?
                  AND s.detected_at COLLATE TI_TIME < ?
                  AND (? = '' OR UPPER(TRIM(o.country)) = ?)
                  AND (? = '' OR LOWER(TRIM(o.language)) = ?)
                """,
                (
                    int(
                        domain_id
                    ),
                    int(
                        topic_id
                    ),
                    window_start,
                    window_end,
                    country, country, language, language,
                ),
            ).fetchone()

            return {
                "signal_count":
                    int(
                        row[
                            "signal_count"
                        ]
                        or 0
                    ),
                "observation_count":
                    int(
                        row[
                            "observation_count"
                        ]
                        or 0
                    ),
                "source_count":
                    int(
                        row[
                            "source_count"
                        ]
                        or 0
                    ),
                "first_seen_at":
                    row[
                        "first_seen_at"
                    ],
                "last_seen_at":
                    row[
                        "last_seen_at"
                    ],
            }

    def get_temporal_window_stats(
        self,
        domain_id,
        topic_id,
        *,
        window_start,
        window_end,
        country="",
        language="",
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        window_start = canonical_time(window_start) if window_start is not None else None
        window_end = canonical_time(window_end) if window_end is not None else None
        if window_start is not None and window_end is not None: canonical_window(window_start, window_end)
        with self._connection() as conn:
            observation_sql = """
                SELECT
                    COUNT(
                        DISTINCT o.id
                    ) AS observation_count,

                    COUNT(
                        DISTINCT ti_source_identity(src.provider, src.base_url, src.code)
                    ) AS source_count

                FROM ti_observations o JOIN ti_sources src ON src.id = o.source_id

                JOIN ti_observation_domains od
                  ON od.observation_id = o.id

                JOIN ti_observation_topics ot
                  ON ot.observation_id = o.id

                WHERE od.domain_id = ?
                  AND ot.topic_id = ?
                  AND o.observed_at COLLATE TI_TIME >= ?
                  AND o.observed_at COLLATE TI_TIME < ?
            """

            observation_params = [
                int(
                    domain_id
                ),
                int(
                    topic_id
                ),
                window_start,
                window_end,
            ]

            if country:
                observation_sql += """
                    AND UPPER(TRIM(o.country)) = ?
                """

                observation_params.append(
                    country
                )

            if language:
                observation_sql += """
                    AND LOWER(TRIM(o.language)) = ?
                """

                observation_params.append(
                    language
                )

            observation_row = (
                conn.execute(
                    observation_sql,
                    observation_params,
                ).fetchone()
            )

            signal_sql = """
                SELECT
                    COUNT(
                        DISTINCT s.id
                    ) AS signal_count

                FROM ti_signals s

                JOIN ti_observations o
                  ON o.id = s.observation_id
                JOIN ti_sources src ON src.id = o.source_id

                JOIN ti_observation_domains od
                  ON od.observation_id =
                     s.observation_id

                WHERE od.domain_id = ?
                  AND s.topic_id = ?
                  AND s.detected_at COLLATE TI_TIME >= ?
                  AND s.detected_at COLLATE TI_TIME < ?
            """

            signal_params = [
                int(
                    domain_id
                ),
                int(
                    topic_id
                ),
                window_start,
                window_end,
            ]

            if country:
                signal_sql += """
                    AND UPPER(TRIM(o.country)) = ?
                """

                signal_params.append(
                    country
                )

            if language:
                signal_sql += """
                    AND LOWER(TRIM(o.language)) = ?
                """

                signal_params.append(
                    language
                )

            signal_row = conn.execute(
                signal_sql,
                signal_params,
            ).fetchone()

            return {
                "observation_count":
                    int(
                        observation_row[
                            "observation_count"
                        ]
                        or 0
                    ),
                "source_count":
                    int(
                        observation_row[
                            "source_count"
                        ]
                        or 0
                    ),
                "signal_count":
                    int(
                        signal_row[
                            "signal_count"
                        ]
                        or 0
                    ),
            }

    def get_temporal_metric(
        self,
        domain_id,
        topic_id,
        *,
        window_start,
        window_end,
        country="",
        language="",
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        window_start = canonical_time(window_start) if window_start is not None else None
        window_end = canonical_time(window_end) if window_end is not None else None
        if window_start is not None and window_end is not None: canonical_window(window_start, window_end)
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM ti_temporal_metrics
                WHERE domain_id = ?
                  AND topic_id = ?
                  AND country = ?
                  AND language = ?
                  AND window_start COLLATE TI_TIME = ?
                  AND window_end COLLATE TI_TIME = ?
                LIMIT 1
                """,
                (
                    int(domain_id),
                    int(topic_id),
                    country,
                    language,
                    window_start,
                    window_end,
                ),
            ).fetchone()

            return (
                self._temporal_metric_from_row(
                    row
                )
            )

    def list_temporal_metrics(
        self,
        domain_id,
        topic_id,
        *,
        country="",
        language="",
        limit=None,
        ascending=True,
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        order = (
            "ASC"
            if ascending
            else "DESC"
        )

        sql = f"""
            SELECT *
            FROM ti_temporal_metrics
            WHERE domain_id = ?
              AND topic_id = ?
              AND country = ?
              AND language = ?
            ORDER BY
                window_start COLLATE TI_TIME {order},
                window_end COLLATE TI_TIME {order}
        """

        params = [
            int(domain_id),
            int(topic_id),
            country,
            language,
        ]

        if limit is not None:
            sql += """
                LIMIT ?
            """

            params.append(
                max(
                    1,
                    int(limit),
                )
            )

        with self._connection() as conn:
            rows = conn.execute(
                sql,
                params,
            ).fetchall()

            return [
                self._temporal_metric_from_row(
                    row
                )
                for row
                in rows
            ]

    def save_temporal_metric(
        self,
        metric: TrendTemporalMetric,
    ):
        metric = _canonical_record(metric)
        with self._connection() as conn:
            _canonicalize_legacy_identity(conn, "ti_temporal_metrics", metric)
            conn.execute(
                """
                INSERT INTO ti_temporal_metrics (
                    domain_id,
                    topic_id,
                    window_start,
                    window_end,
                    country,
                    language,
                    observation_count,
                    source_count,
                    signal_count
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(
                    domain_id,
                    topic_id,
                    country,
                    language,
                    window_start,
                    window_end
                )
                DO UPDATE SET
                    observation_count =
                        excluded.observation_count,
                    source_count =
                        excluded.source_count,
                    signal_count =
                        excluded.signal_count,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE ti_temporal_metrics.observation_count IS NOT excluded.observation_count OR ti_temporal_metrics.source_count IS NOT excluded.source_count OR ti_temporal_metrics.signal_count IS NOT excluded.signal_count
                """,
                (
                    metric.domain_id,
                    metric.topic_id,
                    metric.window_start,
                    metric.window_end,
                    metric.country,
                    metric.language,
                    metric.observation_count,
                    metric.source_count,
                    metric.signal_count,
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_temporal_metrics
                WHERE domain_id = ?
                  AND topic_id = ?
                  AND country = ?
                  AND language = ?
                  AND window_start COLLATE TI_TIME = ?
                  AND window_end COLLATE TI_TIME = ?
                """,
                (
                    metric.domain_id,
                    metric.topic_id,
                    metric.country,
                    metric.language,
                    metric.window_start,
                    metric.window_end,
                ),
            ).fetchone()

            return (
                self._temporal_metric_from_row(
                    row
                )
            )

    def list_temporal_metrics_before(
        self,
        domain_id,
        topic_id,
        *,
        before_window_start,
        country="",
        language="",
        limit=7,
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        before_window_start = canonical_time(before_window_start) if before_window_start is not None else None
        safe_limit = max(
            1,
            min(
                3650,
                int(
                    limit
                    or 7
                ),
            ),
        )

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ti_temporal_metrics
                WHERE domain_id = ?
                  AND topic_id = ?
                  AND country = ?
                  AND language = ?
                  AND window_end COLLATE TI_TIME <= ?
                ORDER BY
                    window_end COLLATE TI_TIME DESC,
                    window_start COLLATE TI_TIME DESC
                LIMIT ?
                """,
                (
                    int(
                        domain_id
                    ),
                    int(
                        topic_id
                    ),
                    country,
                    language,
                    before_window_start,
                    safe_limit,
                ),
            ).fetchall()

            return [
                self._temporal_metric_from_row(
                    row
                )
                for row
                in rows
            ]

    def save_temporal_baseline(
        self,
        baseline: TrendTemporalBaseline,
    ):
        baseline = _canonical_record(baseline)
        with self._connection() as conn:
            _canonicalize_legacy_identity(conn, "ti_temporal_baselines", baseline)
            conn.execute(
                """
                INSERT INTO ti_temporal_baselines (
                    domain_id,
                    topic_id,
                    reference_window_start,
                    reference_window_end,
                    lookback_windows,
                    sample_count,
                    country,
                    language,
                    observation_mean,
                    observation_stddev,
                    source_mean,
                    source_stddev,
                    signal_mean,
                    signal_stddev
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(
                    domain_id,
                    topic_id,
                    country,
                    language,
                    reference_window_start,
                    reference_window_end,
                    lookback_windows
                )
                DO UPDATE SET
                    sample_count =
                        excluded.sample_count,
                    observation_mean =
                        excluded.observation_mean,
                    observation_stddev =
                        excluded.observation_stddev,
                    source_mean =
                        excluded.source_mean,
                    source_stddev =
                        excluded.source_stddev,
                    signal_mean =
                        excluded.signal_mean,
                    signal_stddev =
                        excluded.signal_stddev,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE ti_temporal_baselines.sample_count IS NOT excluded.sample_count OR ti_temporal_baselines.observation_mean IS NOT excluded.observation_mean OR ti_temporal_baselines.observation_stddev IS NOT excluded.observation_stddev OR ti_temporal_baselines.source_mean IS NOT excluded.source_mean OR ti_temporal_baselines.source_stddev IS NOT excluded.source_stddev OR ti_temporal_baselines.signal_mean IS NOT excluded.signal_mean OR ti_temporal_baselines.signal_stddev IS NOT excluded.signal_stddev
                """,
                (
                    baseline.domain_id,
                    baseline.topic_id,
                    baseline.reference_window_start,
                    baseline.reference_window_end,
                    baseline.lookback_windows,
                    baseline.sample_count,
                    baseline.country,
                    baseline.language,
                    baseline.observation_mean,
                    baseline.observation_stddev,
                    baseline.source_mean,
                    baseline.source_stddev,
                    baseline.signal_mean,
                    baseline.signal_stddev,
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_temporal_baselines
                WHERE domain_id = ?
                  AND topic_id = ?
                  AND country = ?
                  AND language = ?
                  AND reference_window_start COLLATE TI_TIME = ?
                  AND reference_window_end COLLATE TI_TIME = ?
                  AND lookback_windows = ?
                """,
                (
                    baseline.domain_id,
                    baseline.topic_id,
                    baseline.country,
                    baseline.language,
                    baseline.reference_window_start,
                    baseline.reference_window_end,
                    baseline.lookback_windows,
                ),
            ).fetchone()

            return (
                self._temporal_baseline_from_row(
                    row
                )
            )

    def get_temporal_baseline(
        self,
        domain_id,
        topic_id,
        *,
        reference_window_start,
        reference_window_end,
        country="",
        language="",
        lookback_windows=None,
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        reference_window_start = canonical_time(reference_window_start) if reference_window_start is not None else None
        reference_window_end = canonical_time(reference_window_end) if reference_window_end is not None else None
        sql = """
            SELECT *
            FROM ti_temporal_baselines
            WHERE domain_id = ?
              AND topic_id = ?
              AND country = ?
              AND language = ?
              AND reference_window_start COLLATE TI_TIME = ?
              AND reference_window_end COLLATE TI_TIME = ?
        """

        params = [
            int(domain_id),
            int(topic_id),
            country,
            language,
            reference_window_start,
            reference_window_end,
        ]

        if lookback_windows is not None:
            sql += """
                AND lookback_windows = ?
            """

            params.append(
                int(lookback_windows)
            )

        # Without an explicit lookback, choose the longest available baseline
        # deterministically; publication supplies its selected lookback explicitly.
        sql += """
            ORDER BY
                lookback_windows DESC
            LIMIT 1
        """

        with self._connection() as conn:
            row = conn.execute(
                sql,
                params,
            ).fetchone()

            return (
                self._temporal_baseline_from_row(
                    row
                )
            )

    def get_latest_temporal_baseline(
        self,
        domain_id,
        topic_id,
        *,
        country="",
        language="",
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM ti_temporal_baselines
                WHERE domain_id = ?
                  AND topic_id = ?
                  AND country = ?
                  AND language = ?
                ORDER BY
                    reference_window_end COLLATE TI_TIME DESC,
                    reference_window_start COLLATE TI_TIME DESC,
                    lookback_windows DESC
                LIMIT 1
                """,
                (
                    int(
                        domain_id
                    ),
                    int(
                        topic_id
                    ),
                    country,
                    language,
                ),
            ).fetchone()

            return (
                self._temporal_baseline_from_row(
                    row
                )
            )

    def save_aggregate_signal(
        self,
        signal: TrendAggregateSignal,
    ):
        signal = _canonical_record(signal)
        with self._connection() as conn:
            _canonicalize_legacy_identity(conn, "ti_aggregate_signals", signal)
            conn.execute(
                """
                INSERT INTO ti_aggregate_signals (
                    domain_id,
                    topic_id,
                    signal_type,
                    window_start,
                    window_end,
                    country,
                    language,
                    strength,
                    confidence,
                    numeric_value,
                    text_value,
                    detector_key,
                    detector_version,
                    reason,
                    metadata_json
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(
                    domain_id,
                    topic_id,
                    signal_type,
                    country,
                    language,
                    window_start,
                    window_end,
                    detector_key,
                    detector_version
                )
                DO UPDATE SET
                    strength = excluded.strength,
                    confidence = excluded.confidence,
                    numeric_value = excluded.numeric_value,
                    text_value = excluded.text_value,
                    reason = excluded.reason,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                WHERE ti_aggregate_signals.strength IS NOT excluded.strength OR ti_aggregate_signals.confidence IS NOT excluded.confidence OR ti_aggregate_signals.numeric_value IS NOT excluded.numeric_value OR ti_aggregate_signals.text_value IS NOT excluded.text_value OR ti_aggregate_signals.reason IS NOT excluded.reason OR ti_aggregate_signals.metadata_json IS NOT excluded.metadata_json
                """,
                (
                    signal.domain_id,
                    signal.topic_id,
                    signal.signal_type,
                    signal.window_start,
                    signal.window_end,
                    signal.country,
                    signal.language,
                    signal.strength,
                    signal.confidence,
                    signal.numeric_value,
                    signal.text_value,
                    signal.detector_key,
                    signal.detector_version,
                    signal.reason,
                    _json_dump(signal.metadata),
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_aggregate_signals
                WHERE domain_id = ?
                  AND topic_id = ?
                  AND signal_type = ?
                  AND country = ?
                  AND language = ?
                  AND window_start COLLATE TI_TIME = ?
                  AND window_end COLLATE TI_TIME = ?
                  AND detector_key = ?
                  AND detector_version = ?
                """,
                (
                    signal.domain_id,
                    signal.topic_id,
                    signal.signal_type,
                    signal.country,
                    signal.language,
                    signal.window_start,
                    signal.window_end,
                    signal.detector_key,
                    signal.detector_version,
                ),
            ).fetchone()

            return self._aggregate_signal_from_row(
                row
            )

    def list_aggregate_signals(
        self,
        domain_id,
        topic_id,
        *,
        window_start=None,
        window_end=None,
        country="",
        language="",
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        window_start = canonical_time(window_start) if window_start is not None else None
        window_end = canonical_time(window_end) if window_end is not None else None
        if window_start is not None and window_end is not None: canonical_window(window_start, window_end)
        sql = """
            SELECT *
            FROM ti_aggregate_signals
            WHERE domain_id = ?
              AND topic_id = ?
              AND country = ?
              AND language = ?
        """

        params = [
            int(domain_id),
            int(topic_id),
            country,
            language,
        ]

        if window_start is not None:
            sql += """
                AND window_start COLLATE TI_TIME >= ?
            """
            params.append(window_start)

        if window_end is not None:
            sql += """
                AND window_end COLLATE TI_TIME <= ?
            """
            params.append(window_end)

        sql += """
            ORDER BY
                window_end COLLATE TI_TIME,
                window_start COLLATE TI_TIME,
                signal_type, detector_key, detector_version
        """

        with self._connection() as conn:
            return [
                self._aggregate_signal_from_row(
                    row
                )
                for row
                in conn.execute(
                    sql,
                    params,
                ).fetchall()
            ]

    def delete_aggregate_signals_for_detector(
        self,
        domain_id,
        topic_id,
        *,
        window_start,
        window_end,
        country,
        language,
        detector_key,
        detector_version,
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        window_start = canonical_time(window_start) if window_start is not None else None
        window_end = canonical_time(window_end) if window_end is not None else None
        if window_start is not None and window_end is not None: canonical_window(window_start, window_end)
        with self._connection() as conn:
            conn.execute(
                """
                DELETE FROM ti_aggregate_signals
                WHERE domain_id = ?
                  AND topic_id = ?
                  AND country = ?
                  AND language = ?
                  AND window_start COLLATE TI_TIME = ?
                  AND window_end COLLATE TI_TIME = ?
                  AND detector_key = ?
                  AND detector_version = ?
                """,
                (
                    int(domain_id),
                    int(topic_id),
                    country,
                    language,
                    window_start,
                    window_end,
                    detector_key,
                    detector_version,
                ),
            )

    def reconcile_aggregate_signals(self, metric, active_versions, persisted):
        """Retain historical versions; remove only stale active natural identities."""
        keep = {item.id for item in persisted}
        with self._connection() as conn:
            existing = self.list_aggregate_signals(
                metric.domain_id, metric.topic_id,
                window_start=metric.window_start, window_end=metric.window_end,
                country=metric.country, language=metric.language,
            )
            for item in existing:
                if (item.window_start == metric.window_start
                        and item.window_end == metric.window_end
                        and active_versions.get(item.detector_key) == item.detector_version
                        and item.id not in keep):
                    conn.execute("DELETE FROM ti_aggregate_signals WHERE id = ?", (item.id,))

    def save_trend_snapshot(
        self,
        snapshot: TrendSnapshot,
    ):
        snapshot = _canonical_record(snapshot)
        with self._connection() as conn:
            _canonicalize_legacy_identity(conn, "ti_trend_snapshots", snapshot)
            conn.execute(
                """
                INSERT INTO ti_trend_snapshots (
                    domain_id,
                    topic_id,
                    window_start,
                    window_end,
                    country,
                    language,
                    status,
                    score,
                    velocity,
                    aggregate_signal_count,
                    observation_count,
                    source_count,
                    baseline_observation_mean,
                    metadata_json
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(
                    domain_id,
                    topic_id,
                    country,
                    language,
                    window_start,
                    window_end
                )
                DO UPDATE SET
                    status =
                        excluded.status,
                    score =
                        excluded.score,
                    velocity =
                        excluded.velocity,
                    aggregate_signal_count =
                        excluded.aggregate_signal_count,
                    observation_count =
                        excluded.observation_count,
                    source_count =
                        excluded.source_count,
                    baseline_observation_mean =
                        excluded.baseline_observation_mean,
                    metadata_json =
                        excluded.metadata_json,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE ti_trend_snapshots.status IS NOT excluded.status OR ti_trend_snapshots.score IS NOT excluded.score OR ti_trend_snapshots.velocity IS NOT excluded.velocity OR ti_trend_snapshots.aggregate_signal_count IS NOT excluded.aggregate_signal_count OR ti_trend_snapshots.observation_count IS NOT excluded.observation_count OR ti_trend_snapshots.source_count IS NOT excluded.source_count OR ti_trend_snapshots.baseline_observation_mean IS NOT excluded.baseline_observation_mean OR ti_trend_snapshots.metadata_json IS NOT excluded.metadata_json
                """,
                (
                    snapshot.domain_id,
                    snapshot.topic_id,
                    snapshot.window_start,
                    snapshot.window_end,
                    snapshot.country,
                    snapshot.language,
                    snapshot.status,
                    snapshot.score,
                    snapshot.velocity,
                    snapshot.aggregate_signal_count,
                    snapshot.observation_count,
                    snapshot.source_count,
                    snapshot.baseline_observation_mean,
                    _json_dump(
                        snapshot.metadata
                    ),
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_trend_snapshots
                WHERE domain_id = ?
                  AND topic_id = ?
                  AND country = ?
                  AND language = ?
                  AND window_start COLLATE TI_TIME = ?
                  AND window_end COLLATE TI_TIME = ?
                """,
                (
                    snapshot.domain_id,
                    snapshot.topic_id,
                    snapshot.country,
                    snapshot.language,
                    snapshot.window_start,
                    snapshot.window_end,
                ),
            ).fetchone()

            return (
                self._trend_snapshot_from_row(
                    row
                )
            )

    def list_trend_snapshots(
        self,
        domain_id,
        topic_id,
        *,
        country="",
        language="",
        limit=None,
        ascending=True,
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        order = (
            "ASC"
            if ascending
            else "DESC"
        )

        sql = f"""
            SELECT *
            FROM ti_trend_snapshots
            WHERE domain_id = ?
              AND topic_id = ?
              AND country = ?
              AND language = ?
            ORDER BY
                window_start COLLATE TI_TIME {order},
                window_end COLLATE TI_TIME {order}
        """

        params = [
            int(domain_id),
            int(topic_id),
            country,
            language,
        ]

        if limit is not None:
            sql += """
                LIMIT ?
            """

            params.append(
                max(
                    1,
                    int(limit),
                )
            )

        with self._connection() as conn:
            rows = conn.execute(
                sql,
                params,
            ).fetchall()

            return [
                self._trend_snapshot_from_row(
                    row
                )
                for row
                in rows
            ]

    def get_latest_trend_snapshot_before(
        self,
        domain_id,
        topic_id,
        *,
        before_window_start,
        country="",
        language="",
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        before_window_start = canonical_time(before_window_start) if before_window_start is not None else None
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM ti_trend_snapshots
                WHERE domain_id = ?
                  AND topic_id = ?
                  AND country = ?
                  AND language = ?
                  AND window_end COLLATE TI_TIME <= ?
                ORDER BY
                    window_end COLLATE TI_TIME DESC,
                    window_start COLLATE TI_TIME DESC
                LIMIT 1
                """,
                (
                    int(domain_id),
                    int(topic_id),
                    country,
                    language,
                    before_window_start,
                ),
            ).fetchone()

            return (
                self._trend_snapshot_from_row(
                    row
                )
            )

    def list_domain_trend_snapshots(
        self,
        domain_id,
        *,
        status=None,
        country=None,
        language=None,
        limit=100,
    ):
        status = str(status).strip() if status else ""
        country = canonical_country(country) if country else ""
        language = canonical_language(language) if language else ""

        safe_limit = max(
            1,
            min(
                5000,
                int(
                    limit
                    or 100
                ),
            ),
        )

        params = [
            int(domain_id)
        ]

        sql = """
            WITH filtered AS (
                SELECT *
                FROM ti_trend_snapshots
                WHERE domain_id = ?
        """

        if status:
            sql += """
                AND status = ?
            """
            params.append(status)

        if country:
            sql += """
                AND country = ?
            """
            params.append(country)

        if language:
            sql += """
                AND language = ?
            """
            params.append(language)

        sql += """
            ),
            ranked AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            topic_id,
                            country,
                            language
                        ORDER BY
                            window_end COLLATE TI_TIME DESC,
                            window_start COLLATE TI_TIME DESC
                    ) AS rn
                FROM filtered
            )
            SELECT *
            FROM ranked
            WHERE rn = 1
            ORDER BY
                score DESC,
                window_end COLLATE TI_TIME DESC,
                id DESC
            LIMIT ?
        """

        params.append(safe_limit)

        with self._connection() as conn:
            return [
                self._trend_snapshot_from_row(
                    row
                )
                for row
                in conn.execute(
                    sql,
                    params,
                ).fetchall()
            ]

    def get_latest_trend_before(
        self,
        domain_id,
        topic_id,
        *,
        country,
        language,
        before_window_start,
    ):
        country = canonical_country(country)
        language = canonical_language(language)
        before_window_start = canonical_time(before_window_start) if before_window_start is not None else None
        with self._connection() as conn:
            return self._trend_from_row(
                conn.execute(
                    """
                    SELECT *
                    FROM ti_trends
                    WHERE domain_id = ?
                      AND topic_id = ?
                      AND country = ?
                      AND language = ?
                      AND window_end COLLATE TI_TIME <= ?
                    ORDER BY
                        window_end COLLATE TI_TIME DESC,
                        window_start COLLATE TI_TIME DESC
                    LIMIT 1
                    """,
                    (
                        int(
                            domain_id
                        ),
                        int(
                            topic_id
                        ),
                        country,
                        language,
                        before_window_start,
                    ),
                ).fetchone()
            )

    def save_trend_with_evidence(
        self,
        trend,
        evidence,
    ):
        trend = _canonical_record(trend)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO ti_trends (
                    domain_id,
                    topic_id,
                    status,
                    score,
                    velocity,
                    observation_count,
                    source_count,
                    signal_count,
                    window_start,
                    window_end,
                    country,
                    language,
                    first_seen_at,
                    last_seen_at,
                    metadata_json
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(
                    domain_id,
                    topic_id,
                    country,
                    language,
                    window_start,
                    window_end
                )
                DO UPDATE SET
                    status = excluded.status,
                    score = excluded.score,
                    velocity = excluded.velocity,
                    observation_count = excluded.observation_count,
                    source_count = excluded.source_count,
                    signal_count = excluded.signal_count,
                    first_seen_at = excluded.first_seen_at,
                    last_seen_at = excluded.last_seen_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    trend.domain_id,
                    trend.topic_id,
                    trend.status,
                    trend.score,
                    trend.velocity,
                    trend.observation_count,
                    trend.source_count,
                    trend.signal_count,
                    trend.window_start,
                    trend.window_end,
                    trend.country,
                    trend.language,
                    trend.first_seen_at,
                    trend.last_seen_at,
                    _json_dump(
                        trend.metadata
                    ),
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM ti_trends
                WHERE domain_id = ?
                  AND topic_id = ?
                  AND country = ?
                  AND language = ?
                  AND window_start COLLATE TI_TIME = ?
                  AND window_end COLLATE TI_TIME = ?
                """,
                (
                    trend.domain_id,
                    trend.topic_id,
                    trend.country,
                    trend.language,
                    trend.window_start,
                    trend.window_end,
                ),
            ).fetchone()

            stored = self._trend_from_row(
                row
            )

            conn.execute(
                """
                DELETE FROM ti_trend_evidence
                WHERE trend_id = ?
                """,
                (
                    stored.id,
                ),
            )

            for item in evidence:
                conn.execute(
                    """
                    INSERT INTO ti_trend_evidence (
                        trend_id,
                        signal_id,
                        weight,
                        reason
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        stored.id,
                        item.signal_id,
                        item.weight,
                        item.reason,
                    ),
                )

            return stored

    def get_trend(
        self,
        trend_id,
    ):
        with self._connection() as conn:
            return self._trend_from_row(
                conn.execute(
                    """
                    SELECT *
                    FROM ti_trends
                    WHERE id = ?
                    """,
                    (
                        int(
                            trend_id
                        ),
                    ),
                ).fetchone()
            )

    def list_trends(
        self,
        *,
        domain_id,
        status=None,
        limit=100,
    ):
        sql = """
            SELECT *
            FROM ti_trends
            WHERE domain_id = ?
        """

        params = [
            int(
                domain_id
            )
        ]

        if status:
            sql += """
                AND status = ?
            """

            params.append(
                str(
                    status
                )
            )

        sql += """
            ORDER BY
                score DESC,
                velocity DESC,
                window_end COLLATE TI_TIME DESC,
                id DESC
            LIMIT ?
        """

        params.append(
            max(
                1,
                min(
                    5000,
                    int(
                        limit
                        or 100
                    ),
                ),
            )
        )

        with self._connection() as conn:
            return [
                self._trend_from_row(
                    row
                )
                for row
                in conn.execute(
                    sql,
                    params,
                ).fetchall()
            ]

    def list_trend_evidence(
        self,
        trend_id,
    ):
        with self._connection() as conn:
            return [
                self._evidence_from_row(
                    row
                )
                for row
                in conn.execute(
                    """
                    SELECT *
                    FROM ti_trend_evidence
                    WHERE trend_id = ?
                    ORDER BY weight DESC, id
                    """,
                    (
                        int(
                            trend_id
                        ),
                    ),
                ).fetchall()
            ]


def _canonical_record(record):
    changes = {}
    names = {field.name for field in fields(record)}
    for name in names:
        value = getattr(record, name)
        if name in {"observed_at", "published_at", "detected_at", "window_start", "window_end", "reference_window_start", "reference_window_end", "first_seen_at", "last_seen_at"} and value is not None:
            changes[name] = canonical_time(value)
        elif name == "country":
            changes[name] = canonical_country(value)
        elif name == "language":
            changes[name] = canonical_language(value)
        elif name in {"strength", "confidence", "numeric_value", "score", "velocity"} and value is not None:
            changes[name] = finite_number(value)
        elif isinstance(value, float):
            finite_number(value)
    for start, end in [("window_start", "window_end"), ("reference_window_start", "reference_window_end")]:
        if start in names and end in names:
            canonical_window(getattr(record, start), getattr(record, end))
    return replace(record, **changes)


def _physical_source_identity(provider, url, code):
    from urllib.parse import urlsplit, urlunsplit
    provider = " ".join(str(provider or "").split()).casefold()
    try:
        parsed = urlsplit(str(url or "").strip())
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname and not parsed.username:
            host = parsed.hostname.lower().encode("idna").decode("ascii")
            port = parsed.port
            if port and (parsed.scheme.lower(), port) not in {("http", 80), ("https", 443)}:
                host += f":{port}"
            normalized = urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip("/"), parsed.query, ""))
            return json.dumps([provider, normalized])
    except ValueError:
        pass
    return json.dumps(["source", str(code).strip().upper()])


def _canonical_row(row):
    row = dict(row)
    for key, value in row.items():
        if value is not None and key in {"observed_at", "published_at", "detected_at", "window_start", "window_end", "reference_window_start", "reference_window_end", "first_seen_at", "last_seen_at", "created_at", "updated_at"}:
            row[key] = canonical_time(value)
        elif key == "country":
            row[key] = canonical_country(value)
        elif key == "language":
            row[key] = canonical_language(value)
    return row


def _canonicalize_legacy_identity(conn, table, record):
    # Only fixed internal table/column names enter this SQL. Legacy equivalent
    # identities retain their row ID. Ambiguous legacy duplicates fail closed.
    start, end = ("reference_window_start", "reference_window_end") if table == "ti_temporal_baselines" else ("window_start", "window_end")
    keys = ["domain_id", "topic_id", "country", "language", start, end]
    if table == "ti_temporal_baselines":
        keys.append("lookback_windows")
    if table == "ti_aggregate_signals":
        keys.extend(["signal_type", "detector_key", "detector_version"])
    expressions = {start: start + " COLLATE TI_TIME", end: end + " COLLATE TI_TIME",
        "country": "UPPER(TRIM(country))", "language": "LOWER(TRIM(language))"}
    where = " AND ".join(expressions.get(k, k) + " = ?" for k in keys)
    values = [getattr(record, k) for k in keys]
    rows = conn.execute(f"SELECT * FROM {table} WHERE {where}", values).fetchall()
    if len(rows) > 1:
        raise ValueError("Ambiguous legacy TI identity; repair duplicate rows before replay")
    if rows and any(rows[0][k] != getattr(record, k) for k in keys):
        assignments = ", ".join(k + " = ?" for k in keys)
        conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", [*values, rows[0]["id"]])
