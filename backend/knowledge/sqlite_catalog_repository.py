"""Persistencia SQLite del catálogo gobernado Knowledge."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from .catalog import (
    KnowledgeCatalogEntry,
    KnowledgeCatalogTier,
    build_knowledge_catalog_entry,
)
from .catalog_repository import (
    KnowledgeCatalogWriteResult,
    KnowledgeCatalogWriteStatus,
)
from .source_registry import (
    normalize_source_key,
)


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260915_create_knowledge_catalog.sql"
)


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


class SQLiteKnowledgeCatalogRepository:
    """Adaptador SQLite independiente del contenido Knowledge."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        self._db_path = Path(
            db_path
        )

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(
        self,
    ) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path
        )

        connection.row_factory = (
            sqlite3.Row
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    @contextmanager
    def _managed_connection(self):
        connection = self._connect()

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize_schema(
        self,
    ) -> None:
        if not _MIGRATION_PATH.exists():
            raise FileNotFoundError(
                "No existe migración de catálogo: "
                f"{_MIGRATION_PATH}"
            )

        schema = (
            _MIGRATION_PATH.read_text(
                encoding="utf-8"
            )
        )

        self._db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._managed_connection() as connection:
            connection.executescript(
                schema
            )

    @staticmethod
    def _entry_from_row(
        row: sqlite3.Row,
    ) -> KnowledgeCatalogEntry:
        return build_knowledge_catalog_entry(
            source_key=row[
                "source_key"
            ],
            external_id=row[
                "external_id"
            ],
            tier=KnowledgeCatalogTier(
                row["tier"]
            ),
            watch_updates=bool(
                row["watch_updates"]
            ),
            priority=int(
                row["priority"]
            ),
            added_reason=row[
                "added_reason"
            ],
        )

    def get_entry(
        self,
        source_key: str,
        external_id: str,
    ) -> KnowledgeCatalogEntry | None:
        source_key = normalize_source_key(
            source_key
        )

        external_id = str(
            external_id or ""
        ).strip()

        if not external_id:
            raise ValueError(
                "external_id no puede estar vacío"
            )

        with self._managed_connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM knowledge_catalog_entries
                WHERE source_key = ?
                  AND external_id = ?
                """,
                (
                    source_key,
                    external_id,
                ),
            ).fetchone()

        if row is None:
            return None

        return self._entry_from_row(
            row
        )

    def upsert(
        self,
        entry: KnowledgeCatalogEntry,
    ) -> KnowledgeCatalogWriteResult:
        if not isinstance(
            entry,
            KnowledgeCatalogEntry,
        ):
            raise TypeError(
                "entry debe ser KnowledgeCatalogEntry"
            )

        with self._managed_connection() as connection:
            current = connection.execute(
                """
                SELECT *
                FROM knowledge_catalog_entries
                WHERE source_key = ?
                  AND external_id = ?
                """,
                (
                    entry.source_key,
                    entry.external_id,
                ),
            ).fetchone()

            if current is not None:
                previous = (
                    self._entry_from_row(
                        current
                    )
                )

                if previous == entry:
                    return KnowledgeCatalogWriteResult(
                        canonical_key=(
                            entry.canonical_key
                        ),
                        status=(
                            KnowledgeCatalogWriteStatus.UNCHANGED
                        ),
                        written=False,
                    )

                connection.execute(
                    """
                    UPDATE knowledge_catalog_entries
                    SET
                        tier = ?,
                        watch_updates = ?,
                        priority = ?,
                        added_reason = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        entry.tier.value,
                        int(
                            entry.watch_updates
                        ),
                        entry.priority,
                        entry.added_reason,
                        _utc_now(),
                        int(
                            current["id"]
                        ),
                    ),
                )

                return KnowledgeCatalogWriteResult(
                    canonical_key=(
                        entry.canonical_key
                    ),
                    status=(
                        KnowledgeCatalogWriteStatus.UPDATED
                    ),
                    written=True,
                )

            now = _utc_now()

            connection.execute(
                """
                INSERT INTO knowledge_catalog_entries (
                    source_key,
                    external_id,
                    canonical_key,
                    tier,
                    watch_updates,
                    priority,
                    added_reason,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.source_key,
                    entry.external_id,
                    entry.canonical_key,
                    entry.tier.value,
                    int(
                        entry.watch_updates
                    ),
                    entry.priority,
                    entry.added_reason,
                    now,
                    now,
                ),
            )

        return KnowledgeCatalogWriteResult(
            canonical_key=(
                entry.canonical_key
            ),
            status=(
                KnowledgeCatalogWriteStatus.NEW
            ),
            written=True,
        )

    def list_entries(
        self,
        *,
        tier: KnowledgeCatalogTier | None = None,
        watch_only: bool = False,
    ) -> tuple[
        KnowledgeCatalogEntry,
        ...,
    ]:
        if (
            tier is not None
            and not isinstance(
                tier,
                KnowledgeCatalogTier,
            )
        ):
            raise TypeError(
                "tier debe ser KnowledgeCatalogTier o None"
            )

        if not isinstance(
            watch_only,
            bool,
        ):
            raise TypeError(
                "watch_only debe ser bool"
            )

        clauses = []
        params: list[object] = []

        if tier is not None:
            clauses.append(
                "tier = ?"
            )
            params.append(
                tier.value
            )

        if watch_only:
            clauses.append(
                "watch_updates = 1"
            )

        where_sql = ""

        if clauses:
            where_sql = (
                "WHERE "
                + " AND ".join(
                    clauses
                )
            )

        sql = f"""
            SELECT *
            FROM knowledge_catalog_entries
            {where_sql}
            ORDER BY
                priority DESC,
                source_key ASC,
                external_id ASC
        """

        with self._managed_connection() as connection:
            rows = connection.execute(
                sql,
                tuple(
                    params
                ),
            ).fetchall()

        return tuple(
            self._entry_from_row(
                row
            )
            for row in rows
        )
