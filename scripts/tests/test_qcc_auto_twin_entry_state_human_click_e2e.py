"""Governed SeleniumBase human-click E2E for entry-state coverage.

QCC_AUTO_TWIN_R5D_ENTRY_NAVIGATION_HUMAN_CLICK_E2E_V1

Reproduces the Mercurio entry-state defect generically, with a fully
synthetic, self-contained fixture (no Mercurio references, no fixed
state IDs beyond this test's own fixture, no site-specific JavaScript):

a TWIN entry state and a sibling physical capture share the exact same
governed Twin identity; only the sibling carries a directly-observed
causal click. QCC_AUTO_TWIN_SEMANTIC_SOURCE_MIRROR_V1
(navigation_transition_runtime.build_navigation_runtime_payload)
mirrors that sibling's outgoing route onto the entry state, and this
test drives a REAL governed SeleniumBase browser to perform a normal,
human-equivalent click on the entry state's visible Continue control
(located by its visible text, never by reading the governed selector)
and asserts the browser reaches the exact local target_runtime_entry.

Never calls the transition replay helper and never invokes target
navigation directly -- only a real DOM click via the SAME generic
capture-phase adapter production installs
(inject_navigation_runtime_adapter).
"""

from __future__ import annotations

import json
import time

import pytest

from backend.qcc.auto_twin.navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    project_twin_eligible_navigation_candidates,
)
from backend.qcc.auto_twin.navigation_transition_runtime import (
    build_navigation_runtime_payload,
    inject_navigation_runtime_adapter,
    outgoing_navigation_transitions,
)
from backend.services.twin_browser_runtime_service import (
    TwinBrowserRuntimeService,
)


TWIN_KEY = "qcce2e"
REVISION_ID = "rev1"

STATE_ENTRY = "STATE-ENTRY"
STATE_REVISIT = "STATE-REVISIT"
STATE_TARGET = "STATE-TARGET"

FP_ENTRY = "1" * 64
FP_REVISIT = "2" * 64
FP_TARGET = "3" * 64

CONTINUE_SELECTOR = 'a[onclick="continuar();"]'

_REACH_TIMEOUT_SECONDS = 15.0
_POLL_INTERVAL_SECONDS = 0.2


def _page_html(*, title, body):
    return (
        "<!doctype html>\n"
        "<html><head><title>"
        + title
        + "</title></head><body>\n"
        + body
        + "\n</body></html>\n"
    )


def _write_state(
    revision_dir,
    *,
    ordinal,
    state_id,
    html,
):
    state_dir = revision_dir / "states" / f"{ordinal}-{state_id}"
    runtime_dir = state_dir / "runtime"
    runtime_dir.mkdir(parents=True)

    (runtime_dir / "index.html").write_text(html, encoding="utf-8")

    return f"states/{ordinal}-{state_id}/runtime/index.html"


def _build_fixture(tmp_path):
    materialized_root = tmp_path / "materialized"
    revision_dir = materialized_root / TWIN_KEY / REVISION_ID
    revision_dir.mkdir(parents=True)

    entry_runtime_entry = _write_state(
        revision_dir,
        ordinal="01",
        state_id=STATE_ENTRY,
        html=_page_html(
            title="Entry",
            body=(
                '<a href="#" onclick="continuar();" '
                'class="btn-continue">Continuar</a>'
            ),
        ),
    )

    revisit_runtime_entry = _write_state(
        revision_dir,
        ordinal="02",
        state_id=STATE_REVISIT,
        html=_page_html(
            title="Entry revisit",
            body=(
                '<a href="#" onclick="continuar();" '
                'class="btn-continue">Continuar</a>'
            ),
        ),
    )

    target_runtime_entry = _write_state(
        revision_dir,
        ordinal="03",
        state_id=STATE_TARGET,
        html=_page_html(
            title="Target",
            body="<p>Arrived</p>",
        ),
    )

    runtime_states = [
        {
            "state_id": STATE_ENTRY,
            "fingerprint": FP_ENTRY,
            "runtime_entry": entry_runtime_entry,
            "pathname": "/app/start.html",
            "functional_state": "APP_START",
        },
        {
            "state_id": STATE_REVISIT,
            "fingerprint": FP_REVISIT,
            "runtime_entry": revisit_runtime_entry,
            "pathname": "/app/start.html",
            "functional_state": "APP_START",
        },
        {
            "state_id": STATE_TARGET,
            "fingerprint": FP_TARGET,
            "runtime_entry": target_runtime_entry,
            "pathname": "/app/next.html",
            "functional_state": None,
        },
    ]

    candidate = {
        "candidate_id": "cand-revisit-continuar",
        "evidence_source": AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
        "before_fingerprint": FP_REVISIT,
        "after_fingerprint": FP_TARGET,
        "action": {
            "kind": "LINK",
            "policy": "NAVIGATION_CANDIDATE",
            "selector": CONTINUE_SELECTOR,
            "frame_path": "main",
        },
        "navigation_context": [],
        "observation_count": 1,
        "status": "CONFIRMED",
    }

    transitions = project_twin_eligible_navigation_candidates(
        {"candidates": [candidate]}
    )

    payload = build_navigation_runtime_payload(
        transitions,
        runtime_states,
    )

    (revision_dir / "runtime").mkdir(exist_ok=True)

    (revision_dir / "runtime" / "index.html").write_text(
        _page_html(title="Revision root", body="<p>root</p>"),
        encoding="utf-8",
    )

    (revision_dir / "runtime" / "registry.json").write_text(
        json.dumps({"states": runtime_states}),
        encoding="utf-8",
    )

    (revision_dir / "runtime" / "navigation_transitions.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    # Mirrors materialization_builder.py's own second pass: install the
    # generic capture-phase navigation adapter for every physical
    # runtime state using exactly its OWN governed outgoing routes.
    for state in runtime_states:
        state_id = state["state_id"]
        outgoing = outgoing_navigation_transitions(payload, state_id)

        html_path = revision_dir / state["runtime_entry"]

        local_html = inject_navigation_runtime_adapter(
            html_path.read_text(encoding="utf-8"),
            state_id=state_id,
            transitions=outgoing,
        )

        html_path.write_text(local_html, encoding="utf-8")

    entry_outgoing = outgoing_navigation_transitions(payload, STATE_ENTRY)

    assert len(entry_outgoing) == 1
    assert (
        entry_outgoing[0]["interactive_execution_mode"]
        == "SEMANTIC_SOURCE_MIRROR"
    )

    return (
        materialized_root,
        entry_outgoing[0]["target_runtime_entry"],
    )


_CLICK_VISIBLE_CONTINUE_SCRIPT = r"""
var links = Array.from(document.querySelectorAll("a"));
var target = links.find(
    (node) => (node.textContent || "").trim() === "Continuar"
);

if (!target) {
    throw new Error("QCC_E2E_VISIBLE_CONTINUE_CONTROL_NOT_FOUND");
}

target.click();
return true;
"""


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
        "QCC_E2E_TARGET_NOT_REACHED:"
        + f" expected_entry={expected_entry}"
        + f" last_href={last_href}"
        + f" last_error={last_error}"
    )


def test_entry_state_human_click_reaches_mirrored_local_target(tmp_path):
    materialized_root, expected_target_entry = _build_fixture(tmp_path)

    service = TwinBrowserRuntimeService(
        materialized_root=materialized_root,
    )

    try:
        try:
            status = service.start(
                twin_key=TWIN_KEY,
                revision_id=REVISION_ID,
                state_id=STATE_ENTRY,
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed to BLOCKED
            pytest.skip(
                "SELENIUMBASE_E2E_BLOCKED:"
                f" start_failed={type(exc).__name__}: {exc}"
            )
            return

        if status["status"] != "RUNNING":
            pytest.skip(
                "SELENIUMBASE_E2E_BLOCKED:"
                f" status={status['status']}"
                f" last_error={status.get('last_error')}"
            )
            return

        entry_before = service.execute_script(
            twin_key=TWIN_KEY,
            script="return window.location.href;",
        )

        entry_host = service.execute_script(
            twin_key=TWIN_KEY,
            script="return window.location.hostname;",
        )

        assert entry_host in ("localhost", "127.0.0.1")

        # Human-equivalent click: located by the control's VISIBLE
        # text, never by reading the governed action.selector out of
        # navigation_transitions.json (that would be the replay
        # helper's job, not a human's).
        service.execute_script(
            twin_key=TWIN_KEY,
            script=_CLICK_VISIBLE_CONTINUE_SCRIPT,
        )

        entry_after = _wait_for_runtime_entry(
            service,
            twin_key=TWIN_KEY,
            expected_entry=expected_target_entry,
            timeout=_REACH_TIMEOUT_SECONDS,
        )

        after_host = service.execute_script(
            twin_key=TWIN_KEY,
            script="return window.location.hostname;",
        )

        assert after_host in ("localhost", "127.0.0.1")

        print(
            "HUMAN_CLICK_ENTRY_E2E=PASS"
            f" ENTRY_BEFORE={entry_before}"
            f" ENTRY_AFTER={entry_after}"
            f" EXPECTED_LOCAL_TARGET={expected_target_entry}"
            f" ACTUAL_LOCAL_TARGET={entry_after}"
            " REAL_NETWORK_ESCAPE=NO"
        )
    finally:
        service.stop_all()
