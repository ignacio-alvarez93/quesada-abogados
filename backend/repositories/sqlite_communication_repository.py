"""
Implementación SQLite del repository de Comunicaciones.

Esta clase encapsula toda la persistencia SQLite del módulo.
El frontend y los servicios de dominio no deben importar sqlite3.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.communications.models import (
    CommunicationAccount,
    CommunicationMessage,
    CommunicationMessageAttempt,
    CommunicationThread,
)


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260810_create_communication_core.sql"
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
        return json.loads(value)
    except Exception:
        return None


class SQLiteCommunicationRepository:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
    ):
        self.db_path = Path(db_path)

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30,
        )

        conn.row_factory = sqlite3.Row

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
                f"No existe la migración: {MIGRATION_PATH}"
            )

        with self._connection() as conn:
            conn.executescript(
                MIGRATION_PATH.read_text(
                    encoding="utf-8"
                )
            )

    @staticmethod
    def _account_from_row(row):
        if not row:
            return None

        return CommunicationAccount(
            id=int(row["id"]),
            code=row["code"],
            channel=row["channel"],
            display_name=row["display_name"],
            transport=row["transport"],
            environment=row["environment"],
            profile_key=row["profile_key"],
            is_active=bool(row["is_active"]),
            is_default=bool(row["is_default"]),
            metadata=_json_load(
                row["metadata_json"]
            ),
        )

    @staticmethod
    def _thread_from_row(row):
        if not row:
            return None

        return CommunicationThread(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            client_id=(
                int(row["client_id"])
                if row["client_id"] is not None
                else None
            ),
            external_thread_key=(
                row["external_thread_key"]
            ),
            external_address=row["external_address"],
            external_display_name=(
                row["external_display_name"]
            ),
            match_status=row["match_status"],
            is_archived=bool(
                row["is_archived"]
            ),
            metadata=_json_load(
                row["metadata_json"]
            ),
        )

    @staticmethod
    def _message_from_row(row):
        if not row:
            return None

        return CommunicationMessage(
            id=int(row["id"]),
            thread_id=int(row["thread_id"]),
            client_id=(
                int(row["client_id"])
                if row["client_id"] is not None
                else None
            ),
            expedient_id=(
                int(row["expedient_id"])
                if row["expedient_id"] is not None
                else None
            ),
            direction=row["direction"],
            body_text=row["body_text"],
            status=row["status"],
            provider_message_id=(
                row["provider_message_id"]
            ),
            provider_timestamp=(
                row["provider_timestamp"]
            ),
            created_by=row["created_by"],
            sent_by=row["sent_by"],
            metadata=_json_load(
                row["metadata_json"]
            ),
        )

    @staticmethod
    def _attempt_from_row(row):
        if not row:
            return None

        return CommunicationMessageAttempt(
            id=int(row["id"]),
            message_id=int(row["message_id"]),
            transport=row["transport"],
            attempt_number=int(
                row["attempt_number"]
            ),
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            metadata=_json_load(
                row["metadata_json"]
            ),
        )

    def save_account(
        self,
        account,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM communication_accounts
                WHERE code = ?
                """,
                (account.code,),
            ).fetchone()

            if existing:
                account_id = int(existing["id"])

                if account.is_default:
                    conn.execute(
                        """
                        UPDATE communication_accounts
                        SET is_default = 0
                        WHERE channel = ?
                          AND id <> ?
                        """,
                        (
                            account.channel,
                            account_id,
                        ),
                    )

                conn.execute(
                    """
                    UPDATE communication_accounts
                    SET
                        channel = ?,
                        display_name = ?,
                        transport = ?,
                        environment = ?,
                        profile_key = ?,
                        is_active = ?,
                        is_default = ?,
                        metadata_json = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        account.channel,
                        account.display_name,
                        account.transport,
                        account.environment,
                        account.profile_key,
                        int(account.is_active),
                        int(account.is_default),
                        _json_dump(
                            account.metadata
                        ),
                        account_id,
                    ),
                )

            else:
                if account.is_default:
                    conn.execute(
                        """
                        UPDATE communication_accounts
                        SET is_default = 0
                        WHERE channel = ?
                        """,
                        (account.channel,),
                    )

                cursor = conn.execute(
                    """
                    INSERT INTO communication_accounts (
                        code,
                        channel,
                        display_name,
                        transport,
                        environment,
                        profile_key,
                        is_active,
                        is_default,
                        metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account.code,
                        account.channel,
                        account.display_name,
                        account.transport,
                        account.environment,
                        account.profile_key,
                        int(account.is_active),
                        int(account.is_default),
                        _json_dump(
                            account.metadata
                        ),
                    ),
                )

                account_id = int(
                    cursor.lastrowid
                )

            row = conn.execute(
                """
                SELECT *
                FROM communication_accounts
                WHERE id = ?
                """,
                (account_id,),
            ).fetchone()

            return self._account_from_row(row)

    def get_account_by_code(
        self,
        code,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_accounts
                WHERE code = ?
                """,
                (str(code or "").strip(),),
            ).fetchone()

            return self._account_from_row(row)

    def get_or_create_thread(
        self,
        thread,
    ):
        stored_thread, _created = (
            self
            .get_or_create_thread_with_status(
                thread
            )
        )

        return stored_thread

    def get_or_create_thread_with_status(
        self,
        thread,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_threads
                WHERE account_id = ?
                  AND external_thread_key = ?
                """,
                (
                    int(thread.account_id),
                    thread.external_thread_key,
                ),
            ).fetchone()

            if row:
                return (
                    self._thread_from_row(row),
                    False,
                )

            cursor = conn.execute(
                """
                INSERT INTO communication_threads (
                    account_id,
                    client_id,
                    external_thread_key,
                    external_address,
                    external_display_name,
                    match_status,
                    is_archived,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(thread.account_id),
                    thread.client_id,
                    thread.external_thread_key,
                    thread.external_address,
                    thread.external_display_name,
                    thread.match_status,
                    int(thread.is_archived),
                    _json_dump(
                        thread.metadata
                    ),
                ),
            )

            thread_id = int(
                cursor.lastrowid
            )

            row = conn.execute(
                """
                SELECT *
                FROM communication_threads
                WHERE id = ?
                """,
                (thread_id,),
            ).fetchone()

            return (
                self._thread_from_row(row),
                True,
            )

    def get_thread(
        self,
        thread_id,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_threads
                WHERE id = ?
                """,
                (int(thread_id),),
            ).fetchone()

            return self._thread_from_row(row)

    def update_thread_match(
        self,
        thread_id,
        *,
        client_id,
        match_status,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            conn.execute(
                """
                UPDATE communication_threads
                SET
                    client_id = ?,
                    match_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    (
                        int(client_id)
                        if client_id is not None
                        else None
                    ),
                    str(
                        match_status
                        or ""
                    ).strip().upper(),
                    int(thread_id),
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM communication_threads
                WHERE id = ?
                """,
                (int(thread_id),),
            ).fetchone()

            if not row:
                raise ValueError(
                    "Conversación de comunicación "
                    "no encontrada"
                )

            return self._thread_from_row(
                row
            )

    def list_client_phone_candidates(
        self,
        *,
        limit=5000,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    nombre,
                    primer_apellido,
                    segundo_apellido,
                    telefono
                FROM clientes
                WHERE COALESCE(
                    TRIM(telefono),
                    ''
                ) <> ''
                ORDER BY id
                LIMIT ?
                """,
                (
                    max(
                        1,
                        int(limit),
                    ),
                ),
            ).fetchall()

            return [
                dict(row)
                for row in rows
            ]

    def list_threads(
        self,
        *,
        account_id=None,
        client_id=None,
        limit=100,
    ):
        self.ensure_schema()

        sql = """
            SELECT *
            FROM communication_threads
            WHERE 1 = 1
        """

        params = []

        if account_id is not None:
            sql += " AND account_id = ?"
            params.append(
                int(account_id)
            )

        if client_id is not None:
            sql += " AND client_id = ?"
            params.append(
                int(client_id)
            )

        sql += """
            ORDER BY
                COALESCE(
                    last_message_at,
                    created_at
                ) DESC,
                id DESC
            LIMIT ?
        """

        params.append(
            max(1, int(limit))
        )

        with self._connection() as conn:
            rows = conn.execute(
                sql,
                params,
            ).fetchall()

            return [
                self._thread_from_row(row)
                for row in rows
            ]

    def create_message(
        self,
        message,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO communication_messages (
                    thread_id,
                    client_id,
                    expedient_id,
                    direction,
                    body_text,
                    status,
                    provider_message_id,
                    provider_timestamp,
                    created_by,
                    sent_by,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(message.thread_id),
                    message.client_id,
                    message.expedient_id,
                    message.direction,
                    message.body_text,
                    message.status,
                    message.provider_message_id,
                    message.provider_timestamp,
                    message.created_by,
                    message.sent_by,
                    _json_dump(
                        message.metadata
                    ),
                ),
            )

            message_id = int(
                cursor.lastrowid
            )

            conn.execute(
                """
                UPDATE communication_threads
                SET
                    last_message_at =
                        CURRENT_TIMESTAMP,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(message.thread_id),),
            )

            row = conn.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()

            return self._message_from_row(row)

    def get_message(
        self,
        message_id,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE id = ?
                """,
                (int(message_id),),
            ).fetchone()

            return self._message_from_row(row)

    def list_messages(
        self,
        thread_id,
        *,
        limit=200,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE thread_id = ?
                ORDER BY
                    COALESCE(
                        provider_timestamp,
                        created_at
                    ) ASC,
                    id ASC
                LIMIT ?
                """,
                (
                    int(thread_id),
                    max(1, int(limit)),
                ),
            ).fetchall()

            return [
                self._message_from_row(row)
                for row in rows
            ]

    def update_message_status(
        self,
        message_id,
        status,
        *,
        sent_by=None,
    ):
        self.ensure_schema()

        normalized_status = (
            str(status or "")
            .strip()
            .upper()
        )

        with self._connection() as conn:
            sent_at_sql = ""

            if normalized_status == "SENT":
                sent_at_sql = (
                    ", sent_at = CURRENT_TIMESTAMP"
                )

            conn.execute(
                f"""
                UPDATE communication_messages
                SET
                    status = ?,
                    sent_by = COALESCE(?, sent_by),
                    updated_at = CURRENT_TIMESTAMP
                    {sent_at_sql}
                WHERE id = ?
                """,
                (
                    normalized_status,
                    sent_by,
                    int(message_id),
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE id = ?
                """,
                (int(message_id),),
            ).fetchone()

            if not row:
                raise ValueError(
                    "Mensaje de comunicación no encontrado"
                )

            return self._message_from_row(row)

    def create_attempt(
        self,
        attempt,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO communication_message_attempts (
                    message_id,
                    transport,
                    attempt_number,
                    status,
                    started_at,
                    finished_at,
                    error_code,
                    error_message,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(attempt.message_id),
                    attempt.transport,
                    int(attempt.attempt_number),
                    attempt.status,
                    attempt.started_at,
                    attempt.finished_at,
                    attempt.error_code,
                    attempt.error_message,
                    _json_dump(
                        attempt.metadata
                    ),
                ),
            )

            attempt_id = int(
                cursor.lastrowid
            )

            row = conn.execute(
                """
                SELECT *
                FROM communication_message_attempts
                WHERE id = ?
                """,
                (attempt_id,),
            ).fetchone()

            return self._attempt_from_row(row)

    def list_attempts(
        self,
        message_id,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM communication_message_attempts
                WHERE message_id = ?
                ORDER BY
                    attempt_number ASC,
                    id ASC
                """,
                (int(message_id),),
            ).fetchall()

            return [
                self._attempt_from_row(row)
                for row in rows
            ]
