import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.ai import runner_factory_ledger as flog


class FakeClock:
    def __init__(self, start=None):
        self.now = start or datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds=1):
        self.now += timedelta(seconds=seconds)
        return self.now


class SequentialIds:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"evt-{self.n:04d}"


class LedgerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "factory"
        self.clock = FakeClock()
        self.ids = SequentialIds()
        self.ledger = flog.FactoryLedger(self.root, clock=self.clock, id_factory=self.ids)

    def emit(self, event_type, **fields):
        self.clock.advance()
        return self.ledger.append(event_type, **fields)


class AppendReadOrderTests(LedgerTestBase):
    def test_events_are_read_back_in_append_order(self):
        for i in range(5):
            self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id=f"w{i}")
        events = self.ledger.events()
        self.assertEqual([e["worker_id"] for e in events], [f"w{i}" for i in range(5)])

    def test_events_jsonl_is_one_json_object_per_line(self):
        self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w0")
        self.emit(flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w0", state="SUCCESS")
        lines = (self.root / flog.EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            parsed = json.loads(line)
            self.assertIn("event_id", parsed)
            self.assertIn("timestamp_utc", parsed)

    def test_unknown_event_type_is_rejected(self):
        with self.assertRaises(flog.FactoryLedgerError) as ctx:
            self.emit("NOT_A_REAL_EVENT", pipeline_id="p1")
        self.assertEqual(ctx.exception.code, "UNKNOWN_EVENT_TYPE")
        events, _ = flog.read_events(self.root)
        self.assertEqual(events, [])

    def test_unknown_event_field_is_rejected(self):
        with self.assertRaises(flog.FactoryLedgerError) as ctx:
            self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w0", api_key="sk-secret")
        self.assertEqual(ctx.exception.code, "UNKNOWN_EVENT_FIELD")


class MultipleProvidersModulesTests(LedgerTestBase):
    def _run(self, pipeline_id, worker_id, provider, module, role, state):
        self.emit(
            flog.WORKER_STARTED, pipeline_id=pipeline_id, worker_id=worker_id, provider=provider,
            module=module, role=role, worktree=f"/repos/{module}", branch="main", base_commit="a" * 40,
        )
        self.emit(
            flog.WORKER_FINISHED, pipeline_id=pipeline_id, worker_id=worker_id, provider=provider,
            module=module, role=role, worktree=f"/repos/{module}", result_commit="b" * 40,
            state=state, state_reason=None,
        )

    def test_multiple_providers_and_modules_are_tracked_independently(self):
        self._run("p1", "w1", "claude", "knowledge", "implementer", "SUCCESS")
        self._run("p1", "w2", "codex", "billing", "implementer", "FAILED")
        modules = self.ledger.modules()
        self.assertEqual(set(modules), {"knowledge", "billing"})
        self.assertEqual(modules["knowledge"]["provider"], "claude")
        self.assertEqual(modules["knowledge"]["state"], "SUCCESS")
        self.assertEqual(modules["billing"]["provider"], "codex")
        self.assertEqual(modules["billing"]["state"], "FAILED")

    def test_module_filter_returns_only_that_modules_events(self):
        self._run("p1", "w1", "claude", "knowledge", "implementer", "SUCCESS")
        self._run("p1", "w2", "codex", "billing", "implementer", "SUCCESS")
        history = self.ledger.events(module="knowledge")
        self.assertTrue(history)
        self.assertTrue(all(e["module"] == "knowledge" for e in history))

    def test_role_filter_returns_only_that_roles_events(self):
        self._run("p1", "w1", "claude", "knowledge", "implementer", "SUCCESS")
        self._run("p1", "w2", "claude", "knowledge", "reviewer", "SUCCESS")
        history = self.ledger.events(role="reviewer")
        self.assertEqual({e["worker_id"] for e in history}, {"w2"})

    def test_provider_and_pipeline_and_worker_filters(self):
        self._run("p1", "w1", "claude", "knowledge", "implementer", "SUCCESS")
        self._run("p2", "w1", "codex", "knowledge", "implementer", "SUCCESS")
        self.assertEqual(len(self.ledger.events(provider="codex")), 2)
        self.assertEqual(len(self.ledger.events(pipeline_id="p2")), 2)
        self.assertEqual(len(self.ledger.events(pipeline_id="p1", worker_id="w1")), 2)


class CurrentStatusTests(LedgerTestBase):
    def test_started_without_finished_is_active(self):
        self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", provider="claude", module="knowledge")
        status = self.ledger.status()
        self.assertEqual(len(status["active_workers"]), 1)
        self.assertEqual(status["active_workers"][0]["worker_id"], "w1")

    def test_finished_worker_is_no_longer_active(self):
        self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", provider="claude")
        self.emit(flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", state="SUCCESS")
        status = self.ledger.status()
        self.assertEqual(status["active_workers"], [])

    def test_same_worker_id_in_different_pipelines_tracked_independently(self):
        self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1")
        self.emit(flog.WORKER_STARTED, pipeline_id="p2", worker_id="w1")
        self.emit(flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", state="SUCCESS")
        status = self.ledger.status()
        self.assertEqual(len(status["active_workers"]), 1)
        self.assertEqual(status["active_workers"][0]["pipeline_id"], "p2")


class HistoricalClosedModuleTests(LedgerTestBase):
    def test_certified_and_closed_module_is_materialized(self):
        self.emit(
            flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", provider="claude", role="implementer",
            module="knowledge", module_version="v1", worktree="/repos/knowledge", branch="feature/x",
            base_commit="a" * 40,
        )
        self.emit(
            flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", provider="claude", role="implementer",
            module="knowledge", module_version="v1", result_commit="b" * 40, state="SUCCESS",
        )
        self.emit(
            flog.CERTIFICATION_STARTED, module="knowledge", module_version="v1",
            certification_status="IN_PROGRESS",
        )
        self.emit(
            flog.CERTIFICATION_FINISHED, module="knowledge", module_version="v1",
            certification_status="PASSED",
        )
        self.emit(
            flog.MODULE_CLOSED, module="knowledge", module_version="v1", state="CLOSED",
            closer="nacho_1_9_9_3@hotmail.com",
        )
        modules = self.ledger.modules()
        entry = modules["knowledge@v1"]
        self.assertEqual(entry["certification_status"], "PASSED")
        self.assertEqual(entry["closer"], "nacho_1_9_9_3@hotmail.com")
        self.assertEqual(entry["state"], "CLOSED")
        self.assertEqual(entry["provider"], "claude")
        self.assertEqual(entry["role"], "implementer")
        self.assertEqual(entry["worktree"], "/repos/knowledge")
        self.assertEqual(entry["branch"], "feature/x")
        self.assertEqual(entry["base_commit"], "a" * 40)
        self.assertEqual(entry["result_commit"], "b" * 40)

    def test_closed_module_no_longer_reported_as_active(self):
        self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", module="knowledge")
        self.emit(flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", module="knowledge", state="SUCCESS")
        self.emit(flog.MODULE_CLOSED, module="knowledge", state="CLOSED", closer="ops")
        self.assertEqual(self.ledger.status()["active_workers"], [])
        self.assertEqual(self.ledger.modules()["knowledge"]["state"], "CLOSED")


class PartialFailedExecutionTests(LedgerTestBase):
    def test_partial_execution_is_recorded_with_reason(self):
        self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", module="knowledge", provider="claude")
        self.emit(
            flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", module="knowledge", provider="claude",
            state="PARTIAL", state_reason="EVIDENCE_FINALIZATION_FAILED",
        )
        entry = self.ledger.modules()["knowledge"]
        self.assertEqual(entry["state"], "PARTIAL")
        self.assertEqual(entry["state_reason"], "EVIDENCE_FINALIZATION_FAILED")

    def test_failed_execution_is_recorded(self):
        self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", module="billing", provider="codex")
        self.emit(
            flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", module="billing", provider="codex",
            state="FAILED", state_reason="CLAUDE_ERROR",
        )
        self.assertEqual(self.ledger.modules()["billing"]["state"], "FAILED")


class MalformedTrailingEventTests(LedgerTestBase):
    def test_incomplete_trailing_line_is_skipped_not_raised(self):
        self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1")
        self.emit(flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", state="SUCCESS")
        with open(self.root / flog.EVENTS_FILENAME, "a", encoding="utf-8") as fh:
            fh.write('{"schema_version": 1, "event_type": "WORKER_STARTED", "worker_id": "w2"')  # torn write
        events, skipped = flog.read_events(self.root)
        self.assertEqual(len(events), 2)
        self.assertEqual(skipped, 1)

    def test_malformed_middle_line_is_skipped_and_surrounding_events_survive(self):
        self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1")
        path = self.root / flog.EVENTS_FILENAME
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("not json at all\n")
        self.emit(flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", state="SUCCESS")
        events, skipped = flog.read_events(self.root)
        self.assertEqual(skipped, 1)
        self.assertEqual([e["event_type"] for e in events], [flog.WORKER_STARTED, flog.WORKER_FINISHED])

    def test_missing_events_file_reads_as_empty_not_an_error(self):
        events, skipped = flog.read_events(self.root)
        self.assertEqual((events, skipped), ([], 0))

    def test_unrecognized_event_type_in_file_is_skipped(self):
        path = self.root
        path.mkdir(parents=True, exist_ok=True)
        with open(path / flog.EVENTS_FILENAME, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"schema_version": 1, "event_type": "SOMETHING_FUTURE", "event_id": "x"}) + "\n")
        events, skipped = flog.read_events(self.root)
        self.assertEqual((events, skipped), ([], 1))


class DeterministicMaterializationTests(LedgerTestBase):
    def test_same_events_in_same_order_always_materialize_identically(self):
        self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", module="knowledge", provider="claude")
        self.emit(
            flog.WORKER_FINISHED, pipeline_id="p1", worker_id="w1", module="knowledge", provider="claude",
            state="SUCCESS",
        )
        events, _ = flog.read_events(self.root)
        first = flog.materialize_modules(events)
        second = flog.materialize_modules(list(events))
        self.assertEqual(first, second)

    def test_materialization_never_reads_the_clock(self):
        events, _ = flog.read_events(self.root)
        # An empty ledger materializes to an empty mapping, deterministically.
        self.assertEqual(flog.materialize_modules(events), {})


class NoSecretLeakageTests(LedgerTestBase):
    def test_extra_drops_secret_shaped_keys(self):
        event = self.emit(
            flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1",
            extra={"api_key": "sk-should-not-persist", "note": "ok"},
        )
        self.assertNotIn("api_key", event.get("extra", {}))
        self.assertEqual(event["extra"], {"note": "ok"})
        raw = (self.root / flog.EVENTS_FILENAME).read_text(encoding="utf-8")
        self.assertNotIn("sk-should-not-persist", raw)

    def test_extra_drops_oversized_values(self):
        huge = "x" * 10_000
        event = self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", extra={"blob": huge})
        self.assertNotIn("blob", event.get("extra", {}))
        raw = (self.root / flog.EVENTS_FILENAME).read_text(encoding="utf-8")
        self.assertNotIn(huge, raw)

    def test_event_schema_has_no_prompt_or_transcript_field(self):
        forbidden = {"prompt", "prompt_text", "transcript", "stdout", "stderr", "token", "credential", "password"}
        self.assertFalse(forbidden & set(flog._EVENT_FIELDS))

    def test_append_rejects_arbitrary_fields_outside_the_schema(self):
        with self.assertRaises(flog.FactoryLedgerError):
            self.emit(flog.WORKER_STARTED, pipeline_id="p1", worker_id="w1", prompt="do the thing")


if __name__ == "__main__":
    unittest.main()
