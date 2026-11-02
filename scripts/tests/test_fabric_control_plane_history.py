"""FCP-11D-04: Fabric Control Plane history of the factory ledger.

Factory and state roots are private temporary directories spelled by their
physical path. Ledger events are written by the ledger's OWN producer
(`runner_factory_ledger.FactoryLedger.append`, fixed clock and ids) or as
synthetic raw lines for malformed / adversarial cases; snapshots come from
FCP-11B-02 over the Runner's own persistence (`PipelineRunner._init_state` /
`_save_worker`, fixed clock, no executor, provider or Git). Nothing is
executed, sent anywhere or skipped.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import random
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_control_plane_history as hist
from scripts.ai import fabric_control_plane_snapshot as snap
from scripts.ai import fabric_resource_quota_report as qrep
from scripts.ai import runner_factory_ledger as flog
from scripts.ai import runner_pipeline as rp
from scripts.tests.test_fabric_resource_quota_report import (
    canonical_temp_dir, directory_alias, remove_directory_alias,
)

MODULE_PATH = Path(hist.__file__)
AS_OF = "2026-11-02T12:00:00Z"
T0 = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
SECRET = "sk-ant-api03-SYNTHETICSECRETVALUE0123456789"
PRIVATE_PATH = "C:/private/client-data/worktree"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
PID, PID2 = "fcp11-pipe", "fcp11-pipe-b"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "ledger_write_allowed",
             "state_persisted", "process_control_allowed", "git_allowed")


def tree_state(root: Path) -> dict:
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


def raw_event(event_id="e" * 32, event_type=flog.WORKER_STARTED, ts="2026-11-02T10:00:00+00:00", **fields) -> dict:
    event = {"schema_version": flog.LEDGER_SCHEMA_VERSION, "event_id": event_id, "event_type": event_type,
             "timestamp_utc": ts}
    for name in flog._EVENT_FIELDS:
        event[name] = fields.pop(name, None)
    event.update(fields)
    return event


class HistoryTestBase(unittest.TestCase):
    def setUp(self):
        self.root = canonical_temp_dir("fcp11d04-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.factory = self.root / "factory"
        self.state = self.root / "state"
        self.factory.mkdir()
        self.state.mkdir()
        self.tick = 0
        self.ids = iter(f"{i:032x}" for i in range(1, 10_000))
        self.ledger = flog.FactoryLedger(self.factory, clock=self.clock, id_factory=lambda: next(self.ids))

    def clock(self) -> datetime:
        self.tick += 1
        return T0 + timedelta(minutes=self.tick)

    def append(self, event_type, pid=PID, wid="w1", **fields) -> dict:
        fields.setdefault("provider", "claude")
        return self.ledger.append(event_type, pipeline_id=pid, worker_id=wid, **fields)

    def run_worker(self, pid=PID, wid="w1", state="SUCCESS", **fields):
        """The Runner's own emission sequence for one finished attempt."""
        common = dict(worktree=PRIVATE_PATH, module="m1", role="builder", project="proj", **fields)
        self.append(flog.WORKER_STARTED, pid, wid, state="RUNNING", branch="feature/" + SECRET,
                    base_commit=COMMIT, **common)
        self.append(flog.WORKER_FINISHED, pid, wid, state=state, state_reason="DONE:" + SECRET,
                    result_commit=OTHER_COMMIT, **common)
        self.append(flog.WORK_PRODUCT_CREATED, pid, wid, state=state, result_commit=OTHER_COMMIT, **common)
        self.append(flog.MODULE_STATE_CHANGED, pid, wid, state=state, **common)

    def write_lines(self, *lines, newline=True):
        data = b"\n".join(l if isinstance(l, bytes) else json.dumps(l).encode() for l in lines)
        (self.factory / flog.EVENTS_FILENAME).write_bytes(data + (b"\n" if newline else b""))

    def take(self, root=None, **kw) -> hist.ControlPlaneHistory:
        return hist.take_history(str(root or self.factory), AS_OF, **kw)

    def make_snapshot(self, workers=(("w1", "SUCCESS"),), pid=PID, **kw) -> snap.ControlPlaneSnapshot:
        specs = [rp.WorkerSpec(id=wid, worktree=PRIVATE_PATH, work_order=PRIVATE_PATH + "/wo.md", mode="write",
                               worktree_top=PRIVATE_PATH) for wid, _ in workers]
        runner = rp.PipelineRunner(rp.Manifest(pipeline_id=pid, workers=specs, sha256="b" * 64, raw={}),
                                   self.state, self_worktree=Path(PRIVATE_PATH), clock=lambda: T0,
                                   heartbeat_interval_seconds=None)
        runner._started_at = T0
        runner._init_state()
        for wid, state in workers:
            runner.workers[wid].state = state
            runner._save_worker(runner.workers[wid])
        runner._save_pipeline()
        return snap.take_snapshot(str(self.state), AS_OF, **kw)

    @staticmethod
    def correlation(history, pid=PID, wid="w1") -> hist.LedgerCorrelation:
        return next(c for c in history.correlations if (c.pipeline_id, c.worker_id) == (pid, wid))

    def alias(self, target: Path, alias: Path) -> None:
        directory_alias(target, alias)
        self.addCleanup(lambda: os.path.lexists(alias) and remove_directory_alias(alias))


# ---------------------------------------------------------------------------
class NativeEventTests(HistoryTestBase):
    def test_native_events_keep_their_identity_order_and_fingerprint(self):
        self.run_worker()
        h = self.take()
        lines = (self.factory / flog.EVENTS_FILENAME).read_bytes().split(b"\n")
        native = [json.loads(l) for l in lines if l]
        self.assertEqual((h.root_condition, h.ledger_condition, h.lines_total, h.rejected, h.events_total),
                         (cp.PRESENT, cp.PRESENT, 4, (), 4))
        self.assertEqual([e.source_event_id for e in h.events], [n["event_id"] for n in native])
        self.assertEqual([e.order for e in h.events], [1, 2, 3, 4])
        self.assertEqual([e.source_line for e in h.events], [1, 2, 3, 4])
        self.assertEqual([e.fingerprint for e in h.events], [hashlib.sha256(l).hexdigest() for l in lines if l])
        self.assertEqual([e.category for e in h.events], [hist.CATEGORY_START, hist.CATEGORY_FINISH,
                                                          hist.CATEGORY_WORK_PRODUCED, hist.CATEGORY_STATE_CHANGE])
        first, finish = h.events[0], h.events[1]
        self.assertEqual((first.timestamp_utc, first.recorded_state, first.base_commit, first.module, first.role,
                          first.project, first.provider), ("2026-11-02T10:01:00Z", "RUNNING", COMMIT, "m1",
                                                           "builder", "proj", "claude"))
        self.assertEqual((finish.recorded_state, finish.state_reason, finish.result_commit),
                         ("SUCCESS", "DONE", OTHER_COMMIT))
        ref = h.observation.evidence[0]
        self.assertEqual((ref.kind, ref.content_sha256),
                         ("FACTORY_EVENTS", hashlib.sha256((self.factory / "events.jsonl").read_bytes()).hexdigest()))
        for flag in ALL_FLAGS:
            self.assertIs(getattr(h, flag), False)

    def test_every_ledger_event_type_has_a_category(self):
        self.assertEqual(set(hist.EVENT_CATEGORY), flog.EVENT_TYPES)
        for event_type in sorted(flog.EVENT_TYPES):
            self.append(event_type, state="CREATED", certification_status="PASSED", closer="someone " + SECRET)
        h = self.take()
        self.assertEqual(sorted(e.event_type for e in h.events), sorted(flog.EVENT_TYPES))
        self.assertEqual({e.category for e in h.events}, set(hist.CATEGORIES))

    def test_withheld_native_fields_never_reach_the_output(self):
        self.run_worker(extra={"note": SECRET, "path": PRIVATE_PATH})
        self.append(flog.MODULE_CLOSED, module="m1", closer="Jane " + SECRET)
        text = hist.canonical_json(self.take())
        for leaked in (SECRET, PRIVATE_PATH, "client-data", "feature/", "Jane"):
            self.assertNotIn(leaked, text)
        event = json.loads(text)["events"][0]
        for withheld in cp.LEDGER_WITHHELD_FIELDS + ("state", "event_id"):
            self.assertNotIn(withheld, event)

    def test_public_fields_are_exactly_the_contract_ledger_allowlist(self):
        native_public = {hist._NATIVE_NAME.get(f, f) for f in hist.EVENT_PUBLIC_FIELDS}
        self.assertEqual(native_public, set(cp.LEDGER_PUBLIC_FIELDS))
        native_keys = set(flog._EVENT_FIELDS) | {"schema_version", "event_id", "event_type", "timestamp_utc", "extra"}
        self.assertEqual(native_keys, set(cp.LEDGER_PUBLIC_FIELDS) | set(cp.LEDGER_WITHHELD_FIELDS))

    def test_history_is_read_only_and_reads_only_the_event_log(self):
        self.run_worker()
        (self.factory / flog.MODULES_FILENAME).write_text(json.dumps({"m1": {"state": "SUCCESS", "x": SECRET}}))
        snapshot = self.make_snapshot()
        before = tree_state(self.root)
        with mock.patch.object(hist.qrep, "read_input_bytes", wraps=qrep.read_input_bytes) as reads, \
                mock.patch.object(flog, "read_events", side_effect=AssertionError("native reader")), \
                mock.patch.object(flog.FactoryLedger, "append", side_effect=AssertionError("write")), \
                mock.patch.object(hist.snap, "_list_dir", side_effect=AssertionError("listing")):
            h = self.take(snapshot=snapshot)
        self.assertEqual([os.path.basename(c.args[0]) for c in reads.call_args_list], [flog.EVENTS_FILENAME])
        self.assertTrue(os.path.normcase(reads.call_args.args[0]).startswith(os.path.normcase(str(self.factory))))
        self.assertEqual(tree_state(self.root), before)
        self.assertNotIn(SECRET, hist.canonical_json(h))


# ---------------------------------------------------------------------------
class OrderAndDuplicateTests(HistoryTestBase):
    def lines(self):
        return [raw_event(f"{i:032x}", flog.WORKER_STARTED if i % 2 else flog.WORKER_FINISHED,
                          f"2026-11-02T10:{i:02d}:00+00:00", pipeline_id=PID, worker_id=f"w{i}") for i in range(1, 9)]

    def test_disordered_lines_give_the_native_order(self):
        ordered = self.lines()
        self.write_lines(*ordered)
        a = self.take()
        shuffled = ordered[:]
        random.Random(7).shuffle(shuffled)
        self.write_lines(*shuffled)
        b = self.take()
        strip = lambda h: [{k: v for k, v in e.to_dict().items() if k != "source_line"} for e in h.events]
        self.assertEqual(strip(a), strip(b))
        self.assertEqual([e.source_event_id for e in b.events], [e["event_id"] for e in ordered])
        self.assertNotEqual([e.source_line for e in a.events], [e.source_line for e in b.events])
        self.assertNotEqual(a.revision, b.revision)  # different bytes, different seal

    def test_equal_instants_break_ties_by_event_id_then_line(self):
        ts = "2026-11-02T10:00:00+00:00"
        self.write_lines(raw_event("b" * 32, ts=ts), raw_event("a" * 32, ts=ts, worker_id="w2"))
        self.assertEqual([e.source_event_id for e in self.take().events], ["a" * 32, "b" * 32])

    def test_instants_are_ordered_by_value_not_by_text(self):
        self.write_lines(raw_event("a" * 32, ts="2026-11-02T10:00:00.500000+00:00"),
                         raw_event("b" * 32, ts="2026-11-02T10:00:00Z"))
        self.assertEqual([e.source_event_id for e in self.take().events], ["b" * 32, "a" * 32])

    def test_identical_duplicate_lines_collapse_and_are_flagged(self):
        line = raw_event("a" * 32, pipeline_id=PID, worker_id="w1")
        self.write_lines(line, raw_event("b" * 32, flog.WORKER_FINISHED, "2026-11-02T10:05:00+00:00",
                                         pipeline_id=PID, worker_id="w1", state="SUCCESS"), line)
        h = self.take()
        self.assertEqual((h.lines_total, h.events_total), (3, 2))
        dup = h.events[0]
        self.assertEqual((dup.copies, dup.anomalies, dup.source_line), (2, (hist.DUPLICATE_EVENT_COPIES,), 1))

    def test_conflicting_event_ids_keep_every_copy_and_trust_none(self):
        self.write_lines(raw_event("a" * 32, pipeline_id=PID, worker_id="w1", state="RUNNING"),
                         raw_event("a" * 32, flog.WORKER_FINISHED, pipeline_id=PID, worker_id="w1", state="SUCCESS"))
        h = self.take(snapshot=self.make_snapshot())
        self.assertEqual([e.anomalies for e in h.events], [(hist.EVENT_ID_CONFLICT,)] * 2)
        c = self.correlation(h)
        self.assertEqual((c.agreement, c.ledger_events, c.ledger_last_recorded_state),
                         (snap.AGREEMENT_UNVERIFIABLE, 0, None))

    def test_replay_is_deterministic(self):
        self.run_worker()
        snapshot = self.make_snapshot()
        first = hist.canonical_json(self.take(snapshot=snapshot))
        self.assertEqual(first, hist.canonical_json(self.take(snapshot=snapshot)))
        doc = json.loads(first)
        self.assertEqual((doc["schema"], doc["snapshot_revision"]), (hist.SCHEMA, snapshot.revision))
        path = self.factory / flog.EVENTS_FILENAME
        path.write_bytes(path.read_bytes().replace(b'"builder"', b'"reviewer"', 1))
        self.assertNotEqual(first, hist.canonical_json(self.take(snapshot=snapshot)))


# ---------------------------------------------------------------------------
class MalformedLedgerTests(HistoryTestBase):
    def test_malformed_lines_are_counted_by_cause_and_never_echoed(self):
        good = raw_event("a" * 32)
        self.write_lines(
            good, b"{not json " + SECRET.encode(), b"[1, 2]", b'"' + SECRET.encode() + b'"',
            b'{"a": 1, "a": 2}', b'{"x": NaN}', b"\xff\xfe" + SECRET.encode(), b"\xef\xbb\xbf" + json.dumps(good).encode(),
            json.dumps({"n": [[[[[[[[[[[[[1]]]]]]]]]]]]]}).encode(),
            raw_event("b" * 32, event_type="WORKER_EXPLODED"), raw_event("c" * 32, event_type=SECRET),
            raw_event("d" * 32, schema_version=2), raw_event("e" * 32, schema_version="1"),
            {k: v for k, v in raw_event("f" * 32).items() if k != "event_id"},
            raw_event(SECRET), raw_event("../../etc"), raw_event(7),
            raw_event("1" * 32, ts=None), raw_event("2" * 32, ts="2026-11-02T10:00:00"),
            raw_event("3" * 32, ts="2026-11-02T12:00:00+02:00"), raw_event("4" * 32, ts=SECRET),
            b"", b"   ", newline=True,
        )
        h = self.take()
        self.assertEqual(dict(h.rejected), {cp.SOURCE_NOT_JSON: 7, cp.SOURCE_TOO_LARGE: 1, cp.VALUE_UNRECOGNIZED: 2,
                                            cp.SCHEMA_UNSUPPORTED: 2, cp.FIELD_ABSENT: 2, cp.FIELD_MALFORMED: 6})
        self.assertEqual((h.lines_total, h.events_total, [e.source_event_id for e in h.events]), (21, 1, ["a" * 32]))
        text = hist.canonical_json(h)
        for leaked in (SECRET, "WORKER_EXPLODED", "etc"):
            self.assertNotIn(leaked, text)

    def test_torn_trailing_line_is_rejected_and_the_rest_kept(self):
        line = json.dumps(raw_event("b" * 32)).encode()
        self.write_lines(raw_event("a" * 32), line[: len(line) // 2], newline=False)
        h = self.take()
        self.assertEqual((h.rejected, h.events_total), (((cp.SOURCE_NOT_JSON, 1),), 1))

    def test_crlf_lines_are_accepted(self):
        (self.factory / flog.EVENTS_FILENAME).write_bytes(
            json.dumps(raw_event("a" * 32)).encode() + b"\r\n" + json.dumps(raw_event("b" * 32)).encode() + b"\r\n")
        self.assertEqual(self.take().events_total, 2)

    def test_malformed_optional_fields_are_withheld_and_named(self):
        self.write_lines(raw_event(
            "a" * 32, pipeline_id="x-" + SECRET, worker_id="../w", provider="Claude Code!", role=7,
            module="CON", module_version="1.", base_commit="abc", result_commit=COMMIT.upper(),
            state="running", state_reason=["DONE"], certification_status=SECRET, project=PRIVATE_PATH))
        (e,) = self.take().events
        self.assertEqual(e.malformed_fields, (
            "project", "module", "module_version", "pipeline_id", "worker_id", "provider", "role", "base_commit",
            "result_commit", "recorded_state", "state_reason", "certification_status"))
        self.assertEqual({n: getattr(e, n) for n in hist._OPTIONAL_FIELDS}, dict.fromkeys(hist._OPTIONAL_FIELDS))

    def test_reason_prose_without_a_code_is_withheld_not_malformed(self):
        self.write_lines(raw_event("a" * 32, state_reason="waiting for a,b " + SECRET))
        (e,) = self.take().events
        self.assertEqual((e.state_reason, e.malformed_fields), (None, ()))

    def test_unknown_native_keys_are_ignored(self):
        self.write_lines(raw_event("a" * 32, prompt=SECRET, stdout=SECRET, worktree=PRIVATE_PATH))
        h = self.take()
        self.assertEqual(h.events_total, 1)
        self.assertNotIn(SECRET, hist.canonical_json(h))


# ---------------------------------------------------------------------------
class AbsenceAndPathTests(HistoryTestBase):
    def assertShowsNothing(self, h, condition, cause):
        self.assertEqual((h.ledger_condition, h.ledger_cause, h.events, h.events_total, h.lines_total,
                          h.correlations), (condition, cause, (), 0, 0, ()))
        self.assertNotIn("SUCCESS", hist.canonical_json(h))

    def test_absent_ledger_is_missing_never_success(self):
        h = self.take(snapshot=self.make_snapshot())
        self.assertShowsNothing(h, cp.MISSING, cp.SOURCE_ABSENT)
        self.assertEqual((h.root_condition, h.to_dict()["ledger_actor"]), (cp.PRESENT, "RUNNER"))

    def test_empty_ledger_is_present_with_no_events(self):
        (self.factory / flog.EVENTS_FILENAME).write_bytes(b"")
        h = self.take()
        self.assertEqual((h.ledger_condition, h.events_total, h.next_offset), (cp.PRESENT, 0, None))

    def test_unreadable_roots_show_nothing(self):
        for root in (self.root / "absent", "relative/factory", self.factory / ".." / "factory"):
            with self.subTest(root=str(root)):
                h = hist.take_history(str(root), AS_OF)
                self.assertNotEqual(h.root_condition, cp.PRESENT)
                self.assertEqual((h.observation.evidence, h.events), ((), ()))

    def test_root_through_an_alias_is_refused(self):
        self.run_worker()
        self.alias(self.factory, self.root / "alias")
        h = hist.take_history(str(self.root / "alias"), AS_OF)
        self.assertEqual((h.root_condition, h.root_cause, h.events), (cp.UNAVAILABLE, cp.LINK_REFUSED, ()))

    def test_event_log_that_is_a_link_or_directory_is_refused(self):
        outside = canonical_temp_dir("fcp11d04-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (outside / "secret.jsonl").write_text(json.dumps(raw_event("a" * 32, module=SECRET)))
        (self.factory / flog.EVENTS_FILENAME).mkdir()
        self.assertShowsNothing(self.take(), cp.UNAVAILABLE, cp.SOURCE_UNREADABLE)
        (self.factory / flog.EVENTS_FILENAME).rmdir()
        try:
            os.symlink(outside / "secret.jsonl", self.factory / flog.EVENTS_FILENAME)
        except OSError:  # no symlink privilege: a junction cannot target a file, use a directory alias
            self.alias(outside, self.factory / flog.EVENTS_FILENAME)
        self.assertShowsNothing(self.take(), cp.UNAVAILABLE, cp.LINK_REFUSED)

    def test_size_limits_refuse_before_reading(self):
        self.run_worker()
        with mock.patch.object(hist.qrep, "read_input_bytes", wraps=qrep.read_input_bytes) as reads:
            h = self.take(max_file_bytes=10)
        self.assertShowsNothing(h, cp.UNAVAILABLE, cp.SOURCE_TOO_LARGE)
        reads.assert_not_called()
        (self.factory / flog.EVENTS_FILENAME).write_bytes(b"\n" * (qrep.MAX_INPUT_BYTES + 1))
        self.assertShowsNothing(self.take(), cp.UNAVAILABLE, cp.SOURCE_TOO_LARGE)

    def test_append_during_the_read_is_changed_not_merged(self):
        self.run_worker()
        real = qrep.read_input_bytes

        def appending(path):
            data = real(path)
            self.append(flog.WORKER_STARTED, wid="w9")
            return data
        with mock.patch.object(hist.qrep, "read_input_bytes", side_effect=appending):
            self.assertShowsNothing(self.take(), cp.UNAVAILABLE, cp.SOURCE_CHANGED_DURING_READ)

    def test_unexpected_reader_failures_degrade_safely(self):
        self.run_worker()
        for error in (OSError("boom " + SECRET), ValueError(SECRET), qrep.ReportError("REPORT_INPUT_FILE_INVALID")):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(hist.qrep, "read_input_bytes", side_effect=error):
                h = self.take()
                self.assertShowsNothing(h, cp.UNAVAILABLE, cp.SOURCE_UNREADABLE)
                self.assertNotIn(SECRET, hist.canonical_json(h))


# ---------------------------------------------------------------------------
class PaginationAndFilterTests(HistoryTestBase):
    def setUp(self):
        super().setUp()
        for wid in ("w1", "w2", "w3"):
            self.run_worker(wid=wid)

    def test_pages_cover_the_ordered_events_exactly_once(self):
        seen, offset = [], 0
        while offset is not None:
            h = self.take(offset=offset, limit=5)
            self.assertLessEqual(len(h.events), 5)
            seen += [e.order for e in h.events]
            offset = h.next_offset
        self.assertEqual(seen, list(range(1, 13)))
        beyond = self.take(offset=50)
        self.assertEqual((beyond.events, beyond.matching, beyond.next_offset), ((), 12, None))

    def test_identity_and_type_filters_reuse_the_ledger_filter(self):
        h = self.take(worker_id="w2", event_type=flog.WORKER_FINISHED)
        self.assertEqual([(e.worker_id, e.event_type) for e in h.events], [("w2", flog.WORKER_FINISHED)])
        self.assertEqual((h.matching, h.events_total, dict(h.filters)),
                         (1, 12, {"worker_id": "w2", "event_type": flog.WORKER_FINISHED}))
        self.assertEqual(self.take(module="m1", role="builder", provider="claude", pipeline_id=PID).matching, 12)
        self.assertEqual(self.take(pipeline_id=PID2).matching, 0)
        with mock.patch.object(flog, "filter_events", wraps=flog.filter_events) as native:
            self.take(role="builder")
        native.assert_called_once()

    def test_time_range_is_since_inclusive_until_exclusive(self):
        h = self.take(since_utc="2026-11-02T10:02:00Z", until_utc="2026-11-02T10:05:00Z")
        self.assertEqual([e.timestamp_utc for e in h.events],
                         ["2026-11-02T10:02:00Z", "2026-11-02T10:03:00Z", "2026-11-02T10:04:00Z"])

    def test_invalid_arguments_raise_without_echo(self):
        bad = ({"offset": -1}, {"offset": True}, {"limit": 0}, {"limit": hist.MAX_PAGE_SIZE + 1},
               {"max_file_bytes": 0}, {"max_file_bytes": hist.MAX_FILE_BYTES + 1}, {"pipeline_id": SECRET},
               {"worker_id": "../w"}, {"provider": "x y"}, {"event_type": "NOPE"},
               {"since_utc": "2026-11-02T10:00:00"}, {"until_utc": "2026-11-02T12:00:00+02:00"})
        for kw in bad:
            with self.subTest(kw=kw), self.assertRaises(ValueError) as caught:
                self.take(**kw)
            self.assertNotIn(SECRET, str(caught.exception))
        with self.assertRaises(ValueError):
            hist.take_history(str(self.factory), "2026-11-02T12:00:00+00:00")
        with self.assertRaises(TypeError):
            self.take(snapshot={"revision": "x"})


# ---------------------------------------------------------------------------
class CorrelationTests(HistoryTestBase):
    def test_consistent_and_divergent_by_exact_identity(self):
        self.run_worker(wid="w1", state="SUCCESS")
        self.run_worker(wid="w2", state="FAILED")
        h = self.take(snapshot=self.make_snapshot((("w1", "SUCCESS"), ("w2", "SUCCESS"))))
        w1, w2 = self.correlation(h, wid="w1"), self.correlation(h, wid="w2")
        self.assertEqual((w1.agreement, w1.ledger_last_recorded_state, w1.snapshot_record.source_value),
                         (snap.AGREEMENT_CONSISTENT, "SUCCESS", "SUCCESS"))
        self.assertEqual((w2.agreement, w2.ledger_last_recorded_state), (snap.AGREEMENT_DIVERGENT, "FAILED"))
        self.assertEqual((w1.ledger_events, w1.ledger_starts, w1.ledger_finishes, w1.ledger_unmatched_start),
                         (4, 1, 1, False))

    def test_two_pipelines_with_equal_worker_ids_never_mix(self):
        self.run_worker(pid=PID, wid="w1", state="SUCCESS")
        self.append(flog.WORKER_STARTED, pid=PID2, wid="w1", state="RUNNING")
        h = self.take(snapshot=self.make_snapshot())
        a, b = self.correlation(h, PID), self.correlation(h, PID2)
        self.assertEqual((a.agreement, a.ledger_unmatched_start), (snap.AGREEMENT_CONSISTENT, False))
        self.assertEqual((b.in_snapshot, b.ledger_events, b.ledger_unmatched_start, b.agreement),
                         (False, 1, True, hist.AGREEMENT_NOT_IN_SNAPSHOT))

    def test_rerun_of_the_same_pipeline_counts_both_attempts(self):
        self.run_worker(state="FAILED")
        self.append(flog.WORKER_STARTED, state="RUNNING")
        c = self.correlation(self.take(snapshot=self.make_snapshot((("w1", "RUNNING"),))))
        self.assertEqual((c.ledger_starts, c.ledger_finishes, c.ledger_unmatched_start, c.ledger_last_recorded_state,
                          c.agreement), (2, 1, True, "RUNNING", snap.AGREEMENT_CONSISTENT))

    def test_unmatched_start_is_never_presented_as_running(self):
        self.append(flog.WORKER_STARTED, state="RUNNING")
        h = self.take(snapshot=self.make_snapshot((("w1", "SUCCESS"),)))
        c = self.correlation(h)
        self.assertEqual((c.ledger_unmatched_start, c.agreement), (True, snap.AGREEMENT_DIVERGENT))
        event = h.to_dict()["events"][0]
        for inferred in ("lifecycle", "runner_outcome", "active", "running", "status"):
            self.assertNotIn(inferred, event)
        self.assertNotIn("active_workers", hist.canonical_json(h))
        self.assertNotIn("modules", h.to_dict())

    def test_ledger_success_without_snapshot_evidence_is_never_consistent(self):
        self.run_worker(state="SUCCESS")
        snapshot = self.make_snapshot((("w1", "SUCCESS"),))
        (self.state / PID / "workers" / "w1" / "worker.json").write_text("{corrupt")
        c = self.correlation(self.take(snapshot=snap.take_snapshot(str(self.state), AS_OF)))
        self.assertEqual((c.snapshot_record.condition, c.agreement), (cp.CORRUPT, snap.AGREEMENT_UNVERIFIABLE))
        self.assertEqual(self.correlation(self.take(snapshot=snapshot)).agreement, snap.AGREEMENT_CONSISTENT)

    def test_snapshot_worker_absent_from_a_complete_ledger_is_not_in_ledger(self):
        self.run_worker(wid="w1")
        h = self.take(snapshot=self.make_snapshot((("w1", "SUCCESS"), ("w2", "QUEUED"))))
        c = self.correlation(h, wid="w2")
        self.assertEqual((c.in_snapshot, c.ledger_events, c.agreement), (True, 0, hist.AGREEMENT_NOT_IN_LEDGER))

    def test_an_incomplete_ledger_cannot_prove_absence(self):
        self.run_worker(wid="w1")
        with open(self.factory / flog.EVENTS_FILENAME, "ab") as fh:
            fh.write(b"{torn\n")
        c = self.correlation(self.take(snapshot=self.make_snapshot((("w1", "SUCCESS"), ("w2", "QUEUED")))), wid="w2")
        self.assertEqual(c.agreement, snap.AGREEMENT_UNVERIFIABLE)

    def test_an_incomplete_snapshot_cannot_prove_absence(self):
        self.append(flog.WORKER_FINISHED, wid="w3", state="SUCCESS")
        snapshot = self.make_snapshot((("w1", "SUCCESS"), ("w2", "SUCCESS"), ("w3", "SUCCESS")), max_workers=1)
        self.assertEqual(self.correlation(self.take(snapshot=snapshot), wid="w3").agreement,
                         snap.AGREEMENT_UNVERIFIABLE)
        self.append(flog.WORKER_FINISHED, pid=PID2, wid="w1", state="SUCCESS")
        snapshot = snap.take_snapshot(str(self.root / "nowhere"), AS_OF)
        self.assertEqual(self.correlation(self.take(snapshot=snapshot), PID2).agreement, snap.AGREEMENT_UNVERIFIABLE)

    def test_events_with_unusable_ids_are_never_correlated(self):
        self.write_lines(raw_event("a" * 32, pipeline_id=PID, worker_id=SECRET, state="SUCCESS"),
                         raw_event("b" * 32, pipeline_id=None, worker_id="w1", state="SUCCESS"))
        h = self.take(snapshot=self.make_snapshot((("w1", "SUCCESS"),)))
        (c,) = h.correlations
        self.assertEqual((c.worker_id, c.ledger_events, c.agreement), ("w1", 0, hist.AGREEMENT_NOT_IN_LEDGER))

    def test_no_correlations_without_a_snapshot_or_a_ledger(self):
        self.run_worker()
        h = self.take()
        self.assertEqual((h.snapshot_revision, h.correlations), (None, ()))
        (self.factory / flog.EVENTS_FILENAME).unlink()
        self.assertEqual(self.take(snapshot=self.make_snapshot()).correlations, ())

    def test_correlations_are_capped_and_counted(self):
        lines = [raw_event(f"{i:032x}", pipeline_id=PID, worker_id=f"w{i}") for i in range(1, 6)]
        self.write_lines(*lines)
        with mock.patch.object(hist, "MAX_CORRELATIONS", 3):
            h = self.take(snapshot=self.make_snapshot((("w1", "RUNNING"),)))
        self.assertEqual((len(h.correlations), h.correlations_omitted), (3, 2))


# ---------------------------------------------------------------------------
class InvariantTests(HistoryTestBase):
    def test_views_reject_impossible_claims(self):
        base = dict(source_event_id="a" * 32, source_line=1, order=1, fingerprint="0" * 64,
                    event_type=flog.WORKER_STARTED, timestamp_utc="2026-11-02T10:00:00Z")
        hist.LedgerEvent(**base)
        for over in ({"source_event_id": SECRET}, {"order": 0}, {"fingerprint": "x"}, {"event_type": "NOPE"},
                     {"timestamp_utc": "2026-11-02T10:00:00+00:00"}, {"copies": 2},
                     {"anomalies": (hist.DUPLICATE_EVENT_COPIES,)}, {"pipeline_id": "../p"},
                     {"recorded_state": "running"}, {"malformed_fields": ("state",)}, {"anomalies": ("NOPE",)}):
            with self.subTest(over=over), self.assertRaises(ValueError):
                hist.LedgerEvent(**{**base, **over})
        present = cp.observe_status(cp.SOURCE_WORKER_STATE, "SUCCESS")
        corr = dict(pipeline_id=PID, worker_id="w1", in_snapshot=True, agreement=snap.AGREEMENT_UNVERIFIABLE,
                    snapshot_record=present)
        hist.LedgerCorrelation(**corr)
        for over in ({"in_snapshot": False}, {"agreement": snap.AGREEMENT_CONSISTENT},
                     {"agreement": hist.AGREEMENT_NOT_IN_SNAPSHOT}, {"ledger_events": 1},
                     {"ledger_unmatched_start": True}, {"ledger_starts": 1}, {"agreement": "WINNER"}):
            with self.subTest(over=over), self.assertRaises(ValueError):
                hist.LedgerCorrelation(**{**corr, **over})

    def test_history_rejects_inconsistent_pages(self):
        self.run_worker()
        h = self.take()
        with self.assertRaises(ValueError):
            hist.ControlPlaneHistory(cp.ControlPlaneObservation(AS_OF), events=h.events, matching=4,
                                     events_total=4, lines_total=4)
        with self.assertRaises(ValueError):
            hist.ControlPlaneHistory(h.observation, lines_total=4, events_total=4, matching=4, events=h.events[:1])
        with self.assertRaises(ValueError):
            hist.ControlPlaneHistory(h.observation, correlations=(), correlations_omitted=1)
        with self.assertRaises(TypeError):
            hist.canonical_json(h.to_dict())


# ---------------------------------------------------------------------------
class StaticGovernanceTests(unittest.TestCase):
    def tree(self):
        return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    def test_module_imports_nothing_that_executes_or_mutates(self):
        imported = set()
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {node.module} | {f"{node.module}.{a.name}" for a in node.names}
        for name in imported:
            for word in ("subprocess", "socket", "urllib", "http", "requests", "shutil", "threading", "asyncio",
                         "multiprocessing", "datetime", "time", "sqlite3", "claude_runner", "runner_git",
                         "fabric_director", "claude_queue", "tempfile", "json", "uuid"):
                self.assertNotIn(word, name.split("."), name)

    def test_module_calls_no_writing_clock_process_or_native_reader_api(self):
        tree = self.tree()
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("environ", "getenv", "write_text", "write_bytes", "mkdir", "makedirs", "remove", "unlink",
                          "rename", "rmdir", "system", "popen", "Popen", "now", "utcnow", "sleep",
                          "symlink", "chmod", "_atomic_write_json", "_append_line", "FactoryLedger",
                          "read_events", "materialize_modules", "QueueLock", "MODULES_FILENAME", "LOCK_DIRNAME",
                          "read_text", "read_bytes", "listdir", "scandir"):
            self.assertNotIn(forbidden, names)
        self.assertNotIn("open", {n.func.id for n in ast.walk(tree)
                                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)})

    def test_contract_snapshot_ledger_and_reader_are_reused_not_redefined(self):
        defined = {n.name for n in ast.walk(self.tree()) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for duplicated in ("read_input_bytes", "admit_path", "parse_document", "_read_json", "_admit_root", "_probe",
                           "_identity", "observe_status", "valid_id", "valid_code", "reason_code", "EvidenceRef",
                           "filter_events", "factory_status", "normalized_utc", "_canonical",
                           "ControlPlaneObservation"):
            self.assertNotIn(duplicated, defined)
        self.assertIs(hist.cp, cp)
        self.assertIs(hist.snap, snap)
        self.assertIs(hist.flog, flog)
        self.assertEqual(cp.EvidenceRef("FACTORY_EVENTS", cp.MISSING, cause=cp.SOURCE_ABSENT).relative_parts(),
                         (flog.EVENTS_FILENAME,))
        self.assertLessEqual(hist.MAX_FILE_BYTES, qrep.MAX_INPUT_BYTES)


if __name__ == "__main__":
    unittest.main()
