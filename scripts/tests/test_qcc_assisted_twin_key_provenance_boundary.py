"""QCC_ASSISTED_REAL_SMOKE_V4: twin_key provenance boundary regression.

Reproduces the exact REAL-smoke bypass left open by V3's
``if not _text(twin_key):`` gate in
``automatic_materialization.reconcile_auto_twin_discovery_materialization``:

    qcc_assisted (passive) capture
        -> AutoTwinObservationStore resolves a managed twin_key purely
           from the capture's own observed site/url correlation
           (``resolve_twin_key_for_capture``), never from any
           human/operator action
        -> the Bridge's artifact-trigger scheduler
           (``_qcc_schedule_auto_twin_materialization_after_artifact``)
           hands that resolved twin_key down EXPLICITLY through the
           REAL ``AutoTwinMaterializationCoordinator``
        -> the REAL processor
           (``_qcc_project_auto_twin_materialization_after_artifact``)

``twin_key is not None`` must never, by itself, be treated as explicit
human/operator Twin authority. Only the trigger capture's OWN recorded
``browser_profile_key`` is trusted provenance.

Everything exercised here is the REAL production chain -- the only
fake is the Twin runtime/navigation-validation default singleton
(SeleniumBase-backed), stubbed exactly like every other test in this
suite that touches this coordinator.
"""

import json
from types import SimpleNamespace

import backend.qcc.auto_twin.navigation_transition_validation_coordinator \
    as navigation_transition_validation_coordinator

from backend.qcc.auto_twin.automatic_materialization import (
    AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED,
    REQUIRED_ARTIFACTS,
)
from backend.qcc.auto_twin.managed_site_registry import AutoTwinManagedSite
from backend.qcc.auto_twin.managed_site_store import AutoTwinManagedSiteStore
from backend.qcc.auto_twin.materialization_coordinator import (
    AutoTwinMaterializationCoordinator,
)
from backend.qcc.auto_twin.observation_store import AutoTwinObservationStore
from backend.qcc.bridge.server import (
    _qcc_project_auto_twin_materialization_after_artifact,
    _qcc_schedule_auto_twin_materialization_after_artifact,
)


TIMEOUT = 5.0

ORIGIN = "https://mercurio.example"
SITE_CODE = "MERCURIO"
TWIN_KEY = "mercurio"
PATHNAME = "/mercurio/nuevaSolicitud.html"
FINGERPRINT = "c" * 64


def _write_capture(root, capture_id, *, browser_profile_key):
    directory = root / capture_id
    directory.mkdir(parents=True, exist_ok=True)

    for filename in REQUIRED_ARTIFACTS:
        path = directory / filename

        if filename == "qcc_capture.json":
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "browser_profile_key": browser_profile_key,
                    "main_url": ORIGIN + PATHNAME,
                }),
                encoding="utf-8",
            )
        elif filename == "site_architecture.json":
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "page": {
                        "pathname": PATHNAME,
                        "url": ORIGIN + PATHNAME,
                        "origin": ORIGIN,
                    },
                    "viewport": {
                        "inner_width": 1280,
                        "inner_height": 800,
                        "device_pixel_ratio": 1,
                        "scroll_x": 0,
                        "scroll_y": 0,
                    },
                    "elements": [],
                    "catalogs": [],
                }),
                encoding="utf-8",
            )
        elif filename == "state_observation.json":
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "state": None,
                    "fingerprint": FINGERPRINT,
                }),
                encoding="utf-8",
            )
        elif filename == "metadata.json":
            path.write_text(
                json.dumps({
                    "capture_id": capture_id,
                    "site_code": SITE_CODE,
                    "artifacts": {
                        "raw_capture": "qcc_capture.json",
                        "site_architecture": "site_architecture.json",
                        "state_observation": "state_observation.json",
                        "metadata": "metadata.json",
                        "screenshot_viewport": "screenshot_viewport.png",
                    },
                    "retention": {
                        "browser_profile_key": browser_profile_key,
                    },
                    "state_observation": {
                        "state": None,
                        "fingerprint": FINGERPRINT,
                    },
                    "visual_evidence": {
                        "viewport": {
                            "artifact": "screenshot_viewport.png",
                            "content_type": "image/png",
                        },
                    },
                }),
                encoding="utf-8",
            )
        elif filename.endswith(".png"):
            path.write_bytes(b"\x89PNG\r\n\x1a\nTEST")
        else:
            path.write_text("{}", encoding="utf-8")


class _RecordingValidationCoordinator:
    def __init__(self, calls):
        self._calls = calls

    def enqueue(self, **kwargs):
        self._calls.append(kwargs)
        return {"status": "QUEUED"}


def _build_world(tmp_path, *, browser_profile_key):
    captures = tmp_path / "captures"
    captures.mkdir()

    site = AutoTwinManagedSite(
        twin_key=TWIN_KEY,
        site_code=SITE_CODE,
        origins=(ORIGIN,),
    )

    managed_store = AutoTwinManagedSiteStore(path=tmp_path / "managed.json")
    managed_store.register(site)

    observation_store = AutoTwinObservationStore(
        path=tmp_path / "observation_state.json"
    )

    # The qcc_assisted (passive) observation is exactly what lets the
    # Bridge automatically resolve a managed twin_key for this
    # capture, from pure site/url correlation -- the REAL smoke's path.
    observation_store.observe(
        site,
        capture_id="cap-assisted-0",
        observed_at="2026-10-11T00:00:00.000000Z",
        browser_profile_key=browser_profile_key,
        url=ORIGIN + PATHNAME,
        site_code=site.site_code,
        state_observation={"fingerprint": FINGERPRINT},
    )

    _write_capture(
        captures, "cap-assisted-0", browser_profile_key=browser_profile_key
    )

    server = SimpleNamespace(
        qcc_auto_twin_store=managed_store,
        qcc_auto_twin_observation_store=observation_store,
        qcc_human_navigation_candidate_store=None,
        qcc_site_architecture_ingestor=SimpleNamespace(output_root=captures),
    )

    return server


def _attach_real_coordinator(server):
    def processor(*, twin_key, trigger_capture_id):
        return _qcc_project_auto_twin_materialization_after_artifact(
            server=server,
            capture_id=trigger_capture_id,
            twin_key=twin_key,
        )

    coordinator = AutoTwinMaterializationCoordinator(processor=processor)
    server.qcc_auto_twin_materialization_coordinator = coordinator
    return coordinator


def test_qcc_assisted_resolved_twin_key_never_auto_materializes(
    tmp_path, monkeypatch
):
    """The REAL smoke regression: a twin_key the Bridge resolved on
    its OWN (never from an explicit operator action) must never
    escalate into materialization, navigation validation enqueue or
    Twin runtime start -- even though the artifact-trigger path hands
    that twin_key down explicitly all the way into the reconciler.
    """

    server = _build_world(tmp_path, browser_profile_key="qcc_assisted")

    validation_calls = []

    monkeypatch.setattr(
        navigation_transition_validation_coordinator,
        "get_default_navigation_transition_validation_coordinator",
        lambda: _RecordingValidationCoordinator(validation_calls),
    )

    coordinator = _attach_real_coordinator(server)

    # The Bridge resolves twin_key automatically from the capture's
    # OWN observed link -- never from an explicit caller/operator.
    schedule = _qcc_schedule_auto_twin_materialization_after_artifact(
        server=server,
        capture_id="cap-assisted-0",
    )

    assert schedule["status"] == "QUEUED"
    assert schedule["twin_key"] == TWIN_KEY

    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    last_result = coordinator.snapshot()["last_result"]
    assert last_result["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    assert (
        last_result["reason"]
        == "TRIGGER_PROFILE_NOT_AUTHORIZED_FOR_AUTO_MATERIALIZATION"
    )

    # No navigation validation enqueue -> no Twin runtime start, no
    # local runtime URL ever opened.
    assert validation_calls == []


def test_qcc_assisted_known_state_never_re_enqueues_validation_via_bridge(
    tmp_path, monkeypatch
):
    """The faithful REAL-smoke shape: NO_CHANGE, not a brand-new
    state. V3's own admission (see
    ``test_qcc_assisted_known_state_trigger_never_reaches_no_change``
    in ``test_qcc_auto_twin_automatic_materialization.py``) is that an
    already-known/materialized state never reaches the deeper,
    mode-specific "selected evidence capture" profile check used only
    when building NEW content -- it falls straight through to
    NO_CHANGE, which the Bridge explicitly re-enqueues for Twin
    navigation validation (a stale Twin runtime recovering after a
    restart). A purely passive qcc_assisted re-observation of an
    ALREADY materialized screen must never reach that NO_CHANGE
    re-enqueue either.
    """

    server = _build_world(tmp_path, browser_profile_key="twin_discovery")

    # Phase 1: a genuine, explicit twin_discovery bootstrap -- self-
    # resolves its own twin_key, passes the (unconditional) provenance
    # gate, and REALLY materializes the first revision on disk.
    bootstrap = _qcc_project_auto_twin_materialization_after_artifact(
        server=server,
        capture_id="cap-assisted-0",
    )

    assert bootstrap["status"] == "MATERIALIZED"

    # Phase 2: a SECOND, purely passive qcc_assisted capture of the
    # EXACT SAME screen (same pathname/fingerprint) arrives later.
    # AutoTwinObservationStore links it to the SAME managed twin --
    # resolve_twin_key_for_capture() has no profile awareness at all.
    _write_capture(
        server.qcc_site_architecture_ingestor.output_root,
        "cap-assisted-1",
        browser_profile_key="qcc_assisted",
    )

    site = server.qcc_auto_twin_store.get(TWIN_KEY)

    server.qcc_auto_twin_observation_store.observe(
        site,
        capture_id="cap-assisted-1",
        observed_at="2026-10-11T00:00:05.000000Z",
        browser_profile_key="qcc_assisted",
        url=ORIGIN + PATHNAME,
        site_code=site.site_code,
        state_observation={"fingerprint": FINGERPRINT},
    )

    validation_calls = []

    monkeypatch.setattr(
        navigation_transition_validation_coordinator,
        "get_default_navigation_transition_validation_coordinator",
        lambda: _RecordingValidationCoordinator(validation_calls),
    )

    coordinator = _attach_real_coordinator(server)

    # The Bridge resolves twin_key automatically from the capture's OWN
    # observed link -- never from an explicit caller/operator -- and
    # hands it down explicitly through the coordinator.
    schedule = _qcc_schedule_auto_twin_materialization_after_artifact(
        server=server,
        capture_id="cap-assisted-1",
    )

    assert schedule["status"] == "QUEUED"
    assert schedule["twin_key"] == TWIN_KEY

    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    last_result = coordinator.snapshot()["last_result"]
    assert last_result["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    assert (
        last_result["reason"]
        == "TRIGGER_PROFILE_NOT_AUTHORIZED_FOR_AUTO_MATERIALIZATION"
    )

    # No navigation validation enqueue -> no stale Twin runtime start,
    # no local runtime URL ever opened.
    assert validation_calls == []


def test_twin_discovery_resolved_twin_key_still_schedules(tmp_path, monkeypatch):
    """Control: the SAME automatic-resolution path, for a genuinely
    twin_discovery-profiled trigger capture, is unaffected by the
    provenance fix and still schedules/runs normally."""

    server = _build_world(tmp_path, browser_profile_key="twin_discovery")

    validation_calls = []

    monkeypatch.setattr(
        navigation_transition_validation_coordinator,
        "get_default_navigation_transition_validation_coordinator",
        lambda: _RecordingValidationCoordinator(validation_calls),
    )

    coordinator = _attach_real_coordinator(server)

    schedule = _qcc_schedule_auto_twin_materialization_after_artifact(
        server=server,
        capture_id="cap-assisted-0",
    )

    assert schedule["status"] == "QUEUED"
    assert schedule["twin_key"] == TWIN_KEY

    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    last_result = coordinator.snapshot()["last_result"]
    assert (
        last_result["reason"]
        != "TRIGGER_PROFILE_NOT_AUTHORIZED_FOR_AUTO_MATERIALIZATION"
    )
