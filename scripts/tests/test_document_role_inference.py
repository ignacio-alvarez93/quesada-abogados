import unittest

from backend.services import (
    document_role_inference_service as inference,
)


class DocumentRoleInferenceTest(unittest.TestCase):
    def test_explicit_role_has_priority(self):
        result = inference.infer_document_role(
            explicit_role="REAGRUPANTE",
            filename="pasaporte_reagrupado.pdf",
            path="REAGRUPADO",
        )

        self.assertEqual(
            result["rol_documental"],
            "REAGRUPANTE",
        )
        self.assertEqual(
            result["estado"],
            "EXPLICITO",
        )

    def test_role_from_filename(self):
        result = inference.infer_document_role(
            filename=(
                "PASAPORTE_REAGRUPANTE.pdf"
            ),
        )

        self.assertEqual(
            result["rol_documental"],
            "REAGRUPANTE",
        )
        self.assertEqual(
            result["estado"],
            "INFERIDO",
        )

    def test_role_from_path(self):
        result = inference.infer_document_role(
            filename="PASAPORTE.pdf",
            path=(
                "EXPEDIENTE/"
                "DOCUMENTOS_REAGRUPADO/"
                "PASAPORTE.pdf"
            ),
        )

        self.assertEqual(
            result["rol_documental"],
            "REAGRUPADO",
        )

    def test_role_from_nomenclature_pattern(self):
        result = inference.infer_document_role(
            filename="DOC001.pdf",
            nomenclature_pattern=(
                "PASAPORTE*REAGRUPANTE*"
            ),
        )

        self.assertEqual(
            result["rol_documental"],
            "REAGRUPANTE",
        )

    def test_generic_document_has_no_role(self):
        result = inference.infer_document_role(
            filename="PASAPORTE.pdf",
            path="EXPEDIENTE/IDENTIDAD",
        )

        self.assertIsNone(
            result["rol_documental"]
        )
        self.assertEqual(
            result["estado"],
            "SIN_EVIDENCIA",
        )

    def test_conflicting_filename_and_path_is_ambiguous(self):
        result = inference.infer_document_role(
            filename=(
                "PASAPORTE_REAGRUPANTE.pdf"
            ),
            path=(
                "EXPEDIENTE/"
                "DOCUMENTOS_REAGRUPADO/"
                "PASAPORTE_REAGRUPANTE.pdf"
            ),
        )

        self.assertIsNone(
            result["rol_documental"]
        )
        self.assertEqual(
            result["estado"],
            "AMBIGUO",
        )
        self.assertEqual(
            set(result["roles_candidatos"]),
            {
                "REAGRUPANTE",
                "REAGRUPADO",
            },
        )

    def test_accents_are_normalized(self):
        result = inference.infer_document_role(
            filename="PASAPORTE_CÓNYUGE.pdf",
        )

        self.assertEqual(
            result["rol_documental"],
            "CONYUGE",
        )

    def test_children_role_uses_canonical_plural_name(self):
        result = inference.infer_document_role(
            filename="ACTA_NACIMIENTO_HIJO_MENOR.pdf",
        )

        self.assertEqual(
            result["rol_documental"],
            "HIJOS_MENORES",
        )
        self.assertEqual(
            result["estado"],
            "INFERIDO",
        )

    def test_explicit_children_role_is_recognized(self):
        result = inference.infer_document_role(
            explicit_role="HIJOS_MENORES",
            filename="ACTA_NACIMIENTO.pdf",
        )

        self.assertEqual(
            result["rol_documental"],
            "HIJOS_MENORES",
        )
        self.assertEqual(
            result["estado"],
            "EXPLICITO",
        )

    def test_singular_children_alias_is_normalized(self):
        result = inference.infer_document_role(
            explicit_role="HIJO_MENOR",
        )

        self.assertEqual(
            result["rol_documental"],
            "HIJOS_MENORES",
        )


    def test_unknown_explicit_role_is_not_inferred(self):
        result = inference.infer_document_role(
            explicit_role="PERSONA_X",
            filename=(
                "PASAPORTE_REAGRUPANTE.pdf"
            ),
        )

        self.assertIsNone(
            result["rol_documental"]
        )
        self.assertEqual(
            result["estado"],
            "AMBIGUO",
        )


if __name__ == "__main__":
    unittest.main()
