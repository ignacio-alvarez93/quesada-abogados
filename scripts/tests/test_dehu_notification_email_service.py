import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backend.services.email_platform import (
    dehu_notification_service,
    email_expedient_sync_service,
    schema_service,
)
from backend.services.email_platform.processors import (
    dehu_notification_notice_processor,
)


SAMPLE_BODY = """
Le informamos que dispone de una nueva notificación electrónica
como Titular procedente del organismo Dirección General de
Gestión Migratoria, con DIR3 EA0055167 y perteneciente a
Ministerio de Inclusión, Seguridad Social y Migraciones, con
los siguientes datos:

Titular: QUESADA SOLER ANA BELEN .. con NIF/NIE ***1004**
Identificador: 52713836a679de8b7ebf
Organismo Emisor: Dirección General de Gestión Migratoria,
con DIR3 EA0055167 y perteneciente a Ministerio de Inclusión,
Seguridad Social y Migraciones
Concepto: not_337020260010359_21457988_11041171
Vínculo: Titular

En caso de que no accediera a su contenido antes de las
23:59:59 del día 06/08/26 en horario peninsular, se considerará
que el acto de notificación ha sido efectuado.
"""


class DehuNotificationEmailServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )
        self.db_path = (
            Path(self.temp_dir.name)
            / "dehu_test.db"
        )

        self.schema_patch = patch.object(
            schema_service,
            "DB_PATH",
            self.db_path,
        )

        self.schema_patch.start()
        self._create_base_schema()

    def tearDown(self):
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

                CREATE TABLE expedientes (
                    id INTEGER PRIMARY KEY,
                    cliente_id INTEGER NOT NULL,
                    numero_expediente TEXT,
                    numero_expediente_extranjeria TEXT,
                    activo INTEGER DEFAULT 1,
                    created_at TEXT
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                        DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE expediente_eventos (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,
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
                    fecha_evento TEXT
                        DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT
                        DEFAULT CURRENT_TIMESTAMP
                );

                INSERT INTO clientes (
                    id,
                    nombre,
                    primer_apellido,
                    segundo_apellido
                )
                VALUES (
                    1,
                    'ANA BELEN',
                    'QUESADA',
                    'SOLER'
                );

                INSERT INTO expedientes (
                    id,
                    cliente_id,
                    numero_expediente,
                    numero_expediente_extranjeria,
                    activo
                )
                VALUES (
                    1,
                    1,
                    'EXP-TEST-DEHU',
                    '337020260010359',
                    1
                );
                """
            )

    def _message(
        self,
        *,
        provider="GMAIL_API",
        provider_message_id="DEHU-001",
        body=SAMPLE_BODY,
    ):
        return {
            "provider": provider,
            "account_email":
                "buzon@despacho.test",
            "provider_message_id":
                provider_message_id,
            "internet_message_id":
                (
                    f"<{provider}-"
                    f"{provider_message_id}@test>"
                ),
            "sender_email":
                "no-reply-notifica@correo.gob.es",
            "subject":
                "Nueva notificación electrónica",
            "received_at":
                "2026-07-29T08:00:00",
            "body_text": body,
        }

    def test_parser_extracts_notice(self):
        result = (
            dehu_notification_notice_processor
            .extract(
                self._message()
            )
        )

        self.assertEqual(
            result["status"],
            "EXTRACTED",
        )

        data = result["extracted_data"]

        self.assertEqual(
            data["dehu_identifier"],
            "52713836a679de8b7ebf",
        )
        self.assertEqual(
            data[
                "numero_expediente_extranjeria"
            ],
            "337020260010359",
        )
        self.assertEqual(
            data["deadline_at"],
            "2026-08-06 23:59:59",
        )
        self.assertEqual(
            data["issuer_dir3"],
            "EA0055167",
        )

    def test_matches_expedient_provisionally(self):
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
        self.assertEqual(
            result["verification_status"],
            "MATCHED_PROVISIONAL",
        )
        self.assertEqual(
            result["expediente_id"],
            1,
        )

        with self._connect() as conn:
            notification = conn.execute(
                """
                SELECT *
                FROM dehu_notifications
                """
            ).fetchone()

            self.assertEqual(
                notification[
                    "email_expedient_number"
                ],
                "337020260010359",
            )
            self.assertEqual(
                notification["expediente_id"],
                1,
            )
            self.assertEqual(
                notification[
                    "dehu_expedient_number"
                ],
                None,
            )

            event = conn.execute(
                """
                SELECT *
                FROM expediente_eventos
                WHERE tipo_evento =
                    'DEHU_NOTIFICATION_NOTICE_RECEIVED'
                """
            ).fetchone()

            self.assertIsNotNone(event)

    def test_unknown_expedient_requires_review(
        self,
    ):
        body = SAMPLE_BODY.replace(
            "337020260010359",
            "337020260099999",
        )

        result = (
            email_expedient_sync_service
            .process_message(
                self._message(
                    provider_message_id="DEHU-002",
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

    def test_same_notification_from_two_providers(
        self,
    ):
        first = (
            email_expedient_sync_service
            .process_message(
                self._message(
                    provider="GMAIL_API",
                    provider_message_id="GMAIL-1",
                )
            )
        )

        second = (
            email_expedient_sync_service
            .process_message(
                self._message(
                    provider="IONOS_IMAP",
                    provider_message_id="IONOS-1",
                )
            )
        )

        self.assertEqual(
            first["dehu_notification_id"],
            second["dehu_notification_id"],
        )

        with self._connect() as conn:
            notification_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM dehu_notifications
                """
            ).fetchone()[0]

            source_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM dehu_notification_email_sources
                """
            ).fetchone()[0]

            event_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM expediente_eventos
                WHERE tipo_evento =
                    'DEHU_NOTIFICATION_NOTICE_RECEIVED'
                """
            ).fetchone()[0]

        self.assertEqual(notification_count, 1)
        self.assertEqual(source_count, 2)
        self.assertEqual(event_count, 1)

    def test_unauthorized_sender_is_not_dehu(self):
        message = self._message()
        message["sender_email"] = (
            "unknown@example.com"
        )

        self.assertFalse(
            dehu_notification_notice_processor
            .can_process(message)
        )




class DehuCurrentNoticeFormatTest(
    unittest.TestCase
):
    def test_extracts_current_html_notice_format(
        self,
    ):
        message = {
            "sender_email":
                "noreply.dehu@correo.gob.es",
            "body_text": """
            <p>Te informamos que está disponible una nueva
            notificación con los siguientes datos:</p>

            <ul>
              <li>ANA BELEN QUESADA SOLER con NIF/NIE:
              ***100*** en calidad de Titular</li>
              <li>Organismo emisor: Oficina de Extranjeria
              en Santander, con DIR3: EA0040331</li>
              <li>Identificador:
              50541956a694b992150f</li>
              <li>Con vencimiento el día:
              08/08/2026</li>
              <li>Concepto:
              not_390020260004768_21500877_11077896</li>
            </ul>
            """,
        }

        result = (
            dehu_notification_notice_processor
            .extract(message)
        )

        self.assertEqual(
            result["status"],
            "EXTRACTED",
        )

        data = result["extracted_data"]

        self.assertEqual(
            data["dehu_identifier"],
            "50541956a694b992150f",
        )
        self.assertEqual(
            data[
                "numero_expediente_extranjeria"
            ],
            "390020260004768",
        )
        self.assertEqual(
            data["deadline_at"],
            "2026-08-08 23:59:59",
        )
        self.assertEqual(
            data["issuer_dir3"],
            "EA0040331",
        )
        self.assertEqual(
            data["recipient_document_masked"],
            "***100***",
        )


if __name__ == "__main__":
    unittest.main()
