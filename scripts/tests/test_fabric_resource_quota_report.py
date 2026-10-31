"""FCP-10D-01: consultative Resource / Quota report and CLI.

Every report goes through the real engines (FCP-10A-02 `adapt_observations`,
FCP-10C-02 `advise_recovery`, FCP-10B-02 `evaluate_budget`); quota / auth
holds are produced by the real `PipelineRunner._hold_for_provider` (only its
persistence is replaced by an in-memory host) and serialized with the
Runner's own `WorkerRuntime.to_dict`. Input documents are real files in a
private temporary directory. Provider ids are opaque labels; nothing is
executed, retried, committed, bought or sent anywhere. Nothing here is
skipped.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import copy
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.ai import fabric_resource_quota_budget as bg
from scripts.ai import fabric_resource_quota_contract as qc
from scripts.ai import fabric_resource_quota_observation as qo
from scripts.ai import fabric_resource_quota_recovery as rq
from scripts.ai import fabric_resource_quota_report as rep
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_provider_availability as availability

MODULE_PATH = Path(rep.__file__)
REPO_ROOT = MODULE_PATH.resolve().parents[2]
AS_OF = "2026-10-31T12:00:00Z"
OBSERVED = "2026-10-31T11:59:00Z"
HIT = datetime(2026, 10, 31, 11, 59, tzinfo=timezone.utc)
QUOTA_RESET_MESSAGE = "You've hit your session limit - resets 3pm (Etc/UTC)"
AUTH_MESSAGE = "Not logged in - please run /login"
SECRET = "sk-ant-api03-" + "Q" * 40
PRIVATE_PATH = "C:/private/client-data/worktree"
REPORT_KEYS = {
    "schema", "schema_version", "marker", "request_id", "as_of_utc", "deadline_utc", "status", "quota",
    "reserved_capacity", "budget", "decisions", "blocking_risk", "next_safe_step", "next_safe_steps",
    "not_authorized_actions", "sources", "authority", "report_sha256", *rep.AUTHORITY_FLAGS,
}


class _PersistenceHost:
    """Replaces only the Runner's disk writes; the hold logic is its own."""

    def __init__(self):
        self.tz_lookup = lambda name: timezone.utc

    def _transition(self, worker, new, reason=None):
        if new not in rp._ALLOWED_TRANSITIONS[worker.worker_state]:
            raise AssertionError(f"illegal transition {worker.state} -> {new.value}")
        worker.state, worker.state_reason = new.value, reason

    def _write_result(self, worker, payload):
        pass


def runner_worker_json(message=QUOTA_RESET_MESSAGE, provider="alpha") -> dict:
    """The Runner's own persisted worker.json of a real provider hold."""
    spec = rp.WorkerSpec(id="w1", worktree=PRIVATE_PATH, work_order="wo.md", provider=provider, mode="write")
    worker = rp.WorkerRuntime(spec=spec, order=0, state=rp.WorkerState.RUNNING.value)
    attempt = {"attempt": 1, "executed": True, "status": "COMPLETED", "evidence_complete": True,
               "process_confirmed_stopped": True, "provider_work_status": None}
    condition = availability.classify_provider_failure(message=message)
    rp.PipelineRunner._hold_for_provider(_PersistenceHost(), worker, attempt, condition, None, HIT)
    return json.loads(json.dumps(worker.to_dict()))


def router(provider="alpha", state="NONE", capacity="AVAILABLE", observed=OBSERVED, evidence_id=None) -> dict:
    return {"evidence_id": evidence_id or f"ev-router-{provider}", "source": qc.SOURCE_ROUTER_PROVIDER_FACTS,
            "provider_id": provider, "observed_at_utc": observed,
            "payload": {"provider_id": provider, "probe_available": True, "policy_mode": "write",
                        "policy_allow_shell": False, "policy_supported": True, "capabilities": ["READ_FILES"],
                        "availability": state, "capacity": capacity}}


def capacity(provider="alpha", state="NONE", cap_state="AVAILABLE", slots=2, observed=OBSERVED) -> dict:
    return {"evidence_id": f"ev-cap-{provider}", "source": qc.SOURCE_SCHEDULER_CAPACITY_FACTS,
            "provider_id": provider,
            "payload": {"provider_id": provider, "availability": state, "capacity": cap_state, "proven_slots": slots,
                        "observed_at_utc": observed}}


def wait(worker_json, provider="alpha") -> dict:
    return {"evidence_id": "ev-wait-w1", "source": qc.SOURCE_RUNNER_PROVIDER_WAIT, "provider_id": provider,
            "payload": worker_json}


def condition(message, provider="alpha") -> dict:
    payload = availability.classify_provider_failure(message=message).as_dict()
    return {"evidence_id": f"ev-cond-{provider}", "source": qc.SOURCE_RUNNER_PROVIDER_CONDITION,
            "provider_id": provider, "observed_at_utc": OBSERVED, "payload": payload}


def window() -> dict:
    return {"kind": "ROLLING", "duration_seconds": 86400}


RESERVE = ((qc.UNIT_INPUT_TOKENS, 1000), (qc.UNIT_OUTPUT_TOKENS, 500), (qc.UNIT_TOTAL_TOKENS, 1500))


def budget(maximum_tokens=10000, maximum_cost="10.00", reserve=RESERVE) -> dict:
    def quantity(unit, amount):
        return {"unit": unit, "minimum": amount, "maximum": amount}

    def tariff(tid, unit, rate):
        return {"tariff_id": tid, "provider_id": "alpha", "unit": unit, "rate": rate, "per_quantity": 1000000,
                "currency": "EUR", "effective_from_utc": "2026-01-01T00:00:00Z"}

    section = {
        "policy": {"policy_id": "pol", "currency": "EUR", "granularity": "0.01", "limits": [
            {"limit_id": "tok", "scope": "GLOBAL", "unit": qc.UNIT_TOTAL_TOKENS, "maximum": maximum_tokens,
             "window": window()},
            {"limit_id": "money", "scope": "GLOBAL", "unit": "COST", "maximum": maximum_cost, "window": window()}]},
        "executions": [{"execution_id": "e1", "provider_id": "alpha", "incurred_at_utc": "2026-10-31T11:00:00Z"}],
        "receipts": [{"receipt_id": "r1", "execution_id": "e1", "basis": "OBSERVED", "reliability": "CALLER_OBSERVED",
                      "recorded_at_utc": "2026-10-31T11:05:00Z",
                      "quantities": [quantity(qc.UNIT_INPUT_TOKENS, 1000), quantity(qc.UNIT_OUTPUT_TOKENS, 500),
                                     quantity(qc.UNIT_TOTAL_TOKENS, 1500)]}],
        "tariffs": [tariff("t-in", qc.UNIT_INPUT_TOKENS, "3"), tariff("t-out", qc.UNIT_OUTPUT_TOKENS, "15")],
    }
    if reserve:
        section["reservation"] = {"reservation_id": "next", "provider_id": "alpha",
                                  "amounts": [[u, a] for u, a in reserve]}
    return section


def document(records=None, **kw) -> dict:
    doc = {"schema": rep.INPUT_SCHEMA, "schema_version": rep.INPUT_SCHEMA_VERSION, "request_id": "rep-1",
           "as_of_utc": AS_OF, "records": [router(), capacity()] if records is None else records}
    doc.update(kw)
    return doc


def snapshot(root: Path) -> dict:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class ReportTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="fcp10d01"))
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def write(self, payload, name=None) -> str:
        type(self).counter += 1
        path = self.root / (name or f"doc-{type(self).counter}.json")
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        path.write_bytes(data)
        return str(path)

    def invoke(self, *argv) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = rep.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def report(self, doc, *extra) -> tuple:
        code, out, err = self.invoke("--input-file", self.write(doc), *extra)
        self.assertEqual(err, "")
        return code, json.loads(out) if "--format" not in extra else out

    def assertRefused(self, payload, code_token, *codes, path=None):
        code, out, err = self.invoke("--input-file", path if path is not None else self.write(payload))
        self.assertEqual((code, out), (rep.EXIT_REFUSED, ""))
        self.assertTrue(err.startswith(f"error: {code_token}: "), err)
        for c in codes:
            self.assertIn(c, err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn(str(self.root), err)
        return err

    def decision(self, report, subject, subject_id):
        found = [d for d in report["decisions"] if (d["subject"], d["id"]) == (subject, subject_id)]
        self.assertEqual(len(found), 1, report["decisions"])
        return found[0]


# ---------------------------------------------------------------------------
class ReportSemanticsTests(ReportTestBase):
    def test_observed_available_provider_and_ready_budget_is_clear_exit_0(self):
        code, report = self.report(document(budget=budget()))
        self.assertEqual((code, report["status"]), (rep.EXIT_OK, rep.CLEAR))
        self.assertEqual(report["quota"]["outcome"], qo.OBSERVED)
        view = report["quota"]["providers"][0]
        self.assertEqual((view["provider_id"], view["availability"], view["capacity"], view["certainty"]),
                         ("alpha", "NONE", "AVAILABLE", qo.CERTAIN))
        self.assertEqual(view["evidence_ids"], ["ev-cap-alpha", "ev-router-alpha"])
        provider = self.decision(report, rep.SUBJECT_PROVIDER, "alpha")
        self.assertEqual((provider["status"], provider["actor"], provider["action"]),
                         (rep.CLEAR, rq.ACTOR_NONE, rq.NO_ACTION))
        self.assertEqual(report["budget"]["verdict"], bg.READY)
        self.assertEqual(report["next_safe_steps"], [])
        self.assertEqual(report["blocking_risk"]["clear"], ["BUDGET:rep-1", "BUDGET_LIMIT:money", "BUDGET_LIMIT:tok",
                                                            "PROVIDER:alpha"])

    def test_real_runner_quota_hold_is_waiting_on_the_runner_with_its_own_eligibility(self):
        code, report = self.report(document([wait(runner_worker_json())]))
        self.assertEqual((code, report["status"]), (rep.EXIT_WAITING, rep.WAITING))
        view = report["quota"]["providers"][0]
        self.assertEqual((view["availability"], view["next_eligible_utc"], view["eligibility_source"]),
                         ("QUOTA_WAIT", "2026-10-31T15:01:00Z", qc.ELIGIBILITY_RESET_HINT))
        provider = self.decision(report, rep.SUBJECT_PROVIDER, "alpha")
        self.assertEqual((provider["actor"], provider["action"]), (rq.ACTOR_RUNNER, rq.AWAIT_RUNNER_ELIGIBILITY))
        self.assertIn(rq.COOLDOWN_PENDING, provider["reasons"])
        self.assertEqual(provider["evidence_ids"], ["ev-wait-w1"])
        self.assertEqual(report["next_safe_step"], {"actor": rq.ACTOR_RUNNER, "action": rq.AWAIT_RUNNER_ELIGIBILITY})

    def test_passed_eligibility_is_never_inferred_as_recovered(self):
        doc = document([wait(runner_worker_json())], as_of_utc="2026-10-31T16:00:00Z",
                       max_evidence_age_seconds=qc.MAX_EVIDENCE_AGE_SECONDS)
        code, report = self.report(doc)
        self.assertEqual((code, report["status"]), (rep.EXIT_WAITING, rep.WAITING))
        provider = self.decision(report, rep.SUBJECT_PROVIDER, "alpha")
        self.assertIn(rq.RECOVERY_UNCONFIRMED, provider["reasons"])
        self.assertEqual(provider["action"], rq.OBSERVE_RUNNER_QUOTA_PROBE)
        self.assertNotEqual(report["quota"]["providers"][0]["availability"], "NONE")

    def test_real_runner_auth_hold_is_blocked_for_a_human_exit_5(self):
        code, report = self.report(document([wait(runner_worker_json(AUTH_MESSAGE)), router()]))
        self.assertEqual((code, report["status"]), (rep.EXIT_BLOCKED, rep.BLOCKED))
        self.assertEqual(report["quota"]["providers"][0]["availability"], "AUTH_BLOCKED")
        provider = self.decision(report, rep.SUBJECT_PROVIDER, "alpha")
        self.assertEqual((provider["status"], provider["actor"], provider["action"]),
                         (rep.BLOCKED, rq.ACTOR_HUMAN, rq.RESTORE_PROVIDER_AUTH))
        self.assertEqual(report["blocking_risk"]["blocked"], ["PROVIDER:alpha"])
        self.assertEqual(report["next_safe_step"], {"actor": rq.ACTOR_HUMAN, "action": rq.RESTORE_PROVIDER_AUTH})

    def test_one_blocked_provider_is_never_hidden_by_a_clear_one(self):
        records = [router(), capacity(), router("beta", state="AUTH_BLOCKED", capacity="UNKNOWN")]
        code, report = self.report(document(records))
        self.assertEqual((code, report["status"]), (rep.EXIT_BLOCKED, rep.BLOCKED))
        self.assertEqual(self.decision(report, rep.SUBJECT_PROVIDER, "alpha")["status"], rep.CLEAR)
        self.assertEqual(self.decision(report, rep.SUBJECT_PROVIDER, "beta")["status"], rep.BLOCKED)

    def test_classified_quota_without_runner_eligibility_is_unknown_exit_4(self):
        code, report = self.report(document([condition("quota exceeded for this account")]))
        self.assertEqual((code, report["status"]), (rep.EXIT_UNKNOWN, rep.UNKNOWN))
        provider = self.decision(report, rep.SUBJECT_PROVIDER, "alpha")
        self.assertIn(rq.ELIGIBILITY_UNOBSERVED, provider["reasons"])
        self.assertEqual((provider["actor"], provider["action"]), (rq.ACTOR_HUMAN, rq.REVIEW_QUOTA_EVIDENCE))

    def test_no_evidence_is_unknown_never_clear(self):
        code, report = self.report(document([]))
        self.assertEqual((code, report["status"]), (rep.EXIT_UNKNOWN, rep.UNKNOWN))
        evidence = self.decision(report, rep.SUBJECT_QUOTA_EVIDENCE, "rep-1")
        self.assertIn(qo.NO_EVIDENCE, evidence["reasons"])
        code, report = self.report(document([], provider_ids=["alpha"]))
        self.assertEqual(code, rep.EXIT_UNKNOWN)
        self.assertIn(rq.QUOTA_EVIDENCE_MISSING, self.decision(report, rep.SUBJECT_PROVIDER, "alpha")["reasons"])

    def test_available_provider_with_uncertain_capacity_is_never_clear(self):
        code, report = self.report(document([router(capacity="UNKNOWN")]))
        self.assertEqual((code, report["status"]), (rep.EXIT_UNKNOWN, rep.UNKNOWN))
        self.assertEqual(self.decision(report, rep.SUBJECT_PROVIDER, "alpha")["status"], rep.CLEAR)
        evidence = self.decision(report, rep.SUBJECT_QUOTA_EVIDENCE, "alpha")
        self.assertEqual((evidence["status"], evidence["reasons"], evidence["evidence_ids"]),
                         (rep.UNKNOWN, [qo.CAPACITY_UNKNOWN], ["ev-router-alpha"]))
        self.assertEqual(report["next_safe_step"], {"actor": rq.ACTOR_HUMAN, "action": rq.REVIEW_QUOTA_EVIDENCE})

    def test_stale_evidence_is_unknown(self):
        code, report = self.report(document([router(observed="2026-10-31T10:00:00Z")]))
        self.assertEqual(code, rep.EXIT_UNKNOWN)
        self.assertIn(qo.EVIDENCE_STALE, report["quota"]["providers"][0]["reasons"])

    def test_unbuildable_payloads_are_rejected_by_a02_not_dropped(self):
        broken = router()
        del broken["payload"]["capacity"]
        foreign_wait = runner_worker_json()
        foreign_wait["provider_wait"]["injected"] = "x"
        records = [broken, {**router(evidence_id="ev-x"), "source": "SCRAPED_WEBPAGE"},
                   {**router(evidence_id="ev-op"), "source": qc.SOURCE_OPERATOR_DECLARATION},
                   wait(foreign_wait), {**wait({"state": "WAITING_PROVIDER_QUOTA"}), "evidence_id": "ev-nospec"}]
        code, report = self.report(document(records))
        self.assertEqual((code, report["status"]), (rep.EXIT_UNKNOWN, rep.UNKNOWN))
        reasons = {r["index"]: r["reasons"] for r in report["quota"]["rejected_records"]}
        self.assertEqual(reasons, {0: [qo.PAYLOAD_NOT_TYPED], 1: [qo.SOURCE_UNKNOWN], 2: [qo.SOURCE_NOT_ADAPTABLE],
                                   3: [qo.PAYLOAD_UNEXPECTED_FIELD], 4: [qo.PAYLOAD_NOT_TYPED]})
        self.assertIn(rep.EVIDENCE_REJECTED, self.decision(report, rep.SUBJECT_QUOTA_EVIDENCE, "rep-1")["reasons"])

    def test_deadline_reached_is_blocked_for_a_new_window_decision(self):
        doc = document([wait(runner_worker_json())], deadline_utc="2026-10-31T11:00:00Z")
        code, report = self.report(doc)
        self.assertEqual(code, rep.EXIT_BLOCKED)
        provider = self.decision(report, rep.SUBJECT_PROVIDER, "alpha")
        self.assertEqual(provider["action"], rq.DECIDE_NEW_EXECUTION_WINDOW)
        self.assertEqual(report["deadline_utc"], "2026-10-31T11:00:00Z")

    def test_saturated_budget_waits_on_direction(self):
        code, report = self.report(document(budget=budget(maximum_tokens=2000)))
        self.assertEqual((code, report["status"]), (rep.EXIT_WAITING, rep.WAITING))
        limit = self.decision(report, rep.SUBJECT_BUDGET_LIMIT, "tok")
        self.assertEqual((limit["status"], limit["actor"], limit["action"]),
                         (rep.WAITING, rep.ACTOR_DIRECTION, rep.REQUEST_DIRECTION))
        self.assertIn(bg.LIMIT_SATURATED, limit["reasons"])

    def test_reservation_exceeding_a_budget_is_blocked(self):
        doc = document(budget=budget(maximum_tokens=100000, reserve=((qc.UNIT_TOTAL_TOKENS, 200000),)))
        code, report = self.report(doc)
        self.assertEqual(code, rep.EXIT_BLOCKED)
        self.assertIn(bg.RESERVATION_EXCEEDS_LIMIT, self.decision(report, rep.SUBJECT_BUDGET_LIMIT, "tok")["reasons"])

    def test_untariffed_reservation_is_unknown_not_ready(self):
        code, report = self.report(document(budget=budget(reserve=((qc.UNIT_TOTAL_TOKENS, 2000),))))
        self.assertEqual(code, rep.EXIT_UNKNOWN)
        self.assertEqual(self.decision(report, rep.SUBJECT_BUDGET_LIMIT, "money")["status"], rep.UNKNOWN)

    def test_reserved_capacity_reports_proven_slots_and_projected_budget(self):
        _, report = self.report(document(budget=budget()))
        reserved = report["reserved_capacity"]
        self.assertEqual(reserved["proven_slots"], [{"provider_id": "alpha", "capacity": "AVAILABLE",
                                                     "proven_slots": 2}])
        tok = [a for a in reserved["budget_reservations"] if a["limit_id"] == "tok"][0]
        self.assertEqual((tok["reserved"], tok["projected"], tok["maximum"]), (1500, 3000, 10000))
        money = [a for a in reserved["budget_reservations"] if a["limit_id"] == "money"][0]
        self.assertEqual((money["reserved"], money["projected"], money["maximum"]), ("0.02", "0.04", "10.00"))

    def test_budget_engine_refusal_is_a_report_refusal_with_its_codes(self):
        doc = document(budget=budget(maximum_cost="ten euros"))
        self.assertRefused(doc, "REPORT_BUDGET_REFUSED", bg.COST_MAXIMUM_INVALID)
        doc = document(budget=budget())
        doc["budget"]["policy"]["currency"] = "eur"
        self.assertRefused(doc, "REPORT_BUDGET_REFUSED", bg.CURRENCY_INVALID)

    def test_quota_engine_refusals_keep_their_codes(self):
        self.assertRefused(document(max_evidence_age_seconds=True), "REPORT_QUOTA_REFUSED",
                           qo.MAX_EVIDENCE_AGE_INVALID)
        self.assertRefused(document([router(evidence_id=f"ev-{i}") for i in range(qo.MAX_RECORDS + 1)]),
                           "REPORT_QUOTA_REFUSED", qo.RECORDS_MALFORMED)
        self.assertRefused(document(as_of_utc="2026-10-31T12:00:00+02:00"), "REPORT_QUOTA_REFUSED", qo.AS_OF_INVALID)

    def test_recovery_engine_refusal_keeps_its_codes(self):
        self.assertRefused(document(deadline_utc="tomorrow"), "REPORT_RECOVERY_REFUSED", rq.DEADLINE_INVALID)


# ---------------------------------------------------------------------------
class CanonicalShapeTests(ReportTestBase):
    def test_report_is_canonical_self_verifying_and_has_a_fixed_key_set(self):
        code, out, _ = self.invoke("--input-file", self.write(document(budget=budget())))
        report = json.loads(out)
        self.assertEqual(code, rep.EXIT_OK)
        self.assertEqual(set(report), REPORT_KEYS)
        self.assertEqual(out.strip(), json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        self.assertTrue(out.strip().isascii())
        self.assertTrue(rep.verify_report(report))
        tampered = copy.deepcopy(report)
        tampered["status"] = rep.CLEAR if report["status"] != rep.CLEAR else rep.BLOCKED
        self.assertFalse(rep.verify_report(tampered))
        self.assertFalse(rep.verify_report({"status": "CLEAR"}))

    def test_sources_bind_the_engine_results(self):
        _, report = self.report(document(budget=budget()))
        self.assertEqual(report["sources"]["quota"]["schema"], qo.SCHEMA)
        self.assertEqual(report["sources"]["recovery"]["schema"], rq.SCHEMA)
        self.assertEqual(report["sources"]["budget"]["schema"], bg.SCHEMA)
        for name in ("quota", "recovery", "budget"):
            for field in ("fingerprint", "sha256"):
                value = report["sources"][name][field]
                self.assertEqual((len(value), set(value) <= set("0123456789abcdef")), (64, True))
        _, without = self.report(document())
        self.assertIsNone(without["sources"]["budget"])
        self.assertIsNone(without["budget"])

    def test_output_is_deterministic_and_independent_of_key_order(self):
        doc = document(budget=budget())
        first = self.invoke("--input-file", self.write(doc))
        second = self.invoke("--input-file", self.write(doc))
        reordered = json.loads(json.dumps(doc), object_pairs_hook=lambda pairs: dict(reversed(pairs)))
        third = self.invoke("--input-file", self.write(reordered))
        self.assertEqual(first, second)
        self.assertEqual(first, third)

    def test_text_format_carries_the_same_facts_and_exit(self):
        doc = document([wait(runner_worker_json())])
        code_json, report = self.report(doc)
        code_text, text = self.report(doc, "--format", "text")
        self.assertEqual(code_json, code_text)
        self.assertIn(f"report_sha256: {report['report_sha256']}", text)
        self.assertIn("status: WAITING", text)
        self.assertIn("next_safe_step: RUNNER AWAIT_RUNNER_ELIGIBILITY", text)
        self.assertIn("quota: alpha availability=QUOTA_WAIT", text)
        self.assertIn("not_authorized: DISPATCH,RETRY,RESUME,PROVIDER_SWITCH", text)

    def test_every_authority_flag_is_false_and_actions_stay_unauthorized(self):
        for doc in (document(budget=budget()), document([wait(runner_worker_json(AUTH_MESSAGE))])):
            _, report = self.report(doc)
            for flag in rep.AUTHORITY_FLAGS:
                self.assertIs(report[flag], False)
            self.assertEqual(report["marker"], rep.REPORT_MARKER)
            self.assertEqual(report["authority"]["execution_authority"], "RUNNER")
            self.assertIs(report["authority"]["launcher"], False)
            self.assertEqual(report["not_authorized_actions"], list(rep.NOT_AUTHORIZED_ACTIONS))
        for action in ("DISPATCH", "RETRY", "PROVIDER_SWITCH", "PURCHASE", "REMOTE_API_CALL", "COMMIT",
                       "CHECKPOINT_CONSOLIDATION", "VERDICT_UPGRADE", "CONFIG_WRITE"):
            self.assertIn(action, rep.NOT_AUTHORIZED_ACTIONS)
        engine_flags = set(rq._RecoveryGuarantees._guarantees()) | set(bg._BudgetGuarantees._guarantees())
        self.assertLessEqual(engine_flags - {"marker"}, set(rep.AUTHORITY_FLAGS))

    def test_exit_codes_are_stable_and_only_clear_is_zero(self):
        self.assertEqual((rep.EXIT_OK, rep.EXIT_REFUSED, rep.EXIT_USAGE, rep.EXIT_WAITING, rep.EXIT_UNKNOWN,
                          rep.EXIT_BLOCKED), (0, 1, 2, 3, 4, 5))
        self.assertEqual(set(rep.EXIT_OF_STATUS), set(rep.STATUSES))
        self.assertEqual([s for s, c in rep.EXIT_OF_STATUS.items() if c == 0], [rep.CLEAR])
        for report in (None, {}, {"status": "PASS"}, {"status": "READY"}, []):
            self.assertEqual(rep.exit_code_for(report), rep.EXIT_REFUSED)

    def test_budget_status_mapping_reuses_existing_actions_only(self):
        self.assertEqual(set(rep._BUDGET_RULES), set(bg.VERDICTS))
        for status, actor, action in rep._BUDGET_RULES.values():
            self.assertIn(status, rep.STATUSES)
            self.assertIn(actor, rq.ACTORS)
            self.assertIn(action, rq.ACTIONS)
        self.assertEqual(rep._BUDGET_RULES[bg.READY][0], rep.CLEAR)
        self.assertEqual(rep._BUDGET_RULES[bg.REFUSE][0], rep.BLOCKED)


# ---------------------------------------------------------------------------
class StrictParserTests(ReportTestBase):
    def test_duplicate_keys_are_refused(self):
        self.assertRefused(b'{"schema": "a", "schema": "b"}', "REPORT_INPUT_DUPLICATE_KEY")

    def test_nan_infinity_and_oversized_numbers_are_refused(self):
        for raw in (b'{"x": NaN}', b'{"x": Infinity}', b'{"x": -Infinity}', b'{"x": 1e400}', b'{"x": -1e999}',
                    b'{"x": 0.' + b"1" * 40 + b"}", b'{"x": ' + b"9" * 40 + b"}"):
            with self.subTest(raw=raw[:20]):
                self.assertRefused(raw, "REPORT_INPUT_NUMBER_FORBIDDEN")

    def test_float_money_and_float_counts_are_refused_by_the_engines(self):
        doc = document(budget=budget())
        doc["budget"]["tariffs"][0]["rate"] = 3.0
        self.assertRefused(doc, "REPORT_BUDGET_REFUSED", bg.TARIFF_RATE_INVALID)
        doc = document(budget=budget())
        doc["budget"]["policy"]["granularity"] = 0.01
        self.assertRefused(doc, "REPORT_BUDGET_REFUSED", bg.GRANULARITY_INVALID)
        self.assertRefused(document(max_evidence_age_seconds=900.0), "REPORT_QUOTA_REFUSED",
                           qo.MAX_EVIDENCE_AGE_INVALID)
        for money in ("1e3", "01.5", "-1", "1.", ".5", "１"):
            doc = document(budget=budget(maximum_cost=json.loads(f'"{money}"')))
            self.assertRefused(doc, "REPORT_BUDGET_REFUSED", bg.COST_MAXIMUM_INVALID)

    def test_non_utf8_and_bom_are_refused(self):
        self.assertRefused(b"\xef\xbb\xbf" + json.dumps(document()).encode(), "REPORT_INPUT_NOT_UTF8")
        self.assertRefused(b'{"schema": "\xff\xfe"}', "REPORT_INPUT_NOT_UTF8")
        self.assertRefused(json.dumps(document()).encode("utf-16"), "REPORT_INPUT_NOT_UTF8")

    def test_excessive_depth_is_refused_without_recursion_errors(self):
        self.assertRefused(b"[" * 50000 + b"]" * 50000, "REPORT_INPUT_TOO_DEEP")
        nested = document()
        nested["records"][0]["payload"]["capabilities"] = json.loads("[" * 20 + "]" * 20)
        self.assertRefused(nested, "REPORT_INPUT_TOO_DEEP")

    def test_lone_surrogates_and_oversized_strings_are_refused(self):
        self.assertRefused(b'{"schema": "\\ud800"}', "REPORT_INPUT_STRING_INVALID")
        self.assertRefused(document(request_id="r" * (rep.MAX_STRING_CHARS + 1)), "REPORT_INPUT_STRING_INVALID")

    def test_not_json_and_trailing_bytes_are_refused(self):
        for raw in (b"", b"not json", b'{"a": 1} {"b": 2}', b"{'a': 1}", b'{"a": 1,}'):
            with self.subTest(raw=raw):
                self.assertRefused(raw, "REPORT_INPUT_JSON_INVALID")

    def test_documented_keys_only(self):
        self.assertRefused(document(extra="x"), "REPORT_INPUT_FIELD_UNKNOWN")
        doc = document()
        del doc["records"]
        self.assertRefused(doc, "REPORT_INPUT_FIELD_MISSING")
        doc = document()
        doc["records"][0]["note"] = "free text"
        self.assertRefused(doc, "REPORT_INPUT_FIELD_UNKNOWN")
        doc = document(budget=budget())
        doc["budget"]["policy"]["limits"][0]["price"] = 1
        self.assertRefused(doc, "REPORT_INPUT_FIELD_UNKNOWN")

    def test_schema_and_shapes_are_exact(self):
        self.assertRefused(document(schema="fcp10d01-other"), "REPORT_INPUT_SCHEMA_UNSUPPORTED")
        self.assertRefused(document(schema_version=True), "REPORT_INPUT_SCHEMA_UNSUPPORTED")
        self.assertRefused(document(schema_version=2), "REPORT_INPUT_SCHEMA_UNSUPPORTED")
        self.assertRefused([document()], "REPORT_INPUT_SHAPE_INVALID")
        self.assertRefused(document(records={"0": router()}), "REPORT_INPUT_SHAPE_INVALID")
        self.assertRefused(document(records=["ev-1"]), "REPORT_INPUT_SHAPE_INVALID")

    def test_unicode_identifiers_are_refused_or_rejected_and_output_stays_ascii(self):
        self.assertRefused(document(request_id="r\u0435p-1"), "REPORT_QUOTA_REFUSED", qo.REQUEST_ID_INVALID)
        record = router(provider="\u0430lpha")
        code, report = self.report(document([record, router(), capacity()]))
        self.assertEqual(code, rep.EXIT_UNKNOWN)
        self.assertEqual(report["quota"]["rejected_records"][0]["provider_id"], None)
        self.assertIn(qo.EVIDENCE_UNATTRIBUTED, report["quota"]["snapshot_reasons"])
        self.assertTrue(json.dumps(report, ensure_ascii=False).isascii())

    def test_secrets_and_prose_are_never_echoed(self):
        worker = runner_worker_json()
        worker["provider_wait"]["message_excerpt"] = f"token {SECRET} at {PRIVATE_PATH}"
        worker["provider_wait"]["reason"] = SECRET
        doc = document([wait(worker), condition(f"quota exceeded {SECRET}")], provider_ids=["alpha"])
        for fmt in ("json", "text"):
            code, out, err = self.invoke("--input-file", self.write(doc), "--format", fmt)
            self.assertNotIn(SECRET, out + err)
            self.assertNotIn("private", out + err)
            self.assertNotIn("Q" * 20, out + err)
        err = self.assertRefused(document(request_id="a" * 40 + "b"), "REPORT_QUOTA_REFUSED", qo.ID_SECRET_SHAPED)
        self.assertNotIn("a" * 40, err)
        err = self.assertRefused(document(records=[{**router(), "evidence_id": SECRET, "x": 1}]),
                                 "REPORT_INPUT_FIELD_UNKNOWN")
        self.assertNotIn(SECRET, err)


# ---------------------------------------------------------------------------
class PathAdmissionTests(ReportTestBase):
    def test_relative_traversal_nul_and_stream_paths_are_not_admissible(self):
        good = self.write(document())
        for path in ("doc.json", "scripts/doc.json", str(self.root / ".." / Path(good).name), good + "\x00x",
                     good + ":stream", "C:relative.json" if os.name == "nt" else "relative.json", ""):
            with self.subTest(path=path):
                self.assertRefused(None, "REPORT_PATH_NOT_ADMISSIBLE", path=path)

    def test_network_device_and_url_paths_are_refused(self):
        for path in ("\\\\server\\share\\doc.json", "//server/share/doc.json", "\\\\?\\C:\\doc.json",
                     "\\\\.\\pipe\\quota", "\\\\?\\UNC\\server\\share\\doc.json", "file:///C:/doc.json",
                     "http://example.invalid/doc.json", "smb://server/share/doc.json"):
            with self.subTest(path=path):
                self.assertRefused(None, "REPORT_PATH_NETWORK_REFUSED", path=path)

    def test_missing_files_and_directories_are_invalid(self):
        self.assertRefused(None, "REPORT_INPUT_FILE_INVALID", path=str(self.root / "absent.json"))
        self.assertRefused(None, "REPORT_INPUT_FILE_INVALID", path=str(self.root))

    def test_symlinks_and_junctions_are_refused(self):
        target = Path(self.write(document()))
        link = self.root / "link.json"
        if os.name == "nt":
            import _winapi
            real_dir = self.root / "real-dir"
            real_dir.mkdir()
            (real_dir / "doc.json").write_bytes(target.read_bytes())
            _winapi.CreateJunction(str(real_dir), str(self.root / "junction"))
            self.addCleanup(os.rmdir, str(self.root / "junction"))
            self.assertRefused(None, "REPORT_PATH_LINK_REFUSED", path=str(self.root / "junction"))
            self.assertRefused(None, "REPORT_PATH_LINK_REFUSED", path=str(self.root / "junction" / "doc.json"))
            self.assertEqual(self.invoke("--input-file", str(real_dir / "doc.json"))[0], rep.EXIT_OK)
        try:
            os.symlink(str(target), str(link))
        except OSError:
            link = None
        if link is not None:
            self.assertRefused(None, "REPORT_PATH_LINK_REFUSED", path=str(link))
        self.assertTrue(os.name == "nt" or link is not None)

    def test_oversized_files_are_refused_before_parsing(self):
        data = json.dumps(document()).encode() + b" " * rep.MAX_INPUT_BYTES
        self.assertRefused(data, "REPORT_INPUT_TOO_LARGE")
        exact = json.dumps(document()).encode()
        exact += b" " * (rep.MAX_INPUT_BYTES - len(exact))
        self.assertEqual(self.invoke("--input-file", self.write(exact))[0], rep.EXIT_OK)

    def test_a_path_swapped_after_admission_is_refused(self):
        path = self.write(document())
        real_lstat = os.lstat
        calls = []

        def swapped_lstat(p, *args, **kwargs):
            result = real_lstat(p, *args, **kwargs)
            calls.append(p)
            if len(calls) == 2:  # the identity snapshot taken right before opening
                return os.stat_result((result.st_mode, result.st_ino + 1) + tuple(result)[2:])
            return result

        with mock.patch.object(rep.os, "lstat", swapped_lstat):
            self.assertRefused(None, "REPORT_PATH_LINK_REFUSED", path=path)


# ---------------------------------------------------------------------------
class IsolationTests(ReportTestBase):
    def module(self, *argv, code=None):
        args = ["-c", code] if code else ["-m", "scripts.ai.fabric_resource_quota_report", *argv]
        return subprocess.run([sys.executable, *args], cwd=str(REPO_ROOT), capture_output=True, text=True,
                              timeout=120)

    def test_engines_are_imported_lazily(self):
        probe = (
            "import sys\n"
            "from scripts.ai import fabric_resource_quota_report as r\n"
            "heavy = ('scripts.ai.runner_pipeline', 'scripts.ai.fabric_resource_quota_observation',\n"
            "         'scripts.ai.fabric_resource_quota_budget', 'scripts.ai.fabric_resource_quota_recovery',\n"
            "         'subprocess', 'socket')\n"
            "print(sorted(m for m in heavy if m in sys.modules))\n"
            "try:\n"
            "    r.main(['--bogus'])\n"
            "except SystemExit as exc:\n"
            "    print(exc.code)\n"
            "print(sorted(m for m in heavy if m in sys.modules))\n"
        )
        completed = self.module(code=probe)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(lines[0], "[]")
        self.assertEqual(lines[1], str(rep.EXIT_USAGE))
        self.assertEqual(lines[2], "[]")

    def test_module_entry_point_exit_codes_and_clean_refusals(self):
        completed = self.module("--input-file", self.write(document([wait(runner_worker_json())])))
        self.assertEqual((completed.returncode, completed.stderr), (rep.EXIT_WAITING, ""))
        self.assertTrue(rep.verify_report(json.loads(completed.stdout)))
        secret_path = str(self.root / f"{SECRET}.json")
        for argv, code, token in ((["--input-file", secret_path], rep.EXIT_REFUSED, "REPORT_INPUT_FILE_INVALID"),
                                  (["--input-file", secret_path, "--watch"], rep.EXIT_USAGE, "REPORT_USAGE_INVALID"),
                                  ([], rep.EXIT_USAGE, "REPORT_USAGE_INVALID"),
                                  (["--input-file", secret_path, "--format", "yaml"], rep.EXIT_USAGE,
                                   "REPORT_USAGE_INVALID")):
            with self.subTest(token=token, argv=len(argv)):
                completed = self.module(*argv)
                self.assertEqual((completed.returncode, completed.stdout), (code, ""))
                self.assertIn(token, completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)
                self.assertNotIn(SECRET, completed.stderr)

    def test_report_runs_without_network_process_or_write(self):
        doc = document([wait(runner_worker_json()), router("beta"), capacity("beta")], budget=budget())
        path = self.write(doc)
        real_open = builtins.open

        def guarded_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise AssertionError("write attempted")
            return real_open(file, mode, *args, **kwargs)

        def refuse(*_args, **_kwargs):
            raise AssertionError("network, process or mutation attempted")

        before = snapshot(self.root)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(builtins, "open", guarded_open))
            for target, name in ((socket, "socket"), (socket, "create_connection"), (socket, "getaddrinfo"),
                                 (subprocess, "Popen"), (subprocess, "run"), (os, "system"), (os, "mkdir"),
                                 (os, "makedirs"), (os, "remove"), (os, "unlink"), (os, "rename"), (os, "replace"),
                                 (os, "rmdir"), (os, "write")):
                stack.enter_context(mock.patch.object(target, name, refuse))
            code, out, err = self.invoke("--input-file", path)
        self.assertEqual((code, err), (rep.EXIT_WAITING, ""))
        self.assertEqual(json.loads(out)["status"], rep.WAITING)
        self.assertEqual(snapshot(self.root), before)

    def test_unexpected_engine_failure_is_a_clean_internal_refusal(self):
        path = self.write(document())
        with mock.patch.object(qo, "adapt_observations", side_effect=RuntimeError(SECRET)):
            code, out, err = self.invoke("--input-file", path)
        self.assertEqual((code, out), (rep.EXIT_REFUSED, ""))
        self.assertIn("REPORT_INTERNAL_ERROR", err)
        self.assertNotIn(SECRET, err)


# ---------------------------------------------------------------------------
class StaticGovernanceTests(unittest.TestCase):
    def tree(self):
        return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    def test_top_level_imports_are_stdlib_only_and_never_process_or_network(self):
        tree = self.tree()
        top = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                top.add(node.module)
        self.assertEqual(top, {"__future__", "argparse", "dataclasses", "hashlib", "json", "math", "os", "re", "stat",
                               "sys", "decimal", "pathlib", "types", "typing"})
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= {f"{node.module}.{a.name}" for a in node.names} | {node.module}
        forbidden = ("subprocess", "socket", "urllib", "http", "requests", "shutil", "threading", "multiprocessing",
                     "concurrent", "asyncio", "sched", "datetime", "time", "claude_runner", "runner_providers",
                     "runner_promotion", "fabric_scheduler_gateway", "fabric_director", "runner_git", "sqlite3")
        for name in imported:
            for word in forbidden:
                self.assertNotIn(word, name.split("."))

    def test_module_calls_no_mutating_clock_environment_or_execution_api(self):
        tree = self.tree()
        attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("environ", "getenv", "putenv", "write_text", "write_bytes", "mkdir", "makedirs", "remove",
                          "unlink", "rename", "replace", "system", "popen", "Popen", "now", "utcnow", "sleep",
                          "symlink", "chmod", "fork", "spawn", "connect", "urlopen", "run_blueprint", "submit",
                          "advance", "_hold_for_provider", "_start_ready", "serve_forever"):
            self.assertNotIn(forbidden, attributes)
            self.assertNotIn(forbidden, names)
        self.assertNotIn("open", {n.func.id for n in ast.walk(tree)
                                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)})

    def test_engine_contracts_are_reused_not_redefined(self):
        e = rep.engines()
        self.assertIs(e.qo.adapt_observations, qo.adapt_observations)
        self.assertIs(e.rq.advise_recovery, rq.advise_recovery)
        self.assertIs(e.bg.evaluate_budget, bg.evaluate_budget)
        self.assertIs(e.pipeline.WorkerRuntime.from_dict.__func__, rp.WorkerRuntime.from_dict.__func__)
        code = MODULE_PATH.read_text(encoding="utf-8").split('"""', 2)[2]
        defined = {n.name for n in ast.walk(ast.parse(code)) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for duplicated in ("adapt_observations", "advise_recovery", "evaluate_budget", "verdict_for", "outcome_for",
                           "_assess_provider", "_provider_view", "parse_utc", "Lease", "Pool", "Ledger"):
            self.assertNotIn(duplicated, defined)

    def test_runner_object_mapping_matches_the_runner_and_router_fields(self):
        self.assertEqual(rep._CLASSIFICATION_KEYS,
                         set(availability.classify_provider_failure(message="x").as_dict()))
        self.assertIsNone(rep.native_payload(qc.SOURCE_OPERATOR_DECLARATION, {}))
        self.assertIsNone(rep.native_payload("UNKNOWN_SOURCE", {}))
        self.assertIsNone(rep.native_payload(qc.SOURCE_RUNNER_PROVIDER_CONDITION, {"condition": "MADE_UP"}))
        worker = rep.native_payload(qc.SOURCE_RUNNER_PROVIDER_WAIT, runner_worker_json())
        self.assertIs(type(worker), rp.WorkerRuntime)
        self.assertEqual(worker.state, rp.WorkerState.WAITING_PROVIDER_QUOTA.value)


if __name__ == "__main__":
    unittest.main()
