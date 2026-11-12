"""WO-DV27-P3B4: governed "Archivar copia en Box" from the viewer (H1/H2 integrated, H3 pending).

Builds on the certified P3B2 sandbox (``ArchiveBase``): synthetic CRM and Bandeja in a
TemporaryDirectory, synthetic Box tree compared byte for byte in tearDown, the certified P3B1 copy
running FOR REAL behind a spy, and the habitual ``quesada.db`` checked untouched. ``ArchiveBase``
opens the gate, installs a sandbox permission contract, applies the DV25 request migration to the
temporary database and takes the single-host decision; each test here closes one of them again
to prove the service refuses without writing. DV28-P2: ``ActivationBase`` also enrolls a
synthetic workstation (``SyntheticStation``: an in-memory P-256 key, sandbox only) because the
service now demands the verified workstation too.

- ``GateTests`` / ``ScopeTests`` read the REAL code: gate OFF, no permission contract, no shared
  authority, H3 not prevented, one physical copy only reachable through a persistent request.
- ``PermissionTests`` (H1), ``IntentTests`` (H2), ``CrashTests`` (crash before/during/after
  COPY, VERIFY, REGISTER), ``SafetyTests`` (collision, expiry, H3 swap, boundedness) and
  ``ViewerTests`` (the dialog shows the concrete reason and never copies while blocked).

No real Box, Drive or CRM data is reached.
"""
import ast
import hashlib
import os
import secrets
import sqlite3
import threading
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from backend.services import document_inbox_service
from backend.services import document_viewer_archive_host_policy as stations
from backend.services import document_viewer_archive_permission_service as permission
from backend.services import document_viewer_archive_repository as intents
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
CODES = (archive.PERMISSION_CONTRACT_PENDING, archive.MULTI_HOST_AUTHORITY_PENDING,
         archive.TOCTOU_PREVENTION_PENDING)
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


class Contract:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def grants(self, user, *, db_path=None):
        self.calls.append(user["id"])
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer(user) if callable(self.answer) else self.answer


class SyntheticStation:
    """Sandbox-only workstation (DV28-P2): an in-memory P-256 key that never leaves the test.

    Plays the OS proof provider: signs the service's fresh challenge with its own secret. It is
    never a real enrollment; ``flags`` simulate the key properties CNG would report.
    """

    def __init__(self, station_id="despacho-sintetico", key_name="quesada-dv28-p2-sandbox", **flags):
        self.secret = secrets.randbelow(stations._N - 1) + 1
        x, y = stations._mul(self.secret, stations._G)
        self.public_key = b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")
        self.enrollment = stations.StationEnrollment(station_id, key_name, self.public_key,
                                                     enrolled_by="sandbox", enrolled_at="sandbox")
        self.flags = {"hardware": True, "exportable": False, "remote_session": False, **flags}
        self.calls = []

    def sign(self, message):
        digest = int.from_bytes(hashlib.sha256(bytes(message)).digest(), "big")
        while True:
            nonce = secrets.randbelow(stations._N - 1) + 1
            r = stations._mul(nonce, stations._G)[0] % stations._N
            s = pow(nonce, -1, stations._N) * (digest + r * self.secret) % stations._N
            if r and s:
                return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    def prove(self, key_name, message):
        self.calls.append(key_name)
        if key_name != self.enrollment.key_name:
            raise stations.StationKeyMissing("sandbox: no such key")
        return stations.StationProof(public_key=self.public_key, signature=self.sign(message), **self.flags)

    def install(self, test, enrollment=None):
        test.patch(stations, "ENROLLED_STATION", enrollment or self.enrollment)
        test.patch(stations, "PROOF_PROVIDER", self)
        return self


# ---------------------------------------------------------------------- real code


class GateTests(unittest.TestCase):
    def test_gate_and_every_precondition_are_closed_in_the_code(self):
        self.assertEqual(literal_assignments(SERVICE, "EXECUTION_ENABLED"), [False])
        self.assertEqual(literal_assignments(SERVICE, "SINGLE_HOST_APPROVED"), [False])
        self.assertEqual(literal_assignments(SERVICE, "H3_WRITE_CONTAINMENT_VERIFIED"), [False])
        self.assertEqual(literal_assignments(PERMISSION, "APPROVED_CONTRACT"), [None])
        self.assertEqual(literal_assignments(REPOSITORY, "MULTI_HOST_GUARANTEE"), [False])
        self.assertIs(archive.EXECUTION_ENABLED, False)
        self.assertEqual(archive.activation_blockers(), CODES)
        self.assertEqual(archive.execution_blocker(), archive.EXECUTION_DISABLED)
        for code in CODES:
            self.assertIn(code, archive.EXECUTION_DISABLED)

    def test_the_gate_cannot_be_open_in_the_code_while_anything_is_pending(self):
        if archive.activation_blockers():
            self.assertEqual(literal_assignments(SERVICE, "EXECUTION_ENABLED"), [False])
        # Resolving one precondition never clears the others.
        with patch.object(permission, "APPROVED_CONTRACT", Contract(True)):
            self.assertEqual(archive.activation_blockers(), CODES[1:])
        with patch.object(archive, "SINGLE_HOST_APPROVED", True):
            self.assertEqual(archive.activation_blockers(), (CODES[0], CODES[2]))
        with patch.object(archive, "H3_WRITE_CONTAINMENT_VERIFIED", True):
            self.assertEqual(archive.activation_blockers(), CODES[:2])
        # Truthy values that are not exactly True never count.
        with patch.object(archive, "SINGLE_HOST_APPROVED", 1), \
                patch.object(archive, "H3_WRITE_CONTAINMENT_VERIFIED", "True"):
            self.assertEqual(archive.activation_blockers(), CODES)

    def test_an_open_gate_still_demands_h1_and_h2(self):
        with patch.object(archive, "EXECUTION_ENABLED", True):
            self.assertEqual(archive.execution_blocker(), archive.PERMISSION_PENDING)
            with patch.object(permission, "APPROVED_CONTRACT", Contract(True)):
                self.assertEqual(archive.execution_blocker(), archive.MULTI_HOST_PENDING)


class ScopeTests(unittest.TestCase):
    def test_one_physical_copy_only_inside_a_persistent_request_after_the_permission(self):
        tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]

        def count(owner, attr):
            return sum(1 for node in calls if node.func.attr == attr
                       and getattr(node.func.value, "id", None) == owner)

        self.assertEqual(count("document_inbox_service", "copy_inbox_item_to_expedient_box"), 1)
        self.assertEqual(count("permission", "authorize_archive"), 1)
        self.assertEqual(count("intents", "run_intent"), 1)
        self.assertEqual(count("intents", "governed_box_copy"), 1)
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertTrue(any(isinstance(node, ast.Call)
                            and getattr(node.func, "attr", None) == "copy_inbox_item_to_expedient_box"
                            for node in ast.walk(functions["certified_copy"])))
        governed, = [node for node in calls if node.func.attr == "governed_box_copy"]
        self.assertEqual([(keyword.arg, getattr(keyword.value, "id", None)) for keyword in governed.keywords],
                         [("copy", "certified_copy")])
        # H1 and H2 are demanded before any document is copied.
        lines = {node.func.id: node.lineno for node in ast.walk(functions["execute_archive"])
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertLess(lines["_authorize"], lines["_execute_one"])
        self.assertLess(lines["_intent_store"], lines["_execute_one"])
        # No recursive or massive exploration from the viewer's operation.
        self.assertEqual(p3a.called_names(SERVICE) & SCANS, set())


# ---------------------------------------------------------------------- sandbox


class ActivationBase(p3b2.ArchiveBase):
    def setUp(self):
        super().setUp()
        # DV28-P2: the verified workstation, sandbox only (never a real key or enrollment).
        self.station = SyntheticStation().install(self)

    def intent_rows(self):
        return [(row["inbox_item_id"], row["state"], row["destination_path"]) for row in self.query(
            "SELECT inbox_item_id, state, destination_path FROM document_viewer_archive_intents ORDER BY id")]

    def intent_states(self):
        return [state for _item, state, _path in self.intent_rows()]

    def sha(self, item_id):
        return hashlib.sha256(self.source(item_id)).hexdigest()

    def intent(self, item_id=6, subfolder="", user=1):
        return intents.ArchiveIntent(
            inbox_item_id=item_id, client_id=7, expedient_id=42, subfolder=subfolder, nomenclature_key=K[0],
            source_sha256=self.sha(item_id), requested_by_user_id=user)

    def expire_leases(self):
        later = datetime.now(timezone.utc) + intents.LEASE + timedelta(minutes=1)
        self.patch(intents, "_utc_now", lambda: later)

    def plan6(self, folder="", actor="default"):
        return self.prepare([6], folder=folder, choices={"inbox:6": K[0]}, actor=actor)

    def assert_refused(self, plan, message):
        with self.assertRaises(archive.ArchiveError) as raised:
            self.run_plan(plan)
        self.assertEqual(str(raised.exception), message)
        self.assertIsNone(plan.result)


# ---------------------------------------------------------------------- H1


class PermissionTests(ActivationBase):
    def test_without_an_approved_contract_an_active_user_copies_nothing(self):
        before = self.snapshot()
        claims = {**self.actor, "role": "admin", "is_admin": True, "permissions": ["archive_box"]}
        for actor in (self.actor, claims):  # client-declared roles are ignored
            with self.subTest(actor=actor), patch.object(permission, "APPROVED_CONTRACT", None):
                plan = self.plan6(actor=actor)
                self.assertEqual(len(plan.ready), 1)
                self.assertEqual(archive.execution_blocker(), archive.PERMISSION_PENDING)
                self.assert_refused(plan, archive.PERMISSION_PENDING)
        self.copy.assert_not_called()
        self.assertEqual(self.intent_rows(), [])
        self.assertEqual(self.snapshot(), before)

    def test_contract_refusals_and_errors_deny(self):
        cases = ((Contract(lambda user: user["id"] == 2), permission.NOT_GRANTED_MESSAGE),
                 (Contract(False), permission.NOT_GRANTED_MESSAGE),
                 (Contract(1), permission.NOT_GRANTED_MESSAGE),
                 (Contract("yes"), permission.NOT_GRANTED_MESSAGE),
                 (Contract(RuntimeError("caído")), permission.CONTRACT_ERROR_MESSAGE))
        for contract, message in cases:
            with self.subTest(answer=contract.answer), patch.object(permission, "APPROVED_CONTRACT", contract):
                self.assert_refused(self.plan6(), message)
                # DV28: asked at the review and at the confirmation, only about the verified user.
                self.assertEqual(contract.calls, [1, 1])
        self.copy.assert_not_called()
        self.assertEqual(self.intent_rows(), [])

    def test_missing_forged_or_inactive_actor_is_denied(self):
        plan = self.plan6()
        for name, actor in (("no actor", None), ("forged", {"id": 1, "username": "luis"}),
                            ("unknown", {"id": 99, "username": "nadie"})):
            with self.subTest(name), self.assertRaises(archive.ArchiveError):
                self.run_plan(replace(plan, actor=actor, token=uuid4().hex))
        # A decision about another user than the verified one is never accepted.
        other = permission.PermissionDecision(permission.ALLOWED, permission.GRANTED, "",
                                              {"id": 2, "username": "luis"})
        with patch.object(permission, "authorize_archive", return_value=other):
            self.assert_refused(replace(plan, token=uuid4().hex), archive.NOT_AUTHORIZED)
        self.execute("UPDATE users SET is_active = 0 WHERE id = 1")
        with self.assertRaises(archive.ArchiveError):
            self.run_plan(plan)
        self.assertIsNone(plan.result)
        self.copy.assert_not_called()
        self.assertEqual(self.intent_rows(), [])

    def test_a_granting_contract_lets_the_verified_user_archive_once(self):
        contract = Contract(lambda user: user == {"id": 1, "username": "ana"})
        before_row = self.row(6)
        with patch.object(permission, "APPROVED_CONTRACT", contract):
            plan = self.plan6()
            tree = self.tree()
            with self.guard():
                result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED)])
        # DV28: review, confirmation and right before the copy; always the verified user.
        self.assertEqual(contract.calls, [1, 1, 1])
        self.copy.assert_called_once_with(6, expedient_id=42, subfolder="", nomenclature_key=K[0])
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})
        row = self.row(6)
        self.assertEqual((row["status"], row["client_id"], row["expedient_id"]), ("copied_to_box", 7, 42))
        self.assertEqual(row["stored_path"], before_row["stored_path"])
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])
        [(item_id, state, destination)] = self.intent_rows()
        self.assertEqual((item_id, state), (6, intents.REGISTERED))
        self.assertEqual(Path(destination).resolve(), (self.box / NAME).resolve())


# ---------------------------------------------------------------------- H2


class IntentTests(ActivationBase):
    def test_one_persistent_request_per_copy_and_replays_write_nothing(self):
        plan = self.plan6()
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
            self.assertIs(self.run_plan(plan), result)  # double click
        self.assertEqual(self.copy.call_count, 1)
        self.assertEqual(self.query("SELECT requested_by_user_id, fence FROM document_viewer_archive_intents"),
                         [{"requested_by_user_id": 1, "fence": 1}])
        self.assertEqual(self.intent_states(), [intents.REGISTERED])
        # Exactly one physical copy and one registration; the replay added nothing.
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])
        again = archive.inspect_archive(self.actor, [self.doc(6)], db_path=self.db)
        self.assertEqual(again.items[0].message, archive.ALREADY_COPIED)

    def test_without_the_migration_or_on_the_habitual_database_nothing_runs(self):
        plan = self.plan6()
        before = self.snapshot()
        with patch.object(intents, "HABITUAL_DB", Path(self.db).resolve()):
            self.assert_refused(plan, archive.INTENTS_UNAVAILABLE)
        self.execute("DROP TABLE document_viewer_archive_intents")
        try:
            self.assert_refused(plan, archive.INTENTS_UNAVAILABLE)
            # The store neither creates nor migrates the table.
            self.assertNotIn("document_viewer_archive_intents", [row["name"] for row in self.schema()])
        finally:
            intents.apply_schema(self.db)
        self.copy.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_without_shared_authority_nothing_runs_and_two_databases_do_not_coordinate(self):
        plan = self.plan6()
        with patch.object(archive, "SINGLE_HOST_APPROVED", False):
            self.assertEqual(archive.execution_blocker(), archive.MULTI_HOST_PENDING)
            self.assert_refused(plan, archive.MULTI_HOST_PENDING)
        self.copy.assert_not_called()
        # Why: one local database per PC; both grant the same request, nothing is coordinated.
        copies = []
        for name in ("pc_a.db", "pc_b.db"):
            target = self.root / name
            with closing(sqlite3.connect(self.db)) as source, closing(sqlite3.connect(target)) as dest:
                source.backup(dest)
            copies.append(target)
        now = datetime.now(timezone.utc)
        self.assertEqual([intents.SqliteArchiveIntentStore(db).claim(self.intent(), uuid4().hex, now).status
                          for db in copies], [intents.ACQUIRED, intents.ACQUIRED])
        self.assertIs(intents.SqliteArchiveIntentStore(self.db).multi_host_guarantee, False)

    def test_a_claim_of_another_process_on_the_shared_database_blocks_the_copy(self):
        other = self.intent(subfolder="01 IDENTIDAD", user=2)  # another key, same item
        claim = intents.SqliteArchiveIntentStore(self.db).claim(other, uuid4().hex, datetime.now(timezone.utc))
        self.assertEqual(claim.status, intents.ACQUIRED)
        plan = self.plan6()
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.REJECTED)])
        self.assertEqual(result.items[0].message, archive.IN_FLIGHT)
        self.copy.assert_not_called()
        self.assertEqual(self.tree(), tree)
        self.assertEqual(self.intent_states(), [intents.CLAIMED])
        self.assertEqual(self.row(6)["status"], "linked")

    def test_parallel_runs_without_shared_memory_copy_once(self):
        # As two processes on one database: the in-memory guard is not shared.
        self.patch(archive, "_claim", lambda item_id: True)
        self.patch(archive, "_release", lambda item_id: None)
        first, second = self.plan6(), self.plan6()
        entered, release, results = threading.Event(), threading.Event(), []

        def slow(item_id, **kwargs):
            entered.set()
            release.wait(10)
            return REAL_COPY(item_id, **kwargs)

        self.copy.side_effect = slow
        tree = self.tree()
        worker = threading.Thread(target=lambda: results.append(self.run_plan(first)))
        worker.start()
        try:
            self.assertTrue(entered.wait(10))
            rival = self.run_plan(second)
        finally:
            release.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.outcomes(rival), [(6, archive.REJECTED)])
        self.assertEqual(rival.items[0].message, archive.IN_FLIGHT)
        self.assertEqual(self.outcomes(results[0]), [(6, archive.ARCHIVED)])
        self.assertEqual(self.copy.call_count, 1)
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})
        self.assertEqual(self.intent_states(), [intents.REGISTERED])


# ---------------------------------------------------------------------- crashes


class CrashTests(ActivationBase):
    def crash(self):
        plan = self.plan6()
        tree = self.tree()
        with self.guard(), self.assertRaises(Crash):
            self.run_plan(plan)
        self.assertEqual(self.intent_states(), [intents.CLAIMED])
        return tree

    def assert_never_retried(self):
        """After a crash: in progress while the lease lasts, then human review; never copied again."""
        for step, message in (("lease", archive.IN_FLIGHT), ("expired", intents.STALE_REVIEW_MESSAGE),
                              ("reviewed", intents.REVIEW_MESSAGE)):
            with self.subTest(step):
                if step == "expired":
                    self.expire_leases()
                with self.guard():
                    result = self.run_plan(self.plan6())
                self.assertEqual(self.outcomes(result), [(6, archive.REJECTED)])
                self.assertEqual(result.items[0].message, message)
        self.assertEqual(self.copy.call_count, 1)
        self.assertEqual(self.intent_states(), [intents.NEEDS_REVIEW])
        self.assertEqual(self.row(6)["status"], "linked")
        self.assertNotIn("copied_to_box", [event["event_type"] for event in self.events(6)])

    def test_crash_before_copy_writes_nothing_and_is_not_retried(self):
        self.patch(document_inbox_service, "_create_box_copy", side_effect=Crash())
        tree = self.crash()
        self.assertEqual(self.tree(), tree)
        self.assert_never_retried()  # the crashing copy stays patched: a retry would raise

    def test_crash_during_copy_keeps_the_partial_file_for_review(self):
        def partial(src, handle):
            handle.write(b"%PDF parcial")
            raise Crash()

        self.patch(document_inbox_service, "_stream_into", partial)
        tree = self.crash()
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", b"%PDF parcial")})  # never deleted
        self.assert_never_retried()

    def test_crash_between_verify_and_register_keeps_the_copy_for_review(self):
        self.patch(document_inbox_service, "_register_box_copy", side_effect=Crash())
        tree = self.crash()
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})
        self.assert_never_retried()

    def test_crash_after_register_is_reconciled_without_another_copy(self):
        real = document_inbox_service._register_box_copy

        def registered_then_crash(*args):
            real(*args)
            raise Crash()

        self.patch(document_inbox_service, "_register_box_copy", registered_then_crash)
        tree = self.crash()
        self.assert_added(tree, {f"EXP-42/{NAME}": ("file", self.source(6))})
        self.assertEqual(self.row(6)["status"], "copied_to_box")
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])
        again = archive.inspect_archive(self.actor, [self.doc(6)], db_path=self.db)
        self.assertEqual((again.items[0].outcome, again.items[0].message), (archive.REJECTED, archive.ALREADY_COPIED))

        def forbidden(*args, **kwargs):
            raise AssertionError("a recovery never copies")

        self.expire_leases()
        intent = self.intent()
        outcome = intents.run_intent(intents.SqliteArchiveIntentStore(self.db), intent,
                                     intents.governed_box_copy(intent, copy=forbidden),
                                     evidence=intents.registered_copy_evidence(self.db))
        self.assertEqual(outcome.status, intents.RECOVERED)
        self.assertEqual(Path(outcome.destination_path).resolve(), (self.box / NAME).resolve())
        self.assertEqual(self.intent_states(), [intents.REGISTERED])
        self.assertEqual(self.copy.call_count, 1)


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
        self.assertEqual(self.intent_rows(), [])

    def test_h3_folder_swap_after_validation_is_prevented(self):
        """H3 (DV28): the swapped link is refused before any write; the flag stays closed in the code."""
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
        self.assertEqual((result.items[0].status, result.items[0].message),
                         (archive.REJECTED, document_inbox_service.BOX_CONTAINMENT_FAILED))
        self.assertEqual(list(escape.iterdir()), [])  # nothing escaped: prevention, not detection
        row = self.row(6)
        self.assertEqual((row["status"], row["copied_to_box_path"]), ("linked", None))
        self.assertEqual(self.events(6), [])
        self.assertEqual(self.intent_states(), [intents.REJECTED])  # nothing written: retryable
        # The flag only opens with Runner evidence on Windows and the supervised Box Drive test.
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
    def check_blocked(self, dialog, reason):
        form = self.open_archive(dialog)
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

    def test_while_blocked_the_dialog_shows_the_concrete_reason_and_copies_nothing(self):
        dialog = self.open_inbox([6, 1])
        before = self.snapshot()
        with self.guard():
            with patch.object(archive, "EXECUTION_ENABLED", False):
                self.check_blocked(dialog, archive.EXECUTION_DISABLED)
            with patch.object(permission, "APPROVED_CONTRACT", None):
                self.check_blocked(dialog, archive.PERMISSION_PENDING)
            with patch.object(archive, "SINGLE_HOST_APPROVED", False):
                self.check_blocked(dialog, archive.MULTI_HOST_PENDING)
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
        self.assertEqual(self.intent_states(), [intents.REGISTERED])
        self.assert_added(tree, {"EXP-42/01 IDENTIDAD/PASAPORTE SOLICITANTE_2.pdf": ("file", self.source(6))})
        form.close()
        self.button(dialog, "Cerrar").on_click(None)


if __name__ == "__main__":
    unittest.main()
