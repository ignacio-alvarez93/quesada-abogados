"""FCP-11F-06: Fabric Control Plane human attention view and blocking priority.

State roots are private temporary directories spelled by their physical
path. `pipeline.json` / `pipeline_result.json` / `worker.json` / `result.json`
are written by the Runner's OWN persistence (FCP-11C-03 test fixtures: hand-
built `Manifest`, fixed clock, no executor, provider or Git); snapshots and
evidence are the real FCP-11B-02 / 11C-03 reads. FCP-6 advisories are the
real `assess_pipeline` / `advise_pipeline` over the bytes on disk, and C02
advice is the real `advise_recovery`. Every scenario is synthetic. Nothing is
executed, sent anywhere or skipped.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import unittest
from pathlib import Path

from scripts.ai import fabric_control_plane_attention as at
from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_control_plane_evidence as ev
from scripts.ai import fabric_control_plane_snapshot as snap
from scripts.ai import fabric_resource_quota_observation as qo
from scripts.ai import fabric_resource_quota_recovery as rq
from scripts.ai import runner_failure_intelligence as fi
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_recovery_advisory as ra
from scripts.tests import test_fabric_control_plane_evidence as evfx
from scripts.tests import test_fabric_resource_quota_recovery as c02fx
from scripts.tests.test_fabric_resource_quota_report import (
    canonical_temp_dir, directory_alias, remove_directory_alias,
)

MODULE_PATH = Path(at.__file__)
AS_OF = evfx.AS_OF  # 12:00; the Runner clock writes at 10:00
C02_AS_OF = "2026-11-02T11:00:00Z"
C02_SEEN = "2026-11-02T10:59:00Z"
PID = evfx.PID
SECRET = evfx.SECRET
PRIVATE_PATH = evfx.PRIVATE_PATH
ALL_FLAGS = evfx.ALL_FLAGS + ("action_executable", "recommendation_binding", "authorization_created")
FORBIDDEN_KEYS = {"action", "actions", "command", "commands", "next_step", "next_steps", "next_safe_step",
                  "next_safe_steps", "observation", "responsibility", "path", "evidence_dir", "message", "reason_text"}


def walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)
    else:
        yield node


class AttentionTestBase(evfx.EvidenceTestBase):
    def setUp(self):
        self.root = canonical_temp_dir("fcp11f06-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.runner = self.make_runner(("w1", "w2"))

    # -- Runner-native fixtures ---------------------------------------------
    def set_state(self, wid, state, attempts=None, result=True, reason=None, wait=None):
        rt = self.runner.workers[wid]
        rt.state, rt.state_reason, rt.provider_wait = state, reason, wait
        if attempts is not None:
            rt.attempts = list(attempts)
        if result:
            self.runner._write_result(rt, {"outcome": state, "message": SECRET})
        else:
            self.runner._save_worker(rt)
        self.runner._save_pipeline()

    def succeed(self, wid, leaf=evfx.LEAF1, **attempt_kw):
        directory = self.artifacts(self.current_dir(leaf, wid), wid=wid)
        attempt_kw.setdefault("process_confirmed_stopped", True)
        self.set_state(wid, "SUCCESS", [self.attempt(directory=directory, **attempt_kw)])

    def ended(self, wid, state, **attempt_kw):
        """A terminal non-success attempt that recorded no evidence directory."""
        fields = dict(work_status=state, checkpoint=None, evidence_complete=None, process_confirmed_stopped=True,
                      retry_decision="NO_RETRY:WORK_" + state)
        fields.update(attempt_kw)
        self.set_state(wid, state, [self.attempt(**fields)])

    def auth_blocked(self, wid):
        """The Runner's auth hold; its native reason carries provider prose."""
        attempt = self.attempt(checkpoint=None, work_status=None, evidence_complete=None)
        self.set_state(wid, "BLOCKED_PROVIDER_AUTH", [attempt], wait={"condition": "PROVIDER_AUTH_BLOCKED"},
                       reason="PROVIDER_AUTH_BLOCKED:" + SECRET)

    def finish(self):
        self.runner._status = self.runner._overall_status()
        self.runner._save_pipeline()

    def read(self, relative):
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    # -- projections --------------------------------------------------------
    def snapshot(self, root=None):
        return snap.take_snapshot(str(root or self.root), AS_OF)

    def evidence(self, snapshot):
        return ev.take_evidence(str(self.root), snapshot)

    def fcp6(self, pid=PID):
        """The real FCP-6A/6B reading of the bytes currently on disk."""
        pipeline_result = self.read(f"{pid}/pipeline_result.json")
        results = {}
        for entry in pipeline_result["workers"]:
            path = self.root / pid / "workers" / entry["id"] / "result.json"
            if path.exists():
                results[entry["id"]] = json.loads(path.read_text(encoding="utf-8"))
        return ra.advise_pipeline(fi.assess_pipeline(pipeline_result, results))

    def c02(self, wids=("w1",), as_of=C02_AS_OF, seen=C02_SEEN):
        """The real FCP-10C-02 advice over the bytes currently on disk."""
        summaries = {e["id"]: e for e in self.read(f"{PID}/pipeline_result.json")["workers"]}
        workers = []
        for wid in wids:
            result = self.read(f"{PID}/workers/{wid}/result.json")
            workers.append(rq.WorkerEvidence(
                worker_id=wid, provider_id="claude", result=result, summary=summaries[wid], pipeline_id=PID,
                diagnostic=fi.assess_worker(wid, result, pipeline_id=PID, summary=summaries[wid]),
                provider_verdict_text="VERDICT=PASS", auditor_verdict_text="VERDICT=PASS"))
        quota = qo.ObservationRequest(request_id="obs-1", as_of_utc=as_of,
                                      records=c02fx.available("claude", observed=seen))
        return rq.advise_recovery(rq.RecoveryRequest(request_id="rec-1", quota_request=quota, workers=tuple(workers)))

    def view(self, *, with_evidence=True, **kw):
        snapshot = self.snapshot()
        evidence = self.evidence(snapshot) if with_evidence else None
        return at.observe_attention(snapshot, evidence=evidence, **kw)

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def item(view, wid=None):
        return next(i for i in view.items if i.worker_id == wid)

    @staticmethod
    def reasons(item, source=None):
        return {c.reason for c in item.causes if source is None or c.source == source}

    @staticmethod
    def binding(view, source, pid=PID):
        return [b for s, p, b in view.bindings if s == source and p == pid]

    def assertZeroAuthority(self, view):
        for obj in (view,) + view.items + view.causes + tuple(c for i in view.items for c in i.causes):
            for flag in ALL_FLAGS:
                self.assertIs(getattr(obj, flag), False, flag)
        body = view.to_dict()
        for flag in ALL_FLAGS:
            self.assertIs(body[flag], False, flag)


# ---------------------------------------------------------------------------
class ClearTests(AttentionTestBase):
    def test_proven_success_is_clear_and_cites_current_evidence(self):
        self.succeed("w1")
        self.succeed("w2")
        self.finish()
        view = self.view()
        self.assertEqual(view.attention_class, at.CLEAR, [i.to_dict() for i in view.items if i.causes])
        body = view.to_dict()
        self.assertIsNone(body["primary"])
        self.assertEqual((body["actor"], body["origin"]), (rq.ACTOR_NONE, at.ORIGIN_NONE))
        self.assertEqual(body["class_counts"][at.CLEAR], 3)
        for wid in ("w1", "w2"):
            kinds = {k for k, _ in self.item(view, wid).evidence}
            self.assertTrue(set(at._WORKER_PROOF) <= kinds, kinds)
        self.assertEqual({k for k, _ in self.item(view).evidence}, set(at._PIPELINE_PROOF))
        self.assertEqual(self.binding(view, at.SOURCE_EVIDENCE, None), [at.BOUND])
        self.assertZeroAuthority(view)

    def test_bound_fcp6_and_c02_on_clean_success_stay_clear(self):
        self.succeed("w1")
        self.succeed("w2")
        self.finish()
        view = self.view(fcp6_advisories=[self.fcp6()], c02_advice={PID: self.c02(("w1", "w2"))})
        self.assertEqual(self.binding(view, at.SOURCE_FCP6), [at.BOUND])
        self.assertEqual(self.binding(view, at.SOURCE_C02), [at.BOUND])
        self.assertEqual(view.attention_class, at.CLEAR, [i.to_dict() for i in view.items if i.causes])


class SuccessWithoutEvidenceTests(AttentionTestBase):
    def test_success_without_evidence_projection_is_unknown(self):
        self.succeed("w1")
        self.succeed("w2")
        self.finish()
        view = self.view(with_evidence=False)
        self.assertEqual(view.attention_class, at.UNKNOWN)
        for wid in ("w1", "w2"):
            item = self.item(view, wid)
            self.assertEqual(item.primary_reason, at.SUCCESS_UNPROVEN)
            self.assertNotIn("ATTEMPT_RESULT", {k for k, _ in item.evidence})
        self.assertIn(at.SUCCESS_UNPROVEN, self.reasons(self.item(view)))
        self.assertEqual(self.binding(view, at.SOURCE_EVIDENCE, None), [at.ABSENT])

    def test_success_with_incomplete_or_missing_attempt_evidence_is_never_clear(self):
        self.succeed("w1", evidence_complete=False)
        self.set_state("w2", "SUCCESS", [])  # recorded SUCCESS, no attempt at all
        self.finish()
        view = self.view()
        w1, w2 = self.item(view, "w1"), self.item(view, "w2")
        self.assertEqual(w1.attention_class, at.EVIDENCE)
        self.assertIn(at.EVIDENCE_INCOMPLETE, self.reasons(w1, at.SOURCE_EVIDENCE))
        self.assertEqual(w2.attention_class, at.UNKNOWN)
        self.assertTrue({at.SUCCESS_UNPROVEN, at.STATUS_UNVERIFIABLE} <= self.reasons(w2))
        self.assertNotEqual(view.attention_class, at.CLEAR)

    def test_success_with_artifact_missing_or_anomaly_is_never_clear(self):
        directory = self.artifacts(self.current_dir(evfx.LEAF1, "w1"), wid="w1")
        (directory / "metadata.json").unlink()
        self.set_state("w1", "SUCCESS", [self.attempt(directory=directory)])
        other = self.artifacts(self.current_dir(evfx.LEAF1, "w2"), wid="w2")
        self.set_state("w2", "SUCCESS", [self.attempt(directory=other, checkpoint={"decision": 7})])
        self.finish()
        view = self.view()
        self.assertEqual(self.item(view, "w1").primary_reason, at.EVIDENCE_ANOMALY)  # unverified completeness claim
        self.assertEqual(self.item(view, "w2").primary_reason, at.EVIDENCE_ANOMALY)
        self.assertIn(ev.CHECKPOINT_MALFORMED, {c.source_code for c in self.item(view, "w2").causes})

    def test_terminal_state_without_result_is_evidence_missing(self):
        self.set_state("w1", "SUCCESS", [], result=False)
        self.set_state("w2", "RUNNING", [], result=False)
        view = self.view()
        self.assertIn(at.EVIDENCE_MISSING, self.reasons(self.item(view, "w1")))
        self.assertNotIn(at.EVIDENCE_MISSING, self.reasons(self.item(view, "w2")))
        self.assertEqual(self.item(view, "w2").primary_reason, at.IN_PROGRESS)

    def test_clear_item_cannot_be_constructed_without_its_proof(self):
        with self.assertRaises(ValueError):
            at.AttentionItem(PID, "w1", (), (("WORKER_RECORD", "a" * 64), ("WORKER_RESULT", "b" * 64)))
        with self.assertRaises(ValueError):
            at.AttentionItem(PID, None, (), (("PIPELINE_RESULT", "a" * 64),))
        with self.assertRaises(ValueError):
            at.ControlPlaneAttention("c" * 64, AS_OF)  # nothing observed is never CLEAR

    def test_empty_root_is_nothing_observed(self):
        empty = canonical_temp_dir("fcp11f06-empty-")
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        view = at.observe_attention(self.snapshot(empty))
        self.assertEqual(view.attention_class, at.UNKNOWN)
        self.assertEqual([c.reason for c in view.causes], [at.NOTHING_OBSERVED])


class WaitDoesNotHideFailureTests(AttentionTestBase):
    def test_stale_wait_record_beside_current_failed_result(self):
        self.ended("w1", "FAILED")
        rt = self.runner.workers["w1"]
        self.runner._force_state(rt, rp.WorkerState.WAITING_PROVIDER_QUOTA, "PROVIDER_QUOTA_EXHAUSTED")
        self.succeed("w2")
        view = self.view()
        w1 = self.item(view, "w1")
        codes = {(c.source, c.source_code, c.reason) for c in w1.causes}
        self.assertIn((at.SOURCE_SNAPSHOT, "FAILED", at.CURRENT_FAILED), codes)
        self.assertIn((at.SOURCE_SNAPSHOT, "WAITING_PROVIDER_QUOTA", at.PROVIDER_QUOTA_WAIT), codes)
        self.assertIn((at.SOURCE_SNAPSHOT, snap.AGREEMENT_DIVERGENT, at.STATUS_DIVERGENT), codes)
        self.assertEqual(w1.attention_class, at.EVIDENCE)
        self.assertLess(at._CLASS_RANK[w1.attention_class], at._CLASS_RANK[at.QUOTA])

    def test_old_fcp6_wait_advisory_is_stale_once_the_worker_failed(self):
        self.set_state("w1", "WAITING_PROVIDER_QUOTA", [self.attempt(retry_decision="WAIT:PROVIDER_QUOTA_EXHAUSTED",
                                                                     checkpoint=None, work_status=None)],
                       wait={"condition": "PROVIDER_QUOTA_EXHAUSTED", "next_eligible_utc": "2026-11-02T15:00:00Z"})
        self.succeed("w2")
        old = self.fcp6()
        self.assertIn("PROVIDER_QUOTA_WAIT", old.reasons)
        self.ended("w1", "FAILED")
        view = self.view(fcp6_advisories=(old,))
        self.assertEqual(self.binding(view, at.SOURCE_FCP6), [at.STALE])
        w1 = self.item(view, "w1")
        self.assertEqual(w1.attention_class, at.FAILURE)
        self.assertEqual(self.reasons(w1, at.SOURCE_FCP6), set())
        self.assertNotIn(at.PROVIDER_QUOTA_WAIT, self.reasons(w1))
        self.assertIn(at.ADVISORY_STALE, self.reasons(self.item(view)))
        self.assertEqual(view.to_dict()["primary"]["worker_id"], "w1")

    def test_old_c02_wait_advice_is_stale_once_the_worker_failed(self):
        self.set_state("w1", "WAITING_PROVIDER_QUOTA", [self.attempt(retry_decision="WAIT:PROVIDER_QUOTA_EXHAUSTED",
                                                                     checkpoint=None, work_status=None)],
                       wait={"condition": "PROVIDER_QUOTA_EXHAUSTED", "next_eligible_utc": "2026-11-02T15:00:00Z"})
        old = self.c02()
        self.assertEqual(old.worker("w1").status, rq.WAITING)
        self.ended("w1", "FAILED")
        view = self.view(c02_advice={PID: old})
        self.assertEqual(self.binding(view, at.SOURCE_C02), [at.STALE])
        self.assertEqual(self.item(view, "w1").attention_class, at.FAILURE)
        self.assertNotIn(at.PROVIDER_QUOTA_WAIT, self.reasons(self.item(view, "w1")))

    def test_failure_on_one_worker_outranks_quota_wait_on_another(self):
        self.set_state("w1", "WAITING_PROVIDER_QUOTA", [],
                       wait={"condition": "PROVIDER_QUOTA_EXHAUSTED", "next_eligible_utc": "2026-11-02T15:00:00Z"},
                       result=False)
        self.ended("w2", "FAILED")
        view = self.view()
        self.assertEqual(view.attention_class, at.FAILURE)
        order = [i.worker_id for i in view.items]
        self.assertLess(order.index("w2"), order.index("w1"))
        self.assertEqual(self.item(view, "w1").attention_class, at.QUOTA)
        self.assertEqual(view.to_dict()["primary"]["reason"], at.CURRENT_FAILED)


class CredentialTests(AttentionTestBase):
    def test_auth_block_is_human_with_provider_origin_and_outranks_quota(self):
        self.auth_blocked("w1")
        self.set_state("w2", "WAITING_PROVIDER_QUOTA", [],
                       wait={"condition": "PROVIDER_QUOTA_EXHAUSTED", "next_eligible_utc": "2026-11-02T15:00:00Z"},
                       result=False)
        view = self.view(fcp6_advisories=[self.fcp6()])
        w1 = self.item(view, "w1")
        self.assertEqual((w1.attention_class, w1.actor, w1.origin), (at.AUTH, rq.ACTOR_HUMAN, at.ORIGIN_PROVIDER))
        self.assertIn(at.PROVIDER_AUTH_BLOCKED, self.reasons(w1, at.SOURCE_FCP6))
        self.assertEqual(self.item(view, "w2").actor, rq.ACTOR_RUNNER)
        self.assertEqual(view.attention_class, at.AUTH)
        self.assertNotIn(SECRET, at.canonical_json(view))

    def test_failure_outranks_auth(self):
        self.set_state("w1", "BLOCKED_PROVIDER_AUTH", [], wait={"condition": "PROVIDER_AUTH_BLOCKED"}, result=False)
        self.ended("w2", "BLOCKED")
        view = self.view()
        self.assertEqual(view.attention_class, at.FAILURE)
        self.assertEqual(self.item(view, "w2").actor, rq.ACTOR_DIRECTION)


class StaleInformationTests(AttentionTestBase):
    def test_evidence_of_an_older_snapshot_is_not_bound(self):
        self.succeed("w1")
        self.succeed("w2")
        self.finish()
        old_evidence = self.evidence(self.snapshot())
        self.ended("w2", "FAILED")
        self.finish()
        view = at.observe_attention(self.snapshot(), evidence=old_evidence)
        self.assertEqual(self.binding(view, at.SOURCE_EVIDENCE, None), [at.NOT_BOUND])
        self.assertIn(at.SOURCE_NOT_BOUND, {c.reason for c in view.causes})
        self.assertIsNone(view.evidence_revision)
        self.assertEqual(self.item(view, "w1").primary_reason, at.SUCCESS_UNPROVEN)
        self.assertEqual(view.attention_class, at.FAILURE)

    def test_c02_advice_older_than_runner_write_or_after_observation_is_stale(self):
        self.succeed("w1")
        older = self.c02(as_of="2026-11-02T09:30:00Z", seen="2026-11-02T09:29:00Z")
        future = self.c02(as_of="2026-11-02T13:00:00Z", seen="2026-11-02T12:59:00Z")
        for advice in (older, future):
            view = self.view(c02_advice={PID: advice})
            self.assertEqual(self.binding(view, at.SOURCE_C02), [at.STALE])
            self.assertIn(at.ADVISORY_STALE, self.reasons(self.item(view)))

    def test_advisories_for_unknown_pipelines_are_not_bound(self):
        self.succeed("w1")
        advisory = self.fcp6()
        other = canonical_temp_dir("fcp11f06-other-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        (other / "other-pipe").mkdir()
        view = at.observe_attention(self.snapshot(other), fcp6_advisories=[advisory],
                                    c02_advice={PID: self.c02()})
        self.assertEqual(self.binding(view, at.SOURCE_FCP6), [at.NOT_BOUND])
        self.assertEqual(self.binding(view, at.SOURCE_C02), [at.NOT_BOUND])
        self.assertEqual({c.reason for c in view.causes}, {at.SOURCE_NOT_BOUND})

    def test_fcp6_with_a_different_worker_set_is_stale(self):
        self.succeed("w1")
        advisory = self.fcp6()
        self.runner = self.make_runner(("w1", "w2", "w3"))
        view = self.view(fcp6_advisories=[advisory])
        self.assertEqual(self.binding(view, at.SOURCE_FCP6), [at.STALE])


class RejectionTests(AttentionTestBase):
    def forged(self, name="PipelineRecoveryAdvisory", module="x.runner_recovery_advisory", **attrs):
        values = dict(pipeline_id=PID, native_status="RUNNING", reasons=("SUCCESS_CONSISTENT",), workers=(),
                      **{f: False for f in at.FCP6_FLAGS})
        values.update(attrs)
        kind = type(name, (), {})
        kind.__module__ = module
        obj = kind()
        for key, value in values.items():
            setattr(obj, key, value)
        return obj

    def test_untyped_flagged_duplicate_or_foreign_advice_is_rejected(self):
        self.ended("w1", "FAILED")
        cases = (
            [self.forged(certified=True)], [self.forged(name="Other")], [self.forged(module="evil")],
            [self.forged(reasons=("NOT_A_CODE",))], [self.forged(reasons=[])], [self.fcp6(), self.fcp6()],
        )
        for advisories in cases:
            view = self.view(fcp6_advisories=advisories)
            self.assertTrue(set(self.binding(view, at.SOURCE_FCP6)) == {at.REJECTED}, advisories)
            self.assertEqual(self.item(view, "w1").attention_class, at.FAILURE)
        view = self.view(fcp6_advisories=[{"pipeline_id": PID}, object()])
        self.assertEqual([b for s, p, b in view.bindings if s == at.SOURCE_FCP6], [at.REJECTED, at.REJECTED])
        self.assertIn(at.ADVISORY_REJECTED, {c.reason for c in view.causes})
        for advice in ({"outcome": "CLEAR"}, rq.advise_recovery(None)):
            view = self.view(c02_advice={PID: advice})
            self.assertEqual(self.binding(view, at.SOURCE_C02), [at.REJECTED])
        view = self.view(c02_advice={"../x": self.c02()})
        self.assertEqual([b for s, p, b in view.bindings if s == at.SOURCE_C02], [at.REJECTED])

    def test_forged_success_advisory_cannot_lower_a_current_failure(self):
        self.ended("w1", "FAILED")
        self.ended("w2", "FAILED")
        worker = lambda wid: self.forged("WorkerRecoveryAdvisory", worker_id=wid, native_state="FAILED")  # noqa
        forged = self.forged(native_status="RUNNING", workers=(worker("w1"), worker("w2")))
        view = self.view(fcp6_advisories=[forged])
        self.assertEqual(self.binding(view, at.SOURCE_FCP6), [at.BOUND])
        self.assertEqual(self.item(view, "w1").attention_class, at.FAILURE)
        self.assertEqual(view.attention_class, at.FAILURE)

    def test_caller_errors_raise(self):
        self.succeed("w1")
        snapshot = self.snapshot()
        with self.assertRaises(TypeError):
            at.observe_attention(snapshot.to_dict())
        with self.assertRaises(TypeError):
            at.observe_attention(snapshot, evidence=snapshot)
        with self.assertRaises(TypeError):
            at.observe_attention(snapshot, fcp6_advisories=self.fcp6())
        with self.assertRaises(TypeError):
            at.observe_attention(snapshot, c02_advice=[self.c02()])
        with self.assertRaises(TypeError):
            at.canonical_json(snapshot)


class FailClosedReadTests(AttentionTestBase):
    def test_missing_root_is_unknown(self):
        view = at.observe_attention(self.snapshot(self.root / "absent"))
        self.assertEqual(view.attention_class, at.UNKNOWN)
        self.assertEqual([(c.source_code, c.reason) for c in view.causes], [(cp.SOURCE_ABSENT, at.EVIDENCE_MISSING)])

    def test_linked_root_and_pipeline_are_safety(self):
        alias = self.root.parent / f"{self.root.name}-alias"
        directory_alias(self.root, alias)
        self.addCleanup(lambda: os.path.lexists(alias) and remove_directory_alias(alias))
        view = at.observe_attention(snap.take_snapshot(str(alias), AS_OF))
        self.assertEqual(view.attention_class, at.SAFETY)
        self.assertEqual(view.to_dict()["primary"]["reason"], at.EVIDENCE_PATH_REFUSED)
        self.assertNotIn(str(alias), at.canonical_json(view))

        target = canonical_temp_dir("fcp11f06-target-")
        self.addCleanup(shutil.rmtree, target, ignore_errors=True)
        link = self.root / "linked-pipe"
        directory_alias(target, link)
        self.addCleanup(lambda: os.path.lexists(link) and remove_directory_alias(link))
        view = at.observe_attention(self.snapshot())
        self.assertEqual(self.item(view).pipeline_id, "linked-pipe")
        self.assertEqual(view.items[0].attention_class, at.SAFETY)

    def test_corrupt_pipeline_result_and_worker_record_are_evidence(self):
        self.succeed("w1")
        (self.root / PID / "pipeline_result.json").write_text("{not json")
        (self.root / PID / "workers" / "w1" / "worker.json").write_text(json.dumps({"schema_version": 99}))
        view = self.view()
        self.assertEqual(self.item(view).attention_class, at.EVIDENCE)
        self.assertIn(at.EVIDENCE_CORRUPT, self.reasons(self.item(view, "w1")))
        self.assertEqual(view.attention_class, at.EVIDENCE)


class PriorityTests(AttentionTestBase):
    def test_reason_rules_follow_the_class_precedence(self):
        self.assertEqual(at.ATTENTION_CLASSES, (at.SAFETY, at.PROCESS, at.EVIDENCE, at.FAILURE, at.AUTH, at.QUOTA,
                                                at.WAITING, at.UNKNOWN, at.CLEAR))
        ranks = [at._CLASS_RANK[rule[1]] for rule in at.REASON_RULES]
        self.assertEqual(ranks, sorted(ranks))
        self.assertNotIn(at.CLEAR, {rule[1] for rule in at.REASON_RULES})
        for _, _, actor, origin in at.REASON_RULES:
            self.assertIn(actor, rq.ACTORS)
            self.assertIn(origin, at.ORIGINS)
        self.assertEqual({rule[2] for rule in at.REASON_RULES} - {rq.ACTOR_NONE},
                         {rq.ACTOR_HUMAN, rq.ACTOR_DIRECTION, rq.ACTOR_RUNNER})

    def test_items_are_totally_ordered_by_class_then_reason_then_ids(self):
        items = [at.AttentionItem("p", f"w{i:02d}", (at.AttentionCause(at.SOURCE_SNAPSHOT, "CODE", reason),))
                 for i, reason in enumerate(reversed(at.REASONS))]
        ordered = sorted(items, key=at.AttentionItem.sort_key)
        self.assertEqual([i.primary_reason for i in ordered], list(at.REASONS))
        view = at.ControlPlaneAttention("a" * 64, AS_OF, items=tuple(ordered))
        self.assertEqual(view.attention_class, at.SAFETY)
        with self.assertRaises(ValueError):
            at.ControlPlaneAttention("a" * 64, AS_OF, items=tuple(reversed(ordered)))

    def test_same_inputs_give_byte_equal_output_in_any_input_order(self):
        self.set_state("w1", "BLOCKED_PROVIDER_AUTH", [], wait={"condition": "PROVIDER_AUTH_BLOCKED"}, result=False)
        self.ended("w2", "FAILED")
        snapshot = self.snapshot()
        evidence = self.evidence(snapshot)
        advisories = [self.fcp6(), object()]
        first = at.observe_attention(snapshot, evidence=evidence, fcp6_advisories=advisories)
        second = at.observe_attention(snapshot, evidence=evidence, fcp6_advisories=list(reversed(advisories)))
        self.assertEqual(at.canonical_json(first), at.canonical_json(second))
        self.assertEqual(first.revision, json.loads(at.canonical_json(first))["revision"])
        self.ended("w2", "PARTIAL")
        self.assertNotEqual(at.observe_attention(self.snapshot()).revision, first.revision)

    def test_unknown_is_never_promoted(self):
        self.set_state("w1", "RUNNING", [], result=False)
        self.set_state("w2", "SUCCESS", [], result=False)
        view = self.view()
        values = set(walk(view.to_dict()))
        self.assertNotIn("READY_FOR_MERGE", values)
        self.assertNotEqual(self.item(view, "w2").attention_class, at.CLEAR)
        self.assertNotEqual(view.attention_class, at.CLEAR)


class TraceabilityAndExposureTests(AttentionTestBase):
    def test_every_cause_is_traced_to_its_source_code(self):
        self.set_state("w1", "INTERRUPTED", [self.attempt(work_status=None, checkpoint=None,
                                                          process_confirmed_stopped=False)])
        self.set_state("w2", "RETRY_WAIT", [], result=False)
        view = self.view(fcp6_advisories=[self.fcp6()])
        w1 = self.item(view, "w1")
        self.assertEqual(w1.attention_class, at.PROCESS)
        sources = {(c.source, c.source_code) for c in w1.causes}
        self.assertIn((at.SOURCE_SNAPSHOT, "INTERRUPTED"), sources)
        self.assertIn((at.SOURCE_FCP6, "PROCESS_TERMINATION_UNRESOLVED"), sources)
        for item in view.items:
            for cause in item.to_dict()["causes"]:
                self.assertEqual(set(cause), {"source", "source_code", "reason", "attention_class", "actor",
                                              "origin"})
                self.assertTrue(cp.valid_code(cause["source_code"]))
        self.assertEqual(self.item(view, "w2").primary_reason, at.RETRY_WAIT)

    def test_no_secret_path_provider_or_executable_action_is_exposed(self):
        self.auth_blocked("w1")
        self.succeed("w2")
        advice = self.c02(("w1", "w2"))
        self.assertIn(rq.RESTORE_PROVIDER_AUTH, {w.action for w in advice.workers})
        view = self.view(fcp6_advisories=[self.fcp6()], c02_advice={PID: advice})
        self.assertEqual(self.binding(view, at.SOURCE_C02), [at.BOUND])
        text = at.canonical_json(view)
        for needle in (SECRET, PRIVATE_PATH, str(self.root), "claude", "VERDICT", "\\\\", "sk-"):
            self.assertNotIn(needle, text)
        body = json.loads(text)
        self.assertFalse(FORBIDDEN_KEYS & set(_keys(body)))
        values = set(walk(body))
        self.assertFalse(values & set(rq.ACTIONS))
        self.assertFalse(values & {obs for _, obs in ra.CATEGORY_RULES.values()})
        self.assertZeroAuthority(view)


def _keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _keys(item)


class ContractPinningTests(unittest.TestCase):
    def test_vocabulary_mirrors_are_pinned_to_their_sources(self):
        self.assertEqual(set(at.FCP6_REASON), set(ra.ADVISORY_PRECEDENCE))
        self.assertEqual(set(at.FCP6_REASON) - set(fi.REASON_PRECEDENCE), set(at.FCP6_INTEGRITY_CODES))
        flags = {k for k in ra.PipelineRecoveryAdvisory._guarantees(None) if k != "marker"}
        self.assertEqual(set(at.FCP6_FLAGS), flags)
        self.assertEqual((ra.PipelineRecoveryAdvisory.__name__, ra.WorkerRecoveryAdvisory.__name__,
                          ra.__name__.rsplit(".", 1)[-1]),
                         (at.FCP6_PIPELINE_TYPE, at.FCP6_WORKER_TYPE, at.FCP6_MODULE))
        self.assertEqual(set(at.C02_REASON), set(rq.WORKER_REASONS))
        self.assertEqual(set(at.WORKER_STATE_REASON), set(cp.WORKER_STATES))
        self.assertEqual(set(at.PIPELINE_STATUS_REASON), set(cp.PIPELINE_STATUSES))
        self.assertEqual(set(at.AGREEMENT_REASON), set(snap.AGREEMENTS))
        for mapping in (at.FCP6_REASON, at.C02_REASON, at.WORKER_STATE_REASON, at.PIPELINE_STATUS_REASON,
                        at.AGREEMENT_REASON):
            self.assertTrue({v for v in mapping.values() if v is not None} <= set(at.REASONS))
        self.assertEqual(at.ACTORS, rq.ACTORS)

    def test_module_is_pure_and_never_imports_fcp6(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        names = {a.name.rsplit(".", 1)[-1] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                 for a in n.names}
        names |= {n.module.rsplit(".", 1)[-1] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse(names & {"runner_failure_intelligence", "runner_recovery_advisory"})
        self.assertFalse(names & {"os", "subprocess", "socket", "shutil", "pathlib", "time", "datetime",
                                  "fabric_director", "runner_factory_ledger", "random", "threading"})
        calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertFalse(calls & {"open", "exec", "eval", "__import__"})

    def test_constructors_reject_out_of_contract_values(self):
        for args in ((at.SOURCE_SNAPSHOT, "lower", at.CURRENT_FAILED), ("X", "CODE", at.CURRENT_FAILED),
                     (at.SOURCE_SNAPSHOT, "CODE", "NOT_A_REASON"),
                     (at.SOURCE_SNAPSHOT, "TOKEN_" + "A1B2" * 10, at.CURRENT_FAILED)):
            with self.assertRaises(ValueError, msg=args):
                at.AttentionCause(*args)
        cause = at.AttentionCause(at.SOURCE_SNAPSHOT, "FAILED", at.CURRENT_FAILED)
        with self.assertRaises(ValueError):
            at.AttentionItem("../x", None, (cause,))
        with self.assertRaises(ValueError):
            at.AttentionItem("p", None, (cause, cause))
        with self.assertRaises(ValueError):
            at.ControlPlaneAttention("a" * 64, "2026-11-02T12:00:00+01:00", causes=(cause,))
        with self.assertRaises(ValueError):
            at.ControlPlaneAttention("a" * 64, AS_OF, bindings=(("X", None, at.BOUND),), causes=(cause,))


if __name__ == "__main__":
    unittest.main()
