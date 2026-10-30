"""FCP-9D-01: Director gateway with explicit Host authorization.

Unit tests build `DirectorDagHandle`s in memory from the blueprint compiler's
own plan helpers and dispatch to a fake Director that records every call, so
a refusal is proven to make ZERO mutating calls. The integration tests use the
real `FabricDirectorService` (`submit_blueprint` + `run_blueprint`) over
ephemeral `git init` repositories with the Director suite's fake executor; no
real provider, process, network or project worktree is touched. Nothing here
is skipped.
"""

from __future__ import annotations

import ast
import builtins
import dataclasses
import hashlib
import importlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_dag_blueprint as bp
from scripts.ai import fabric_director as fd
from scripts.ai import fabric_scheduler_contract as sc
from scripts.ai import fabric_scheduler_gateway as gw
from scripts.tests.test_fabric_director import _git
from scripts.tests.test_fabric_director_dag import DagTestBase, Recorder

MODULE_PATH = Path(gw.__file__)
RUN = "fdb-20261030t120000000000-abcdef12"
OTHER_RUN = "fdb-20261030t120000000000-00000000"
AS_OF = "2026-10-30T12:00:00Z"
LATER = "2026-10-30T12:05:00+00:00"
COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
WT_ROOT = "C:/fcp9d01-private/worktrees"
WO_ROOT = "C:/fcp9d01-private/work_orders"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "direction_approval",
             "human_approval")
MUTATING_METHODS = ("submit", "submit_blueprint", "run", "run_blueprint", "submit_and_run", "recover")


def _module_code() -> str:
    """The module without its docstring and comments."""
    code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


def worker_entry(wid, depends_on=(), **extra) -> dict:
    entry = {
        "id": wid, "worktree": f"{WT_ROOT}/{wid}", "work_order": f"{WO_ROOT}/{wid}.md", "provider": "opaque-a",
        "mode": "write", "depends_on": list(depends_on), "authorize_path": [f"scripts/ai/{wid}.py"],
        "checkpoint_policy": "ON_SUCCESS", "completion_policy": "runner_acceptance",
        "acceptance_commands": ["python -m unittest"], "max_attempts": 1,
    }
    entry.update(extra)
    return {k: v for k, v in entry.items() if v is not None}


def make_handle(run_id=RUN, workers=None, **pipeline) -> fd.DirectorDagHandle:
    """A handle exactly as `FabricDirectorService._dag_handle` shapes it, over
    a plan built and fingerprinted by the blueprint compiler's own helpers."""
    workers = workers if workers is not None else [worker_entry("w-00"), worker_entry("w-01", ("w-00",))]
    data = {"pipeline_id": run_id, "workers": workers, **pipeline}
    text = bp._canonical(data)
    nodes = tuple(
        bp.PlanNode(
            id=w["id"], provider=w["provider"], mode=w["mode"], depends_on=tuple(w["depends_on"]),
            dependency_policy=w.get("dependency_policy", "success"), priority=w.get("priority", 0),
            worktree_top=w["worktree"], work_order=w["work_order"], allow_shell=w.get("allow_shell", False),
        )
        for w in workers
    )
    draft = bp.BlueprintPlan(pipeline_id=run_id, nodes=nodes, manifest_json=text,
                             manifest_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), fingerprint="")
    plan = dataclasses.replace(draft, fingerprint=bp.plan_fingerprint(draft))
    director_dir = f"C:/fcp9d01-private/director/{run_id}"
    return fd.DirectorDagHandle(
        director_run_id=run_id, pipeline_id=run_id, blueprint_pipeline_id="bp-private",
        worker_ids=tuple(n.id for n in nodes), director_dir=director_dir,
        manifest_path=f"{director_dir}/manifest.json", plan_path=f"{director_dir}/dag_plan.json",
        provenance_path=f"{director_dir}/dag_provenance.json", state_root="C:/fcp9d01-private/state",
        manifest_sha256=plan.manifest_sha256, plan_fingerprint=plan.fingerprint, plan=plan,
    )


def bases(handle, commit=COMMIT_A) -> tuple:
    return tuple((wid, commit) for wid in handle.worker_ids)


def context(handle, as_of=AS_OF, **kw) -> gw.ReviewContext:
    kw.setdefault("base_commits", bases(handle))
    return gw.ReviewContext(as_of_utc=as_of, **kw)


def confirm(review, at=LATER, *, base_commits=None, **kw) -> gw.HostConfirmation:
    values = dict(review_fingerprint=review.review_fingerprint,
                  confirmation_token=gw.confirmation_token_for(review, at), confirmed_at_utc=at,
                  base_commits=base_commits if base_commits is not None else review.base_commits,
                  host_confirmed=True)
    values.update(kw)
    return gw.HostConfirmation(**values)


def summary_for(handle, aggregate="SUCCESS", **overrides) -> fd.DirectorDagRunSummary:
    values = dict(
        run_id=handle.pipeline_id, pipeline_id=handle.pipeline_id, blueprint_pipeline_id="bp-private",
        manifest_sha256=handle.manifest_sha256, plan_fingerprint=handle.plan_fingerprint, pipeline_status=aggregate,
        stop_reason="provider prose", workers=tuple(fd.DirectorDagWorkerSummary(worker_id=w, depends_on=())
                                                     for w in handle.worker_ids),
        aggregate_status=aggregate,
    )
    values.update(overrides)
    return fd.DirectorDagRunSummary(**values)


class FakeDirector:
    """Records every call; only `run_blueprint` has a programmed answer."""

    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer

    def _record(self, name, *args):
        self.calls.append((name, args))

    def run_blueprint(self, handle):
        self._record("run_blueprint", handle)
        answer = self.answer(handle) if callable(self.answer) else self.answer
        if isinstance(answer, BaseException):
            raise answer
        return answer if answer is not None else summary_for(handle)

    def submit(self, *a):
        self._record("submit", *a)

    def submit_blueprint(self, *a):
        self._record("submit_blueprint", *a)

    def run(self, *a):
        self._record("run", *a)

    def submit_and_run(self, *a):
        self._record("submit_and_run", *a)

    def recover(self, *a):
        self._record("recover", *a)

    def status(self, *a):
        self._record("status", *a)

    def result_blueprint(self, *a):
        self._record("result_blueprint", *a)


class GatewayTestBase(unittest.TestCase):
    def setUp(self):
        self.handle = make_handle()
        self.review = gw.preview(self.handle, context(self.handle))
        self.assertTrue(self.review.reviewed, self.review.reasons)

    def assertRefusedWithoutCalls(self, result, *codes, director=None):
        self.assertEqual(result.outcome, gw.REFUSED)
        self.assertFalse(result.dispatch_attempted)
        for code in codes:
            self.assertIn(code, result.reasons)
        if director is not None:
            self.assertEqual(director.calls, [])

    def changed(self, *codes, workers=None, review_handle=None, **pipeline):
        """Submit a different handle (same run id) than the one reviewed."""
        other = make_handle(workers=workers, **pipeline)
        director = FakeDirector()
        result = gw.submit(director, other, self.review, confirm(self.review))
        self.assertRefusedWithoutCalls(result, *codes, director=director)
        return result


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

class PreviewTests(GatewayTestBase):
    def test_valid_handle_is_reviewed_and_bound_to_the_manifest_digest(self):
        r = self.review
        self.assertEqual((r.outcome, r.reasons), (gw.REVIEWED, ()))
        self.assertEqual(r.run_id, RUN)
        self.assertEqual(r.manifest_sha256, self.handle.manifest_sha256)
        self.assertEqual(r.plan_fingerprint, self.handle.plan_fingerprint)
        self.assertEqual(r.worker_ids, ("w-00", "w-01"))
        self.assertEqual(r.review_date, "2026-10-30")
        self.assertEqual(tuple(g for g, _ in r.groups), gw.GROUPS)
        self.assertRegex(r.review_fingerprint, r"^[0-9a-f]{64}$")

    def test_review_never_authorizes_or_claims_approval(self):
        data = self.review.to_dict()
        for flag in ALL_FLAGS:
            self.assertIs(getattr(self.review, flag), False, flag)
            self.assertIs(data[flag], False, flag)
        self.assertEqual(data["marker"], gw.GATEWAY_MARKER)
        self.assertIn("BRANCH_GUARD", data["execution_time_guards_not_evaluated"])

    def test_preview_is_deterministic_across_equal_handles(self):
        again = gw.preview(make_handle(), context(make_handle()))
        self.assertEqual(gw.canonical_json(again), gw.canonical_json(self.review))
        self.assertEqual(again, self.review)

    def test_preview_performs_no_io_process_network_or_service_call(self):
        boom = mock.Mock(side_effect=AssertionError("I/O during preview"))
        with mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(socket, "socket", boom), mock.patch.object(os, "system", boom), \
                mock.patch.object(Path, "read_bytes", boom), mock.patch.object(Path, "exists", boom):
            review = gw.preview(self.handle, context(self.handle))
        self.assertTrue(review.reviewed)
        self.assertNotIn("service", gw.preview.__code__.co_varnames[:gw.preview.__code__.co_argcount])

    def test_preview_does_not_mutate_its_inputs(self):
        before = (dataclasses.astuple(self.handle), self.handle.plan.manifest_json)
        gw.preview(self.handle, context(self.handle))
        self.assertEqual((dataclasses.astuple(self.handle), self.handle.plan.manifest_json), before)

    def test_untyped_inputs_are_refused_and_echo_nothing(self):
        r = gw.preview({"pipeline_id": RUN}, {"as_of_utc": AS_OF})
        self.assertEqual(r.reasons, (gw.CONTEXT_NOT_TYPED, gw.HANDLE_NOT_TYPED))
        self.assertEqual((r.run_id, r.review_fingerprint, r.groups, r.worker_ids), (None, None, (), ()))
        for flag in ALL_FLAGS:
            self.assertIs(getattr(r, flag), False)

    def test_tampered_plan_is_unverified(self):
        plan = dataclasses.replace(self.handle.plan, fingerprint="0" * 64)
        r = gw.preview(dataclasses.replace(self.handle, plan=plan), context(self.handle))
        self.assertEqual(r.reasons, (gw.PLAN_UNVERIFIED,))

    def test_handle_disagreeing_with_its_plan_is_inconsistent(self):
        for field, value in (("manifest_sha256", "f" * 64), ("plan_fingerprint", "e" * 64),
                             ("worker_ids", ("w-01", "w-00")), ("director_run_id", OTHER_RUN)):
            with self.subTest(field=field):
                r = gw.preview(dataclasses.replace(self.handle, **{field: value}), context(self.handle))
                self.assertEqual(r.reasons, (gw.HANDLE_INCONSISTENT,))

    def test_non_director_run_id_is_refused(self):
        r = gw.preview(dataclasses.replace(self.handle, pipeline_id="../escape"), context(self.handle))
        self.assertEqual(r.reasons, (gw.RUN_ID_INVALID,))

    def test_base_commits_must_be_exact_and_cover_every_node(self):
        bad = (["w-00", COMMIT_A], (("w-00", COMMIT_A), ("w-00", COMMIT_B)), (("w-00", "HEAD"), ("w-01", COMMIT_A)),
               (("w-00", COMMIT_A.upper()), ("w-01", COMMIT_A)), (), None)
        for value in bad:
            with self.subTest(value=value):
                r = gw.preview(self.handle, context(self.handle, base_commits=value))
                self.assertIn(gw.BASE_MALFORMED, r.reasons)
        r = gw.preview(self.handle, context(self.handle, base_commits=(("w-00", COMMIT_A),)))
        self.assertEqual(r.reasons, (gw.BASE_COVERAGE_MISMATCH,))

    def test_as_of_must_be_a_strict_aware_instant(self):
        for value in ("2026-10-30T12:00:00", "yesterday", "", None, 1730289600):
            with self.subTest(value=value):
                self.assertIn(gw.AS_OF_INVALID, gw.preview(self.handle, context(self.handle, value)).reasons)

    def test_unsupported_context_schema_is_refused(self):
        r = gw.preview(self.handle, context(self.handle, schema_version=2))
        self.assertEqual(r.reasons, (gw.SCHEMA_VERSION_UNSUPPORTED,))

    def test_manifest_window_is_enforced_at_review(self):
        cases = ((dict(not_before_utc="2026-10-30T13:00:00Z"), gw.WINDOW_NOT_OPEN),
                 (dict(deadline_utc="2026-10-30T11:00:00Z"), gw.WINDOW_EXPIRED),
                 (dict(deadline_utc="2027-12-30T11:00:00Z"), gw.WINDOW_INVALID))
        for pipeline, code in cases:
            with self.subTest(code=code):
                handle = make_handle(**pipeline)
                self.assertEqual(gw.preview(handle, context(handle)).reasons, (code,))

    def test_fallback_resume_and_unknown_keys_are_refused(self):
        cases = ((dict(fallback_providers=["opaque-b"]), gw.FALLBACK_DECLARED),
                 (dict(resume_from="C:/fcp9d01-private/prior"), gw.RESUME_DECLARED),
                 (dict(metadata={"token": "x"}), gw.MANIFEST_KEY_UNSUPPORTED))
        for extra, code in cases:
            with self.subTest(code=code):
                handle = make_handle(workers=[worker_entry("w-00", **extra), worker_entry("w-01", ("w-00",))])
                self.assertEqual(gw.preview(handle, context(handle)).reasons, (code,))

    def test_permission_levels_are_derived_from_mode_and_shell(self):
        handle = make_handle(workers=[
            worker_entry("w-00", mode="read-only", checkpoint_policy=None, completion_policy=None,
                         acceptance_commands=None, authorize_path=None),
            worker_entry("w-01", ("w-00",)), worker_entry("w-02", ("w-01",), allow_shell=True),
        ])
        r = gw.preview(handle, context(handle))
        self.assertEqual(r.permission_levels, (("w-00", gw.PERMISSION_READ_ONLY), ("w-01", gw.PERMISSION_WRITE),
                                               ("w-02", gw.PERMISSION_WRITE_SHELL)))

    def test_review_echoes_no_path_work_order_or_command(self):
        text = gw.canonical_json(self.review)
        for leaked in (WT_ROOT, WO_ROOT, "C:/fcp9d01-private", "scripts/ai/w-00.py", "python -m unittest",
                       "bp-private"):
            self.assertNotIn(leaked, text)

    def test_hand_made_or_replaced_review_cannot_forge_its_fingerprint(self):
        with self.assertRaises(ValueError):
            dataclasses.replace(self.review, review_fingerprint="0" * 64)
        with self.assertRaises(ValueError):
            dataclasses.replace(self.review, groups=self.review.groups[:-1])
        with self.assertRaises(ValueError):
            dataclasses.replace(self.review, outcome=gw.REFUSED)
        with self.assertRaises(TypeError):
            gw.canonical_json(self.review.to_dict())

    def test_token_cannot_be_derived_for_a_refused_review(self):
        refused = gw.preview(None, None)
        with self.assertRaises(ValueError):
            gw.confirmation_token_for(refused, LATER)
        with self.assertRaises(ValueError):
            gw.confirmation_token_for(self.review, "not-a-date")


# ---------------------------------------------------------------------------
# Submit: refusals make zero Director calls
# ---------------------------------------------------------------------------

class SubmitRefusalTests(GatewayTestBase):
    def test_no_confirmation_means_zero_calls(self):
        director = FakeDirector()
        result = gw.submit(director, self.handle, self.review, None)
        self.assertRefusedWithoutCalls(result, gw.CONFIRMATION_MISSING, director=director)
        self.assertEqual(result.reasons, (gw.CONFIRMATION_MISSING,))

    def test_confirmation_must_be_typed(self):
        director = FakeDirector()
        as_dict = dataclasses.asdict(confirm(self.review))
        result = gw.submit(director, self.handle, self.review, as_dict)
        self.assertRefusedWithoutCalls(result, gw.CONFIRMATION_NOT_TYPED, director=director)

    def test_host_confirmation_must_be_literally_true(self):
        for value in (False, 1, "yes", None):
            with self.subTest(value=value):
                director = FakeDirector()
                result = gw.submit(director, self.handle, self.review, confirm(self.review, host_confirmed=value))
                self.assertRefusedWithoutCalls(result, gw.HOST_CONFIRMATION_NOT_EXPLICIT, director=director)

    def test_forged_or_rebound_token_is_refused(self):
        tokens = ("0" * 64, "", None, gw.confirmation_token_for(self.review, "2026-10-30T12:06:00Z"))
        for token in tokens:
            with self.subTest(token=token):
                director = FakeDirector()
                result = gw.submit(director, self.handle, self.review,
                                   confirm(self.review, confirmation_token=token))
                self.assertRefusedWithoutCalls(result, gw.CONFIRMATION_TOKEN_INVALID, director=director)

    def test_confirmation_of_another_review_is_refused(self):
        other_handle = make_handle(run_id=OTHER_RUN)
        other = gw.preview(other_handle, context(other_handle))
        director = FakeDirector()
        result = gw.submit(director, self.handle, self.review, confirm(other))
        self.assertRefusedWithoutCalls(result, gw.CONFIRMATION_REVIEW_MISMATCH, director=director)

    def test_untyped_service_handle_or_review_are_refused(self):
        class NoRunner:
            def submit_blueprint(self, *a):
                raise AssertionError("never called")

        director = FakeDirector()
        conf = confirm(self.review)
        self.assertRefusedWithoutCalls(gw.submit(NoRunner(), self.handle, self.review, conf), gw.SERVICE_UNSUPPORTED)
        self.assertRefusedWithoutCalls(gw.submit(director, dataclasses.asdict(self.handle), self.review, conf),
                                       gw.HANDLE_NOT_TYPED, director=director)
        self.assertRefusedWithoutCalls(gw.submit(director, self.handle, self.review.to_dict(), conf),
                                       gw.REVIEW_NOT_TYPED, director=director)
        refused = gw.preview(self.handle, context(self.handle, "bad"))
        self.assertRefusedWithoutCalls(gw.submit(director, self.handle, refused, conf),
                                       gw.REVIEW_NOT_REVIEWED, director=director)

    def test_review_age_bound_is_validated(self):
        for value in (0, gw.MAX_REVIEW_AGE_SECONDS + 1, True, 1.5, "900"):
            with self.subTest(value=value):
                director = FakeDirector()
                result = gw.submit(director, self.handle, self.review, confirm(self.review),
                                   max_review_age_seconds=value)
                self.assertRefusedWithoutCalls(result, gw.MAX_REVIEW_AGE_INVALID, director=director)

    def test_handle_tampered_after_review_is_refused_with_the_review_reasons(self):
        plan = dataclasses.replace(self.handle.plan, fingerprint="0" * 64)
        director = FakeDirector()
        result = gw.submit(director, dataclasses.replace(self.handle, plan=plan), self.review, confirm(self.review))
        self.assertRefusedWithoutCalls(result, gw.HANDLE_REFUSED, director=director)
        self.assertEqual(result.review_reasons, (gw.PLAN_UNVERIFIED,))

    def test_changed_worktree_is_refused(self):
        self.changed(gw.WORKTREE_CHANGED, gw.PLAN_CHANGED, workers=[
            worker_entry("w-00", worktree=f"{WT_ROOT}/elsewhere"), worker_entry("w-01", ("w-00",))])

    def test_changed_provider_is_refused(self):
        r = self.changed(gw.PROVIDER_CHANGED, workers=[
            worker_entry("w-00", provider="opaque-b"), worker_entry("w-01", ("w-00",))])
        self.assertNotIn(gw.MODE_CHANGED, r.reasons)

    def test_changed_mode_is_refused(self):
        self.changed(gw.MODE_CHANGED, gw.PERMISSION_CHANGED, workers=[
            worker_entry("w-00", mode="read-only"), worker_entry("w-01", ("w-00",))])

    def test_changed_scope_is_refused(self):
        r = self.changed(gw.SCOPE_CHANGED, workers=[
            worker_entry("w-00", authorize_path=["scripts/ai/w-00.py", "scripts/ai/runner_pipeline.py"]),
            worker_entry("w-01", ("w-00",))])
        self.assertNotIn(gw.PROVIDER_CHANGED, r.reasons)

    def test_changed_limit_is_refused(self):
        self.changed(gw.LIMIT_CHANGED, max_workers=4)
        self.changed(gw.LIMIT_CHANGED, workers=[worker_entry("w-00", max_attempts=3), worker_entry("w-01", ("w-00",))])

    def test_changed_permission_level_is_refused(self):
        self.changed(gw.PERMISSION_CHANGED, workers=[
            worker_entry("w-00", allow_shell=True), worker_entry("w-01", ("w-00",))])
        self.changed(gw.PERMISSION_CHANGED, workers=[
            worker_entry("w-00", completion_policy="provider_verdict"), worker_entry("w-01", ("w-00",))])

    def test_changed_plan_is_refused(self):
        r = self.changed(gw.PLAN_CHANGED, workers=[worker_entry("w-00"), worker_entry("w-01")])
        self.assertEqual(r.review_reasons, ())

    def test_changed_manifest_dates_are_refused(self):
        self.changed(gw.DATE_CHANGED, deadline_utc="2026-10-30T18:00:00Z")

    def test_changed_base_is_refused(self):
        director = FakeDirector()
        moved = (("w-00", COMMIT_B), ("w-01", COMMIT_A))
        result = gw.submit(director, self.handle, self.review, confirm(self.review, base_commits=moved))
        self.assertRefusedWithoutCalls(result, gw.BASE_CHANGED, director=director)
        result = gw.submit(director, self.handle, self.review, confirm(self.review, base_commits=(("w-00", "x"),)))
        self.assertRefusedWithoutCalls(result, gw.BASE_MALFORMED, director=director)

    def test_confirmation_on_another_utc_date_is_refused(self):
        late = gw.preview(self.handle, context(self.handle, "2026-10-30T23:58:00Z"))
        director = FakeDirector()
        result = gw.submit(director, self.handle, late, confirm(late, "2026-10-31T00:01:00Z"))
        self.assertRefusedWithoutCalls(result, gw.DATE_CHANGED, director=director)

    def test_confirmation_before_review_or_too_late_is_refused(self):
        director = FakeDirector()
        early = gw.submit(director, self.handle, self.review, confirm(self.review, "2026-10-30T11:59:59Z"))
        self.assertRefusedWithoutCalls(early, gw.CONFIRMED_BEFORE_REVIEW, director=director)
        stale = gw.submit(director, self.handle, self.review, confirm(self.review, "2026-10-30T12:15:01Z"))
        self.assertRefusedWithoutCalls(stale, gw.REVIEW_EXPIRED, director=director)
        bad = gw.submit(director, self.handle, self.review,
                        gw.HostConfirmation(self.review.review_fingerprint, "0" * 64, "soon", self.review.base_commits,
                                            True))
        self.assertRefusedWithoutCalls(bad, gw.CONFIRMED_AT_INVALID, director=director)

    def test_window_closing_between_review_and_confirmation_is_refused(self):
        handle = make_handle(deadline_utc="2026-10-30T12:03:00Z")
        review = gw.preview(handle, context(handle))
        self.assertTrue(review.reviewed)
        director = FakeDirector()
        result = gw.submit(director, handle, review, confirm(review))
        self.assertRefusedWithoutCalls(result, gw.WINDOW_EXPIRED, director=director)

    def test_refusal_result_is_fail_closed_and_serializable(self):
        result = gw.submit(FakeDirector(), self.handle, self.review, None)
        data = json.loads(gw.canonical_json(result))
        self.assertEqual((data["outcome"], data["dispatch_attempted"], data["runner_aggregate_status"]),
                         (gw.REFUSED, False, None))
        for flag in ALL_FLAGS:
            self.assertIs(getattr(result, flag), False)
        with self.assertRaises(ValueError):
            dataclasses.replace(result, dispatch_attempted=True)


# ---------------------------------------------------------------------------
# Submit: the one Director call
# ---------------------------------------------------------------------------

class SubmitDispatchTests(GatewayTestBase):
    def test_confirmed_submit_calls_run_blueprint_exactly_once_with_the_reviewed_handle(self):
        director = FakeDirector()
        result = gw.submit(director, self.handle, self.review, confirm(self.review))
        self.assertEqual(result.outcome, gw.DISPATCHED)
        self.assertEqual([name for name, _ in director.calls], ["run_blueprint"])
        self.assertIs(director.calls[0][1][0], self.handle)
        self.assertEqual((result.run_id, result.review_fingerprint, result.runner_aggregate_status),
                         (RUN, self.review.review_fingerprint, "SUCCESS"))
        self.assertTrue(result.dispatched)
        for flag in ALL_FLAGS:
            self.assertIs(getattr(result, flag), False)

    def test_director_refusal_echoes_only_its_code_and_is_never_retried(self):
        director = FakeDirector(fd.DirectorError("DAG_ALREADY_EXECUTED", f"state under {WT_ROOT}"))
        result = gw.submit(director, self.handle, self.review, confirm(self.review))
        self.assertEqual((result.outcome, result.reasons, result.director_error_code),
                         (gw.DIRECTOR_REFUSED, (gw.DIRECTOR_REFUSAL,), "DAG_ALREADY_EXECUTED"))
        self.assertEqual(len(director.calls), 1)
        self.assertNotIn(WT_ROOT, gw.canonical_json(result))

    def test_director_refusal_with_unrecognized_code_is_not_echoed(self):
        director = FakeDirector(fd.DirectorError("the provider says fine", "x"))
        result = gw.submit(director, self.handle, self.review, confirm(self.review))
        self.assertEqual(result.director_error_code, "UNRECOGNIZED")

    def test_unexpected_dispatch_failure_is_unknown_and_never_retried(self):
        director = FakeDirector(RuntimeError("boom"))
        result = gw.submit(director, self.handle, self.review, confirm(self.review))
        self.assertEqual((result.outcome, result.reasons), (gw.UNKNOWN, (gw.DISPATCH_RAISED,)))
        self.assertTrue(result.dispatch_attempted)
        self.assertEqual(len(director.calls), 1)

    def test_unbound_or_untyped_summary_is_unknown_never_success(self):
        cases = ((lambda h: {"aggregate_status": "SUCCESS"}, gw.SUMMARY_NOT_TYPED),
                 (lambda h: summary_for(h, manifest_sha256="c" * 64), gw.SUMMARY_MISMATCH),
                 (lambda h: summary_for(h, run_id=OTHER_RUN), gw.SUMMARY_MISMATCH),
                 (lambda h: summary_for(h, workers=()), gw.SUMMARY_MISMATCH))
        for answer, code in cases:
            with self.subTest(code=code):
                director = FakeDirector(answer)
                result = gw.submit(director, self.handle, self.review, confirm(self.review))
                self.assertEqual((result.outcome, result.reasons, result.runner_aggregate_status),
                                 (gw.UNKNOWN, (code,), None))
                self.assertFalse(result.dispatched)

    def test_aggregate_status_is_echoed_verbatim_or_as_unknown(self):
        for aggregate, expected in (("UNVERIFIED", "UNVERIFIED"), ("FAILED", "FAILED"), ("GREAT", "UNKNOWN")):
            with self.subTest(aggregate=aggregate):
                director = FakeDirector(lambda h: summary_for(h, aggregate=aggregate))
                result = gw.submit(director, self.handle, self.review, confirm(self.review))
                self.assertEqual((result.outcome, result.runner_aggregate_status), (gw.DISPATCHED, expected))

    def test_submit_result_invariants_cannot_be_forged(self):
        with self.assertRaises(ValueError):
            gw.SubmitResult(outcome=gw.DISPATCHED, reasons=(), run_id=RUN, review_fingerprint=None,
                            dispatch_attempted=True, runner_aggregate_status="SUCCESS")
        with self.assertRaises(ValueError):
            gw.SubmitResult(outcome=gw.REFUSED, reasons=(gw.CONFIRMATION_MISSING,), run_id=None,
                            review_fingerprint=None, dispatch_attempted=True)
        with self.assertRaises(ValueError):
            gw.SubmitResult(outcome=gw.REFUSED, reasons=(gw.DISPATCH_RAISED,), run_id=None,
                            review_fingerprint=None, dispatch_attempted=False)


# ---------------------------------------------------------------------------
# Authority boundary (source and import)
# ---------------------------------------------------------------------------

class AuthorityBoundaryTests(unittest.TestCase):
    def test_only_run_blueprint_is_ever_called_on_a_service(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and isinstance(n.func.value, ast.Name) and n.func.value.id == "service"}
        self.assertEqual(called, {"run_blueprint"})
        self.assertEqual(_module_code().count(".run_blueprint("), 1)

    def test_no_process_shell_network_filesystem_or_git_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertTrue(imported.isdisjoint({"os", "subprocess", "socket", "shutil", "pathlib", "urllib", "http",
                                             "threading", "multiprocessing", "concurrent", "asyncio", "time"}))
        code = _module_code()
        for word in ("submit_blueprint", "submit_and_run", "recover(", "_run_manifest", "merge(", "push",
                     "open(", "environ", "getenv", "datetime.now", "utcnow", "sleep", "Popen", "token_hex"):
            self.assertNotIn(word, code, word)

    def test_module_is_provider_neutral(self):
        code = _module_code().lower()
        for name in ("claude", "codex", "gemini", "openai", "anthropic"):
            self.assertNotIn(name, code)

    def test_import_has_no_side_effects(self):
        boom = mock.Mock(side_effect=AssertionError("side effect on import"))
        with mock.patch.object(subprocess, "Popen", boom), mock.patch.object(socket, "socket", boom), \
                mock.patch.object(fd.FabricDirectorService, "run_blueprint", boom), \
                mock.patch.object(fd.FabricDirectorService, "submit_blueprint", boom):
            # A private copy: the shared module object is never re-executed.
            spec = importlib.util.spec_from_file_location("fcp9d01_gateway_import_probe", MODULE_PATH)
            probe = importlib.util.module_from_spec(spec)
            with mock.patch.dict(sys.modules, {spec.name: probe}):
                spec.loader.exec_module(probe)
        self.assertEqual(probe.GROUPS, gw.GROUPS)
        boom.assert_not_called()

    def test_preview_makes_no_call_on_any_director(self):
        director = FakeDirector()
        handle = make_handle()
        gw.preview(handle, context(handle))
        self.assertEqual(director.calls, [])
        self.assertEqual(gw.preview.__code__.co_argcount, 2)

    def test_pinned_director_surface_and_shared_vocabulary(self):
        for name in ("run_blueprint", "submit_blueprint", "result_blueprint"):
            self.assertTrue(callable(getattr(fd.FabricDirectorService, name)))
        self.assertEqual(
            [f.name for f in dataclasses.fields(fd.DirectorDagHandle)],
            ["director_run_id", "pipeline_id", "blueprint_pipeline_id", "worker_ids", "director_dir",
             "manifest_path", "plan_path", "provenance_path", "state_root", "manifest_sha256",
             "plan_fingerprint", "plan"])
        self.assertEqual(sc.MODES, ("read-only", "write"))
        self.assertTrue(set(gw.GROUPS) == set(gw.CHANGE_CODES))
        self.assertEqual(len(gw.SUBMIT_REASONS), len(set(gw.SUBMIT_REASONS)))
        self.assertEqual(len(gw.REVIEW_REASONS), len(set(gw.REVIEW_REASONS)))


# ---------------------------------------------------------------------------
# Integration with the real Director (fake executor, ephemeral repos)
# ---------------------------------------------------------------------------

class RealDirectorIntegrationTests(DagTestBase):
    def submitted(self):
        executor = Recorder()
        svc = self.service(executor)
        handle = svc.submit_blueprint(self.blueprint([self.node("a"), self.node("b", depends_on=("a",))]))
        base = tuple(sorted((wid, _git(self.repos[wid], "rev-parse", "HEAD").stdout.strip())
                            for wid in handle.worker_ids))
        as_of = sc._utc_text(datetime.now(timezone.utc))
        review = gw.preview(handle, gw.ReviewContext(as_of_utc=as_of, base_commits=base))
        self.assertTrue(review.reviewed, review.reasons)
        return svc, executor, handle, review

    def test_confirmed_submit_dispatches_once_through_the_real_director(self):
        svc, executor, handle, review = self.submitted()
        result = gw.submit(svc, handle, review, confirm(review, review.as_of_utc))
        self.assertEqual(result.outcome, gw.DISPATCHED, result.reasons)
        self.assertEqual(result.summary.manifest_sha256, review.manifest_sha256)
        self.assertEqual(sorted(r.worker_id for r in executor.requests), ["a", "b"])
        self.assertIs(result.certified, False)

    def test_unconfirmed_submit_leaves_no_runner_state_and_starts_nothing(self):
        svc, executor, handle, review = self.submitted()
        with mock.patch.object(svc, "_run_manifest", wraps=svc._run_manifest) as helper:
            result = gw.submit(svc, handle, review, confirm(review, review.as_of_utc, host_confirmed=False))
        self.assertEqual(result.outcome, gw.REFUSED)
        helper.assert_not_called()
        self.assertEqual(executor.requests, [])
        self.assertFalse((self.state_root / handle.pipeline_id).exists())

    def test_second_submit_is_the_directors_refusal_and_never_retried(self):
        svc, executor, handle, review = self.submitted()
        conf = confirm(review, review.as_of_utc)
        self.assertEqual(gw.submit(svc, handle, review, conf).outcome, gw.DISPATCHED)
        started = len(executor.requests)
        again = gw.submit(svc, handle, review, conf)
        self.assertEqual((again.outcome, again.director_error_code), (gw.DIRECTOR_REFUSED, "DAG_ALREADY_EXECUTED"))
        self.assertEqual(len(executor.requests), started)


if __name__ == "__main__":
    unittest.main()
