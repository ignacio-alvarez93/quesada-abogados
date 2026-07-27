import unittest
from pathlib import Path

from backend.services import justificante_presentacion_extraction_service as extractor


ROOT = Path(__file__).resolve().parents[2]
DOWNLOADS = Path.home() / "Downloads"


def _resolve_pdf(local_name, download_pattern):
    local_path = ROOT / "tmp_test_assets" / local_name

    if local_path.exists():
        return local_path

    candidates = sorted(
        DOWNLOADS.glob(download_pattern)
    )

    if candidates:
        return candidates[0]

    return local_path


PDF_21 = _resolve_pdf(
    "justificante_21072026.pdf",
    "justificante_23010047L_21072026045905*.pdf",
)

PDF_17 = _resolve_pdf(
    "justificante_17072026.pdf",
    "justificante_23010047L_17072026075943*.pdf",
)


class JustificantePresentacionExtractionTest(unittest.TestCase):
    def test_extract_21_july_receipt(self):
        result = extractor.extract_justificante_presentacion(PDF_21)

        self.assertEqual(result["format"], "GEISER_REGAGE")
        self.assertEqual(
            result["numero_presentacion_registro"],
            "I33202604692498",
        )
        self.assertEqual(
            result["numero_registro_regage"],
            "REGAGE26e00067195547",
        )
        self.assertEqual(
            result["fecha_hora_presentacion"],
            "2026-07-21 16:59:03",
        )
        self.assertEqual(
            result["fecha_hora_registro"],
            "2026-07-21 16:59:05",
        )
        self.assertEqual(
            result["oficina_registro_codigo"],
            "O00001605",
        )
        self.assertEqual(
            result["unidad_tramitacion_codigo"],
            "EA0040281",
        )
        self.assertEqual(
            result["registro_ambito_prefijo"],
            "GEISER",
        )
        self.assertEqual(
            result["registro_csv_geiser"],
            "GEISER-efc6-814c-c393-4ca4-87ac-fd5a-de22-c3ab",
        )
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["confidence"], 1.0)

    def test_extract_17_july_receipt(self):
        result = extractor.extract_justificante_presentacion(PDF_17)

        self.assertEqual(
            result["numero_presentacion_registro"],
            "I33202604679301",
        )
        self.assertEqual(
            result["numero_registro_regage"],
            "REGAGE26e00066168051",
        )
        self.assertEqual(
            result["fecha_hora_presentacion"],
            "2026-07-17 07:59:42",
        )
        self.assertEqual(
            result["fecha_hora_registro"],
            "2026-07-17 07:59:43",
        )
        self.assertEqual(
            result["registro_csv_geiser"],
            "GEISER-c6ef-9860-7978-4a85-b42a-e67b-eee5-8bdb",
        )
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["confidence"], 1.0)

    def test_reject_non_pdf(self):
        with self.assertRaisesRegex(ValueError, "PDF"):
            extractor.extract_justificante_presentacion(
                ROOT / "README.md"
            )


if __name__ == "__main__":
    unittest.main()
