"""FCP-8C-02: auditable, deterministic, secret-free validation report over the
FCP-8 evaluations. Offline and synthetic - observations come from the A-02 /
B-01 / C-01 test fixtures (fake Director services); no Runner, Git, process,
network or file is touched."""

from __future__ import annotations

import ast
import builtins
import dataclasses
import hashlib
import json
import os
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_validation_acceptance as va
from scripts.ai import fabric_validation_contract as vc
from scripts.ai import fabric_validation_report as rp
from scripts.ai import fabric_validation_rules as vr
from scripts.ai import fabric_validation_single as vs
from scripts.tests import test_fabric_validation_acceptance as ta
from scripts.tests import test_fabric_validation_dag as td
from scripts.tests import test_fabric_validation_single as ts

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_validation_report.py"

ALL_TRUE = dict.fromkeys(vc.DIMENSIONS, True)
# SHA-256 of the all-TRUE assessment report; any platform must reproduce it.
GOLDEN_ALL_TRUE_SHA256 = "8c860d494460756e3ab1f5d21275e3d6ce74313d29951c11391230c44d6bed7b"
FORBIDDEN_TEXT = (ts.EMAIL, ts.SECRET_DIR, ts.RUN, ts.WORKER, td.BLUEPRINT, "provider prose", "pytest", "Traceback",
                  "work_order_text", "C:/", "Users", "@", "\\", "sk-", "Bearer", "unittest", "Ran 40 tests")


def assessment(**values) -> vc.ValidationAssessment:
    return vc.assess_validation(vc.ValidationFacts(**{**ALL_TRUE, **values}))


def single():
    return ts.observe_consistent()


def dag(**kwargs):
    return td.obs(td.dag(**kwargs))


def report_dict(observation=None, acceptance=None) -> dict:
    return rp.build_report(assessment() if observation is None else observation, acceptance).to_dict()


def reseal(data: dict) -> dict:
    """A forger that recomputes manifest and digest after altering a field."""
    data = json.loads(json.dumps(data))
    data["manifest"] = {name: rp._sha256(rp._canonical(data.get(name))) for name in rp.MANIFEST_SECTIONS}
    body = {k: v for k, v in data.items() if k != "report_sha256"}
    data["report_sha256"] = rp._sha256(rp._canonical(body))
    return data


def codes_of(data) -> tuple:
    return rp.verify_report(data).codes


# ---------------------------------------------------------------------------
class PositiveCompositionTests(unittest.TestCase):
    def test_complete_single_run_with_passed_acceptance(self):
        r = rp.build_report(single(), ta.project())
        self.assertEqual(r.verdict, vr.VALIDATION_COMPLETE)
        self.assertEqual(r.reason_codes, ())
        self.assertEqual(len(r.claims["verified"]), len(vc.DIMENSIONS) + 1)
        self.assertIn(rp.ACCEPTANCE_CLAIM_ID, r.claims["verified"])
        self.assertEqual((r.claims["unknown"], r.claims["failed"]), ((), ()))
        d = r.to_dict()
        self.assertEqual([s["kind"] for s in d["sources"]], [rp.KIND_SINGLE_RUN, rp.KIND_ACCEPTANCE])
        self.assertEqual([s["source_id"] for s in d["sources"]], ["SRC-1", "SRC-2"])
        self.assertTrue(rp.verify_report(r).valid)

    def test_report_composes_existing_evaluations_verbatim(self):
        o, p = single(), ta.project()
        d = report_dict(o, p)
        self.assertEqual(d["classification"], vr.EvidenceClassification.to_dict(vr.classify_evidence(o)))
        self.assertEqual(d["acceptance"], va.AcceptanceProjection.to_dict(p))
        self.assertEqual(d["sources"][0]["sha256"], hashlib.sha256(vs.canonical_json(o).encode()).hexdigest())
        self.assertEqual(d["sources"][1]["sha256"], hashlib.sha256(va.canonical_json(p).encode()).hexdigest())

    def test_claims_partition_verified_unknown_failed(self):
        r = rp.build_report(assessment(work_success=None, safety_clean=False, scope_clean="yes"))
        self.assertEqual(r.claims["failed"], ("unit.0.safety_clean",))
        self.assertEqual(r.claims["unknown"], ("unit.0.work_success", "unit.0.scope_clean"))
        self.assertEqual(len(r.claims["verified"]), 3)
        self.assertEqual(r.to_dict()["claim_counts"], {"verified": 3, "unknown": 2, "failed": 1})
        self.assertEqual(r.verdict, vr.HUMAN_REVIEW_REQUIRED)

    def test_dag_units_follow_native_worker_order(self):
        r = rp.build_report(dag(n=3))
        ids = r.claims["verified"] + r.claims["unknown"] + r.claims["failed"]
        self.assertEqual(sorted({i.split(".")[1] for i in ids}), ["0", "1", "2"])
        self.assertEqual(r.claims["unknown"], tuple(f"unit.{i}.{d}" for i in range(3)
                                                    for d in (vc.SAFETY_CLEAN, vc.ACCEPTANCE_PROVEN)))
        self.assertEqual(r.verdict, vr.UNPROVEN)
        self.assertTrue(rp.verify_report(r).valid)


# ---------------------------------------------------------------------------
class NegativeAndMissingEvidenceTests(unittest.TestCase):
    def test_missing_evidence_is_unknown_never_verified(self):
        o = ts.observe_consistent(shared={"evidence_complete": None})
        r = rp.build_report(o)
        self.assertIn("unit.0.evidence_complete", r.claims["unknown"])
        self.assertNotIn("unit.0.evidence_complete", r.claims["verified"])
        self.assertNotEqual(r.verdict, vr.VALIDATION_COMPLETE)

    def test_none_and_malformed_never_become_pass(self):
        for bad in (None, 1, "True", 0.0):
            for dimension in vc.DIMENSIONS:
                with self.subTest(bad=repr(bad), dimension=dimension):
                    r = rp.build_report(assessment(**{dimension: bad}))
                    self.assertIn(f"unit.0.{dimension}", r.claims["unknown"])
                    self.assertEqual(r.verdict, vr.UNPROVEN)

    def test_failed_acceptance_preserved_as_negative(self):
        p = ta.project(ta.evidence(acceptance=ta.record(ta.entry(exit_code=1), decision="FAILED"),
                                   work_status="FAILED", work_status_source="PROVIDER"))
        r = rp.build_report(assessment(work_success=None, acceptance_proven=None), p)
        self.assertIn(rp.ACCEPTANCE_FAILED, r.reason_codes)
        self.assertIn(rp.ACCEPTANCE_CLAIM_ID, r.claims["failed"])
        self.assertEqual(r.verdict, vr.HUMAN_REVIEW_REQUIRED)

    def test_acceptance_contradicting_observation_requires_review(self):
        p = ta.project(ta.evidence(acceptance=ta.record(decision="FAILED"), work_status_source="PROVIDER"))
        self.assertIs(p.acceptance_proven, False)
        r = rp.build_report(assessment(), p)
        self.assertIn(rp.ACCEPTANCE_CONTRADICTS_OBSERVATION, r.reason_codes)
        self.assertEqual(r.verdict, vr.HUMAN_REVIEW_REQUIRED)

    def test_unproven_acceptance_blocks_completion(self):
        r = rp.build_report(assessment(), ta.project(commands=None))
        self.assertIn(rp.ACCEPTANCE_UNPROVEN, r.reason_codes)
        self.assertIn(rp.ACCEPTANCE_CLAIM_ID, r.claims["unknown"])
        self.assertEqual(r.verdict, vr.UNPROVEN)

    def test_invalid_inputs_never_raise_and_are_unproven(self):
        for bad in (None, "x", 42, {"work_success": True}, vc.ValidationFacts(**ALL_TRUE), object()):
            with self.subTest(bad=type(bad).__name__):
                r = rp.build_report(bad)
                self.assertEqual(r.verdict, vr.UNPROVEN)
                self.assertEqual(r.to_dict()["sources"], [])
                self.assertIn(vr.NO_UNITS, r.reason_codes)

    def test_acceptance_input_typing_and_binding(self):
        cases = ((assessment(), {"status": "PASSED"}, rp.ACCEPTANCE_NOT_TYPED),
                 (dag(), ta.project(), rp.ACCEPTANCE_NOT_BINDABLE),
                 ("bad", ta.project(), rp.ACCEPTANCE_NOT_BINDABLE))
        for observation, acceptance, code in cases:
            with self.subTest(code=code):
                r = rp.build_report(observation, acceptance)
                self.assertIn(code, r.reason_codes)
                self.assertIsNone(r.to_dict()["acceptance"])
                self.assertNotEqual(r.verdict, vr.VALIDATION_COMPLETE)
                self.assertTrue(rp.verify_report(r).valid)


# ---------------------------------------------------------------------------
class ForgeryTests(unittest.TestCase):
    def test_tampered_acceptance_projection_refused_and_not_serialized(self):
        p = ta.project()
        object.__setattr__(p, "codes", (ts.EMAIL,))
        r = rp.build_report(single(), p)
        self.assertIn(rp.ACCEPTANCE_INPUT_INCONSISTENT, r.reason_codes)
        self.assertNotIn(ts.EMAIL, r.canonical)
        self.assertIsNone(r.to_dict()["acceptance"])

    def test_tampered_command_evidence_refused(self):
        p = ta.project()
        object.__setattr__(p.commands[0], "exit_code", 1)
        r = rp.build_report(single(), p)
        self.assertIn(rp.ACCEPTANCE_INPUT_INCONSISTENT, r.reason_codes)
        self.assertNotEqual(r.verdict, vr.VALIDATION_COMPLETE)

    def test_tampered_single_observation_is_not_complete(self):
        o = single()
        object.__setattr__(o, "facts", vc.ValidationFacts(**{**ALL_TRUE, "evidence_complete": False}))
        r = rp.build_report(o)
        self.assertIn(vr.INPUT_INCONSISTENT, r.reason_codes)
        self.assertNotEqual(r.verdict, vr.VALIDATION_COMPLETE)

    def test_unserializable_source_is_recorded(self):
        a = assessment()
        object.__setattr__(a, "classification", object())
        r = rp.build_report(a)
        self.assertIn(rp.SOURCE_NOT_SERIALIZABLE, r.reason_codes)
        self.assertEqual(r.to_dict()["sources"], [])
        self.assertTrue(rp.verify_report(r).valid)

    def test_hand_made_report_refused_by_constructor(self):
        d = report_dict()
        d["verdict"] = vr.UNPROVEN
        for canonical in (rp._canonical(d), "{}", "", 7):
            with self.subTest(canonical=repr(canonical)[:20]):
                with self.assertRaises(ValueError):
                    rp.ValidationReport(canonical)

    def test_forged_complete_verdict_over_failed_claim_refused(self):
        d = report_dict(assessment(safety_clean=False))
        d["verdict"] = vr.VALIDATION_COMPLETE
        d["claims"]["verified"].append(d["claims"]["failed"].pop())
        d["claim_counts"] = {"verified": 6, "unknown": 0, "failed": 0}
        self.assertEqual(codes_of(reseal(d)), ("CONTENT_MISMATCH",))

    def test_forged_classification_refused(self):
        d = report_dict(assessment(work_success=None))
        d["classification"]["outcomes"]["VALIDATION_COMPLETE"] = True
        self.assertEqual(codes_of(reseal(d)), ("CLASSIFICATION_INVALID",))
        d = report_dict(assessment(work_success=None))
        d["classification"]["units"][0]["work_success"] = "TRUE"
        self.assertEqual(codes_of(reseal(d)), ("CLASSIFICATION_INVALID",))

    def test_forged_acceptance_section_refused(self):
        d = report_dict(single(), ta.project())
        d["acceptance"]["commands"][0]["exit_code"] = 1
        self.assertEqual(codes_of(reseal(d)), ("ACCEPTANCE_INVALID",))
        d = report_dict(single(), ta.project())
        d["acceptance"]["commands"][0]["test_count"] = 40
        self.assertEqual(codes_of(reseal(d)), ("ACCEPTANCE_INVALID",))

    def test_dropping_a_negative_reason_code_refused(self):
        d = report_dict(assessment(provenance_bound=False))
        d["reason_codes"] = []
        d["verdict"] = vr.VALIDATION_COMPLETE
        self.assertEqual(codes_of(reseal(d)), ("CONTENT_MISMATCH",))

    def test_injected_input_code_inconsistent_with_sections_refused(self):
        d = report_dict(single(), ta.project())
        d["reason_codes"] = [rp.ACCEPTANCE_NOT_BINDABLE]
        self.assertEqual(codes_of(reseal(d)), ("CONTENT_MISMATCH",))


# ---------------------------------------------------------------------------
class TamperingTests(unittest.TestCase):
    def test_every_field_alteration_detected(self):
        base = report_dict(single(), ta.project())
        mutations = {
            "verdict": lambda d: d.__setitem__("verdict", vr.UNPROVEN),
            "claim_counts": lambda d: d["claim_counts"].__setitem__("verified", 99),
            "schema_version": lambda d: d.__setitem__("schema_version", 2),
            "marker": lambda d: d.__setitem__("marker", "X"),
            "extra_key": lambda d: d.__setitem__("extra", 1),
            "missing_key": lambda d: d.pop("claims"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                d = json.loads(json.dumps(base))
                mutate(d)
                self.assertFalse(rp.verify_report(d).valid)
                self.assertFalse(rp.verify_report(reseal(d)).valid)

    def test_hash_tampering_detected(self):
        d = report_dict()
        d["report_sha256"] = "0" * 64
        self.assertEqual(codes_of(d), ("DIGEST_MISMATCH", "CONTENT_MISMATCH"))
        d = report_dict()
        d["report_sha256"] = "zz"
        self.assertFalse(rp.verify_report(d).valid)

    def test_manifest_tampering_detected(self):
        d = report_dict()
        d["manifest"]["claims"] = "f" * 64
        self.assertIn("MANIFEST_MISMATCH", codes_of(d))
        d = report_dict()
        d["manifest"].pop("acceptance")
        self.assertIn("MANIFEST_MISMATCH", codes_of(d))

    def test_section_change_without_reseal_detected(self):
        d = report_dict(assessment(work_success=None))
        d["claims"]["unknown"] = []
        self.assertEqual(codes_of(d), ("MANIFEST_MISMATCH", "DIGEST_MISMATCH", "CONTENT_MISMATCH"))

    def test_authority_flags_cannot_be_raised(self):
        for flag in rp.AUTHORITY_FLAGS:
            for value in (True, 0, None, "false"):
                with self.subTest(flag=flag, value=value):
                    d = report_dict()
                    d[flag] = value
                    self.assertFalse(rp.verify_report(reseal(d)).valid)
        d = report_dict()
        d["classification"]["merging_allowed"] = True
        self.assertEqual(codes_of(reseal(d)), ("CLASSIFICATION_INVALID",))

    def test_list_order_alteration_detected(self):
        d = report_dict(assessment(work_success=None, safety_clean=None))
        d["claims"]["unknown"].reverse()
        self.assertEqual(codes_of(reseal(d)), ("CONTENT_MISMATCH",))
        d = report_dict(assessment(work_success=None, safety_clean=None))
        d["reason_codes"].reverse()
        self.assertEqual(codes_of(reseal(d)), ("REASON_CODES_INVALID",))

    def test_worker_order_alteration_detected(self):
        workers = list(td.chain(3, {1: {"evidence_complete": None}}))
        d = report_dict(dag(workers=tuple(workers)))
        units = d["classification"]["units"]
        units[0], units[1] = units[1], units[0]
        self.assertFalse(rp.verify_report(reseal(d)).valid)

    def test_source_and_claim_id_alteration_detected(self):
        alterations = (
            lambda d: d["sources"][0].__setitem__("source_id", "SRC-9"),
            lambda d: d["sources"].reverse(),
            lambda d: d["sources"][0].__setitem__("kind", rp.KIND_DAG_RUN),
            lambda d: d["sources"][1].__setitem__("sha256", "1" * 64),
            lambda d: d["sources"].pop(),
            lambda d: d["claims"]["verified"].__setitem__(0, "unit.1.work_success"),
        )
        for index, alter in enumerate(alterations):
            with self.subTest(index=index):
                d = report_dict(single(), ta.project())
                alter(d)
                self.assertFalse(rp.verify_report(reseal(d)).valid)

    def test_source_binding_detects_substituted_observation(self):
        r = rp.build_report(single(), ta.project())
        self.assertTrue(rp.verify_report(r, observation=single(), acceptance=ta.project()).valid)
        # Same classification, different native source (preflight ABSENT): only the source digest differs.
        other = ts.observe_consistent(evidence_overrides={"preflight": None})
        self.assertEqual(vr.classify_evidence(other), vr.classify_evidence(single()))
        self.assertEqual(rp.verify_report(r, observation=other, acceptance=ta.project()).codes,
                         ("SOURCE_BINDING_MISMATCH",))
        self.assertEqual(rp.verify_report(r, observation=single()).codes, ("SOURCE_BINDING_MISMATCH",))


# ---------------------------------------------------------------------------
class AdversarialSchemaTests(unittest.TestCase):
    def test_non_canonical_text_refused(self):
        text = rp.build_report(assessment()).canonical
        variants = (json.dumps(json.loads(text), indent=1), json.dumps(json.loads(text)), text + "\n",
                    " " + text, text.replace("\n", "\r\n") + "\r\n")
        for variant in variants:
            with self.subTest(variant=variant[:15]):
                self.assertFalse(rp.verify_report(variant).valid)
        self.assertEqual(rp.verify_report(text + " ").codes, ("NOT_CANONICAL",))

    def test_malformed_payloads_refused_without_raising(self):
        text = rp.build_report(assessment()).canonical
        dup = '{"schema":"a","schema":"b"}'
        cases = (("{", "NOT_JSON"), (dup, "NOT_JSON"), ('{"a":1.5}', "NOT_JSON"), ('{"a":NaN}', "NOT_JSON"),
                 ("[]", "SCHEMA_INVALID"), ("{}", "SCHEMA_INVALID"), (b"\xff\xfe", "NOT_JSON"),
                 (text.encode("ascii"), None), (3, "INPUT_NOT_SUPPORTED"), (None, "INPUT_NOT_SUPPORTED"),
                 ({"a": object()}, "NOT_JSON"), ({"a": float("nan")}, "NOT_JSON"),
                 ("x" * (rp.MAX_REPORT_BYTES + 1), "SIZE_LIMIT_EXCEEDED"),
                 (b"x" * (rp.MAX_REPORT_BYTES + 1), "SIZE_LIMIT_EXCEEDED"))
        for payload, code in cases:
            with self.subTest(payload=repr(payload)[:30]):
                v = rp.verify_report(payload)
                if code is None:
                    self.assertTrue(v.valid)
                else:
                    self.assertEqual(v.codes, (code,))
                    self.assertIsNone(v.report_sha256)

    def test_type_confusion_in_sections_refused(self):
        alterations = (
            lambda d: d.__setitem__("classification", []),
            lambda d: d.__setitem__("acceptance", "PASSED"),
            lambda d: d.__setitem__("sources", {}),
            lambda d: d.__setitem__("reason_codes", "NO_UNITS"),
            lambda d: d.__setitem__("claims", None),
            lambda d: d["classification"]["outcomes"].__setitem__("UNPROVEN", 0),
            lambda d: d["classification"].__setitem__("units", [{"work_success": "TRUE"}]),
            lambda d: d["sources"][0].__setitem__("schema_version", True),
            lambda d: d.__setitem__("schema_version", True),
            lambda d: d["reason_codes"].append("NOT_A_CODE"),
        )
        for index, alter in enumerate(alterations):
            with self.subTest(index=index):
                d = report_dict(assessment(work_success=None))
                alter(d)
                self.assertFalse(rp.verify_report(reseal(d)).valid)

    def test_depth_limit_enforced(self):
        d = report_dict()
        nested = 1
        for _ in range(rp.MAX_DEPTH + 2):
            nested = [nested]
        d["claims"]["unknown"] = nested
        self.assertEqual(codes_of(reseal(d)), ("UNSAFE_TEXT",))

    def test_verification_result_is_closed(self):
        with self.assertRaises(ValueError):
            rp.ReportVerification(valid=True, codes=("DIGEST_MISMATCH",), report_sha256="0" * 64)
        with self.assertRaises(ValueError):
            rp.ReportVerification(valid=False, codes=("NOT_A_CODE",))
        with self.assertRaises(ValueError):
            rp.ReportVerification(valid=True, codes=())


# ---------------------------------------------------------------------------
class PrivacyTests(unittest.TestCase):
    def test_no_secret_path_pii_or_prose_reaches_any_report(self):
        reports = (
            rp.build_report(single(), ta.project()),
            rp.build_report(dag()),
            rp.build_report(ts.observe_consistent(shared={"evidence_complete": None})),
            rp.build_report(ts.observe_consistent(evidence_overrides={"safety_verdict": ts.EMAIL})),
            rp.build_report(td.obs(td.dag(), expected_manifest_sha256="c" * 64)),
        )
        for r in reports:
            for text in FORBIDDEN_TEXT:
                with self.subTest(text=text):
                    self.assertNotIn(text, r.canonical)
            self.assertFalse(rp._unsafe(r.to_dict(), 0))

    def test_injected_pii_or_path_is_unsafe(self):
        for value in (ts.EMAIL, ts.SECRET_DIR, "C:\\Users\\x", "Traceback (most recent call last)", "a b",
                      "x" * (rp.MAX_TOKEN_LENGTH + 1), "token\nvalue"):
            with self.subTest(value=value[:20]):
                d = report_dict()
                d["reason_codes"] = [value]
                self.assertEqual(codes_of(reseal(d)), ("UNSAFE_TEXT",))
                d = report_dict()
                d[value] = False
                self.assertEqual(codes_of(reseal(d)), ("UNSAFE_TEXT",))

    def test_dict_view_is_a_copy(self):
        r = rp.build_report(single(), ta.project())
        r.to_dict()["verdict"] = vr.HUMAN_REVIEW_REQUIRED
        r.to_dict()["acceptance"]["commands"].clear()
        self.assertEqual(r.verdict, vr.VALIDATION_COMPLETE)
        self.assertTrue(rp.verify_report(r).valid)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.canonical = "{}"


# ---------------------------------------------------------------------------
class AuthorityTests(unittest.TestCase):
    def test_no_authority_ever(self):
        reports = (rp.build_report(single(), ta.project()), rp.build_report(assessment(safety_clean=False)),
                   rp.build_report(dag()), rp.build_report(None))
        for r in reports:
            d = r.to_dict()
            for flag in rp.AUTHORITY_FLAGS:
                with self.subTest(flag=flag):
                    self.assertIs(d[flag], False)
                    self.assertIs(getattr(r, flag), False)
            for flag in ("merging_allowed", "approved", "certified", "execution_allowed"):
                self.assertIs(getattr(rp.verify_report(r), flag), False)

    def test_authority_flags_are_not_fields(self):
        names = {f.name for f in dataclasses.fields(rp.ValidationReport)}
        self.assertEqual(names, {"canonical"})
        r = rp.build_report(assessment())
        for flag in ("merging_allowed", "approved", "certified", "execution_allowed"):
            with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
                setattr(r, flag, True)
            with self.assertRaises(TypeError):
                dataclasses.replace(r, **{flag: True})

    def test_canonical_json_accepts_only_the_contract_type(self):
        r = rp.build_report(assessment())
        self.assertEqual(rp.canonical_json(r), r.canonical)
        for bad in (r.to_dict(), r.canonical, None):
            with self.assertRaises(TypeError):
                rp.canonical_json(bad)


# ---------------------------------------------------------------------------
class DeterminismTests(unittest.TestCase):
    def test_byte_identical_and_idempotent(self):
        first = rp.build_report(single(), ta.project())
        for _ in range(3):
            again = rp.build_report(single(), ta.project())
            self.assertEqual(again.to_bytes(), first.to_bytes())
            self.assertEqual(again, first)
        self.assertEqual(rp.build_report(dag()).canonical, rp.build_report(dag()).canonical)

    def test_golden_digest_is_platform_stable(self):
        r = rp.build_report(assessment())
        self.assertEqual(r.report_sha256, GOLDEN_ALL_TRUE_SHA256)
        raw = r.to_bytes()
        self.assertTrue(raw.isascii())
        for byte in (b"\r", b"\n", b"\t", b": ", b", "):
            self.assertNotIn(byte, raw)
        body = {k: v for k, v in r.to_dict().items() if k != "report_sha256"}
        self.assertEqual(hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
                         .hexdigest(), r.report_sha256)

    def test_digest_differs_for_different_input(self):
        digests = {rp.build_report(assessment(**{d: None})).report_sha256 for d in vc.DIMENSIONS}
        digests.add(rp.build_report(assessment()).report_sha256)
        self.assertEqual(len(digests), len(vc.DIMENSIONS) + 1)

    def test_worker_order_changes_the_report(self):
        workers = td.chain(3, {1: {"evidence_complete": None}})
        flipped = (td.worker(td.wid(0)), td.worker(td.wid(1), (td.wid(0),), evidence_complete=None),
                   td.worker(td.wid(2), (td.wid(0),)))
        a, b = rp.build_report(dag(workers=workers)), rp.build_report(dag(workers=flipped))
        self.assertIn("unit.1.evidence_complete", a.claims["unknown"])
        self.assertNotEqual(a.report_sha256, b.report_sha256)
        self.assertTrue(rp.verify_report(a).valid and rp.verify_report(b).valid)

    def test_limits_are_bounded(self):
        cmds = tuple(f"python -c pass{i}" for i in range(va.MAX_COMMANDS))
        p = ta.project(ta.evidence(acceptance=ta.record(*(ta.entry(c) for c in cmds))), commands=cmds)
        big_dag = dag(n=td.vd.MAX_WORKERS)
        for r in (rp.build_report(single(), p), rp.build_report(big_dag)):
            self.assertLessEqual(len(r.canonical), rp.MAX_REPORT_BYTES)
            self.assertLessEqual(len(r.reason_codes), rp.MAX_REASON_CODES)
            self.assertTrue(rp.verify_report(r).valid)
        self.assertEqual(rp.build_report(big_dag).to_dict()["classification"]["unit_count"], td.vd.MAX_WORKERS)


# ---------------------------------------------------------------------------
class PurityAndRegressionTests(unittest.TestCase):
    def test_no_io_process_or_network(self):
        boom = mock.Mock(side_effect=AssertionError("side effect"))
        with mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(socket, "socket", boom), mock.patch.object(os, "replace", boom), \
                mock.patch.object(os, "remove", boom), mock.patch.object(os, "getenv", boom), \
                mock.patch.object(os, "mkdir", boom):
            r = rp.build_report(single(), ta.project())
            self.assertTrue(rp.verify_report(r.canonical, observation=single(), acceptance=ta.project()).valid)
        boom.assert_not_called()

    def test_module_imports_only_stdlib_and_fcp8(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(f"{node.module}.{a.name}" if node.module else a.name for a in node.names)
        allowed_stdlib = {"__future__.annotations", "hashlib", "json", "re", "dataclasses.dataclass",
                          "dataclasses.fields", "typing.Optional"}
        fcp8 = {n for n in imported if "fabric_validation_" in n}
        self.assertEqual(imported - fcp8, allowed_stdlib)
        for forbidden in ("os", "subprocess", "socket", "fabric_director", "runner_pipeline", "claude_runner"):
            self.assertFalse(any(n == forbidden or n.endswith("." + forbidden) for n in imported))

    def test_upstream_evaluations_unchanged_by_reporting(self):
        o, p = single(), ta.project()
        before = (vr.canonical_json(vr.classify_evidence(o)), va.canonical_json(p))
        rp.build_report(o, p)
        rp.verify_report(rp.build_report(o, p), observation=o, acceptance=p)
        self.assertEqual(before, (vr.canonical_json(vr.classify_evidence(o)), va.canonical_json(p)))

    def test_report_verdict_never_better_than_rules_verdict(self):
        rank = {vr.VALIDATION_COMPLETE: 2, vr.UNPROVEN: 1, vr.HUMAN_REVIEW_REQUIRED: 0}
        observations = (single(), dag(), assessment(work_success=None), assessment(safety_clean=False),
                        ts.observe_consistent(shared={"evidence_complete": False}), None)
        for o in observations:
            for p in (None, ta.project(), ta.project(commands=None)):
                with self.subTest(o=type(o).__name__, p=p is not None):
                    r = rp.build_report(o, p)
                    self.assertLessEqual(rank[r.verdict], rank[vr.classify_evidence(o).verdict])
                    self.assertTrue(rp.verify_report(r, observation=o, acceptance=p).valid)


if __name__ == "__main__":
    unittest.main()
