"""FCP-2B-CORE: deterministic, read-only semantic reconciliation analysis.

Every repository here is a throwaway under a temporary directory, built with
PLAIN git (subprocess) - commits and safe synthetic merges are fixture
construction only; the module under test is restricted to
`runner_integration._git`. Security tests pair each "nothing ran / nothing
changed" assertion with a positive control proving the hostile
configuration is really active, so no assertion is vacuous.
"""

import ast
import dataclasses
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import runner_git
from scripts.ai import runner_integration as ri
from scripts.ai import runner_pipeline as pipeline
from scripts.ai import runner_reconciliation as rr
from scripts.tests.test_runner_git import install_hostile_config, plain_git
from scripts.tests.test_runner_integration import (
    REMOTE_URL, _ISOLATED_ENV, _git_dir_state, _rmtree, good_evidence, head, write,
)

SCOPES = ("src",)
ACCEPTANCE = ("python -B -m unittest scripts.tests.test_example -q",)
LINES = tuple(f"line {i}\n" for i in range(1, 13))


def text(replace=None) -> str:
    """The 12-line src/a.py with 1-based lines replaced."""
    lines = list(LINES)
    for number, value in (replace or {}).items():
        lines[number - 1] = value
    return "".join(lines)


def change(repo: Path, message: str, files=None, delete=(), index_entries=()) -> str:
    for rel, content in (files or {}).items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            write(path, content)
        plain_git(repo, "add", "--", rel)
    for rel in delete:
        plain_git(repo, "rm", "-q", "--", rel)
    for mode, sha, rel in index_entries:
        plain_git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{sha},{rel}")
    plain_git(repo, "commit", "-q", "-m", message)
    return head(repo)


def hash_blob(repo: Path, data: bytes) -> str:
    result = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=data,
                            capture_output=True, check=True)
    return result.stdout.decode().strip()


class Fixture:
    """`repo` on develop (origin/develop tracking ref, remote URL) and a
    linked candidate worktree `wt` on a feature branch, both at c0."""

    def __init__(self, root: Path, name: str = "repo"):
        self.root = root
        self.repo = root / name
        self.repo.mkdir()
        plain_git(self.repo, "init", "-q", "-b", "develop")
        plain_git(self.repo, "config", "user.email", "fcp2b@example.invalid")
        plain_git(self.repo, "config", "user.name", "FCP2B Tests")
        plain_git(self.repo, "config", "remote.origin.url", REMOTE_URL)
        self.c0 = change(self.repo, "c0", {"src/a.py": text(), "src/old.py": "old\n",
                                           "docs/readme.md": "readme\n", "shared.txt": "shared\n"})
        self.set_base(self.c0)
        self.wt = self.add_worktree(f"{name}-wt", "feature/fcp2b")

    def add_worktree(self, name: str, branch: str, start: str = None) -> Path:
        path = self.root / name
        plain_git(self.repo, "worktree", "add", "-q", "-b", branch, str(path), start or self.c0)
        return path

    def set_base(self, sha: str) -> None:
        plain_git(self.repo, "update-ref", ri.TRACKING_REF, sha)
        self.base = sha

    def head_commit(self, files=None, delete=(), worktree=None, **kw) -> str:
        return change(worktree or self.wt, "feature", files, delete, **kw)

    def base_commit(self, files=None, delete=(), **kw) -> str:
        sha = change(self.repo, "base advance", files, delete, **kw)
        self.set_base(sha)
        return sha

    def analyze(self, worktree=None, *, scopes=SCOPES, **kwargs):
        worktree = worktree or self.wt
        if "evidence" not in kwargs:
            kwargs["evidence"] = good_evidence(Path(worktree))
        return rr.analyze_reconciliation(worktree, attested_sha=self.base, authorized_scopes=scopes, **kwargs)


def _isolate_env(case) -> None:
    patch = mock.patch.dict(os.environ, _ISOLATED_ENV)
    patch.start()
    case.addCleanup(patch.stop)


class ReconTestCase(unittest.TestCase):
    def setUp(self):
        _isolate_env(self)
        self.root = Path(tempfile.mkdtemp(prefix="fcp2b-")).resolve()
        self.addCleanup(_rmtree, self.root)
        self.fx = Fixture(self.root)

    def assertRecon(self, analysis, classification, *reasons):
        self.assertEqual(analysis.classification, classification, analysis.reason_codes)
        for reason in reasons:
            self.assertIn(reason, analysis.reason_codes)
        self.assertIs(analysis.human_approval_required, True)
        self.assertIs(analysis.authorizes_action, False)
        self.assertRegex(analysis.fingerprint, r"^[0-9a-f]{64}$")
        if classification in (rr.NO_TEXTUAL_CONFLICT, rr.SEMANTIC_REVIEW_REQUIRED, rr.HUMAN_REQUIRED):
            self.assertIn(rr.RECON_SEMANTIC_VALIDATION_REQUIRED, analysis.reason_codes)
            self.assertTrue(analysis.semantic_validation_required)

    def finding(self, analysis, path):
        return next(f for f in analysis.path_findings if f.path == path)


def _wrap_git(transform):
    """Patches runner_integration._git so `transform(args, out)` may replace
    the output of the module's own diff reads (FCP-1 reads pass through)."""
    real = ri._git

    def wrapped(repo, *args, **kwargs):
        code, out = real(repo, *args, **kwargs)
        return code, transform(args, out)

    return mock.patch.object(ri, "_git", wrapped)


# ---------------------------------------------------------------------------
# Real Git fixtures: textual relations
# ---------------------------------------------------------------------------

class TextualRelationTests(ReconTestCase):
    def test_stale_disjoint_paths(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        self.fx.base_commit({"docs/readme.md": "readme v2\n"})
        a = self.fx.analyze()
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT, rr.RECON_NO_TEXTUAL_CONFLICT, rr.RECON_DISJOINT_PATHS)
        self.assertEqual(self.finding(a, "src/a.py").outcome, rr.PATH_HEAD_ONLY)
        self.assertEqual(self.finding(a, "docs/readme.md").outcome, rr.PATH_BASE_ONLY)
        self.assertEqual(a.scope, ("src/a.py",))
        self.assertEqual(a.authorized_scopes, SCOPES)
        self.assertEqual((a.head_sha, a.base_sha), (head(self.fx.wt), self.fx.base))
        self.assertEqual(a.merge_bases, (self.fx.c0,))
        # The FCP-1 assessment and its original fingerprint are exposed as-is.
        self.assertEqual(a.assessment_fingerprint, a.assessment.fingerprint)
        self.assertEqual(a.facts.reassessment_fingerprint, a.assessment.fingerprint)
        self.assertEqual(rr._fcp1_fingerprint(a.assessment), a.assessment_fingerprint)

    def test_convergent_identical_blob(self):
        same = text({3: "same\n"})
        self.fx.head_commit({"src/a.py": same})
        self.fx.base_commit({"src/a.py": same})
        a = self.fx.analyze()
        self.assertEqual(a.assessment_classification, ri.NEEDS_RECONCILIATION)
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT, rr.RECON_CONVERGENT_CHANGES)
        self.assertEqual(self.finding(a, "src/a.py").outcome, rr.PATH_CONVERGENT)
        self.assertEqual(a.facts.head_hunks, ())  # identical outcome: no hunk read needed

    def test_delete_delete(self):
        self.fx.head_commit(delete=("src/old.py",))
        self.fx.base_commit(delete=("src/old.py",))
        a = self.fx.analyze()
        self.assertEqual(a.assessment_classification, ri.NEEDS_RECONCILIATION)
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT, rr.RECON_CONVERGENT_CHANGES)
        self.assertEqual(self.finding(a, "src/old.py").outcome, rr.PATH_CONVERGENT)

    def test_disjoint_text_hunks(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        self.fx.base_commit({"src/a.py": text({8: "base\n"})})
        a = self.fx.analyze()
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT, rr.RECON_DISJOINT_HUNKS)
        self.assertEqual(self.finding(a, "src/a.py").outcome, rr.PATH_DISJOINT_HUNKS)
        self.assertEqual(a.facts.head_hunks[0].hunks, ((2, 1, 2, 1),))
        self.assertEqual(a.facts.base_hunks[0].hunks, ((8, 1, 8, 1),))
        # Textual only: never a semantic-safety or merge-readiness verdict.
        self.assertNotIn("SAFE", " ".join(a.reason_codes).replace("SEMANTIC_VALIDATION", ""))

    def test_touching_text_hunks(self):
        self.fx.head_commit({"src/a.py": text({4: "head\n"})})
        self.fx.base_commit({"src/a.py": text({5: "base\n"})})
        a = self.fx.analyze()
        self.assertRecon(a, rr.SEMANTIC_REVIEW_REQUIRED, rr.RECON_TOUCHING_HUNKS)
        self.assertEqual(self.finding(a, "src/a.py").outcome, rr.PATH_OVERLAPPING_HUNKS)

    def test_overlapping_text_hunks(self):
        self.fx.head_commit({"src/a.py": text({5: "head\n"})})
        self.fx.base_commit({"src/a.py": text({5: "base\n"})})
        a = self.fx.analyze()
        self.assertRecon(a, rr.SEMANTIC_REVIEW_REQUIRED, rr.RECON_OVERLAPPING_HUNKS)

    def test_not_applicable_reads_nothing_and_preserves_fcp1(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        calls = []
        real = ri._git

        def recording(repo, *args, **kwargs):
            calls.append(args)
            return real(repo, *args, **kwargs)

        with mock.patch.object(ri, "_git", recording):
            a = self.fx.analyze()
        self.assertEqual(a.assessment_classification, ri.ELIGIBLE_PENDING_APPROVAL)
        self.assertRecon(a, rr.NOT_APPLICABLE, rr.RECON_NOT_APPLICABLE, "FCP1_ELIGIBLE_PENDING_APPROVAL")
        self.assertIsNone(a.facts)
        self.assertFalse(any("--raw" in c or "-U0" in c for c in calls))
        self.assertFalse(a.semantic_validation_required)
        self.assertIsNone(rr.propose_reconciliation_plan(a, acceptance_commands=ACCEPTANCE))
        # Missing evidence is preserved as the FCP-1 classification too.
        a = self.fx.analyze(evidence=None)
        self.assertRecon(a, rr.NOT_APPLICABLE, "FCP1_EVIDENCE_MISSING")


# ---------------------------------------------------------------------------
# Real Git fixtures: human-only situations
# ---------------------------------------------------------------------------

class HumanRequiredTests(ReconTestCase):
    def test_unrelated_histories(self):
        orphan = self.root / "orphan"
        plain_git(self.fx.repo, "worktree", "add", "-q", "--detach", str(orphan), self.fx.c0)
        plain_git(orphan, "checkout", "-q", "--orphan", "feature/orphan")
        plain_git(orphan, "rm", "-rqf", ".")
        change(orphan, "orphan root", {"src/z.py": "z\n"})
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        a = self.fx.analyze(orphan, scopes=("src", "docs", "shared.txt"))
        self.assertEqual(a.assessment_classification, ri.NEEDS_RECONCILIATION)
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_UNRELATED_HISTORIES)
        self.assertEqual(a.facts.head_changes, ())

    def test_multiple_merge_bases(self):
        x1 = self.fx.head_commit({"src/x.py": "x\n"})
        y1 = self.fx.base_commit({"docs/y.md": "y\n"})
        plain_git(self.fx.wt, "merge", "--no-ff", "-q", "-m", "criss", y1)
        plain_git(self.fx.repo, "merge", "--no-ff", "-q", "-m", "cross", x1)
        self.fx.set_base(head(self.fx.repo))
        a = self.fx.analyze()
        self.assertEqual(len(a.merge_bases), 2)
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_MULTIPLE_MERGE_BASES)

    def test_modify_delete_both_directions(self):
        self.fx.head_commit({"src/old.py": "head edit\n"})
        self.fx.base_commit(delete=("src/old.py",))
        self.assertRecon(self.fx.analyze(), rr.HUMAN_REQUIRED, rr.RECON_MODIFY_DELETE)

        other = self.fx.add_worktree("del-wt", "feature/delete", self.fx.c0)
        self.fx.head_commit(delete=("src/a.py",), worktree=other)
        self.fx.base_commit({"src/a.py": text({1: "base\n"})})
        a = self.fx.analyze(other)
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_MODIFY_DELETE)
        self.assertEqual(self.finding(a, "src/a.py").outcome, rr.PATH_HUMAN_REQUIRED)

    def test_differing_add_add(self):
        self.fx.head_commit({"src/new.py": "head\n"})
        self.fx.base_commit({"src/new.py": "base\n"})
        self.assertRecon(self.fx.analyze(), rr.HUMAN_REQUIRED, rr.RECON_ADD_ADD_DIFFERENT)

    def test_binary(self):
        self.fx.head_commit({"src/blob.bin": b"\x00\x01\x02binary\xff"})
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        a = self.fx.analyze()
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_BINARY)
        self.assertIs(next(c for c in a.facts.head_changes if c.path == "src/blob.bin").binary, True)

    def test_symlink_and_gitlink(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        target = hash_blob(self.fx.repo, b"../shared.txt")
        self.fx.base_commit(index_entries=(("120000", target, "docs/link"),
                                           ("160000", self.fx.c0, "vendor/sub")))
        a = self.fx.analyze()
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_SYMLINK, rr.RECON_GITLINK)
        self.assertIn(rr.RECON_SYMLINK, self.finding(a, "docs/link").reason_codes)
        self.assertIn(rr.RECON_GITLINK, self.finding(a, "vendor/sub").reason_codes)

    def test_case_collision(self):
        self.fx.head_commit({"src/Readme.md": "head\n"})
        self.fx.base_commit({"src/readme.md": "base\n"})
        a = self.fx.analyze()
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)  # FCP-1 sees no exact overlap
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_CASE_COLLISION)


# ---------------------------------------------------------------------------
# Fail-closed reads, drift and limits (real Git)
# ---------------------------------------------------------------------------

class FailClosedReadTests(ReconTestCase):
    def setUp(self):
        super().setUp()
        self.fx.head_commit({"src/a.py": text({4: "head\n"})})
        self.fx.base_commit({"src/a.py": text({9: "base\n"})})

    def test_read_failure(self):
        real = ri._git

        def failing(repo, *args, **kwargs):
            if "--raw" in args:
                raise ri._GitReadError("git diff", "simulated read failure")
            return real(repo, *args, **kwargs)

        with mock.patch.object(ri, "_git", failing):
            a = self.fx.analyze()
        self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_READ_FAILED)
        self.assertIn("simulated read failure", a.facts.read_errors[0][1])
        self.assertEqual(a.assessment_classification, ri.NEEDS_RECONCILIATION)
        self.assertFalse(a.semantic_validation_required)

    def test_drift_between_assessment_passes(self):
        real = rr._read_facts
        for name, mutate in (
            ("base", lambda: self.fx.set_base(self.fx.c0)),
            ("head", lambda: change(self.fx.wt, "concurrent", {"src/late.py": "late\n"})),
        ):
            with self.subTest(drift=name):
                base_before = self.fx.base

                def drifting(*args, _mutate=mutate):
                    facts = real(*args)
                    _mutate()
                    return facts

                with mock.patch.object(rr, "_read_facts", drifting):
                    a = self.fx.analyze()
                self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_ASSESSMENT_DRIFT)
                self.assertNotEqual(a.facts.reassessment_fingerprint, a.assessment_fingerprint)
                self.fx.set_base(base_before)

    def test_unexpected_raw(self):
        def bad_status(args, out):
            return out.replace(" M\0", " R100\0", 1) if "--raw" in args else out

        def extra_field(args, out):
            return out + "unexpected\0" if "--raw" in args else out

        for transform in (bad_status, extra_field):
            with self.subTest(transform=transform.__name__), _wrap_git(transform):
                self.assertRecon(self.fx.analyze(), rr.FAIL_CLOSED, rr.RECON_UNEXPECTED_RAW)

    def test_unexpected_numstat(self):
        def extra_column(args, out):
            return out.replace("\t", "\t0\t", 1) if "--numstat" in args else out

        def missing_record(args, out):
            return "" if "--numstat" in args else out

        with _wrap_git(extra_column):
            a = self.fx.analyze()
        # "1\t0\t1\tsrc/a.py" parses as counts with a tab in the path -> unknown path.
        self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_UNEXPECTED_NUMSTAT)
        with _wrap_git(missing_record):
            self.assertRecon(self.fx.analyze(), rr.FAIL_CLOSED, rr.RECON_UNEXPECTED_NUMSTAT)

    def test_unexpected_hunk_output(self):
        def context_line(args, out):
            # What a non-zero inter-hunk context would add: a context line.
            return out.replace("\n+head\n", "\n line 0\n+head\n", 1) if "-U0" in args else out

        with _wrap_git(context_line):
            self.assertRecon(self.fx.analyze(), rr.FAIL_CLOSED, rr.RECON_UNEXPECTED_HUNK)

    def test_path_count_overflow(self):
        a = self.fx.analyze(max_paths=1)
        self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_PATH_LIMIT_EXCEEDED)
        for bad in (0, 257, True, "5", 1.5, None):
            with self.subTest(max_paths=bad), self.assertRaises(rr.ReconciliationInputError):
                self.fx.analyze(max_paths=bad)

    def test_hunk_size_overflow(self):
        with mock.patch.object(rr, "MAX_HUNK_BYTES", 10):
            a = self.fx.analyze()
        self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_HUNK_LIMIT_EXCEEDED)
        with mock.patch.object(rr, "MAX_HUNK_BYTES", 3):  # refused from numstat, before reading hunks
            self.assertRecon(self.fx.analyze(), rr.FAIL_CLOSED, rr.RECON_HUNK_LIMIT_EXCEEDED)

    def test_assessment_exception_fails_closed(self):
        with mock.patch.object(ri, "assess_integration", side_effect=UnicodeEncodeError("utf-8", "x", 0, 1, "bad")):
            a = self.fx.analyze()
        self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_ASSESSMENT_FAILED)
        self.assertIsNone(a.assessment)
        self.assertNotIn(rr.RECON_MALFORMED_ASSESSMENT, a.reason_codes)


# ---------------------------------------------------------------------------
# Pure classification over shared real analyses
# ---------------------------------------------------------------------------

class PureClassificationTests(unittest.TestCase):
    """One repository, two candidates against the same base advance:
    `overlap` (SEMANTIC_REVIEW_REQUIRED) and `disjoint`
    (NO_TEXTUAL_CONFLICT), built once; the tests classify edited facts."""

    @classmethod
    def setUpClass(cls):
        patch = mock.patch.dict(os.environ, _ISOLATED_ENV)
        patch.start()
        cls.addClassCleanup(patch.stop)
        cls.root = Path(tempfile.mkdtemp(prefix="fcp2b-shared-")).resolve()
        cls.addClassCleanup(_rmtree, cls.root)
        fx = cls.fx = Fixture(cls.root)
        disjoint_wt = fx.add_worktree("disjoint-wt", "feature/disjoint")
        fx.head_commit({"src/a.py": text({5: "head\n"})})
        fx.head_commit({"src/a.py": text({10: "head\n"})}, worktree=disjoint_wt)
        fx.base_commit({"src/a.py": text({5: "base\n"})})
        cls.overlap = fx.analyze()
        cls.disjoint = fx.analyze(disjoint_wt)

    assertRecon = ReconTestCase.assertRecon
    finding = ReconTestCase.finding

    def classify(self, analysis=None, **facts_overrides):
        analysis = analysis or self.overlap
        facts = dataclasses.replace(analysis.facts, **facts_overrides)
        return rr.classify_reconciliation(analysis.assessment, facts)

    def test_shared_baselines(self):
        self.assertRecon(self.overlap, rr.SEMANTIC_REVIEW_REQUIRED, rr.RECON_OVERLAPPING_HUNKS)
        self.assertRecon(self.disjoint, rr.NO_TEXTUAL_CONFLICT, rr.RECON_DISJOINT_HUNKS)
        # Re-classifying the unmodified facts is pure and reproduces them exactly.
        again = rr.classify_reconciliation(self.overlap.assessment, self.overlap.facts)
        self.assertEqual(again, self.overlap)
        self.assertIs(again.assessment, self.overlap.assessment)

    def test_fixed_precedence(self):
        ambiguous = (dataclasses.replace(self.overlap.facts.head_hunks[0],
                                         hunks=self.overlap.facts.head_hunks[0].hunks + ((9, 0, 9, 0),)),)
        human = self.classify(head_hunks=ambiguous)
        self.assertRecon(human, rr.HUMAN_REQUIRED, rr.RECON_AMBIGUOUS_HUNK_GEOMETRY)
        broken = self.classify(head_hunks=ambiguous, read_errors=((rr.RECON_READ_FAILED, "x"),))
        self.assertRecon(broken, rr.FAIL_CLOSED, rr.RECON_READ_FAILED)
        not_applicable = rr.classify_reconciliation(
            dataclasses.replace(self.overlap.assessment, classification=ri.ELIGIBLE_PENDING_APPROVAL),
            broken.facts)
        self.assertRecon(not_applicable, rr.NOT_APPLICABLE, "FCP1_ELIGIBLE_PENDING_APPROVAL")
        self.assertEqual(not_applicable.assessment_classification, ri.ELIGIBLE_PENDING_APPROVAL)
        # SEMANTIC_REVIEW_REQUIRED outranks NO_TEXTUAL_CONFLICT on the same file.
        self.assertEqual(rr.RECONCILIATION_PRECEDENCE, (
            rr.NOT_APPLICABLE, rr.FAIL_CLOSED, rr.HUMAN_REQUIRED, rr.SEMANTIC_REVIEW_REQUIRED,
            rr.NO_TEXTUAL_CONFLICT))

    def test_missing_safety_facts(self):
        self.assertRecon(rr.classify_reconciliation(self.overlap.assessment, None),
                         rr.FAIL_CLOSED, rr.RECON_MISSING_SAFETY_FACT)
        head_change = self.overlap.facts.head_changes[0]
        cases = {
            "binary": {"head_changes": (dataclasses.replace(head_change, binary=None),)},
            "hunks": {"head_hunks": ()},
            "reassessment": {"reassessment_fingerprint": None},
        }
        for name, overrides in cases.items():
            with self.subTest(missing=name):
                self.assertRecon(self.classify(**overrides), rr.FAIL_CLOSED, rr.RECON_MISSING_SAFETY_FACT)

    def test_contradictory_overlap_and_hunks(self):
        a = self.classify(base_changes=())
        self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_CONTRADICTORY_OVERLAP, rr.RECON_FACTS_MISMATCH)
        hunks = self.overlap.facts.head_hunks[0]
        a = self.classify(head_hunks=(dataclasses.replace(hunks, hunks=((5, 2, 5, 2),)),))
        self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_CONTRADICTORY_HUNKS)
        self.assertRecon(self.classify(base_sha=self.fx.c0), rr.FAIL_CLOSED, rr.RECON_FACTS_MISMATCH)
        self.assertRecon(self.classify(reassessment_classification=ri.STALE_BASE),
                         rr.FAIL_CLOSED, rr.RECON_ASSESSMENT_DRIFT)

    def test_malformed_facts_and_unknown_fields(self):
        @dataclasses.dataclass(frozen=True)
        class ExtendedFacts(rr.ReconciliationFacts):
            unexpected: str = "field"

        extended = ExtendedFacts(**{f.name: getattr(self.overlap.facts, f.name)
                                    for f in dataclasses.fields(rr.ReconciliationFacts)})
        for facts in (dataclasses.asdict(self.overlap.facts), extended, "facts"):
            with self.subTest(facts=type(facts).__name__):
                a = rr.classify_reconciliation(self.overlap.assessment, facts)
                self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_MALFORMED_FACTS)
        bad_status = dataclasses.replace(self.overlap.facts.head_changes[0], status="R100")
        self.assertRecon(self.classify(head_changes=(bad_status,)), rr.FAIL_CLOSED, rr.RECON_MALFORMED_FACTS)
        self.assertRecon(self.classify(read_errors=(("SOMETHING_NEW", "x"),)), rr.FAIL_CLOSED, rr.RECON_READ_FAILED)
        self.assertRecon(self.classify(max_paths=1000), rr.FAIL_CLOSED, rr.RECON_MALFORMED_FACTS)
        self.assertRecon(self.classify(head_hunk_bytes=rr.MAX_HUNK_BYTES + 1),
                         rr.FAIL_CLOSED, rr.RECON_HUNK_LIMIT_EXCEEDED)
        self.assertRecon(self.classify(max_paths=1), rr.FAIL_CLOSED, rr.RECON_PATH_LIMIT_EXCEEDED)
        self.assertRecon(rr.classify_reconciliation({"classification": ri.STALE_BASE}, self.overlap.facts),
                         rr.FAIL_CLOSED, rr.RECON_MALFORMED_ASSESSMENT)

    def test_tampered_assessment_fails_closed(self):
        a = self.overlap.assessment
        for tampered in (
            dataclasses.replace(a, reason_codes=()),
            dataclasses.replace(a, candidate=dataclasses.replace(a.candidate, overlapping_paths=())),
            dataclasses.replace(a, human_approval_required=False),
        ):
            self.assertRecon(rr.classify_reconciliation(tampered, self.overlap.facts),
                             rr.FAIL_CLOSED, rr.RECON_ASSESSMENT_TAMPERED)

    def test_scope_must_stay_within_assessed_scope(self):
        facts = self.overlap.facts
        outside = dataclasses.replace(facts.head_changes[0], path="docs/x.md")
        a = self.classify(head_changes=(outside,), head_hunks=())
        self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_FACTS_MISMATCH, rr.RECON_SCOPE_VIOLATION)

    def test_hunk_geometry(self):
        ov, touch = rr.RECON_OVERLAPPING_HUNKS, rr.RECON_TOUCHING_HUNKS
        cases = [
            (((5, 1, 5, 1),), ((5, 1, 5, 1),), ov),        # same line
            (((4, 2, 4, 2),), ((5, 1, 5, 1),), ov),        # nested
            (((4, 1, 4, 1),), ((5, 1, 5, 1),), touch),     # adjacent lines
            (((4, 0, 5, 1),), ((5, 1, 5, 1),), touch),     # insertion right before a changed line
            (((5, 0, 6, 1),), ((5, 1, 5, 1),), touch),     # insertion right after a changed line
            (((5, 0, 6, 1),), ((5, 0, 6, 2),), ov),        # insertions at the same point
            (((5, 0, 6, 1),), ((5, 2, 5, 0),), ov),        # insertion inside a deleted range
            (((0, 0, 1, 1),), ((1, 1, 1, 1),), touch),     # insertion at file start
            (((3, 1, 3, 1),), ((5, 1, 5, 1),), None),      # one untouched line between
            (((3, 0, 4, 1),), ((5, 1, 5, 1),), None),
        ]
        for left, right, expected in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(rr._hunk_relation(left, right), expected)
                self.assertEqual(rr._hunk_relation(right, left), expected)
        for hunks in ((), ((5, 1, 5, 1), (5, 1, 5, 1)), ((6, 1, 6, 1), (2, 1, 2, 1)), ((0, 1, 1, 1),),
                      ((3, 0, 3, 0),), ((4, 1, 4, 1), (5, 1, 5, 1))):
            with self.subTest(ambiguous=hunks):
                self.assertTrue(rr._geometry_ambiguous(hunks))
        self.assertFalse(rr._geometry_ambiguous(((2, 1, 2, 1), (8, 0, 9, 3))))

    def test_header_quoting_and_case_keys(self):
        self.assertEqual(rr._expected_headers("src/a b.py"), {"diff --git a/src/a b.py b/src/a b.py"})
        self.assertIn('diff --git "a/src/t\\tab" "b/src/t\\tab"', rr._expected_headers("src/t\tab"))
        quoted = rr._expected_headers("src/é.py")
        self.assertEqual(quoted, {'diff --git "a/src/\\303\\251.py" "b/src/\\303\\251.py"',
                                  "diff --git a/src/é.py b/src/é.py"})
        self.assertEqual(rr._case_collisions({"SRC/x", "src/y", "docs/z"}), {"SRC/x", "src/y"})
        self.assertEqual(rr._case_collisions({"src/x", "src/y"}), set())

    def test_parsers_refuse_unexpected_shapes(self):
        sha = "a" * 40
        with self.assertRaises(rr._ReadFailure):
            rr._parse_raw(f":100644 100644 {sha} {sha} M\0p\0:100644\0", "sha1")
        with self.assertRaises(rr._ReadFailure):
            rr._parse_raw(f":100644 100644 {sha} {sha} X\0p\0", "sha1")
        with self.assertRaises(rr._ReadFailure) as ctx:
            rr._parse_raw(f":100644 100644 {sha} {sha} M\0bad\udcff\0", "sha1")
        self.assertEqual(ctx.exception.code, rr.RECON_UNDECODABLE_PATH)
        for numstat in ("1\t2\0", "x\t1\tp\0", "1\t1\tp\0" * 2, "1\t1\t\0"):
            with self.subTest(numstat=numstat), self.assertRaises(rr._ReadFailure):
                rr._parse_numstat(numstat)
        good = "diff --git a/p b/p\nindex 1..2 100644\n--- a/p\n+++ b/p\n@@ -2 +2 @@ f\n--x\n+-y\n"
        parsed = rr._parse_hunks(good, ["p"])["p"]
        self.assertEqual((parsed.hunks, parsed.added, parsed.deleted), (((2, 1, 2, 1),), 1, 1))
        for bad in (good.replace("index", "similarity index"), good + "@@ -9 +9 @@\n-a\n",
                    good.replace("+-y\n", "+-y\n+extra\n"), good.replace("a/p b/p", "a/q b/q"),
                    "@@ -1 +1 @@\n-a\n+b\n"):
            with self.subTest(bad=bad[:40]), self.assertRaises(rr._ReadFailure):
                rr._parse_hunks(bad, ["p"])
        nul = rr._parse_hunks(good.replace("+-y", "+\0y"), ["p"])["p"]
        self.assertTrue(nul.binary_content)

    # -- determinism and immutability -------------------------------------

    def test_deterministic_frozen_results(self):
        again = self.fx.analyze()
        self.assertEqual(again.fingerprint, self.overlap.fingerprint)
        self.assertEqual(again.facts, self.overlap.facts)
        leases = self.fx.analyze(lease_root=self.root / "leases")
        self.assertEqual(leases.fingerprint, self.overlap.fingerprint)
        self.assertNotEqual(self.overlap.fingerprint, self.disjoint.fingerprint)
        plan = rr.propose_reconciliation_plan(self.disjoint, acceptance_commands=ACCEPTANCE)
        validation = rr.validate_reconciliation_plan(plan, self.disjoint)
        for result, attr in ((self.overlap, "classification"), (self.overlap.facts, "head_sha"),
                             (self.overlap.path_findings[0], "outcome"), (plan, "status"),
                             (validation, "valid")):
            with self.subTest(type=type(result).__name__), self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(result, attr, None)

    # -- plans ---------------------------------------------------------------

    def test_plan_is_proposed_never_authorized(self):
        plan = rr.propose_reconciliation_plan(self.disjoint, acceptance_commands=list(ACCEPTANCE))
        self.assertEqual(plan.status, rr.PLAN_PROPOSED)
        self.assertIs(plan.authorizes_action, False)
        self.assertIs(plan.human_approval_required, True)
        self.assertIs(plan.semantic_validation_required, True)
        self.assertEqual(plan.acceptance_commands, ACCEPTANCE)
        self.assertEqual(plan.analysis_fingerprint, self.disjoint.fingerprint)
        self.assertEqual(plan.assessment_fingerprint, self.disjoint.assessment_fingerprint)
        self.assertEqual(plan.scope, ("src/a.py",))
        self.assertEqual(plan.review_paths, ())
        self.assertIn(rr.STEP_HUMAN_APPROVE_MECHANISM, plan.steps)
        self.assertRegex(plan.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(plan, rr.propose_reconciliation_plan(self.disjoint, acceptance_commands=ACCEPTANCE))

        review = rr.propose_reconciliation_plan(self.overlap, acceptance_commands=ACCEPTANCE)
        self.assertEqual(review.review_paths, ("src/a.py",))
        self.assertIn(rr.STEP_HUMAN_SEMANTIC_REVIEW, review.steps)
        self.assertEqual(review.status, rr.PLAN_PROPOSED)

        validation = rr.validate_reconciliation_plan(plan, self.disjoint)
        self.assertTrue(validation.valid, validation.reason_codes)
        self.assertIs(validation.authorizes_action, False)
        self.assertIs(validation.human_approval_required, True)

    def test_no_plan_for_non_plannable_analyses(self):
        ambiguous = (dataclasses.replace(self.overlap.facts.head_hunks[0],
                                         hunks=self.overlap.facts.head_hunks[0].hunks + ((9, 0, 9, 0),)),)
        for analysis in (
            self.classify(head_hunks=ambiguous),                                    # HUMAN_REQUIRED
            self.classify(read_errors=((rr.RECON_READ_FAILED, "x"),)),              # FAIL_CLOSED
        ):
            with self.subTest(classification=analysis.classification):
                self.assertIsNone(rr.propose_reconciliation_plan(analysis, acceptance_commands=ACCEPTANCE))

    def test_invalid_inputs_and_acceptance_commands_refused(self):
        for commands in (None, [], (), "python -m unittest", [""], ["   "], [1], ["a\nb"], ["a", "a"]):
            with self.subTest(commands=commands), self.assertRaises(rr.ReconciliationInputError):
                rr.propose_reconciliation_plan(self.disjoint, acceptance_commands=commands)
        for analysis in (None, {"classification": rr.NO_TEXTUAL_CONFLICT},
                         dataclasses.replace(self.overlap, classification=rr.NO_TEXTUAL_CONFLICT),
                         dataclasses.replace(self.disjoint, authorizes_action=True),
                         dataclasses.replace(self.disjoint, scope=("docs/readme.md",))):
            with self.subTest(analysis=type(analysis).__name__), self.assertRaises(rr.ReconciliationInputError):
                rr.propose_reconciliation_plan(analysis, acceptance_commands=ACCEPTANCE)

    def test_tampered_plan_or_analysis_invalidates(self):
        plan = rr.propose_reconciliation_plan(self.disjoint, acceptance_commands=ACCEPTANCE)
        cases = {
            rr.PLAN_TAMPERED: dataclasses.replace(plan, scope=("src/a.py", "src/b.py")),
            rr.PLAN_NOT_PROPOSED: dataclasses.replace(plan, status="APPROVED"),
            rr.PLAN_AUTHORIZATION_CLAIMED: dataclasses.replace(plan, authorizes_action=True),
        }
        for reason, tampered in cases.items():
            with self.subTest(reason=reason):
                v = rr.validate_reconciliation_plan(tampered, self.disjoint)
                self.assertFalse(v.valid)
                self.assertIn(reason, v.reason_codes)
                self.assertIs(v.authorizes_action, False)
        v = rr.validate_reconciliation_plan(plan, self.overlap)  # another candidate's analysis
        self.assertFalse(v.valid)
        self.assertIn(rr.PLAN_HEAD_CHANGED, v.reason_codes)
        self.assertIn(rr.PLAN_CLASSIFICATION_CHANGED, v.reason_codes)
        v = rr.validate_reconciliation_plan(plan, dataclasses.replace(self.disjoint, head_sha="0" * 40))
        self.assertIn(rr.PLAN_ANALYSIS_INVALID, v.reason_codes)
        for bad in (None, "plan", dataclasses.asdict(plan)):
            self.assertEqual(rr.validate_reconciliation_plan(bad, self.disjoint).reason_codes,
                             (rr.PLAN_INVALID_INPUT,))


class PlanInvalidationTests(ReconTestCase):
    def test_base_advance_and_new_head_invalidate_previous_plan(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        first = self.fx.analyze()
        plan = rr.propose_reconciliation_plan(first, acceptance_commands=ACCEPTANCE)
        self.assertTrue(rr.validate_reconciliation_plan(plan, self.fx.analyze()).valid)

        self.fx.base_commit({"docs/readme.md": "v3\n"})
        fresh = self.fx.analyze()
        self.assertRecon(fresh, rr.NO_TEXTUAL_CONFLICT)
        v = rr.validate_reconciliation_plan(plan, fresh)
        self.assertFalse(v.valid)
        self.assertIn(rr.PLAN_BASE_CHANGED, v.reason_codes)
        self.assertIn(rr.PLAN_FACTS_CHANGED, v.reason_codes)

        self.fx.head_commit({"src/b.py": "b\n"})
        fresh = self.fx.analyze()
        self.assertRecon(fresh, rr.NO_TEXTUAL_CONFLICT)
        v = rr.validate_reconciliation_plan(plan, fresh)
        self.assertFalse(v.valid)
        self.assertIn(rr.PLAN_HEAD_CHANGED, v.reason_codes)
        self.assertIn(rr.PLAN_SCOPE_VIOLATION, v.reason_codes)  # scope grew: not the planned scope


# ---------------------------------------------------------------------------
# Security and non-mutation
# ---------------------------------------------------------------------------

class SecurityAndReadOnlyTests(ReconTestCase):
    def _two_hunk_scenario(self, fx):
        fx.head_commit({"src/a.py": text({2: "head\n", 8: "head\n"})})
        fx.base_commit({"src/a.py": text({5: "base\n"})})

    def test_hostile_config_cannot_run_programs_or_change_results(self):
        for ext_diff in (False, True):
            with self.subTest(ext_diff=ext_diff):
                fx = Fixture(self.root, f"hostile-{int(ext_diff)}")
                self._two_hunk_scenario(fx)
                clean = fx.analyze()
                self.assertRecon(clean, rr.NO_TEXTUAL_CONFLICT, rr.RECON_DISJOINT_HUNKS)
                armed = self.root / f"armed-{int(ext_diff)}"
                armed.mkdir()
                markers = install_hostile_config(fx.repo, armed, ext_diff=ext_diff)
                for key, value in (("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"),
                                   ("diff.interHunkContext", "20"), ("diff.context", "7"),
                                   ("diff.algorithm", "histogram"), ("diff.renames", "copies"),
                                   ("diff.relative", "true"), ("color.ui", "always"), ("color.diff", "always"),
                                   ("core.abbrev", "7"), ("diff.ignoreSubmodules", "all")):
                    plain_git(fx.repo, "config", key, value)
                hostile = fx.analyze()
                self.assertEqual(fired_markers(markers), [])
                self.assertEqual(hostile.classification, clean.classification)
                self.assertEqual(hostile.facts, clean.facts)
                self.assertEqual(hostile.path_findings, clean.path_findings)
                # Positive controls: plain git really runs the programs and
                # really reshapes its output under this configuration.
                fused = plain_git(fx.wt, "diff", "--no-ext-diff", "-U0", fx.c0, "HEAD").stdout
                self.assertNotIn("diff --git a/", fused)
                self.assertIn("\x1b[", fused)
                self.assertIn("@@ -2,7 +2,7 @@", fused)
                plain_git(fx.wt, "diff", fx.c0, "HEAD")
                plain_git(fx.wt, "status", "--porcelain=v1")
                plain_git(fx.wt, "hook", "run", "--ignore-missing", "post-index-change")
                expected = {"fsmonitor", "hook-post-index-change", "ext-diff" if ext_diff else "textconv"}
                self.assertTrue(expected <= set(fired_markers(markers)), fired_markers(markers))

    def test_only_governed_read_only_git_and_no_writes(self):
        self.fx.head_commit({"src/a.py": text({4: "head\n"})})
        self.fx.base_commit({"src/a.py": text({5: "base\n"})})
        os.utime(self.fx.wt / "src" / "a.py", None)  # stat-dirty: an unguarded status would rewrite the index
        evidence = good_evidence(self.fx.wt)
        wt_git_dir = Path(plain_git(self.fx.wt, "rev-parse", "--absolute-git-dir").stdout.strip())
        before_state = _git_dir_state([self.fx.repo / ".git"])
        before_refs = plain_git(self.fx.repo, "for-each-ref").stdout
        before_objects = plain_git(self.fx.repo, "count-objects", "-v").stdout
        before_listing = set(os.listdir(wt_git_dir))
        calls = []
        real_run = runner_git.subprocess.run

        def recording(cmd, *args, **kwargs):
            calls.append((list(cmd), dict(kwargs.get("env") or {})))
            return real_run(cmd, *args, **kwargs)

        with mock.patch.object(runner_git.subprocess, "run", recording):
            a = self.fx.analyze(evidence=evidence, ledger_root=self.root)
        self.assertRecon(a, rr.SEMANTIC_REVIEW_REQUIRED)

        allowed = ri._READ_SUBCOMMANDS | {"ls-files", "check-attr"}
        forbidden = {"merge", "merge-tree", "merge-file", "rebase", "checkout", "switch", "reset", "commit",
                     "update-ref", "update-index", "push", "fetch", "pull", "apply", "am", "cherry-pick",
                     "read-tree", "write-tree", "hash-object", "stash", "restore", "gc", "replace", "add"}
        diffs = []
        for cmd, env in calls:
            rest = cmd[3:]
            sub = rest[runner_git._subcommand_index(rest):]
            with self.subTest(cmd=sub[:2]):
                self.assertIn(sub[0], allowed)
                self.assertNotIn(sub[0], forbidden)
                for entry in runner_git.HARDENING_CONFIG:
                    self.assertIn(entry, rest)
            if sub[0] == "diff" and ("--raw" in sub or "--numstat" in sub or "-U0" in sub):
                diffs.append((rest, sub, env))
        self.assertEqual(len(diffs), 6)  # raw + numstat + hunks, for each side
        for rest, sub, env in diffs:
            for option in rr._PINNED_DIFF_OPTIONS + runner_git.DIFF_HARDENING_OPTIONS:
                self.assertIn(option, sub)
            self.assertIn("--no-replace-objects", rest)
            self.assertEqual(env.get("GIT_OPTIONAL_LOCKS"), "0")
            pathspecs = sub[sub.index("--") + 1:]
            self.assertTrue(all(p.startswith(":(literal)") for p in pathspecs), pathspecs)

        self.assertEqual(_git_dir_state([self.fx.repo / ".git"]), before_state)
        self.assertEqual(plain_git(self.fx.repo, "for-each-ref").stdout, before_refs)
        self.assertEqual(plain_git(self.fx.repo, "count-objects", "-v").stdout, before_objects)
        self.assertEqual(set(os.listdir(wt_git_dir)) - before_listing, {pipeline.WRITE_LEASE_DIRNAME})
        self.assertFalse((wt_git_dir / pipeline.WRITE_LEASE_DIRNAME / pipeline.DirLease.IDENTITY).exists())
        self.assertEqual(plain_git(self.fx.wt, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")

    def test_module_has_no_direct_process_or_write_access(self):
        source = Path(rr.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names} | {node.module for node in ast.walk(tree)
                                                if isinstance(node, ast.ImportFrom) and node.module}
        for module in ("subprocess", "os", "shutil", "socket", "urllib", "http", "pygit2", "dulwich", "git",
                       "runner_git"):
            self.assertNotIn(module, imported)
        self.assertNotIn("subprocess.", source)
        self.assertNotIn("open(", source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "_git"]
        self.assertEqual(len(calls), 1)  # the single governed read helper
        # The governed helper itself refuses every write subcommand.
        for bad in (("merge-tree", "a", "b"), ("merge",), ("update-ref", "x"), ("checkout",)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ri._git(self.fx.wt, *bad)


def fired_markers(markers) -> list:
    return sorted(p.name for p in Path(markers).iterdir()) if markers and Path(markers).is_dir() else []


# ---------------------------------------------------------------------------
# FCP-2B-FIX-01: forced-text binaries, case collisions with unchanged tree
# paths, provably bounded hunk reads
# ---------------------------------------------------------------------------

NUL_BLOB = b"hello\0evil\n"


def recording_git():
    """(calls, patch): records the args of every governed read."""
    calls, real = [], ri._git

    def recording(repo, *args, **kwargs):
        calls.append(args)
        return real(repo, *args, **kwargs)

    return calls, mock.patch.object(ri, "_git", recording)


def blob_sha(repo: Path, rev: str, path: str) -> str:
    return plain_git(repo, "rev-parse", f"{rev}:{path}").stdout.strip()


def blob_verdicts(analysis) -> dict:
    return {sha: verdict for sha, _, verdict in analysis.facts.blob_checks}


class ForcedTextBinaryTests(ReconTestCase):
    """Defect A: with `*.dat diff`, numstat reports line counts for a NUL
    blob, so the binary flag alone would let it through as text."""

    def setUp(self):
        super().setUp()
        info = self.fx.repo / ".git" / "info"
        info.mkdir(exist_ok=True)
        (info / "attributes").write_text("*.dat diff\n", encoding="utf-8", newline="\n")
        self.c1 = self.fx.base_commit({"src/sample.dat": "hello\n"})  # tracked text in the merge base
        self.wt = self.fx.add_worktree("forced-wt", "feature/forced", self.c1)

    def head_commit(self, files=None, **kw):
        return self.fx.head_commit(files, worktree=self.wt, **kw)

    def assertForcedText(self, old, new, path="src/sample.dat"):
        # Positive control: git really reports text counts for the NUL blob.
        out = plain_git(self.wt, "diff", "--numstat", old, new, "--", path).stdout
        self.assertRegex(out, r"^[0-9]+\t[0-9]+\t" + path)
        self.assertIn(b"\0", subprocess.run(["git", "-C", str(self.wt), "cat-file", "blob", f"{new}:{path}"],
                                            capture_output=True, check=True).stdout)

    def assertBinaryHuman(self, a, path="src/sample.dat"):
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_BINARY)
        self.assertNotIn(rr.NO_TEXTUAL_CONFLICT, (a.classification,))
        finding = self.finding(a, path)
        self.assertEqual(finding.outcome, rr.PATH_HUMAN_REQUIRED)
        self.assertIn(rr.RECON_BINARY, finding.reason_codes)
        for ch in a.facts.head_changes + a.facts.base_changes:
            if ch.path == path:
                self.assertIs(ch.binary, False)  # numstat alone was fooled

    def test_head_only_forced_text_nul_blob(self):
        head_sha = self.head_commit({"src/sample.dat": NUL_BLOB})
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        self.assertForcedText(self.c1, head_sha)
        a = self.fx.analyze(self.wt)
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)
        self.assertBinaryHuman(a)
        self.assertEqual(blob_verdicts(a)[blob_sha(self.wt, head_sha, "src/sample.dat")], rr.BLOB_BINARY)

    def test_base_only_forced_text_nul_blob(self):
        self.head_commit({"src/a.py": text({2: "head\n"})})
        base = self.fx.base_commit({"src/sample.dat": NUL_BLOB})
        self.assertForcedText(self.c1, base)
        a = self.fx.analyze(self.wt)
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)
        self.assertBinaryHuman(a)
        self.assertEqual(self.finding(a, "src/a.py").outcome, rr.PATH_HEAD_ONLY)

    def test_convergent_forced_text_nul_blob(self):
        head_sha = self.head_commit({"src/sample.dat": NUL_BLOB})
        self.fx.base_commit({"src/sample.dat": NUL_BLOB})
        self.assertForcedText(self.c1, head_sha)
        a = self.fx.analyze(self.wt)
        self.assertEqual(a.assessment_classification, ri.NEEDS_RECONCILIATION)
        self.assertBinaryHuman(a)

    def test_both_sides_and_added_forced_text_nul_blobs(self):
        head_sha = self.head_commit({"src/sample.dat": b"hello\0head\n", "src/new.dat": NUL_BLOB})
        self.fx.base_commit({"src/sample.dat": b"hello\0base\n"})
        self.assertForcedText(self.c1, head_sha, "src/new.dat")
        a = self.fx.analyze(self.wt)
        self.assertBinaryHuman(a)
        self.assertBinaryHuman(a, "src/new.dat")

    def test_nul_beyond_git_heuristic_without_attributes(self):
        late = b"x" * 9000 + b"\0tail\n"  # git only inspects the first 8000 bytes
        head_sha = self.head_commit({"src/late.txt": late})
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        self.assertForcedText(self.c1, head_sha, "src/late.txt")
        self.assertBinaryHuman(self.fx.analyze(self.wt), "src/late.txt")

    def test_text_blob_under_forcing_attribute_stays_no_textual(self):
        # Negative control: the attribute alone does not make a text change human.
        self.head_commit({"src/sample.dat": "hello world\n"})
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        a = self.fx.analyze(self.wt)
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT, rr.RECON_DISJOINT_PATHS)
        self.assertEqual(set(blob_verdicts(a).values()), {rr.BLOB_TEXT})

    def test_text_safety_unproven_beyond_limits_is_human(self):
        head_sha = self.head_commit({"src/sample.dat": "hello world\n"})
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        sample = {blob_sha(self.wt, rev, "src/sample.dat") for rev in (self.c1, head_sha)}
        for name, value in (("MAX_BLOB_BYTES", 4), ("MAX_BLOB_TOTAL_BYTES", 0)):
            with self.subTest(limit=name):
                calls, recording = recording_git()
                with mock.patch.object(rr, name, value), recording:
                    a = self.fx.analyze(self.wt)
                    self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_TEXT_SAFETY_UNPROVEN)
                self.assertEqual(self.finding(a, "src/sample.dat").outcome, rr.PATH_HUMAN_REQUIRED)
                self.assertEqual({blob_verdicts(a)[sha] for sha in sample}, {rr.BLOB_UNPROVEN})
                self.assertFalse([c for c in calls if c[:2] == ("cat-file", "blob") and c[2] in sample])
                self.assertEqual(sample - {c[2] for c in calls if c[:2] == ("cat-file", "-s")}, set())
                self.assertIsNone(rr.propose_reconciliation_plan(a, acceptance_commands=ACCEPTANCE))


def case_sensitive_filesystem() -> bool:
    probe = Path(tempfile.mkdtemp(prefix="fcp2b-case-"))
    try:
        (probe / "a").write_bytes(b"")
        return not (probe / "A").exists()
    finally:
        _rmtree(probe)


class CaseCollisionTests(ReconTestCase):
    """Defect B: collisions with paths that are UNCHANGED in the merge-base
    tree, directory prefixes and cross-side additions."""

    def test_base_adds_case_variant_of_unchanged_path(self):
        self.fx.head_commit({"src/old.py": "head\n"})
        variant = hash_blob(self.fx.repo, b"variant\n")
        self.fx.base_commit(index_entries=(("100644", variant, "src/A.py"),))
        tree = plain_git(self.fx.repo, "ls-tree", "-r", "--name-only", self.fx.base).stdout.split("\n")
        self.assertIn("src/a.py", tree)  # positive control: both names exist in the base tip
        self.assertIn("src/A.py", tree)
        a = self.fx.analyze()
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)
        # src/a.py is unchanged on BOTH sides: only the merge-base tree knows it.
        self.assertNotIn("src/a.py", {ch.path for ch in a.facts.head_changes + a.facts.base_changes})
        self.assertEqual(rr._case_collisions({"src/old.py", "src/A.py"}), set())  # the old, diff-only view
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_CASE_COLLISION)
        self.assertEqual(a.facts.case_checks, (("src/A.py", rr.CASE_COLLISION),))
        self.assertIn(rr.RECON_CASE_COLLISION, self.finding(a, "src/A.py").reason_codes)
        self.assertEqual(self.finding(a, "src/old.py").outcome, rr.PATH_HEAD_ONLY)

    def test_head_adds_normalization_variant_of_unchanged_path(self):
        nfc, nfd = "src/café.py", "src/café.py"
        c1 = self.fx.base_commit({nfc: "nfc\n"})
        wt = self.fx.add_worktree("nfd-wt", "feature/nfd", c1)
        self.fx.head_commit({nfd: "nfd\n"}, worktree=wt)
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        a = self.fx.analyze(wt)
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)
        self.assertEqual({ch.path for ch in a.facts.head_changes}, {nfd})
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_CASE_COLLISION)
        self.assertEqual(a.facts.case_checks, ((nfd, rr.CASE_COLLISION),))

    @unittest.skipUnless(case_sensitive_filesystem(), "needs a case-sensitive filesystem for both names")
    def test_head_adds_ascii_case_variant_of_unchanged_path(self):
        self.fx.head_commit({"src/A.py": "variant\n"})
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        a = self.fx.analyze()
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_CASE_COLLISION)

    def test_reader_against_real_merge_base_tree(self):
        # The exact FCP-2B-FIX-01 scenario, independent of the filesystem:
        # candidate additions checked against the real, unchanged c0 tree.
        reader_cases = {
            "src/A.py": rr.CASE_COLLISION,            # unchanged src/a.py
            "SRC/x.py": rr.CASE_COLLISION,            # directory prefix vs src/
            "docs/README.md/x": rr.CASE_COLLISION,    # nested prefix vs docs/readme.md
            "Shared.TXT": rr.CASE_COLLISION,
            "src/new.py": rr.CASE_SAFE,
            "src/pkg/new.py": rr.CASE_SAFE,           # directory absent from the merge base
            "src/a.py/b": rr.CASE_SAFE,               # a.py is a file: nothing below it
        }
        calls, recording = recording_git()
        with recording:
            checks = rr._read_case_checks(self.fx.wt, self.fx.c0, set(reader_cases), "sha1")
        self.assertEqual(dict(checks), reader_cases)
        self.assertEqual([c[0] for c in checks], sorted(reader_cases))
        self.assertTrue(all(c[0] in ("rev-parse", "cat-file") for c in calls), calls)
        self.assertTrue(all(c[1] in ("-s", "tree") for c in calls if c[0] == "cat-file"), calls)
        self.assertEqual(sum(1 for c in calls if c[:2] == ("cat-file", "tree")), 3)  # root, src, docs: cached

    def test_directory_prefix_against_unchanged_tree(self):
        c1 = self.fx.base_commit({"src/pkg/mod.py": "mod\n"})
        wt = self.fx.add_worktree("prefix-wt", "feature/prefix", c1)
        self.fx.head_commit({"src/a.py": text({2: "head\n"})}, worktree=wt)
        blob = hash_blob(self.fx.repo, b"new\n")
        self.fx.base_commit(index_entries=(("100644", blob, "src/PKG/new.py"), ("100644", blob, "DOCS/x.md")))
        a = self.fx.analyze(wt)
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_CASE_COLLISION)
        self.assertEqual(dict(a.facts.case_checks),
                         {"src/PKG/new.py": rr.CASE_COLLISION, "DOCS/x.md": rr.CASE_COLLISION})
        # Only the unchanged merge-base tree reveals them: no changed path collides.
        self.assertEqual(rr._case_collisions({"src/a.py", "src/PKG/new.py", "DOCS/x.md"}), set())

    def test_cross_side_additions(self):
        self.fx.head_commit({"src/Lib/x.py": "x\n"})
        self.fx.base_commit({"src/lib/y.py": "y\n"})
        a = self.fx.analyze()
        self.assertEqual(a.assessment_classification, ri.STALE_BASE)
        # Neither collides with the merge base; they collide with each other.
        self.assertEqual(set(dict(a.facts.case_checks).values()), {rr.CASE_SAFE})
        self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_CASE_COLLISION)
        for path in ("src/Lib/x.py", "src/lib/y.py"):
            self.assertIn(rr.RECON_CASE_COLLISION, self.finding(a, path).reason_codes)

    def test_case_safety_unproven_beyond_limits_is_human(self):
        self.fx.head_commit({"src/new.py": "new\n"})
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        self.assertRecon(self.fx.analyze(), rr.NO_TEXTUAL_CONFLICT)  # positive control
        for name, value in (("MAX_TREE_READS", 1), ("MAX_TREE_BYTES", 1), ("MAX_TREE_TOTAL_BYTES", 0)):
            with self.subTest(limit=name), mock.patch.object(rr, name, value):
                a = self.fx.analyze()
                self.assertRecon(a, rr.HUMAN_REQUIRED, rr.RECON_CASE_SAFETY_UNPROVEN)
                self.assertEqual(a.facts.case_checks, (("src/new.py", rr.CASE_UNPROVEN),))

    def test_clean_disjoint_with_new_file_stays_no_textual(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"}), "src/new_module.py": "new\n"})
        self.fx.base_commit({"src/a.py": text({9: "base\n"}), "docs/readme.md": "v2\n"})
        a = self.fx.analyze()
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT, rr.RECON_DISJOINT_HUNKS, rr.RECON_DISJOINT_PATHS)
        self.assertEqual(a.facts.case_checks, (("src/new_module.py", rr.CASE_SAFE),))
        self.assertEqual(set(blob_verdicts(a).values()), {rr.BLOB_TEXT})
        plan = rr.propose_reconciliation_plan(a, acceptance_commands=ACCEPTANCE)
        self.assertTrue(rr.validate_reconciliation_plan(plan, self.fx.analyze()).valid)
        self.assertIs(plan.semantic_validation_required, True)

    def test_modification_only_reads_no_tree(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n"})})
        self.fx.base_commit({"docs/readme.md": "v2\n"})
        calls, recording = recording_git()
        with recording:
            a = self.fx.analyze()
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT, rr.RECON_DISJOINT_PATHS)
        self.assertEqual(a.facts.case_checks, ())
        self.assertFalse([c for c in calls if c[:2] == ("cat-file", "tree")])


class BoundedHunkReadTests(ReconTestCase):
    def test_large_single_line_fails_closed_before_hunk_request(self):
        size = rr.MAX_HUNK_BYTES + 64
        c1 = self.fx.base_commit({"src/big.txt": "x" * size + "\n"})
        wt = self.fx.add_worktree("big-wt", "feature/big", c1)
        head_sha = self.fx.head_commit({"src/big.txt": "y" * size + "\n"}, worktree=wt)
        self.fx.base_commit({"src/big.txt": "z" * size + "\n"})
        # Positive control: numstat counts are tiny, so the line-count lower
        # bound alone would have let the >2 MiB hunk output be requested.
        self.assertEqual(plain_git(wt, "diff", "--numstat", c1, head_sha).stdout, "1\t1\tsrc/big.txt\n")
        big = {blob_sha(wt, rev, "src/big.txt") for rev in (c1, head_sha, self.fx.base)}
        calls, recording = recording_git()
        with recording:
            a = self.fx.analyze(wt)
        self.assertEqual(a.assessment_classification, ri.NEEDS_RECONCILIATION)
        self.assertRecon(a, rr.FAIL_CLOSED, rr.RECON_HUNK_LIMIT_EXCEEDED)
        self.assertFalse(a.semantic_validation_required)
        self.assertFalse([c for c in calls if "-U0" in c])
        self.assertFalse([c for c in calls if c[:2] == ("cat-file", "blob") and c[2] in big])
        self.assertEqual({c[2] for c in calls if c[:2] == ("cat-file", "-s")}, big)
        self.assertEqual({sha: v for sha, _, v in a.facts.blob_checks}, dict.fromkeys(big, rr.BLOB_UNPROVEN))

    def test_bound_covers_real_output_and_post_read_gate_is_kept(self):
        self.fx.head_commit({"src/a.py": text({2: "head\n", 12: "tail without newline"})})
        self.fx.base_commit({"src/a.py": text({7: "base\n"})})
        a = self.fx.analyze()
        self.assertRecon(a, rr.NO_TEXTUAL_CONFLICT, rr.RECON_DISJOINT_HUNKS)
        sizes = {sha: size for sha, size, _ in a.facts.blob_checks}
        for changes, read in ((a.facts.head_changes, a.facts.head_hunk_bytes),
                              (a.facts.base_changes, a.facts.base_hunk_bytes)):
            bound = rr._hunk_bound(["src/a.py"], {ch.path: ch for ch in changes}, sizes)
            self.assertLessEqual(read, bound)
            self.assertGreater(read, 0)
        # Second gate: a (hypothetically) wrong precheck still fails closed after the read.
        with mock.patch.object(rr, "_hunk_bound", return_value=0), mock.patch.object(rr, "MAX_HUNK_BYTES", 10):
            calls, recording = recording_git()
            with recording:
                gated = self.fx.analyze()
        self.assertRecon(gated, rr.FAIL_CLOSED, rr.RECON_HUNK_LIMIT_EXCEEDED)
        self.assertTrue([c for c in calls if "-U0" in c])


class FixPureFactsTests(unittest.TestCase):
    """Pure classification of edited blob/case facts from one real analysis:
    head adds src/new.py and edits line 10, base edits line 5."""

    @classmethod
    def setUpClass(cls):
        patch = mock.patch.dict(os.environ, _ISOLATED_ENV)
        patch.start()
        cls.addClassCleanup(patch.stop)
        cls.root = Path(tempfile.mkdtemp(prefix="fcp2b-fix01-")).resolve()
        cls.addClassCleanup(_rmtree, cls.root)
        fx = cls.fx = Fixture(cls.root)
        fx.head_commit({"src/a.py": text({10: "head\n"}), "src/new.py": "new\n"})
        fx.base_commit({"src/a.py": text({5: "base\n"})})
        cls.analysis = fx.analyze()

    assertRecon = ReconTestCase.assertRecon

    def classify(self, **overrides):
        return rr.classify_reconciliation(self.analysis.assessment,
                                          dataclasses.replace(self.analysis.facts, **overrides))

    def test_baseline_and_determinism(self):
        self.assertRecon(self.analysis, rr.NO_TEXTUAL_CONFLICT, rr.RECON_DISJOINT_HUNKS)
        again = self.fx.analyze()
        self.assertEqual(again.fingerprint, self.analysis.fingerprint)
        self.assertEqual(again.facts, self.analysis.facts)
        self.assertEqual(rr.classify_reconciliation(self.analysis.assessment, self.analysis.facts), self.analysis)
        self.assertEqual(len(self.analysis.facts.blob_checks), 4)  # a.py: base, head, ours; new.py
        self.assertEqual(self.analysis.facts.case_checks, (("src/new.py", rr.CASE_SAFE),))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.analysis.facts.blob_checks = ()

    def test_verdicts_drive_human_required(self):
        checks = self.analysis.facts.blob_checks
        for verdict, reason in ((rr.BLOB_BINARY, rr.RECON_BINARY), (rr.BLOB_UNPROVEN, rr.RECON_TEXT_SAFETY_UNPROVEN)):
            with self.subTest(verdict=verdict):
                edited = tuple((sha, size, verdict) for sha, size, _ in checks)
                self.assertRecon(self.classify(blob_checks=edited), rr.HUMAN_REQUIRED, reason)
        for verdict, reason in ((rr.CASE_COLLISION, rr.RECON_CASE_COLLISION),
                                (rr.CASE_UNPROVEN, rr.RECON_CASE_SAFETY_UNPROVEN)):
            with self.subTest(verdict=verdict):
                self.assertRecon(self.classify(case_checks=(("src/new.py", verdict),)), rr.HUMAN_REQUIRED, reason)

    def test_missing_malformed_or_contradictory_checks_fail_closed(self):
        checks = self.analysis.facts.blob_checks
        sha, size, _ = checks[0]
        cases = (
            ({"blob_checks": None}, rr.RECON_MISSING_SAFETY_FACT),
            ({"blob_checks": checks[1:]}, rr.RECON_MISSING_SAFETY_FACT),
            ({"blob_checks": checks + (("f" * 40, 1, rr.BLOB_TEXT),)}, rr.RECON_CONTRADICTORY_CHANGE),
            ({"blob_checks": checks + checks[:1]}, rr.RECON_CONTRADICTORY_CHANGE),
            ({"blob_checks": ((sha, size, "MAYBE"),) + checks[1:]}, rr.RECON_MALFORMED_FACTS),
            ({"blob_checks": ((sha, -1, rr.BLOB_TEXT),) + checks[1:]}, rr.RECON_MALFORMED_FACTS),
            ({"blob_checks": ((sha, rr.MAX_BLOB_BYTES + 1, rr.BLOB_TEXT),) + checks[1:]}, rr.RECON_MALFORMED_FACTS),
            ({"blob_checks": list(checks)}, rr.RECON_MALFORMED_FACTS),
            ({"case_checks": None}, rr.RECON_MISSING_SAFETY_FACT),
            ({"case_checks": ()}, rr.RECON_MISSING_SAFETY_FACT),
            ({"case_checks": (("src/new.py", rr.CASE_SAFE), ("src/a.py", rr.CASE_SAFE))},
             rr.RECON_CONTRADICTORY_CHANGE),
            ({"case_checks": (("src/new.py", "SAFE"),)}, rr.RECON_MALFORMED_FACTS),
            ({"blob_checks": tuple((s, rr.MAX_HUNK_BYTES, rr.BLOB_UNPROVEN) for s, _, _ in checks)},
             rr.RECON_HUNK_LIMIT_EXCEEDED),  # hunks could not have been provably bounded
        )
        for overrides, reason in cases:
            with self.subTest(overrides=overrides):
                self.assertRecon(self.classify(**overrides), rr.FAIL_CLOSED, reason)

    def test_new_reads_are_governed_filter_free_and_write_nothing(self):
        info = self.fx.repo / ".git" / "info"
        before_objects = plain_git(self.fx.repo, "count-objects", "-v").stdout
        armed = self.root / "armed"
        armed.mkdir()
        markers = install_hostile_config(self.fx.repo, armed)  # also writes info/attributes "* diff=evil"
        self.addCleanup(plain_git, self.fx.repo, "config", "--unset", "diff.evil.textconv")
        self.addCleanup(plain_git, self.fx.repo, "config", "--unset", "core.fsmonitor")
        self.addCleanup(plain_git, self.fx.repo, "config", "--unset", "core.hooksPath")
        self.addCleanup((info / "attributes").unlink)
        calls, recording = recording_git()
        with recording:
            hostile = self.fx.analyze()
        self.assertEqual(fired_markers(markers), [])
        self.assertEqual(hostile.facts.blob_checks, self.analysis.facts.blob_checks)
        self.assertEqual(hostile.facts.case_checks, self.analysis.facts.case_checks)
        self.assertEqual(hostile.classification, self.analysis.classification)
        object_reads = [c for c in calls if c[0] in ("cat-file", "rev-parse") and ("-s" in c or "blob" in c
                                                                                   or "tree" in c or "--quiet" in c)]
        self.assertTrue(object_reads)
        for args in object_reads:
            with self.subTest(args=args):
                if args[0] == "cat-file":
                    self.assertEqual(len(args), 3)
                    self.assertIn(args[1], ("-s", "blob", "tree"))
                    self.assertRegex(args[2], r"^[0-9a-f]{40}$")
                else:
                    self.assertEqual(args, ("rev-parse", "--verify", "--quiet", self.fx.c0 + "^{tree}"))
        self.assertEqual(plain_git(self.fx.repo, "count-objects", "-v").stdout, before_objects)
        plain_git(self.fx.wt, "diff", self.fx.c0, "HEAD")  # positive control: textconv really armed
        self.assertIn("textconv", fired_markers(markers))


if __name__ == "__main__":
    unittest.main()
