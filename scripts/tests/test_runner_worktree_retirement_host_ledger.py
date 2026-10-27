"""FCP-4E-02c: isolated, durable, non-authorizing retirement host ledger (NOT LIVE).

Every ledger is a disposable SQLite file inside a fresh, private temporary
"host" directory created by these tests (never a registered worktree, never
inside a repository). Proposals are the synthetic FCP-4E-02a fixtures and
signing keys are ephemeral Ed25519 keys generated in memory, exactly as in
the FCP-4E-02b tests: they stand in for the Director's own tool. The only
subprocess is the disposable crash fixture (a raw SQLite writer that dies
mid-transaction). No network is reachable. Nothing here is skipped: without
`cryptography` the evidence tests FAIL (CI installs the pinned dependency
and enforces zero skips).
"""

import ast
import dataclasses
import hashlib
import os
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from unittest import mock

from scripts.ai import runner_worktree_retirement_authorization as wra
from scripts.ai import runner_worktree_retirement_host_authority as rha
from scripts.ai import runner_worktree_retirement_host_ledger as rlg
from scripts.tests import test_runner_worktree_retirement_authorization as twra
from scripts.tests import test_runner_worktree_retirement_host_authority as t

if rha.CRYPTO_AVAILABLE:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MODULE_PATH = Path(rlg.__file__)
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "fabric-ci.yml"
# sha256 (LF-normalized) of the merged FCP-4E-02a/02b files (fd990af); 02c must not change them.
PINNED_SOURCES = {
    "scripts/ai/runner_worktree_retirement_authorization.py":
        "c51068e0eff2aa4a20a2edf712d86a716cc784e6a9e52b1c877e5a9d8cc205c0",
    "scripts/ai/runner_worktree_retirement_host_authority.py":
        "3c13c160fed6dd5510c0586a40e4cc31248acce0aadd9ada47d69f7ea1c94ccd",
    "scripts/tests/test_runner_worktree_retirement_authorization.py":
        "c4431cc2ab26c0323e01c982a12baf462ffc52361c7095c0c645d113870cbfae",
    "scripts/tests/test_runner_worktree_retirement_host_authority.py":
        "68b5bdf20f0241840808bd8d18968d86c956698727188a62b5c46e9c6d03b9b0",
}

NOW = t.NOW
HOST = t.HOST
LEDGER_NAME = "host-01" + rlg.LEDGER_FILENAME_SUFFIX
_NETWORK = []
_FIXED_RESULT_FLAGS = (("authorizes_action", False), ("deletion_authorized", False),
                       ("branch_deletion_authorized", False), ("issued", False), ("consumed", False),
                       ("host_identity_authenticated", False), ("queue_scope_attested", False),
                       ("file_acl_verified", False), ("clock_attested", False), ("human_review_required", True))
_FIXED_RECORD_FLAGS = _FIXED_RESULT_FLAGS[:7]


def _deny_network(*_args, **_kwargs):
    _NETWORK.append("attempt")
    raise OSError("network denied during retirement host ledger tests")


def setUpModule():
    for target, name in ((socket.socket, "connect"), (socket, "create_connection"), (socket, "getaddrinfo")):
        patcher = mock.patch.object(target, name, _deny_network)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


def nonce(i) -> str:
    return hashlib.sha256(f"fcp4e02c-nonce-{i}".encode()).hexdigest()


def at(seconds=0, microseconds=0) -> datetime:
    return NOW + timedelta(seconds=seconds, microseconds=microseconds)


def raw(path, mode="rw"):
    """A raw SQLite connection used only by tests to attack the file."""
    return sqlite3.connect(rlg._sqlite_uri(str(path), mode), uri=True, isolation_level=None, timeout=0)


class _FakeLondon(tzinfo):
    """Zero offset in winter, but not UTC: a DST zone must be refused."""

    def utcoffset(self, dt):
        return timedelta(0)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "Europe/London"


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(rha.CRYPTO_AVAILABLE, "cryptography is required: these tests never skip")
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix="fcp4e02c-")))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.host_dir = self.base / "isolated-host"
        self.host_dir.mkdir(mode=0o700)
        self.untrusted = self.base / "untrusted-worktrees"
        self.untrusted.mkdir(mode=0o700)
        self.roots = (str(self.untrusted),)
        self.path = self.host_dir / LEDGER_NAME
        self.now = NOW
        self.clock = lambda: self.now
        self.key = Ed25519PrivateKey.generate()
        self.proposal, self.report, self.inventory_record = t.make_proposal()
        self.config = t.make_config(t.raw_public(self.key))

    # Helpers ---------------------------------------------------------------
    def provision(self, path=None, **kwargs):
        kwargs.setdefault("host_id", HOST)
        kwargs.setdefault("forbidden_roots", self.roots)
        kwargs.setdefault("clock", self.clock)
        return rlg.provision(str(path or self.path), **kwargs)

    def open(self, path=None, **kwargs):
        kwargs.setdefault("host_id", HOST)
        kwargs.setdefault("forbidden_roots", self.roots)
        return rlg.open_existing(str(path or self.path), **kwargs)

    def ledger(self):
        self.assertEqual(self.provision().status, rlg.STATUS_PROVISIONED_EMPTY)
        return self.open()

    def env(self, private=None, **changes) -> bytes:
        return t.envelope(t.command_for(self.proposal, **changes), private or self.key)

    def record(self, ledger, envelope=None, **kwargs):
        kwargs.setdefault("config", self.config)
        kwargs.setdefault("proposal", self.proposal)
        kwargs.setdefault("clock", self.clock)
        return ledger.record_reverified_command_evidence(self.env() if envelope is None else envelope, **kwargs)

    def snapshot(self, directory=None):
        directory = Path(directory or self.host_dir)
        files = {}
        for entry in sorted(os.listdir(directory)):
            full = directory / entry
            if full.is_file():
                st = os.stat(full)
                files[entry] = (hashlib.sha256(full.read_bytes()).hexdigest(), st.st_mtime_ns, st.st_size)
            else:
                files[entry] = None
        return files

    def assertRefused(self, result, *codes):
        self.assertIs(type(result), rlg.RetirementLedgerResult)
        self.assertEqual(result.status, rlg.STATUS_REFUSED)
        self.assertEqual(result.reason_codes[:len(codes)], codes)
        self.assertIsNone(result.audit_seq)
        self.assertFixedFlags(result)
        return result

    def assertOpenRefused(self, code, path=None, **kwargs):
        with self.assertRaises(rlg.RetirementLedgerRefused) as ctx:
            self.open(path, **kwargs)
        self.assertEqual(ctx.exception.code, code)
        self.assertEqual(str(ctx.exception), code)

    def assertQueryRefused(self, code, call):
        with self.assertRaises(rlg.RetirementLedgerRefused) as ctx:
            call()
        self.assertEqual(ctx.exception.code, code)

    def assertFixedFlags(self, obj, flags=_FIXED_RESULT_FLAGS):
        for name, value in flags:
            self.assertIs(getattr(obj, name), value, name)

    def rows(self, sql, path=None):
        con = raw(path or self.path, "ro")
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def tamper(self, *statements, path=None):
        """Direct writes by an attacker who can write the file."""
        con = raw(path or self.path)
        try:
            for statement in statements:
                con.execute(statement)
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

class ProvisionTests(LedgerCase):
    def test_provision_creates_exactly_one_valid_empty_ledger(self):
        result = self.provision()
        self.assertEqual((result.schema, result.operation, result.status, result.reason_codes),
                         (rlg.RESULT_SCHEMA, rlg.OP_PROVISION, rlg.STATUS_PROVISIONED_EMPTY, ()))
        self.assertEqual(result.audit_seq, 1)
        self.assertEqual(result.clock_high_water_mark, "2026-10-26T12:00:00.000000Z")
        self.assertIsNone(result.command_id)
        self.assertIs(result.signature_reverified, False)
        self.assertFixedFlags(result)
        self.assertEqual(result.limitations, rlg.LEDGER_LIMITATIONS)
        self.assertEqual(sorted(os.listdir(self.host_dir)), [LEDGER_NAME])
        ledger = self.open()
        self.assertEqual(ledger.host_id_label, HOST)
        self.assertEqual(ledger.clock_high_water_mark(), "2026-10-26T12:00:00.000000Z")
        self.assertEqual(ledger.audit_trail(), (rlg.RetirementAuditEvent(
            1, "2026-10-26T12:00:00.000000Z", rlg.EVENT_LEDGER_PROVISIONED, rlg.LEDGER_SCHEMA_VERSION, None, None),))
        self.assertEqual(dict(self.rows("SELECT key, value FROM meta")), {
            "schema_version": "fcp4e02c-retirement-ledger-v1", "domain": rha.COMMAND_FORMAT, "host_id": HOST,
            "provisioned_at": "2026-10-26T12:00:00.000000Z"})
        self.assertEqual(self.rows("SELECT COUNT(*) FROM command_evidence"), [(0,)])
        header = self.path.read_bytes()[:100]
        self.assertEqual((header[18], header[19]), (1, 1))   # rollback journal, never WAL
        if os.name == "posix":
            self.assertFalse(os.stat(self.path).st_mode & 0o077)

    def test_schema_is_domain_specific_and_separate_from_the_pr_ledger(self):
        self.assertEqual(rlg.LEDGER_SCHEMA_VERSION, "fcp4e02c-retirement-ledger-v1")
        self.assertEqual(rlg.LEDGER_DOMAIN, "fcp4e02b-retirement-command-v1")
        self.assertTrue(rlg.LEDGER_FILENAME_SUFFIX.endswith(".sqlite3"))
        self.assertIn("retirement-ledger", rlg.LEDGER_FILENAME_SUFFIX)
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("fcp3b2b2-host-ledger", source)

    def test_existing_file_or_ledger_is_never_overwritten(self):
        self.path.write_bytes(b"precious host bytes")
        before = self.snapshot()
        self.assertRefused(self.provision(), rlg.RLG_PATH_EXISTS)
        self.assertEqual(self.snapshot(), before)
        self.path.unlink()
        self.provision()
        before = self.snapshot()
        self.assertRefused(self.provision(), rlg.RLG_PATH_EXISTS)
        self.assertRefused(self.provision(host_id="host-02"), rlg.RLG_PATH_EXISTS)
        self.assertEqual(self.snapshot(), before)

    def test_stale_side_files_refuse_provisioning(self):
        for suffix in ("-journal", "-wal", "-shm"):
            with self.subTest(suffix=suffix):
                side = Path(str(self.path) + suffix)
                side.write_bytes(b"stale")
                before = self.snapshot()
                self.assertRefused(self.provision(), rlg.RLG_PATH_EXISTS)
                self.assertEqual(self.snapshot(), before)
                side.unlink()

    def test_create_exclusive_even_when_the_existence_check_races(self):
        self.path.write_bytes(b"appeared after the check")
        before = self.snapshot()
        with mock.patch.object(rlg.os.path, "lexists", return_value=False):
            self.assertRefused(self.provision(), rlg.RLG_PATH_EXISTS)
        self.assertEqual(self.snapshot(), before)

    def test_missing_parent_creates_nothing(self):
        missing = self.host_dir / "not-there" / LEDGER_NAME
        self.assertRefused(self.provision(missing), rlg.RLG_PARENT_MISSING)
        self.assertFalse(missing.parent.exists())
        self.assertEqual(os.listdir(self.host_dir), [])

    def test_invalid_paths_refused_without_creating_anything(self):
        relative = os.path.join("isolated-host", LEDGER_NAME)
        cases = [relative, "file:" + str(self.path), "file:///" + str(self.path).replace("\\", "/"),
                 ":memory:", "", " " + str(self.path), str(self.path) + os.sep,
                 str(self.host_dir / ".." / "isolated-host" / LEDGER_NAME),
                 os.path.join(str(self.host_dir), ".", LEDGER_NAME), str(self.host_dir / "ledger.sqlite3"),
                 str(self.host_dir / rlg.LEDGER_FILENAME_SUFFIX), str(self.host_dir / (LEDGER_NAME + "\0"))]
        if os.name == "nt":
            cases += [r"\\server\share\x" + rlg.LEDGER_FILENAME_SUFFIX,
                      "\\\\?\\" + str(self.path), str(self.path) + ":stream" + rlg.LEDGER_FILENAME_SUFFIX]
        for path in cases:
            with self.subTest(path=path):
                self.assertRefused(rlg.provision(path, host_id=HOST, forbidden_roots=self.roots, clock=self.clock),
                                   rlg.RLG_PATH_INVALID)
        for path in (None, 7, str(self.path).encode()):
            self.assertRefused(rlg.provision(path, host_id=HOST, forbidden_roots=self.roots, clock=self.clock),
                               rlg.RLG_PATH_INVALID)
        self.assertEqual(os.listdir(self.host_dir), [])
        self.assertFalse(os.path.exists(os.path.join(os.getcwd(), relative)))

    def test_paths_inside_forbidden_roots_or_repositories_are_refused(self):
        inside_root = self.untrusted / LEDGER_NAME
        self.assertRefused(self.provision(inside_root), rlg.RLG_PATH_FORBIDDEN_ROOT)
        real_repo = REPO_ROOT / "scripts" / LEDGER_NAME
        self.assertRefused(self.provision(real_repo), rlg.RLG_PATH_FORBIDDEN_ROOT)
        self.assertFalse(real_repo.exists())
        for kind in ("dir", "file"):
            with self.subTest(fixture_repo=kind):
                repo = self.base / f"fixture-repo-{kind}"
                (repo / "nested").mkdir(parents=True, mode=0o700)
                if kind == "dir":
                    (repo / ".git").mkdir()
                else:   # a linked worktree's `.git` file
                    (repo / ".git").write_text("gitdir: /nowhere\n", encoding="utf-8")
                for path in (repo / LEDGER_NAME, repo / "nested" / LEDGER_NAME):
                    self.assertRefused(self.provision(path), rlg.RLG_PATH_INSIDE_REPOSITORY)
                    self.assertFalse(path.exists())
        self.assertEqual(os.listdir(self.untrusted), [])

    def test_forbidden_roots_are_mandatory(self):
        for roots in ((), [], None, str(self.untrusted), Path(self.untrusted), ("relative/root",), ("",), (7,)):
            with self.subTest(roots=roots):
                self.assertRefused(self.provision(forbidden_roots=roots), rlg.RLG_ROOTS_INVALID)
        self.assertEqual(os.listdir(self.host_dir), [])

    def test_host_id_is_a_validated_label(self):
        for host_id in ("", " host", "host/01", "h" * 129, None, 1, b"host-01"):
            with self.subTest(host_id=host_id):
                self.assertRefused(self.provision(host_id=host_id), rlg.RLG_HOST_ID_INVALID)
        self.assertEqual(os.listdir(self.host_dir), [])

    def test_acl_safety_claims_are_refused(self):
        self.assertRefused(self.provision(require_verified_acl=True), rlg.RLG_ACL_UNVERIFIABLE)
        self.assertRefused(self.provision(require_verified_acl="yes"), rlg.RLG_ARGUMENT_INVALID)
        self.assertRefused(self.provision(require_verified_acl=1), rlg.RLG_ARGUMENT_INVALID)
        self.assertEqual(os.listdir(self.host_dir), [])
        self.provision()
        self.assertOpenRefused(rlg.RLG_ACL_UNVERIFIABLE, require_verified_acl=True)

    def test_clock_is_checked_before_anything_is_created(self):
        def broken():
            raise RuntimeError("clock failure")
        for clock, code in ((broken, rlg.RLG_CLOCK_INVALID), (None, rlg.RLG_CLOCK_INVALID),
                            (lambda: NOW.replace(tzinfo=None), rlg.RLG_CLOCK_INVALID),
                            (lambda: datetime(2200, 1, 1, tzinfo=timezone.utc), rlg.RLG_CLOCK_IMPLAUSIBLE)):
            with self.subTest(code=code):
                self.assertRefused(self.provision(clock=clock), code)
        self.assertEqual(os.listdir(self.host_dir), [])

    def test_aliased_parent_directories_are_refused(self):
        target = self.base / "real-host"
        target.mkdir(mode=0o700)
        link = self.base / "alias-host"
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
        self.addCleanup(lambda: os.path.lexists(link) and (os.rmdir(link) if os.name == "nt" else os.unlink(link)))
        self.assertRefused(self.provision(link / LEDGER_NAME), rlg.RLG_PATH_ALIAS)
        self.assertEqual(os.listdir(target), [])
        with mock.patch.object(rha, "_is_alias", return_value=True):
            self.assertRefused(self.provision(), rlg.RLG_PATH_ALIAS)
        self.assertEqual(os.listdir(self.host_dir), [])

    def test_insecure_directories_are_refused_when_detectable(self):
        with mock.patch.object(rha, "_mode_insecure", return_value=True):
            self.assertRefused(self.provision(), rlg.RLG_PATH_INSECURE)
        if os.name == "posix":
            os.chmod(self.host_dir, 0o770)
            self.assertRefused(self.provision(), rlg.RLG_PATH_INSECURE)
            os.chmod(self.host_dir, 0o700)
        self.assertEqual(os.listdir(self.host_dir), [])

    def test_failed_provisioning_never_yields_an_openable_ledger(self):
        with mock.patch.object(rlg, "_validate", side_effect=rlg._Refused(rlg.RLG_SCHEMA_INVALID)):
            self.assertRefused(self.provision(), rlg.RLG_SCHEMA_INVALID)
        self.assertTrue(self.path.exists())   # left in place, never deleted or reused
        self.assertOpenRefused(rlg.RLG_NOT_A_RETIREMENT_LEDGER)
        self.assertRefused(self.provision(), rlg.RLG_PATH_EXISTS)
        result = rlg.recover_interrupted_write(str(self.path), host_id=HOST, forbidden_roots=self.roots)
        self.assertRefused(result, rlg.RLG_NOT_A_RETIREMENT_LEDGER)

    # FCP-4E-02d may open an existing ledger read-only; it is the only module
    # besides the ledger itself allowed to name it. The reader is checked
    # syntactically (AST): this refuses direct, aliased, string-named and
    # dynamic access to the writers, but it is not a runtime sandbox -- the
    # composition's own adversarial tests cover its behaviour.
    # FCP-4F-00 (F-01): `getattr` is allowed only in the exact forms 02d uses
    # (attribute names drawn from a literal module-level table), imports are
    # limited to the reader's own, `sys`/`os` to the attributes it uses, and
    # dunder, frame and ledger-internal attributes are refused, closing
    # `sys.modules`, aliased `getattr`, `__globals__` and accessor modules.
    LEDGER_READER = "runner_worktree_retirement_host_composition.py"
    LEDGER_WRITERS = frozenset({"provision", "recover_interrupted_write", "record_reverified_command_evidence",
                                "revoke_command", "_write", "_connect", "_sqlite_uri", "_audit"})
    READER_MODULE_ATTRS = frozenset({"open_existing", "RetirementLedgerRefused", "RecordedRetirementCommandEvidence",
                                     "_reverified_command", "_Refused", "_instant"})
    READER_LEDGER_METHODS = frozenset({"get_command", "is_revoked", "audit_trail", "clock_high_water_mark"})
    READER_GETATTR_TARGETS = frozenset({"manifest", "evidence"})
    # getattr(<target>, name) is read only inside a loop over this literal table.
    READER_GETATTR_FIELDS = {"manifest": "MANIFEST_FIELDS", "evidence": "_EVIDENCE_FLAGS"}
    DYNAMIC_ACCESS = frozenset({"eval", "exec", "compile", "__import__", "setattr", "delattr", "vars", "globals",
                                "locals", "importlib", "sqlite3", "__dict__", "__getattribute__"})
    DYNAMIC_ATTRS = frozenset({"__dict__", "__getattribute__", "import_module", "__loader__", "__spec__", "modules"})
    # (from-module or None, name, asname): exactly what the 02d reader imports.
    READER_IMPORTS = frozenset({
        (None, "base64", None), (None, "binascii", None), (None, "hashlib", None), (None, "json", None),
        (None, "os", None), (None, "re", None), (None, "sys", None),
        (None, "runner_worktree_retirement_authorization", "wra"),
        (None, "runner_worktree_retirement_host_authority", "rha"),
        (None, "runner_worktree_retirement_host_ledger", "rlg"),
        ("__future__", "annotations", None), ("dataclasses", "dataclass", None), ("dataclasses", "field", None),
        ("datetime", "datetime", None), ("datetime", "timedelta", None), ("datetime", "timezone", None),
        ("pathlib", "Path", None), ("typing", "Optional", None),
        ("scripts.ai", "runner_worktree_retirement_authorization", "wra"),
        ("scripts.ai", "runner_worktree_retirement_host_authority", "rha"),
        ("scripts.ai", "runner_worktree_retirement_host_ledger", "rlg"),
        ("cryptography.hazmat.primitives.asymmetric.ed25519", "Ed25519PublicKey", "_Ed25519PublicKey")})
    READER_MODULE_USES = {"sys": frozenset({"path"}), "os": frozenset({"path", "name"})}
    READER_DUNDER_NAMES = frozenset({"__file__"})
    FRAME_ATTR = re.compile(r"(?:f|tb|gi|cr|ag|co)_")
    SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
    COMPREHENSIONS = (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)

    @classmethod
    def ledger_internals(cls) -> frozenset:
        """Private callables of the ledger module and private ledger methods,
        derived from the real module so new internals are covered too."""
        names = {n for n, v in vars(rlg).items() if n.startswith("_") and not n.startswith("__")
                 and callable(v) and getattr(v, "__module__", None) == rlg.__name__}
        names |= {n for n in vars(rlg.RetirementLedger) if n.startswith("_") and not n.startswith("__")}
        return frozenset(names - cls.READER_MODULE_ATTRS)

    @staticmethod
    def _binds(node, ident: str) -> int:
        """How many times `ident` is (re)bound anywhere inside `node`."""
        count = 0
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and n.id == ident and not isinstance(n.ctx, ast.Load):
                count += 1
            elif isinstance(n, ast.arg) and n.arg == ident:
                count += 1
            elif isinstance(n, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar, ast.FunctionDef,
                                ast.AsyncFunctionDef, ast.ClassDef)) and getattr(n, "name", None) == ident:
                count += 1
            elif isinstance(n, ast.alias) and (n.asname or n.name) == ident:
                count += 1
            elif isinstance(n, (ast.Global, ast.Nonlocal)) and ident in n.names:
                count += 1
        return count

    @classmethod
    def _field_table(cls, tree, table: str, position, forbidden) -> bool:
        """`table` is assigned once, at module level, to a literal whose
        entries (or entry[position]) are public, non-ledger attribute names."""
        assigns = [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                   and isinstance(n.targets[0], ast.Name) and n.targets[0].id == table]
        if len(assigns) != 1 or cls._binds(tree, table) != 1:
            return False
        try:
            entries = ast.literal_eval(assigns[0].value)
        except (ValueError, TypeError, SyntaxError, RecursionError):
            return False
        if not isinstance(entries, tuple) or not entries:
            return False
        names = []
        for entry in entries:
            if position is not None:
                if not isinstance(entry, tuple) or not 0 <= position < len(entry):
                    return False
                entry = entry[position]
            names.append(entry)
        return all(isinstance(n, str) and n.isidentifier() and not n.startswith("_") and n not in forbidden
                   for n in names)

    @classmethod
    def permitted_getattr_table(cls, call, parents, tree, forbidden):
        """The field table read by an exactly permitted `getattr(target, name)`
        call, or None: two plain names, no default, `name` bound only by the
        nearest enclosing loop over the target's literal table."""
        if not (isinstance(call.func, ast.Name) and call.func.id == "getattr" and len(call.args) == 2
                and not call.keywords and all(type(a) is ast.Name for a in call.args)):
            return None
        target, name = call.args
        table = cls.READER_GETATTR_FIELDS.get(target.id)
        if table is None or target.id not in cls.READER_GETATTR_TARGETS:
            return None
        node = call
        while node in parents and not isinstance(node, cls.SCOPES):
            child, node = node, parents[node]
            if isinstance(node, ast.For) and child in node.body:
                loops, scope = [node], node
            elif isinstance(node, cls.COMPREHENSIONS) and child in (getattr(node, "elt", None),
                                                                    getattr(node, "key", None),
                                                                    getattr(node, "value", None)):
                loops, scope = node.generators, node
            else:
                continue
            for loop in loops:
                targets = loop.target.elts if isinstance(loop.target, ast.Tuple) else [loop.target]
                ids = [t.id if type(t) is ast.Name else None for t in targets]
                if name.id not in ids:
                    continue
                position = ids.index(name.id) if isinstance(loop.target, ast.Tuple) else None
                if not (isinstance(loop.iter, ast.Name) and loop.iter.id == table
                        and cls._binds(scope, name.id) == 1
                        and cls._field_table(tree, table, position, forbidden)):
                    return None
                return table
        return None

    @classmethod
    def ledger_reader_violations(cls, source: str) -> list:
        tree = ast.parse(source)
        found, imports = [], 0
        attribute_values = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        internals = cls.ledger_internals()
        forbidden = cls.LEDGER_WRITERS | cls.DYNAMIC_ACCESS | cls.DYNAMIC_ATTRS | internals
        permitted_getattr = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)
                             and cls.permitted_getattr_table(n, parents, tree, forbidden) is not None}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = node.module if isinstance(node, ast.ImportFrom) else None
                for alias in node.names:
                    if getattr(node, "level", 0) or (module, alias.name, alias.asname) not in cls.READER_IMPORTS:
                        found.append("unlisted import %s %s as %s" % (module, alias.name, alias.asname))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ("sqlite3", "importlib") or alias.name.startswith("importlib."):
                        found.append("import " + alias.name)
                    if "runner_worktree_retirement_host_ledger" in alias.name:
                        imports += 1
                        if alias.name != "runner_worktree_retirement_host_ledger" or alias.asname != "rlg":
                            found.append("import " + alias.name)
            elif isinstance(node, ast.ImportFrom):
                names = [a.name for a in node.names]
                if node.module in ("sqlite3", "importlib") or "runner_worktree_retirement_host_ledger" in (
                        node.module or ""):
                    found.append("from %s import" % node.module)
                for alias in node.names:
                    if alias.name == "runner_worktree_retirement_host_ledger":
                        imports += 1
                        if node.module != "scripts.ai" or alias.asname != "rlg" or len(names) != 1:
                            found.append("from %s import %s" % (node.module, alias.name))
            elif isinstance(node, ast.Attribute):
                if node.attr in cls.LEDGER_WRITERS or node.attr in cls.DYNAMIC_ATTRS or node.attr in internals:
                    found.append("." + node.attr)
                if re.fullmatch(r"__\w+__", node.attr) and not (
                        node.attr == "__init__" and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Name) and node.value.func.id == "super"
                        and not node.value.args and not node.value.keywords):
                    found.append("dunder ." + node.attr)
                if cls.FRAME_ATTR.match(node.attr):
                    found.append("frame ." + node.attr)
                if isinstance(node.value, ast.Name) and node.value.id == "rlg" and node.attr not in \
                        cls.READER_MODULE_ATTRS and not (re.fullmatch(r"[A-Z][A-Z0-9_]*", node.attr)
                                                         and not callable(getattr(rlg, node.attr, None))):
                    found.append("rlg." + node.attr)
                if isinstance(node.value, ast.Name) and node.value.id == "ledger" \
                        and node.attr not in cls.READER_LEDGER_METHODS:
                    found.append("ledger." + node.attr)
            elif isinstance(node, ast.Name):
                if node.id in cls.LEDGER_WRITERS or node.id in cls.DYNAMIC_ACCESS:
                    found.append(node.id)
                if node.id == "rlg" and id(node) not in attribute_values:
                    found.append("bare rlg")
                if node.id in cls.READER_MODULE_USES:
                    parent = parents.get(node)
                    if not (isinstance(parent, ast.Attribute) and parent.value is node
                            and parent.attr in cls.READER_MODULE_USES[node.id]):
                        found.append("%s use: %s" % (node.id, ast.unparse(parent) if parent else node.id))
                if re.fullmatch(r"__\w+__", node.id) and node.id not in cls.READER_DUNDER_NAMES:
                    found.append("dunder " + node.id)
                if node.id in ("getattr", "hasattr") and id(node) not in permitted_getattr:
                    parent = parents.get(node)
                    found.append(ast.unparse(parent) if isinstance(parent, ast.Call) else node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in cls.LEDGER_WRITERS or node.value in cls.DYNAMIC_ACCESS or node.value in internals:
                    found.append(repr(node.value))
            elif isinstance(node, ast.MatchClass):
                for name in node.kwd_attrs:
                    if name in forbidden or name.startswith("_"):
                        found.append("match " + name)
        if imports not in (1, 2):
            found.append("ledger imports: %d" % imports)
        return found

    @classmethod
    def ledger_referencing_modules(cls, directory: Path) -> list:
        return [module.name for module in sorted(directory.glob("*.py"))
                if module.name not in (MODULE_PATH.name, cls.LEDGER_READER)
                and "runner_worktree_retirement_host_ledger" in module.read_text(encoding="utf-8")]

    def test_provisioning_is_not_exposed_anywhere_else(self):
        self.assertEqual(self.ledger_referencing_modules(REPO_ROOT / "scripts" / "ai"), [])
        reader = REPO_ROOT / "scripts" / "ai" / self.LEDGER_READER
        self.assertTrue(reader.is_file())
        source = reader.read_text(encoding="utf-8")
        self.assertEqual(self.ledger_reader_violations(source), [])
        tree = ast.parse(source)
        used = {n.attr for n in ast.walk(tree)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "rlg"}
        self.assertIn("open_existing", used)
        self.assertTrue(self.READER_LEDGER_METHODS <= {
            n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "ledger"})
        self.assertFalse(used & self.LEDGER_WRITERS)
        for name in self.READER_MODULE_ATTRS:
            self.assertTrue(hasattr(rlg, name), name)
        for name in self.LEDGER_WRITERS:
            self.assertTrue(hasattr(rlg, name) or hasattr(rlg.RetirementLedger, name), name)
        # F-01: the real reader's only dynamic reads are the two exact 02d
        # forms, each over its literal table; the record flags it reads exist.
        self.assertEqual(set(self.READER_GETATTR_FIELDS), self.READER_GETATTR_TARGETS)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        forbidden = self.LEDGER_WRITERS | self.DYNAMIC_ACCESS | self.DYNAMIC_ATTRS | self.ledger_internals()
        reads = sorted((ast.unparse(n), self.permitted_getattr_table(n, parents, tree, forbidden))
                       for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id in ("getattr", "hasattr"))
        self.assertEqual(reads, [("getattr(evidence, name)", "_EVIDENCE_FLAGS"),
                                 ("getattr(manifest, name)", "MANIFEST_FIELDS")])
        flags = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                     and ast.unparse(n.targets[0]) == "_EVIDENCE_FLAGS")
        record_fields = {f.name for f in dataclasses.fields(rlg.RecordedRetirementCommandEvidence)}
        self.assertTrue({name for name, _ in flags} <= record_fields)
        internals = self.ledger_internals()
        self.assertTrue({"_provision", "_validate", "_read", "_query"} <= internals)
        self.assertFalse(internals & (self.READER_MODULE_ATTRS | self.READER_LEDGER_METHODS))

    def test_ledger_reader_check_refuses_writers_and_bypasses(self):
        good = "from scripts.ai import runner_worktree_retirement_host_ledger as rlg\n" \
               "ledger = rlg.open_existing(p, host_id=h, forbidden_roots=r)\n" \
               "x = (ledger.get_command(c), ledger.is_revoked(c), rlg.RLG_PATH_MISSING)\n"
        self.assertEqual(self.ledger_reader_violations(good), [])
        # The exact getattr forms 02d uses remain accepted.
        reads = "MANIFEST_FIELDS = ('format', 'roots')\n" \
                "_EVIDENCE_FLAGS = (('authorizes_action', False), ('issued', False))\n" \
                "def f(manifest, evidence):\n" \
                "    for name in MANIFEST_FIELDS:\n" \
                "        v = getattr(manifest, name)\n" \
                "    return any(getattr(evidence, name) is not value for name, value in _EVIDENCE_FLAGS)\n"
        self.assertEqual(self.ledger_reader_violations(good + reads), [])
        key = "'scripts.ai.runner_worktree_retirement_host_ledger'"
        refused = {
            "provision": "rlg.provision(p, host_id=h, forbidden_roots=r, clock=k)",
            "recover": "rlg.recover_interrupted_write(p, host_id=h, forbidden_roots=r)",
            "record": "ledger.record_reverified_command_evidence(e, config=c, proposal=q, clock=k)",
            "revoke": "ledger.revoke_command(c, 'SUPERSEDED', clock=k)",
            "write": "ledger._write('op', k, w)",
            "connect": "rlg._connect(p, 'rw', 1.0)",
            "alias module": "m = rlg\nm.open_existing(p)",
            "alias writer": "w = rlg.provision",
            "from import writer": "from scripts.ai.runner_worktree_retirement_host_ledger import provision",
            "getattr module": "getattr(rlg, 'pro' + 'vision')",
            "getattr ledger": "getattr(ledger, n)()",
            "string name": "f = 'revoke_command'",
            "eval": "eval(s)",
            "dunder import": "__import__(s)",
            "importlib": "import importlib",
            "sqlite": "import sqlite3",
            "unknown ledger method": "ledger.something_else()",
            "unknown module function": "rlg._validate(con, h)",
            # F-01 (1): sys.modules, aliases of sys, index and methods.
            "sys.modules index": "import sys\nmanifest = sys.modules[" + key + "]\ngetattr(manifest, n)(p)",
            "sys.modules via sys alias": "import sys as s\nmanifest = s.modules[" + key + "]\n"
                                         "getattr(manifest, 'pro' + 'vision')(p)",
            "sys rebound": "import sys\ns = sys\nm = s.modules[" + key + "]",
            "from sys import modules": "from sys import modules as mods\nevidence = mods.get(" + key + ")\n"
                                       "getattr(evidence, n)()",
            "sys.modules methods": "import sys\nm = [v for v in sys.modules.values() if v.__name__ == k]",
            "sys exc_info frame": "import sys\ng = sys.exc_info()[2].tb_frame.f_globals[n]",
            # F-01 (2): getattr/hasattr on manifest or evidence outside the exact 02d forms.
            "getattr manifest variable": "manifest = ledger\ngetattr(manifest, n)(e)",
            "getattr evidence concat": "getattr(evidence, 'pro' + 'vision')",
            "getattr default": "getattr(manifest, 'roots', None)",
            "getattr no arguments": "getattr()",
            "getattr one argument": "getattr(manifest)",
            "getattr extra arguments": "getattr(manifest, name, None, 1)",
            "getattr keyword": "getattr(manifest, name=n)",
            "getattr starred": "getattr(manifest, *names)",
            "hasattr dynamic": "hasattr(evidence, n)",
            "getattr nested": "getattr(manifest, getattr(evidence, n))",
            "getattr outside its loop": "name = n\ngetattr(manifest, name)",
            "getattr name rebound in loop": reads + "for name in MANIFEST_FIELDS:\n    name = n\n"
                                                    "    getattr(manifest, name)",
            "getattr walrus in comprehension": reads + "any(getattr(evidence, (name := n)) "
                                                       "for name, value in _EVIDENCE_FLAGS)",
            "getattr inside nested lambda": reads + "for name in MANIFEST_FIELDS:\n"
                                                    "    (lambda name: getattr(manifest, name))(n)",
            "getattr over the other table": reads + "for name in _EVIDENCE_FLAGS:\n    getattr(manifest, name)",
            "getattr table rebound": reads.replace("('format', 'roots')", "(n,)"),
            "getattr table mutated": reads + "MANIFEST_FIELDS += (n,)",
            "getattr table dunder entry": reads.replace("'roots'", "'__globals__'"),
            "getattr table internal entry": reads.replace("'roots'", "'_query'"),
            # F-01 (3): other indirect routes to the writers.
            "getattr alias": "import sys\ng = getattr\ng(sys.modules[" + key + "], n)(p)",
            "getattr passed as value": "f = map(getattr, [ledger], [n])",
            "builtins getattr": "import builtins\nbuiltins.getattr(ledger, n)(e)",
            "from builtins import getattr": "from builtins import getattr as g\ng(ledger, n)(e)",
            "__builtins__": "g = __builtins__['get' + 'attr']",
            "operator attrgetter": "import operator\noperator.attrgetter(n)(ledger)(e)",
            "from operator import methodcaller": "from operator import methodcaller as mc\nmc(n, e)(ledger)",
            "inspect getmembers": "import inspect\nw = dict(inspect.getmembers(ledger))[n]",
            "pickle find_class": "import pickle\npickle.loads(b)",
            "gc objects": "import gc\nw = [o for o in gc.get_objects() if callable(o)]",
            "function globals": "w = rlg.open_existing.__globals__['pro' + 'vision']",
            "bound method globals": "w = ledger.get_command.__func__.__globals__[n]",
            "class mro": "c = type(ledger).__mro__",
            "generator frame": "m = (x for x in ()).gi_frame.f_globals[n]",
            "internal function name": "f = '_provision'",
            "aliased ledger internal method": "x = ledger\nx._read(w)",
            "match keyword pattern": "match ledger:\n    case object(revoke_command=f):\n        f(c)",
            "os process": "import os\nos.system(s)",
            "relative import": "from . import runner_worktree_retirement_host_ledger as rlg",
            "aliased allowed import": "import json as rlg2",
        }
        for name, extra in refused.items():
            with self.subTest(name):
                self.assertNotEqual(self.ledger_reader_violations(good + extra + "\n"), [])
        unaliased = good.replace(" as rlg\n", "\nrlg = runner_worktree_retirement_host_ledger\n")
        self.assertNotEqual(self.ledger_reader_violations(unaliased), [])
        self.assertNotEqual(self.ledger_reader_violations("x = 1\n"), [])
        # Any other module merely naming the ledger, even with a read-only
        # call, is still refused by the literal scan.
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp)
            (scripts / MODULE_PATH.name).write_text("# runner_worktree_retirement_host_ledger\n", encoding="utf-8")
            (scripts / self.LEDGER_READER).write_text(good, encoding="utf-8")
            (scripts / "innocent.py").write_text("x = 1\n", encoding="utf-8")
            self.assertEqual(self.ledger_referencing_modules(scripts), [])
            (scripts / "other_reader.py").write_text(good, encoding="utf-8")
            (scripts / "other_writer.py").write_text(
                "import runner_worktree_retirement_host_ledger as rlg\nrlg.provision(p)\n", encoding="utf-8")
            (scripts / "other_mention.py").write_text("'runner_worktree_retirement_host_ledger'\n", encoding="utf-8")
            self.assertEqual(self.ledger_referencing_modules(scripts),
                             ["other_mention.py", "other_reader.py", "other_writer.py"])


# ---------------------------------------------------------------------------
# Opening existing ledgers
# ---------------------------------------------------------------------------

class OpenExistingTests(LedgerCase):
    def test_missing_ledger_is_refused_and_never_created(self):
        before = self.snapshot()
        self.assertOpenRefused(rlg.RLG_PATH_MISSING)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.path.exists())

    def test_files_that_are_not_retirement_ledgers_are_refused_untouched(self):
        plain = self.host_dir / ("plain" + rlg.LEDGER_FILENAME_SUFFIX)
        con = sqlite3.connect(str(plain))
        con.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        con.commit()
        con.close()
        cases = {"empty": b"", "text": b"not a database at all" * 10, "sqlite-header-only": b"SQLite format 3\x00"}
        for name, content in cases.items():
            (self.host_dir / (name + rlg.LEDGER_FILENAME_SUFFIX)).write_bytes(content)
        before = self.snapshot()
        for name in ("plain", *cases):
            with self.subTest(name=name):
                self.assertOpenRefused(rlg.RLG_NOT_A_RETIREMENT_LEDGER, self.host_dir / (name + rlg.LEDGER_FILENAME_SUFFIX))
        self.assertEqual(self.snapshot(), before)

    def test_the_pr_promotion_host_ledger_is_not_a_retirement_ledger(self):
        from scripts.ai import runner_promotion_host_ledger as rphl
        pr_path = self.host_dir / ("pr" + rlg.LEDGER_FILENAME_SUFFIX)
        rphl.HostLedger(pr_path, owner="host-owner-1", clock=self.clock, untrusted_roots=self.roots)
        before = self.snapshot()
        self.assertOpenRefused(rlg.RLG_NOT_A_RETIREMENT_LEDGER, pr_path)
        self.assertRefused(self.provision(pr_path), rlg.RLG_PATH_EXISTS)
        self.assertEqual(self.snapshot(), before)

    def test_host_id_binding(self):
        self.provision()
        before = self.snapshot()
        self.assertOpenRefused(rlg.RLG_HOST_MISMATCH, host_id="host-02")
        self.assertOpenRefused(rlg.RLG_HOST_ID_INVALID, host_id="host 02")
        self.assertEqual(self.snapshot(), before)

    def test_unsupported_versions_are_refused_not_migrated(self):
        self.provision()
        self.tamper("PRAGMA user_version = 4002004")
        before = self.snapshot()
        self.assertOpenRefused(rlg.RLG_SCHEMA_UNSUPPORTED)
        self.assertEqual(self.snapshot(), before)
        self.tamper(f"PRAGMA user_version = {rlg.LEDGER_USER_VERSION}", "DROP TRIGGER meta_no_update",
                    "UPDATE meta SET value = 'fcp4e02c-retirement-ledger-v2' WHERE key = 'schema_version'",
                    dict(rlg._TRIGGERS)["meta_no_update"])
        before = self.snapshot()
        self.assertOpenRefused(rlg.RLG_SCHEMA_UNSUPPORTED)
        self.assertEqual(self.snapshot(), before)

    def test_foreign_application_id_is_refused(self):
        self.provision()
        self.tamper("PRAGMA application_id = 1")
        self.assertOpenRefused(rlg.RLG_NOT_A_RETIREMENT_LEDGER)

    def test_missing_altered_or_extra_schema_objects_are_refused(self):
        self.provision()
        pristine = self.path.read_bytes()
        attacks = {
            "dropped audit trigger": ("DROP TRIGGER audit_no_delete",),
            "dropped evidence trigger": ("DROP TRIGGER command_evidence_no_update",),
            "dropped revocation guard": ("DROP TRIGGER command_evidence_not_revoked",),
            "dropped clock guard": ("DROP TRIGGER clock_forward_only",),
            "weakened trigger": ("DROP TRIGGER audit_no_update",
                                 "CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit WHEN 0\n"
                                 "    BEGIN SELECT RAISE(ABORT, 'fcp4e02c-ledger-append-only'); END"),
            "extra trigger": ("CREATE TRIGGER sneaky AFTER INSERT ON audit BEGIN SELECT 1; END",),
            "extra view": ("CREATE VIEW permits AS SELECT 1",),
            "extra table": ("CREATE TABLE issued_permits (id TEXT)",),
            "extra index": ("CREATE INDEX audit_event ON audit(event)",),
        }
        for name, statements in attacks.items():
            with self.subTest(attack=name):
                self.path.write_bytes(pristine)
                self.tamper(*statements)
                before = self.snapshot()
                self.assertOpenRefused(rlg.RLG_SCHEMA_INVALID)
                self.assertEqual(self.snapshot(), before)

    def test_tables_rebuilt_without_unique_constraints_are_refused(self):
        self.provision()
        sql = dict(rlg._TABLES)["command_evidence"]
        self.tamper("DROP TABLE command_evidence",
                    sql.replace("command_id TEXT NOT NULL UNIQUE", "command_id TEXT NOT NULL"),
                    *(s for n, s in rlg._TRIGGERS if n.startswith("command_evidence")))
        self.assertOpenRefused(rlg.RLG_SCHEMA_INVALID)

    def test_wal_mode_is_refused(self):
        self.provision()
        self.tamper("PRAGMA journal_mode = WAL")
        for suffix in ("-wal", "-shm"):
            side = Path(str(self.path) + suffix)
            if side.exists():
                side.unlink()
        before = self.snapshot()
        self.assertOpenRefused(rlg.RLG_SCHEMA_INVALID)
        self.assertEqual(self.snapshot(), before)

    def test_unexpected_wal_side_files_are_refused(self):
        self.provision()
        Path(str(self.path) + "-wal").write_bytes(b"")
        before = self.snapshot()
        self.assertOpenRefused(rlg.RLG_SIDE_FILE_PRESENT)
        self.assertEqual(self.snapshot(), before)

    def test_corruption_and_truncation_are_refused_not_repaired(self):
        self.provision()
        pristine = self.path.read_bytes()
        page = int.from_bytes(pristine[16:18], "big")
        corrupt = bytearray(pristine)
        corrupt[page:2 * page] = b"\xa5" * page
        self.path.write_bytes(bytes(corrupt))
        before = self.snapshot()
        self.assertOpenRefused(rlg.RLG_CORRUPT)
        self.assertEqual(self.snapshot(), before)
        self.path.write_bytes(pristine[:len(pristine) - 10])
        before = self.snapshot()
        self.assertOpenRefused(rlg.RLG_SCHEMA_INVALID)
        self.assertEqual(self.snapshot(), before)

    def test_tampered_rows_break_the_invariants(self):
        ledger = self.ledger()
        self.assertEqual(self.record(ledger).status, rlg.STATUS_RECORDED_NON_AUTHORIZING)
        pristine = self.path.read_bytes()
        attacks = {
            "deleted audit row": ("DROP TRIGGER audit_no_delete", "DELETE FROM audit WHERE seq = 2",
                                  dict(rlg._TRIGGERS)["audit_no_delete"]),
            "clock rewound": ("DROP TRIGGER clock_forward_only",
                              "UPDATE clock_high_water SET high_water = '2026-10-26T11:00:00.000000Z'",
                              dict(rlg._TRIGGERS)["clock_forward_only"]),
            "foreign host row": ("DROP TRIGGER command_evidence_no_update",
                                 "UPDATE command_evidence SET host_id = 'host-02'",
                                 dict(rlg._TRIGGERS)["command_evidence_no_update"]),
            "metadata row added": ("DROP TRIGGER meta_no_insert",
                                   "INSERT INTO meta (key, value) VALUES ('domain', 'x') ON CONFLICT DO NOTHING",
                                   "DROP TRIGGER meta_no_update", "UPDATE meta SET value = 'other-domain'"
                                   " WHERE key = 'domain'", dict(rlg._TRIGGERS)["meta_no_update"],
                                   dict(rlg._TRIGGERS)["meta_no_insert"]),
        }
        for name, statements in attacks.items():
            with self.subTest(attack=name):
                self.path.write_bytes(pristine)
                self.tamper(*statements)
                self.assertOpenRefused(rlg.RLG_LEDGER_INCONSISTENT)

    def test_non_regular_or_linked_ledgers_are_refused(self):
        directory = self.host_dir / ("dir" + rlg.LEDGER_FILENAME_SUFFIX)
        directory.mkdir()
        self.assertOpenRefused(rlg.RLG_NOT_REGULAR_FILE, directory)
        self.provision()
        hard = self.host_dir / ("hard" + rlg.LEDGER_FILENAME_SUFFIX)
        os.link(self.path, hard)
        self.assertOpenRefused(rlg.RLG_PATH_ALIAS)
        self.assertOpenRefused(rlg.RLG_PATH_ALIAS, hard)
        hard.unlink()
        self.open()
        with mock.patch.object(rha, "_is_alias", side_effect=lambda st: stat.S_ISREG(st.st_mode)):
            self.assertOpenRefused(rlg.RLG_PATH_ALIAS)
        symlink = self.host_dir / ("sym" + rlg.LEDGER_FILENAME_SUFFIX)
        try:
            os.symlink(self.path, symlink)
        except OSError:   # unprivileged Windows: covered by the mocked alias above
            symlink = None
        if symlink is not None:
            self.assertOpenRefused(rlg.RLG_PATH_ALIAS, symlink)

    def test_invalid_open_arguments(self):
        self.provision()
        for timeout in (-1, 31, "5", None, True):
            with self.subTest(timeout=timeout):
                self.assertOpenRefused(rlg.RLG_ARGUMENT_INVALID, busy_timeout_seconds=timeout)
        self.assertOpenRefused(rlg.RLG_ROOTS_INVALID, forbidden_roots=())
        self.assertOpenRefused(rlg.RLG_PATH_INVALID, "relative" + rlg.LEDGER_FILENAME_SUFFIX)
        with self.assertRaises(TypeError):
            rlg.RetirementLedger(object(), str(self.path), HOST, (0, 0), 1.0)

    def test_a_ledger_moved_into_a_forbidden_root_is_refused(self):
        self.provision()
        moved = self.untrusted / LEDGER_NAME
        os.replace(self.path, moved)
        self.assertOpenRefused(rlg.RLG_PATH_FORBIDDEN_ROOT, moved)


# ---------------------------------------------------------------------------
# Read-only behaviour
# ---------------------------------------------------------------------------

class ReadOnlyTests(LedgerCase):
    def setUp(self):
        super().setUp()
        ledger = self.ledger()
        self.assertEqual(self.record(ledger).status, rlg.STATUS_RECORDED_NON_AUTHORIZING)
        self.assertEqual(ledger.revoke_command("retire-cmd-9", "OPERATOR_HOLD", clock=self.clock).status,
                         rlg.STATUS_REVOKED)

    def all_reads(self, ledger):
        return (ledger.get_command("retire-cmd-1"), ledger.get_command("unknown-cmd"), ledger.is_revoked("retire-cmd-9"),
                ledger.is_revoked("retire-cmd-1"), ledger.audit_trail(), ledger.clock_high_water_mark())

    def test_reads_preserve_bytes_mtime_and_directory_listing(self):
        before = self.snapshot()
        ledger = self.open()
        first = self.all_reads(ledger)
        for _ in range(3):
            self.assertEqual(self.all_reads(ledger), first)
            self.assertEqual(self.all_reads(self.open()), first)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(sorted(os.listdir(self.host_dir)), [LEDGER_NAME])

    def test_reads_use_real_sqlite_read_only_connections_and_issue_no_writes(self):
        modes, statements = [], []
        real_connect = rlg._connect

        def spy(path, mode, timeout):
            modes.append(mode)
            con = real_connect(path, mode, timeout)
            con.set_trace_callback(statements.append)
            return con

        with mock.patch.object(rlg, "_connect", spy):
            self.all_reads(self.open())
        self.assertEqual(set(modes), {"ro"})
        text = "\n".join(statements).upper()
        for forbidden in ("BEGIN IMMEDIATE", "BEGIN EXCLUSIVE", "INSERT", "UPDATE ", "DELETE", "CREATE",
                          "JOURNAL_MODE", "WAL_CHECKPOINT", "VACUUM", "USER_VERSION =", "APPLICATION_ID ="):
            self.assertNotIn(forbidden, text)
        con = rlg._connect(str(self.path), "ro", 1.0)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("INSERT INTO audit (at, event, code) VALUES ('x', 'y', 'z')")
        finally:
            con.close()
        for mode in ("rwc", "memory", ""):
            with self.assertRaises(ValueError):
                rlg._connect(str(self.path), mode, 1.0)

    def test_reads_take_no_clock_and_never_advance_the_mark(self):
        ledger = self.open()
        mark = ledger.clock_high_water_mark()
        trail = ledger.audit_trail()
        self.now = at(3600)
        self.all_reads(ledger)
        self.assertEqual((ledger.clock_high_water_mark(), ledger.audit_trail()), (mark, trail))
        with self.assertRaises(TypeError):
            ledger.get_command("retire-cmd-1", clock=self.clock)

    def test_reads_after_the_file_vanished_or_changed_refuse_and_recreate_nothing(self):
        ledger = self.open()
        moved = self.base / ("moved" + rlg.LEDGER_FILENAME_SUFFIX)
        os.replace(self.path, moved)
        self.assertQueryRefused(rlg.RLG_PATH_MISSING, ledger.audit_trail)
        self.assertRefused(ledger.revoke_command("x-1", "SUPERSEDED", clock=self.clock), rlg.RLG_PATH_MISSING)
        self.assertEqual(os.listdir(self.host_dir), [])
        self.path.write_bytes(moved.read_bytes())   # same bytes, different file object
        self.assertQueryRefused(rlg.RLG_FILE_CHANGED, ledger.clock_high_water_mark)
        self.assertRefused(self.record(ledger, self.env(command_id="retire-cmd-2", nonce=nonce(2))),
                           rlg.RLG_FILE_CHANGED)

    def test_query_arguments_are_validated(self):
        ledger = self.open()
        for bad in ("", "has space", None, 3, "x" * 129):
            with self.subTest(bad=bad):
                self.assertQueryRefused(rlg.RLG_ARGUMENT_INVALID, lambda: ledger.get_command(bad))
                self.assertQueryRefused(rlg.RLG_ARGUMENT_INVALID, lambda: ledger.is_revoked(bad))

    def test_records_returned_by_reads_are_never_authorizing(self):
        record = self.open().get_command("retire-cmd-1")
        self.assertIs(type(record), rlg.RecordedRetirementCommandEvidence)
        self.assertFixedFlags(record, _FIXED_RECORD_FLAGS)
        self.assertEqual(record.record_state, rlg.RECORD_STATE_RECORDED_NON_AUTHORIZING)
        self.assertEqual(record.evidence_kind, rlg.EVIDENCE_SIGNATURE_REVERIFIED_NON_AUTHORIZING)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.authorizes_action = True
        with self.assertRaises(ValueError):
            dataclasses.replace(record, issued=True)


# ---------------------------------------------------------------------------
# Command evidence
# ---------------------------------------------------------------------------

class CommandEvidenceTests(LedgerCase):
    def setUp(self):
        super().setUp()
        self.ledger_ = self.ledger()

    def test_reverified_evidence_is_recorded_once_and_never_authorizes(self):
        envelope = self.env()
        result = self.record(self.ledger_, envelope)
        message = rha.canonical_command_message(t.command_for(self.proposal))
        digest = hashlib.sha256(message).hexdigest()
        self.assertEqual((result.operation, result.status, result.reason_codes, result.command_id,
                          result.command_message_digest, result.signature_reverified, result.audit_seq,
                          result.clock_high_water_mark),
                         (rlg.OP_RECORD_REVERIFIED_COMMAND_EVIDENCE, rlg.STATUS_RECORDED_NON_AUTHORIZING, (),
                          "retire-cmd-1", digest, True, 2, "2026-10-26T12:00:00.000000Z"))
        self.assertFixedFlags(result)
        record = self.ledger_.get_command("retire-cmd-1")
        c = t.command_for(self.proposal)
        self.assertEqual(dataclasses.astuple(record)[:17], (
            rlg.RECORD_VERSION, rlg.EVIDENCE_SIGNATURE_REVERIFIED_NON_AUTHORIZING,
            rlg.RECORD_STATE_RECORDED_NON_AUTHORIZING, rha.COMMAND_FORMAT, HOST, c.command_id, c.nonce, c.key_id,
            c.director_id, c.proposal_digest, c.scope_digest, c.target_identity_digest, digest, c.issued_at,
            c.expires_at, "2026-10-26T12:00:00.000000Z", None))
        self.assertEqual(self.ledger_.audit_trail()[-1], rlg.RetirementAuditEvent(
            2, "2026-10-26T12:00:00.000000Z", rlg.EVENT_COMMAND_EVIDENCE_RECORDED,
            rlg.EVIDENCE_SIGNATURE_REVERIFIED_NON_AUTHORIZING, "retire-cmd-1", digest))

    def test_no_envelope_signature_key_or_path_is_stored(self):
        envelope = self.env()
        self.record(self.ledger_, envelope)
        data = self.path.read_bytes()
        signature = self.key.sign(rha.canonical_command_message(t.command_for(self.proposal)))
        target = self.proposal.target
        for secret in (envelope, signature, signature.hex().encode(), t.raw_public(self.key),
                       t.raw_public(self.key).hex().encode(), str(self.path).encode(), str(self.host_dir).encode(),
                       target.path.encode(), target.git_dir.encode(), target.head_sha.encode(),
                       rha.SIGNATURE_DOMAIN):
            self.assertNotIn(secret, data)
        import base64
        self.assertNotIn(base64.b64encode(signature), data)

    def test_replay_and_collisions_are_refused_without_any_mutation(self):
        self.record(self.ledger_)
        before = self.snapshot()
        cases = (
            (self.env(), rlg.RLG_COMMAND_DUPLICATE),
            (self.env(nonce=nonce(1)), rlg.RLG_COMMAND_DUPLICATE),
            (self.env(command_id="retire-cmd-2"), rlg.RLG_NONCE_REUSED),
        )
        for envelope, code in cases:
            with self.subTest(code=code):
                self.assertRefused(self.record(self.ledger_, envelope), code)
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.ledger_.audit_trail()), 2)

    def test_message_digest_is_unique_at_the_storage_layer(self):
        self.record(self.ledger_)
        con = raw(self.path)
        try:
            row = con.execute("SELECT * FROM command_evidence").fetchone()
            values = list(row[1:])
            values[5], values[6] = "retire-cmd-2", nonce(2)   # new id and nonce, same message digest
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO command_evidence (record_version, evidence_kind, record_state, domain,"
                            " host_id, command_id, nonce, key_id, director_id, proposal_digest, scope_digest,"
                            " target_identity_digest, command_message_digest, issued_at, expires_at, recorded_at)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
        finally:
            con.close()
        sql = dict(rlg._TABLES)["command_evidence"]
        for column in ("command_id", "nonce", "command_message_digest"):
            self.assertIn(f"{column} TEXT NOT NULL UNIQUE", sql)
        with mock.patch.object(rha, "verify_retirement_command") as verify, \
                mock.patch.object(rlg, "_reverified_command", return_value=dataclasses.replace(
                    t.command_for(self.proposal), command_id="retire-cmd-2", nonce=nonce(2))):
            verify.return_value = mock.Mock(command_message_digest=self.ledger_.get_command(
                "retire-cmd-1").command_message_digest)
            self.assertRefused(self.record(self.ledger_), rlg.RLG_MESSAGE_DUPLICATE)

    def test_revoked_commands_cannot_be_recorded_later(self):
        self.assertEqual(self.ledger_.revoke_command("retire-cmd-1", "DIRECTOR_WITHDRAWN", clock=self.clock).status,
                         rlg.STATUS_REVOKED)
        before = self.snapshot()
        self.assertRefused(self.record(self.ledger_), rlg.RLG_COMMAND_REVOKED)
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.ledger_.get_command("retire-cmd-1"))
        self.assertTrue(self.ledger_.is_revoked("retire-cmd-1"))

    def test_other_host_or_other_domain_is_refused(self):
        other = t.make_config(t.raw_public(self.key), host_id="host-02")
        before = self.snapshot()
        self.assertRefused(self.record(self.ledger_, config=other), rlg.RLG_HOST_MISMATCH)
        other_proposal = t.make_proposal(host_id="host-02")[0]
        self.assertRefused(self.record(self.ledger_, t.envelope(t.command_for(other_proposal, host_id="host-02"),
                                                                self.key), proposal=other_proposal),
                           rlg.RLG_VERIFICATION_REFUSED, rha.RCV_HOST_MISMATCH)
        self.assertRefused(self.record(self.ledger_, self.env(host_id="host-02")),
                           rlg.RLG_VERIFICATION_REFUSED, rha.RCV_HOST_MISMATCH)
        self.assertRefused(self.record(self.ledger_, self.env(format="fcp3b-promotion-command-v1")),
                           rlg.RLG_VERIFICATION_REFUSED, rha.RCV_COMMAND_VERSION_UNSUPPORTED)
        self.assertRefused(self.record(self.ledger_, self.env(action="DELETE_BRANCH")),
                           rlg.RLG_VERIFICATION_REFUSED, rha.RCV_ACTION_INVALID)
        self.assertEqual(self.snapshot(), before)

    def test_verifier_refusals_are_carried_and_nothing_is_recorded(self):
        stranger = Ed25519PrivateKey.generate()
        revoked = t.make_config(t.raw_public(self.key), revoked_key_ids=(t.KEY_ID,))
        tampered = t.forge(self.proposal, proposal_digest="0" * 64)
        mismatched_report = twra.fixture()[0]
        cases = (
            (dict(envelope=self.env(stranger)), rha.RCV_SIGNATURE_INVALID),
            (dict(envelope=self.env(), config=revoked), rha.RCV_KEY_REVOKED),
            (dict(envelope=self.env(), proposal=tampered), rha.RCV_PROPOSAL_TAMPERED),
            (dict(envelope=self.env(), report=mismatched_report, inventory_record=None), rha.RCV_INPUT_INVALID),
            (dict(envelope=b'{"command": {}, "signature": ""}'), rha.RCV_COMMAND_MALFORMED),
            (dict(envelope=b"{"), rha.RCV_ENVELOPE_MALFORMED),
            (dict(envelope=self.env(nonce="0" * 64)), rha.RCV_NONCE_INVALID),
        )
        before = self.snapshot()
        for kwargs, code in cases:
            with self.subTest(code=code):
                envelope = kwargs.pop("envelope")
                result = self.assertRefused(self.record(self.ledger_, envelope, **kwargs),
                                            rlg.RLG_VERIFICATION_REFUSED, code)
                self.assertIs(result.signature_reverified, False)
        self.assertEqual(self.snapshot(), before)

    def test_command_window_is_checked_against_the_callers_clock(self):
        before = self.snapshot()
        self.now = at(180)
        self.assertRefused(self.record(self.ledger_), rlg.RLG_VERIFICATION_REFUSED, rha.RCV_COMMAND_EXPIRED)
        self.now = NOW
        self.assertRefused(self.record(self.ledger_, self.env(issued_at=t.stamp(30), expires_at=t.stamp(200))),
                           rlg.RLG_VERIFICATION_REFUSED, rha.RCV_COMMAND_NOT_YET_VALID)
        self.assertEqual(self.snapshot(), before)

    def test_source_records_are_revalidated_when_given(self):
        result = self.record(self.ledger_, report=self.report, inventory_record=self.inventory_record)
        self.assertEqual(result.status, rlg.STATUS_RECORDED_NON_AUTHORIZING)

    def test_wrong_argument_types_are_refused_before_storage(self):
        verification = rha.verify_retirement_command(self.env(), config=self.config, proposal=self.proposal, now=NOW)
        self.assertIs(verification.signature_verified, True)
        before = self.snapshot()
        for envelope in (verification, self.env().decode(), bytearray(self.env()), None):
            with self.subTest(envelope=type(envelope)):
                self.assertRefused(self.ledger_.record_reverified_command_evidence(
                    envelope, config=self.config, proposal=self.proposal, clock=self.clock), rlg.RLG_ARGUMENT_INVALID)
        self.assertRefused(self.record(self.ledger_, config=dataclasses.asdict(self.config)),
                           rlg.RLG_ARGUMENT_INVALID)
        self.assertEqual(self.snapshot(), before)

    def test_crypto_unavailable_never_records(self):
        before = self.snapshot()
        with mock.patch.object(rha, "CRYPTO_AVAILABLE", False):
            self.assertRefused(self.record(self.ledger_), rlg.RLG_CRYPTO_UNAVAILABLE)
        with mock.patch.object(rha, "_Ed25519PublicKey", None):
            result = self.assertRefused(self.record(self.ledger_), rlg.RLG_VERIFICATION_REFUSED)
            self.assertIn(result.reason_codes[1], (rha.RCV_CONFIG_INVALID, rha.RCV_SIGNATURE_INVALID))
        self.assertEqual(self.snapshot(), before)

    def test_spoofed_verification_results_are_never_trusted(self):
        good = rha.verify_retirement_command(self.env(), config=self.config, proposal=self.proposal, now=NOW)
        other = self.env(command_id="retire-cmd-2", nonce=nonce(2))
        fake_type = type("RetirementCommandVerification", (), dict(
            (f.name, getattr(good, f.name)) for f in dataclasses.fields(good)))()
        inconsistent = (rlg.RLG_VERIFICATION_INCONSISTENT,)
        spoofs = {
            "valid result for another envelope": (good, other, inconsistent),
            "authorizing flag": (t.forge(good, authorizes_action=True), self.env(), inconsistent),
            "issued flag": (t.forge(good, issued=True), self.env(), inconsistent),
            "host authenticated": (t.forge(good, host_identity_authenticated=True), self.env(), inconsistent),
            "duck typed": (fake_type, self.env(), inconsistent),
            "digest mismatch": (t.forge(good, command_message_digest="1" * 64), self.env(), inconsistent),
            "verified status with reasons": (t.forge(good, reason_codes=(rha.RCV_INTERNAL_ERROR,)), self.env(),
                                             inconsistent),
            "verified status without signature": (t.forge(good, signature_verified=False), self.env(),
                                                  inconsistent),
            "limitations dropped": (t.forge(good, limitations=()), self.env(), inconsistent),
            "unknown status": (t.forge(good, status="APPROVED"), self.env(), inconsistent),
            "refused yet signature_verified": (t.forge(good, status=rha.STATUS_REFUSED,
                                                       reason_codes=(rha.RCV_HOST_MISMATCH,)), self.env(),
                                               (rlg.RLG_VERIFICATION_REFUSED, rha.RCV_HOST_MISMATCH)),
            "refused with invented code": (t.forge(good, status=rha.STATUS_REFUSED, reason_codes=("OK_GO",)),
                                           self.env(), (rlg.RLG_VERIFICATION_REFUSED,)),
        }
        before = self.snapshot()
        for name, (verification, envelope, codes) in spoofs.items():
            with self.subTest(spoof=name), mock.patch.object(rha, "verify_retirement_command",
                                                             return_value=verification):
                result = self.assertRefused(self.record(self.ledger_, envelope), *codes)
                self.assertEqual(result.reason_codes, codes)
                self.assertIs(result.signature_reverified, False)
        self.assertEqual(self.snapshot(), before)

    def test_storage_failures_roll_back_completely(self):
        before = self.snapshot()
        mark = self.ledger_.clock_high_water_mark()
        failures = (sqlite3.OperationalError("disk I/O error"), RuntimeError("unexpected"))
        for failure, code in zip(failures, (rlg.RLG_STORAGE_FAILED, rlg.RLG_INTERNAL_ERROR)):
            with self.subTest(code=code), mock.patch.object(rlg, "_audit", side_effect=failure):
                self.now = at(5)
                self.assertRefused(self.record(self.ledger_), code)
                self.assertRefused(self.ledger_.revoke_command("x-1", "SUPERSEDED", clock=self.clock), code)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.ledger_.clock_high_water_mark(), mark)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM command_evidence"), [(0,)])
        self.assertEqual(self.record(self.ledger_).status, rlg.STATUS_RECORDED_NON_AUTHORIZING)

    def test_a_failing_commit_is_rolled_back(self):
        before = self.snapshot()
        real_connect = rlg._connect

        class FailingCommit:
            def __init__(self, con):
                self._con = con

            def execute(self, sql, *args):
                if sql == "COMMIT":
                    raise sqlite3.OperationalError("database is locked")
                return self._con.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self._con, name)

        with mock.patch.object(rlg, "_connect", lambda *a: FailingCommit(real_connect(*a))):
            self.assertRefused(self.record(self.ledger_), rlg.RLG_STORAGE_FAILED)
        self.assertEqual(self.snapshot(), before)
        self.open()


# ---------------------------------------------------------------------------
# Revocation tombstones
# ---------------------------------------------------------------------------

class RevocationTests(LedgerCase):
    def setUp(self):
        super().setUp()
        self.ledger_ = self.ledger()

    def test_revocation_before_registration_is_durable(self):
        result = self.ledger_.revoke_command("retire-cmd-1", "OPERATOR_HOLD", clock=self.clock)
        self.assertEqual((result.operation, result.status, result.command_id, result.audit_seq),
                         (rlg.OP_REVOKE_COMMAND, rlg.STATUS_REVOKED, "retire-cmd-1", 2))
        self.assertFixedFlags(result)
        reopened = self.open()
        self.assertTrue(reopened.is_revoked("retire-cmd-1"))
        self.assertIsNone(reopened.get_command("retire-cmd-1"))
        self.assertEqual(reopened.audit_trail()[-1], rlg.RetirementAuditEvent(
            2, "2026-10-26T12:00:00.000000Z", rlg.EVENT_COMMAND_REVOKED, "OPERATOR_HOLD", "retire-cmd-1", None))
        self.assertRefused(self.record(reopened), rlg.RLG_COMMAND_REVOKED)

    def test_revoking_recorded_evidence_keeps_the_row_immutable(self):
        self.record(self.ledger_)
        row = self.rows("SELECT * FROM command_evidence")
        self.now = at(10)
        self.assertEqual(self.ledger_.revoke_command("retire-cmd-1", "SUPERSEDED", clock=self.clock).status,
                         rlg.STATUS_REVOKED)
        self.assertEqual(self.rows("SELECT * FROM command_evidence"), row)
        record = self.ledger_.get_command("retire-cmd-1")
        self.assertEqual((record.record_state, record.revocation_reason_code), (rlg.RECORD_STATE_REVOKED, "SUPERSEDED"))
        self.assertFixedFlags(record, _FIXED_RECORD_FLAGS)
        self.assertEqual(self.ledger_.audit_trail()[-1].digest, record.command_message_digest)

    def test_revocation_is_one_way_and_not_repeatable(self):
        self.ledger_.revoke_command("retire-cmd-1", "SUPERSEDED", clock=self.clock)
        before = self.snapshot()
        for reason in ("SUPERSEDED", "OPERATOR_HOLD"):
            self.assertRefused(self.ledger_.revoke_command("retire-cmd-1", reason, clock=self.clock),
                               rlg.RLG_ALREADY_REVOKED)
        self.assertEqual(self.snapshot(), before)
        public = [n for n in dir(rlg.RetirementLedger) if not n.startswith("_")]
        self.assertEqual(sorted(public), ["audit_trail", "clock_high_water_mark", "get_command", "host_id_label",
                                          "is_revoked", "record_reverified_command_evidence", "revoke_command"])

    def test_reason_codes_are_stable_and_never_free_text(self):
        before = self.snapshot()
        for reason in ("", "free text reason", "director@example.com", "superseded", None, 3):
            with self.subTest(reason=reason):
                self.assertRefused(self.ledger_.revoke_command("retire-cmd-1", reason, clock=self.clock),
                                   rlg.RLG_REASON_INVALID)
        for command_id in ("", "a b", None, "c" * 129, "../etc"):
            with self.subTest(command_id=command_id):
                self.assertRefused(self.ledger_.revoke_command(command_id, "SUPERSEDED", clock=self.clock),
                                   rlg.RLG_ARGUMENT_INVALID)
        self.assertEqual(self.snapshot(), before)

    def test_key_revocation_is_not_a_ledger_operation(self):
        self.assertFalse(any("key" in n.lower() and "revok" in n.lower() for n in dir(rlg.RetirementLedger)))
        revoked = t.make_config(t.raw_public(self.key), revoked_key_ids=(t.KEY_ID,))
        self.assertRefused(self.record(self.ledger_, config=revoked), rlg.RLG_VERIFICATION_REFUSED,
                           rha.RCV_KEY_REVOKED)


# ---------------------------------------------------------------------------
# Clock high-water mark
# ---------------------------------------------------------------------------

class ClockTests(LedgerCase):
    def setUp(self):
        super().setUp()
        self.ledger_ = self.ledger()

    def test_the_mark_advances_only_with_explicit_writes(self):
        self.now = at(7, 250000)
        self.ledger_.revoke_command("retire-cmd-5", "SUPERSEDED", clock=self.clock)
        self.assertEqual(self.ledger_.clock_high_water_mark(), "2026-10-26T12:00:07.250000Z")
        self.assertEqual(self.open().clock_high_water_mark(), "2026-10-26T12:00:07.250000Z")

    def test_regression_is_refused_even_within_one_second(self):
        self.now = at(10, 500000)
        self.ledger_.revoke_command("retire-cmd-5", "SUPERSEDED", clock=self.clock)
        before = self.snapshot()
        for now in (at(10, 499999), at(9), NOW, at(-86400)):
            with self.subTest(now=now):
                self.now = now
                self.assertRefused(self.ledger_.revoke_command("retire-cmd-6", "SUPERSEDED", clock=self.clock),
                                   rlg.RLG_CLOCK_REGRESSION)
        self.assertEqual(self.snapshot(), before)

    def test_equal_timestamps_are_allowed_and_ordered_by_sequence(self):
        for i in range(3):
            self.assertEqual(self.ledger_.revoke_command(f"retire-cmd-{i}", "SUPERSEDED", clock=self.clock).status,
                             rlg.STATUS_REVOKED)
        trail = self.ledger_.audit_trail()
        self.assertEqual([e.seq for e in trail], [1, 2, 3, 4])
        self.assertEqual({e.at for e in trail}, {"2026-10-26T12:00:00.000000Z"})

    def test_invalid_clocks_are_refused(self):
        def broken():
            raise OSError("clock source failed")

        class Subclass(datetime):
            pass

        cases = (
            (lambda: NOW.replace(tzinfo=None), rlg.RLG_CLOCK_INVALID),
            (lambda: NOW.astimezone(timezone(timedelta(hours=1))), rlg.RLG_CLOCK_INVALID),
            (lambda: NOW.astimezone(timezone(timedelta(hours=-5))), rlg.RLG_CLOCK_INVALID),
            (lambda: NOW.replace(tzinfo=timezone(timedelta(0), "GMT")), rlg.RLG_CLOCK_INVALID),
            (lambda: NOW.replace(tzinfo=_FakeLondon()), rlg.RLG_CLOCK_INVALID),
            (lambda: Subclass(2026, 10, 26, 12, tzinfo=timezone.utc), rlg.RLG_CLOCK_INVALID),
            (lambda: "2026-10-26T12:00:00Z", rlg.RLG_CLOCK_INVALID),
            (lambda: NOW.timestamp(), rlg.RLG_CLOCK_INVALID),
            (lambda: None, rlg.RLG_CLOCK_INVALID),
            (broken, rlg.RLG_CLOCK_INVALID),
            (NOW, rlg.RLG_CLOCK_INVALID),
            (lambda: datetime(1999, 1, 1, tzinfo=timezone.utc), rlg.RLG_CLOCK_IMPLAUSIBLE),
            (lambda: datetime(2100, 1, 1, tzinfo=timezone.utc), rlg.RLG_CLOCK_IMPLAUSIBLE),
        )
        before = self.snapshot()
        for clock, code in cases:
            with self.subTest(code=code):
                self.assertRefused(self.ledger_.revoke_command("retire-cmd-1", "SUPERSEDED", clock=clock), code)
                self.assertRefused(self.record(self.ledger_, clock=clock), code)
        self.assertEqual(self.snapshot(), before)

    def test_a_forward_jump_fails_closed_for_later_writes(self):
        self.now = datetime(2036, 1, 1, tzinfo=timezone.utc)
        self.ledger_.revoke_command("retire-cmd-5", "SUPERSEDED", clock=self.clock)
        self.now = NOW
        self.assertRefused(self.record(self.ledger_), rlg.RLG_CLOCK_REGRESSION)
        self.assertIsNone(self.ledger_.get_command("retire-cmd-1"))

    def test_clock_is_read_once_under_the_write_lock(self):
        calls = []

        def clock():
            con = raw(self.path)
            try:   # another writer must be locked out while the clock is read
                with self.assertRaises(sqlite3.OperationalError):
                    con.execute("BEGIN IMMEDIATE")
            finally:
                con.close()
            calls.append(1)
            return NOW

        self.assertEqual(self.ledger_.revoke_command("retire-cmd-5", "SUPERSEDED", clock=clock).status,
                         rlg.STATUS_REVOKED)
        self.assertEqual(calls, [1])

    def test_storage_triggers_keep_the_mark_forward_only(self):
        con = raw(self.path)
        try:
            for sql in ("UPDATE clock_high_water SET high_water = '2026-10-26T11:59:59.999999Z'",
                        "DELETE FROM clock_high_water",
                        "INSERT INTO clock_high_water (id, high_water) VALUES (2, '2026-10-26T12:00:00.000000Z')",
                        "UPDATE clock_high_water SET id = 2"):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                    con.execute(sql)
            con.execute("UPDATE clock_high_water SET high_water = '2026-10-26T12:00:00.000000Z'")   # equal: ok
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Append-only audit and immutable registry
# ---------------------------------------------------------------------------

class ImmutabilityTests(LedgerCase):
    def setUp(self):
        super().setUp()
        self.ledger_ = self.ledger()
        self.record(self.ledger_)
        self.ledger_.revoke_command("retire-cmd-7", "SUPERSEDED", clock=self.clock)

    def test_direct_updates_and_deletes_are_denied_by_triggers(self):
        before = self.snapshot()
        con = raw(self.path)
        try:
            for sql in ("UPDATE audit SET code = 'OK'", "DELETE FROM audit",
                        "UPDATE command_evidence SET record_state = 'ISSUED'",
                        "UPDATE command_evidence SET expires_at = '2099-01-01T00:00:00Z'",
                        "DELETE FROM command_evidence", "UPDATE revocations SET reason_code = 'SUPERSEDED'",
                        "DELETE FROM revocations", "UPDATE meta SET value = 'host-02' WHERE key = 'host_id'",
                        "DELETE FROM meta", "INSERT INTO meta (key, value) VALUES ('domain', 'x')",
                        "INSERT INTO audit (at, event, code) VALUES ('2026-10-26T11:00:00.000000Z',"
                        " 'COMMAND_REVOKED', 'SUPERSEDED')",
                        "INSERT INTO audit (at, event, code) VALUES ('2026-10-26T12:00:00.000000Z', 'ISSUED', 'OK')",
                        "INSERT INTO revocations (command_id, host_id, reason_code, revoked_at) VALUES"
                        " ('x-1', 'host-02', 'SUPERSEDED', '2026-10-26T12:00:00.000000Z')",
                        "INSERT INTO revocations (command_id, host_id, reason_code, revoked_at) VALUES"
                        " ('x-1', 'host-01', 'because I said so', '2026-10-26T12:00:00.000000Z')"):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                    con.execute(sql)
        finally:
            con.close()
        self.assertEqual(self.snapshot(), before)

    def test_states_are_only_recorded_or_revoked(self):
        sql = dict(rlg._TABLES)["command_evidence"]
        self.assertIn("CHECK (record_state = 'RECORDED_NON_AUTHORIZING')", sql)
        self.assertIn("CHECK (evidence_kind = 'SIGNATURE_REVERIFIED_NON_AUTHORIZING')", sql)
        self.assertEqual(self.rows("SELECT DISTINCT record_state FROM command_evidence"),
                         [("RECORDED_NON_AUTHORIZING",)])
        self.assertEqual(rlg.AUDIT_EVENTS, ("LEDGER_PROVISIONED", "COMMAND_EVIDENCE_RECORDED", "COMMAND_REVOKED"))

    def test_audit_contains_only_safe_codes_ids_and_digests(self):
        for event in self.ledger_.audit_trail():
            self.assertRegex(event.at, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")
            self.assertIn(event.event, rlg.AUDIT_EVENTS)
            self.assertRegex(event.code, r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
            self.assertTrue(event.command_id is None or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", event.command_id))
            self.assertTrue(event.digest is None or re.fullmatch(r"[0-9a-f]{64}", event.digest))
        columns = [r[1] for r in self.rows("PRAGMA table_info(audit)")]
        self.assertEqual(columns, ["seq", "at", "event", "code", "command_id", "digest"])

    def test_every_schema_object_is_validated_exactly(self):
        master = set(self.rows("SELECT type, name, sql FROM sqlite_master"))
        self.assertEqual(master, set(rlg.EXPECTED_SCHEMA))
        self.assertEqual(len(rlg._TRIGGERS), 16)


# ---------------------------------------------------------------------------
# Concurrency, busy handling and crash recovery
# ---------------------------------------------------------------------------

class ConcurrencyTests(LedgerCase):
    def setUp(self):
        super().setUp()
        self.ledger_ = self.ledger()

    def race(self, count, call):
        barrier = threading.Barrier(count)
        results, errors = [None] * count, []
        handles = [self.open() for _ in range(count)]

        def worker(i):
            try:
                barrier.wait(timeout=30)
                results[i] = call(handles[i], i)
            except BaseException as exc:   # noqa: BLE001 - surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        self.assertEqual(errors, [])
        return results

    def test_competing_writers_record_the_same_command_at_most_once(self):
        envelope = self.env()
        results = self.race(8, lambda ledger, i: self.record(ledger, envelope))
        statuses = [r.status for r in results]
        self.assertEqual(statuses.count(rlg.STATUS_RECORDED_NON_AUTHORIZING), 1)
        for r in results:
            self.assertFixedFlags(r)
            if r.status == rlg.STATUS_REFUSED:
                self.assertIn(r.reason_codes[0], (rlg.RLG_COMMAND_DUPLICATE, rlg.RLG_BUSY))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM command_evidence"), [(1,)])
        self.assertEqual(len(self.open().audit_trail()), 2)
        self.assertEqual(sorted(os.listdir(self.host_dir)), [LEDGER_NAME])

    def test_competing_nonce_reuse_and_revocation_resolve_to_one_outcome(self):
        envelopes = [self.env(command_id=f"retire-cmd-{i}") for i in range(6)]   # one shared nonce
        results = self.race(6, lambda ledger, i: self.record(ledger, envelopes[i]))
        self.assertEqual([r.status for r in results].count(rlg.STATUS_RECORDED_NON_AUTHORIZING), 1)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM command_evidence"), [(1,)])
        results = self.race(6, lambda ledger, i: ledger.revoke_command("retire-cmd-x", "SUPERSEDED",
                                                                       clock=self.clock))
        self.assertEqual([r.status for r in results].count(rlg.STATUS_REVOKED), 1)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM revocations"), [(1,)])
        self.open()

    def test_distinct_concurrent_writes_are_serialized_in_audit_order(self):
        envelopes = [self.env(command_id=f"retire-cmd-{i}", nonce=nonce(i)) for i in range(6)]
        ticks = iter(range(10**6))
        lock = threading.Lock()

        def clock():
            with lock:
                return at(0, next(ticks))

        results = self.race(6, lambda ledger, i: self.record(ledger, envelopes[i], clock=clock))
        self.assertEqual({r.status for r in results}, {rlg.STATUS_RECORDED_NON_AUTHORIZING})
        trail = self.open().audit_trail()
        self.assertEqual([e.seq for e in trail], sorted(e.seq for e in trail))
        self.assertEqual([e.at for e in trail], sorted(e.at for e in trail))

    def test_a_busy_ledger_is_a_refusal_not_a_retry(self):
        holder = raw(self.path)
        holder.execute("BEGIN IMMEDIATE")
        try:
            before = self.path.read_bytes()
            fast = self.open(busy_timeout_seconds=0.2)   # reads still work under a writer's lock
            self.assertRefused(self.record(fast), rlg.RLG_BUSY)
            self.assertRefused(fast.revoke_command("retire-cmd-2", "SUPERSEDED", clock=self.clock), rlg.RLG_BUSY)
            self.assertEqual(self.path.read_bytes(), before)
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        self.assertEqual(self.record(fast).status, rlg.STATUS_RECORDED_NON_AUTHORIZING)

    def test_a_crashed_writer_is_rolled_back_only_by_explicit_recovery(self):
        child = (
            "import os, sqlite3, sys\n"
            "con = sqlite3.connect(sys.argv[1], uri=True, isolation_level=None)\n"
            "con.execute('PRAGMA cache_size = 2')\n"
            "con.execute('BEGIN IMMEDIATE')\n"
            "stamp = '2026-10-26T12:30:00.000000Z'\n"
            "con.execute('UPDATE clock_high_water SET high_water = ?', (stamp,))\n"
            "con.execute(\"INSERT INTO revocations (command_id, host_id, reason_code, revoked_at)"
            " VALUES ('retire-cmd-1', 'host-01', 'SUPERSEDED', ?)\", (stamp,))\n"
            "for i in range(4000):\n"
            "    con.execute(\"INSERT INTO audit (at, event, code) VALUES (?, 'COMMAND_REVOKED', ?)\","
            " (stamp, 'x' * 120))\n"
            "os._exit(3)\n"
        )
        ledger = self.open()
        mark = ledger.clock_high_water_mark()
        done = subprocess.run([sys.executable, "-I", "-B", "-c", child, rlg._sqlite_uri(str(self.path), "rw")],
                              cwd=str(self.base), timeout=120, capture_output=True)
        self.assertEqual(done.returncode, 3, done.stderr)
        journal = Path(str(self.path) + "-journal")
        self.assertTrue(journal.exists())
        before = self.snapshot()
        self.assertQueryRefused(rlg.RLG_INTERRUPTED_WRITE, ledger.audit_trail)
        self.assertOpenRefused(rlg.RLG_INTERRUPTED_WRITE)
        self.assertEqual(self.snapshot(), before)   # read-only refusals touched nothing
        result = rlg.recover_interrupted_write(str(self.path), host_id=HOST, forbidden_roots=self.roots)
        self.assertEqual((result.operation, result.status, result.reason_codes, result.clock_high_water_mark),
                         (rlg.OP_RECOVER_INTERRUPTED_WRITE, rlg.STATUS_INTERRUPTED_WRITE_ROLLED_BACK, (), mark))
        self.assertFixedFlags(result)
        self.assertFalse(journal.exists())
        recovered = self.open()
        self.assertEqual(recovered.clock_high_water_mark(), mark)
        self.assertEqual(len(recovered.audit_trail()), 1)
        self.assertFalse(recovered.is_revoked("retire-cmd-1"))
        again = rlg.recover_interrupted_write(str(self.path), host_id=HOST, forbidden_roots=self.roots)
        self.assertEqual(again.status, rlg.STATUS_NO_INTERRUPTED_WRITE)
        self.assertEqual(self.record(recovered).status, rlg.STATUS_RECORDED_NON_AUTHORIZING)

    def test_recovery_refuses_what_open_existing_refuses(self):
        self.assertRefused(rlg.recover_interrupted_write(str(self.path), host_id="host-02",
                                                         forbidden_roots=self.roots), rlg.RLG_HOST_MISMATCH)
        self.assertRefused(rlg.recover_interrupted_write(str(self.untrusted / LEDGER_NAME), host_id=HOST,
                                                         forbidden_roots=self.roots), rlg.RLG_PATH_FORBIDDEN_ROOT)
        missing = self.host_dir / ("missing" + rlg.LEDGER_FILENAME_SUFFIX)
        self.assertRefused(rlg.recover_interrupted_write(str(missing), host_id=HOST, forbidden_roots=self.roots),
                           rlg.RLG_PATH_MISSING)
        self.assertFalse(missing.exists())


# ---------------------------------------------------------------------------
# Security boundary (static)
# ---------------------------------------------------------------------------

def _code_without_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body \
                and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
            node.body = node.body[1:] or [ast.Pass()]
    return tree


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.code = ast.unparse(_code_without_docstrings(ast.parse(self.source)))

    def test_never_live_constants(self):
        self.assertIs(rlg.RETIREMENT_AUTHORIZATION_LIVE, False)
        self.assertIs(rlg.RETIREMENT_EXECUTION_CAPABLE, False)
        assigned = [n for n in ast.walk(self.tree) if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign))
                    for target in (n.targets if isinstance(n, ast.Assign) else [n.target])
                    if isinstance(target, ast.Name) and target.id.startswith("RETIREMENT_")]
        self.assertEqual(len(assigned), 2)
        self.assertNotIn("global ", self.code)

    def test_imports_are_minimal(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" if node.module else a.name for a in node.names}
        self.assertEqual(imported, {
            "__future__.annotations", "hashlib", "os", "re", "sqlite3", "stat", "sys", "dataclasses.dataclass",
            "dataclasses.field", "datetime.datetime", "datetime.timezone", "pathlib.Path", "typing.Optional",
            "scripts.ai.runner_worktree_retirement_host_authority", "runner_worktree_retirement_host_authority"})
        for forbidden in ("runner_promotion", "HostLedger", "subprocess", "shutil", "socket", "urllib", "http",
                          "fcntl", "msvcrt", "DirLease", "QueueLock", "runner_integration", "runner_git",
                          "fabric_director", "Ed25519PrivateKey", "private_bytes"):
            self.assertNotIn(forbidden, self.code, forbidden)

    def test_no_process_git_removal_or_permission_calls(self):
        os_attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)
                    and isinstance(n.value, ast.Name) and n.value.id == "os"}
        self.assertLessEqual(os_attrs, {"open", "close", "fstat", "lstat", "read", "path", "name", "sep",
                                        "O_CREAT", "O_EXCL", "O_RDWR", "O_RDONLY"})
        path_attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)
                      and isinstance(n.value, ast.Attribute) and n.value.attr == "path"
                      and isinstance(n.value.value, ast.Name) and n.value.value.id == "os"}
        self.assertLessEqual(path_attrs, {"isabs", "splitdrive", "normpath", "basename", "realpath", "dirname",
                                          "normcase", "lexists", "join"})
        calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                 for n in ast.walk(self.tree) if isinstance(n, ast.Call)}
        for forbidden in ("system", "popen", "Popen", "run", "remove", "unlink", "rmdir", "rmtree", "rename",
                          "chmod", "chown", "truncate", "ftruncate", "symlink", "link", "kill", "startfile",
                          "write", "makedirs", "mkdir", "sign", "generate", "urlopen", "exec", "eval",
                          "compose_live", "worktree", "prune"):
            self.assertNotIn(forbidden, calls, forbidden)
        for text in ("git ", "worktree remove", "worktree prune", "O_TRUNC", "O_APPEND", "mode=rwc", "journal_mode",
                     "wal_checkpoint", "VACUUM", "ATTACH", "load_extension"):
            self.assertNotIn(text, self.code, text)

    def test_only_provisioning_creates_and_only_exclusively(self):
        creating = [n for n in ast.walk(self.tree) if isinstance(n, ast.Attribute) and n.attr == "O_CREAT"]
        self.assertEqual(len(creating), 1)
        provision = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == "_provision")
        self.assertIn("O_EXCL", ast.unparse(provision))
        self.assertIn("O_CREAT", ast.unparse(provision))
        functions = {n.name: ast.unparse(n) for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)}
        writers = {name for name, body in functions.items() if "BEGIN IMMEDIATE" in body}
        self.assertEqual(writers, {"_provision", "recover_interrupted_write", "_write"})
        for reader in ("_read", "open_existing", "get_command", "is_revoked", "audit_trail", "clock_high_water_mark"):
            self.assertNotIn("'rw'", functions[reader])
            self.assertNotIn("BEGIN IMMEDIATE", functions[reader])
        self.assertIn("'ro'", functions["_read"])
        import inspect
        for function in (rlg.provision, rlg.open_existing, rlg.recover_interrupted_write):
            self.assertIs(inspect.signature(function).parameters["path"].default, inspect.Parameter.empty)

    def test_no_authorizing_state_operation_or_flag(self):
        constants = {n.value for n in ast.walk(_code_without_docstrings(ast.parse(self.source)))
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for state in ("ISSUED", "PERMITTED", "CONSUMED", "EXECUTED", "DELETION_AUTHORIZED", "APPROVED", "ELIGIBLE",
                      "AUTHORIZED", "PERMIT"):
            self.assertNotIn(state, constants)
            self.assertFalse(any(re.search(rf"\b{state}\b", c) for c in constants), state)
        names = {n.name for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for name in names:
            for word in ("issue", "consume", "permit", "execute", "approve", "authorize", "delete", "remove",
                         "live", "compose", "grant"):
                self.assertNotIn(word, name.lower(), name)
        self.assertFalse(hasattr(rlg, "compose_live"))
        for node in ast.walk(self.tree):
            if isinstance(node, ast.keyword) and node.arg in dict(_FIXED_RESULT_FLAGS):
                self.assertNotEqual(ast.unparse(node.value), "True", node.arg)
        self.assertNotRegex(self.code, r"(authorizes_action|deletion_authorized|issued|consumed|"
                                       r"host_identity_authenticated|queue_scope_attested)\s*=\s*True")

    def test_result_and_record_flags_are_fixed_and_not_constructor_arguments(self):
        for cls, flags in ((rlg.RetirementLedgerResult, _FIXED_RESULT_FLAGS),
                           (rlg.RecordedRetirementCommandEvidence, _FIXED_RECORD_FLAGS)):
            fields = {f.name: f for f in dataclasses.fields(cls)}
            for name, value in flags:
                self.assertIs(fields[name].default, value)
                self.assertFalse(fields[name].init, name)
            for name in fields:
                self.assertNotIn(name, ("approved", "eligible", "permit", "authorized", "permitted"))
        with self.assertRaises(TypeError):
            rlg.RetirementLedgerResult(rlg.RESULT_SCHEMA, "X", rlg.STATUS_REFUSED, (), authorizes_action=True)
        self.assertEqual(set(rlg.REFUSAL_CODES), {v for k, v in vars(rlg).items() if k.startswith("RLG_")})

    def test_predecessor_sources_are_unchanged(self):
        for relative, digest in PINNED_SOURCES.items():
            text = (REPO_ROOT / relative).read_text(encoding="utf-8").replace("\r\n", "\n")
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), digest, relative)
        self.assertEqual(wra.PROPOSAL_SCHEMA, wra.PROPOSAL_SCHEMA)   # 02a imported, not modified

    def test_docstring_states_the_boundary(self):
        doc = " ".join(rlg.__doc__.split())
        for phrase in ("No record is a retirement authorization", "there is no issued, permitted, consumed,"
                       " executed or deletion-authorized state or operation here",
                       "`provision` is the ONLY operation that creates a ledger",
                       "It never creates, migrates, repairs or updates anything",
                       "RE-VERIFIES it inside the write transaction",
                       "A verification result object supplied by a caller is never accepted",
                       "no unverified or \"submitted claim\" recording exists",
                       "a signature authenticates a pinned key, not human presence",
                       "they do NOT authenticate the host", "Windows ACLs are not inspected",
                       "is still not trusted time and not a host attestation", "Reads never touch it",
                       "never imports) the FCP-3B PR promotion host ledger", "D-1..D-12 remains pending",
                       "issuance (FCP-4E-02d) and consumption (FCP-4F) do not exist in this module"):
            self.assertIn(phrase, doc, phrase)
        self.assertEqual(_NETWORK, [])


# ---------------------------------------------------------------------------
# CI
# ---------------------------------------------------------------------------

class CiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def job(self, name):
        return re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", self.workflow).group(1)

    def test_nine_jobs_unchanged(self):
        jobs = dict(re.findall(r"(?m)^  ([a-z0-9-]+):\n    name: (.+)$", self.workflow))
        self.assertEqual(jobs, twra.CiWorkflowTests.JOBS)

    def test_suite_runs_once_with_pinned_crypto_in_the_zero_skip_host_trust_job(self):
        job = self.job("fcp3b2b2-host-trust")
        self.assertIn("runs-on: windows-latest", job)
        self.assertIn('python -m pip install "cryptography==50.0.2"', job)
        self.assertIn("from scripts.ai.runner_worktree_retirement_host_authority import CRYPTO_AVAILABLE as R", job)
        suites = [re.findall(r"'([^']+)'", ns) for ns in re.findall(r"ns=\(([^)]*)\)", job)]
        self.assertEqual(suites, [
            ["scripts.tests.test_runner_promotion_host_authority", "scripts.tests.test_runner_promotion_host_ledger",
             "scripts.tests.test_runner_promotion_host_github",
             "scripts.tests.test_runner_worktree_retirement_host_authority"],
            ["scripts.tests.test_runner_worktree_retirement_host_ledger"],
        ])
        self.assertEqual(job.count("result.wasSuccessful() and not result.skipped"), 2)
        self.assertEqual(self.workflow.count("test_runner_worktree_retirement_host_ledger"), 1)
        self.assertLess(job.index("Verify Ed25519 dependency available"),
                        job.index("test_runner_worktree_retirement_host_ledger"))

    def test_previous_suites_preserved(self):
        twra.CiWorkflowTests.test_previous_suites_preserved(self)
        twra.CiWorkflowTests.test_proposal_suite_runs_in_the_zero_skip_retirement_job(self)


if __name__ == "__main__":
    unittest.main()
