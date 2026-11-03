"""FCP-11E-05: Fabric Control Plane providers / quota / cost / capacity view.

Snapshots are real FCP-11B-02 `take_snapshot` reads of synthetic Runner-shaped
files in a private temporary directory; reports are produced by the real
FCP-10D-01 report over the real FCP-10 engines (A02 / C02 / B02), with input
documents built by the FCP-10D-01 test fixtures (quota / auth holds from the
Runner's own `_hold_for_provider`). Provider ids are opaque labels. Nothing is
probed, priced, executed, sent anywhere or skipped.
"""

from __future__ import annotations

import ast
import copy
import json
import shutil
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_control_plane_contract as cp
from scripts.ai import fabric_control_plane_resources as res
from scripts.ai import fabric_control_plane_snapshot as snap
from scripts.ai import fabric_resource_quota_report as qrep
from scripts.tests import test_fabric_resource_quota_report as fx
from scripts.tests.test_fabric_resource_quota_report import canonical_temp_dir

MODULE_PATH = Path(res.__file__)
OBSERVED_AT = "2026-10-31T12:30:00Z"  # after the FCP-10D-01 fixtures' as_of (12:00)
QUOTA = "PROVIDER_QUOTA_EXHAUSTED"
AUTH = "PROVIDER_AUTH_BLOCKED"
ALL_FLAGS = ("certified", "authorizes_action", "execution_allowed", "dispatch_allowed", "auto_retry_allowed",
             "resume_allowed", "merging_allowed", "provider_switch_authorized", "ledger_write_allowed",
             "state_persisted", "process_control_allowed", "git_allowed", "provider_api_called",
             "remote_probe_made", "charge_made", "purchase_allowed", "price_generated", "time_estimated")


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


def floats_in(node) -> list:
    if isinstance(node, float):
        return [node]
    if isinstance(node, dict):
        return [f for v in node.values() for f in floats_in(v)]
    if isinstance(node, list):
        return [f for v in node for f in floats_in(v)]
    return []


def report_of(document) -> dict:
    """A real FCP-10D-01 report of `document` (engines run once)."""
    quota, recovery, budget = qrep.build_requests(json.loads(json.dumps(document)))
    return qrep.build_report(*qrep.evaluate(quota, recovery, budget))


def reseal(report) -> dict:
    report = {k: v for k, v in report.items() if k != "report_sha256"}
    report["report_sha256"] = qrep._sha(qrep._canonical(report))
    return report


class ResourcesTestBase(unittest.TestCase):
    def setUp(self):
        self.root = canonical_temp_dir("fcp11e05-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def put(self, relative: str, payload) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8"))
        return path

    def pipeline(self, workers, pid="fcp11-pipe", status="RUNNING", record_states=None):
        """Synthetic Runner-shaped files: `workers` are pipeline_result entries."""
        self.put(f"{pid}/pipeline_result.json", {"schema_version": 1, "pipeline_id": pid, "status": status,
                                                 "workers_total": len(workers), "workers": workers})
        self.put(f"{pid}/pipeline.json", {"schema_version": 1, "pipeline_id": pid, "status": status})
        for entry in workers:
            state = (record_states or {}).get(entry["id"], entry["state"])
            self.put(f"{pid}/workers/{entry['id']}/worker.json",
                     {"schema_version": 1, "spec": {"id": entry["id"]}, "state": state})

    def snapshot(self) -> snap.ControlPlaneSnapshot:
        return snap.take_snapshot(str(self.root), OBSERVED_AT)

    def observe(self, **kw) -> res.ControlPlaneResources:
        return res.observe_resources(self.snapshot(), **kw)

    @staticmethod
    def provider(view, name) -> res.ProviderResource:
        return next(p for p in view.providers if p.provider_id == name)

    @staticmethod
    def worker(view, wid) -> res.WorkerResource:
        return next(w for w in view.workers if w.worker_id == wid)

    def report_file(self, document) -> str:
        path = self.root.parent / f"{self.root.name}-report.json"
        path.write_bytes(json.dumps(document).encode("utf-8"))
        self.addCleanup(lambda: path.exists() and path.unlink())
        return str(path)


# ---------------------------------------------------------------------------
class HoldTests(ResourcesTestBase):
    def test_quota_exhausted_but_worker_complete_stays_success(self):
        self.pipeline([{"id": "w1", "state": "SUCCESS", "provider": "alpha", "provider_condition": QUOTA,
                        "next_eligible_utc": "2026-10-31T15:00:00Z"}], status="SUCCESS")
        doc = fx.document(records=[fx.wait(fx.runner_worker_json())])
        view = self.observe(report=report_of(doc))
        w = self.worker(view, "w1")
        self.assertEqual((w.status.runner_outcome, w.hold), ("SUCCESS", res.HOLD_NONE))
        self.assertEqual((w.recorded_provider_condition, w.condition_scope), (QUOTA, res.SCOPE_RECORDED_ONLY))
        p = self.provider(view, "alpha")
        self.assertEqual((p.quota_wait_workers, p.auth_hold_workers, p.unknown_hold_workers), (0, 0, 0))
        self.assertEqual(dict(p.quota)["availability"], "QUOTA_WAIT")
        self.assertEqual(p.capacity_condition, res.UNKNOWN)
        self.assertEqual(dict(p.advisory)["status"], qrep.WAITING)
        self.assertNotIn("dispatch", json.dumps(dict(p.advisory)).lower())

    def test_active_quota_wait_and_auth_hold_are_counted_per_provider(self):
        self.pipeline([
            {"id": "w1", "state": "WAITING_PROVIDER_QUOTA", "provider": "alpha", "provider_condition": QUOTA,
             "next_eligible_utc": "2026-10-31T09:00:00Z"},
            {"id": "w2", "state": "BLOCKED_PROVIDER_AUTH", "provider": "beta", "provider_condition": AUTH},
            {"id": "w3", "state": "WAITING_PROVIDER_QUOTA", "provider": "alpha"},
        ])
        view = self.observe()
        w1, w2, w3 = (self.worker(view, w) for w in ("w1", "w2", "w3"))
        self.assertEqual((w1.hold, w1.condition_scope, w1.anomalies), (res.HOLD_QUOTA_WAIT, res.SCOPE_ACTIVE_HOLD, ()))
        self.assertEqual((w2.hold, w2.condition_scope), (res.HOLD_AUTH, res.SCOPE_ACTIVE_HOLD))
        self.assertEqual(w3.anomalies, (res.HOLD_CONDITION_MISMATCH,))
        self.assertEqual(self.provider(view, "alpha").quota_wait_workers, 2)
        self.assertEqual(self.provider(view, "beta").auth_hold_workers, 1)

    def test_eligibility_instant_is_verbatim_never_an_estimate(self):
        # next_eligible_utc is before the observation instant: still held,
        # never "eligible now", no ETA / remaining wait anywhere.
        self.pipeline([{"id": "w1", "state": "WAITING_PROVIDER_QUOTA", "provider": "alpha",
                        "provider_condition": QUOTA, "next_eligible_utc": "2026-10-31T09:00:00Z"}])
        body = self.observe().to_dict()
        w = body["workers"][0]
        self.assertEqual((w["hold"], w["recorded_next_eligible_utc"]), (res.HOLD_QUOTA_WAIT, "2026-10-31T09:00:00Z"))
        for key in walk_keys(body):
            tokens = key.lower().split("_")
            for word in ("eta", "duration", "seconds", "now", "estimate", "estimated", "until"):
                self.assertFalse(word in tokens and key != "time_estimated", key)
        self.assertIs(body["time_estimated"], False)

    def test_divergent_or_unverifiable_worker_has_unknown_hold(self):
        self.pipeline([{"id": "w1", "state": "WAITING_PROVIDER_QUOTA", "provider": "alpha",
                        "provider_condition": QUOTA}], record_states={"w1": "RUNNING"})
        w = self.worker(self.observe(), "w1")
        self.assertEqual((w.hold, w.anomalies), (res.HOLD_UNKNOWN, (res.WORKER_STATUS_DIVERGENT,)))
        self.assertEqual(w.condition_scope, res.SCOPE_RECORDED_ONLY)
        (self.root / "fcp11-pipe/workers/w1/worker.json").unlink()
        w = self.worker(self.observe(), "w1")
        self.assertEqual((w.hold, w.agreement), (res.HOLD_UNKNOWN, snap.AGREEMENT_UNVERIFIABLE))

    def test_unattributed_and_unlisted_workers_are_counted_not_named(self):
        self.pipeline([{"id": "w1", "state": "RUNNING"}, {"id": "w2", "state": "RUNNING", "provider": "alpha"}])
        self.put("fcp11-pipe/workers/w9/worker.json", {"schema_version": 1, "spec": {"id": "w9"}, "state": "QUEUED"})
        view = self.observe()
        self.assertEqual(view.unattributed_workers, 2)
        self.assertEqual([p.provider_id for p in view.providers], ["alpha"])
        self.assertTrue(view.snapshot_complete)
        self.assertNotIn("w9", [w.worker_id for w in view.workers])

    def test_unreadable_root_is_no_success_and_no_provider(self):
        view = res.observe_resources(snap.take_snapshot(str(self.root / "absent"), OBSERVED_AT))
        self.assertEqual((view.workers, view.providers, view.snapshot_complete), ((), (), False))


# ---------------------------------------------------------------------------
class ReportTests(ResourcesTestBase):
    def test_no_report_is_missing_and_everything_unknown(self):
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": "alpha"}])
        view = self.observe()
        self.assertEqual((view.report_condition, view.report_cause), (cp.MISSING, cp.SOURCE_ABSENT))
        p = self.provider(view, "alpha")
        self.assertEqual((p.capacity_condition, p.capacity_reasons), (res.UNKNOWN, (res.REPORT_ABSENT,)))
        self.assertEqual((p.cost_condition, p.cost_reasons), (res.UNKNOWN, (res.REPORT_ABSENT,)))
        self.assertEqual((view.global_cost_condition, view.global_cost_reasons), (res.UNKNOWN, (res.REPORT_ABSENT,)))
        self.assertEqual(view.to_dict()["report_actor"], cp.qr.ACTOR_RUNNER)

    def test_auth_blocked_with_unknown_cost(self):
        self.pipeline([{"id": "w1", "state": "BLOCKED_PROVIDER_AUTH", "provider": "beta", "provider_condition": AUTH}])
        doc = fx.document(records=[fx.wait(fx.runner_worker_json(fx.AUTH_MESSAGE, provider="beta"), provider="beta")])
        view = self.observe(report_file=self.report_file(doc))
        self.assertEqual(view.report_condition, cp.PRESENT)
        p = self.provider(view, "beta")
        self.assertEqual(dict(p.quota)["availability"], "AUTH_BLOCKED")
        self.assertEqual(dict(p.advisory)["action"], "RESTORE_PROVIDER_AUTH")
        self.assertEqual((p.auth_hold_workers, p.capacity_condition), (1, res.UNKNOWN))
        self.assertEqual((p.cost_condition, p.cost_reasons), (res.UNKNOWN, (res.NO_COST_EVIDENCE,)))
        self.assertEqual(view.global_cost_reasons, (res.NO_COST_EVIDENCE,))
        self.assertEqual(view.report_status, qrep.BLOCKED)

    def test_stale_evidence_withholds_capacity_and_slots(self):
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": "alpha"}])
        doc = fx.document(records=[fx.router(), fx.capacity(observed="2026-10-30T00:00:00Z")],
                          max_evidence_age_seconds=3600)
        report = report_of(doc)
        self.assertEqual(report["quota"]["providers"][0]["proven_slots"], 2)  # A02 still lists them
        p = self.provider(self.observe(report=report), "alpha")
        self.assertEqual((p.capacity_condition, p.capacity, p.proven_slots), (res.UNKNOWN, None, None))
        self.assertIn("EVIDENCE_STALE", p.capacity_reasons)

    def test_fresh_certain_capacity_is_known(self):
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": "alpha"}])
        p = self.provider(self.observe(report=report_of(fx.document())), "alpha")
        self.assertEqual((p.capacity_condition, p.capacity, p.proven_slots), (res.KNOWN, "AVAILABLE", 2))

    def test_report_after_observation_or_too_old_is_doubtful(self):
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": "alpha"}])
        later = fx.document(as_of_utc="2026-10-31T13:00:00Z", budget=fx.budget(reserve=None))
        view = self.observe(report=report_of(later))
        self.assertEqual(view.report_anomalies, (res.REPORT_AFTER_OBSERVATION,))
        p = self.provider(view, "alpha")
        self.assertEqual(p.capacity_condition, res.UNKNOWN)
        self.assertTrue(all(c.condition == res.UNKNOWN for c in view.global_costs))
        view = self.observe(report=report_of(fx.document()), max_report_age_seconds=60)
        self.assertEqual(view.report_anomalies, (res.REPORT_STALE,))
        self.assertIn(res.REPORT_STALE, self.provider(view, "alpha").capacity_reasons)
        self.assertEqual(self.observe(report=report_of(fx.document()), max_report_age_seconds=3600).report_anomalies,
                         ())

    def test_refused_report_files_are_safe_errors(self):
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": "alpha"}])
        bad = self.root.parent / f"{self.root.name}-bad.json"
        bad.write_bytes(b'{"a": 1, "a": 2}')
        self.addCleanup(bad.unlink)
        cases = {
            "relative.json": (cp.UNAVAILABLE, cp.PATH_REFUSED, "REPORT_PATH_NOT_ADMISSIBLE"),
            str(self.root / ".." / "x.json"): (cp.UNAVAILABLE, cp.PATH_REFUSED, "REPORT_PATH_NOT_ADMISSIBLE"),
            "//server/share/x.json": (cp.UNAVAILABLE, cp.PATH_REFUSED, "REPORT_PATH_NETWORK_REFUSED"),
            str(self.root / "absent.json"): (cp.UNAVAILABLE, cp.SOURCE_UNREADABLE, "REPORT_INPUT_FILE_INVALID"),
            str(bad): (cp.CORRUPT, cp.SOURCE_NOT_JSON, "REPORT_INPUT_DUPLICATE_KEY"),
            self.report_file({"schema": "other"}): (cp.CORRUPT, cp.SCHEMA_UNSUPPORTED, "REPORT_INPUT_FIELD_MISSING"),
        }
        for path, expected in cases.items():
            view = self.observe(report_file=path)
            self.assertEqual((view.report_condition, view.report_cause, view.report_code), expected, path)
            text = res.canonical_json(view)
            self.assertNotIn(self.root.name, text)
            self.assertNotIn("server", text)
            self.assertEqual(self.provider(view, "alpha").capacity_condition, res.UNKNOWN)

    def test_engine_refusal_and_internal_errors_fail_closed(self):
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": "alpha"}])
        doc = fx.document(request_id="../bad")
        view = self.observe(report_file=self.report_file(doc))
        self.assertEqual((view.report_condition, view.report_code), (cp.CORRUPT, "REPORT_QUOTA_REFUSED"))
        with mock.patch.object(res.qrep, "run_report", side_effect=RuntimeError(fx.SECRET)):
            view = self.observe(report_file=self.report_file(fx.document()))
        self.assertEqual((view.report_condition, view.report_code), (cp.UNAVAILABLE, "REPORT_INTERNAL_ERROR"))
        self.assertNotIn(fx.SECRET, res.canonical_json(view))

    def test_tampered_or_foreign_reports_are_corrupt(self):
        good = report_of(fx.document())
        tampered = copy.deepcopy(good)
        tampered["quota"]["providers"][0]["capacity"] = "FULL"
        upgraded = reseal({**copy.deepcopy(good), "dispatch_allowed": True})
        cases = [
            ([], cp.SOURCE_NOT_JSON), ({**good, "schema": "other"}, cp.SCHEMA_UNSUPPORTED),
            ({k: v for k, v in good.items() if k != "marker"}, cp.SCHEMA_UNSUPPORTED),
            (tampered, cp.FIELD_MALFORMED), (upgraded, cp.FIELD_MALFORMED),
            (reseal({**good, "as_of_utc": "yesterday"}), cp.FIELD_MALFORMED),
            ({**good, "quota": float("nan")}, cp.SOURCE_NOT_JSON),
            ({**good, "quota": "x" * (qrep.MAX_REPORT_BYTES + 1)}, cp.SOURCE_TOO_LARGE),
        ]
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": "alpha"}])
        snapshot = self.snapshot()
        for report, cause in cases:
            view = res.observe_resources(snapshot, report=report)
            self.assertEqual((view.report_condition, view.report_cause), (cp.CORRUPT if cause != cp.SOURCE_TOO_LARGE
                                                                          else cp.UNAVAILABLE, cause))
            self.assertIsNone(view.report_sha256)
        with self.assertRaises(ValueError):
            res.observe_resources(snapshot, report=good, report_file="C:/x.json")

    def test_malicious_report_entries_are_rejected_never_named(self):
        report = report_of(fx.document(records=[fx.router(), fx.router("beta")]))
        report["quota"]["providers"][1]["provider_id"] = fx.SECRET
        report["quota"]["providers"].append({"provider_id": "gamma", "availability": "NONE"})
        report["decisions"][0]["action"] = "PURCHASE"
        report = reseal(report)
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": "alpha"}])
        view = self.observe(report=report)
        self.assertEqual(view.report_condition, cp.PRESENT)
        self.assertEqual(view.rejected_report_entries, 3)
        # beta keeps its valid C02 decision but its (renamed) quota view is gone.
        self.assertEqual([p.provider_id for p in view.providers], ["alpha", "beta"])
        beta = self.provider(view, "beta")
        self.assertEqual((beta.quota, beta.capacity_reasons), ((), (res.QUOTA_EVIDENCE_ABSENT,)))
        self.assertEqual(self.provider(view, "alpha").advisory, ())
        self.assertNotIn(fx.SECRET, res.canonical_json(view))
        self.assertNotIn("PURCHASE\"", json.dumps(view.to_dict()["providers"]))


# ---------------------------------------------------------------------------
class CostTests(ResourcesTestBase):
    def setUp(self):
        super().setUp()
        self.pipeline([{"id": "w1", "state": "SUCCESS", "provider": "alpha"}], status="SUCCESS")

    def test_known_cost_keeps_exact_decimal_strings_and_provenance(self):
        report = report_of(fx.document(budget=fx.budget()))
        view = self.observe(report=report)
        (money,) = view.global_costs
        body = money.to_dict()
        self.assertEqual((body["condition"], body["basis"], body["currency"]), (res.KNOWN, res.BASIS_OBSERVED, "EUR"))
        self.assertEqual((body["accounted"], body["remaining"], body["maximum"]), ("0.02", "9.98", "10.00"))
        self.assertEqual(Decimal(body["maximum"]) - Decimal(body["accounted"]), Decimal(body["remaining"]))
        self.assertEqual(body["provenance"]["source"], res.COST_SOURCE)
        self.assertEqual(body["provenance"]["fingerprint"], report["sources"]["budget"]["fingerprint"])
        self.assertEqual(body["provenance"]["report_sha256"], report["report_sha256"])
        self.assertEqual(body["evidence_ids"], ["r1"])
        self.assertEqual(floats_in(view.to_dict()), [])
        # Global money is never apportioned to a provider.
        p = self.provider(view, "alpha")
        self.assertEqual((p.cost_condition, p.cost_reasons, p.costs), (res.UNKNOWN, (res.NO_COST_LIMIT,), ()))
        self.assertNotIn("tariff", json.dumps(view.to_dict()).lower())
        self.assertNotIn("execution_ids", list(walk_keys(view.to_dict())))

    def test_missing_tariff_is_unknown_with_no_amount(self):
        doc = fx.document(budget=fx.budget(reserve=None))
        doc["budget"]["tariffs"] = []
        (money,) = self.observe(report=report_of(doc)).global_costs
        self.assertEqual((money.condition, money.reasons, money.amounts), (res.UNKNOWN, ("TARIFF_MISSING",), ()))
        self.assertIsNone(money.to_dict()["accounted"])
        self.assertIsNone(money.basis)

    def test_provider_scoped_cost_attaches_to_its_provider(self):
        doc = fx.document(budget=fx.budget(reserve=None))
        doc["budget"]["policy"]["limits"][1].update(scope="PROVIDER", provider_id="alpha")
        view = self.observe(report=report_of(doc))
        p = self.provider(view, "alpha")
        self.assertEqual((p.cost_condition, [c.limit_id for c in p.costs]), (res.KNOWN, ["money"]))
        self.assertEqual((view.global_costs, view.global_cost_condition), ((), res.UNKNOWN))

    def test_tampered_figures_are_inconsistent_not_trusted(self):
        report = report_of(fx.document(budget=fx.budget(reserve=None)))
        account = next(a for a in report["budget"]["accounts"] if a["unit"] == "COST")
        for field, value in (("remaining", "9.99"), ("accounted", "0.020"), ("observed", "1e-2"),
                             ("maximum", 10.0), ("uncertainty", "-0.00")):
            forged = copy.deepcopy(report)
            next(a for a in forged["budget"]["accounts"] if a["unit"] == "COST")[field] = value
            (money,) = self.observe(report=reseal(forged)).global_costs
            self.assertEqual((money.condition, money.reasons), (res.UNKNOWN, (res.COST_FIGURES_INCONSISTENT,)),
                             field)
        self.assertEqual(account["accounted"], "0.02")

    def test_decimal_precision_is_exact_at_fine_granularity(self):
        doc = fx.document(budget=fx.budget(reserve=None))
        doc["budget"]["policy"]["granularity"] = "0.00000001"
        doc["budget"]["tariffs"][0]["rate"] = "0.000000123456789"
        (money,) = self.observe(report=report_of(doc)).global_costs
        body = money.to_dict()
        self.assertEqual(money.condition, res.KNOWN)
        self.assertEqual(len(body["accounted"].split(".")[1]), 8)
        self.assertEqual(Decimal(body["observed"]) + Decimal(body["estimated_high"]), Decimal(body["accounted"]))

    def test_invalid_cost_views_are_refused(self):
        with self.assertRaises(ValueError):
            res.CostView("money", "GLOBAL", None, "EUR", res.KNOWN)
        with self.assertRaises(ValueError):
            res.CostView("money", "GLOBAL", None, "EUR", res.UNKNOWN, amounts=(("maximum", "1"),), reasons=("X_Y",))
        with self.assertRaises(ValueError):
            res.CostView("money", "GLOBAL", None, "EUR", res.UNKNOWN)


# ---------------------------------------------------------------------------
class AuthorityAndDeterminismTests(ResourcesTestBase):
    def test_zero_automatic_actions(self):
        self.pipeline([{"id": "w1", "state": "WAITING_PROVIDER_QUOTA", "provider": "alpha",
                        "provider_condition": QUOTA}])
        view = self.observe(report=report_of(fx.document(budget=fx.budget())))
        body = view.to_dict()
        for flag in ALL_FLAGS:
            self.assertIs(body[flag], False, flag)
            self.assertIs(getattr(view, flag), False, flag)
        self.assertEqual(body["not_authorized_actions"], list(qrep.NOT_AUTHORIZED_ACTIONS))
        for action in ("RETRY", "RESUME", "PROVIDER_SWITCH", "PURCHASE", "DISPATCH"):
            self.assertIn(action, body["not_authorized_actions"])
        for key in ("next_safe_step", "next_safe_steps", "tariffs", "receipts", "reservation", "message"):
            self.assertNotIn(key, set(walk_keys(body)))

    def test_snapshot_root_and_report_file_are_never_written(self):
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": "alpha"}])
        path = self.report_file(fx.document())
        before = {str(p): p.read_bytes() for p in sorted(self.root.rglob("*")) if p.is_file()}
        report_before = Path(path).read_bytes()
        self.observe(report_file=path)
        self.assertEqual(before, {str(p): p.read_bytes() for p in sorted(self.root.rglob("*")) if p.is_file()})
        self.assertEqual(report_before, Path(path).read_bytes())

    def test_equal_inputs_give_byte_equal_output_and_changes_change_revision(self):
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": "alpha"}])
        report = report_of(fx.document(budget=fx.budget()))
        snapshot = self.snapshot()
        a, b = res.observe_resources(snapshot, report=report), res.observe_resources(snapshot, report=report)
        self.assertEqual(res.canonical_json(a), res.canonical_json(b))
        self.assertEqual(a.revision, json.loads(res.canonical_json(a))["revision"])
        self.assertNotEqual(a.revision, res.observe_resources(snapshot).revision)
        with self.assertRaises(TypeError):
            res.canonical_json(a.to_dict())
        with self.assertRaises(TypeError):
            res.observe_resources(snapshot.to_dict())
        for bad in (-1, True, 1.5, res.MAX_REPORT_AGE_SECONDS + 1):
            with self.assertRaises(ValueError):
                res.observe_resources(snapshot, max_report_age_seconds=bad)

    def test_secret_shaped_provider_labels_are_withheld(self):
        label = "sk-" + "a" * 28
        self.pipeline([{"id": "w1", "state": "RUNNING", "provider": label}])
        view = self.observe()
        self.assertEqual((view.providers, view.unattributed_workers), ((), 1))
        self.assertNotIn(label, res.canonical_json(view))

    def test_view_invariants_refuse_impossible_claims(self):
        running = cp.StatusView(cp.SOURCE_WORKER_STATE, cp.PRESENT, "RUNNING")
        with self.assertRaises(ValueError):
            res.WorkerResource("p", "w", running, snap.AGREEMENT_CONSISTENT, res.HOLD_QUOTA_WAIT)
        with self.assertRaises(ValueError):
            res.WorkerResource("p", "w", running, snap.AGREEMENT_DIVERGENT, res.HOLD_NONE)
        with self.assertRaises(ValueError):
            res.ProviderResource("alpha", capacity_condition=res.UNKNOWN, proven_slots=2, capacity_reasons=("X_Y",))
        with self.assertRaises(ValueError):
            res.ProviderResource("alpha", capacity_condition=res.KNOWN, capacity="UNKNOWN")
        with self.assertRaises(ValueError):
            res.ProviderResource("Alpha!", capacity_reasons=("X_Y",))


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
                         "fabric_director", "runner_factory_ledger", "tempfile", "os"):
                self.assertNotIn(word, name.split("."), name)

    def test_module_calls_no_writing_clock_or_process_api(self):
        tree = self.tree()
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("environ", "getenv", "write_text", "write_bytes", "mkdir", "makedirs", "remove", "unlink",
                          "rename", "replace", "rmdir", "system", "popen", "Popen", "now", "utcnow", "sleep", "time",
                          "read_input_bytes", "scandir", "listdir", "evaluate_budget", "advise_recovery",
                          "adapt_observations", "float"):
            self.assertNotIn(forbidden, names)
        self.assertNotIn("open", {n.func.id for n in ast.walk(tree)
                                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)})

    def test_engines_and_report_are_reused_not_redefined(self):
        defined = {n.name for n in ast.walk(self.tree()) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for duplicated in ("run_report", "verify_report", "build_report", "read_input_bytes", "parse_document",
                           "take_snapshot", "evaluate_budget", "advise_recovery", "adapt_observations",
                           "WorkerView", "StatusView", "_money_text", "granularity_ok"):
            self.assertNotIn(duplicated, defined)
        self.assertIs(res.qrep, qrep)
        self.assertIs(res.snap, snap)
        with mock.patch.object(res.qrep, "run_report", wraps=qrep.run_report) as runs:
            path = canonical_temp_dir("fcp11e05-static-")
            self.addCleanup(shutil.rmtree, path, ignore_errors=True)
            (path / "doc.json").write_bytes(json.dumps(fx.document()).encode("utf-8"))
            res.observe_resources(snap.take_snapshot(str(path), OBSERVED_AT), report_file=str(path / "doc.json"))
        self.assertEqual(runs.call_count, 1)


if __name__ == "__main__":
    unittest.main()
