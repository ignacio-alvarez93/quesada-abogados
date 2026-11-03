"""FCP-11G-07: Fabric Control Plane read gateway.

Every fixture lives under ONE private temporary directory spelled by its
physical path (the allowed root): `state/` is written by the Runner's OWN
persistence (FCP-11C-03 / 11F-06 fixtures: hand-built `Manifest`, fixed
clock, no executor, provider or Git), `factory/` by the native
`FactoryLedger` with a fixed clock, and report documents by the FCP-10D-01
test fixtures. Expected values are the real FCP-11 projections over the same
bytes. Nothing is executed, sent anywhere or skipped.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_control_plane_attention as at
from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_control_plane_evidence as ev
from scripts.ai import fabric_control_plane_gateway as gw
from scripts.ai import fabric_control_plane_history as hist
from scripts.ai import fabric_control_plane_resources as res
from scripts.ai import fabric_control_plane_snapshot as snap
from scripts.ai import runner_factory_ledger as flog
from scripts.tests import test_fabric_control_plane_attention as atfx
from scripts.tests import test_fabric_control_plane_evidence as evfx
from scripts.tests import test_fabric_resource_quota_report as qfx
from scripts.tests.test_fabric_resource_quota_report import (
    canonical_temp_dir, directory_alias, remove_directory_alias,
)

MODULE_PATH = Path(gw.__file__)
AS_OF = evfx.AS_OF
PID = evfx.PID
SECRET = evfx.SECRET
PRIVATE_PATH = evfx.PRIVATE_PATH
T0 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
FLAGS = atfx.ALL_FLAGS + ("network_used", "write_performed")
LEAKY_KEYS = {"path", "evidence_dir", "worktree", "branch", "message", "work_order", "prompt", "stdout", "stderr"}


def tree_state(root: Path) -> dict:
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


class GatewayTestBase(atfx.AttentionTestBase):
    def setUp(self):
        self.top = canonical_temp_dir("fcp11g07-")
        self.addCleanup(shutil.rmtree, self.top, ignore_errors=True)
        self.root = self.top / "state"
        self.factory = self.top / "factory"
        self.root.mkdir()
        self.factory.mkdir()
        self.runner = self.make_runner(("w1", "w2"))
        self.tick = 0
        self.ids = iter(f"{i:032x}" for i in range(1, 10_000))
        self.ledger = flog.FactoryLedger(self.factory, clock=self.clock, id_factory=lambda: next(self.ids))

    def clock(self) -> datetime:
        self.tick += 1
        return T0 + timedelta(minutes=self.tick)

    def scenario(self):
        """w1 proven SUCCESS, w2 auth hold; the ledger saw both start."""
        self.succeed("w1")
        self.auth_blocked("w2")
        self.finish()
        for wid in ("w1", "w2"):
            self.ledger.append(flog.WORKER_STARTED, pipeline_id=PID, worker_id=wid, provider="claude",
                               state="RUNNING", worktree=PRIVATE_PATH, branch="feature/" + SECRET)
        self.ledger.append(flog.WORKER_FINISHED, pipeline_id=PID, worker_id="w1", provider="claude",
                           state="SUCCESS", state_reason="DONE:" + SECRET, worktree=PRIVATE_PATH)

    def put(self, relative: str, payload) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8"))
        return path

    def synthetic_pipeline(self, pid, states=("RUNNING",)):
        workers = [{"id": f"w{i}", "state": s, "provider": "alpha"} for i, s in enumerate(states, 1)]
        self.put(f"{pid}/pipeline_result.json", {"schema_version": 1, "pipeline_id": pid, "status": "RUNNING",
                                                 "workers_total": len(workers), "workers": workers})
        self.put(f"{pid}/pipeline.json", {"schema_version": 1, "pipeline_id": pid, "status": "RUNNING"})
        for w in workers:
            self.put(f"{pid}/workers/{w['id']}/worker.json",
                     {"schema_version": 1, "spec": {"id": w["id"]}, "state": w["state"]})

    def request(self, name, **kw) -> gw.GatewayRequest:
        kw.setdefault("allowed_roots", (str(self.top),))
        kw.setdefault("state_root", str(self.root))
        kw.setdefault("observed_at_utc", AS_OF)
        return gw.GatewayRequest(name, **kw)

    def ask(self, name, **kw) -> dict:
        return gw.query(self.request(name, **kw))

    def refused(self, code, name="summary", **kw):
        with self.assertRaises(gw.GatewayError) as ctx:
            self.ask(name, **kw)
        self.assertEqual(ctx.exception.code, code)
        return ctx.exception

    def alias(self, target: Path, alias: Path) -> None:
        directory_alias(target, alias)
        self.addCleanup(lambda: os.path.lexists(alias) and remove_directory_alias(alias))

    def direct(self):
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        evidence = ev.take_evidence(str(self.root), snapshot)
        return snapshot, evidence, at.observe_attention(snapshot, evidence=evidence)


# ---------------------------------------------------------------------------
# Composition: values are the projections', never re-decided
# ---------------------------------------------------------------------------

class CompositionTests(GatewayTestBase):
    def setUp(self):
        super().setUp()
        self.scenario()

    def test_summary_copies_the_projections(self):
        snapshot, evidence, attention = self.direct()
        out = self.ask("summary")
        self.assertEqual(out["sources"], {"snapshot": snapshot.revision, "evidence": evidence.revision,
                                          "attention": attention.revision})
        body = attention.to_dict()
        result = out["result"]
        for key in ("attention_class", "actor", "origin", "primary", "class_counts", "bindings", "causes"):
            self.assertEqual(result[key], body[key], key)
        self.assertEqual(result["attention_class"], at.AUTH)
        self.assertEqual((result["root_condition"], result["pipelines_shown"], result["workers_shown"]),
                         (cp.PRESENT, 1, 2))
        self.assertEqual(result["worker_record_outcomes"],
                         {w.record_status.runner_outcome: 1 for p in snapshot.pipelines for w in p.workers})
        self.assertIsNone(out["page"])

    def test_pipelines_rows_copy_statuses_and_attention(self):
        snapshot, _, attention = self.direct()
        (row,) = self.ask("pipelines")["result"]["pipelines"]
        p = snapshot.pipelines[0]
        self.assertEqual(row["status"]["runner_outcome"], p.view.status.runner_outcome)
        self.assertEqual(row["agreement"], p.agreement)
        items = {(i.pipeline_id, i.worker_id): i for i in attention.items}
        for wrow, w in zip(row["workers"], p.workers):
            self.assertEqual(wrow["record_status"], {k: w.record_status.to_dict()[k] for k in wrow["record_status"]})
            self.assertEqual(wrow["attention_class"], items[(PID, w.worker_id)].attention_class)
        self.assertEqual(row["attention_class"], items[(PID, None)].attention_class)

    def test_worker_joins_snapshot_view_evidence_and_attention(self):
        _, evidence, attention = self.direct()
        out = self.ask("worker", pipeline_id=PID, worker_id="w1")["result"]
        self.assertTrue(out["found"])
        self.assertEqual(out["evidence"], evfx.EvidenceTestBase.worker(evidence, "w1").to_dict())
        item = next(i for i in attention.items if (i.pipeline_id, i.worker_id) == (PID, "w1"))
        self.assertEqual(out["attention"], item.to_dict())
        self.assertEqual(out["attention"]["attention_class"], at.CLEAR)
        self.assertEqual(out["listed_view"]["worker_id"], "w1")

    def test_unknown_worker_is_not_found_never_success(self):
        out = self.ask("worker", pipeline_id=PID, worker_id="w9")["result"]
        self.assertEqual((out["found"], out["snapshot"], out["evidence"], out["attention"]), (False, None, None, None))

    def test_activity_is_the_history_page_correlated_with_the_snapshot(self):
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        history = hist.take_history(str(self.factory), AS_OF, snapshot=snapshot, limit=2)
        out = self.ask("activity", factory_root=str(self.factory), limit=2)
        self.assertEqual(out["sources"], {"snapshot": snapshot.revision, "history": history.revision})
        self.assertEqual(out["result"]["events"], history.to_dict()["events"])
        self.assertEqual(out["page"], {"offset": 0, "limit": 2, "total": 3, "returned": 2, "next_offset": 2})
        last = self.ask("activity", factory_root=str(self.factory), offset=2, limit=2)
        self.assertEqual((last["page"]["returned"], last["page"]["next_offset"]), (1, None))
        only = self.ask("activity", factory_root=str(self.factory), worker_id="w2")
        self.assertEqual({e["worker_id"] for e in only["result"]["events"]}, {"w2"})
        finished = self.ask("activity", factory_root=str(self.factory), event_type=flog.WORKER_FINISHED)
        self.assertEqual(finished["page"]["total"], 1)

    def test_activity_without_a_ledger_is_missing_not_empty_success(self):
        shutil.rmtree(self.factory)
        self.factory.mkdir()
        out = self.ask("activity", factory_root=str(self.factory))["result"]
        self.assertEqual((out["ledger_condition"], out["ledger_cause"], out["events"]),
                         (cp.MISSING, cp.SOURCE_ABSENT, []))

    def test_attention_items_are_prioritized_and_paged(self):
        _, _, attention = self.direct()
        out = self.ask("attention", limit=1)
        self.assertEqual(out["result"]["items"], [attention.items[0].to_dict()])
        self.assertEqual(out["page"]["total"], len(attention.items))
        self.assertEqual(out["page"]["next_offset"], 1)

    def test_resources_without_report_are_missing_and_unknown(self):
        snapshot = snap.take_snapshot(str(self.root), AS_OF)
        resources = res.observe_resources(snapshot)
        out = self.ask("resources")
        self.assertEqual(out["sources"]["resources"], resources.revision)
        r = out["result"]
        self.assertEqual((r["report_condition"], r["report_cause"]), (cp.MISSING, cp.SOURCE_ABSENT))
        self.assertEqual(r["global_cost_condition"], res.UNKNOWN)
        self.assertEqual(r["workers"], resources.to_dict()["workers"])

    def test_resources_with_a_report_file_inside_the_allowed_root(self):
        report = self.top / "report.json"
        report.write_bytes(json.dumps(qfx.document()).encode("utf-8"))
        out = self.ask("resources", report_file=str(report))
        self.assertEqual(out["result"]["report_condition"], cp.PRESENT)
        self.assertIs(out["request"]["report_file_given"], True)
        self.assertNotIn(str(self.top), gw.render_json(out))


# ---------------------------------------------------------------------------
# Determinism, read-only, limits
# ---------------------------------------------------------------------------

class DeterminismAndLimitTests(GatewayTestBase):
    def test_same_input_gives_byte_equal_output(self):
        self.scenario()
        for name, kw in (("summary", {}), ("pipelines", {}), ("attention", {}), ("resources", {}),
                         ("worker", {"pipeline_id": PID, "worker_id": "w2"}),
                         ("activity", {"factory_root": str(self.factory)})):
            first, second = gw.render_json(self.ask(name, **kw)), gw.render_json(self.ask(name, **kw))
            self.assertEqual(first, second, name)
            self.assertEqual(json.loads(first)["revision"], self.ask(name, **kw)["revision"])

    def test_one_hundred_queries_mutate_nothing(self):
        self.scenario()
        before = tree_state(self.top)
        kinds = [("summary", {}), ("pipelines", {}), ("attention", {}), ("resources", {}),
                 ("worker", {"pipeline_id": PID, "worker_id": "w1"}),
                 ("activity", {"factory_root": str(self.factory)})]
        answers = {}
        for i in range(100):
            name, kw = kinds[i % len(kinds)]
            answers.setdefault(name, set()).add(gw.render_json(self.ask(name, **kw)))
        self.assertEqual(tree_state(self.top), before)
        self.assertTrue(all(len(v) == 1 for v in answers.values()))

    def test_pages_are_bounded_by_the_limit(self):
        for i in range(5):
            self.synthetic_pipeline(f"p{i}")
        out = self.ask("pipelines", limit=2, offset=1)
        self.assertEqual([p["pipeline_id"] for p in out["result"]["pipelines"]], ["p0", "p1"])
        self.assertEqual(out["page"], {"offset": 1, "limit": 2, "total": 6, "returned": 2, "next_offset": 3})
        tail = self.ask("pipelines", offset=6)
        self.assertEqual((tail["result"]["pipelines"], tail["page"]["next_offset"]), ([], None))
        one = self.ask("pipelines", pipeline_id="p3")
        self.assertEqual([p["pipeline_id"] for p in one["result"]["pipelines"]], ["p3"])

    def test_limit_and_offset_out_of_range_are_refused(self):
        for kw in ({"limit": 0}, {"limit": gw.MAX_LIMIT + 1}, {"offset": -1}, {"limit": True}, {"limit": "5"},
                   {"offset": gw.MAX_OFFSET + 1}):
            error = self.refused("GATEWAY_PAGE_INVALID", "pipelines", **kw)
            self.assertTrue(error.usage)
        self.assertEqual(self.ask("pipelines", limit=gw.MAX_LIMIT)["page"]["limit"], gw.MAX_LIMIT)

    def test_oversized_response_is_refused_never_truncated(self):
        self.scenario()
        with mock.patch.object(gw, "MAX_RESPONSE_BYTES", 512):
            error = self.refused("GATEWAY_RESPONSE_TOO_LARGE", "pipelines")
        self.assertFalse(error.usage)
        self.assertLess(len(gw.render_json(self.ask("summary"))), gw.MAX_RESPONSE_BYTES)


# ---------------------------------------------------------------------------
# Paths, ids, corrupt sources
# ---------------------------------------------------------------------------

class PathAndInputTests(GatewayTestBase):
    def test_sources_outside_the_allowed_roots_are_refused_before_reading(self):
        outside = canonical_temp_dir("fcp11g07-out-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        with mock.patch.object(snap, "take_snapshot") as taken:
            self.refused("GATEWAY_PATH_OUTSIDE_ROOTS", state_root=str(outside))
            self.refused("GATEWAY_PATH_OUTSIDE_ROOTS", "activity", factory_root=str(outside))
            report = outside / "report.json"
            report.write_bytes(json.dumps(qfx.document()).encode("utf-8"))
            self.refused("GATEWAY_PATH_OUTSIDE_ROOTS", "resources", report_file=str(report))
            self.refused("GATEWAY_PATH_OUTSIDE_ROOTS", state_root=str(self.top) + "-sibling")
            taken.assert_not_called()

    def test_inadmissible_paths_are_refused(self):
        for path in ("state", "", "\\\\server\\share\\state", str(self.top / ".." / self.top.name / "state"),
                     str(self.root) + "\x00", "file://" + str(self.root), None, 7):
            self.refused("GATEWAY_PATH_NOT_ADMISSIBLE", state_root=path)

    def test_allowed_roots_must_be_plain_existing_directories(self):
        alias = self.top.parent / (self.top.name + "-alias")
        self.alias(self.top, alias)
        for roots in ((), ("relative",), (str(self.top / "missing"),), (str(alias),), str(self.top),
                      (str(self.top),) * (gw.MAX_ALLOWED_ROOTS + 1), (str(self.top / "state" / "x"),)):
            self.refused("GATEWAY_ROOTS_INVALID", allowed_roots=roots)

    def test_a_junction_escaping_the_allowed_root_is_refused(self):
        outside = canonical_temp_dir("fcp11g07-esc-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        self.alias(outside, self.top / "escape")
        self.refused("GATEWAY_PATH_OUTSIDE_ROOTS", state_root=str(self.top / "escape"))

    def test_a_junction_inside_the_allowed_root_is_never_followed(self):
        self.scenario()
        self.alias(self.root, self.top / "inner")
        out = self.ask("summary", state_root=str(self.top / "inner"))["result"]
        self.assertEqual((out["root_condition"], out["root_cause"]), (cp.UNAVAILABLE, cp.LINK_REFUSED))
        self.assertNotEqual(out["attention_class"], at.CLEAR)

    def test_missing_state_root_is_missing_never_success(self):
        out = self.ask("summary", state_root=str(self.top / "absent"))["result"]
        self.assertEqual((out["root_condition"], out["root_cause"]), (cp.MISSING, cp.SOURCE_ABSENT))
        self.assertNotEqual(out["attention_class"], at.CLEAR)

    def test_malicious_ids_and_bad_requests_are_usage_errors(self):
        for kw in ({"pipeline_id": "../x"}, {"pipeline_id": "a/b"}, {"worker_id": "CON"}, {"pipeline_id": SECRET},
                   {"pipeline_id": "x" * 300}, {"event_type": "DROP_TABLE"}, {"pipeline_id": 5}):
            self.assertTrue(self.refused("GATEWAY_ID_INVALID", "pipelines", **kw).usage)
        self.refused("GATEWAY_QUERY_UNKNOWN", "watch")
        self.refused("GATEWAY_QUERY_UNKNOWN", "write")
        self.refused("GATEWAY_INSTANT_INVALID", observed_at_utc="2026-11-02T12:00:00+00:00")
        self.refused("GATEWAY_INSTANT_INVALID", observed_at_utc=None)
        self.refused("GATEWAY_SOURCE_REQUIRED", "worker", pipeline_id=PID)
        self.refused("GATEWAY_SOURCE_REQUIRED", "activity")
        self.refused("GATEWAY_USAGE_INVALID", "summary", report_file=str(self.top / "r.json"))
        with self.assertRaises(gw.GatewayError) as ctx:
            gw.query({"query": "summary"})
        self.assertEqual(ctx.exception.code, "GATEWAY_USAGE_INVALID")

    def test_corrupt_json_is_reported_corrupt_not_raised(self):
        self.scenario()
        (self.root / PID / "pipeline.json").write_bytes(b'{"schema_version": 1, "status": ')
        (self.root / PID / "workers" / "w2" / "worker.json").write_bytes(b'{"a": 1, "a": 2}')
        (self.root / PID / "pipeline_result.json").write_bytes(b"\xff\xfe" + SECRET.encode())
        row = self.ask("pipelines")["result"]["pipelines"][0]
        self.assertEqual((row["record_status"]["condition"], row["record_status"]["cause"]),
                         (cp.CORRUPT, cp.SOURCE_NOT_JSON))
        self.assertEqual(row["status"]["condition"], cp.CORRUPT)
        w2 = next(w for w in row["workers"] if w["worker_id"] == "w2")
        self.assertEqual(w2["record_status"]["condition"], cp.CORRUPT)
        self.assertNotEqual(self.ask("summary")["result"]["attention_class"], at.CLEAR)
        (self.factory / flog.EVENTS_FILENAME).write_bytes(b"{not json}\n" + SECRET.encode() + b"\n")
        out = self.ask("activity", factory_root=str(self.factory))
        self.assertEqual(out["result"]["events"], [])
        self.assertNotIn(SECRET, gw.render_json(out))


# ---------------------------------------------------------------------------
# Safe output and errors
# ---------------------------------------------------------------------------

class SafeOutputTests(GatewayTestBase):
    def test_no_secret_path_or_withheld_field_reaches_the_output(self):
        self.scenario()
        texts = [gw.render_json(self.ask(n, **kw)) for n, kw in (
            ("summary", {}), ("pipelines", {}), ("attention", {}), ("resources", {}),
            ("worker", {"pipeline_id": PID, "worker_id": "w1"}), ("worker", {"pipeline_id": PID, "worker_id": "w2"}),
            ("activity", {"factory_root": str(self.factory)}))]
        for text in texts:
            self.assertTrue(text.isascii())
            for leak in (SECRET, PRIVATE_PATH, "client-data", str(self.top), "feature/", "confidential"):
                self.assertNotIn(leak, text)
            keys = {k for k in atfx.walk(json.loads(text)) if isinstance(k, str)}
            self.assertFalse(keys & LEAKY_KEYS)

    def test_zero_authority_flags_are_all_false(self):
        out = self.ask("summary")
        for flag in FLAGS:
            self.assertIs(out[flag], False, flag)
        self.assertEqual(out["marker"], cp.CONTROL_PLANE_MARKER)
        self.assertEqual(out["schema"], gw.SCHEMA)
        self.assertEqual(out["request"]["factory_root_given"], False)

    def test_sanitize_redacts_and_bounds_strings(self):
        self.assertEqual(gw._sanitize(SECRET), gw.REDACTED)
        for path in (PRIVATE_PATH, "C:\\x", "/etc/passwd", "~/x", "a\\b", "x/y/z"):
            self.assertEqual(gw._sanitize(path), gw.REDACTED, path)
        self.assertEqual(gw._sanitize("caf\u00e9 ok\x07"), "caf? ok?")
        self.assertIn(gw._sanitize("caf\u00e9\n\x1b[31m"), (gw.REDACTED, "caf???[31m"))
        self.assertLessEqual(len(gw._sanitize("ab " * gw.MAX_STRING_CHARS)), gw.MAX_STRING_CHARS)
        with mock.patch.object(gw, "MAX_STRING_CHARS", 5):
            self.assertEqual(gw._sanitize("PROVIDER_AUTH_BLOCKED"), "PROVI")
        for kept in ("2026-11-02T12:00:00Z", "PROVIDER_AUTH_BLOCKED", "fcp11-pipe", "a/b"):
            self.assertEqual(gw._sanitize(kept), kept)
        self.assertEqual(gw._sanitize({"k": [1, True, None, ("x",)]}), {"k": [1, True, None, ["x"]]})
        for bad in (1.5, b"x", object(), {1: "x"}):
            with self.assertRaises(gw.GatewayError):
                gw._sanitize(bad)

    def test_text_rendering_holds_the_same_facts(self):
        self.scenario()
        out = self.ask("summary")
        text = gw.render_text(out)
        self.assertTrue(text.isascii())
        self.assertIn(f"revision: {out['revision']}", text.splitlines())
        self.assertIn(f"result.attention_class: {out['result']['attention_class']}", text.splitlines())
        self.assertIn("network_used: false", text.splitlines())

    def test_internal_failures_are_safe_errors(self):
        with mock.patch.object(snap, "take_snapshot", side_effect=RuntimeError(SECRET + PRIVATE_PATH)):
            error = self.refused("GATEWAY_INTERNAL_ERROR")
        self.assertFalse(error.usage)
        self.assertNotIn(SECRET, error.render())
        self.assertIsNone(error.__cause__)
        self.assertEqual(error.render(), "error: GATEWAY_INTERNAL_ERROR: the response could not be produced")

    def test_convenience_functions_equal_query(self):
        self.scenario()
        roots = [str(self.top)]
        self.assertEqual(gw.summary(roots, str(self.root), AS_OF), self.ask("summary"))
        self.assertEqual(gw.pipelines(roots, str(self.root), AS_OF, limit=1), self.ask("pipelines", limit=1))
        self.assertEqual(gw.worker(roots, str(self.root), AS_OF, pipeline_id=PID, worker_id="w1"),
                         self.ask("worker", pipeline_id=PID, worker_id="w1"))
        self.assertEqual(gw.activity(roots, str(self.root), AS_OF, factory_root=str(self.factory)),
                         self.ask("activity", factory_root=str(self.factory)))
        self.assertEqual(gw.attention(roots, str(self.root), AS_OF), self.ask("attention"))
        self.assertEqual(gw.resources(roots, str(self.root), AS_OF), self.ask("resources"))


class StaticTests(unittest.TestCase):
    def test_no_network_server_process_git_or_write_primitive(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(imported & {"socket", "http", "urllib", "subprocess", "threading", "asyncio",
                                     "sqlite3", "shutil", "tempfile", "requests"})
        calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
                 for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertFalse(calls & {"open", "write", "write_text", "write_bytes", "mkdir", "remove", "unlink",
                                  "rename", "replace", "system", "popen", "append_event", "getenv", "now", "time"})
        self.assertNotIn("FactoryLedger", MODULE_PATH.read_text(encoding="utf-8"))

    def test_queries_are_read_only_names(self):
        self.assertEqual(gw.QUERIES, ("summary", "pipelines", "worker", "activity", "attention", "resources"))


if __name__ == "__main__":
    unittest.main()
