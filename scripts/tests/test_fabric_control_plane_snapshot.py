"""FCP-11B-02: Fabric Control Plane snapshot of Runner pipelines and workers.

State roots are private temporary directories spelled by their physical
path. Real-schema fixtures are written by the Runner's OWN persistence
(`PipelineRunner._init_state` / `_transition` / `_write_result` /
`_save_pipeline` over a hand-built `Manifest`, fixed clock, no executor, no
provider, no Git); adversarial fixtures are synthetic bytes. Nothing is
executed, sent anywhere or skipped.
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
from scripts.ai import fabric_control_plane_snapshot as snap
from scripts.ai import fabric_resource_quota_report as qrep
from scripts.ai import runner_pipeline as rp
from scripts.tests.test_fabric_resource_quota_report import (
    canonical_temp_dir, directory_alias, remove_directory_alias, short_path,
)

MODULE_PATH = Path(snap.__file__)
AS_OF = "2026-11-02T12:00:00Z"
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
SECRET = "sk-ant-api03-SYNTHETICSECRETVALUE0123456789"
PRIVATE_PATH = "C:/private/client-data/worktree"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "ledger_write_allowed",
             "state_persisted", "process_control_allowed", "git_allowed")
W = rp.WorkerState


def tree_state(root: Path) -> dict:
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


class SnapshotTestBase(unittest.TestCase):
    def setUp(self):
        self.root = canonical_temp_dir("fcp11b02-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    # -- real Runner persistence -------------------------------------------
    def runner(self, pipeline_id="fcp11-pipe", worker_ids=("w1",), root=None):
        specs = [rp.WorkerSpec(id=wid, worktree=PRIVATE_PATH, work_order=PRIVATE_PATH + "/wo.md",
                               checkpoint_policy="ON_SUCCESS", metadata={"note": SECRET}, worktree_top=PRIVATE_PATH)
                 for wid in worker_ids]
        manifest = rp.Manifest(pipeline_id=pipeline_id, workers=specs, sha256="b" * 64, raw={"secret": SECRET})
        runner = rp.PipelineRunner(manifest, root or self.root, self_worktree=Path(PRIVATE_PATH),
                                   clock=lambda: NOW, heartbeat_interval_seconds=None)
        runner._started_at = NOW
        runner._init_state()
        runner._save_pipeline()
        return runner

    @staticmethod
    def walk(runner, wid, *states, reason=None):
        for state in states:
            runner._transition(runner.workers[wid], state, reason)

    @staticmethod
    def finish(runner):
        runner._status = runner._overall_status()
        runner._ended_at = NOW
        runner._save_pipeline()

    # -- synthetic files ----------------------------------------------------
    def put(self, relative: str, payload) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8"))
        return path

    def synthetic(self, pid="fcp11-pipe", status="RUNNING", workers=(("w1", "RUNNING"),), record_status=None,
                  on_disk=None):
        entries = [{"id": wid, "state": state} for wid, state in workers]
        self.put(f"{pid}/pipeline_result.json", {"schema_version": 1, "pipeline_id": pid, "status": status,
                                                 "workers_total": len(entries), "workers": entries})
        self.put(f"{pid}/pipeline.json", {"schema_version": 1, "pipeline_id": pid,
                                          "status": record_status or status,
                                          "updated_at_utc": "2026-11-02T09:00:00+00:00"})
        for wid, state in (workers if on_disk is None else on_disk):
            self.put(f"{pid}/workers/{wid}/worker.json", {"schema_version": 1, "spec": {"id": wid}, "state": state,
                                                          "updated_at_utc": "2026-11-02T09:30:00+00:00"})

    def alias(self, target: Path, alias: Path) -> None:
        directory_alias(target, alias)
        self.addCleanup(lambda: os.path.lexists(alias) and remove_directory_alias(alias))

    def take(self, root=None, **kw) -> snap.ControlPlaneSnapshot:
        return snap.take_snapshot(str(root or self.root), AS_OF, **kw)

    @staticmethod
    def pipeline(snapshot, pid="fcp11-pipe") -> snap.PipelineSnapshot:
        return next(p for p in snapshot.pipelines if p.pipeline_id == pid)

    def worker(self, snapshot, wid="w1", pid="fcp11-pipe") -> snap.WorkerSnapshot:
        return next(w for w in self.pipeline(snapshot, pid).workers if w.worker_id == wid)

    @staticmethod
    def ref(snapshot, kind, pid="fcp11-pipe", wid=None) -> cp.EvidenceRef:
        return next(e for e in snapshot.observation.evidence
                    if (e.kind, e.pipeline_id, e.worker_id) == (kind, pid, wid))

    def assertUnknown(self, status, condition, cause):
        self.assertEqual((status.condition, status.cause, status.source_value), (condition, cause, None))
        self.assertEqual((status.lifecycle, status.runner_outcome), (cp.LIFECYCLE_UNKNOWN, cp.OUTCOME_UNKNOWN))


# ---------------------------------------------------------------------------
class RealRunnerSchemaTests(SnapshotTestBase):
    """Fixtures written by the Runner's own persistence code."""

    def test_running_pipeline_with_queued_and_active_workers(self):
        runner = self.runner(worker_ids=("w1", "w2"))
        self.walk(runner, "w1", W.READY, W.RUNNING)
        s = self.take()
        p = self.pipeline(s)
        self.assertEqual((p.view.status.source_value, p.view.status.lifecycle), ("RUNNING", cp.LIFECYCLE_ACTIVE))
        self.assertEqual(p.record_status.source_value, "RUNNING")
        self.assertEqual(p.agreement, snap.AGREEMENT_CONSISTENT)
        w1, w2 = self.worker(s, "w1"), self.worker(s, "w2")
        self.assertEqual((w1.listed_status.lifecycle, w1.record_status.source_value), (cp.LIFECYCLE_ACTIVE, "RUNNING"))
        self.assertEqual((w2.listed_status.lifecycle, w2.record_status.source_value), (cp.LIFECYCLE_QUEUED, "QUEUED"))
        for w in (w1, w2):
            self.assertEqual(w.agreement, snap.AGREEMENT_CONSISTENT)
            self.assertUnknown(w.result_status, cp.MISSING, cp.SOURCE_ABSENT)
            self.assertEqual(w.listed_status.runner_outcome, cp.OUTCOME_NONE)
        self.assertEqual(s.evidence_as_of_utc, "2026-11-02T10:00:00Z")
        self.assertEqual(self.ref(s, "WORKER_RESULT", wid="w1").condition, cp.MISSING)
        self.assertEqual(self.ref(s, "WORKER_RECORD", wid="w1").condition, cp.PRESENT)

    def test_waiting_worker_in_a_running_pipeline(self):
        runner = self.runner()
        self.walk(runner, "w1", W.READY, W.RUNNING)
        self.walk(runner, "w1", W.WAITING_PROVIDER_QUOTA, reason="PROVIDER_QUOTA_EXHAUSTED:" + SECRET)
        s = self.take()
        w = self.worker(s)
        self.assertEqual(self.pipeline(s).view.status.source_value, "RUNNING")
        self.assertEqual((w.listed_status.source_value, w.listed_status.lifecycle),
                         ("WAITING_PROVIDER_QUOTA", cp.LIFECYCLE_WAITING))
        self.assertEqual(self.pipeline(s).view.workers[0].state_reason, "PROVIDER_QUOTA_EXHAUSTED")
        self.assertEqual(w.agreement, snap.AGREEMENT_CONSISTENT)
        self.assertNotIn(SECRET, snap.canonical_json(s))

    def test_blocked_pipeline_is_a_runner_outcome_not_a_decision(self):
        runner = self.runner()
        self.walk(runner, "w1", W.BLOCKED, reason="DEPENDENCY_UNSATISFIED:w0")
        runner._write_result(runner.workers["w1"], {"outcome": "BLOCKED", "code": "X", "message": SECRET})
        self.finish(runner)
        s = self.take()
        p, w = self.pipeline(s), self.worker(s)
        self.assertEqual((p.view.status.lifecycle, p.view.status.runner_outcome), (cp.LIFECYCLE_TERMINAL, "BLOCKED"))
        self.assertEqual((w.result_status.source_value, w.agreement), ("BLOCKED", snap.AGREEMENT_CONSISTENT))
        self.assertEqual(w.result_written_at_utc, "2026-11-02T10:00:00Z")
        self.assertEqual(p.view.status.actor, cp.qr.ACTOR_NONE)

    def test_success_is_only_the_runner_record_never_a_closure(self):
        runner = self.runner()
        self.walk(runner, "w1", W.READY, W.RUNNING, W.SUCCESS)
        runner._write_result(runner.workers["w1"], {"outcome": "SUCCESS"})
        self.finish(runner)
        s = self.take()
        self.assertEqual(self.pipeline(s).view.status.runner_outcome, "SUCCESS")
        self.assertEqual(self.worker(s).agreement, snap.AGREEMENT_CONSISTENT)
        body = s.to_dict()
        for flag in ALL_FLAGS:
            self.assertIs(body[flag], False)
            self.assertIs(getattr(s, flag), False)
        self.assertEqual(body["marker"], cp.CONTROL_PLANE_MARKER)
        self.assertEqual(len(s.observation.evidence), 4)

    def test_operator_requeue_divergence_is_reported_not_resolved(self):
        # `_force_state` rewrites worker.json only: the Runner's own files
        # legitimately disagree until the next pipeline save.
        runner = self.runner()
        self.walk(runner, "w1", W.READY, W.RUNNING, W.FAILED)
        runner._write_result(runner.workers["w1"], {"outcome": "FAILED"})
        self.finish(runner)
        runner._force_state(runner.workers["w1"], W.QUEUED, "OPERATOR_RERUN")
        w = self.worker(self.take())
        self.assertEqual((w.listed_status.source_value, w.record_status.source_value, w.result_status.source_value),
                         ("FAILED", "QUEUED", "FAILED"))
        self.assertEqual(w.agreement, snap.AGREEMENT_DIVERGENT)

    def test_withheld_native_fields_never_reach_the_snapshot(self):
        runner = self.runner()
        self.walk(runner, "w1", W.READY, W.RUNNING, W.SUCCESS)
        runner.workers["w1"].attempts.append({"checkpoint": {"commit_hash": COMMIT}, "evidence_dir": PRIVATE_PATH})
        runner._write_result(runner.workers["w1"], {"outcome": "SUCCESS", "message": SECRET})
        self.finish(runner)
        text = snap.canonical_json(self.take())
        for leaked in (SECRET, PRIVATE_PATH, "client-data", str(self.root), self.root.name, "worker_path",
                       "result_path", "manifest_sha256", "orchestrator", "hostname"):
            self.assertNotIn(leaked, text)
        self.assertIn(COMMIT, text)  # an allowlisted, validated field

    def test_snapshot_is_read_only(self):
        runner = self.runner(worker_ids=("w1", "w2"))
        self.walk(runner, "w1", W.READY, W.RUNNING, W.SUCCESS)
        runner._write_result(runner.workers["w1"], {"outcome": "SUCCESS"})
        before = tree_state(self.root)
        dirs = sorted(str(p) for p in self.root.rglob("*") if p.is_dir())
        self.take()
        self.assertEqual(tree_state(self.root), before)
        self.assertEqual(sorted(str(p) for p in self.root.rglob("*") if p.is_dir()), dirs)


# ---------------------------------------------------------------------------
class AgreementTests(SnapshotTestBase):
    def test_pipeline_record_and_result_disagree(self):
        self.synthetic(status="RUNNING", record_status="SUCCESS")
        p = self.pipeline(self.take())
        self.assertEqual(p.agreement, snap.AGREEMENT_DIVERGENT)
        self.assertEqual(p.view.status.runner_outcome, cp.OUTCOME_NONE)

    def test_worker_record_disagrees_with_listing(self):
        self.synthetic(workers=(("w1", "RUNNING"),), on_disk=(("w1", "SUCCESS"),))
        self.assertEqual(self.worker(self.take()).agreement, snap.AGREEMENT_DIVERGENT)

    def test_stale_result_disagrees(self):
        self.synthetic(workers=(("w1", "RUNNING"),))
        self.put("fcp11-pipe/workers/w1/result.json", {"pipeline_id": "fcp11-pipe", "worker_id": "w1",
                                                       "state": "SUCCESS", "written_at_utc": "2026-11-01T00:00:00Z"})
        w = self.worker(self.take())
        self.assertEqual((w.agreement, w.result_status.source_value), (snap.AGREEMENT_DIVERGENT, "SUCCESS"))

    def test_worker_directory_not_listed(self):
        self.synthetic(workers=(("w1", "RUNNING"),), on_disk=(("w1", "RUNNING"), ("w9", "SUCCESS")))
        w = self.worker(self.take(), "w9")
        self.assertEqual((w.agreement, w.listed, w.on_disk), (snap.AGREEMENT_NOT_LISTED, False, True))
        self.assertUnknown(w.listed_status, cp.MISSING, cp.FIELD_ABSENT)

    def test_listed_worker_without_directory(self):
        self.synthetic(workers=(("w1", "RUNNING"), ("w2", "QUEUED")), on_disk=(("w1", "RUNNING"),))
        s = self.take()
        w = self.worker(s, "w2")
        self.assertEqual((w.agreement, w.on_disk, w.listed), (snap.AGREEMENT_NOT_ON_DISK, False, True))
        self.assertEqual(self.ref(s, "WORKER_RECORD", wid="w2").cause, cp.SOURCE_ABSENT)

    def test_workers_directory_absent(self):
        self.synthetic(workers=(("w1", "RUNNING"),), on_disk=())
        p = self.pipeline(self.take())
        self.assertEqual((p.workers_condition, p.workers_cause), (cp.MISSING, cp.SOURCE_ABSENT))
        self.assertEqual(p.workers[0].agreement, snap.AGREEMENT_NOT_ON_DISK)

    def test_missing_pipeline_result_makes_listing_unknown_not_unlisted(self):
        self.synthetic()
        (self.root / "fcp11-pipe" / "pipeline_result.json").unlink()
        s = self.take()
        p, w = self.pipeline(s), self.worker(s)
        self.assertUnknown(p.view.status, cp.MISSING, cp.SOURCE_ABSENT)
        self.assertEqual(p.agreement, snap.AGREEMENT_UNVERIFIABLE)
        self.assertEqual((w.listed, w.agreement), (None, snap.AGREEMENT_UNVERIFIABLE))
        self.assertEqual(w.record_status.source_value, "RUNNING")

    def test_rejected_entries_make_listing_unknown(self):
        self.synthetic(workers=(("w1", "RUNNING"),), on_disk=(("w1", "RUNNING"), ("w2", "RUNNING")))
        payload = json.loads((self.root / "fcp11-pipe" / "pipeline_result.json").read_bytes())
        payload["workers"].append({"id": "../w2", "state": "SUCCESS"})
        payload["workers_total"] = 2
        self.put("fcp11-pipe/pipeline_result.json", payload)
        w = self.worker(self.take(), "w2")
        self.assertEqual((w.listed, w.agreement), (None, snap.AGREEMENT_UNVERIFIABLE))

    def test_missing_results_are_never_success(self):
        self.synthetic(status="SUCCESS", workers=(("w1", "SUCCESS"),))
        w = self.worker(self.take())
        self.assertUnknown(w.result_status, cp.MISSING, cp.SOURCE_ABSENT)
        self.assertEqual(w.agreement, snap.AGREEMENT_CONSISTENT)  # listed + record agree; result unknown


# ---------------------------------------------------------------------------
class CorruptEvidenceTests(SnapshotTestBase):
    def corrupt(self, relative, data):
        self.synthetic(status="SUCCESS", workers=(("w1", "SUCCESS"),))
        self.put(relative, data)
        return self.take()

    def test_truncated_and_non_strict_json_is_corrupt(self):
        for data in (b'{"schema_version": 1, "pipeline_id": "fcp11-pi', b"", b"\xef\xbb\xbf{}", b'{"a":1,"a":2}',
                     b'{"a": NaN}', b"\xff\xfe", b'{"a": "\\ud800"}', b"1" * 40):
            with self.subTest(data=data[:20]):
                s = self.corrupt("fcp11-pipe/pipeline_result.json", data)
                ref = self.ref(s, "PIPELINE_RESULT")
                self.assertEqual((ref.condition, ref.cause, ref.content_sha256), (cp.CORRUPT, cp.SOURCE_NOT_JSON, None))
                p = self.pipeline(s)
                self.assertUnknown(p.view.status, cp.CORRUPT, cp.SOURCE_NOT_JSON)
                self.assertEqual(p.workers[0].listed, None)

    def test_corrupt_worker_record_and_result(self):
        s = self.corrupt("fcp11-pipe/workers/w1/worker.json", b'{"state": "SUCC')
        self.assertUnknown(self.worker(s).record_status, cp.CORRUPT, cp.SOURCE_NOT_JSON)
        self.assertEqual(self.worker(s).agreement, snap.AGREEMENT_UNVERIFIABLE)
        s = self.corrupt("fcp11-pipe/workers/w1/result.json", b"[")
        self.assertUnknown(self.worker(s).result_status, cp.CORRUPT, cp.SOURCE_NOT_JSON)

    def test_too_deep_is_unavailable(self):
        s = self.corrupt("fcp11-pipe/pipeline.json", b"[" * 40 + b"]" * 40)
        self.assertUnknown(self.pipeline(s).record_status, cp.UNAVAILABLE, cp.SOURCE_TOO_LARGE)

    def test_parsed_but_meaningless_files_are_present_refs_with_corrupt_status(self):
        cases = (
            ("fcp11-pipe/pipeline.json", {"schema_version": 2, "pipeline_id": "fcp11-pipe", "status": "SUCCESS"},
             "record", cp.SCHEMA_UNSUPPORTED),
            ("fcp11-pipe/pipeline.json", {"schema_version": True, "pipeline_id": "fcp11-pipe", "status": "SUCCESS"},
             "record", cp.SCHEMA_UNSUPPORTED),
            ("fcp11-pipe/pipeline.json", {"schema_version": 1, "pipeline_id": "other", "status": "SUCCESS"},
             "record", cp.IDENTITY_MISMATCH),
            ("fcp11-pipe/pipeline.json", ["SUCCESS"], "record", cp.SOURCE_NOT_JSON),
            ("fcp11-pipe/pipeline.json", {"schema_version": 1, "pipeline_id": "fcp11-pipe", "status": "DONE"},
             "record", cp.VALUE_UNRECOGNIZED),
            ("fcp11-pipe/pipeline.json", {"schema_version": 1, "pipeline_id": "fcp11-pipe"},
             "record", cp.FIELD_ABSENT),
            ("fcp11-pipe/workers/w1/worker.json", {"schema_version": 1, "spec": {"id": "W1"}, "state": "SUCCESS"},
             "worker", cp.IDENTITY_MISMATCH),
            ("fcp11-pipe/workers/w1/worker.json", {"schema_version": 1, "spec": "w1", "state": "SUCCESS"},
             "worker", cp.IDENTITY_MISMATCH),
            ("fcp11-pipe/workers/w1/result.json", {"pipeline_id": "other", "worker_id": "w1", "state": "SUCCESS"},
             "result", cp.IDENTITY_MISMATCH),
            ("fcp11-pipe/workers/w1/result.json", {"pipeline_id": "fcp11-pipe", "worker_id": "w1", "state": 1},
             "result", cp.VALUE_UNRECOGNIZED),
        )
        for relative, payload, which, cause in cases:
            with self.subTest(relative=relative, cause=cause):
                s = self.corrupt(relative, payload)
                status = {"record": lambda: self.pipeline(s).record_status,
                          "worker": lambda: self.worker(s).record_status,
                          "result": lambda: self.worker(s).result_status}[which]()
                self.assertUnknown(status, cp.CAUSE_CONDITION[cause], cause)
                kind = {"record": "PIPELINE_RECORD", "worker": "WORKER_RECORD", "result": "WORKER_RESULT"}[which]
                self.assertEqual(self.ref(s, kind, wid=None if which == "record" else "w1").condition, cp.PRESENT)

    def test_instants_only_from_files_whose_identity_held(self):
        s = self.corrupt("fcp11-pipe/workers/w1/worker.json",
                         {"schema_version": 1, "spec": {"id": "intruder"}, "state": "SUCCESS",
                          "updated_at_utc": "2099-01-01T00:00:00Z"})
        self.assertIsNone(self.worker(s).record_updated_at_utc)
        self.assertEqual(s.evidence_as_of_utc, "2026-11-02T09:00:00Z")

    def test_bad_instants_are_dropped_not_echoed(self):
        s = self.corrupt("fcp11-pipe/pipeline.json", {"schema_version": 1, "pipeline_id": "fcp11-pipe",
                                                      "status": "SUCCESS", "updated_at_utc": SECRET})
        self.assertIsNone(self.pipeline(s).record_updated_at_utc)
        self.assertNotIn(SECRET, snap.canonical_json(s))

    def test_payload_text_is_never_echoed(self):
        s = self.corrupt("fcp11-pipe/pipeline_result.json",
                         {"schema_version": 1, "pipeline_id": "fcp11-pipe", "status": SECRET,
                          "workers": [{"id": SECRET, "state": SECRET}]})
        self.assertNotIn(SECRET, snap.canonical_json(s))
        self.assertUnknown(self.pipeline(s).view.status, cp.CORRUPT, cp.VALUE_UNRECOGNIZED)


# ---------------------------------------------------------------------------
class PathSafetyTests(SnapshotTestBase):
    def assertRoot(self, root, condition, cause):
        s = snap.take_snapshot(root, AS_OF)
        self.assertEqual((s.root_condition, s.root_cause), (condition, cause))
        self.assertEqual((s.pipelines, s.observation.pipelines, s.observation.evidence), ((), (), ()))
        self.assertEqual(s.to_dict()["root_actor"], cp.CONDITION_ACTOR[condition])
        if isinstance(root, str) and len(root) > 8:
            self.assertNotIn(root, snap.canonical_json(s))

    def test_inadmissible_roots_are_refused(self):
        for root in ("relative/state", "state", "", "\\\\server\\share\\state", "//server/share", "file:///c:/x",
                     str(self.root / ".." / self.root.name), str(self.root) + "\x00", None, 7, b"C:\\x"):
            with self.subTest(root=root):
                self.assertRoot(root, cp.UNAVAILABLE, cp.PATH_REFUSED)
        if os.name == "nt":
            self.assertRoot(str(self.root) + ":stream", cp.UNAVAILABLE, cp.PATH_REFUSED)

    def test_absent_root_and_file_root(self):
        self.assertRoot(str(self.root / "absent"), cp.MISSING, cp.SOURCE_ABSENT)
        self.assertRoot(str(self.put("file.json", {})), cp.UNAVAILABLE, cp.SOURCE_UNREADABLE)

    def test_pathlike_root_is_accepted(self):
        self.synthetic()
        self.assertEqual(snap.take_snapshot(self.root, AS_OF).root_condition, cp.PRESENT)

    def test_root_through_an_alias_is_refused(self):
        real = self.root / "real"
        real.mkdir()
        self.alias(real, self.root / "alias")
        self.assertRoot(str(self.root / "alias"), cp.UNAVAILABLE, cp.LINK_REFUSED)
        (real / "inner").mkdir()
        self.assertRoot(str(self.root / "alias" / "inner"), cp.UNAVAILABLE, cp.LINK_REFUSED)
        if os.name == "nt":
            short = short_path(real / "inner")
            if os.path.normcase(short) != os.path.normcase(str(real / "inner")):
                self.assertRoot(short, cp.UNAVAILABLE, cp.LINK_REFUSED)

    def test_pipeline_directory_alias_is_shown_but_never_followed(self):
        outside = canonical_temp_dir("fcp11b02-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        self.synthetic(pid="decoy", status="SUCCESS", workers=(("w1", "SUCCESS"),))
        shutil.move(str(self.root / "decoy"), str(outside / "decoy"))
        self.alias(outside / "decoy", self.root / "decoy")
        with mock.patch.object(snap.qrep, "read_input_bytes", wraps=qrep.read_input_bytes) as reads:
            s = self.take()
        reads.assert_not_called()
        p = self.pipeline(s, "decoy")
        self.assertUnknown(p.view.status, cp.UNAVAILABLE, cp.LINK_REFUSED)
        self.assertUnknown(p.record_status, cp.UNAVAILABLE, cp.LINK_REFUSED)
        self.assertEqual((p.workers, p.workers_cause), ((), cp.LINK_REFUSED))
        self.assertEqual({e.cause for e in s.observation.evidence}, {cp.LINK_REFUSED})

    def test_worker_directory_and_workers_directory_aliases(self):
        outside = canonical_temp_dir("fcp11b02-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        self.synthetic(workers=(("w1", "RUNNING"), ("w2", "RUNNING")), on_disk=(("w1", "RUNNING"),))
        (outside / "w2").mkdir()
        (outside / "w2" / "worker.json").write_text(json.dumps({"schema_version": 1, "spec": {"id": "w2"},
                                                                "state": "SUCCESS"}))
        self.alias(outside / "w2", self.root / "fcp11-pipe" / "workers" / "w2")
        w = self.worker(self.take(), "w2")
        self.assertTrue(w.on_disk)
        self.assertUnknown(w.record_status, cp.UNAVAILABLE, cp.LINK_REFUSED)
        self.assertEqual(w.agreement, snap.AGREEMENT_UNVERIFIABLE)

        workers = self.root / "fcp11-pipe" / "workers"
        remove_directory_alias(workers / "w2")
        shutil.move(str(workers), str(outside / "workers"))
        self.alias(outside / "workers", workers)
        p = self.pipeline(self.take())
        self.assertEqual((p.workers_condition, p.workers_cause), (cp.UNAVAILABLE, cp.LINK_REFUSED))
        self.assertTrue(all(not w.on_disk for w in p.workers))

    def test_file_symlinks_are_refused(self):
        self.synthetic()
        target = self.root / "fcp11-pipe" / "pipeline.json"
        outside = canonical_temp_dir("fcp11b02-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        shutil.move(str(target), str(outside / "pipeline.json"))
        try:
            os.symlink(str(outside / "pipeline.json"), str(target))
        except OSError:  # unprivileged Windows: no file symlinks; junction cases cover links there
            self.assertEqual(os.name, "nt")
            return
        self.assertUnknown(self.pipeline(self.take()).record_status, cp.UNAVAILABLE, cp.LINK_REFUSED)

    def test_directory_swapped_for_a_junction_right_before_open_is_refused_unread(self):
        self.synthetic(status="SUCCESS", workers=(("w1", "SUCCESS"),))
        outside = canonical_temp_dir("fcp11b02-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        real_read, fired = qrep.read_input_bytes, []

        def swap_then_read(path):
            if not fired:
                fired.append(True)
                shutil.move(str(self.root / "fcp11-pipe"), str(outside / "fcp11-pipe"))
                self.alias(outside / "fcp11-pipe", self.root / "fcp11-pipe")
            return real_read(path)

        with mock.patch.object(snap.qrep, "read_input_bytes", side_effect=swap_then_read):
            s = self.take()
        self.assertEqual(self.ref(s, "PIPELINE_RESULT").cause, cp.LINK_REFUSED)
        self.assertUnknown(self.pipeline(s).view.status, cp.UNAVAILABLE, cp.LINK_REFUSED)

    def test_file_replaced_during_read_is_unavailable(self):
        self.synthetic(status="SUCCESS", workers=(("w1", "SUCCESS"),))
        real_read = qrep.read_input_bytes

        def read_then_replace(path):
            data = real_read(path)
            if path.endswith("pipeline_result.json"):
                tmp = path + ".tmp"
                Path(tmp).write_bytes(data + b" ")
                os.replace(tmp, path)
            return data

        with mock.patch.object(snap.qrep, "read_input_bytes", side_effect=read_then_replace):
            s = self.take()
        self.assertEqual(self.ref(s, "PIPELINE_RESULT").cause, cp.SOURCE_CHANGED_DURING_READ)
        self.assertUnknown(self.pipeline(s).view.status, cp.UNAVAILABLE, cp.SOURCE_CHANGED_DURING_READ)

    def test_unexpected_reader_failures_degrade_safely(self):
        self.synthetic()
        for error in (OSError("C:/secret/path denied"), ValueError(SECRET),
                      qrep.ReportError("REPORT_INTERNAL_ERROR")):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(snap.qrep, "read_input_bytes", side_effect=error):
                s = self.take()
                self.assertEqual({e.cause for e in s.observation.evidence if e.cause != cp.SOURCE_ABSENT},
                                 {cp.SOURCE_UNREADABLE})
                self.assertNotIn("secret", snap.canonical_json(s).lower())

    def test_malicious_names_are_ignored_never_echoed_or_opened(self):
        self.synthetic()
        # ("trailing." is not creatable on Windows; `valid_id` refuses it anyway.)
        for name in (".hidden", "has space", "x" * 65, "sk-abcdefghijkl", "\u00e9t\u00e9"):
            (self.root / name).mkdir()
            (self.root / name / "pipeline_result.json").write_text("{}")
        (self.root / "notes.json").write_text("{}")
        (self.root / rp.EVIDENCE_ROOT_DIRNAME).mkdir()
        (self.root / "fcp11-pipe" / "workers" / "bad name").mkdir()
        (self.root / "fcp11-pipe" / "workers" / "w-file").write_text("{}")
        s = self.take()
        self.assertEqual([p.pipeline_id for p in s.pipelines], ["fcp11-pipe"])
        self.assertEqual(s.ignored_entries, 7)
        self.assertEqual((self.pipeline(s).ignored_entries, [w.worker_id for w in self.pipeline(s).workers]),
                         (2, ["w1"]))
        text = snap.canonical_json(s)
        for name in ("hidden", "has space", "sk-abcdef", "notes", "_evidence", "bad name", "w-file"):
            self.assertNotIn(name, text)

    def test_listed_ids_never_become_paths(self):
        self.synthetic(on_disk=())
        payload = json.loads((self.root / "fcp11-pipe" / "pipeline_result.json").read_bytes())
        payload["workers"] = [{"id": i, "state": "SUCCESS"} for i in ("..", "../../etc", "C:\\x", "a/b", "CON")]
        payload["workers_total"] = 5
        self.put("fcp11-pipe/pipeline_result.json", payload)
        with mock.patch.object(snap.qrep, "read_input_bytes", wraps=qrep.read_input_bytes) as reads:
            p = self.pipeline(self.take())
        self.assertEqual((p.workers, p.view.rejected_workers), ((), 5))
        self.assertEqual(sorted(Path(c.args[0]).name for c in reads.call_args_list),
                         ["pipeline.json", "pipeline_result.json"])


# ---------------------------------------------------------------------------
class LimitTests(SnapshotTestBase):
    def test_pipeline_limit_is_deterministic(self):
        for pid in ("p-c", "p-a", "p-b"):
            self.synthetic(pid=pid)
        s = self.take(max_pipelines=2)
        self.assertEqual(([p.pipeline_id for p in s.pipelines], s.pipelines_omitted), (["p-a", "p-b"], 1))
        self.assertFalse(any(e.pipeline_id == "p-c" for e in s.observation.evidence))

    def test_worker_limit_is_deterministic_over_listing_and_disk(self):
        self.synthetic(workers=(("w3", "QUEUED"), ("w1", "QUEUED")), on_disk=(("w2", "QUEUED"), ("w1", "QUEUED")))
        with mock.patch.object(snap.qrep, "read_input_bytes", wraps=qrep.read_input_bytes) as reads:
            p = self.pipeline(self.take(max_workers=2))
        self.assertEqual(([w.worker_id for w in p.workers], p.workers_omitted), (["w1", "w2"], 1))
        self.assertFalse(any("w3" in c.args[0] for c in reads.call_args_list))
        self.assertEqual(len(p.view.workers), 2)  # the result projection itself is the contract's

    def test_file_byte_limit_refuses_before_reading(self):
        self.synthetic()
        with mock.patch.object(snap.qrep, "read_input_bytes", wraps=qrep.read_input_bytes) as reads:
            s = self.take(max_file_bytes=16)
        reads.assert_not_called()
        self.assertEqual({e.cause for e in s.observation.evidence if e.condition != cp.MISSING},
                         {cp.SOURCE_TOO_LARGE})
        self.put("fcp11-pipe/pipeline.json", b" " * (snap.MAX_FILE_BYTES + 1))
        self.assertUnknown(self.pipeline(self.take()).record_status, cp.UNAVAILABLE, cp.SOURCE_TOO_LARGE)

    def test_bytes_grown_past_the_limit_after_lstat_are_refused(self):
        self.synthetic()
        with mock.patch.object(snap.qrep, "read_input_bytes", return_value=b"{}" * 200):
            s = self.take(max_file_bytes=300)
        self.assertEqual({e.cause for e in s.observation.evidence if e.condition != cp.MISSING},
                         {cp.SOURCE_TOO_LARGE})

    def test_oversized_directories_are_refused_whole(self):
        self.synthetic()
        (self.root / "extra").mkdir()  # root: 2 entries; workers/: 4 entries
        for i in range(3):
            (self.root / "fcp11-pipe" / "workers" / f"x{i}").mkdir()
        with mock.patch.object(snap, "MAX_DIR_ENTRIES", 1):
            s = self.take()
        self.assertEqual((s.root_condition, s.root_cause, s.pipelines), (cp.UNAVAILABLE, cp.SOURCE_TOO_LARGE, ()))
        with mock.patch.object(snap, "MAX_DIR_ENTRIES", 3):
            p = self.pipeline(self.take())
        self.assertEqual((p.workers_condition, p.workers_cause), (cp.UNAVAILABLE, cp.SOURCE_TOO_LARGE))

    def test_invalid_limits_and_instants_raise(self):
        for kw in ({"max_pipelines": 0}, {"max_pipelines": cp.MAX_PIPELINES + 1}, {"max_pipelines": True},
                   {"max_workers": 0}, {"max_workers": cp.MAX_WORKERS + 1}, {"max_workers": 2.0},
                   {"max_file_bytes": 0}, {"max_file_bytes": snap.MAX_FILE_BYTES + 1},
                   {"max_pipelines": 64, "max_workers": 64}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.take(**kw)
        for instant in ("2026-11-02T12:00:00+00:00", "2026-11-02", None, "now"):
            with self.subTest(instant=instant), self.assertRaises(ValueError):
                snap.take_snapshot(str(self.root), instant)

    def test_default_limits_fit_the_contract(self):
        self.assertLessEqual(snap.DEFAULT_MAX_PIPELINES * (2 + 2 * snap.DEFAULT_MAX_WORKERS), cp.MAX_EVIDENCE_REFS)
        self.assertLessEqual(snap.MAX_FILE_BYTES, cp.MAX_EVIDENCE_BYTES)
        self.assertEqual(snap.MAX_FILE_BYTES, qrep.MAX_INPUT_BYTES)


# ---------------------------------------------------------------------------
class DeterminismTests(SnapshotTestBase):
    def build(self, root, order):
        for pid in order:
            runner = self.runner(pipeline_id=pid, worker_ids=("w2", "w1"), root=root)
            self.walk(runner, "w1", W.READY, W.RUNNING, W.SUCCESS)
            runner._write_result(runner.workers["w1"], {"outcome": "SUCCESS"})

    def test_equal_inputs_give_byte_equal_output_independent_of_creation_order(self):
        # Synthetic bytes: the Runner's own files embed a time-based run_id
        # (withheld from the output, but part of the hashed bytes).
        self.synthetic(pid="p-a", workers=(("w1", "SUCCESS"), ("w2", "QUEUED")))
        self.synthetic(pid="p-b", workers=(("w2", "QUEUED"), ("w1", "SUCCESS")))
        first, again = self.take(), self.take()
        for child in self.root.iterdir():
            shutil.rmtree(child)
        self.synthetic(pid="p-b", workers=(("w2", "QUEUED"), ("w1", "SUCCESS")))
        self.synthetic(pid="p-a", workers=(("w1", "SUCCESS"), ("w2", "QUEUED")))
        second = self.take()
        self.assertEqual(snap.canonical_json(first), snap.canonical_json(again))
        self.assertEqual(snap.canonical_json(first), snap.canonical_json(second))
        self.assertEqual(first.revision, json.loads(snap.canonical_json(first))["revision"])

    def test_snapshot_output_does_not_depend_on_the_root_spelling(self):
        other = canonical_temp_dir("fcp11b02-other-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.synthetic(pid="p-b")
        self.synthetic(pid="p-a")
        shutil.copytree(str(self.root / "p-a"), str(other / "p-a"))
        shutil.copytree(str(self.root / "p-b"), str(other / "p-b"))
        self.assertEqual(snap.canonical_json(self.take()), snap.canonical_json(self.take(root=other)))

    def test_any_material_change_changes_the_revision(self):
        self.build(self.root, ("p-a",))
        base = self.take()
        path = self.root / "p-a" / "workers" / "w2" / "worker.json"
        payload = json.loads(path.read_bytes())
        payload["attempts"] = [{"note": "withheld but hashed"}]
        path.write_text(json.dumps(payload))
        changed = self.take()
        self.assertNotEqual(base.revision, changed.revision)
        self.assertNotEqual(base.observation.revision, changed.observation.revision)
        self.assertNotEqual(snap.take_snapshot(str(self.root), "2026-11-02T12:00:01Z").revision, changed.revision)

    def test_canonical_json_is_ascii_sorted_and_compact(self):
        self.build(self.root, ("p-a",))
        text = snap.canonical_json(self.take())
        body = json.loads(text)
        self.assertEqual(text, json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        self.assertEqual(body["schema"], snap.SCHEMA)


# ---------------------------------------------------------------------------
class ViewInvariantTests(SnapshotTestBase):
    def status(self, value="RUNNING", kind=cp.SOURCE_WORKER_STATE):
        return cp.observe_status(kind, value)

    def absent(self):
        return snap._not_present(cp.SOURCE_WORKER_STATE, cp.SOURCE_ABSENT)

    def test_worker_snapshot_rejects_impossible_claims(self):
        ok = dict(pipeline_id="p", worker_id="w", on_disk=True, listed=True, listed_status=self.status(),
                  record_status=self.status(), result_status=self.absent())
        self.assertEqual(snap.WorkerSnapshot(**ok).agreement, snap.AGREEMENT_CONSISTENT)
        for bad in ({"worker_id": "../w"}, {"on_disk": 1}, {"listed": 1}, {"listed": 0.0}, {"listed": "yes"},
                    {"on_disk": False, "listed": False, "listed_status": self.absent()},
                    {"on_disk": False},  # no directory, yet a record
                    {"listed": False},  # unlisted, yet a listed status
                    {"record_status": self.status("RUNNING", cp.SOURCE_PIPELINE_STATUS)},
                    {"record_updated_at_utc": "2026-11-02T10:00:00+00:00"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                snap.WorkerSnapshot(**{**ok, **bad})

    def test_snapshot_must_match_its_observation(self):
        self.synthetic()
        s = self.take()
        with self.assertRaises(ValueError):
            snap.ControlPlaneSnapshot(s.observation, pipelines=())
        with self.assertRaises(ValueError):
            snap.ControlPlaneSnapshot(s.observation, root_condition=cp.MISSING, root_cause=cp.SOURCE_ABSENT,
                                      pipelines=s.pipelines)
        with self.assertRaises(ValueError):
            snap.ControlPlaneSnapshot(s.observation, root_condition=cp.MISSING, pipelines=s.pipelines)
        with self.assertRaises(TypeError):
            snap.canonical_json(s.to_dict())

    def test_agreement_is_derived_not_stored(self):
        self.synthetic()
        w = self.worker(self.take())
        with self.assertRaises(AttributeError):
            w.agreement = snap.AGREEMENT_CONSISTENT  # type: ignore[misc]
        self.assertNotIn("agreement", {f.name for f in snap.WorkerSnapshot.__dataclass_fields__.values()})


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
                         "fabric_director", "runner_factory_ledger", "tempfile"):
                self.assertNotIn(word, name.split("."), name)

    def test_module_calls_no_writing_clock_or_process_api(self):
        tree = self.tree()
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("environ", "getenv", "write_text", "write_bytes", "mkdir", "makedirs", "remove", "unlink",
                          "rename", "replace", "rmdir", "system", "popen", "Popen", "now", "utcnow", "sleep", "time",
                          "symlink", "chmod", "_atomic_write_json", "_transition", "_save_pipeline", "append_event"):
            self.assertNotIn(forbidden, names)
        self.assertNotIn("open", {n.func.id for n in ast.walk(tree)
                                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)})

    def test_contract_and_reader_are_reused_not_redefined(self):
        defined = {n.name for n in ast.walk(self.tree()) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for duplicated in ("read_input_bytes", "admit_path", "parse_document", "project_pipeline_result",
                           "observe_status", "classify", "valid_id", "normalized_utc", "StatusView", "EvidenceRef",
                           "PipelineView", "WorkerView", "same_physical_path", "evidence_root_key"):
            self.assertNotIn(duplicated, defined)
        self.assertIs(snap.cp, cp)
        self.assertIs(snap.qrep.read_input_bytes, qrep.read_input_bytes)

    def test_every_read_goes_through_the_fcp10_reader(self):
        root = canonical_temp_dir("fcp11b02-static-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "p" / "workers" / "w").mkdir(parents=True)
        for rel in ("p/pipeline.json", "p/pipeline_result.json", "p/workers/w/worker.json", "p/workers/w/result.json"):
            (root / rel).write_text("{}")
        with mock.patch.object(snap.qrep, "read_input_bytes", wraps=qrep.read_input_bytes) as reads:
            s = snap.take_snapshot(str(root), AS_OF)
        self.assertEqual(reads.call_count, 4)
        self.assertEqual(len([e for e in s.observation.evidence if e.condition == cp.PRESENT]), 4)
        for call in reads.call_args_list:
            self.assertTrue(os.path.normcase(call.args[0]).startswith(os.path.normcase(str(root)) + os.sep))


if __name__ == "__main__":
    unittest.main()
