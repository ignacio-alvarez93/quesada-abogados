"""Hardened git argv construction shared by Runner, Queue, Pipeline and providers.

Every git call these modules make is governed: it must never start a process
the governance layer did not choose. Plain `git -C <repo> ...` inherits the
user's, the system's and - critically - the TARGET REPOSITORY's own config,
so a repository under inspection could make a read-only `git status` run an
arbitrary `core.fsmonitor` program, or make the checkpoint commit run
`prepare-commit-msg` / `commit-msg` / `post-commit` hooks (`commit
--no-verify` only skips pre-commit and commit-msg).

`git_command` closes that by injecting command-line `-c` overrides, which
take precedence over every config file and over inherited
GIT_CONFIG_COUNT/GIT_CONFIG_PARAMETERS entries, right before the subcommand
(after any caller-supplied global options, so a caller cannot override them
either):

* core.fsmonitor=false, core.useBuiltinFSMonitor=false - no fsmonitor hook
  program and no fsmonitor daemon (the latter key is honored by older Git
  for Windows builds and ignored elsewhere);
* core.hooksPath=<path that can never be a directory> - no hook of any kind
  can be found, whatever the repository's .git/hooks or config contain;
* commit.gpgSign=false, plus `--no-gpg-sign` for `commit` - a governed
  commit never runs gpg.program / gpg.ssh.program / gpg.x509.program (or
  gpg.ssh.defaultKeyCommand); a caller passing -S/--gpg-sign, or any
  abbreviation of --gpg-sign (--g, --gpg, --gpg-sig=<key>, ...: Git honors
  the last one, so it would override --no-gpg-sign), is refused;
* for `diff`: --no-ext-diff --no-textconv - neither diff.external,
  GIT_EXTERNAL_DIFF, diff.<driver>.command nor diff.<driver>.textconv run.
  Git honors the LAST of --[no-]ext-diff / --[no-]textconv, so a caller
  option that would turn either back on (--ext-diff, --textconv, or any
  abbreviation of them) is refused; pathspecs after `--` are not options.

Content filters (P1-3 FIX1) cannot be handled the same way: dropping a
`filter.<driver>.clean` / `.process` program would silently change what
git hashes, stages and diffs. `run` therefore preflights every subcommand
that may read worktree content: it enumerates the effective filter
drivers (`git config --get-regexp`, so every config scope, include and
inherited GIT_CONFIG_* entry), asks `git check-attr` for the effective
`filter` attribute of every file the operation may hash (all tracked files,
plus the named untracked ones for `add`; recursively into populated
submodules), and REFUSES the operation - without starting it - if any of
them maps to a driver with a clean/process program. A configured driver no
involved file uses (e.g. a global Git LFS install) does not block anything.
As a backstop, every such driver is additionally overridden to an empty
clean/process/smudge with `required=true`, so even a file the preflight
did not foresee makes git fail ("clean filter failed") instead of running
the program or silently skipping it.

Nothing is written to any git config: user and repository preferences are
untouched; the overrides live only in the child process argv. Output,
exit codes and errors are otherwise exactly git's own - callers keep their
own `subprocess.run` keyword arguments (text/binary, encoding, error
handling). A refusal is reported the way a git failure is: a
CompletedProcess with returncode REFUSED_RETURNCODE and a stderr starting
with REFUSED_PREFIX.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# A path anchored UNDER this module's own regular file: no filesystem lets a
# directory exist beneath a regular file, so git's hook lookup there always
# fails with ENOENT/ENOTDIR (silently - git only prints its "hook was
# ignored" hint for an existing non-executable hook), on POSIX and on
# Windows alike. Absolute, so it never resolves relative to the target
# repository; and nothing needs to be created or cleaned up.
DISABLED_HOOKS_PATH = os.path.join(os.path.abspath(__file__), "hooks-disabled")

HARDENING_CONFIG = (
    "core.fsmonitor=false",
    "core.useBuiltinFSMonitor=false",
    f"core.hooksPath={DISABLED_HOOKS_PATH}",
    "commit.gpgSign=false",
)

DIFF_HARDENING_OPTIONS = ("--no-ext-diff", "--no-textconv")
COMMIT_HARDENING_OPTIONS = ("--no-gpg-sign",)

# `git diff` long options that would re-enable what DIFF_HARDENING_OPTIONS
# disables. Whether diff accepts abbreviated long options depends on the
# Git version, so every prefix is refused as well - except these exact,
# unrelated options that happen to be prefixes (`--text` is `-a`).
_DIFF_REENABLING_OPTIONS = ("ext-diff", "textconv")
_DIFF_UNRELATED_PREFIX_OPTIONS = frozenset({"text"})

# Same code git uses for fatal errors: every caller already treats any
# non-zero exit as failure.
REFUSED_RETURNCODE = 128
REFUSED_PREFIX = "fatal: governed git refused: "

# Subcommands that never hash worktree content, so no content filter can run.
# Everything else is preflighted.
FILTER_FREE_SUBCOMMANDS = frozenset({"rev-parse", "config", "check-attr"})

# `git check-attr` prints these for a valueless attribute, so a driver
# literally named like one cannot be told apart from "no driver".
_AMBIGUOUS_DRIVER_NAMES = frozenset({"set", "unset", "unspecified"})
_FILTER_PROGRAM_KEYS = ("clean", "process", "smudge")
_MAX_REPORTED_PATHS = 10

# Global git options (before the subcommand) that consume the next argv token.
_GLOBAL_OPTIONS_WITH_VALUE = frozenset({"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--config-env"})

# `git commit` options whose value is the next token (so that token is not
# itself scanned for -S).
_COMMIT_OPTIONS_WITH_VALUE = frozenset({
    "-m", "-F", "-c", "-C", "-t", "--message", "--file", "--reuse-message", "--reedit-message",
    "--template", "--author", "--date", "--cleanup", "--fixup", "--squash", "--trailer",
    "--pathspec-from-file",
})

# `git commit` accepts any unambiguous prefix of a long option, and no other
# commit option starts with "g", so every prefix of this one turns signing
# on. Negated spellings (--no-gpg-sign and its prefixes) only turn it off.
_COMMIT_SIGNING_OPTION = "gpg-sign"


class GitRefused(Exception):
    pass


def _subcommand_index(args: list) -> int:
    i = 0
    while i < len(args):
        token = args[i]
        if token in _GLOBAL_OPTIONS_WITH_VALUE:
            i += 2
        elif token.startswith("-"):
            i += 1
        else:
            return i
    return len(args)


def _requests_signing(commit_args: list) -> bool:
    skip_value = False
    for token in commit_args:
        if skip_value:
            skip_value = False
            continue
        if token == "--":
            return False
        if token in _COMMIT_OPTIONS_WITH_VALUE:
            skip_value = True
        elif token.startswith("--"):
            name = token[2:].split("=", 1)[0]
            if name and _COMMIT_SIGNING_OPTION.startswith(name):
                return True
        elif token.startswith("-") and "S" in token:
            # Conservative: also matches a bundled value such as -mSome.
            return True
    return False


def _reenabling_diff_option(diff_args: list):
    """The first caller option that would turn external diff or textconv
    back on, or None. Conservative: a value token (e.g. `-S --ext-diff`) is
    refused too; anything after `--` is a pathspec and is never matched."""
    for token in diff_args:
        if token == "--":
            return None
        if not token.startswith("--"):
            continue
        name = token[2:].split("=", 1)[0]
        if not name or name in _DIFF_UNRELATED_PREFIX_OPTIONS:
            continue
        if any(option.startswith(name) for option in _DIFF_REENABLING_OPTIONS):
            return token
    return None


def _safe_driver_name(name: str) -> bool:
    # A `-c` key is split at its first "=", so such a driver cannot be
    # overridden from the command line.
    return bool(name) and not any(ch in name for ch in "=\n\0")


def git_command(repo, args, *, filter_drivers=()) -> list:
    """Returns the argv for `git -C <repo> <args>` with the hardening
    overrides applied. `args` is everything the caller would have placed
    after `-C <repo>`, optionally starting with its own global options.
    `filter_drivers` are content-filter drivers to neutralize (see `run`).
    Raises ValueError for a commit that asks to be signed and for a diff
    that asks for an external diff or textconv."""
    args = [str(a) for a in args]
    idx = _subcommand_index(args)
    hardening = []
    for entry in HARDENING_CONFIG:
        hardening += ["-c", entry]
    for driver in filter_drivers:
        if not _safe_driver_name(driver):
            raise ValueError(f"filter driver name cannot be overridden: {driver!r}")
        for key in _FILTER_PROGRAM_KEYS:
            hardening += ["-c", f"filter.{driver}.{key}="]
        hardening += ["-c", f"filter.{driver}.required=true"]
    rest = args[idx:]
    if rest and rest[0] == "diff":
        reenabling = _reenabling_diff_option(rest[1:])
        if reenabling is not None:
            raise ValueError(
                f"governed git diff never runs external diff or textconv programs: {reenabling} is refused"
            )
        rest = [rest[0], *DIFF_HARDENING_OPTIONS, *rest[1:]]
    elif rest and rest[0] == "commit":
        if _requests_signing(rest[1:]):
            raise ValueError("governed git commits are never signed: -S/--gpg-sign is refused")
        rest = [rest[0], *COMMIT_HARDENING_OPTIONS, *rest[1:]]
    return ["git", "-C", str(repo), *args[:idx], *hardening, *rest]


def _query(repo, global_opts: list, args: list, env, stdin: bytes = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        git_command(repo, [*global_opts, *args]), input=stdin, capture_output=True, env=env,
    )


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


def _failed(result: subprocess.CompletedProcess, what: str):
    detail = _decode(result.stderr).strip()
    raise GitRefused(f"{what} failed (exit {result.returncode})" + (f": {detail}" if detail else ""))


def _program_drivers(repo, global_opts: list, env) -> dict:
    """Effective filter drivers that configure a clean/process/smudge
    program: {driver: [keys]}. Last value wins, as in git; empty = unset."""
    result = _query(repo, global_opts, ["config", "-z", "--get-regexp", r"^filter\."], env)
    if result.returncode == 1 and not result.stdout:
        return {}
    if result.returncode != 0:
        _failed(result, "enumerating filter drivers")
    values = {}
    for entry in _decode(result.stdout).split("\0"):
        if not entry:
            continue
        key, _, value = entry.partition("\n")
        # A valueless key (`clean` with no "=") is "true": treat as set.
        value = value if "\n" in entry else "true"
        name, _, var = key[len("filter."):].rpartition(".")
        if name and var in _FILTER_PROGRAM_KEYS:
            values[(name, var)] = value
    drivers = {}
    for (name, var), value in values.items():
        if value:
            drivers.setdefault(name, []).append(var)
    return drivers


def _filtered_paths(top, global_opts: list, env, extra_untracked, label: str, drivers: dict) -> list:
    """Collects (driver, path) pairs, for `top` and its populated
    submodules, where an involved file's effective `filter` attribute
    selects a clean/process program. Updates `drivers` with every driver
    found (submodules have their own config)."""
    found = _program_drivers(top, global_opts, env)
    for name in found:
        if not _safe_driver_name(name):
            raise GitRefused(f"{label}filter driver {name!r} cannot be neutralized")
        drivers.setdefault(name, found[name])
    executable = {name for name, keys in found.items() if "clean" in keys or "process" in keys}
    ambiguous = executable & _AMBIGUOUS_DRIVER_NAMES
    if ambiguous:
        raise GitRefused(f"{label}filter driver {sorted(ambiguous)[0]!r} is indistinguishable from an unset attribute")

    staged = _query(top, global_opts, ["ls-files", "-z", "--stage", "--full-name", "--", ":/"], env)
    if staged.returncode != 0:
        _failed(staged, "listing tracked files")
    paths, gitlinks = [], []
    for entry in _decode(staged.stdout).split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        if meta.split(" ", 1)[0] == "160000":
            gitlinks.append(path)
        elif not paths or paths[-1] != path:  # conflict stages repeat a path
            paths.append(path)
    tracked = set(paths)
    paths += [p for p in extra_untracked if p not in tracked]

    hits = []
    if executable and paths:
        attrs = _query(
            top, global_opts, ["check-attr", "-z", "--stdin", "filter"], env,
            stdin=b"".join(p.encode("utf-8", "surrogateescape") + b"\0" for p in paths),
        )
        if attrs.returncode != 0:
            _failed(attrs, "reading filter attributes")
        fields = _decode(attrs.stdout).split("\0")
        for i in range(0, len(fields) - 2, 3):
            path, value = fields[i], fields[i + 2]
            if value in executable:
                hits.append((value, label + path))

    for sub in gitlinks:
        sub_dir = Path(top) / sub
        if (sub_dir / ".git").exists():
            hits += _filtered_paths(sub_dir, global_opts, env, [], f"{label}{sub}/", drivers)
    return hits


def _pathspecs_after_separator(sub_args: list):
    return sub_args[sub_args.index("--") + 1:] if "--" in sub_args else None


def preflight(repo, args, *, env=None) -> list:
    """Raises GitRefused if the governed operation could run a content
    filter program; otherwise returns the filter drivers to neutralize."""
    args = [str(a) for a in args]
    idx = _subcommand_index(args)
    global_opts, rest = args[:idx], args[idx:]
    if not rest or rest[0] in FILTER_FREE_SUBCOMMANDS:
        return []
    top_result = _query(repo, global_opts, ["rev-parse", "--show-toplevel"], env)
    if top_result.returncode != 0:
        _failed(top_result, "locating the worktree")
    top = _decode(top_result.stdout).strip()

    untracked = []
    if rest[0] == "add":
        # `add` hashes the untracked files it is given, ignored ones included
        # (conservatively, even though plain `add` would refuse them).
        pathspecs = _pathspecs_after_separator(rest[1:])
        listed = _query(
            repo, global_opts, ["ls-files", "-z", "--others", "--full-name", "--", *(pathspecs or [":/"])], env,
        )
        if listed.returncode != 0:
            _failed(listed, "listing untracked files")
        untracked = [p for p in _decode(listed.stdout).split("\0") if p]

    drivers = {}
    hits = _filtered_paths(top, global_opts, env, untracked, "", drivers)
    if hits:
        shown = ", ".join(f"{path} (filter={driver})" for driver, path in hits[:_MAX_REPORTED_PATHS])
        more = f" and {len(hits) - _MAX_REPORTED_PATHS} more" if len(hits) > _MAX_REPORTED_PATHS else ""
        raise GitRefused(
            f"`git {rest[0]}` would run an external content filter program for: {shown}{more}"
        )
    return sorted(drivers)


def _refusal(cmd: list, reason: str, kwargs: dict) -> subprocess.CompletedProcess:
    message = f"{REFUSED_PREFIX}{reason}\n"
    textual = kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding") or kwargs.get("errors")
    if textual:
        return subprocess.CompletedProcess(cmd, REFUSED_RETURNCODE, "", message)
    return subprocess.CompletedProcess(cmd, REFUSED_RETURNCODE, b"", message.encode("utf-8", "replace"))


def run(repo, args, **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run(git_command(repo, args), **kwargs)` for governed
    calls, after the content-filter preflight. A refused operation is never
    started; it returns a REFUSED_RETURNCODE result instead."""
    args = [str(a) for a in args]
    cmd = git_command(repo, args)  # validates (e.g. signing) before any git runs
    try:
        drivers = preflight(repo, args, env=kwargs.get("env"))
    except GitRefused as exc:
        return _refusal(cmd, str(exc), kwargs)
    return subprocess.run(git_command(repo, args, filter_drivers=drivers), **kwargs)
