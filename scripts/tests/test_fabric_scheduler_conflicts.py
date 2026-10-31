"""FCP-9B-01: Worktree isolation and shared-resource conflict analysis.
Offline, synthetic, never-resolved paths only."""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import json
import os
import socket
import subprocess
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.ai import fabric_scheduler_conflicts as cf
from scripts.ai import fabric_scheduler_contract as sc

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_scheduler_conflicts.py"
TEST_PATH = Path(__file__).resolve()

ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "lock_acquired", "lease_acquired")
ROOT = "C:\\Repo"
WT1 = "C:\\Repo\\wt1"
WT2 = "C:\\Repo\\wt2"
NO_LINK = cf.LINK_NONE


def wk(worker_id, mode="write", worktree=WT1, link=NO_LINK, claims=()):
    return cf.WorkerClaims(worker_id=worker_id, mode=mode, worktree=worktree, worktree_link_state=link,
                           claims=claims)


def path(p, access="READ", link=NO_LINK):
    return cf.PathClaim(path=p, access=access, link_state=link)


def source(source_id, access="READ"):
    return cf.SourceClaim(source_id=source_id, access=access)


def req(*workers, roots=(ROOT,), dag_id="dag-1", **kw):
    return cf.ConflictRequest(dag_id=dag_id, allowed_roots=roots, workers=workers, **kw)


def analyze(*workers, **kw):
    return cf.analyze_conflicts(req(*workers, **kw))


def refused_with(test, graph, *reasons):
    test.assertEqual(graph.outcome, cf.REFUSED)
    for reason in reasons:
        test.assertIn(reason, graph.request_reasons)
    test.assertEqual((graph.nodes, graph.edges, graph.dag_id, graph.request_fingerprint), ((), (), None, None))
    return graph


def unknown_with(test, graph, worker_id, *reasons):
    node = graph.node_of(worker_id)
    test.assertEqual(node.status, cf.UNKNOWN)
    for reason in reasons:
        test.assertIn(reason, node.reasons)
    test.assertEqual(graph.outcome, cf.UNKNOWN)
    return node


def reasons_between(graph, a, b):
    edge = graph.edge_between(a, b)
    return () if edge is None else edge.reasons


# ---------------------------------------------------------------------------
# Positive / negative concurrency scenarios
# ---------------------------------------------------------------------------

class WorktreeScenarioTests(unittest.TestCase):
    def test_independent_worktrees_writers_are_compatible(self):
        graph = analyze(wk("a", worktree=WT1), wk("b", worktree=WT2))
        self.assertEqual(graph.outcome, cf.COMPATIBLE)
        self.assertEqual(graph.edges, ())
        self.assertTrue(graph.compatible("a", "b"))
        self.assertEqual([n.status for n in graph.nodes], [cf.IDENTIFIED, cf.IDENTIFIED])

    def test_write_write_same_worktree_conflicts(self):
        graph = analyze(wk("a"), wk("b"))
        self.assertEqual(graph.outcome, cf.CONFLICTS)
        self.assertEqual(reasons_between(graph, "b", "a"), (cf.WORKTREE_WRITE_WRITE,))
        self.assertFalse(graph.compatible("a", "b"))

    def test_read_write_same_worktree_conflicts_in_both_orders(self):
        for workers in ((wk("a", "read-only"), wk("b")), (wk("a"), wk("b", "read-only"))):
            graph = analyze(*workers)
            self.assertEqual(reasons_between(graph, "a", "b"), (cf.WORKTREE_READ_WRITE,))

    def test_read_read_same_worktree_is_compatible(self):
        graph = analyze(wk("a", "read-only"), wk("b", "read-only"), wk("c", "read-only"))
        self.assertEqual(graph.outcome, cf.COMPATIBLE)
        self.assertTrue(graph.compatible("a", "c"))

    def test_nested_worktree_with_a_writer_conflicts_but_nested_readers_do_not(self):
        nested = WT1 + "\\sub\\deeper"
        graph = analyze(wk("a", worktree=WT1), wk("b", "read-only", worktree=nested))
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.WORKTREE_NESTED,))
        graph = analyze(wk("a", worktree=nested), wk("b", worktree=ROOT))
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.WORKTREE_NESTED,))
        graph = analyze(wk("a", "read-only", worktree=WT1), wk("b", "read-only", worktree=nested))
        self.assertEqual(graph.outcome, cf.COMPATIBLE)

    def test_sibling_sharing_a_text_prefix_is_not_nested(self):
        graph = analyze(wk("a", worktree=WT1), wk("b", worktree=WT1 + "0"), wk("c", worktree=WT1 + "-x"))
        self.assertEqual(graph.outcome, cf.COMPATIBLE)

    def test_equivalent_spellings_are_the_same_worktree_and_flag_the_alias(self):
        for alias in ("c:/repo/WT1", "C:\\Repo\\wt1\\", "C:\\\\Repo\\.\\wt1", "C:/Repo//wt1/.", "c:\\REPO\\Wt1"):
            graph = analyze(wk("a", worktree=WT1), wk("b", worktree=alias))
            self.assertEqual(reasons_between(graph, "a", "b"), (cf.WORKTREE_WRITE_WRITE, cf.ALIAS_DETECTED), alias)
        graph = analyze(wk("a"), wk("b"))
        self.assertNotIn(cf.ALIAS_DETECTED, reasons_between(graph, "a", "b"))

    def test_posix_roots_are_case_sensitive_and_still_alias_separators(self):
        roots = ("/srv/repo",)
        graph = analyze(wk("a", worktree="/srv/repo/wt"), wk("b", worktree="/srv/repo/WT"), roots=roots)
        self.assertEqual(graph.outcome, cf.COMPATIBLE)
        graph = analyze(wk("a", worktree="/srv/repo/wt"), wk("b", worktree="/srv/repo//./wt/"), roots=roots)
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.WORKTREE_WRITE_WRITE, cf.ALIAS_DETECTED))


class CrossWorktreeAndSourceTests(unittest.TestCase):
    def test_cross_worktree_write_into_a_reader_worktree_conflicts(self):
        graph = analyze(wk("a", worktree=WT1, claims=(path(WT2 + "\\out.txt", "WRITE"),)),
                        wk("b", "read-only", worktree=WT2))
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.PATH_OVERLAP_READ_WRITE,))

    def test_cross_worktree_write_into_a_writer_worktree_conflicts(self):
        graph = analyze(wk("a", worktree=WT1, claims=(path(WT2 + "\\out.txt", "WRITE"),)), wk("b", worktree=WT2))
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.PATH_OVERLAP_WRITE_WRITE,))

    def test_cross_worktree_read_of_a_writer_worktree_conflicts(self):
        graph = analyze(wk("a", "read-only", worktree=WT1, claims=(path(WT2 + "\\docs"),)), wk("b", worktree=WT2))
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.PATH_OVERLAP_READ_WRITE,))

    def test_readers_without_writer_share_paths_and_sources(self):
        shared = (path(ROOT + "\\shared"), path(ROOT + "\\shared\\x.json"), source("factory-ledger"))
        graph = analyze(wk("a", worktree=WT1, claims=shared), wk("b", worktree=WT2, claims=shared),
                        wk("c", "read-only", worktree=ROOT + "\\ro", claims=shared))
        self.assertEqual(graph.outcome, cf.COMPATIBLE)

    def test_two_writers_on_one_source_of_truth_conflict_even_across_worktrees(self):
        graph = analyze(wk("a", worktree=WT1, claims=(source("factory-ledger", "WRITE"),)),
                        wk("b", worktree=WT2, claims=(source("Factory-Ledger", "WRITE"),)))
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.SOURCE_OF_TRUTH_WRITE_WRITE, cf.ALIAS_DETECTED))

    def test_reader_and_writer_on_one_source_conflict_distinct_sources_do_not(self):
        graph = analyze(wk("a", worktree=WT1, claims=(source("ledger", "WRITE"),)),
                        wk("b", "read-only", worktree=WT2, claims=(source("ledger"),)),
                        wk("c", worktree=ROOT + "\\wt3", claims=(source("other-ledger", "WRITE"),)))
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.SOURCE_OF_TRUTH_READ_WRITE,))
        self.assertTrue(graph.compatible("a", "c"))
        self.assertTrue(graph.compatible("b", "c"))

    def test_source_ids_and_paths_never_collide(self):
        graph = analyze(wk("a", worktree=WT1, claims=(source("wt2", "WRITE"),)), wk("b", worktree=WT2))
        self.assertEqual(graph.outcome, cf.COMPATIBLE)

    def test_multiple_codes_on_one_edge_are_ordered(self):
        graph = analyze(wk("a", claims=(source("s", "WRITE"), path(WT2, "WRITE"))),
                        wk("b", claims=(source("s", "WRITE"),)), wk("c", worktree=WT2))
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.WORKTREE_WRITE_WRITE, cf.SOURCE_OF_TRUTH_WRITE_WRITE))
        self.assertEqual(reasons_between(graph, "a", "c"), (cf.PATH_OVERLAP_WRITE_WRITE,))
        self.assertTrue(graph.compatible("b", "c"))


# ---------------------------------------------------------------------------
# Fail-closed identification
# ---------------------------------------------------------------------------

class FailClosedTests(unittest.TestCase):
    def test_unidentified_worktree_is_incompatible_with_everyone(self):
        graph = analyze(wk("a", worktree=None), wk("b", worktree=WT2), wk("c", "read-only", worktree=ROOT + "\\x"))
        unknown_with(self, graph, "a", cf.RESOURCE_UNIDENTIFIED)
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.RESOURCE_UNIDENTIFIED_PEER,))
        self.assertEqual(reasons_between(graph, "a", "c"), (cf.RESOURCE_UNIDENTIFIED_PEER,))
        self.assertIsNone(graph.edge_between("b", "c"))
        self.assertFalse(graph.compatible("a", "b"))
        self.assertTrue(graph.compatible("b", "c"))

    def test_unknown_claim_types_and_missing_source_are_unidentified(self):
        for claim in ({"path": WT2, "access": "READ"}, ("source", "x"), None, source(None)):
            graph = analyze(wk("a", claims=(claim,)), wk("b", worktree=WT2))
            unknown_with(self, graph, "a", cf.RESOURCE_UNIDENTIFIED)
            self.assertFalse(graph.compatible("a", "b"))
        unknown_with(self, analyze(wk("a", claims=(path(None),))), "a", cf.RESOURCE_UNIDENTIFIED)

    def test_link_state_unknown_or_link_fails_closed(self):
        unknown_with(self, analyze(wk("a", link=cf.LINK_UNKNOWN)), "a", cf.PATH_LINK_UNVERIFIED)
        unknown_with(self, analyze(wk("a", link=cf.LINK_PRESENT)), "a", cf.PATH_LINK_AMBIGUOUS)
        unknown_with(self, analyze(wk("a", claims=(path(WT2, link=cf.LINK_PRESENT),))), "a", cf.PATH_LINK_AMBIGUOUS)
        # The default for both worktree and claims is UNKNOWN: fail closed.
        graph = cf.analyze_conflicts(req(cf.WorkerClaims("a", "write", WT1, claims=(cf.PathClaim(WT2, "READ"),))))
        unknown_with(self, graph, "a", cf.PATH_LINK_UNVERIFIED)

    def test_traversal_is_refused_never_collapsed(self):
        for p in (WT1 + "\\..\\wt2", ROOT + "\\..\\..\\Windows", "/srv/repo/../etc"):
            self.assertEqual(cf.target_key(p), ((cf.PATH_TRAVERSAL,), None), p)
        unknown_with(self, analyze(wk("a", worktree=WT1 + "\\..\\wt1")), "a", cf.PATH_TRAVERSAL)

    def test_indeterminate_paths(self):
        for p in ("", "wt1", ".\\wt1", "C:wt1", "C:", "\\Repo\\wt1", "C:\\Repo\\w*", "C:\\Repo\\a?b",
                  "C:\\Repo\\a\x00b", "C:\\Repo\\a\nb", "C:\\" + "a" * cf.MAX_PATH_CHARS):
            self.assertEqual(cf.target_key(p)[1], None, repr(p))
            self.assertIn(cf.PATH_INDETERMINATE, cf.target_key(p)[0], repr(p))

    def test_unsupported_forms(self):
        for p in ("\\\\server\\share\\wt", "\\\\?\\C:\\Repo\\wt1", "\\\\.\\C:\\Repo", "//server/share",
                  "C:\\Repo\\CON", "C:\\Repo\\nul.txt", "C:\\Repo\\com1\\x", "C:\\Repo\\LPT9."):
            self.assertIn(cf.PATH_UNSUPPORTED_FORM, cf.target_key(p)[0], p)
            self.assertIsNone(cf.target_key(p)[1])

    def test_ambiguous_aliases(self):
        for p in ("C:\\PROGRA~1\\wt", "C:\\Repo\\wt1.", "C:\\Repo\\wt1 ", "C:\\Repo\\wt1:stream",
                  "C:\\Repo\\wt-\u00f1", "/srv/repo\\wt", "/srv/re\u0301po"):
            self.assertIn(cf.PATH_AMBIGUOUS_ALIAS, cf.target_key(p)[0], p)
        unknown_with(self, analyze(wk("a", worktree="C:\\Repo\\WT1~1")), "a", cf.PATH_AMBIGUOUS_ALIAS)

    def test_flavor_mismatch_and_outside_roots(self):
        unknown_with(self, analyze(wk("a", worktree="/c/Repo/wt1")), "a", cf.PATH_FLAVOR_MISMATCH)
        for outside in ("C:\\Other\\wt", "C:\\RepoEvil\\wt", "D:\\Repo\\wt1", "C:\\"):
            unknown_with(self, analyze(wk("a", worktree=outside)), "a", cf.PATH_OUTSIDE_ALLOWED_ROOTS)
        unknown_with(self, analyze(wk("a", claims=(path("C:\\Windows\\x"),))), "a", cf.PATH_OUTSIDE_ALLOWED_ROOTS)
        graph = analyze(wk("a", worktree="D:\\Work\\a"), roots=(ROOT, "d:/work"))
        self.assertEqual(graph.outcome, cf.COMPATIBLE)

    def test_lone_unknown_worker_and_all_unknown_reasons_are_collected(self):
        graph = analyze(wk("a", worktree=None, link=cf.LINK_PRESENT,
                           claims=(path("rel"), path("C:\\Other"), source(None))))
        node = unknown_with(self, graph, "a")
        self.assertEqual(node.reasons, (cf.RESOURCE_UNIDENTIFIED, cf.PATH_INDETERMINATE,
                                        cf.PATH_OUTSIDE_ALLOWED_ROOTS))
        self.assertEqual(graph.edges, ())
        self.assertFalse(graph.compatible("a", "a"))
        self.assertFalse(graph.compatible("a", "nobody"))

    def test_unknown_worker_still_reports_its_identified_conflicts(self):
        graph = analyze(wk("a", claims=(source(None),)), wk("b"))
        self.assertEqual(reasons_between(graph, "a", "b"), (cf.WORKTREE_WRITE_WRITE, cf.RESOURCE_UNIDENTIFIED_PEER))


# ---------------------------------------------------------------------------
# Request refusals, typing and bounds
# ---------------------------------------------------------------------------

class RefusalTests(unittest.TestCase):
    def test_untyped_requests(self):
        for bad in (None, {}, "req", sc.ScheduleRequest("d", 1, (), "2026-10-30T10:00:00Z")):
            refused_with(self, cf.analyze_conflicts(bad), cf.REQUEST_NOT_TYPED)

    def test_schema_and_dag_id(self):
        for version in (2, True, "1", 1.0):
            refused_with(self, analyze(wk("a"), schema_version=version), cf.SCHEMA_VERSION_UNSUPPORTED)
        for dag_id in ("", "a/b", "..", "C:x", None, 5, "x" * 65):
            refused_with(self, analyze(wk("a"), dag_id=dag_id), cf.DAG_ID_INVALID)

    def test_allowed_roots(self):
        for roots in ([ROOT], (), (ROOT,) * 17, (ROOT, 5)):
            refused_with(self, analyze(wk("a"), roots=roots), cf.ALLOWED_ROOTS_MALFORMED)
        for root in ("Repo", "C:\\Repo\\..", "\\\\srv\\share", "C:\\PROGRA~1"):
            refused_with(self, analyze(wk("a"), roots=(root,)), cf.ALLOWED_ROOT_INVALID)
        refused_with(self, analyze(wk("a"), roots=(ROOT, "/srv/repo")), cf.ALLOWED_ROOTS_MIXED_FLAVOR)

    def test_workers_collection(self):
        refused_with(self, cf.analyze_conflicts(cf.ConflictRequest("d", (ROOT,), [wk("a")])), cf.WORKERS_NOT_TUPLE)
        refused_with(self, cf.analyze_conflicts(cf.ConflictRequest("d", (ROOT,), ())), cf.WORKERS_EMPTY)
        many = tuple(wk(f"w{i}", worktree=f"{ROOT}\\w{i}") for i in range(cf.MAX_WORKERS + 1))
        refused_with(self, analyze(*many), cf.WORKERS_TOO_MANY)
        refused_with(self, analyze(wk("a"), {"worker_id": "b"}), cf.WORKER_NOT_TYPED)
        refused_with(self, analyze(wk("a"), wk("a", worktree=WT2)), cf.WORKER_ID_DUPLICATE)
        refused_with(self, analyze(wk("a/b")), cf.WORKER_ID_INVALID)

    def test_worker_fields(self):
        refused_with(self, analyze(wk("a", mode="WRITE")), cf.MODE_UNKNOWN)
        refused_with(self, analyze(wk("a", worktree=Path(WT1))), cf.WORKTREE_NOT_TEXT)
        refused_with(self, analyze(wk("a", link="no_link")), cf.LINK_STATE_INVALID)
        refused_with(self, analyze(wk("a", claims=[path(WT2)])), cf.CLAIMS_MALFORMED)
        too_many = tuple(path(f"{WT1}\\f{i}") for i in range(cf.MAX_CLAIMS_PER_WORKER + 1))
        refused_with(self, analyze(wk("a", claims=too_many)), cf.CLAIMS_MALFORMED)

    def test_claim_fields(self):
        refused_with(self, analyze(wk("a", claims=(path(WT2, "write"),))), cf.ACCESS_UNKNOWN)
        refused_with(self, analyze(wk("a", claims=(source("s", None),))), cf.ACCESS_UNKNOWN)
        refused_with(self, analyze(wk("a", claims=(path(b"C:\\Repo"),))), cf.PATH_NOT_TEXT)
        refused_with(self, analyze(wk("a", claims=(path(WT2, link=None),))), cf.LINK_STATE_INVALID)
        for bad in ("", "a/b", "..", 7):
            refused_with(self, analyze(wk("a", claims=(source(bad),))), cf.SOURCE_ID_INVALID)

    def test_read_only_worker_cannot_claim_write(self):
        for claim in (path(WT2, "WRITE"), source("ledger", "WRITE")):
            refused_with(self, analyze(wk("a", "read-only", claims=(claim,))), cf.CLAIM_EXCEEDS_MODE)

    def test_refusal_reasons_are_collected_and_ordered(self):
        graph = cf.analyze_conflicts(cf.ConflictRequest("a/b", (), (wk("x/y", mode="?"),), schema_version=9))
        self.assertEqual(graph.request_reasons, (cf.SCHEMA_VERSION_UNSUPPORTED, cf.DAG_ID_INVALID,
                                                 cf.ALLOWED_ROOTS_MALFORMED, cf.WORKER_ID_INVALID, cf.MODE_UNKNOWN))
        self.assertFalse(graph.compatible("x", "y"))

    def test_bounds_at_maximum_are_accepted(self):
        claims = tuple(path(f"{ROOT}\\shared\\f{i}") for i in range(cf.MAX_CLAIMS_PER_WORKER))
        workers = tuple(wk(f"w{i}", worktree=f"{ROOT}\\w{i}", claims=claims) for i in range(cf.MAX_WORKERS))
        graph = analyze(*workers, roots=tuple(f"{ROOT}\\r{i}" for i in range(cf.MAX_ALLOWED_ROOTS - 1)) + (ROOT,))
        self.assertEqual(graph.outcome, cf.COMPATIBLE)
        self.assertEqual(len(graph.nodes), cf.MAX_WORKERS)
        longest = "C:\\" + "a" * (cf.MAX_PATH_CHARS - 3)
        self.assertEqual(cf.target_key(longest)[0], ())


# ---------------------------------------------------------------------------
# Output invariants and zero authority
# ---------------------------------------------------------------------------

class OutputInvariantTests(unittest.TestCase):
    def test_zero_authority_flags_are_fixed_false(self):
        for graph in (analyze(wk("a")), analyze(wk("a"), wk("b")), cf.analyze_conflicts(None)):
            data = graph.to_dict()
            for flag in ALL_FLAGS:
                self.assertIs(getattr(graph, flag), False, flag)
                self.assertIs(data[flag], False, flag)
            self.assertEqual(data["marker"], cf.CONFLICT_MARKER)
        field_names = {f.name for f in dataclasses.fields(cf.ConflictGraph)}
        self.assertFalse(field_names & set(ALL_FLAGS))
        with self.assertRaises(TypeError):
            dataclasses.replace(analyze(wk("a")), dispatch_allowed=True)
        with self.assertRaises(AttributeError):
            analyze(wk("a")).lock_acquired = True

    def test_hand_made_graphs_cannot_overclaim(self):
        good = analyze(wk("a"), wk("b"))
        fp = good.request_fingerprint
        nodes = good.nodes
        with self.assertRaises(ValueError):
            cf.ConflictGraph(cf.COMPATIBLE, "d", fp, (), nodes, good.edges)
        with self.assertRaises(ValueError):
            cf.ConflictGraph(cf.CONFLICTS, "d", fp, (), nodes, good.edges * 2)
        with self.assertRaises(ValueError):
            cf.ConflictGraph(cf.CONFLICTS, "d", fp, (), nodes[:1], good.edges)
        unknown = (cf.WorkerNode("a", cf.UNKNOWN, (cf.RESOURCE_UNIDENTIFIED,)), nodes[1])
        with self.assertRaises(ValueError):
            cf.ConflictGraph(cf.UNKNOWN, "d", fp, (), unknown, ())
        with self.assertRaises(ValueError):
            cf.ConflictGraph(cf.REFUSED, None, None, (cf.DAG_ID_INVALID,), nodes, ())
        with self.assertRaises(ValueError):
            cf.ConflictGraph(cf.COMPATIBLE, "d", "f" * 63, (), nodes, ())

    def test_hand_made_nodes_and_edges_are_rechecked(self):
        for args in (("b", "a", (cf.WORKTREE_WRITE_WRITE,)), ("a", "a", (cf.WORKTREE_WRITE_WRITE,)),
                     ("a", "b", (cf.ALIAS_DETECTED,)), ("a", "b", ()),
                     ("a", "b", (cf.ALIAS_DETECTED, cf.WORKTREE_WRITE_WRITE)), ("a", "b", ["WORKTREE_NESTED"])):
            with self.assertRaises(ValueError, msg=args):
                cf.ConflictEdge(*args)
        for args in (("a", cf.IDENTIFIED, (cf.PATH_TRAVERSAL,)), ("a", cf.UNKNOWN, ()), ("a/b", cf.IDENTIFIED, ()),
                     ("a", cf.UNKNOWN, (cf.WORKTREE_NESTED,))):
            with self.assertRaises(ValueError, msg=args):
                cf.WorkerNode(*args)

    def test_canonical_json_is_exact_type_bounded_and_path_free(self):
        secret = ROOT + "\\SECRETPATH-sk-live"
        graph = analyze(wk("a", worktree=secret), wk("b", worktree=secret + "\\in"),
                        wk("c", worktree="C:\\SECRETOUTSIDE"))
        text = cf.canonical_json(graph)
        self.assertEqual(json.loads(text), graph.to_dict())
        for leaked in ("SECRET", "sk-live", "Repo", "C:"):
            self.assertNotIn(leaked, text)

        class Sub(cf.ConflictGraph):
            pass
        for bad in (Sub(**{f.name: getattr(graph, f.name) for f in dataclasses.fields(graph)}), graph.to_dict(), None):
            with self.assertRaises(TypeError):
                cf.canonical_json(bad)


# ---------------------------------------------------------------------------
# Determinism, purity, isolation
# ---------------------------------------------------------------------------

class DeterminismAndPurityTests(unittest.TestCase):
    def test_deterministic_and_edges_sorted(self):
        workers = (wk("z"), wk("m"), wk("a", worktree=None), wk("q", worktree=WT2))
        first = cf.canonical_json(analyze(*workers))
        self.assertEqual(first, cf.canonical_json(analyze(*workers)))
        graph = analyze(*workers)
        pairs = [(e.worker_a, e.worker_b) for e in graph.edges]
        self.assertEqual(pairs, sorted(pairs))
        self.assertEqual([n.worker_id for n in graph.nodes], ["z", "m", "a", "q"])
        reordered = analyze(*reversed(workers))
        self.assertEqual(reordered.edges, graph.edges)
        self.assertNotEqual(reordered.request_fingerprint, graph.request_fingerprint)

    def test_preview_never_mutates_inputs(self):
        claims = (path(WT2, "WRITE"), source("ledger", "WRITE"))
        request = req(wk("a", claims=claims), wk("b", worktree=WT2), wk("c", worktree=None))
        before = copy.deepcopy(request)
        cf.analyze_conflicts(request)
        cf.canonical_json(cf.analyze_conflicts(request))
        self.assertEqual(request, before)
        for frozen in (request, request.workers[0], claims[0], claims[1], cf.analyze_conflicts(request)):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(frozen, dataclasses.fields(frozen)[0].name, None)

    def test_no_filesystem_resolution_clock_process_or_network(self):
        def boom(*a, **k):
            raise AssertionError("I/O, resolution or clock attempted")
        patches = [mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom),
                   mock.patch.object(subprocess, "run", boom), mock.patch.object(socket, "socket", boom),
                   mock.patch.object(os, "stat", boom), mock.patch.object(os, "lstat", boom),
                   mock.patch.object(os, "readlink", boom), mock.patch.object(os, "listdir", boom),
                   mock.patch.object(os, "scandir", boom), mock.patch.object(os, "getcwd", boom),
                   mock.patch.object(os, "getenv", boom), mock.patch.object(os.path, "realpath", boom),
                   mock.patch.object(os.path, "abspath", boom), mock.patch.object(os.path, "normcase", boom),
                   mock.patch.object(Path, "resolve", boom), mock.patch.object(time, "time", boom),
                   mock.patch.object(time, "sleep", boom)]
        for p in patches:
            p.start()
        try:
            for request in (req(wk("a"), wk("b", "read-only", worktree=WT1 + "\\..\\x"), wk("c", worktree="rel")),
                            req(wk("a", claims=(source("s", "WRITE"),))), None):
                cf.canonical_json(cf.analyze_conflicts(request))
        finally:
            for p in reversed(patches):
                p.stop()

    def test_module_imports_only_pure_stdlib_and_contract(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {f"{n.module}.{a.name}" if n.module == "scripts.ai" else n.module
                     for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertEqual(imported, {"__future__", "dataclasses", "hashlib", "re", "typing",
                                    "scripts.ai.fabric_scheduler_contract", "fabric_scheduler_contract"})
        code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
        code = "\n".join(line.split("#", 1)[0] for line in code.splitlines())
        for word in ("runner_", "claude", "fabric_director", "DirLease", "lease_dir", "subprocess", "shutil",
                     "socket", "open(", "Path(", "os.", "resolve(", "realpath", "readlink", "environ", "eval(",
                     "exec(", "__import__", "importlib", "git", ".now(", "utcnow", "import time", "sleep",
                     "threading", "Thread", "multiprocessing", "asyncio", "random", "while ", "global "):
            self.assertFalse(word in code.replace("fabric_scheduler_contract", ""), word)

    def test_no_mutable_module_state_changes(self):
        snapshot = {k: copy.deepcopy(v) for k, v in vars(cf).items()
                    if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
        analyze(wk("a"), wk("b"), wk("c", worktree=None))
        cf.analyze_conflicts(None)
        self.assertEqual({k: v for k, v in vars(cf).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_upper_snake(self):
        vocabs = (cf.OUTCOMES, cf.NODE_STATUSES, cf.REQUEST_REASONS, cf.NODE_REASONS, cf.EDGE_REASONS,
                  cf.ACCESSES, cf.LINK_STATES)
        for vocab in vocabs:
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertFalse(set(cf.REQUEST_REASONS) & set(cf.NODE_REASONS))
        self.assertFalse(set(cf.REQUEST_REASONS) & set(cf.EDGE_REASONS))
        self.assertFalse(set(cf.NODE_REASONS) & set(cf.EDGE_REASONS))
        self.assertEqual(cf.OUTCOMES, ("COMPATIBLE", "CONFLICTS", "UNKNOWN", "REFUSED"))
        self.assertEqual(set(cf.EDGE_REASONS) - set(cf.BLOCKING_EDGE_REASONS), {cf.ALIAS_DETECTED})

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


# ---------------------------------------------------------------------------
# Runner policy pins (only the tests import the Runner)
# ---------------------------------------------------------------------------

# Paths that do not exist, so the Runner's own `resolve(strict=False)` stays
# lexical; native flavor so both sides compare the same OS semantics.
NATIVE_ROOT = "C:\\fcp9b01-nonexistent" if os.name == "nt" else "/fcp9b01-nonexistent"
SEP = "\\" if os.name == "nt" else "/"


def native(*parts):
    return SEP.join((NATIVE_ROOT,) + parts)


class RunnerPolicyPinTests(unittest.TestCase):
    def test_mirrored_constants(self):
        from scripts.ai import fabric_dag_blueprint, runner_providers
        self.assertEqual(cf.MODES, (runner_providers.MODE_READ_ONLY, runner_providers.MODE_WRITE))
        self.assertEqual(cf.MAX_WORKERS, fabric_dag_blueprint.MAX_BLUEPRINT_NODES)

    def test_same_worktree_rule_matches_runner_same_worktree_conflict(self):
        from scripts.ai import runner_pipeline
        roots = (NATIVE_ROOT,)
        for mode_a in cf.MODES:
            for mode_b in cf.MODES:
                for top_b in (native("wt"), native("wt2")):
                    running = SimpleNamespace(spec=SimpleNamespace(worktree_top=native("wt"), mode=mode_a))
                    fake = SimpleNamespace(_running=lambda r=running: [r])
                    rt = SimpleNamespace(spec=SimpleNamespace(worktree_top=top_b, mode=mode_b))
                    runner_says = runner_pipeline.PipelineRunner._same_worktree_conflict(fake, rt)
                    graph = analyze(wk("a", mode_a, native("wt")), wk("b", mode_b, top_b), roots=roots)
                    self.assertEqual(not graph.compatible("a", "b"), runner_says, (mode_a, mode_b, top_b))

    def test_target_identity_matches_canonical_target_key_on_clean_spellings(self):
        from scripts.ai import claude_multiworker as mw
        base = native("Repo", "wt")
        variants = [base, base + SEP, native("Repo", ".", "wt"), native("Repo", "", "wt"), native("Repo", "wt2"),
                    native("Repo"), base.replace("Repo", "REPO")]
        if os.name == "nt":
            variants += [base.replace("\\", "/"), base.lower()]
        for a in variants:
            for b in variants:
                ours = cf.target_key(a)[1] == cf.target_key(b)[1]
                self.assertEqual(ours, mw.canonical_target_key(a) == mw.canonical_target_key(b), (a, b))

    def test_nesting_matches_runner_paths_overlap(self):
        from scripts.ai import runner_pipeline
        spellings = [native("Repo"), native("Repo", "wt"), native("Repo", "wt", "sub"), native("Repo", "wt0"),
                     native("Other")]
        for a in spellings:
            for b in spellings:
                ours = cf.overlaps(cf.target_key(a)[1], cf.target_key(b)[1])
                self.assertEqual(ours, runner_pipeline._paths_overlap(Path(a), Path(b)), (a, b))


if __name__ == "__main__":
    unittest.main()
