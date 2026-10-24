"""FCP-3B-2B2-HOST-01: GitHub REST adapter and governed host composition.

GitHub is simulated by `FakeGitHub`, an in-memory transport that answers
injected HTTP responses; no socket, credential or real repository is used
and the network is denied for the whole module. The request is a REAL
`PromotionExecutionRequest` built through the existing executor fixtures.
End-to-end tests drive `rpe.simulate_promotion` through the real Ed25519
authority (ephemeral in-memory key), a temporary SQLite host ledger created
by these tests, and this adapter: every outcome is SIMULATED, never live,
and no merge of a real pull request happens anywhere.
"""

import ast
import dataclasses
import json
import os
import re
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ai import runner_promotion_executor as rpe
from scripts.ai import runner_promotion_host_authority as rauth
from scripts.ai import runner_promotion_host_github as rhg
from scripts.ai import runner_promotion_host_ledger as rhl
from scripts.ai import runner_promotion_human_authorization as rha
from scripts.ai import runner_promotion_pr_gate as rpg
from scripts.tests import test_runner_promotion_executor as tpe
from scripts.tests import test_runner_promotion_host_authority as tau

MODULE_PATH = Path(rhg.__file__)
AI_DIR = MODULE_PATH.parent
REPO = rpg.CANONICAL_REPOSITORY
PR = tpe.PR
JOBS = rpg.REQUIRED_CI_JOBS
NOW = tpe.NOW
MERGE_SHA = tpe.MERGE_SHA
AUTHOR, DIRECTOR, OTHER, BOT = tpe.thu.AUTHOR, tpe.thu.DIRECTOR, tpe.thu.OTHER, tpe.thu.BOT
SUITE, RUN_ID = 555, tpe.tpg.RUN_ID
P = rhg.REPO_PATH
JSON = (("content-type", "application/json; charset=utf-8"),)
_NETWORK = []


def _deny_network(*_args, **_kwargs):
    _NETWORK.append("attempt")
    raise OSError("network denied during host GitHub tests")


def setUpModule():
    for target, name in ((socket.socket, "connect"), (socket, "create_connection"), (socket, "getaddrinfo")):
        patcher = mock.patch.object(target, name, _deny_network)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


def respond(request, status, payload, headers=JSON, url=None):
    body = payload if type(payload) is bytes else json.dumps(payload).encode("utf-8")
    return rhg.HttpResponse(status=status, headers=headers, body=body, url=url or request.url)


def check_json(head, job, index, **changes):
    return dict({"id": 100 + index, "name": job, "head_sha": head, "status": "completed", "conclusion": "success",
                 "app": {"id": rhg.GITHUB_ACTIONS_APP_ID, "slug": "github-actions"}, "check_suite": {"id": SUITE},
                 "pull_requests": [{"number": PR}]}, **changes)


def review_json(head, rid, state="APPROVED", actor=DIRECTOR, **changes):
    return dict({"id": rid, "user": {"id": actor, "login": tpe.thu.LOGINS[actor],
                                     "type": "Bot" if actor == BOT else "User"},
                 "state": state, "commit_id": head, "submitted_at": tpe.thu.ts(rid)}, **changes)


class FakeGitHub:
    """In-memory GitHub REST answers. Records every request; `routes`
    overrides one (method, path) with a callable(request)."""

    transport_kind = rhg.TRANSPORT_KIND_IN_MEMORY_FAKE

    def __init__(self, intent):
        head, base = intent.head_sha, intent.base_sha
        self.head, self.base, self.requests, self.routes = head, base, [], {}
        self.repo = {"full_name": REPO, "archived": False, "allow_merge_commit": True}
        self.tip = base
        self.pr = {"number": PR, "state": "open", "merged": False, "draft": False, "auto_merge": None,
                   "user": {"id": AUTHOR}, "changed_files": 1, "merge_commit_sha": "c" * 40,
                   "base": {"ref": "develop", "sha": base, "repo": {"full_name": REPO}},
                   "head": {"ref": intent.head_ref[len("refs/heads/"):], "sha": head, "repo": {"full_name": REPO}}}
        self.files = [{"filename": "src/a.py", "status": "modified"}]
        self.check_runs = [check_json(head, job, i) for i, job in enumerate(JOBS)]
        self.check_total = None
        self.workflow_runs = {SUITE: [{"id": RUN_ID, "check_suite_id": SUITE, "name": "Fabric CI",
                                       "path": ".github/workflows/fabric-ci.yml", "event": "pull_request",
                                       "head_sha": head}]}
        self.reviews = [review_json(head, 1)]
        self.commits = {head: {"sha": head, "author": {"id": AUTHOR}, "parents": [{"sha": base}]}}
        self.protection = {
            "url": "https://api.github.com/ignored",
            "required_status_checks": {"strict": True, "contexts": list(JOBS),
                                       "checks": [{"context": j, "app_id": rhg.GITHUB_ACTIONS_APP_ID} for j in JOBS]},
            "required_pull_request_reviews": {"dismiss_stale_reviews": True, "require_code_owner_reviews": False,
                                              "required_approving_review_count": 1,
                                              "require_last_push_approval": False},
            "enforce_admins": {"enabled": True}, "required_linear_history": {"enabled": False},
            "allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False},
            "required_conversation_resolution": {"enabled": False}, "lock_branch": {"enabled": False},
            "block_creations": {"enabled": False},
        }
        self.rules, self.rulesets = [], {}

    # Transport ----------------------------------------------------------
    def send(self, request):
        assert type(request) is rhg.HttpRequest
        self.requests.append(request)
        assert request.url.startswith(rhg.API_ORIGIN + "/repos/" + REPO), request.url
        path, _, query = request.url[len(rhg.API_ORIGIN):].partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if p)
        route = self.routes.get((request.method, path))
        if route is not None:
            return route(request)
        return self.default(request, path, params)

    def page(self, request, params, items, wrap=None):
        start = (int(params["page"]) - 1) * int(params["per_page"])
        chunk = items[start:start + int(params["per_page"])]
        return respond(request, 200, chunk if wrap is None else wrap(chunk))

    def default(self, request, path, params):
        if request.method == "PUT" and path == f"{P}/pulls/{PR}/merge":
            return self.merge(request)
        if path == P:
            return respond(request, 200, self.repo)
        if path == f"{P}/branches/develop":
            return respond(request, 200, {"name": "develop", "commit": {"sha": self.tip}, "protected": True})
        if path == f"{P}/branches/develop/protection":
            if self.protection is None:
                return respond(request, 404, {"message": "Branch not protected"})
            return respond(request, 200, self.protection)
        if path == f"{P}/pulls/{PR}":
            return respond(request, 200, self.pr)
        if path == f"{P}/pulls/{PR}/files":
            return self.page(request, params, self.files)
        if path == f"{P}/pulls/{PR}/reviews":
            return self.page(request, params, self.reviews)
        if path == f"{P}/rules/branches/develop":
            return self.page(request, params, self.rules)
        if path == f"{P}/actions/runs":
            runs = self.workflow_runs.get(int(params["check_suite_id"]), [])
            return respond(request, 200, {"total_count": len(runs), "workflow_runs": runs})
        match = re.fullmatch(re.escape(P) + r"/commits/([0-9a-f]+)/check-runs", path)
        if match:
            total = len(self.check_runs) if self.check_total is None else self.check_total
            return self.page(request, params, self.check_runs, lambda c: {"total_count": total, "check_runs": c})
        match = re.fullmatch(re.escape(P) + r"/commits/([0-9a-f]+)", path)
        if match and match.group(1) in self.commits:
            return respond(request, 200, self.commits[match.group(1)])
        match = re.fullmatch(re.escape(P) + r"/rulesets/([0-9]+)", path)
        if match and int(match.group(1)) in self.rulesets:
            return respond(request, 200, self.rulesets[int(match.group(1))])
        return respond(request, 404, {"message": "Not Found"})

    def merge(self, request):
        body = json.loads(request.body)
        assert body == {"merge_method": "merge", "sha": body["sha"]}
        if body["sha"] != self.pr["head"]["sha"]:
            return respond(request, 409, {"message": "Head branch was modified. Review and try the merge again."})
        self.apply_merge()
        return respond(request, 200, {"sha": MERGE_SHA, "merged": True, "message": "Pull Request successfully merged"})

    def apply_merge(self):
        self.pr.update(state="closed", merged=True, merge_commit_sha=MERGE_SHA)
        self.tip = MERGE_SHA
        self.commits[MERGE_SHA] = {"sha": MERGE_SHA, "author": None,
                                   "parents": [{"sha": self.base}, {"sha": self.head}]}

    def writes(self):
        return [r for r in self.requests if r.method != "GET"]


class NoNetworkMixin:
    def tearDown(self):
        self.assertEqual(_NETWORK, [])
        super().tearDown()


class ReadFixture(NoNetworkMixin, tpe.ExecutorFixture):
    """A real request, a fake GitHub and one adapter client."""

    def setUp(self):
        super().setUp()
        self.fake = FakeGitHub(self.intent)
        self.client = rhg.GitHubPromotionClient(self.fake, clock=lambda: NOW)

    def read(self):
        return self.client.read_fresh_state(REPO, PR)

    def findings(self):
        return rpe._fresh_findings(self.request, self.read(), NOW)["errors"]

    def assertFindings(self, *codes):
        errors = self.findings()
        for code in codes:
            self.assertIn(code, errors)
        self.assertTrue(errors)
        return errors

    def assertReadRefused(self, code, fn=None):
        with self.assertRaises(rhg.GitHubReadRefused) as caught:
            (fn or self.read)()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.fake.writes(), [])


# ---------------------------------------------------------------------------
# Reads mapped to FCP types
# ---------------------------------------------------------------------------

class FreshReadTests(ReadFixture):
    def test_fresh_read_maps_exactly_to_fcp_types_and_passes_the_core(self):
        state = self.read()
        self.assertIs(type(state), rpe.FreshPromotionState)
        self.assertTrue(rpe._plain(state, rpe._FRESH_TYPES))
        self.assertEqual(rpe._fresh_findings(self.request, state, NOW)["errors"], [])
        checks = state.pr_snapshot.checks
        self.assertEqual(tuple(r.name for r in checks.runs), JOBS)
        self.assertEqual({r.workflow_run_id for r in checks.runs}, {RUN_ID})
        self.assertEqual({(r.app_slug, r.event, r.head_sha) for r in checks.runs},
                         {("github-actions", "pull_request", self.head)})
        self.assertEqual(checks.policy.rule_types, ("deletion", "non_fast_forward", "pull_request",
                                                    "required_status_checks"))
        p = state.protection
        self.assertEqual((p.complete, p.enforce_admins, p.strict_up_to_date, p.dismiss_stale_reviews,
                          p.merge_queue_required, set(p.required_check_names)), (True, True, True, True, False,
                                                                                 set(JOBS)))
        self.assertEqual(state.review_sequence.observed_at, "2026-10-24T12:00:00Z")
        self.assertEqual(state.develop_tip_sha, self.base)
        self.assertEqual(self.fake.writes(), [])
        for r in self.fake.requests:
            self.assertTrue(r.url.startswith(f"https://api.github.com/repos/{REPO}"), r.url)
            self.assertNotIn("authorization", {k.lower() for k, _ in r.headers})
            self.assertEqual(r.timeout_seconds, rhg.READ_TIMEOUT_SECONDS)

    def test_seven_checks_must_come_from_one_actions_run_of_this_pr_and_sha(self):
        cases = (
            (lambda f: f.check_runs.pop(), rpg.PR_GATE_CHECK_MISSING),
            (lambda f: f.check_runs.append(dict(check_json(f.head, JOBS[0], 50),
                                                app={"id": 999, "slug": "impostor"})), rpg.PR_GATE_CHECK_DUPLICATE),
            (lambda f: f.check_runs[2].update(conclusion="failure"), rpg.PR_GATE_CHECK_FAILED),
            (lambda f: f.check_runs[3].update(status="in_progress", conclusion=None), rpg.PR_GATE_CHECK_PENDING),
            (lambda f: f.check_runs[1].update(pull_requests=[]), rpg.PR_GATE_CHECK_BINDING_MISMATCH),
            (lambda f: f.workflow_runs[SUITE][0].update(event="push"), rpg.PR_GATE_CHECK_EVENT_MISMATCH),
            (lambda f: f.workflow_runs[SUITE][0].update(path=".github/workflows/other.yml"),
             rpg.PR_GATE_CHECK_BINDING_MISMATCH),
        )
        for mutate, code in cases:
            with self.subTest(code=code):
                self.setUp()
                mutate(self.fake)
                self.assertFindings(rpe.EXEC_FRESH_GATE_NOT_REVIEWABLE, code)
        self.setUp()
        self.fake.check_runs[6]["check_suite"] = {"id": 556}
        self.fake.workflow_runs[556] = [dict(self.fake.workflow_runs[SUITE][0], id=RUN_ID + 1, check_suite_id=556)]
        self.assertFindings(rpg.PR_GATE_CHECK_RUN_CONFLICT)
        self.setUp()
        self.fake.check_runs[0]["app"] = {"id": 999, "slug": "github-actions"}
        self.assertReadRefused(rhg.GH_CHECK_BINDING_INVALID)
        self.setUp()
        self.fake.workflow_runs[SUITE][0]["head_sha"] = "c" * 40
        self.assertReadRefused(rhg.GH_CHECK_BINDING_INVALID)

    def test_truncated_or_unbounded_listings_never_look_complete(self):
        self.fake.check_total = len(JOBS) + 1
        self.assertFindings(rpg.PR_GATE_CHECKS_INCOMPLETE)
        self.setUp()
        self.fake.pr["changed_files"] = 2
        self.assertFindings(rpg.PR_GATE_FILES_INCOMPLETE)
        self.setUp()
        self.fake.files = [{"filename": f"src/f{i}.py", "status": "modified"} for i in range(150)]
        self.fake.pr["changed_files"] = 150
        listing = self.read().pr_snapshot.changed_files
        self.assertEqual((len(listing.files), listing.pages_fetched, listing.complete), (150, 2, True))
        self.assertEqual(self.findings(), [])
        self.setUp()
        self.fake.pr["changed_files"] = rpg.MAX_CHANGED_FILES + 1
        self.assertReadRefused(rhg.GH_FILES_LIMIT)
        self.setUp()
        self.fake.check_runs += [check_json(self.head, f"extra-{i}", 10 + i, app={"id": 7, "slug": "other"})
                                 for i in range(100 - len(JOBS))]
        with mock.patch.object(rhg, "MAX_CHECK_PAGES", 1):
            self.assertReadRefused(rhg.GH_PAGINATION_LIMIT)
        self.setUp()
        self.fake.files = [{"filename": "src/new.py", "status": "renamed", "previous_filename": "docs/old.py"}]
        self.assertFindings(rpg.PR_GATE_PATH_OUT_OF_SCOPE)
        self.setUp()
        self.fake.files = [{"filename": "src/new.py", "status": "renamed"}]
        self.assertReadRefused(rhg.GH_PAYLOAD_INVALID)

    def test_dismissed_bot_stale_or_missing_reviews_are_never_favorable(self):
        cases = (
            ([review_json(self.head, 1), review_json(self.head, 2, state="DISMISSED")],
             rpe.EXEC_FRESH_REVIEWS_NOT_FAVORABLE),
            ([review_json(self.head, 1, actor=BOT)], rha.HAUTH_REVIEW_ACTOR_NOT_HUMAN),
            ([review_json("c" * 40, 1)], rha.HAUTH_NO_CURRENT_APPROVAL),
            ([review_json(self.head, 1, actor=AUTHOR)], rha.HAUTH_REVIEW_SELF_APPROVAL),
            ([review_json(self.head, 1), review_json(self.head, 2, state="CHANGES_REQUESTED", actor=OTHER)],
             rha.HAUTH_CHANGES_REQUESTED),
            ([], rha.HAUTH_NO_CURRENT_APPROVAL),
        )
        for reviews, code in cases:
            with self.subTest(code=code):
                self.setUp()
                self.fake.reviews = reviews
                self.assertFindings(rpe.EXEC_FRESH_REVIEWS_NOT_FAVORABLE, code)
        self.setUp()
        self.fake.reviews = [review_json(self.head, 1, user=None)]
        self.assertReadRefused(rhg.GH_PAYLOAD_INVALID)
        self.setUp()
        pending = review_json(self.head, 1, state="PENDING")
        del pending["submitted_at"]
        self.fake.reviews = [pending]
        self.assertReadRefused(rhg.GH_PAYLOAD_INVALID)


class ProtectionTests(ReadFixture):
    def mutate_and_find(self, mutate, *codes):
        self.setUp()
        mutate(self.fake.protection)
        return self.assertFindings(*codes)

    def test_classic_protection_must_be_complete_strict_and_admin_enforced(self):
        rsc = "required_status_checks"
        prr = "required_pull_request_reviews"
        cases = (
            (lambda p: p["enforce_admins"].update(enabled=False), rpe.EXEC_PROTECTION_ADMIN_BYPASS),
            (lambda p: p[prr].update(dismiss_stale_reviews=False), rpe.EXEC_PROTECTION_STALE_REVIEWS_KEPT),
            (lambda p: p[prr].update(required_approving_review_count=0), rpe.EXEC_PROTECTION_REVIEWS_NOT_REQUIRED),
            (lambda p: p[rsc].update(strict=False), rpe.EXEC_PROTECTION_NOT_STRICT),
            (lambda p: p["allow_force_pushes"].update(enabled=True), rpe.EXEC_PROTECTION_REWRITE_ALLOWED),
            (lambda p: p["required_linear_history"].update(enabled=True), rpe.EXEC_MERGE_METHOD_FORBIDDEN_BY_POLICY),
            (lambda p: p[prr].update(bypass_pull_request_allowances={"users": [{"id": 1}], "teams": [], "apps": []}),
             rpe.EXEC_PROTECTION_UNKNOWN),
            (lambda p: p[rsc]["checks"][0].update(app_id=None), rpe.EXEC_PROTECTION_UNKNOWN),
            (lambda p: p[rsc]["checks"][0].update(app_id=4242), rpe.EXEC_PROTECTION_UNKNOWN),
            (lambda p: p.update(future_setting={"enabled": True}), rpe.EXEC_PROTECTION_UNKNOWN),
            (lambda p: p["required_conversation_resolution"].update(enabled=True), rpe.EXEC_FRESH_GATE_NOT_REVIEWABLE),
            (lambda p: p.pop(rsc), rpe.EXEC_PROTECTION_CHECKS_NOT_REQUIRED),
            (lambda p: p.pop(prr), rpe.EXEC_PROTECTION_REVIEWS_NOT_REQUIRED),
        )
        for mutate, code in cases:
            with self.subTest(code=code):
                self.mutate_and_find(mutate, code)
        self.setUp()
        self.fake.protection = None
        self.assertFindings(rpe.EXEC_PROTECTION_UNKNOWN, rpg.PR_GATE_POLICY_NOT_PROVEN)
        self.setUp()
        self.fake.routes[("GET", f"{P}/branches/develop/protection")] = lambda r: respond(r, 403, {"message": "x"})
        self.assertReadRefused(rhg.GH_PERMISSION_DENIED)

    def test_rulesets_with_hidden_or_real_bypass_or_merge_queue_refuse(self):
        pr_rule = {"type": "pull_request", "ruleset_id": 7, "parameters": {
            "required_approving_review_count": 1, "dismiss_stale_reviews_on_push": True}}
        clean = {"id": 7, "enforcement": "active", "bypass_actors": [], "current_user_can_bypass": "never"}
        self.fake.rules, self.fake.rulesets = [pr_rule], {7: clean}
        self.assertEqual(self.findings(), [])
        for ruleset in ({"id": 7, "enforcement": "active"}, dict(clean, bypass_actors=[{"actor_id": 1}]),
                        dict(clean, current_user_can_bypass="always"), dict(clean, enforcement="evaluate")):
            with self.subTest(ruleset=ruleset):
                self.setUp()
                self.fake.rules, self.fake.rulesets = [pr_rule], {7: ruleset}
                self.assertFindings(rpe.EXEC_PROTECTION_UNKNOWN)
        self.setUp()
        self.fake.rules, self.fake.rulesets = [pr_rule], {}
        self.assertFindings(rpe.EXEC_PROTECTION_UNKNOWN)
        self.setUp()
        self.fake.rules = [{"type": "merge_queue", "ruleset_id": 7, "parameters": {}}]
        self.fake.rulesets = {7: clean}
        self.assertFindings(rpe.EXEC_MERGE_QUEUE_NOT_SUPPORTED, rpg.PR_GATE_POLICY_RULE_UNMODELED)
        self.setUp()
        self.fake.rules = [{"type": "required_status_checks", "ruleset_id": 7, "parameters": {
            "strict_required_status_checks_policy": True,
            "required_status_checks": [{"context": "Other check"}]}}]
        self.fake.rulesets = {7: clean}
        self.assertFindings(rpe.EXEC_PROTECTION_UNKNOWN)


class DriftAndFailureTests(ReadFixture):
    def test_base_and_head_drift_and_races_refuse(self):
        self.fake.tip = "d" * 40
        self.assertFindings(rpe.EXEC_BASE_DRIFT, rpg.PR_GATE_STALE_BASE)
        self.setUp()
        self.fake.pr["head"]["sha"] = "c" * 40
        self.assertReadRefused(rhg.GH_NOT_FOUND)   # the moved head commit is unknown: no default is invented
        self.setUp()
        self.fake.pr["head"]["sha"] = "c" * 40
        self.fake.commits["c" * 40] = {"sha": "c" * 40, "author": {"id": AUTHOR}, "parents": []}
        self.assertFindings(rpe.EXEC_FRESH_GATE_NOT_REVIEWABLE, rpg.PR_GATE_STALE_HEAD)
        for path, mutate in ((f"{P}/branches/develop", lambda f: setattr(f, "tip", "d" * 40)),
                             (f"{P}/pulls/{PR}", lambda f: f.pr["head"].update(sha="c" * 40))):
            with self.subTest(path=path):
                self.setUp()
                calls, fake = [], self.fake

                def racing(request, path=path, mutate=mutate, calls=calls, fake=fake):
                    calls.append(1)
                    answer = fake.default(request, path, {})
                    if len(calls) == 1:
                        mutate(fake)   # moves right after the first read
                    return answer

                self.fake.routes[("GET", path)] = racing
                self.assertReadRefused(rhg.GH_STATE_CHANGED_DURING_READ)

    def test_http_transport_and_payload_failures_refuse(self):
        pr_path = ("GET", f"{P}/pulls/{PR}")

        def answer(status, payload=None, headers=JSON, url=None):
            return lambda r: respond(r, status, {"message": "x"} if payload is None else payload, headers, url)

        def raise_(exc):
            def route(_request):
                raise exc
            return route

        cases = (
            (answer(403), rhg.GH_PERMISSION_DENIED),
            (answer(403, headers=JSON + (("X-RateLimit-Remaining", "0"),)), rhg.GH_RATE_LIMITED),
            (answer(429, headers=JSON + (("Retry-After", "60"),)), rhg.GH_RATE_LIMITED),
            (answer(404), rhg.GH_NOT_FOUND),
            (answer(500), rhg.GH_HTTP_STATUS_UNEXPECTED),
            (answer(301), rhg.GH_HTTP_STATUS_UNEXPECTED),
            (answer(200, b"{not json"), rhg.GH_JSON_INVALID),
            (answer(200, b'{"number": 42, "number": 43}'), rhg.GH_JSON_INVALID),
            (answer(200, b'{"number": NaN}'), rhg.GH_JSON_INVALID),
            (answer(200, headers=(("content-type", "text/html"),)), rhg.GH_CONTENT_TYPE_INVALID),
            (answer(200, url="https://evil.example/repos/x"), rhg.GH_URL_MISMATCH),
            (lambda r: "not a response", rhg.GH_RESPONSE_INVALID),
            (raise_(rhg.TransportTimeout(request_sent=True)), rhg.GH_TRANSPORT_TIMEOUT),
            (raise_(rhg.TransportFailure(request_sent=False)), rhg.GH_TRANSPORT_FAILED),
        )
        for route, code in cases:
            with self.subTest(code=code):
                self.setUp()
                self.fake.routes[pr_path] = route
                self.assertReadRefused(code)
        payload_cases = (
            (lambda f: f.pr.update(number="42"), rhg.GH_PAYLOAD_INVALID),
            (lambda f: f.pr.update(draft=0), rhg.GH_PAYLOAD_INVALID),
            (lambda f: f.pr.pop("changed_files"), rhg.GH_PAYLOAD_INVALID),
            (lambda f: f.pr["head"].update(repo=None), rhg.GH_PAYLOAD_INVALID),
            (lambda f: f.pr.update(auto_merge={"merge_method": "squash"}), rhg.GH_AUTO_MERGE_ENABLED),
            (lambda f: f.repo.update(allow_merge_commit=False), rhg.GH_MERGE_COMMIT_NOT_ALLOWED),
            (lambda f: f.repo.update(archived=True), rhg.GH_REPOSITORY_ARCHIVED),
            (lambda f: f.repo.update(full_name="someone/fork"), rhg.GH_REPOSITORY_MISMATCH),
        )
        for mutate, code in payload_cases:
            with self.subTest(code=code):
                self.setUp()
                mutate(self.fake)
                self.assertReadRefused(code)

    def test_only_get_and_the_one_merge_put_can_leave_the_client(self):
        refs = f"{P}/git/refs/heads/develop"
        for method, path, body in (("PATCH", refs, b"{}"), ("POST", refs, b"{}"), ("PUT", refs, b"{}"),
                                   ("DELETE", refs, None), ("POST", f"{P}/pulls/{PR}/merge", b"{}"),
                                   ("POST", f"{P}/pulls/{PR}/reviews", b"{}"), ("GET", refs, b"{}")):
            with self.assertRaises(rhg.GitHubMergeRefusedBeforeSend):
                self.client._send(method, path, body=body)
        for path in ("/user", "/repos/someone/else/pulls/1", f"{P}/../x", "https://evil.example" + P):
            with self.assertRaises(rhg.GitHubReadRefused):
                self.client._send("GET", path)
        for target in (("someone/else", PR), (REPO, 0), (REPO, True), (REPO, "42")):
            self.assertReadRefused(rhg.GH_TARGET_INVALID, lambda t=target: self.client.read_fresh_state(*t))
        self.assertEqual(self.fake.requests, [])

    def test_only_the_in_memory_fake_transport_is_accepted_and_no_token_is_read(self):
        class LiveLooking:
            transport_kind = "LIVE_HTTPS"

            def send(self, request):
                raise AssertionError("never called")

        class Unmarked:
            def send(self, request):
                raise AssertionError("never called")

        for transport in (LiveLooking(), Unmarked(), None):
            with self.assertRaises(rhg.GitHubReadRefused) as caught:
                rhg.GitHubPromotionClient(transport, clock=lambda: NOW)
            self.assertEqual(caught.exception.code, rhg.GH_TRANSPORT_NOT_ACCEPTED)
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_runner-env-token", "GH_TOKEN": "ghp_other"}):
            self.read()
        dumped = repr(self.fake.requests)
        for leak in ("ghp_", "Bearer", "token", "authorization"):
            self.assertNotIn(leak, dumped.lower() if leak.islower() else dumped)


# ---------------------------------------------------------------------------
# The merge request itself
# ---------------------------------------------------------------------------

class MergeClientTests(ReadFixture):
    def merge(self, **changes):
        args = dict(repository=REPO, pr_number=PR, expected_head_sha=self.head, merge_method="merge",
                    permit_id="permit-1")
        args.update(changes)
        return self.client.merge_pull_request(**args)

    def test_merge_is_one_put_with_expected_head_and_merge_method(self):
        response = self.merge()
        self.assertEqual(response, rpe.MergeResponse(rpe.MERGE_MERGED, 200, MERGE_SHA))
        [put] = self.fake.writes()
        self.assertEqual((put.method, put.url, json.loads(put.body), put.timeout_seconds),
                         ("PUT", f"https://api.github.com/repos/{REPO}/pulls/{PR}/merge",
                          {"merge_method": "merge", "sha": self.head}, rhg.MERGE_TIMEOUT_SECONDS))
        for changes, code in (({}, rhg.GH_MERGE_ALREADY_SENT),):
            with self.assertRaises(rhg.GitHubMergeRefusedBeforeSend) as caught:
                self.merge(**changes)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(len(self.fake.writes()), 1)

    def test_invalid_merge_arguments_are_refused_before_sending(self):
        for changes, code in (({"merge_method": "squash"}, rhg.GH_MERGE_METHOD_INVALID),
                              ({"merge_method": "rebase"}, rhg.GH_MERGE_METHOD_INVALID),
                              ({"expected_head_sha": "HEAD"}, rhg.GH_MERGE_ARGUMENT_INVALID),
                              ({"repository": "someone/else"}, rhg.GH_MERGE_ARGUMENT_INVALID),
                              ({"pr_number": "42"}, rhg.GH_MERGE_ARGUMENT_INVALID),
                              ({"permit_id": "bad id"}, rhg.GH_MERGE_ARGUMENT_INVALID)):
            with self.assertRaises(rhg.GitHubMergeRefusedBeforeSend) as caught:
                self.merge(**changes)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.fake.requests, [])

    def test_every_merge_answer_is_classified_or_uncertain(self):
        merge_path = ("PUT", f"{P}/pulls/{PR}/merge")

        def answer(status, payload):
            return lambda r: respond(r, status, payload)

        def raise_(exc):
            def route(_request):
                raise exc
            return route

        classified = (
            (answer(409, {"message": "Head branch was modified. Review and try the merge again."}),
             rpe.MergeResponse(rpe.MERGE_REJECTED_HEAD_MISMATCH, 409, None)),
            (answer(409, {"message": "Merge conflict"}), rpe.MergeResponse(rpe.MERGE_REJECTED_CONFLICT, 409, None)),
            (answer(405, {"message": "Pull Request is not mergeable"}),
             rpe.MergeResponse(rpe.MERGE_REJECTED_NOT_MERGEABLE, 405, None)),
            (answer(422, {"message": "Validation Failed"}),
             rpe.MergeResponse(rpe.MERGE_REJECTED_UNPROCESSABLE, 422, None)),
            (answer(403, {"message": "Forbidden"}), rpe.MergeResponse(rpe.MERGE_REJECTED_FORBIDDEN, 403, None)),
            (raise_(rhg.TransportTimeout(request_sent=False)), rpe.MergeResponse(rpe.MERGE_NOT_SENT, None, None)),
            (raise_(rhg.TransportFailure(request_sent=False)), rpe.MergeResponse(rpe.MERGE_NOT_SENT, None, None)),
            (raise_(rhg.TransportTimeout(request_sent=True)),
             rpe.MergeResponse(rpe.MERGE_TIMEOUT_AFTER_SEND, None, None)),
            (raise_(rhg.TransportFailure(request_sent=None)),
             rpe.MergeResponse(rpe.MERGE_TIMEOUT_AFTER_SEND, None, None)),
        )
        for route, expected in classified:
            with self.subTest(expected=expected.status):
                self.setUp()
                self.fake.routes[merge_path] = route
                self.assertEqual(self.merge(), expected)
                self.assertEqual(len(self.fake.writes()), 1)
                self.assertTrue(rpe._response_status(expected, self.request))
        uncertain = (answer(500, {"message": "x"}), answer(404, {"message": "x"}), answer(201, {"merged": True}),
                     answer(200, {"merged": False, "sha": MERGE_SHA}), answer(200, {"merged": True, "sha": "zz"}),
                     answer(202, {}), lambda r: respond(r, 200, {"merged": True, "sha": MERGE_SHA},
                                                        url="https://elsewhere.example/merge"))
        for route in uncertain:
            with self.subTest(route=route):
                self.setUp()
                self.fake.routes[merge_path] = route
                with self.assertRaises(rhg.GitHubMergeUncertain):
                    self.merge()
                self.assertEqual(len(self.fake.writes()), 1)

    def test_postcondition_is_read_including_merge_commit_parents(self):
        untouched = self.client.read_postcondition(REPO, PR)
        self.assertEqual((untouched.merged, untouched.state, untouched.merge_commit_parents, untouched.develop_tip_sha),
                         (False, "open", (), self.base))
        self.fake.apply_merge()
        merged = self.client.read_postcondition(REPO, PR)
        self.assertTrue(rpe._post_verified(merged, self.request, MERGE_SHA))
        self.fake.commits[MERGE_SHA]["parents"] = [{"sha": "d" * 40}, {"sha": self.head}]
        self.assertFalse(rpe._post_verified(self.client.read_postcondition(REPO, PR), self.request, MERGE_SHA))
        self.assertEqual(self.fake.writes(), [])


# ---------------------------------------------------------------------------
# End to end: authority -> ledger -> GitHub adapter inside simulate_promotion
# ---------------------------------------------------------------------------

@unittest.skipUnless(rauth.CRYPTO_AVAILABLE, "cryptography not installed: signature verification NOT proven here")
class GovernedHostTests(NoNetworkMixin, tpe.ExecutorFixture):
    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="fcp-host-e2e-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.private = tau.Ed25519PrivateKey.generate()
        self.build("ledger")

    def build(self, name):
        self.ledger = rhl.HostLedger(self.root / f"{name}.sqlite3", owner="host-a", clock=lambda: NOW)
        config = rauth.HostAuthorityConfig(
            keys=(rauth.PinnedDirectorKey(tau.KEY_ID, DIRECTOR, tau.raw_public(self.private)),),
            allowed_director_ids=(DIRECTOR,), revoked_key_ids=(), source=str(self.root / "authority.json"))
        self.authority = rauth.HumanCommandAuthority(config, self.ledger, clock=lambda: NOW)
        self.fake = FakeGitHub(self.intent)
        self.client = rhg.GitHubPromotionClient(self.fake, clock=lambda: NOW)
        self.governed = rhg.compose_simulated_host(self.authority, self.ledger, self.client)

    def submit(self):
        submission = self.authority.submit_command(
            tau.envelope(tau.command_for(self.request), self.private), self.request)
        self.assertIs(submission.accepted, True, submission.reason_codes)

    def run_attempt(self, host=None):
        return rpe.simulate_promotion(self.request, host or self.governed, clock=lambda: NOW)

    def test_full_path_is_merged_verified_but_only_simulated(self):
        self.submit()
        o = self.assertOutcome(self.run_attempt(), rpe.MERGED_VERIFIED, rpe.EXEC_MERGED_VERIFIED_SIMULATED,
                               rpe.EXEC_SIMULATED_NOT_REAL_MERGE, merges=1)
        self.assertEqual((o.execution_mode, o.live_authorized, o.production_capable, o.merge_commit_sha,
                          o.observed_develop_tip_sha, o.command_id),
                         (rpe.MODE_SIMULATED, False, False, MERGE_SHA, MERGE_SHA, "cmd-1"))
        self.assertEqual([s.result for s in o.step_trace], ["OK"] * len(o.step_trace))
        [put] = self.fake.writes()
        self.assertEqual((put.method, json.loads(put.body)), ("PUT", {"merge_method": "merge", "sha": self.head}))
        self.assertEqual(self.ledger.merge_send_state(self.op), (rhl.SEND_RESULT_RECORDED, rpe.MERGE_MERGED))
        self.assertEqual(self.ledger.reservation_state(self.op), (rhl.RES_FINALIZED, rpe.MERGED_VERIFIED))
        self.assertEqual([e.event for e in self.ledger.audit_trail(self.op)],
                         ["COMMAND_REGISTERED", "LEASE_ACQUIRED", "RESERVED", "PERMIT_ISSUED", "CONSUMED",
                          "MERGE_SEND_STARTED", "MERGE_RESULT_RECORDED", "FINALIZED", "LEASE_RELEASED"])

    def test_replay_from_a_new_process_is_refused_without_any_write(self):
        self.submit()
        self.fake.routes[("PUT", f"{P}/pulls/{PR}/merge")] = lambda r: respond(r, 405, {"message": "no"})
        self.assertOutcome(self.run_attempt(), rpe.FAILED_SAFE, rpe.EXEC_MERGE_REJECTED_NOT_MERGEABLE, merges=1)
        # A new host process: fresh ledger instance on the same file, fresh client.
        ledger = rhl.HostLedger(self.ledger.path, owner="host-b", clock=lambda: NOW)
        authority = rauth.HumanCommandAuthority(self.authority.config, ledger, clock=lambda: NOW)
        host = rhg.compose_simulated_host(authority, ledger, rhg.GitHubPromotionClient(self.fake, clock=lambda: NOW))
        self.assertOutcome(self.run_attempt(host), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_REPLAY_DETECTED)
        self.assertEqual(len(self.fake.writes()), 1)
        again = self.authority.submit_command(tau.envelope(tau.command_for(self.request), self.private), self.request)
        self.assertEqual(again.reason_codes, (rauth.AUTH_COMMAND_REPLAYED,))

    def test_absent_or_revoked_command_writes_nothing(self):
        self.assertOutcome(self.run_attempt(), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_COMMAND_ABSENT)
        self.submit()
        self.authority.revoke_command("cmd-1", "DIRECTOR-REVOKED")
        self.assertOutcome(self.run_attempt(), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_COMMAND_REVOKED)
        self.assertEqual(self.fake.writes(), [])

    def test_revocation_during_the_attempt_blocks_consumption_and_the_merge(self):
        self.submit()
        reads = []

        def revoke_on_final_read(request):
            reads.append(1)
            if len(reads) == 2:   # the final read, after the final command check
                self.ledger.revoke_command("cmd-1", "DIRECTOR-REVOKED")
            return self.fake.default(request, P, {})

        self.fake.routes[("GET", P)] = revoke_on_final_read
        self.assertOutcome(self.run_attempt(), rpe.FAILED_SAFE, rpe.EXEC_CONSUMPTION_FAILED)
        self.assertEqual(self.fake.writes(), [])
        self.assertEqual(self.ledger.reservation_state(self.op), (rhl.RES_FINALIZED, rpe.FAILED_SAFE))

    def test_timeout_after_send_is_uncertain_recorded_and_never_retried(self):
        self.submit()

        def timeout(_request):
            raise rhg.TransportTimeout(request_sent=True)

        self.fake.routes[("PUT", f"{P}/pulls/{PR}/merge")] = timeout
        self.assertOutcome(self.run_attempt(), rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION,
                           rpe.EXEC_MERGE_OUTCOME_UNKNOWN, rpe.EXEC_NO_RETRY_AFTER_UNCERTAINTY, merges=1)
        self.assertEqual(self.ledger.merge_send_state(self.op), (rhl.SEND_UNCERTAIN, rpe.MERGE_TIMEOUT_AFTER_SEND))
        self.assertEqual(self.ledger.reservation_state(self.op),
                         (rhl.RES_FINALIZED, rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION))
        self.assertOutcome(self.run_attempt(), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_REPLAY_DETECTED)
        self.assertEqual(len(self.fake.writes()), 1)

    def test_unclassifiable_answer_or_unconfirmed_postcondition_is_uncertain(self):
        merge_path = ("PUT", f"{P}/pulls/{PR}/merge")
        for route, code in ((lambda r: respond(r, 500, {"message": "x"}), rpe.EXEC_MERGE_OUTCOME_UNKNOWN),
                            (lambda r: respond(r, 200, {"merged": True, "sha": MERGE_SHA}),
                             rpe.EXEC_POSTCONDITION_CONTRADICTS)):
            with self.subTest(code=code):
                self.build(f"ledger-{code}")
                self.submit()
                self.fake.routes[merge_path] = route   # GitHub state is NOT updated by these answers
                self.assertOutcome(self.run_attempt(), rpe.UNCERTAIN_REQUIRES_HUMAN_RECONCILIATION, code, merges=1)
                self.assertEqual(self.ledger.merge_send_state(self.op)[0], rhl.SEND_UNCERTAIN
                                 if code == rpe.EXEC_MERGE_OUTCOME_UNKNOWN else rhl.SEND_RESULT_RECORDED)

    def test_explicit_rejections_and_not_sent_fail_safe_after_one_call(self):
        merge_path = ("PUT", f"{P}/pulls/{PR}/merge")

        def not_sent(_request):
            raise rhg.TransportTimeout(request_sent=False)

        for route, code in ((lambda r: respond(r, 409, {"message": "Head branch was modified. Review."}),
                             rpe.EXEC_MERGE_REJECTED_HEAD_MISMATCH),
                            (lambda r: respond(r, 409, {"message": "Merge conflict"}), rpe.EXEC_MERGE_REJECTED_CONFLICT),
                            (lambda r: respond(r, 422, {"message": "x"}), rpe.EXEC_MERGE_REJECTED_UNPROCESSABLE),
                            (lambda r: respond(r, 403, {"message": "x"}), rpe.EXEC_MERGE_REJECTED_FORBIDDEN),
                            (not_sent, rpe.EXEC_MERGE_NOT_SENT)):
            with self.subTest(code=code):
                self.build(f"ledger-{code}")
                self.submit()
                self.fake.routes[merge_path] = route
                self.assertOutcome(self.run_attempt(), rpe.FAILED_SAFE, code, merges=1)
                self.assertEqual(len(self.fake.writes()), 1)
                self.assertEqual(self.ledger.merge_send_state(self.op)[0], rhl.SEND_RESULT_RECORDED)

    def test_drift_between_preflight_and_final_read_refuses_before_consumption(self):
        self.submit()
        reads = []

        def reviews(request):
            reads.append(1)
            if len(reads) == 2:
                self.fake.reviews.append(review_json(self.head, 5, state="COMMENTED", actor=OTHER))
            return self.fake.page(request, {"page": request.url.rsplit("page=", 1)[1], "per_page": "100"},
                                  self.fake.reviews)

        self.fake.routes[("GET", f"{P}/pulls/{PR}/reviews")] = reviews
        self.assertOutcome(self.run_attempt(), rpe.PRECONDITION_REFUSED, rpe.EXEC_STATE_CHANGED_DURING_PREFLIGHT)
        self.assertEqual(self.fake.writes(), [])
        self.assertEqual(self.ledger.reservation_state(self.op),
                         (rhl.RES_FINALIZED, rpe.PRECONDITION_REFUSED))

    def test_merge_queue_or_admin_bypass_refuses_before_any_reservation(self):
        for mutate, code in ((lambda f: f.protection["enforce_admins"].update(enabled=False),
                              rpe.EXEC_PROTECTION_ADMIN_BYPASS),
                             (lambda f: (f.rules.append({"type": "merge_queue", "ruleset_id": 7, "parameters": {}}),
                                         f.rulesets.update({7: {"id": 7, "enforcement": "active", "bypass_actors": [],
                                                                "current_user_can_bypass": "never"}})),
                              rpe.EXEC_MERGE_QUEUE_NOT_SUPPORTED)):
            with self.subTest(code=code):
                self.build(f"ledger-{code}")
                self.submit()
                mutate(self.fake)
                self.assertOutcome(self.run_attempt(), rpe.PRECONDITION_REFUSED, code)
                self.assertIsNone(self.ledger.reservation_state(self.op))
                self.assertEqual(self.fake.writes(), [])

    def test_unactivated_host_live_composition_and_production_entry_stay_blocked(self):
        self.submit()
        unactivated = rhg.GovernedPromotionHost(self.authority, self.ledger, self.client)
        self.assertOutcome(self.run_attempt(unactivated), rpe.AUTHORIZATION_REFUSED, rpe.EXEC_TRUSTED_HOST_ABSENT)
        prod = rpe.execute_promotion(self.request)
        self.assertOutcome(prod, rpe.AUTHORIZATION_REFUSED, rpe.EXEC_TRUSTED_HOST_NOT_AVAILABLE)
        self.assertEqual(prod.execution_mode, rpe.MODE_PRODUCTION_BLOCKED)
        self.assertEqual(self.fake.requests, [])
        self.assertEqual([e.event for e in self.ledger.audit_trail(self.op)], ["COMMAND_REGISTERED"])
        with self.assertRaises(rhg.HostActivationBlocked) as caught:
            rhg.compose_live_host()
        self.assertEqual(caught.exception.gaps, rhg.HOST_ACTIVATION_GAPS)
        other = rhl.HostLedger(self.root / "other.sqlite3", owner="host-a", clock=lambda: NOW)
        for args in ((self.authority, other, self.client), (self.authority, self.ledger, tpe.FakeHost({}, None)),
                     (object(), self.ledger, self.client)):
            with self.assertRaises(rhg.HostActivationBlocked):
                rhg.GovernedPromotionHost(*args)
        report = rhg.activation_report()
        self.assertEqual((report.activated, report.live_authorized, report.production_capable),
                         (False, False, False))
        self.assertEqual(report.core_requirements_unmet, rpe.PRODUCTION_ACTIVATION_REQUIREMENTS)
        self.assertEqual(report.accepted_transport_kinds, (rhg.TRANSPORT_KIND_IN_MEMORY_FAKE,))


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names} \
        | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}


class GitHubStructureTests(NoNetworkMixin, unittest.TestCase):
    def setUp(self):
        self.source = MODULE_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.code = re.sub(r'"""[\s\S]*?"""', "", self.source)

    def test_one_write_site_and_no_forbidden_operation_or_credential(self):
        strings = [n.value for n in ast.walk(self.tree) if isinstance(n, ast.Constant) and type(n.value) is str]
        for method in ("POST", "PATCH", "DELETE"):
            self.assertNotIn(method, strings)
        puts = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == "self._send"
                and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertEqual(ast.unparse(puts[0].args[1]), "f'{REPO_PATH}/pulls/{pr_number}/merge'")
        transport_calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call)
                           and ast.unparse(n.func) == "self._transport.send"]
        self.assertEqual(len(transport_calls), 1)   # `_send` is the single exit
        for banned in ("subprocess", "socket", "os", "urllib", "http", "requests", "httpx", "ssl", "runner_git",
                       "runner_pipeline", "runner_factory_ledger", "github"):
            self.assertNotIn(banned, _imports(MODULE_PATH), banned)
        for text in ("environ", "getenv", ".env", "git push", "update-ref", "git/refs", "Authorization", "Bearer",
                     "token", "admin_bypass", "squash", "rebase", "/comments"):
            self.assertNotIn(text, self.code, text)
        self.assertEqual(rhg.API_ORIGIN, "https://api.github.com")
        self.assertEqual(rhg.REPOSITORY, "ignacio-alvarez93/quesada-abogados")
        self.assertEqual(rhg.ACCEPTED_TRANSPORT_KINDS, (rhg.TRANSPORT_KIND_IN_MEMORY_FAKE,))

    def test_no_circular_imports_and_the_core_is_untouched(self):
        ledger, authority = _imports(AI_DIR / "runner_promotion_host_ledger.py"), \
            _imports(AI_DIR / "runner_promotion_host_authority.py")
        self.assertFalse({"runner_promotion_host_authority", "runner_promotion_host_github"} & ledger)
        self.assertNotIn("runner_promotion_host_github", authority)
        self.assertIn("runner_promotion_host_ledger", authority)
        for core in ("runner_promotion_executor.py", "runner_promotion_pr_gate.py",
                     "runner_promotion_human_authorization.py", "runner_promotion_authorization.py"):
            text = (AI_DIR / core).read_text(encoding="utf-8")
            self.assertNotIn("runner_promotion_host", text, core)
        self.assertIs(rpe.PRODUCTION_PROMOTION_CAPABLE, False)
        self.assertEqual(len(JOBS), 7)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.keyword):
                self.assertNotIn(node.arg, ("live_authorized", "human_command_authenticated", "authorizes_action",
                                            "execution_allowed"))
        self.assertNotIn("MODE_LIVE_AUTHORIZED", self.code)

    def test_docstring_states_the_boundary(self):
        doc = " ".join(rhg.__doc__.split())
        for phrase in ("never reads the environment", "ONLY place", "never resent", "protects only the head",
                       "NOT an authenticated host", "never inferred", "without optimistic defaults",
                       "compose_live_host"):
            self.assertIn(phrase, doc, phrase)


if __name__ == "__main__":
    unittest.main()
