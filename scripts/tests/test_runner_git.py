"""P1-3 git execution hardening: `runner_git.git_command` never lets a
target repository run hooks, fsmonitor, external diff or textconv programs.

Every hostile repository here is a throwaway under a TemporaryDirectory.
Each executable it configures appends to a marker file OUTSIDE the
repository (so markers never dirty the worktree under test). Positive
controls run the same operations through PLAIN git to prove the fixture
really fires - otherwise a "no marker" assertion would be vacuous.

The helpers at module level are reused by the Runner/Queue/Pipeline/
provider test modules; they are plain functions, not TestCases.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.ai import runner_git

HOOK_NAMES = (
    "pre-commit", "prepare-commit-msg", "commit-msg", "post-commit",
    "post-index-change", "reference-transaction", "pre-auto-gc", "post-rewrite",
    "post-checkout", "pre-push",
)


def plain_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """UNHARDENED git - only ever used on throwaway temp repositories."""
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def make_repo(root: Path, name: str = "repo") -> Path:
    repo = root / name
    repo.mkdir()
    plain_git(repo, "init", "-q", "-b", "main")
    plain_git(repo, "config", "user.email", "runner-git-tests@example.invalid")
    plain_git(repo, "config", "user.name", "Runner Git Tests")
    (repo / "README.md").write_text("seed\n", encoding="utf-8", newline="\n")
    plain_git(repo, "add", "README.md")
    plain_git(repo, "commit", "-q", "-m", "seed commit")
    return repo


def _write_script(path: Path, body: str) -> None:
    # LF endings and a /bin/sh shebang: runs under POSIX sh and under the sh
    # bundled with Git for Windows (Git Bash) alike.
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
    os.chmod(path, 0o755)


def _marker_append(markers: Path, name: str) -> str:
    return f'echo fired >> "{(markers / name).as_posix()}"\n'


def install_hooks(hooks_dir: Path, markers: Path) -> None:
    hooks_dir.mkdir(parents=True, exist_ok=True)
    for hook in HOOK_NAMES:
        _write_script(hooks_dir / hook, _marker_append(markers, f"hook-{hook}") + "exit 0\n")


def install_hostile_config(repo: Path, root: Path, *, ext_diff: bool = False) -> Path:
    """Arms `repo` with marker hooks (in .git/hooks AND in a repository-
    configured core.hooksPath), a hook-style core.fsmonitor, and either a
    textconv driver (default) or diff.external - the two are exclusive
    because an external diff takes precedence over textconv in plain git.
    Returns the markers directory."""
    markers = root / "markers"
    markers.mkdir(exist_ok=True)
    install_hooks(repo / ".git" / "hooks", markers)
    configured_hooks = root / "configured-hooks"
    install_hooks(configured_hooks, markers)
    plain_git(repo, "config", "core.hooksPath", configured_hooks.as_posix())

    fsmonitor = root / "fsmonitor.sh"
    _write_script(fsmonitor, _marker_append(markers, "fsmonitor") + "exit 1\n")
    plain_git(repo, "config", "core.fsmonitor", f'sh "{fsmonitor.as_posix()}"')

    if ext_diff:
        extdiff = root / "extdiff.sh"
        _write_script(extdiff, _marker_append(markers, "ext-diff") + "exit 0\n")
        plain_git(repo, "config", "diff.external", f'sh "{extdiff.as_posix()}"')
    else:
        textconv = root / "textconv.sh"
        _write_script(textconv, _marker_append(markers, "textconv") + 'cat "$1"\n')
        plain_git(repo, "config", "diff.evil.textconv", f'sh "{textconv.as_posix()}"')
        (repo / ".git" / "info").mkdir(exist_ok=True)
        (repo / ".git" / "info" / "attributes").write_text("* diff=evil\n", encoding="utf-8", newline="\n")

    # A hook-mode fsmonitor is only queried once the index carries an
    # fsmonitor token; prime it with plain git (twice: the first run may only
    # record the token) so every later status really would consult it. Then
    # reset the markers so tests observe only their own operations.
    plain_git(repo, "status", "--porcelain=v1")
    plain_git(repo, "status", "--porcelain=v1")
    for marker in markers.iterdir():
        marker.unlink()
    return markers


FILTERED_FILE = "tracked.dat"


def install_filter(
    repo: Path, root: Path, *, driver: str = "evil", kind: str = "clean", required: bool = False,
    attributes: str = "gitattributes", tracked_file: bool = True, configure: bool = True,
) -> Path:
    """Arms `repo` with a content filter whose program appends to a marker:
    `kind` "clean" (a pass-through `cat`) or "process" (fails the
    long-running protocol handshake, after leaving its marker). The
    `*.dat filter=<driver>` rule lives in a committed .gitattributes
    ("gitattributes") or in .git/info/attributes ("info"). With
    `tracked_file`, FILTERED_FILE is committed first - before the driver is
    configured, so the fixture itself never fires it. `configure=False`
    leaves the driver to the caller (e.g. inherited environment config).
    Returns the markers directory."""
    markers = root / "markers"
    markers.mkdir(exist_ok=True)
    rule = f"*.dat filter={driver}\n"
    if attributes == "gitattributes":
        (repo / ".gitattributes").write_text(rule, encoding="utf-8", newline="\n")
        plain_git(repo, "add", ".gitattributes")
    else:
        (repo / ".git" / "info").mkdir(exist_ok=True)
        (repo / ".git" / "info" / "attributes").write_text(rule, encoding="utf-8", newline="\n")
    if tracked_file:
        (repo / FILTERED_FILE).write_text("original\n", encoding="utf-8", newline="\n")
        plain_git(repo, "add", FILTERED_FILE)
    if attributes == "gitattributes" or tracked_file:
        plain_git(repo, "commit", "-q", "-m", "filter fixture")

    script = root / f"filter-{driver}-{kind}.sh"
    tail = 'cat\n' if kind == "clean" else "exit 1\n"
    _write_script(script, _marker_append(markers, f"filter-{driver}-{kind}") + tail)
    if configure:
        plain_git(repo, "config", f"filter.{driver}.{kind}", f'sh "{script.as_posix()}"')
        if required:
            plain_git(repo, "config", f"filter.{driver}.required", "true")
    return markers


def modify_same_size(path: Path) -> None:
    """Changes content but not size: `git status` must then hash the file
    (running its clean filter) instead of deciding from the size alone."""
    path.write_text("ORIGINAL\n", encoding="utf-8", newline="\n")
    os.utime(path, (1_000_000_000, 1_000_000_000))


def filter_program(root: Path, driver: str = "evil", kind: str = "clean") -> str:
    return f'sh "{(root / f"filter-{driver}-{kind}.sh").as_posix()}"'


def install_signing(repo: Path, root: Path, *, fmt: str = "openpgp") -> Path:
    """commit.gpgSign=true with a signing program that leaves a marker and
    fails. Returns the markers directory."""
    markers = root / "markers"
    markers.mkdir(exist_ok=True)
    signer = root / f"sign-{fmt}.sh"
    _write_script(signer, _marker_append(markers, f"sign-{fmt}") + "exit 1\n")
    plain_git(repo, "config", "commit.gpgSign", "true")
    plain_git(repo, "config", "gpg.format", fmt)
    if fmt == "ssh":
        plain_git(repo, "config", "gpg.ssh.program", signer.as_posix())
        plain_git(repo, "config", "user.signingKey", "key::ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample")
    else:
        plain_git(repo, "config", "gpg.program", signer.as_posix())
        plain_git(repo, "config", "user.signingKey", "runner-git-tests@example.invalid")
    return markers


# Every spelling git commit takes as --gpg-sign (P1-3 FIX3), with and without a key.
SIGNING_ABBREVIATIONS = (
    "--g", "--gp", "--gpg", "--gpg-", "--gpg-s", "--gpg-si", "--gpg-sig",
    "--g=k", "--gpg=k", "--gpg-sig=k", "--gpg-sign=", "--gpg-sign=k",
)


def fired(markers: Path) -> list:
    return sorted(p.name for p in markers.iterdir()) if markers.is_dir() else []


def hardened_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(runner_git.git_command(repo, args), capture_output=True, text=True)


class _TempRootMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)


class GitCommandShapeTest(unittest.TestCase):
    def _hardening(self) -> list:
        out = []
        for entry in runner_git.HARDENING_CONFIG:
            out += ["-c", entry]
        return out

    def test_plain_subcommand(self):
        self.assertEqual(
            runner_git.git_command(Path("r"), ["rev-parse", "HEAD"]),
            ["git", "-C", str(Path("r")), *self._hardening(), "rev-parse", "HEAD"],
        )

    def test_hardening_follows_caller_global_options_so_it_cannot_be_overridden(self):
        cmd = runner_git.git_command("r", ["-c", "core.hooksPath=evil", "-c", "user.name=X", "commit", "-m", "m"])
        self.assertEqual(
            cmd, ["git", "-C", "r", "-c", "core.hooksPath=evil", "-c", "user.name=X",
                  *self._hardening(), "commit", "--no-gpg-sign", "-m", "m"],
        )

    def test_caller_signing_config_is_overridden(self):
        cmd = runner_git.git_command("r", ["-c", "commit.gpgSign=true", "commit", "-m", "m"])
        self.assertLess(cmd.index("commit.gpgSign=true"), cmd.index("commit.gpgSign=false"))
        self.assertEqual(cmd[-4:], ["commit", "--no-gpg-sign", "-m", "m"])

    def test_commit_signing_options_are_refused(self):
        for args in (["-S"], ["-Skeyid"], ["--gpg-sign"], ["--gpg-sign=k"], ["-qS"], ["-a", "-S", "-m", "m"]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                runner_git.git_command("r", ["commit", *args])
        # A message value or a pathspec is not an option.
        for args in (["-m", "-S looks like an option"], ["-m", "m", "--", "-S"], ["--no-gpg-sign", "-m", "m"]):
            with self.subTest(args=args):
                runner_git.git_command("r", ["commit", *args])

    def test_commit_signing_abbreviations_are_refused(self):
        # P1-3 FIX3: git commit accepts every prefix of --gpg-sign.
        for option in SIGNING_ABBREVIATIONS:
            for args in ([option], ["-m", "m", option], [option, "-m", "m"], ["--no-gpg-sign", option, "-m", "m"]):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    runner_git.git_command("r", ["commit", *args])
            with self.subTest(global_opts=True, option=option), self.assertRaises(ValueError):
                runner_git.git_command("r", ["-c", "user.name=X", "commit", option, "-m", "m"])

    def test_commit_signing_lookalikes_are_not_refused(self):
        for args in (
            # Negations, abbreviated or not, only turn signing off.
            ["--no-gpg-sign"], ["--no-gpg-sig"], ["--no-gpg"], ["--no-g"],
            # Option values and pathspecs are not options.
            ["-m", "--gpg"], ["--message", "--g"], ["-F", "--gpg-sig"], ["--author", "--gp <a@b.c>"],
            ["-m", "m", "--", "--gpg", "--g", "--gpg-sign"], ["--message=--gpg-sign"],
            # Unrelated long options.
            ["--allow-empty", "--no-verify", "-q", "-m", "m"], ["--amend", "--no-edit"],
        ):
            with self.subTest(args=args):
                cmd = runner_git.git_command("r", ["commit", *args])
                self.assertEqual(cmd[-len(args) - 2:], ["commit", "--no-gpg-sign", *args])
        # Only `commit` is scanned.
        self.assertEqual(runner_git.git_command("r", ["add", "--", "--gpg"])[-3:], ["add", "--", "--gpg"])

    def test_filter_drivers_are_neutralized_and_required(self):
        cmd = runner_git.git_command("r", ["status"], filter_drivers=["lfs"])
        for entry in ("filter.lfs.clean=", "filter.lfs.process=", "filter.lfs.smudge=", "filter.lfs.required=true"):
            self.assertIn(entry, cmd)
        self.assertEqual(cmd[-1], "status")
        for name in ("a=b", "a\nb", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner_git.git_command("r", ["status"], filter_drivers=[name])

    def test_diff_gets_no_ext_diff_no_textconv_and_short_submodules(self):
        cmd = runner_git.git_command("r", ["diff", "--binary", "HEAD", "--", "."])
        self.assertEqual(
            cmd[-8:], ["diff", "--no-ext-diff", "--no-textconv", "--submodule=short", "--binary", "HEAD", "--", "."],
        )

    def test_diff_submodule_options_that_may_run_programs_are_refused(self):
        for option in (
            "--submodule=diff", "--submodule=", "--submodule=x",
            # Abbreviations (accepted by some Git versions), with or without a value.
            "--submodul=diff", "--sub=diff", "--su=diff", "--s=diff", "--sub", "--s", "--submodul=short",
            # Negation resets to the configured format (possibly diff.submodule=diff).
            "--no-submodule", "--no-sub", "--no-s", "--no-",
        ):
            for args in ([option], ["HEAD", option], ["--binary", "--full-index", "HEAD", option, "--", "."]):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    runner_git.git_command("r", ["diff", *args])
        with self.assertRaises(ValueError):
            runner_git.git_command("r", ["-c", "diff.submodule=diff", "diff", "--submodule=diff"])
        for args in (
            ["--submodule"], ["--submodule=log"], ["--submodule=short"], ["HEAD", "--", "--submodule=diff"],
            ["--stat"], ["--summary"], ["--ignore-submodules"], ["--ignore-submodules=dirty"],
        ):
            with self.subTest(args=args):
                cmd = runner_git.git_command("r", ["diff", *args])
                self.assertEqual(cmd[-len(args) - 4:], ["diff", *runner_git.DIFF_HARDENING_OPTIONS, *args])

    def test_diff_options_reenabling_external_programs_are_refused(self):
        for option in (
            "--ext-diff", "--textconv", "--ext-diff=1", "--textconv=true",
            # Abbreviations (accepted by some Git versions) and ambiguous prefixes.
            "--ext", "--ext-", "--ext-d", "--ext-dif", "--e", "--ex",
            "--textc", "--textco", "--textcon", "--t", "--te", "--tex",
        ):
            for args in (
                [option], ["HEAD", option], ["--binary", option, "HEAD", "--", "."],
                ["--cached", "--check", option], ["--no-ext-diff", "--no-textconv", option],
            ):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    runner_git.git_command("r", ["diff", *args])
        # Caller global options before the subcommand do not hide them.
        with self.assertRaises(ValueError):
            runner_git.git_command("r", ["-c", "core.quotePath=false", "diff", "--textconv"])

    def test_diff_pathspecs_and_unrelated_options_are_not_refused(self):
        for args in (
            ["HEAD", "--", "--ext-diff"], ["--", "--textconv", "--ext", "--textc"],
            ["--cached", "--check", "--", "a.txt"], ["--binary", "--full-index", "HEAD", "--", "."],
            ["--text"], ["-a"], ["--exit-code"], ["--no-ext-diff"], ["--no-textconv"], ["--no-ext"],
            ["--name-status", "-z", "--no-renames", "HEAD", "--"], ["--stat"], ["--", ":(exclude)--textconv"],
        ):
            with self.subTest(args=args):
                cmd = runner_git.git_command("r", ["diff", *args])
                self.assertEqual(cmd[-len(args) - 4:], ["diff", *runner_git.DIFF_HARDENING_OPTIONS, *args])
        # Only `diff` is scanned: the same token elsewhere is someone else's business.
        self.assertEqual(runner_git.git_command("r", ["add", "--", "--textconv"])[-3:], ["add", "--", "--textconv"])

    def test_non_diff_subcommand_arguments_untouched(self):
        args = ["status", "--porcelain=v1", "--branch", "--untracked-files=all"]
        self.assertEqual(runner_git.git_command("r", args)[-len(args):], args)
        # A "diff" that is a pathspec/value, not the subcommand, is not rewritten.
        self.assertEqual(runner_git.git_command("r", ["add", "--", "diff"])[-3:], ["add", "--", "diff"])

    def test_config_covers_fsmonitor_hooks_and_signing(self):
        keys = {entry.split("=", 1)[0] for entry in runner_git.HARDENING_CONFIG}
        self.assertEqual(
            keys, {"core.fsmonitor", "core.useBuiltinFSMonitor", "core.hooksPath", "commit.gpgSign", "diff.submodule"},
        )
        self.assertIn("core.fsmonitor=false", runner_git.HARDENING_CONFIG)
        self.assertIn("commit.gpgSign=false", runner_git.HARDENING_CONFIG)
        self.assertIn("diff.submodule=short", runner_git.HARDENING_CONFIG)

    def test_disabled_hooks_path_can_never_hold_hooks(self):
        path = Path(runner_git.DISABLED_HOOKS_PATH)
        self.assertTrue(path.is_absolute())
        self.assertFalse(path.exists())
        self.assertTrue(path.parent.is_file())


class PlainGitControlTest(_TempRootMixin, unittest.TestCase):
    """Proves the fixtures are live and documents the diagnosis: plain git
    runs these programs, `commit --no-verify` included."""

    def test_commit_no_verify_still_runs_prepare_commit_msg_and_post_commit(self):
        repo = make_repo(self.root)
        markers = install_hostile_config(repo, self.root)
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        plain_git(repo, "add", "a.txt")
        plain_git(repo, "commit", "--no-verify", "-q", "-m", "x")
        hits = fired(markers)
        self.assertIn("hook-prepare-commit-msg", hits)
        self.assertIn("hook-post-commit", hits)
        self.assertNotIn("hook-pre-commit", hits)

    def test_status_runs_fsmonitor(self):
        repo = make_repo(self.root)
        markers = install_hostile_config(repo, self.root)
        plain_git(repo, "status", "--porcelain=v1")
        self.assertIn("fsmonitor", fired(markers))

    def test_diff_runs_textconv(self):
        repo = make_repo(self.root)
        markers = install_hostile_config(repo, self.root)
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        plain_git(repo, "diff", "HEAD")
        self.assertIn("textconv", fired(markers))

    def test_diff_runs_external_diff(self):
        repo = make_repo(self.root)
        markers = install_hostile_config(repo, self.root, ext_diff=True)
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        plain_git(repo, "diff", "HEAD")
        self.assertIn("ext-diff", fired(markers))

    def test_later_ext_diff_and_textconv_override_the_safety_options(self):
        # P1-3 FIX2 diagnosis: git honors the LAST --[no-]ext-diff /
        # --[no-]textconv, so a later caller option re-enables the program.
        for ext_diff, option in ((True, "--ext-diff"), (False, "--textconv")):
            with self.subTest(option=option):
                root = self.root / option.strip("-")
                root.mkdir()
                repo = make_repo(root)
                markers = install_hostile_config(repo, root, ext_diff=ext_diff)
                (repo / "README.md").write_text("changed\n", encoding="utf-8")
                plain_git(repo, "diff", "--no-ext-diff", "--no-textconv", option, "HEAD")
                self.assertIn("ext-diff" if ext_diff else "textconv", fired(markers))


class HardenedGitTest(_TempRootMixin, unittest.TestCase):
    def test_add_and_commit_run_no_hook(self):
        repo = make_repo(self.root)
        markers = install_hostile_config(repo, self.root)
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        self.assertEqual(hardened_git(repo, "add", "a.txt").returncode, 0)
        result = hardened_git(repo, "-c", "user.name=T", "commit", "--no-verify", "-m", "x")
        self.assertEqual(result.returncode, 0, result.stderr)
        # Even without --no-verify, pre-commit/commit-msg cannot run either.
        (repo / "b.txt").write_text("b\n", encoding="utf-8")
        hardened_git(repo, "add", "b.txt")
        self.assertEqual(hardened_git(repo, "commit", "-m", "y").returncode, 0)
        self.assertEqual(fired(markers), [])
        self.assertEqual(plain_git(repo, "log", "-1", "--pretty=%s").stdout.strip(), "y")

    def test_status_runs_no_fsmonitor(self):
        repo = make_repo(self.root)
        markers = install_hostile_config(repo, self.root)
        (repo / "new.txt").write_text("n\n", encoding="utf-8")
        result = hardened_git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "?? new.txt\n")
        self.assertEqual(fired(markers), [])

    def test_diff_runs_no_textconv_or_external_diff(self):
        for ext_diff in (False, True):
            with self.subTest(ext_diff=ext_diff):
                root = self.root / ("ext" if ext_diff else "textconv")
                root.mkdir()
                repo = make_repo(root)
                markers = install_hostile_config(repo, root, ext_diff=ext_diff)
                (repo / "README.md").write_text("changed\n", encoding="utf-8")
                result = hardened_git(repo, "diff", "HEAD")
                self.assertEqual(result.returncode, 0)
                self.assertIn("+changed", result.stdout)
                self.assertEqual(fired(markers), [])

    def test_overrides_win_over_repository_config_without_rewriting_it(self):
        repo = make_repo(self.root)
        install_hostile_config(repo, self.root)
        before = (repo / ".git" / "config").read_bytes()
        self.assertEqual(hardened_git(repo, "config", "--get", "core.fsmonitor").stdout.strip(), "false")
        self.assertEqual(
            hardened_git(repo, "config", "--get", "core.hooksPath").stdout.strip(),
            runner_git.DISABLED_HOOKS_PATH,
        )
        hardened_git(repo, "status")
        # The user's / repository's own preferences are never modified.
        self.assertEqual((repo / ".git" / "config").read_bytes(), before)
        self.assertIn("fsmonitor.sh", plain_git(repo, "config", "--get", "core.fsmonitor").stdout)

    def test_overrides_win_over_inherited_config_environment(self):
        repo = make_repo(self.root)
        markers = install_hostile_config(repo, self.root)
        plain_git(repo, "config", "--unset", "core.fsmonitor")
        fsmonitor = (self.root / "fsmonitor.sh").as_posix()
        env = dict(os.environ)
        env.update({
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": f'sh "{fsmonitor}"',
        })
        result = subprocess.run(
            runner_git.git_command(repo, ["status", "--porcelain=v1"]), capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fired(markers), [])


class NormalBehaviorParityTest(_TempRootMixin, unittest.TestCase):
    """On an ordinary repository the hardened argv is observably identical
    to plain git: stdout, stderr, exit codes and binary output."""

    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.root)
        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")
        (self.repo / "data.bin").write_bytes(bytes(range(256)) * 4)
        (self.repo / "untracked.txt").write_text("u\n", encoding="utf-8")

    def _both(self, *args, text=True):
        kwargs = {"capture_output": True}
        if text:
            kwargs["text"] = True
        plain = subprocess.run(["git", "-C", str(self.repo), *args], **kwargs)
        hard = subprocess.run(runner_git.git_command(self.repo, args), **kwargs)
        return plain, hard

    def test_text_commands_match(self):
        for args in (
            ("rev-parse", "HEAD"), ("rev-parse", "--abbrev-ref", "HEAD"), ("rev-parse", "--show-toplevel"),
            ("status", "--porcelain=v1", "--branch", "--untracked-files=all"),
            ("diff", "--name-status", "-z", "--no-renames", "HEAD", "--"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        ):
            with self.subTest(args=args):
                plain, hard = self._both(*args)
                self.assertEqual((hard.returncode, hard.stdout, hard.stderr), (plain.returncode, plain.stdout, plain.stderr))

    def test_binary_patch_matches(self):
        plain_git(self.repo, "add", "data.bin")
        plain, hard = self._both("diff", "--binary", "--full-index", "HEAD", "--", ".", text=False)
        self.assertEqual(hard.returncode, 0)
        self.assertEqual(hard.stdout, plain.stdout)
        self.assertIn(b"GIT binary patch", hard.stdout)

    def test_errors_match(self):
        plain, hard = self._both("rev-parse", "--verify", "no-such-ref")
        self.assertNotEqual(hard.returncode, 0)
        self.assertEqual((hard.returncode, hard.stdout, hard.stderr), (plain.returncode, plain.stdout, plain.stderr))

    def test_not_a_repository_matches(self):
        outside = self.root / "not_a_repo"
        outside.mkdir()
        plain = subprocess.run(["git", "-C", str(outside), "rev-parse", "HEAD"], capture_output=True, text=True)
        hard = subprocess.run(runner_git.git_command(outside, ["rev-parse", "HEAD"]), capture_output=True, text=True)
        self.assertEqual((hard.returncode, hard.stdout, hard.stderr), (plain.returncode, plain.stdout, plain.stderr))


def governed(repo: Path, *args: str, **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("text", True)
    return runner_git.run(repo, args, capture_output=True, **kwargs)


def index_state(repo: Path) -> str:
    # `ls-files --stage` lists the index without hashing worktree content.
    return plain_git(repo, "ls-files", "--stage").stdout


class PlainGitFilterAndSigningControlTest(_TempRootMixin, unittest.TestCase):
    """Positive controls for P1-3 FIX1: plain git really runs these
    programs, so the governed "no marker" assertions are not vacuous."""

    def test_diff_without_ext_diff_or_textconv_still_runs_clean(self):
        repo = make_repo(self.root)
        markers = install_filter(repo, self.root)
        (repo / FILTERED_FILE).write_text("modified content\n", encoding="utf-8")
        plain_git(repo, "diff", "--no-ext-diff", "--no-textconv", check=False)
        self.assertIn("filter-evil-clean", fired(markers))

    def test_add_runs_clean(self):
        repo = make_repo(self.root)
        markers = install_filter(repo, self.root)
        (repo / FILTERED_FILE).write_text("modified content\n", encoding="utf-8")
        plain_git(repo, "add", "--", FILTERED_FILE)
        self.assertIn("filter-evil-clean", fired(markers))

    def test_status_runs_process_filter(self):
        repo = make_repo(self.root)
        markers = install_filter(repo, self.root, kind="process")
        modify_same_size(repo / FILTERED_FILE)
        plain_git(repo, "status", "--porcelain=v1", check=False)
        self.assertIn("filter-evil-process", fired(markers))

    def test_status_does_not_hash_untracked_files(self):
        # Why the preflight only adds untracked files for `add`.
        repo = make_repo(self.root)
        markers = install_filter(repo, self.root, tracked_file=False)
        (repo / "new.dat").write_text("n\n", encoding="utf-8")
        self.assertIn("?? new.dat", plain_git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout)
        self.assertEqual(fired(markers), [])

    def test_status_runs_submodule_filter(self):
        repo, sub, markers = _repo_with_filtered_submodule(self.root)
        plain_git(repo, "status", "--porcelain=v1", check=False)
        self.assertIn("filter-evil-clean", fired(markers))

    def test_commit_runs_signing_program_despite_disabled_hooks(self):
        for fmt in ("openpgp", "ssh"):
            with self.subTest(fmt=fmt):
                root = self.root / fmt
                root.mkdir()
                repo = make_repo(root)
                markers = install_signing(repo, root, fmt=fmt)
                (repo / "a.txt").write_text("a\n", encoding="utf-8")
                plain_git(repo, "add", "a.txt")
                result = plain_git(
                    repo, "-c", f"core.hooksPath={runner_git.DISABLED_HOOKS_PATH}",
                    "commit", "--no-verify", "-q", "-m", "x", check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"sign-{fmt}", fired(markers))


def _repo_with_filtered_submodule(root: Path):
    """A superproject whose (embedded, populated) submodule has its OWN
    filter driver and a modified filtered tracked file."""
    repo = make_repo(root)
    sub = make_repo(repo, "sub")
    markers = install_filter(sub, root)  # driver configured in sub/.git/config only
    plain_git(repo, "add", "sub")
    plain_git(repo, "commit", "-q", "-m", "add submodule")
    modify_same_size(sub / FILTERED_FILE)
    return repo, sub, markers


class GovernedFilterRefusalTest(_TempRootMixin, unittest.TestCase):
    """A governed operation that would hash a file whose effective `filter`
    attribute selects a clean/process program is refused BEFORE git runs:
    no program starts, the index is untouched, the refusal is a normal
    git-style failure carrying the offending path and driver."""

    OPERATIONS = (
        ("diff", "HEAD"),
        ("diff", "--name-status", "-z", "--no-renames", "HEAD", "--"),
        ("diff", "--binary", "--full-index", "HEAD", "--", "."),
        ("status", "--porcelain=v1", "--branch", "--untracked-files=all"),
        ("add", "--", FILTERED_FILE),
        ("ls-files", "--others", "--exclude-standard", "-z"),
        ("commit", "-m", "x"),
        ("reset", "--", FILTERED_FILE),
    )

    def _assert_refused(self, result, *, path=FILTERED_FILE, driver="evil"):
        self.assertEqual(result.returncode, runner_git.REFUSED_RETURNCODE)
        self.assertTrue(result.stderr.startswith(runner_git.REFUSED_PREFIX), result.stderr)
        self.assertIn(f"{path} (filter={driver})", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_matrix_kind_required_and_attribute_source(self):
        for kind in ("clean", "process"):
            for required in (False, True):
                for attributes in ("gitattributes", "info"):
                    with self.subTest(kind=kind, required=required, attributes=attributes):
                        root = self.root / f"{kind}-{required}-{attributes}"
                        root.mkdir()
                        repo = make_repo(root)
                        markers = install_filter(repo, root, kind=kind, required=required, attributes=attributes)
                        (repo / FILTERED_FILE).write_text("modified content\n", encoding="utf-8")
                        index_before = index_state(repo)
                        head_before = plain_git(repo, "rev-parse", "HEAD").stdout
                        for op in self.OPERATIONS:
                            self._assert_refused(governed(repo, *op))
                        self.assertEqual(fired(markers), [])
                        self.assertEqual(index_state(repo), index_before)
                        self.assertEqual(plain_git(repo, "rev-parse", "HEAD").stdout, head_before)
                        # rev-parse never hashes content and stays available.
                        self.assertEqual(governed(repo, "rev-parse", "HEAD").stdout, head_before)

    def test_add_of_untracked_filtered_file_refused_while_status_works(self):
        repo = make_repo(self.root)
        markers = install_filter(repo, self.root, tracked_file=False)
        (repo / "new.dat").write_text("n\n", encoding="utf-8")
        (repo / "plain.txt").write_text("p\n", encoding="utf-8")
        status = governed(repo, "status", "--porcelain=v1", "--untracked-files=all")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("?? new.dat", status.stdout)
        self._assert_refused(governed(repo, "add", "--", "new.dat"), path="new.dat")
        self._assert_refused(governed(repo, "add", "--", "."), path="new.dat")
        # An unrelated file in the same repository is still staged normally.
        self.assertEqual(governed(repo, "add", "--", "plain.txt").returncode, 0)
        self.assertIn("plain.txt", index_state(repo))
        self.assertNotIn("new.dat", index_state(repo))
        self.assertEqual(fired(markers), [])

    def test_driver_from_inherited_environment_config_refused(self):
        repo = make_repo(self.root)
        markers = install_filter(repo, self.root, configure=False)
        (repo / FILTERED_FILE).write_text("modified content\n", encoding="utf-8")
        env = dict(os.environ)
        env.update({
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "filter.evil.clean",
            "GIT_CONFIG_VALUE_0": filter_program(self.root),
        })
        # Control: the environment really configures the driver.
        subprocess.run(["git", "-C", str(repo), "add", "--", FILTERED_FILE], env=env, capture_output=True)
        self.assertIn("filter-evil-clean", fired(markers))
        plain_git(repo, "reset", "-q", "--", FILTERED_FILE)
        for marker in markers.iterdir():
            marker.unlink()
        (repo / FILTERED_FILE).write_text("modified again, longer\n", encoding="utf-8")
        self._assert_refused(governed(repo, "diff", "HEAD", env=env))
        self.assertEqual(fired(markers), [])

    def test_submodule_filter_refused(self):
        repo, sub, markers = _repo_with_filtered_submodule(self.root)
        self._assert_refused(governed(repo, "status", "--porcelain=v1"), path=f"sub/{FILTERED_FILE}")
        self._assert_refused(governed(repo, "diff", "HEAD"), path=f"sub/{FILTERED_FILE}")
        self.assertEqual(fired(markers), [])

    def test_refusal_honors_binary_mode(self):
        repo = make_repo(self.root)
        install_filter(repo, self.root)
        (repo / FILTERED_FILE).write_text("modified content\n", encoding="utf-8")
        result = runner_git.run(repo, ["diff", "--binary", "HEAD"], capture_output=True)
        self.assertEqual(result.returncode, runner_git.REFUSED_RETURNCODE)
        self.assertEqual(result.stdout, b"")
        self.assertTrue(result.stderr.startswith(runner_git.REFUSED_PREFIX.encode()))

    def test_not_a_repository_reports_gits_own_error(self):
        outside = self.root / "not_a_repo"
        outside.mkdir()
        result = governed(outside, "status")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a git repository", result.stderr)


class BackstopTest(_TempRootMixin, unittest.TestCase):
    """Even with the preflight bypassed, the argv `run` builds makes git
    fail instead of running - or silently skipping - a neutralized filter."""

    def test_neutralized_driver_fails_instead_of_running(self):
        for kind in ("clean", "process"):
            with self.subTest(kind=kind):
                root = self.root / kind
                root.mkdir()
                repo = make_repo(root)
                markers = install_filter(repo, root, kind=kind)  # optional driver
                modify_same_size(repo / FILTERED_FILE)
                index_before = index_state(repo)
                for args in (["add", "--", FILTERED_FILE], ["status", "--porcelain=v1"]):
                    result = subprocess.run(
                        runner_git.git_command(repo, args, filter_drivers=["evil"]), capture_output=True, text=True,
                    )
                    self.assertNotEqual(result.returncode, 0, args)
                    self.assertIn("filter", result.stderr)
                self.assertEqual(fired(markers), [])
                self.assertEqual(index_state(repo), index_before)

    def test_preflight_returns_every_program_driver(self):
        repo = make_repo(self.root)
        install_filter(repo, self.root, tracked_file=False)
        plain_git(repo, "config", "filter.lfs.smudge", "git-lfs smudge -- %f")
        plain_git(repo, "config", "filter.plain.required", "true")  # no program: nothing to neutralize
        self.assertEqual(runner_git.preflight(repo, ["status"]), ["evil", "lfs"])
        self.assertEqual(runner_git.preflight(repo, ["rev-parse", "HEAD"]), [])


class UnusedFilterDriverTest(_TempRootMixin, unittest.TestCase):
    """A repository is not blocked just because a driver (here an
    LFS-shaped one) is configured: only files that use it matter."""

    def test_lfs_shaped_driver_without_matching_files_does_not_block(self):
        repo = make_repo(self.root)
        markers = self.root / "markers"
        markers.mkdir()
        lfs = self.root / "lfs.sh"
        _write_script(lfs, _marker_append(markers, "lfs") + "cat\n")
        for key in ("clean", "smudge", "process"):
            plain_git(repo, "config", f"filter.lfs.{key}", f'sh "{lfs.as_posix()}"')
        plain_git(repo, "config", "filter.lfs.required", "true")
        (repo / ".gitattributes").write_text("*.psd filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8", newline="\n")
        plain_git(repo, "add", ".gitattributes")
        plain_git(repo, "commit", "-q", "-m", "attributes")
        for marker in markers.iterdir():
            marker.unlink()

        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        (repo / "new.txt").write_text("n\n", encoding="utf-8")
        status = governed(repo, "status", "--porcelain=v1", "--untracked-files=all")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(status.stdout, " M README.md\n?? new.txt\n")
        diff = governed(repo, "diff", "HEAD")
        self.assertEqual(diff.returncode, 0, diff.stderr)
        self.assertIn("+changed", diff.stdout)
        self.assertEqual(governed(repo, "add", "--", "README.md", "new.txt").returncode, 0)
        commit = governed(repo, "-c", "user.name=T", "commit", "-m", "ordinary")
        self.assertEqual(commit.returncode, 0, commit.stderr)
        self.assertEqual(plain_git(repo, "status", "--porcelain=v1").stdout, "")
        self.assertEqual(fired(markers), [])


class GovernedSigningTest(_TempRootMixin, unittest.TestCase):
    def test_commit_is_never_signed(self):
        for fmt in ("openpgp", "ssh"):
            for caller_opts in ([], ["-c", "commit.gpgSign=true"]):
                with self.subTest(fmt=fmt, caller_opts=caller_opts):
                    root = self.root / f"{fmt}-{len(caller_opts)}"
                    root.mkdir()
                    repo = make_repo(root)
                    markers = install_signing(repo, root, fmt=fmt)
                    (repo / "a.txt").write_text("a\n", encoding="utf-8")
                    self.assertEqual(governed(repo, "add", "--", "a.txt").returncode, 0)
                    result = governed(repo, *caller_opts, "commit", "--no-verify", "-m", "unsigned")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(fired(markers), [])
                    self.assertNotIn("gpgsig", plain_git(repo, "cat-file", "commit", "HEAD").stdout)
                    self.assertEqual(plain_git(repo, "log", "-1", "--pretty=%s").stdout.strip(), "unsigned")

    def test_signing_request_refused_before_git_runs(self):
        repo = make_repo(self.root)
        markers = install_signing(repo, self.root)
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        plain_git(repo, "add", "a.txt")
        head = plain_git(repo, "rev-parse", "HEAD").stdout
        with self.assertRaises(ValueError):
            governed(repo, "commit", "-S", "-m", "x")
        self.assertEqual(plain_git(repo, "rev-parse", "HEAD").stdout, head)
        self.assertEqual(fired(markers), [])


class SigningAbbreviationTest(_TempRootMixin, unittest.TestCase):
    """P1-3 FIX3: abbreviations of --gpg-sign. The signer is a simulated
    program that leaves a marker and fails; commit.gpgSign stays false so
    only the command-line option could start it."""

    def _repo(self, name: str):
        root = self.root / name
        root.mkdir()
        repo = make_repo(root)
        markers = install_signing(repo, root)
        plain_git(repo, "config", "commit.gpgSign", "false")
        (repo / "a.txt").write_text("a\n", encoding="utf-8", newline="\n")
        plain_git(repo, "add", "a.txt")
        return repo, markers

    def test_plain_git_signs_with_abbreviation_despite_previous_hardening(self):
        # Positive control: the FIX2 argv shape (`--no-gpg-sign` injected
        # before the caller's options) loses to a later abbreviation.
        for option in ("--g", "--gpg", "--gpg-sig", "--gpg=k"):
            with self.subTest(option=option):
                repo, markers = self._repo(option.strip("-").replace("=", "_"))
                result = plain_git(
                    repo, "-c", "commit.gpgSign=false", "-c", f"core.hooksPath={runner_git.DISABLED_HOOKS_PATH}",
                    "commit", "--no-gpg-sign", "--no-verify", "-q", "-m", "x", option, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("sign-openpgp", fired(markers))

    def test_governed_abbreviations_refused_before_git_runs(self):
        repo, markers = self._repo("refused")
        head = plain_git(repo, "rev-parse", "HEAD").stdout
        for option in SIGNING_ABBREVIATIONS:
            with self.subTest(option=option):
                with self.assertRaises(ValueError):
                    governed(repo, "commit", "--no-verify", "-m", "x", option)
                with self.assertRaises(ValueError):
                    runner_git.run(repo, ["commit", "--no-verify", "-m", "x", option], capture_output=True)
        self.assertEqual(plain_git(repo, "rev-parse", "HEAD").stdout, head)
        self.assertEqual(fired(markers), [])

    def test_governed_values_pathspecs_and_negations_commit_unsigned(self):
        cases = (
            (("-m", "--gpg"), "--gpg"),
            (("--message", "--g"), "--g"),
            (("--no-gpg", "-m", "negated"), "negated"),
            (("--no-g", "-m", "negated short"), "negated short"),
        )
        for args, subject in cases:
            with self.subTest(args=args):
                repo, markers = self._repo("ok-" + str(cases.index((args, subject))))
                result = runner_git.run(repo, ["commit", "--no-verify", *args], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(fired(markers), [])
                self.assertNotIn("gpgsig", plain_git(repo, "cat-file", "commit", "HEAD").stdout)
                self.assertEqual(plain_git(repo, "log", "-1", "--pretty=%s").stdout.strip(), subject)
        # An option-shaped pathspec after `--` is committed, not refused.
        repo, markers = self._repo("pathspec")
        (repo / "--gpg").write_text("p\n", encoding="utf-8", newline="\n")
        plain_git(repo, "add", "--", "--gpg")
        result = runner_git.run(repo, ["commit", "--no-verify", "-m", "path", "--", "--gpg"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fired(markers), [])
        self.assertEqual(plain_git(repo, "show", "--name-only", "--pretty=", "HEAD").stdout.split(), ["--gpg"])
        self.assertNotIn("gpgsig", plain_git(repo, "cat-file", "commit", "HEAD").stdout)


class GovernedDiffProgramsTest(_TempRootMixin, unittest.TestCase):
    """P1-3 FIX2: a governed diff never runs an external diff or textconv
    program, whatever the caller appends; ordinary diffs keep working."""

    def _hostile(self, ext_diff: bool):
        root = self.root / ("ext" if ext_diff else "textconv")
        root.mkdir()
        repo = make_repo(root)
        markers = install_hostile_config(repo, root, ext_diff=ext_diff)
        (repo / "README.md").write_text("changed\n", encoding="utf-8", newline="\n")
        return repo, markers

    def _stage(self, repo: Path, markers: Path, *paths: str) -> None:
        # Fixture staging via plain git fires the hostile fsmonitor/hooks;
        # forget those markers so tests observe only governed operations.
        plain_git(repo, "add", "--", *paths)
        for marker in markers.iterdir():
            marker.unlink()

    def test_reenabling_options_refused_before_git_runs(self):
        for ext_diff in (True, False):
            repo, markers = self._hostile(ext_diff)
            for args in (
                ("--ext-diff", "HEAD"), ("--textconv", "HEAD"), ("HEAD", "--ext-diff"),
                ("--binary", "HEAD", "--textconv", "--", "."), ("--ext", "HEAD"), ("--textc", "HEAD"),
            ):
                with self.subTest(ext_diff=ext_diff, args=args):
                    with self.assertRaises(ValueError):
                        governed(repo, "diff", *args)
                    with self.assertRaises(ValueError):
                        runner_git.run(repo, ["diff", *args], capture_output=True)
            self.assertEqual(fired(markers), [])

    def test_ordinary_diff_runs_no_program(self):
        for ext_diff in (True, False):
            with self.subTest(ext_diff=ext_diff):
                repo, markers = self._hostile(ext_diff)
                result = governed(repo, "diff", "HEAD")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("+changed", result.stdout)
                names = governed(repo, "diff", "--name-status", "-z", "--no-renames", "HEAD", "--")
                self.assertEqual(names.stdout, "M\0README.md\0")
                self.assertEqual(fired(markers), [])

    def test_option_shaped_pathspecs_are_diffed_not_refused(self):
        # `* diff=evil` covers these files too, so a textconv would fire.
        repo, markers = self._hostile(ext_diff=False)
        for name in ("--textconv", "--ext-diff"):
            (repo / name).write_text("seed\n", encoding="utf-8", newline="\n")
        plain_git(repo, "add", "--", "--textconv", "--ext-diff")
        plain_git(repo, "commit", "-q", "--no-verify", "-m", "option-shaped names")
        for marker in markers.iterdir():
            marker.unlink()
        (repo / "--textconv").write_text("edited\n", encoding="utf-8", newline="\n")
        result = governed(repo, "diff", "HEAD", "--", "--textconv", "--ext-diff")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("+++ b/--textconv", result.stdout)
        self.assertIn("+edited", result.stdout)
        self.assertEqual(fired(markers), [])

    def test_cached_check_works(self):
        repo, markers = self._hostile(ext_diff=True)
        self._stage(repo, markers, "README.md")
        clean = governed(repo, "diff", "--cached", "--check", "--", "README.md")
        self.assertEqual((clean.returncode, clean.stdout, clean.stderr), (0, "", ""))
        (repo / "README.md").write_text("trailing   \n", encoding="utf-8", newline="\n")
        self._stage(repo, markers, "README.md")
        dirty = governed(repo, "diff", "--cached", "--check", "--", "README.md")
        plain = plain_git(
            repo, "-c", "core.fsmonitor=false", "diff", "--no-ext-diff", "--cached", "--check", "--", "README.md",
            check=False,
        )
        self.assertNotEqual(dirty.returncode, 0)
        self.assertIn("trailing whitespace", dirty.stdout)
        self.assertEqual((dirty.returncode, dirty.stdout), (plain.returncode, plain.stdout))
        self.assertEqual(fired(markers), [])

    def test_binary_output_preserved(self):
        for ext_diff in (True, False):
            with self.subTest(ext_diff=ext_diff):
                repo, markers = self._hostile(ext_diff)
                (repo / "data.bin").write_bytes(bytes(range(256)) * 4)
                self._stage(repo, markers, "data.bin")
                args = ["diff", "--binary", "--full-index", "HEAD", "--", "."]
                result = runner_git.run(repo, args, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                # Reference: plain git with the programs disabled by hand.
                reference = subprocess.run(
                    ["git", "-C", str(repo), "-c", "core.fsmonitor=false", "diff", "--no-ext-diff", "--no-textconv", *args[1:]],
                    capture_output=True,
                )
                self.assertEqual(result.stdout, reference.stdout)
                self.assertIn(b"GIT binary patch", result.stdout)
                self.assertIn(b"+changed", result.stdout)
                self.assertEqual(fired(markers), [])


class GovernedSubmoduleDiffTest(_TempRootMixin, unittest.TestCase):
    """P1-3 FIX4: with diff.submodule=diff in the superproject, git diff
    spawns a child `git diff` inside each changed submodule which honors the
    SUBMODULE's own diff.external / textconv, ignoring the parent's
    --no-ext-diff/--no-textconv. A governed diff never does; the gitlink
    change itself is still reported."""

    BINARY_ARGS = ("diff", "--binary", "--full-index", "HEAD", "--", ".")

    def _hostile(self, ext_diff: bool):
        root = self.root / ("ext" if ext_diff else "textconv")
        root.mkdir()
        markers = root / "markers"
        markers.mkdir()
        repo = make_repo(root)
        sub = make_repo(repo, "sub")
        plain_git(repo, "add", "sub")
        plain_git(repo, "commit", "-q", "-m", "add submodule")
        recorded = plain_git(sub, "rev-parse", "HEAD").stdout.strip()
        plain_git(repo, "config", "diff.submodule", "diff")
        if ext_diff:
            program = root / "sub-extdiff.sh"
            _write_script(program, _marker_append(markers, "sub-ext-diff") + "exit 0\n")
            plain_git(sub, "config", "diff.external", f'sh "{program.as_posix()}"')
        else:
            program = root / "sub-textconv.sh"
            _write_script(program, _marker_append(markers, "sub-textconv") + 'cat "$1"\n')
            plain_git(sub, "config", "diff.evil.textconv", f'sh "{program.as_posix()}"')
            (sub / ".git" / "info").mkdir(exist_ok=True)
            (sub / ".git" / "info" / "attributes").write_text("* diff=evil\n", encoding="utf-8", newline="\n")
        # The submodule moves away from the recorded gitlink.
        (sub / "README.md").write_text("sub changed\n", encoding="utf-8", newline="\n")
        plain_git(sub, "commit", "-q", "-am", "move submodule")
        current = plain_git(sub, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(fired(markers), [])
        return repo, markers, recorded, current

    def test_plain_git_runs_submodule_programs_despite_no_ext_diff_and_no_textconv(self):
        # Positive control: the previous hardening alone does not stop it.
        for ext_diff in (True, False):
            with self.subTest(ext_diff=ext_diff):
                repo, markers, _, _ = self._hostile(ext_diff)
                plain_git(repo, "-c", "core.fsmonitor=false", "diff", "--no-ext-diff", "--no-textconv", "HEAD")
                self.assertEqual(fired(markers), ["sub-ext-diff" if ext_diff else "sub-textconv"])

    def test_governed_binary_diff_runs_no_submodule_program_and_reports_gitlink(self):
        for ext_diff in (True, False):
            with self.subTest(ext_diff=ext_diff):
                repo, markers, recorded, current = self._hostile(ext_diff)
                result = runner_git.run(repo, list(self.BINARY_ARGS), capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(fired(markers), [])
                self.assertIn(b"diff --git a/sub b/sub", result.stdout)
                self.assertIn(f"-Subproject commit {recorded}".encode(), result.stdout)
                self.assertIn(f"+Subproject commit {current}".encode(), result.stdout)
                self.assertNotIn(b"sub changed", result.stdout)
                # Same bytes as git's default (short) submodule format.
                reference = subprocess.run(
                    ["git", "-C", str(repo), "-c", "core.fsmonitor=false", "-c", "diff.submodule=short",
                     "diff", "--no-ext-diff", "--no-textconv", *self.BINARY_ARGS[1:]],
                    capture_output=True,
                )
                self.assertEqual(result.stdout, reference.stdout)
                names = governed(repo, "diff", "--name-status", "-z", "--no-renames", "HEAD", "--")
                self.assertEqual(names.stdout, "M\0sub\0")
                self.assertEqual(fired(markers), [])

    def test_caller_config_and_safe_submodule_formats_run_no_program(self):
        repo, markers, _, current = self._hostile(ext_diff=True)
        result = governed(repo, "-c", "diff.submodule=diff", "diff", "HEAD")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"+Subproject commit {current}", result.stdout)
        for option in ("--submodule", "--submodule=log", "--submodule=short"):
            with self.subTest(option=option):
                result = governed(repo, "diff", option, "HEAD")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(current[:7], result.stdout)
        self.assertEqual(fired(markers), [])

    def test_inline_submodule_options_refused_before_git_runs(self):
        for ext_diff in (True, False):
            repo, markers, _, _ = self._hostile(ext_diff)
            for option in ("--submodule=diff", "--submodul=diff", "--sub=diff", "--s=diff", "--no-submodule", "--no-sub"):
                with self.subTest(ext_diff=ext_diff, option=option):
                    with self.assertRaises(ValueError):
                        runner_git.run(repo, [*self.BINARY_ARGS[:4], option, "--", "."], capture_output=True)
            self.assertEqual(fired(markers), [])


if __name__ == "__main__":
    unittest.main()
