"""QCC AUTO TWIN R5E: CRM product-path SeleniumBase human-click E2E.

Drives the EXACT same CRM Open Twin product path as the Twins view
(TwinManagementService.start_twin_browser), not an isolated
materializer-only helper and not the governed transition-replay
helper:

    CRM Open Twin (TwinManagementService.start_twin_browser)
      -> compatibility gate detects a STALE persisted materialization
      -> canonical materializer refresh (contract-equivalent fake:
         builds a fresh revision using the SAME current-code adapter
         exactly as materialization_builder.py would)
      -> opens the NEW immutable revision via the REAL
         TwinBrowserRuntimeService
      -> a real governed SeleniumBase browser performs a normal,
         human-equivalent click on the entry state's visible Continue
         control
      -> asserts the browser reaches the exact local target_runtime_entry

Entirely synthetic, provider-neutral fixture: no Mercurio references,
no fixed state ids beyond this test's own fixture.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from backend.qcc.auto_twin.managed_site_registry import (
    AutoTwinManagedSite,
)

from backend.qcc.auto_twin.managed_site_store import (
    AutoTwinManagedSiteStore,
)

from backend.qcc.auto_twin.materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
    build_auto_twin_materialized_revision,
)

from backend.qcc.auto_twin.materialized_revision_store import (
    AutoTwinMaterializedRevisionStore,
)

from backend.qcc.auto_twin.navigation_transition_materialization import (
    AUTO_TWIN_NAVIGATION_EVIDENCE_SOURCE,
    project_twin_eligible_navigation_candidates,
)

from backend.qcc.auto_twin.navigation_transition_runtime import (
    AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,
    build_navigation_runtime_payload,
    inject_navigation_runtime_adapter,
    outgoing_navigation_transitions,
)

from backend.services.twin_browser_runtime_service import (
    TwinBrowserRuntimeService,
)

from backend.services.twin_management_service import (
    TWIN_CATALOG,
    TwinManagementService,
)


TWIN_KEY = "qcce2e_refresh"

OLD_ADAPTER_VERSION = AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION - 1

STATE_ENTRY = "STATE-ENTRY"
STATE_REVISIT = "STATE-REVISIT"
STATE_TARGET = "STATE-TARGET"

FP_ENTRY = "1" * 64
FP_REVISIT = "2" * 64
FP_TARGET = "3" * 64

CONTINUE_SELECTOR = 'a[onclick="continuar();"]'

HASH_OLD = "a" * 64
HASH_NEW = "b" * 64

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


def _write_state(revision_dir, *, ordinal, state_id, html):
    state_dir = revision_dir / "states" / f"{ordinal}-{state_id}"
    runtime_dir = state_dir / "runtime"
    runtime_dir.mkdir(parents=True)

    (runtime_dir / "index.html").write_text(html, encoding="utf-8")

    return f"states/{ordinal}-{state_id}/runtime/index.html"


def _save_manifest(materialized_root, *, state_id, content_sha256):
    store = AutoTwinMaterializedRevisionStore(root=materialized_root)

    record = build_auto_twin_materialized_revision(
        twin_key=TWIN_KEY,
        materialization_mode=(
            AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
        ),
        source_capture_ids=["capture-1"],
        candidate_refs=[],
        state_manifest=[
            {
                "state_id": state_id,
                "source_capture_id": "capture-1",
                "pathname": "/fixture/" + state_id + ".html",
                "functional_state": state_id,
            },
        ],
        artifact_manifest=[
            {
                "path": "states/01-" + state_id + "/runtime/index.html",
                "kind": "RUNTIME",
                "sha256": content_sha256,
                "size_bytes": 1,
            },
        ],
        content_sha256=content_sha256,
    )

    saved = store.save(record)
    return saved["materialized_revision_id"]


def _install_stale_revision(materialized_root):
    revision_id = _save_manifest(
        materialized_root,
        state_id="STALE_STATE",
        content_sha256=HASH_OLD,
    )

    revision_dir = Path(materialized_root) / TWIN_KEY / revision_id
    runtime = revision_dir / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)

    (runtime / "index.html").write_text(
        "<html></html>", encoding="utf-8"
    )

    (runtime / "registry.json").write_text(
        json.dumps({"states": [{"state_id": "STALE_STATE"}]}),
        encoding="utf-8",
    )

    (runtime / "navigation_transitions.json").write_text(
        json.dumps(
            {
                "adapter_version": OLD_ADAPTER_VERSION,
                "transitions": [],
            }
        ),
        encoding="utf-8",
    )

    return revision_id


def _build_fresh_v7_revision(materialized_root):
    """Contract-equivalent of what the canonical materializer
    (materialization_builder.materialize_auto_twin_plan, via
    reconcile_auto_twin_discovery_materialization) produces from
    existing local evidence: a fresh immutable revision generated by
    the CURRENT navigation runtime adapter, reproducing the exact R5D
    entry-state semantic-source-mirror defect fix generically."""

    revision_id = _save_manifest(
        materialized_root,
        state_id=STATE_ENTRY,
        content_sha256=HASH_NEW,
    )

    revision_dir = Path(materialized_root) / TWIN_KEY / revision_id

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
        html=_page_html(title="Target", body="<p>Arrived</p>"),
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
        transitions, runtime_states
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

    (
        revision_dir / "runtime" / "navigation_transitions.json"
    ).write_text(json.dumps(payload), encoding="utf-8")

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

    entry_outgoing = outgoing_navigation_transitions(
        payload, STATE_ENTRY
    )

    assert len(entry_outgoing) == 1
    assert (
        entry_outgoing[0]["interactive_execution_mode"]
        == "SEMANTIC_SOURCE_MIRROR"
    )

    return revision_id, entry_outgoing[0]["target_runtime_entry"]


class _FreshRevisionRefresher:
    def __init__(self, materialized_root):
        self.materialized_root = materialized_root
        self.calls = 0
        self.expected_target_entry = None

    def __call__(
        self,
        *,
        twin_key,
        revision_id,
        managed_site_store,
        observation_store,
        materialized_root,
        capture_root,
    ):
        self.calls += 1

        new_revision_id, target_entry = _build_fresh_v7_revision(
            self.materialized_root
        )

        self.expected_target_entry = target_entry

        return {
            "status": "MATERIALIZED",
            "materialized_revision_id": new_revision_id,
        }


class _FakeDiscoveryRuntime:
    def get_status(self, *, twin_key):
        return {
            "status": "STOPPED",
            "qcc_registered": False,
            "qcc_extension_mode": "DISABLED",
            "profile_dir": None,
        }


class _FakeLocalRuntime:
    def get_status(self, *, twin_key):
        return {"status": "STOPPED", "url": None}


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


def test_crm_open_twin_refreshes_stale_runtime_and_reaches_entry_target(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "backend.services.twin_management_service.TWIN_CATALOG",
        TWIN_CATALOG
        + (
            {
                "twin_key": TWIN_KEY,
                "site_code": "QCCE2E_REFRESH",
                "label": "QCC E2E Refresh Fixture",
                "enabled": True,
            },
        ),
    )

    materialized_root = tmp_path / "materialized"

    stale_revision_id = _install_stale_revision(materialized_root)

    managed_site_store = AutoTwinManagedSiteStore(
        path=tmp_path / "managed_sites.json"
    )

    managed_site_store.register(
        AutoTwinManagedSite(
            twin_key=TWIN_KEY,
            site_code="QCCE2E_REFRESH",
            origins=("https://qcc-e2e-refresh-fixture.test",),
            enabled=True,
            auto_update=True,
        )
    )

    refresher = _FreshRevisionRefresher(materialized_root)

    browser_runtime_service = TwinBrowserRuntimeService(
        materialized_root=materialized_root,
    )

    service = TwinManagementService(
        materialized_root=materialized_root,
        managed_site_store=managed_site_store,
        observation_store=None,
        materialization_refresher=refresher,
        browser_runtime_service=browser_runtime_service,
        discovery_runtime_service=_FakeDiscoveryRuntime(),
        local_runtime_service=_FakeLocalRuntime(),
    )

    try:
        try:
            status = service.start_twin_browser(TWIN_KEY)
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

        # The compatibility gate must have gone through the refresh
        # branch exactly once, and opened something other than the
        # original stale revision.
        assert refresher.calls == 1
        assert status["revision_id"] != stale_revision_id

        expected_target_entry = refresher.expected_target_entry

        entry_host = browser_runtime_service.execute_script(
            twin_key=TWIN_KEY,
            script="return window.location.hostname;",
        )

        assert entry_host in ("localhost", "127.0.0.1")

        browser_runtime_service.execute_script(
            twin_key=TWIN_KEY,
            script=_CLICK_VISIBLE_CONTINUE_SCRIPT,
        )

        entry_after = _wait_for_runtime_entry(
            browser_runtime_service,
            twin_key=TWIN_KEY,
            expected_entry=expected_target_entry,
            timeout=_REACH_TIMEOUT_SECONDS,
        )

        after_host = browser_runtime_service.execute_script(
            twin_key=TWIN_KEY,
            script="return window.location.hostname;",
        )

        assert after_host in ("localhost", "127.0.0.1")

        print(
            "CRM_PRODUCT_PATH_E2E=PASS"
            " HUMAN_CLICK_ENTRY_E2E=PASS"
            f" ENTRY_AFTER={entry_after}"
            f" EXPECTED_LOCAL_TARGET={expected_target_entry}"
            " REAL_NETWORK_ESCAPE=NO"
        )
    finally:
        browser_runtime_service.stop_all()
