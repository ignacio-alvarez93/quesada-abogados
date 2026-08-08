import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    calendar_alert_service,
    calendar_tracking_producer_service,
    expedient_traceability_service,
    notification_tracking_service,
)


ROOT = Path(__file__).resolve().parents[2]

TRACEABILITY_SCHEMA = (
    ROOT
    / "database"
    / "expedient_traceability_schema.sql"
)


class TraceabilityCalendarIntegrationTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "traceability_calendar.db"
        )

        self._create_base_database()

        self.patches = [
            patch.object(
                expedient_traceability_service,
                "DB_PATH",
                self.db_path,
            ),
            patch.object(
                notification_tracking_service,
                "DB_PATH",
                self.db_path,
            ),
            patch.object(
                expedient_traceability_service,
                "_evaluate_derivations_after_admin_event",
                return_value={
                    "ok": True,
                    "rules_evaluated": 0,
                    "proposals": [],
                },
            ),
            patch(
                (
                    "backend.services."
                    "presentation_queue_service."
                    "mark_presented_by_expediente"
                ),
                return_value={
                    "ok": True,
                    "changed": False,
                    "reason": "TEST",
                },
            ),
        ]

        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(
            self.patches
        ):
            item.stop()

        self.temp_dir.cleanup()

    def _connect(self):
        conn = sqlite3.connect(
            self.db_path
        )

        conn.row_factory = (
            sqlite3.Row
        )

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        return conn

    def _create_base_database(self):
        with closing(
            sqlite3.connect(
                self.db_path
            )
        ) as conn:
            conn.row_factory = (
                sqlite3.Row
            )

            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

            conn.executescript(
                """
                CREATE TABLE clientes (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT,
                    primer_apellido TEXT,
                    segundo_apellido TEXT,
                    nie TEXT,
                    dni TEXT,
                    pasaporte TEXT,
                    activo INTEGER
                        DEFAULT 1,
                    created_at TEXT
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                        DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE
                config_familias_expediente (
                    id INTEGER
                        PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT
                        NOT NULL UNIQUE,
                    nombre TEXT
                        NOT NULL,
                    descripcion TEXT,
                    notification_workflow_code TEXT
                        NOT NULL
                        DEFAULT
                        'RESOLUCION_DIRECTA',
                    orden INTEGER
                        NOT NULL DEFAULT 0,
                    activo INTEGER
                        NOT NULL DEFAULT 1,
                    created_at TEXT
                        NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                        NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE
                config_tipos_expediente (
                    id INTEGER
                        PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT
                        NOT NULL UNIQUE,
                    nombre TEXT
                        NOT NULL,
                    descripcion TEXT,
                    activo INTEGER
                        NOT NULL DEFAULT 1,
                    created_at TEXT
                        NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                        NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    url_presentacion TEXT,
                    workflow_code TEXT,
                    familia_id INTEGER,
                    FOREIGN KEY (
                        familia_id
                    )
                    REFERENCES
                        config_familias_expediente(
                            id
                        )
                );

                CREATE TABLE
                config_subtipos_expediente (
                    id INTEGER
                        PRIMARY KEY AUTOINCREMENT,
                    tipo_expediente_id INTEGER
                        NOT NULL,
                    codigo TEXT
                        NOT NULL UNIQUE,
                    nombre TEXT
                        NOT NULL,
                    descripcion TEXT,
                    orden INTEGER
                        DEFAULT 0,
                    activo INTEGER
                        DEFAULT 1,
                    created_at TEXT
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                        DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (
                        tipo_expediente_id
                    )
                    REFERENCES
                        config_tipos_expediente(
                            id
                        )
                );

                CREATE TABLE
                config_tipos_autorizacion (
                    id INTEGER
                        PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT
                        NOT NULL UNIQUE,
                    nombre TEXT
                        NOT NULL,
                    categoria TEXT
                        DEFAULT
                        'RESIDENCIA_TEMPORAL',
                    activo INTEGER
                        NOT NULL DEFAULT 1,
                    familia_codigo TEXT
                        DEFAULT 'EXTRANJERIA'
                );

                CREATE TABLE
                config_estados_documentales (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT UNIQUE,
                    nombre TEXT,
                    color TEXT,
                    orden INTEGER
                        DEFAULT 0,
                    activo INTEGER
                        DEFAULT 1
                );

                CREATE TABLE
                config_estados_administrativos (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT UNIQUE,
                    nombre TEXT,
                    color TEXT,
                    orden INTEGER
                        DEFAULT 0,
                    activo INTEGER
                        DEFAULT 1
                );

                CREATE TABLE
                config_prioridades (
                    id INTEGER PRIMARY KEY,
                    nombre TEXT,
                    color TEXT,
                    orden INTEGER
                        DEFAULT 0,
                    activo INTEGER
                        DEFAULT 1
                );

                CREATE TABLE expedientes (
                    id INTEGER
                        PRIMARY KEY AUTOINCREMENT,
                    cliente_id INTEGER
                        NOT NULL,

                    numero_expediente TEXT
                        NOT NULL,

                    numero_expediente_mercurio TEXT,
                    numero_presentacion_registro TEXT,
                    numero_expediente_extranjeria TEXT,
                    numero_registro_regage TEXT,
                    registro_csv_geiser TEXT,

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

                    activo INTEGER
                        DEFAULT 1,

                    created_at TEXT
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT
                        DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (
                        cliente_id
                    )
                    REFERENCES clientes(id),

                    FOREIGN KEY (
                        tipo_expediente_id
                    )
                    REFERENCES
                        config_tipos_expediente(
                            id
                        ),

                    FOREIGN KEY (
                        subtipo_expediente_id
                    )
                    REFERENCES
                        config_subtipos_expediente(
                            id
                        )
                );

                INSERT INTO clientes (
                    id,
                    nombre,
                    primer_apellido,
                    activo
                )
                VALUES (
                    1,
                    'CLIENTE',
                    'PRUEBA',
                    1
                );

                INSERT INTO
                config_familias_expediente (
                    id,
                    codigo,
                    nombre,
                    notification_workflow_code,
                    orden,
                    activo
                )
                VALUES (
                    1,
                    'EXTRANJERIA',
                    'EXTRANJERÍA',
                    'EXTRANJERIA_STANDARD',
                    10,
                    1
                );

                INSERT INTO
                config_tipos_expediente (
                    id,
                    codigo,
                    nombre,
                    activo,
                    workflow_code,
                    familia_id
                )
                VALUES (
                    14,
                    'REAGRUPACION_FAMILIAR',
                    'REAGRUPACIÓN FAMILIAR',
                    1,
                    'EXTRANJERIA',
                    1
                );

                INSERT INTO
                config_subtipos_expediente (
                    id,
                    tipo_expediente_id,
                    codigo,
                    nombre,
                    activo
                )
                VALUES (
                    8,
                    14,
                    'INICIAL',
                    'INICIAL',
                    1
                );

                INSERT INTO
                config_estados_documentales (
                    id,
                    codigo,
                    nombre,
                    activo
                )
                VALUES (
                    1,
                    'PENDIENTE_DOCUMENTACION',
                    'PENDIENTE DE DOCUMENTACIÓN',
                    1
                );

                INSERT INTO
                config_estados_administrativos (
                    id,
                    codigo,
                    nombre,
                    orden,
                    activo
                )
                VALUES
                    (
                        1,
                        'NO_PRESENTADO',
                        'NO PRESENTADO',
                        10,
                        1
                    ),
                    (
                        2,
                        'PRESENTADO',
                        'PRESENTADO',
                        20,
                        1
                    );

                INSERT INTO
                config_prioridades (
                    id,
                    nombre,
                    activo
                )
                VALUES (
                    1,
                    'NORMAL',
                    1
                );

                INSERT INTO expedientes (
                    id,
                    cliente_id,
                    numero_expediente,
                    tipo_expediente_id,
                    subtipo_expediente_id,
                    subtipo_expediente,
                    estado_documental_id,
                    estado_administrativo_id,
                    estado_presentacion,
                    prioridad_id,
                    responsable,
                    fecha_apertura,
                    provincia,
                    activo
                )
                VALUES (
                    1000,
                    1,
                    'EXP-2026-1000',
                    14,
                    8,
                    'INICIAL',
                    1,
                    1,
                    'NO PRESENTADO',
                    1,
                    'NACHO',
                    '2026-08-08',
                    'ASTURIAS',
                    1
                );
                """
            )

            conn.executescript(
                TRACEABILITY_SCHEMA
                .read_text(
                    encoding="utf-8"
                )
            )

            conn.commit()

    def _all_alerts(self):
        return (
            calendar_alert_service
            .list_alerts(
                expediente_id=1000,
                include_archived=True,
                db_path=self.db_path,
            )
        )

    def test_presentation_tracking_calendar_lifecycle(
        self,
    ):
        # -------------------------------------------------
        # 1. PRESENTACIÓN REAL DESDE TRAZABILIDAD
        # -------------------------------------------------

        presentation = (
            expedient_traceability_service
            .create_admin_document_event(
                {
                    "expediente_id": 1000,
                    "file_name": (
                        "justificante_"
                        "presentacion_test.pdf"
                    ),
                    "event_code": (
                        "JUSTIFICANTE_PRESENTACION"
                    ),
                    "usuario": "TEST",
                }
            )
        )

        self.assertTrue(
            presentation[
                "notification_tracking"
            ]["ok"]
        )

        self.assertEqual(
            presentation[
                "notification_tracking"
            ]["estado_nuevo"],
            (
                notification_tracking_service
                .ESTADO_ESPERA_NUMERO
            ),
        )

        self.assertEqual(
            presentation[
                "notification_tracking"
            ]["activo"],
            1,
        )

        self.assertTrue(
            presentation[
                "calendar_tracking"
            ]["ok"]
        )

        self.assertEqual(
            presentation[
                "calendar_tracking"
            ]["action"],
            "CREATED",
        )

        justificante_id = (
            presentation[
                "justificante_id"
            ]
        )

        alerts = self._all_alerts()

        self.assertEqual(
            len(alerts),
            1,
        )

        created_alert = alerts[0]

        alert_id = (
            created_alert["id"]
        )

        source_key = (
            "NOTIFICATION_TRACKING:"
            "EXP:1000"
        )

        self.assertEqual(
            created_alert["titulo"],
            "En espera de notificación",
        )

        self.assertEqual(
            created_alert[
                "descripcion"
            ],
            (
                "Esperando número "
                "de expediente."
            ),
        )

        self.assertEqual(
            created_alert[
                "estado"
            ],
            "ACTIVO",
        )

        self.assertEqual(
            created_alert[
                "origen_tipo"
            ],
            "TRAZABILIDAD",
        )

        self.assertEqual(
            created_alert[
                "source_key"
            ],
            source_key,
        )

        # Comprobación adicional:
        # la transición administrativa
        # también ocurrió realmente.
        with closing(
            self._connect()
        ) as conn:
            expediente = (
                conn.execute(
                    """
                    SELECT
                        e.estado_presentacion,
                        a.nombre
                            AS estado_nombre
                    FROM expedientes e
                    LEFT JOIN
                        config_estados_administrativos a
                      ON a.id =
                         e.estado_administrativo_id
                    WHERE e.id = 1000
                    """
                ).fetchone()
            )

        self.assertEqual(
            expediente[
                "estado_presentacion"
            ],
            "PRESENTADO",
        )

        self.assertEqual(
            expediente[
                "estado_nombre"
            ],
            "PRESENTADO",
        )

        # -------------------------------------------------
        # 2. REPROCESADO REAL / IDEMPOTENCIA
        # -------------------------------------------------

        tracking_again = (
            notification_tracking_service
            .reconcile_expedient(
                1000,
                source="TEST_REPROCESS",
                usuario="TEST",
            )
        )

        projection_again = (
            calendar_tracking_producer_service
            .sync_from_tracking_result(
                tracking_again,
                db_path=self.db_path,
            )
        )

        self.assertTrue(
            tracking_again["ok"]
        )

        self.assertFalse(
            tracking_again["changed"]
        )

        self.assertEqual(
            projection_again["action"],
            "UNCHANGED",
        )

        alerts = self._all_alerts()

        self.assertEqual(
            len(alerts),
            1,
        )

        self.assertEqual(
            alerts[0]["id"],
            alert_id,
        )

        self.assertEqual(
            alerts[0][
                "source_key"
            ],
            source_key,
        )

        # -------------------------------------------------
        # 3. ARCHIVADO REAL DESDE TRAZABILIDAD
        # -------------------------------------------------

        archived = (
            expedient_traceability_service
            .archive_admin_document(
                justificante_id
            )
        )

        self.assertTrue(
            archived["ok"]
        )

        self.assertTrue(
            archived[
                "notification_tracking"
            ]["ok"]
        )

        self.assertEqual(
            archived[
                "notification_tracking"
            ]["estado_nuevo"],
            (
                notification_tracking_service
                .ESTADO_CANCELADO_SIN_PRESENTACION
            ),
        )

        self.assertEqual(
            archived[
                "notification_tracking"
            ]["activo"],
            0,
        )

        self.assertTrue(
            archived[
                "calendar_tracking"
            ]["ok"]
        )

        self.assertEqual(
            archived[
                "calendar_tracking"
            ]["action"],
            "CANCELLED",
        )

        alerts = self._all_alerts()

        self.assertEqual(
            len(alerts),
            1,
        )

        cancelled_alert = (
            alerts[0]
        )

        self.assertEqual(
            cancelled_alert["id"],
            alert_id,
        )

        self.assertEqual(
            cancelled_alert[
                "source_key"
            ],
            source_key,
        )

        self.assertEqual(
            cancelled_alert[
                "estado"
            ],
            "CANCELADO",
        )

        with closing(
            self._connect()
        ) as conn:
            expediente = (
                conn.execute(
                    """
                    SELECT
                        e.estado_presentacion,
                        a.nombre
                            AS estado_nombre
                    FROM expedientes e
                    LEFT JOIN
                        config_estados_administrativos a
                      ON a.id =
                         e.estado_administrativo_id
                    WHERE e.id = 1000
                    """
                ).fetchone()
            )

        self.assertEqual(
            expediente[
                "estado_presentacion"
            ],
            "NO PRESENTADO",
        )

        self.assertEqual(
            expediente[
                "estado_nombre"
            ],
            "NO PRESENTADO",
        )


if __name__ == "__main__":
    unittest.main()
