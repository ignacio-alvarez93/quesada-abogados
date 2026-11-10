"""WO-DV25-P1: the viewer queue holds only the documents marked by the user.

Diagnosis: every DV24 entry point passed the whole listing (expediente
folder, documents dialog, Bandeja page or group) as the viewer queue, so
"Previsualizar" on one file queued the entire directory. Now "Previsualizar"
opens one document and "Ver seleccionados" opens a snapshot of the visible
marked documents.

Synthetic PDFs (DV24 fixtures) and Flet fakes only: no database, no Box, no
real documents. PDF tool handlers are mocks; no PDF operation runs.
"""
import ast
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import flet as ft

from backend.services import document_viewer_service as service
from backend.services.document_tools import document_inbox_tools_service as inbox_tools
from frontend.components import document_viewer_multidoc as multidoc
from frontend.components.app_button import secondary_button
from frontend.components.bulk_action_bar import bulk_action_bar
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_active_document, viewer_layout,
)
from frontend.components.document_viewer_pdf_tools import ViewerPdfTools
from frontend.components.pdf_tools_toolbar_adapter import PDF_ACTIONS, PdfToolsToolbarAdapter
from scripts.tests import test_document_viewer_dv24_multidoc as dv24


SIZES = (0, 1, 2, 4, 5, 9)
GROUPS = {0: 0, 1: 1, 2: 1, 4: 1, 5: 2, 9: 3}
# Marking order differs from listing order; 4, 6 and 8 are never marked.
PICKS = (11, 0, 7, 3, 5, 9, 1, 10, 2)
SCOPE = dict(marked_queue=multidoc.marked_queue, path_key=multidoc.path_key,
             view_selected_action=multidoc.view_selected_action, NO_MARKED=multidoc.NO_MARKED,
             bulk_action_bar=bulk_action_bar)


def listing(count, folder="exp/A"):
    paths = [f"{folder}/doc{index:02d}.pdf" for index in range(count)]
    return [{"path": p, "name": p.rsplit("/", 1)[1], "key": multidoc.path_key(p)} for p in paths]


def keys(entries, indexes):
    return {entries[index]["key"] for index in indexes}


def checked(value):
    return SimpleNamespace(control=SimpleNamespace(value=value))


def icon_buttons(root, icon):
    return [c for c in dv24.walk(root) if isinstance(c, ft.IconButton) and c.icon == icon]


class SnapshotModelTests(unittest.TestCase):
    def test_sizes_form_single_document_or_pages_of_four(self):
        visible = listing(12)
        for size in SIZES:
            with self.subTest(size=size):
                snapshot = multidoc.marked_queue(visible, keys(visible, PICKS[:size]))
                self.assertEqual([e["path"] for e in snapshot],
                                 [visible[i]["path"] for i in sorted(PICKS[:size])])
                queue = multidoc.DocumentQueue(snapshot)
                self.assertEqual((len(queue), queue.group_count), (size, GROUPS[size]))
                pages = []
                while queue.documents:
                    pages.append([d.path for d in queue.group()])
                    if not queue.move_group(1):
                        break
                self.assertEqual(sum(pages, []), [e["path"] for e in snapshot])
                self.assertTrue(all(len(page) == 4 for page in pages[:-1]))
                unmarked = {visible[i]["path"] for i in range(12) if i not in PICKS[:size]}
                self.assertFalse(unmarked & {d.path for d in queue.documents})

    def test_check_and_uncheck_follow_the_listing_order(self):
        visible = listing(6)
        marked = set()
        for index in (4, 1, 3):
            marked.add(visible[index]["key"])
        marked.discard(visible[1]["key"])
        self.assertEqual([e["name"] for e in multidoc.marked_queue(visible, marked)],
                         ["doc03.pdf", "doc04.pdf"])
        marked.add(visible[1]["key"])  # re-checked: listing position, not click order
        self.assertEqual([e["name"] for e in multidoc.marked_queue(visible, marked)],
                         ["doc01.pdf", "doc03.pdf", "doc04.pdf"])
        marked.clear()
        self.assertEqual(multidoc.marked_queue(visible, marked), [])

    def test_fifty_files_with_three_marked_queue_three(self):
        visible = listing(50)
        snapshot = multidoc.marked_queue(visible, keys(visible, (41, 7, 23)))
        self.assertEqual([e["name"] for e in snapshot], ["doc07.pdf", "doc23.pdf", "doc41.pdf"])
        queue = multidoc.DocumentQueue(snapshot)
        self.assertEqual((len(queue), queue.group_count), (3, 1))
        self.assertEqual(queue.group_summary, "3 documentos · Documentos 1–3 de 3")

    def test_filtered_out_marks_are_announced_not_added(self):
        everything = listing(10)
        marked = keys(everything, (1, 2, 8))
        visible = [e for i, e in enumerate(everything) if i % 2 == 0]  # filter: even only
        snapshot = multidoc.marked_queue(visible, marked)
        self.assertEqual([e["name"] for e in snapshot], ["doc02.pdf", "doc08.pdf"])
        action = multidoc.view_selected_action(Mock(), len(snapshot), hidden=len(marked) - len(snapshot))
        self.assertFalse(action["disabled"])
        self.assertIn("1 fuera de este listado no se incluyen", action["tooltip"])
        self.assertEqual(len(marked), 3)  # the filter does not erase the hidden mark

    def test_marks_of_another_folder_are_never_recovered(self):
        folder_a, folder_b = listing(5, "exp/A"), listing(5, "exp/B")
        marked = keys(folder_a, (0, 3))
        self.assertEqual(multidoc.marked_queue(folder_b, marked), [])
        action = multidoc.view_selected_action(Mock(), 0, hidden=2)
        self.assertEqual((action["disabled"], action["tooltip"], action["on_click"]),
                         (True, multidoc.NO_MARKED_VISIBLE, None))
        mixed = multidoc.marked_queue(folder_b, marked | keys(folder_b, (4,)))
        self.assertEqual([e["path"] for e in mixed], ["exp/B/doc04.pdf"])

    def test_keys_are_stable_duplicates_dropped_and_snapshot_detached(self):
        visible = [{"path": "bandeja/a.pdf", "name": "A", "key": "inbox:7", "inbox_item_id": 7},
                   {"path": "exp/x.pdf", "name": "X"},
                   {"path": "bandeja/a.pdf", "name": "A otra vez", "key": "inbox:7"},
                   {"path": "exp/x.pdf", "name": "X otra vez"},
                   {"path": "", "name": "sin identidad"},
                   "exp/y.pdf"]
        marked = {"inbox:7", multidoc.path_key("exp/x.pdf"), multidoc.path_key("exp/y.pdf"), "position:4"}
        snapshot = multidoc.marked_queue(visible, marked)
        self.assertEqual([(e["key"], e["name"] if "name" in e else None) for e in snapshot], [
            ("inbox:7", "A"), (multidoc.path_key("exp/x.pdf"), "X"), (multidoc.path_key("exp/y.pdf"), None)])
        self.assertEqual(snapshot[0]["inbox_item_id"], 7)
        visible[0]["name"] = "cambiado"
        visible.clear()
        self.assertEqual(snapshot[0]["name"], "A")
        queue = multidoc.DocumentQueue(snapshot)
        self.assertEqual([d.key for d in queue.documents], [e["key"] for e in snapshot])
        self.assertEqual(queue.documents[1].key, multidoc.document_key({}, "exp/x.pdf", 0))

    def test_view_selected_action_is_disabled_with_a_visible_reason(self):
        handler = Mock()
        for count, hidden, disabled, tooltip in (
                (0, 0, True, multidoc.NO_MARKED), (0, 3, True, multidoc.NO_MARKED_VISIBLE),
                (2, 0, False, multidoc.VIEW_SELECTED)):
            with self.subTest(count=count, hidden=hidden):
                bar = bulk_action_bar(selected_count=count + hidden,
                                      actions=[multidoc.view_selected_action(handler, count, hidden)])
                button, = icon_buttons(bar, ft.Icons.VISIBILITY)
                self.assertEqual((button.disabled, button.tooltip), (disabled, tooltip))
                self.assertEqual(button.on_click, None if disabled else handler)


class SnapshotViewerTests(dv24.MultidocBase):
    def setUp(self):
        super().setUp()
        for index in range(9, 12):
            path = self.root / f"doc{index}.pdf"
            path.write_bytes(self.originals[self.docs[index - 9]])
            self.docs.append(path)
        self.visible = [{"path": str(p), "name": p.name, "key": multidoc.path_key(p)} for p in self.docs]

    def snapshot(self, indexes):
        return multidoc.marked_queue(self.visible, keys(self.visible, indexes))

    def open_snapshot(self, snapshot, **kwargs):
        kwargs.setdefault("near_window", 0)
        return open_document_viewer_modal(self.page, snapshot[0]["path"], title=snapshot[0]["name"],
                                          queue=snapshot, queue_index=0, **kwargs)

    def test_viewer_shows_only_the_marked_documents_for_each_size(self):
        for size in SIZES[1:]:
            with self.subTest(size=size):
                snapshot = self.snapshot(PICKS[:size])
                names = [e["name"] for e in snapshot]
                dialog = self.open_snapshot(snapshot)
                if size == 1:
                    # One marked document: DV23 single shell, no queue or mosaic.
                    self.assertEqual(len(dialog.content.content.controls), 2)
                    self.assertNotIn("Comparador 4", self.labels(dialog))
                    self.assertEqual(viewer_layout(dialog).title.value, names[0])
                    self.button(dialog, "Cerrar").on_click(None)
                    continue
                layout = self.compare(dialog)
                self.assertEqual(layout.group_label.value, f"Grupo 1 de {GROUPS[size]}")
                shown = []
                while True:
                    shown += self.tile_names(dialog)
                    following = self.button(dialog, "Grupo siguiente")
                    if following.disabled:
                        break
                    following.on_click(None)
                self.assertEqual(shown, names)
                self.assertLessEqual(viewer_layout(dialog).comparator.live_sessions(), 4)
                self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.previews(), [])

    def test_mode_zoom_and_page_changes_keep_the_chosen_set(self):
        snapshot = self.snapshot(PICKS[:5])
        expected = [e["key"] for e in snapshot]
        listing_call = Mock(side_effect=AssertionError("the viewer must not query the listing"))
        with patch.object(service, "list_expediente_documents", listing_call):
            dialog = self.open_snapshot(snapshot)
            steps = [lambda: self.compare(dialog),
                     lambda: viewer_layout(dialog).tiles[1].zoom_in.on_click(None),
                     lambda: viewer_layout(dialog).tiles[0].next_page.on_click(None),
                     lambda: self.button(dialog, "Grupo siguiente").on_click(None),
                     lambda: self.button(dialog, "Documento único").on_click(None),
                     lambda: self.button(dialog, "Zoom +").on_click(None),
                     lambda: self.button(dialog, "Siguiente").on_click(None),
                     lambda: self.button(dialog, "Doc anterior").on_click(None),
                     lambda: self.compare(dialog)]
            for step in steps:
                step()
                queue = viewer_layout(dialog).queue
                self.assertEqual([d.key for d in queue.documents], expected)
            self.button(dialog, "Cerrar").on_click(None)
        listing_call.assert_not_called()

    def test_tile_click_changes_the_active_document_not_the_set(self):
        snapshot = self.snapshot((2, 6, 8))
        dialog = self.open_snapshot(snapshot)
        layout = self.compare(dialog)
        layout.tiles[2].container.on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual(viewer_active_document(dialog).path, str(self.docs[8]))
        self.assertEqual([v.active for v in layout.tiles], [False, False, True])
        self.assertEqual([d.key for d in layout.queue.documents], [e["key"] for e in snapshot])
        self.button(dialog, "Cerrar").on_click(None)

    def test_pdf_buttons_act_only_on_the_active_marked_document(self):
        items = {str(p): {"id": 100 + i, "stored_path": str(p)} for i, p in enumerate(self.docs)}
        handlers = {"rotate": Mock(), "split": Mock()}
        adapter = PdfToolsToolbarAdapter(lambda request: items.get(request.path), handlers, Mock())
        dialog = self.open_snapshot(self.snapshot((7, 2, 5)), toolbar_actions=adapter)
        layout = self.compare(dialog)
        operations = {operation for operation, _ in PDF_ACTIONS}
        self.assertFalse([c for c in dv24.walk(layout.canvas) if getattr(c, "data", None) in operations])
        self.assertEqual(self.labels(dialog).count("Rotar páginas"), 1)
        self.button(dialog, "Rotar páginas").on_click("first")
        layout.tiles[2].container.on_click(None)
        self.button(dialog, "Rotar páginas").on_click("third")
        self.assertEqual([c.kwargs["item_id"] for c in handlers["rotate"].call_args_list], [102, 107])
        handlers["split"].assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)


class InboxSelectionWiringTests(dv24.MultidocBase):
    FUNCTIONS = dv24.INBOX_FUNCTIONS + ("build_bulk_actions_content", "select_item", "clear_selection")

    def setUp(self):
        super().setUp()
        self.inbox = {index + 1: {"id": index + 1, "stored_path": str(path),
                                  "original_filename": f"Bandeja {index + 1}.pdf"}
                      for index, path in enumerate(self.docs[:6])}
        self.state = {"selected_item_id": 4, "selected_item_ids": set(),
                      "items": [dict(item) for item in self.inbox.values()]}
        self.error = Mock()
        self.batch_message = SimpleNamespace(content=None, update=Mock())
        patcher = patch.object(inbox_tools, "get_inbox_item",
                               side_effect=lambda item_id: self.inbox.get(int(item_id)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.canonical = Mock()
        self.scope = dv24.bind(dv24.INBOX, self.FUNCTIONS, dict(
            SCOPE, ft=ft, page=self.page, state=self.state, open_document_viewer_modal=self.canonical,
            ViewerPdfTools=ViewerPdfTools,
            document_inbox_service=SimpleNamespace(get_inbox_item=lambda i: self.inbox.get(int(i)),
                                                   client_autocomplete_options=Mock(return_value=[])),
            refresh_items=Mock(), _document_tool_register_response_in_batch_if_needed=Mock(),
            show_error=self.error, batch_detail_message=self.batch_message,
            error_alert=lambda text: ft.Text(str(text)), item=self.inbox[3],
            clear_bulk_selection=Mock(), bulk_actions_message=ft.Container(),
            build_document_tools_bulk_control=lambda: None, mark_selected_reviewed=Mock(),
            discard_selected_documents=Mock(), open_create_batch_dialog=Mock(),
            selected_label=SimpleNamespace(value=""), client_autocomplete=Mock(),
            expedient_autocomplete=Mock(), refresh_relation_label=Mock(),
            events_box=SimpleNamespace(content=None, update=Mock()), build_events_panel=Mock(),
            render_items=Mock(),
        ))

    def view_button(self):
        button, = icon_buttons(self.scope["build_bulk_actions_content"](), ft.Icons.VISIBILITY)
        return button

    def test_ver_seleccionados_ignores_active_hidden_and_unmarked_items(self):
        # Item 4 is active but unmarked; 99 is marked on another page.
        self.state["selected_item_ids"] = {5, 99, 2}
        button = self.view_button()
        self.assertFalse(button.disabled)
        self.assertIn("1 fuera de este listado", button.tooltip)
        button.on_click(None)
        kwargs = self.canonical.call_args.kwargs
        self.assertEqual([e["inbox_item_id"] for e in kwargs["queue"]], [2, 5])
        self.assertEqual([e["key"] for e in kwargs["queue"]], ["inbox:2", "inbox:5"])
        self.assertEqual((kwargs["file_path"], kwargs["queue_index"]), (str(self.docs[1]), 0))
        # The individual preview opens the active item alone.
        self.scope["show_preview"]()
        kwargs = self.canonical.call_args.kwargs
        self.assertIsNone(kwargs["queue"])
        self.assertEqual(kwargs["file_path"], str(self.docs[3]))
        # One marked item: single mode.
        self.state["selected_item_ids"] = {3}
        self.view_button().on_click(None)
        kwargs = self.canonical.call_args.kwargs
        self.assertIsNone(kwargs["queue"])
        self.assertEqual(kwargs["file_path"], str(self.docs[2]))
        self.assertEqual(self.state["selected_item_id"], 4)
        self.error.assert_not_called()

    def test_zero_visible_marks_disable_the_action_without_fallback(self):
        for marked, reason in ((set(), multidoc.NO_MARKED), ({99}, multidoc.NO_MARKED_VISIBLE)):
            with self.subTest(marked=marked):
                self.state["selected_item_ids"] = marked
                button = self.view_button()
                self.assertEqual((button.disabled, button.tooltip, button.on_click), (True, reason, None))
        calls = self.canonical.call_count
        self.scope["show_selected_preview"]()  # stale handler: an error, never the listing
        self.assertEqual(self.canonical.call_count, calls)
        self.error.assert_called_once()

    def test_filtered_listing_reconciles_the_visible_selection(self):
        self.state["selected_item_ids"] = {1, 2, 6}
        self.state["items"] = [i for i in self.state["items"] if i["id"] % 2 == 0]  # filter
        self.view_button().on_click(None)
        self.assertEqual([e["inbox_item_id"] for e in self.canonical.call_args.kwargs["queue"]], [2, 6])
        self.assertEqual(self.state["selected_item_ids"], {1, 2, 6})

    def test_group_previews_its_marked_items_only(self):
        batch = [{"id": 7, "stored_path": "", "linked_document_path": str(self.docs[6])},
                 {"id": 8, "stored_path": str(self.docs[7]), "original_filename": "ocho.pdf"},
                 {"id": 9, "stored_path": str(self.docs[8]), "original_filename": "nueve.pdf"}]
        self.state["open_batch_selected_item_ids"] = {9, 7, 2}  # 2 belongs to another listing
        self.scope["show_batch_selected_preview"](batch)
        kwargs = self.canonical.call_args.kwargs
        self.assertEqual([e["path"] for e in kwargs["queue"]], [str(self.docs[6]), str(self.docs[8])])
        self.scope["show_batch_item_preview"](batch[1])
        self.assertIsNone(self.canonical.call_args.kwargs["queue"])
        calls = self.canonical.call_count
        self.state["open_batch_selected_item_ids"] = set()
        self.scope["show_batch_selected_preview"](batch)
        self.assertEqual(self.canonical.call_count, calls)
        self.assertEqual(self.batch_message.content.value, "Selecciona uno o varios documentos del grupo.")

    def test_clicking_cards_changes_the_active_item_not_the_marks(self):
        self.state["selected_item_ids"] = {1, 5}
        self.scope["select_item"](2)
        self.assertEqual((self.state["selected_item_id"], self.state["selected_item_ids"]), (2, {1, 5}))
        self.scope["select_item"](2)  # deactivating the card keeps the marks
        self.assertEqual((self.state["selected_item_id"], self.state["selected_item_ids"]), (None, {1, 5}))


class ExpedientSelectionWiringTests(unittest.TestCase):
    def setUp(self):
        self.page = SimpleNamespace(overlay=[], update=Mock())
        self.preview = Mock()
        self.form_error = Mock()

    def scope(self, docs, **extra):
        return dict(SCOPE, ft=ft, page=self.page, state={"dialog_expediente_id": 42},
                    show_form_error=self.form_error, secondary_button=secondary_button,
                    Q_PRIMARY="#0057B8", Q_PRIMARY_DARK="#003B7A", Q_MUTED="#64748B", Q_BORDER="#D0D5DD",
                    document_viewer_service=SimpleNamespace(list_expediente_documents=Mock(return_value={
                        "root_path": "exp", "total_documents": len(docs), "documents": docs})),
                    show_document_preview=self.preview, open_document_with_system=Mock(), **extra)

    def test_documents_dialog_with_fifty_files_and_three_marked(self):
        docs = [{"path": e["path"], "name": e["name"], "type": "pdf"} for e in listing(50)]
        cards, dialog = [], ft.AlertDialog(modal=True)
        scope = dv24.bind(dv24.EXPEDIENTS, ("show_expediente_documents_dialog",), self.scope(
            docs, document_list_dialog=dialog, close_document_list_dialog=Mock(),
            document_file_card=lambda **kwargs: cards.append(kwargs) or ft.Container()))
        scope["show_expediente_documents_dialog"]()

        def view():
            button, = icon_buttons(dialog.content, ft.Icons.VISIBILITY)
            return button

        self.assertEqual((view().disabled, view().tooltip), (True, multidoc.NO_MARKED))
        for index in (41, 7, 23):
            cards[index]["on_select"](checked(True))
        view().on_click(None)
        args, kwargs = self.preview.call_args
        self.assertEqual(args, (docs[7]["path"], "doc07.pdf"))
        self.assertEqual([e["path"] for e in kwargs["queue"]], [docs[i]["path"] for i in (7, 23, 41)])
        self.assertEqual((kwargs["queue_index"], kwargs["expediente_id"]), (0, 42))
        cards[23]["on_select"](checked(False))
        view().on_click(None)
        self.assertEqual([e["path"] for e in self.preview.call_args.kwargs["queue"]],
                         [docs[7]["path"], docs[41]["path"]])
        # "Previsualizar" of one card: that document, no queue.
        cards[12]["on_preview"](None)
        self.assertNotIn("queue", self.preview.call_args.kwargs)
        self.assertEqual(self.preview.call_args.args, (docs[12]["path"], "doc12.pdf"))
        for index in (7, 41):
            cards[index]["on_select"](checked(False))
        self.assertTrue(view().disabled)
        self.form_error.assert_not_called()

    def test_inline_listing_marks_rows_across_heterogeneous_folders(self):
        docs = [dict(e, type="pdf", folder_relative=folder) for e, folder in zip(
            listing(2, "exp/Raíz") + listing(3, "exp/Sub"), ("Raíz",) * 2 + ("Sub",) * 3)]
        scope = dv24.bind(dv24.EXPEDIENTS, ("build_expediente_documents_inline",), self.scope(docs))
        panel = scope["build_expediente_documents_inline"](42)
        boxes = [c for c in dv24.walk(panel) if isinstance(c, ft.Checkbox)]
        self.assertEqual(len(boxes), 5)
        self.assertTrue(icon_buttons(panel, ft.Icons.VISIBILITY)[0].disabled)
        for index in (4, 0):
            boxes[index].value = True
            boxes[index].on_change(SimpleNamespace(control=boxes[index]))
        self.preview.assert_not_called()  # checking never opens the viewer by itself
        icon_buttons(panel, ft.Icons.VISIBILITY)[0].on_click(None)
        self.assertEqual([e["path"] for e in self.preview.call_args.kwargs["queue"]],
                         [docs[0]["path"], docs[4]["path"]])
        previews = [c for c in dv24.walk(panel) if isinstance(c, ft.OutlinedButton)
                    and getattr(c.content, "value", None) == "Previsualizar"]
        previews[2].on_click(None)
        self.assertEqual(self.preview.call_args, ((docs[2]["path"], docs[2]["name"]), {}))

    def test_folder_explorer_queues_the_visible_marked_files_only(self):
        tree = ast.parse(dv24.EXPEDIENTS.read_text(encoding="utf-8"))
        explorer = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == "build_documentacion_content")
        inner = {n.name: n for n in ast.walk(explorer) if isinstance(n, ast.FunctionDef)}
        visible = ast.unparse(inner["visible_selected_documents"])
        self.assertIn("marked_queue(files_queue,", visible)
        self.assertIn("visible_selected_documents()", ast.unparse(inner["open_selected_documents"]))
        self.assertIn("view_selected_action(", ast.unparse(inner["build_documents_bulk_bar"]))
        previews = [n for n in ast.walk(explorer) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "show_document_preview"]
        self.assertEqual(len(previews), 2)
        self.assertEqual(sorted(len(call.args) for call in previews), [3, 7])
        self.assertFalse(any(k.arg == "queue" for call in previews for k in call.keywords))


if __name__ == "__main__":
    unittest.main()
