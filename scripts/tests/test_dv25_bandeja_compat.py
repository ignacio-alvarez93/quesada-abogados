"""WO-DV25-C2-C3 · C2: the existing Bandeja button «Copiar a Box expediente» after P3B1 (OFFLINE).

The button's real handlers of ``frontend/views/document_inbox_view.py`` (``copy_to_box`` and the
detail dialog's ``detail_copy_to_box``, with ``selected_item`` and the subfolder/filename
resolvers they close over) are bound with DV24's ``bind`` and run FOR REAL against the
certified P3B1 copy ``copy_inbox_item_to_expedient_box``. The viewer gate is not involved:
it stays closed (``EXECUTION_ENABLED = False``) and the button still copies.

Sandbox (all inside a TemporaryDirectory):

- P3B1's ``BoxCopyBase``: synthetic SQLite CRM (``connection.DB_PATH`` and ``get_connection``
  redirected and checked), synthetic Bandeja (``INBOX_*``), synthetic Box tree; any delete,
  move, rename, symlink or shutil copy fails, and any open-for-write or mkdir outside the sandbox;
- P3B3's ``SandboxMixin``: ``sqlite3.connect`` refuses any database outside the sandbox and
  ``expedient_service.DB_PATH`` points to it;
- here: ``os.open`` for writing outside the sandbox, any child process, any socket connection
  or name resolution, and any filesystem call on a UNC/device path fail the test; that is how
  UNC roots are proven to be refused WITHOUT contacting the network. ``get_inbox_item`` and
  ``get_expedient`` are spied (real code, sandbox database).

The habitual ``quesada.db`` is fingerprinted (size, mtime, SHA-256) before and after the module.
A synthetic PASS here is C2 OFFLINE only: it proves nothing about a real Box Drive installation
(C2 REAL stays PENDING; see docs/dv25_c2_c3_smoke_instructions.md).
"""
import ast
import os
from pathlib import Path
import socket
import subprocess
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.services import document_inbox_service as inbox
from backend.services import document_viewer_box_archive_service as archive
from scripts.tests import test_document_viewer_dv24_linking as dv24
from scripts.tests import test_document_viewer_dv25_box_hardening as p3b1
from scripts.tests import test_document_viewer_dv25_security as security


VIEW_HANDLERS = ("selected_item", "_normalize_box_subfolder_for_copy", "_resolve_box_subfolder_for_copy",
                 "_resolve_box_target_filename_for_copy", "open_expediente_from_document_flow",
                 "copy_to_box", "detail_copy_to_box")
BUTTON = "Copiar a Box expediente"
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
UNC_ROOTS = ("\\\\servidor\\box\\EXP-42", "//servidor/box/EXP-42", "\\\\?\\UNC\\servidor\\box\\EXP-42",
             "\\\\?\\C:\\box\\EXP-42", "\\\\.\\C:\\box\\EXP-42")
HABITUAL_BEFORE = []


def setUpModule():
    HABITUAL_BEFORE[:] = security.habitual_fingerprint()


def tearDownModule():
    if security.habitual_fingerprint() != HABITUAL_BEFORE:
        raise AssertionError("The habitual database changed during the C2 compatibility suite.")


def network_path(value):
    try:
        text = os.fsdecode(os.fspath(value))
    except TypeError:
        return False
    return text.startswith(("\\\\", "//"))


class BandejaCompatBase(security.SandboxMixin, p3b1.BoxCopyBase):
    def setUp(self):
        super().setUp()
        self.sandbox(self.root, self.db)
        self.network_touches = []
        self.guard_isolation()
        self.get_item = self.patch(inbox, "get_inbox_item", wraps=inbox.get_inbox_item)
        self.get_expedient = self.patch(inbox, "get_expedient", wraps=inbox.get_expedient)
        self.bind_view()

    def tearDown(self):
        self.assertEqual(self.network_touches, [])
        self.popen.assert_not_called()
        self.connect.assert_not_called()
        self.resolve.assert_not_called()
        self.get_expedient.assert_not_called()  # the button reads the expediente inside the copy only
        self.assertIs(archive.EXECUTION_ENABLED, False)
        super().tearDown()

    # ------------------------------------------------------------------ isolation

    def guard_isolation(self):
        real_os_open = os.open

        def guarded_os_open(path, flags, *args, **kwargs):
            if flags & WRITE_FLAGS and not self.inside_sandbox(path):
                self.violations.append(("os.open", str(path)))
                raise AssertionError(f"os.open for writing outside the sandbox: {path}")
            return real_os_open(path, flags, *args, **kwargs)

        self.patch(os, "open", guarded_os_open)
        self.popen = self.patch(subprocess, "Popen", side_effect=AssertionError("child process"))
        self.connect = self.patch(socket.socket, "connect", side_effect=AssertionError("network"))
        self.resolve = self.patch(socket, "getaddrinfo", side_effect=AssertionError("name resolution"))

        def refuse(name, original):
            def wrapper(*args, **kwargs):
                if args and network_path(args[0]):
                    self.network_touches.append((name, str(args[0])))
                    raise AssertionError(f"{name} on a network or device path: {args[0]}")
                return original(*args, **kwargs)
            return wrapper

        for name in ("stat", "lstat", "scandir", "listdir"):
            self.patch(os, name, refuse(f"os.{name}", getattr(os, name)))
        for name in ("exists", "is_dir", "is_file", "resolve", "stat", "lstat", "iterdir", "mkdir", "open"):
            self.patch(Path, name, refuse(f"Path.{name}", getattr(Path, name)))

    # ------------------------------------------------------------------ the view's handlers

    def bind_view(self):
        self.view_state = {"selected_item_id": None, "selected_expedient_id": None, "selected_client_id": None}
        self.messages = []
        self.refresh_items = Mock()
        self.on_open_expediente = Mock()
        self.box_subfolder = SimpleNamespace(value="")
        self.detail_relation_text = SimpleNamespace(value="", update=Mock())
        self.detail_events_box = SimpleNamespace(content=None, update=Mock())
        self.scope = dv24.bind(dv24.INBOX, VIEW_HANDLERS, dict(
            page=SimpleNamespace(overlay=[], update=Mock()), state=self.view_state,
            document_inbox_service=inbox, box_subfolder=self.box_subfolder,
            show_error=lambda message: self.messages.append(("error", str(message))),
            show_success=lambda message: self.messages.append(("success", str(message))),
            refresh_items=self.refresh_items, on_open_expediente=self.on_open_expediente,
            detail_relation_text=self.detail_relation_text, detail_events_box=self.detail_events_box,
            build_events_panel=Mock(return_value="panel"), item_id=None,
        ))

    def press(self, item_id, expedient_id=42, subfolder=""):
        """«Copiar a Box expediente» of the actions panel, on the selected item."""
        self.view_state.update(selected_item_id=item_id, selected_expedient_id=expedient_id)
        self.box_subfolder.value = subfolder
        return self.scope["copy_to_box"](None)

    def press_detail(self, item_id, *, directory="", target_filename="", expedient_id=42, client_id=7):
        """«Copiar a Box expediente» of the document detail dialog."""
        self.view_state.update(detail_selected_client_id=client_id, detail_selected_expedient_id=expedient_id,
                               detail_selected_directory=directory,
                               detail_selected_expedient_box_folder_path=str(self.box),
                               detail_selected_document_nomenclature={"target_filename": target_filename})
        self.scope["item_id"] = item_id
        return self.scope["detail_copy_to_box"](None)

    def assert_button_refused(self, item_id, fragment, **kwargs):
        """Error shown, no navigation, no file, no state or event change."""
        state, events, tree = self.item_state(item_id), self.events(item_id), self.tree()
        self.messages.clear()
        self.on_open_expediente.reset_mock()
        self.assertIsNone(self.press(item_id, **kwargs))
        self.assertEqual(len(self.messages), 1, self.messages)
        kind, message = self.messages[0]
        self.assertEqual(kind, "error")
        self.assertIn(fragment, message)
        self.on_open_expediente.assert_not_called()
        self.assertEqual(self.item_state(item_id), state)
        self.assertEqual(self.events(item_id), events)
        self.assertEqual(self.tree(), tree)

    def set_root(self, value, expedient_id=42):
        self.execute("UPDATE expedientes SET box_folder_path = ? WHERE id = ?", (value, expedient_id))


# ---------------------------------------------------------------------- wiring


class WiringTests(unittest.TestCase):
    def test_both_buttons_call_the_existing_handlers_and_the_certified_copy(self):
        tree = ast.parse(dv24.INBOX.read_text(encoding="utf-8"))
        wired = sorted(node.args[1].id for node in ast.walk(tree)
                       if isinstance(node, ast.Call) and getattr(node.func, "id", None) in (
                           "primary_button", "secondary_button")
                       and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant)
                       and node.args[0].value == BUTTON and isinstance(node.args[1], ast.Name))
        self.assertEqual(wired, ["copy_to_box", "detail_copy_to_box"])
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and getattr(node.func, "attr", None) == "copy_inbox_item_to_expedient_box"]
        self.assertEqual(len(calls), 1)
        # The classic button never passes a nomenclature: the P3B1 path that creates missing folders.
        self.assertEqual({keyword.arg for keyword in calls[0].keywords},
                         {"expedient_id", "subfolder", "target_filename"})

    def test_the_viewer_gate_is_not_on_the_bandeja_path(self):
        for path in (dv24.INBOX, Path(inbox.__file__)):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("EXECUTION_ENABLED", source)
            self.assertNotIn("document_viewer_box_archive_service", source)
        self.assertIs(archive.EXECUTION_ENABLED, False)


# ---------------------------------------------------------------------- C2 OFFLINE matrix


class LocalRootTests(BandejaCompatBase):
    def test_button_copies_to_a_local_root_copy_verify_register(self):
        item = self.add_item()
        order = []
        real_stream, real_verify, real_register = inbox._stream_into, inbox._verify_box_copy, inbox._register_box_copy

        def stream(*args):
            order.append(("copy", self.item_state(item)["status"]))
            return real_stream(*args)

        def verify(*args):
            order.append(("verify", self.item_state(item)["status"]))
            return real_verify(*args)

        def register(*args):
            order.append(("register", self.item_state(item)["status"]))
            return real_register(*args)

        with patch.object(inbox, "_stream_into", stream), patch.object(inbox, "_verify_box_copy", verify), \
                patch.object(inbox, "_register_box_copy", register):
            result = self.press(item, subfolder="01 IDENTIDAD")
        dest = self.box / "01 IDENTIDAD" / "Pasaporte.pdf"
        self.assertEqual(order, [("copy", "linked"), ("verify", "linked"), ("register", "linked")])
        self.assert_registered(item, result, dest)
        self.assertEqual(self.messages, [("success", f"Documento copiado a Box: {dest}")])
        self.refresh_items.assert_called_once_with()
        self.on_open_expediente.assert_called_once_with(42)
        self.get_item.assert_called()  # selected_item() reads the real item from the sandbox
        [event] = self.events(item, "copied_to_box")
        trace = event["metadata"]
        self.assertEqual((trace["collision_decision"], trace["provenance"], trace["created_by_this_operation"]),
                         ("none", "created", True))
        self.assertEqual(trace["destination_sha256"], trace["source_sha256"])
        self.assertEqual(trace["box_root"], str(self.box))
        # The source stays in Bandeja, byte for byte (also checked in tearDown) and with its metadata.
        source, data = self.sources[item]
        self.assertEqual(source.read_bytes(), data)
        self.assertEqual(self.item_state(item)["stored_path"], str(source))

    def test_detail_button_with_selected_directory_and_nomenclature_name(self):
        item = self.add_item()
        result = self.press_detail(item, directory=str(self.box / "02 LABORAL" / "Contratos"),
                                   target_filename="CONTRATO DE TRABAJO")
        self.assertIsNone(result)  # the detail handler reports through the dialog, not a return value
        dest = self.box / "02 LABORAL" / "Contratos" / "CONTRATO DE TRABAJO.pdf"
        self.assert_registered(item, inbox.get_inbox_item(item), dest)
        self.assertEqual(dest.read_bytes(), self.sources[item][1])
        self.assertIn(f"Box destino: {dest}", self.detail_relation_text.value)
        self.on_open_expediente.assert_called_once_with(42)
        # The one-shot overrides are consumed: the next classic copy uses the panel's own fields.
        self.assertNotIn("copy_to_box_subfolder_override", self.view_state)
        self.assertNotIn("copy_to_box_target_filename_override", self.view_state)
        other = self.add_item(name="Nomina.pdf")
        self.assert_registered(other, self.press(other), self.box / "Nomina.pdf")

    def test_missing_subfolder_is_created_inside_the_root_by_the_classic_button(self):
        """Existing behaviour kept by P3B1 for this button (the viewer path never recreates folders)."""
        item = self.add_item()
        result = self.press(item, subfolder="03 NUEVA/Requerimientos")
        self.assert_registered(item, result, self.box / "03 NUEVA" / "Requerimientos" / "Pasaporte.pdf")
        self.assertEqual(result["box_copy"]["created_folders"], ["03 NUEVA", "03 NUEVA/Requerimientos"])

    def test_detail_directory_outside_the_root_is_refused(self):
        item = self.add_item()
        state, tree = self.item_state(item), self.tree()
        self.assertIsNone(self.press_detail(item, directory=str(self.outside)))
        [(kind, message)] = self.messages
        self.assertEqual(kind, "error")
        self.assertIn("Subcarpeta destino no válida", message)
        self.on_open_expediente.assert_not_called()
        self.assertEqual((self.item_state(item), self.tree()), (state, tree))

    def test_hostile_subfolders_from_the_panel_are_refused(self):
        item = self.add_item()
        for subfolder in ("..", "../fuera", "01 IDENTIDAD/../../fuera", "C:/fuera", "\\\\servidor\\box",
                          "//servidor/box", "CON", "carpeta."):
            with self.subTest(subfolder=subfolder):
                self.assert_button_refused(item, "Subcarpeta destino no válida", subfolder=subfolder)


class NetworkAndLinkTests(BandejaCompatBase):
    def test_unc_and_device_roots_are_refused_without_touching_the_network(self):
        item = self.add_item()
        for raw in UNC_ROOTS:
            with self.subTest(root=raw):
                self.set_root(raw)
                self.assert_button_refused(item, "ruta de red o de dispositivo")
        self.assertEqual(self.network_touches, [])

    def test_the_network_guard_itself_is_active(self):
        with self.assertRaises(AssertionError):
            Path("\\\\servidor\\box\\EXP-42").exists()
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("servidor", 445)
        self.assertEqual(len(self.network_touches), 1)
        self.network_touches.clear()
        self.resolve.reset_mock()

    def test_root_that_is_a_link_or_junction_is_refused(self):
        link = self.root / "box_enlace"
        try:
            kind = self.make_dir_link(self.box, link)
        except OSError as exc:
            self.skipTest(f"Este equipo no permite crear enlaces ni uniones de directorio: {exc}")
        self.set_root(str(link))
        with self.subTest(kind=kind):
            self.assert_button_refused(self.add_item(), "enlace o una unión")

    def test_link_or_junction_inside_the_root_is_refused_and_never_followed(self):
        try:
            kind = self.make_dir_link(self.outside, self.box / "01 IDENTIDAD" / "salida")
        except OSError as exc:
            self.skipTest(f"Este equipo no permite crear enlaces ni uniones de directorio: {exc}")
        self.protect_box()
        item = self.add_item()
        for subfolder in ("01 IDENTIDAD/salida", "01 IDENTIDAD/salida/secreta", "01 IDENTIDAD/salida/nueva"):
            with self.subTest(kind=kind, subfolder=subfolder):
                self.assert_button_refused(item, "no es una carpeta real", subfolder=subfolder)
        self.assertFalse((self.outside / "nueva").exists())

    @unittest.skip("NO PROBADO (C2 REAL PENDIENTE): una letra de unidad asignada a un recurso de red (Z:) "
                   "no se puede simular sin crear una asignación real; _authorized_box_root solo rechaza "
                   "prefijos UNC/dispositivo por texto y trataría esa unidad como local.")
    def test_mapped_network_drive_letter(self):
        pass

    @unittest.skip("NO PROBADO (C2 REAL PENDIENTE): la raíz real de Box Drive y sus marcadores de nube "
                   "requieren autorización humana separada; aquí solo se prueba el predicado sintético "
                   "(P3B1 test_reparse_points_other_than_cloud_placeholders_are_unsafe).")
    def test_real_box_drive_root_and_cloud_placeholders(self):
        pass


class CollisionAndIntegrityTests(BandejaCompatBase):
    def test_existing_name_is_never_overwritten(self):
        self.seed(self.box / "Pasaporte.pdf", b"otro documento previo")
        self.protect_box()
        item = self.add_item()
        result = self.press(item)
        self.assert_registered(item, result, self.box / "Pasaporte_2.pdf")
        self.assertEqual(result["box_copy"]["collision_decision"], "renamed")
        self.assertEqual((self.box / "Pasaporte.pdf").read_bytes(), b"otro documento previo")
        self.assertEqual(set(self.box_write_modes), {"xb"})

    def test_identical_previous_file_is_reused_with_its_provenance(self):
        content = b"%PDF-1.4 nomina identica"
        self.seed(self.box / "Nomina.pdf", content)
        self.protect_box()
        item = self.add_item(content=content, name="Nomina.pdf")
        result = self.press(item)
        self.assert_registered(item, result, self.box / "Nomina.pdf")
        trace = result["box_copy"]
        self.assertEqual((trace["collision_decision"], trace["provenance"], trace["created_by_this_operation"]),
                         ("reused_identical", "preexisting_unverified", False))
        [event] = self.query("SELECT message FROM document_inbox_events WHERE item_id = ? "
                             "AND event_type = 'copied_to_box'", (item,))
        self.assertIn("no lo creó esta operación", event["message"])
        self.assertFalse((self.box / "Nomina_2.pdf").exists())

    def test_pressing_twice_copies_once(self):
        """Sequential second press: the registered, intact copy is reported, nothing is written."""
        item = self.add_item()
        first = self.press(item)
        self.assertEqual(first["box_copy"]["result"], "copied")
        events, tree, writes = self.events(item), self.tree(), len(self.box_write_modes)
        second = self.press(item, subfolder="02 LABORAL")
        self.assertEqual(second["box_copy"]["result"], "already_copied")
        self.assertEqual(second["copied_to_box_path"], first["copied_to_box_path"])
        self.assertEqual(self.events(item), events)
        # Whole Box tree byte for byte (the P3B1 fixture already holds «PASAPORTE SOLICITANTE.pdf»).
        self.assertEqual(self.tree(), tree)
        self.assertEqual(len(self.box_write_modes), writes)
        self.assertFalse((self.box / "02 LABORAL" / "Pasaporte.pdf").exists())

    def test_double_press_protection_is_in_process_only(self):
        """Residual (not fixed here): the button's lock is a threading.Lock of this process.

        Two CRM processes pressing at the same time are not coordinated by it; exclusive ``xb``
        creation then yields ``Pasaporte_2.pdf`` instead of overwriting (see
        test_existing_name_is_never_overwritten). Inter-process protection stays PENDING.
        """
        self.assertIsInstance(inbox._box_copy_lock(1), type(threading.Lock()))
        self.assertIs(inbox._box_copy_lock(1), inbox._box_copy_lock(1))
        self.assertIsNot(inbox._box_copy_lock(1), inbox._box_copy_lock(2))

    def test_changed_source_is_refused_and_never_copied(self):
        self.assert_button_refused(self.add_item(sha256="f" * 64), "no coincide con el SHA-256")

    def test_source_outside_bandeja_is_refused(self):
        external = self.root / "descargas" / "externo.pdf"
        external.parent.mkdir()
        external.write_bytes(b"%PDF externo")
        self.assert_button_refused(self.add_item(stored_path=external), "no es un archivo interno de Bandeja")


class DestinationChangeTests(BandejaCompatBase):
    def test_removed_root_is_refused_and_not_recreated(self):
        retired = self.root / "box" / "EXP-RETIRADO"
        self.set_root(str(retired))
        self.assert_button_refused(self.add_item(), "no existe en este equipo")
        self.assertFalse(retired.exists())

    def test_root_changed_after_the_copy_requires_review(self):
        item = self.add_item()
        first = Path(self.press(item)["copied_to_box_path"])
        moved = self.root / "box" / "EXP-42-NUEVA"
        moved.mkdir()
        self.set_root(str(moved))
        self.assert_button_refused(item, "requiere revisión")
        self.assertEqual(list(moved.iterdir()), [])
        self.assertTrue(first.is_file())

    def test_registered_copy_removed_in_box_is_copied_again(self):
        item = self.add_item()
        first = Path(self.press(item)["copied_to_box_path"])
        self.real["unlink"](first)  # manual removal in Box, outside the service
        result = self.press(item, subfolder="01 IDENTIDAD")
        self.assert_registered(item, result, self.box / "01 IDENTIDAD" / "Pasaporte.pdf")
        self.assertEqual(len(self.events(item, "copied_to_box")), 2)

    def test_expedient_without_box_folder_or_of_another_client(self):
        self.assert_button_refused(self.add_item(), "no tiene carpeta Box vinculada", expedient_id=43)
        self.assert_button_refused(self.add_item(client_id=8), "cliente distinto")


if __name__ == "__main__":
    unittest.main()
