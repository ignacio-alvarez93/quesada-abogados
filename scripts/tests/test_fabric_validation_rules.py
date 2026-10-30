"""FCP-8B-02: evidence sufficiency rules over the FCP-8A-01 assessment and
the FCP-8A-02 / FCP-8B-01 observations. Offline and synthetic - observations
are built with the A-02/B-01 test fixtures (fake Director services); no
Runner, Git, process, network or file is touched."""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import itertools
import json
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_director as fd
from scripts.ai import fabric_validation_contract as vc
from scripts.ai import fabric_validation_dag as vd
from scripts.ai import fabric_validation_rules as vr
from scripts.ai import fabric_validation_single as vs
from scripts.tests import test_fabric_validation_dag as td
from scripts.tests import test_fabric_validation_single as ts

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_validation_rules.py"

ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
             "auto_retry_allowed", "resume_allowed", "push_allowed", "fallback_allowed", "provider_switch_allowed")
TRI = (True, False, None)
ALL_TRUE = dict.fromkeys(vc.DIMENSIONS, True)
BLOCKING_DIMENSIONS = (vc.PROVENANCE_BOUND, vc.SCOPE_CLEAN, vc.ACCEPTANCE_PROVEN, vc.EVIDENCE_COMPLETE)


def facts(**values) -> vc.ValidationFacts:
    return vc.ValidationFacts(**{**ALL_TRUE, **values})


def classify_facts(**values) -> vr.EvidenceClassification:
    return vr.classify_evidence(vc.assess_validation(facts(**values)))


def every_combination():
    for combo in itertools.product(TRI, repeat=len(vc.DIMENSIONS)):
        yield dict(zip(vc.DIMENSIONS, combo))


RANK = {vr.VALIDATION_COMPLETE: 2, vr.UNPROVEN: 1, vr.HUMAN_REVIEW_REQUIRED: 0}


# ---------------------------------------------------------------------------
class TruthTableTests(unittest.TestCase):
    def test_validation_complete_iff_every_dimension_true(self):
        for combo in every_combination():
            with self.subTest(**combo):
                c = classify_facts(**combo)
                self.assertEqual(c.validation_complete, all(v is True for v in combo.values()))
                self.assertEqual(c.verdict == vr.VALIDATION_COMPLETE, c.validation_complete)

    def test_any_negative_requires_human_review_and_is_preserved(self):
        for combo in every_combination():
            if False not in combo.values():
                continue
            with self.subTest(**combo):
                c = classify_facts(**combo)
                self.assertTrue(c.human_review_required)
                self.assertEqual(c.verdict, vr.HUMAN_REVIEW_REQUIRED)
                self.assertFalse(c.validation_complete)
                self.assertTrue(c.negative_codes)

    def test_any_unknown_is_unproven(self):
        for combo in every_combination():
            if None not in combo.values():
                continue
            with self.subTest(**combo):
                c = classify_facts(**combo)
                self.assertTrue(c.unproven)
                self.assertFalse(c.validation_complete)
                self.assertTrue(c.unknown_codes)

    def test_unknown_in_provenance_scope_acceptance_or_evidence_blocks_sufficiency(self):
        expected = {vc.PROVENANCE_BOUND: vc.PROVENANCE_UNKNOWN, vc.SCOPE_CLEAN: vc.SCOPE_UNKNOWN,
                    vc.ACCEPTANCE_PROVEN: vc.ACCEPTANCE_UNKNOWN, vc.EVIDENCE_COMPLETE: vc.EVIDENCE_UNKNOWN}
        for dimension in BLOCKING_DIMENSIONS:
            with self.subTest(dimension=dimension):
                c = classify_facts(**{dimension: None})
                self.assertEqual(c.verdict, vr.UNPROVEN)
                self.assertEqual(c.codes, (expected[dimension],))
                self.assertNotIn(vr.VALIDATION_COMPLETE, c.outcomes)

    def test_work_success_does_not_imply_evidence_complete(self):
        for missing in (None, False):
            with self.subTest(evidence_complete=missing):
                c = classify_facts(evidence_complete=missing)
                self.assertTrue(c.work_success)
                self.assertFalse(c.evidence_complete)
                self.assertFalse(c.validation_complete)

    def test_evidence_complete_does_not_imply_work_success(self):
        for missing in (None, False):
            with self.subTest(work_success=missing):
                c = classify_facts(work_success=missing, acceptance_proven=None)
                self.assertTrue(c.evidence_complete)
                self.assertFalse(c.work_success)
                self.assertFalse(c.validation_complete)

    def test_outcome_flags_read_only_their_own_dimension(self):
        for combo in every_combination():
            with self.subTest(**combo):
                c = classify_facts(**combo)
                self.assertEqual(c.work_success, combo[vc.WORK_SUCCESS] is True)
                self.assertEqual(c.evidence_complete, combo[vc.EVIDENCE_COMPLETE] is True)

    def test_negative_preserved_alongside_unknowns(self):
        c = classify_facts(work_success=None, safety_clean=None, provenance_bound=False, acceptance_proven=None)
        self.assertEqual(c.outcomes, (vr.EVIDENCE_COMPLETE, vr.HUMAN_REVIEW_REQUIRED, vr.UNPROVEN))
        self.assertEqual(c.verdict, vr.HUMAN_REVIEW_REQUIRED)
        self.assertEqual(c.negative_codes, (vc.PROVENANCE_NOT_BOUND,))
        self.assertEqual(c.unknown_codes, (vc.WORK_SUCCESS_UNKNOWN, vc.SAFETY_UNKNOWN, vc.ACCEPTANCE_UNKNOWN))

    def test_malformed_facts_are_never_true(self):
        for bad in (1, 0, "True", 1.0, [], object()):
            for dimension in vc.DIMENSIONS:
                with self.subTest(bad=repr(bad), dimension=dimension):
                    c = classify_facts(**{dimension: bad})
                    self.assertEqual(c.verdict, vr.UNPROVEN)
                    self.assertEqual(c.unit_states[0][vc.DIMENSIONS.index(dimension)], vc.STATE_MALFORMED)
                    self.assertFalse(c.validation_complete)

    def test_contract_inconsistencies_require_human_review(self):
        cases = ((dict(scope_clean=False), vc.INCONSISTENT_SCOPE_VIOLATION_WITH_CLEAN_SAFETY),
                 (dict(work_success=False), vc.INCONSISTENT_ACCEPTANCE_WITHOUT_WORK_SUCCESS))
        for values, reason in cases:
            with self.subTest(reason=reason):
                c = classify_facts(**values)
                self.assertIn(reason, c.negative_codes)
                self.assertEqual(c.verdict, vr.HUMAN_REVIEW_REQUIRED)

    def test_invalid_facts_assessment_is_unproven(self):
        c = vr.classify_evidence(vc.assess_validation({"work_success": True}))
        self.assertEqual((c.source, c.verdict, c.codes), (vr.SOURCE_ASSESSMENT, vr.UNPROVEN, (vc.FACTS_NOT_TYPED,)))
        self.assertEqual(c.outcomes, (vr.UNPROVEN,))

    def test_validation_complete_agrees_with_contract_ready_for_human_review(self):
        for combo in every_combination():
            with self.subTest(**combo):
                assessment = vc.assess_validation(facts(**combo))
                self.assertEqual(vr.classify_evidence(assessment).validation_complete,
                                 assessment.ready_for_human_review)

    def test_outcome_combinations_are_coherent(self):
        for combo in every_combination():
            with self.subTest(**combo):
                c = classify_facts(**combo)
                self.assertEqual(c.validation_complete, not c.human_review_required and not c.unproven)
                if c.validation_complete:
                    self.assertEqual(c.outcomes, (vr.WORK_SUCCESS, vr.EVIDENCE_COMPLETE, vr.VALIDATION_COMPLETE))


# ---------------------------------------------------------------------------
class MonotonicityTests(unittest.TestCase):
    def test_removing_true_evidence_never_improves_any_outcome(self):
        for combo in every_combination():
            before = classify_facts(**combo)
            for dimension, value in combo.items():
                if value is not True:
                    continue
                with self.subTest(dimension=dimension, **combo):
                    after = classify_facts(**{**combo, dimension: None})
                    self.assertLessEqual(RANK[after.verdict], RANK[before.verdict])
                    for name in ("work_success", "evidence_complete", "validation_complete"):
                        self.assertLessEqual(getattr(after, name), getattr(before, name))
                    self.assertTrue(after.unproven)

    def test_removing_a_negative_never_yields_validation_complete(self):
        for combo in every_combination():
            for dimension, value in combo.items():
                if value is not False:
                    continue
                with self.subTest(dimension=dimension, **combo):
                    after = classify_facts(**{**combo, dimension: None})
                    self.assertFalse(after.validation_complete)
                    self.assertTrue(after.unproven)

    def test_adding_a_negative_always_requires_human_review(self):
        for combo in every_combination():
            for dimension in vc.DIMENSIONS:
                with self.subTest(dimension=dimension, **combo):
                    after = classify_facts(**{**combo, dimension: False})
                    self.assertTrue(after.human_review_required)
                    self.assertFalse(after.validation_complete)

    def test_dag_missing_worker_evidence_never_improves(self):
        before = vr.classify_evidence(td.obs(td.dag()))
        for index in range(3):
            for override in ({"evidence_complete": None}, {"worker_record": "MISSING"}):
                with self.subTest(index=index, override=override):
                    after = vr.classify_evidence(td.obs(td.dag(td.chain(3, {index: override}))))
                    self.assertLessEqual(RANK[after.verdict], RANK[before.verdict])
                    self.assertLessEqual(after.evidence_complete, before.evidence_complete)
                    self.assertLessEqual(after.work_success, before.work_success)
                    self.assertTrue(after.unproven)


# ---------------------------------------------------------------------------
class SingleRunTests(unittest.TestCase):
    def test_fully_consistent_single_run_is_validation_complete(self):
        c = vr.classify_evidence(ts.observe_consistent())
        self.assertEqual((c.source, c.verdict, c.unit_count, c.codes),
                         (vr.SOURCE_SINGLE_RUN, vr.VALIDATION_COMPLETE, 1, ()))

    def test_single_run_success_with_incomplete_evidence(self):
        c = vr.classify_evidence(ts.observe_consistent(shared={"evidence_complete": False}))
        self.assertTrue(c.work_success)
        self.assertFalse(c.evidence_complete)
        self.assertIn(vc.EVIDENCE_INCOMPLETE, c.negative_codes)
        self.assertEqual(c.verdict, vr.HUMAN_REVIEW_REQUIRED)

    def test_single_run_provider_only_success_is_unproven(self):
        o = ts.observe_consistent(shared={"work_status_source": fd.claude_runner.WORK_STATUS_SOURCE_PROVIDER})
        c = vr.classify_evidence(o)
        self.assertFalse(c.work_success)
        self.assertFalse(c.validation_complete)
        self.assertIn(vc.WORK_SUCCESS_UNKNOWN, c.unknown_codes)

    def test_single_run_read_failure_is_unobservable(self):
        o, _ = ts.observe(*ts.consistent(), raises={"evidence": RuntimeError("boom")})
        c = vr.classify_evidence(o)
        self.assertEqual(c.verdict, vr.UNPROVEN)
        self.assertIn(vr.OBSERVATION_UNOBSERVABLE, c.codes)
        self.assertFalse(c.work_success or c.evidence_complete)

    def test_single_run_identity_mismatch_preserves_provenance_negative(self):
        s, e, d = ts.consistent()
        o, _ = ts.observe(s, dataclasses.replace(e, worker_id="w-other"), d)
        c = vr.classify_evidence(o)
        self.assertIn(vc.PROVENANCE_NOT_BOUND, c.negative_codes)
        self.assertIn(vr.OBSERVATION_CONTRADICTION, c.negative_codes)
        self.assertEqual(c.verdict, vr.HUMAN_REVIEW_REQUIRED)
        self.assertTrue(c.unproven)

    def test_single_run_decision_contradiction_requires_review(self):
        s, e, d = ts.consistent()
        o, _ = ts.observe(s, e, dataclasses.replace(d, decision_code="FAILED_REVIEW_REQUIRED"))
        self.assertIn("DECISION_CONTRADICTS_SOURCES", o.observation_codes)
        c = vr.classify_evidence(o)
        self.assertIn(vr.OBSERVATION_CONTRADICTION, c.negative_codes)
        self.assertFalse(c.work_success)

    def test_provider_work_status_divergence_is_not_a_negative(self):
        o = ts.observe_consistent(shared={"provider_work_status": "FAILED"})
        self.assertIn("PROVIDER_WORK_STATUS_DIVERGES", o.observation_codes)
        c = vr.classify_evidence(o)
        self.assertNotIn(vr.OBSERVATION_CONTRADICTION, c.codes)
        self.assertEqual((c.verdict, c.codes), (vr.VALIDATION_COMPLETE, ()))

    def test_single_code_rules_cover_only_real_observation_codes(self):
        self.assertLessEqual(set(vr._SINGLE_CODE_RULES), set(vs.OBSERVATION_CODES))
        self.assertLessEqual(set(vr._SINGLE_CODE_RULES.values()), set(vr.RULE_CODES))

    def test_tampered_single_observation_is_inconsistent(self):
        o = ts.observe_consistent(shared={"evidence_complete": False})
        object.__setattr__(o, "facts", facts())
        c = vr.classify_evidence(o)
        self.assertEqual((c.verdict, c.unit_count), (vr.UNPROVEN, 0))
        self.assertEqual(c.codes, (vr.INPUT_INCONSISTENT, vr.NO_UNITS))


# ---------------------------------------------------------------------------
class DagRunTests(unittest.TestCase):
    def test_all_workers_proven_dag_is_never_validation_complete(self):
        o = td.obs(td.dag(n=5))
        self.assertEqual(o.classification, vd.ALL_WORKERS_PROVEN)
        c = vr.classify_evidence(o)
        self.assertEqual(c.outcomes, (vr.WORK_SUCCESS, vr.EVIDENCE_COMPLETE, vr.UNPROVEN))
        self.assertEqual(c.codes, (vc.SAFETY_UNKNOWN, vc.ACCEPTANCE_UNKNOWN))
        self.assertEqual(c.unit_count, 5)

    def test_aggregate_success_with_one_unproven_worker(self):
        workers = td.chain(3, {1: {"evidence_complete": None}})
        o = td.obs(td.dag(workers, aggregate_status="SUCCESS"))
        self.assertIn("AGGREGATE_SUCCESS_WITH_UNPROVEN_WORKER", o.observation_codes)
        c = vr.classify_evidence(o)
        self.assertFalse(c.evidence_complete)
        self.assertIn(vr.DAG_AGGREGATE_INCONSISTENT, c.negative_codes)
        self.assertIn(vc.EVIDENCE_UNKNOWN, c.unknown_codes)
        self.assertEqual(c.verdict, vr.HUMAN_REVIEW_REQUIRED)

    def test_failed_worker_preserves_negative(self):
        workers = td.chain(3, {2: {"worker_state": "FAILED", "work_status": "FAILED"}})
        c = vr.classify_evidence(td.obs(td.dag(workers, pipeline_status="FAILED")))
        self.assertFalse(c.work_success)
        self.assertIn(vc.WORK_NOT_SUCCESSFUL, c.negative_codes)
        self.assertIn(vr.DAG_NOT_SUCCESSFUL, c.negative_codes)
        self.assertEqual(c.verdict, vr.HUMAN_REVIEW_REQUIRED)

    def test_failed_pipeline_denies_work_success_even_with_successful_workers(self):
        o = td.obs(td.dag(pipeline_status="FAILED"))
        self.assertEqual(o.classification, vd.NOT_SUCCESSFUL)
        c = vr.classify_evidence(o)
        self.assertFalse(c.work_success)
        self.assertTrue(c.evidence_complete)
        self.assertEqual(c.verdict, vr.HUMAN_REVIEW_REQUIRED)

    def test_not_terminal_pipeline_is_unproven_without_work_success(self):
        o = td.obs(td.dag(pipeline_status="RUNNING"))
        self.assertEqual(o.classification, vd.NOT_TERMINAL)
        c = vr.classify_evidence(o)
        self.assertIn(vr.DAG_NOT_TERMINAL, c.unknown_codes)
        self.assertFalse(c.work_success)
        self.assertEqual(c.verdict, vr.UNPROVEN)

    def test_unobservable_dag_has_no_units(self):
        o = td.obs(td.dag(), raises=RuntimeError("boom"))
        c = vr.classify_evidence(o)
        self.assertEqual(c.codes, (vr.NO_UNITS, vr.DAG_UNOBSERVABLE))
        self.assertEqual((c.unit_count, c.outcomes), (0, (vr.UNPROVEN,)))

    def test_stale_provenance_is_a_negative(self):
        o = td.obs(td.dag(), expected_manifest_sha256="c" * 64)
        self.assertEqual(o.classification, vd.INVALID_PROJECTION)
        c = vr.classify_evidence(o)
        self.assertEqual(c.negative_codes, (vr.DAG_PROVENANCE_MISMATCH,))
        self.assertIn(vr.DAG_INVALID_PROJECTION, c.unknown_codes)
        self.assertEqual(c.verdict, vr.HUMAN_REVIEW_REQUIRED)

    def test_foreign_worker_record_is_a_provenance_negative(self):
        c = vr.classify_evidence(td.obs(td.dag(td.chain(3, {0: {"worker_record": "MISMATCH"}}))))
        self.assertIn(vc.PROVENANCE_NOT_BOUND, c.negative_codes)
        self.assertEqual(c.unit_states[0][vc.DIMENSIONS.index(vc.PROVENANCE_BOUND)], vc.STATE_FALSE)

    def test_tampered_dag_worker_assessment_is_inconsistent(self):
        o = td.obs(td.dag())
        object.__setattr__(o.workers[1], "facts", facts(evidence_complete=False))
        c = vr.classify_evidence(o)
        self.assertEqual(c.codes, (vr.INPUT_INCONSISTENT, vr.NO_UNITS))
        self.assertEqual(c.verdict, vr.UNPROVEN)

    def test_dag_rules_cover_only_real_classifications_and_codes(self):
        self.assertEqual(set(vr._DAG_CLASSIFICATION_RULES) | {vd.ALL_WORKERS_PROVEN}, set(vd.DAG_CLASSIFICATIONS))
        self.assertLessEqual(set(vr._DAG_CODE_RULES), set(vd.DAG_CODES))


# ---------------------------------------------------------------------------
class DegenerateInputTests(unittest.TestCase):
    def test_untyped_inputs_are_invalid_and_never_raise(self):
        subclass = type("Sub", (vc.ValidationAssessment,), {})
        sub = subclass(**{f.name: getattr(vc.assess_validation(facts()), f.name)
                          for f in dataclasses.fields(vc.ValidationAssessment)})
        for bad in (None, 0, "VALIDATION_COMPLETE", {}, [], facts(), sub, vc.assess_validation,
                    {"verdict": "VALIDATION_COMPLETE"}):
            with self.subTest(bad=type(bad).__name__):
                c = vr.classify_evidence(bad)
                self.assertEqual((c.source, c.verdict), (vr.SOURCE_INVALID, vr.UNPROVEN))
                self.assertEqual(c.codes, (vr.INPUT_NOT_TYPED, vr.NO_UNITS))
                self.assertEqual(c.outcomes, (vr.UNPROVEN,))

    def test_tampered_assessment_is_inconsistent(self):
        a = vc.assess_validation(facts(evidence_complete=None))
        object.__setattr__(a, "ready_for_human_review", True)
        object.__setattr__(a, "evidence_sufficient", True)
        c = vr.classify_evidence(a)
        self.assertEqual(c.codes, (vr.INPUT_INCONSISTENT, vr.NO_UNITS))
        self.assertFalse(c.validation_complete)

    def test_hand_made_classification_cannot_overclaim(self):
        unknown_unit = (vc.STATE_UNKNOWN,) * len(vc.DIMENSIONS)
        false_unit = (vc.STATE_FALSE,) + (vc.STATE_TRUE,) * (len(vc.DIMENSIONS) - 1)
        base = dict(source=vr.SOURCE_ASSESSMENT, verdict=vr.VALIDATION_COMPLETE, work_success=True,
                    evidence_complete=True, validation_complete=True, human_review_required=False, unproven=False)
        for units, codes in (((unknown_unit,), ()), ((false_unit,), ()), ((), ()),
                             ((unknown_unit,), (vc.WORK_SUCCESS_UNKNOWN,))):
            with self.subTest(units=units, codes=codes), self.assertRaises(ValueError):
                vr.EvidenceClassification(unit_states=units, codes=codes, **base)
        with self.assertRaises(ValueError):
            vr.EvidenceClassification(unit_states=(), codes=("PUSH_NOW",), **base)

    def test_code_vocabulary_partitions(self):
        self.assertEqual(set(vr.NEGATIVE_CODES) | set(vr.UNKNOWN_CODES), set(vr.CODES))
        self.assertFalse(set(vr.NEGATIVE_CODES) & set(vr.UNKNOWN_CODES))
        self.assertEqual(len(set(vr.CODES)), len(vr.CODES))
        for dimension in vc.DIMENSIONS:
            with self.subTest(dimension=dimension):
                negative = vc.assess_validation(vc.ValidationFacts(**{dimension: False})).reasons
                self.assertTrue(set(negative) & set(vr.NEGATIVE_REASONS))
                unknown_only = vc.assess_validation(facts(**{dimension: None})).reasons
                self.assertLessEqual(set(unknown_only), set(vr.UNKNOWN_REASONS))


# ---------------------------------------------------------------------------
class DeterminismTests(unittest.TestCase):
    def test_equal_inputs_give_equal_results(self):
        inputs = (vc.assess_validation(facts(scope_clean=None)), ts.observe_consistent(), td.obs(td.dag(n=4)))
        for value in inputs:
            with self.subTest(source=type(value).__name__):
                first = vr.classify_evidence(value)
                self.assertEqual(first, vr.classify_evidence(copy.deepcopy(value)))
                self.assertEqual(vr.canonical_json(first), vr.canonical_json(vr.classify_evidence(value)))

    def test_independently_built_equal_inputs_classify_identically(self):
        a = vr.classify_evidence(td.obs(td.dag(td.chain(3, {1: {"evidence_complete": False}}))))
        b = vr.classify_evidence(td.obs(td.dag(td.chain(3, {1: {"evidence_complete": False}}))))
        self.assertEqual(vr.canonical_json(a), vr.canonical_json(b))

    def test_inputs_are_not_mutated(self):
        for value in (vc.assess_validation(facts()), ts.observe_consistent(), td.obs(td.dag())):
            with self.subTest(source=type(value).__name__):
                before = copy.deepcopy(value)
                vr.classify_evidence(value)
                self.assertEqual(value, before)

    def test_canonical_json_is_stable_and_typed(self):
        c = classify_facts(evidence_complete=None)
        text = vr.canonical_json(c)
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True, separators=(",", ":")))
        for bad in (None, c.to_dict(), text):
            with self.subTest(bad=type(bad).__name__), self.assertRaises(TypeError):
                vr.canonical_json(bad)

    def test_serialization_contains_only_enumerated_values(self):
        o = ts.observe_consistent(shared={"evidence_complete": None})
        text = vr.canonical_json(vr.classify_evidence(o))
        for secret in (ts.SECRET_DIR, ts.EMAIL, ts.RUN, ts.WORKER, "provider prose", "pytest"):
            self.assertNotIn(secret, text)
        data = json.loads(text)
        vocabulary = set(vr.CODES) | set(vc.STATES)
        self.assertLessEqual(set(data["codes"]) | {s for u in data["units"] for s in u.values()}, vocabulary)


# ---------------------------------------------------------------------------
class AuthorityTests(unittest.TestCase):
    def test_every_authority_flag_is_false_for_every_verdict(self):
        cases = (classify_facts(), classify_facts(evidence_complete=None), classify_facts(scope_clean=False),
                 vr.classify_evidence(None), vr.classify_evidence(td.obs(td.dag())))
        self.assertEqual({c.verdict for c in cases}, set(vr.VERDICTS))
        for c in cases:
            with self.subTest(verdict=c.verdict):
                data = c.to_dict()
                for flag in ALL_FLAGS:
                    self.assertIs(getattr(c, flag), False)
                    self.assertIs(data[flag], False)
                self.assertEqual(data["marker"], vr.RULES_MARKER)

    def test_authority_flags_cannot_be_injected(self):
        c = classify_facts()
        for flag in ALL_FLAGS:
            with self.subTest(flag=flag):
                with self.assertRaises(TypeError):
                    vr.EvidenceClassification(**{**{f.name: getattr(c, f.name)
                                                    for f in dataclasses.fields(c)}, flag: True})
                with self.assertRaises(TypeError):
                    dataclasses.replace(c, **{flag: True})
                with self.assertRaises(AttributeError):
                    setattr(c, flag, True)

    def test_no_next_action_or_executive_decision_is_produced(self):
        data = classify_facts().to_dict()
        action_words = ("action", "next", "retry", "resume", "merge", "push", "promot", "fallback", "switch",
                        "execut", "dispatch", "approve")
        for key in data:
            if key in ALL_FLAGS:
                continue
            with self.subTest(key=key):
                self.assertFalse(any(w in key.lower() for w in action_words))
        self.assertFalse(any(any(w in c.lower() for w in action_words) for c in vr.CODES + vr.OUTCOMES))

    def test_no_io_process_or_network_during_classification(self):
        inputs = (vc.assess_validation(facts()), ts.observe_consistent(), td.obs(td.dag(n=9)))
        boom = mock.Mock(side_effect=AssertionError("io"))
        with mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(subprocess, "run", boom), mock.patch.object(socket, "socket", boom), \
                mock.patch.object(Path, "read_text", boom), mock.patch.object(Path, "exists", boom), \
                mock.patch.object(vc, "assess_validation", wraps=vc.assess_validation):
            results = [vr.classify_evidence(v) for v in inputs]
        boom.assert_not_called()
        self.assertEqual(results[0].verdict, vr.VALIDATION_COMPLETE)

    def test_module_source_imports_only_fcp8_contracts(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(f"{node.module}.{a.name}" if node.module else a.name for a in node.names)
                imported.add(node.module or "")
        allowed = {"__future__", "__future__.annotations", "json", "dataclasses", "dataclasses.dataclass",
                   "dataclasses.fields", "scripts.ai", "scripts.ai.fabric_validation_contract",
                   "scripts.ai.fabric_validation_dag", "scripts.ai.fabric_validation_single",
                   "fabric_validation_contract", "fabric_validation_dag", "fabric_validation_single"}
        self.assertEqual(imported - allowed, set())
        called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for name in td.FORBIDDEN_METHODS + ("observe_single_run", "observe_dag_run", "result_blueprint",
                                            "PipelineRunner", "open", "Popen", "system", "getenv", "read_text",
                                            "write_text", "_classify_decision"):
            self.assertNotIn(name, called)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"fd", "os", "subprocess", "socket", "DirectorRunDecision"})

    def test_prior_stage_outputs_are_unchanged_by_classification(self):
        o = td.obs(td.dag())
        single = ts.observe_consistent()
        before = (vd.canonical_json(o), vs.canonical_json(single))
        vr.classify_evidence(o)
        vr.classify_evidence(single)
        self.assertEqual((vd.canonical_json(o), vs.canonical_json(single)), before)
        self.assertEqual(o.classification, vd.ALL_WORKERS_PROVEN)
        self.assertTrue(single.assessment.ready_for_human_review)


if __name__ == "__main__":
    unittest.main()
