"""FCP-3B-2B2-HOST-01: GitHub REST adapter and host composition (NOT LIVE).

The `GitHubPromotionPort` half of the `TrustedPromotionHost` contract of
`runner_promotion_executor`, and the composition of the three host parts
(authority -> ledger -> GitHub client) behind that contract. A library for a
FUTURE isolated host process: this delivery opens no connection, holds no
credential and produces no live promotion (`rpe.PRODUCTION_PROMOTION_CAPABLE`
stays False; `compose_live_host` always refuses).

Transport
---------
The client never builds credentials and never reads the environment. Every
request goes through a host-supplied `HostTransport` that is the ONLY place
where an authenticated HTTPS session to API_ORIGIN may exist; it is
provisioned by the host's trusted credential provider, never from Runner
variables. Only transports whose class declares a kind in
ACCEPTED_TRANSPORT_KINDS are accepted, and in this delivery that is the
in-memory fake alone. URLs are API_ORIGIN plus paths built from constants
and integers (the canonical repository is fixed); no URL from a payload or a
user is followed, and a response for another URL (redirect) is refused.

Reads (`read_fresh_state`)
--------------------------
Repository settings (merge commits allowed, not archived), `develop`, the PR
(`auto_merge` must be off), every changed file with renames (complete
pagination, at most rpg.MAX_CHANGED_FILES), the head commit, every latest
check run of the head SHA with its GitHub Actions workflow run (app id and
slug pinned), every review in listing order, classic branch protection and
every active ruleset rule of `develop` with its ruleset bypass list; then
the PR head and `develop` again: any movement during the read is a refusal.
JSON is parsed strictly (duplicate keys, NaN, wrong types and missing fields
refuse) and mapped into the existing FCP types (`rpg.PullRequestSnapshot`,
`rha.ReviewEventSequence`, `rpe.BranchProtectionState`) without optimistic
defaults: an absent fact is a refusal, or an incomplete listing that the
FCP-3B-2A/2B1 gates reject. 403, 404, rate limits, pagination limits, a bad
status, content type or size refuse. Protection that is not fully
representable (bypass allowances, hidden or non-empty ruleset bypass lists,
required checks not pinned to the GitHub Actions app, unknown settings) is
reported incomplete, never assumed.

The ONE write (`merge_pull_request`)
-----------------------------------
`PUT /repos/{owner}/{repo}/pulls/{n}/merge` with the expected head `sha` and
`merge_method="merge"`, at most once per client, after the host ledger has
journaled the send. No other method or path can leave the client: no
`git push`, no ref update, no admin bypass, no comment or approval. The
merge API's `sha` protects only the head; the base is protected by strict
required checks and verified afterwards from the merge commit parents. A
timeout or transport failure after the request may have left is
TIMEOUT_AFTER_SEND (never resent); 403/405/409/422 are explicit rejections;
any other answer raises (the executor records UNCERTAIN). The postcondition
is read (PR, merge commit parents, `develop`), never inferred.

Composition
-----------
`GovernedPromotionHost` wires the parts in the order the executor calls
them. Its `host_kind` is not accepted by the executor, and the simulation
subclass is built only around an in-memory fake transport. A host built by a
provider or the Runner from fakes is NOT an authenticated host;
`compose_live_host` refuses with HOST_ACTIVATION_GAPS.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

try:
    from scripts.ai import runner_integration as ri
    from scripts.ai import runner_promotion_executor as rpe
    from scripts.ai import runner_promotion_host_authority as rhauth
    from scripts.ai import runner_promotion_host_ledger as rhl
    from scripts.ai import runner_promotion_human_authorization as rha
    from scripts.ai import runner_promotion_pr_gate as rpg
except ImportError:  # pragma: no cover - direct script execution
    _this_dir = Path(__file__).resolve().parent
    if str(_this_dir) not in sys.path:
        sys.path.insert(0, str(_this_dir))
    import runner_integration as ri  # type: ignore[no-redef]
    import runner_promotion_executor as rpe  # type: ignore[no-redef]
    import runner_promotion_host_authority as rhauth  # type: ignore[no-redef]
    import runner_promotion_host_ledger as rhl  # type: ignore[no-redef]
    import runner_promotion_human_authorization as rha  # type: ignore[no-redef]
    import runner_promotion_pr_gate as rpg  # type: ignore[no-redef]


API_ORIGIN = "https://api.github.com"
API_VERSION = "2022-11-28"
REPOSITORY = rpg.CANONICAL_REPOSITORY
REPO_PATH = f"/repos/{REPOSITORY}"
BASE_BRANCH = rpg.BASE_BRANCH
GITHUB_ACTIONS_APP_ID = 15368
TRANSPORT_KIND_IN_MEMORY_FAKE = "IN_MEMORY_FAKE_TRANSPORT"
# Activation of a real transport kind requires a separate audited Work Order.
ACCEPTED_TRANSPORT_KINDS = (TRANSPORT_KIND_IN_MEMORY_FAKE,)

READ_TIMEOUT_SECONDS = 15
MERGE_TIMEOUT_SECONDS = 30
PER_PAGE = rpg.MAX_PAGE_SIZE
MAX_FILE_PAGES = rpg.MAX_CHANGED_FILES // PER_PAGE + 1
MAX_CHECK_PAGES = 10
MAX_REVIEW_PAGES = rha.MAX_REVIEWS // PER_PAGE
MAX_RULE_PAGES = 10
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

HOST_KIND_GOVERNED_NOT_ACTIVATED = "GOVERNED_HOST_NOT_ACTIVATED"

# Read refusals.
GH_TARGET_INVALID = "GH_TARGET_INVALID"
GH_TRANSPORT_NOT_ACCEPTED = "GH_TRANSPORT_NOT_ACCEPTED"
GH_TRANSPORT_FAILED = "GH_TRANSPORT_FAILED"
GH_TRANSPORT_TIMEOUT = "GH_TRANSPORT_TIMEOUT"
GH_RESPONSE_INVALID = "GH_RESPONSE_INVALID"
GH_URL_MISMATCH = "GH_URL_MISMATCH"
GH_RESPONSE_TOO_LARGE = "GH_RESPONSE_TOO_LARGE"
GH_CONTENT_TYPE_INVALID = "GH_CONTENT_TYPE_INVALID"
GH_JSON_INVALID = "GH_JSON_INVALID"
GH_PAYLOAD_INVALID = "GH_PAYLOAD_INVALID"
GH_RATE_LIMITED = "GH_RATE_LIMITED"
GH_PERMISSION_DENIED = "GH_PERMISSION_DENIED"
GH_NOT_FOUND = "GH_NOT_FOUND"
GH_HTTP_STATUS_UNEXPECTED = "GH_HTTP_STATUS_UNEXPECTED"
GH_PAGINATION_LIMIT = "GH_PAGINATION_LIMIT"
GH_PAGINATION_INCONSISTENT = "GH_PAGINATION_INCONSISTENT"
GH_REPOSITORY_MISMATCH = "GH_REPOSITORY_MISMATCH"
GH_REPOSITORY_ARCHIVED = "GH_REPOSITORY_ARCHIVED"
GH_MERGE_COMMIT_NOT_ALLOWED = "GH_MERGE_COMMIT_NOT_ALLOWED"
GH_AUTO_MERGE_ENABLED = "GH_AUTO_MERGE_ENABLED"
GH_FILES_LIMIT = "GH_FILES_LIMIT"
GH_CHECK_BINDING_INVALID = "GH_CHECK_BINDING_INVALID"
GH_STATE_CHANGED_DURING_READ = "GH_STATE_CHANGED_DURING_READ"
# Merge refusals before any send.
GH_MERGE_ARGUMENT_INVALID = "GH_MERGE_ARGUMENT_INVALID"
GH_MERGE_METHOD_INVALID = "GH_MERGE_METHOD_INVALID"
GH_MERGE_ALREADY_SENT = "GH_MERGE_ALREADY_SENT"
GH_WRITE_NOT_ALLOWED = "GH_WRITE_NOT_ALLOWED"
# Merge answers the executor cannot classify.
GH_MERGE_RESPONSE_UNRECOGNIZED = "GH_MERGE_RESPONSE_UNRECOGNIZED"
# Composition.
HOST_COMPOSITION_INVALID = "HOST_COMPOSITION_INVALID"

# What a live host must still prove; nothing in this delivery proves any.
HOST_ACTIVATION_GAPS = (
    "HOST_REQ_ISOLATED_PRIVILEGED_PROCESS_OUTSIDE_RUNNER_AND_PROVIDERS",
    "HOST_REQ_INDEPENDENT_CREDENTIAL_PROVISIONING",
    "HOST_REQ_AUTHENTICATED_HTTPS_TRANSPORT_HELD_ONLY_BY_HOST",
    "HOST_REQ_DIRECTOR_KEYS_PINNED_BY_HUMAN_PROVISIONING",
    "HOST_REQ_EFFECTIVE_HUMAN_IDENTITY_AND_KEY_CUSTODY",
    "HOST_REQ_LEDGER_ACL_JOURNAL_BACKUP_IN_HOST",
    "HOST_REQ_CRYPTOGRAPHY_DEPENDENCY_IN_HOST",
    "HOST_REQ_CI_JOB_FOR_HOST_SUITES",
    "HOST_REQ_CONTROLLED_ACTIVATION_ON_PROTECTED_TEST_REPOSITORY",
    "HOST_REQ_CORE_LIVE_ENTRYPOINT_WORK_ORDER",
    "HOST_REQ_INDEPENDENT_SECURITY_AUDIT",
)

# Classic protection keys this adapter represents; anything else is unknown.
_PROTECTION_KEYS = frozenset((
    "url", "required_status_checks", "required_pull_request_reviews", "enforce_admins", "allow_force_pushes",
    "allow_deletions", "required_linear_history", "required_conversation_resolution", "lock_branch",
    "block_creations", "allow_fork_syncing", "required_signatures", "restrictions",
))
# Enabled classic settings the gate does not model: listed as rule types so
# FCP-3B-2A reports the policy as not proven.
_UNMODELED_TOGGLES = ("required_conversation_resolution", "lock_branch", "block_creations", "required_signatures")
_MERGE_PATH_RE = re.compile(r"/repos/" + re.escape(REPOSITORY) + r"/pulls/[1-9][0-9]{0,9}/merge")
_PATH_RE = re.compile(r"/repos/" + re.escape(REPOSITORY) + r"(?:/[A-Za-z0-9._-]+)*")
_QUERY_VALUE_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_HEAD_MODIFIED = "Head branch was modified"
_STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# ---------------------------------------------------------------------------
# Transport contract (host side)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: tuple
    body: Optional[bytes]
    timeout_seconds: int


@dataclass(frozen=True)
class HttpResponse:
    """`url` is the URL the transport actually answered for."""

    status: int
    headers: tuple
    body: bytes
    url: str


class TransportTimeout(Exception):
    """`request_sent` is the transport's statement: False only if no byte of
    the request left the host."""

    def __init__(self, request_sent):
        self.request_sent = request_sent
        super().__init__("transport timeout")


class TransportFailure(Exception):
    def __init__(self, request_sent):
        self.request_sent = request_sent
        super().__init__("transport failure")


class HostTransport(Protocol):
    """Host-held, authenticated HTTPS to API_ORIGIN. `transport_kind` is a
    class attribute; the client never sees a credential."""

    transport_kind: str

    def send(self, request: HttpRequest) -> HttpResponse: ...


class GitHubReadRefused(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class GitHubMergeRefusedBeforeSend(Exception):
    """Nothing was sent."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class GitHubMergeUncertain(Exception):
    """A request was sent and its answer is not classifiable."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class HostActivationBlocked(Exception):
    def __init__(self, gaps):
        self.gaps = tuple(gaps)
        super().__init__(", ".join(self.gaps))


# ---------------------------------------------------------------------------
# Strict payload access
# ---------------------------------------------------------------------------

def _refuse(code=GH_PAYLOAD_INVALID):
    raise GitHubReadRefused(code)


def _get(obj, name, kind, nullable=False):
    """`obj[name]` of exactly `kind` (bool is never an int); missing or
    mistyped refuses."""
    if type(obj) is not dict or name not in obj:
        _refuse()
    value = obj[name]
    if value is None and nullable:
        return None
    if type(value) is not kind:
        _refuse()
    return value


def _sha(value, fmt=None) -> str:
    if type(value) is not str or rpg._sha_format(value) is None or (fmt and rpg._sha_format(value) != fmt):
        _refuse()
    return value


def _enabled(protection, name) -> Optional[bool]:
    if name not in protection:
        return None
    return _get(_get(protection, name, dict), "enabled", bool)


def _unique_pairs(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        _refuse(GH_JSON_INVALID)
    return dict(pairs)


def _reject_constant(_name):
    _refuse(GH_JSON_INVALID)


def _header(response, name) -> Optional[str]:
    values = [v for k, v in response.headers if type(k) is str and k.lower() == name]
    return values[0] if len(values) == 1 and type(values[0]) is str else None


def _stamp(instant) -> str:
    return instant.strftime(_STAMP_FORMAT)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GitHubPromotionClient:
    """Reads and the ONE merge, through a host transport only."""

    def __init__(self, transport, *, clock):
        kind = getattr(type(transport), "transport_kind", None)
        if transport is None or type(kind) is not str or kind not in ACCEPTED_TRANSPORT_KINDS \
                or not callable(getattr(transport, "send", None)) or not callable(clock):
            raise GitHubReadRefused(GH_TRANSPORT_NOT_ACCEPTED)
        self._transport, self._clock = transport, clock
        self._merge_sent = False

    # Requests -------------------------------------------------------------
    @staticmethod
    def _url(path: str, query=()) -> str:
        if type(path) is not str or not _PATH_RE.fullmatch(path) \
                or any(segment.strip(".") == "" for segment in path.split("/")[1:]):
            raise GitHubReadRefused(GH_TARGET_INVALID)
        parts = []
        for name, value in query:
            text = str(value) if type(value) is int else value
            if type(text) is not str or not _QUERY_VALUE_RE.fullmatch(text) or not re.fullmatch(r"[a-z_]+", name):
                raise GitHubReadRefused(GH_TARGET_INVALID)
            parts.append(f"{name}={text}")
        return API_ORIGIN + path + ("?" + "&".join(parts) if parts else "")

    def _send(self, method: str, path: str, query=(), body: Optional[bytes] = None,
              timeout: int = READ_TIMEOUT_SECONDS) -> HttpResponse:
        """The single exit of the client. GET anywhere under the canonical
        repository; PUT only to the merge path; nothing else ever."""
        if method == "PUT":
            if not _MERGE_PATH_RE.fullmatch(path or "") or query or type(body) is not bytes:
                raise GitHubMergeRefusedBeforeSend(GH_WRITE_NOT_ALLOWED)
        elif method != "GET" or body is not None:
            raise GitHubMergeRefusedBeforeSend(GH_WRITE_NOT_ALLOWED)
        headers = (("accept", "application/vnd.github+json"), ("x-github-api-version", API_VERSION))
        if method == "PUT":
            headers += (("content-type", "application/json"),)
        request = HttpRequest(method=method, url=self._url(path, query), headers=headers, body=body,
                              timeout_seconds=timeout)
        response = self._transport.send(request)
        if type(response) is not HttpResponse or type(response.status) is not int \
                or type(response.body) is not bytes or type(response.headers) is not tuple \
                or not all(type(h) is tuple and len(h) == 2 for h in response.headers):
            raise GitHubReadRefused(GH_RESPONSE_INVALID)
        if response.url != request.url:
            raise GitHubReadRefused(GH_URL_MISMATCH)
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise GitHubReadRefused(GH_RESPONSE_TOO_LARGE)
        return response

    @staticmethod
    def _json(response: HttpResponse):
        content_type = _header(response, "content-type") or ""
        if not content_type.split(";")[0].strip().lower() == "application/json":
            _refuse(GH_CONTENT_TYPE_INVALID)
        try:
            return json.loads(response.body.decode("utf-8"), object_pairs_hook=_unique_pairs,
                              parse_constant=_reject_constant)
        except GitHubReadRefused:
            raise
        except (ValueError, UnicodeDecodeError):
            _refuse(GH_JSON_INVALID)

    @staticmethod
    def _status_error(response: HttpResponse) -> str:
        if response.status in (403, 429) and (_header(response, "x-ratelimit-remaining") == "0"
                                              or _header(response, "retry-after") is not None):
            return GH_RATE_LIMITED
        return {403: GH_PERMISSION_DENIED, 404: GH_NOT_FOUND}.get(response.status, GH_HTTP_STATUS_UNEXPECTED)

    def _read(self, path: str, query=(), *, absent_ok=False):
        """The JSON of a 200 answer (None for 404 when `absent_ok`)."""
        try:
            response = self._send("GET", path, query)
        except TransportTimeout:
            raise GitHubReadRefused(GH_TRANSPORT_TIMEOUT) from None
        except TransportFailure:
            raise GitHubReadRefused(GH_TRANSPORT_FAILED) from None
        if response.status == 404 and absent_ok:
            return None
        if response.status != 200:
            raise GitHubReadRefused(self._status_error(response))
        return self._json(response)

    def _pages(self, path, extract, max_pages, extra=()):
        """Every item of a paginated listing: reads until a short page. A
        full last allowed page is a limit refusal, never a truncated list.
        Returns (items, payloads)."""
        items, payloads = [], []
        for page in range(1, max_pages + 1):
            payload = self._read(path, extra + (("per_page", PER_PAGE), ("page", page)))
            chunk = extract(payload)
            if type(chunk) is not list or len(chunk) > PER_PAGE:
                _refuse(GH_PAGINATION_INCONSISTENT)
            items += chunk
            payloads.append(payload)
            if len(chunk) < PER_PAGE:
                return items, payloads
        raise GitHubReadRefused(GH_PAGINATION_LIMIT)

    # Target ---------------------------------------------------------------
    @staticmethod
    def _target(repository, pr_number):
        if repository != REPOSITORY or not rha._int(pr_number, 1, rpg.MAX_PR_NUMBER):
            raise GitHubReadRefused(GH_TARGET_INVALID)

    # Individual reads -----------------------------------------------------
    def _repository_settings(self):
        repo = self._read(REPO_PATH)
        if _get(repo, "full_name", str) != REPOSITORY:
            _refuse(GH_REPOSITORY_MISMATCH)
        if _get(repo, "archived", bool):
            _refuse(GH_REPOSITORY_ARCHIVED)
        if _get(repo, "allow_merge_commit", bool) is not True:
            _refuse(GH_MERGE_COMMIT_NOT_ALLOWED)

    def _branch(self):
        branch = self._read(f"{REPO_PATH}/branches/{BASE_BRANCH}")
        if _get(branch, "name", str) != BASE_BRANCH:
            _refuse()
        return _sha(_get(_get(branch, "commit", dict), "sha", str)), _get(branch, "protected", bool)

    def _pull(self, pr_number):
        pr = self._read(f"{REPO_PATH}/pulls/{pr_number}")
        if _get(pr, "number", int) != pr_number:
            _refuse()
        if _get(pr, "auto_merge", dict, nullable=True) is not None:
            _refuse(GH_AUTO_MERGE_ENABLED)
        base, head = _get(pr, "base", dict), _get(pr, "head", dict)
        head_repo = _get(head, "repo", dict)
        return dict(
            state=_get(pr, "state", str), merged=_get(pr, "merged", bool), draft=_get(pr, "draft", bool),
            base_repository=_get(_get(base, "repo", dict), "full_name", str), base_ref=_get(base, "ref", str),
            base_sha=_sha(_get(base, "sha", str)), head_repository=_get(head_repo, "full_name", str),
            head_ref=_get(head, "ref", str), head_sha=_sha(_get(head, "sha", str)),
            changed_files=_get(pr, "changed_files", int), author_id=_get(_get(pr, "user", dict), "id", int),
            merge_commit_sha=_get(pr, "merge_commit_sha", str, nullable=True),
        )

    def _files(self, pr_number, reported):
        if reported > rpg.MAX_CHANGED_FILES:
            _refuse(GH_FILES_LIMIT)
        raw, _ = self._pages(f"{REPO_PATH}/pulls/{pr_number}/files", lambda p: p, MAX_FILE_PAGES)
        files = []
        for f in raw:
            status = _get(f, "status", str)
            previous = _get(f, "previous_filename", str) if status in ("renamed", "copied") else None
            if status not in ("renamed", "copied") and "previous_filename" in f:
                _refuse()
            files.append(rpg.ChangedFile(path=_get(f, "filename", str), status=status, previous_path=previous))
        # pages_fetched counts the pages that carried items; the terminating
        # short (possibly empty) page is the proof of completeness.
        return rpg.ChangedFileListing(files=tuple(files), reported_total=reported, page_size=PER_PAGE,
                                      pages_fetched=max(1, -(-len(files) // PER_PAGE)),
                                      complete=len(files) == reported)

    def _head_commit(self, head_sha):
        commit = self._read(f"{REPO_PATH}/commits/{head_sha}")
        if _get(commit, "sha", str) != head_sha:
            _refuse()
        author = _get(commit, "author", dict, nullable=True)
        return None if author is None else _get(author, "id", int)

    def _workflow_run(self, suite_id, head_sha, cache):
        if suite_id not in cache:
            listing = self._read(f"{REPO_PATH}/actions/runs", (("check_suite_id", suite_id), ("per_page", PER_PAGE)))
            runs = _get(listing, "workflow_runs", list)
            if _get(listing, "total_count", int) != 1 or len(runs) != 1:
                _refuse(GH_CHECK_BINDING_INVALID)
            run = runs[0]
            if _get(run, "check_suite_id", int) != suite_id or _sha(_get(run, "head_sha", str)) != head_sha:
                _refuse(GH_CHECK_BINDING_INVALID)
            cache[suite_id] = (_get(run, "name", str), _get(run, "path", str), _get(run, "id", int),
                               _get(run, "event", str))
        return cache[suite_id]

    def _checks(self, head_sha, policy):
        raw, payloads = self._pages(f"{REPO_PATH}/commits/{head_sha}/check-runs",
                                    lambda p: _get(p, "check_runs", list), MAX_CHECK_PAGES, (("filter", "latest"),))
        totals = {_get(p, "total_count", int) for p in payloads}
        if len(totals) != 1:
            _refuse(GH_PAGINATION_INCONSISTENT)
        total, runs, cache = totals.pop(), [], {}
        for c in raw:
            app = _get(c, "app", dict)
            slug, app_id = _get(app, "slug", str), _get(app, "id", int)
            workflow = (None, None, None, None)
            if slug == rpg.CI_APP_SLUG:
                if app_id != GITHUB_ACTIONS_APP_ID:
                    _refuse(GH_CHECK_BINDING_INVALID)
                suite = _get(_get(c, "check_suite", dict), "id", int)
                workflow = self._workflow_run(suite, _get(c, "head_sha", str), cache)
            runs.append(rpg.CheckRun(
                name=_get(c, "name", str), check_run_id=_get(c, "id", int), head_sha=_get(c, "head_sha", str),
                status=_get(c, "status", str), conclusion=_get(c, "conclusion", str, nullable=True), app_slug=slug,
                workflow_name=workflow[0], workflow_path=workflow[1], workflow_run_id=workflow[2],
                event=workflow[3],
                pull_request_numbers=tuple(_get(p, "number", int) for p in _get(c, "pull_requests", list))))
        return rpg.RequiredCheckListing(policy=policy, runs=tuple(runs), reported_total=total,
                                        complete=len(runs) == total)

    def _reviews(self, pr_number, pr, head_author_id, observed_at):
        raw, _ = self._pages(f"{REPO_PATH}/pulls/{pr_number}/reviews", lambda p: p, MAX_REVIEW_PAGES)
        events = []
        for r in raw:
            user = _get(r, "user", dict)
            events.append(rha.ReviewEvent(
                review_id=_get(r, "id", int), repository=REPOSITORY, pr_number=pr_number,
                actor_id=_get(user, "id", int), actor_login=_get(user, "login", str),
                actor_type=_get(user, "type", str), state=_get(r, "state", str),
                commit_sha=_get(r, "commit_id", str), submitted_at=_get(r, "submitted_at", str)))
        return rha.ReviewEventSequence(
            repository=REPOSITORY, pr_number=pr_number, pr_head_sha=pr["head_sha"], pr_author_id=pr["author_id"],
            head_commit_author_id=head_author_id, events=tuple(events), reported_total=len(events),
            page_size=PER_PAGE, pages_fetched=max(1, -(-len(events) // PER_PAGE)), complete=True,
            observed_at=observed_at)

    def _rulesets(self):
        rules, _ = self._pages(f"{REPO_PATH}/rules/branches/{BASE_BRANCH}", lambda p: p, MAX_RULE_PAGES)
        complete, details = True, {}
        for rule in rules:
            ruleset_id = _get(rule, "ruleset_id", int)
            if ruleset_id not in details:
                ruleset = self._read(f"{REPO_PATH}/rulesets/{ruleset_id}", absent_ok=True)
                if ruleset is None or _get(ruleset, "id", int) != ruleset_id \
                        or _get(ruleset, "enforcement", str) != "active":
                    complete = False
                # The bypass list is visible only with admin read access: hidden
                # or non-empty, the rules are not enforceable as represented.
                elif "bypass_actors" not in ruleset or _get(ruleset, "bypass_actors", list) != [] \
                        or ruleset.get("current_user_can_bypass", "never") != "never":
                    complete = False
                details[ruleset_id] = True
        return rules, complete

    def _protection(self, protected):
        """(rpg.BranchPolicy, rpe.BranchProtectionState), or (None, None)
        when `develop` has no classic protection."""
        protection = self._read(f"{REPO_PATH}/branches/{BASE_BRANCH}/protection", absent_ok=True)
        if protection is None or not protected:
            return None, None
        if type(protection) is not dict:
            _refuse()
        complete = set(protection) <= _PROTECTION_KEYS
        rule_types, checks = set(), set()
        pull_required, approvals, dismiss_stale, strict = False, 0, False, False
        status_checks = _get(protection, "required_status_checks", dict, nullable=True) \
            if "required_status_checks" in protection else None
        if status_checks is not None:
            strict = _get(status_checks, "strict", bool)
            for entry in _get(status_checks, "checks", list):
                name, app_id = _get(entry, "context", str), _get(entry, "app_id", int, nullable=True)
                checks.add(name)
                if app_id is None or (name in rpg.REQUIRED_CI_JOBS and app_id != GITHUB_ACTIONS_APP_ID):
                    complete = False   # satisfiable by any status of that name
            if set(_get(status_checks, "contexts", list)) != checks:
                complete = False
            rule_types.add("required_status_checks")
        reviews = _get(protection, "required_pull_request_reviews", dict, nullable=True) \
            if "required_pull_request_reviews" in protection else None
        if reviews is not None:
            pull_required = True
            approvals = _get(reviews, "required_approving_review_count", int)
            dismiss_stale = _get(reviews, "dismiss_stale_reviews", bool)
            bypass = reviews.get("bypass_pull_request_allowances")
            if bypass is not None and (type(bypass) is not dict or any(bypass.get(k) for k in bypass)):
                complete = False
            if _get(reviews, "require_code_owner_reviews", bool):
                rule_types.add("code_owner_review")
            if reviews.get("require_last_push_approval") is True:
                rule_types.add("last_push_approval")
            rule_types.add("pull_request")
        enforce_admins = _enabled(protection, "enforce_admins")
        force_pushes = _enabled(protection, "allow_force_pushes")
        deletions = _enabled(protection, "allow_deletions")
        if enforce_admins is None or force_pushes is None or deletions is None:
            _refuse()
        if not force_pushes:
            rule_types.add("non_fast_forward")
        if not deletions:
            rule_types.add("deletion")
        if _enabled(protection, "required_linear_history"):
            rule_types.add("required_linear_history")
        for toggle in _UNMODELED_TOGGLES:
            if _enabled(protection, toggle):
                rule_types.add(toggle)
        if protection.get("restrictions") is not None:
            rule_types.add("restrictions")
        rules, rules_complete = self._rulesets()
        merge_queue = False
        for rule in rules:
            kind = _get(rule, "type", str)
            rule_types.add(kind)
            params = rule.get("parameters") or {}
            if type(params) is not dict:
                _refuse()
            if kind == "merge_queue":
                merge_queue = True
            elif kind == "pull_request":
                pull_required = True
                approvals = max(approvals, _get(params, "required_approving_review_count", int))
                dismiss_stale = dismiss_stale or _get(params, "dismiss_stale_reviews_on_push", bool)
            elif kind == "required_status_checks":
                strict = strict or _get(params, "strict_required_status_checks_policy", bool)
                for entry in _get(params, "required_status_checks", list):
                    name = _get(entry, "context", str)
                    integration = _get(entry, "integration_id", int) if "integration_id" in entry else None
                    checks.add(name)
                    if integration is None or (name in rpg.REQUIRED_CI_JOBS and integration != GITHUB_ACTIONS_APP_ID):
                        complete = False
        complete = complete and rules_complete
        names = tuple(sorted(checks))
        policy = rpg.BranchPolicy(base_ref=BASE_BRANCH, rule_types=tuple(sorted(rule_types)),
                                  required_check_names=names, complete=complete)
        state = rpe.BranchProtectionState(
            repository=REPOSITORY, base_ref=BASE_BRANCH, complete=complete, pull_request_required=pull_required,
            required_approving_review_count=approvals, dismiss_stale_reviews=dismiss_stale,
            required_check_names=names, strict_up_to_date=strict, enforce_admins=enforce_admins,
            allow_force_pushes=force_pushes, allow_deletions=deletions, merge_queue_required=merge_queue)
        return policy, state

    # GitHubPromotionPort --------------------------------------------------
    def read_fresh_state(self, repository: str, pr_number: int) -> rpe.FreshPromotionState:
        """One complete fresh read, or GitHubReadRefused."""
        self._target(repository, pr_number)
        self._repository_settings()
        tip, protected = self._branch()
        pr = self._pull(pr_number)
        fmt = rpg._sha_format(pr["head_sha"])
        files = self._files(pr_number, pr["changed_files"])
        head_author = self._head_commit(pr["head_sha"])
        policy, protection = self._protection(protected)
        checks = self._checks(pr["head_sha"], policy)
        observed_at = _stamp(self._clock())
        reviews = self._reviews(pr_number, pr, head_author, observed_at)
        # The same facts again: any movement during the read is a race.
        if self._pull(pr_number)["head_sha"] != pr["head_sha"] or self._branch()[0] != tip:
            raise GitHubReadRefused(GH_STATE_CHANGED_DURING_READ)
        _sha(tip, fmt)
        metadata = rpg.PullRequestMetadata(
            repository=REPOSITORY, number=pr_number, state=pr["state"], merged=pr["merged"], draft=pr["draft"],
            base_repository=pr["base_repository"], base_ref=pr["base_ref"], base_sha=pr["base_sha"],
            head_repository=pr["head_repository"], head_ref=pr["head_ref"], head_sha=pr["head_sha"],
            base_branch_sha=tip, changed_files=pr["changed_files"])
        return rpe.FreshPromotionState(
            repository=REPOSITORY, pr_number=pr_number,
            pr_snapshot=rpg.PullRequestSnapshot(pull_request=metadata, changed_files=files, checks=checks),
            review_sequence=reviews, protection=protection, develop_tip_sha=tip)

    def merge_pull_request(self, repository: str, pr_number: int, expected_head_sha: str, merge_method: str,
                           permit_id: str) -> rpe.MergeResponse:
        """The ONE write, at most once per client. Arguments are checked
        before anything is sent (GitHubMergeRefusedBeforeSend)."""
        if repository != REPOSITORY or not rha._int(pr_number, 1, rpg.MAX_PR_NUMBER) \
                or rpg._sha_format(expected_head_sha) is None or not rpe._id_ok(permit_id):
            raise GitHubMergeRefusedBeforeSend(GH_MERGE_ARGUMENT_INVALID)
        if merge_method != rpe.MERGE_METHOD:
            raise GitHubMergeRefusedBeforeSend(GH_MERGE_METHOD_INVALID)
        if self._merge_sent:
            raise GitHubMergeRefusedBeforeSend(GH_MERGE_ALREADY_SENT)
        body = json.dumps({"merge_method": rpe.MERGE_METHOD, "sha": expected_head_sha}, sort_keys=True,
                          separators=(",", ":")).encode("ascii")
        self._merge_sent = True
        try:
            response = self._send("PUT", f"{REPO_PATH}/pulls/{pr_number}/merge", body=body,
                                  timeout=MERGE_TIMEOUT_SECONDS)
        except (TransportTimeout, TransportFailure) as exc:
            if exc.request_sent is False:
                return rpe.MergeResponse(rpe.MERGE_NOT_SENT, None, None)
            return rpe.MergeResponse(rpe.MERGE_TIMEOUT_AFTER_SEND, None, None)
        except GitHubReadRefused:
            raise GitHubMergeUncertain(GH_MERGE_RESPONSE_UNRECOGNIZED) from None
        return self._merge_response(response, rpg._sha_format(expected_head_sha))

    def _merge_response(self, response, fmt) -> rpe.MergeResponse:
        status = response.status
        if status == 200:
            try:
                payload = self._json(response)
                merged, sha = _get(payload, "merged", bool), _get(payload, "sha", str)
            except GitHubReadRefused:
                raise GitHubMergeUncertain(GH_MERGE_RESPONSE_UNRECOGNIZED) from None
            if merged is not True or not ri._is_sha(sha, fmt):
                raise GitHubMergeUncertain(GH_MERGE_RESPONSE_UNRECOGNIZED)
            return rpe.MergeResponse(rpe.MERGE_MERGED, 200, sha)
        if status == 409:
            try:
                message = _get(self._json(response), "message", str)
            except GitHubReadRefused:
                message = ""
            kind = rpe.MERGE_REJECTED_HEAD_MISMATCH if message.startswith(_HEAD_MODIFIED) \
                else rpe.MERGE_REJECTED_CONFLICT
            return rpe.MergeResponse(kind, 409, None)
        rejected = {403: rpe.MERGE_REJECTED_FORBIDDEN, 405: rpe.MERGE_REJECTED_NOT_MERGEABLE,
                    422: rpe.MERGE_REJECTED_UNPROCESSABLE}
        if status in rejected:
            return rpe.MergeResponse(rejected[status], status, None)
        raise GitHubMergeUncertain(GH_MERGE_RESPONSE_UNRECOGNIZED)

    def read_postcondition(self, repository: str, pr_number: int) -> rpe.PostMergeObservation:
        """PR, merge commit parents (only when merged) and `develop`, read."""
        self._target(repository, pr_number)
        pr = self._pull(pr_number)
        parents = ()
        merge_sha = pr["merge_commit_sha"]
        if pr["merged"]:
            commit = self._read(f"{REPO_PATH}/commits/{_sha(merge_sha)}")
            if _get(commit, "sha", str) != merge_sha:
                _refuse()
            parents = tuple(_sha(_get(p, "sha", str)) for p in _get(commit, "parents", list))
        tip, _ = self._branch()
        return rpe.PostMergeObservation(
            repository=REPOSITORY, pr_number=pr_number, state=pr["state"], merged=pr["merged"],
            head_sha=pr["head_sha"], merge_commit_sha=merge_sha, merge_commit_parents=parents, develop_tip_sha=tip)


# ---------------------------------------------------------------------------
# Composition (one trust boundary)
# ---------------------------------------------------------------------------

class GovernedPromotionHost:
    """authority -> ledger -> GitHub client behind the executor's
    `TrustedPromotionHost` contract. Its `host_kind` is not accepted by the
    executor: constructing it activates nothing."""

    host_kind = HOST_KIND_GOVERNED_NOT_ACTIVATED

    def __init__(self, authority, ledger, github):
        if type(authority) is not rhauth.HumanCommandAuthority or type(ledger) is not rhl.HostLedger \
                or type(github) is not GitHubPromotionClient or authority.registry is not ledger:
            raise HostActivationBlocked((HOST_COMPOSITION_INVALID,))
        self.authority, self.ledger, self.github = authority, ledger, github

    # LeasePort
    def acquire_lease(self, operation_id, resource):
        return self.ledger.acquire_lease(operation_id, resource)

    def release_lease(self, lease_id):
        self.ledger.release_lease(lease_id)

    # HumanCommandPort
    def verify_human_command(self, operation_id, repository, pr_number, base_sha, head_sha, action):
        return self.authority.verify_human_command(operation_id, repository, pr_number, base_sha, head_sha, action)

    # SingleUseLedgerPort
    def reserve_single_use(self, operation_id, command_id):
        return self.ledger.reserve_single_use(operation_id, command_id)

    def issue_operation_permit(self, operation_id, reservation_id, command_id):
        return self.ledger.issue_operation_permit(operation_id, reservation_id, command_id)

    def consume_single_use(self, reservation_id):
        return self.ledger.consume_single_use(reservation_id)

    def finalize_reservation(self, reservation_id, final_state):
        self.ledger.finalize_reservation(reservation_id, final_state)

    # GitHubPromotionPort
    def read_fresh_state(self, repository, pr_number):
        return self.github.read_fresh_state(repository, pr_number)

    def merge_pull_request(self, repository, pr_number, expected_head_sha, merge_method, permit_id):
        """Journal the send durably, send once, record the answer. A refusal
        before the send is NOT_SENT; anything unknown after it is UNCERTAIN."""
        if merge_method != rpe.MERGE_METHOD:
            return rpe.MergeResponse(rpe.MERGE_NOT_SENT, None, None)
        try:
            self.ledger.begin_merge_send(permit_id, repository, pr_number, expected_head_sha)
        except rhl.HostLedgerRefused:
            return rpe.MergeResponse(rpe.MERGE_NOT_SENT, None, None)
        try:
            response = self.github.merge_pull_request(repository, pr_number, expected_head_sha, merge_method,
                                                      permit_id)
        except GitHubMergeRefusedBeforeSend:
            self.ledger.record_merge_response(permit_id, rpe.MERGE_NOT_SENT)
            return rpe.MergeResponse(rpe.MERGE_NOT_SENT, None, None)
        except BaseException:
            self.ledger.record_merge_uncertain(permit_id)
            raise
        self.ledger.record_merge_response(permit_id, response.status)
        return response

    def read_postcondition(self, repository, pr_number):
        return self.github.read_postcondition(repository, pr_number)


class SimulatedGovernedPromotionHost(GovernedPromotionHost):
    """The same composition, accepted only by `rpe.simulate_promotion`, and
    only around an in-memory fake transport. Outcomes are SIMULATED."""

    host_kind = rpe.HOST_KIND_IN_MEMORY_SIMULATION


def compose_simulated_host(authority, ledger, github) -> SimulatedGovernedPromotionHost:
    if type(github) is not GitHubPromotionClient \
            or getattr(type(github._transport), "transport_kind", None) != TRANSPORT_KIND_IN_MEMORY_FAKE:
        raise HostActivationBlocked((HOST_COMPOSITION_INVALID,))
    return SimulatedGovernedPromotionHost(authority, ledger, github)


def compose_live_host():
    """There is no live host in this delivery: always refuses."""
    raise HostActivationBlocked(HOST_ACTIVATION_GAPS)


@dataclass(frozen=True)
class HostActivationReport:
    """No code path sets `activated` or `live_authorized`."""

    production_capable: bool
    host_activation_gaps: tuple
    core_requirements_unmet: tuple
    cryptography_available: bool
    accepted_transport_kinds: tuple
    activated: bool = False
    live_authorized: bool = False


def activation_report() -> HostActivationReport:
    """What exists and what is still missing before any live operation."""
    return HostActivationReport(
        production_capable=rpe.PRODUCTION_PROMOTION_CAPABLE, host_activation_gaps=HOST_ACTIVATION_GAPS,
        core_requirements_unmet=rpe.PRODUCTION_ACTIVATION_REQUIREMENTS, cryptography_available=rhauth.CRYPTO_AVAILABLE,
        accepted_transport_kinds=ACCEPTED_TRANSPORT_KINDS)
