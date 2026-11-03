"""FCP-11A-01: Fabric Control Plane contract.

The contract is pure, so every payload here is synthetic: pipeline results
are hand-written dicts shaped like `PipelineRunner.build_result`, paths and
secrets are fake markers, and nothing is read, executed or persisted.
Nothing here is skipped.
"""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import json
import os
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner
from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_director as fd
from scripts.ai import fabric_resource_quota_recovery as qr
from scripts.ai import fabric_scheduler_contract as sc
from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_provider_availability as availability

MODULE_PATH = Path(cp.__file__)
TEST_PATH = Path(__file__).resolve()
AS_OF = "2026-11-02T12:00:00Z"
SHA = "a" * 64
COMMIT = "0123456789abcdef0123456789abcdef01234567"
LEAF = "20261102T101010Z_1a2b3c4d"
SECRET = "sk-ant-api03-SYNTHETICSECRETVALUE"
FAKE_PATH = "C:\\Users\\someone\\private\\state\\workers\\w1\\result.json"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "ledger_write_allowed",
             "state_persisted", "process_control_allowed", "git_allowed")

ADVERSARIAL_IDS = (
    "", ".", "..", "../x", "a/b", "a\\b", "C:", "a:b", "a b", "a\x00b", "a\nb", ".hidden", "trailing.", "a" * 65,
    "CON", "con", "nul.txt", "COM1", "lpt9.log", "\u00e9t\u00e9", "\uff41", "%2e%2e", "sk-abcdef123",
    "0123456789abcdef0123456789abcdef", "x-" + "Z" * 40, None, 7, True, b"pipe", ["p"],
)


def _module_code() -> str:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    if tree.body and isinstance(tree.body[0], ast.Expr):
        tree.body = tree.body[1:]
    return ast.unparse(tree)


def worker_entry(wid="w1", **overrides) -> dict:
    entry = {
        "id": wid, "provider": "claude", "requested_provider": "claude", "state": "SUCCESS", "state_reason": None,
        "attempts": 1, "work_attempts_used": 1, "availability_attempts": 0, "provider_condition": None,
        "next_eligible_utc": None, "result_path": FAKE_PATH, "worker_path": FAKE_PATH,
        "checkpoint_policy": "ON_SUCCESS", "checkpoint_commit": COMMIT,
    }
    entry.update(overrides)
    return entry


def pipeline_payload(pid="fcp11-pipe", workers=None, **overrides) -> dict:
    workers = [worker_entry()] if workers is None else workers
    payload = {
        "schema_version": 1, "pipeline_id": pid, "status": "SUCCESS", "stop_reason": None,
        "started_at_utc": "2026-11-02T10:00:00.123456+00:00", "ended_at_utc": "2026-11-02T10:30:00+00:00",
        "duration_seconds": 1800.0, "workers_total": len(workers), "success": 1, "partial": 0, "blocked": 0,
        "failed": 0, "cancelled": 0, "interrupted": 0, "waiting_provider_quota": 0, "blocked_provider_auth": 0,
        "state_counts": {}, "provider_breakdown": {"claude": {"total": 1}}, "max_observed_concurrency": 1,
        "workers": workers,
    }
    payload.update(overrides)
    return payload


def evidence(kind="PIPELINE_RESULT", condition=cp.PRESENT, **kw) -> cp.EvidenceRef:
    needed = cp._placeholders(kind)
    if needed & {"{pipeline}", "{evidence_key}"}:
        kw.setdefault("pipeline_id", "fcp11-pipe")
    if needed & {"{worker}", "{evidence_key}"}:
        kw.setdefault("worker_id", "w1")
    if "{attempt}" in needed:
        kw.setdefault("attempt_leaf", LEAF)
    if condition == cp.PRESENT:
        kw.setdefault("content_sha256", SHA)
        kw.setdefault("size_bytes", 10)
    return cp.EvidenceRef(kind, condition, **kw)


def observation(**kw) -> cp.ControlPlaneObservation:
    kw.setdefault("pipelines", (cp.project_pipeline_result(pipeline_payload(), "fcp11-pipe"),))
    kw.setdefault("evidence", (evidence(),))
    return cp.ControlPlaneObservation(AS_OF, **kw)


def _build_result_keys() -> tuple:
    tree = ast.parse(Path(rp.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_result")
    worker = next(n.args[0] for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "append")
    top = next(n.value for n in ast.walk(fn) if isinstance(n, ast.Return))
    return {k.value for k in top.keys}, {k.value for k in worker.keys}


# ---------------------------------------------------------------------------
class IdentifierTests(unittest.TestCase):
    def test_real_runner_and_director_ids_are_valid(self):
        for value in ("fcp10-ci-windows-report-path-toctou-20261102-r11", "fdb-20261102t101010z-1a2b3c4d",
                      "fix_ci_windows_path_toctou_r11", "w1", "_abc", "Worker.v2", "ab-" * 21 + "a"):
            self.assertTrue(cp.valid_id(value), value)

    def test_adversarial_ids_are_refused(self):
        for value in ADVERSARIAL_IDS:
            self.assertFalse(cp.valid_id(value), repr(value))

    def test_str_subclass_ids_are_refused(self):
        class Sneaky(str):
            pass
        self.assertFalse(cp.valid_id(Sneaky("w1")))

    def test_secret_rule_mirrors_runner_redact_per_token(self):
        self.assertNotEqual(availability.redact("a" * 32), "a" * 32)
        self.assertEqual(availability.redact("a" * 31), "a" * 31)
        self.assertTrue(cp.valid_id("-".join(["a" * 31] * 2)))
        self.assertFalse(cp.valid_id("ok-" + "a" * 32))
        self.assertFalse(cp.valid_id("task.sk-abcdef"))

    def test_codes_and_reasons(self):
        self.assertTrue(cp.valid_code("CHECKPOINT_FAILED"))
        for bad in ("lower", "A-B", "A" * 65, "C", "", None, 3, "SK_" + "A" * 40):
            self.assertFalse(cp.valid_code(bad), repr(bad))
        self.assertEqual(cp.reason_code("PROVIDER_QUOTA_EXHAUSTED:RESET_HINT"), "PROVIDER_QUOTA_EXHAUSTED")
        self.assertEqual(cp.reason_code(f"FALLBACK_TO:{SECRET}"), "FALLBACK_TO")
        self.assertIsNone(cp.reason_code("waiting for a,b"))
        self.assertIsNone(cp.reason_code(f"{FAKE_PATH}:x"))
        self.assertIsNone(cp.reason_code(5))

    def test_timestamps_are_strict_utc_and_normalized(self):
        self.assertEqual(cp.normalized_utc("2026-11-02T10:00:00+00:00"), "2026-11-02T10:00:00Z")
        for bad in ("2026-11-02T10:00:00", "2026-11-02T10:00:00+01:00", "yesterday", "", None, 1):
            self.assertIsNone(cp.normalized_utc(bad), repr(bad))


# ---------------------------------------------------------------------------
class StatusTests(unittest.TestCase):
    def test_every_worker_state_maps_through_the_runner_category(self):
        terminal = {s.value for s in rp.TERMINAL_STATES} | {"INTERRUPTED"}
        for state in cp.WORKER_STATES:
            view = cp.observe_status(cp.SOURCE_WORKER_STATE, state)
            self.assertEqual(view.lifecycle, rp._WORKER_CATEGORY[state])
            self.assertEqual(view.runner_outcome, state if state in terminal else cp.OUTCOME_NONE)
            self.assertEqual(view.actor, qr.ACTOR_NONE)

    def test_pipeline_statuses_terminal_and_non_terminal(self):
        expected = {
            "RUNNING": ("ACTIVE", "NONE"), "DRAINING": ("ACTIVE", "NONE"), "INCOMPLETE": ("INCOMPLETE", "NONE"),
            "SUCCESS": ("TERMINAL", "SUCCESS"), "PARTIAL": ("TERMINAL", "PARTIAL"),
            "BLOCKED": ("TERMINAL", "BLOCKED"), "FAILED": ("TERMINAL", "FAILED"),
            "CANCELLED": ("TERMINAL", "CANCELLED"),
        }
        self.assertEqual(set(expected), set(cp.PIPELINE_STATUSES))
        for status, pair in expected.items():
            view = cp.observe_status(cp.SOURCE_PIPELINE_STATUS, status)
            self.assertEqual((view.lifecycle, view.runner_outcome), pair, status)

    def test_director_unverified_is_never_success(self):
        view = cp.observe_status(cp.SOURCE_DIRECTOR_DAG_AGGREGATE, fd.DAG_AGGREGATE_UNVERIFIED)
        self.assertEqual((view.lifecycle, view.runner_outcome), ("TERMINAL", "UNVERIFIED"))
        view = cp.observe_status(cp.SOURCE_DIRECTOR_DAG_AGGREGATE, fd.DAG_AGGREGATE_UNKNOWN)
        self.assertEqual((view.lifecycle, view.runner_outcome), ("UNKNOWN", "UNKNOWN"))
        with self.assertRaises(ValueError):
            cp.StatusView(cp.SOURCE_PIPELINE_STATUS, cp.PRESENT, "UNVERIFIED")

    def test_absent_corrupt_or_unavailable_is_unknown_never_success(self):
        for cause, condition in cp.CAUSE_CONDITION.items():
            for kind in cp.SOURCE_KINDS:
                view = cp.observe_status(kind, "SUCCESS", condition=condition, cause=cause)
                self.assertEqual((view.condition, view.source_value, view.cause), (condition, None, cause))
                self.assertEqual((view.lifecycle, view.runner_outcome), ("UNKNOWN", "UNKNOWN"))
                self.assertEqual(view.actor, cp.CONDITION_ACTOR[condition])

    def test_unrecognized_or_missing_values_fail_closed_without_echo(self):
        for raw in ("success", "DONE", SECRET, FAKE_PATH, 1, True, {"state": "SUCCESS"}, ["SUCCESS"]):
            view = cp.observe_status(cp.SOURCE_WORKER_STATE, raw)
            self.assertEqual((view.condition, view.cause, view.source_value), (cp.CORRUPT, cp.VALUE_UNRECOGNIZED, None))
            self.assertNotIn("SUCCESS", json.dumps(view.to_dict()).replace('"UNKNOWN"', ""))
        view = cp.observe_status(cp.SOURCE_WORKER_STATE, None)
        self.assertEqual((view.condition, view.cause), (cp.MISSING, cp.FIELD_ABSENT))

    def test_presentation_is_derived_never_claimed(self):
        fields = {f.name for f in dataclasses.fields(cp.StatusView)}
        self.assertFalse(fields & {"lifecycle", "runner_outcome", "actor"})
        for args in ((cp.SOURCE_WORKER_STATE, cp.PRESENT, "NOPE"), (cp.SOURCE_WORKER_STATE, cp.PRESENT, None),
                     (cp.SOURCE_WORKER_STATE, cp.MISSING, "SUCCESS", cp.SOURCE_ABSENT),
                     (cp.SOURCE_WORKER_STATE, cp.MISSING, None, cp.LINK_REFUSED),
                     (cp.SOURCE_WORKER_STATE, cp.MISSING, None, None),
                     (cp.SOURCE_WORKER_STATE, cp.PRESENT, "SUCCESS", cp.SOURCE_ABSENT),
                     ("OTHER", cp.PRESENT, "SUCCESS"), (cp.SOURCE_WORKER_STATE, "FINE", "SUCCESS")):
            with self.assertRaises(ValueError, msg=repr(args)):
                cp.StatusView(*args)


# ---------------------------------------------------------------------------
class EvidenceRefTests(unittest.TestCase):
    def test_inventory_matches_the_native_layout(self):
        self.assertEqual(evidence("PIPELINE_RESULT").relative_parts(), ("fcp11-pipe", "pipeline_result.json"))
        self.assertEqual(evidence("WORKER_RESULT").relative_parts(),
                         ("fcp11-pipe", "workers", "w1", "result.json"))
        self.assertEqual(evidence("ATTEMPT_WORK_PRODUCT").relative_parts(),
                         (rp.EVIDENCE_ROOT_DIRNAME, rp.evidence_root_key("fcp11-pipe", "w1"), LEAF, "work_product.json"))
        self.assertEqual(evidence("FACTORY_EVENTS").relative_parts(), (flog.EVENTS_FILENAME,))
        self.assertEqual(evidence("DIRECTOR_DAG_PLAN").relative_parts(), ("fcp11-pipe", fd.DAG_PLAN_FILENAME))
        for kind in cp.EVIDENCE_KINDS:
            self.assertIn(evidence(kind).root_kind, cp.ROOT_KINDS)

    def test_sensitive_and_derived_files_are_not_referenceable(self):
        names = {parts[-1] for _root, parts in cp.EVIDENCE_INVENTORY.values()}
        for excluded in ("prompt.txt", "stdout.txt", "stderr.txt", "git_before.txt", flog.MODULES_FILENAME, "lock"):
            self.assertNotIn(excluded, names)
        self.assertTrue(names <= {"pipeline.json", "pipeline_result.json", "worker.json", "heartbeat.json",
                                  "preflight.json", "result.json", "metadata.json", "work_product.json",
                                  flog.EVENTS_FILENAME, fd.DAG_MANIFEST_FILENAME, fd.DAG_PLAN_FILENAME,
                                  fd.DAG_PROVENANCE_FILENAME})

    def test_serialization_never_contains_a_path(self):
        for kind in cp.EVIDENCE_KINDS:
            ref = evidence(kind)
            text = json.dumps(ref.to_dict())
            for part in ref.relative_parts():
                if part not in ("fcp11-pipe", "w1", LEAF):
                    self.assertNotIn(part, text)
            self.assertNotIn("/", text)
            self.assertNotIn("\\", text)

    def test_ids_and_leaves_are_validated(self):
        for bad in ADVERSARIAL_IDS:
            with self.assertRaises(ValueError, msg=repr(bad)):
                evidence("WORKER_RESULT", pipeline_id=bad)
            with self.assertRaises(ValueError, msg=repr(bad)):
                evidence("ATTEMPT_RESULT", worker_id=bad)
        for leaf in ("../x", "20261102T101010Z", "20261102T101010Z_1A2B3C4D", LEAF + "/..", None):
            with self.assertRaises(ValueError, msg=repr(leaf)):
                evidence("ATTEMPT_RESULT", attempt_leaf=leaf)
        with self.assertRaises(ValueError):
            evidence("FACTORY_EVENTS", pipeline_id="p1")
        with self.assertRaises(ValueError):
            evidence("PIPELINE_RESULT", worker_id="w1")
        with self.assertRaises(ValueError):
            evidence("WORKER_RESULT", attempt_leaf=LEAF)
        with self.assertRaises(ValueError):
            cp.EvidenceRef("NOT_A_KIND", cp.MISSING, cause=cp.SOURCE_ABSENT)

    def test_content_facts_only_for_present_and_bounded(self):
        for bad in ({"content_sha256": None}, {"content_sha256": "A" * 64}, {"content_sha256": "a" * 63},
                    {"size_bytes": -1}, {"size_bytes": cp.MAX_EVIDENCE_BYTES + 1}, {"size_bytes": True},
                    {"size_bytes": 1.0}, {"cause": cp.SOURCE_ABSENT}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                evidence(**bad)
        with self.assertRaises(ValueError):
            evidence(condition=cp.MISSING, cause=cp.SOURCE_ABSENT, content_sha256=SHA)
        with self.assertRaises(ValueError):
            evidence(condition=cp.CORRUPT, cause=cp.SOURCE_ABSENT)
        for cause, condition in cp.CAUSE_CONDITION.items():
            ref = evidence(condition=condition, cause=cause)
            self.assertEqual(ref.to_dict()["actor"], cp.CONDITION_ACTOR[condition])


# ---------------------------------------------------------------------------
class ProjectionTests(unittest.TestCase):
    def test_well_formed_result_is_projected_through_the_allowlist(self):
        view = cp.project_pipeline_result(pipeline_payload(), "fcp11-pipe")
        self.assertEqual((view.status.condition, view.status.runner_outcome), (cp.PRESENT, "SUCCESS"))
        self.assertEqual(view.started_at_utc, "2026-11-02T10:00:00.123456Z")
        self.assertEqual((view.workers_total, view.rejected_workers, view.malformed_fields), (1, 0, ()))
        worker = view.workers[0]
        self.assertEqual((worker.worker_id, worker.provider_id, worker.checkpoint_commit), ("w1", "claude", COMMIT))
        text = json.dumps(view.to_dict())
        for withheld in ("result_path", "worker_path", "duration_seconds", "provider_breakdown", FAKE_PATH,
                         "private"):
            self.assertNotIn(withheld, text)

    def test_document_level_corruption(self):
        cases = (
            (None, cp.SOURCE_NOT_JSON), ([], cp.SOURCE_NOT_JSON), ("{}", cp.SOURCE_NOT_JSON),
            (pipeline_payload(schema_version=2), cp.SCHEMA_UNSUPPORTED),
            (pipeline_payload(schema_version=True), cp.SCHEMA_UNSUPPORTED),
            (pipeline_payload(schema_version="1"), cp.SCHEMA_UNSUPPORTED),
            (pipeline_payload(pid="other"), cp.IDENTITY_MISMATCH),
            (pipeline_payload(pid="../fcp11-pipe"), cp.IDENTITY_MISMATCH),
            (pipeline_payload(status="DONE"), cp.VALUE_UNRECOGNIZED),
            (pipeline_payload(status=None), cp.FIELD_ABSENT),
        )
        for payload, cause in cases:
            view = cp.project_pipeline_result(payload, "fcp11-pipe")
            self.assertEqual((view.status.condition, view.status.cause), (cp.CAUSE_CONDITION[cause], cause))
            self.assertEqual((view.workers, view.status.runner_outcome), ((), "UNKNOWN"))

    def test_worker_entries_that_cannot_be_identified_are_rejected_not_shown(self):
        entries = [worker_entry("w1"), worker_entry("w1"), worker_entry("../w2"), worker_entry(SECRET), "x", None,
                   worker_entry("w3"), {"state": "SUCCESS"}]
        view = cp.project_pipeline_result(pipeline_payload(workers=entries), "fcp11-pipe")
        self.assertEqual([w.worker_id for w in view.workers], ["w3"])
        self.assertEqual(view.rejected_workers, 7)
        self.assertNotIn(SECRET, json.dumps(view.to_dict()))

    def test_malformed_public_fields_degrade_to_none_and_are_named(self):
        bad = worker_entry(provider=FAKE_PATH, requested_provider="Claude", state="WEIRD", state_reason=7,
                           attempts=-1, work_attempts_used=True, availability_attempts="0",
                           provider_condition="QUOTA", next_eligible_utc="tomorrow", checkpoint_policy="ALWAYS",
                           checkpoint_commit="HEAD")
        view = cp.project_pipeline_result(
            pipeline_payload(workers=[bad], stop_reason={"x": 1}, started_at_utc="2026-11-02T10:00:00",
                             workers_total=5, max_observed_concurrency=99), "fcp11-pipe")
        self.assertEqual(view.malformed_fields, ("stop_reason", "started_at_utc", "workers_total",
                                                 "max_observed_concurrency"))
        worker = view.workers[0]
        self.assertEqual(worker.malformed_fields, tuple(f for f in cp.WORKER_PUBLIC_FIELDS if f != "id"))
        self.assertEqual((worker.status.condition, worker.status.runner_outcome), (cp.CORRUPT, "UNKNOWN"))
        for name in ("provider_id", "requested_provider_id", "state_reason", "attempts", "checkpoint_commit"):
            self.assertIsNone(getattr(worker, name))
        self.assertNotIn(FAKE_PATH.replace("\\", "\\\\"), json.dumps(view.to_dict()))

    def test_native_reason_prose_is_withheld_not_malformed(self):
        entry = worker_entry(state="WAITING_DEPENDENCY", state_reason="waiting for w0,w2")
        worker = cp.project_pipeline_result(pipeline_payload(workers=[entry], status="RUNNING"), "fcp11-pipe").workers[0]
        self.assertEqual((worker.state_reason, worker.malformed_fields), (None, ()))
        self.assertEqual((worker.status.lifecycle, worker.status.runner_outcome), ("QUEUED", "NONE"))
        entry = worker_entry(state="WAITING_PROVIDER_QUOTA", state_reason="PROVIDER_QUOTA_EXHAUSTED:RESET_HINT",
                             provider_condition="PROVIDER_QUOTA_EXHAUSTED", next_eligible_utc="2026-11-02T13:00:00+00:00")
        worker = cp.project_pipeline_result(pipeline_payload(workers=[entry]), "fcp11-pipe").workers[0]
        self.assertEqual((worker.state_reason, worker.next_eligible_utc, worker.status.lifecycle),
                         ("PROVIDER_QUOTA_EXHAUSTED", "2026-11-02T13:00:00Z", "WAITING"))

    def test_workers_container_is_bounded_and_typed(self):
        for workers in ({"w1": {}}, "w1", [worker_entry(f"w{i}") for i in range(cp.MAX_WORKERS + 1)]):
            view = cp.project_pipeline_result(pipeline_payload(workers=workers), "fcp11-pipe")
            self.assertEqual(view.workers, ())
            self.assertIn("workers", view.malformed_fields)

    def test_projection_never_raises_on_hostile_payloads(self):
        hostile = (0, 1.5, "x", b"x", object(), {"schema_version": 1}, {1: 2},
                   pipeline_payload(workers=[{"id": "w1", "state": {"nested": [1] * 100}}]),
                   pipeline_payload(workers=[worker_entry(**{k: object() for k in cp.WORKER_PUBLIC_FIELDS[1:]})]))
        for payload in hostile:
            self.assertIs(type(cp.project_pipeline_result(payload, "fcp11-pipe")), cp.PipelineView)
        with self.assertRaises(ValueError):
            cp.project_pipeline_result(pipeline_payload(), "../x")

    def test_view_invariants_are_enforced(self):
        ok = cp.observe_status(cp.SOURCE_WORKER_STATE, "SUCCESS")
        missing = cp.observe_status(cp.SOURCE_PIPELINE_STATUS, None, condition=cp.MISSING, cause=cp.SOURCE_ABSENT)
        worker = cp.WorkerView("p1", "w1", ok)
        for bad in (lambda: cp.WorkerView("p1", "../w", ok), lambda: cp.WorkerView("p1", "w1", missing),
                    lambda: cp.WorkerView("p1", "w1", ok, provider_id=FAKE_PATH),
                    lambda: cp.WorkerView("p1", "w1", ok, next_eligible_utc="2026-11-02T10:00:00+00:00"),
                    lambda: cp.WorkerView("p1", "w1", ok, malformed_fields=("result_path",)),
                    lambda: cp.PipelineView("p1", ok),
                    lambda: cp.PipelineView("p1", missing, workers=(worker,)),
                    lambda: cp.PipelineView("p2", cp.observe_status(cp.SOURCE_PIPELINE_STATUS, "SUCCESS"),
                                            workers=(worker,)),
                    lambda: cp.PipelineView("p1", cp.observe_status(cp.SOURCE_PIPELINE_STATUS, "SUCCESS"),
                                            workers=[worker])):
            with self.assertRaises(ValueError):
                bad()


# ---------------------------------------------------------------------------
class CatalogPinTests(unittest.TestCase):
    def test_every_pipeline_result_key_is_classified(self):
        top, worker = _build_result_keys()
        self.assertEqual(set(cp.PIPELINE_PUBLIC_FIELDS) | set(cp.PIPELINE_WITHHELD_FIELDS), top)
        self.assertEqual(set(cp.WORKER_PUBLIC_FIELDS) | set(cp.WORKER_WITHHELD_FIELDS), worker)
        self.assertFalse(set(cp.PIPELINE_PUBLIC_FIELDS) & set(cp.PIPELINE_WITHHELD_FIELDS))
        self.assertFalse(set(cp.WORKER_PUBLIC_FIELDS) & set(cp.WORKER_WITHHELD_FIELDS))

    def test_every_ledger_field_is_classified(self):
        event = flog._build_event(flog.WORKER_STARTED, "e1", AS_OF, {}, {"tag": "x"})
        self.assertEqual(set(cp.LEDGER_PUBLIC_FIELDS) | set(cp.LEDGER_WITHHELD_FIELDS), set(event))
        self.assertFalse(set(cp.LEDGER_PUBLIC_FIELDS) & set(cp.LEDGER_WITHHELD_FIELDS))
        self.assertEqual(set(cp.LEDGER_EVENT_TYPES), flog.EVENT_TYPES)

    def test_vocabularies_are_reused(self):
        self.assertEqual(cp.WORKER_STATES, tuple(s.value for s in rp.WorkerState))
        self.assertEqual(cp.PIPELINE_STATUSES, tuple(s.value for s in rp.PipelineStatus))
        self.assertEqual(set(cp.DIRECTOR_DAG_AGGREGATES), set(cp.PIPELINE_STATUSES) | {"UNVERIFIED", "UNKNOWN"})
        self.assertEqual(cp.ACTORS, qr.ACTORS)
        self.assertEqual(set(cp.CHECKPOINT_POLICIES), claude_runner.CHECKPOINT_POLICIES)
        self.assertEqual(set(cp.PROVIDER_CONDITIONS), {c.value for c in availability.ProviderCondition})
        self.assertEqual(set(rp._WORKER_CATEGORY), set(cp.WORKER_STATES))
        self.assertTrue(set(rp._WORKER_CATEGORY.values()) <= set(cp.LIFECYCLES))

    def test_attempt_leaf_mirrors_create_run_dir(self):
        self.assertEqual(claude_runner._LABEL_DIGEST_CHARS, 10)
        tree = ast.parse(Path(claude_runner.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "create_run_dir")
        literals = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertTrue({"%Y%m%dT%H%M%SZ", "_"} <= literals)
        self.assertTrue(cp._ATTEMPT_LEAF_RE.fullmatch(LEAF + "_0123456789"))

    def test_vocabularies_unique_and_upper_snake(self):
        for vocab in (cp.CONDITIONS, cp.CAUSES, cp.SOURCE_KINDS, cp.LIFECYCLES, cp.RUNNER_OUTCOMES, cp.EVIDENCE_KINDS,
                      cp.ROOT_KINDS):
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertEqual(set(cp.CAUSE_CONDITION.values()), set(cp.CONDITIONS) - {cp.PRESENT})
        self.assertEqual(set(cp.CONDITION_ACTOR), set(cp.CONDITIONS))
        self.assertTrue(set(cp.CONDITION_ACTOR.values()) <= set(qr.ACTORS))


# ---------------------------------------------------------------------------
class ObservationTests(unittest.TestCase):
    def test_serialization_is_stable_and_sealed(self):
        first, second = canonical = cp.canonical_json(observation()), cp.canonical_json(observation())
        self.assertEqual(first, second)
        body = json.loads(canonical[0])
        self.assertEqual(body["schema"], cp.SCHEMA)
        self.assertRegex(body["revision"], r"^[0-9a-f]{64}$")
        self.assertEqual(body["revision"], observation().revision)
        self.assertEqual(first, json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True))

    def test_revision_tracks_every_material_change(self):
        base = observation().revision
        changed = (
            cp.ControlPlaneObservation("2026-11-02T12:00:01Z", observation().pipelines, observation().evidence),
            observation(evidence=(evidence(content_sha256="b" * 64),)),
            observation(evidence=()),
            observation(pipelines=(cp.project_pipeline_result(pipeline_payload(status="FAILED"), "fcp11-pipe"),)),
        )
        revisions = {c.revision for c in changed}
        self.assertNotIn(base, revisions)
        self.assertEqual(len(revisions), len(changed))

    def test_collections_must_be_sorted_unique_and_typed(self):
        a = cp.project_pipeline_result(pipeline_payload(pid="a1"), "a1")
        b = cp.project_pipeline_result(pipeline_payload(pid="b1"), "b1")
        self.assertEqual(observation(pipelines=(a, b)).pipelines, (a, b))
        for bad in ({"pipelines": (b, a)}, {"pipelines": (a, a)}, {"pipelines": [a]}, {"pipelines": (a.to_dict(),)},
                    {"evidence": (evidence(), evidence())}, {"evidence": [evidence()]},
                    {"evidence": (evidence("WORKER_RESULT"), evidence("PIPELINE_RESULT"))}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                observation(**bad)
        for instant in ("2026-11-02T12:00:00+00:00", "2026-11-02T12:00:00", None):
            with self.assertRaises(ValueError):
                cp.ControlPlaneObservation(instant)

    def test_canonical_json_is_exact_type_and_bounded(self):
        class Sub(cp.ControlPlaneObservation):
            def to_dict(self):
                return {"certified": True}
        with self.assertRaises(TypeError):
            cp.canonical_json(Sub(AS_OF))
        with self.assertRaises(TypeError):
            cp.canonical_json(observation().to_dict())
        with mock.patch.object(cp, "MAX_CANONICAL_JSON_BYTES", 10):
            with self.assertRaises(ValueError):
                cp.canonical_json(observation())

    def test_output_holds_no_path_secret_or_raw_input(self):
        hostile = worker_entry("w9", state=SECRET, state_reason=f"FAILED:{SECRET}", provider=SECRET)
        pipe = cp.project_pipeline_result(pipeline_payload(workers=[hostile], stop_reason=FAKE_PATH), "fcp11-pipe")
        text = cp.canonical_json(observation(pipelines=(pipe,)))
        for needle in ("sk-", "SYNTHETIC", "Users", "private", "result_path", ":\\\\"):
            self.assertNotIn(needle, text)


# ---------------------------------------------------------------------------
class AuthorityTests(unittest.TestCase):
    def test_every_authority_flag_is_false_by_construction(self):
        objects = (observation(), evidence(), cp.observe_status(cp.SOURCE_WORKER_STATE, "SUCCESS"),
                   observation().pipelines[0], observation().pipelines[0].workers[0])
        for obj in objects:
            for flag in ALL_FLAGS:
                self.assertIs(getattr(obj, flag), False, flag)
                with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
                    setattr(obj, flag, True)
            names = {f.name for f in dataclasses.fields(obj)}
            self.assertFalse(names & set(ALL_FLAGS))
        body = observation().to_dict()
        self.assertEqual(body["marker"], cp.CONTROL_PLANE_MARKER)
        for flag in ALL_FLAGS:
            self.assertIs(body[flag], False)
        with self.assertRaises(TypeError):
            cp.ControlPlaneObservation(AS_OF, certified=True)

    def test_zero_authority_flags_extend_the_scheduler_contract(self):
        self.assertTrue(set(sc._NotAuthorized._guarantees()) <= set(cp._ControlPlaneGuarantees._guarantees()))
        self.assertTrue(issubclass(cp.ControlPlaneObservation, sc._NotAuthorized))


# ---------------------------------------------------------------------------
class PurityTests(unittest.TestCase):
    def test_no_io_processes_network_or_runner_entry_points(self):
        boom = AssertionError("I/O or execution entry point")
        payload = pipeline_payload()
        with mock.patch.object(subprocess, "Popen", side_effect=boom), \
                mock.patch.object(builtins, "open", side_effect=boom), \
                mock.patch.object(socket, "socket", side_effect=boom), \
                mock.patch.object(os, "stat", side_effect=boom), \
                mock.patch.object(os, "replace", side_effect=boom), \
                mock.patch.object(os, "mkdir", side_effect=boom), \
                mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom), \
                mock.patch.object(flog.FactoryLedger, "append", side_effect=boom), \
                mock.patch.object(fd.FabricDirectorService, "__init__", side_effect=boom):
            view = cp.project_pipeline_result(payload, "fcp11-pipe")
            cp.canonical_json(observation(pipelines=(view,)))
            evidence("ATTEMPT_RESULT").relative_parts()

    def test_projection_never_mutates_inputs(self):
        payload = pipeline_payload()
        before = copy.deepcopy(payload)
        cp.project_pipeline_result(payload, "fcp11-pipe")
        self.assertEqual(payload, before)

    def test_module_imports_and_code_stay_within_the_governed_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        own = ("fabric_director", "fabric_resource_quota_contract", "fabric_resource_quota_recovery",
               "fabric_scheduler_contract", "runner_factory_ledger", "runner_pipeline", "runner_provider_availability")
        self.assertEqual(imported, {"__future__", "dataclasses", "hashlib", "re", "typing"}
                         | {f"scripts.ai.{m}" for m in own} | set(own))
        code = _module_code()
        for word in ("subprocess", "open(", "Path(", "os.", "socket", "Thread", "Executor", "PipelineRunner(",
                     "DirLease", ".append(event", "FactoryLedger(", "read_events", "_atomic_write", ".now(",
                     "utcnow", "sleep", "while ", "eval(", "exec(", "importlib", "random", "requests.", "urllib",
                     "http", "environ", "execute_work_order", "FabricDirectorService", "cost", "price", "progress"):
            self.assertNotIn(word, code, word)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))])

    def test_no_mutable_module_state_changes(self):
        modules = (cp, rp, flog, availability)
        snapshots = [{k: copy.deepcopy(v) for k, v in vars(mod).items()
                      if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
                     for mod in modules]
        cp.project_pipeline_result(pipeline_payload(), "fcp11-pipe")
        cp.project_pipeline_result(None, "fcp11-pipe")
        cp.canonical_json(observation())
        for mod, snapshot in zip(modules, snapshots):
            self.assertEqual({k: v for k, v in vars(mod).items() if k in snapshot}, snapshot)

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


if __name__ == "__main__":
    unittest.main()
