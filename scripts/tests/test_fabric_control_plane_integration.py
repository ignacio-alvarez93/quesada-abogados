"""FCP-11H-08: Fabric Control Plane end-to-end integration (synthetic).

state files + ledger -> FCP-11 projections -> gateway -> CLI -> view model
-> Flet renderer. The fixtures are the FCP-11G-07 ones: the Runner's OWN
persistence writes `state/` (hand-built manifest, fixed clock, no executor,
provider or Git) and the native `FactoryLedger` writes `factory/`, all under
one private temporary allowed root. The CLI runs in-process; Flet is the
isolated stub of the view suite. Nothing is executed, sent anywhere or
skipped.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import unittest

from scripts.ai import fabric_control_plane_attention as at
from scripts.ai import fabric_control_plane_cli as cli
from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_control_plane_gateway as gw
from scripts.ai import runner_factory_ledger as flog
from scripts.tests import test_fabric_control_plane_gateway as gwfx
from scripts.tests import test_fabric_control_plane_view as vfx
from scripts.tests.test_fabric_resource_quota_report import canonical_temp_dir

fv = vfx.fv  # loaded by file path (see the view suite)
AS_OF = gwfx.AS_OF
PID = gwfx.PID
SECRET = gwfx.SECRET
PRIVATE_PATH = gwfx.PRIVATE_PATH


class IntegrationBase(vfx.StubFletMixin, gwfx.GatewayTestBase):
    def setUp(self):
        super().setUp()
        self.sources = fv.ControlPlaneSources((str(self.top),), str(self.root))

    def view_model(self, sources=None) -> dict:
        return fv.observe(sources or self.sources, AS_OF)

    def cli(self, *argv) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def cli_args(self, query, *extra) -> tuple:
        return ("--query", query, "--allowed-root", str(self.top), "--state-root", str(self.root),
                "--observed-at-utc", AS_OF, *extra)


class EndToEndTests(IntegrationBase):
    def setUp(self):
        super().setUp()
        self.scenario()

    def test_view_summary_is_the_gateway_summary(self):
        head = self.ask("summary")["result"]
        m = self.view_model()
        self.assertEqual(m["state"], fv.STATE_READY)
        self.assertEqual(m["headline"], {k: head[k] for k in ("attention_class", "actor", "origin")})
        self.assertEqual(m["headline"]["attention_class"], at.AUTH)
        self.assertEqual(m["counts"]["workers_shown"], head["workers_shown"])
        self.assertEqual(m["class_counts"], head["class_counts"])
        self.assertTrue(m["consistent"])

    def test_view_pipeline_and_worker_rows_are_the_gateway_rows(self):
        (row,) = self.ask("pipelines")["result"]["pipelines"]
        (p,) = self.view_model()["pipelines"]
        self.assertEqual((p["pipeline_id"], p["outcome"], p["agreement"], p["attention_class"]),
                         (row["pipeline_id"], row["status"]["runner_outcome"], row["agreement"],
                          row["attention_class"]))
        for w, raw in zip(p["workers"], row["workers"]):
            self.assertEqual((w["worker_id"], w["outcome"], w["result_outcome"], w["attention_class"]),
                             (raw["worker_id"], raw["record_status"]["runner_outcome"],
                              raw["result_status"]["runner_outcome"], raw["attention_class"]))
        self.assertEqual([w["worker_id"] for w in p["workers"]], ["w1", "w2"])

    def test_view_attention_is_the_gateway_attention_without_clear(self):
        items = self.ask("attention")["result"]["items"]
        m = self.view_model()
        expected = [(i["pipeline_id"], i["worker_id"], i["attention_class"]) for i in items
                    if i["attention_class"] != at.CLEAR]
        self.assertEqual([(i["pipeline_id"], i["worker_id"], i["attention_class"]) for i in m["attention"]],
                         expected)
        self.assertIn((PID, "w2", at.AUTH), expected)

    def test_cli_json_is_byte_equal_to_the_gateway_the_view_consumes(self):
        for query in fv.QUERIES:
            code, out, err = self.cli(*self.cli_args(query, "--limit", str(fv.PAGE_LIMIT)))
            self.assertEqual((code, err), (cli.EXIT_OK, ""))
            self.assertEqual(out.strip(), gw.render_json(self.ask(query, limit=fv.PAGE_LIMIT)))
        self.assertEqual(json.loads(self.cli(*self.cli_args("summary"))[1])["result"]["attention_class"],
                         self.view_model()["headline"]["attention_class"])

    def test_ledger_activity_reaches_the_cli_correlated_with_the_same_state(self):
        code, out, _ = self.cli(*self.cli_args("activity", "--factory-root", str(self.factory)))
        body = json.loads(out)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual((body["result"]["ledger_condition"], body["page"]["total"]), (cp.PRESENT, 3))
        self.assertEqual({e["event_type"] for e in body["result"]["events"]},
                         {flog.WORKER_STARTED, flog.WORKER_FINISHED})
        self.assertNotIn(SECRET, out)
        self.assertNotIn("client-data", out)

    def test_rendered_view_shows_the_real_state_and_no_secret_or_path(self):
        self.stub_flet()
        root = fv.fabric_control_plane_view(object(), sources=self.sources, now_utc=lambda: fv.datetime(
            2026, 11, 2, 12, 0, tzinfo=fv.timezone.utc))
        text = " ".join(vfx.texts(root))
        for expected in (PID, "w1", "w2", at.AUTH, "HUMAN ATTENTION", "No autorizada"):
            self.assertIn(expected, text)
        for leak in (SECRET, PRIVATE_PATH, "client-data", str(self.top), "feature/"):
            self.assertNotIn(leak, text)
            self.assertNotIn(leak, repr(self.view_model()))
        self.assertEqual(len(vfx.handlers(root)), 1)

    def test_repeated_observation_is_deterministic_and_mutates_nothing(self):
        before = gwfx.tree_state(self.top)
        first = self.view_model()
        for _ in range(20):
            self.assertEqual(self.view_model(), first)
        self.assertEqual(gwfx.tree_state(self.top), before)

    def test_every_answer_used_by_the_view_has_zero_authority(self):
        for query in fv.QUERIES:
            body = self.ask(query, limit=fv.PAGE_LIMIT)
            for flag in gwfx.FLAGS:
                self.assertIs(body[flag], False, (query, flag))
        self.assertEqual({a["availability"] for a in self.view_model()["actions"]}, {fv.ACTION_NOT_AUTHORIZED})


class FailClosedTests(IntegrationBase):
    def test_missing_state_root_is_empty_missing_never_success(self):
        m = self.view_model(fv.ControlPlaneSources((str(self.top),), str(self.top / "absent")))
        self.assertEqual((m["state"], m["root"]["condition"]), (fv.STATE_EMPTY, cp.MISSING))
        self.assertNotEqual(m["headline"]["attention_class"], at.CLEAR)

    def test_corrupt_state_is_shown_corrupt_never_success(self):
        self.scenario()
        (self.root / PID / "pipeline_result.json").write_bytes(b"\xff\xfe" + SECRET.encode())
        (self.root / PID / "workers" / "w2" / "worker.json").write_bytes(b'{"a": 1, "a": 2}')
        m = self.view_model()
        (p,) = m["pipelines"]
        self.assertEqual(p["condition"], cp.CORRUPT)
        self.assertEqual(p["workers"][1]["condition"], cp.CORRUPT)
        self.assertNotEqual(m["headline"]["attention_class"], at.CLEAR)
        self.assertNotIn(SECRET, repr(m))

    def test_sources_outside_the_allowed_root_are_refused_by_view_and_cli(self):
        outside = canonical_temp_dir("fcp11h08-out-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        m = self.view_model(fv.ControlPlaneSources((str(self.top),), str(outside)))
        self.assertEqual((m["state"], m["error"]["code"]), (fv.STATE_ERROR, "GATEWAY_PATH_OUTSIDE_ROOTS"))
        self.assertNotIn(str(outside), repr(m))
        code, out, err = self.cli("--query", "summary", "--allowed-root", str(self.top), "--state-root",
                                  str(outside), "--observed-at-utc", AS_OF)
        self.assertEqual((code, out), (cli.EXIT_REFUSED, ""))
        self.assertIn("GATEWAY_PATH_OUTSIDE_ROOTS", err)

    def test_junction_escaping_the_root_is_refused(self):
        outside = canonical_temp_dir("fcp11h08-esc-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        self.alias(outside, self.top / "escape")
        m = self.view_model(fv.ControlPlaneSources((str(self.top),), str(self.top / "escape")))
        self.assertEqual(m["error"]["code"], "GATEWAY_PATH_OUTSIDE_ROOTS")

    def test_absent_runner_layout_is_an_explicit_error(self):
        sources = fv.control_plane_sources(self.top / "no-repo")
        m = self.view_model(sources)
        self.assertEqual((m["state"], m["error"]["code"]), (fv.STATE_ERROR, "GATEWAY_ROOTS_INVALID"))
        self.assertIn("no están disponibles", m["error"]["friendly"])

    def test_default_runner_layout_is_observed_end_to_end(self):
        runtime = self.top / "repo" / "runtime" / "claude_runner"
        (runtime / "pipelines").mkdir(parents=True)
        self.synthetic_pipeline("pipe-x", ("RUNNING", "SUCCESS"))
        shutil.copytree(self.root / "pipe-x", runtime / "pipelines" / "pipe-x")
        m = self.view_model(fv.control_plane_sources(self.top / "repo"))
        self.assertEqual(m["state"], fv.STATE_READY)
        self.assertEqual([p["pipeline_id"] for p in m["pipelines"]], ["pipe-x"])
        self.assertEqual([w["worker_id"] for w in m["pipelines"][0]["workers"]], ["w1", "w2"])

    def test_invalid_instant_from_the_caller_is_an_error_state(self):
        m = fv.observe(self.sources, "2026-11-02T12:00:00+00:00")
        self.assertEqual(m["error"]["code"], "GATEWAY_INSTANT_INVALID")


if __name__ == "__main__":
    unittest.main()
