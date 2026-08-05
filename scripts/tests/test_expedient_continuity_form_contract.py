import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

VIEW = (
    ROOT
    / "frontend"
    / "views"
    / "expedients_view.py"
)


class ExpedientContinuityFormContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = VIEW.read_text(
            encoding="utf-8"
        )

        cls.tree = ast.parse(cls.source)

    def test_imports_trajectory_service(self):
        self.assertIn(
            (
                "from backend.services import "
                "expedient_trajectory_service"
            ),
            self.source,
        )

    def test_contains_three_continuity_modes(self):
        for mode in [
            "INDEPENDENT",
            "DIRECT_RELATION",
            "EXTERNAL_MILESTONE",
        ]:
            self.assertIn(mode, self.source)

    def test_builds_continuity_payload(self):
        function_names = {
            node.name
            for node in ast.walk(self.tree)
            if isinstance(
                node,
                ast.FunctionDef,
            )
        }

        self.assertIn(
            "continuity_data",
            function_names,
        )

        self.assertIn(
            "validate_continuity",
            function_names,
        )

    def test_uses_transactional_creation(self):
        self.assertIn(
            (
                "create_expedient_with_continuity"
            ),
            self.source,
        )

    def test_keeps_existing_update_path(self):
        self.assertIn(
            "expedient_service.update_expediente",
            self.source,
        )

    def test_filters_previous_expedients_by_client(
        self,
    ):
        self.assertIn(
            (
                "expedient_service.get_expedientes("
            ),
            self.source,
        )

        self.assertIn(
            "cliente_id=client_id",
            self.source,
        )

    def test_hides_continuity_during_edit(self):
        self.assertIn(
            (
                "is_new = not bool("
                "state.get(\"editing_id\")"
            ),
            self.source,
        )

        self.assertIn(
            "continuity_form_wrapper.visible = is_new",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
