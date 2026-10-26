"""FCP-4E-02a: retirement PROPOSAL contracts (non-live, pure).

Every input is a synthetic in-memory dataclass under a path root that does
not exist; nothing here runs Git, reads a repository or touches a real
worktree. Records and assessments are produced by the REAL pure
classifiers (`classify_record`, `classify_retirement`), so every positive
fixture is exactly what FCP-4C/4D would emit for those facts - no fail-
closed mapping is weakened to obtain a CANDIDATE. Each refusal is paired
with the positive control `test_positive_fixture_is_a_non_authorizing_proposal`.
"""

import ast
import builtins
import copy
import dataclasses
import json
import os
import pathlib
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_multiworker as mw
from scripts.ai import runner_worktree_inventory as inv
from scripts.ai import runner_worktree_retirement as wr
from scripts.ai import runner_worktree_retirement_authorization as wra

MODULE_PATH = Path(wra.__file__)
WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "fabric-ci.yml"

ROOT = os.path.normcase(os.path.abspath(os.path.join(os.sep, "fcp4e02a-synthetic-nonexistent")))
REPO = os.path.join(ROOT, "repo")
COMMON = os.path.join(REPO, ".git")
WT = os.path.join(ROOT, "wt-feature")
GIT_DIR = os.path.join(COMMON, "worktrees", "wt-feature")
STATE = os.path.join(ROOT, "runtime", "state")
LEDGER = os.path.join(ROOT, "runtime", "ledger")
QUEUE = os.path.join(ROOT, "runtime", "queue")
GOVERNED = os.path.join(ROOT, "governed")
SHA = "a" * 40
BRANCH = "refs/heads/feature/fcp4e02a"
HOST = "host-01"


def make_record(**changes):
    fields = dict(
        path=WT, worktree_key=WT, registered=True, path_exists=True, listed_head=SHA, listed_branch=BRANCH,
        worktree_top=WT, git_dir=GIT_DIR, common_dir=COMMON, object_format="sha1", head_ref=BRANCH,
        head_sha=SHA, detached=False, protected_branch=False, clean=True,
        lease_dir=os.path.join(GIT_DIR, "runner-write-lease"), lease_state=inv.LEASE_NOT_CREATED,
        runner_state_readable=True,
    )
    fields.update(changes)
    return inv.classify_record(inv.WorktreeRecord(**fields))


def make_facts(record, **changes):
    fields = dict(
        worktree_key=record.worktree_key, path=record.path,
        first_inventory_status=inv.INVENTORY_COMPLETE, second_inventory_status=inv.INVENTORY_COMPLETE,
        in_first_inventory=True, in_second_inventory=True,
        inventory_classification=record.classification, second_inventory_classification=record.classification,
        inventory_reason_codes=record.reason_codes, inventory_advisories=record.advisories,
        inventory_lease_state=record.lease_state,
        first_record_fingerprint=record.fingerprint, second_record_fingerprint=record.fingerprint,
        self_worktree_known=True, governed_roots_resolved=True,
        supplemental_checked=True, ignored_count=0, paused_probe_ok=True, index_flags_proven=True,
        head_ref_consistent=True, topology_proven=True, local_only_commits=0, unique_commits=0,
        queue_roots_declared=True, queue_roots_complete_claim=True,
    )
    fields.update(changes)
    return wr.RetirementFacts(**fields)


def make_report(records, counts=None, **changes):
    fields = dict(
        schema=wr.SCHEMA, status=wr.REPORT_COMPLETE, requested_path=REPO, repository_top=REPO, common_dir=COMMON,
        state_root=STATE, ledger_root=LEDGER, lease_root=None, queue_roots=(QUEUE,),
        queue_roots_complete_claim=True, self_worktree=REPO, governed_roots=(GOVERNED,),
        first_inventory_status=inv.INVENTORY_COMPLETE, second_inventory_status=inv.INVENTORY_COMPLETE,
        first_inventory_fingerprint="f" * 64, second_inventory_fingerprint="f" * 64,
        global_errors=(), records=tuple(records), fingerprint="9" * 64,
    )
    fields.update(changes)
    fields["counts"] = wr._counts(fields["records"]) if counts is None else counts
    return wr.RetirementReport(**fields)


def main_assessment():
    return wr.classify_retirement(wr.RetirementFacts(worktree_key=REPO, path=REPO))


def fixture(record_changes=None, facts_changes=None, **report_changes):
    """(report, record): a consistent synthetic report whose only
    non-main record is the given record's real assessment."""
    record = make_record(**(record_changes or {}))
    assessment = wr.classify_retirement(make_facts(record, **(facts_changes or {})))
    return make_report((main_assessment(), assessment), **report_changes), record


def candidate(report):
    return next(r for r in report.records if r.worktree_key == WT)


def forge(obj, **changes):
    """A copy with fields overwritten WITHOUT recomputing any digest."""
    clone = copy.copy(obj)
    for name, value in changes.items():
        object.__setattr__(clone, name, value)
    return clone


class ProposalTestCase(unittest.TestCase):
    def build(self, report, record, host_id=HOST):
        return wra.build_retirement_proposal(report, record, host_id=host_id)

    def assertRefused(self, code, report, record, host_id=HOST):
        with self.assertRaises(wra.RetirementProposalRefused) as ctx:
            self.build(report, record, host_id)
        self.assertEqual(ctx.exception.code, code, ctx.exception.detail)
        self.assertIn(code, wra.REFUSAL_CODES)
        return ctx.exception


class PositiveProposalTests(ProposalTestCase):
    def test_positive_fixture_is_a_non_authorizing_proposal(self):
        report, record = fixture()
        self.assertEqual(candidate(report).classification, wr.CANDIDATE_FOR_HUMAN_REVIEW)
        self.assertEqual(record.classification, inv.IDLE_CLEAN_UNBOUND)
        p = self.build(report, record)
        self.assertIs(type(p), wra.RetirementProposal)
        self.assertEqual((p.human_review_required, p.authorizes_action, p.deletion_authorized,
                          p.human_command_present, p.issued, p.host_identity_authenticated,
                          p.queue_scope_attested), (True, False, False, False, False, False, False))
        self.assertEqual(p.schema, wra.PROPOSAL_SCHEMA)
        self.assertEqual(p.assessment_classification, wr.CANDIDATE_FOR_HUMAN_REVIEW)
        self.assertEqual(p.limitations, wr.LIMITATIONS)
        self.assertEqual(p.advisories, candidate(report).advisories)
        self.assertEqual(p.advisories, ("NO_LOCAL_ONLY_COMMITS_IS_NOT_REMOTE_PROOF",))
        self.assertEqual(p.proposal_limitations, wra.PROPOSAL_LIMITATIONS)
        self.assertEqual(p.report_fingerprint, report.fingerprint)
        self.assertEqual(wra.validate_proposal_against_report(p, report, record), ())

    def test_target_identity_is_the_inventory_record_identity(self):
        report, record = fixture()
        t = self.build(report, record).target
        self.assertEqual(t.schema, wra.TARGET_SCHEMA)
        self.assertEqual((t.worktree_key, t.path, t.worktree_top, t.git_dir, t.common_dir, t.head_ref, t.head_sha,
                          t.listed_branch, t.listed_head, t.object_format),
                         (record.worktree_key, record.path, record.worktree_top, record.git_dir, record.common_dir,
                          record.head_ref, record.head_sha, record.listed_branch, record.listed_head,
                          record.object_format))
        self.assertEqual(t.admin_entry, "wt-feature")
        self.assertEqual(t.inventory_record_fingerprint, record.fingerprint)
        self.assertEqual(t.assessment_fingerprint, candidate(report).fingerprint)
        self.assertEqual(t.host_id_label, HOST)
        self.assertIsNone(t.file_object_id)
        self.assertIs(t.file_object_id_verified, False)
        self.assertIs(t.host_identity_authenticated, False)

    def test_scope_is_canonical_sorted_and_claim_unverified(self):
        q2 = os.path.join(ROOT, "runtime", "queue-b")
        report, record = fixture(queue_roots=(q2, QUEUE))
        s = self.build(report, record).scope
        self.assertEqual(s.schema, wra.SCOPE_SCHEMA)
        self.assertEqual(s.queue_roots, tuple(sorted((QUEUE, q2))))
        self.assertEqual((s.requested_path, s.repository_top, s.common_dir, s.state_root, s.ledger_root,
                          s.lease_root, s.self_worktree, s.governed_roots),
                         (REPO, REPO, COMMON, STATE, LEDGER, None, REPO, (GOVERNED,)))
        self.assertIs(s.queue_roots_complete_claim, True)
        self.assertIs(s.queue_roots_complete_claim_verified, False)
        self.assertIs(s.queue_scope_attested, False)
        reordered, _ = fixture(queue_roots=(QUEUE, q2))
        self.assertEqual(self.build(reordered, record).scope, s)

    def test_digests_are_deterministic_and_cover_every_material_field(self):
        report, record = fixture()
        a, b = self.build(report, record), self.build(report, record)
        self.assertEqual(a, b)
        for digest in (a.proposal_digest, a.target.identity_digest, a.scope.scope_digest, a.report_content_digest):
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(a.proposal_digest, wra.proposal_digest(a))
        self.assertEqual(a.scope.scope_digest, wra.scope_digest(a.scope))
        self.assertEqual(a.target.identity_digest, wra.identity_digest(a.target))
        other_host = self.build(report, record, host_id="host-02")
        self.assertNotEqual(other_host.target.identity_digest, a.target.identity_digest)
        self.assertNotEqual(other_host.proposal_digest, a.proposal_digest)
        for change in ({"requested_path": os.path.join(REPO, "sub")}, {"lease_root": os.path.join(ROOT, "lease")},
                       {"governed_roots": ()}, {"fingerprint": "8" * 64}):
            changed, _ = fixture(**change)
            p = self.build(changed, record)
            self.assertNotEqual(p.proposal_digest, a.proposal_digest, change)
        for name in ("requested_path", "repository_top", "common_dir"):
            forged = forge(a.scope, **{name: os.path.join(ROOT, "x")})
            self.assertNotEqual(wra.scope_digest(forged), a.scope.scope_digest, name)
        for f in dataclasses.fields(a.target):
            if f.name != "identity_digest" and isinstance(getattr(a.target, f.name), str):
                forged = forge(a.target, **{f.name: getattr(a.target, f.name) + "x"})
                self.assertNotEqual(wra.identity_digest(forged), a.target.identity_digest, f.name)

    def test_schemas_are_frozen_and_flags_are_not_constructor_arguments(self):
        report, record = fixture()
        p = self.build(report, record)
        for cls in (wra.RetirementTargetIdentity, wra.RetirementScope, wra.RetirementProposal):
            self.assertTrue(cls.__dataclass_params__.frozen, cls.__name__)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.authorizes_action = True
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.scope.queue_scope_attested = True
        with self.assertRaises(ValueError):
            dataclasses.replace(p, authorizes_action=True)
        with self.assertRaises(ValueError):
            dataclasses.replace(p.target, host_identity_authenticated=True)
        with self.assertRaises(TypeError):
            wra.RetirementProposal(**{f.name: getattr(p, f.name) for f in dataclasses.fields(p) if f.init},
                                   issued=True)
        flags = {f.name for cls in (wra.RetirementTargetIdentity, wra.RetirementScope, wra.RetirementProposal)
                 for f in dataclasses.fields(cls) if not f.init}
        self.assertEqual(flags, {"file_object_id", "file_object_id_verified", "host_identity_authenticated",
                                 "queue_roots_complete_claim_verified", "queue_scope_attested",
                                 "human_review_required", "authorizes_action", "deletion_authorized",
                                 "human_command_present", "issued"})

    def test_no_capability_fields_or_live_flags(self):
        self.assertIs(wra.RETIREMENT_AUTHORIZATION_LIVE, False)
        self.assertIs(wra.RETIREMENT_EXECUTION_CAPABLE, False)
        banned = ("eligib", "permit", "token", "approv", "execut", "signature", "secret", "credential", "nonce",
                  "timestamp", "expires", "trusted")
        for cls in (wra.RetirementTargetIdentity, wra.RetirementScope, wra.RetirementProposal):
            for f in dataclasses.fields(cls):
                for word in banned:
                    self.assertNotIn(word, f.name, (cls.__name__, f.name))
        public = [n for n in dir(wra) if not n.startswith("_") and callable(getattr(wra, n))
                  and getattr(getattr(wra, n), "__module__", None) == wra.__name__]
        self.assertEqual(sorted(public), sorted([
            "RetirementProposalRefused", "RetirementTargetIdentity", "RetirementScope", "RetirementProposal",
            "identity_digest", "scope_digest", "proposal_digest", "build_retirement_proposal",
            "validate_proposal_against_report"]))
        self.assertEqual(len(set(wra.REFUSAL_CODES)), len(wra.REFUSAL_CODES))


class ReportAloneTests(ProposalTestCase):
    def test_report_does_not_carry_the_git_identity(self):
        names = {f.name for f in dataclasses.fields(wr.RetirementReport)}
        names |= {f.name for f in dataclasses.fields(wr.WorktreeRetirementAssessment)}
        names |= {f.name for f in dataclasses.fields(wr.RetirementFacts)}
        for needed in ("git_dir", "head_sha", "object_format", "head_ref", "listed_branch"):
            self.assertNotIn(needed, names)
            self.assertIn(needed, {f.name for f in dataclasses.fields(inv.WorktreeRecord)})

    def test_report_alone_or_a_stand_in_record_is_refused(self):
        report, record = fixture()
        params = list(__import__("inspect").signature(wra.build_retirement_proposal).parameters.values())
        self.assertEqual([p.name for p in params], ["report", "inventory_record", "host_id"])
        self.assertEqual(params[2].kind, params[2].KEYWORD_ONLY)
        for stand_in in (None, WT, candidate(report), candidate(report).facts, dataclasses.asdict(record)):
            self.assertRefused(wra.REFUSED_SCHEMA, report, stand_in)

        class SubRecord(inv.WorktreeRecord):
            pass

        self.assertRefused(wra.REFUSED_SCHEMA, report, SubRecord(**record.__dict__))

    def test_caller_crafted_candidate_is_still_only_a_proposal(self):
        # Anyone can craft facts that classify as CANDIDATE: the result is
        # consistent, but never authenticated, issued or authorizing.
        report, record = fixture()
        p = self.build(report, record)
        self.assertIn("CALLER_CRAFTED_CANDIDATE_INDISTINGUISHABLE", p.proposal_limitations)
        self.assertIn("HOST_IDENTITY_NOT_AUTHENTICATED", p.proposal_limitations)
        self.assertIs(p.host_identity_authenticated, False)
        self.assertIs(p.authorizes_action, False)


class ReportRefusalTests(ProposalTestCase):
    def test_report_state_refusals(self):
        _, record = fixture()
        cases = [
            ({"status": wr.REPORT_FAILED_CLOSED}, wra.REFUSED_INCOMPLETE),
            ({"global_errors": ("LEDGER_UNREADABLE: x",)}, wra.REFUSED_INCOMPLETE),
            ({"first_inventory_status": inv.INVENTORY_FAILED_CLOSED}, wra.REFUSED_INCOMPLETE),
            ({"second_inventory_status": None}, wra.REFUSED_INCOMPLETE),
            ({"second_inventory_fingerprint": "e" * 64}, wra.REFUSED_INCOMPLETE),
            ({"first_inventory_fingerprint": None, "second_inventory_fingerprint": None}, wra.REFUSED_INCOMPLETE),
            ({"fingerprint": ""}, wra.REFUSED_INCOMPLETE),
            ({"schema": "fcp4d02-worktree-retirement-assessment-v2"}, wra.REFUSED_SCHEMA),
            ({"classification_precedence": tuple(reversed(wr.CLASSIFICATION_PRECEDENCE))}, wra.REFUSED_SCHEMA),
            ({"limitations": wr.LIMITATIONS[:-1]}, wra.REFUSED_LIMITATIONS_ALTERED),
            ({"limitations": wr.LIMITATIONS + ("EXTRA",)}, wra.REFUSED_LIMITATIONS_ALTERED),
            ({"authorizes_action": True}, wra.REFUSED_UNTRUSTED_FIELD),
            ({"deletion_authorized": True}, wra.REFUSED_UNTRUSTED_FIELD),
            ({"human_review_required": False}, wra.REFUSED_UNTRUSTED_FIELD),
            ({"queue_roots_complete_claim": 1}, wra.REFUSED_UNTRUSTED_FIELD),
        ]
        for changes, code in cases:
            with self.subTest(changes=changes):
                report, _ = fixture(**changes)
                self.assertRefused(code, report, record)

    def test_forged_report_shapes_are_refused(self):
        report, record = fixture()
        self.assertRefused(wra.REFUSED_SCHEMA, json.loads(json.dumps(dataclasses.asdict(report))), record)
        self.assertRefused(wra.REFUSED_SCHEMA, forge(report, records=list(report.records)), record)
        self.assertRefused(wra.REFUSED_SCHEMA, forge(report, records=(dataclasses.asdict(candidate(report)),)),
                           record)
        self.assertRefused(wra.REFUSED_TAMPERED, forge(report, counts=()), record)

        class SubReport(wr.RetirementReport):
            pass

        self.assertRefused(wra.REFUSED_SCHEMA, SubReport(**report.__dict__), record)
        self.assertRefused(wra.REFUSED_UNTRUSTED_FIELD, forge(report, requested_path=object()), record)

    def test_target_selection(self):
        report, record = fixture()
        other = make_record(path=os.path.join(ROOT, "wt-other"), worktree_key=os.path.join(ROOT, "wt-other"),
                            worktree_top=os.path.join(ROOT, "wt-other"))
        self.assertRefused(wra.REFUSED_TARGET_ABSENT, report, other)
        duplicated = make_report(report.records + (candidate(report),))
        self.assertRefused(wra.REFUSED_AMBIGUOUS, duplicated, record)
        self.assertRefused(wra.REFUSED_IDENTITY_INCOMPLETE, report, forge(record, worktree_key=" "))
        self.assertRefused(wra.REFUSED_IDENTITY_INCOMPLETE, report, forge(record, worktree_key=None))

    def test_host_label_is_validated_but_never_authenticated(self):
        report, record = fixture()
        for bad in ("", " host", "host\n", "a/b", None, 7, "x" * 129):
            self.assertRefused(wra.REFUSED_UNTRUSTED_FIELD, report, record, host_id=bad)


class ClassificationRefusalTests(ProposalTestCase):
    def test_every_non_candidate_class_is_refused(self):
        cases = [
            ({"is_self_worktree": True}, wr.BLOCKED, wra.REFUSED_BLOCKED),
            ({"queue_items": ((QUEUE, "item-1", "PENDING", 0),)}, wr.BLOCKED, wra.REFUSED_BLOCKED),
            ({"ledger_error": "unreadable"}, wr.INSUFFICIENT_EVIDENCE, wra.REFUSED_INSUFFICIENT_EVIDENCE),
            ({"topology_proven": False}, wr.INSUFFICIENT_EVIDENCE, wra.REFUSED_INSUFFICIENT_EVIDENCE),
            ({"second_record_fingerprint": "0" * 64}, wr.INSUFFICIENT_EVIDENCE, wra.REFUSED_INSUFFICIENT_EVIDENCE),
            ({"in_second_inventory": False}, wr.INSUFFICIENT_EVIDENCE, wra.REFUSED_INSUFFICIENT_EVIDENCE),
            ({"queue_roots_complete_claim": False}, wr.INSUFFICIENT_EVIDENCE, wra.REFUSED_INSUFFICIENT_EVIDENCE),
            ({"worktree_local_refs": ("refs/worktree/x",)}, wr.REVIEW_REQUIRED, wra.REFUSED_REVIEW_REQUIRED),
            ({"ledger_history": (("WORKER_FINISHED", "p", "w"),)}, wr.REVIEW_REQUIRED, wra.REFUSED_REVIEW_REQUIRED),
            ({"ignored_count": 1, "ignored_paths": ("build/x",)}, wr.REVIEW_REQUIRED, wra.REFUSED_REVIEW_REQUIRED),
        ]
        for facts, classification, code in cases:
            with self.subTest(facts=facts):
                report, record = fixture(facts_changes=facts)
                self.assertEqual(candidate(report).classification, classification)
                self.assertRefused(code, report, record)

    def test_inventory_classes_other_than_idle_are_refused(self):
        cases = [
            ({"is_main": True}, wra.REFUSED_BLOCKED),                      # PROTECTED -> BLOCKED
            ({"locked": True}, wra.REFUSED_BLOCKED),                       # GIT_LOCKED -> BLOCKED
            ({"clean": False, "untracked_paths": ("x",)}, wra.REFUSED_BLOCKED),
            ({"listed_branch": "refs/heads/other"}, wra.REFUSED_INSUFFICIENT_EVIDENCE),  # UNSAFE
            ({"listed_head": "b" * 40}, wra.REFUSED_INSUFFICIENT_EVIDENCE),              # UNSAFE
            ({"lease_state": inv.LEASE_HELD}, wra.REFUSED_BLOCKED),
            ({"read_errors": ("boom",)}, wra.REFUSED_INSUFFICIENT_EVIDENCE),
        ]
        for changes, code in cases:
            with self.subTest(changes=changes):
                report, record = fixture(record_changes=changes)
                self.assertNotEqual(candidate(report).classification, wr.CANDIDATE_FOR_HUMAN_REVIEW)
                self.assertRefused(code, report, record)

    def test_forged_classification_is_refused_as_tampered(self):
        blocked_report, record = fixture(facts_changes={"is_self_worktree": True})
        forged = forge(candidate(blocked_report), classification=wr.CANDIDATE_FOR_HUMAN_REVIEW, reason_codes=())
        report = make_report((main_assessment(), forged))
        self.assertRefused(wra.REFUSED_TAMPERED, report, record)
        good, record = fixture()
        for changes in ({"classification": "ELIGIBLE"}, {"reason_codes": ("X",)}, {"advisories": ()},
                        {"fingerprint": "0" * 64}, {"path": os.path.join(ROOT, "elsewhere")},
                        {"facts": dataclasses.replace(candidate(good).facts, is_self_worktree=True)}):
            with self.subTest(changes=changes):
                report = make_report((main_assessment(), forge(candidate(good), **changes)))
                self.assertRefused(wra.REFUSED_TAMPERED, report, record)

    def test_unknown_classification_is_refused_even_if_reproducible(self):
        good, record = fixture()
        unknown = forge(candidate(good), classification="UNKNOWN_CLASS")
        report = make_report((main_assessment(), unknown))
        with mock.patch.object(wra.wr, "classify_retirement", side_effect=lambda facts: unknown):
            self.assertRefused(wra.REFUSED_UNKNOWN_CLASSIFICATION, report, record)

    def test_altered_assessment_limitations_or_flags(self):
        good, record = fixture()
        for changes, code in (({"limitations": wr.LIMITATIONS[1:]}, wra.REFUSED_LIMITATIONS_ALTERED),
                              ({"limitations": ()}, wra.REFUSED_LIMITATIONS_ALTERED),
                              ({"authorizes_action": True}, wra.REFUSED_UNTRUSTED_FIELD),
                              ({"deletion_authorized": True}, wra.REFUSED_UNTRUSTED_FIELD),
                              ({"human_review_required": False}, wra.REFUSED_UNTRUSTED_FIELD)):
            with self.subTest(changes=changes):
                report = make_report((main_assessment(), forge(candidate(good), **changes)))
                self.assertRefused(code, report, record)

    def test_facts_disagreeing_with_report_are_refused(self):
        report, record = fixture(queue_roots_complete_claim=False)
        self.assertRefused(wra.REFUSED_IDENTITY_MISMATCH, report, record)
        report, record = fixture(queue_roots=())
        self.assertRefused(wra.REFUSED_IDENTITY_MISMATCH, report, record)


class IdentityRefusalTests(ProposalTestCase):
    def test_record_fingerprint_must_match_both_assessed_fingerprints(self):
        report, _ = fixture()
        moved = make_record(head_sha="b" * 40, listed_head="b" * 40)     # real, re-fingerprinted record
        self.assertNotEqual(moved.fingerprint, make_record().fingerprint)
        self.assertRefused(wra.REFUSED_IDENTITY_MISMATCH, report, moved)

    def test_record_altered_without_refingerprint_is_tampered(self):
        report, record = fixture()
        for changes in ({"head_sha": "b" * 40}, {"git_dir": os.path.join(ROOT, "x")}, {"head_ref": BRANCH + "x"},
                        {"is_main": True}, {"classification": inv.UNSAFE}, {"fingerprint": "0" * 64}):
            with self.subTest(changes=changes):
                self.assertRefused(wra.REFUSED_TAMPERED, report, forge(record, **changes))

    def test_record_flags_and_bound_workers(self):
        report, record = fixture()
        self.assertRefused(wra.REFUSED_UNTRUSTED_FIELD, report, forge(record, authorizes_action=True))
        self.assertRefused(wra.REFUSED_UNTRUSTED_FIELD, report, forge(record, human_review_required=False))
        self.assertRefused(wra.REFUSED_BLOCKED, report, forge(record, duplicate_checkouts=(REPO,)))
        self.assertRefused(wra.REFUSED_BLOCKED, report, forge(record, ledger_open_workers=(("p", "w"),)))

    def test_object_format_outside_fingerprint_is_checked_against_head_sha(self):
        report, record = fixture()
        # object_format is not part of the inventory fingerprint, so these
        # reproduce exactly; the sha shape must still refuse them.
        for fmt, code in (("sha256", wra.REFUSED_IDENTITY_MISMATCH), ("md5", wra.REFUSED_IDENTITY_MISMATCH),
                          (None, wra.REFUSED_IDENTITY_INCOMPLETE), ("", wra.REFUSED_IDENTITY_INCOMPLETE)):
            with self.subTest(fmt=fmt):
                forged = forge(record, object_format=fmt)
                self.assertEqual(inv.classify_record(forged), forged)
                self.assertRefused(code, report, forged)
        sha256 = "c" * 64
        report, record = fixture(record_changes={"object_format": "sha256", "head_sha": sha256,
                                                 "listed_head": sha256})
        self.assertEqual(self.build(report, record).target.object_format, "sha256")
        report, record = fixture(record_changes={"head_sha": "A" * 40, "listed_head": "A" * 40})
        self.assertRefused(wra.REFUSED_IDENTITY_MISMATCH, report, record)

    def test_consistent_but_wrong_identity_is_refused(self):
        cases = [
            ({"git_dir": os.path.join(ROOT, "admin", "wt-feature")}, wra.REFUSED_IDENTITY_MISMATCH),
            ({"git_dir": COMMON}, wra.REFUSED_IDENTITY_MISMATCH),
            ({"git_dir": os.path.join(COMMON, "worktrees")}, wra.REFUSED_IDENTITY_MISMATCH),
            ({"common_dir": os.path.join(ROOT, "other", ".git"),
              "git_dir": os.path.join(ROOT, "other", ".git", "worktrees", "wt-feature")},
             wra.REFUSED_IDENTITY_MISMATCH),
            ({"worktree_top": os.path.join(ROOT, "elsewhere")}, wra.REFUSED_IDENTITY_MISMATCH),
            ({"path": os.path.join(ROOT, "elsewhere")}, wra.REFUSED_IDENTITY_MISMATCH),
            ({"worktree_key": "wt-feature", "path": "wt-feature"}, wra.REFUSED_IDENTITY_MISMATCH),
            ({"head_ref": "refs/tags/v1", "listed_branch": "refs/tags/v1"}, wra.REFUSED_INSUFFICIENT_EVIDENCE),
            ({"head_ref": "refs/heads/develop", "listed_branch": "refs/heads/develop"},
             wra.REFUSED_PROTECTED_TARGET),
            ({"protected_branch": True}, wra.REFUSED_BLOCKED),
            ({"git_dir": None}, wra.REFUSED_IDENTITY_INCOMPLETE),
            ({"common_dir": " "}, wra.REFUSED_IDENTITY_INCOMPLETE),
        ]
        for changes, code in cases:
            with self.subTest(changes=changes):
                report, record = fixture(record_changes=changes)
                self.assertRefused(code, report, record)

    def test_report_common_dir_must_match_record(self):
        report, record = fixture(common_dir=os.path.join(ROOT, "other", ".git"))
        self.assertRefused(wra.REFUSED_IDENTITY_MISMATCH, report, record)


class ScopeRefusalTests(ProposalTestCase):
    def test_missing_or_unresolved_roots(self):
        _, record = fixture()
        for name in ("requested_path", "repository_top", "state_root", "ledger_root", "self_worktree"):
            for bad in (None, "", "relative" + os.sep + "root"):
                with self.subTest(name=name, bad=bad):
                    report, _ = fixture(**{name: bad})
                    self.assertRefused(wra.REFUSED_SCOPE_MISSING, report, record)
        for changes in ({"lease_root": "relative"}, {"lease_root": ""}, {"queue_roots": ("relative",)},
                        {"governed_roots": ("",)}):
            with self.subTest(changes=changes):
                report, _ = fixture(**changes)
                self.assertRefused(wra.REFUSED_SCOPE_MISSING, report, record)
        report, _ = fixture(governed_roots=[GOVERNED])  # non-canonical container type
        self.assertRefused(wra.REFUSED_UNTRUSTED_FIELD, report, record)

    def test_alias_and_duplicate_keys(self):
        _, record = fixture()
        spelled = QUEUE.upper() if os.name == "nt" else QUEUE + os.sep
        for changes in ({"ledger_root": STATE}, {"queue_roots": (QUEUE, spelled)},
                        {"queue_roots": (QUEUE, os.path.join(QUEUE, "x", ".."))},
                        {"governed_roots": (REPO,)}, {"lease_root": QUEUE}, {"governed_roots": (GOVERNED, GOVERNED)}):
            with self.subTest(changes=changes):
                report, _ = fixture(**changes)
                self.assertRefused(wra.REFUSED_SCOPE_ALIAS, report, record)

    def test_target_overlapping_any_scope_root(self):
        _, record = fixture()
        for changes in ({"governed_roots": (ROOT,)}, {"queue_roots": (os.path.join(WT, "queue"),)},
                        {"state_root": os.path.join(WT, "state")}, {"self_worktree": WT},
                        {"lease_root": os.path.join(WT, "lease")}, {"repository_top": os.path.join(WT, "inner")}):
            with self.subTest(changes=changes):
                report, _ = fixture(**changes)
                self.assertRefused(wra.REFUSED_SCOPE_OVERLAP, report, record)


class ValidationTests(ProposalTestCase):
    def setUp(self):
        self.report, self.record = fixture()
        self.p = self.build(self.report, self.record)

    def findings(self, proposal, report=None, record=None):
        return wra.validate_proposal_against_report(proposal, report or self.report, record or self.record)

    def test_untouched_proposal_has_no_findings_and_no_permission(self):
        result = self.findings(self.p)
        self.assertEqual(result, ())
        self.assertIsInstance(result, tuple)

    def test_tampered_proposal_content(self):
        for changes in ({"limitations": wr.LIMITATIONS[:-1]}, {"advisories": ()},
                        {"proposal_limitations": ()}, {"report_fingerprint": "0" * 64},
                        {"assessment_classification": "ELIGIBLE"}):
            with self.subTest(changes=changes):
                findings = self.findings(forge(self.p, **changes))
                self.assertIn(wra.PROPOSAL_DIGEST_MISMATCH, findings)
                self.assertIn(wra.PROPOSAL_CONTENT_MISMATCH, findings)

    def test_tampered_scope_and_target(self):
        scope = forge(self.p.scope, queue_roots=())
        findings = self.findings(forge(self.p, scope=scope))
        self.assertIn(wra.SCOPE_DIGEST_MISMATCH, findings)
        self.assertIn(wra.SCOPE_MISMATCH, findings)
        target = forge(self.p.target, head_sha="b" * 40)
        findings = self.findings(forge(self.p, target=target))
        self.assertIn(wra.TARGET_DIGEST_MISMATCH, findings)
        self.assertIn(wra.TARGET_MISMATCH, findings)

    def test_digest_consistent_forgery_still_mismatches_the_inputs(self):
        scope = dataclasses.replace(self.p.scope, queue_roots=(os.path.join(ROOT, "fake"),))
        scope = dataclasses.replace(scope, scope_digest=wra.scope_digest(scope))
        forged = dataclasses.replace(self.p, scope=scope)
        forged = dataclasses.replace(forged, proposal_digest=wra.proposal_digest(forged))
        findings = self.findings(forged)
        self.assertNotIn(wra.SCOPE_DIGEST_MISMATCH, findings)
        self.assertNotIn(wra.PROPOSAL_DIGEST_MISMATCH, findings)
        self.assertIn(wra.SCOPE_MISMATCH, findings)

    def test_flipped_flags_are_reported(self):
        for obj, name, value in ((None, "authorizes_action", True), (None, "issued", True),
                                 (None, "queue_scope_attested", True), ("scope", "queue_scope_attested", True),
                                 ("target", "host_identity_authenticated", True),
                                 ("target", "file_object_id", (1, 2))):
            with self.subTest(obj=obj, name=name):
                if obj is None:
                    forged = forge(self.p, **{name: value})
                else:
                    forged = forge(self.p, **{obj: forge(getattr(self.p, obj), **{name: value})})
                self.assertIn(wra.PROPOSAL_FLAG_ALTERED, self.findings(forged))

    def test_refused_or_different_inputs(self):
        failed, _ = fixture(status=wr.REPORT_FAILED_CLOSED)
        self.assertEqual(self.findings(self.p, report=failed), (wra.REFUSED_INCOMPLETE,))
        other_report, other_record = fixture(record_changes={"head_sha": "d" * 40, "listed_head": "d" * 40})
        findings = self.findings(self.p, report=other_report, record=other_record)
        self.assertIn(wra.TARGET_MISMATCH, findings)
        changed_scope, _ = fixture(state_root=os.path.join(ROOT, "other-state"))
        self.assertIn(wra.SCOPE_MISMATCH, self.findings(self.p, report=changed_scope))

    def test_non_proposals(self):
        for bad in (None, dataclasses.asdict(self.p), self.report, forge(self.p, target=None),
                    forge(self.p, scope=dataclasses.asdict(self.p.scope))):
            self.assertEqual(self.findings(bad), (wra.PROPOSAL_TYPE_INVALID,))


class PurityAndSecurityTests(unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_imports_are_limited_to_pure_sources(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module == "scripts.ai" else node.module
                             for a in node.names}
        self.assertEqual(imported, {
            "__future__", "dataclasses", "hashlib", "json", "os", "re", "sys", "pathlib", "typing",
            "scripts.ai.claude_runner", "scripts.ai.runner_worktree_inventory",
            "scripts.ai.runner_worktree_retirement",
            "claude_runner", "runner_worktree_inventory", "runner_worktree_retirement",
        })

    def test_no_side_effecting_calls_or_names(self):
        code = re.sub(r'"""[\s\S]*?"""', "", self.source)
        # The only path resolution is the shared direct-execution import fallback.
        self.assertEqual(code.count("Path(__file__).resolve()"), 1)
        code = code.replace("Path(__file__).resolve()", "")
        for word in ("subprocess", "Popen", "shell", "os.system", "os.remove", "os.unlink", "rmtree", ".unlink",
                     "rmdir", "sqlite", "HostLedger", "hmac", "secrets", "cryptography", "Ed25519", "private_key",
                     "sign(", "open(", "write_text", "write_bytes", "mkdir", "touch(", "QueueLock", "DirLease",
                     "acquire", "release", "lease_dir(", "_git(", "runner_git", "runner_integration",
                     "runner_promotion", "claude_queue", "runner_pipeline", "runner_factory_ledger",
                     "canonical_target_key", "inventory_worktrees", "assess_worktree_retirement", "resolve(",
                     "exists(", "is_dir(", "iterdir", "scandir", "listdir", "walk(", "stat(", "realpath",
                     "abspath", "getcwd", "environ", "socket", "urllib", "requests", "http", "datetime",
                     "time.", "prune", "worktree remove", "unlock("):
            self.assertNotIn(word, code, word)

    def test_attribute_use_of_sources_is_allowlisted(self):
        used = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                used.setdefault(node.value.id, set()).add(node.attr)
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name) and node.value.value.id == "os"):
                used.setdefault("os.path", set()).add(node.attr)
        self.assertLessEqual(used.get("os", set()), {"path", "name", "sep"})
        self.assertLessEqual(used.get("os.path", set()),
                             {"isabs", "splitdrive", "normcase", "normpath", "basename", "dirname", "join"})
        self.assertLessEqual(used.get("wr", set()), {
            "BLOCKED", "INSUFFICIENT_EVIDENCE", "REVIEW_REQUIRED", "CANDIDATE_FOR_HUMAN_REVIEW", "SCHEMA",
            "CLASSIFICATION_PRECEDENCE", "LIMITATIONS", "REPORT_COMPLETE", "RetirementReport",
            "WorktreeRetirementAssessment", "RetirementFacts", "classify_retirement", "_counts"})
        self.assertLessEqual(used.get("inv", set()), {
            "WorktreeRecord", "classify_record", "INVENTORY_COMPLETE", "IDLE_CLEAN_UNBOUND"})
        self.assertEqual(used.get("claude_runner", set()), {"PROTECTED_BRANCHES"})
        self.assertLessEqual(used.get("sys", set()), {"path"})

    def test_never_live_constants_are_assigned_once_to_false(self):
        assigns = [n for n in ast.walk(self.tree) if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign))]
        for name in ("RETIREMENT_AUTHORIZATION_LIVE", "RETIREMENT_EXECUTION_CAPABLE"):
            hits = [n for n in assigns for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
                    if isinstance(t, ast.Name) and t.id == name]
            self.assertEqual(len(hits), 1, name)
            self.assertIsInstance(hits[0].value, ast.Constant)
            self.assertIs(hits[0].value.value, False)
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, (ast.Global, ast.Nonlocal))])

    def test_build_and_validate_touch_no_filesystem_process_or_path_resolution(self):
        report, record = fixture()

        def boom(*args, **kwargs):
            raise AssertionError("side effect attempted")

        patches = [
            mock.patch.object(subprocess, "Popen", boom), mock.patch.object(subprocess, "run", boom),
            mock.patch.object(os, "remove", boom), mock.patch.object(os, "unlink", boom),
            mock.patch.object(os, "rmdir", boom), mock.patch.object(os, "replace", boom),
            mock.patch.object(os, "rename", boom), mock.patch.object(os, "mkdir", boom),
            mock.patch.object(os, "scandir", boom), mock.patch.object(os, "listdir", boom),
            mock.patch.object(os, "stat", boom), mock.patch.object(os, "lstat", boom),
            mock.patch.object(os, "getcwd", boom), mock.patch.object(shutil, "rmtree", boom),
            mock.patch.object(builtins, "open", boom), mock.patch.object(pathlib.Path, "resolve", boom),
            mock.patch.object(pathlib.Path, "exists", boom), mock.patch.object(pathlib.Path, "is_dir", boom),
            mock.patch.object(pathlib.Path, "unlink", boom), mock.patch.object(pathlib.Path, "stat", boom),
            mock.patch.object(mw, "canonical_target_key", boom), mock.patch.object(wr, "_key", boom),
            mock.patch.object(inv, "_key", boom), mock.patch.object(inv, "inventory_worktrees", boom),
            mock.patch.object(wr, "assess_worktree_retirement", boom),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        proposal = wra.build_retirement_proposal(report, record, host_id=HOST)
        self.assertEqual(wra.validate_proposal_against_report(proposal, report, record), ())
        refused, _ = fixture(status=wr.REPORT_FAILED_CLOSED)
        self.assertEqual(wra.validate_proposal_against_report(proposal, refused, record), (wra.REFUSED_INCOMPLETE,))

    def test_inputs_are_not_modified(self):
        report, record = fixture()
        before = (copy.deepcopy(dataclasses.asdict(report)), copy.deepcopy(dataclasses.asdict(record)))
        wra.build_retirement_proposal(report, record, host_id=HOST)
        self.assertEqual((dataclasses.asdict(report), dataclasses.asdict(record)), before)

    def test_docstring_states_the_boundary(self):
        doc = " ".join(wra.__doc__.split())
        for phrase in ("NOT an approval, authorization, permit or execution capability",
                       "never an authenticated host identity", "never a trusted certificate",
                       "does NOT carry the per-worktree Git identity", "left absent/unverified"):
            self.assertIn(phrase, doc, phrase)


class CiWorkflowTests(unittest.TestCase):
    JOBS = {
        "fabric-regression": "Fabric regression / Windows / Python 3.11",
        "fcp2b-reconciliation": "FCP-2B reconciliation / Windows / Python 3.11",
        "fcp3a-promotion": "FCP-3A promotion preflight / Windows / Python 3.11",
        "fcp3b1-authorization-intent": "FCP-3B-1 promotion intent / Windows / Python 3.11",
        "fcp3b2a-pr-gate": "FCP-3B-2A PR eligibility gate / Windows / Python 3.11",
        "fcp3b2b1-human-authorization": "FCP-3B-2B1 human decision evidence / Windows / Python 3.11",
        "fcp3b2b2-governed-executor": "FCP-3B-2B2 governed executor simulation / Windows / Python 3.11",
        "fcp4d02-worktree-retirement":
            "FCP-4C/4D worktree inventory and retirement assessment / Windows / Python 3.11",
        "fcp3b2b2-host-trust": "FCP-3B-2B2 HOST-01 trust adapters / Windows / Python 3.11",
    }

    def setUp(self):
        self.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_nine_jobs_unchanged(self):
        jobs = dict(re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: (.+)$", self.workflow))
        self.assertEqual(jobs, self.JOBS)

    def test_proposal_suite_runs_in_the_zero_skip_retirement_job(self):
        job = re.search(r"(?ms)^  fcp4d02-worktree-retirement:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", self.workflow).group(1)
        self.assertIn("runs-on: windows-latest", job)
        ns = re.search(r"ns=\(([^)]*)\)", job).group(1)
        self.assertEqual(re.findall(r"'([^']+)'", ns), [
            "scripts.tests.test_runner_worktree_inventory", "scripts.tests.test_runner_worktree_retirement",
            "scripts.tests.test_runner_integration", "scripts.tests.test_runner_worktree_retirement_authorization",
        ])
        self.assertIn("result.wasSuccessful() and not result.skipped", job)

    def test_previous_suites_preserved(self):
        for module in ("test_fabric_director", "test_fabric_director_cli", "test_runner_git", "test_runner_pipeline",
                       "test_runner_providers", "test_runner_factory_ledger", "test_runner_module_governance",
                       "test_claude_runner", "test_claude_queue", "test_claude_multiworker",
                       "test_runner_process_supervision", "test_runner_provider_quota_guard",
                       "test_runner_reconciliation", "test_runner_promotion", "test_runner_promotion_authorization",
                       "test_runner_promotion_pr_gate", "test_runner_promotion_human_authorization",
                       "test_runner_promotion_executor", "test_runner_promotion_host_authority",
                       "test_runner_promotion_host_ledger", "test_runner_promotion_host_github"):
            self.assertRegex(self.workflow, rf"scripts\.tests\.{module}\b", module)


if __name__ == "__main__":
    unittest.main()
