"""Provider quota / auth / transient availability guard (Runner V2).

Everything here is deterministic: a fake clock drives every wait, timezone
resolution is injected, and no test sleeps for real beyond a millisecond.
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.ai import claude_runner as runner
from scripts.ai import runner_pipeline as rp
from scripts.ai import runner_provider_availability as av
from scripts.ai import runner_providers as providers
import scripts.tests.test_runner_pipeline as tp
import scripts.tests.test_runner_providers as tpv

RS = runner.RunState
QUOTA = av.ProviderCondition.QUOTA_EXHAUSTED
AUTH = av.ProviderCondition.AUTH_BLOCKED
TRANSIENT = av.ProviderCondition.TRANSIENT_ERROR
EXECUTION = av.ProviderCondition.EXECUTION_ERROR

QUOTA_TEXT = "You've hit your session limit · resets 3pm (Europe/Madrid)"
QUOTA_TEXT_NO_HINT = "You've hit your session limit"
MADRID_SUMMER = timezone(timedelta(hours=2))
UTC = timezone.utc


def envelope(status=429, *, result=QUOTA_TEXT, terminal="api_error", is_error=True) -> str:
    """Claude CLI `--output-format json` error envelope (the demonstrated shape)."""
    return json.dumps({
        "type": "result", "is_error": is_error, "api_error_status": status,
        "terminal_reason": terminal, "result": result,
    })


def fake_tz(name):
    if name == "Europe/Madrid":
        return MADRID_SUMMER
    raise av.ZoneInfoNotFoundError(name)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


# ---------------------------------------------------------------------------
class ClassificationTests(unittest.TestCase):
    def classify(self, stdout="", stderr="", error_text=None, provider=None):
        return (provider or providers.ClaudeProvider()).classify_failure(
            stdout=stdout, stderr=stderr, error_text=error_text)

    def test_demonstrated_claude_429_session_limit_is_quota_exhausted(self):  # 1
        c = self.classify(envelope())
        self.assertEqual(c.condition, QUOTA)
        self.assertEqual((c.http_status, c.terminal_reason), (429, "api_error"))
        self.assertEqual(c.reset_hint, "resets 3pm (Europe/Madrid)")

    def test_plain_429_is_transient_never_quota(self):
        for text in ("Too many requests, slow down", "rate limit exceeded", ""):
            with self.subTest(text=text):
                self.assertEqual(self.classify(envelope(429, result=text)).condition, TRANSIENT)

    def test_quota_wording_under_a_server_status_is_not_quota(self):
        self.assertEqual(self.classify(envelope(500)).condition, TRANSIENT)
        self.assertEqual(self.classify(envelope(503, result="Overloaded")).condition, TRANSIENT)

    def test_auth_failures_are_auth_blocked(self):
        self.assertEqual(self.classify(envelope(401, result="Invalid API key")).condition, AUTH)
        self.assertEqual(
            self.classify("", stderr="Not logged in · Please run /login").condition, AUTH)
        self.assertEqual(self.classify(envelope(None, result="OAuth token has expired")).condition, AUTH)

    def test_network_text_is_transient(self):
        self.assertEqual(self.classify("", stderr="read ECONNRESET").condition, TRANSIENT)

    def test_generic_error_is_execution_error(self):
        self.assertEqual(self.classify(envelope(None, result="tool crashed")).condition, EXECUTION)
        self.assertEqual(self.classify("", stderr="segfault").condition, EXECUTION)
        self.assertEqual(self.classify("not json at all").condition, EXECUTION)

    def test_default_adapter_reads_stderr_but_never_agent_stdout(self):  # extensibility
        codex = providers.CodexProvider()
        self.assertEqual(
            self.classify("I documented the usage limit handling", provider=codex).condition, EXECUTION)
        self.assertEqual(
            self.classify("", stderr="ERROR: You've hit your usage limit.", provider=codex).condition, QUOTA)

    def test_classification_round_trips_and_rejects_garbage(self):
        c = self.classify(envelope())
        self.assertEqual(av.ProviderClassification.from_dict(c.as_dict()), c)
        self.assertIsNone(av.ProviderClassification.from_dict({"condition": "NOPE"}))
        self.assertIsNone(av.ProviderClassification.from_dict(None))


class ResetHintTests(unittest.TestCase):
    HINT = "You've hit your session limit · resets 3pm (Europe/Madrid)"

    def parse(self, now, text=HINT, tz=fake_tz):
        return av.parse_reset_hint(text, now, tz)

    def test_hint_resolves_to_next_occurrence_in_hinted_timezone(self):  # 2
        # 10:00Z == 12:00 Madrid (CEST) -> 15:00 Madrid today == 13:00Z.
        self.assertEqual(self.parse(utc(2026, 9, 22, 10, 0)), utc(2026, 9, 22, 13, 0))

    def test_hint_rolls_to_tomorrow_when_time_already_passed_or_equal(self):
        self.assertEqual(self.parse(utc(2026, 9, 22, 14, 0)), utc(2026, 9, 23, 13, 0))
        self.assertEqual(self.parse(utc(2026, 9, 22, 13, 0)), utc(2026, 9, 23, 13, 0))

    def test_other_time_formats(self):
        now = utc(2026, 9, 22, 10, 0)
        self.assertEqual(self.parse(now, "resets 3:30pm (Europe/Madrid)"), utc(2026, 9, 22, 13, 30))
        self.assertEqual(self.parse(now, "resets 15:00 (Europe/Madrid)"), utc(2026, 9, 22, 13, 0))
        self.assertEqual(self.parse(now, "resets 12am (Europe/Madrid)"), utc(2026, 9, 22, 22, 0))

    def test_unsafe_hints_yield_none_so_caller_backs_off(self):
        now = utc(2026, 9, 22, 10, 0)
        self.assertIsNone(self.parse(now, "resets 3pm"))                       # no timezone
        self.assertIsNone(self.parse(now, "resets 3pm (Mars/Olympus)"))        # unknown timezone
        self.assertIsNone(self.parse(now, "resets 13pm (Europe/Madrid)"))      # impossible time
        self.assertIsNone(self.parse(now, "resets 25:00 (Europe/Madrid)"))
        self.assertIsNone(self.parse(now, "no hint here"))
        self.assertIsNone(self.parse(datetime(2026, 9, 22, 10, 0)))           # naive clock
        self.assertIsNone(av.parse_reset_hint(None, now, fake_tz))

    def test_real_zoneinfo_honours_dst(self):
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo("Europe/Madrid")
        except Exception:  # noqa: BLE001 - tzdata not installed on this host
            self.skipTest("IANA tz database unavailable")
        # 2026-03-28: CET (+1) -> 15:00 local is 14:00Z. Next day CEST (+2) -> 13:00Z.
        self.assertEqual(self.parse(utc(2026, 3, 28, 12, 0), tz=None), utc(2026, 3, 28, 14, 0))
        self.assertEqual(self.parse(utc(2026, 3, 28, 15, 0), tz=None), utc(2026, 3, 29, 13, 0))

    def test_reset_hint_extraction_is_bounded(self):
        self.assertEqual(av.extract_reset_hint(self.HINT), "resets 3pm (Europe/Madrid)")
        self.assertIsNone(av.extract_reset_hint("resets soon"))


class RedactionTests(unittest.TestCase):
    def test_no_secrets_in_classification_evidence(self):  # 14
        leaky = (
            QUOTA_TEXT + " Authorization: Bearer abc.def.ghi key sk-ant-api03-LEAKLEAKLEAK token=zzz9"
        )
        c = providers.ClaudeProvider().classify_failure(stdout=envelope(result=leaky), stderr="")
        self.assertEqual(c.condition, QUOTA)
        dumped = json.dumps(c.as_dict())
        for secret in ("abc.def.ghi", "LEAKLEAKLEAK", "zzz9"):
            self.assertNotIn(secret, dumped)
        self.assertEqual(c.reset_hint, "resets 3pm (Europe/Madrid)")
        self.assertLessEqual(len(c.message_excerpt), av.MESSAGE_EXCERPT_CHARS)


# ---------------------------------------------------------------------------
class QuotaClaude(providers.ClaudeProvider):
    """Real Claude adapter (real classification) with a scripted process."""

    def __init__(self, stdout, stderr="", returncode=1):
        self._outcome = providers.ProcessOutcome(returncode, stdout, stderr, False, False, 0.1)

    def probe(self):
        return providers.ProviderProbe("claude", True, executable="claude-fake", version="0.0-fake")

    def execute(self, invocation, timeout_seconds, transport=None, control=None):
        return self._outcome


class RunnerEvidenceTests(tpv.TempRepoCase):
    def run_claude(self, stdout, returncode=1, stderr=""):
        registry = providers.ProviderRegistry()
        fake = QuotaClaude(stdout, stderr, returncode)
        registry.register("claude", lambda: fake)
        return self.run_with(registry, self.request(provider="claude"))

    def evidence_json(self, result, name):
        return json.loads((result.evidence_dir / name).read_text(encoding="utf-8"))

    def test_quota_classification_is_durable_in_runner_evidence(self):  # 13
        result = self.run_claude(envelope())
        self.assertEqual(result.state, RS.CLAUDE_ERROR)  # runner state unchanged; pipeline decides
        self.assertEqual(result.provider_condition["condition"], "PROVIDER_QUOTA_EXHAUSTED")
        self.assertEqual(result.provider_condition["reset_hint"], "resets 3pm (Europe/Madrid)")
        self.assertEqual(self.evidence_json(result, "metadata.json")["provider_condition"], result.provider_condition)
        self.assertEqual(self.evidence_json(result, "result.json")["provider_condition"], result.provider_condition)

    def test_runner_condition_holds_no_secret(self):  # 14
        leaky = QUOTA_TEXT + " Bearer abc.def.ghi sk-ant-api03-LEAKLEAKLEAK"
        result = self.run_claude(envelope(result=leaky))
        self.assertNotIn("LEAKLEAKLEAK", json.dumps(result.provider_condition))
        self.assertNotIn("abc.def.ghi", json.dumps(result.provider_condition))

    def test_generic_failure_and_success_classification(self):
        failed = self.run_claude("", returncode=2, stderr="segfault")
        self.assertEqual(failed.provider_condition["condition"], "PROVIDER_EXECUTION_ERROR")
        ok = self.run_claude(json.dumps({"type": "result", "result": "fine", "is_error": False}), returncode=0)
        self.assertEqual(ok.state, RS.SUCCESS)
        self.assertIsNone(ok.provider_condition)


# ---------------------------------------------------------------------------
class ClaudeLikeFake(tp.FakeProvider):
    """Pipeline provider double that classifies with the real Claude adapter."""
    classify_failure = providers.ClaudeProvider.classify_failure


class QuotaPipelineBase(tp.PipelineTestBase):
    def setUp(self):
        super().setUp()
        self.providers["claude"] = ClaudeLikeFake("claude")
        self.clock = tp.FakeClock()
        self.clock.now = utc(2026, 9, 22, 12, 0)  # 14:00 in Madrid; reset 15:00 == 13:00Z
        self._evidence_n = 0

    def runner(self, manifest, executor=None, **kw):
        kw.setdefault("clock", self.clock)
        kw.setdefault("sleep_fn", self.clock.sleep)
        kw.setdefault("tz_lookup", fake_tz)
        return super().runner(manifest, executor, **kw)

    def failure(self, status=429, result=QUOTA_TEXT, stdout=None, stderr=""):
        self._evidence_n += 1
        directory = self.root / "evidence" / f"e{self._evidence_n}"
        directory.mkdir(parents=True)
        (directory / "stdout.txt").write_text(
            stdout if stdout is not None else envelope(status, result=result), encoding="utf-8")
        (directory / "stderr.txt").write_text(stderr, encoding="utf-8")
        return tp._res(RS.CLAUDE_ERROR, evidence=directory)

    def hold(self, workers, script, *, seconds=120, **kw):
        """Runs until the (fake) deadline so still-waiting workers are observable."""
        executor = tp.Executor(script, on_call=kw.pop("on_call", None))
        r = self.runner(self.manifest(workers), executor, max_runtime_seconds=seconds, **kw)
        return r, executor, r.run()

    def attempts(self, wid):
        return self.worker_json(wid)["attempts"]


class QuotaWaitTests(QuotaPipelineBase):
    def test_quota_puts_worker_in_waiting_provider_quota_not_failed(self):  # 3
        r, executor, result = self.hold([self.worker("w", max_attempts=1)], {"w": [self.failure()]})
        self.assertEqual(self.states(result), {"w": "WAITING_PROVIDER_QUOTA"})
        self.assertEqual(len(executor.calls_for("w")), 1)  # not retried, not hammered
        w = self.worker_json("w")
        self.assertEqual(w["state_reason"], "PROVIDER_QUOTA_EXHAUSTED:RESET_HINT")
        self.assertEqual(w["provider_wait"]["condition"], "PROVIDER_QUOTA_EXHAUSTED")
        self.assertEqual(w["provider_wait"]["eligibility_source"], "RESET_HINT")
        self.assertEqual(w["provider_wait"]["next_eligible_utc"], "2026-09-22T13:01:00+00:00")
        self.assertEqual(result.summary["waiting_provider_quota"], 1)
        self.assertEqual(result.summary["state_counts"]["WAITING_PROVIDER_QUOTA"], 1)
        entry = result.summary["workers"][0]
        self.assertEqual(entry["provider_condition"], "PROVIDER_QUOTA_EXHAUSTED")
        self.assertEqual(entry["next_eligible_utc"], "2026-09-22T13:01:00+00:00")
        self.assertNotEqual(result.status, "FAILED")

    def test_quota_is_not_charged_to_max_attempts_and_resumes_automatically(self):  # 4, 5
        times = []
        executor = tp.Executor(
            {"w": [self.failure(), tp._res()]}, on_call=lambda wid, req: times.append(self.clock.now))
        result = self.runner(self.manifest([self.worker("w", max_attempts=1)]), executor).run()
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(len(executor.calls_for("w")), 2)
        self.assertEqual(times[0], utc(2026, 9, 22, 12, 0))
        self.assertGreaterEqual(times[1], utc(2026, 9, 22, 13, 1))  # not before the derived reset
        attempts = self.attempts("w")
        self.assertEqual([a["budget_class"] for a in attempts], ["PROVIDER_AVAILABILITY", "WORK"])
        w = self.worker_json("w")
        self.assertEqual((w["work_attempts_used"], w["availability_attempts"]), (1, 1))
        self.assertIsNone(w["provider_wait"])  # wait ended once the provider worked again

    def test_work_budget_still_applies_after_provider_recovers(self):  # 4
        transient = self.failure(503, "Overloaded")
        executor = tp.Executor({"w": [self.failure(), transient]})
        result = self.runner(self.manifest([self.worker("w", max_attempts=1)]), executor).run()
        self.assertEqual(self.states(result)["w"], "FAILED")
        self.assertEqual(self.worker_json("w")["state_reason"], "MAX_ATTEMPTS_EXHAUSTED")
        self.assertEqual(len(executor.calls_for("w")), 2)

    def test_unknown_reset_uses_bounded_exponential_probing(self):  # 5, no hammering
        times = []
        quota = self.failure(result=QUOTA_TEXT_NO_HINT)
        executor = tp.Executor(
            {"w": [quota, quota, quota, tp._res()]}, on_call=lambda wid, req: times.append(self.clock.now))
        result = self.runner(self.manifest([self.worker("w", max_attempts=1)]), executor).run()
        self.assertEqual(result.status, "SUCCESS")
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
        self.assertEqual(len(gaps), 3)
        for gap, delay in zip(gaps, (rp.QUOTA_PROBE_BASE_SECONDS, 2 * rp.QUOTA_PROBE_BASE_SECONDS,
                                     4 * rp.QUOTA_PROBE_BASE_SECONDS)):
            self.assertGreaterEqual(gap, delay)
            self.assertLessEqual(gap, delay + 61)
        reasons = {a["provider_condition"]["reason"] for a in self.attempts("w")[:3]}
        self.assertEqual(reasons, {"STATUS_429+QUOTA_MESSAGE"})
        self.assertLessEqual(rp.QUOTA_PROBE_MAX_SECONDS, 3600.0)

    def test_unresolvable_timezone_falls_back_to_bounded_probing(self):
        def no_tz(name):
            raise av.ZoneInfoNotFoundError(name)

        self.hold([self.worker("w")], {"w": [self.failure()]}, tz_lookup=no_tz)
        wait = self.worker_json("w")["provider_wait"]
        self.assertEqual(wait["eligibility_source"], "BACKOFF_PROBE")
        self.assertEqual(wait["next_eligible_utc"], "2026-09-22T12:05:00+00:00")


class DagAndIsolationTests(QuotaPipelineBase):
    def test_success_only_dependents_stay_waiting_while_independent_branches_run(self):  # 7
        workers = [
            self.worker("up", repo="a"),
            self.worker("down", repo="b", provider="codex", depends_on=["up"]),
            self.worker("anyway", repo="d", provider="codex", depends_on=["up"], dependency_policy="completed"),
            self.worker("free", repo="c", provider="codex"),
        ]
        r, executor, result = self.hold(workers, {"up": [self.failure()]})
        self.assertEqual(self.states(result), {
            "up": "WAITING_PROVIDER_QUOTA", "down": "WAITING_DEPENDENCY",
            "anyway": "WAITING_DEPENDENCY", "free": "SUCCESS",
        })
        self.assertEqual(executor.calls_for("down"), [])
        self.assertEqual(executor.calls_for("anyway"), [])

    def test_claude_quota_does_not_stop_codex_worker(self):  # 6
        workers = [self.worker("c", repo="a"), self.worker("x", repo="b", provider="codex")]
        r, executor, result = self.hold(workers, {"c": [self.failure()]})
        self.assertEqual(self.states(result), {"c": "WAITING_PROVIDER_QUOTA", "x": "SUCCESS"})

    def test_waiting_worker_does_not_occupy_execution_slot(self):  # 16
        workers = [self.worker("c", repo="a"), self.worker("x", repo="b", provider="codex")]
        r, executor, result = self.hold(workers, {"c": [self.failure()]}, max_workers=1)
        self.assertEqual(self.states(result), {"c": "WAITING_PROVIDER_QUOTA", "x": "SUCCESS"})
        self.assertEqual(executor.max_concurrent, 1)
        self.assertEqual(r.observed_max_concurrency, 1)
        self.assertEqual(r._futures, {})

    def test_same_provider_workers_are_held_not_hammered_while_quota_waits(self):
        workers = [self.worker("c1", repo="a"), self.worker("c2", repo="b"),
                   self.worker("x", repo="c", provider="codex")]
        r, executor, result = self.hold(workers, {"c1": [self.failure()]}, max_workers=1)
        self.assertEqual(self.states(result), {"c1": "WAITING_PROVIDER_QUOTA", "c2": "READY", "x": "SUCCESS"})
        self.assertEqual(executor.calls_for("c2"), [])

    def test_write_lease_released_and_worktree_preserved_while_waiting(self):
        def partial_write(request):
            (Path(request.repo) / "partial.txt").write_text("work in progress\n", encoding="utf-8")
            return self.failure()

        r, _, result = self.hold(
            [self.worker("w", repo="a", mode="write", authorize_path=["docs/"])], {"w": partial_write})
        self.assertEqual(self.states(result)["w"], "WAITING_PROVIDER_QUOTA")
        self.assertEqual((self.repos["a"] / "partial.txt").read_text(encoding="utf-8"), "work in progress\n")
        self.assertEqual(r._leases, {})
        lease = rp.DirLease(rp.worktree_lease_dir(self.repos["a"]))
        self.assertTrue(lease.try_acquire({"pid": 1}), "write lease still held while waiting for quota")
        lease.release()
        self.assertIs(self.attempts("w")[0]["process_confirmed_stopped"], True)


class NoFallbackTests(QuotaPipelineBase):
    def test_quota_never_falls_back_to_another_provider_or_credential(self):  # 12
        r, executor, result = self.hold(
            [self.worker("w", fallback_providers=["codex"], max_attempts=3)], {"w": [self.failure()]})
        self.assertEqual(self.states(result)["w"], "WAITING_PROVIDER_QUOTA")
        self.assertEqual({req.provider for _, req in executor.calls}, {"claude"})
        w = self.worker_json("w")
        self.assertEqual((w["active_provider"], w["fallbacks_used"], w["provider_locked"]), ("claude", [], True))

    def test_quota_without_evidence_dir_still_does_not_trigger_fallback(self):  # 12
        quota = tp._res(RS.CLAUDE_ERROR, evidence=None)  # would qualify as "provider never ran"
        quota.provider_condition = av.classify_provider_failure(
            http_status=429, message=QUOTA_TEXT).as_dict()
        r, executor, result = self.hold([self.worker("w", fallback_providers=["codex"])], {"w": [quota]})
        self.assertEqual(self.states(result)["w"], "WAITING_PROVIDER_QUOTA")
        self.assertEqual({req.provider for _, req in executor.calls}, {"claude"})
        self.assertEqual(self.worker_json("w")["fallbacks_used"], [])

    def test_auth_never_falls_back_either(self):  # 12
        r, executor, result = self.hold(
            [self.worker("w", fallback_providers=["codex"])], {"w": [self.failure(401, "Invalid API key")]})
        self.assertEqual(self.states(result)["w"], "BLOCKED_PROVIDER_AUTH")
        self.assertEqual({req.provider for _, req in executor.calls}, {"claude"})


class AuthTests(QuotaPipelineBase):
    def test_auth_failure_becomes_blocked_provider_auth(self):  # 8
        r, executor, result = self.hold(
            [self.worker("w", max_attempts=5)], {"w": [self.failure(401, "Invalid API key")]})
        self.assertEqual(self.states(result)["w"], "BLOCKED_PROVIDER_AUTH")
        w = self.worker_json("w")
        self.assertEqual(w["state_reason"], "PROVIDER_AUTH_BLOCKED")
        self.assertEqual(w["provider_wait"]["condition"], "PROVIDER_AUTH_BLOCKED")
        self.assertNotEqual(w["state"], "FAILED")
        payload = json.loads((self.state_root / "night-001" / "workers" / "w" / "result.json").read_text("utf-8"))
        self.assertEqual((payload["outcome"], payload["code"]), ("BLOCKED_PROVIDER_AUTH", "PROVIDER_AUTH_BLOCKED"))
        self.assertEqual(result.summary["blocked_provider_auth"], 1)

    def test_auth_is_never_retried(self):  # 9
        executor = tp.Executor({"w": [self.failure(401, "Invalid API key")]})
        result = self.runner(self.manifest([self.worker("w", max_attempts=9)]), executor).run()
        self.assertEqual(len(executor.calls_for("w")), 1)
        self.assertEqual(self.attempts("w")[0]["retry_decision"], "NO_RETRY:PROVIDER_AUTH_BLOCKED")
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertEqual(result.stop_reason, "PROVIDER_AUTH_BLOCKED")
        self.assertEqual(self.attempts("w")[0]["budget_class"], "PROVIDER_AVAILABILITY")

    def test_auth_block_does_not_release_dependents_and_spares_other_providers(self):
        workers = [
            self.worker("up", repo="a"),
            self.worker("down", repo="b", provider="codex", depends_on=["up"], dependency_policy="completed"),
            self.worker("free", repo="c", provider="codex"),
            self.worker("same", repo="d"),
        ]
        # One slot: the provider-level hold is observed deterministically.
        r, executor, result = self.hold(workers, {"up": [self.failure(401, "Invalid API key")]}, max_workers=1)
        self.assertEqual(self.states(result), {
            "up": "BLOCKED_PROVIDER_AUTH", "down": "WAITING_DEPENDENCY", "free": "SUCCESS", "same": "READY",
        })
        self.assertEqual(executor.calls_for("down"), [])
        self.assertEqual(executor.calls_for("same"), [])  # same provider, same wall: not started

    def test_operator_rerun_can_recover_an_auth_blocked_worker(self):
        manifest = self.manifest([self.worker("w")])
        first = self.runner(manifest, tp.Executor({"w": [self.failure(401, "Invalid API key")]}))
        self.assertEqual(self.states(first.run())["w"], "BLOCKED_PROVIDER_AUTH")
        second = self.runner(manifest, tp.Executor({"w": [tp._res()]}), rerun=["w"])
        self.assertEqual(self.states(second.run())["w"], "SUCCESS")


class TransientAndGenericTests(QuotaPipelineBase):
    def test_transient_provider_error_goes_through_bounded_retry_wait(self):  # 10
        executor = tp.Executor({"w": [self.failure(529, "Overloaded"), tp._res()]})
        result = self.runner(self.manifest([self.worker("w", max_attempts=2, backoff_seconds=60)]), executor).run()
        self.assertEqual(result.status, "SUCCESS")
        first = self.attempts("w")[0]
        self.assertTrue(first["retry_decision"].startswith("RETRY:TRANSIENT"))
        self.assertEqual(first["budget_class"], "WORK")  # transient failures DO use the work budget
        self.assertEqual(first["provider_condition"]["condition"], "PROVIDER_TRANSIENT_ERROR")

    def test_plain_429_retries_as_transient_and_exhausts_budget(self):  # 10
        executor = tp.Executor({"w": [self.failure(429, "Too many requests")]})
        result = self.runner(self.manifest([self.worker("w", max_attempts=2)]), executor).run()
        self.assertEqual(self.states(result)["w"], "FAILED")
        self.assertEqual(self.worker_json("w")["state_reason"], "MAX_ATTEMPTS_EXHAUSTED")
        self.assertEqual(len(executor.calls_for("w")), 2)

    def test_generic_execution_error_keeps_existing_failure_semantics(self):  # 11
        crash = self.failure(stdout=json.dumps({"is_error": True, "result": "tool crashed"}))
        executor = tp.Executor({"w": [crash]})
        result = self.runner(self.manifest([self.worker("w", max_attempts=5)]), executor).run()
        self.assertEqual(self.states(result)["w"], "FAILED")
        self.assertEqual(len(executor.calls_for("w")), 1)
        attempt = self.attempts("w")[0]
        self.assertEqual(attempt["retry_decision"], "NO_RETRY:NON_TRANSIENT:CLAUDE_ERROR")
        self.assertEqual(attempt["provider_condition"]["condition"], "PROVIDER_EXECUTION_ERROR")
        self.assertEqual(attempt["budget_class"], "WORK")


class DurabilityTests(QuotaPipelineBase):
    def test_classification_and_reset_evidence_are_durable(self):  # 13
        self.hold([self.worker("w")], {"w": [self.failure()]})
        attempt = self.attempts("w")[0]
        condition = attempt["provider_condition"]
        self.assertEqual(condition["condition"], "PROVIDER_QUOTA_EXHAUSTED")
        self.assertEqual((condition["http_status"], condition["terminal_reason"]), (429, "api_error"))
        self.assertEqual(condition["reset_hint"], "resets 3pm (Europe/Madrid)")
        payload = json.loads((self.state_root / "night-001" / "workers" / "w" / "result.json").read_text("utf-8"))
        self.assertEqual(payload["outcome"], "WAITING_PROVIDER_QUOTA")
        self.assertEqual(payload["provider_condition"], condition)
        self.assertEqual(payload["next_eligible_utc"], "2026-09-22T13:01:00+00:00")

    def test_no_secrets_reach_any_durable_pipeline_file(self):  # 14
        leaky = QUOTA_TEXT + " Authorization: Bearer abc.def.ghi sk-ant-api03-LEAKLEAKLEAK token=zzz9"
        self.hold([self.worker("w")], {"w": [self.failure(result=leaky)]})
        files = [p for p in (self.state_root / "night-001").rglob("*.json")]
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            for secret in ("abc.def.ghi", "LEAKLEAKLEAK", "zzz9"):
                self.assertNotIn(secret, text, f"{secret} leaked into {path.name}")

    def test_restart_preserves_quota_wait_then_resumes_after_reset(self):  # 15
        manifest = self.manifest([self.worker("w", max_attempts=1)])
        first = self.runner(manifest, tp.Executor({"w": [self.failure()]}), max_runtime_seconds=120)
        first.run()
        before = self.worker_json("w")

        # Restart while still inside the quota window: nothing runs, nothing fails.
        idle = tp.Executor({"w": [tp._res()]})
        second = self.runner(manifest, idle, max_runtime_seconds=120).run()
        self.assertEqual(self.states(second)["w"], "WAITING_PROVIDER_QUOTA")
        self.assertEqual(idle.calls, [])
        after = self.worker_json("w")
        self.assertEqual(after["provider_wait"], before["provider_wait"])
        self.assertEqual((after["work_attempts_used"], after["availability_attempts"]), (0, 1))
        self.assertEqual(len(after["attempts"]), 1)

        # Restart after the provider recovered: the worker resumes and succeeds
        # although max_attempts is 1.
        self.clock.now = utc(2026, 9, 22, 13, 5)
        resumed = tp.Executor({"w": [tp._res()]})
        third = self.runner(manifest, resumed).run()
        self.assertEqual(third.status, "SUCCESS")
        self.assertEqual(len(resumed.calls_for("w")), 1)
        final = self.worker_json("w")
        self.assertEqual((final["work_attempts_used"], final["availability_attempts"]), (1, 1))


class ProcessSupervisionCompatibilityTests(QuotaPipelineBase):
    def test_unresolved_process_dominates_quota_classification(self):  # 17
        def quota_with_stuck_process(request):
            request.execution_control.attach(tp._StuckProcess())
            return self.failure()

        executor = tp.Executor({"w": quota_with_stuck_process})
        r = self.runner(self.manifest([self.worker("w", mode="write", authorize_path=["docs/"])]), executor)
        self.addCleanup(lambda: [lease.release() for lease in list(r._unresolved_leases.values())])
        result = r.run()
        self.assertEqual(self.states(result)["w"], "BLOCKED")
        w = self.worker_json("w")
        self.assertEqual(w["state_reason"], "PROVIDER_PROCESS_UNRESOLVED")
        self.assertIsNone(w["provider_wait"])
        self.assertIs(w["attempts"][0]["process_termination_unresolved"], True)
        contender = rp.DirLease(rp.worktree_lease_dir(self.repos["a"]))
        self.assertFalse(contender.try_acquire({"pid": 2}), "lease released although the provider is unconfirmed")

    def test_quota_wait_records_a_confirmed_stopped_process_first(self):  # 17
        self.hold([self.worker("w")], {"w": [self.failure()]})
        attempt = self.attempts("w")[0]
        self.assertIs(attempt["process_confirmed_stopped"], True)
        self.assertNotIn("process_termination_unresolved", attempt)
        self.assertEqual(self.worker_json("w")["state"], "WAITING_PROVIDER_QUOTA")


class StateModelTests(unittest.TestCase):
    def test_new_states_are_not_terminal_and_have_controlled_transitions(self):
        for state in (rp.WorkerState.WAITING_PROVIDER_QUOTA, rp.WorkerState.BLOCKED_PROVIDER_AUTH):
            self.assertNotIn(state, rp.TERMINAL_STATES)
            self.assertIn(state, rp._ALLOWED_TRANSITIONS[rp.WorkerState.RUNNING])
        self.assertNotIn(rp.WorkerState.FAILED, rp._ALLOWED_TRANSITIONS[rp.WorkerState.WAITING_PROVIDER_QUOTA])
        self.assertEqual(rp._ALLOWED_TRANSITIONS[rp.WorkerState.BLOCKED_PROVIDER_AUTH], {rp.WorkerState.CANCELLED})

    def test_availability_attempts_do_not_count_against_work_budget(self):
        spec = rp.WorkerSpec(id="w", worktree="x", work_order="y", max_attempts=1)
        rt = rp.WorkerRuntime(spec=spec, order=0)
        rt.attempts = [
            {"executed": True, "budget_class": "PROVIDER_AVAILABILITY"},
            {"executed": True},  # legacy record without budget_class == WORK
            {"executed": False, "budget_class": "WORK"},
        ]
        self.assertEqual((rt.attempts_used, rt.availability_attempts), (1, 1))


if __name__ == "__main__":
    unittest.main()
