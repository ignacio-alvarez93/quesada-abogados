"""FCP-8A-01: Validation & Evidence contract V1 - independent work/evidence
assessment. Offline, synthetic facts only."""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import itertools
import json
import os
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_validation_contract as vc

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_validation_contract.py"
TEST_PATH = Path(__file__).resolve()

ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
             "auto_retry_allowed", "resume_allowed")
ALL_TRUE = {d: True for d in vc.DIMENSIONS}


def facts(**overrides):
    values = dict(ALL_TRUE)
    values.update(overrides)
    return vc.ValidationFacts(**values)


def assess(**overrides):
    return vc.assess_validation(facts(**overrides))


def outcomes(a):
    return (a.technical_success, a.evidence_sufficient, a.ready_for_human_review)


# ---------------------------------------------------------------------------
class IndependenceTests(unittest.TestCase):
    def test_all_true_is_ready_for_human_review(self):
        a = assess()
        self.assertEqual(a.classification, vc.READY_FOR_HUMAN_REVIEW)
        self.assertEqual(outcomes(a), (True, True, True))
        self.assertEqual(a.reasons, ())

    def test_work_success_does_not_imply_evidence_complete(self):
        a = vc.assess_validation(vc.ValidationFacts(work_success=True, safety_clean=True, scope_clean=True))
        self.assertTrue(a.technical_success)
        self.assertFalse(a.evidence_sufficient)
        self.assertEqual(a.state_of(vc.EVIDENCE_COMPLETE), vc.STATE_UNKNOWN)
        self.assertEqual(a.classification, vc.TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT)

    def test_evidence_complete_does_not_imply_work_success(self):
        a = vc.assess_validation(vc.ValidationFacts(evidence_complete=True, provenance_bound=True,
                                                    acceptance_proven=True))
        self.assertTrue(a.evidence_sufficient)
        self.assertFalse(a.technical_success)
        self.assertEqual(a.state_of(vc.WORK_SUCCESS), vc.STATE_UNKNOWN)
        self.assertEqual(a.classification, vc.EVIDENCE_SUFFICIENT_NO_TECHNICAL_SUCCESS)

    def test_work_failure_with_complete_evidence(self):
        a = assess(work_success=False, acceptance_proven=False)
        self.assertEqual(outcomes(a), (False, False, False))
        self.assertEqual(a.state_of(vc.EVIDENCE_COMPLETE), vc.STATE_TRUE)
        self.assertIn(vc.WORK_NOT_SUCCESSFUL, a.reasons)

    def test_technical_success_reads_only_work_dimensions(self):
        for combo in itertools.product((True, False, None), repeat=3):
            a = assess(**dict(zip(vc.EVIDENCE_DIMENSIONS, combo)))
            if vc.INCONSISTENT_FACTS != a.classification:
                self.assertTrue(a.technical_success, combo)

    def test_evidence_sufficient_reads_only_evidence_dimensions(self):
        for combo in itertools.product((True, False, None), repeat=3):
            a = assess(**dict(zip(vc.WORK_DIMENSIONS, combo)))
            if vc.INCONSISTENT_FACTS != a.classification:
                self.assertTrue(a.evidence_sufficient, combo)

    def test_each_false_dimension_alone_blocks_readiness(self):
        for d in vc.DIMENSIONS:
            a = assess(**{d: False})
            self.assertFalse(a.ready_for_human_review, d)
            self.assertIn(vc._DIMENSION_REASON[d][vc.STATE_FALSE], a.reasons)

    def test_exhaustive_ready_iff_every_dimension_true(self):
        for combo in itertools.product((True, False, None), repeat=len(vc.DIMENSIONS)):
            a = vc.assess_validation(vc.ValidationFacts(*combo))
            self.assertEqual(a.ready_for_human_review, all(v is True for v in combo), combo)
            self.assertEqual(a.ready_for_human_review, a.reasons == ())


class UnknownTests(unittest.TestCase):
    def test_default_facts_are_all_unknown_and_not_ready(self):
        a = vc.assess_validation(vc.ValidationFacts())
        self.assertEqual(a.states, (vc.STATE_UNKNOWN,) * 6)
        self.assertEqual(a.classification, vc.NOT_READY)
        self.assertEqual(outcomes(a), (False, False, False))

    def test_each_unknown_dimension_alone_blocks_readiness(self):
        for d in vc.DIMENSIONS:
            a = assess(**{d: None})
            self.assertFalse(a.ready_for_human_review, d)
            self.assertEqual(a.reasons, (vc._DIMENSION_REASON[d][vc.STATE_UNKNOWN],))

    def test_truthy_non_bool_values_are_malformed_never_true(self):
        for bad in (1, "True", "TRUE", "yes", 1.0, [True], {"v": True}, object()):
            for d in vc.DIMENSIONS:
                a = assess(**{d: bad})
                self.assertEqual(a.state_of(d), vc.STATE_MALFORMED, (d, bad))
                self.assertEqual(a.reasons, (vc._DIMENSION_REASON[d][vc.STATE_MALFORMED],))
                self.assertFalse(a.ready_for_human_review)

    def test_falsy_non_bool_values_are_malformed_not_false(self):
        for bad in (0, "", "False", [], 0.0):
            a = assess(work_success=bad)
            self.assertEqual(a.state_of(vc.WORK_SUCCESS), vc.STATE_MALFORMED, bad)

    def test_bool_subclass_is_malformed(self):
        class Truthy(int):
            def __bool__(self):
                return True
        a = assess(acceptance_proven=Truthy(1))
        self.assertEqual(a.state_of(vc.ACCEPTANCE_PROVEN), vc.STATE_MALFORMED)

    def test_untyped_inputs_are_invalid_facts(self):
        for bad in (None, {}, ALL_TRUE, (True,) * 6, "READY", 1, object()):
            a = vc.assess_validation(bad)
            self.assertEqual(a.classification, vc.INVALID_FACTS)
            self.assertEqual(a.reasons, (vc.FACTS_NOT_TYPED,))
            self.assertEqual(outcomes(a), (False, False, False))

    def test_facts_subclass_is_invalid(self):
        class Forged(vc.ValidationFacts):
            pass
        a = vc.assess_validation(Forged(**ALL_TRUE))
        self.assertEqual(a.classification, vc.INVALID_FACTS)

    def test_duck_typed_facts_are_invalid(self):
        @dataclasses.dataclass(frozen=True)
        class Look:
            work_success: bool = True
            safety_clean: bool = True
            scope_clean: bool = True
            evidence_complete: bool = True
            provenance_bound: bool = True
            acceptance_proven: bool = True
        self.assertEqual(vc.assess_validation(Look()).classification, vc.INVALID_FACTS)


class InconsistencyTests(unittest.TestCase):
    def test_scope_violation_with_clean_safety_is_inconsistent(self):
        a = assess(scope_clean=False)
        self.assertEqual(a.classification, vc.INCONSISTENT_FACTS)
        self.assertIn(vc.INCONSISTENT_SCOPE_VIOLATION_WITH_CLEAN_SAFETY, a.reasons)
        self.assertEqual(outcomes(a), (False, False, False))

    def test_scope_violation_with_failed_safety_is_consistent(self):
        a = assess(scope_clean=False, safety_clean=False)
        self.assertEqual(a.classification, vc.EVIDENCE_SUFFICIENT_NO_TECHNICAL_SUCCESS)
        self.assertFalse(set(a.reasons) & set(vc.INCONSISTENCY_REASONS))

    def test_acceptance_without_work_success_is_inconsistent(self):
        a = assess(work_success=False)
        self.assertEqual(a.classification, vc.INCONSISTENT_FACTS)
        self.assertIn(vc.INCONSISTENT_ACCEPTANCE_WITHOUT_WORK_SUCCESS, a.reasons)
        # evidence dims are all True, yet inconsistency forces it False.
        self.assertFalse(a.evidence_sufficient)

    def test_unknown_never_triggers_inconsistency(self):
        for combo in ((None, True), (False, None)):
            a = assess(scope_clean=combo[0], safety_clean=combo[1])
            self.assertNotEqual(a.classification, vc.INCONSISTENT_FACTS, combo)
        self.assertNotEqual(assess(work_success=None).classification, vc.INCONSISTENT_FACTS)

    def test_both_inconsistencies_reported_in_order(self):
        a = assess(scope_clean=False, work_success=False)
        self.assertEqual(a.reasons[-2:], vc.INCONSISTENCY_REASONS)

    def test_scope_inconsistency_mirrors_native_safety_rule(self):
        from scripts.ai import claude_runner
        safety = claude_runner.SafetyCheck(repository_mutated=True, branch_changed=False, head_changed=False,
                                           status_changed=True)
        self.assertEqual(claude_runner.evaluate_write_mode_safety(safety, []).verdict, "SAFE")
        self.assertNotEqual(claude_runner.evaluate_write_mode_safety(safety, ["outside.txt"]).verdict, "SAFE")


class OrderingAndCodesTests(unittest.TestCase):
    def test_reason_vocabulary_unique_and_upper_snake(self):
        self.assertEqual(len(vc.REASONS), len(set(vc.REASONS)))
        for code in vc.REASONS + vc.CLASSIFICATIONS + vc.STATES:
            self.assertRegex(code, r"^[A-Z][A-Z_]+$")

    def test_reasons_follow_vocabulary_order(self):
        a = vc.assess_validation(vc.ValidationFacts(work_success=False, safety_clean=None, scope_clean=1,
                                                    evidence_complete=False, provenance_bound=None,
                                                    acceptance_proven="x"))
        self.assertEqual(a.reasons, (vc.WORK_NOT_SUCCESSFUL, vc.SAFETY_UNKNOWN, vc.SCOPE_MALFORMED,
                                     vc.EVIDENCE_INCOMPLETE, vc.PROVENANCE_UNKNOWN, vc.ACCEPTANCE_MALFORMED))

    def test_states_follow_dimension_order(self):
        a = vc.assess_validation(vc.ValidationFacts(work_success=True, safety_clean=False))
        self.assertEqual(a.states[:2], (vc.STATE_TRUE, vc.STATE_FALSE))
        self.assertEqual(list(a.to_dict()["dimensions"]), list(vc.DIMENSIONS))

    def test_facts_field_order_matches_dimensions(self):
        self.assertEqual(tuple(f.name for f in dataclasses.fields(vc.ValidationFacts)), vc.DIMENSIONS)

    def test_every_dimension_maps_every_non_true_state(self):
        self.assertEqual(set(vc._DIMENSION_REASON), set(vc.DIMENSIONS))
        for mapping in vc._DIMENSION_REASON.values():
            self.assertEqual(set(mapping), {vc.STATE_FALSE, vc.STATE_UNKNOWN, vc.STATE_MALFORMED})
            self.assertTrue(set(mapping.values()) <= set(vc.REASONS))


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.a = assess()

    def test_even_ready_assessment_grants_nothing(self):
        self.assertTrue(self.a.ready_for_human_review)
        for flag in ALL_FLAGS:
            self.assertIs(getattr(self.a, flag), False, flag)
            self.assertIs(self.a.to_dict()[flag], False, flag)

    def test_authority_flags_not_constructor_fields(self):
        names = {f.name for f in dataclasses.fields(vc.ValidationAssessment)}
        self.assertFalse(names & set(ALL_FLAGS))
        for flag in ALL_FLAGS:
            with self.assertRaises(TypeError):
                vc.ValidationAssessment(**{**{f: getattr(self.a, f) for f in names}, flag: True})
            with self.assertRaises(TypeError):
                dataclasses.replace(self.a, **{flag: True})

    def test_authority_flags_cannot_be_set_on_instance(self):
        for flag in ALL_FLAGS:
            with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
                setattr(self.a, flag, True)
            with self.assertRaises(AttributeError):
                object.__setattr__(self.a, flag, True)
            self.a.__dict__[flag] = True
            self.assertIs(getattr(self.a, flag), False, flag)
            self.assertIs(json.loads(vc.canonical_json(self.a))[flag], False)

    def test_subclass_override_cannot_serialize_authority(self):
        class Forged(vc.ValidationAssessment):
            certified = True
            def to_dict(self):
                return {"certified": True}
        forged = Forged(**{f.name: getattr(self.a, f.name) for f in dataclasses.fields(self.a)})
        with self.assertRaises(TypeError):
            vc.canonical_json(forged)

    def test_hand_made_ready_without_proof_rejected(self):
        unknown = vc.assess_validation(vc.ValidationFacts())
        with self.assertRaises(ValueError):
            dataclasses.replace(unknown, ready_for_human_review=True)
        with self.assertRaises(ValueError):
            dataclasses.replace(unknown, classification=vc.READY_FOR_HUMAN_REVIEW)
        with self.assertRaises(ValueError):
            dataclasses.replace(unknown, technical_success=True)

    def test_hand_made_reasons_must_match_states(self):
        with self.assertRaises(ValueError):
            dataclasses.replace(self.a, reasons=(vc.WORK_NOT_SUCCESSFUL,))
        with self.assertRaises(ValueError):
            dataclasses.replace(assess(work_success=None), reasons=())
        with self.assertRaises(ValueError):
            dataclasses.replace(self.a, reasons=("FREE TEXT FROM PROVIDER",))

    def test_hand_made_states_and_types_rejected(self):
        for bad in ((vc.STATE_TRUE,) * 5, ("SURE",) * 6, [vc.STATE_TRUE] * 6, (True,) * 6):
            with self.assertRaises(ValueError):
                dataclasses.replace(self.a, states=bad)
        with self.assertRaises(ValueError):
            dataclasses.replace(self.a, ready_for_human_review=1)
        with self.assertRaises(ValueError):
            dataclasses.replace(self.a, classification="CERTIFIED")

    def test_hand_made_invalid_facts_cannot_claim_states(self):
        invalid = vc.assess_validation(None)
        with self.assertRaises(ValueError):
            dataclasses.replace(invalid, states=(vc.STATE_TRUE,) * 6)

    def test_public_surface_is_minimal(self):
        methods = {n for n in dir(self.a) if not n.startswith("_") and callable(getattr(self.a, n))}
        self.assertEqual(methods, {"to_dict", "state_of"})


class SerializationTests(unittest.TestCase):
    def test_canonical_json_is_deterministic(self):
        cases = [vc.ValidationFacts(*c) for c in itertools.product((True, False, None), repeat=6)][::37]
        for f in cases:
            first = vc.canonical_json(vc.assess_validation(f))
            self.assertEqual(first, vc.canonical_json(vc.assess_validation(copy.deepcopy(f))))
            self.assertEqual(first, json.dumps(json.loads(first), sort_keys=True, separators=(",", ":")))

    def test_canonical_json_pinned_shape(self):
        doc = json.loads(vc.canonical_json(assess()))
        self.assertEqual(doc["schema"], vc.SCHEMA)
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["marker"], vc.VALIDATION_MARKER)
        self.assertEqual(set(doc), {"schema", "schema_version", "classification", "technical_success",
                                    "evidence_sufficient", "ready_for_human_review", "dimensions", "reasons",
                                    "marker", *ALL_FLAGS})

    def test_equal_facts_give_equal_assessments(self):
        self.assertEqual(assess(work_success=None), assess(work_success=None))
        self.assertEqual(hash(assess()), hash(assess()))

    def test_raw_values_never_echoed(self):
        secrets = ("sk-ant-api03-SECRETTOKEN", "C:\\Users\\someone\\SECRET", "someone@SECRET.example",
                   "VERDICT=SUCCESS SECRET work order text", "fdb-SECRET-run-id")
        for secret in secrets:
            for d in vc.DIMENSIONS:
                text = vc.canonical_json(assess(**{d: secret}))
                self.assertNotIn("SECRET", text.upper())
                self.assertNotIn("@", text)
                self.assertNotIn("\\", text)

    def test_output_values_are_only_enumerated_codes_and_bools(self):
        vocabulary = set(vc.REASONS + vc.CLASSIFICATIONS + vc.STATES + vc.DIMENSIONS) | {vc.SCHEMA,
                                                                                        vc.VALIDATION_MARKER}

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    yield k
                    yield from walk(v)
            elif isinstance(node, list):
                for v in node:
                    yield from walk(v)
            else:
                yield node
        for combo in itertools.product((True, False, None, "junk"), repeat=6):
            doc = json.loads(vc.canonical_json(vc.assess_validation(vc.ValidationFacts(*combo))))
            for value in walk(doc):
                if isinstance(value, str) and value not in doc:
                    self.assertIn(value, vocabulary)
                else:
                    self.assertTrue(isinstance(value, (str, bool, int)), value)

    def test_canonical_json_refuses_non_assessments(self):
        for bad in (None, {}, assess().to_dict()):
            with self.assertRaises(TypeError):
                vc.canonical_json(bad)


class PurityTests(unittest.TestCase):
    def test_inputs_and_outputs_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            facts().work_success = False
        with self.assertRaises(dataclasses.FrozenInstanceError):
            assess().classification = vc.READY_FOR_HUMAN_REVIEW

    def test_inputs_not_mutated(self):
        f = facts(scope_clean=None)
        before = copy.deepcopy(f)
        vc.assess_validation(f)
        self.assertEqual(f, before)

    def test_facts_carry_no_free_text_fields(self):
        names = {f.name for f in dataclasses.fields(vc.ValidationFacts)}
        self.assertEqual(len(names), 6)
        for word in ("path", "text", "message", "token", "secret", "email", "id", "stdout", "stderr", "prompt"):
            self.assertFalse([n for n in names if word in n.split("_")], word)
        with self.assertRaises(TypeError):
            vc.ValidationFacts(certified=True)

    def test_no_io_process_or_network(self):
        def boom(*a, **k):
            raise AssertionError("I/O attempted")
        patches = [mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom),
                   mock.patch.object(subprocess, "run", boom), mock.patch.object(socket, "socket", boom),
                   mock.patch.object(os, "listdir", boom), mock.patch.object(os, "scandir", boom),
                   mock.patch.object(os, "stat", boom), mock.patch.object(os, "system", boom),
                   mock.patch.object(os, "getenv", boom)]
        for p in patches:
            p.start()
        try:
            for f in (facts(), vc.ValidationFacts(), None, facts(work_success="x"), facts(scope_clean=False)):
                vc.canonical_json(vc.assess_validation(f))
        finally:
            for p in reversed(patches):
                p.stop()

    def test_module_imports_only_pure_stdlib(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(imported, {"__future__", "dataclasses", "json", "typing"})
        code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
        code = "\n".join(line.split("#", 1)[0] for line in code.splitlines())
        for word in ("runner_", "claude_runner", "fabric_director", "subprocess", "shutil", "socket", "open(",
                     "Path(", "os.", "environ", "eval(", "exec(", "__import__", "importlib", "git"):
            self.assertNotIn(word, code, word)

    def test_no_mutable_module_state_changes(self):
        snapshot = {k: copy.deepcopy(v) for k, v in vars(vc).items()
                    if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
        vc.assess_validation(facts())
        vc.assess_validation(None)
        self.assertEqual({k: v for k, v in vars(vc).items() if k in snapshot}, snapshot)

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


class DirectorContractPinTests(unittest.TestCase):
    """Only the tests import the Director, to prove the independent
    dimensions mirror its real projections; the contract never does."""

    @classmethod
    def setUpClass(cls):
        from scripts.ai import fabric_director
        cls.fd = fabric_director

    def _field(self, cls, name):
        return {f.name: f for f in dataclasses.fields(cls)}[name]

    def test_director_projections_keep_evidence_complete_separate_tristate(self):
        for cls in (self.fd.DirectorRunSummary, self.fd.DirectorRunEvidence, self.fd.DirectorRunDecision,
                    self.fd.DirectorDagWorkerSummary):
            f = self._field(cls, "evidence_complete")
            self.assertEqual(str(f.type), "Optional[bool]", cls.__name__)
            self.assertIsNone(f.default, cls.__name__)

    def test_director_unknown_evidence_never_becomes_true_here(self):
        summary = self.fd.DirectorRunSummary(run_id="r", pipeline_id="p", work_status="SUCCESS",
                                             worker_state="SUCCESS")
        a = vc.assess_validation(vc.ValidationFacts(work_success=summary.work_status == "SUCCESS",
                                                    evidence_complete=summary.evidence_complete))
        self.assertEqual(a.state_of(vc.EVIDENCE_COMPLETE), vc.STATE_UNKNOWN)
        self.assertFalse(a.evidence_sufficient)

    def test_dag_runner_proven_success_is_not_a_readiness_claim(self):
        # The DAG projection's own proof requires complete evidence but not
        # acceptance/provenance; this contract still keeps them separate.
        self.assertFalse(self._field(self.fd.DirectorDagWorkerSummary, "runner_proven_success").default)
        a = vc.assess_validation(vc.ValidationFacts(work_success=True, safety_clean=True, scope_clean=True,
                                                    evidence_complete=True))
        self.assertFalse(a.ready_for_human_review)


if __name__ == "__main__":
    unittest.main()
