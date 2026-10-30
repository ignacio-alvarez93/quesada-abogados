"""FCP-9A-02: UTC execution windows, deadlines and temporal eligibility.
Offline, synthetic windows and an injected clock only."""

from __future__ import annotations

import ast
import builtins
import copy
import dataclasses
import os
import socket
import subprocess
import time
import unittest
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_scheduler_contract as sc
from scripts.ai import fabric_scheduler_window as sw

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "ai" / "fabric_scheduler_window.py"
TEST_PATH = Path(__file__).resolve()

ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized")
AS_OF = "2026-10-30T10:00:00Z"
NB = "2026-10-30T09:00:00Z"
DL = "2026-10-30T11:00:00Z"


def window(not_before=None, deadline=None):
    return sw.ExecutionWindow(not_before_utc=not_before, deadline_utc=deadline)


def evaluate(not_before=None, deadline=None, as_of=AS_OF):
    return sw.evaluate_window(window(not_before, deadline), as_of=as_of)


def invalid_with(test, evaluation, *reasons):
    test.assertEqual(evaluation.status, sw.INVALID)
    for reason in reasons:
        test.assertIn(reason, evaluation.reasons)
    test.assertEqual((evaluation.as_of_utc, evaluation.not_before_utc, evaluation.deadline_utc,
                      evaluation.next_eligible_utc), (None, None, None, None))
    test.assertFalse(evaluation.eligible)
    return evaluation


class FixedClock:
    """Injected test clock: returns one preset instant and counts calls."""

    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


class MadridTZ(tzinfo):
    """Deterministic Europe/Madrid (CET/CEST, EU rule: last Sunday of March
    and of October at 01:00 UTC) with PEP 495 fold, so the tests need no
    tzdata on the host."""

    @staticmethod
    def _last_sunday(year, month):
        day = datetime(year, month + 1, 1) - timedelta(days=1)
        return day - timedelta(days=(day.weekday() + 1) % 7)

    def _dst_bounds_local_std(self, year):
        # Transitions expressed as standard-time (UTC+1) wall clock.
        start = self._last_sunday(year, 3).replace(hour=2)
        end = self._last_sunday(year, 10).replace(hour=2)
        return start, end

    def utcoffset(self, dt):
        start, end = self._dst_bounds_local_std(dt.year)
        wall = dt.replace(tzinfo=None, fold=0)
        if start <= wall < start + timedelta(hours=1):          # spring gap 02:00-03:00
            return timedelta(hours=2 if dt.fold == 0 else 1)
        if end <= wall < end + timedelta(hours=1):              # autumn fold 02:00-03:00
            return timedelta(hours=2 if dt.fold == 0 else 1)
        if start + timedelta(hours=1) <= wall < end:
            return timedelta(hours=2)
        return timedelta(hours=1)

    def dst(self, dt):
        return self.utcoffset(dt) - timedelta(hours=1)

    def tzname(self, dt):
        return "CEST" if self.dst(dt) else "CET"

    def fromutc(self, dt):
        start, end = self._dst_bounds_local_std(dt.year)
        std = dt.replace(tzinfo=None) + timedelta(hours=1)
        if start <= std < end - timedelta(hours=1):
            return (std + timedelta(hours=1)).replace(tzinfo=self)
        if end - timedelta(hours=1) <= std < end:
            return (std + timedelta(hours=1)).replace(tzinfo=self, fold=0)
        if end <= std < end + timedelta(hours=1):
            return std.replace(tzinfo=self, fold=1)
        return std.replace(tzinfo=self)


MADRID = MadridTZ()


class PositiveWindowTests(unittest.TestCase):
    def test_inside_window_is_ready_with_explicit_next_eligible(self):
        ev = evaluate(NB, DL)
        self.assertEqual(ev.status, sw.READY)
        self.assertEqual(ev.reasons, ())
        self.assertEqual(ev.next_eligible_utc, AS_OF)
        self.assertEqual((ev.seconds_until_eligible, ev.seconds_until_deadline), (0, 3600))
        self.assertTrue(ev.eligible)

    def test_unbounded_window_is_ready(self):
        ev = evaluate()
        self.assertEqual((ev.status, ev.not_before_utc, ev.deadline_utc), (sw.READY, None, None))
        self.assertIsNone(ev.seconds_until_deadline)

    def test_before_not_before_waits_until_it(self):
        ev = evaluate("2026-10-30T12:30:00Z", "2026-10-30T18:00:00Z")
        self.assertEqual(ev.status, sw.WAIT_UNTIL)
        self.assertEqual(ev.reasons, (sw.WINDOW_NOT_OPEN,))
        self.assertEqual(ev.next_eligible_utc, "2026-10-30T12:30:00Z")
        self.assertEqual((ev.seconds_until_eligible, ev.seconds_until_deadline), (9000, 28800))
        self.assertFalse(ev.eligible)

    def test_not_before_is_inclusive_like_runner(self):
        self.assertEqual(evaluate(AS_OF).status, sw.READY)
        ev = evaluate("2026-10-30T10:00:00.000001Z")
        self.assertEqual((ev.status, ev.seconds_until_eligible), (sw.WAIT_UNTIL, 1))

    def test_deadline_is_exclusive_like_runner(self):
        ev = evaluate(deadline=AS_OF)
        self.assertEqual((ev.status, ev.reasons, ev.next_eligible_utc), (sw.EXPIRED, (sw.WINDOW_EXPIRED,), None))
        self.assertEqual(evaluate(deadline="2026-10-30T10:00:00.000001Z").status, sw.READY)

    def test_past_deadline_is_expired_never_eligible(self):
        ev = evaluate(NB, "2026-10-30T09:30:00Z")
        self.assertEqual(ev.status, sw.EXPIRED)
        self.assertEqual((ev.next_eligible_utc, ev.seconds_until_eligible, ev.seconds_until_deadline),
                         (None, None, None))
        self.assertFalse(ev.eligible)

    def test_offsets_normalized_to_utc(self):
        ev = evaluate("2026-10-30T11:00:00+02:00", "2026-10-30T05:00:00-06:00", as_of="2026-10-30T10:00:00+01:00")
        self.assertEqual((ev.as_of_utc, ev.not_before_utc, ev.deadline_utc),
                         ("2026-10-30T09:00:00Z", "2026-10-30T09:00:00Z", "2026-10-30T11:00:00Z"))
        self.assertEqual(ev.status, sw.READY)

    def test_fractional_wait_rounds_up_to_whole_seconds(self):
        ev = evaluate("2026-10-30T10:00:01.500000Z", "2026-10-30T10:00:02.250000Z")
        self.assertEqual((ev.seconds_until_eligible, ev.seconds_until_deadline), (2, 3))
        self.assertEqual(ev.next_eligible_utc, "2026-10-30T10:00:01.500000Z")


class ClockInjectionTests(unittest.TestCase):
    def test_injected_clock_called_exactly_once(self):
        clock = FixedClock(datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc))
        ev = sw.evaluate_window(window(NB, DL), clock=clock)
        self.assertEqual((ev.status, ev.as_of_utc, clock.calls), (sw.READY, AS_OF, 1))

    def test_clock_may_return_iso_string(self):
        ev = sw.evaluate_window(window("2026-10-30T11:00:00Z"), clock=FixedClock(AS_OF))
        self.assertEqual(ev.status, sw.WAIT_UNTIL)

    def test_no_instant_is_invalid_never_wall_clock(self):
        invalid_with(self, sw.evaluate_window(window()), sw.AS_OF_MISSING)
        with mock.patch.object(time, "time", side_effect=AssertionError("wall clock read")):
            invalid_with(self, sw.evaluate_window(window(NB, DL)), sw.AS_OF_MISSING)

    def test_both_instant_sources_is_ambiguous(self):
        clock = FixedClock(AS_OF)
        invalid_with(self, sw.evaluate_window(window(), as_of=AS_OF, clock=clock), sw.AS_OF_SOURCE_AMBIGUOUS)
        self.assertEqual(clock.calls, 0)

    def test_failing_or_non_callable_clock_fails_closed(self):
        def broken():
            raise RuntimeError("clock offline")
        invalid_with(self, sw.evaluate_window(window(), clock=broken), sw.CLOCK_UNAVAILABLE)
        invalid_with(self, sw.evaluate_window(window(), clock="now"), sw.CLOCK_UNAVAILABLE)

    def test_clock_returning_naive_or_garbage_fails_closed(self):
        invalid_with(self, sw.evaluate_window(window(), clock=FixedClock(datetime(2026, 10, 30, 10))), sw.AS_OF_NAIVE)
        for bad in (None, 0, 1730282400.0, b"2026-10-30T10:00:00Z", object()):
            invalid_with(self, sw.evaluate_window(window(), clock=FixedClock(bad)), sw.AS_OF_INVALID)

    def test_datetime_subclass_as_of_refused(self):
        class Fake(datetime):
            pass
        invalid_with(self, evaluate(as_of=Fake(2026, 10, 30, 10, tzinfo=timezone.utc)), sw.AS_OF_INVALID)


class MadridDstAndDayChangeTests(unittest.TestCase):
    def test_madrid_tz_helper_is_correct(self):
        # 2026: CEST from 29 Mar 01:00 UTC to 25 Oct 01:00 UTC.
        self.assertEqual(datetime(2026, 3, 29, 0, 59, tzinfo=timezone.utc).astimezone(MADRID).hour, 1)
        self.assertEqual(datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc).astimezone(MADRID).hour, 3)
        first = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc).astimezone(MADRID)
        second = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc).astimezone(MADRID)
        self.assertEqual((first.hour, first.fold, second.hour, second.fold), (2, 0, 2, 1))

    def test_spring_forward_offsets_resolve_to_one_utc_hour(self):
        # 01:59:59+01:00 and 03:00:00+02:00 are one second apart across the gap.
        ev = evaluate("2026-03-29T03:00:00+02:00", "2026-03-29T04:00:00+02:00", as_of="2026-03-29T01:59:59+01:00")
        self.assertEqual((ev.status, ev.next_eligible_utc, ev.seconds_until_eligible),
                         (sw.WAIT_UNTIL, "2026-03-29T01:00:00Z", 1))

    def test_autumn_repeated_hour_is_unambiguous_with_offsets(self):
        nb_first = evaluate("2026-10-25T02:30:00+02:00", as_of="2026-10-25T02:15:00+01:00")
        nb_second = evaluate("2026-10-25T02:30:00+01:00", as_of="2026-10-25T02:15:00+01:00")
        self.assertEqual(nb_first.status, sw.READY)            # 00:30Z <= 01:15Z
        self.assertEqual((nb_second.status, nb_second.next_eligible_utc), (sw.WAIT_UNTIL, "2026-10-25T01:30:00Z"))

    def test_window_across_dst_has_true_elapsed_length(self):
        # Local 00:00 -> 06:00 on the spring day is 5 real hours, not 6.
        ev = evaluate("2026-03-29T00:00:00+01:00", "2026-03-29T06:00:00+02:00", as_of="2026-03-28T23:00:00Z")
        self.assertEqual(ev.status, sw.READY)
        self.assertEqual(ev.seconds_until_deadline, 5 * 3600)

    def test_madrid_aware_datetime_as_of_outside_transitions(self):
        summer = datetime(2026, 7, 1, 12, 0, tzinfo=MADRID)
        winter = datetime(2026, 12, 1, 12, 0, tzinfo=MADRID)
        self.assertEqual(evaluate(as_of=summer).as_of_utc, "2026-07-01T10:00:00Z")
        self.assertEqual(evaluate(as_of=winter).as_of_utc, "2026-12-01T11:00:00Z")

    def test_ambiguous_or_nonexistent_madrid_wall_time_refused(self):
        for wall in (datetime(2026, 10, 25, 2, 30, tzinfo=MADRID), datetime(2026, 10, 25, 2, 30, fold=1, tzinfo=MADRID),
                     datetime(2026, 3, 29, 2, 30, tzinfo=MADRID)):
            invalid_with(self, evaluate(as_of=wall), sw.AS_OF_AMBIGUOUS_LOCAL_TIME)

    def test_day_month_and_year_rollover_by_offset(self):
        ev = evaluate("2027-01-01T00:30:00+01:00", "2027-01-01T09:00:00+09:00", as_of="2026-12-31T23:00:00Z")
        self.assertEqual((ev.not_before_utc, ev.deadline_utc), ("2026-12-31T23:30:00Z", "2027-01-01T00:00:00Z"))
        self.assertEqual((ev.status, ev.seconds_until_eligible), (sw.WAIT_UNTIL, 1800))
        leap = evaluate("2028-02-29T23:30:00-01:00", as_of="2028-03-01T00:00:00Z")
        self.assertEqual((leap.status, leap.next_eligible_utc), (sw.WAIT_UNTIL, "2028-03-01T00:30:00Z"))


class FormatRefusalTests(unittest.TestCase):
    def test_naive_bounds_refused(self):
        invalid_with(self, evaluate("2026-10-30T09:00:00"), sw.NOT_BEFORE_NAIVE)
        invalid_with(self, evaluate(deadline="2026-10-30T11:00:00.5"), sw.DEADLINE_NAIVE)
        invalid_with(self, evaluate(as_of="2026-10-30T10:00:00"), sw.AS_OF_NAIVE)

    def test_non_strict_iso_forms_refused_even_if_python_parses_them(self):
        for text in ("20261030T090000Z", "2026-W44-5T09:00:00Z", "2026-10-30 09:00:00+00:00", "2026-10-30T09:00Z",
                     "2026-10-30T09:00:00z", "2026-10-30T09:00:00+0000", "2026-10-30", "2026-10-30T09:00:00.1234567Z",
                     " 2026-10-30T09:00:00Z", "2026-10-30T09:00:00Z\n", "２０26-10-30T09:00:00Z"):
            invalid_with(self, evaluate(text), sw.NOT_BEFORE_INVALID)

    def test_impossible_dates_and_offsets_refused(self):
        for text in ("2026-02-30T09:00:00Z", "2026-10-30T24:00:00Z", "2026-10-30T09:60:00Z", "2026-13-01T00:00:00Z",
                     "2026-10-30T09:00:00+14:01", "2026-10-30T09:00:00+15:00", "2026-10-30T09:00:00+01:60",
                     "2026-10-30T09:00:00-00:00"):
            invalid_with(self, evaluate(deadline=text), sw.DEADLINE_INVALID)
        self.assertEqual(evaluate("2026-10-30T23:00:00+14:00").status, sw.READY)

    def test_wrong_types_and_oversized_refused(self):
        for bad in (0, 1.5, b"2026-10-30T09:00:00Z", ["2026-10-30T09:00:00Z"], "", "x" * 41, True,
                    datetime(2026, 10, 30, 9, tzinfo=timezone.utc)):
            invalid_with(self, evaluate(bad), sw.NOT_BEFORE_INVALID)

    def test_out_of_range_years_refused_without_overflow(self):
        for text in ("0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00", "1999-12-31T23:59:59Z",
                     "2000-01-01T00:30:00+01:00", "2199-12-31T23:00:00-14:00"):
            invalid_with(self, evaluate(text), sw.NOT_BEFORE_OUT_OF_RANGE)
        invalid_with(self, evaluate(as_of=datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1)))),
                     sw.AS_OF_OUT_OF_RANGE)
        invalid_with(self, evaluate(as_of=datetime(9999, 12, 31, 23, tzinfo=timezone(timedelta(hours=-2)))),
                     sw.AS_OF_OUT_OF_RANGE)


class ContradictionAndHorizonTests(unittest.TestCase):
    def test_inverted_or_empty_window_refused(self):
        invalid_with(self, evaluate(DL, NB), sw.WINDOW_INVERTED)
        invalid_with(self, evaluate(NB, NB), sw.WINDOW_INVERTED)
        # Same instant written with different offsets is still an empty window.
        invalid_with(self, evaluate("2026-10-30T11:00:00+02:00", "2026-10-30T09:00:00Z"), sw.WINDOW_INVERTED)

    def test_contradiction_reported_even_when_as_of_invalid(self):
        ev = invalid_with(self, sw.evaluate_window(window(DL, NB)), sw.WINDOW_INVERTED, sw.AS_OF_MISSING)
        self.assertEqual(ev.reasons, (sw.AS_OF_MISSING, sw.WINDOW_INVERTED))

    def test_absurd_horizon_refused_boundary_inclusive(self):
        limit = datetime(2026, 10, 30, 10, tzinfo=timezone.utc) + sw.MAX_HORIZON
        at_limit = limit.isoformat()
        beyond = (limit + timedelta(microseconds=1)).isoformat()
        self.assertEqual(evaluate(at_limit).status, sw.WAIT_UNTIL)
        self.assertEqual(evaluate(deadline=at_limit).status, sw.READY)
        invalid_with(self, evaluate(beyond), sw.HORIZON_EXCEEDED)
        invalid_with(self, evaluate(deadline=beyond), sw.HORIZON_EXCEEDED)
        invalid_with(self, evaluate("2099-01-01T00:00:00Z", "2100-01-01T00:00:00Z"), sw.HORIZON_EXCEEDED)

    def test_old_not_before_is_fine_but_old_deadline_expires(self):
        self.assertEqual(evaluate("2020-01-01T00:00:00Z").status, sw.READY)
        self.assertEqual(evaluate("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z").status, sw.EXPIRED)

    def test_all_reasons_collected_and_ordered(self):
        ev = sw.evaluate_window(window("bad", "2026-10-30T11:00:00"), as_of="2026-10-30T10:00:00")
        self.assertEqual(ev.reasons, (sw.AS_OF_NAIVE, sw.NOT_BEFORE_INVALID, sw.DEADLINE_NAIVE))


class SourceReuseTests(unittest.TestCase):
    """The bounds are read from the Runner's own Manifest / Blueprint fields;
    no other clock or calendar is introduced."""

    def test_reads_runner_manifest_fields(self):
        from scripts.ai import runner_pipeline
        manifest = runner_pipeline.Manifest(pipeline_id="p", workers=[], not_before_utc=NB, deadline_utc=DL)
        self.assertEqual(sw.window_from_source(manifest), window(NB, DL))
        self.assertEqual(sw.evaluate_window(manifest, as_of=AS_OF), evaluate(NB, DL))

    def test_reads_blueprint_and_schedule_request_and_manifest_dict(self):
        from scripts.ai import fabric_dag_blueprint as bp
        blueprint = bp.DagBlueprint(pipeline_id="p", nodes=(), not_before_utc=NB, deadline_utc=DL)
        data = bp.compose_manifest_data(blueprint)
        req = sc.ScheduleRequest(dag_id="d", item_count=0, items=(), as_of_utc=AS_OF, not_before_utc=NB,
                                 deadline_utc=DL)
        for source in (blueprint, data, req):
            self.assertEqual(sw.window_from_source(source), window(NB, DL), type(source).__name__)
        self.assertEqual(sw.window_from_source({"pipeline_id": "p"}), window())

    def test_unsupported_sources_fail_closed(self):
        class NoBounds:
            pass

        class Computed:
            calls = 0

            @property
            def not_before_utc(self):
                Computed.calls += 1
                return NB
            deadline_utc = DL
        for source in (None, "2026-10-30T09:00:00Z", 5, (NB, DL), [NB, DL], NoBounds(), Computed()):
            invalid_with(self, sw.evaluate_window(source, as_of=AS_OF), sw.WINDOW_SOURCE_UNSUPPORTED)
        self.assertEqual(Computed.calls, 0)

    def test_runner_semantics_pinned(self):
        from scripts.ai import runner_pipeline
        source = (REPO_ROOT / "scripts" / "ai" / "runner_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("self._now() < not_before", source)
        self.assertIn("self._now() >= self._deadline", source)
        self.assertIn('_MANIFEST_KEYS = {"pipeline_id", "workers", "max_workers", "provider_limits", '
                      '"not_before_utc", "deadline_utc"}', source)
        for text in ("2026-10-30T10:00:00Z", "2026-10-30T10:00:00+02:00", "2026-10-30T10:00:00.5-03:30",
                     "2026-03-29T03:00:00+02:00", "2026-10-25T02:30:00+01:00", AS_OF):
            self.assertEqual(sw.parse_utc(text), runner_pipeline._parse_iso(text), text)
            self.assertEqual(sw.parse_utc(text), sc._parse_utc(text), text)
        # Stricter than the Runner where the Runner would guess or overflow.
        self.assertIsNone(sw.parse_utc("2026-10-30T10:00:00-00:00"))
        self.assertIsNotNone(runner_pipeline._parse_iso("2026-10-30T10:00:00-00:00"))


class OutputInvariantAndAuthorityTests(unittest.TestCase):
    def test_every_status_carries_zero_authority(self):
        cases = (evaluate(NB, DL), evaluate(DL), evaluate(deadline=NB), evaluate("bad"))
        self.assertEqual([c.status for c in cases], [sw.READY, sw.WAIT_UNTIL, sw.EXPIRED, sw.INVALID])
        for ev in cases:
            data = ev.to_dict()
            for flag in ALL_FLAGS:
                self.assertIs(getattr(ev, flag), False, flag)
                self.assertIs(data[flag], False, flag)
            self.assertEqual(data["marker"], sw.WINDOW_MARKER)
            self.assertEqual((data["schema"], data["schema_version"]), (sw.SCHEMA, sw.SCHEMA_VERSION))

    def test_authority_flags_not_fields_and_not_settable(self):
        names = {f.name for f in dataclasses.fields(sw.WindowEvaluation)}
        self.assertFalse(names & set(ALL_FLAGS))
        ev = evaluate()
        for flag in ALL_FLAGS:
            with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
                setattr(ev, flag, True)
            with self.assertRaises(TypeError):
                dataclasses.replace(ev, **{flag: True})

    def test_hand_made_evaluations_cannot_overclaim(self):
        ready = evaluate(NB, DL)
        bad = (
            dict(status=sw.READY), dict(next_eligible_utc=DL), dict(seconds_until_deadline=1),
            dict(as_of_utc="2026-10-30T10:00:00+00:00"), dict(reasons=(sw.WINDOW_NOT_OPEN,)), dict(status="GO"),
            dict(as_of_utc=None),
        )
        expired = evaluate(deadline=NB)
        for overrides in bad:
            base = expired if overrides.get("status") == sw.READY else ready
            with self.assertRaises(ValueError, msg=overrides):
                dataclasses.replace(base, **overrides)
        with self.assertRaises(ValueError):
            dataclasses.replace(ready, not_before_utc=DL, deadline_utc=NB)
        with self.assertRaises(ValueError):
            dataclasses.replace(evaluate("bad"), as_of_utc=AS_OF)
        with self.assertRaises(ValueError):
            dataclasses.replace(evaluate("bad"), reasons=(sw.WINDOW_EXPIRED,))
        with self.assertRaises(ValueError):
            dataclasses.replace(ready, status=sw.INVALID)

    def test_canonical_json_exact_type_and_stable(self):
        class Evil(sw.WindowEvaluation):
            def to_dict(self):
                return {"execution_allowed": True}
        ev = evaluate(NB, DL)
        with self.assertRaises(TypeError):
            sw.canonical_json(Evil(**{f.name: getattr(ev, f.name) for f in dataclasses.fields(ev)}))
        with self.assertRaises(TypeError):
            sw.canonical_json(ev.to_dict())
        text = sw.canonical_json(ev)
        self.assertNotIn(" ", text)
        self.assertLessEqual(len(text), sw.MAX_CANONICAL_JSON_BYTES)

    def test_invalid_input_never_echoed(self):
        secret = "2026-10-30T09:00:00Z-sk-live-XYZ"
        text = sw.canonical_json(evaluate(secret))
        self.assertNotIn("sk-live", text)
        self.assertNotIn("2026-10-30T09", text)


class DeterminismAndPurityTests(unittest.TestCase):
    def test_deterministic_and_equivalent_inputs_equal(self):
        a = sw.canonical_json(evaluate(NB, DL))
        self.assertEqual(a, sw.canonical_json(evaluate(NB, DL)))
        b = sw.canonical_json(sw.evaluate_window(window("2026-10-30T10:00:00+01:00", "2026-10-30T06:00:00-05:00"),
                                                 clock=FixedClock(datetime(2026, 10, 30, 11, tzinfo=MADRID))))
        self.assertEqual(a, b)

    def test_preview_never_mutates_inputs(self):
        from scripts.ai import runner_pipeline
        data = {"pipeline_id": "p", "workers": [], "not_before_utc": NB, "deadline_utc": DL}
        manifest = runner_pipeline.Manifest(pipeline_id="p", workers=[], not_before_utc=NB, deadline_utc=DL)
        before = (copy.deepcopy(data), copy.deepcopy(manifest))
        for source in (data, manifest, window(NB, DL)):
            sw.evaluate_window(source, as_of=AS_OF)
            sw.evaluate_window(source, clock=FixedClock(AS_OF))
        self.assertEqual((data, manifest), before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(window(), "deadline_utc", DL)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(evaluate(), "status", sw.READY)

    def test_no_clock_io_process_or_network(self):
        def boom(*a, **k):
            raise AssertionError("I/O or clock attempted")
        patches = [mock.patch.object(builtins, "open", boom), mock.patch.object(subprocess, "Popen", boom),
                   mock.patch.object(subprocess, "run", boom), mock.patch.object(socket, "socket", boom),
                   mock.patch.object(os, "listdir", boom), mock.patch.object(os, "stat", boom),
                   mock.patch.object(os, "getenv", boom), mock.patch.object(time, "time", boom),
                   mock.patch.object(time, "sleep", boom), mock.patch.object(time, "monotonic", boom)]
        for p in patches:
            p.start()
        try:
            for ev in (evaluate(NB, DL), evaluate(DL), evaluate(deadline=NB), evaluate("bad"),
                       sw.evaluate_window(window()), sw.evaluate_window(window(), clock=FixedClock(AS_OF))):
                sw.canonical_json(ev)
        finally:
            for p in reversed(patches):
                p.stop()

    def test_module_imports_only_pure_stdlib_and_contract(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {f"{n.module}.{a.name}" if n.module == "scripts.ai" else n.module
                     for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertEqual(imported, {"__future__", "dataclasses", "datetime", "re", "typing",
                                    "scripts.ai.fabric_scheduler_contract", "fabric_scheduler_contract"})
        code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
        code = "\n".join(line.split("#", 1)[0] for line in code.splitlines())
        for word in ("runner_", "claude", "fabric_director", "subprocess", "shutil", "socket", "open(", "Path(",
                     "os.", "environ", "eval(", "exec(", "__import__", "importlib", "git", ".now(", "utcnow",
                     "today(", "import time", "time.time", "sleep", "monotonic", "threading", "Thread", "multiprocessing", "asyncio",
                     "import sched", "random", "while "):
            self.assertFalse(word in code.replace("fabric_scheduler_contract", ""), word)

    def test_no_mutable_module_state_changes(self):
        snapshot = {k: copy.deepcopy(v) for k, v in vars(sw).items()
                    if not k.startswith("__") and isinstance(v, (dict, list, set, tuple, frozenset, str, int))}
        evaluate(NB, DL)
        evaluate("bad")
        sw.evaluate_window(None)
        self.assertEqual({k: v for k, v in vars(sw).items() if k in snapshot}, snapshot)

    def test_vocabularies_unique_disjoint_and_upper_snake(self):
        for vocab in (sw.STATUSES, sw.INVALID_REASONS, sw.TEMPORAL_REASONS, sw.REASONS):
            self.assertEqual(len(vocab), len(set(vocab)))
            for code in vocab:
                self.assertRegex(code, r"^[A-Z][A-Z_]*$")
        self.assertFalse(set(sw.INVALID_REASONS) & set(sw.TEMPORAL_REASONS))
        self.assertEqual(sw.STATUSES, ("READY", "WAIT_UNTIL", "EXPIRED", "INVALID"))
        self.assertIn(sw.WINDOW_EXPIRED, sc.ITEM_REASONS)
        self.assertIn(sw.WINDOW_NOT_OPEN, sc.ITEM_REASONS)

    def test_this_suite_skips_nothing(self):
        tree = ast.parse(TEST_PATH.read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for word in ("skip", "skipIf", "skipUnless", "expectedFailure", "SkipTest"):
            self.assertNotIn(word, attrs | names, word)


if __name__ == "__main__":
    unittest.main()
