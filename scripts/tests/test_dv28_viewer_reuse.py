"""WO-DV28-CIERRE: one Box copy engine, two entry points (Bandeja and the viewer).

The viewer's archive service calls ``document_inbox_service.copy_inbox_item_to_expedient_box``
exactly as Bandeja does, without the DV27 permission contract or persistent request store. It
keeps the reviewed destination (client, expediente, folder, nomenclature), the explicit consent,
the per-document revalidation, the double-click guard and the check of the engine's answer.

- ``EntryPointTests`` read the REAL code: one engine call per entry point, none in the dialog,
  gate closed.
- ``ViewerReuseTests`` run on the certified P3B2 sandbox (``ArchiveBase``: TemporaryDirectory,
  synthetic CRM/Bandeja/Box compared byte for byte, engine FOR REAL behind a spy, habitual
  ``quesada.db`` untouched): PDF and JPG, name and folder, original and pre-existing files
  intact, consent, replays, write and register failures, closed gate, Bandeja then viewer.
- ``BandejaButtonTests`` press Bandeja's real «Copiar a Box expediente» handler (DV25-C2 sandbox)
  with the viewer gate closed: Bandeja keeps working, PDF and JPG.

No real Box, Drive or CRM data is reached.
"""
import ast
import copy
import hashlib
import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import document_inbox_service
from backend.services import document_viewer_box_archive_service as archive
from scripts.tests import test_document_viewer_dv24_linking as dv24
from scripts.tests import test_document_viewer_dv25_box_from_viewer as p3b2
from scripts.tests import test_dv25_bandeja_compat as compat


SERVICE = p3b2.SERVICE
DIALOG = p3b2.ARCHIVE_DIALOG
REAL_COPY = p3b2.REAL_COPY
K = p3b2.K
NAME = "PASAPORTE SOLICITANTE"  # K[0]
JPG = b"\xff\xd8\xff\xe0 foto sintetica DV28"
ENGINE = "copy_inbox_item_to_expedient_box"
ENV = "QUESADA_VIEWER_BOX_COPY_ENABLED"


def without_env():
    """os.environ without the gate variable, whatever the shell running the tests has set."""
    return {key: value for key, value in os.environ.items() if key != ENV}


def engine_calls(path):
    return [node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == ENGINE]


class EntryPointTests(unittest.TestCase):
    def test_one_engine_two_entry_points(self):
        bandeja, viewer = engine_calls(dv24.INBOX), engine_calls(SERVICE)
        self.assertEqual((len(bandeja), len(viewer)), (1, 1))
        for call in (*bandeja, *viewer):
            self.assertEqual(getattr(call.func.value, "id", None), "document_inbox_service")
        # Same function, different naming input: Bandeja a free name, the viewer a catalog key.
        self.assertEqual({keyword.arg for keyword in viewer[0].keywords},
                         {"expedient_id", "subfolder", "nomenclature_key"})
        self.assertEqual(engine_calls(DIALOG), [])
        self.assertNotIn("document_inbox_service", DIALOG.read_text(encoding="utf-8"))

    def test_gate_closed_and_no_dv27_layer_on_the_viewer_path(self):
        self.assertIs(archive.EXECUTION_ENABLED, False)
        with patch.dict(os.environ, without_env(), clear=True):
            self.assertEqual(archive.execution_blocker(), archive.EXECUTION_DISABLED)
        modules = dv24.imported_modules(SERVICE)
        self.assertNotIn("backend.services.document_viewer_archive_permission_service", modules)
        self.assertNotIn("backend.services.document_viewer_archive_repository", modules)


class EnvGateTests(unittest.TestCase):
    """DV28-GATE-FIX: QUESADA_VIEWER_BOX_COPY_ENABLED opens the gate only with exactly "1"."""

    def blocker(self, value):
        env = without_env() if value is None else {**without_env(), ENV: value}
        with patch.object(archive, "EXECUTION_ENABLED", False), patch.dict(os.environ, env, clear=True):
            return archive.execution_blocker()

    def test_only_exactly_one_opens_the_gate(self):
        for value in (None, "0", "true", "True", "yes", "", " 1", "1 ", "01"):
            with self.subTest(value=value):
                self.assertEqual(self.blocker(value), archive.EXECUTION_DISABLED)
        self.assertEqual(self.blocker("1"), "")

    def test_read_at_runtime_not_at_import(self):
        with patch.object(archive, "EXECUTION_ENABLED", False):
            with patch.dict(os.environ, {**without_env(), ENV: "1"}, clear=True):
                self.assertEqual(archive.execution_blocker(), "")
            with patch.dict(os.environ, without_env(), clear=True):
                self.assertEqual(archive.execution_blocker(), archive.EXECUTION_DISABLED)

    def test_code_flag_still_opens_it_and_h3_stays_unverified(self):
        with patch.object(archive, "EXECUTION_ENABLED", True), patch.dict(os.environ, without_env(), clear=True):
            self.assertEqual(archive.execution_blocker(), "")
        self.assertIs(archive.H3_WRITE_CONTAINMENT_VERIFIED, False)
        with patch.dict(os.environ, {**without_env(), ENV: "1"}, clear=True):
            self.assertEqual(archive.activation_blockers(), (archive.TOCTOU_PREVENTION_PENDING,))


class ViewerReuseTests(p3b2.ArchiveBase):
    def jpg_document(self):
        """Bandeja item 4 becomes a JPG linked to client 7 / expediente 42 (synthetic)."""
        path = self.root / "inbox" / "4_Foto.jpg"
        path.write_bytes(JPG)
        self.execute("UPDATE document_inbox_items SET stored_path = ?, stored_filename = ?, "
                     "original_filename = 'Foto.jpg', sha256 = ?, status = 'linked', client_id = 7, "
                     "expedient_id = 42 WHERE id = 4", (str(path), path.name, hashlib.sha256(JPG).hexdigest()))
        return {"key": "inbox:4", "name": "Foto.jpg", "path": str(path), "inbox_item_id": 4}

    def prepare_documents(self, documents, *, folder, choices):
        return archive.prepare_archive(self.actor, documents, client_id=7, expedient_id=42, folder=folder,
                                       choices=choices, db_path=self.db)

    # ------------------------------------------------------------------ copy

    def test_pdf_and_jpg_are_copied_once_with_their_name_folder_and_extension(self):
        jpg = self.jpg_document()
        source_pdf = self.inbox_docs[6]
        before = {6: (source_pdf.read_bytes(), source_pdf.stat().st_mtime_ns, self.row(6)["stored_path"]),
                  4: (JPG, Path(jpg["path"]).stat().st_mtime_ns, self.row(4)["stored_path"])}
        plan = self.prepare_documents([self.doc(6), jpg], folder="02 LABORAL",
                                      choices={"inbox:6": K[0], "inbox:4": K[2]})
        self.assertEqual([item.proposed_name for item in plan.ready],
                         [f"{NAME}.pdf", "PASAPORTE FAMILIAR.jpg"])
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED), (4, archive.ARCHIVED)])
        self.assertEqual([(item.final_name, item.destination) for item in result.items], [
            (f"{NAME}.pdf", f"02 LABORAL/{NAME}.pdf"),
            ("PASAPORTE FAMILIAR.jpg", "02 LABORAL/PASAPORTE FAMILIAR.jpg")])
        self.assertEqual([call.kwargs for call in self.copy.call_args_list], [
            {"expedient_id": 42, "subfolder": "02 LABORAL", "nomenclature_key": K[0]},
            {"expedient_id": 42, "subfolder": "02 LABORAL", "nomenclature_key": K[2]}])
        self.assert_added(tree, {f"EXP-42/02 LABORAL/{NAME}.pdf": ("file", self.source(6)),
                                 "EXP-42/02 LABORAL/PASAPORTE FAMILIAR.jpg": ("file", JPG)})
        for item_id, path in ((6, source_pdf), (4, Path(jpg["path"]))):
            data, mtime, stored = before[item_id]
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (data, mtime))  # original intact
            row = self.row(item_id)
            self.assertEqual((row["status"], row["stored_path"], row["client_id"], row["expedient_id"]),
                             ("copied_to_box", stored, 7, 42))
            self.assertEqual([event["event_type"] for event in self.events(item_id)], ["copied_to_box"])

    def test_existing_file_is_kept_intact_and_the_copy_gets_the_next_name(self):
        existing = self.box / "01 IDENTIDAD" / f"{NAME}.pdf"
        data = existing.read_bytes()
        plan = self.prepare([6], folder="01 IDENTIDAD", choices={"inbox:6": K[0]})
        self.assertEqual(plan.ready[0].proposed_name, f"{NAME}_2.pdf")
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        self.assertEqual((result.items[0].final_name, result.items[0].collision), (f"{NAME}_2.pdf", "renamed"))
        self.assertEqual(existing.read_bytes(), data)
        self.assert_added(tree, {f"EXP-42/01 IDENTIDAD/{NAME}_2.pdf": ("file", self.source(6))})

    # ------------------------------------------------------------------ consent and replays

    def test_confirmation_is_mandatory_and_bound_to_the_review(self):
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        before = self.snapshot()
        for confirmed in (False, None, "sí", 1):
            with self.subTest(confirmed=confirmed), self.assertRaises(archive.ArchiveError) as raised:
                archive.execute_archive(plan, confirmed=confirmed, fingerprint=plan.fingerprint)
            self.assertEqual(str(raised.exception), archive.NOT_CONFIRMED)
        for fingerprint in (None, "", "0" * 64):
            with self.subTest(fingerprint=fingerprint), self.assertRaises(archive.ArchiveError) as raised:
                archive.execute_archive(plan, confirmed=True, fingerprint=fingerprint)
            self.assertEqual(str(raised.exception), archive.STALE_CONSENT)
        self.assertIsNone(plan.result)
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()

    def test_repeated_requests_never_copy_again(self):
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        twin = copy.copy(plan)
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
            self.assertIs(self.run_plan(plan), result)  # double click: same result
        with self.assertRaises(archive.ArchiveError) as raised:
            self.run_plan(twin)  # the same review handed around
        self.assertEqual(str(raised.exception), archive.REPLAYED)
        again = self.prepare([6], folder="", choices={"inbox:6": K[0]})  # a new review
        self.assertEqual((again.ready, again.items[0].message), ((), archive.ALREADY_COPIED))
        self.assertEqual(self.copy.call_count, 1)
        self.assert_added(tree, {f"EXP-42/{NAME}.pdf": ("file", self.source(6))})
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])

    # ------------------------------------------------------------------ failures

    def test_write_failure_keeps_the_partial_file_and_stops_the_batch(self):
        self.link_items(1)

        def partial(src, handle):
            handle.write(b"%PDF parcial")
            raise OSError(28, "disco lleno (simulado)")

        plan = self.prepare([6, 1], folder="", choices={"inbox:6": K[0], "inbox:1": K[1]})
        tree = self.tree()
        with patch.object(document_inbox_service, "_stream_into", partial), self.guard():
            result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.INCOMPLETE), (1, archive.NOT_ATTEMPTED)])
        self.assertIn("Requiere revisión humana", result.items[0].message)
        self.assertEqual(Path(result.items[0].written_path).resolve(), (self.box / f"{NAME}.pdf").resolve())
        self.assertEqual(self.copied_ids(), [6])
        self.assertEqual((self.row(6)["status"], self.row(6)["copied_to_box_path"]), ("linked", None))
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copy_to_box_failed"])
        self.assert_added(tree, {f"EXP-42/{NAME}.pdf": ("file", b"%PDF parcial")})  # never deleted
        # A new review never overwrites the partial file.
        tree = self.tree()
        with self.guard():
            retry = self.run_plan(self.prepare([6], folder="", choices={"inbox:6": K[0]}))
        self.assertEqual((retry.items[0].status, retry.items[0].final_name), (archive.ARCHIVED, f"{NAME}_2.pdf"))
        self.assert_added(tree, {f"EXP-42/{NAME}_2.pdf": ("file", self.source(6))})

    def test_register_failure_keeps_the_verified_copy_and_a_new_review_registers_it_once(self):
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        tree = self.tree()
        with patch.object(document_inbox_service, "_register_box_copy",
                          side_effect=sqlite3.OperationalError("database is locked (simulado)")), self.guard():
            result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.INCOMPLETE)])
        self.assertEqual(self.row(6)["status"], "linked")
        self.assert_added(tree, {f"EXP-42/{NAME}.pdf": ("file", self.source(6))})
        tree = self.tree()
        with self.guard():
            retry = self.run_plan(self.prepare([6], folder="", choices={"inbox:6": K[0]}))
        outcome, = retry.items
        self.assertEqual((outcome.status, outcome.final_name, outcome.collision),
                         (archive.ARCHIVED, f"{NAME}.pdf", "reused_identical"))
        self.assertNotIn("No lo creó esta operación", outcome.message)  # its own unregistered copy
        self.assert_added(tree, {})
        self.assertEqual([event["event_type"] for event in self.events(6)],
                         ["copy_to_box_failed", "copied_to_box"])

    def test_unexpected_engine_error_is_a_failure_not_a_success(self):
        self.copy.side_effect = RuntimeError("fallo inesperado (simulado)")
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        tree = self.tree()
        result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.FAILED)])
        self.assertFalse(result.complete)
        self.assertEqual(self.tree(), tree)

    # ------------------------------------------------------------------ gate and validation

    def test_closed_gate_copies_nothing(self):
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        before = self.snapshot()
        with patch.object(archive, "EXECUTION_ENABLED", False), patch.dict(os.environ, without_env(), clear=True), \
                self.assertRaises(archive.ArchiveError) as raised:
            self.run_plan(plan)
        self.assertEqual(str(raised.exception), archive.EXECUTION_DISABLED)
        self.assertIsNone(plan.result)
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()

    def test_env_gate_blocks_every_value_but_one_without_writing(self):
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        before = self.snapshot()
        for value in (None, "0", "true"):
            env = without_env() if value is None else {**without_env(), ENV: value}
            with self.subTest(value=value), patch.object(archive, "EXECUTION_ENABLED", False), \
                    patch.dict(os.environ, env, clear=True), self.assertRaises(archive.ArchiveError) as raised:
                self.run_plan(plan)
            self.assertEqual(str(raised.exception), archive.EXECUTION_DISABLED)
        self.assertIsNone(plan.result)
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()

    def test_env_gate_one_copies_once_with_bandejas_engine_inside_the_sandbox(self):
        plan = self.prepare([6], folder="02 LABORAL", choices={"inbox:6": K[0]})
        source = self.inbox_docs[6]
        data, mtime = source.read_bytes(), source.stat().st_mtime_ns
        tree = self.tree()
        with patch.object(archive, "EXECUTION_ENABLED", False), \
                patch.dict(os.environ, {**without_env(), ENV: "1"}, clear=True), self.guard():
            result = self.run_plan(plan)
            self.assertIs(self.run_plan(plan), result)  # double execution: same result, no new copy
            again = self.prepare([6], folder="02 LABORAL", choices={"inbox:6": K[0]})
            self.assertEqual((again.ready, again.items[0].message), ((), archive.ALREADY_COPIED))
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED)])
        # Bandeja's real engine (spy wrapping REAL_COPY), called once with the reviewed destination.
        self.assertIs(self.copy._mock_wraps, REAL_COPY)
        self.assertEqual(self.copy.call_count, 1)
        self.assertEqual(self.copy.call_args.kwargs,
                         {"expedient_id": 42, "subfolder": "02 LABORAL", "nomenclature_key": K[0]})
        self.assert_added(tree, {f"EXP-42/02 LABORAL/{NAME}.pdf": ("file", self.source(6))})
        # The copy lands in the temporary Box of the sandbox, never in the real one.
        written = Path(self.row(6)["copied_to_box_path"]).resolve()
        self.assertEqual(written, (self.box / "02 LABORAL" / f"{NAME}.pdf").resolve())
        self.assertTrue(written.is_relative_to(self.root.resolve()))
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), (data, mtime))  # original intact

    def test_document_expediente_and_folder_are_validated(self):
        before = self.snapshot()
        plan = self.prepare([6, 4, 1], folder="", choices={f"inbox:{i}": K[0] for i in (6, 4, 1)})
        self.assertEqual([(item.inbox_item_id, item.outcome, item.message) for item in plan.items[1:]],
                         [(4, archive.REJECTED, archive.OTHER_TARGET), (1, archive.REJECTED, archive.NOT_LINKED)])
        for folder in ("../fuera", str(self.root / "fuera"), "C:/Windows", "\\\\servidor\\box", "no-existe"):
            with self.subTest(folder=folder):
                plan = self.prepare([6], folder=folder, choices={"inbox:6": K[0]})
                self.assertEqual((plan.folder, plan.ready), (None, ()))
        with self.assertRaises(archive.ArchiveError):
            self.prepare([6], client_id=8, expedient_id=42, folder="")
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()

    # ------------------------------------------------------------------ both entry points

    def test_a_copy_made_from_bandeja_is_not_repeated_from_the_viewer(self):
        tree = self.tree()
        with patch.object(archive, "EXECUTION_ENABLED", False):  # the viewer gate is not on Bandeja's path
            updated = document_inbox_service.copy_inbox_item_to_expedient_box(
                6, expedient_id=42, subfolder="02 LABORAL", target_filename="Pasaporte Bandeja")
        self.assertEqual(updated["status"], "copied_to_box")
        self.assert_added(tree, {"EXP-42/02 LABORAL/Pasaporte Bandeja.pdf": ("file", self.source(6))})
        inspection = archive.inspect_archive(self.actor, [self.doc(6)], db_path=self.db)
        self.assertEqual((inspection.items[0].outcome, inspection.items[0].message),
                         (archive.REJECTED, archive.ALREADY_COPIED))
        self.assertEqual(self.copy.call_count, 1)


class BandejaButtonTests(compat.BandejaCompatBase):
    """Bandeja's real button, with the viewer gate closed in the code (checked in tearDown)."""

    def test_bandeja_still_copies_pdf_and_jpg_once(self):
        pdf = self.add_item(name="Pasaporte.pdf")
        jpg = self.add_item(content=JPG, name="Foto.jpg")
        self.assert_registered(pdf, self.press(pdf, subfolder="02 LABORAL"), self.box / "02 LABORAL" / "Pasaporte.pdf")
        self.assert_registered(jpg, self.press(jpg, subfolder="02 LABORAL"), self.box / "02 LABORAL" / "Foto.jpg")
        tree = self.tree()
        self.assertEqual(self.press(jpg, subfolder="02 LABORAL")["box_copy"]["result"], "already_copied")
        self.assertEqual(self.tree(), tree)
        for item_id in (pdf, jpg):
            path, data = self.sources[item_id]
            self.assertEqual(path.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
