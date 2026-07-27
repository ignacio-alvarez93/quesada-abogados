import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    notification_tracking_service,
)
from backend.services.email_platform import (
    email_expedient_sync_service,
    schema_service,
)


SAMPLE_BODY = """
Estimado/a usuario/a,

Le informamos que su solicitud realizada a traves de Mercurio
con ID I33202604680666 para el/la interesado/a con nombre
VICTOR ALFONSO GONZALEZ FERREIRA, ha sido grabada por la
Oficina de Extranjería responsable de su tramitación,
asignándole el número de Expediente 330020260007765.

Reciba un cordial saludo.
"""


class EmailExpedientSyncTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )
        self.db_path = (
            Path(self.temp_dir.name)
            / "email_platform_test.db"
        )

        self.schema_patch = patch.object(
            schema_service,
            "DB_PATH",
            self.db_path,
        )
        self.notification_patch = patch.object(
            notification_tracking_service,
            "DB_PATH",
            self.db_path,
        )

        self.schema_patch.start()
        self.notification_patch.start()

        self._create_base_schema()

    def tearDown(self):
        self.notification_patch.stop()
        self.schema_patch.stop()
        self.temp_dir.cleanup()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(
            self.db_path
        )
        conn.row_factory = sqlite3.Row
        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _create_base_schema(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE clientes (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT,
                    primer_apellido TEXT,
                    segundo_apellido TEXT
                );

                CREATE TABLE config_familias_expediente (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT,
                    nombre TEXT,
                    notification_workflow_code TEXT
                );

                CREATE TABLE config_tipos_expediente (
                    id INTEGER PRIMARY KEY,
                    familia_id INTEGER,
                    codigo TEXT,
                    nombre TEXT
                );

                CREATE TABLE expedientes (
                    id INTEGER PRIMARY KEY,
                    cliente_id INTEGER NOT NULL,
                    numero_expediente TEXT,
                    numero_expediente_mercurio TEXT,
                    numero_presentacion_registro TEXT,
                    numero_expediente_extranjeria TEXT,
                    numero_registro_regage TEXT,
                    registro_csv_geiser TEXT,
                    estado_presentacion TEXT,
                    tipo_expediente_id INTEGER,
                    activo INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE expediente_justificantes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expediente_id INTEGER NOT NULL,
                    cliente_id INTEGER NOT NULL,
                    tipo_justificante TEXT,
                    numero_expediente_documento TEXT,
                    metadata_documento_json TEXT,
                    fecha_documento TEXT,
                    fecha_presentacion TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    activo INTEGER DEFAULT 1
                );

                CREATE TABLE expediente_eventos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expediente_id INTEGER NOT NULL,
                    cliente_id INTEGER NOT NULL,
                    tipo_evento TEXT NOT NULL,
                    titulo TEXT NOT NULL,
                    descripcion TEXT,
                    estado_anterior TEXT,
                    estado_nuevo TEXT,
                    entidad_relacionada TEXT,
                    entidad_relacionada_id INTEGER,
                    usuario TEXT,
                    fecha_evento TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                INSERT INTO clientes (
                    id,
                    nombre,
                    primer_apellido,
                    segundo_apellido
                )
                VALUES (
                    1,
                    'VICTOR ALFONSO',
                    'GONZALEZ',
                    'FERREIRA'
                );

                INSERT INTO config_familias_expediente (
                    id,
                    codigo,
                    nombre,
                    notification_workflow_code
                )
                VALUES (
                    1,
                    'EXTRANJERIA',
                    'EXTRANJERÍA',
                    'EXTRANJERIA_STANDARD'
                );

                INSERT INTO config_tipos_expediente (
                    id,
                    familia_id,
                    codigo,
                    nombre
                )
                VALUES (
                    1,
                    1,
                    'ARRAIGO',
                    'ARRAIGO SOCIOLABORAL'
                );

                INSERT INTO expedientes (
                    id,
                    cliente_id,
                    numero_expediente,
                    numero_expediente_mercurio,
                    numero_presentacion_registro,
                    numero_expediente_extranjeria,
                    numero_registro_regage,
                    registro_csv_geiser,
                    estado_presentacion,
                    tipo_expediente_id,
                    activo
                )
                VALUES (
                    1,
                    1,
                    'EXP-TEST-0001',
                    'I33202604680666',
                    'I33202604680666',
                    '',
                    '',
                    '',
                    'PRESENTADO',
                    1,
                    1
                );

                INSERT INTO expediente_justificantes (
                    expediente_id,
                    cliente_id,
                    tipo_justificante,
                    activo
                )
                VALUES (
                    1,
                    1,
                    'JUSTIFICANTE_PRESENTACION',
                    1
                );
                """
            )

    def _message(
        self,
        *,
        provider_message_id="MSG-001",
        sender=(
            "notificaciones.extranjeria"
            "@correo.gob.es"
        ),
        body=SAMPLE_BODY,
    ):
        return {
            "provider": "TEST",
            "account_email":
                "buzon@despacho.test",
            "provider_message_id":
                provider_message_id,
            "internet_message_id":
                f"<{provider_message_id}@test>",
            "sender_email": sender,
            "subject":
                "Asignación de número "
                "de expediente",
            "received_at":
                "2026-07-27T10:00:00",
            "body_text": body,
        }

    def test_assigns_official_number_and_reconciles(
        self,
    ):
        result = (
            email_expedient_sync_service
            .process_message(
                self._message()
            )
        )

        self.assertEqual(
            result["status"],
            "PROCESSED",
        )

        with self._connect() as conn:
            expediente = conn.execute(
                """
                SELECT *
                FROM expedientes
                WHERE id = 1
                """
            ).fetchone()

            self.assertEqual(
                expediente[
                    "numero_expediente_extranjeria"
                ],
                "330020260007765",
            )

            event = conn.execute(
                """
                SELECT *
                FROM expediente_eventos
                WHERE tipo_evento =
                    'NUMERO_EXPEDIENTE_RECIBIDO_EMAIL'
                """
            ).fetchone()

            self.assertIsNotNone(event)

            message_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM email_messages
                """
            ).fetchone()[0]

            self.assertEqual(
                message_count,
                1,
            )

        tracking = (
            notification_tracking_service
            .get_tracking_by_expedient(1)
        )

        self.assertEqual(
            tracking["estado"],
            (
                notification_tracking_service
                .ESTADO_ESPERA_ADMISION
            ),
        )

    def test_same_message_is_deduplicated(self):
        first = (
            email_expedient_sync_service
            .process_message(
                self._message()
            )
        )
        second = (
            email_expedient_sync_service
            .process_message(
                self._message()
            )
        )

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])

        with self._connect() as conn:
            count = conn.execute(
                """
                SELECT COUNT(*)
                FROM email_messages
                """
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_unknown_expedient_requires_review(
        self,
    ):
        body = SAMPLE_BODY.replace(
            "I33202604680666",
            "I33202609999999",
        )

        result = (
            email_expedient_sync_service
            .process_message(
                self._message(
                    provider_message_id="MSG-002",
                    body=body,
                )
            )
        )

        self.assertEqual(
            result["status"],
            "REVIEW_REQUIRED",
        )
        self.assertEqual(
            result["reason"],
            "EXPEDIENTE_NO_ENCONTRADO",
        )

    def test_unauthorized_sender_is_ignored(
        self,
    ):
        result = (
            email_expedient_sync_service
            .process_message(
                self._message(
                    provider_message_id="MSG-003",
                    sender="unknown@example.com",
                )
            )
        )

        self.assertEqual(
            result["status"],
            "IGNORED",
        )

    def test_different_existing_number_requires_review(
        self,
    ):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE expedientes
                SET numero_expediente_extranjeria =
                    '330020260000001'
                WHERE id = 1
                """
            )

        result = (
            email_expedient_sync_service
            .process_message(
                self._message(
                    provider_message_id="MSG-004"
                )
            )
        )

        self.assertEqual(
            result["status"],
            "REVIEW_REQUIRED",
        )
        self.assertEqual(
            result["reason"],
            (
                "EXPEDIENTE_CON_NUMERO_DIFERENTE"
            ),
        )


if __name__ == "__main__":
    unittest.main()
