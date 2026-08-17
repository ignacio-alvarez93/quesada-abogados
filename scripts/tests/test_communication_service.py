import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.communications.models import (
    CommunicationThread,
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    MESSAGE_STATUS_DELIVERED,
    MESSAGE_STATUS_READ,
    MESSAGE_STATUS_RECEIVED,
    THREAD_MATCH_MATCHED,
    THREAD_MATCH_UNMATCHED,
)
from backend.communications.phone_normalization import (
    normalize_phone,
)
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)
from backend.services.communication_service import (
    CommunicationService,
)


class CommunicationServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "communications.db"
        )

        conn = sqlite3.connect(
            str(self.db_path)
        )

        try:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE clientes (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    primer_apellido TEXT,
                    segundo_apellido TEXT,
                    nie TEXT,
                    pasaporte TEXT,
                    dni TEXT,
                    telefono TEXT,
                    email TEXT,
                    nacionalidad TEXT,
                    estado_cliente TEXT
                );

                CREATE TABLE config_familias_expediente (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT,
                    nombre TEXT
                );

                CREATE TABLE config_tipos_expediente (
                    id INTEGER PRIMARY KEY,
                    familia_id INTEGER,
                    codigo TEXT,
                    nombre TEXT
                );

                CREATE TABLE config_subtipos_expediente (
                    id INTEGER PRIMARY KEY,
                    tipo_expediente_id INTEGER,
                    codigo TEXT,
                    nombre TEXT
                );

                CREATE TABLE config_estados_documentales (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT
                );

                CREATE TABLE config_estados_administrativos (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT
                );

                CREATE TABLE expedientes (
                    id INTEGER PRIMARY KEY,
                    cliente_id INTEGER,
                    numero_expediente TEXT,
                    box_folder_path TEXT,
                    tipo_expediente_id INTEGER,
                    subtipo_expediente_id INTEGER,
                    estado_documental_id INTEGER,
                    estado_administrativo_id INTEGER,
                    activo INTEGER DEFAULT 1,
                    created_at TEXT
                        DEFAULT CURRENT_TIMESTAMP
                );

                INSERT INTO clientes (
                    id,
                    nombre,
                    primer_apellido,
                    segundo_apellido,
                    nie,
                    pasaporte,
                    dni,
                    telefono,
                    email,
                    nacionalidad,
                    estado_cliente
                )
                VALUES (
                    10,
                    'CLIENTE',
                    'PRUEBA',
                    NULL,
                    'X1234567A',
                    NULL,
                    NULL,
                    '600 123 456',
                    'cliente@example.com',
                    'ESPAÑA',
                    'ASESORAMIENTO INICIAL'
                );

                INSERT INTO config_familias_expediente (
                    id,
                    codigo,
                    nombre
                )
                VALUES (
                    1,
                    'EXTRANJERIA',
                    'EXTRANJERÍA'
                );

                INSERT INTO config_tipos_expediente (
                    id,
                    familia_id,
                    codigo,
                    nombre
                )
                VALUES (
                    2,
                    1,
                    'REAGRUPACION_FAMILIAR',
                    'REAGRUPACIÓN FAMILIAR'
                );

                INSERT INTO config_subtipos_expediente (
                    id,
                    tipo_expediente_id,
                    codigo,
                    nombre
                )
                VALUES (
                    3,
                    2,
                    'INICIAL',
                    'INICIAL'
                );

                INSERT INTO config_estados_documentales (
                    id,
                    nombre
                )
                VALUES (
                    4,
                    'DOCUMENTACIÓN COMPLETA'
                );

                INSERT INTO config_estados_administrativos (
                    id,
                    nombre
                )
                VALUES (
                    5,
                    'PRESENTADO'
                );

                INSERT INTO expedientes (
                    id,
                    cliente_id,
                    numero_expediente,
                    box_folder_path,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    estado_documental_id,
                    estado_administrativo_id,
                    activo
                )
                VALUES (
                    20,
                    10,
                    'EXP-TEST-0020',
                    'C:/Box/DESPACHO/TEST/EXP-TEST-0020',
                    2,
                    3,
                    4,
                    5,
                    1
                );
                """
            )

            conn.commit()

        finally:
            conn.close()

        repository = (
            SQLiteCommunicationRepository(
                self.db_path
            )
        )

        self.service = (
            CommunicationService(
                repository=repository
            )
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_spanish_mobile_normalization(self):
        phone = normalize_phone(
            "600 123 456"
        )

        self.assertTrue(phone.valid)

        self.assertEqual(
            phone.digits,
            "34600123456",
        )

        self.assertEqual(
            phone.e164,
            "+34600123456",
        )

    def test_whatsapp_dev_account_is_idempotent(
        self,
    ):
        first = (
            self.service
            .ensure_whatsapp_dev_account()
        )

        second = (
            self.service
            .ensure_whatsapp_dev_account()
        )

        self.assertEqual(
            first.id,
            second.id,
        )

        self.assertEqual(
            first.profile_key,
            "whatsapp_dev",
        )

    def test_thread_matches_client_by_phone(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "34600123456"
                ),
                phone="+34 600 123 456",
                display_name=(
                    "Cliente prueba"
                ),
            )
        )

        thread = result["thread"]

        self.assertEqual(
            thread.client_id,
            10,
        )

        self.assertEqual(
            thread.match_status,
            THREAD_MATCH_MATCHED,
        )

    def test_unknown_phone_is_unmatched(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "34600999888"
                ),
                phone="+34 600 999 888",
                display_name="Desconocido",
            )
        )

        thread = result["thread"]

        self.assertIsNone(
            thread.client_id
        )

        self.assertEqual(
            thread.match_status,
            THREAD_MATCH_UNMATCHED,
        )

    def test_passive_sidebar_discovery_creates_unknown_phone_once(
        self,
    ):
        first = (
            self.service
            .discover_whatsapp_sidebar_thread(
                identity=(
                    "34 600 999 888"
                ),
                display_name=(
                    "+34 600 999 888"
                ),
                preview="Hola",
                primary_detail="13:05",
                unread_count=1,
            )
        )

        second = (
            self.service
            .discover_whatsapp_sidebar_thread(
                identity=(
                    "34 600 999 888"
                ),
                display_name=(
                    "+34 600 999 888"
                ),
                preview="Hola otra vez",
                primary_detail="13:06",
                unread_count=2,
            )
        )

        self.assertTrue(
            first["discovered"]
        )
        self.assertTrue(
            first["created"]
        )
        self.assertFalse(
            first["reused"]
        )

        self.assertTrue(
            second["discovered"]
        )
        self.assertFalse(
            second["created"]
        )
        self.assertTrue(
            second["reused"]
        )

        self.assertEqual(
            first["thread"].id,
            second["thread"].id,
        )

        self.assertEqual(
            first[
                "external_thread_key"
            ],
            "phone:34600999888",
        )

        self.assertEqual(
            first["thread"].external_address,
            "+34600999888",
        )

        self.assertIsNone(
            first["thread"].client_id
        )

        self.assertEqual(
            first["thread"].match_status,
            THREAD_MATCH_UNMATCHED,
        )

    def test_passive_sidebar_discovery_rejects_non_phone_identity(
        self,
    ):
        result = (
            self.service
            .discover_whatsapp_sidebar_thread(
                identity="mohamed",
                display_name="Mohamed",
                preview="Hola",
                unread_count=1,
            )
        )

        self.assertFalse(
            result["discovered"]
        )
        self.assertFalse(
            result["created"]
        )
        self.assertFalse(
            result["reused"]
        )

        self.assertEqual(
            result["reason"],
            "SIDEBAR_IDENTITY_NOT_PHONE",
        )

        self.assertIsNone(
            result["thread"]
        )


    def test_whatsapp_thread_is_idempotent(
        self,
    ):
        first = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600123456"
                ),
                phone="+34 600 123 456",
                display_name=(
                    "Cliente prueba"
                ),
                metadata={
                    "source":
                        "whatsapp_web_sync",
                },
            )
        )

        second = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600123456"
                ),
                phone="+34 600 123 456",
                display_name=(
                    "Cliente prueba"
                ),
                metadata={
                    "source":
                        "whatsapp_web_sync",
                },
            )
        )

        first_thread = (
            first["thread"]
        )

        second_thread = (
            second["thread"]
        )

        self.assertTrue(
            first["created"]
        )

        self.assertFalse(
            second["created"]
        )

        self.assertEqual(
            first_thread.id,
            second_thread.id,
        )

        self.assertEqual(
            first_thread.external_thread_key,
            "phone:34600123456",
        )

        self.assertEqual(
            second_thread.external_thread_key,
            "phone:34600123456",
        )

        self.assertEqual(
            first_thread.client_id,
            10,
        )

        self.assertEqual(
            second_thread.client_id,
            10,
        )

        account = (
            self.service
            .ensure_whatsapp_dev_account()
        )

        threads = (
            self.service
            .repository
            .list_threads(
                account_id=account.id,
                limit=100,
            )
        )

        matching = [
            thread
            for thread in threads
            if (
                thread.external_thread_key
                == "phone:34600123456"
            )
        ]

        self.assertEqual(
            len(matching),
            1,
        )

    def test_whatsapp_match_backfill_preserves_unmatched(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600123456"
                ),
                phone="+34 699 999 999",
                display_name=(
                    "Pendiente de match"
                ),
            )
        )

        thread = result[
            "thread"
        ]

        self.assertIsNone(
            thread.client_id
        )

        conn = sqlite3.connect(
            str(
                self.db_path
            )
        )

        try:
            conn.execute(
                """
                UPDATE clientes
                SET telefono = ?
                WHERE id = ?
                """,
                (
                    "+34 600 123 456",
                    10,
                ),
            )

            conn.commit()

        finally:
            conn.close()

        stored = (
            self.service
            .repository
            .update_thread_match(
                thread.id,
                client_id=None,
                match_status=(
                    THREAD_MATCH_UNMATCHED
                ),
            )
        )

        self.assertIsNone(
            stored.client_id
        )

        result = (
            self.service
            .backfill_whatsapp_thread_matches()
        )

        summary = result[
            "summary"
        ]

        self.assertEqual(
            summary["scanned"],
            1,
        )

        self.assertEqual(
            summary["updated"],
            0,
        )

        # El teléfono del thread sigue siendo
        # +34699999999, por lo que no debe
        # enlazarse accidentalmente.
        self.assertEqual(
            summary["unmatched"],
            1,
        )

    def test_whatsapp_match_backfill_is_idempotent(
        self,
    ):
        account = (
            self.service
            .ensure_whatsapp_dev_account()
        )

        thread = (
            self.service
            .repository
            .get_or_create_thread(
                CommunicationThread(
                    id=None,
                    account_id=account.id,
                    client_id=None,
                    external_thread_key=(
                        "phone:34600123456"
                    ),
                    external_address=(
                        "+34600123456"
                    ),
                    external_display_name=(
                        "Cliente prueba"
                    ),
                    match_status=(
                        THREAD_MATCH_UNMATCHED
                    ),
                )
            )
        )

        first = (
            self.service
            .backfill_whatsapp_thread_matches()
        )

        first_summary = (
            first["summary"]
        )

        self.assertEqual(
            first_summary["updated"],
            1,
        )

        self.assertEqual(
            first_summary["matched"],
            1,
        )

        self.assertEqual(
            first_summary["scanned"],
            (
                first_summary[
                    "already_linked"
                ]
                + first_summary[
                    "updated"
                ]
                + first_summary[
                    "ambiguous"
                ]
                + first_summary[
                    "unmatched"
                ]
            ),
        )

        self.assertEqual(
            first_summary["matched"],
            first_summary["updated"],
        )

        stored = (
            self.service
            .repository
            .get_thread(
                thread.id
            )
        )

        self.assertEqual(
            stored.client_id,
            10,
        )

        self.assertEqual(
            stored.match_status,
            THREAD_MATCH_MATCHED,
        )

        second = (
            self.service
            .backfill_whatsapp_thread_matches()
        )

        second_summary = (
            second["summary"]
        )

        self.assertEqual(
            second_summary["updated"],
            0,
        )

        self.assertEqual(
            second_summary[
                "already_linked"
            ],
            1,
        )

        stored_second = (
            self.service
            .repository
            .get_thread(
                thread.id
            )
        )

        self.assertEqual(
            stored_second.client_id,
            10,
        )

    def test_whatsapp_match_backfill_preserves_ambiguity(
        self,
    ):
        conn = sqlite3.connect(
            str(
                self.db_path
            )
        )

        try:
            conn.execute(
                """
                INSERT INTO clientes (
                    id,
                    nombre,
                    primer_apellido,
                    segundo_apellido,
                    telefono
                )
                VALUES (
                    11,
                    'OTRO',
                    'CLIENTE',
                    NULL,
                    '+34 600 123 456'
                )
                """
            )

            conn.commit()

        finally:
            conn.close()

        account = (
            self.service
            .ensure_whatsapp_dev_account()
        )

        thread = (
            self.service
            .repository
            .get_or_create_thread(
                CommunicationThread(
                    id=None,
                    account_id=account.id,
                    client_id=None,
                    external_thread_key=(
                        "phone:34600123456"
                    ),
                    external_address=(
                        "+34600123456"
                    ),
                    external_display_name=(
                        "Ambiguo"
                    ),
                    match_status=(
                        THREAD_MATCH_UNMATCHED
                    ),
                )
            )
        )

        result = (
            self.service
            .backfill_whatsapp_thread_matches()
        )

        summary = result[
            "summary"
        ]

        self.assertEqual(
            summary["updated"],
            0,
        )

        self.assertEqual(
            summary["ambiguous"],
            1,
        )

        stored = (
            self.service
            .repository
            .get_thread(
                thread.id
            )
        )

        self.assertIsNone(
            stored.client_id
        )

        self.assertEqual(
            stored.match_status,
            THREAD_MATCH_UNMATCHED,
        )

    def test_resolve_whatsapp_thread_by_unique_display_name(
        self,
    ):
        created = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600111111"
                ),
                phone="+34 600 111 111",
                display_name=(
                    "Mi Amor ❤️"
                ),
            )
        )

        expected = created[
            "thread"
        ]

        result = (
            self.service
            .resolve_whatsapp_thread_by_identity(
                "Mi Amor"
            )
        )

        self.assertTrue(
            result["matched"]
        )

        self.assertFalse(
            result["ambiguous"]
        )

        self.assertEqual(
            result["match_basis"],
            "DISPLAY_NAME",
        )

        self.assertEqual(
            result["thread"].thread_id,
            expected.id,
        )


    def test_resolve_whatsapp_thread_prefers_phone_identity(
        self,
    ):
        created = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600111222"
                ),
                phone="+34 600 111 222",
                display_name=(
                    "Contacto teléfono"
                ),
            )
        )

        expected = created[
            "thread"
        ]

        result = (
            self.service
            .resolve_whatsapp_thread_by_identity(
                "+34 600 111 222"
            )
        )

        self.assertTrue(
            result["matched"]
        )

        self.assertFalse(
            result["ambiguous"]
        )

        self.assertEqual(
            result["match_basis"],
            "PHONE",
        )

        self.assertEqual(
            result["thread"].thread_id,
            expected.id,
        )


    def test_resolve_whatsapp_thread_rejects_ambiguous_display_name(
        self,
    ):
        self.service.get_or_create_whatsapp_thread(
            external_thread_key=(
                "phone:34600111333"
            ),
            phone="+34 600 111 333",
            display_name="Mohamed",
        )

        self.service.get_or_create_whatsapp_thread(
            external_thread_key=(
                "phone:34600111444"
            ),
            phone="+34 600 111 444",
            display_name="MOHAMED ❤️",
        )

        result = (
            self.service
            .resolve_whatsapp_thread_by_identity(
                "Mohamed"
            )
        )

        self.assertFalse(
            result["matched"]
        )

        self.assertTrue(
            result["ambiguous"]
        )

        self.assertEqual(
            result["match_basis"],
            "DISPLAY_NAME",
        )

        self.assertIsNone(
            result["thread"]
        )

        self.assertEqual(
            len(
                result["matches"]
            ),
            2,
        )


    def test_resolve_whatsapp_thread_preserves_unmatched_identity(
        self,
    ):
        result = (
            self.service
            .resolve_whatsapp_thread_by_identity(
                "Contacto inexistente"
            )
        )

        self.assertFalse(
            result["matched"]
        )

        self.assertFalse(
            result["ambiguous"]
        )

        self.assertIsNone(
            result["thread"]
        )

        self.assertEqual(
            result["matches"],
            [],
        )


    def test_thread_overview_projects_client_and_messages(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600123456"
                ),
                phone="+34 600 123 456",
                display_name=(
                    "Cliente WhatsApp"
                ),
            )
        )

        thread = result["thread"]

        self.service.register_inbound_message(
            thread_id=thread.id,
            body_text="Primer mensaje",
            provider_message_id=(
                "overview-in-1"
            ),
        )

        self.service.create_outbound_message(
            thread_id=thread.id,
            body_text="Último mensaje",
            expedient_id=20,
            created_by="TEST",
        )

        overview = (
            self.service
            .list_thread_overviews(
                channel="WHATSAPP",
            )
        )

        summary = overview[
            "summary"
        ]

        items = overview[
            "items"
        ]

        self.assertEqual(
            summary["total"],
            1,
        )

        self.assertEqual(
            summary["linked"],
            1,
        )

        self.assertEqual(
            summary["unlinked"],
            0,
        )

        self.assertEqual(
            summary["whatsapp"],
            1,
        )

        self.assertEqual(
            len(items),
            1,
        )

        item = items[0]

        self.assertEqual(
            item.thread_id,
            thread.id,
        )

        self.assertEqual(
            item.client_id,
            10,
        )

        self.assertEqual(
            item.client_name,
            "CLIENTE PRUEBA",
        )

        self.assertEqual(
            item.channel,
            "WHATSAPP",
        )

        self.assertEqual(
            item.external_address,
            "+34600123456",
        )

        self.assertEqual(
            item.message_count,
            2,
        )

        self.assertEqual(
            item.last_message_preview,
            "Último mensaje",
        )

    def test_thread_overview_filters_linkage(
        self,
    ):
        self.service.get_or_create_whatsapp_thread(
            external_thread_key=(
                "phone:34600123456"
            ),
            phone="+34 600 123 456",
            display_name="Vinculado",
        )

        self.service.get_or_create_whatsapp_thread(
            external_thread_key=(
                "phone:34600999888"
            ),
            phone="+34 600 999 888",
            display_name="Sin vincular",
        )

        all_result = (
            self.service
            .list_thread_overviews(
                channel="WHATSAPP",
                linkage="ALL",
            )
        )

        linked_result = (
            self.service
            .list_thread_overviews(
                channel="WHATSAPP",
                linkage="LINKED",
            )
        )

        unlinked_result = (
            self.service
            .list_thread_overviews(
                channel="WHATSAPP",
                linkage="UNLINKED",
            )
        )

        self.assertEqual(
            all_result[
                "summary"
            ][
                "visible"
            ],
            2,
        )

        self.assertEqual(
            linked_result[
                "summary"
            ][
                "visible"
            ],
            1,
        )

        self.assertEqual(
            unlinked_result[
                "summary"
            ][
                "visible"
            ],
            1,
        )

        self.assertEqual(
            linked_result[
                "items"
            ][0].client_id,
            10,
        )

        self.assertIsNone(
            unlinked_result[
                "items"
            ][0].client_id
        )

    def test_thread_overview_search_is_format_agnostic(
        self,
    ):
        self.service.get_or_create_whatsapp_thread(
            external_thread_key=(
                "phone:34600123456"
            ),
            phone="+34 600 123 456",
            display_name=(
                "Nombre WhatsApp"
            ),
        )

        by_client = (
            self.service
            .list_thread_overviews(
                search="cliente prueba",
            )
        )

        by_display = (
            self.service
            .list_thread_overviews(
                search="nombre whatsapp",
            )
        )

        by_phone = (
            self.service
            .list_thread_overviews(
                search="+34600123456",
            )
        )

        self.assertEqual(
            len(
                by_client["items"]
            ),
            1,
        )

        self.assertEqual(
            len(
                by_display["items"]
            ),
            1,
        )

        self.assertEqual(
            len(
                by_phone["items"]
            ),
            1,
        )

    def test_thread_context_returns_linked_client(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600123456"
                ),
                phone="+34 600 123 456",
                display_name=(
                    "Cliente contexto"
                ),
            )
        )

        thread = result[
            "thread"
        ]

        context = (
            self.service
            .get_thread_context(
                thread.id
            )
        )

        self.assertIsNotNone(
            context
        )

        self.assertEqual(
            context.thread_id,
            thread.id,
        )

        self.assertIsNotNone(
            context.client
        )

        self.assertEqual(
            context.client.client_id,
            10,
        )

        self.assertEqual(
            context.client.full_name,
            "CLIENTE PRUEBA",
        )

        self.assertEqual(
            context.client.phone,
            "600 123 456",
        )

    def test_thread_context_preserves_unlinked_thread(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600999888"
                ),
                phone="+34 600 999 888",
                display_name=(
                    "Sin cliente"
                ),
            )
        )

        thread = result[
            "thread"
        ]

        self.assertIsNone(
            thread.client_id
        )

        context = (
            self.service
            .get_thread_context(
                thread.id
            )
        )

        self.assertIsNotNone(
            context
        )

        self.assertIsNone(
            context.client
        )

        self.assertEqual(
            context.expedients,
            (),
        )

    def test_thread_context_returns_client_expedients(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600123456"
                ),
                phone="+34 600 123 456",
                display_name=(
                    "Cliente con expediente"
                ),
            )
        )

        thread = result[
            "thread"
        ]

        context = (
            self.service
            .get_thread_context(
                thread.id
            )
        )

        self.assertIsNotNone(
            context.client
        )

        self.assertEqual(
            context.client.client_id,
            10,
        )

        self.assertEqual(
            len(
                context.expedients
            ),
            1,
        )

        expedient = (
            context.expedients[0]
        )

        self.assertEqual(
            expedient.expedient_id,
            20,
        )

        self.assertEqual(
            expedient.box_folder_path,
            "C:/Box/DESPACHO/TEST/EXP-TEST-0020",
        )

    def test_register_inbound_and_outbound(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "34600123456"
                ),
                phone="600123456",
            )
        )

        thread = result["thread"]

        inbound = (
            self.service
            .register_inbound_message(
                thread_id=thread.id,
                body_text="Hola",
                provider_message_id=(
                    "wa-in-1"
                ),
            )
        )

        outbound = (
            self.service
            .create_outbound_message(
                thread_id=thread.id,
                body_text="Buenos días",
                expedient_id=20,
                created_by="TEST",
            )
        )

        self.assertEqual(
            inbound.direction,
            DIRECTION_INBOUND,
        )

        self.assertEqual(
            outbound.direction,
            DIRECTION_OUTBOUND,
        )

        self.assertEqual(
            outbound.expedient_id,
            20,
        )

    def test_inbound_provider_message_is_idempotent(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600123456"
                ),
                phone=(
                    "+34 600 123 456"
                ),
            )
        )

        thread = result["thread"]

        first = (
            self.service
            .register_inbound_message(
                thread_id=thread.id,
                body_text="Hola",
                provider_message_id=(
                    "wa-in-idempotent-1"
                ),
                provider_timestamp=(
                    "2026-08-10T12:00:00"
                ),
            )
        )

        second = (
            self.service
            .register_inbound_message(
                thread_id=thread.id,
                body_text="Hola",
                provider_message_id=(
                    "wa-in-idempotent-1"
                ),
                provider_timestamp=(
                    "2026-08-10T12:00:00"
                ),
            )
        )

        self.assertEqual(
            first.id,
            second.id,
        )

        messages = (
            self.service.repository
            .list_messages(
                thread.id
            )
        )

        self.assertEqual(
            len(messages),
            1,
        )

    def test_import_provider_messages_supports_both_directions(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600444444"
                ),
                phone=(
                    "+34 600 444 444"
                ),
            )
        )

        thread = result["thread"]

        inbound = (
            self.service
            .import_provider_message(
                thread_id=thread.id,
                direction=DIRECTION_INBOUND,
                body_text="Entrada",
                provider_message_id=(
                    "wa-import-in-1"
                ),
                provider_timestamp=(
                    "2026-08-12T10:00:00"
                ),
                status=(
                    MESSAGE_STATUS_RECEIVED
                ),
                metadata={
                    "message_type": "TEXT",
                },
            )
        )

        outbound = (
            self.service
            .import_provider_message(
                thread_id=thread.id,
                direction=DIRECTION_OUTBOUND,
                body_text="Salida",
                provider_message_id=(
                    "wa-import-out-1"
                ),
                provider_timestamp=(
                    "2026-08-12T10:01:00"
                ),
                status=(
                    MESSAGE_STATUS_DELIVERED
                ),
                metadata={
                    "message_type": "TEXT",
                },
            )
        )

        self.assertTrue(
            inbound["created"]
        )

        self.assertTrue(
            outbound["created"]
        )

        self.assertEqual(
            inbound["message"].status,
            MESSAGE_STATUS_RECEIVED,
        )

        self.assertEqual(
            outbound["message"].status,
            MESSAGE_STATUS_DELIVERED,
        )


    def test_import_provider_message_advances_status_idempotently(
        self,
    ):
        result = (
            self.service
            .get_or_create_whatsapp_thread(
                external_thread_key=(
                    "phone:34600555555"
                ),
                phone=(
                    "+34 600 555 555"
                ),
            )
        )

        thread = result["thread"]

        first = (
            self.service
            .import_provider_message(
                thread_id=thread.id,
                direction=DIRECTION_OUTBOUND,
                body_text="Mensaje",
                provider_message_id=(
                    "wa-progress-service-1"
                ),
                provider_timestamp=(
                    "2026-08-12T10:05:00"
                ),
                status=(
                    MESSAGE_STATUS_DELIVERED
                ),
            )
        )

        second = (
            self.service
            .import_provider_message(
                thread_id=thread.id,
                direction=DIRECTION_OUTBOUND,
                body_text="Mensaje",
                provider_message_id=(
                    "wa-progress-service-1"
                ),
                provider_timestamp=(
                    "2026-08-12T10:05:00"
                ),
                status=(
                    MESSAGE_STATUS_READ
                ),
            )
        )

        self.assertTrue(
            first["created"]
        )

        self.assertFalse(
            second["created"]
        )

        self.assertEqual(
            first["message"].id,
            second["message"].id,
        )

        self.assertEqual(
            second["message"].status,
            MESSAGE_STATUS_READ,
        )

        self.assertFalse(
            second["created"]
        )

        self.assertTrue(
            second["reused"]
        )

        self.assertTrue(
            second["status_advanced"]
        )

        messages = (
            self.service.repository
            .list_messages(
                thread.id
            )
        )

        self.assertEqual(
            len(messages),
            1,
        )

    def test_get_latest_thread_provider_message_id(
        self,
    ):
        repository = (
            SQLiteCommunicationRepository(
                self.db_path
            )
        )

        service = CommunicationService(
            repository=repository
        )

        account = (
            service
            .ensure_whatsapp_dev_account()
        )

        thread = (
            repository
            .get_or_create_thread(
                CommunicationThread(
                    id=None,
                    account_id=account.id,
                    client_id=None,
                    external_thread_key=(
                        "checkpoint-thread"
                    ),
                    external_address=(
                        "+34600888888"
                    ),
                    match_status=(
                        THREAD_MATCH_UNMATCHED
                    ),
                )
            )
        )

        service.import_provider_message(
            thread_id=thread.id,
            direction=DIRECTION_INBOUND,
            body_text="Anterior",
            provider_message_id=(
                "CHECKPOINT-OLD"
            ),
            provider_timestamp=(
                "2026-08-13T08:00:00"
            ),
            status=(
                MESSAGE_STATUS_RECEIVED
            ),
        )

        service.import_provider_message(
            thread_id=thread.id,
            direction=DIRECTION_INBOUND,
            body_text="Último",
            provider_message_id=(
                "CHECKPOINT-NEW"
            ),
            provider_timestamp=(
                "2026-08-13T09:00:00"
            ),
            status=(
                MESSAGE_STATUS_RECEIVED
            ),
        )

        self.assertEqual(
            service
            .get_latest_thread_provider_message_id(
                thread.id
            ),
            "CHECKPOINT-NEW",
        )


    def test_list_thread_messages_delegates_to_repository(
        self,
    ):
        repository = (
            SQLiteCommunicationRepository(
                db_path=self.db_path
            )
        )

        service = CommunicationService(
            repository=repository
        )

        account = (
            service
            .ensure_whatsapp_dev_account()
        )

        thread = (
            repository
            .get_or_create_thread(
                CommunicationThread(
                    id=None,
                    account_id=account.id,
                    client_id=None,
                    external_thread_key=(
                        "phone:34600000001"
                    ),
                    external_address=(
                        "+34600000001"
                    ),
                    external_display_name=(
                        "TEST"
                    ),
                    match_status=(
                        THREAD_MATCH_UNMATCHED
                    ),
                )
            )
        )

        service.import_provider_message(
            thread_id=thread.id,
            direction=DIRECTION_INBOUND,
            body_text="Mensaje test",
            provider_message_id=(
                "PROVIDER-MESSAGE-UI-1"
            ),
            provider_timestamp=(
                "2026-08-12T09:22:00"
            ),
            status=(
                MESSAGE_STATUS_RECEIVED
            ),
            metadata={
                "message_type": "TEXT",
            },
        )

        messages = (
            service
            .list_thread_messages(
                thread.id,
                limit=500,
            )
        )

        self.assertEqual(
            len(messages),
            1,
        )

        self.assertEqual(
            messages[0].body_text,
            "Mensaje test",
        )

        self.assertEqual(
            messages[0].provider_message_id,
            "PROVIDER-MESSAGE-UI-1",
        )



    def test_list_thread_messages_before_delegates_to_repository(
        self,
    ):
        repository = SQLiteCommunicationRepository(
            db_path=self.db_path
        )

        service = CommunicationService(
            repository=repository
        )

        account = (
            service
            .ensure_whatsapp_dev_account()
        )

        thread = repository.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key=(
                    "history-before-service"
                ),
                external_address=(
                    "+34600900123"
                ),
                match_status=(
                    THREAD_MATCH_UNMATCHED
                ),
            )
        )

        created = []

        for index in range(
            1,
            5,
        ):
            result = service.import_provider_message(
                thread_id=thread.id,
                direction=DIRECTION_INBOUND,
                body_text=(
                    f"Servicio {index}"
                ),
                provider_message_id=(
                    f"SERVICE-HISTORY-{index}"
                ),
                provider_timestamp=(
                    "2026-08-13T"
                    f"{index + 8:02d}:00:00"
                ),
                status=MESSAGE_STATUS_RECEIVED,
            )

            created.append(
                result[
                    "message"
                ]
            )

        previous = (
            service
            .list_thread_messages_before(
                thread.id,
                before_message_id=(
                    created[3].id
                ),
                limit=2,
            )
        )

        self.assertEqual(
            [
                message.body_text
                for message in previous
            ],
            [
                "Servicio 2",
                "Servicio 3",
            ],
        )


if __name__ == "__main__":
    unittest.main()
