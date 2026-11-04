"""FCP-12A-02: Self-Dogfood isolation guardrails V1 - controller / target
isolation from caller-captured snapshots. Offline, synthetic facts only
(mocks prove regressions, never a real dogfood run)."""

from __future__ import annotations

import ast
import builtins
import dataclasses
import json
import os
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as cr
from scripts.ai import fabric_self_dogfood_contract as dc
from scripts.ai import fabric_self_dogfood_guardrails as g

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_self_dogfood_guardrails.py"

BASE = "a" * 40
ATTEMPT_BASE = "b" * 40
CHECKPOINT = "c" * 40
COMMON = "C:/Users/Op/Desktop/IGNACIO/quesada-abogados/.git"
CONTROLLER = "C:/Users/Op/Desktop/IGNACIO/fcp12-nightshift-runtime/controller-fcp12-stable-v1"
TARGET = "C:/Users/Op/Desktop/IGNACIO/quesada-fcp12-self-dogfood-v1"
BRANCH = "feature/fcp12-self-dogfood-v1"
SCOPES = ("scripts/ai/fabric_self_dogfood_guardrails.py", "scripts/tests/test_fabric_self_dogfood_guardrails.py")
DIRTY_IN_SCOPE = " M scripts/ai/fabric_self_dogfood_guardrails.py\n?? scripts/tests/test_fabric_self_dogfood_guardrails.py\n"
ALL_FLAGS = (
    "certified", "authorizes_action", "execution_allowed", "merging_allowed", "promotion_allowed",
    "auto_retry_allowed", "resume_allowed", "release_allowed", "human_approval_granted", "host_ci_verified",
    "closure_complete", "git_allowed", "ledger_write_allowed", "self_promotion_allowed",
    "external_authorization_accepted",
)


def plan(**overrides):
    values = dict(base_commit=BASE, controller_commit=BASE, controller_path=CONTROLLER, target_path=TARGET,
                  target_branch=BRANCH, attempt_base_head=ATTEMPT_BASE, authorized_scopes=SCOPES)
    values.update(overrides)
    return g.IsolationPlan(**values)


def controller(**overrides):
    values = dict(declared_path=CONTROLLER, resolved_path=CONTROLLER, link_component_observed=False,
                  git_dir=COMMON + "/worktrees/controller-fcp12-stable-v1", git_common_dir=COMMON, branch="HEAD",
                  head=BASE, porcelain_status="")
    values.update(overrides)
    return g.WorktreeSnapshot(**values)


def target(**overrides):
    values = dict(declared_path=TARGET, resolved_path=TARGET, link_component_observed=False,
                  git_dir=COMMON + "/worktrees/quesada-fcp12-self-dogfood-v1", git_common_dir=COMMON,
                  branch=BRANCH, head=ATTEMPT_BASE, porcelain_status="")
    values.update(overrides)
    return g.WorktreeSnapshot(**values)


def process(**overrides):
    values = dict(module_path=CONTROLLER + "/scripts/ai/runner_pipeline.py", worktree_top=CONTROLLER)
    values.update(overrides)
    return g.ControllerProcess(**values)


def admit(**overrides):
    values = dict(schema_version=1, action=g.ACTION_ADMIT_ATTEMPT, plan=plan(), process=process(),
                  controller_before=controller(), target_before=target())
    values.update(overrides)
    return g.GuardrailRequest(**values)


def confirm(**overrides):
    values = dict(schema_version=1, action=g.ACTION_CONFIRM_ISOLATION, plan=plan(), process=process(),
                  controller_before=controller(), target_before=target(), controller_after=controller(),
                  target_after=target(head=CHECKPOINT), target_checkpoint_commit=CHECKPOINT)
    values.update(overrides)
    return g.GuardrailRequest(**values)


def reasons(request):
    return g.assess_guardrails(request).reasons


class PositivePathTests(unittest.TestCase):
    def test_admit_and_confirm_hold_with_zero_authority(self):
        for request in (admit(), confirm(), confirm(target_after=target(porcelain_status=DIRTY_IN_SCOPE),
                                                    target_checkpoint_commit=None)):
            a = g.assess_guardrails(request)
            self.assertEqual((a.decision, a.reasons), (g.ISOLATION_HOLDS, ()), request.action)
            self.assertTrue(a.isolation_holds)
            self.assertRegex(a.binding, r"^[0-9a-f]{64}$")
            for flag in ALL_FLAGS:
                self.assertIs(getattr(a, flag), False, flag)
            payload = json.loads(g.canonical_json(a))
            self.assertEqual(payload["schema"], g.SCHEMA)
            for flag in ALL_FLAGS:
                self.assertIs(payload[flag], False, flag)

    def test_deterministic_and_binding_tracks_facts(self):
        self.assertEqual(g.canonical_json(g.assess_guardrails(confirm())),
                         g.canonical_json(g.assess_guardrails(confirm())))
        self.assertNotEqual(g.assess_guardrails(admit()).binding, g.assess_guardrails(confirm()).binding)
        other = confirm(plan=plan(authorized_scopes=SCOPES[:1]),
                        target_after=target(head=CHECKPOINT, porcelain_status=""))
        self.assertNotEqual(g.assess_guardrails(other).binding, g.assess_guardrails(confirm()).binding)

    def test_closure_identity_feeds_the_fcp12a01_contract(self):
        identity = g.closure_identity(confirm())
        self.assertIs(type(identity), dc.DogfoodIdentity)
        self.assertEqual(identity, dc.DogfoodIdentity(base_commit=BASE, controller_commit=BASE,
                                                      controller_head_observed=BASE, target_head_observed=CHECKPOINT,
                                                      target_isolated=True))
        # Denied, pre-attempt, promotion or untyped requests never claim isolation.
        for request in (confirm(controller_after=controller(head=CHECKPOINT)), admit(),
                        confirm(action=g.ACTION_SELF_PROMOTE), None, "x"):
            self.assertIs(g.closure_identity(request).target_isolated, False)


class IdentityAndPathTests(unittest.TestCase):
    def test_same_worktree_and_controller_from_target_are_refused(self):
        self.assertIn(g.SAME_WORKTREE, reasons(admit(plan=plan(target_path=CONTROLLER))))
        self.assertIn(g.SAME_WORKTREE, reasons(admit(target_before=target(git_dir=controller().git_dir))))
        # Case / separator variants of the same path are the same worktree.
        self.assertIn(g.SAME_WORKTREE, reasons(admit(plan=plan(target_path=CONTROLLER.upper().replace("/", "\\")))))
        nested = CONTROLLER + "/inner"
        self.assertIn(g.WORKTREE_OVERLAP, reasons(admit(plan=plan(target_path=nested))))
        # The controller process executing from the target worktree.
        from_target = process(module_path=TARGET + "/scripts/ai/runner_pipeline.py", worktree_top=TARGET)
        got = reasons(admit(process=from_target))
        self.assertIn(g.CONTROLLER_RUNS_FROM_TARGET, got)
        self.assertIn(g.CONTROLLER_LOCATION_UNPROVEN, got)
        self.assertIn(g.CONTROLLER_LOCATION_UNPROVEN, reasons(admit(process=None)))
        self.assertIn(g.CONTROLLER_LOCATION_UNPROVEN,
                      reasons(admit(process=process(module_path="C:/elsewhere/runner_pipeline.py"))))

    def test_repository_and_path_mismatch(self):
        self.assertIn(g.REPOSITORY_MISMATCH, reasons(admit(target_before=target(git_common_dir="D:/other/.git"))))
        moved = "C:/Users/Op/Desktop/IGNACIO/other-worktree"
        self.assertIn(g.PATH_MISMATCH, reasons(admit(target_before=target(declared_path=moved, resolved_path=moved))))
        self.assertIn(g.PATH_MISMATCH,
                      reasons(admit(controller_before=controller(declared_path=moved, resolved_path=moved))))

    def test_symlinks_and_non_canonical_paths(self):
        self.assertIn(g.SYMLINK_PRESENT, reasons(admit(target_before=target(link_component_observed=True))))
        self.assertIn(g.SYMLINK_UNPROVEN, reasons(admit(controller_before=controller(link_component_observed=None))))
        # A declared path that resolves elsewhere (junction / link) is not canonical.
        self.assertIn(g.PATH_NOT_CANONICAL,
                      reasons(admit(target_before=target(declared_path="C:/Users/Op/link-to-target"))))

    def test_malicious_paths_are_rejected(self):
        hostile = (
            "relative/path", "~/repo", "C:relative", "//server/share/repo", "\\\\?\\C:\\repo", "\\\\.\\pipe\\x",
            "C:/repo/../controller", "C:/repo/./x", "C:/repo//x", "C:/repo/", "C:/", "/", "C:/repo/file.txt:stream",
            "C:/repo/a*b", "C:/repo/trailing.", "C:/repo/trailing ", "C:/PROGRA~1/repo", "C:/repo\x00/x",
            "C:/repo\n/x", "C:/" + "x" * 2000, "", None, 7, b"C:/repo",
        )
        for value in hostile:
            self.assertIsNone(g.canonical_path_key(value), repr(value))
            self.assertIn(g.PATH_MALFORMED, reasons(admit(plan=plan(target_path=value))), repr(value))
            self.assertNotEqual(g.assess_guardrails(admit(target_before=target(resolved_path=value))).decision,
                                g.ISOLATION_HOLDS, repr(value))
        self.assertEqual(g.canonical_path_key("C:\\Users\\Op\\Repo"), "c:/users/op/repo")
        self.assertEqual(g.canonical_path_key("/home/op/repo"), "/home/op/repo")


class BranchHeadStatusTests(unittest.TestCase):
    def test_controller_must_be_detached_at_pinned_base_and_clean(self):
        self.assertIn(g.CONTROLLER_NOT_DETACHED, reasons(admit(controller_before=controller(branch="main"))))
        self.assertIn(g.CONTROLLER_HEAD_UNEXPECTED, reasons(admit(controller_before=controller(head=CHECKPOINT))))
        self.assertIn(g.CONTROLLER_NOT_AT_BASE, reasons(admit(plan=plan(controller_commit=CHECKPOINT))))
        self.assertIn(g.CONTROLLER_DIRTY, reasons(admit(controller_before=controller(porcelain_status=" M x.py\n"))))
        self.assertIn(g.STATUS_UNAVAILABLE,
                      reasons(admit(controller_before=controller(porcelain_status=cr.GIT_STATUS_UNAVAILABLE))))

    def test_target_branch_head_and_clean_start(self):
        for protected in sorted(cr.PROTECTED_BRANCHES):
            self.assertIn(g.TARGET_BRANCH_PROTECTED, reasons(admit(target_before=target(branch=protected))))
            self.assertIn(g.TARGET_BRANCH_PROTECTED,
                          reasons(admit(plan=plan(target_branch=protected), target_before=target(branch=protected))))
        self.assertIn(g.TARGET_BRANCH_UNEXPECTED, reasons(admit(target_before=target(branch="HEAD"))))
        self.assertIn(g.TARGET_BRANCH_UNEXPECTED, reasons(admit(target_before=target(branch="feature/other"))))
        for bad in ("HEAD", "a..b", "x/", ".hidden", "x.lock", "", "a b", "-x"):
            self.assertIn(g.PLAN_MALFORMED, reasons(admit(plan=plan(target_branch=bad))), bad)
        self.assertIn(g.TARGET_HEAD_UNEXPECTED, reasons(admit(target_before=target(head=BASE))))
        self.assertIn(g.TARGET_DIRTY_AT_START, reasons(admit(target_before=target(porcelain_status="?? junk.txt\n"))))
        self.assertIn(g.STATUS_UNAVAILABLE, reasons(admit(target_before=target(porcelain_status="M\n"))))


class DriftTests(unittest.TestCase):
    def test_controller_drift_after_attempt(self):
        for change in (dict(head=CHECKPOINT), dict(porcelain_status=" M scripts/ai/runner_pipeline.py\n"),
                       dict(branch="feature/x"), dict(git_dir=COMMON + "/worktrees/other"),
                       dict(link_component_observed=None)):
            got = reasons(confirm(controller_after=controller(**change)))
            self.assertIn(g.CONTROLLER_DRIFT, got, change)

    def test_target_drift_and_unexpected_head(self):
        self.assertIn(g.TARGET_DRIFT, reasons(confirm(target_after=target(head=CHECKPOINT, branch="feature/x"))))
        self.assertIn(g.TARGET_DRIFT, reasons(confirm(target_after=target(head=CHECKPOINT,
                                                                          git_dir=COMMON + "/worktrees/z"))))
        self.assertIn(g.TARGET_HEAD_DRIFT, reasons(confirm(target_after=target(head="e" * 40))))
        self.assertIn(g.TARGET_HEAD_DRIFT, reasons(confirm(target_checkpoint_commit=None)))
        self.assertIn(g.SNAPSHOT_MALFORMED, reasons(confirm(target_checkpoint_commit=ATTEMPT_BASE)))
        self.assertIn(g.SNAPSHOT_MALFORMED, reasons(confirm(target_checkpoint_commit="not-a-commit")))
        # Post-attempt snapshots on a pre-attempt request are refused, not ignored.
        self.assertIn(g.SNAPSHOT_MALFORMED, reasons(admit(controller_after=controller())))
        self.assertIn(g.SNAPSHOT_MALFORMED, reasons(confirm(target_after=None)))


class ScopeTests(unittest.TestCase):
    def test_plan_scope_is_reused_runner_write_scope(self):
        self.assertIn(g.SCOPE_MISSING, reasons(admit(plan=plan(authorized_scopes=()))))
        for bad in ("/abs/path", "C:/abs", "../escape", "a/../../b", "", "  ", "."):
            self.assertIn(g.SCOPE_INVALID, reasons(admit(plan=plan(authorized_scopes=(bad,)))), bad)
        for broad in ("*", ".github", ".GITHUB/workflows", ".github/workflows/*.yml", ".git", "x/.git/hooks", "?*"):
            self.assertIn(g.SCOPE_TOO_BROAD, reasons(admit(plan=plan(authorized_scopes=(broad,)))), broad)
        self.assertIn(g.PLAN_MALFORMED, reasons(admit(plan=plan(authorized_scopes=["scripts/ai"]))))
        self.assertIn(g.PLAN_MALFORMED, reasons(admit(plan=plan(authorized_scopes=(None,)))))

    def test_changed_paths_must_stay_in_scope(self):
        def after(status):
            return reasons(confirm(target_after=target(head=CHECKPOINT, porcelain_status=status)))
        self.assertIn(g.SCOPE_VIOLATION, after(" M scripts/ai/runner_pipeline.py\n"))
        self.assertIn(g.SCOPE_VIOLATION, after("R  scripts/ai/fabric_self_dogfood_guardrails.py -> scripts/x.py\n"))
        self.assertIn(g.SCOPE_VIOLATION, after("?? scripts/\n"))
        got = after(" M .github/workflows/fabric-ci.yml\n")
        self.assertIn(g.PROTECTED_PATH_CHANGED, got)
        self.assertIn(g.SCOPE_VIOLATION, got)
        # A glob scope must not let traversal or git metadata through.
        globbed = plan(authorized_scopes=("scripts/*",))
        for status in (" M scripts/../.github/workflows/fcp11-control-plane.yml\n", " M scripts/x/.git/config\n"):
            got = reasons(confirm(plan=globbed, target_after=target(head=CHECKPOINT, porcelain_status=status)))
            self.assertIn(g.SCOPE_VIOLATION, got, status)
        self.assertIn(g.STATUS_UNAVAILABLE, after(cr.GIT_STATUS_UNAVAILABLE))

    def test_own_fcp12_gate_cannot_be_scoped_in_any_spelling_or_glob(self):
        for scope in (".github/workflows/fcp12-self-dogfood.yml", ".GITHUB/WORKFLOWS/FCP12-SELF-DOGFOOD.YML",
                      ".github\\workflows\\fcp12-self-dogfood.yml", "./.github//workflows/./fcp12-self-dogfood.yml",
                      ".github/workflows/fcp12-self-dogfood.yml.", ".github/workflows/fcp12-*",
                      ".github/workflows/fcp1?-self-dogfood.yml", ".github/workflows/[f]cp12-self-dogfood.yml",
                      ".github/**", "*/workflows/*", ".github/workflows", "**/*.yml"):
            got = reasons(admit(plan=plan(authorized_scopes=SCOPES + (scope,))))
            self.assertIn(g.SCOPE_TOO_BROAD, got, scope)
            self.assertEqual(g.assess_guardrails(admit(plan=plan(authorized_scopes=(scope,)))).decision, g.DENIED)

    def test_own_fcp12_gate_change_is_protected_even_when_scope_authorizes_it(self):
        # Even an (already refused) scope naming the gate cannot turn its change into an allowed one.
        own_scopes = SCOPES + (".github/workflows/fcp12-self-dogfood.yml",)
        for status in (" M .github/workflows/fcp12-self-dogfood.yml\n", " M .GitHub/Workflows/FCP12-Self-Dogfood.yml\n",
                       "R  scripts/ai/fabric_self_dogfood_guardrails.py -> .github/workflows/fcp12-self-dogfood.yml\n",
                       " D .github/workflows/fcp12-self-dogfood.yml\n", "?? .github/\n"):
            for scopes in (SCOPES, own_scopes):
                got = reasons(confirm(plan=plan(authorized_scopes=scopes),
                                      target_after=target(head=CHECKPOINT, porcelain_status=status)))
                self.assertIn(g.PROTECTED_PATH_CHANGED, got, (status, scopes))
                self.assertNotEqual(g.assess_guardrails(confirm(
                    plan=plan(authorized_scopes=scopes),
                    target_after=target(head=CHECKPOINT, porcelain_status=status))).decision, g.ISOLATION_HOLDS)
        # Traversal / dot-segment aliases of the gate are both protected and out of scope.
        globbed = plan(authorized_scopes=("scripts/*",))
        for status in (" M scripts/../.github/workflows/fcp12-self-dogfood.yml\n",
                       " M scripts/./../.github//workflows/FCP12-self-dogfood.yml\n"):
            got = reasons(confirm(plan=globbed, target_after=target(head=CHECKPOINT, porcelain_status=status)))
            self.assertIn(g.PROTECTED_PATH_CHANGED, got, status)
            self.assertIn(g.SCOPE_VIOLATION, got, status)

    def test_unprotected_workflow_scope_keeps_its_treatment(self):
        scopes = SCOPES + (".github/workflows/other.yml",)
        status = DIRTY_IN_SCOPE + " M .github/workflows/other.yml\n"
        for request in (admit(plan=plan(authorized_scopes=scopes)),
                        confirm(plan=plan(authorized_scopes=scopes),
                                target_after=target(head=CHECKPOINT, porcelain_status=status))):
            self.assertEqual(g.assess_guardrails(request).decision, g.ISOLATION_HOLDS, request.action)


class AuthorityTests(unittest.TestCase):
    def test_external_authorization_is_never_accepted(self):
        for claim in ("approved-by-human", {"approved": True}, True, False, 0, "", object()):
            a = g.assess_guardrails(confirm(external_authorization=claim))
            self.assertEqual(a.decision, g.DENIED)
            self.assertIn(g.EXTERNAL_AUTHORIZATION_NOT_ACCEPTED, a.reasons)
            self.assertIs(a.external_authorization_accepted, False)

    def test_self_promotion_is_always_denied(self):
        a = g.assess_guardrails(confirm(action=g.ACTION_SELF_PROMOTE))
        self.assertEqual((a.decision, a.reasons), (g.DENIED, (g.SELF_PROMOTION_REQUIRES_FCP3_HUMAN_AUTHORIZATION,)))
        self.assertIsNone(a.binding)
        self.assertIs(a.promotion_allowed, False)
        self.assertIs(a.self_promotion_allowed, False)

    def test_assessment_cannot_be_forged(self):
        with self.assertRaises(ValueError):
            g.GuardrailAssessment(decision=g.ISOLATION_HOLDS, reasons=(), action=g.ACTION_SELF_PROMOTE,
                                  binding="0" * 64)
        with self.assertRaises(ValueError):
            g.GuardrailAssessment(decision=g.ISOLATION_HOLDS, reasons=(), action=g.ACTION_ADMIT_ATTEMPT)
        with self.assertRaises(ValueError):
            g.GuardrailAssessment(decision=g.DENIED, reasons=(g.SAME_WORKTREE,), action=g.ACTION_ADMIT_ATTEMPT,
                                  binding="0" * 64)
        with self.assertRaises(ValueError):
            g.GuardrailAssessment(decision=g.ISOLATION_HOLDS, reasons=(g.SAME_WORKTREE,),
                                  action=g.ACTION_ADMIT_ATTEMPT, binding="0" * 64)
        with self.assertRaises(TypeError):
            g.canonical_json({"decision": g.ISOLATION_HOLDS})


class InvalidAndCorruptInputTests(unittest.TestCase):
    def test_invalid_requests(self):
        self.assertEqual(g.assess_guardrails(None).reasons, (g.REQUEST_NOT_TYPED,))
        self.assertEqual(g.assess_guardrails({"action": g.ACTION_ADMIT_ATTEMPT}).decision, g.INVALID_REQUEST)
        for version in (None, 2, "1", True, 1.0):
            self.assertEqual(reasons(admit(schema_version=version)), (g.SCHEMA_UNSUPPORTED,), version)
        for action in (None, "", "admit_attempt", "PROMOTE", 1):
            self.assertEqual(reasons(admit(action=action)), (g.ACTION_UNKNOWN,), action)

    def test_corrupt_inputs_never_raise_and_never_hold(self):
        weird = (None, 0, -1, True, 1.5, "", "x" * 5000, b"\x00", [], {}, (), object(), float("nan"), "\x00")
        builders = {"plan": plan, "controller_before": controller, "target_before": target, "process": process}
        types_ = {"plan": g.IsolationPlan, "controller_before": g.WorktreeSnapshot,
                  "target_before": g.WorktreeSnapshot, "process": g.ControllerProcess}
        for part, builder in builders.items():
            self.assertNotEqual(g.assess_guardrails(admit(**{part: "corrupt"})).decision, g.ISOLATION_HOLDS, part)
            for f in dataclasses.fields(types_[part]):
                baseline = getattr(builder(), f.name)
                for value in weird:
                    if type(value) is type(baseline) and value == baseline:
                        continue  # e.g. "" is the valid clean porcelain status
                    a = g.assess_guardrails(admit(**{part: builder(**{f.name: value})}))
                    self.assertIn(a.decision, (g.DENIED, g.ISOLATION_HOLDS), (part, f.name, value))
                    self.assertEqual(a.decision, g.DENIED, (part, f.name, value))

    def test_contract_version_drift_fails_closed(self):
        with mock.patch.object(dc, "SCHEMA_VERSION", 2):
            self.assertIn(g.CONTRACT_VERSION_UNSUPPORTED, reasons(admit()))


class PurityTests(unittest.TestCase):
    def test_module_imports_no_side_effect_libraries(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("os", "subprocess", "socket", "shutil", "pathlib", "urllib", "http", "time", "random"):
            self.assertNotIn(forbidden, imported)
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("runner_git", {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)})
        self.assertNotIn("git_command(", source)

    def test_assessment_performs_no_io_process_git_or_network(self):
        boom = mock.Mock(side_effect=AssertionError("side effect"))
        with mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(socket, "socket", boom), \
                mock.patch.object(os, "system", boom), mock.patch.object(Path, "resolve", boom), \
                mock.patch.object(os.path, "realpath", boom), mock.patch.object(os.path, "islink", boom):
            self.assertEqual(g.assess_guardrails(admit()).decision, g.ISOLATION_HOLDS)
            self.assertEqual(g.assess_guardrails(confirm()).decision, g.ISOLATION_HOLDS)
            self.assertEqual(g.assess_guardrails(confirm(action=g.ACTION_SELF_PROMOTE)).decision, g.DENIED)
            self.assertIs(g.closure_identity(confirm()).target_isolated, True)
        boom.assert_not_called()


if __name__ == "__main__":
    unittest.main()
