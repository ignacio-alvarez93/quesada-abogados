"""WO-DV27-P3B4, adapted by WO-DV28-CIERRE: governed "Archivar copia en Box" from the viewer.

DV28-CIERRE replaced two DV27 architectural assumptions: the viewer no longer asks the permission
contract (H1) nor runs the copy inside a persistent request (H2). It calls Bandeja's engine
``copy_inbox_item_to_expedient_box`` directly, as Bandeja does. The DV27 functional guarantees
are kept and still proven here on the certified P3B2 sandbox (``ArchiveBase``): synthetic CRM and
Bandeja in a TemporaryDirectory, synthetic Box tree compared byte for byte in tearDown, the
engine running FOR REAL behind a spy, the habitual ``quesada.db`` checked untouched.

- ``GateTests`` / ``ScopeTests`` read the REAL code: gate OFF, H3 real check pending, one physical
  copy call, no H1/H2 dependency left in the viewer.
- ``SessionTests`` (verified session user), ``ReplayTests`` (double click, parallel operations),
  ``CrashTests`` (crash before/during/after COPY, VERIFY, REGISTER: nothing deleted, nothing
  overwritten, registered once), ``SafetyTests`` (collision, expiry, H3 swap, boundedness) and
  ``ViewerTests`` (the dialog shows the reason and never copies while blocked).

No real Box, Drive or CRM data is reached.
"""
import ast
import os
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from backend.services import document_inbox_service
from backend.services import document_viewer_box_archive_service as archive
from backend.services import document_viewer_filing_plan_service as filing
from scripts.tests import test_document_viewer_dv24_linking as dv24
from scripts.tests import test_document_viewer_dv25_box_from_viewer as p3b2
from scripts.tests import test_document_viewer_dv25_filing_plan as p3a


SERVICE = p3b2.SERVICE
PERMISSION = dv24.REPO_ROOT / "backend" / "services" / "document_viewer_archive_permission_service.py"
REPOSITORY = dv24.REPO_ROOT / "backend" / "services" / "document_viewer_archive_repository.py"
REAL_COPY = p3b2.REAL_COPY
K = p3b2.K
NAME = "PASAPORTE SOLICITANTE.pdf"  # K[0] for item 6
SCANS = {"rglob", "glob", "walk", "scandir", "listdir", "iterdir"}


def literal_assignments(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.value.value for node in tree.body if isinstance(node, ast.Assign)
            and any(getattr(target, "id", None) == name for target in node.targets)]


def link_dir(target, link):
    """Directory symlink if allowed, otherwise an NTFS junction (no privilege needed)."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
        import _winapi
        _winapi.CreateJunction(str(target), str(link))


def unlink_dir(link):
    (os.rmdir if os.name == "nt" else os.unlink)(link)


class Crash(BaseException):
    """Simulated process death: not an Exception, nothing in the service catches it."""


def crashing(*args, **kwargs):
    raise Crash()


# ---------------------------------------------------------------------- real code


class GateTests(unittest.TestCase):
    def test_gate_and_the_real_box_check_are_closed_in_the_code(self):
        self.assertEqual(literal_assignments(SERVICE, "EXECUTION_ENABLED"), [False])
        self.assertEqual(literal_assignments(SERVICE, "H3_WRITE_CONTAINMENT_VERIFIED"), [False])
        self.assertIs(archive.EXECUTION_ENABLED, False)
        self.assertEqual(archive.activation_blockers(), (archive.TOCTOU_PREVENTION_PENDING,))
        self.assertEqual(archive.execution_blocker(), archive.EXECUTION_DISABLED)
        self.assertIn(archive.TOCTOU_PREVENTION_PENDING, archive.EXECUTION_DISABLED)
        # The DV27 modules are no longer on the viewer's path, and still grant nothing by themselves.
        self.assertEqual(literal_assignments(PERMISSION, "APPROVED_CONTRACT"), [None])
        self.assertEqual(literal_assignments(REPOSITORY, "MULTI_HOST_GUARANTEE"), [False])

    def test_only_exactly_true_opens_the_gate(self):
        for value in (False, None, 1, "True"):
            with self.subTest(gate=value), patch.object(archive, "EXECUTION_ENABLED", value):
                self.assertEqual(archive.execution_blocker(), archive.EXECUTION_DISABLED)
        with patch.object(archive, "EXECUTION_ENABLED", True):
            self.assertEqual(archive.execution_blocker(), "")
        with patch.object(archive, "H3_WRITE_CONTAINMENT_VERIFIED", "True"):
            self.assertEqual(archive.activation_blockers(), (archive.TOCTOU_PREVENTION_PENDING,))
        with patch.object(archive, "H3_WRITE_CONTAINMENT_VERIFIED", True):
            self.assertEqual(archive.activation_blockers(), ())


class ScopeTests(unittest.TestCase):
    def test_one_physical_copy_through_bandejas_engine_without_dv27_layers(self):
        tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        copies = [node for node in calls if node.func.attr == "copy_inbox_item_to_expedient_box"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(getattr(copies[0].func.value, "id", None), "document_inbox_service")
        modules = dv24.imported_modules(SERVICE)
        for replaced in ("backend.services.document_viewer_archive_permission_service",
                         "backend.services.document_viewer_archive_repository"):
            self.assertNotIn(replaced, modules)
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertTrue(any(node in copies for node in ast.walk(functions["_certified_copy"])))
        # The gate is checked before any document is copied; each copy only after its claim.
        lines = {node.func.id: node.lineno for node in ast.walk(functions["execute_archive"])
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertLess(lines["execution_blocker"], lines["_execute_one"])
        lines = {node.func.id: node.lineno for node in ast.walk(functions["_execute_one"])
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertLess(lines["read_document"], lines["_certified_copy"])
        self.assertLess(lines["_claim"], lines["_certified_copy"])
        # No recursive or massive exploration from the viewer's operation.
        self.assertEqual(p3a.called_names(SERVICE) & SCANS, set())


# ---------------------------------------------------------------------- sandbox


class ActivationBase(p3b2.ArchiveBase):
    def plan6(self, folder="", actor="default"):
        return self.prepare([6], folder=folder, choices={"inbox:6": K[0]}, actor=actor)

    def assert_refused(self, plan, message):
        with self.assertRaises(archive.ArchiveError) as raised:
            self.run_plan(plan)
        self.assertEqual(str(raised.exception), message)
        self.assertIsNone(plan.result)


# ---------------------------------------------------------------------- session (was H1)


class SessionTests(ActivationBase):
    def test_missing_forged_or_inactive_actor_copies_nothing(self):
        plan = self.plan6()
        before = self.snapshot()
        claims = {"id": 1, "username": "luis", "role": "admin", "is_admin": True, "permissions": ["archive_box"]}
        for name, actor in (("no actor", None), ("forged", {"id": 1, "username": "luis"}),
                            ("unknown", {"id": 99, "username": "nadie"}), ("client claims", claims)):
            with self.subTest(name), self.assertRaises(archive.ArchiveError):
                self.run_plan(replace(plan, actor=actor, token=uuid4().hex))
        self.execute("UPDATE users SET is_active = 0 WHERE id = 1")
        self.assert_refused(plan, archive.NOT_AUTHORIZED)
        self.copy.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_the_verified_user_archives_once_and_is_reported(self):
        before_row = self.row(6)
        plan = self.plan6()
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED)])
        self.assertEqual(result.user, {"id": 1, "username": "ana"})
        self.copy.assert_called_once_with(6, expedient_id=42, subfolder="", nomenclature_key=K[0])
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})
        row = self.row(6)
        self.assertEqual((row["status"], row["client_id"], row["expedient_id"]), ("copied_to_box", 7, 42))
        self.assertEqual(row["stored_path"], before_row["stored_path"])
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])


# ---------------------------------------------------------------------- replays (was H2)


class ReplayTests(ActivationBase):
    def test_double_click_and_a_new_review_never_copy_twice(self):
        plan = self.plan6()
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
            self.assertIs(self.run_plan(plan), result)  # double click
        self.assertEqual(self.copy.call_count, 1)
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])
        again = archive.inspect_archive(self.actor, [self.doc(6)], db_path=self.db)
        self.assertEqual(again.items[0].message, archive.ALREADY_COPIED)
        # The viewer never creates the DV27 request table.
        self.assertNotIn("document_viewer_archive_intents", [row["name"] for row in self.schema()])

    def test_parallel_operations_without_the_viewer_guard_copy_once(self):
        # Two operations of this process past the viewer's in-memory guard: Bandeja's own per-item
        # lock serialises them and the second one finds the copy already registered.
        self.patch(archive, "_claim", lambda item_id: True)
        self.patch(archive, "_release", lambda item_id: None)
        first, second = self.plan6(), self.plan6()
        entered, second_in, release, results = threading.Event(), threading.Event(), threading.Event(), {}
        real_create = document_inbox_service._create_box_copy

        def slow(*args):
            entered.set()
            release.wait(10)
            return real_create(*args)

        def counted(item_id, **kwargs):
            if self.copy.call_count == 2:
                second_in.set()  # the second operation reached the engine before the first registers
            return REAL_COPY(item_id, **kwargs)

        creations = self.patch(document_inbox_service, "_create_box_copy", side_effect=slow)
        self.copy.side_effect = counted
        tree = self.tree()
        workers = [threading.Thread(target=lambda: results.setdefault("first", self.run_plan(first)))]
        workers[0].start()
        try:
            self.assertTrue(entered.wait(10))
            workers.append(threading.Thread(target=lambda: results.setdefault("second", self.run_plan(second))))
            workers[1].start()
            self.assertTrue(second_in.wait(10))
        finally:
            release.set()
            for worker in workers:
                worker.join(10)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(self.outcomes(results["first"]), [(6, archive.ARCHIVED)])
        self.assertEqual(self.outcomes(results["second"]), [(6, archive.REJECTED)])
        self.assertEqual(results["second"].items[0].message, archive.ALREADY_COPIED)
        self.assertEqual(creations.call_count, 1)
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])


# ---------------------------------------------------------------------- crashes


class CrashTests(ActivationBase):
    def crash(self, target, effect):
        plan = self.plan6()
        tree = self.tree()
        with patch.object(document_inbox_service, target, effect), self.guard(), self.assertRaises(Crash):
            self.run_plan(plan)
        # The interrupted review is spent: it is never replayed.
        self.assert_refused(plan, archive.REPLAYED)
        return tree

    def retry(self):
        with self.guard():
            return self.run_plan(self.plan6())

    def test_crash_before_copy_writes_nothing_and_a_new_review_copies_once(self):
        tree = self.crash("_create_box_copy", crashing)
        self.assertEqual(self.tree(), tree)
        self.assertEqual((self.row(6)["status"], self.events(6)), ("linked", []))
        result = self.retry()
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED)])
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})

    def test_crash_during_copy_keeps_the_partial_file_and_never_overwrites_it(self):
        def partial(src, handle):
            handle.write(b"%PDF parcial")
            raise Crash()

        tree = self.crash("_stream_into", partial)
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", b"%PDF parcial")})  # never deleted
        self.assertEqual(self.row(6)["status"], "linked")
        tree = self.tree()
        result = self.retry()
        self.assertEqual((result.items[0].status, result.items[0].final_name),
                         (archive.ARCHIVED, "PASAPORTE SOLICITANTE_2.pdf"))
        self.assert_added(tree, {"EXP-42/PASAPORTE SOLICITANTE_2.pdf": ("file", self.source(6))})

    def test_crash_between_verify_and_register_is_registered_once_without_another_file(self):
        tree = self.crash("_register_box_copy", crashing)
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})
        self.assertEqual(self.row(6)["status"], "linked")
        tree = self.tree()
        result = self.retry()
        outcome, = result.items
        self.assertEqual((outcome.status, outcome.final_name, outcome.collision),
                         (archive.ARCHIVED, NAME, "reused_identical"))
        self.assert_added(tree, {})
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])

    def test_crash_after_register_is_already_copied(self):
        real = document_inbox_service._register_box_copy

        def registered_then_crash(*args):
            real(*args)
            raise Crash()

        tree = self.crash("_register_box_copy", registered_then_crash)
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})
        self.assertEqual(self.row(6)["status"], "copied_to_box")
        again = archive.inspect_archive(self.actor, [self.doc(6)], db_path=self.db)
        self.assertEqual((again.items[0].outcome, again.items[0].message), (archive.REJECTED, archive.ALREADY_COPIED))
        self.assertEqual(self.copy.call_count, 1)
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])


# ---------------------------------------------------------------------- destination safety


class SafetyTests(ActivationBase):
    def test_collision_keeps_the_existing_file_and_creates_exactly_one_copy(self):
        plan = self.plan6(folder="01 IDENTIDAD")
        self.assertEqual(plan.ready[0].proposed_name, "PASAPORTE SOLICITANTE_2.pdf")
        creations = self.patch(document_inbox_service, "_create_box_copy",
                               wraps=document_inbox_service._create_box_copy)
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        self.assertEqual((result.items[0].status, result.items[0].final_name, result.items[0].collision),
                         (archive.ARCHIVED, "PASAPORTE SOLICITANTE_2.pdf", "renamed"))
        self.assertEqual(creations.call_count, 1)
        # The homonym keeps its bytes (assert_added compares every previous entry).
        self.assert_added(tree, {"EXP-42/01 IDENTIDAD/PASAPORTE SOLICITANTE_2.pdf": ("file", self.source(6))})

    def test_an_expired_review_needs_a_new_confirmation(self):
        plan = self.plan6()
        old = replace(plan, created=plan.created - archive.REVIEW_MAX_AGE - 1, token=uuid4().hex)
        self.assert_refused(old, archive.EXPIRED)
        self.copy.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "H3 prevention pins folders with Win32 handles (Windows only)")
    def test_h3_folder_swap_is_refused_before_any_write(self):
        """H3 (DV28): the shared Bandeja engine pins the folder; nothing is written anywhere."""
        escape = self.root / "fuera_toctou"
        escape.mkdir()
        folder = self.box / "02 LABORAL" / "Contratos"
        real_folder = document_inbox_service._box_destination_folder

        def validated_then_swapped(root, relative, create_missing=True):
            result = real_folder(root, relative, create_missing)
            os.rmdir(folder)
            link_dir(escape, folder)
            return result

        plan = self.plan6(folder="02 LABORAL/Contratos")
        self.patch(document_inbox_service, "_box_destination_folder", validated_then_swapped)
        try:
            result = self.run_plan(plan)
        finally:
            if os.path.lexists(folder) and filing._redirects(folder):
                unlink_dir(folder)
            if not os.path.lexists(folder):
                folder.mkdir()
        self.assertEqual(result.items[0].status, archive.REJECTED)
        self.assertEqual(list(escape.iterdir()), [])
        row = self.row(6)
        self.assertEqual((row["status"], row["copied_to_box_path"]), ("linked", None))
        self.assertEqual(self.events(6), [])
        # Prevention passes in the sandbox; the real path stays blocked until the supervised
        # Windows/Box Drive check and an independent authorization.
        self.assertIn(archive.TOCTOU_PREVENTION_PENDING, archive.activation_blockers())

    def test_execution_is_bounded_and_stays_inside_the_expediente_root(self):
        real_iterdir = Path.iterdir
        listed = []

        def counted(path):
            listed.append(Path(path))
            return real_iterdir(path)

        def forbidden(*args, **kwargs):
            raise AssertionError("recursive scan")

        tree = self.tree()
        with patch.object(Path, "iterdir", counted), patch.object(Path, "rglob", forbidden), \
                patch.object(Path, "glob", forbidden), patch.object(os, "walk", forbidden), self.guard():
            plan = self.plan6(folder="02 LABORAL")
            result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED)])
        root = self.box.resolve()
        self.assertTrue(listed)
        self.assertLessEqual(len(listed), 2 * (filing.MAX_FOLDERS + 1))
        for path in listed:
            resolved = path.resolve()
            self.assertTrue(resolved == root or root in resolved.parents, path)
        self.assert_added(tree, {f"EXP-42/02 LABORAL/{NAME}": ("file", self.source(6))})


# ---------------------------------------------------------------------- viewer


class ViewerTests(ActivationBase):
    def test_while_blocked_the_dialog_shows_the_reason_and_copies_nothing(self):
        dialog = self.open_inbox([6, 1])
        before = self.snapshot()
        with self.guard(), patch.object(archive, "EXECUTION_ENABLED", False):
            form = self.open_archive(dialog)
            reason = archive.EXECUTION_DISABLED
            self.assertEqual(form.blocker, reason)
            self.assertIn(reason, self.texts(form.dialog))
            self.assertEqual(form.submit_button.tooltip, reason)
            self.choose(form.folder_select, filing.ROOT_LABEL)
            self.choose(form.nomenclature_selects["inbox:6"], "PASAPORTE · SOLICITANTE")
            # The review (destination and projected name) is still shown; the consent is not taken.
            self.assertEqual([item.proposed_name for item in form.plan.ready], [NAME])
            self.assertTrue(form.confirm.disabled)
            self.confirm(form)
            self.assertIsNone(form.consented)
            self.assertTrue(form.submit_button.disabled)
            self.assertIsNone(form.submit())
            form.close()
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)

    def test_when_available_the_dialog_shows_destination_name_and_the_real_result(self):
        dialog = self.open_inbox([6, 1])
        tree = self.tree()
        with self.guard():
            form = self.open_archive(dialog)
            self.assertEqual(form.blocker, "")
            self.choose(form.folder_select, "01 IDENTIDAD")
            self.choose(form.nomenclature_selects["inbox:6"], "PASAPORTE · SOLICITANTE")
            self.assertEqual([item.proposed_name for item in form.plan.ready], ["PASAPORTE SOLICITANTE_2.pdf"])
            self.confirm(form)
            form.submit_button.on_click(None)
            form.submit_button.on_click(None)  # double click
        self.assertTrue(form.result.complete)
        line = form.review_column.controls[1].value
        self.assertIn("«PASAPORTE SOLICITANTE_2.pdf»", line)
        self.assertIn("Destino: 01 IDENTIDAD/PASAPORTE SOLICITANTE_2.pdf.", line)
        self.assertEqual(self.copy.call_count, 1)
        self.assert_added(tree, {"EXP-42/01 IDENTIDAD/PASAPORTE SOLICITANTE_2.pdf": ("file", self.source(6))})
        form.close()
        self.button(dialog, "Cerrar").on_click(None)


if __name__ == "__main__":
    unittest.main()
