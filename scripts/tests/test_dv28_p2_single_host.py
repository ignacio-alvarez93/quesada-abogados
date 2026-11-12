"""WO-DV28-P2: single-workstation pilot of "Archivar copia en Box" from the viewer, gate OFF.

Everything runs on the certified sandboxes (TemporaryDirectory CRM, Bandeja and Box; the habitual
``quesada.db`` checked untouched; no network, no Box Drive, no real key):

- ``GateTests`` read the REAL code: the five production flags closed, no workstation enrolled and no
  proof provider installed, the station never read from the actor, the UI or the environment, no key
  creation/import/deletion API, the station checked at review, confirmation and right before COPY.
- ``StationPolicyTests``: ECDSA P-256 verification (RFC 6979 vector), ALLOWED only for the enrolled
  key proven on a fresh challenge; not enrolled, home PC, cloned configuration, replayed proof,
  exportable or software key, remote session, provider error, non-local authority => denied.
- ``SandboxStationFixtureTests``: the DV25 ``ArchiveBase`` sandbox enrolls its synthetic station only
  while its test runs; afterwards nothing is enrolled and every machine is refused again.
- ``ViewerStationTests`` (``ActivationBase``: gate, permission contract and single-host decision opened
  in the sandbox, synthetic station enrolled): user granted but machine refused => nothing; station
  lost, changed or failing right before the copy => zero writes; four reviews => one copy.
- ``ProcessStationTests``: real processes on ONE temporary database => one copy, one closed request,
  no ``_2``; the home PC with the copied configuration (and even a copied database) => refused; two
  independent databases are NOT global exclusion.
- ``H3EvidenceTests``: on Windows, ``ContainmentTests`` run with zero skips and zero failures.

A real enrollment, Box Drive and the production gates are out of scope (docs/dv28_p2_single_host.md).
"""
import ast
import inspect
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from backend.services import document_viewer_archive_host_policy as stations
from backend.services import document_viewer_archive_permission_service as permission
from backend.services import document_viewer_archive_repository as intents
from backend.services import document_viewer_box_archive_service as archive
from backend.services import document_viewer_filing_plan_service as filing
from scripts.tests import test_document_viewer_dv24_linking as dv24
from scripts.tests import test_document_viewer_dv25_box_from_viewer as p3b2
from scripts.tests import test_document_viewer_dv25_box_hardening as p3b1
from scripts.tests import test_document_viewer_dv25_security as sec
from scripts.tests import test_dv27_box_copy_activation as dv27
from scripts.tests import test_dv28_box_activation as dv28


REPO_ROOT = dv24.REPO_ROOT
SERVICE = p3b2.SERVICE
DIALOG = p3b2.ARCHIVE_DIALOG
HOST_POLICY = REPO_ROOT / "backend" / "services" / "document_viewer_archive_host_policy.py"
SyntheticStation = dv27.SyntheticStation
KEY = sec.KEY
NAME = sec.NAME

# RFC 6979, A.2.5 (ECDSA, P-256, SHA-256, message "sample"): an independent known answer, so the
# verifier is checked against the standard and not only against the test signer.
RFC6979_SECRET = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721
RFC6979_PUBLIC = bytes.fromhex(
    "04" "60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6"
    "7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299")
RFC6979_SIGNATURE = bytes.fromhex(
    "EFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716"
    "F7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8")


def code_strings(path):
    """String constants of the module that are not docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body
                  and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]


def call_lines(function):
    """Name of every called function/attribute -> line numbers, inside ``function``."""
    lines = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            lines.setdefault(name, []).append(node.lineno)
    return lines


class Replay:
    """A provider that captured one valid proof and presents it again (a replayed signature)."""

    def __init__(self, station):
        self.station, self.captured = station, None

    def prove(self, key_name, message):
        if self.captured is None:
            self.captured = self.station.prove(key_name, message)
        return self.captured


class Clone(SyntheticStation):
    """Copied configuration: presents the despacho's public key but holds only its own secret."""

    def __init__(self, copied_public_key):
        super().__init__()
        self.public_key = copied_public_key


class Failing:
    def __init__(self, error):
        self.error = error

    def prove(self, key_name, message):
        raise self.error


# ---------------------------------------------------------------------- real code


class GateTests(unittest.TestCase):
    def test_production_gates_stay_closed_and_no_station_is_enrolled(self):
        self.assertEqual(dv27.literal_assignments(SERVICE, "EXECUTION_ENABLED"), [False])
        self.assertEqual(dv27.literal_assignments(SERVICE, "SINGLE_HOST_APPROVED"), [False])
        self.assertEqual(dv27.literal_assignments(SERVICE, "H3_WRITE_CONTAINMENT_VERIFIED"), [False])
        self.assertEqual(dv27.literal_assignments(dv27.PERMISSION, "APPROVED_CONTRACT"), [None])
        self.assertEqual(dv27.literal_assignments(dv27.REPOSITORY, "MULTI_HOST_GUARANTEE"), [False])
        self.assertEqual(dv27.literal_assignments(HOST_POLICY, "ENROLLED_STATION"), [None])
        self.assertEqual(dv27.literal_assignments(HOST_POLICY, "PROOF_PROVIDER"), [None])
        self.assertEqual(archive.activation_blockers(), dv27.CODES)
        self.assertEqual(archive.execution_blocker(), archive.EXECUTION_DISABLED)
        # Fail closed by default: with nothing installed every machine is refused.
        with TemporaryDirectory() as temp:
            decision = stations.verify_station(db_path=Path(temp) / "crm.db")
        self.assertEqual((decision.outcome, decision.reason), (stations.NOT_ENROLLED, stations.NO_ENROLLMENT))

    def test_the_station_never_comes_from_the_actor_the_ui_or_the_environment(self):
        self.assertEqual(list(inspect.signature(stations.verify_station).parameters), ["db_path"])
        modules = dv24.imported_modules(HOST_POLICY)
        for forbidden in ("socket", "platform", "getpass", "winreg", "uuid", "subprocess", "sqlite3", "shutil",
                          "database", "frontend", "flet", "backend"):
            self.assertFalse(any(m == forbidden or m.startswith(forbidden + ".") for m in modules), forbidden)
        tree = ast.parse(HOST_POLICY.read_text(encoding="utf-8"))
        used = {getattr(node, "attr", None) or getattr(node, "id", None) for node in ast.walk(tree)
                if isinstance(node, (ast.Attribute, ast.Name))}
        for spoofable in ("environ", "getenv", "gethostname", "getnode", "getlogin", "getuser", "uname", "node"):
            self.assertNotIn(spoofable, used)
        strings = " ".join(code_strings(HOST_POLICY)).lower()
        for spoofable in ("computername", "machineguid", "hostname", "username", "userdomain"):
            self.assertNotIn(spoofable, strings)
        # Only open, read properties, export the PUBLIC blob and sign: never create, import or delete.
        apis = {value for value in code_strings(HOST_POLICY) if value.startswith("NCrypt")}
        self.assertEqual(apis, {"NCryptOpenStorageProvider", "NCryptOpenKey", "NCryptGetProperty",
                                "NCryptExportKey", "NCryptSignHash", "NCryptFreeObject"})
        self.assertIn("ECCPUBLICBLOB", code_strings(HOST_POLICY))
        self.assertFalse([value for value in code_strings(HOST_POLICY) if "PRIVATE" in value.upper()])
        # No file, database or Box path of its own.
        self.assertNotIn("open", set(call_lines(ast.parse(HOST_POLICY.read_text(encoding="utf-8")))))
        self.assertFalse([value for value in code_strings(HOST_POLICY) if re.match(r"^[A-Za-z]:[\\/]", value)])
        # The UI never reaches the station policy: only the archive service decides.
        for path in sorted((REPO_ROOT / "frontend").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for name in ("host_policy", "verify_station", "ENROLLED_STATION", "PROOF_PROVIDER"):
                self.assertNotIn(name, text, path)

    def test_the_service_checks_the_station_at_review_confirmation_and_right_before_the_copy(self):
        tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertIn("_station", call_lines(functions["prepare_archive"]))
        station = call_lines(functions["_station"])
        self.assertEqual(len(station["verify_station"]), 1)
        [call] = [node for node in ast.walk(functions["_station"]) if isinstance(node, ast.Call)
                  and getattr(node.func, "attr", None) == "verify_station"]
        self.assertEqual(([keyword.arg for keyword in call.keywords], call.args), (["db_path"], []))
        execute = call_lines(functions["execute_archive"])
        self.assertLess(execute["_authorize"][0], execute["_station_denied"][0])
        self.assertLess(execute["_station_denied"][0], execute["_intent_store"][0])
        self.assertLess(execute["_intent_store"][0], execute["_execute_one"][0])
        copy = call_lines(functions["certified_copy"])
        self.assertLess(copy["_permission"][0], copy["_station_denied"][0])
        self.assertLess(copy["_station_denied"][0], copy["copy_inbox_item_to_expedient_box"][0])
        # Neither the single-host decision nor the permission contract grants the station.
        for name in ("_station", "_station_denied"):
            names = {getattr(node, "id", None) for node in ast.walk(functions[name])}
            self.assertFalse(names & {"SINGLE_HOST_APPROVED", "APPROVED_CONTRACT", "actor", "user"}, name)


# ---------------------------------------------------------------------- station policy


class PolicyBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name).resolve() / "crm.db"
        self.despacho = SyntheticStation()

    def patch(self, target, name, *args, **kwargs):
        patcher = patch.object(target, name, *args, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def decide(self):
        return stations.verify_station(db_path=self.db)

    def assert_decision(self, outcome, reason):
        decision = self.decide()
        self.assertEqual((decision.outcome, decision.reason), (outcome, reason))
        self.assertEqual(decision.allowed, outcome == stations.ALLOWED)
        return decision


class StationPolicyTests(PolicyBase):
    def test_p256_verification_matches_the_standard(self):
        x, y = stations._G
        self.assertEqual((y * y - (x ** 3 + stations._A * x + stations._B)) % stations._P, 0)
        self.assertIsNone(stations._mul(stations._N, stations._G))
        point = stations._mul(RFC6979_SECRET, stations._G)
        self.assertEqual(b"\x04" + point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big"), RFC6979_PUBLIC)
        self.assertIs(stations.verify_signature(RFC6979_PUBLIC, b"sample", RFC6979_SIGNATURE), True)
        self.assertIs(stations.verify_signature(RFC6979_PUBLIC, b"sample!", RFC6979_SIGNATURE), False)
        tampered = RFC6979_SIGNATURE[:-1] + bytes([RFC6979_SIGNATURE[-1] ^ 1])
        self.assertIs(stations.verify_signature(RFC6979_PUBLIC, b"sample", tampered), False)
        n = stations._N.to_bytes(32, "big")
        for bad in (b"", RFC6979_SIGNATURE[:63], bytes(64), n + RFC6979_SIGNATURE[32:], RFC6979_SIGNATURE[:32] + n,
                    "texto", None):
            with self.subTest(signature=bad):
                self.assertIs(stations.verify_signature(RFC6979_PUBLIC, b"sample", bad), False)
        for bad in (b"", RFC6979_PUBLIC[:64], b"\x02" + RFC6979_PUBLIC[1:], RFC6979_PUBLIC[:-1] + b"\x00", None):
            with self.subTest(public_key=bad), self.assertRaises(stations.StationProofError):
                stations.verify_signature(bad, b"sample", RFC6979_SIGNATURE)
        # The synthetic sandbox station signs what the verifier accepts.
        message = b"reto sintetico"
        self.assertIs(stations.verify_signature(self.despacho.public_key, message, self.despacho.sign(message)), True)

    def test_nothing_installed_and_spoofed_identity_strings_are_not_enrolled(self):
        spoofed = {"COMPUTERNAME": "DESPACHO", "USERNAME": "ana", "USERDOMAIN": "DESPACHO",
                   "QUESADA_STATION": "despacho-1", "QUESADA_ARCHIVE_STATION_VERIFIED": "1"}
        with patch.dict(os.environ, spoofed):
            self.assert_decision(stations.NOT_ENROLLED, stations.NO_ENROLLMENT)
            # An enrollment-shaped dict (e.g. copied JSON) is not an enrollment.
            self.patch(stations, "ENROLLED_STATION", asdict(self.despacho.enrollment))
            self.patch(stations, "PROOF_PROVIDER", self.despacho)
            self.assert_decision(stations.NOT_ENROLLED, stations.NO_ENROLLMENT)

    def test_the_enrolled_station_is_allowed_on_a_fresh_challenge(self):
        self.despacho.install(self)
        first = self.assert_decision(stations.ALLOWED, stations.VERIFIED)
        second = self.assert_decision(stations.ALLOWED, stations.VERIFIED)
        self.assertEqual(first.fingerprint, stations.key_fingerprint(self.despacho.public_key))
        self.assertEqual(len(first.fingerprint), 12)
        self.assertEqual((first.fingerprint, first.station_id), (second.fingerprint, "despacho-sintetico"))
        # Traces carry a short fingerprint, never the key.
        self.assertNotIn(self.despacho.public_key.hex()[2:26], repr(first))
        self.assertEqual(self.despacho.calls, [self.despacho.enrollment.key_name] * 2)

    def test_home_pc_cloned_or_replayed_identity_is_refused(self):
        self.despacho.install(self)
        home = SyntheticStation(station_id="despacho-sintetico", key_name=self.despacho.enrollment.key_name)
        cases = (
            ("no provider", None, (stations.UNVERIFIED, stations.NO_PROVIDER)),
            ("home PC: its own key", home, (stations.NOT_THIS_WORKSTATION, stations.OTHER_KEY)),
            ("copied configuration", Clone(self.despacho.public_key),
             (stations.UNVERIFIED, stations.BAD_SIGNATURE)),
            ("key absent on this machine", Failing(stations.StationKeyMissing("x")),
             (stations.NOT_ENROLLED, stations.KEY_MISSING)),
            ("provider failure", Failing(OSError("TPM no disponible")), (stations.ERROR, stations.PROVIDER_ERROR)),
            ("provider answers something else", type("Odd", (), {"prove": lambda s, k, m: {"ok": True}})(),
             (stations.ERROR, stations.PROVIDER_ERROR)),
        )
        for name, provider, expected in cases:
            with self.subTest(name), patch.object(stations, "PROOF_PROVIDER", provider):
                self.assert_decision(*expected)
        replay = Replay(self.despacho)
        self.patch(stations, "PROOF_PROVIDER", replay)
        self.assert_decision(stations.ALLOWED, stations.VERIFIED)  # the first, genuine proof
        self.assert_decision(stations.UNVERIFIED, stations.BAD_SIGNATURE)  # the same proof again

    def test_copiable_software_or_remote_keys_are_refused(self):
        cases = (({"exportable": True}, (stations.UNVERIFIED, stations.EXPORTABLE_KEY)),
                 ({"exportable": 0}, (stations.UNVERIFIED, stations.EXPORTABLE_KEY)),
                 ({"hardware": False}, (stations.UNVERIFIED, stations.SOFTWARE_KEY)),
                 ({"hardware": 1}, (stations.UNVERIFIED, stations.SOFTWARE_KEY)),
                 ({"remote_session": True}, (stations.NOT_THIS_WORKSTATION, stations.REMOTE_SESSION)),
                 ({"remote_session": None}, (stations.NOT_THIS_WORKSTATION, stations.REMOTE_SESSION)))
        for flags, expected in cases:
            with self.subTest(flags=flags):
                station = SyntheticStation(**flags)
                with patch.object(stations, "ENROLLED_STATION", station.enrollment), \
                        patch.object(stations, "PROOF_PROVIDER", station):
                    self.assert_decision(*expected)

    def test_invalid_enrollment_is_an_error_never_a_grant(self):
        enrollment = self.despacho.enrollment
        for name, broken in (("bad key", stations.StationEnrollment("despacho", "clave", b"\x04" + bytes(64))),
                             ("short key", stations.StationEnrollment("despacho", "clave", b"\x04")),
                             ("no station id", stations.StationEnrollment(" ", "clave", enrollment.public_key)),
                             ("no key name", stations.StationEnrollment("despacho", "", enrollment.public_key))):
            with self.subTest(name), patch.object(stations, "ENROLLED_STATION", broken), \
                    patch.object(stations, "PROOF_PROVIDER", self.despacho):
                self.assertEqual(self.decide().outcome, stations.ERROR)

    def test_the_request_authority_must_be_a_local_fixed_disk(self):
        self.despacho.install(self)
        for path in (None, r"\\servidor\crm\quesada.db", "//servidor/crm/quesada.db", r"\\?\UNC\servidor\crm\q.db"):
            with self.subTest(path=path):
                self.assertIs(stations.local_authority(path), False)
                decision = stations.verify_station(db_path=path)
                self.assertEqual((decision.outcome, decision.reason),
                                 (stations.NOT_THIS_WORKSTATION, stations.AUTHORITY_NOT_LOCAL))
        self.assertIs(stations.local_authority(self.db), True)  # TEMP on this machine
        if os.name == "nt":
            for drive_type in (2, 4, 5, 6):  # removable, network, CD, RAM disk
                with self.subTest(drive_type=drive_type), patch.object(stations, "_drive_type",
                                                                       return_value=drive_type):
                    self.assert_decision(stations.NOT_THIS_WORKSTATION, stations.AUTHORITY_NOT_LOCAL)
            with patch.object(stations, "_drive_type", side_effect=OSError("sin API")):
                self.assert_decision(stations.NOT_THIS_WORKSTATION, stations.AUTHORITY_NOT_LOCAL)
        self.assert_decision(stations.ALLOWED, stations.VERIFIED)

    def test_the_real_os_provider_only_opens_and_this_machine_is_not_enrolled(self):
        """Read-only: opens a key that does not exist; never creates, imports or deletes one."""
        provider = stations.WindowsCngProofProvider()
        self.assertIsInstance(provider, stations.StationProofProvider)
        absent = f"quesada-dv28-p2-inexistente-{uuid4().hex}"
        with self.assertRaises((stations.StationProofError, OSError)):
            provider.prove(absent, b"reto")
        missing = SyntheticStation(key_name=absent)
        self.patch(stations, "ENROLLED_STATION", missing.enrollment)
        self.patch(stations, "PROOF_PROVIDER", provider)
        decision = self.decide()
        # NOT_ENROLLED where the TPM provider answers; ERROR without it (or off Windows). Never ALLOWED.
        self.assertIn(decision.outcome, (stations.NOT_ENROLLED, stations.ERROR))
        if os.name != "nt":
            self.assertEqual(decision.outcome, stations.ERROR)


class SandboxStationFixtureTests(unittest.TestCase):
    def test_the_dv25_sandbox_station_lives_only_inside_its_test(self):
        """DV28-P2-FIX1: ``ArchiveBase`` enrolls a synthetic station for the test and restores the policy."""
        self.assertEqual((stations.ENROLLED_STATION, stations.PROOF_PROVIDER), (None, None))
        seen = {}

        class Probe(p3b2.ArchiveBase):
            def test_probe(probe):
                seen["station"] = probe.station
                seen["during"] = stations.verify_station(db_path=probe.db).outcome
                # A negative test can still replace the fake.
                with patch.object(stations, "PROOF_PROVIDER", None):
                    seen["overridden"] = stations.verify_station(db_path=probe.db).outcome

        result = unittest.TestResult()
        Probe("test_probe").run(result)
        self.assertEqual((result.errors, result.failures, result.skipped), ([], [], []))
        self.assertTrue(result.wasSuccessful())
        self.assertIsInstance(seen["station"], SyntheticStation)
        self.assertEqual((seen["during"], seen["overridden"]), (stations.ALLOWED, stations.UNVERIFIED))
        # Once the test is over nothing is enrolled and every machine is refused again.
        self.assertEqual((stations.ENROLLED_STATION, stations.PROOF_PROVIDER), (None, None))
        with TemporaryDirectory() as temp:
            decision = stations.verify_station(db_path=Path(temp) / "crm.db")
        self.assertEqual((decision.outcome, decision.reason), (stations.NOT_ENROLLED, stations.NO_ENROLLMENT))


# ---------------------------------------------------------------------- the viewer


class ViewerStationTests(dv27.ActivationBase):
    """Granted user, single-host decision and gate opened in the sandbox: the machine still decides."""

    def assert_nothing_written(self, before):
        self.copy.assert_not_called()
        self.assertEqual(self.intent_rows(), [])
        self.assertEqual(self.snapshot(), before)

    def test_the_enrolled_station_with_a_grant_and_one_store_copies_once(self):
        self.assertIs(archive.SINGLE_HOST_APPROVED, True)  # sandbox only
        source, tree = self.source(6), self.tree()
        plan = self.plan6()
        self.assertEqual((plan.authorized, plan.station_verified, plan.station_message), (True, True, ""))
        self.assertEqual(plan.station_fingerprint, stations.key_fingerprint(self.station.public_key))
        with self.guard():
            result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED)])
        # Review, confirmation and right before the copy.
        self.assertEqual(len(self.station.calls), 3)
        self.copy.assert_called_once_with(6, expedient_id=42, subfolder="", nomenclature_key=p3b2.K[0])
        self.assertEqual(self.intent_states(), [intents.REGISTERED])
        self.assert_added(tree, {f"EXP-42/{dv27.NAME}": ("file", source)})
        self.assertEqual(self.source(6), source)

    def test_a_granted_user_on_a_machine_that_is_not_the_station_copies_nothing(self):
        home = SyntheticStation(station_id="despacho-sintetico", key_name=self.station.enrollment.key_name)
        software = SyntheticStation(hardware=False)
        cases = (
            ("not enrolled", {"ENROLLED_STATION": None}, stations.NOT_ENROLLED_MESSAGE),
            ("home PC", {"PROOF_PROVIDER": home}, stations.NOT_THIS_WORKSTATION_MESSAGE),
            ("copied configuration", {"PROOF_PROVIDER": Clone(self.station.public_key)},
             stations.UNVERIFIED_MESSAGE),
            ("no credential", {"PROOF_PROVIDER": Failing(stations.StationKeyMissing("x"))},
             stations.NOT_ENROLLED_MESSAGE),
            ("no OS provider", {"PROOF_PROVIDER": None}, stations.UNVERIFIED_MESSAGE),
            ("provider error", {"PROOF_PROVIDER": Failing(RuntimeError("x"))}, stations.ERROR_MESSAGE),
            ("software key", {"ENROLLED_STATION": software.enrollment, "PROOF_PROVIDER": software},
             stations.UNVERIFIED_MESSAGE),
        )
        before = self.snapshot()
        for name, patched, message in cases:
            with self.subTest(name):
                patchers = [patch.object(stations, attr, value) for attr, value in patched.items()]
                for patcher in patchers:
                    patcher.start()
                try:
                    # Station claims of the actor are ignored like its role claims.
                    plan = self.plan6(actor={**self.actor, "station": "despacho", "station_verified": True})
                    self.assertEqual(len(plan.ready), 1)  # the review stays available
                    self.assertEqual((plan.authorized, plan.station_verified, plan.station_message),
                                     (True, False, message))
                    self.assert_refused(plan, message)
                finally:
                    for patcher in reversed(patchers):
                        patcher.stop()
        self.assert_nothing_written(before)

    def test_a_review_without_the_station_never_runs_and_a_changed_station_neither(self):
        before = self.snapshot()
        self.patch(stations, "ENROLLED_STATION", None)
        plan = self.plan6()
        self.patch(stations, "ENROLLED_STATION", self.station.enrollment)  # enrolled later
        self.assert_refused(plan, archive.STATION_CHANGED)
        # Another verified station (a different key) after the review is not the reviewed one.
        plan = self.plan6()
        SyntheticStation().install(self)
        self.assert_refused(plan, archive.STATION_CHANGED)
        self.assert_nothing_written(before)

    def test_losing_or_changing_the_station_right_before_the_copy_writes_nothing(self):
        other = SyntheticStation()
        changes = (("lost", {"ENROLLED_STATION": None}),
                   ("other station", {"ENROLLED_STATION": other.enrollment, "PROOF_PROVIDER": other}),
                   ("provider error", {"PROOF_PROVIDER": Failing(OSError("TPM ocupado"))}),
                   ("home PC", {"PROOF_PROVIDER": SyntheticStation(key_name=self.station.enrollment.key_name)}))
        real_claim = intents.SqliteArchiveIntentStore.claim
        tree = self.tree()
        for attempt, (name, change) in enumerate(changes, start=1):
            with self.subTest(name):
                applied = []

                def claim_then_change(store, intent, owner_token, now):
                    # After the confirmation, with the request being claimed: before COPY.
                    if not applied:
                        applied.extend(patch.object(stations, attr, value) for attr, value in change.items())
                        for patcher in applied:
                            patcher.start()
                    return real_claim(store, intent, owner_token, now)

                with patch.object(intents.SqliteArchiveIntentStore, "claim", claim_then_change):
                    try:
                        with self.guard():
                            result = self.run_plan(self.plan6())
                    finally:
                        for patcher in reversed(applied):
                            patcher.stop()
                self.assertEqual([(item.status, item.message) for item in result.items],
                                 [(archive.REJECTED, archive.STATION_LOST)])
                self.copy.assert_not_called()
                self.assertEqual(self.tree(), tree)
                self.assertEqual(self.query("SELECT state, fence FROM document_viewer_archive_intents"),
                                 [{"state": intents.REJECTED, "fence": attempt}])
                self.assertEqual(self.row(6)["status"], "linked")
        # Nothing was written: back on the station, a new review copies once, on a new fence.
        with self.guard():
            result = self.run_plan(self.plan6())
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED)])
        self.assertEqual(self.query("SELECT state, fence FROM document_viewer_archive_intents"),
                         [{"state": intents.REGISTERED, "fence": len(changes) + 1}])
        self.assert_added(tree, {f"EXP-42/{dv27.NAME}": ("file", self.source(6))})

    def test_forged_actor_revoked_permission_and_repeated_request_never_reach_box_again(self):
        tree = self.tree()
        forged = {"id": 1, "username": "luis", "station": "despacho", "station_verified": True}
        with self.assertRaises(archive.ArchiveError):
            self.plan6(actor=forged)
        plan = self.plan6()
        with patch.object(permission, "APPROVED_CONTRACT", dv27.Contract(False)):
            self.assert_refused(plan, permission.NOT_GRANTED_MESSAGE)
        self.copy.assert_not_called()
        plan = self.plan6()
        with self.guard():
            result = self.run_plan(plan)
            self.assertIs(self.run_plan(plan), result)  # double click: same result, no write
        self.assertEqual(self.outcomes(result), [(6, archive.ARCHIVED)])
        again = self.plan6()
        self.assertEqual([(item.outcome, item.message) for item in again.items],
                         [(archive.REJECTED, archive.ALREADY_COPIED)])
        self.assert_refused(again, archive.NOTHING_READY)
        self.assertEqual(self.copy.call_count, 1)
        self.assertEqual(self.intent_states(), [intents.REGISTERED])
        self.assert_added(tree, {f"EXP-42/{dv27.NAME}": ("file", self.source(6))})

    def test_four_concurrent_reviews_on_the_station_copy_once(self):
        # As four processes on one database: the in-memory guard is not shared.
        self.patch(archive, "_claim", lambda item_id: True)
        self.patch(archive, "_release", lambda item_id: None)
        plans = [self.plan6() for _ in range(4)]
        entered, release, lock, outcomes = threading.Event(), threading.Event(), threading.Lock(), []

        def slow(item_id, **kwargs):
            entered.set()
            release.wait(30)
            return p3b2.REAL_COPY(item_id, **kwargs)

        def worker(plan):
            try:
                value = [(item.status, item.message) for item in self.run_plan(plan).items][0]
            except archive.ArchiveError as exc:
                value = ("error", str(exc))
            with lock:
                outcomes.append(value)

        self.copy.side_effect = slow
        tree = self.tree()
        threads = [threading.Thread(target=worker, args=(plan,)) for plan in plans]
        for thread in threads:
            thread.start()
        try:
            self.assertTrue(entered.wait(60))
            deadline = time.monotonic() + 60
            while len(outcomes) < 3 and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            release.set()
            for thread in threads:
                thread.join(90)
        self.assertEqual(len(outcomes), 4, outcomes)
        self.assertEqual([status for status, _message in outcomes].count(archive.ARCHIVED), 1, outcomes)
        self.assertEqual([outcome for outcome in outcomes if outcome[0] != archive.ARCHIVED],
                         [(archive.REJECTED, archive.IN_FLIGHT)] * 3)
        self.assertEqual(self.copy.call_count, 1)
        self.assertEqual(self.intent_states(), [intents.REGISTERED])
        self.assert_added(tree, {f"EXP-42/{dv27.NAME}": ("file", self.source(6))})

    def test_the_dialog_shows_the_station_refusal_and_never_takes_the_consent(self):
        self.patch(stations, "ENROLLED_STATION", None)
        dialog = self.open_inbox([6, 1])
        before = self.snapshot()
        with self.guard():
            form = self.open_archive(dialog)
            self.assertEqual(form.blocker, "")
            self.choose(form.folder_select, filing.ROOT_LABEL)
            self.choose(form.nomenclature_selects["inbox:6"], "PASAPORTE · SOLICITANTE")
            self.assertEqual([item.proposed_name for item in form.plan.ready], [dv27.NAME])
            self.assertEqual(form.status.value, stations.NOT_ENROLLED_MESSAGE)
            self.assertTrue(form.confirm.disabled)
            self.confirm(form)
            self.assertIsNone(form.consented)
            self.assertTrue(form.submit_button.disabled)
            self.assertIsNone(form.submit())
            form.close()
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)


# ---------------------------------------------------------------------- real processes


CHILD_MARKER = "from backend.services import document_viewer_archive_repository as repo"
assert sec.CHILD.count(CHILD_MARKER) == 1  # reuse P3B3's fail-closed child guard up to this line
CHILD = sec.CHILD.split(CHILD_MARKER)[0] + r"""
import hashlib, secrets
from backend.services import document_viewer_archive_host_policy as stations
from backend.services import document_viewer_archive_repository as repo
from backend.services import document_viewer_box_archive_service as archive

# THIS process' machine: a synthetic secret (sandbox only). The anchor is the despacho's public key,
# copied as-is, as any other machine could copy the configuration.
secret = int(cfg["secret"], 16)
x, y = stations._mul(secret, stations._G)
own_key = b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")
anchor = bytes.fromhex(cfg["anchor"])


class Provider:
    def prove(self, key_name, message):
        digest = int.from_bytes(hashlib.sha256(message).digest(), "big")
        while True:
            k = secrets.randbelow(stations._N - 1) + 1
            r = stations._mul(k, stations._G)[0] % stations._N
            s = pow(k, -1, stations._N) * (digest + r * secret) % stations._N
            if r and s:
                break
        return stations.StationProof(public_key=anchor if cfg["present"] == "anchor" else own_key,
                                     signature=r.to_bytes(32, "big") + s.to_bytes(32, "big"),
                                     hardware=True, exportable=False, remote_session=False)


stations.ENROLLED_STATION = stations.StationEnrollment(cfg["station_id"], cfg["key_name"], anchor)
stations.PROOF_PROVIDER = Provider()
real_copy = inbox.copy_inbox_item_to_expedient_box


def copy(*args, **kwargs):
    time.sleep(cfg.get("hold", 0))
    # The service's own guard, right before the certified copy, as in ``certified_copy``.
    denied = archive._station_denied(cfg["db"], cfg["fingerprint"])
    if denied:
        raise archive.ArchiveError(denied)
    return real_copy(*args, **kwargs)


intent = repo.ArchiveIntent(**cfg["intent"])
Path(cfg["ready"]).write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 120
while not Path(cfg["go"]).exists():
    if time.monotonic() > deadline:
        os._exit(91)
    time.sleep(0.01)
outcome = repo.run_intent(repo.SqliteArchiveIntentStore(cfg["db"]), intent,
                          repo.governed_box_copy(intent, copy=copy),
                          evidence=repo.registered_copy_evidence(cfg["db"]))
print(json.dumps({"status": outcome.status, "destination": outcome.destination_path,
                  "message": outcome.message}))
"""


class ProcessStationTests(sec.SandboxMixin, p3b1.BoxCopyBase):
    """Real independent processes; the certified P3B1 copy runs FOR REAL behind the station guard."""

    start = sec.MultiProcessTests.start
    files = sec.MultiProcessTests.files
    intent_rows = sec.MultiProcessTests.intents

    def setUp(self):
        super().setUp()
        self.sandbox(self.root, self.db)
        intents.apply_schema(self.db)
        self.item = self.add_item()
        self.intent = intents.ArchiveIntent(
            inbox_item_id=self.item, client_id=7, expedient_id=42, subfolder="", nomenclature_key=KEY,
            source_sha256=p3b1.sha(self.sources[self.item][1]), requested_by_user_id=1)
        self.go = self.root / "go"
        self.despacho = SyntheticStation()
        self.home = SyntheticStation()

    def spawn(self, name, db, station, present="own", **extra):
        config = {"root": str(self.root), "db": str(db), "bandeja": str(self.root / "bandeja"),
                  "intent": asdict(self.intent), "ready": str(self.root / f"{name}.ready"), "go": str(self.go),
                  "secret": format(station.secret, "x"), "present": present,
                  "anchor": self.despacho.public_key.hex(), "station_id": self.despacho.enrollment.station_id,
                  "key_name": self.despacho.enrollment.key_name,
                  "fingerprint": stations.key_fingerprint(self.despacho.public_key), **extra}
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), env.get("PYTHONPATH", "")]))
        process = subprocess.Popen([sys.executable, "-c", CHILD, json.dumps(config)], cwd=REPO_ROOT, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def copy_database(self, name):
        target = self.root / name
        with closing(sqlite3.connect(self.db)) as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
        return target

    def test_four_processes_on_the_station_and_one_database_copy_once(self):
        results = self.start(*[self.spawn(str(index), self.db, self.despacho, hold=1.0) for index in range(4)])
        self.assertEqual([code for code, _answer in results], [0] * 4, results)
        statuses = [answer["status"] for _code, answer in results]
        self.assertEqual(statuses.count(intents.DONE), 1, statuses)
        self.assertLessEqual(set(statuses), {intents.DONE, intents.IN_PROGRESS, intents.ALREADY_DONE})
        self.assertEqual(self.files(), [NAME])  # never a _2 of the same document
        self.assertEqual((self.box / NAME).read_bytes(), self.sources[self.item][1])
        self.assertEqual(len(self.events(self.item, "copied_to_box")), 1)
        self.assertEqual(self.intent_rows(), [(intents.REGISTERED, str(self.box / NAME))])

    def test_the_home_pc_is_refused_even_with_the_copied_configuration_and_database(self):
        state = self.item_state(self.item)
        home_db = self.copy_database("pc_casa.db")
        # One after the other: each attempt must be refused by the station, not by a concurrent claim.
        results = [result for db, present in ((self.db, "own"), (self.db, "anchor"), (home_db, "own"))
                   for result in self.start(self.spawn("0", db, self.home, present=present))]
        self.assertEqual([code for code, _answer in results], [0, 0, 0], results)
        self.assertEqual([answer["status"] for _code, answer in results], [intents.REFUSED] * 3)
        self.assertEqual([answer["message"] for _code, answer in results],
                         [stations.NOT_THIS_WORKSTATION_MESSAGE, stations.UNVERIFIED_MESSAGE,
                          stations.NOT_THIS_WORKSTATION_MESSAGE])
        self.assertEqual(self.files(), [])
        self.assertEqual(self.item_state(self.item), state)
        self.assertEqual(self.events(self.item, "copied_to_box"), [])
        for db in (self.db, home_db):
            self.assertEqual([row_state for row_state, _path in self.intent_rows(db)], [intents.REJECTED])

    def test_independent_databases_are_separate_authorities_not_global_exclusion(self):
        """Two local databases: each claims on its own. The pilot never presents this as multi-host."""
        copies = [self.copy_database("puesto_a.db"), self.copy_database("puesto_b.db")]
        results = self.start(self.spawn("0", copies[0], self.despacho, hold=0.5),
                             self.spawn("1", copies[1], self.despacho, hold=0.5))
        self.assertEqual([code for code, _ in results], [0, 0], results)
        self.assertEqual([answer["status"] for _code, answer in results], [intents.DONE, intents.DONE])
        for target in copies:
            self.assertEqual([row_state for row_state, _ in self.intent_rows(target)], [intents.REGISTERED])
        self.assertIn(len(self.files()), (1, 2))  # no guarantee across databases
        self.assertEqual(self.intent_rows(), [])  # the original database coordinated nothing
        self.assertIs(intents.MULTI_HOST_GUARANTEE, False)
        self.assertIs(intents.SqliteArchiveIntentStore(self.db).multi_host_guarantee, False)
        self.assertIn(archive.MULTI_HOST_AUTHORITY_PENDING, archive.activation_blockers())


# ---------------------------------------------------------------------- H3 evidence


class H3EvidenceTests(unittest.TestCase):
    def test_containment_runs_on_windows_with_zero_skips(self):
        """Global acceptance is not enough: every ContainmentTests case must RUN and pass here."""
        if os.name != "nt":
            self.fail("H3 is only evidenced on real Windows (NTFS in TEMP): no Windows, no H3 evidence.")
        names = unittest.defaultTestLoader.getTestCaseNames(dv28.ContainmentTests)
        self.assertEqual(len(names), 7, names)
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(dv28.ContainmentTests).run(result)
        self.assertEqual(result.testsRun, len(names))
        self.assertEqual([str(test) for test, _reason in result.skipped], [])
        self.assertEqual([str(test) for test, _trace in result.expectedFailures], [])
        self.assertEqual([str(test) for test in result.unexpectedSuccesses], [])
        self.assertEqual([(str(test), trace) for test, trace in result.failures + result.errors], [])


if __name__ == "__main__":
    unittest.main()
