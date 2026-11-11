"""WO-DV26-UI1: visual composition of "Vincular a expediente" (LinkForm).

Reuses the DV25-P3A fixtures (themselves on top of DV24): synthetic PDFs, a
synthetic SQLite CRM and a synthetic Box tree in a TemporaryDirectory, the
canonical ``link_inbox_item`` running against that file and every other
Bandeja/Box mutation patched to fail. ``guard()`` makes any filesystem write
outside the viewer's preview cache fail. The tests inspect the real Flet tree
of LinkForm: zones, cards, widths, the status strip, the actions and their
states; behaviour is the DV24/DV25 one.
"""
import ast
import unittest

import flet as ft

from backend.services import document_viewer_filing_plan_service as filing
from backend.services import document_viewer_link_service as link_service
from frontend.components import document_viewer_link_dialog as link_dialog
from frontend.components.document_viewer_link_dialog import LinkLayout, link_layout
from frontend.components.document_viewer_modal import open_document_viewer_modal, viewer_action_label
from scripts.tests import test_document_viewer_dv25_filing_plan as p3a

dv24 = p3a.dv24


def find(root, data):
    return next(c for c in dv24.walk(root) if isinstance(getattr(c, "data", None), str) and c.data == data)


def has(root, data):
    return any(isinstance(getattr(c, "data", None), str) and c.data == data for c in dv24.walk(root))


def contains(root, control):
    return any(c is control for c in dv24.walk(root))


def texts(root):
    return [c.value for c in dv24.walk(root) if isinstance(c, ft.Text)]


class LayoutBudgetTests(unittest.TestCase):
    def test_minimum_window_fits_with_two_zones(self):
        layout = link_layout(1200, 750)
        self.assertTrue(layout.wide)
        self.assertLessEqual(layout.width + 2 * LinkLayout.INSET_H, 1200)
        self.assertLessEqual(layout.height + LinkLayout.FOOTER + 2 * LinkLayout.INSET_V, 750)
        self.assertEqual(layout.left + LinkLayout.GAP + layout.right, layout.width - 2 * LinkLayout.PAD)
        # Client and expediente side by side inside the left card, the Box fields inside the right one.
        self.assertGreaterEqual(layout.pair, LinkLayout.MIN_FIELD)
        self.assertLessEqual(2 * layout.pair + 12, layout.left - LinkLayout.CARD)
        self.assertLessEqual(layout.box_field, layout.right - LinkLayout.CARD)

    def test_full_hd_is_capped_and_narrow_windows_stack(self):
        layout = link_layout(1920, 1080)
        self.assertEqual((layout.width, layout.height, layout.wide), (1240, 900, True))
        for width, height in ((1000, 700), (800, 600)):
            with self.subTest(size=(width, height)):
                layout = link_layout(width, height)
                self.assertFalse(layout.wide)
                self.assertLessEqual(layout.width + 2 * LinkLayout.INSET_H, width)
                self.assertLessEqual(layout.height + LinkLayout.FOOTER + 2 * LinkLayout.INSET_V, height)
                self.assertEqual(layout.left, layout.right)
                self.assertLessEqual(max(layout.pair * 2 + 12, layout.field), layout.left - LinkLayout.CARD)
                self.assertLessEqual(layout.box_field, layout.right - LinkLayout.CARD)


class LinkVisualTests(p3a.FilingBase):
    def open_at(self, dialog, size, command="Vincular a expediente"):
        # The viewer opens at its own size; LinkForm measures the window when it is created.
        self.page.width, self.page.height = size
        return self.open_form(dialog, command)

    def open_selected(self, ids, tiles):
        dialog = self.open_inbox(ids)
        self.button(dialog, "Comparador 4").on_click(None)
        for tile in tiles:
            self.check(dialog, tile, True)
        return dialog

    def assert_footer(self, form):
        cancel, archive, submit = form.dialog.actions
        self.assertIs(cancel, form.cancel_button)
        self.assertIs(archive, form.archive_button)
        self.assertIs(submit, form.submit_button)
        self.assertIsInstance(submit, ft.ElevatedButton)  # the only primary action
        self.assertIsInstance(cancel, ft.OutlinedButton)
        self.assertEqual(viewer_action_label(archive), "Vincular y archivar copia")
        self.assertTrue(archive.disabled)
        self.assertIsNone(archive.on_click)
        self.assertEqual(archive.tooltip, filing.ARCHIVE_PENDING)

    def test_single_form_composition_at_the_minimum_window(self):
        dialog = self.open_inbox([1, 2])
        with self.guard():
            form = self.open_at(dialog, (1200, 750))
            layout = link_layout(1200, 750)
            self.assertEqual(form.layout, layout)
            shell = form.dialog.content
            self.assertEqual((shell.data, shell.width, shell.height), ("link-shell", layout.width, layout.height))
            # DV24 semantic title, rendered by the navy header.
            self.assertEqual(form.dialog.title.value, "Vincular a expediente")
            header = find(form.dialog, "link-header")
            self.assertEqual(find(header, "link-title").value, "Vincular a expediente")
            self.assertIn(link_dialog.LOGICAL_ONLY, texts(header))
            self.assertIn("Documento activo", texts(header))

            # Two zones: documents and destination left, Box planning right; review and table below.
            body = find(form.dialog, "link-body")
            zones = body.controls[0]
            self.assertIsInstance(zones, ft.Row)
            left, right = zones.controls
            self.assertEqual((left.width, right.width), (layout.left, layout.right))
            self.assertEqual([c.data for c in left.controls], ["documents-card", "destination-card"])
            self.assertEqual([c.data for c in right.controls], ["box-card"])
            self.assertEqual([c.data for c in body.controls[1:]], ["review-card", "preview-card"])
            self.assertTrue(contains(left.controls[0], form.document_column))
            self.assertEqual([c.data for c in form.document_column.controls], ["inbox:1"])
            self.assertIn("Bandeja #1 · Sin expediente · Cliente #7", texts(form.document_column))
            self.assertIn("Vinculable", texts(form.document_column))
            selects = (form.client_select.control, form.expedient_select.control)
            self.assertTrue(any(isinstance(c, ft.Row) and len(c.controls) == 2
                                and all(a is b for a, b in zip(c.controls, selects))
                                for c in dv24.walk(left.controls[1])))
            self.assertEqual({form.client_select.width, form.expedient_select.width}, {layout.pair})
            review = find(form.dialog, "review-card")
            for control in (form.review_column, form.transfer, form.confirm):
                self.assertTrue(contains(review, control))
            self.assertTrue(contains(find(form.dialog, "preview-card"), form.filing_column))
            self.assertTrue(has(form.filing_column, "preview-empty"))

            # Status strip outside the scrolled body; actions in their DV25 order.
            bar = find(form.dialog, "link-status-bar")
            self.assertTrue(contains(bar, form.status))
            self.assertFalse(contains(body, form.status))
            self.assertTrue(has(bar, "archive-pending"))
            self.assert_footer(form)
            self.assertTrue(form.confirm.disabled and form.submit_button.disabled)
            form.close()
        self.link.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)

    def test_box_card_only_plans_and_the_table_keeps_the_preview(self):
        dialog = self.open_inbox([1, 2])
        with self.guard():
            form = self.open_at(dialog, (1200, 750))
            box = find(form.dialog, "box-card")
            self.assertIn(link_dialog.BOX_TITLE, texts(box))
            self.assertIn(link_dialog.BOX_BADGE, texts(box))
            self.assertIn(filing.PREVIEW_ONLY, texts(box))
            self.assertIn(link_dialog.BOX_NO_WRITES, texts(box))
            self.assertIn(link_dialog.CHOOSE_EXPEDIENT, texts(box))
            self.assertIsNone(form.folder_select)

            self.pick(form.expedient_select, 42)
            self.assertNotIn(link_dialog.CHOOSE_EXPEDIENT, texts(box))
            selects = [form.folder_select, *form.nomenclature_selects.values()]
            self.assertEqual(list(form.nomenclature_selects), ["inbox:1"])
            for select in selects:
                self.assertTrue(contains(box, select.control))
                self.assertEqual(select.width, form.layout.box_field)
                self.assertFalse(select.allow_free_text)  # catalog only, never a free path or name
            self.assertEqual(self.labels_of(form.folder_select), p3a.FOLDERS_42)

            self.choose(form.folder_select, filing.ROOT_LABEL)
            self.choose(form.nomenclature_selects["inbox:1"], "PASAPORTE · SOLICITANTE")
            self.assertFalse(has(form.filing_column, "preview-empty"))
            (row,) = form.filing_column.controls
            self.assertEqual(row.data, "filing-preview")
            self.assertEqual(row.scroll, ft.ScrollMode.AUTO)
            (table,) = row.controls
            self.assertEqual([column.label.value for column in table.columns], list(link_dialog.PREVIEW_COLUMNS))
            self.assertEqual(len(table.rows), len(form.preview))
            preview = form.preview[0]
            cells = [cell.content for cell in table.rows[0].cells]
            self.assertEqual([cell.value for cell in cells], [str(value or "—") for value in (
                preview.source_name, "#1", preview.nomenclature, preview.folder, preview.proposed_name,
                preview.message)])
            self.assertEqual((preview.proposed_name, preview.status), ("PASAPORTE SOLICITANTE.pdf", filing.PROPOSED))
            self.assertEqual(cells[-1].color, link_dialog.Q_SUCCESS)
            # Box choices never enable the link nor the archive.
            self.assertTrue(form.submit_button.disabled)
            self.assert_footer(form)
            form.cancel_button.on_click(None)
        self.link.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)

    def test_without_box_the_notice_is_real_and_no_selector_is_offered(self):
        self.set_box(42, str(self.root / "no-existe"))
        dialog = self.open_inbox([1, 2])
        with self.guard():
            form = self.open_at(dialog, (1200, 750))
            self.pick(form.expedient_select, 42)
            box = find(form.dialog, "box-card")
            self.assertIn(filing.NO_BOX, texts(box))
            self.assertEqual((form.folder_select, form.nomenclature_selects), (None, {}))
            self.assertFalse(any(isinstance(c, ft.Dropdown) for c in dv24.walk(box)))
            self.assertEqual(form.preview[0].status, filing.BLOCKED)
            table = form.filing_column.controls[0].controls[0]
            self.assertEqual(table.rows[0].cells[-1].content.color, link_dialog.Q_ERROR)
            form.close()
        self.assertFalse((self.root / "no-existe").exists())
        self.link.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)

    def test_batch_shows_every_document_and_selector_in_order(self):
        dialog = self.open_selected([1, 2, 5, 3], (0, 1, 2))
        with self.guard():
            form = self.open_at(dialog, (1200, 750), "Vincular seleccionados")
            self.assertEqual(form.dialog.title.value, "Vincular 3 documentos seleccionados")
            header = find(form.dialog, "link-header")
            self.assertEqual(find(header, "link-title").value, "Vincular 3 documentos seleccionados")
            self.assertIn("Lote · 3 documentos", texts(header))
            self.assertIn("Documentos a vincular (3)", texts(find(form.dialog, "documents-card")))
            self.assertEqual([c.data for c in form.document_column.controls], ["inbox:1", "inbox:2", "inbox:5"])
            for line in form.document_column.controls:
                name = next(c for c in dv24.walk(line) if isinstance(c, ft.Text))
                self.assertEqual(name.max_lines, 2)
            self.assertIn(link_service.BATCH_POLICY, texts(find(form.dialog, "review-card")))

            self.pick(form.expedient_select, 42)
            box = find(form.dialog, "box-card")
            order = [c for c in dv24.walk(box) if any(c is s.control for s in form.nomenclature_selects.values())]
            self.assertEqual(order, [form.nomenclature_selects[key].control for key in ("inbox:1", "inbox:2")])
            table = form.filing_column.controls[0].controls[0]
            self.assertEqual([table_row.cells[0].content.value for table_row in table.rows],
                             [row.source_name for row in form.preview])
            self.assertEqual([row.key for row in form.preview], ["inbox:1", "inbox:2", "inbox:5"])
            self.assertEqual(table.rows[2].cells[-1].content.color, link_dialog.Q_ERROR)
            self.assert_footer(form)
            form.cancel_button.on_click(None)
        self.link.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)

    def test_transfer_needs_its_own_confirmation_inside_the_review_card(self):
        dialog = self.open_selected([1, 4], (0, 1))
        with self.guard():
            form = self.open_at(dialog, (1200, 750), "Vincular seleccionados")
            review = find(form.dialog, "review-card")
            self.assertFalse(form.transfer.visible)
            self.pick(form.expedient_select, 42)
            self.assertTrue(form.transfer.visible)
            self.assertTrue(contains(review, form.transfer))
            self.assertEqual(form.review_column.controls[0].value, "Revisión")
            self.assertIn(link_service.TRANSFER, [c.data for c in form.review_column.controls[1:]])
            self.assertIn("Confirmo vincular 1 documento(s)", form.confirm.label)
            self.confirm(form)
            self.assertFalse(form.submit_button.disabled)
            # Authorising the transfer drops the previous confirmation.
            form.transfer.value = True
            form.transfer.on_change(None)
            self.assertFalse(form.confirm.value)
            self.assertTrue(form.submit_button.disabled)
            self.assertIn("Confirmo vincular 2 documento(s)", form.confirm.label)
            self.confirm(form)
            self.assertFalse(form.submit_button.disabled)
            form.cancel_button.on_click(None)
            self.assertIsNone(form.submit())
        self.link.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)

    def test_result_locks_inputs_and_keeps_the_status_visible(self):
        dialog = self.open_inbox([1, 2])
        with self.guard():
            form = self.open_at(dialog, (1200, 750))
            self.pick(form.expedient_select, 42)
            self.choose(form.folder_select, filing.ROOT_LABEL)
            # Changing the expediente resets the review and the confirmation.
            self.confirm(form)
            self.pick(form.expedient_select, 43)
            self.assertEqual((form.confirm.value, form.submit_button.disabled), (False, True))
            self.pick(form.expedient_select, 42)
            self.confirm(form)
            form.submit_button.on_click(None)
            form.submit_button.on_click(None)  # double click
            self.link.assert_called_once_with(1, client_id=7, expedient_id=42)
            self.assertEqual(form.review_column.controls[0].value, "Resultado")
            self.assertTrue(contains(find(form.dialog, "review-card"), form.review_column))
            self.assertFalse(form.submit_button.visible)
            self.assertTrue(form.confirm.disabled and form.transfer.disabled)
            for select in (form.client_select, form.expedient_select, form.folder_select,
                           *form.nomenclature_selects.values()):
                self.assertTrue(select.input.disabled)
            self.assertEqual(viewer_action_label(form.cancel_button), "Cerrar")
            self.assertEqual(form.status.color, link_dialog.Q_SUCCESS)
            self.assertTrue(contains(find(form.dialog, "link-status-bar"), form.status))
            self.assert_footer(form)
            self.on_linked.assert_called_once()
            form.close()
        self.assertEqual(self.row(1)["expedient_id"], 42)
        self.assertIsNone(self.row(1)["copied_to_box_path"])
        self.button(dialog, "Cerrar").on_click(None)

    def test_narrow_window_stacks_the_zones(self):
        dialog = self.open_inbox([1, 2])
        with self.guard():
            form = self.open_at(dialog, (1000, 700))
            zones = find(form.dialog, "link-zones")
            self.assertIsInstance(zones, ft.Column)
            self.assertEqual([c.data for c in zones.controls], ["documents-card", "destination-card", "box-card"])
            self.assertFalse(form.layout.wide)
            self.assertLessEqual(form.client_select.width * 2 + 12, form.layout.left - LinkLayout.CARD)
            self.pick(form.expedient_select, 42)
            self.assertLessEqual(form.folder_select.width, form.layout.right - LinkLayout.CARD)
            form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_nothing_linkable_is_a_compact_form_without_destination(self):
        queue = [{"path": str(path), "name": path.name} for path in self.exp_docs]
        dialog = open_document_viewer_modal(self.page, queue[0]["path"], expediente_id=42, queue=queue,
                                            near_window=0, linking=self.linking())
        with self.guard():
            form = self.open_at(dialog, (1200, 750))
            self.assertEqual(form.status.value, link_service.NOT_LINKABLE_MESSAGE)
            self.assertTrue(contains(find(form.dialog, "link-status-bar"), form.status))
            self.assertTrue(has(form.dialog, "documents-card"))
            for data in ("destination-card", "box-card", "review-card", "preview-card"):
                self.assertFalse(has(form.dialog, data), data)
            self.assertFalse(contains(form.dialog, form.filing_column))
            self.assertLess(form.dialog.content.height, form.layout.height)
            self.assertFalse(form.submit_button.visible)
            self.assertEqual(viewer_action_label(form.cancel_button), "Cerrar")
            self.assert_footer(form)
            form.cancel_button.on_click(None)
        self.link.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)


class ScopeTests(unittest.TestCase):
    def test_the_refactor_adds_no_operation(self):
        source = dv24.DIALOG.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assignments = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    assignments.setdefault(ast.unparse(target), []).append(ast.unparse(node.value))
        # The archive action of LinkForm never gets a handler nor becomes enabled.
        self.assertNotIn("self.archive_button.on_click", assignments)
        self.assertEqual(assignments["self.archive_button.disabled"], ["True"])
        self.assertEqual(source.count("link_service.execute_link("), 1)
        self.assertNotIn("EXECUTION_ENABLED", source)
        self.assertNotIn("allow_free_text=True", source)


if __name__ == "__main__":
    unittest.main()
