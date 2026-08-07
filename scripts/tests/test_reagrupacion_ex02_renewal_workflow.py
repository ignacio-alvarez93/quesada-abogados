import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.services import (
    expedient_consistency_service as consistency,
)
from backend.services import (
    presentation_config_service,
)


class ReagrupacionEX02RenewalWorkflowTests(
    unittest.TestCase
):
    def test_initial_ex02_options_do_not_include_renewal(self):
        contract = (
            consistency
            .get_reagrupacion_request_options(
                "INICIAL"
            )
        )

        self.assertFalse(
            contract["locked"]
        )

        self.assertIn(
            consistency.REAGRUPACION_REQUEST_INITIAL,
            contract["options"],
        )

        self.assertIn(
            consistency
            .REAGRUPACION_REQUEST_INITIAL_LONG_TERM_EU,
            contract["options"],
        )

        self.assertNotIn(
            consistency.REAGRUPACION_REQUEST_RENEWAL,
            contract["options"],
        )

    def test_renewal_ex02_has_only_renewal(self):
        contract = (
            consistency
            .get_reagrupacion_request_options(
                "RENOVACION"
            )
        )

        self.assertTrue(
            contract["locked"]
        )

        self.assertEqual(
            contract["options"],
            [
                consistency
                .REAGRUPACION_REQUEST_RENEWAL
            ],
        )

        self.assertEqual(
            contract["default"],
            consistency
            .REAGRUPACION_REQUEST_RENEWAL,
        )

    def test_renewal_normalizes_old_initial_value(self):
        value = (
            consistency
            .normalize_reagrupacion_request_for_subtype(
                "RENOVACION",
                consistency.REAGRUPACION_REQUEST_INITIAL,
            )
        )

        self.assertEqual(
            value,
            consistency.REAGRUPACION_REQUEST_RENEWAL,
        )

    def test_initial_preserves_long_term_eu_variant(self):
        value = (
            consistency
            .normalize_reagrupacion_request_for_subtype(
                "INICIAL",
                consistency
                .REAGRUPACION_REQUEST_INITIAL_LONG_TERM_EU,
            )
        )

        self.assertEqual(
            value,
            consistency
            .REAGRUPACION_REQUEST_INITIAL_LONG_TERM_EU,
        )

    def test_presentation_seed_creates_initial_and_renewal(self):
        original_db = presentation_config_service.DB_PATH

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "presentation.db"

            conn = sqlite3.connect(db)

            conn.executescript(
                """
                CREATE TABLE config_tipos_expediente (
                    id INTEGER PRIMARY KEY,
                    codigo TEXT NOT NULL,
                    nombre TEXT NOT NULL
                );

                CREATE TABLE config_subtipos_expediente (
                    id INTEGER PRIMARY KEY,
                    tipo_expediente_id INTEGER NOT NULL,
                    codigo TEXT NOT NULL,
                    nombre TEXT NOT NULL
                );

                CREATE TABLE config_presentaciones_asistidas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo_expediente_id INTEGER NOT NULL,
                    subtipo_expediente_id INTEGER,
                    nombre_configuracion TEXT,
                    url_presentacion TEXT,
                    portal TEXT,
                    flujo TEXT,
                    selectores_json TEXT,
                    reglas_json TEXT,
                    documentos_json TEXT,
                    activo INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                INSERT INTO config_tipos_expediente (
                    id,
                    codigo,
                    nombre
                )
                VALUES (
                    14,
                    'REAGRUPACION_FAMILIAR',
                    'REAGRUPACIÓN FAMILIAR'
                );

                INSERT INTO config_subtipos_expediente (
                    id,
                    tipo_expediente_id,
                    codigo,
                    nombre
                )
                VALUES
                    (
                        8,
                        14,
                        'INICIAL',
                        'INICIAL'
                    ),
                    (
                        10,
                        14,
                        'RENOVACION',
                        'RENOVACIÓN'
                    );
                """
            )

            conn.commit()
            conn.close()

            try:
                presentation_config_service.DB_PATH = db

                presentation_config_service\
                    .seed_presentaciones_asistidas_defaults()

                conn = sqlite3.connect(db)
                conn.row_factory = sqlite3.Row

                rows = conn.execute(
                    """
                    SELECT
                        s.codigo AS subtipo_codigo,
                        p.reglas_json
                    FROM config_presentaciones_asistidas p
                    JOIN config_subtipos_expediente s
                      ON s.id = p.subtipo_expediente_id
                    WHERE p.tipo_expediente_id = 14
                      AND p.activo = 1
                    ORDER BY s.id
                    """
                ).fetchall()

                conn.close()

            finally:
                presentation_config_service.DB_PATH = (
                    original_db
                )

        self.assertEqual(
            {
                row["subtipo_codigo"]
                for row in rows
            },
            {
                "INICIAL",
                "RENOVACION",
            },
        )

        for row in rows:
            rules = json.loads(
                row["reglas_json"]
            )

            self.assertEqual(
                rules["tipo_formulario_objetivo"],
                "EX02",
            )

            self.assertEqual(
                rules["mapper_codigo"],
                "MERCURIO_EX02",
            )

    def test_real_mapper_contains_renewal_checkbox_contract(self):
        db = Path("database/quesada.db")

        conn = sqlite3.connect(
            f"file:{db}?mode=ro",
            uri=True,
        )
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT mapper_json
            FROM form_mapper_templates
            WHERE codigo = 'EX02'
              AND activo = 1
            ORDER BY version DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

        conn.close()

        self.assertIsNotNone(row)

        mapper = json.loads(
            row["mapper_json"]
        )

        self.assertEqual(
            mapper.get(
                "Casilla de verificación113"
            ),
            (
                "__equals__:"
                "datos_especificos.tipo_de_solicitud:"
                "REAGRUPACIÓN FAMILIAR RENOVACIÓN"
            ),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
