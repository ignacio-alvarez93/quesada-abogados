"""QCC AUTO TWIN R5E: runtime materialization compatibility + auto refresh.

Covers the CRM Open Twin product path
(TwinManagementService.start_twin_browser), not an isolated
materializer-only helper:

    Open Twin
      -> compatibility gate (materialization_compatibility.py)
      -> compatible: open as-is
      -> stale + managed auto_update: canonical materializer refresh,
         then open the NEW immutable revision
      -> stale + auto_update False: fail closed

The fixture twin ("qcce2e") is entirely synthetic and provider-neutral:
no Mercurio references, no fixed matrev ids, no hardcoded transition
counts.
"""

from __future__ import annotations

import json
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

from backend.qcc.auto_twin.navigation_transition_runtime import (
    AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,
)

from backend.qcc.auto_twin.materialization_compatibility import (
    AUTO_TWIN_MATERIALIZATION_COMPATIBLE,
    AUTO_TWIN_MATERIALIZATION_INCOMPATIBLE,
    AUTO_TWIN_MATERIALIZATION_STALE_REGENERATABLE,
    evaluate_materialized_revision_compatibility,
)

from backend.services.twin_management_service import (
    TWIN_CATALOG,
    TwinManagementService,
)


TWIN_KEY = "qcce2e"

HASH_OLD = "a" * 64
HASH_NEW = "b" * 64

OLD_ADAPTER_VERSION = AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION - 1
FUTURE_ADAPTER_VERSION = AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION + 1


def _enable_fixture_twin(monkeypatch):
    """TWIN_KEY is not part of the real TWIN_CATALOG; register it for
    the duration of a single test without touching production data."""

    monkeypatch.setattr(
        "backend.services.twin_management_service.TWIN_CATALOG",
        TWIN_CATALOG
        + (
            {
                "twin_key": TWIN_KEY,
                "site_code": "QCCE2E",
                "label": "QCC E2E Fixture",
                "enabled": True,
            },
        ),
    )


def _install_revision(
    root,
    *,
    adapter_version,
    content_sha256,
    state_id="FIXTURE_STATE",
):
    store = AutoTwinMaterializedRevisionStore(
        root=root
    )

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

    revision_id = saved["materialized_revision_id"]
    revision_dir = Path(root) / TWIN_KEY / revision_id
    runtime = revision_dir / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)

    (runtime / "index.html").write_text(
        "<html></html>", encoding="utf-8"
    )

    (runtime / "registry.json").write_text(
        json.dumps({"states": [{"state_id": state_id}]}),
        encoding="utf-8",
    )

    if adapter_version is not None:
        (runtime / "navigation_transitions.json").write_text(
            json.dumps(
                {
                    "adapter_version": adapter_version,
                    "transitions": [],
                }
            ),
            encoding="utf-8",
        )

    return revision_id


class _RecordingRefresher:
    """Stands in for the canonical materializer's CONTRACT only:
    stale-in, new-immutable-compatible-revision-out. The real wiring
    (refresh_stale_twin_materialization ->
    reconcile_auto_twin_discovery_materialization) is exercised by its
    own existing automatic_materialization.py coverage; this test
    suite's job is TwinManagementService's own gating/orchestration."""

    def __init__(self, materialized_root):
        self.materialized_root = materialized_root
        self.calls = []

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
        self.calls.append(
            {
                "twin_key": twin_key,
                "revision_id": revision_id,
            }
        )

        new_revision_id = _install_revision(
            self.materialized_root,
            adapter_version=(
                AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION
            ),
            content_sha256=HASH_NEW,
            state_id="FIXTURE_STATE_REFRESHED",
        )

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

    def start(self, *, twin_key, revision_id):
        return {"status": "RUNNING", "url": "http://127.0.0.1:0/"}

    def stop(self, *, twin_key):
        return {"status": "STOPPED"}


class _FakeBrowserRuntime:
    def __init__(self):
        self.starts = []

    def get_status(self, *, twin_key):
        return {
            "status": "STOPPED",
            "url": None,
            "profile_key": None,
            "profile_dir": None,
            "browser_session_mode": "PERSISTENT",
            "qcc_registered": False,
            "owner_thread_alive": False,
            "last_error": None,
        }

    def start(self, *, twin_key, revision_id, pathname=None):
        self.starts.append(
            {
                "twin_key": twin_key,
                "revision_id": revision_id,
                "pathname": pathname,
            }
        )

        return {
            "status": "RUNNING",
            "revision_id": revision_id,
        }


def _managed_site(*, auto_update):
    return AutoTwinManagedSite(
        twin_key=TWIN_KEY,
        site_code="QCCE2E",
        origins=("https://qcc-e2e-fixture.test",),
        enabled=True,
        auto_update=auto_update,
    )


def _service(
    tmp_path,
    *,
    managed_site_store=None,
    refresher=None,
    browser=None,
):
    return TwinManagementService(
        materialized_root=tmp_path,
        managed_site_store=(
            managed_site_store
            or AutoTwinManagedSiteStore(
                path=tmp_path / "managed_sites.json"
            )
        ),
        observation_store=None,
        materialization_refresher=refresher,
        browser_runtime_service=(
            browser
            or _FakeBrowserRuntime()
        ),
        discovery_runtime_service=_FakeDiscoveryRuntime(),
        local_runtime_service=_FakeLocalRuntime(),
    )


# ---------------------------------------------------------------------
# A. COMPATIBLE REVISION -> reused, no rematerialization.
# ---------------------------------------------------------------------

def test_compatible_revision_opens_unchanged_without_refresh(
    tmp_path, monkeypatch
):
    _enable_fixture_twin(monkeypatch)

    revision_id = _install_revision(
        tmp_path,
        adapter_version=AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,
        content_sha256=HASH_OLD,
    )

    refresher = _RecordingRefresher(tmp_path)
    browser = _FakeBrowserRuntime()

    service = _service(
        tmp_path, refresher=refresher, browser=browser
    )

    result = service.start_twin_browser(TWIN_KEY)

    assert result["status"] == "RUNNING"
    assert browser.starts == [
        {
            "twin_key": TWIN_KEY,
            "revision_id": revision_id,
            "pathname": None,
        }
    ]
    assert refresher.calls == []


# ---------------------------------------------------------------------
# B. STALE + AUTO UPDATE -> canonical materializer invoked once, new
#    immutable revision selected/opened.
# ---------------------------------------------------------------------

def test_stale_revision_with_auto_update_regenerates_once(
    tmp_path, monkeypatch
):
    _enable_fixture_twin(monkeypatch)

    old_revision_id = _install_revision(
        tmp_path,
        adapter_version=OLD_ADAPTER_VERSION,
        content_sha256=HASH_OLD,
    )

    managed_site_store = AutoTwinManagedSiteStore(
        path=tmp_path / "managed_sites.json"
    )
    managed_site_store.register(_managed_site(auto_update=True))

    refresher = _RecordingRefresher(tmp_path)
    browser = _FakeBrowserRuntime()

    service = _service(
        tmp_path,
        managed_site_store=managed_site_store,
        refresher=refresher,
        browser=browser,
    )

    result = service.start_twin_browser(TWIN_KEY)

    assert result["status"] == "RUNNING"
    assert len(refresher.calls) == 1
    assert refresher.calls[0]["revision_id"] == old_revision_id

    opened_revision_id = browser.starts[0]["revision_id"]
    assert opened_revision_id != old_revision_id

    decision = evaluate_materialized_revision_compatibility(
        materialized_root=tmp_path,
        twin_key=TWIN_KEY,
        revision_id=opened_revision_id,
    )
    assert decision == AUTO_TWIN_MATERIALIZATION_COMPATIBLE


# ---------------------------------------------------------------------
# C. IMMUTABILITY -> the old materialized revision's own files are
#    never mutated by the refresh.
# ---------------------------------------------------------------------

def test_stale_refresh_never_mutates_old_revision(tmp_path, monkeypatch):
    _enable_fixture_twin(monkeypatch)

    old_revision_id = _install_revision(
        tmp_path,
        adapter_version=OLD_ADAPTER_VERSION,
        content_sha256=HASH_OLD,
    )

    old_revision_dir = Path(tmp_path) / TWIN_KEY / old_revision_id

    before = {
        path.relative_to(old_revision_dir): path.read_bytes()
        for path in sorted(old_revision_dir.rglob("*"))
        if path.is_file()
    }

    managed_site_store = AutoTwinManagedSiteStore(
        path=tmp_path / "managed_sites.json"
    )
    managed_site_store.register(_managed_site(auto_update=True))

    service = _service(
        tmp_path,
        managed_site_store=managed_site_store,
        refresher=_RecordingRefresher(tmp_path),
    )

    service.start_twin_browser(TWIN_KEY)

    after = {
        path.relative_to(old_revision_dir): path.read_bytes()
        for path in sorted(old_revision_dir.rglob("*"))
        if path.is_file()
    }

    assert before == after


# ---------------------------------------------------------------------
# D. IDEMPOTENCY -> second open reuses the newly-compatible revision,
#    no second materialization.
# ---------------------------------------------------------------------

def test_second_open_reuses_refreshed_revision_without_remateralizing(
    tmp_path, monkeypatch
):
    _enable_fixture_twin(monkeypatch)

    _install_revision(
        tmp_path,
        adapter_version=OLD_ADAPTER_VERSION,
        content_sha256=HASH_OLD,
    )

    managed_site_store = AutoTwinManagedSiteStore(
        path=tmp_path / "managed_sites.json"
    )
    managed_site_store.register(_managed_site(auto_update=True))

    refresher = _RecordingRefresher(tmp_path)
    browser = _FakeBrowserRuntime()

    service = _service(
        tmp_path,
        managed_site_store=managed_site_store,
        refresher=refresher,
        browser=browser,
    )

    first = service.start_twin_browser(TWIN_KEY)
    second = service.start_twin_browser(TWIN_KEY)

    assert first["status"] == "RUNNING"
    assert second["status"] == "RUNNING"

    # Exactly one regeneration across both opens.
    assert len(refresher.calls) == 1

    assert (
        browser.starts[0]["revision_id"]
        == browser.starts[1]["revision_id"]
    )


# ---------------------------------------------------------------------
# E. AUTO_UPDATE FALSE -> stale revision not rematerialized, explicit
#    controlled failure.
# ---------------------------------------------------------------------

def test_stale_revision_with_auto_update_false_fails_closed(
    tmp_path, monkeypatch
):
    _enable_fixture_twin(monkeypatch)

    old_revision_id = _install_revision(
        tmp_path,
        adapter_version=OLD_ADAPTER_VERSION,
        content_sha256=HASH_OLD,
    )

    managed_site_store = AutoTwinManagedSiteStore(
        path=tmp_path / "managed_sites.json"
    )
    managed_site_store.register(_managed_site(auto_update=False))

    refresher = _RecordingRefresher(tmp_path)
    browser = _FakeBrowserRuntime()

    service = _service(
        tmp_path,
        managed_site_store=managed_site_store,
        refresher=refresher,
        browser=browser,
    )

    with pytest.raises(RuntimeError) as excinfo:
        service.start_twin_browser(TWIN_KEY)

    assert "STALE" in str(excinfo.value)
    assert refresher.calls == []
    assert browser.starts == []

    old_revision_dir = Path(tmp_path) / TWIN_KEY / old_revision_id
    assert old_revision_dir.is_dir()


def test_unmanaged_stale_twin_fails_closed_without_refresh(
    tmp_path, monkeypatch
):
    """No managed-site record at all is treated the same as
    auto_update=False: never silently regenerate, never silently open
    a stale runtime."""

    _enable_fixture_twin(monkeypatch)

    _install_revision(
        tmp_path,
        adapter_version=OLD_ADAPTER_VERSION,
        content_sha256=HASH_OLD,
    )

    refresher = _RecordingRefresher(tmp_path)
    browser = _FakeBrowserRuntime()

    service = _service(
        tmp_path, refresher=refresher, browser=browser
    )

    with pytest.raises(RuntimeError):
        service.start_twin_browser(TWIN_KEY)

    assert refresher.calls == []
    assert browser.starts == []


def test_incompatible_future_revision_fails_closed_even_with_auto_update(
    tmp_path, monkeypatch
):
    """A revision generated by a NEWER adapter than the current code
    is never opened and never regenerated, regardless of auto_update."""

    _enable_fixture_twin(monkeypatch)

    _install_revision(
        tmp_path,
        adapter_version=FUTURE_ADAPTER_VERSION,
        content_sha256=HASH_OLD,
    )

    managed_site_store = AutoTwinManagedSiteStore(
        path=tmp_path / "managed_sites.json"
    )
    managed_site_store.register(_managed_site(auto_update=True))

    refresher = _RecordingRefresher(tmp_path)
    browser = _FakeBrowserRuntime()

    service = _service(
        tmp_path,
        managed_site_store=managed_site_store,
        refresher=refresher,
        browser=browser,
    )

    with pytest.raises(RuntimeError) as excinfo:
        service.start_twin_browser(TWIN_KEY)

    assert "INCOMPATIBLE" in str(excinfo.value)
    assert refresher.calls == []
    assert browser.starts == []


# ---------------------------------------------------------------------
# F. GENERICITY -> the compatibility decision is provider-neutral.
# ---------------------------------------------------------------------

def test_compatibility_decision_module_is_provider_neutral():
    source = Path(
        "backend/qcc/auto_twin/materialization_compatibility.py"
    ).read_text(encoding="utf-8")

    lowered = source.lower()

    for forbidden in (
        "mercurio",
        "red_sara",
        "matrev-",
    ):
        assert forbidden not in lowered


def test_missing_navigation_manifest_is_stale_not_incompatible(
    tmp_path,
):
    revision_id = _install_revision(
        tmp_path,
        adapter_version=None,
        content_sha256=HASH_OLD,
    )

    decision = evaluate_materialized_revision_compatibility(
        materialized_root=tmp_path,
        twin_key=TWIN_KEY,
        revision_id=revision_id,
    )

    assert decision == AUTO_TWIN_MATERIALIZATION_STALE_REGENERATABLE


def test_future_adapter_version_is_incompatible(tmp_path):
    revision_id = _install_revision(
        tmp_path,
        adapter_version=FUTURE_ADAPTER_VERSION,
        content_sha256=HASH_OLD,
    )

    decision = evaluate_materialized_revision_compatibility(
        materialized_root=tmp_path,
        twin_key=TWIN_KEY,
        revision_id=revision_id,
    )

    assert decision == AUTO_TWIN_MATERIALIZATION_INCOMPATIBLE


# ---------------------------------------------------------------------
# H. CRM PRODUCT PATH -> exercised through start_twin_browser, the
#    exact method/callback the Twins view itself calls.
# ---------------------------------------------------------------------

def test_frontend_twins_view_calls_the_gated_service_method():
    source = Path(
        "frontend/views/twins_view.py"
    ).read_text(encoding="utf-8")

    assert "service.start_twin_browser(" in source
