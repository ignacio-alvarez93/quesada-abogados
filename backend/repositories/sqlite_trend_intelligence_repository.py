"""
SQLite repository para Trend Intelligence.

Toda dependencia SQLite queda encapsulada aquí.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.trend_intelligence.models import (
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
)


PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)

DEFAULT_DB_PATH = (
    PROJECT_ROOT
    / "database"
    / "quesada.db"
)

MIGRATION_PATH = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "20260920_01_create_trend_intelligence_core.sql"
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
        self.db_path = Path(
            db_path
        )

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(
            str(
                self.db_path
            ),
            timeout=30,
        )

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
        if not MIGRATION_PATH.exists():
            raise FileNotFoundError(
                str(
                    MIGRATION_PATH
                )
            )

        with self._connection() as conn:
            conn.executescript(
                MIGRATION_PATH.read_text(
                    encoding="utf-8"
                )
            )

    @staticmethod
    def _domain_from_row(
        row,
    ):
        if not row:
            return None

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
    def _evidence_from_row(
        row,
    ):
        if not row:
            return None

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
    ):
        with self._connection() as conn:
            return [
                self._signal_from_row(
                    row
                )
                for row
                in conn.execute(
                    """
                    SELECT s.*
                    FROM ti_signals s

                    JOIN ti_observation_domains od
                      ON od.observation_id =
                         s.observation_id

                    WHERE od.domain_id = ?
                      AND s.topic_id = ?
                      AND s.detected_at >= ?
                      AND s.detected_at <= ?

                    ORDER BY
                        s.detected_at,
                        s.id
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
    ):
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
                        DISTINCT o.source_id
                    )
                        AS source_count,

                    MIN(
                        s.detected_at
                    )
                        AS first_seen_at,

                    MAX(
                        s.detected_at
                    )
                        AS last_seen_at

                FROM ti_signals s

                JOIN ti_observations o
                  ON o.id = s.observation_id

                JOIN ti_observation_domains od
                  ON od.observation_id =
                     s.observation_id

                WHERE od.domain_id = ?
                  AND s.topic_id = ?
                  AND s.detected_at >= ?
                  AND s.detected_at <= ?
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

    def get_latest_trend_before(
        self,
        domain_id,
        topic_id,
        *,
        country,
        language,
        before_window_start,
    ):
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
                      AND window_start < ?
                    ORDER BY
                        window_end DESC,
                        id DESC
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
                  AND window_start = ?
                  AND window_end = ?
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
                window_end DESC,
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
