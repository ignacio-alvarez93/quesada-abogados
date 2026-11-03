"""FCP-11C-03: Fabric Control Plane projection of worker / attempt evidence.

State roots are private temporary directories spelled by their physical
path. `worker.json` / `result.json` are written by the Runner's OWN
persistence (`PipelineRunner._init_state` / `_save_worker` / `_write_result`
over a hand-built `Manifest`, fixed clock, no executor, provider or Git) and
the CURRENT evidence root is the Runner's own `_evidence_root`; attempt
records, artifacts and attacks are synthetic. Nothing is executed, sent
anywhere or skipped.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_control_plane_evidence as ev
from scripts.ai import fabric_control_plane_snapshot as snap
from scripts.ai import fabric_resource_quota_report as qrep
from scripts.ai import runner_pipeline as rp
from scripts.tests.test_fabric_resource_quota_report import (
    canonical_temp_dir, directory_alias, remove_directory_alias,
)

MODULE_PATH = Path(ev.__file__)
AS_OF = "2026-11-02T12:00:00Z"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
SECRET = "sk-ant-api03-SYNTHETICSECRETVALUE0123456789"
PRIVATE_PATH = "C:/private/client-data/worktree"
WORK_ORDER = PRIVATE_PATH + "/confidential-work-order.md"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
LEAF1, LEAF2 = "20261102T100000Z_0123abcd", "20261102T110000Z_4567cdef_0123456789"
PID = "fcp11-pipe"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "ledger_write_allowed",
             "state_persisted", "process_control_allowed", "git_allowed")


def tree_state(root: Path) -> dict:
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


class EvidenceTestBase(unittest.TestCase):
    def setUp(self):
        self.root = canonical_temp_dir("fcp11c03-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.runner = self.make_runner()

    def make_runner(self, worker_ids=("w1",)):
        specs = [rp.WorkerSpec(id=wid, worktree=PRIVATE_PATH, work_order=WORK_ORDER, mode="write",
                               checkpoint_policy="ON_SUCCESS", metadata={"note": SECRET}, worktree_top=PRIVATE_PATH)
                 for wid in worker_ids]
        manifest = rp.Manifest(pipeline_id=PID, workers=specs, sha256="b" * 64, raw={"secret": SECRET})
        runner = rp.PipelineRunner(manifest, self.root, self_worktree=Path(PRIVATE_PATH),
                                   clock=lambda: NOW, heartbeat_interval_seconds=None)
        runner._started_at = NOW
        runner._init_state()
        runner._save_pipeline()
        return runner

    # -- fixtures ------------------------------------------------------------
    def current_dir(self, leaf=LEAF1, wid="w1") -> Path:
        return self.runner._evidence_root(wid) / leaf

    def historical_dir(self, leaf=LEAF1, wid="w1") -> Path:
        return self.runner._worker_dir(wid) / "evidence" / leaf

    def artifacts(self, directory: Path, number=1, wid="w1", work_product=True, incomplete=False, **wp_over):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "metadata.json").write_text(json.dumps({"run_id": directory.name}))
        (directory / "result.json").write_text(json.dumps({"state": "SUCCESS"}))
        (directory / "stdout.txt").write_text("VERDICT: SUCCESS " + SECRET)
        (directory / "prompt.txt").write_text(WORK_ORDER)
        if work_product:
            record = {
                "schema_version": 1, "run_id": directory.name, "pipeline_id": PID, "worker_id": wid,
                "attempt": number, "provider": "claude", "worktree": PRIVATE_PATH, "branch": "feature/x",
                "base_head": COMMIT, "authorized_scopes": ["scripts/ai/x.py"],
                "authorized_changed_paths": [" M scripts/ai/x.py"], "process_confirmed_stopped": True,
                "state": "SUCCESS", "incomplete": incomplete, "reason_incomplete": None,
                "evidence_dir": str(directory), "runner_evidence_dir": str(directory), "runner_owned_paths": [],
            }
            record.update(wp_over)
            (directory / "work_product.json").write_text(json.dumps(record))
        return directory

    @staticmethod
    def attempt(number=1, directory=None, work_status="SUCCESS", status="COMPLETED", evidence_complete=True,
                checkpoint="created", **over):
        record = {
            "attempt": number, "provider": "claude", "started_at_utc": "2026-11-02T09:00:00+00:00",
            "status": status, "executed": True, "runner_state": "SUCCESS", "work_status": work_status,
            "provider_work_status": work_status, "work_status_source": "PROVIDER",
            "evidence_dir": None if directory is None else str(directory), "retry_decision": "NONE:SUCCESS",
            "error_message": SECRET, "process_evidence_path": PRIVATE_PATH + "/process.json",
        }
        if evidence_complete is not None:
            record["evidence_complete"] = evidence_complete
        if checkpoint == "created":
            record["checkpoint"] = {"decision": "CREATED", "commit_hash": COMMIT, "reason": SECRET,
                                    "committed_paths": [PRIVATE_PATH], "message": WORK_ORDER,
                                    "work_product_source": "CURRENT_ATTEMPT_WORK_PRODUCT"}
        elif checkpoint is not None:
            record["checkpoint"] = checkpoint
        record.update(over)
        return record

    def record(self, *attempts, wid="w1", result=True, result_extra=None):
        rt = self.runner.workers[wid]
        rt.attempts = list(attempts)
        rt.state = "SUCCESS"
        self.runner._save_worker(rt)
        if result:
            last = attempts[-1] if attempts else {}
            extra = {"outcome": "SUCCESS", "message": SECRET}
            if isinstance(last.get("checkpoint"), dict):
                extra["checkpoint"] = last["checkpoint"]
            extra.update(result_extra or {})
            self.runner._write_result(rt, extra)

    def take(self, root=None, snapshot=None, **kw) -> ev.ControlPlaneEvidence:
        snapshot = snapshot or snap.take_snapshot(str(root or self.root), AS_OF)
        return ev.take_evidence(str(root or self.root), snapshot, **kw)

    @staticmethod
    def worker(evidence, wid="w1") -> ev.WorkerEvidence:
        return next(w for w in evidence.workers if w.worker_id == wid)

    def only(self, evidence, wid="w1") -> ev.AttemptEvidence:
        (attempt,) = self.worker(evidence, wid).attempts
        return attempt

    def assertAbstains(self, a: ev.AttemptEvidence):
        self.assertEqual((a.evidence_complete, a.work_product_present, a.work_product_complete,
                          a.checkpoint_created, a.checkpoint_commit, a.audit_verdict),
                         (ev.UNKNOWN,) * 4 + (None, ev.UNKNOWN))

    def assertUnlocated(self, a: ev.AttemptEvidence, condition, cause):
        self.assertEqual((a.layout, a.location_condition, a.location_cause, a.attempt_leaf, a.artifacts),
                         (ev.LAYOUT_NONE, condition, cause, None, ()))

    def alias(self, target: Path, alias: Path) -> None:
        directory_alias(target, alias)
        self.addCleanup(lambda: os.path.lexists(alias) and remove_directory_alias(alias))


# ---------------------------------------------------------------------------
class TrustedEvidenceTests(EvidenceTestBase):
    def test_success_with_complete_evidence_and_checkpoint(self):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d))
        e = self.take()
        w = self.worker(e)
        self.assertEqual((w.record_condition, w.attempts_total, w.attempts_omitted, w.reference_agreement),
                         (cp.PRESENT, 1, 0, snap.AGREEMENT_CONSISTENT))
        a = self.only(e)
        self.assertEqual((a.attempt, a.attempt_status, a.work_status, a.work_status_source),
                         (1, "COMPLETED", "SUCCESS", "PROVIDER"))
        self.assertEqual((a.layout, a.location_condition, a.attempt_leaf), (ev.LAYOUT_CURRENT, cp.PRESENT, LEAF1))
        self.assertEqual([x.condition for x in a.artifacts], [cp.PRESENT] * 3)
        self.assertEqual((a.evidence_complete, a.work_product_present, a.work_product_complete), (ev.TRUE,) * 3)
        self.assertEqual((a.checkpoint_decision, a.checkpoint_commit, a.checkpoint_created),
                         ("CREATED", COMMIT, ev.TRUE))
        self.assertEqual((a.audit_verdict, a.anomalies), (ev.UNKNOWN, ()))
        refs = e.observation.evidence
        self.assertEqual([(r.kind, r.attempt_leaf, r.condition) for r in refs],
                         [(k, LEAF1, cp.PRESENT) for k in ev.ATTEMPT_ARTIFACT_KINDS])
        self.assertEqual(refs[0].relative_parts()[:2], (rp.EVIDENCE_ROOT_DIRNAME, rp.evidence_root_key(PID, "w1")))
        out = ev.canonical_json(e)
        self.assertIn('"audit_verdict":"UNKNOWN"', out)
        for flag in ALL_FLAGS:
            self.assertIs(e.to_dict()[flag], False)
            self.assertIs(getattr(a, flag), False)

    def test_success_with_incomplete_evidence_keeps_the_axes_apart(self):
        d = self.artifacts(self.current_dir(), work_product=False)
        (d / "metadata.json").unlink()
        self.record(self.attempt(1, d, evidence_complete=False, checkpoint=None))
        a = self.only(self.take())
        self.assertEqual((a.work_status, a.evidence_complete), ("SUCCESS", ev.FALSE))
        self.assertEqual((a.work_product_present, a.work_product_complete), (ev.FALSE, ev.UNKNOWN))
        self.assertEqual((a.checkpoint_decision, a.checkpoint_created), (None, ev.UNKNOWN))
        self.assertEqual(a.artifacts[0].cause, cp.SOURCE_ABSENT)

    def test_incomplete_work_product_and_skipped_checkpoint(self):
        d = self.artifacts(self.current_dir(), incomplete=True)
        self.record(self.attempt(1, d, work_status="PARTIAL",
                                 checkpoint={"decision": "SKIPPED_NO_WORK_PRODUCT", "reason": SECRET}))
        a = self.only(self.take())
        self.assertEqual((a.work_product_present, a.work_product_complete), (ev.TRUE, ev.FALSE))
        self.assertEqual((a.checkpoint_decision, a.checkpoint_created, a.checkpoint_commit),
                         ("SKIPPED_NO_WORK_PRODUCT", ev.FALSE, None))

    def test_refused_checkpoint_is_false_and_shows_no_commit(self):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d, checkpoint={"decision": "REFUSED_HEAD_CHANGED", "commit_hash": COMMIT}))
        a = self.only(self.take())
        self.assertEqual((a.checkpoint_created, a.checkpoint_commit), (ev.FALSE, None))

    def test_acceptance_is_runner_acceptance_never_an_audit(self):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d, work_status_source="RUNNER_ACCEPTANCE",
                                 acceptance={"decision": "PASSED", "commands": [{"argv": [SECRET]}]}))
        a = self.only(self.take())
        self.assertEqual((a.acceptance_decision, a.work_status_source, a.audit_verdict),
                         ("PASSED", "RUNNER_ACCEPTANCE", ev.UNKNOWN))

    def test_historical_layout_is_governed_but_not_a_contract_ref(self):
        d = self.artifacts(self.historical_dir())
        self.record(self.attempt(1, d))
        e = self.take()
        a = self.only(e)
        self.assertEqual((a.layout, a.location_condition, a.evidence_complete, a.checkpoint_created),
                         (ev.LAYOUT_HISTORICAL, cp.PRESENT, ev.TRUE, ev.TRUE))
        self.assertEqual(e.observation.evidence, ())

    def test_mixed_historical_and_current_attempts(self):
        old = self.artifacts(self.historical_dir(LEAF1), number=1)
        new = self.artifacts(self.current_dir(LEAF2), number=2)
        self.record(self.attempt(1, old, checkpoint=None), self.attempt(2, new))
        e = self.take()
        self.assertEqual([a.layout for a in self.worker(e).attempts], [ev.LAYOUT_HISTORICAL, ev.LAYOUT_CURRENT])
        self.assertEqual({r.attempt_leaf for r in e.observation.evidence}, {LEAF2})

    def test_projection_is_read_only(self):
        self.record(self.attempt(1, self.artifacts(self.current_dir())))
        before = tree_state(self.root)
        self.take()
        self.assertEqual(tree_state(self.root), before)


# ---------------------------------------------------------------------------
class AbstentionTests(EvidenceTestBase):
    def test_no_evidence_dir_abstains(self):
        self.record(self.attempt(1, None, checkpoint=None, evidence_complete=None))
        a = self.only(self.take())
        self.assertUnlocated(a, cp.MISSING, cp.FIELD_ABSENT)
        self.assertAbstains(a)

    def test_recorded_true_without_artifacts_is_unverified(self):
        d = self.artifacts(self.current_dir())
        (d / "result.json").unlink()
        self.record(self.attempt(1, d))
        a = self.only(self.take())
        self.assertEqual(a.anomalies, (ev.EVIDENCE_CLAIM_UNVERIFIED,))
        self.assertAbstains(a)

    def test_evidence_dir_recorded_but_absent(self):
        self.record(self.attempt(1, self.current_dir()))
        a = self.only(self.take())
        self.assertEqual((a.location_condition, a.location_cause), (cp.MISSING, cp.SOURCE_ABSENT))
        self.assertAbstains(a)

    def test_corrupt_artifact_is_never_complete(self):
        d = self.artifacts(self.current_dir())
        (d / "metadata.json").write_bytes(b'{"run_id": "x",')
        (d / "work_product.json").write_bytes(b"\xff\xfe")
        self.record(self.attempt(1, d))
        a = self.only(self.take())
        self.assertEqual([x.cause for x in a.artifacts], [cp.SOURCE_NOT_JSON, None, cp.SOURCE_NOT_JSON])
        self.assertAbstains(a)

    def test_missing_or_unbound_worker_record_shows_no_attempts(self):
        self.record(self.attempt(1, self.artifacts(self.current_dir())))
        worker_json = self.runner._worker_dir("w1") / "worker.json"
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        worker_json.write_bytes(worker_json.read_bytes() + b" ")
        w = self.worker(ev.take_evidence(str(self.root), snapshot))
        self.assertEqual((w.record_condition, w.record_cause, w.attempts, w.attempts_total),
                         (cp.UNAVAILABLE, cp.SOURCE_CHANGED_DURING_READ, (), None))
        worker_json.unlink()
        w = self.worker(self.take())
        self.assertEqual((w.record_condition, w.record_cause), (cp.MISSING, cp.SOURCE_ABSENT))

    def test_malformed_worker_records(self):
        cases = {
            cp.SOURCE_NOT_JSON: b"[1, 2]", cp.SCHEMA_UNSUPPORTED: json.dumps({"schema_version": 99}).encode(),
            cp.IDENTITY_MISMATCH: json.dumps({"schema_version": 1, "spec": {"id": "w2"}, "attempts": []}).encode(),
            cp.FIELD_MALFORMED: json.dumps({"schema_version": 1, "spec": {"id": "w1"}, "attempts": [1]}).encode(),
        }
        for cause, data in cases.items():
            with self.subTest(cause=cause):
                (self.runner._worker_dir("w1") / "worker.json").write_bytes(data)
                w = self.worker(self.take())
                self.assertEqual((w.record_cause, w.attempts), (cause, ()))

    def test_unknown_values_are_never_echoed(self):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d, work_status=SECRET, status="running " + SECRET, work_status_source=SECRET,
                                 checkpoint=None))
        a = self.only(self.take())
        self.assertEqual((a.work_status, a.attempt_status, a.work_status_source), (ev.UNKNOWN, None, None))


# ---------------------------------------------------------------------------
class CheckpointConsistencyTests(EvidenceTestBase):
    def check(self, anomaly, **attempt):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d, **attempt))
        a = self.only(self.take())
        self.assertIn(anomaly, a.anomalies)
        self.assertAbstains(a)
        return a

    def test_no_checkpoint_without_result(self):
        for work_status, status in (("FAILED", "COMPLETED"), ("SUCCESS", "RUNNING"), ("UNVERIFIED", "COMPLETED")):
            with self.subTest(work_status=work_status, status=status):
                a = self.check(ev.CHECKPOINT_WITHOUT_RESULT, work_status=work_status, status=status)
                self.assertEqual(a.checkpoint_decision, "CREATED")

    def test_created_checkpoint_needs_a_valid_commit(self):
        for commit in (None, "abc", COMMIT.upper(), 12345, SECRET):
            with self.subTest(commit=commit):
                self.check(ev.CHECKPOINT_COMMIT_INVALID, checkpoint={"decision": "CREATED", "commit_hash": commit})

    def test_malformed_checkpoint_records(self):
        for checkpoint in ("CREATED", ["CREATED"], {"decision": SECRET}, {"decision": "created"}, {}):
            with self.subTest(checkpoint=checkpoint):
                self.check(ev.CHECKPOINT_MALFORMED, checkpoint=checkpoint)

    def test_result_json_referencing_another_evidence_dir_diverges(self):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d), result_extra={"evidence_dir": str(self.current_dir(LEAF2))})
        e = self.take()
        self.assertEqual(self.worker(e).reference_agreement, snap.AGREEMENT_DIVERGENT)
        self.assertEqual(self.only(e).anomalies, (ev.RESULT_REFERENCE_MISMATCH,))
        self.assertAbstains(self.only(e))

    def test_result_json_with_another_checkpoint_commit_diverges(self):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d), result_extra={"checkpoint": {"decision": "CREATED",
                                                                     "commit_hash": OTHER_COMMIT}})
        e = self.take()
        self.assertEqual(self.worker(e).reference_agreement, snap.AGREEMENT_DIVERGENT)
        self.assertAbstains(self.only(e))

    def test_result_json_reporting_an_unknown_attempt_diverges_for_all(self):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d), result_extra={"attempts": [{"attempt": 7}]})
        e = self.take()
        self.assertEqual(self.worker(e).reference_agreement, snap.AGREEMENT_DIVERGENT)
        self.assertEqual(self.only(e).anomalies, (ev.RESULT_REFERENCE_MISMATCH,))

    def test_result_json_for_an_earlier_attempt_only_binds_that_attempt(self):
        d1 = self.artifacts(self.current_dir(LEAF1), number=1)
        self.record(self.attempt(1, d1))
        d2 = self.artifacts(self.current_dir(LEAF2), number=2)
        rt = self.runner.workers["w1"]
        rt.attempts.append(self.attempt(2, d2, status="RUNNING", work_status=None, checkpoint=None,
                                        evidence_complete=None))
        self.runner._save_worker(rt)
        e = self.take()
        self.assertEqual(self.worker(e).reference_agreement, snap.AGREEMENT_CONSISTENT)
        first, second = self.worker(e).attempts
        self.assertEqual((first.checkpoint_created, second.checkpoint_created), (ev.TRUE, ev.UNKNOWN))
        self.assertEqual((second.work_status, second.anomalies), (ev.UNKNOWN, ()))

    def test_missing_result_json_is_unverifiable_not_divergent(self):
        self.record(self.attempt(1, self.artifacts(self.current_dir())), result=False)
        e = self.take()
        self.assertEqual(self.worker(e).reference_agreement, snap.AGREEMENT_UNVERIFIABLE)
        self.assertEqual(self.only(e).checkpoint_created, ev.TRUE)

    def test_changed_result_json_is_unverifiable(self):
        self.record(self.attempt(1, self.artifacts(self.current_dir())))
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        result = self.runner._worker_dir("w1") / "result.json"
        result.write_bytes(result.read_bytes() + b"\n")
        self.assertEqual(self.worker(ev.take_evidence(str(self.root), snapshot)).reference_agreement,
                         snap.AGREEMENT_UNVERIFIABLE)


# ---------------------------------------------------------------------------
class WorkProductTests(EvidenceTestBase):
    def check(self, anomaly, **wp_over):
        d = self.artifacts(self.current_dir(), **wp_over)
        self.record(self.attempt(1, d))
        a = self.only(self.take())
        self.assertEqual(a.anomalies, (anomaly,))
        self.assertAbstains(a)

    def test_work_product_of_another_attempt_is_refused(self):
        other = str(self.current_dir(LEAF2))
        for over in ({"pipeline_id": "other"}, {"worker_id": "w2"}, {"attempt": 2}, {"attempt": True},
                     {"run_id": LEAF2}, {"evidence_dir": other}, {"evidence_dir": None}):
            with self.subTest(over=over):
                self.check(ev.WORK_PRODUCT_IDENTITY_MISMATCH, **over)

    def test_unsupported_work_product_schema(self):
        for version in (2, "1", None, True):
            with self.subTest(version=version):
                self.check(ev.WORK_PRODUCT_SCHEMA_UNSUPPORTED, schema_version=version)

    def test_non_boolean_incomplete_leaves_completeness_unknown(self):
        d = self.artifacts(self.current_dir(), incomplete="no")
        self.record(self.attempt(1, d))
        a = self.only(self.take())
        self.assertEqual((a.work_product_present, a.work_product_complete), (ev.TRUE, ev.UNKNOWN))


# ---------------------------------------------------------------------------
class MaliciousReferenceTests(EvidenceTestBase):
    def unlocated(self, raw, condition, cause):
        # (`_write_result` itself would crash on a non-string evidence_dir.)
        self.record(self.attempt(1, None, evidence_dir=raw), result=isinstance(raw, str))
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        with mock.patch.object(ev.snap.qrep, "read_input_bytes", wraps=qrep.read_input_bytes) as reads:
            a = self.only(ev.take_evidence(str(self.root), snapshot))
        worker_dir = os.path.normcase(str(self.runner._worker_dir("w1")))
        opened = [os.path.normcase(os.path.dirname(c.args[0])) for c in reads.call_args_list]
        self.assertTrue(opened and set(opened) == {worker_dir}, opened)  # worker.json / result.json only
        self.assertUnlocated(a, condition, cause)
        self.assertAbstains(a)

    def test_references_outside_the_governed_layouts(self):
        key = rp.evidence_root_key(PID, "w1")
        root, outside = str(self.root), canonical_temp_dir("fcp11c03-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        self.artifacts(outside / LEAF1)
        cases = [
            (str(outside / LEAF1), cp.PATH_REFUSED),
            (os.path.join(root, "_evidence", key, "..", "..", "_evidence", key, LEAF1), cp.PATH_REFUSED),
            (os.path.join("_evidence", key, LEAF1), cp.PATH_REFUSED),
            ("\\\\server\\share\\_evidence\\" + LEAF1, cp.PATH_REFUSED),
            ("file://" + root, cp.PATH_REFUSED),
            (root + "-sibling" + os.sep + LEAF1, cp.PATH_REFUSED),
            (os.path.join(root, "_evidence", rp.evidence_root_key(PID, "w2"), LEAF1), cp.EVIDENCE_PATH_UNEXPECTED),
            (os.path.join(root, "_evidence", key), cp.EVIDENCE_PATH_UNEXPECTED),
            (os.path.join(root, "_evidence", key, LEAF1, "nested"), cp.EVIDENCE_PATH_UNEXPECTED),
            (os.path.join(root, "_evidence", key, "not-a-leaf"), cp.EVIDENCE_PATH_UNEXPECTED),
            (os.path.join(root, PID, "workers", "w2", "evidence", LEAF1), cp.EVIDENCE_PATH_UNEXPECTED),
            (os.path.join(root, PID, "workers", "w1", LEAF1), cp.EVIDENCE_PATH_UNEXPECTED),
            (os.path.join(root, PID), cp.EVIDENCE_PATH_UNEXPECTED),
            (root, cp.EVIDENCE_PATH_UNEXPECTED),
        ]
        for raw, cause in cases:
            with self.subTest(raw=raw):
                self.unlocated(raw, cp.CAUSE_CONDITION[cause], cause)

    def test_malformed_references(self):
        for raw in ("", 42, ["x"], {"p": 1}, "C:\\" + "a" * ev.MAX_EVIDENCE_DIR_CHARS):
            with self.subTest(raw=type(raw).__name__):
                self.unlocated(raw, cp.CORRUPT, cp.FIELD_MALFORMED)
        self.unlocated(str(self.root) + "\x00x", cp.UNAVAILABLE, cp.PATH_REFUSED)

    def test_evidence_directory_through_a_junction_is_refused_unread(self):
        outside = canonical_temp_dir("fcp11c03-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        self.artifacts(outside / LEAF1)
        self.current_dir().parent.mkdir(parents=True)
        self.alias(outside / LEAF1, self.current_dir())
        self.unlocated_link(self.current_dir())

    def test_evidence_root_through_a_junction_is_refused_unread(self):
        outside = canonical_temp_dir("fcp11c03-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        key = rp.evidence_root_key(PID, "w1")
        self.artifacts(outside / key / LEAF1)
        self.alias(outside, self.root / rp.EVIDENCE_ROOT_DIRNAME)
        self.unlocated_link(self.current_dir())

    def unlocated_link(self, directory):
        self.record(self.attempt(1, directory))
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        with mock.patch.object(ev.snap.qrep, "read_input_bytes", wraps=qrep.read_input_bytes) as reads:
            a = self.only(ev.take_evidence(str(self.root), snapshot))
        self.assertFalse([c for c in reads.call_args_list if LEAF1 in c.args[0]])
        self.assertEqual((a.location_condition, a.location_cause), (cp.UNAVAILABLE, cp.LINK_REFUSED))
        self.assertAbstains(a)

    def test_artifact_file_symlinks_are_refused(self):
        d = self.artifacts(self.current_dir())
        outside = canonical_temp_dir("fcp11c03-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        shutil.move(str(d / "metadata.json"), str(outside / "metadata.json"))
        try:
            os.symlink(str(outside / "metadata.json"), str(d / "metadata.json"))
        except OSError:  # unprivileged Windows: no file symlinks; junction cases cover links there
            self.assertEqual(os.name, "nt")
            return
        self.record(self.attempt(1, d))
        a = self.only(self.take())
        self.assertEqual(a.artifacts[0].cause, cp.LINK_REFUSED)
        self.assertAbstains(a)

    def test_artifact_directory_planted_where_a_file_belongs(self):
        d = self.artifacts(self.current_dir(), work_product=False)
        (d / "work_product.json").mkdir()
        self.record(self.attempt(1, d))
        a = self.only(self.take())
        self.assertEqual(a.artifacts[2].cause, cp.SOURCE_UNREADABLE)
        self.assertEqual(a.work_product_present, ev.UNKNOWN)

    def test_duplicate_evidence_references(self):
        d = self.artifacts(self.current_dir())
        spelled = str(d).upper() if os.name == "nt" else str(d) + os.sep
        self.record(self.attempt(1, d, checkpoint=None), self.attempt(2, spelled))
        for a in self.worker(self.take()).attempts:
            self.assertIn(ev.DUPLICATE_EVIDENCE_REFERENCE, a.anomalies)
            self.assertUnlocated(a, cp.UNAVAILABLE, cp.EVIDENCE_PATH_UNEXPECTED)
            self.assertAbstains(a)

    def test_duplicate_attempt_numbers(self):
        d1 = self.artifacts(self.current_dir(LEAF1), number=1)
        d2 = self.artifacts(self.current_dir(LEAF2), number=1)
        self.record(self.attempt(1, d1, checkpoint=None), self.attempt(1, d2))
        for a in self.worker(self.take()).attempts:
            self.assertEqual(a.anomalies, (ev.DUPLICATE_ATTEMPT_NUMBER,))
            self.assertEqual(a.location_condition, cp.PRESENT)
            self.assertAbstains(a)

    def test_unexpected_reader_failures_degrade_safely(self):
        self.record(self.attempt(1, self.artifacts(self.current_dir())))
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        for error in (OSError("C:/secret/path denied"), ValueError(SECRET), qrep.ReportError("REPORT_INTERNAL_ERROR")):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(ev.snap.qrep, "read_input_bytes", side_effect=error):
                e = ev.take_evidence(str(self.root), snapshot)
                self.assertEqual(self.worker(e).record_cause, cp.SOURCE_UNREADABLE)
                self.assertNotIn("secret", ev.canonical_json(e).lower())


# ---------------------------------------------------------------------------
class SanitizationAndLimitTests(EvidenceTestBase):
    def test_no_path_secret_or_work_order_reaches_the_output(self):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d, error=SECRET, reconciliation={"work_product_path": str(d)},
                                 acceptance={"decision": "PASSED", "reason": SECRET}))
        out = ev.canonical_json(self.take())
        lowered = out.lower()
        for needle in (str(self.root), str(d), PRIVATE_PATH, WORK_ORDER, SECRET, "client-data", "feature/x",
                       "scripts/ai/x.py", "verdict: success", "sk-ant", "\\\\", "C:".lower() + "\\\\"):
            self.assertNotIn(needle.lower(), lowered)
        self.assertTrue(out.isascii())

    def test_artifact_size_limit_refuses_before_reading(self):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d))
        worker_dir = self.runner._worker_dir("w1")
        limit = max(p.stat().st_size for p in (worker_dir / "worker.json", worker_dir / "result.json",
                                               d / "metadata.json", d / "result.json"))
        (d / "work_product.json").write_bytes(b" " * limit + (d / "work_product.json").read_bytes())
        a = self.only(self.take(max_file_bytes=limit))
        wp = a.artifacts[2]
        self.assertEqual((wp.condition, wp.cause), (cp.UNAVAILABLE, cp.SOURCE_TOO_LARGE))
        self.assertEqual((a.work_product_present, a.checkpoint_created), (ev.UNKNOWN, ev.TRUE))

    def test_oversized_artifact_over_the_fcp10_cap(self):
        d = self.artifacts(self.current_dir())
        (d / "metadata.json").write_bytes(b" " * (snap.MAX_FILE_BYTES + 1))
        self.record(self.attempt(1, d))
        a = self.only(self.take())
        self.assertEqual(a.artifacts[0].cause, cp.SOURCE_TOO_LARGE)
        self.assertEqual(a.anomalies, (ev.EVIDENCE_CLAIM_UNVERIFIED,))

    def test_attempt_limit_shows_the_newest_and_counts_the_rest(self):
        attempts = [self.attempt(n, None, checkpoint=None) for n in range(1, 6)]
        self.record(*attempts)
        w = self.worker(self.take(max_attempts_per_worker=2, max_attempt_reads=4))
        self.assertEqual(([a.attempt for a in w.attempts], w.attempts_total, w.attempts_omitted), ([4, 5], 5, 3))

    def test_read_budget_omits_whole_workers_deterministically(self):
        shutil.rmtree(self.root / PID)
        self.runner = self.make_runner(("w1", "w2", "w3"))
        for wid in ("w1", "w2", "w3"):
            self.record(self.attempt(1, None, checkpoint=None), self.attempt(2, None, checkpoint=None), wid=wid)
        e = self.take(max_attempts_per_worker=2, max_attempt_reads=5)
        self.assertEqual(([w.worker_id for w in e.workers], e.workers_omitted), (["w1", "w2"], 1))

    def test_invalid_arguments_raise(self):
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        with self.assertRaises(TypeError):
            ev.take_evidence(str(self.root), snapshot.to_dict())
        for kw in ({"max_attempts_per_worker": 0}, {"max_attempts_per_worker": True},
                   {"max_attempt_reads": ev.MAX_ATTEMPT_READS + 1}, {"max_attempts_per_worker": 9,
                                                                     "max_attempt_reads": 8},
                   {"max_file_bytes": 0}, {"max_file_bytes": snap.MAX_FILE_BYTES + 1}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                ev.take_evidence(str(self.root), snapshot, **kw)
        with self.assertRaises(TypeError):
            ev.canonical_json(snapshot)

    def test_default_limits_fit_the_contract(self):
        self.assertLessEqual(ev.MAX_ATTEMPT_READS * len(ev.ATTEMPT_ARTIFACT_KINDS), cp.MAX_EVIDENCE_REFS)
        self.assertLessEqual(ev.DEFAULT_MAX_ATTEMPTS_PER_WORKER, ev.DEFAULT_MAX_ATTEMPT_READS)

    def test_unreadable_roots_show_nothing(self):
        absent = self.root / "absent"
        e = self.take(root=absent)
        self.assertEqual((e.root_condition, e.root_cause, e.workers), (cp.MISSING, cp.SOURCE_ABSENT, ()))
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        for root in ("relative/root", str(absent)):
            with self.subTest(root=root):
                e = ev.take_evidence(root, snapshot)
                self.assertNotEqual(e.root_condition, cp.PRESENT)
                self.assertEqual(e.workers, ())

    def test_evidence_root_through_an_alias_is_refused(self):
        self.record(self.attempt(1, self.artifacts(self.current_dir())))
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        holder = canonical_temp_dir("fcp11c03-alias-")
        self.addCleanup(shutil.rmtree, holder, ignore_errors=True)
        self.alias(self.root, holder / "alias")
        e = ev.take_evidence(str(holder / "alias"), snapshot)
        self.assertEqual((e.root_condition, e.root_cause), (cp.UNAVAILABLE, cp.LINK_REFUSED))


# ---------------------------------------------------------------------------
class DeterminismAndInvariantTests(EvidenceTestBase):
    def test_equal_inputs_give_byte_equal_output(self):
        self.record(self.attempt(1, self.artifacts(self.current_dir())))
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        first = ev.canonical_json(ev.take_evidence(str(self.root), snapshot))
        self.assertEqual(first, ev.canonical_json(ev.take_evidence(str(self.root), snapshot)))
        e = json.loads(first)
        self.assertEqual((e["schema"], e["snapshot_revision"]), (ev.SCHEMA, snapshot.revision))

    def test_any_material_change_changes_the_revision(self):
        d = self.artifacts(self.current_dir())
        self.record(self.attempt(1, d))
        before = self.take().revision
        (d / "metadata.json").write_text(json.dumps({"run_id": "changed"}))
        self.assertNotEqual(before, self.take().revision)

    def test_views_reject_impossible_claims(self):
        base = dict(attempt=1, attempt_status="COMPLETED", work_status="SUCCESS", work_status_source=None,
                    acceptance_decision=None, layout=ev.LAYOUT_NONE, location_condition=cp.MISSING,
                    location_cause=cp.FIELD_ABSENT)
        ev.AttemptEvidence(**base)
        bad = (
            {"evidence_complete": ev.TRUE}, {"work_product_present": ev.TRUE},
            {"anomalies": (ev.CHECKPOINT_MALFORMED,), "checkpoint_created": ev.FALSE},
            {"checkpoint_created": ev.TRUE}, {"checkpoint_commit": COMMIT},
            {"checkpoint_created": ev.TRUE, "checkpoint_commit": COMMIT, "checkpoint_decision": "CREATED",
             "work_status": "FAILED"},
            {"work_status": "DONE"}, {"attempt": 0}, {"attempt_status": SECRET}, {"layout": ev.LAYOUT_CURRENT},
            {"attempt_leaf": LEAF1}, {"anomalies": ("NOPE",)},
            {"anomalies": (ev.RESULT_REFERENCE_MISMATCH, ev.DUPLICATE_ATTEMPT_NUMBER)},
        )
        for over in bad:
            with self.subTest(over=over), self.assertRaises(ValueError):
                ev.AttemptEvidence(**{**base, **over})
        with self.assertRaises(ValueError):
            ev.WorkerEvidence(PID, "w1", cp.MISSING, cp.SOURCE_ABSENT, attempts_total=0)
        with self.assertRaises(ValueError):
            ev.WorkerEvidence(PID, "w1", cp.PRESENT, attempts_total=2, attempts_omitted=0,
                              attempts=(ev.AttemptEvidence(**base),))
        with self.assertRaises(ValueError):
            ev.ArtifactView("ATTEMPT_METADATA", cp.PRESENT)

    def test_evidence_must_seal_its_workers_refs(self):
        self.record(self.attempt(1, self.artifacts(self.current_dir())))
        e = self.take()
        with self.assertRaises(ValueError):
            ev.ControlPlaneEvidence(e.snapshot_revision, cp.ControlPlaneObservation(AS_OF), workers=e.workers)
        with self.assertRaises(ValueError):
            ev.ControlPlaneEvidence("x", e.observation, workers=e.workers)


# ---------------------------------------------------------------------------
class StaticGovernanceTests(unittest.TestCase):
    def tree(self):
        return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    def test_module_imports_nothing_that_executes_or_mutates(self):
        imported = set()
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {node.module} | {f"{node.module}.{a.name}" for a in node.names}
        for name in imported:
            for word in ("subprocess", "socket", "urllib", "http", "requests", "shutil", "threading", "asyncio",
                         "multiprocessing", "datetime", "time", "sqlite3", "claude_runner", "runner_git",
                         "fabric_director", "runner_factory_ledger", "tempfile", "json"):
                self.assertNotIn(word, name.split("."), name)

    def test_module_calls_no_writing_clock_or_process_api(self):
        tree = self.tree()
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("environ", "getenv", "write_text", "write_bytes", "mkdir", "makedirs", "remove", "unlink",
                          "rename", "replace", "rmdir", "system", "popen", "Popen", "now", "utcnow", "sleep", "time",
                          "symlink", "chmod", "_atomic_write_json", "_transition", "_save_pipeline", "_save_worker",
                          "append_event", "create_checkpoint", "load_work_product_record", "evaluate_resume",
                          "read_text", "read_bytes", "listdir", "scandir"):
            self.assertNotIn(forbidden, names)
        self.assertNotIn("open", {n.func.id for n in ast.walk(tree)
                                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)})

    def test_never_names_provider_prose_artifacts(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        code = source.split('"""', 2)[2]  # outside the module docstring
        for name in ("stdout.txt", "stderr.txt", "prompt.txt", "git_before", "work_order"):
            self.assertNotIn(name, code)

    def test_contract_snapshot_and_reader_are_reused_not_redefined(self):
        defined = {n.name for n in ast.walk(self.tree()) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for duplicated in ("read_input_bytes", "admit_path", "parse_document", "_read_json", "_admit_root", "_probe",
                           "observe_status", "valid_id", "valid_code", "EvidenceRef", "evidence_root_key",
                           "same_physical_path", "_canonical", "ControlPlaneObservation"):
            self.assertNotIn(duplicated, defined)
        self.assertIs(ev.cp, cp)
        self.assertIs(ev.snap, snap)
        self.assertEqual(ev.WORK_STATUSES, tuple(s.value for s in rp.providers.WorkStatus))

    def test_every_file_read_goes_through_the_fcp10_reader_under_the_root(self):
        case = TrustedEvidenceTests("test_projection_is_read_only")
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.record(case.attempt(1, case.artifacts(case.current_dir())))
        snapshot = snap.take_snapshot(str(case.root), AS_OF)
        with mock.patch.object(ev.snap.qrep, "read_input_bytes", wraps=qrep.read_input_bytes) as reads:
            ev.take_evidence(str(case.root), snapshot)
        opened = sorted(os.path.basename(c.args[0]) for c in reads.call_args_list)
        self.assertEqual(opened, ["metadata.json", "result.json", "result.json", "work_product.json", "worker.json"])
        for call in reads.call_args_list:
            self.assertTrue(os.path.normcase(call.args[0]).startswith(os.path.normcase(str(case.root)) + os.sep))


if __name__ == "__main__":
    unittest.main()
