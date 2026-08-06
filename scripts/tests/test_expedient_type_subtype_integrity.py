import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

from backend.services import config_service
from backend.services import expedient_family_service
from backend.services import expedient_service


class ExpedientTypeSubtypeIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "integrity.db"

        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                primer_apellido TEXT,
                segundo_apellido TEXT,
                nie TEXT,
                pasaporte TEXT,
                dni TEXT,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE config_tipos_expediente (
                id INTEGER PRIMARY KEY,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                activo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                url_presentacion TEXT,
                workflow_code TEXT,
                familia_id INTEGER
            );

            CREATE TABLE config_subtipos_expediente (
                id INTEGER PRIMARY KEY,
                tipo_expediente_id INTEGER NOT NULL,
                codigo TEXT NOT NULL,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE config_documentos_requeridos (
                id INTEGER PRIMARY KEY,
                tipo_expediente_id INTEGER NOT NULL,
                subtipo_expediente_id INTEGER,
                codigo_documento TEXT NOT NULL,
                nombre_documento TEXT NOT NULL,
                obligatorio INTEGER NOT NULL DEFAULT 1,
                orden INTEGER NOT NULL DEFAULT 0,
                activo INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE config_nomenclaturas_documentales (
                id INTEGER PRIMARY KEY,
                tipo_expediente_id INTEGER NOT NULL,
                subtipo_expediente_id INTEGER,
                documento_id INTEGER NOT NULL,
                patron_nombre TEXT NOT NULL,
                extension_permitida TEXT,
                activo INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE config_estados_documentales (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                color TEXT,
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE config_estados_administrativos (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                color TEXT,
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE config_prioridades (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                color TEXT,
                orden INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE expedientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                numero_expediente TEXT NOT NULL,
                numero_expediente_mercurio TEXT,
                numero_presentacion_registro TEXT,
                numero_expediente_extranjeria TEXT,
                tipo_expediente_id INTEGER,
                subtipo_expediente_id INTEGER,
                subtipo_expediente TEXT,
                estado_documental_id INTEGER,
                estado_administrativo_id INTEGER,
                estado_presentacion TEXT,
                prioridad_id INTEGER,
                responsable TEXT,
                fecha_apertura TEXT,
                fecha_presentacion TEXT,
                fecha_resolucion TEXT,
                numero_registro TEXT,
                organo_presentacion TEXT,
                provincia TEXT,
                observaciones TEXT,
                observaciones_internas TEXT,
                box_folder_path TEXT,
                activo INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO clientes (id, nombre, activo)
            VALUES (1, 'CLIENTE PRUEBA', 1);

            INSERT INTO config_tipos_expediente
                (id, codigo, nombre, activo, workflow_code)
            VALUES
                (10, 'TIPO_A', 'TIPO A', 1, 'EXTRANJERIA'),
                (20, 'TIPO_B', 'TIPO B', 1, 'EXTRANJERIA'),
                (30, 'TIPO_INACTIVO', 'TIPO INACTIVO', 0, 'EXTRANJERIA');

            INSERT INTO config_subtipos_expediente
                (id, tipo_expediente_id, codigo, nombre, activo)
            VALUES
                (100, 10, 'SUBTIPO_A1', 'SUBTIPO A1', 1),
                (101, 10, 'SUBTIPO_A2', 'SUBTIPO A2', 1),
                (200, 20, 'SUBTIPO_B1', 'SUBTIPO B1', 1),
                (201, 20, 'SUBTIPO_B_INACTIVO', 'SUBTIPO B INACTIVO', 0);

            INSERT INTO config_documentos_requeridos
                (
                    id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    codigo_documento,
                    nombre_documento,
                    activo
                )
            VALUES
                (1000, 10, NULL, 'DOC_GENERAL_A', 'DOCUMENTO GENERAL A', 1),
                (1001, 10, 100, 'DOC_A1', 'DOCUMENTO A1', 1),
                (2000, 20, 200, 'DOC_B1', 'DOCUMENTO B1', 1);
            """
        )
        conn.commit()
        conn.close()

        self.patches = [
            patch.object(config_service, "DB_PATH", self.db_path),
            patch.object(expedient_service, "DB_PATH", self.db_path),
            patch.object(expedient_family_service, "DB_PATH", self.db_path),
            patch.object(
                config_service,
                "_initialize_dynamic_forms_runtime_schema",
                lambda: None,
            ),
        ]

        for item in self.patches:
            item.start()

        @contextmanager
        def closed_connection():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        self.config_connect_patch = patch.object(
            config_service,
            "_connect",
            closed_connection,
        )
        self.expedient_connect_patch = patch.object(
            expedient_service,
            "_connect",
            closed_connection,
        )

        self.config_connect_patch.start()
        self.expedient_connect_patch.start()

    def tearDown(self):
        self.expedient_connect_patch.stop()
        self.config_connect_patch.stop()

        for item in reversed(self.patches):
            item.stop()

        self.temp_dir.cleanup()

    def _expedient_data(self, tipo_id=10, subtipo_id=100):
        return {
            "cliente_id": 1,
            "numero_expediente": "EXP-TEST-001",
            "tipo_expediente_id": tipo_id,
            "subtipo_expediente_id": subtipo_id,
            "subtipo_expediente": "TEXTO INCORRECTO",
            "estado_presentacion": "NO PRESENTADO",
            "activo": 1,
        }

    def test_expedient_rejects_missing_type(self):
        data = self._expedient_data(tipo_id=None, subtipo_id=None)

        with self.assertRaisesRegex(ValueError, "tipo de expediente"):
            expedient_service.create_expediente(data)

    def test_expedient_rejects_unknown_type(self):
        data = self._expedient_data(tipo_id=999, subtipo_id=None)

        with self.assertRaisesRegex(ValueError, "no existe"):
            expedient_service.create_expediente(data)

    def test_expedient_rejects_inactive_type(self):
        data = self._expedient_data(tipo_id=30, subtipo_id=None)

        with self.assertRaisesRegex(ValueError, "inactivo"):
            expedient_service.create_expediente(data)

    def test_expedient_rejects_subtype_from_other_type(self):
        data = self._expedient_data(tipo_id=10, subtipo_id=200)

        with self.assertRaisesRegex(ValueError, "no pertenece"):
            expedient_service.create_expediente(data)

    def test_expedient_rejects_inactive_subtype(self):
        data = self._expedient_data(tipo_id=20, subtipo_id=201)

        with self.assertRaisesRegex(ValueError, "inactivo"):
            expedient_service.create_expediente(data)

    def test_expedient_accepts_type_without_subtype(self):
        data = self._expedient_data(tipo_id=10, subtipo_id=None)
        data["subtipo_expediente"] = ""

        expediente_id = expedient_service.create_expediente(data)

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT tipo_expediente_id,
                       subtipo_expediente_id,
                       subtipo_expediente
                FROM expedientes
                WHERE id = ?
                """,
                (expediente_id,),
            ).fetchone()

        self.assertEqual(row[0], 10)
        self.assertIsNone(row[1])
        self.assertEqual(row[2], "")

    def test_expedient_synchronizes_legacy_subtype_text(self):
        expediente_id = expedient_service.create_expediente(
            self._expedient_data(tipo_id=10, subtipo_id=100)
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT subtipo_expediente_id, subtipo_expediente
                FROM expedientes
                WHERE id = ?
                """,
                (expediente_id,),
            ).fetchone()

        self.assertEqual(row[0], 100)
        self.assertEqual(row[1], "SUBTIPO A1")

    def test_create_with_external_connection_does_not_commit(self):
        data = self._expedient_data(
            tipo_id=10,
            subtipo_id=100,
        )
        data["numero_expediente"] = "EXP-TRANSACTION-001"

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        try:
            expediente_id = (
                expedient_service
                ._create_expediente_with_connection(
                    conn,
                    data,
                )
            )

            row_same_connection = conn.execute(
                """
                SELECT id
                FROM expedientes
                WHERE id = ?
                """,
                (expediente_id,),
            ).fetchone()

            self.assertIsNotNone(row_same_connection)

            conn.rollback()
        finally:
            conn.close()

        with closing(sqlite3.connect(self.db_path)) as check_conn:
            persisted = check_conn.execute(
                """
                SELECT id
                FROM expedientes
                WHERE numero_expediente =
                    'EXP-TRANSACTION-001'
                """
            ).fetchone()

        self.assertIsNone(persisted)

    def test_create_with_external_connection_can_commit(self):
        data = self._expedient_data(
            tipo_id=10,
            subtipo_id=100,
        )
        data["numero_expediente"] = "EXP-TRANSACTION-002"

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        try:
            expediente_id = (
                expedient_service
                ._create_expediente_with_connection(
                    conn,
                    data,
                )
            )
            conn.commit()
        finally:
            conn.close()

        with closing(sqlite3.connect(self.db_path)) as check_conn:
            persisted = check_conn.execute(
                """
                SELECT
                    id,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    subtipo_expediente
                FROM expedientes
                WHERE id = ?
                """,
                (expediente_id,),
            ).fetchone()

        self.assertIsNotNone(persisted)
        self.assertEqual(persisted[1], 10)
        self.assertEqual(persisted[2], 100)
        self.assertEqual(persisted[3], "SUBTIPO A1")

    def test_public_create_expediente_still_commits(self):
        data = self._expedient_data(
            tipo_id=10,
            subtipo_id=100,
        )
        data["numero_expediente"] = "EXP-PUBLIC-001"

        expediente_id = expedient_service.create_expediente(
            data
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT id
                FROM expedientes
                WHERE id = ?
                """,
                (expediente_id,),
            ).fetchone()

        self.assertIsNotNone(row)

    def test_required_document_rejects_subtype_from_other_type(self):
        with self.assertRaisesRegex(ValueError, "no pertenece"):
            config_service.create_documento_requerido(
                {
                    "tipo_expediente_id": 10,
                    "subtipo_expediente_id": 200,
                    "codigo_documento": "INVALIDO",
                    "nombre_documento": "DOCUMENTO INVÁLIDO",
                    "activo": 1,
                }
            )

    def test_nomenclature_rejects_document_from_other_type(self):
        with self.assertRaisesRegex(
            ValueError,
            "documento requerido no pertenece al tipo",
        ):
            config_service.create_nomenclatura(
                {
                    "tipo_expediente_id": 10,
                    "subtipo_expediente_id": 100,
                    "documento_id": 2000,
                    "patron_nombre": "DOCUMENTO_B",
                    "activo": 1,
                }
            )

    def test_nomenclature_rejects_specific_document_without_subtype(self):
        with self.assertRaisesRegex(
            ValueError,
            "no pertenece al subtipo",
        ):
            config_service.create_nomenclatura(
                {
                    "tipo_expediente_id": 10,
                    "subtipo_expediente_id": None,
                    "documento_id": 1001,
                    "patron_nombre": "DOCUMENTO_A1",
                    "activo": 1,
                }
            )

    def test_nomenclature_accepts_general_document_for_subtype(self):
        nomenclatura_id = config_service.create_nomenclatura(
            {
                "tipo_expediente_id": 10,
                "subtipo_expediente_id": 100,
                "documento_id": 1000,
                "patron_nombre": "GENERAL_A",
                "extension_permitida": "pdf",
                "activo": 1,
            }
        )

        rows = config_service.get_nomenclaturas(active_only=True)
        created = next(
            row for row in rows
            if int(row["id"]) == int(nomenclatura_id)
        )

        self.assertEqual(created["subtipo_expediente_id"], 100)
        self.assertEqual(
            created["subtipo_expediente_nombre"],
            "SUBTIPO A1",
        )

    def test_nomenclature_accepts_matching_specific_document(self):
        nomenclatura_id = config_service.create_nomenclatura(
            {
                "tipo_expediente_id": 10,
                "subtipo_expediente_id": 100,
                "documento_id": 1001,
                "patron_nombre": "ESPECIFICO_A1",
                "activo": 1,
            }
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT tipo_expediente_id,
                       subtipo_expediente_id,
                       documento_id
                FROM config_nomenclaturas_documentales
                WHERE id = ?
                """,
                (nomenclatura_id,),
            ).fetchone()

        self.assertEqual(row, (10, 100, 1001))

    def test_cannot_move_used_subtype_to_other_type(self):
        expedient_service.create_expediente(
            self._expedient_data(tipo_id=10, subtipo_id=100)
        )

        with self.assertRaisesRegex(
            ValueError,
            "tiene elementos vinculados",
        ):
            config_service.update_subtipo_expediente(
                100,
                {
                    "tipo_expediente_id": 20,
                    "codigo": "SUBTIPO_A1",
                    "nombre": "SUBTIPO A1",
                    "activo": 1,
                },
            )

    def test_can_move_unused_subtype_to_other_type(self):
        config_service.update_subtipo_expediente(
            101,
            {
                "tipo_expediente_id": 20,
                "codigo": "SUBTIPO_A2",
                "nombre": "SUBTIPO A2",
                "activo": 1,
            },
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT tipo_expediente_id
                FROM config_subtipos_expediente
                WHERE id = 101
                """
            ).fetchone()

        self.assertEqual(row[0], 20)


if __name__ == "__main__":
    unittest.main()
