"""Local rematerialization + governed SeleniumBase E2E for backfill.

QCC_AUTO_TWIN_R5F_PRIMARY_CLICK_TEACHING

Exercises the FULL local pipeline required by work-order section 14,
using ONLY TEMP/tmp_path fixtures (no REAL, no Box, no network escape
beyond localhost):

1. register a human-confirmed primary click through the canonical
   service (``register_human_confirmed_transition``);
2. project the resulting CONFIRMED candidate into a fresh navigation
   runtime payload (``project_twin_eligible_navigation_candidates`` +
   ``build_navigation_runtime_payload`` -- never a hand-edited
   navigation_transitions.json, never a mutated existing revision);
3. confirm the generated navigation graph contains the new transition
   (NEW_TRANSITION_PRESENT);
4. run a governed local SeleniumBase browser (TwinBrowserRuntimeService)
   against that fresh local revision and click the visible
   modal-close-like control NORMALLY (never by invoking replay/the
   action.selector programmatically -- located by its visible text,
   same convention as the R5D entry-state E2E);
5. verify the local target state is reached, on localhost only.

The fixture is intentionally Mercurio-SHAPED (mirrors the regression
evidence in the work order: a DOM modal with a "Cerrar" close button)
but is entirely self-contained and synthetic. Production code contains
none of these literals -- see
test_human_confirmed_backfill_module_has_no_mercurio_literals in
test_qcc_human_confirmed_backfill.py.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

from backend.qcc.auto_twin.navigation_transition_materialization import (
    project_twin_eligible_navigation_candidates,
)
from backend.qcc.auto_twin.navigation_transition_runtime import (
    build_navigation_runtime_payload,
    outgoing_navigation_transitions,
)
from backend.qcc.context.human_confirmed_backfill import (
    register_human_confirmed_transition,
)
from backend.qcc.navigation_knowledge.store import NavigationKnowledgeStore
from backend.qcc.navigation_learning.human_candidate_store import (
    HumanNavigationCandidateStore,
)
from backend.services.twin_browser_runtime_service import (
    TwinBrowserRuntimeService,
)


TWIN_KEY = "qccbackfille2e"
REVISION_ID = "rev1"

SITE_CODE = "MERCURIOFIXTURE"
ENVIRONMENT = "TEST"

STATE_MODAL = "STATE-MODAL-OPEN"
STATE_TARGET = "STATE-ENTRY-SELECTION"

FP_MODAL = "1" * 64
FP_TARGET = "2" * 64

# Mirrors the captured REAL DOM shape from the work order (regression
# evidence only): a dialog with a "Cerrar" close button whose actual
# interactive surface is the <button>, not its child <span> icon.
CLOSE_BUTTON_SELECTOR = 'button.mdCer[title="Cerrar la ventana"]'

ACTION_OBSERVED_AT = datetime(2026, 10, 8, 19, 11, 16, tzinfo=timezone.utc)
AFTER_OBSERVED_AT = datetime(2026, 10, 8, 19, 11, 26, tzinfo=timezone.utc)

_REACH_TIMEOUT_SECONDS = 15.0
_POLL_INTERVAL_SECONDS = 0.2


def _page_html(*, title, body):
    return (
        "<!doctype html>\n"
        "<html><head><title>" + title + "</title></head><body>\n"
        + body
        + "\n</body></html>\n"
    )


def _write_state(revision_dir, *, ordinal, state_id, html):
    state_dir = revision_dir / "states" / f"{ordinal}-{state_id}"
    runtime_dir = state_dir / "runtime"
    runtime_dir.mkdir(parents=True)

    (runtime_dir / "index.html").write_text(html, encoding="utf-8")

    return f"states/{ordinal}-{state_id}/runtime/index.html"


def _register_confirmed_transition(tmp_path):
    candidate_store = HumanNavigationCandidateStore(
        root=tmp_path / "navigation_learning"
    )

    knowledge_store = NavigationKnowledgeStore(
        root=tmp_path / "navigation_knowledge"
    )

    result = register_human_confirmed_transition(
        candidate_store,
        knowledge_store,
        site_code=SITE_CODE,
        environment=ENVIRONMENT,
        before_state=STATE_MODAL,
        before_fingerprint=FP_MODAL,
        action_kind="BUTTON",
        action_selector=CLOSE_BUTTON_SELECTOR,
        action_frame_path="main",
        after_state=STATE_TARGET,
        after_fingerprint=FP_TARGET,
        action_observed_at=ACTION_OBSERVED_AT,
        after_observed_at=AFTER_OBSERVED_AT,
        confirmed_by="qa-operator@example.test",
    )

    assert result["candidate_status"] == "CONFIRMED"

    snapshot = candidate_store.snapshot(SITE_CODE, environment=ENVIRONMENT)

    return result, snapshot


def _build_fixture(tmp_path):
    _result, snapshot = _register_confirmed_transition(tmp_path)

    materialized_root = tmp_path / "materialized"
    revision_dir = materialized_root / TWIN_KEY / REVISION_ID
    revision_dir.mkdir(parents=True)

    modal_runtime_entry = _write_state(
        revision_dir,
        ordinal="01",
        state_id=STATE_MODAL,
        html=_page_html(
            title="Modal open",
            body=(
                '<div id="dialog" class="mf-dialog open_in_dialog">\n'
                '  <button class="mdCer" title="Cerrar la ventana">\n'
                '    <span class="icon"></span>\n'
                "    Cerrar\n"
                "  </button>\n"
                "</div>\n"
                "<script>\n"
                'document.querySelector("button.mdCer")'
                ".addEventListener(\"click\", function () {\n"
                '  window.location.href = "/states/02-'
                + STATE_TARGET
                + '/runtime/index.html";\n'
                "});\n"
                "</script>\n"
            ),
        ),
    )

    target_runtime_entry = _write_state(
        revision_dir,
        ordinal="02",
        state_id=STATE_TARGET,
        html=_page_html(title="Entry selection", body="<p>Arrived</p>"),
    )

    runtime_states = [
        {
            "state_id": STATE_MODAL,
            "fingerprint": FP_MODAL,
            "runtime_entry": modal_runtime_entry,
            "pathname": "/app/modal.html",
            "functional_state": "MODAL_OPEN",
        },
        {
            "state_id": STATE_TARGET,
            "fingerprint": FP_TARGET,
            "runtime_entry": target_runtime_entry,
            "pathname": "/app/entry-selection.html",
            "functional_state": "ENTRY_SELECTION",
        },
    ]

    # ---------------------------------------------------------------
    # FRESH MATERIALIZATION.
    #
    # The CONFIRMED candidate -- registered through the SAME canonical
    # service live teaching uses -- is projected via the governed
    # builder functions, never by hand-editing JSON and never by
    # mutating an existing revision.
    # ---------------------------------------------------------------
    transitions = project_twin_eligible_navigation_candidates(snapshot)

    payload = build_navigation_runtime_payload(transitions, runtime_states)

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

    modal_outgoing = outgoing_navigation_transitions(payload, STATE_MODAL)

    assert len(modal_outgoing) == 1
    assert modal_outgoing[0]["after_state_id"] == STATE_TARGET

    return materialized_root, modal_outgoing[0]["target_runtime_entry"]


_CLICK_VISIBLE_CLOSE_SCRIPT = r"""
var buttons = Array.from(document.querySelectorAll("button"));
var target = buttons.find(
    (node) => (node.textContent || "").trim() === "Cerrar"
);

if (!target) {
    throw new Error("QCC_E2E_VISIBLE_CLOSE_CONTROL_NOT_FOUND");
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


def test_human_confirmed_backfill_reaches_fresh_local_target(tmp_path):
    materialized_root, expected_target_entry = _build_fixture(tmp_path)

    service = TwinBrowserRuntimeService(materialized_root=materialized_root)

    try:
        try:
            status = service.start(
                twin_key=TWIN_KEY,
                revision_id=REVISION_ID,
                state_id=STATE_MODAL,
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

        before_host = service.execute_script(
            twin_key=TWIN_KEY,
            script="return window.location.hostname;",
        )

        assert before_host in ("localhost", "127.0.0.1")

        # Human-equivalent click located by VISIBLE text, never by
        # reading action.selector out of navigation_transitions.json.
        service.execute_script(
            twin_key=TWIN_KEY,
            script=_CLICK_VISIBLE_CLOSE_SCRIPT,
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
            "HUMAN_CONFIRMED_BACKFILL_E2E=PASS"
            f" ENTRY_BEFORE={entry_before}"
            f" ENTRY_AFTER={entry_after}"
            f" EXPECTED_LOCAL_TARGET={expected_target_entry}"
            " REAL_NETWORK_ESCAPE=NO"
        )
    finally:
        service.stop_all()
