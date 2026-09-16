"""Persistencia SQLite de la estructura jurídica Knowledge."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import (
    date,
    datetime,
    timezone,
)
import json
from pathlib import Path
import sqlite3

from .items import (
    compute_content_sha256,
)
from .legal_structure import (
    KnowledgeBlock,
    KnowledgeBlockVersion,
    KnowledgeStructuredDocument,
)
from .source_registry import (
    normalize_source_key,
)
from .structure_repository import (
    KnowledgeStructureWriteResult,
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
    / "20260915_create_knowledge_structure.sql"
)


class KnowledgeStructureRepositoryIntegrityError(
    RuntimeError
):
    """La estructura persistida viola el contrato canónico."""


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _date_text(
    value: date | None,
) -> str | None:
    if value is None:
        return None

    return value.isoformat()


def _date_from_text(
    value: object,
) -> date | None:
    raw = str(
        value or ""
    ).strip()

    if not raw:
        return None

    return date.fromisoformat(
        raw
    )


def _metadata_json(
    metadata: tuple[
        tuple[str, str],
        ...,
    ],
) -> str:
    return json.dumps(
        dict(
            metadata
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _metadata_from_json(
    raw: object,
) -> dict[str, str]:
    value = json.loads(
        str(
            raw or "{}"
        )
    )

    if not isinstance(
        value,
        dict,
    ):
        raise (
            KnowledgeStructureRepositoryIntegrityError(
                "metadata_json estructural "
                "no contiene objeto"
            )
        )

    return {
        str(key): str(
            item or ""
        )
        for key, item
        in value.items()
    }


class SQLiteKnowledgeStructureRepository:
    """Adaptador SQLite del modelo estructural Knowledge."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        self._db_path = Path(
            db_path
        )

    @property
    def db_path(
        self,
    ) -> Path:
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
    def _managed_connection(
        self,
    ):
        connection = (
            self._connect()
        )

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
                "No existe migración "
                "Knowledge Structure: "
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
    def _block_from_row(
        row: sqlite3.Row,
    ) -> KnowledgeBlock:
        return KnowledgeBlock(
            source_key=row[
                "source_key"
            ],
            external_id=row[
                "external_id"
            ],
            block_id=row[
                "block_id"
            ],
            position=int(
                row[
                    "position"
                ]
            ),
            title=row[
                "title"
            ],
            canonical_uri=row[
                "canonical_uri"
            ],
            current_version_key=row[
                "current_version_key"
            ],
            metadata=tuple(
                sorted(
                    _metadata_from_json(
                        row[
                            "metadata_json"
                        ]
                    ).items()
                )
            ),
        )

    @staticmethod
    def _version_from_row(
        row: sqlite3.Row,
    ) -> KnowledgeBlockVersion:
        version = KnowledgeBlockVersion(
            source_key=row[
                "source_key"
            ],
            external_id=row[
                "external_id"
            ],
            block_id=row[
                "block_id"
            ],
            version_key=row[
                "version_key"
            ],
            version_position=int(
                row[
                    "version_position"
                ]
            ),
            content_text=row[
                "content_text"
            ],
            modifier_external_id=row[
                "modifier_external_id"
            ],
            published_on=(
                _date_from_text(
                    row[
                        "published_on"
                    ]
                )
            ),
            effective_from=(
                _date_from_text(
                    row[
                        "effective_from"
                    ]
                )
            ),
            is_current=bool(
                row[
                    "is_current"
                ]
            ),
            metadata=tuple(
                sorted(
                    _metadata_from_json(
                        row[
                            "metadata_json"
                        ]
                    ).items()
                )
            ),
        )

        if (
            version.content_sha256
            != row[
                "content_sha256"
            ]
        ):
            raise (
                KnowledgeStructureRepositoryIntegrityError(
                    "content_sha256 de versión "
                    "persistida no coincide"
                )
            )

        return version

    def get_document(
        self,
        source_key: str,
        external_id: str,
    ) -> KnowledgeStructuredDocument | None:
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
            block_rows = connection.execute(
                """
                SELECT *
                FROM knowledge_blocks
                WHERE source_key = ?
                  AND external_id = ?
                ORDER BY position ASC
                """,
                (
                    source_key,
                    external_id,
                ),
            ).fetchall()

            if not block_rows:
                return None

            version_rows = connection.execute(
                """
                SELECT
                    versions.*
                FROM knowledge_block_versions
                    AS versions
                INNER JOIN knowledge_blocks
                    AS blocks
                    ON blocks.id
                     = versions.knowledge_block_id
                WHERE versions.source_key = ?
                  AND versions.external_id = ?
                ORDER BY
                    blocks.position ASC,
                    versions.version_position ASC
                """,
                (
                    source_key,
                    external_id,
                ),
            ).fetchall()

        blocks = tuple(
            self._block_from_row(
                row
            )
            for row
            in block_rows
        )

        versions = tuple(
            self._version_from_row(
                row
            )
            for row
            in version_rows
        )

        return KnowledgeStructuredDocument(
            source_key=source_key,
            external_id=external_id,
            blocks=blocks,
            versions=versions,
        )

    def _validate_parent_item(
        self,
        document: KnowledgeStructuredDocument,
    ) -> None:
        with self._managed_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    content_sha256
                FROM knowledge_items
                WHERE source_key = ?
                  AND external_id = ?
                """,
                (
                    document.source_key,
                    document.external_id,
                ),
            ).fetchone()

        if row is None:
            raise (
                KnowledgeStructureRepositoryIntegrityError(
                    "La estructura requiere "
                    "KnowledgeItem materializado: "
                    f"{document.canonical_key}"
                )
            )

        structured_hash = (
            compute_content_sha256(
                document.current_content_text
            )
        )

        if (
            structured_hash
            != row[
                "content_sha256"
            ]
        ):
            raise (
                KnowledgeStructureRepositoryIntegrityError(
                    "La vista vigente estructurada "
                    "no coincide con KnowledgeItem"
                )
            )

    def persist(
        self,
        document: KnowledgeStructuredDocument,
    ) -> KnowledgeStructureWriteResult:
        if not isinstance(
            document,
            KnowledgeStructuredDocument,
        ):
            raise TypeError(
                "document debe ser "
                "KnowledgeStructuredDocument"
            )

        self._validate_parent_item(
            document
        )

        previous = self.get_document(
            document.source_key,
            document.external_id,
        )

        if (
            previous is not None
            and previous == document
        ):
            return KnowledgeStructureWriteResult(
                canonical_key=(
                    document.canonical_key
                ),
                block_count=len(
                    document.blocks
                ),
                version_count=len(
                    document.versions
                ),
                inserted_blocks=0,
                updated_blocks=0,
                inserted_versions=0,
                updated_versions=0,
                written=False,
            )

        inserted_blocks = 0
        updated_blocks = 0

        inserted_versions = 0
        updated_versions = 0

        incoming_block_ids = {
            block.block_id
            for block
            in document.blocks
        }

        incoming_version_keys = {
            version.version_key
            for version
            in document.versions
        }

        incoming_version_positions = {
            version.version_key: (
                version.block_id,
                version.version_position,
            )
            for version
            in document.versions
        }

        now = _utc_now()

        with self._managed_connection() as connection:
            stored_blocks = connection.execute(
                """
                SELECT block_id
                FROM knowledge_blocks
                WHERE source_key = ?
                  AND external_id = ?
                """,
                (
                    document.source_key,
                    document.external_id,
                ),
            ).fetchall()

            missing_blocks = {
                row[
                    "block_id"
                ]
                for row
                in stored_blocks
            } - incoming_block_ids

            if missing_blocks:
                raise (
                    KnowledgeStructureRepositoryIntegrityError(
                        "Snapshot estructural perdió "
                        "bloques previamente observados: "
                        f"{tuple(sorted(missing_blocks))}"
                    )
                )

            stored_versions = connection.execute(
                """
                SELECT
                    block_id,
                    version_key,
                    version_position
                FROM knowledge_block_versions
                WHERE source_key = ?
                  AND external_id = ?
                """,
                (
                    document.source_key,
                    document.external_id,
                ),
            ).fetchall()

            missing_versions = {
                str(
                    row[
                        "version_key"
                    ]
                )
                for row
                in stored_versions
            } - incoming_version_keys

            if missing_versions:
                raise (
                    KnowledgeStructureRepositoryIntegrityError(
                        "Snapshot estructural perdió "
                        "versiones previamente observadas: "
                        f"{tuple(sorted(missing_versions))}"
                    )
                )

            rebase_block_ids = {
                str(
                    row[
                        "block_id"
                    ]
                )
                for row
                in stored_versions
                if (
                    incoming_version_positions[
                        str(
                            row[
                                "version_key"
                            ]
                        )
                    ][1]
                    != int(
                        row[
                            "version_position"
                        ]
                    )
                )
            }

            block_ids: dict[
                str,
                int,
            ] = {}

            for block in document.blocks:
                metadata_json = (
                    _metadata_json(
                        block.metadata
                    )
                )

                row = connection.execute(
                    """
                    SELECT *
                    FROM knowledge_blocks
                    WHERE source_key = ?
                      AND external_id = ?
                      AND block_id = ?
                    """,
                    (
                        block.source_key,
                        block.external_id,
                        block.block_id,
                    ),
                ).fetchone()

                if row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO knowledge_blocks (
                            source_key,
                            external_id,
                            block_id,
                            canonical_key,
                            position,
                            title,
                            canonical_uri,
                            current_version_key,
                            metadata_json,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            block.source_key,
                            block.external_id,
                            block.block_id,
                            block.canonical_key,
                            block.position,
                            block.title,
                            block.canonical_uri,
                            block.current_version_key,
                            metadata_json,
                            now,
                            now,
                        ),
                    )

                    block_ids[
                        block.block_id
                    ] = int(
                        cursor.lastrowid
                    )

                    inserted_blocks += 1

                else:
                    block_ids[
                        block.block_id
                    ] = int(
                        row[
                            "id"
                        ]
                    )

                    current_values = (
                        int(
                            row[
                                "position"
                            ]
                        ),
                        row[
                            "title"
                        ],
                        row[
                            "canonical_uri"
                        ],
                        row[
                            "current_version_key"
                        ],
                        row[
                            "metadata_json"
                        ],
                    )

                    desired_values = (
                        block.position,
                        block.title,
                        block.canonical_uri,
                        block.current_version_key,
                        metadata_json,
                    )

                    if (
                        current_values
                        != desired_values
                    ):
                        connection.execute(
                            """
                            UPDATE knowledge_blocks
                            SET
                                position = ?,
                                title = ?,
                                canonical_uri = ?,
                                current_version_key = ?,
                                metadata_json = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                block.position,
                                block.title,
                                block.canonical_uri,
                                block.current_version_key,
                                metadata_json,
                                now,
                                int(
                                    row[
                                        "id"
                                    ]
                                ),
                            ),
                        )

                        updated_blocks += 1

            # version_position expresa orden, no identidad.
            #
            # Si aparece una revisión histórica anterior, versiones
            # ya persistidas pueden desplazarse de posición sin cambiar
            # su version_key. Liberamos primero el rango ordinal del
            # bloque para evitar colisiones UNIQUE durante el rebasing.
            for block_id in sorted(
                rebase_block_ids
            ):
                stored_max_row = connection.execute(
                    """
                    SELECT COALESCE(
                        MAX(version_position),
                        0
                    ) AS max_position
                    FROM knowledge_block_versions
                    WHERE source_key = ?
                      AND external_id = ?
                      AND block_id = ?
                    """,
                    (
                        document.source_key,
                        document.external_id,
                        block_id,
                    ),
                ).fetchone()

                stored_max = int(
                    stored_max_row[
                        "max_position"
                    ]
                )

                incoming_max = max(
                    version.version_position
                    for version
                    in document.versions
                    if (
                        version.block_id
                        == block_id
                    )
                )

                position_offset = (
                    stored_max
                    + incoming_max
                    + 1
                )

                connection.execute(
                    """
                    UPDATE knowledge_block_versions
                    SET
                        version_position = (
                            version_position + ?
                        ),
                        updated_at = ?
                    WHERE source_key = ?
                      AND external_id = ?
                      AND block_id = ?
                    """,
                    (
                        position_offset,
                        now,
                        document.source_key,
                        document.external_id,
                        block_id,
                    ),
                )

            # Permite trasladar atomicamente el marcador vigente.
            connection.execute(
                """
                UPDATE knowledge_block_versions
                SET
                    is_current = 0,
                    updated_at = ?
                WHERE source_key = ?
                  AND external_id = ?
                  AND is_current = 1
                """,
                (
                    now,
                    document.source_key,
                    document.external_id,
                ),
            )

            for version in document.versions:
                metadata_json = (
                    _metadata_json(
                        version.metadata
                    )
                )

                row = connection.execute(
                    """
                    SELECT *
                    FROM knowledge_block_versions
                    WHERE source_key = ?
                      AND external_id = ?
                      AND block_id = ?
                      AND version_key = ?
                    """,
                    (
                        version.source_key,
                        version.external_id,
                        version.block_id,
                        version.version_key,
                    ),
                ).fetchone()

                desired_values = (
                    version.version_position,
                    version.version_key,
                    version.canonical_key,
                    version.modifier_external_id,
                    _date_text(
                        version.published_on
                    ),
                    _date_text(
                        version.effective_from
                    ),
                    int(
                        version.is_current
                    ),
                    version.content_text,
                    version.content_sha256,
                    metadata_json,
                )

                if row is None:
                    connection.execute(
                        """
                        INSERT INTO knowledge_block_versions (
                            knowledge_block_id,
                            source_key,
                            external_id,
                            block_id,
                            version_key,
                            canonical_key,
                            version_position,
                            modifier_external_id,
                            published_on,
                            effective_from,
                            is_current,
                            content_text,
                            content_sha256,
                            metadata_json,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            block_ids[
                                version.block_id
                            ],
                            version.source_key,
                            version.external_id,
                            version.block_id,
                            version.version_key,
                            version.canonical_key,
                            version.version_position,
                            version.modifier_external_id,
                            _date_text(
                                version.published_on
                            ),
                            _date_text(
                                version.effective_from
                            ),
                            int(
                                version.is_current
                            ),
                            version.content_text,
                            version.content_sha256,
                            metadata_json,
                            now,
                            now,
                        ),
                    )

                    inserted_versions += 1

                else:
                    current_values = (
                        int(
                            row[
                                "version_position"
                            ]
                        ),
                        row[
                            "version_key"
                        ],
                        row[
                            "canonical_key"
                        ],
                        row[
                            "modifier_external_id"
                        ],
                        row[
                            "published_on"
                        ],
                        row[
                            "effective_from"
                        ],
                        int(
                            row[
                                "is_current"
                            ]
                        ),
                        row[
                            "content_text"
                        ],
                        row[
                            "content_sha256"
                        ],
                        row[
                            "metadata_json"
                        ],
                    )

                    if (
                        current_values
                        != desired_values
                    ):
                        connection.execute(
                            """
                            UPDATE knowledge_block_versions
                            SET
                                version_position = ?,
                                version_key = ?,
                                canonical_key = ?,
                                modifier_external_id = ?,
                                published_on = ?,
                                effective_from = ?,
                                is_current = ?,
                                content_text = ?,
                                content_sha256 = ?,
                                metadata_json = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                version.version_position,
                                version.version_key,
                                version.canonical_key,
                                version.modifier_external_id,
                                _date_text(
                                    version.published_on
                                ),
                                _date_text(
                                    version.effective_from
                                ),
                                int(
                                    version.is_current
                                ),
                                version.content_text,
                                version.content_sha256,
                                metadata_json,
                                now,
                                int(
                                    row[
                                        "id"
                                    ]
                                ),
                            ),
                        )

                        updated_versions += 1

        return KnowledgeStructureWriteResult(
            canonical_key=(
                document.canonical_key
            ),
            block_count=len(
                document.blocks
            ),
            version_count=len(
                document.versions
            ),
            inserted_blocks=(
                inserted_blocks
            ),
            updated_blocks=(
                updated_blocks
            ),
            inserted_versions=(
                inserted_versions
            ),
            updated_versions=(
                updated_versions
            ),
            written=True,
        )
