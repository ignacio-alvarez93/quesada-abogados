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


class ExternalMilestonesEvolutionContractTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = VIEW.read_text(
            encoding="utf-8"
        )

        cls.tree = ast.parse(cls.source)

        cls.function_names = {
            node.name
            for node in ast.walk(cls.tree)
            if isinstance(
                node,
                ast.FunctionDef,
            )
        }

    def test_reads_creation_origin(self):
        self.assertIn(
            "get_expedient_creation_origin",
            self.source,
        )

    def test_reads_external_milestones(self):
        self.assertIn(
            "list_external_milestones",
            self.source,
        )

    def test_has_milestone_card_builder(self):
        self.assertIn(
            "_build_external_milestone_card",
            self.function_names,
        )

    def test_distinguishes_direction(self):
        self.assertIn(
            "_external_milestone_direction",
            self.function_names,
        )

        self.assertIn(
            "incoming_external_milestones",
            self.source,
        )

        self.assertIn(
            "outgoing_external_milestones",
            self.source,
        )

    def test_displays_creation_origin(self):
        self.assertIn(
            "Origen de apertura",
            self.source,
        )

        self.assertIn(
            "CREATION_ORIGIN_LABELS",
            self.source,
        )

    def test_displays_external_sections(self):
        self.assertIn(
            "incoming_external_cards",
            self.source,
        )

        self.assertIn(
            "outgoing_external_cards",
            self.source,
        )

        self.assertIn(
            "incoming_external_milestones",
            self.source,
        )

        self.assertIn(
            "outgoing_external_milestones",
            self.source,
        )

    def test_full_chain_includes_milestones(self):
        self.assertIn(
            "all_external_milestones",
            self.source,
        )

        self.assertIn(
            "rendered_milestone_ids",
            self.source,
        )

        self.assertIn(
            "pending_terminal_milestones",
            self.source,
        )

    def test_milestone_card_does_not_open_expedient(
        self,
    ):
        builder = next(
            node
            for node in ast.walk(self.tree)
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "_build_external_milestone_card"
            )
        )

        builder_source = ast.get_source_segment(
            self.source,
            builder,
        )

        self.assertNotIn(
            "_open_related_expedient",
            builder_source,
        )


if __name__ == "__main__":
    unittest.main()
