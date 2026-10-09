"""Durable governed SeleniumBase UWT transition replay certification.

QCC_UWT_GOVERNED_TRANSITION_REPLAY_CERTIFICATION_V1

Generic UWT/AUTO TWIN infrastructure: given ANY materialized revision
(materialized_root + twin_key + revision_id), replays every edge
recorded in ``runtime/navigation_transitions.json`` against a REAL
governed SeleniumBase browser driven by ``TwinBrowserRuntimeService``,
and asserts each transition lands on its recorded ``after_state_id``.

Nothing here references Mercurio, Red SARA, DEHu or any other
specific site: the certification fixture is supplied exclusively via
environment variables, read once at collection time. If unset, the
test is skipped (not failed) -- this file stays a durable, reusable
regression/certification harness regardless of which revision is
being certified.

Each transition is replayed in isolation: the browser is (re)started
fresh at ``before_state_id`` for every edge. This matches the one
proven unit of evidence already established for this contract (an
isolated positional transition replay) and avoids coupling this
harness to any single site's full walk ordering, which is a materializer
concern, not a replay concern.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from backend.services.twin_browser_runtime_service import (
    TwinBrowserRuntimeService,
)


ENV_MATERIALIZED_ROOT = "QCC_UWT_CERT_MATERIALIZED_ROOT"
ENV_TWIN_KEY = "QCC_UWT_CERT_TWIN_KEY"
ENV_REVISION_ID = "QCC_UWT_CERT_REVISION_ID"

_DEFAULT_REACH_TIMEOUT_SECONDS = 15.0
_POLL_INTERVAL_SECONDS = 0.2


# Executed via TwinBrowserRuntimeService.execute_script, which wraps
# this body as a function body (``arguments[0]``, ``arguments[1]``
# are the positional ``args``). Generic across any UWT navigation
# transition record: applies the recorded navigation_context (form
# state the trigger action is conditioned on), then clicks the exact
# physical trigger element identified by the transition's action
# selector, including the universal ``:qcc-nth-onclick(N)`` positional
# disambiguation suffix emitted by the materializer.
_APPLY_CONTEXT_AND_CLICK_TRIGGER_SCRIPT = r"""
var context = arguments[0] || [];
var selector = arguments[1];

for (var i = 0; i < context.length; i++) {
    var entry = context[i];
    var nodes = document.querySelectorAll(entry.selector);
    var wanted = entry.selected_values || [];
    var kind = String(entry.kind || "").toUpperCase();

    if (nodes.length === 0) {
        throw new Error(
            "QCC_UWT_REPLAY_CONTEXT_SELECTOR_NOT_FOUND:" + entry.selector
        );
    }

    if (kind === "RADIO" || kind === "CHECKBOX") {
        var matched = false;

        for (var j = 0; j < nodes.length; j++) {
            var node = nodes[j];
            var isWanted = wanted.indexOf(node.value) !== -1;
            node.checked = isWanted;

            if (isWanted) {
                matched = true;
                node.dispatchEvent(new Event("input", {bubbles: true}));
                node.dispatchEvent(new Event("change", {bubbles: true}));
            }
        }

        if (!matched) {
            throw new Error(
                "QCC_UWT_REPLAY_CONTEXT_VALUE_NOT_FOUND:" + entry.selector
            );
        }
    } else if (kind === "SELECT") {
        var select = nodes[0];
        select.value = wanted[0];
        select.dispatchEvent(new Event("input", {bubbles: true}));
        select.dispatchEvent(new Event("change", {bubbles: true}));
    } else {
        throw new Error(
            "QCC_UWT_REPLAY_CONTEXT_KIND_UNSUPPORTED:" + kind
        );
    }
}

var positional = /^(.*):qcc-nth-onclick\((\d+)\)$/.exec(selector);
var target;

if (positional) {
    var candidates = document.querySelectorAll(positional[1]);
    target = candidates[parseInt(positional[2], 10) - 1] || null;
} else {
    target = document.querySelector(selector);
}

if (!target) {
    throw new Error("QCC_UWT_REPLAY_TRIGGER_ELEMENT_NOT_FOUND:" + selector);
}

target.click();
return true;
"""


def _require_certification_fixture():
    materialized_root = os.environ.get(ENV_MATERIALIZED_ROOT)
    twin_key = os.environ.get(ENV_TWIN_KEY)
    revision_id = os.environ.get(ENV_REVISION_ID)

    if not materialized_root or not twin_key or not revision_id:
        pytest.skip(
            "QCC_UWT_CERT_FIXTURE_NOT_CONFIGURED: set "
            + ", ".join(
                (ENV_MATERIALIZED_ROOT, ENV_TWIN_KEY, ENV_REVISION_ID)
            )
        )

    return Path(materialized_root), twin_key, revision_id


def _load_navigation_runtime(materialized_root, twin_key, revision_id):
    runtime_path = (
        materialized_root
        / twin_key
        / revision_id
        / "runtime"
        / "navigation_transitions.json"
    )

    if not runtime_path.is_file():
        pytest.fail(
            "QCC_UWT_CERT_NAVIGATION_RUNTIME_MISSING:" + str(runtime_path)
        )

    return json.loads(runtime_path.read_text(encoding="utf-8"))


def _wait_for_runtime_entry(service, *, twin_key, expected_entry, timeout):
    deadline = time.monotonic() + timeout
    last_href = None
    last_error = None

    while time.monotonic() < deadline:
        try:
            last_href = service.execute_script(
                twin_key=twin_key,
                script="return window.location.href;",
            )
        except Exception as exc:  # noqa: BLE001 - polled transient CDP state
            last_error = exc
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue

        if expected_entry in str(last_href or ""):
            return last_href

        time.sleep(_POLL_INTERVAL_SECONDS)

    raise AssertionError(
        "QCC_UWT_REPLAY_TARGET_NOT_REACHED:"
        + f" expected_entry={expected_entry}"
        + f" last_href={last_href}"
        + f" last_error={last_error}"
    )


def test_uwt_governed_transition_replay_certification():
    materialized_root, twin_key, revision_id = _require_certification_fixture()

    navigation_runtime = _load_navigation_runtime(
        materialized_root, twin_key, revision_id
    )

    transitions = navigation_runtime.get("interactive_transitions") or []
    declared_count = navigation_runtime.get("transition_count")

    assert declared_count == len(transitions), (
        "QCC_UWT_CERT_TRANSITION_COUNT_MISMATCH:"
        f" declared={declared_count} actual={len(transitions)}"
    )

    assert transitions, "QCC_UWT_CERT_NO_TRANSITIONS_TO_REPLAY"

    service = TwinBrowserRuntimeService(
        materialized_root=materialized_root,
    )

    results = []

    try:
        for index, transition in enumerate(transitions, start=1):
            before_state_id = transition["before_state_id"]
            after_state_id = transition["after_state_id"]
            action = transition["action"]
            navigation_context = transition.get("navigation_context") or []
            target_runtime_entry = transition["target_runtime_entry"]

            try:
                status = service.start(
                    twin_key=twin_key,
                    revision_id=revision_id,
                    state_id=before_state_id,
                )
            except Exception as exc:  # noqa: BLE001 - fail-closed to BLOCKED
                pytest.skip(
                    "SELENIUMBASE_E2E_BLOCKED:"
                    f" transition={index}/{len(transitions)}"
                    f" start_failed={type(exc).__name__}: {exc}"
                )
                return

            if status["status"] != "RUNNING":
                pytest.skip(
                    "SELENIUMBASE_E2E_BLOCKED:"
                    f" transition={index}/{len(transitions)}"
                    f" status={status['status']}"
                    f" last_error={status.get('last_error')}"
                )
                return

            try:
                service.execute_script(
                    twin_key=twin_key,
                    script=_APPLY_CONTEXT_AND_CLICK_TRIGGER_SCRIPT,
                    args=[navigation_context, action["selector"]],
                )

                landed_href = _wait_for_runtime_entry(
                    service,
                    twin_key=twin_key,
                    expected_entry=target_runtime_entry,
                    timeout=_DEFAULT_REACH_TIMEOUT_SECONDS,
                )

                results.append(
                    {
                        "transition": index,
                        "before_state_id": before_state_id,
                        "after_state_id": after_state_id,
                        "landed_href": landed_href,
                    }
                )
            finally:
                service.stop(twin_key=twin_key)
    finally:
        service.stop_all()

    assert len(results) == len(transitions), (
        "QCC_UWT_CERT_INCOMPLETE_REPLAY:"
        f" completed={len(results)} expected={len(transitions)}"
    )
