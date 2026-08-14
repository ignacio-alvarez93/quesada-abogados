"""
Implementación SQLite del repository de Comunicaciones.

Esta clase encapsula toda la persistencia SQLite del módulo.
El frontend y los servicios de dominio no deben importar sqlite3.
"""

import json
import sqlite3
from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path

from backend.communications.call_followups import (
    CommunicationCallCallback,
    CommunicationCallFollowUp,
    CommunicationCallFollowUpOverview,
)
from backend.communications.calls import (
    CommunicationCall,
)
from backend.communications.models import (
    CommunicationAccount,
    CommunicationClientContext,
    CommunicationExpedientContext,
    CommunicationMessage,
    CommunicationMessageAttempt,
    CommunicationThread,
    CommunicationThreadContext,
    CommunicationThreadOverview,
)


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

MIGRATION_PATHS = (
    (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "20260810_create_communication_core.sql"
    ),
    (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "20260812_harden_communication_message_identity.sql"
    ),
    (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "20260814_create_communication_calls.sql"
    ),
    (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "20260814_harden_communication_call_identity.sql"
    ),
    (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "20260814_create_communication_call_followups.sql"
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
        for migration_path in MIGRATION_PATHS:
            if not migration_path.exists():
                raise FileNotFoundError(
                    (
                        "No existe la migración: "
                        f"{migration_path}"
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
    def _call_from_row(row):
        if not row:
            return None

        return CommunicationCall(
            id=int(row["id"]),
            thread_id=(
                int(row["thread_id"])
                if row["thread_id"] is not None
                else None
            ),
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
            channel=row["channel"],
            direction=row["direction"],
            phone_number=row["phone_number"],
            display_name_snapshot=(
                row["display_name_snapshot"]
            ),
            reason_code=row["reason_code"],
            reason_detail=row["reason_detail"],
            status=row["status"],
            outcome_code=row["outcome_code"],
            provider=row["provider"],
            provider_call_id=(
                row["provider_call_id"]
            ),
            external_call_key=(
                row["external_call_key"]
            ),
            created_at=row["created_at"],
            dialed_at=row["dialed_at"],
            ringing_at=row["ringing_at"],
            answered_at=row["answered_at"],
            ended_at=row["ended_at"],
            ring_duration_seconds=(
                int(
                    row[
                        "ring_duration_seconds"
                    ]
                )
                if row[
                    "ring_duration_seconds"
                ] is not None
                else None
            ),
            talk_duration_seconds=(
                int(
                    row[
                        "talk_duration_seconds"
                    ]
                )
                if row[
                    "talk_duration_seconds"
                ] is not None
                else None
            ),
            total_duration_seconds=(
                int(
                    row[
                        "total_duration_seconds"
                    ]
                )
                if row[
                    "total_duration_seconds"
                ] is not None
                else None
            ),
            notes=row["notes"],
            created_by=row["created_by"],
            metadata=_json_load(
                row["metadata_json"]
            ),
        )

    @staticmethod
    def _call_follow_up_from_row(
        row,
    ):
        if not row:
            return None

        return CommunicationCallFollowUp(
            id=int(row["id"]),
            source_call_id=int(
                row["source_call_id"]
            ),
            status=row["status"],
            resolved_at=row["resolved_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _call_callback_from_row(
        row,
    ):
        if not row:
            return None

        return CommunicationCallCallback(
            id=int(row["id"]),
            source_call_id=int(
                row["source_call_id"]
            ),
            callback_call_id=int(
                row["callback_call_id"]
            ),
            created_at=row["created_at"],
        )

    @staticmethod
    def _call_follow_up_overview_from_row(
        row,
    ):
        if not row:
            return None

        return CommunicationCallFollowUpOverview(
            follow_up_id=int(
                row["follow_up_id"]
            ),
            source_call_id=int(
                row["source_call_id"]
            ),
            follow_up_status=(
                row["follow_up_status"]
            ),
            channel=row["channel"],
            phone_number=row["phone_number"],
            display_name_snapshot=(
                row["display_name_snapshot"]
            ),
            thread_id=(
                int(row["thread_id"])
                if row["thread_id"]
                is not None
                else None
            ),
            client_id=(
                int(row["client_id"])
                if row["client_id"]
                is not None
                else None
            ),
            expedient_id=(
                int(row["expedient_id"])
                if row["expedient_id"]
                is not None
                else None
            ),
            source_call_status=(
                row["source_call_status"]
            ),
            source_call_created_at=(
                row["source_call_created_at"]
            ),
            source_call_ringing_at=(
                row["source_call_ringing_at"]
            ),
            source_call_ended_at=(
                row["source_call_ended_at"]
            ),
            callback_count=int(
                row["callback_count"]
                or 0
            ),
            latest_callback_at=(
                row["latest_callback_at"]
            ),
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
    def _thread_overview_from_row(
        row,
    ):
        if not row:
            return None

        return CommunicationThreadOverview(
            thread_id=int(
                row["thread_id"]
            ),
            account_id=int(
                row["account_id"]
            ),
            channel=(
                row["channel"]
            ),
            client_id=(
                int(
                    row["client_id"]
                )
                if row["client_id"]
                is not None
                else None
            ),
            client_name=(
                row["client_name"]
                or None
            ),
            external_thread_key=(
                row[
                    "external_thread_key"
                ]
            ),
            external_address=(
                row[
                    "external_address"
                ]
            ),
            external_display_name=(
                row[
                    "external_display_name"
                ]
            ),
            match_status=(
                row["match_status"]
            ),
            is_archived=bool(
                row["is_archived"]
            ),
            last_message_at=(
                row["last_message_at"]
            ),
            last_message_preview=(
                row[
                    "last_message_preview"
                ]
            ),
            message_count=int(
                row["message_count"]
                or 0
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

    @staticmethod
    def _normalize_call_provider_identity(
        call,
    ):
        """
        Canonicaliza exclusivamente identidad de proveedor.

        provider se persiste en mayúsculas.
        external_call_key conserva mayúsculas/minúsculas porque
        puede representar un identificador case-sensitive.
        """
        provider = (
            str(
                call.provider
                or ""
            )
            .strip()
            .upper()
            or None
        )

        provider_call_id = (
            str(
                call.provider_call_id
                or ""
            )
            .strip()
            or None
        )

        external_call_key = (
            str(
                call.external_call_key
                or ""
            )
            .strip()
            or None
        )

        if (
            external_call_key is not None
            and provider is None
        ):
            raise ValueError(
                "external_call_key requiere provider"
            )

        return replace(
            call,
            provider=provider,
            provider_call_id=provider_call_id,
            external_call_key=external_call_key,
        )

    def _insert_call(
        self,
        conn,
        call,
    ):
        cursor = conn.execute(
            """
            INSERT INTO communication_calls (
                thread_id,
                client_id,
                expedient_id,
                channel,
                direction,
                phone_number,
                display_name_snapshot,
                reason_code,
                reason_detail,
                status,
                outcome_code,
                provider,
                provider_call_id,
                external_call_key,
                dialed_at,
                ringing_at,
                answered_at,
                ended_at,
                ring_duration_seconds,
                talk_duration_seconds,
                total_duration_seconds,
                notes,
                created_by,
                metadata_json
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                call.thread_id,
                call.client_id,
                call.expedient_id,
                call.channel,
                call.direction,
                call.phone_number,
                call.display_name_snapshot,
                call.reason_code,
                call.reason_detail,
                call.status,
                call.outcome_code,
                call.provider,
                call.provider_call_id,
                call.external_call_key,
                call.dialed_at,
                call.ringing_at,
                call.answered_at,
                call.ended_at,
                call.ring_duration_seconds,
                call.talk_duration_seconds,
                call.total_duration_seconds,
                call.notes,
                call.created_by,
                _json_dump(
                    call.metadata
                ),
            ),
        )

        row = conn.execute(
            """
            SELECT *
            FROM communication_calls
            WHERE id = ?
            """,
            (
                int(
                    cursor.lastrowid
                ),
            ),
        ).fetchone()

        return self._call_from_row(
            row
        )

    def create_call(
        self,
        call,
    ):
        """
        Inserción estricta.

        Si existe otra llamada con la misma identidad externa,
        el índice UNIQUE rechazará la duplicidad.
        """
        self.ensure_schema()

        normalized = (
            self
            ._normalize_call_provider_identity(
                call
            )
        )

        with self._connection() as conn:
            return self._insert_call(
                conn,
                normalized,
            )

    def get_call_by_provider_identity(
        self,
        *,
        provider,
        external_call_key,
    ):
        """
        Recupera una llamada por identidad externa canónica.
        """
        self.ensure_schema()

        normalized_provider = (
            str(
                provider
                or ""
            )
            .strip()
            .upper()
            or None
        )

        normalized_key = (
            str(
                external_call_key
                or ""
            )
            .strip()
            or None
        )

        if (
            normalized_provider is None
            or normalized_key is None
        ):
            return None

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_calls
                WHERE provider = ?
                  AND external_call_key = ?
                """,
                (
                    normalized_provider,
                    normalized_key,
                ),
            ).fetchone()

            return self._call_from_row(
                row
            )

    def get_or_create_call_with_identity(
        self,
        call,
    ):
        """
        Inserta una llamada o reutiliza la ya persistida.

        Cuando existe identidad completa:
            (provider, external_call_key)

        la operación es idempotente y tolera carreras entre
        observación realtime y reconciliación histórica.

        Sin external_call_key se mantiene el comportamiento de
        creación normal porque todavía no existe identidad
        externa suficiente para deduplicar con seguridad.
        """
        self.ensure_schema()

        candidate = (
            self
            ._normalize_call_provider_identity(
                call
            )
        )

        provider = candidate.provider
        external_call_key = (
            candidate.external_call_key
        )

        with self._connection() as conn:
            if external_call_key is None:
                return (
                    self._insert_call(
                        conn,
                        candidate,
                    ),
                    True,
                )

            existing = conn.execute(
                """
                SELECT *
                FROM communication_calls
                WHERE provider = ?
                  AND external_call_key = ?
                """,
                (
                    provider,
                    external_call_key,
                ),
            ).fetchone()

            if existing:
                return (
                    self._call_from_row(
                        existing
                    ),
                    False,
                )

            try:
                created = self._insert_call(
                    conn,
                    candidate,
                )

                return (
                    created,
                    True,
                )

            except sqlite3.IntegrityError:
                existing = conn.execute(
                    """
                    SELECT *
                    FROM communication_calls
                    WHERE provider = ?
                      AND external_call_key = ?
                    """,
                    (
                        provider,
                        external_call_key,
                    ),
                ).fetchone()

                if existing:
                    return (
                        self._call_from_row(
                            existing
                        ),
                        False,
                    )

                raise

    def get_call(
        self,
        call_id,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_calls
                WHERE id = ?
                """,
                (
                    int(call_id),
                ),
            ).fetchone()

            return self._call_from_row(
                row
            )

    def update_call_state(
        self,
        call,
    ):
        """
        Persiste únicamente lifecycle y timing de una llamada.

        No permite modificar mediante esta operación:
        - identidad/interlocutor;
        - canal o dirección;
        - vínculos CRM;
        - proveedor;
        - motivo, resultado o notas.

        Las transiciones válidas deben haberse aplicado
        previamente en el dominio de llamadas.
        """
        self.ensure_schema()

        if (
            call is None
            or call.id in (
                None,
                "",
            )
        ):
            raise ValueError(
                "La llamada debe tener id "
                "para actualizar su estado"
            )

        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE communication_calls
                SET
                    status = ?,
                    dialed_at = ?,
                    ringing_at = ?,
                    answered_at = ?,
                    ended_at = ?,
                    ring_duration_seconds = ?,
                    talk_duration_seconds = ?,
                    total_duration_seconds = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    call.status,
                    call.dialed_at,
                    call.ringing_at,
                    call.answered_at,
                    call.ended_at,
                    call.ring_duration_seconds,
                    call.talk_duration_seconds,
                    call.total_duration_seconds,
                    int(call.id),
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Llamada de comunicación "
                    "no encontrada"
                )

            row = conn.execute(
                """
                SELECT *
                FROM communication_calls
                WHERE id = ?
                """,
                (
                    int(call.id),
                ),
            ).fetchone()

            return self._call_from_row(
                row
            )

    def update_call_provider_reconciliation(
        self,
        call,
    ):
        """
        Persiste únicamente conocimiento reconciliable
        procedente del proveedor.

        Puede actualizar:
        - provider_call_id;
        - display_name_snapshot;
        - lifecycle/timestamps/duraciones;
        - metadata_json.

        Nunca modifica:
        - provider / external_call_key;
        - channel / direction / phone_number;
        - thread/client/expedient;
        - reason/outcome/notes/created_by.
        """
        self.ensure_schema()

        if (
            call is None
            or call.id in (
                None,
                "",
            )
        ):
            raise ValueError(
                "La llamada debe tener id "
                "para reconciliarse"
            )

        provider = str(
            call.provider
            or ""
        ).strip().upper()

        external_call_key = str(
            call.external_call_key
            or ""
        ).strip()

        if (
            not provider
            or not external_call_key
        ):
            raise ValueError(
                "La reconciliación requiere "
                "identidad externa completa"
            )

        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE communication_calls
                SET
                    provider_call_id = ?,
                    display_name_snapshot = ?,
                    status = ?,
                    dialed_at = ?,
                    ringing_at = ?,
                    answered_at = ?,
                    ended_at = ?,
                    ring_duration_seconds = ?,
                    talk_duration_seconds = ?,
                    total_duration_seconds = ?,
                    metadata_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND provider = ?
                  AND external_call_key = ?
                """,
                (
                    call.provider_call_id,
                    call.display_name_snapshot,
                    call.status,
                    call.dialed_at,
                    call.ringing_at,
                    call.answered_at,
                    call.ended_at,
                    call.ring_duration_seconds,
                    call.talk_duration_seconds,
                    call.total_duration_seconds,
                    _json_dump(
                        call.metadata
                    ),
                    int(call.id),
                    provider,
                    external_call_key,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Llamada de comunicación "
                    "no encontrada para reconciliar"
                )

            row = conn.execute(
                """
                SELECT *
                FROM communication_calls
                WHERE id = ?
                """,
                (
                    int(call.id),
                ),
            ).fetchone()

            return self._call_from_row(
                row
            )

    def get_call_follow_up(
        self,
        follow_up_id,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_call_followups
                WHERE id = ?
                """,
                (
                    int(follow_up_id),
                ),
            ).fetchone()

            return (
                self._call_follow_up_from_row(
                    row
                )
            )

    def get_call_follow_up_by_source_call(
        self,
        source_call_id,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_call_followups
                WHERE source_call_id = ?
                """,
                (
                    int(source_call_id),
                ),
            ).fetchone()

            return (
                self._call_follow_up_from_row(
                    row
                )
            )

    def get_or_create_call_follow_up(
        self,
        source_call_id,
    ):
        """
        Crea como máximo un seguimiento por llamada origen.

        La operación es idempotente para soportar eventos
        repetidos o reconciliaciones posteriores.
        """
        self.ensure_schema()

        normalized_source_call_id = int(
            source_call_id
        )

        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM communication_call_followups
                WHERE source_call_id = ?
                """,
                (
                    normalized_source_call_id,
                ),
            ).fetchone()

            if existing:
                return (
                    self._call_follow_up_from_row(
                        existing
                    )
                )

            try:
                cursor = conn.execute(
                    """
                    INSERT INTO
                        communication_call_followups (
                            source_call_id,
                            status
                        )
                    VALUES (?, 'PENDING')
                    """,
                    (
                        normalized_source_call_id,
                    ),
                )

            except sqlite3.IntegrityError as exc:
                existing = conn.execute(
                    """
                    SELECT *
                    FROM communication_call_followups
                    WHERE source_call_id = ?
                    """,
                    (
                        normalized_source_call_id,
                    ),
                ).fetchone()

                if existing:
                    return (
                        self._call_follow_up_from_row(
                            existing
                        )
                    )

                raise ValueError(
                    "Llamada origen no encontrada "
                    "para crear seguimiento"
                ) from exc

            row = conn.execute(
                """
                SELECT *
                FROM communication_call_followups
                WHERE id = ?
                """,
                (
                    int(cursor.lastrowid),
                ),
            ).fetchone()

            return (
                self._call_follow_up_from_row(
                    row
                )
            )

    def update_call_follow_up(
        self,
        follow_up,
    ):
        """
        Persiste exclusivamente estado operativo y resolved_at.

        La transición debe haberse validado previamente en
        backend.communications.call_followups.
        """
        self.ensure_schema()

        if (
            follow_up is None
            or follow_up.id in (
                None,
                "",
            )
        ):
            raise ValueError(
                "El seguimiento debe tener id "
                "para ser actualizado"
            )

        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE communication_call_followups
                SET
                    status = ?,
                    resolved_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    follow_up.status,
                    follow_up.resolved_at,
                    int(follow_up.id),
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Seguimiento de llamada "
                    "no encontrado"
                )

            row = conn.execute(
                """
                SELECT *
                FROM communication_call_followups
                WHERE id = ?
                """,
                (
                    int(follow_up.id),
                ),
            ).fetchone()

            return (
                self._call_follow_up_from_row(
                    row
                )
            )

    def link_callback_call(
        self,
        *,
        source_call_id,
        callback_call_id,
    ):
        """
        Vincula una llamada saliente como intento de devolución.

        La misma pareja es idempotente.

        Una llamada callback concreta no puede pertenecer a
        dos llamadas origen diferentes.
        """
        self.ensure_schema()

        source_id = int(
            source_call_id
        )

        callback_id = int(
            callback_call_id
        )

        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM communication_call_callbacks
                WHERE source_call_id = ?
                  AND callback_call_id = ?
                """,
                (
                    source_id,
                    callback_id,
                ),
            ).fetchone()

            if existing:
                return (
                    self._call_callback_from_row(
                        existing
                    )
                )

            try:
                cursor = conn.execute(
                    """
                    INSERT INTO
                        communication_call_callbacks (
                            source_call_id,
                            callback_call_id
                        )
                    VALUES (?, ?)
                    """,
                    (
                        source_id,
                        callback_id,
                    ),
                )

            except sqlite3.IntegrityError as exc:
                conflicting = conn.execute(
                    """
                    SELECT *
                    FROM communication_call_callbacks
                    WHERE callback_call_id = ?
                    """,
                    (
                        callback_id,
                    ),
                ).fetchone()

                if conflicting:
                    raise ValueError(
                        "La llamada de devolución "
                        "ya está vinculada a otro "
                        "seguimiento"
                    ) from exc

                follow_up = conn.execute(
                    """
                    SELECT id
                    FROM communication_call_followups
                    WHERE source_call_id = ?
                    """,
                    (
                        source_id,
                    ),
                ).fetchone()

                if not follow_up:
                    raise ValueError(
                        "Seguimiento de llamada "
                        "no encontrado"
                    ) from exc

                callback_call = conn.execute(
                    """
                    SELECT id
                    FROM communication_calls
                    WHERE id = ?
                    """,
                    (
                        callback_id,
                    ),
                ).fetchone()

                if not callback_call:
                    raise ValueError(
                        "Llamada de devolución "
                        "no encontrada"
                    ) from exc

                raise

            row = conn.execute(
                """
                SELECT *
                FROM communication_call_callbacks
                WHERE id = ?
                """,
                (
                    int(cursor.lastrowid),
                ),
            ).fetchone()

            return (
                self._call_callback_from_row(
                    row
                )
            )

    def get_call_callback_by_callback_call(
        self,
        callback_call_id,
    ):
        """
        Obtiene la relación de devolución a partir
        de la llamada saliente concreta.
        """
        self.ensure_schema()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_call_callbacks
                WHERE callback_call_id = ?
                """,
                (
                    int(callback_call_id),
                ),
            ).fetchone()

            return (
                self._call_callback_from_row(
                    row
                )
            )

    def list_callback_calls(
        self,
        source_call_id,
        *,
        limit=100,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT c.*
                FROM communication_call_callbacks cb
                INNER JOIN communication_calls c
                    ON c.id = cb.callback_call_id
                WHERE cb.source_call_id = ?
                ORDER BY
                    c.created_at ASC,
                    c.id ASC
                LIMIT ?
                """,
                (
                    int(source_call_id),
                    max(
                        1,
                        int(limit),
                    ),
                ),
            ).fetchall()

            return [
                self._call_from_row(
                    row
                )
                for row in rows
            ]

    def list_pending_call_follow_ups(
        self,
        *,
        limit=500,
    ):
        """
        Inventario operativo de seguimientos todavía abiertos.

        Incluye PENDING e IN_PROGRESS.

        Los más antiguos aparecen primero para evitar que una
        llamada perdida quede enterrada por nuevas entradas.
        """
        self.ensure_schema()

        normalized_limit = max(
            1,
            int(limit),
        )

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    f.id
                        AS follow_up_id,

                    f.source_call_id
                        AS source_call_id,

                    f.status
                        AS follow_up_status,

                    c.channel
                        AS channel,

                    c.phone_number
                        AS phone_number,

                    c.display_name_snapshot
                        AS display_name_snapshot,

                    c.thread_id
                        AS thread_id,

                    c.client_id
                        AS client_id,

                    c.expedient_id
                        AS expedient_id,

                    c.status
                        AS source_call_status,

                    c.created_at
                        AS source_call_created_at,

                    c.ringing_at
                        AS source_call_ringing_at,

                    c.ended_at
                        AS source_call_ended_at,

                    (
                        SELECT COUNT(*)
                        FROM communication_call_callbacks cb
                        WHERE
                            cb.source_call_id
                            = f.source_call_id
                    )
                        AS callback_count,

                    (
                        SELECT MAX(cc.created_at)
                        FROM communication_call_callbacks cb2
                        INNER JOIN communication_calls cc
                            ON
                                cc.id
                                = cb2.callback_call_id
                        WHERE
                            cb2.source_call_id
                            = f.source_call_id
                    )
                        AS latest_callback_at

                FROM communication_call_followups f

                INNER JOIN communication_calls c
                    ON c.id = f.source_call_id

                WHERE
                    f.status IN (
                        'PENDING',
                        'IN_PROGRESS'
                    )

                ORDER BY
                    COALESCE(
                        c.ended_at,
                        c.ringing_at,
                        c.created_at
                    ) ASC,
                    f.id ASC

                LIMIT ?
                """,
                (
                    normalized_limit,
                ),
            ).fetchall()

            return [
                self
                ._call_follow_up_overview_from_row(
                    row
                )
                for row in rows
            ]

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

    def get_thread_context(
        self,
        thread_id,
    ):
        self.ensure_schema()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    t.id AS thread_id,
                    t.client_id AS client_id,
                    c.nombre AS nombre,
                    c.primer_apellido
                        AS primer_apellido,
                    c.segundo_apellido
                        AS segundo_apellido,
                    c.nie AS nie,
                    c.pasaporte AS pasaporte,
                    c.dni AS dni,
                    c.telefono AS telefono,
                    c.email AS email,
                    c.nacionalidad
                        AS nacionalidad,
                    c.estado_cliente
                        AS estado_cliente
                FROM communication_threads t
                LEFT JOIN clientes c
                    ON c.id = t.client_id
                WHERE t.id = ?
                """,
                (
                    int(thread_id),
                ),
            ).fetchone()

            if not row:
                return None

            client = None
            expedients = []

            if (
                row["client_id"]
                is not None
            ):
                full_name = " ".join(
                    part
                    for part in (
                        row["nombre"],
                        row[
                            "primer_apellido"
                        ],
                        row[
                            "segundo_apellido"
                        ],
                    )
                    if str(
                        part
                        or ""
                    ).strip()
                ).strip()

                document = (
                    row["nie"]
                    or row["pasaporte"]
                    or row["dni"]
                    or None
                )

                client = (
                    CommunicationClientContext(
                        client_id=int(
                            row["client_id"]
                        ),
                        full_name=(
                            full_name
                            or "Cliente sin nombre"
                        ),
                        document=document,
                        phone=(
                            row["telefono"]
                            or None
                        ),
                        email=(
                            row["email"]
                            or None
                        ),
                        nationality=(
                            row["nacionalidad"]
                            or None
                        ),
                        status=(
                            row["estado_cliente"]
                            or None
                        ),
                    )
                )

                expedient_rows = (
                    conn.execute(
                        """
                        SELECT
                            e.id
                                AS expedient_id,
                            e.numero_expediente
                                AS number,
                            f.nombre
                                AS family_name,
                            te.nombre
                                AS type_name,
                            st.nombre
                                AS subtype_name,
                            ed.nombre
                                AS documentary_status,
                            ea.nombre
                                AS administrative_status
                        FROM expedientes e
                        LEFT JOIN
                            config_tipos_expediente te
                            ON te.id =
                                e.tipo_expediente_id
                        LEFT JOIN
                            config_familias_expediente f
                            ON f.id =
                                te.familia_id
                        LEFT JOIN
                            config_subtipos_expediente st
                            ON st.id =
                                e.subtipo_expediente_id
                        LEFT JOIN
                            config_estados_documentales ed
                            ON ed.id =
                                e.estado_documental_id
                        LEFT JOIN
                            config_estados_administrativos ea
                            ON ea.id =
                                e.estado_administrativo_id
                        WHERE
                            e.cliente_id = ?
                            AND COALESCE(
                                e.activo,
                                1
                            ) = 1
                        ORDER BY
                            e.created_at DESC,
                            e.id DESC
                        """,
                        (
                            int(
                                row["client_id"]
                            ),
                        ),
                    )
                    .fetchall()
                )

                expedients = [
                    CommunicationExpedientContext(
                        expedient_id=int(
                            expedient_row[
                                "expedient_id"
                            ]
                        ),
                        number=(
                            expedient_row[
                                "number"
                            ]
                            or None
                        ),
                        family_name=(
                            expedient_row[
                                "family_name"
                            ]
                            or None
                        ),
                        type_name=(
                            expedient_row[
                                "type_name"
                            ]
                            or None
                        ),
                        subtype_name=(
                            expedient_row[
                                "subtype_name"
                            ]
                            or None
                        ),
                        documentary_status=(
                            expedient_row[
                                "documentary_status"
                            ]
                            or None
                        ),
                        administrative_status=(
                            expedient_row[
                                "administrative_status"
                            ]
                            or None
                        ),
                    )
                    for expedient_row
                    in expedient_rows
                ]

            return CommunicationThreadContext(
                thread_id=int(
                    row["thread_id"]
                ),
                client=client,
                expedients=tuple(
                    expedients
                ),
            )

    def list_thread_overviews(
        self,
        *,
        account_id=None,
        client_id=None,
        channel=None,
        limit=5000,
    ):
        self.ensure_schema()

        sql = """
            SELECT
                t.id AS thread_id,
                t.account_id AS account_id,
                a.channel AS channel,
                t.client_id AS client_id,
                TRIM(
                    COALESCE(
                        c.nombre,
                        ''
                    )
                    || ' '
                    || COALESCE(
                        c.primer_apellido,
                        ''
                    )
                    || ' '
                    || COALESCE(
                        c.segundo_apellido,
                        ''
                    )
                ) AS client_name,
                t.external_thread_key
                    AS external_thread_key,
                t.external_address
                    AS external_address,
                t.external_display_name
                    AS external_display_name,
                t.match_status
                    AS match_status,
                t.is_archived
                    AS is_archived,
                t.last_message_at
                    AS last_message_at,
                (
                    SELECT
                        m.body_text
                    FROM communication_messages m
                    WHERE
                        m.thread_id = t.id
                    ORDER BY
                        COALESCE(
                            m.provider_timestamp,
                            m.created_at
                        ) DESC,
                        m.id DESC
                    LIMIT 1
                ) AS last_message_preview,
                (
                    SELECT
                        COUNT(*)
                    FROM communication_messages mc
                    WHERE
                        mc.thread_id = t.id
                ) AS message_count
            FROM communication_threads t
            INNER JOIN communication_accounts a
                ON a.id = t.account_id
            LEFT JOIN clientes c
                ON c.id = t.client_id
            WHERE 1 = 1
        """

        params = []

        if account_id is not None:
            sql += """
                AND t.account_id = ?
            """

            params.append(
                int(account_id)
            )

        if client_id is not None:
            sql += """
                AND t.client_id = ?
            """

            params.append(
                int(client_id)
            )

        if channel:
            sql += """
                AND UPPER(a.channel) = ?
            """

            params.append(
                str(
                    channel
                )
                .strip()
                .upper()
            )

        sql += """
            ORDER BY
                COALESCE(
                    t.last_message_at,
                    t.created_at
                ) DESC,
                t.id DESC
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
                self._thread_overview_from_row(
                    row
                )
                for row in rows
            ]

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

    @staticmethod
    def _should_advance_provider_status(
        current_status,
        candidate_status,
    ):
        current = str(
            current_status
            or ""
        ).strip().upper()

        candidate = str(
            candidate_status
            or ""
        ).strip().upper()

        if not candidate:
            return False

        if current == candidate:
            return False

        outbound_rank = {
            "PENDING": 0,
            "QUEUED": 1,
            "SENDING": 2,
            "SENT": 3,
            "DELIVERED": 4,
            "READ": 5,
        }

        if (
            current in outbound_rank
            and candidate in outbound_rank
        ):
            return (
                outbound_rank[candidate]
                > outbound_rank[current]
            )

        if (
            current == "RECEIVED"
            and candidate == "RECEIVED"
        ):
            return False

        return False

    @staticmethod
    def _update_thread_last_message(
        conn,
        *,
        thread_id,
        provider_timestamp=None,
    ):
        provider_value = (
            str(
                provider_timestamp
                or ""
            ).strip()
            or None
        )

        conn.execute(
            """
            UPDATE communication_threads
            SET
                last_message_at =
                    CASE
                        WHEN last_message_at IS NULL
                        THEN COALESCE(
                            ?,
                            CURRENT_TIMESTAMP
                        )

                        WHEN ? IS NOT NULL
                             AND ? > last_message_at
                        THEN ?

                        WHEN ? IS NULL
                             AND CURRENT_TIMESTAMP
                                 > last_message_at
                        THEN CURRENT_TIMESTAMP

                        ELSE last_message_at
                    END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                provider_value,
                provider_value,
                provider_value,
                provider_value,
                provider_value,
                int(thread_id),
            ),
        )

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

            self._update_thread_last_message(
                conn,
                thread_id=message.thread_id,
                provider_timestamp=(
                    message.provider_timestamp
                ),
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

    def get_or_create_message_with_status(
        self,
        message,
    ):
        self.ensure_schema()

        provider_message_id = (
            str(
                message.provider_message_id
                or ""
            ).strip()
            or None
        )

        if provider_message_id is None:
            return (
                self.create_message(
                    message
                ),
                True,
            )

        with self._connection() as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE thread_id = ?
                  AND provider_message_id = ?
                """,
                (
                    int(message.thread_id),
                    provider_message_id,
                ),
            ).fetchone()

            if existing:
                existing_message = (
                    self._message_from_row(
                        existing
                    )
                )

                if (
                    self
                    ._should_advance_provider_status(
                        existing_message.status,
                        message.status,
                    )
                ):
                    conn.execute(
                        """
                        UPDATE communication_messages
                        SET
                            status = ?,
                            updated_at =
                                CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            str(
                                message.status
                                or ""
                            )
                            .strip()
                            .upper(),
                            int(
                                existing_message.id
                            ),
                        ),
                    )

                    existing = conn.execute(
                        """
                        SELECT *
                        FROM communication_messages
                        WHERE id = ?
                        """,
                        (
                            int(
                                existing_message.id
                            ),
                        ),
                    ).fetchone()

                return (
                    self._message_from_row(
                        existing
                    ),
                    False,
                )

            try:
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
                        provider_message_id,
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

            except sqlite3.IntegrityError:
                existing = conn.execute(
                    """
                    SELECT *
                    FROM communication_messages
                    WHERE thread_id = ?
                      AND provider_message_id = ?
                    """,
                    (
                        int(message.thread_id),
                        provider_message_id,
                    ),
                ).fetchone()

                if existing:
                    existing_message = (
                        self._message_from_row(
                            existing
                        )
                    )

                    if (
                        self
                        ._should_advance_provider_status(
                            existing_message.status,
                            message.status,
                        )
                    ):
                        conn.execute(
                            """
                            UPDATE communication_messages
                            SET
                                status = ?,
                                updated_at =
                                    CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                str(
                                    message.status
                                    or ""
                                )
                                .strip()
                                .upper(),
                                int(
                                    existing_message.id
                                ),
                            ),
                        )

                        existing = conn.execute(
                            """
                            SELECT *
                            FROM communication_messages
                            WHERE id = ?
                            """,
                            (
                                int(
                                    existing_message.id
                                ),
                            ),
                        ).fetchone()

                    return (
                        self._message_from_row(
                            existing
                        ),
                        False,
                    )

                raise

            self._update_thread_last_message(
                conn,
                thread_id=message.thread_id,
                provider_timestamp=(
                    message.provider_timestamp
                ),
            )

            row = conn.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()

            return (
                self._message_from_row(
                    row
                ),
                True,
            )

    def get_message_by_provider_identity(
        self,
        *,
        thread_id,
        provider_message_id,
    ):
        self.ensure_schema()

        normalized_provider_id = (
            str(
                provider_message_id
                or ""
            ).strip()
        )

        if not normalized_provider_id:
            return None

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE thread_id = ?
                  AND provider_message_id = ?
                LIMIT 1
                """,
                (
                    int(thread_id),
                    normalized_provider_id,
                ),
            ).fetchone()

            return self._message_from_row(
                row
            )

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

    def list_latest_messages(
        self,
        thread_id,
        *,
        limit=50,
    ):
        """Devuelve la ventana más reciente en orden cronológico.

        La selección interior usa DESC para que LIMIT recorte
        desde el final del historial. La consulta exterior vuelve
        a ASC porque ése es el orden requerido por la UI.
        """
        self.ensure_schema()

        normalized_limit = max(
            1,
            int(
                limit
            ),
        )

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM (
                    SELECT *
                    FROM communication_messages
                    WHERE thread_id = ?
                    ORDER BY
                        COALESCE(
                            provider_timestamp,
                            created_at
                        ) DESC,
                        id DESC
                    LIMIT ?
                ) AS recent_messages
                ORDER BY
                    COALESCE(
                        provider_timestamp,
                        created_at
                    ) ASC,
                    id ASC
                """,
                (
                    int(
                        thread_id
                    ),
                    normalized_limit,
                ),
            ).fetchall()

            return [
                self._message_from_row(
                    row
                )
                for row in rows
            ]

    def list_messages_before(
        self,
        thread_id,
        *,
        before_message_id,
        limit=50,
    ):
        """Devuelve la página inmediatamente anterior al cursor.

        El caller solo necesita conocer el id del mensaje más
        antiguo visible. El repositorio resuelve internamente
        la clave cronológica real usada por communication_messages:

            COALESCE(provider_timestamp, created_at), id

        De este modo el frontend no replica semántica SQL ni
        necesita conocer created_at.
        """
        self.ensure_schema()

        normalized_thread_id = int(
            thread_id
        )
        normalized_before_id = int(
            before_message_id
        )
        normalized_limit = max(
            1,
            int(
                limit
            ),
        )

        with self._connection() as conn:
            anchor = conn.execute(
                """
                SELECT
                    id,
                    COALESCE(
                        provider_timestamp,
                        created_at
                    ) AS order_timestamp
                FROM communication_messages
                WHERE thread_id = ?
                  AND id = ?
                LIMIT 1
                """,
                (
                    normalized_thread_id,
                    normalized_before_id,
                ),
            ).fetchone()

            if not anchor:
                return []

            anchor_timestamp = (
                anchor[
                    "order_timestamp"
                ]
            )
            anchor_id = int(
                anchor[
                    "id"
                ]
            )

            rows = conn.execute(
                """
                SELECT *
                FROM (
                    SELECT *
                    FROM communication_messages
                    WHERE thread_id = ?
                      AND (
                            COALESCE(
                                provider_timestamp,
                                created_at
                            ) < ?
                            OR (
                                COALESCE(
                                    provider_timestamp,
                                    created_at
                                ) = ?
                                AND id < ?
                            )
                      )
                    ORDER BY
                        COALESCE(
                            provider_timestamp,
                            created_at
                        ) DESC,
                        id DESC
                    LIMIT ?
                ) AS previous_messages
                ORDER BY
                    COALESCE(
                        provider_timestamp,
                        created_at
                    ) ASC,
                    id ASC
                """,
                (
                    normalized_thread_id,
                    anchor_timestamp,
                    anchor_timestamp,
                    anchor_id,
                    normalized_limit,
                ),
            ).fetchall()

            return [
                self._message_from_row(
                    row
                )
                for row in rows
            ]

    def get_latest_provider_message(
        self,
        thread_id,
    ):
        """Devuelve el mensaje provider más reciente del thread.

        No utiliza list_messages(), porque ese contrato
        devuelve orden cronológico ASC y su LIMIT recorta
        desde el inicio histórico de la conversación.
        """
        self.ensure_schema()

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE thread_id = ?
                  AND provider_message_id IS NOT NULL
                  AND TRIM(provider_message_id) <> ''
                ORDER BY
                    COALESCE(
                        provider_timestamp,
                        created_at
                    ) DESC,
                    id DESC
                LIMIT 1
                """,
                (
                    int(thread_id),
                ),
            ).fetchone()

            return self._message_from_row(
                row
            )

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

    def attach_message_provider_identity(
        self,
        message_id,
        *,
        provider_message_id,
        provider_timestamp=None,
    ):
        """Asocia identidad del proveedor a un mensaje existente.

        La operación es idempotente para la misma identidad y
        nunca sobrescribe silenciosamente otra identidad.
        """
        self.ensure_schema()

        normalized_provider_id = (
            str(
                provider_message_id
                or ""
            ).strip()
        )

        if not normalized_provider_id:
            raise ValueError(
                "provider_message_id es obligatorio"
            )

        normalized_timestamp = (
            str(
                provider_timestamp
                or ""
            ).strip()
            or None
        )

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE id = ?
                """,
                (
                    int(message_id),
                ),
            ).fetchone()

            if not row:
                raise ValueError(
                    "Mensaje de comunicación no encontrado"
                )

            message = (
                self._message_from_row(
                    row
                )
            )

            current_provider_id = (
                str(
                    message.provider_message_id
                    or ""
                ).strip()
                or None
            )

            if (
                current_provider_id
                and current_provider_id
                != normalized_provider_id
            ):
                raise ValueError(
                    "El mensaje ya tiene otra identidad "
                    "de proveedor"
                )

            conflict = conn.execute(
                """
                SELECT id
                FROM communication_messages
                WHERE thread_id = ?
                  AND provider_message_id = ?
                  AND id <> ?
                LIMIT 1
                """,
                (
                    int(
                        message.thread_id
                    ),
                    normalized_provider_id,
                    int(
                        message.id
                    ),
                ),
            ).fetchone()

            if conflict:
                raise ValueError(
                    "La identidad de proveedor ya pertenece "
                    "a otro mensaje de la conversación"
                )

            conn.execute(
                """
                UPDATE communication_messages
                SET
                    provider_message_id = ?,
                    provider_timestamp = COALESCE(
                        provider_timestamp,
                        ?
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    normalized_provider_id,
                    normalized_timestamp,
                    int(
                        message.id
                    ),
                ),
            )

            self._update_thread_last_message(
                conn,
                thread_id=(
                    message.thread_id
                ),
                provider_timestamp=(
                    normalized_timestamp
                ),
            )

            updated = conn.execute(
                """
                SELECT *
                FROM communication_messages
                WHERE id = ?
                """,
                (
                    int(
                        message.id
                    ),
                ),
            ).fetchone()

            return (
                self._message_from_row(
                    updated
                )
            )

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

    def finish_attempt(
        self,
        attempt_id,
        *,
        status,
        error_code=None,
        error_message=None,
        metadata=None,
    ):
        """Finaliza un intento STARTED como SENT o ERROR.

        Un intento ya finalizado solo admite repetición
        idempotente del mismo estado.
        """
        self.ensure_schema()

        normalized_status = (
            str(
                status
                or ""
            )
            .strip()
            .upper()
        )

        if normalized_status not in (
            "SENT",
            "ERROR",
        ):
            raise ValueError(
                "Estado final de intento no válido"
            )

        normalized_error_code = (
            str(
                error_code
                or ""
            ).strip()
            or None
        )

        normalized_error_message = (
            str(
                error_message
                or ""
            ).strip()
            or None
        )

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM communication_message_attempts
                WHERE id = ?
                """,
                (
                    int(attempt_id),
                ),
            ).fetchone()

            if not row:
                raise ValueError(
                    "Intento de comunicación no encontrado"
                )

            attempt = (
                self._attempt_from_row(
                    row
                )
            )

            current_status = (
                str(
                    attempt.status
                    or ""
                )
                .strip()
                .upper()
            )

            if current_status == normalized_status:
                return attempt

            if current_status != "STARTED":
                raise ValueError(
                    "El intento ya está finalizado "
                    "con otro estado"
                )

            metadata_json = (
                _json_dump(
                    metadata
                )
                if metadata is not None
                else None
            )

            conn.execute(
                """
                UPDATE communication_message_attempts
                SET
                    status = ?,
                    finished_at = CURRENT_TIMESTAMP,
                    error_code = ?,
                    error_message = ?,
                    metadata_json = COALESCE(
                        ?,
                        metadata_json
                    )
                WHERE id = ?
                """,
                (
                    normalized_status,
                    (
                        normalized_error_code
                        if normalized_status
                        == "ERROR"
                        else None
                    ),
                    (
                        normalized_error_message
                        if normalized_status
                        == "ERROR"
                        else None
                    ),
                    metadata_json,
                    int(
                        attempt.id
                    ),
                ),
            )

            updated = conn.execute(
                """
                SELECT *
                FROM communication_message_attempts
                WHERE id = ?
                """,
                (
                    int(
                        attempt.id
                    ),
                ),
            ).fetchone()

            return (
                self._attempt_from_row(
                    updated
                )
            )

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
