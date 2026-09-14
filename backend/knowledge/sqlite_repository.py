"""Adaptador SQLite para el puerto KnowledgeRepository.

SQLite es una decisión de infraestructura de V1, no una dependencia
del dominio Knowledge. El servicio de ingestión solo deberá conocer
KnowledgeRepository.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3

from .contracts import KnowledgeItemKind
from .items import (
    KnowledgeItem,
    build_knowledge_item,
)
from .repository import (
    KnowledgeRepositoryWriteResult,
    KnowledgeRevisionSnapshot,
)
from .revisions import (
    KnowledgeRevisionDecision,
    KnowledgeRevisionStatus,
    knowledge_record_sha256,
)
from .source_registry import normalize_source_key


_SCHEMA_PATH = (
    Path(__file__).resolve().parent
    / "storage"
    / "sqlite_schema.sql"
)


class KnowledgeRepositoryIntegrityError(RuntimeError):
    """La persistencia no coincide con el contrato canónico."""


def _metadata_json(
    item: KnowledgeItem,
) -> str:
    return json.dumps(
        dict(item.metadata),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _published_on_text(
    item: KnowledgeItem,
) -> str | None:
    if item.published_on is None:
        return None

    return item.published_on.isoformat()


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


class SQLiteKnowledgeRepository:
    """Persistencia SQLite intercambiable por otra implementación."""

    def __init__(
        self,
        db_path: str | Path,
    ) -> None:
        self._db_path = Path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._db_path
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )
        return connection

    def initialize_schema(self) -> None:
        schema = _SCHEMA_PATH.read_text(
            encoding="utf-8"
        )

        self._db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._connect() as connection:
            connection.executescript(
                schema
            )

    @staticmethod
    def _item_from_row(
        row: sqlite3.Row,
    ) -> KnowledgeItem:
        published_raw = (
            row["published_on"]
        )

        published_on = (
            date.fromisoformat(
                published_raw
            )
            if published_raw
            else None
        )

        metadata_raw = json.loads(
            row["metadata_json"]
        )

        if not isinstance(
            metadata_raw,
            dict,
        ):
            raise KnowledgeRepositoryIntegrityError(
                "knowledge metadata_json no es objeto"
            )

        item = build_knowledge_item(
            source_key=row["source_key"],
            external_id=row["external_id"],
            title=row["title"],
            item_kind=KnowledgeItemKind(
                row["item_kind"]
            ),
            content_text=row["content_text"],
            canonical_uri=row[
                "canonical_uri"
            ],
            source_revision=row[
                "source_revision"
            ],
            published_on=published_on,
            language=row["language"],
            metadata=metadata_raw,
        )

        if (
            item.content_sha256
            != row["content_sha256"]
        ):
            raise KnowledgeRepositoryIntegrityError(
                "content_sha256 persistido no coincide"
            )

        if (
            knowledge_record_sha256(item)
            != row["record_sha256"]
        ):
            raise KnowledgeRepositoryIntegrityError(
                "record_sha256 persistido no coincide"
            )

        return item

    def get_current(
        self,
        source_key: str,
        external_id: str,
    ) -> KnowledgeItem | None:
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

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM knowledge_items
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

        return self._item_from_row(row)

    @staticmethod
    def _validate_decision(
        item: KnowledgeItem,
        decision: KnowledgeRevisionDecision,
    ) -> None:
        if (
            decision.canonical_key
            != item.canonical_key
        ):
            raise ValueError(
                "RevisionDecision pertenece "
                "a otra KnowledgeItem"
            )

        expected_record = (
            knowledge_record_sha256(
                item
            )
        )

        if (
            decision.current_record_sha256
            != expected_record
        ):
            raise ValueError(
                "RevisionDecision contiene "
                "record_sha256 incompatible"
            )

        if (
            decision.current_content_sha256
            != item.content_sha256
        ):
            raise ValueError(
                "RevisionDecision contiene "
                "content_sha256 incompatible"
            )

    @staticmethod
    def _revision_values(
        *,
        knowledge_item_id: int,
        revision_number: int,
        revision_status: KnowledgeRevisionStatus,
        item: KnowledgeItem,
        record_sha256: str,
        observed_at: str,
    ) -> tuple:
        return (
            knowledge_item_id,
            revision_number,
            revision_status.value,
            item.source_key,
            item.external_id,
            item.canonical_key,
            item.title,
            item.item_kind.value,
            item.canonical_uri,
            item.source_revision,
            _published_on_text(item),
            item.language,
            item.content_text,
            item.content_sha256,
            record_sha256,
            _metadata_json(item),
            observed_at,
        )

    def persist(
        self,
        item: KnowledgeItem,
        decision: KnowledgeRevisionDecision,
    ) -> KnowledgeRepositoryWriteResult:
        if not isinstance(
            item,
            KnowledgeItem,
        ):
            raise TypeError(
                "item debe ser KnowledgeItem"
            )

        if not isinstance(
            decision,
            KnowledgeRevisionDecision,
        ):
            raise TypeError(
                "decision debe ser KnowledgeRevisionDecision"
            )

        self._validate_decision(
            item,
            decision,
        )

        with self._connect() as connection:
            current_row = connection.execute(
                """
                SELECT *
                FROM knowledge_items
                WHERE source_key = ?
                  AND external_id = ?
                """,
                (
                    item.source_key,
                    item.external_id,
                ),
            ).fetchone()

            if (
                decision.status
                is KnowledgeRevisionStatus.UNCHANGED
            ):
                if current_row is None:
                    raise ValueError(
                        "UNCHANGED requiere versión previa persistida"
                    )

                return KnowledgeRepositoryWriteResult(
                    canonical_key=item.canonical_key,
                    status=decision.status,
                    revision_number=int(
                        current_row[
                            "revision_number"
                        ]
                    ),
                    written=False,
                )

            now = _utc_now()
            record_sha256 = (
                decision.current_record_sha256
            )

            if (
                decision.status
                is KnowledgeRevisionStatus.NEW
            ):
                if current_row is not None:
                    raise ValueError(
                        "NEW no puede sobrescribir "
                        "una identidad existente"
                    )

                cursor = connection.execute(
                    """
                    INSERT INTO knowledge_items (
                        source_key,
                        external_id,
                        canonical_key,
                        title,
                        item_kind,
                        canonical_uri,
                        source_revision,
                        published_on,
                        language,
                        content_text,
                        content_sha256,
                        record_sha256,
                        metadata_json,
                        revision_number,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.source_key,
                        item.external_id,
                        item.canonical_key,
                        item.title,
                        item.item_kind.value,
                        item.canonical_uri,
                        item.source_revision,
                        _published_on_text(
                            item
                        ),
                        item.language,
                        item.content_text,
                        item.content_sha256,
                        record_sha256,
                        _metadata_json(item),
                        1,
                        now,
                        now,
                    ),
                )

                knowledge_item_id = int(
                    cursor.lastrowid
                )
                revision_number = 1

            else:
                if current_row is None:
                    raise ValueError(
                        "Una revisión requiere "
                        "versión previa persistida"
                    )

                revision_number = (
                    int(
                        current_row[
                            "revision_number"
                        ]
                    )
                    + 1
                )

                knowledge_item_id = int(
                    current_row["id"]
                )

                connection.execute(
                    """
                    UPDATE knowledge_items
                    SET
                        title = ?,
                        item_kind = ?,
                        canonical_uri = ?,
                        source_revision = ?,
                        published_on = ?,
                        language = ?,
                        content_text = ?,
                        content_sha256 = ?,
                        record_sha256 = ?,
                        metadata_json = ?,
                        revision_number = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        item.title,
                        item.item_kind.value,
                        item.canonical_uri,
                        item.source_revision,
                        _published_on_text(
                            item
                        ),
                        item.language,
                        item.content_text,
                        item.content_sha256,
                        record_sha256,
                        _metadata_json(item),
                        revision_number,
                        now,
                        knowledge_item_id,
                    ),
                )

            connection.execute(
                """
                INSERT INTO knowledge_item_revisions (
                    knowledge_item_id,
                    revision_number,
                    revision_status,
                    source_key,
                    external_id,
                    canonical_key,
                    title,
                    item_kind,
                    canonical_uri,
                    source_revision,
                    published_on,
                    language,
                    content_text,
                    content_sha256,
                    record_sha256,
                    metadata_json,
                    observed_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._revision_values(
                    knowledge_item_id=knowledge_item_id,
                    revision_number=revision_number,
                    revision_status=decision.status,
                    item=item,
                    record_sha256=record_sha256,
                    observed_at=now,
                ),
            )

        return KnowledgeRepositoryWriteResult(
            canonical_key=item.canonical_key,
            status=decision.status,
            revision_number=revision_number,
            written=True,
        )

    def list_revisions(
        self,
        source_key: str,
        external_id: str,
    ) -> tuple[
        KnowledgeRevisionSnapshot,
        ...,
    ]:
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

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM knowledge_item_revisions
                WHERE source_key = ?
                  AND external_id = ?
                ORDER BY revision_number ASC
                """,
                (
                    source_key,
                    external_id,
                ),
            ).fetchall()

        snapshots = []

        for row in rows:
            item = self._item_from_row(
                row
            )

            snapshots.append(
                KnowledgeRevisionSnapshot(
                    revision_number=int(
                        row[
                            "revision_number"
                        ]
                    ),
                    revision_status=(
                        KnowledgeRevisionStatus(
                            row[
                                "revision_status"
                            ]
                        )
                    ),
                    item=item,
                    record_sha256=row[
                        "record_sha256"
                    ],
                    observed_at=row[
                        "observed_at"
                    ],
                )
            )

        return tuple(
            snapshots
        )
