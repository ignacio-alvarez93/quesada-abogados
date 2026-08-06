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

    def test_distinguishes_milestone_direction(self):
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
            "CREATION_ORIGIN_LABELS",
            self.source,
        )

        self.assertIn(
            "_creation_origin_label",
            self.function_names,
        )

        self.assertIn(
            "creation_origin",
            self.source,
        )

    def test_builds_external_sections(self):
        for identifier in (
            "incoming_external_cards",
            "outgoing_external_cards",
            "incoming_external_milestones",
            "outgoing_external_milestones",
        ):
            self.assertIn(
                identifier,
                self.source,
            )

    def test_full_chain_includes_external_milestones(
        self,
    ):
        for identifier in (
            "all_external_milestones",
            "external_milestones",
            "rendered_milestone_ids",
            "pending_terminal_milestones",
        ):
            self.assertIn(
                identifier,
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


    def test_has_external_milestone_management_menu(
        self,
    ):
        self.assertIn(
            "_external_milestone_management_menu",
            self.function_names,
        )

        self.assertIn(
            "allow_management",
            self.source,
        )

    def test_has_external_milestone_edit_dialog(
        self,
    ):
        self.assertIn(
            "open_external_milestone_edit_dialog",
            self.function_names,
        )

        self.assertIn(
            "update_external_milestone",
            self.source,
        )

    def test_has_external_milestone_complete_dialog(
        self,
    ):
        self.assertIn(
            "open_external_milestone_complete_dialog",
            self.function_names,
        )

        self.assertIn(
            "complete_external_milestone",
            self.source,
        )

    def test_has_external_milestone_deactivation(
        self,
    ):
        self.assertIn(
            "confirm_deactivate_external_milestone",
            self.function_names,
        )

        self.assertIn(
            "deactivate_external_milestone",
            self.source,
        )

    def test_refreshes_expedient_after_change(
        self,
    ):
        self.assertIn(
            "_refresh_expedient_after_milestone_change",
            self.function_names,
        )

        self.assertIn(
            "build_expediente_dialog_content",
            self.source,
        )

    def test_management_is_enabled_in_evolution(
        self,
    ):
        self.assertGreaterEqual(
            self.source.count(
                "allow_management=True"
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
