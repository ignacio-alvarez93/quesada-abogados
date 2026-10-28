"""FCP-5A-01: declarative DAG blueprint bridge over the EXISTING Runner pipeline.

Every repository/worktree here is an ephemeral `git init` under a temporary
directory (the same `_make_repo` the Runner pipeline tests use) and every
provider id is one of the Runner tests' `KNOWN` ids; no real project
worktree is ever a target. Refusals the Runner owns are asserted by their
NATIVE `ManifestError` codes. The side-effect tests patch the Runner's
execution entry points, the persistence/write APIs and `subprocess.run` and
assert nothing executes or writes beyond the parser's own read-only
inspection. Nothing here is skipped.
"""

import ast
import builtins
import copy
import dataclasses
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import claude_runner as runner
from scripts.ai import fabric_dag_blueprint as bp
from scripts.ai import fabric_director as fd
from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_pipeline as rp
from scripts.tests.test_runner_pipeline import KNOWN, _git, _make_repo

MODULE_PATH = Path(bp.__file__)
TEST_PATH = Path(__file__).resolve()
REPO_ROOT = TEST_PATH.parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
# sha256 (LF-normalized) of the merged sources at 5862688; FCP-5A-01 must not change them.
# FCP-5B-01 amendment: `scripts/ai/fabric_director.py` is no longer pinned
# whole-file - FCP-5B-01 is the authorized change that adds the Director DAG
# gateway to it. Its single-worker surface is pinned instead, per API and
# more strictly, by DIRECTOR_SINGLE_WORKER_AST_PINS below.
PINNED_SOURCES = {
    "scripts/ai/runner_pipeline.py": "760e6bf3f940afd214918d19863ef381f90266a2f7ae8da6ffdec361d00ce8cc",
    "scripts/ai/fabric_director_cli.py": "0e992a865669f0a63d29f7b8fb35225878605d54c4971add4d5a581b2d16fc83",
    "scripts/tests/test_runner_pipeline.py": "1129beaaf48ec47d00439747556eb0c0b9630bc191371cdee1380cfc182f96e7",
    "scripts/tests/test_fabric_director.py": "93f350d24fa4ae392380d39e1fe56cf76fc89902a0a263a1aad4ff2c57f44d58",
}
WORKFLOW_BASELINE_SHA256 = "853ff0a6820ce296cc52dbf488f298f2dabab143660c2c2d1d4b6166f0fbb7e5"
NEW_CI_STEP_NAME = "FCP-5A-01 DAG blueprint bridge regression without skipped tests"
# FCP-5B-01 amendment: the one other additive step since the baseline above.
FCP5B01_CI_STEP_NAME = "FCP-5B-01 Director DAG gateway regression without skipped tests"

# FCP-5B-01 amendment: version-stable AST digests (see `_ast_digest`) of every
# single-worker Director API, module table and contract as merged at 2ccc522.
# Each must stay identical, except exactly two documented FCP-5B-01 edits
# that the test reverses before comparing: one `_refuse_multiworker_projection`
# guard statement in `result()`/`evidence()`, and `run()`'s PipelineRunner
# block extracted verbatim into `_run_manifest()`.
DIRECTOR_SINGLE_WORKER_AST_PINS = {
    "DirectorError": "ebeccfd10070306fc8cde2104a6ef7758956011bbbbbbb1009ad4dbd2d5f3c18",
    "DirectorWorkOrderSpec": "7a8aa027e2ba3a4140cf4f0567c19683e120e79b16d0dab400701b61dafbc3a4",
    "DirectorRecoverySpec": "64e440803bc7fdbeff3503467ecf8777dadb42c98cc1c030f37e46dede113614",
    "DirectorRunHandle": "4ca2deb9b8fbac58831e4272fef8d681dbd1d35a94018c94f9cd8d90457beb91",
    "DirectorRunSummary": "9ad8af85bee37d0d9ead113c21e839405c80a146c38bad050385a111aa9c4e70",
    "DirectorRunEvidence": "606dd437ccf37d80a32d24542c9050608717aea0c20a07d0c7c5dedf7c656013",
    "DirectorRunDecision": "d059caf09e419a8a8e9aa5e3f8ad4524dbbdbff6f921c910a863bcf0da3e95de",
    "_TRANSIENT_WORKER_STATES": "f3378d2dd56446da4ceb2e042c59900cec41702f3b29dd51b8db1037a8e00192",
    "_classify_decision": "5d8ccd9874a13bce9abd2755f71c2e0940b1eb1137b965bab229468b251c8a2f",
    "_DECISION_MAP": "1f2851773ba594abee229eaf6e9fc3a11cba9c95b4dc6c992e3e401999e6953b",
    "_decision_for": "66008c189a2c65a28d6e4c42e8bc191d0c298445c3fe36fc39ed36913038396b",
    "_project_evidence_complete": "b54218a0087ceac5b5c16a387eb2e8e28f2f6c49217568516d9ff766d3501749",
    "_classify_completion_mode": "50b9a46b9e4652a791025489a5b2c9ec62f0aa55fc1e33fdce2e1f4086beefa0",
    "_RECOVERY_ELIGIBLE_DECISION_CODES": "5a913179a3946829cae95a51b843d55aa43f9869bad2a4c6bca9ec493c1a38ed",
    "_RECOVERY_RESERVED_METADATA_KEYS": "980400437af74f11b94a4097411998572056ff1ed060627e12b9482b1c4380e3",
    "_resolve_recovery_completion": "9bf350260494d5502f6e3f1741da0f4a24a606e7d6308496cfe3bced3464ea65",
    "build_audit_spec": "5a4388d35100142a180a18aa84bae3ec2f6e96fa9ffe4183d5fcac551bedb680",
    "_validate_assessment_inputs": "ef7f134b07808ef3d8a3493744ebdc0e740a1c029db07a36f643bd570a75ea4e",
    "FabricDirectorService.__init__": "21d609672a374de04155753a028ed03c7a7820ebf4caea195bd4972552dad380",
    "FabricDirectorService.project_state": "0b2bacacdc85128bb63ada7c16a5d3c3c91adb7edf921412386cdbb4ef47680f",
    "FabricDirectorService._generate_pipeline_id": "1468e742cc2b980a2a6cbea2267f86cd95f34aa9919ba1d3de24332c44957a21",
    "FabricDirectorService._validate_spec": "c988b231037fa02db1fe4313de2ef71e6bdeb08fe802759f2442819c61c81794",
    "FabricDirectorService._build_manifest_data": "b29f4124a618968cf5d434bd73d21062139e4bfd9194d058ffa4035f4a18bb0c",
    "FabricDirectorService.submit": "fd96043bb2af9218d254b4e264a8a45af127f79db54aa6cdb2a36e78005cbcbf",
    "FabricDirectorService._submit": "96f09bf9a9e7424fa0eda767e03ad4d9de1533e77025a8be258d01aa5d28b2f2",
    "FabricDirectorService._prior_completion_contract":
        "ce59e199409daf0c04b4affd3e107d21abc177bf6974e29451954bbab4777b16",
    "FabricDirectorService.recover": "0f8c716393aa24972243994e97fa6d6bf1ab455954a579aa9a097419cdd10bb3",
    "FabricDirectorService.validate": "ae957f01c39c0c53a94c7d5feda1539659fd62f184ac182bea00522d6d19c42a",
    "FabricDirectorService.run": "6e197e0868a867dd47daa6a7756d6aee2a3f837379ed5897b8d5b7060a2910a4",
    "FabricDirectorService.submit_and_run": "be253e0144c92dbb02cce88a7175be6673d7bb9697ff0d425203c8c049434205",
    "FabricDirectorService.status": "6577fe8abe4679072a47bc2f4b109f8b875c3096e135ac92d799653b79213ef5",
    "FabricDirectorService._load_json": "66ff5d1a3c57b7716f68e8b2c9f4cc5bb3bcb8f89ca9a89bb54bd2b7d631c7e0",
    "FabricDirectorService.result": "e09038de705cfad4fe26380a7a6d4ddc8b14793183b362857e4d1aabcf5b3503",
    "FabricDirectorService.evidence": "3436b189c4366e2208a40552aef809e802c67e31625ef082dcc1570adf7e1f6d",
    "FabricDirectorService.decision": "3c90c2ed726dc515f5d505e626bfb5d45011d0d429f1b674683e43e6a9b484a9",
    "FabricDirectorService.integration_ledger_root": "2e60272513809e315aa40c0dcba943dd2c63e6f29661667de966cd169453ed2f",
    "FabricDirectorService.assess_integration": "1f5c7e0b48f143dd27f9a1d9d36e62b173b7fac04bd4c69fe9fb78dfdccce478",
    "FabricDirectorService.assess_reconciliation": "6d892ad5960d13cfa5ee1ee7083e2b05de37437f339213eb6147c29aa2478fa6",
    "FabricDirectorService.propose_reconciliation_plan":
        "3b51bed024a35c79bf1bc051a2c3b5ede6351095d19ceb8070a00131a0ce3484",
    "FabricDirectorService.validate_reconciliation_plan":
        "a4f1d539f96c911b74d00f3cf466db5e260854896e0ed68fbf48a57e9b7115a5",
    "FabricDirectorService.inventory_worktrees": "4228b1ba8ba9f685bf72d1c09ca86d9538e2ec49220902207a02dd3c98727348",
    "FabricDirectorService.assess_worktree_retirement":
        "ae6a6134c131f61614e90ea56a99ca7079d639d93fef31786813f2e080d9dca0",
    "FabricDirectorService.factory_state": "cef4262ed824a2cb85247d98290521256a4f74aa9da810de15694fde1cc371e5",
}
FCP5B01_GUARDED_PROJECTIONS = ("FabricDirectorService.result", "FabricDirectorService.evidence")
FCP5B01_GUARD = "_refuse_multiworker_projection"
FCP5B01_RUN_HELPER = "_run_manifest"

MUTATING_GIT_SUBCOMMANDS = {
    "add", "am", "branch", "checkout", "cherry-pick", "clean", "commit", "fetch", "gc", "init", "merge", "mv",
    "prune", "pull", "push", "rebase", "reset", "restore", "revert", "rm", "stash", "switch", "tag",
    "update-ref", "worktree",
}


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _ast_shape(node):
    """Structure-only AST serialization. None/empty fields are dropped so a
    field newer Pythons add with an empty default (e.g. `type_params`) does
    not change the digest; positions and formatting never enter it."""
    if isinstance(node, ast.AST):
        return [type(node).__name__,
                [[name, _ast_shape(value)] for name, value in ast.iter_fields(node)
                 if value is not None and value != []]]
    if isinstance(node, list):
        return [_ast_shape(value) for value in node]
    return repr(node)


def _ast_digest(node) -> str:
    return hashlib.sha256(json.dumps(_ast_shape(node), separators=(",", ":")).encode("utf-8")).hexdigest()


def _is_self_call(stmt, method: str, args: tuple) -> bool:
    return (
        isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and not stmt.value.keywords
        and isinstance(stmt.value.func, ast.Attribute) and stmt.value.func.attr == method
        and isinstance(stmt.value.func.value, ast.Name) and stmt.value.func.value.id == "self"
        and [getattr(a, "id", None) for a in stmt.value.args] == list(args)
    )


def _tree_snapshot(root: Path) -> dict:
    snapshot = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            stat = path.stat()
            snapshot[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


class BlueprintTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.stable = _make_repo(self.root, "stable")
        self.repos = {n: _make_repo(self.root, n) for n in ("a", "b", "c", "d")}
        for repo in self.repos.values():
            _git(repo, "checkout", "-q", "-b", "feature/fcp5a01-test")
        self.wos = {}
        for name in ("a", "b", "c", "d"):
            path = self.root / "work_orders" / f"wo_{name}.md"
            path.parent.mkdir(exist_ok=True)
            path.write_text(f"Work Order {name}.\n", encoding="utf-8")
            self.wos[name] = path

    def node(self, nid, repo=None, *, depends_on=(), provider="claude", mode="read-only", **extra):
        repo = repo or nid
        return bp.BlueprintNode(
            id=nid, worktree=str(self.repos.get(repo, repo)), work_order=str(self.wos.get(repo, self.wos["a"])),
            provider=provider, mode=mode, depends_on=depends_on, **extra,
        )

    def blueprint(self, nodes, pipeline_id="fcp5a01-dag", **extra):
        return bp.DagBlueprint(pipeline_id=pipeline_id, nodes=tuple(nodes), **extra)

    def compile(self, blueprint, **kw):
        kw.setdefault("self_worktree", self.stable)
        kw.setdefault("registered_providers", KNOWN)
        return bp.compile_blueprint(blueprint, **kw)

    def assertNative(self, blueprint, code, **kw):
        with self.assertRaises(rp.ManifestError) as ctx:
            self.compile(blueprint, **kw)
        self.assertIn(code, [e["code"] for e in ctx.exception.errors])
        return ctx.exception

    def assertAdapter(self, blueprint, code):
        with mock.patch.object(rp, "parse_manifest", side_effect=AssertionError("parser must not run")) as spy:
            with self.assertRaises(bp.BlueprintError) as ctx:
                self.compile(blueprint)
        spy.assert_not_called()
        self.assertIn(code, [e["code"] for e in ctx.exception.errors])
        return ctx.exception

    def edges(self, manifest):
        return {s.id: list(s.depends_on) for s in manifest.workers}


# ---------------------------------------------------------------------------
class GraphShapeTests(BlueprintTestBase):
    def test_two_node_chain(self):
        result = self.compile(self.blueprint([self.node("a"), self.node("b", depends_on=("a",))]))
        self.assertIsInstance(result.manifest, rp.Manifest)
        self.assertEqual(self.edges(result.manifest), {"a": [], "b": ["a"]})
        self.assertEqual([n.id for n in result.plan.nodes], ["a", "b"])
        self.assertEqual(result.plan.nodes[1].depends_on, ("a",))
        self.assertEqual(result.plan.status, bp.STATUS_STRUCTURALLY_VALID)
        self.assertTrue(bp.verify_plan(result.plan))

    def test_fan_out_fan_in(self):
        result = self.compile(self.blueprint([
            self.node("a"), self.node("b", depends_on=("a",)), self.node("c", depends_on=("a",)),
            self.node("d", depends_on=("b", "c")),
        ]))
        self.assertEqual(self.edges(result.manifest), {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]})

    def test_independent_nodes(self):
        result = self.compile(self.blueprint([self.node("a"), self.node("b")]))
        self.assertEqual(self.edges(result.manifest), {"a": [], "b": []})

    def test_dependency_meaning_independent_of_declaration_order(self):
        forward = self.compile(self.blueprint([
            self.node("a"), self.node("b", depends_on=("a",)), self.node("c", depends_on=("a",)),
            self.node("d", depends_on=("b", "c")),
        ]))
        reverse = self.compile(self.blueprint([
            self.node("d", depends_on=("b", "c")), self.node("c", depends_on=("a",)),
            self.node("b", depends_on=("a",)), self.node("a"),
        ]))
        self.assertEqual(self.edges(forward.manifest), self.edges(reverse.manifest))
        # Declared order is forwarded verbatim (Runner tie-break), never re-sorted here.
        self.assertEqual([s.id for s in reverse.manifest.workers], ["d", "c", "b", "a"])
        self.assertEqual([w["id"] for w in json.loads(reverse.plan.manifest_json)["workers"]], ["d", "c", "b", "a"])

    def test_edges_forwarded_verbatim_including_order_and_no_inference(self):
        result = self.compile(self.blueprint([
            self.node("a"), self.node("b"), self.node("c", depends_on=("b", "a")),
        ]))
        self.assertEqual(self.edges(result.manifest), {"a": [], "b": [], "c": ["b", "a"]})

    def test_claude_and_codex_providers_are_neutral(self):
        result = self.compile(self.blueprint([
            self.node("a", provider="claude"), self.node("b", provider="codex", depends_on=("a",)),
        ]))
        self.assertEqual([s.provider for s in result.manifest.workers], ["claude", "codex"])
        self.assertEqual([n.provider for n in result.plan.nodes], ["claude", "codex"])


# ---------------------------------------------------------------------------
class PassThroughTests(BlueprintTestBase):
    def full_write_node(self):
        return self.node(
            "b", depends_on=("a",), provider="codex", mode="write", dependency_policy="success_or_partial",
            priority=7, model="m-1", required_capabilities=("EDIT_FILES",), authorize_path=("src/feature",),
            allow_shell=True, checkpoint_policy="ON_SUCCESS", timeout_seconds=600, max_attempts=3,
            backoff_seconds=2.5, completion_policy="runner_acceptance",
            acceptance_commands=("python -m unittest scripts.tests.test_x",),
        )

    def test_native_worker_spec_equals_declared_meaning(self):
        result = self.compile(self.blueprint([self.node("a"), self.full_write_node()]))
        spec = result.manifest.workers[1]
        self.assertIsInstance(spec, rp.WorkerSpec)
        expected = {
            "id": "b", "worktree": str(self.repos["b"]), "work_order": str(self.wos["b"]), "provider": "codex",
            "mode": "write", "depends_on": ["a"], "dependency_policy": "success_or_partial", "priority": 7,
            "model": "m-1", "required_capabilities": ["EDIT_FILES"], "authorize_path": ["src/feature"],
            "allow_shell": True, "checkpoint_policy": "ON_SUCCESS", "timeout_seconds": 600, "max_attempts": 3,
            "backoff_seconds": 2.5, "completion_policy": "runner_acceptance",
            "acceptance_commands": ["python -m unittest scripts.tests.test_x"],
            "fallback_providers": [], "metadata": {}, "resume_from": None,
            "worktree_top": str(self.repos["b"]),
        }
        self.assertEqual(spec.to_dict(), expected)
        node = result.plan.nodes[1]
        self.assertEqual(
            (node.provider, node.mode, node.depends_on, node.dependency_policy, node.priority, node.allow_shell),
            ("codex", "write", ("a",), "success_or_partial", 7, True),
        )

    def test_omitted_options_are_absent_and_take_runner_defaults(self):
        result = self.compile(self.blueprint([self.node("a"), self.node("b", depends_on=("a",))]))
        workers = json.loads(result.plan.manifest_json)["workers"]
        for worker in workers:
            self.assertEqual(set(worker), {"id", "worktree", "work_order", "provider", "mode", "depends_on"})
        default = rp.WorkerSpec(id="x", worktree="", work_order="")
        for spec in result.manifest.workers:
            for name in ("dependency_policy", "priority", "model", "required_capabilities", "authorize_path",
                         "allow_shell", "checkpoint_policy", "timeout_seconds", "max_attempts", "backoff_seconds",
                         "completion_policy", "acceptance_commands", "fallback_providers", "metadata",
                         "resume_from"):
                self.assertEqual(getattr(spec, name), getattr(default, name), name)
        self.assertNotIn("max_workers", json.loads(result.plan.manifest_json))

    def test_pipeline_level_options_forwarded_only_when_explicit(self):
        result = self.compile(self.blueprint(
            [self.node("a", provider="codex"), self.node("b")], max_workers=2, provider_limits=(("codex", 1),),
            not_before_utc="2026-10-28T22:00:00+00:00", deadline_utc="2026-10-29T06:00:00+00:00",
        ))
        m = result.manifest
        self.assertEqual((m.max_workers, m.provider_limits), (2, {"codex": 1}))
        self.assertEqual((m.not_before_utc, m.deadline_utc), ("2026-10-28T22:00:00+00:00", "2026-10-29T06:00:00+00:00"))

    def test_unsupported_v1_fields_do_not_exist(self):
        for name in ("fallback_providers", "metadata", "resume_from", "dependencies", "worktree_top"):
            self.assertNotIn(name, {f.name for f in dataclasses.fields(bp.BlueprintNode)}, name)
            with self.assertRaises(TypeError):
                self.node("a", **{name: None})

    def test_source_declaration_is_never_mutated(self):
        blueprint = self.blueprint([self.node("a"), self.full_write_node()], provider_limits=(("codex", 1),))
        before = copy.deepcopy(blueprint)
        data = bp.compose_manifest_data(blueprint)
        data["workers"][1]["depends_on"].append("zzz")
        data["workers"][1]["authorize_path"].append("../escape")
        self.compile(blueprint)
        self.assertEqual(blueprint, before)
        self.assertEqual(blueprint.nodes[1].depends_on, ("a",))
        self.assertEqual(blueprint.nodes[1].authorize_path, ("src/feature",))

    def test_declarations_are_frozen(self):
        node = self.node("a")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            node.mode = "write"
        blueprint = self.blueprint([node, self.node("b")])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            blueprint.nodes = ()


# ---------------------------------------------------------------------------
class PlanPreviewTests(BlueprintTestBase):
    def make(self):
        return self.blueprint([self.node("a"), self.node("b", depends_on=("a",), provider="codex")])

    def test_preview_is_deterministic_and_canonical(self):
        first, second = self.compile(self.make()), self.compile(self.make())
        self.assertEqual(bp.canonical_plan_json(first.plan), bp.canonical_plan_json(second.plan))
        self.assertEqual(first.plan.fingerprint, second.plan.fingerprint)
        self.assertEqual(first.plan, second.plan)
        self.assertEqual(first.plan.fingerprint, bp.plan_fingerprint(first.plan))
        self.assertRegex(first.plan.fingerprint, r"^[0-9a-f]{64}$")

    def test_manifest_digest_is_runners_own(self):
        result = self.compile(self.make())
        data = json.loads(result.plan.manifest_json)
        self.assertEqual(data, bp.compose_manifest_data(self.make()))
        self.assertEqual(result.plan.manifest_sha256, result.manifest.sha256)
        self.assertEqual(result.manifest.raw, data)

    def test_different_meaning_changes_fingerprint(self):
        base = self.compile(self.make()).plan
        other = self.compile(self.blueprint([self.node("a"), self.node("b", provider="codex")])).plan
        self.assertNotEqual(base.fingerprint, other.fingerprint)

    def test_plan_states_structural_validity_only(self):
        plan = self.compile(self.make()).plan
        self.assertEqual(plan.schema, bp.PLAN_SCHEMA)
        self.assertEqual(plan.marker, bp.PLAN_MARKER)
        self.assertIn("NOT_EXECUTED", plan.marker)
        self.assertIn("NOT_A_PERMIT", plan.marker)
        for flag in ("executed", "approved", "merged", "integrated", "execution_permit"):
            self.assertIs(getattr(plan, flag), False, flag)
        self.assertEqual(plan.execution_time_guards_not_evaluated, bp.EXECUTION_TIME_GUARDS_NOT_EVALUATED)
        self.assertIn("BRANCH_GUARD", plan.execution_time_guards_not_evaluated)

    def test_constant_flags_are_not_constructor_arguments(self):
        plan = self.compile(self.make()).plan
        for flag in ("executed", "approved", "merged", "integrated", "execution_permit", "status", "marker", "schema"):
            with self.assertRaises(ValueError):
                dataclasses.replace(plan, **{flag: True})
        with self.assertRaises(TypeError):
            bp.BlueprintPlan(pipeline_id="p", nodes=(), manifest_json="{}", manifest_sha256="", fingerprint="",
                             approved=True)

    def test_plan_is_frozen_and_tamper_is_refused(self):
        plan = self.compile(self.make()).plan
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.executed = True
        tampers = {
            "executed": True, "approved": True, "execution_permit": True, "status": "APPROVED",
            "manifest_json": plan.manifest_json.replace('"read-only"', '"write"'),
            "nodes": plan.nodes[:1], "pipeline_id": "other", "manifest_sha256": "0" * 64,
            "execution_time_guards_not_evaluated": (),
        }
        for name, value in tampers.items():
            forged = copy.copy(plan)
            object.__setattr__(forged, name, value)
            self.assertFalse(bp.verify_plan(forged), name)
        forged = copy.copy(plan)
        object.__setattr__(forged, "approved", True)
        object.__setattr__(forged, "fingerprint", bp.plan_fingerprint(forged))
        self.assertFalse(bp.verify_plan(forged))
        self.assertFalse(bp.verify_plan(dataclasses.asdict(plan)))
        self.assertTrue(bp.verify_plan(plan))

    def test_preview_carries_no_secret_or_metadata_surface(self):
        secret = "sk-fcp5a01-SHOULD-NEVER-APPEAR"
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": secret, "GITHUB_TOKEN": secret}):
            rendered = bp.canonical_plan_json(self.compile(self.make()).plan)
        self.assertNotIn(secret, rendered)
        for word in ("metadata", "resume_from", "fallback_providers", "token", "envelope", "signature"):
            self.assertNotIn(word, rendered, word)


# ---------------------------------------------------------------------------
class NativeRefusalTests(BlueprintTestBase):
    """Every refusal here is the Runner parser's, surfaced by native code."""

    def test_empty_graph(self):
        self.assertNative(self.blueprint([]), "NO_WORKERS")

    def test_duplicate_ids(self):
        self.assertNative(self.blueprint([self.node("a"), self.node("a", "b")]), "DUPLICATE_WORKER_ID")

    def test_unknown_dependency(self):
        self.assertNative(self.blueprint([self.node("a"), self.node("b", depends_on=("zz",))]), "UNKNOWN_DEPENDENCY")

    def test_self_dependency(self):
        self.assertNative(self.blueprint([self.node("a"), self.node("b", depends_on=("b",))]), "SELF_DEPENDENCY")

    def test_cycles(self):
        self.assertNative(self.blueprint([
            self.node("a", depends_on=("b",)), self.node("b", depends_on=("a",)),
        ]), "DEPENDENCY_CYCLE")
        self.assertNative(self.blueprint([
            self.node("a", depends_on=("c",)), self.node("b", depends_on=("a",)), self.node("c", depends_on=("b",)),
        ]), "DEPENDENCY_CYCLE")

    def test_unknown_provider(self):
        self.assertNative(self.blueprint([self.node("a"), self.node("b", provider="nonexistent")]), "UNKNOWN_PROVIDER")

    def test_invalid_mode(self):
        self.assertNative(self.blueprint([self.node("a"), self.node("b", mode="root")]), "INVALID_MODE")

    def test_malformed_worktrees(self):
        missing = self.root / "does-not-exist"
        plain = self.root / "plain-dir"
        plain.mkdir()
        for target in (missing, plain):
            self.assertNative(self.blueprint([self.node("a"), self.node("b", str(target))]), "INVALID_WORKTREE")

    def test_missing_or_empty_work_order(self):
        empty = self.root / "empty.md"
        empty.write_text("   \n", encoding="utf-8")
        for path in (self.root / "missing.md", empty):
            node = dataclasses.replace(self.node("b"), work_order=str(path))
            self.assertNative(self.blueprint([self.node("a"), node]), "INVALID_WORK_ORDER")

    def test_write_mode_self_target(self):
        self.assertNative(self.blueprint([
            self.node("a"), self.node("b", str(self.stable), mode="write", authorize_path=("src",)),
        ]), "SELF_MODIFICATION_REFUSED")
        # Read-only on the same worktree stays the Runner's to allow.
        self.compile(self.blueprint([self.node("a"), self.node("b", str(self.stable))]))

    def test_omitted_self_worktree_uses_runners_default_never_disables_guard(self):
        blueprint = self.blueprint([self.node("a"), self.node("b", mode="write", authorize_path=("src",))])
        with mock.patch.object(rp, "default_self_worktree", return_value=self.repos["b"]) as default:
            self.assertNative(blueprint, "SELF_MODIFICATION_REFUSED", self_worktree=None)
        default.assert_called_once_with()

    def test_protected_develop_stays_a_runner_execution_time_guard(self):
        develop = _make_repo(self.root, "develop_repo")
        _git(develop, "checkout", "-q", "-b", "develop")
        plan = self.compile(self.blueprint([
            self.node("a"), self.node("b", str(develop), mode="write", authorize_path=("src",)),
        ])).plan
        # The parser owns no branch rule, so the adapter adds none, fixes nothing and claims nothing.
        self.assertEqual(plan.nodes[1].mode, "write")
        self.assertIn("BRANCH_GUARD", plan.execution_time_guards_not_evaluated)
        self.assertFalse(plan.execution_permit)
        decision = runner.evaluate_branch_guard(runner.capture_git_snapshot(develop))
        self.assertEqual(decision.decision, "REFUSED_PROTECTED_BRANCH")

    def test_invalid_dependency_policy(self):
        self.assertNative(self.blueprint([
            self.node("a"), self.node("b", depends_on=("a",), dependency_policy="whenever"),
        ]), "INVALID_DEPENDENCY_POLICY")

    def test_invalid_concurrency_limits(self):
        nodes = [self.node("a"), self.node("b")]
        for value in (0, rp.MAX_PIPELINE_WORKERS + 1, True):
            self.assertNative(self.blueprint(nodes, max_workers=value), "INVALID_MAX_WORKERS")
        self.assertNative(self.blueprint(nodes, provider_limits=(("claude", 0),)), "INVALID_PROVIDER_LIMITS")
        self.assertNative(self.blueprint(nodes, provider_limits=(("ghost", 1),)), "INVALID_PROVIDER_LIMITS")

    def test_allow_shell_mismatch(self):
        self.assertNative(self.blueprint([self.node("a"), self.node("b", allow_shell=True)]),
                          "ALLOW_SHELL_REQUIRES_WRITE_MODE")
        self.assertNative(self.blueprint([self.node("a"), self.node("b", allow_shell="yes")]), "INVALID_ALLOW_SHELL")

    def test_checkpoint_and_completion_mismatches(self):
        self.assertNative(self.blueprint([self.node("a"), self.node("b", checkpoint_policy="ON_SUCCESS")]),
                          "CHECKPOINT_POLICY_REQUIRES_WRITE_MODE")
        self.assertNative(self.blueprint([self.node("a"), self.node("b", completion_policy="runner_acceptance")]),
                          "RUNNER_ACCEPTANCE_REQUIRES_ACCEPTANCE_COMMANDS")

    def test_invalid_scalar_and_element_types_are_runners(self):
        cases = {
            "INVALID_PRIORITY": {"priority": "high"},
            "INVALID_TIMEOUT": {"timeout_seconds": 0},
            "INVALID_MAX_ATTEMPTS": {"max_attempts": 99},
            "INVALID_BACKOFF": {"backoff_seconds": -1},
            "INVALID_MODEL": {"model": 5},
            "INVALID_CAPABILITIES": {"required_capabilities": (1,)},
            "INVALID_AUTHORIZE_PATH": {"authorize_path": (None,)},
            "INVALID_ACCEPTANCE_COMMANDS": {"acceptance_commands": ("",)},
        }
        for code, extra in cases.items():
            self.assertNative(self.blueprint([self.node("a"), self.node("b", **extra)]), code)
        self.assertNative(self.blueprint([self.node("a"), self.node("b", depends_on=(1,))]), "INVALID_DEPENDENCIES")
        self.assertNative(self.blueprint([self.node("a"), self.node("b", provider=None)]), "UNKNOWN_PROVIDER")

    def test_identifier_injection(self):
        nodes = [self.node("a"), self.node("b")]
        for pid in ("../evil", "a/b", "", ".hidden", "x" * 65):
            self.assertNative(self.blueprint(nodes, pipeline_id=pid), "INVALID_PIPELINE_ID")
        for wid in ("../x", "a\\b", "..", 7):
            self.assertNative(self.blueprint([self.node("a"), dataclasses.replace(self.node("b"), id=wid)]),
                              "INVALID_WORKER_ID")

    def test_scope_injection_is_forwarded_verbatim_and_refused_by_runner(self):
        node = self.node("b", mode="write", authorize_path=("../outside",))
        plan = self.compile(self.blueprint([self.node("a"), node])).plan
        self.assertEqual(json.loads(plan.manifest_json)["workers"][1]["authorize_path"], ["../outside"])
        self.assertIn("WRITE_SCOPE", plan.execution_time_guards_not_evaluated)
        self.assertEqual(runner.evaluate_write_scope(["../outside"]).decision, "REFUSED_INVALID_SCOPE")

    def test_all_native_errors_are_reported_together(self):
        exc = self.assertNative(self.blueprint([
            self.node("a", provider="ghost"), self.node("b", depends_on=("zz",), dependency_policy="bad"),
        ]), "UNKNOWN_PROVIDER")
        codes = {e["code"] for e in exc.errors}
        self.assertTrue({"UNKNOWN_PROVIDER", "UNKNOWN_DEPENDENCY", "INVALID_DEPENDENCY_POLICY"} <= codes)

    def test_manifest_error_propagates_unchanged(self):
        native = rp.ManifestError([{"code": "NATIVE_SENTINEL", "worker": None, "message": "x"}])
        with mock.patch.object(rp, "parse_manifest", side_effect=native):
            with self.assertRaises(rp.ManifestError) as ctx:
                self.compile(self.blueprint([self.node("a"), self.node("b")]))
        self.assertIs(ctx.exception, native)
        self.assertFalse(isinstance(ctx.exception, bp.BlueprintError))


# ---------------------------------------------------------------------------
class AdapterRefusalTests(BlueprintTestBase):
    """Declaration-integrity refusals raised BEFORE delegation."""

    def test_wrong_container_types(self):
        good = self.blueprint([self.node("a"), self.node("b")])
        self.assertAdapter(dataclasses.asdict(good), "BLUEPRINT_INVALID_TYPE")
        self.assertAdapter(None, "BLUEPRINT_INVALID_TYPE")
        self.assertAdapter(bp.DagBlueprint(pipeline_id="p", nodes=list(good.nodes)), "BLUEPRINT_NOT_IMMUTABLE")
        self.assertAdapter(self.blueprint([self.node("a"), dataclasses.asdict(self.node("b"))]),
                           "BLUEPRINT_INVALID_TYPE")

    def test_mutable_sequences_refused(self):
        self.assertAdapter(self.blueprint([self.node("a"), self.node("b", depends_on=["a"])]),
                           "BLUEPRINT_NOT_IMMUTABLE")
        for name in ("required_capabilities", "authorize_path", "acceptance_commands"):
            self.assertAdapter(self.blueprint([self.node("a"), self.node("b", **{name: ["x"]})]),
                               "BLUEPRINT_NOT_IMMUTABLE")
        nodes = [self.node("a"), self.node("b")]
        self.assertAdapter(self.blueprint(nodes, provider_limits={"claude": 1}), "BLUEPRINT_NOT_IMMUTABLE")
        self.assertAdapter(self.blueprint(nodes, provider_limits=(["claude", 1],)), "BLUEPRINT_NOT_IMMUTABLE")

    def test_provider_limit_pairs(self):
        nodes = [self.node("a"), self.node("b")]
        self.assertAdapter(self.blueprint(nodes, provider_limits=(("claude", 1), ("claude", 2))),
                           "BLUEPRINT_DUPLICATE_PROVIDER_LIMIT")
        self.assertAdapter(self.blueprint(nodes, provider_limits=((["claude"], 1),)), "BLUEPRINT_INVALID_TYPE")

    def test_node_count_bounds(self):
        self.assertAdapter(self.blueprint([self.node("a")]), "BLUEPRINT_TOO_FEW_NODES")
        many = [dataclasses.replace(self.node("a"), id=f"n{i}") for i in range(bp.MAX_BLUEPRINT_NODES + 1)]
        self.assertAdapter(self.blueprint(many), "BLUEPRINT_TOO_MANY_NODES")

    def test_paths_must_be_explicit_absolute_strings(self):
        for field_name, value, code in (
            ("worktree", "a", "BLUEPRINT_PATH_NOT_ABSOLUTE"),
            ("worktree", "", "BLUEPRINT_PATH_NOT_ABSOLUTE"),
            ("worktree", 5, "BLUEPRINT_INVALID_TYPE"),
            ("worktree", None, "BLUEPRINT_INVALID_TYPE"),
            ("work_order", "work_orders/wo_b.md", "BLUEPRINT_PATH_NOT_ABSOLUTE"),
            ("work_order", Path(self.wos["b"]), "BLUEPRINT_INVALID_TYPE"),
            ("worktree", str(self.repos["b"]) + "\x00", "BLUEPRINT_PATH_INVALID"),
            ("work_order", str(self.wos["b"]) + "\n--evil", "BLUEPRINT_PATH_INVALID"),
        ):
            node = dataclasses.replace(self.node("b"), **{field_name: value})
            self.assertAdapter(self.blueprint([self.node("a"), node]), code)

    def test_adapter_errors_are_aggregated(self):
        exc = self.assertAdapter(self.blueprint([
            dataclasses.replace(self.node("a"), worktree="rel"), self.node("b", depends_on=["a"]),
        ]), "BLUEPRINT_PATH_NOT_ABSOLUTE")
        self.assertEqual({e["code"] for e in exc.errors}, {"BLUEPRINT_PATH_NOT_ABSOLUTE", "BLUEPRINT_NOT_IMMUTABLE"})
        self.assertEqual({e["worker"] for e in exc.errors}, {"a", "b"})
        self.assertEqual(bp.blueprint_errors(self.blueprint([self.node("a"), self.node("b")])), ())

    def test_relative_path_sentinel_fails_closed_in_the_native_parser(self):
        data = bp.compose_manifest_data(self.blueprint([self.node("a"), self.node("b")]))
        data["workers"][1]["worktree"] = "b"
        data["workers"][1]["work_order"] = "wo_b.md"
        with self.assertRaises(rp.ManifestError) as ctx:
            rp.parse_manifest(data, bp._ABSOLUTE_PATHS_ONLY_BASE_DIR, self_worktree=self.stable,
                              registered_providers=KNOWN)
        codes = {e["code"] for e in ctx.exception.errors}
        self.assertTrue({"INVALID_WORKTREE", "INVALID_WORK_ORDER"} <= codes)
        self.assertFalse(Path(bp._ABSOLUTE_PATHS_ONLY_BASE_DIR).is_absolute())


# ---------------------------------------------------------------------------
class DelegationAndNoExecutionTests(BlueprintTestBase):
    def make(self):
        return self.blueprint([
            self.node("a"), self.node("b", depends_on=("a",), mode="write", authorize_path=("src",)),
            self.node("c", depends_on=("a",), provider="codex"), self.node("d", depends_on=("b", "c")),
        ])

    def test_parse_manifest_called_exactly_once_with_native_arguments(self):
        blueprint = self.make()
        returned = []
        real_parse = rp.parse_manifest

        def spy_parse(*args, **kwargs):
            returned.append(real_parse(*args, **kwargs))
            return returned[-1]

        with mock.patch.object(rp, "parse_manifest", side_effect=spy_parse) as spy:
            result = self.compile(blueprint)
        self.assertEqual(spy.call_count, 1)
        args, kwargs = spy.call_args
        self.assertEqual(args, (bp.compose_manifest_data(blueprint), bp._ABSOLUTE_PATHS_ONLY_BASE_DIR))
        self.assertEqual(kwargs, {"self_worktree": self.stable, "registered_providers": KNOWN})
        self.assertIs(result.manifest, returned[0])

    def test_registered_providers_none_means_runners_own_registry(self):
        with mock.patch.object(rp, "parse_manifest", wraps=rp.parse_manifest) as spy:
            self.compile(self.blueprint([self.node("a"), self.node("b", provider="codex")]),
                         registered_providers=None)
        self.assertIsNone(spy.call_args.kwargs["registered_providers"])

    def test_no_second_graph_validator_runs(self):
        with mock.patch.object(rp, "_find_cycle", wraps=rp._find_cycle) as cycle:
            self.compile(self.make())
        self.assertEqual(cycle.call_count, 1)  # the parser's own, once
        with mock.patch.object(rp, "parse_manifest", side_effect=rp.ManifestError([])):
            with mock.patch.object(rp, "_find_cycle", side_effect=AssertionError("adapter ran a validator")):
                with self.assertRaises(rp.ManifestError):
                    self.compile(self.blueprint([self.node("a", depends_on=("b",)), self.node("b", depends_on=("a",))]))

    def test_nothing_executes_and_nothing_is_written(self):
        boom = AssertionError("blueprint compile must not execute or write")
        git_calls = []
        real_run = subprocess.run
        real_open = builtins.open

        def spy_run(cmd, *args, **kwargs):
            argv = [str(a) for a in cmd]
            git_calls.append(argv)
            if "git" not in Path(argv[0]).name.lower():
                raise boom
            if MUTATING_GIT_SUBCOMMANDS & set(argv):
                raise boom
            return real_run(cmd, *args, **kwargs)

        def guarded_open(file, mode="r", *args, **kwargs):
            if any(ch in mode for ch in "wax+"):
                raise boom
            return real_open(file, mode, *args, **kwargs)

        heads = {n: _git(r, "rev-parse", "HEAD").stdout for n, r in self.repos.items()}
        before = _tree_snapshot(self.root)
        patches = [
            mock.patch.object(rp.PipelineRunner, "__init__", side_effect=boom),
            mock.patch.object(rp.PipelineRunner, "run", side_effect=boom),
            mock.patch.object(runner, "execute_work_order", side_effect=boom),
            mock.patch.object(runner, "create_checkpoint", side_effect=boom),
            mock.patch.object(runner, "create_run_dir", side_effect=boom),
            mock.patch.object(flog, "FactoryLedger", side_effect=boom),
            mock.patch.object(fd.FabricDirectorService, "submit", side_effect=boom),
            mock.patch.object(fd.FabricDirectorService, "run", side_effect=boom),
            mock.patch("subprocess.run", side_effect=spy_run),
            mock.patch.object(subprocess, "call", side_effect=boom),
            mock.patch.object(subprocess, "check_call", side_effect=boom),
            mock.patch("builtins.open", side_effect=guarded_open),
            mock.patch("io.open", side_effect=guarded_open),
            mock.patch.object(Path, "write_text", side_effect=boom),
            mock.patch.object(Path, "write_bytes", side_effect=boom),
            mock.patch.object(Path, "mkdir", side_effect=boom),
            mock.patch.object(Path, "touch", side_effect=boom),
            mock.patch.object(Path, "unlink", side_effect=boom),
            mock.patch.object(Path, "rename", side_effect=boom),
            mock.patch.object(Path, "replace", side_effect=boom),
            mock.patch.object(os, "makedirs", side_effect=boom),
            mock.patch.object(os, "replace", side_effect=boom),
            mock.patch.object(os, "remove", side_effect=boom),
            mock.patch.object(os, "system", side_effect=boom),
            mock.patch.object(shutil, "rmtree", side_effect=boom),
            mock.patch.object(shutil, "copy", side_effect=boom),
        ]
        for patcher in patches:
            patcher.start()
        try:
            result = bp.compile_blueprint(self.make(), self_worktree=self.stable, registered_providers=KNOWN)
        finally:
            for patcher in reversed(patches):
                patcher.stop()
        self.assertTrue(bp.verify_plan(result.plan))
        self.assertTrue(git_calls, "the native parser's read-only worktree inspection should have run")
        self.assertEqual(_tree_snapshot(self.root), before)
        self.assertEqual({n: _git(r, "rev-parse", "HEAD").stdout for n, r in self.repos.items()}, heads)
        for repo in self.repos.values():
            self.assertEqual(_git(repo, "status", "--porcelain").stdout, "")

    def test_refusals_execute_nothing_either(self):
        with mock.patch.object(rp.PipelineRunner, "run", side_effect=AssertionError("ran")), \
                mock.patch.object(runner, "execute_work_order", side_effect=AssertionError("ran")):
            self.assertNative(self.blueprint([self.node("a", depends_on=("b",)), self.node("b", depends_on=("a",))]),
                              "DEPENDENCY_CYCLE")
            self.assertAdapter(self.blueprint([self.node("a")]), "BLUEPRINT_TOO_FEW_NODES")


# ---------------------------------------------------------------------------
class ModuleContractTests(unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_imports_are_minimal_and_wire_no_execution_or_retirement(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                imported.update(f"{node.module}.{a.name}" for a in node.names)
        allowed = {
            "__future__", "__future__.annotations", "dataclasses", "dataclasses.dataclass", "dataclasses.field",
            "hashlib", "json", "sys", "pathlib", "pathlib.Path", "typing", "typing.Optional",
            "scripts.ai", "scripts.ai.runner_pipeline", "runner_pipeline",
        }
        self.assertEqual(imported - allowed, set())
        for forbidden in ("subprocess", "shutil", "os", "claude_runner", "fabric_director", "runner_git",
                          "runner_worktree_retirement", "runner_promotion", "runner_factory_ledger", "threading"):
            self.assertFalse(any(name == forbidden or name.endswith("." + forbidden) for name in imported),
                             forbidden)

    def test_only_parser_surface_of_runner_is_used(self):
        used = {
            node.attr for node in ast.walk(self.tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "pipeline"
        }
        self.assertEqual(used, {"parse_manifest", "default_self_worktree", "Manifest"})
        calls = {
            (node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", ""))
            for node in ast.walk(self.tree) if isinstance(node, ast.Call)
        }
        for forbidden in ("run", "Popen", "system", "execute_work_order", "PipelineRunner", "write_text",
                          "write_bytes", "mkdir", "open", "unlink", "rmtree", "create_checkpoint", "load_manifest"):
            self.assertNotIn(forbidden, calls, forbidden)

    def test_no_retirement_approval_or_execution_feature_is_wired(self):
        public = {n for n in dir(bp) if not n.startswith("_")}
        for word in ("retire", "retirement", "approve", "authorize_execution", "execute", "launch", "merge_plan",
                     "promote", "delete", "prune", "submit", "run_plan"):
            self.assertFalse(any(word in n.lower() for n in public), word)
        lowered = self.source.lower()
        self.assertNotIn("runner_worktree_retirement", lowered)
        self.assertNotRegex(lowered, r"d-1\.\.d-12 (?:is |are )?approved")
        self.assertFalse(any(getattr(bp, n) is True for n in public if n.isupper()))

    def test_director_dag_awareness_is_confined_to_the_fcp5b01_gateway(self):
        # FCP-5B-01 amendment: replaces "the Director is unaware of DAGs",
        # which held only until FCP-5B-01 (the authorized Director DAG
        # gateway). What still must hold: the Director reaches this module
        # only through its public compile/verify surface, compiles in exactly
        # one place, never runs the Runner parser itself for a DAG, and the
        # only blueprint-named methods are the three gateway entry points.
        tree = ast.parse(Path(fd.__file__).read_text(encoding="utf-8"))
        used = {
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "blueprints"
        }
        self.assertEqual(used, {
            "DagBlueprint", "BlueprintError", "BlueprintPlan", "PlanNode", "compile_blueprint", "verify_plan",
            "canonical_plan_json",
        })
        service = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FabricDirectorService")

        def callers(attr):
            return sorted(
                method.name for method in service.body if isinstance(method, ast.FunctionDef)
                for node in ast.walk(method)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == attr
            )

        self.assertEqual(callers("compile_blueprint"), ["submit_blueprint"])
        self.assertEqual(callers("parse_manifest"), ["_submit"])  # the single-worker path's own, unchanged
        self.assertEqual(callers("PipelineRunner"), ["_run_manifest"])
        self.assertEqual({n for n in dir(fd.FabricDirectorService) if "blueprint" in n.lower()},
                         {"submit_blueprint", "run_blueprint", "result_blueprint"})

    def test_single_worker_director_apis_unchanged_by_ast(self):
        # FCP-5B-01 amendment: replaces the whole-file `fabric_director.py`
        # pin. Each original single-worker API is pinned individually; the
        # only tolerated differences are the two FCP-5B-01 edits, which are
        # reversed here and must reproduce the original digest exactly.
        tree = ast.parse(Path(fd.__file__).read_text(encoding="utf-8"))
        defs = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "FabricDirectorService":
                defs.update({f"{node.name}.{m.name}": m for m in node.body if isinstance(m, ast.FunctionDef)})
            elif isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                defs[node.name] = node
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                defs[node.targets[0].id] = node

        for name in FCP5B01_GUARDED_PROJECTIONS:
            node = copy.deepcopy(defs[name])
            # `workers = ...` is immediately followed by the guard, before any artifact read.
            sites = [i for i, s in enumerate(node.body) if _is_self_call(s, FCP5B01_GUARD, ("run_id", "workers"))]
            self.assertEqual(len(sites), 1, name)
            before = node.body[sites[0] - 1]
            self.assertTrue(isinstance(before, ast.Assign) and getattr(before.targets[0], "id", None) == "workers",
                            name)
            del node.body[sites[0]]
            defs[name] = node

        run = copy.deepcopy(defs["FabricDirectorService.run"])
        helper = defs[f"FabricDirectorService.{FCP5B01_RUN_HELPER}"]
        self.assertEqual([a.arg for a in helper.args.args], ["self", "manifest"])
        sites = [i for i, s in enumerate(run.body) if _is_self_call(s, FCP5B01_RUN_HELPER, ("manifest",))]
        self.assertEqual(len(sites), 1)
        helper_body = helper.body[1:] if ast.get_docstring(helper) is not None else helper.body
        run.body[sites[0]:sites[0] + 1] = copy.deepcopy(helper_body)
        defs["FabricDirectorService.run"] = run

        for name, digest in DIRECTOR_SINGLE_WORKER_AST_PINS.items():
            self.assertIn(name, defs, name)
            self.assertEqual(_ast_digest(defs[name]), digest, name)

    def test_pinned_runner_and_director_sources_unchanged(self):
        for rel, digest in PINNED_SOURCES.items():
            self.assertEqual(_lf_sha256(REPO_ROOT / rel), digest, rel)


# ---------------------------------------------------------------------------
class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW_PATH.read_bytes().decode("utf-8").replace("\r\n", "\n")
        self.lines = self.text.split("\n")

    def _jobs(self):
        start = self.lines.index("jobs:")
        return [m.group(1) for line in self.lines[start + 1:] if (m := re.match(r"^  ([A-Za-z0-9_-]+):$", line))]

    def _step_block(self):
        header = f"      - name: {NEW_CI_STEP_NAME}"
        start = self.lines.index(header)
        end = start + 1
        while end < len(self.lines) and self.lines[end].startswith("        "):
            end += 1
        return start, end

    def test_still_nine_jobs_and_permissions_unchanged(self):
        self.assertEqual(len(self._jobs()), 9)
        self.assertEqual(self._jobs()[0], "fabric-regression")
        self.assertIn("permissions:\n  contents: read\n", self.text)

    def test_new_step_is_single_additive_and_correctly_placed(self):
        self.assertEqual(self.text.count("test_fabric_dag_blueprint"), 1)
        start, end = self._step_block()
        jobs_start = self.lines.index("jobs:")
        second_job = next(i for i in range(jobs_start + 2, len(self.lines))
                          if re.match(r"^  [A-Za-z0-9_-]+:$", self.lines[i]))
        names = [(i, line) for i, line in enumerate(self.lines[:second_job]) if line.startswith("      - name: ")]
        order = [line.split("- name: ", 1)[1] for _, line in names]
        idx = order.index(NEW_CI_STEP_NAME)
        self.assertEqual(order[idx - 1], "Pipeline and infrastructure regression")
        self.assertEqual(order[idx + 1], "Runner Queue Multiworker regression")
        block = "\n".join(self.lines[start:end])
        self.assertIn("loadTestsFromName('scripts.tests.test_fabric_dag_blueprint')", block)
        self.assertIn("r.wasSuccessful() and not r.skipped", block)
        for other in ("test_runner_pipeline", "test_fabric_director"):
            self.assertNotIn(other, block)

    def test_removing_new_step_restores_baseline_byte_for_byte(self):
        start, end = self._step_block()
        self.assertEqual(self.lines[end], "")  # the step's own blank separator
        lines = self.lines[:start] + self.lines[end + 1:]
        # FCP-5B-01 amendment: the workflow now also carries the one FCP-5B-01
        # step; stripping exactly both additive steps (and nothing else) must
        # still reproduce the 5862688 baseline byte for byte.
        header = f"      - name: {FCP5B01_CI_STEP_NAME}"
        self.assertEqual(lines.count(header), 1)
        later = lines.index(header)
        later_end = later + 1
        while later_end < len(lines) and lines[later_end].startswith("        "):
            later_end += 1
        self.assertEqual(lines[later_end], "")
        restored = "\n".join(lines[:later] + lines[later_end + 1:])
        self.assertEqual(hashlib.sha256(restored.encode("utf-8")).hexdigest(), WORKFLOW_BASELINE_SHA256)


if __name__ == "__main__":
    unittest.main()
