"""
Esquema y conexión SQLite de la plataforma de correo.

Las credenciales nunca se almacenan en estas tablas. email_accounts
solo conserva una clave lógica para resolverlas mediante un almacén
seguro externo.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_PATH = (
    Path(__file__).resolve().parents[3]
    / "database"
    / "quesada.db"
)


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def connection(conn=None):
    owns_connection = conn is None
    current = conn or _connect()

    try:
        yield current

        if owns_connection:
            current.commit()

    except Exception:
        if owns_connection:
            current.rollback()
        raise

    finally:
        if owns_connection:
            current.close()


def ensure_email_platform_schema(conn=None):
    with connection(conn) as current:
        current.execute(
            """
            CREATE TABLE IF NOT EXISTS email_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                nombre TEXT NOT NULL,
                email_address TEXT NOT NULL,
                provider TEXT NOT NULL,

                incoming_enabled INTEGER NOT NULL DEFAULT 1,
                outgoing_enabled INTEGER NOT NULL DEFAULT 0,

                credential_key TEXT,
                config_json TEXT,

                last_sync_cursor TEXT,
                last_sync_at TEXT,
                last_sync_status TEXT,
                last_sync_error TEXT,

                activo INTEGER NOT NULL DEFAULT 1,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(provider, email_address)
            )
            """
        )

        current.execute(
            """
            CREATE TABLE IF NOT EXISTS email_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                account_id INTEGER,

                provider TEXT NOT NULL,
                account_email TEXT,
                provider_message_id TEXT,
                provider_thread_id TEXT,
                internet_message_id TEXT,

                dedupe_key TEXT NOT NULL UNIQUE,

                direction TEXT NOT NULL DEFAULT 'INBOUND',
                folder TEXT,

                sender_email TEXT,
                sender_name TEXT,

                recipients_json TEXT,
                cc_json TEXT,
                bcc_json TEXT,

                subject TEXT,
                received_at TEXT,
                sent_at TEXT,

                body_text TEXT,
                body_html TEXT,
                body_sha256 TEXT,

                has_attachments INTEGER NOT NULL DEFAULT 0,

                processing_status TEXT NOT NULL DEFAULT 'NEW',
                processing_error TEXT,

                raw_metadata_json TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (account_id)
                    REFERENCES email_accounts(id)
            )
            """
        )

        current.execute(
            """
            CREATE TABLE IF NOT EXISTS email_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                email_message_id INTEGER NOT NULL,

                provider_attachment_id TEXT,
                filename TEXT,
                mime_type TEXT,
                size_bytes INTEGER,
                sha256 TEXT,

                local_path TEXT,
                document_inbox_id INTEGER,

                download_status TEXT NOT NULL
                    DEFAULT 'PENDING',
                processing_error TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (email_message_id)
                    REFERENCES email_messages(id)
            )
            """
        )

        current.execute(
            """
            CREATE TABLE IF NOT EXISTS email_processing_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                email_message_id INTEGER NOT NULL,
                processor_code TEXT NOT NULL,

                status TEXT NOT NULL,
                confidence INTEGER NOT NULL DEFAULT 0,

                extracted_data_json TEXT,

                matched_entity_type TEXT,
                matched_entity_id INTEGER,

                action_code TEXT,
                action_status TEXT,
                review_reason TEXT,
                error_message TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (email_message_id)
                    REFERENCES email_messages(id),

                UNIQUE(email_message_id, processor_code)
            )
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_email_messages_received
            ON email_messages(received_at)
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_email_messages_processing
            ON email_messages(processing_status)
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_email_messages_sender
            ON email_messages(sender_email)
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_email_processing_status
            ON email_processing_results(
                processor_code,
                status
            )
            """
        )

        current.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_email_processing_match
            ON email_processing_results(
                matched_entity_type,
                matched_entity_id
            )
            """
        )
