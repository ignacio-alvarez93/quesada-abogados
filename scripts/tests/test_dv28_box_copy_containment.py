"""WO-DV28-SIMPLE: H3 containment in the ONE Box copy engine shared by Bandeja and the viewer.

``copy_inbox_item_to_expedient_box`` now pins the expediente's Box root and every folder down to
the destination (Win32 handles without FILE_SHARE_DELETE, reparse points not followed) for the
whole COPY + VERIFY, and checks what was actually opened. Everything runs on the certified P3B1
sandbox (``BoxCopyBase``): TemporaryDirectory, synthetic SQLite, synthetic Box compared byte for
byte, no delete/move/rename/overwrite primitive reachable, habitual ``quesada.db`` untouched.

- ``ContainmentTests`` (Windows only, real NTFS junctions): swapped destination or intermediate
  folder refused before any write; pinned folders cannot be removed or renamed mid-copy; a folder
  that cannot be pinned refuses without writing.
- ``EngineTests`` (every platform): the copy runs inside the pin; PDF/JPG names and extensions,
  collisions, retries, write and register failures and hostile destinations keep the P3B1
  semantics (nothing overwritten, original intact, unregistered files kept for review).
"""
import ast
import os
import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from backend.services import document_inbox_service as inbox
from scripts.tests import test_document_viewer_dv25_box_hardening as p3b1


WINDOWS_ONLY = "H3 prevention pins folders with Win32 handles (Windows only)"
PIN_HELPERS = ("_pinned_box_folder", "_pin_directory", "_pinned_final_path", "_kernel32")
WIN32_CALLS = {"CreateFileW", "GetFileInformationByHandleEx", "GetFinalPathNameByHandleW", "CloseHandle"}


class ScopeTests(unittest.TestCase):
    def test_the_pin_only_opens_reads_and_closes_handles(self):
        tree = ast.parse(p3b1.INBOX_SERVICE.read_text(encoding="utf-8"))
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        banned = {"copy2", "copyfile", "copy", "move", "unlink", "remove", "rename", "replace", "rmtree",
                  "rmdir", "mkdir", "makedirs", "write_bytes", "write_text", "touch", "open", "symlink"}
        win32 = set()
        for name in PIN_HELPERS:
            calls = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                     for node in ast.walk(functions[name]) if isinstance(node, ast.Call)}
            self.assertEqual(calls & banned, set(), name)
            win32 |= {node.func.attr for node in ast.walk(functions[name]) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute) and node.func.attr[:1].isupper()
                      and node.func.attr not in ("WinDLL",)}
        self.assertLessEqual(win32, WIN32_CALLS)
        # The pin wraps exactly the creation (COPY + VERIFY) inside the single engine.
        engine = ast.unparse(functions["_copy_inbox_item_to_box"])
        self.assertIn("with _pinned_box_folder(root, folder):", engine)
        self.assertEqual(engine.count("_create_box_copy("), 1)


class PinnedBase(p3b1.BoxCopyBase):
    def swap_after_validation(self, swapped, escape):
        """Patch the validation so that, once it passed, ``swapped`` becomes a link to ``escape``."""
        real_folder = inbox._box_destination_folder

        def validated_then_swapped(root, relative, create_missing=True):
            result = real_folder(root, relative, create_missing)
            for folder in sorted((p for p in swapped.rglob("*") if p.is_dir()), reverse=True):
                self.real["rmdir"](folder)
            self.real["rmdir"](swapped)
            self.make_dir_link(escape, swapped)
            return result

        return patch.object(inbox, "_box_destination_folder", validated_then_swapped)

    def assert_nothing_happened(self, item_id, events=()):
        state = self.item_state(item_id)
        self.assertEqual((state["status"], state["copied_to_box_path"], state["linked_document_path"]),
                         ("linked", None, None))
        self.assertEqual([event["event_type"] for event in self.events(item_id)], list(events))


@unittest.skipUnless(os.name == "nt", WINDOWS_ONLY)
class ContainmentTests(PinnedBase):
    def test_bandeja_copy_refuses_a_destination_swapped_after_validation(self):
        escape = self.root / "fuera_h3"
        escape.mkdir()
        item = self.add_item()
        with self.swap_after_validation(self.box / "02 LABORAL" / "Contratos", escape), \
                self.assertRaises(inbox.BoxCopyRejected) as caught:
            self.copy(item, subfolder="02 LABORAL/Contratos", target_filename="Pasaporte Ana")
        self.assertNotIsInstance(caught.exception, inbox.BoxCopyIncomplete)
        self.assertEqual(list(escape.iterdir()), [])
        self.assert_nothing_happened(item)

    def test_an_intermediate_folder_swapped_after_validation_is_refused(self):
        escape = self.root / "fuera_h3"
        (escape / "Sub").mkdir(parents=True)
        item = self.add_item()
        # Bandeja creates the missing folders; the parent is then swapped for a junction.
        with self.swap_after_validation(self.box / "03 NUEVA", escape), \
                self.assertRaises(inbox.BoxCopyRejected):
            self.copy(item, subfolder="03 NUEVA/Sub")
        self.assertEqual(list((escape / "Sub").iterdir()), [])
        self.assert_nothing_happened(item)

    def test_pinned_folders_cannot_be_removed_or_renamed_during_the_copy(self):
        folder = self.box / "02 LABORAL" / "Contratos"
        attempts = {
            "rmdir destino": lambda: self.real["rmdir"](folder),
            "renombrar destino": lambda: self.real["rename"](folder, folder.with_name("Movida")),
            "renombrar intermedia": lambda: self.real["rename"](folder.parent, folder.parent.with_name("Movida")),
            "renombrar raíz": lambda: self.real["rename"](self.box, self.box.with_name("EXP-42-movido")),
            "renombrar padre de la raíz": lambda: self.real["rename"](self.root / "box",
                                                                     self.root / "box_movida"),
        }
        undo = {
            "rmdir destino": lambda: folder.mkdir(),
            "renombrar destino": lambda: self.real["rename"](folder.with_name("Movida"), folder),
            "renombrar intermedia": lambda: self.real["rename"](folder.parent.with_name("Movida"), folder.parent),
            "renombrar raíz": lambda: self.real["rename"](self.box.with_name("EXP-42-movido"), self.box),
            "renombrar padre de la raíz": lambda: self.real["rename"](self.root / "box_movida",
                                                                     self.root / "box"),
        }
        succeeded = []
        real_create = inbox._create_box_copy

        def tamper_then_create(*args):
            for name, attempt in attempts.items():
                try:
                    attempt()
                except OSError:
                    continue
                succeeded.append(name)
                undo[name]()
            return real_create(*args)

        item = self.add_item()
        with patch.object(inbox, "_create_box_copy", tamper_then_create):
            result = self.copy(item, subfolder="02 LABORAL/Contratos")
        self.assertEqual(succeeded, [])
        self.assert_registered(item, result, folder / "Pasaporte.pdf")

    def test_a_folder_that_cannot_be_pinned_refuses_without_writing(self):
        item = self.add_item()
        with patch.object(inbox, "_pin_directory", side_effect=OSError(32, "sharing violation (simulado)")):
            self.assert_refused(item, subfolder="01 IDENTIDAD")


class EngineTests(PinnedBase):
    def track_pin(self):
        """Record that every creation happens while the pin is held."""
        real_pin, real_create, state = inbox._pinned_box_folder, inbox._create_box_copy, {"held": False}
        creations = []

        @contextmanager
        def tracked(root, folder):
            with real_pin(root, folder):
                state["held"] = True
                try:
                    yield
                finally:
                    state["held"] = False

        def create(*args):
            creations.append(state["held"])
            return real_create(*args)

        self.patch(inbox, "_pinned_box_folder", tracked)
        self.patch(inbox, "_create_box_copy", create)
        return creations

    def test_pdf_and_jpg_keep_name_extension_and_original(self):
        creations = self.track_pin()
        pdf = self.add_item(name="Pasaporte.pdf")
        jpg = self.add_item(content=b"\xff\xd8\xff\xe0 foto sintetica", name="Foto.jpg")
        self.assert_registered(pdf, self.copy(pdf, subfolder="02 LABORAL"), self.box / "02 LABORAL" / "Pasaporte.pdf")
        self.assert_registered(jpg, self.copy(jpg, subfolder="02 LABORAL"), self.box / "02 LABORAL" / "Foto.jpg")
        self.assertEqual(creations, [True, True])
        for item_id in (pdf, jpg):
            path, data = self.sources[item_id]
            self.assertEqual(path.read_bytes(), data)  # Bandeja's original stays where it was

    def test_collisions_never_overwrite_and_retries_never_copy_twice(self):
        creations = self.track_pin()
        self.seed(self.box / "01 IDENTIDAD" / "Pasaporte.pdf", b"%PDF otro documento")
        self.protect_box()
        item = self.add_item()
        first = self.copy(item, subfolder="01 IDENTIDAD")
        self.assert_registered(item, first, self.box / "01 IDENTIDAD" / "Pasaporte_2.pdf")
        self.assertEqual(first["box_copy"]["collision_decision"], "renamed")
        again = self.copy(item, subfolder="01 IDENTIDAD")
        self.assertEqual(again["box_copy"]["result"], "already_copied")
        self.assertEqual(creations, [True])
        # Full listing, not a glob: on Windows "Pasaporte*" also matches the fixture's
        # p3b1.EXISTING ("PASAPORTE SOLICITANTE.pdf"), whose bytes and mtime tearDown re-checks.
        self.assertEqual(sorted(p.name for p in (self.box / "01 IDENTIDAD").iterdir()),
                         sorted(["PASAPORTE SOLICITANTE.pdf", "Pasaporte.pdf", "Pasaporte_2.pdf"]))
        self.assertEqual((self.box / p3b1.EXISTING).read_bytes(), b"%PDF existente en Box")

    def test_a_failed_write_is_kept_unregistered_and_the_retry_uses_a_new_name(self):
        item = self.add_item()
        self.write_limit = 4
        with self.assertRaises(inbox.BoxCopyIncomplete) as caught:
            self.copy(item, subfolder="02 LABORAL")
        self.assertEqual(caught.exception.stage, "write")
        partial = self.box / "02 LABORAL" / "Pasaporte.pdf"
        self.assertEqual(caught.exception.written_path, str(partial))
        self.assert_nothing_happened(item, ["copy_to_box_failed"])
        self.write_limit = None
        result = self.copy(item, subfolder="02 LABORAL")
        self.assert_registered(item, result, self.box / "02 LABORAL" / "Pasaporte_2.pdf")
        self.assertEqual(partial.read_bytes(), b"")  # never deleted nor overwritten

    def test_a_failed_register_keeps_the_verified_copy_and_the_retry_registers_it(self):
        item = self.add_item()
        with patch.object(inbox, "_register_box_copy",
                          side_effect=sqlite3.OperationalError("database is locked (simulado)")), \
                self.assertRaises(inbox.BoxCopyIncomplete) as caught:
            self.copy(item)
        self.assertEqual(caught.exception.stage, "register")
        self.assert_nothing_happened(item, ["copy_to_box_failed"])
        result = self.copy(item)
        self.assert_registered(item, result, self.box / "Pasaporte.pdf")
        self.assertEqual((result["box_copy"]["collision_decision"], result["box_copy"]["provenance"]),
                         ("reused_identical", "own_unregistered_copy"))

    def test_destinations_outside_the_root_or_through_links_are_refused(self):
        self.make_dir_link(self.outside, self.box / "salida")
        self.protect_box()
        item = self.add_item()
        for subfolder in ("salida", "salida/secreta", "..", "../fuera", str(self.outside)):
            with self.subTest(subfolder=subfolder):
                self.assert_refused(item, subfolder=subfolder)


if __name__ == "__main__":
    unittest.main()
