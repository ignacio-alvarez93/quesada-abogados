"""FCP-8B-01: multi-worker (DAG) validation evidence adapter over the
Director's `result_blueprint` projection. Offline, synthetic fake service
only - no Runner, Git, process, network or file is touched. Native-consistent
projections are built with the Director's own projection helpers."""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import json
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_director as fd
from scripts.ai import fabric_validation_contract as vc
from scripts.ai import fabric_validation_dag as vd
from scripts.ai import fabric_validation_single as vs

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_validation_dag.py"

RUN = "fdb-20261030t000000000000-abcdef12"
BLUEPRINT = "bp-private-blueprint"
MANIFEST = "a" * 64
PLAN = "b" * 64
SECRET_DIR = "C:/Users/someone/private/evidence/attempt-1"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
             "auto_retry_allowed", "resume_allowed")
FORBIDDEN_METHODS = ("submit", "run", "recover", "submit_and_run", "validate", "execute_work_order",
                     "run_blueprint", "submit_blueprint", "status", "result", "evidence", "decision", "_load_json")


def wid(i: int) -> str:
    return f"w-{i:02d}"


def worker(worker_id, depends_on=(), **overrides) -> fd.DirectorDagWorkerSummary:
    """A worker whose health/proof are derived by the Director's own helper
    unless explicitly overridden."""
    values = dict(
        worker_id=worker_id, depends_on=tuple(depends_on), worker_state="SUCCESS", state_reason="provider prose",
        provider="claude", requested_provider="claude", work_status="SUCCESS", provider_work_status="SUCCESS",
        work_status_source="RUNNER_ACCEPTANCE", runner_state="SUCCESS", attempts=1, work_attempts_used=1,
        availability_attempts=0, provider_condition=None, next_eligible_utc=None, checkpoint_commit="abc1234",
        worker_record="PRESENT", evidence_dir=SECRET_DIR, evidence_complete=True, unauthorized_changed_paths=(),
    )
    values.update(overrides)
    if "evidence_health" not in overrides:
        values["evidence_health"] = {True: "COMPLETE", False: "INCOMPLETE"}.get(values["evidence_complete"],
                                                                                "UNKNOWN")
    if "unproven_reasons" not in overrides:
        values["unproven_reasons"] = fd._dag_unproven_reasons(
            worker_state=values["worker_state"], work_status=values["work_status"],
            worker_record=values["worker_record"], evidence_health=values["evidence_health"],
            unauthorized=values["unauthorized_changed_paths"],
        )
    if "runner_proven_success" not in overrides:
        values["runner_proven_success"] = not values["unproven_reasons"]
    return fd.DirectorDagWorkerSummary(**values)


def chain(n: int, overrides=None) -> tuple:
    overrides = overrides or {}
    return tuple(worker(wid(i), (wid(i - 1),) if i else (), **overrides.get(i, {})) for i in range(n))


def dag(workers=None, pipeline_status="SUCCESS", n=3, **overrides) -> fd.DirectorDagRunSummary:
    workers = chain(n) if workers is None else workers
    if type(workers) is tuple and all(type(w) is fd.DirectorDagWorkerSummary for w in workers)             and all(type(w.unproven_reasons) is tuple for w in workers):
        aggregate, reasons = fd._classify_dag_aggregate(pipeline_status, workers)
    else:
        aggregate, reasons = pipeline_status, ()
    values = dict(
        run_id=RUN, pipeline_id=RUN, blueprint_pipeline_id=BLUEPRINT, manifest_sha256=MANIFEST,
        plan_fingerprint=PLAN, pipeline_status=pipeline_status, stop_reason="provider prose", workers=workers,
        aggregate_status=aggregate, aggregate_reasons=reasons,
    )
    values.update(overrides)
    return fd.DirectorDagRunSummary(**values)


class FakeService:
    """Only `result_blueprint` exists; any other attribute access is recorded
    and fails."""

    def __init__(self, value, *, raises=None):
        self.__dict__["calls"] = []
        self.__dict__["forbidden"] = []
        self.__dict__["_value"] = value
        self.__dict__["_raises"] = raises

    def result_blueprint(self, run_id):
        self.calls.append(run_id)
        if self._raises is not None:
            raise self._raises
        return self._value

    def __getattr__(self, name):
        self.forbidden.append(name)
        raise AssertionError(f"forbidden access: {name}")

    def __setattr__(self, name, value):
        raise AssertionError(f"forbidden write: {name}")


def observe(summary, **kwargs):
    service = FakeService(summary, raises=kwargs.pop("raises", None))
    return vd.observe_dag_run(service, RUN, **kwargs), service


def obs(summary, **kwargs):
    return observe(summary, **kwargs)[0]


# ---------------------------------------------------------------------------
class ReadDisciplineTests(unittest.TestCase):
    def test_reads_result_blueprint_exactly_once_and_nothing_else(self):
        o, service = observe(dag())
        self.assertEqual(service.calls, [RUN])
        self.assertEqual(service.forbidden, [])
        self.assertEqual(o.classification, vd.ALL_WORKERS_PROVEN)

    def test_no_io_process_or_network_during_observation(self):
        summary = dag(n=9)
        boom = mock.Mock(side_effect=AssertionError("io"))
        with mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(subprocess, "run", boom), mock.patch.object(socket, "socket", boom), \
                mock.patch.object(Path, "read_text", boom), mock.patch.object(Path, "write_text", boom), \
                mock.patch.object(Path, "exists", boom):
            o, _ = observe(summary)
        boom.assert_not_called()
        self.assertEqual(o.classification, vd.ALL_WORKERS_PROVEN)

    def test_module_source_has_no_dispatch_io_or_runner_imports(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(f"{node.module}.{a.name}" if node.module else a.name for a in node.names)
                imported.add(node.module or "")
        allowed = {"__future__", "__future__.annotations", "json", "re", "dataclasses", "dataclasses.dataclass",
                   "typing", "typing.Optional", "scripts.ai", "scripts.ai.fabric_director",
                   "scripts.ai.fabric_validation_contract", "fabric_director", "fabric_validation_contract"}
        self.assertEqual(imported - allowed, set())
        called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for name in FORBIDDEN_METHODS + ("PipelineRunner", "open", "Popen", "system", "read_text", "write_text",
                                         "_dag_unproven_reasons", "_classify_dag_aggregate", "_dag_worker_summary"):
            self.assertNotIn(name, called)

    def test_sources_are_not_mutated(self):
        summary = dag(n=9)
        before = copy.deepcopy(summary)
        observe(summary)
        self.assertEqual(summary, before)

    def test_invalid_run_id_reads_nothing(self):
        for bad in (None, "", 5, b"fdb-x", "not-a-director-id", "fdb-" + "x" * 80):
            with self.subTest(bad=bad):
                service = FakeService(dag())
                o = vd.observe_dag_run(service, bad)
                self.assertEqual(service.calls, [])
                self.assertEqual((o.classification, o.observation_codes), (vd.UNOBSERVABLE, ("RUN_ID_INVALID",)))

    def test_invalid_expected_digest_reads_nothing(self):
        for bad in ("A" * 64, "a" * 63, 7, ""):
            with self.subTest(bad=bad):
                service = FakeService(dag())
                o = vd.observe_dag_run(service, RUN, expected_plan_fingerprint=bad)
                self.assertEqual(service.calls, [])
                self.assertEqual(o.observation_codes, ("EXPECTED_DIGEST_INVALID",))

    def test_read_failures_are_unobservable(self):
        cases = (
            (OSError("disk"), "READ_FAILED"),
            (fd.DirectorError("PIPELINE_NOT_FOUND", "x"), "READ_FAILED"),
            (fd.DirectorError("DAG_PROVENANCE_MISMATCH", "x"), "PROVENANCE_REFUSED"),
        )
        for exc, code in cases:
            with self.subTest(code=code):
                o = obs(dag(), raises=exc)
                self.assertEqual((o.classification, o.observation_codes), (vd.UNOBSERVABLE, (code,)))
                self.assertFalse(o.evidence_sufficient)
                self.assertEqual(o.workers, ())

    def test_wrong_summary_types_and_missing_method(self):
        class SubSummary(fd.DirectorDagRunSummary):
            pass

        summary = dag()
        for bad in (dataclasses.asdict(summary), SubSummary(**{f.name: getattr(summary, f.name)
                                                               for f in dataclasses.fields(summary)}), None):
            with self.subTest(bad=type(bad).__name__):
                self.assertEqual(obs(bad).observation_codes, ("SUMMARY_NOT_TYPED",))
        self.assertEqual(vd.observe_dag_run(object(), RUN).observation_codes, ("READ_FAILED",))


class PositiveTests(unittest.TestCase):
    def assert_proven(self, o, n):
        self.assertEqual(o.classification, vd.ALL_WORKERS_PROVEN)
        self.assertTrue(o.evidence_sufficient and o.all_work_proven)
        self.assertEqual((o.worker_count, o.runner_proven_count, o.evidence_certain_count), (n, n, n))
        for w in o.workers:
            self.assertTrue(w.work_proven and w.evidence_certain)
            # Safety/acceptance are not projected: never inferred, never READY.
            self.assertIsNone(w.facts.safety_clean)
            self.assertIsNone(w.facts.acceptance_proven)
            self.assertFalse(w.assessment.ready_for_human_review)
            self.assertEqual(w.checkpoint, vd.CHECKPOINT_RECORDED)

    def test_two_workers_proven(self):
        o = obs(dag(n=2))
        self.assert_proven(o, 2)
        self.assertEqual([w.depends_on for w in o.workers], [(), (0,)])

    def test_nine_workers_fan_out_fan_in(self):
        root = worker("root")
        mids = tuple(worker(f"mid-{i}", ("root",)) for i in range(7))
        sink = worker("sink", tuple(m.worker_id for m in reversed(mids)))
        o = obs(dag((root,) + mids + (sink,)))
        self.assert_proven(o, 9)
        self.assertEqual(o.workers[8].depends_on, tuple(range(7, 0, -1)))
        self.assertTrue(all(w.depends_on == (0,) for w in o.workers[1:8]))

    def test_sixty_four_workers_proven(self):
        self.assert_proven(obs(dag(n=64)), 64)

    def test_native_order_is_kept_not_sorted(self):
        workers = (worker("zeta"), worker("alpha", ("zeta",)), worker("mid", ("alpha", "zeta")))
        o = obs(dag(workers))
        self.assertEqual([w.index for w in o.workers], [0, 1, 2])
        self.assertEqual([w.depends_on for w in o.workers], [(), (0,), (1, 0)])

    def test_dependency_on_a_later_worker_is_allowed(self):
        o = obs(dag((worker("a", ("b",)), worker("b"))))
        self.assertEqual(o.classification, vd.ALL_WORKERS_PROVEN)
        self.assertEqual(o.workers[0].depends_on, (1,))

    def test_matching_expected_digests(self):
        o = obs(dag(), expected_manifest_sha256=MANIFEST, expected_plan_fingerprint=PLAN)
        self.assertEqual(o.classification, vd.ALL_WORKERS_PROVEN)


class EvidenceInsufficientTests(unittest.TestCase):
    def test_aggregate_success_with_single_unproven_worker(self):
        workers = chain(3, {1: {"evidence_complete": None}})
        o = obs(dag(workers, aggregate_status="SUCCESS"))
        self.assertEqual(o.classification, vd.TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT)
        self.assertFalse(o.evidence_sufficient)
        self.assertTrue(o.all_work_proven)
        self.assertIn("AGGREGATE_SUCCESS_WITH_UNPROVEN_WORKER", o.observation_codes)
        self.assertEqual(o.runner_proven_count, 2)
        self.assertFalse(o.workers[1].evidence_certain)

    def test_native_unverified_aggregate_separates_work_from_evidence(self):
        o = obs(dag(chain(4, {2: {"evidence_complete": False}})))
        self.assertEqual(o.aggregate_status, fd.DAG_AGGREGATE_UNVERIFIED)
        self.assertEqual(o.classification, vd.TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT)
        w = o.workers[2]
        self.assertTrue(w.work_proven)
        self.assertFalse(w.evidence_certain)
        self.assertEqual(w.unproven_reasons, ("EVIDENCE_INCOMPLETE",))
        self.assertIs(w.facts.evidence_complete, False)

    def test_sixty_four_workers_one_unproven(self):
        o = obs(dag(chain(64, {63: {"evidence_complete": None}})))
        self.assertFalse(o.evidence_sufficient)
        self.assertEqual((o.runner_proven_count, o.evidence_certain_count), (63, 63))

    def test_missing_worker_record_is_not_technical_success(self):
        o = obs(dag(chain(2, {0: {"worker_record": "MISSING", "evidence_complete": None}})))
        self.assertEqual(o.classification, vd.SUCCESS_REPORTED_EVIDENCE_INSUFFICIENT)
        w = o.workers[0]
        self.assertIsNone(w.facts.work_success)
        self.assertIsNone(w.facts.provenance_bound)
        self.assertIn("WORKER_RECORD_MISSING", w.observation_codes)

    def test_stale_or_foreign_worker_record(self):
        o = obs(dag(chain(2, {1: {"worker_record": "MISMATCH", "evidence_complete": None}})))
        w = o.workers[1]
        self.assertIs(w.facts.provenance_bound, False)
        self.assertIn("WORKER_RECORD_STALE_OR_FOREIGN", w.observation_codes)
        self.assertFalse(o.evidence_sufficient)

    def test_stale_provenance_against_expected_digests(self):
        for kwargs in ({"expected_manifest_sha256": "c" * 64}, {"expected_plan_fingerprint": "c" * 64}):
            with self.subTest(**kwargs):
                o = obs(dag(), **kwargs)
                self.assertEqual(o.classification, vd.INVALID_PROJECTION)
                self.assertEqual(o.observation_codes, ("STALE_PROVENANCE",))
                self.assertEqual(o.workers, ())

    def test_no_checkpoint_is_unverifiable_not_success(self):
        o = obs(dag(chain(2, {1: {"checkpoint_commit": None}})))
        w = o.workers[1]
        self.assertTrue(w.runner_proven_success)  # Director's verdict, verbatim
        self.assertIsNone(w.facts.work_success)
        self.assertEqual(w.checkpoint, vd.CHECKPOINT_ABSENT)
        self.assertIn("CHECKPOINT_UNVERIFIABLE", w.observation_codes)
        self.assertEqual(o.classification, vd.SUCCESS_REPORTED_EVIDENCE_INSUFFICIENT)

    def test_provider_sourced_success_is_not_certified(self):
        for source, code in (("PROVIDER", "WORK_STATUS_PROVIDER_ONLY"), (None, "WORK_STATUS_SOURCE_MISSING"),
                             ("SELF", "WORK_STATUS_SOURCE_UNRECOGNIZED")):
            with self.subTest(source=source):
                o = obs(dag(chain(2, {0: {"work_status_source": source}})))
                self.assertIsNone(o.workers[0].facts.work_success)
                self.assertIn(code, o.workers[0].observation_codes)
                self.assertFalse(o.evidence_sufficient)

    def test_unauthorized_paths_are_scope_violation(self):
        o = obs(dag(chain(2, {0: {"unauthorized_changed_paths": ("secret/x.py",)}})))
        w = o.workers[0]
        self.assertIs(w.facts.scope_clean, False)
        self.assertFalse(w.work_proven)
        self.assertEqual(o.classification, vd.SUCCESS_REPORTED_EVIDENCE_INSUFFICIENT)

    def test_provider_condition_on_success_is_unknown(self):
        o = obs(dag(chain(2, {1: {"provider_condition": "PROVIDER_QUOTA_EXHAUSTED"}})))
        self.assertIsNone(o.workers[1].facts.work_success)
        self.assertIn("PROVIDER_CONDITION_PRESENT", o.workers[1].observation_codes)


class StatusTests(unittest.TestCase):
    def test_partial_pipeline(self):
        workers = chain(3, {2: {"worker_state": "FAILED", "work_status": "FAILED", "checkpoint_commit": None}})
        o = obs(dag(workers, pipeline_status="PARTIAL"))
        self.assertEqual(o.classification, vd.NOT_SUCCESSFUL)
        self.assertIs(o.workers[2].facts.work_success, False)
        self.assertTrue(o.workers[0].work_proven)
        self.assertIn("PIPELINE_NOT_SUCCESSFUL", o.observation_codes)
        self.assertIn("WORKER_NOT_SUCCESSFUL", o.observation_codes)

    def test_blocked_pipeline_with_waiting_dependents(self):
        workers = chain(3, {1: {"worker_state": "BLOCKED", "work_status": "BLOCKED", "checkpoint_commit": None},
                            2: {"worker_state": "WAITING_DEPENDENCY", "work_status": None, "evidence_complete": None,
                                "worker_record": "MISSING", "checkpoint_commit": None}})
        o = obs(dag(workers, pipeline_status="BLOCKED"))
        self.assertEqual(o.classification, vd.NOT_SUCCESSFUL)
        self.assertEqual(o.aggregate_status, "BLOCKED")
        self.assertIn("WORKER_NOT_TERMINAL", o.workers[2].observation_codes)
        self.assertIsNone(o.workers[2].facts.work_success)

    def test_running_pipeline_is_not_terminal(self):
        workers = chain(2, {1: {"worker_state": "RUNNING", "work_status": None, "evidence_complete": None,
                                "worker_record": "MISSING", "checkpoint_commit": None}})
        o = obs(dag(workers, pipeline_status="RUNNING"))
        self.assertEqual(o.classification, vd.NOT_TERMINAL)
        self.assertIn("PIPELINE_NOT_TERMINAL", o.observation_codes)

    def test_unknown_pipeline_status(self):
        for status in ("WEIRD", None):
            with self.subTest(status=status):
                o = obs(dag(pipeline_status=status))
                self.assertEqual(o.classification, vd.UNKNOWN_STATUS)
                self.assertEqual(o.aggregate_status, fd.DAG_AGGREGATE_UNKNOWN)
                self.assertIn(o.pipeline_status, (vd.UNRECOGNIZED, None))
                self.assertFalse(o.evidence_sufficient)

    def test_unrecognized_worker_state(self):
        o = obs(dag(chain(2, {0: {"worker_state": "DONE"}})))
        w = o.workers[0]
        self.assertEqual(w.worker_state, vd.UNRECOGNIZED)
        self.assertIn("WORKER_STATE_UNKNOWN", w.observation_codes)
        self.assertIsNone(w.facts.work_success)


class SchemaProvenanceTests(unittest.TestCase):
    def assert_invalid(self, summary, code):
        o = obs(summary)
        self.assertEqual(o.classification, vd.INVALID_PROJECTION)
        self.assertIn(code, o.observation_codes)
        self.assertEqual(o.workers, ())
        self.assertFalse(o.evidence_sufficient or o.all_work_proven)

    def test_cardinality_bounds(self):
        self.assert_invalid(dag(n=1), "TOO_FEW_WORKERS")
        self.assert_invalid(dag(workers=()), "TOO_FEW_WORKERS")
        self.assert_invalid(dag(n=65), "TOO_MANY_WORKERS")

    def test_too_many_workers_is_refused_before_iterating(self):
        class Poison:
            def __eq__(self, other):
                raise AssertionError("iterated")
            __hash__ = object.__hash__

        o = obs(dag(workers=(Poison(),) * 100000))
        self.assertEqual(o.observation_codes, ("TOO_MANY_WORKERS",))

    def test_duplicate_worker_id(self):
        self.assert_invalid(dag((worker("a"), worker("a"))), "DUPLICATE_WORKER_ID")

    def test_bad_worker_ids(self):
        for bad in ("", 3, None, "x" * (vd.MAX_ID_LENGTH + 1)):
            with self.subTest(bad=bad):
                self.assert_invalid(dag((worker("a"), worker(bad))), "WORKER_ID_INVALID")

    def test_depends_on_violations(self):
        cases = (
            ((worker("a"), worker("b", ("ghost",))), "DEPENDS_ON_UNKNOWN_WORKER"),
            ((worker("a", ("a",)), worker("b")), "DEPENDS_ON_SELF"),
            ((worker("a"), worker("b", ("a", "a"))), "DEPENDS_ON_DUPLICATE"),
            ((worker("a"), dataclasses.replace(worker("b"), depends_on=["a"])), "DEPENDS_ON_MALFORMED"),
            ((worker("a"), dataclasses.replace(worker("b"), depends_on=(1,))), "DEPENDS_ON_MALFORMED"),
        )
        for workers, code in cases:
            with self.subTest(code=code):
                self.assert_invalid(dag(workers), code)

    def test_dependency_cycle(self):
        self.assert_invalid(dag((worker("a", ("c",)), worker("b", ("a",)), worker("c", ("b",)))),
                            "DEPENDENCY_CYCLE")

    def test_missing_or_malformed_digests(self):
        for bad in (None, "", "A" * 64, "a" * 63, 5):
            with self.subTest(bad=bad):
                self.assert_invalid(dag(manifest_sha256=bad), "MANIFEST_DIGEST_MISSING")
                self.assert_invalid(dag(plan_fingerprint=bad), "PLAN_FINGERPRINT_MISSING")

    def test_identity_mismatches(self):
        other = "fdb-20261030t000000000000-00000000"
        self.assert_invalid(dag(run_id=other), "RUN_ID_MISMATCH")
        self.assert_invalid(dag(pipeline_id=other), "PIPELINE_ID_MISMATCH")
        self.assert_invalid(dag(blueprint_pipeline_id=None), "BLUEPRINT_PIPELINE_ID_MISSING")

    def test_workers_container_and_types(self):
        self.assert_invalid(dag(workers=list(chain(2))), "WORKERS_NOT_TUPLE")
        self.assert_invalid(dag(workers=(worker("a"), dataclasses.asdict(worker("b")))), "WORKER_NOT_TYPED")

    def test_aggregate_status_corruption(self):
        self.assert_invalid(dag(aggregate_status="APPROVED"), "AGGREGATE_STATUS_MALFORMED")
        self.assert_invalid(dag(pipeline_status="FAILED", aggregate_status="SUCCESS"), "AGGREGATE_STATUS_MISMATCH")
        self.assert_invalid(dag(pipeline_status="WEIRD", aggregate_status="SUCCESS"), "AGGREGATE_STATUS_MISMATCH")

    def test_aggregate_reasons_corruption(self):
        for bad in (("ghost:EVIDENCE_UNKNOWN",), ("w-00:NOT_A_REASON",), ("free text",), ["w-00:EVIDENCE_UNKNOWN"],
                    ("w-00:EVIDENCE_UNKNOWN",) * 2, tuple(f"w-00:{i}" for i in range(100))):
            with self.subTest(bad=str(bad)[:40]):
                self.assert_invalid(dag(aggregate_reasons=bad), "AGGREGATE_REASONS_MALFORMED")


class ProofConsistencyTests(unittest.TestCase):
    def test_proof_disagreeing_with_reasons_is_never_upgraded(self):
        workers = chain(2, {1: {"runner_proven_success": True, "unproven_reasons": ("EVIDENCE_UNKNOWN",),
                                "evidence_complete": None}})
        o = obs(dag(workers, aggregate_status="UNVERIFIED", aggregate_reasons=("w-01:EVIDENCE_UNKNOWN",)))
        w = o.workers[1]
        self.assertIn("PROOF_REASONS_DISAGREE", w.observation_codes)
        self.assertFalse(w.evidence_certain)
        self.assertIsNone(w.facts.work_success)
        self.assertIn("WORKER_INCONSISTENT", o.observation_codes)
        self.assertFalse(o.evidence_sufficient)

    def test_proof_contradicting_fields(self):
        workers = chain(2, {0: {"evidence_complete": False, "unproven_reasons": (), "runner_proven_success": True}})
        o = obs(dag(workers))
        self.assertIn("PROOF_CONTRADICTS_FIELDS", o.workers[0].observation_codes)
        self.assertFalse(o.evidence_sufficient)
        self.assertNotEqual(o.classification, vd.ALL_WORKERS_PROVEN)

    def test_reason_contradicting_fields(self):
        workers = chain(2, {1: {"unproven_reasons": ("UNAUTHORIZED_PATHS",), "runner_proven_success": False}})
        o = obs(dag(workers))
        w = o.workers[1]
        self.assertIn("REASON_CONTRADICTS_FIELDS", w.observation_codes)
        self.assertIsNone(w.facts.work_success)
        self.assertFalse(o.evidence_sufficient)

    def test_malformed_proof_values(self):
        for overrides in ({"runner_proven_success": 1}, {"runner_proven_success": "True"},
                          {"unproven_reasons": ("MADE_UP",), "runner_proven_success": False},
                          {"unproven_reasons": ["EVIDENCE_UNKNOWN"], "runner_proven_success": False}):
            with self.subTest(overrides=str(overrides)):
                o = obs(dag(chain(2, {0: overrides}), aggregate_reasons=()))
                w = o.workers[0]
                self.assertIn("PROOF_MALFORMED", w.observation_codes)
                self.assertFalse(w.evidence_certain)
                self.assertFalse(o.evidence_sufficient)

    def test_evidence_health_mismatch(self):
        o = obs(dag(chain(2, {0: {"evidence_complete": True, "evidence_health": "UNKNOWN"}})))
        w = o.workers[0]
        self.assertIn("EVIDENCE_HEALTH_MISMATCH", w.observation_codes)
        self.assertIsNone(w.facts.evidence_complete)
        self.assertFalse(o.evidence_sufficient)

    def test_malformed_evidence_complete_is_never_true(self):
        o = obs(dag(chain(2, {0: {"evidence_complete": 1, "evidence_health": "COMPLETE"}})))
        self.assertIsNone(o.workers[0].facts.evidence_complete)
        self.assertFalse(o.evidence_sufficient)

    def test_unverified_aggregate_with_all_proven_fails_closed(self):
        o = obs(dag(aggregate_status="UNVERIFIED"))
        self.assertIn("AGGREGATE_UNVERIFIED_WITH_ALL_PROVEN", o.observation_codes)
        self.assertEqual(o.classification, vd.TECHNICAL_SUCCESS_EVIDENCE_INSUFFICIENT)

    def test_aggregate_reasons_mismatch_fails_closed(self):
        o = obs(dag(aggregate_reasons=("w-00:EVIDENCE_UNKNOWN",)))
        self.assertIn("AGGREGATE_REASONS_MISMATCH", o.observation_codes)
        self.assertFalse(o.evidence_sufficient)

    def test_unauthorized_paths_over_cap_are_malformed_and_unclean(self):
        paths = tuple(f"p{i}" for i in range(vd.MAX_UNAUTHORIZED_PATHS + 1))
        o = obs(dag(chain(2, {0: {"unauthorized_changed_paths": paths}})))
        w = o.workers[0]
        self.assertIn("FIELD_MALFORMED", w.observation_codes)
        self.assertIs(w.facts.scope_clean, False)

    def test_no_single_mutation_of_a_proven_dag_is_evidence_sufficient(self):
        mutations = (
            {"worker_state": "FAILED"}, {"work_status": "PARTIAL"}, {"work_status": None},
            {"worker_record": "MISSING"}, {"worker_record": "MISMATCH"}, {"evidence_complete": False},
            {"evidence_complete": None}, {"unauthorized_changed_paths": ("x",)}, {"checkpoint_commit": None},
            {"work_status_source": "PROVIDER"}, {"provider_condition": "PROVIDER_AUTH_BLOCKED"},
            {"worker_state": "RUNNING"}, {"worker_state": 5}, {"evidence_health": "BAD"},
        )
        for index in (0, 4, 8):
            for mutation in mutations:
                for aggregate in (None, "SUCCESS"):
                    with self.subTest(index=index, mutation=mutation, aggregate=aggregate):
                        extra = {"aggregate_status": aggregate} if aggregate else {}
                        o = obs(dag(chain(9, {index: mutation}), **extra))
                        self.assertFalse(o.evidence_sufficient)
                        self.assertNotEqual(o.classification, vd.ALL_WORKERS_PROVEN)


class AuthorityPrivacyDeterminismTests(unittest.TestCase):
    def test_every_authority_flag_is_false(self):
        for o in (obs(dag()), obs(dag(n=1)), obs(dag(), raises=OSError())):
            for flag in ALL_FLAGS:
                self.assertIs(getattr(o, flag), False)
                self.assertIs(o.to_dict()[flag], False)
            self.assertEqual(o.to_dict()["marker"], vd.OBSERVATION_MARKER)

    def test_flags_cannot_be_set(self):
        o = obs(dag())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            o.certified = True  # type: ignore[misc]
        with self.assertRaises(TypeError):
            dataclasses.replace(o, execution_allowed=True)

    def test_report_contains_no_ids_digests_paths_or_provider_text(self):
        text = vd.canonical_json(obs(dag(n=9)))
        for needle in (RUN, BLUEPRINT, "w-0", MANIFEST, PLAN, SECRET_DIR, "private", "provider prose",
                       "abc1234", "claude"):
            self.assertNotIn(needle, text)

    def test_canonical_json_is_deterministic(self):
        a, b = obs(dag(n=64)), obs(copy.deepcopy(dag(n=64)))
        self.assertEqual(vd.canonical_json(a), vd.canonical_json(b))
        self.assertEqual(a, b)
        data = json.loads(vd.canonical_json(a))
        self.assertEqual((data["schema"], data["worker_count"]), (vd.SCHEMA, 64))
        with self.assertRaises(TypeError):
            vd.canonical_json(a.to_dict())

    def test_forged_observations_are_rejected(self):
        o = obs(dag(chain(2, {1: {"evidence_complete": None}})))
        with self.assertRaises(ValueError):
            dataclasses.replace(o, classification=vd.ALL_WORKERS_PROVEN, evidence_sufficient=True)
        with self.assertRaises(ValueError):
            dataclasses.replace(o, evidence_sufficient=True)
        with self.assertRaises(ValueError):
            dataclasses.replace(o.workers[1], evidence_certain=True)
        with self.assertRaises(ValueError):
            dataclasses.replace(o.workers[0], work_proven=False)
        forged = vc.assess_validation(vc.ValidationFacts(*(True,) * 6))
        with self.assertRaises(ValueError):
            dataclasses.replace(o.workers[0], assessment=forged)
        with self.assertRaises(ValueError):
            dataclasses.replace(o, observation_codes=("NOT_A_CODE",))
        with self.assertRaises(ValueError):
            vd.DagRunObservation(classification=vd.INVALID_PROJECTION, all_work_proven=False,
                                 evidence_sufficient=False, workers=o.workers, observation_codes=())


class RegressionTests(unittest.TestCase):
    def test_cardinality_matches_blueprint_contract(self):
        self.assertEqual((vd.MIN_WORKERS, vd.MAX_WORKERS),
                         (fd.blueprints.MIN_BLUEPRINT_NODES, fd.blueprints.MAX_BLUEPRINT_NODES))
        self.assertEqual((vd.MIN_WORKERS, vd.MAX_WORKERS), (2, 64))

    def test_unproven_vocabulary_covers_director(self):
        seen = set()
        for state in ("SUCCESS", "FAILED", None):
            for status in ("SUCCESS", "FAILED", None):
                for record in vd.WORKER_RECORDS:
                    for health in vd.EVIDENCE_HEALTHS:
                        for unauthorized in ((), ("x",)):
                            seen.update(fd._dag_unproven_reasons(
                                worker_state=state, work_status=status, worker_record=record,
                                evidence_health=health, unauthorized=unauthorized))
        self.assertEqual(seen, set(vd.UNPROVEN_REASONS))

    def test_every_native_projection_is_never_upgraded(self):
        # Workers built by the Director's own helpers: evidence_sufficient is
        # only ever reported when every worker is Runner-proven.
        for state in sorted(vd.WORKER_STATES):
            for ec in (True, False, None):
                for record in vd.WORKER_RECORDS:
                    workers = chain(2, {1: {"worker_state": state, "evidence_complete": ec, "worker_record": record}})
                    for status in sorted(vd.PIPELINE_STATUSES):
                        o = obs(dag(workers, pipeline_status=status))
                        self.assertNotIn(o.classification, (vd.INVALID_PROJECTION, vd.UNOBSERVABLE))
                        if o.evidence_sufficient:
                            self.assertTrue(all(w.runner_proven_success for w in workers))
                            self.assertEqual(status, "SUCCESS")

    def test_single_worker_adapter_still_refuses_dag_runs(self):
        err = fd.DirectorError("MULTIWORKER_RUN_USE_RESULT_BLUEPRINT", "dag")

        class Refusing:
            def result(self, run_id):
                raise err
            evidence = decision = result

        o = vs.observe_single_run(Refusing(), RUN)
        self.assertEqual(o.observation_codes, ("MULTIWORKER_REFUSED",))
        self.assertFalse(o.assessment.ready_for_human_review)

    def test_contract_inputs_are_typed_facts(self):
        for w in obs(dag(n=3)).workers:
            self.assertIs(type(w.facts), vc.ValidationFacts)
            self.assertEqual(w.assessment, vc.assess_validation(w.facts))


if __name__ == "__main__":
    unittest.main()
