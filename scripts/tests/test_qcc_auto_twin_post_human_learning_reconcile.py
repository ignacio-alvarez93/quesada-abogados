"""Post human-learning AUTO TWIN reconciliation.

Integration tests deliberately use the REAL
reconcile_auto_twin_discovery_materialization(), the REAL
materializer/plan builder, and REAL temporary managed-site,
observation, candidate and materialized-revision stores.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.qcc.auto_twin.automatic_materialization as auto_materialization

from backend.qcc.auto_twin.automatic_materialization import (
    AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED,
    AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE,
    AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED,
    REQUIRED_ARTIFACTS,
    reconcile_auto_twin_discovery_materialization,
)
from backend.qcc.auto_twin.managed_site_registry import (
    AutoTwinManagedSite,
)
from backend.qcc.auto_twin.managed_site_store import (
    AutoTwinManagedSiteStore,
)
from backend.qcc.auto_twin.materialization_builder import (
    AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    materialize_auto_twin_plan,
)
from backend.qcc.auto_twin.materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
    AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
)
from backend.qcc.auto_twin.materialized_revision_store import (
    AutoTwinMaterializedRevisionStore,
)
from backend.qcc.auto_twin.observation_store import (
    AutoTwinObservationStore,
)
from backend.qcc.auto_twin.materialization_coordinator import (
    AutoTwinMaterializationCoordinator,
)
from backend.qcc.bridge.server import (
    _qcc_project_auto_twin_materialization_after_artifact,
    _qcc_project_auto_twin_materialization_after_human_learning,
)
from backend.qcc.context.live_action_evidence import (
    QccLiveActionEvidence,
)
from backend.qcc.context.observed_human_action import (
    QccObservedHumanAction,
)
from backend.qcc.navigation_learning.human_candidate_store import (
    HumanNavigationCandidateStore,
)


ORIGIN = "https://reg.redsara.es"
TWIN_KEY = "red_sara"
SITE_CODE = "RED_SARA"

FP_A = "a" * 64
FP_B = "b" * 64

# Structural, sanitized selector: never a raw onclick literal.
ACTION_SELECTOR = 'a[onclick="continuar();"]'


def _write_capture(root, capture_id):
    directory = root / capture_id
    directory.mkdir(parents=True, exist_ok=True)

    for filename in REQUIRED_ARTIFACTS:
        path = directory / filename

        if filename == "qcc_capture.json":
            path.write_text(
                json.dumps({"browser_profile_key": "twin_discovery"}),
                encoding="utf-8",
            )
        elif filename.endswith(".png"):
            path.write_bytes(b"\x89PNG\r\n\x1a\nTEST")
        else:
            path.write_text("{}", encoding="utf-8")


def _observe(store, site, *, capture_id, fingerprint, pathname, second):
    return store.observe(
        site,
        capture_id=capture_id,
        observed_at=f"2026-09-05T15:00:{second:02d}.000000Z",
        browser_profile_key="twin_discovery",
        url=ORIGIN + pathname,
        site_code=site.site_code,
        state_observation={"fingerprint": fingerprint},
    )


def _write_golden_state(base, index, state_id, pathname, fingerprint):
    state_root = base / "states" / f"{index:02d}-{state_id}"
    runtime = state_root / "runtime"
    runtime.mkdir(parents=True)

    (runtime / "state.json").write_text(
        json.dumps({
            "state_id": state_id,
            "source_capture_id": f"cap-{state_id}-0",
            "pathname": pathname,
            "functional_state": None,
            "fingerprint": fingerprint,
        }),
        encoding="utf-8",
    )

    (runtime / "index.html").write_text(
        '<html><body><a id="go">go</a></body></html>',
        encoding="utf-8",
    )

    (runtime / "shadow_styles.json").write_text("{}", encoding="utf-8")

    # Physically unique action evidence: exactly ONE element carries the
    # structural onclick owned by the learned transition, so the real
    # restore_navigation_action_identity() resolves it without needing a
    # positional :qcc-nth-onclick(N) suffix. Only STATE_A owns the action.
    elements = (
        [{
            "tag": "a",
            "text": "go",
            "attributes": {"id": "go", "onclick": "continuar();"},
        }]
        if state_id == "STATE_A"
        else []
    )

    evidence = state_root / "evidence"
    evidence.mkdir()
    (evidence / "qcc_capture.json").write_text(
        json.dumps({
            "frames": [{
                "frame_id": 0,
                "result": {"elements": elements},
            }],
        }),
        encoding="utf-8",
    )

    source = state_root / "source"
    source.mkdir()
    (source / "page.html").write_text("SRC", encoding="utf-8")


def _seed_revision(materialized_root):
    """First REAL revision: 2 states, zero navigation transitions."""

    base = materialized_root / TWIN_KEY / "matrev-golden"
    (base / "runtime").mkdir(parents=True)

    (base / "runtime" / "renderer.json").write_text(
        json.dumps({"renderer_version": AUTO_TWIN_RUNTIME_RENDERER_VERSION}),
        encoding="utf-8",
    )

    _write_golden_state(base, 1, "STATE_A", "/es/a", FP_A)
    _write_golden_state(base, 2, "STATE_B", "/es/b", FP_B)

    manifest = [
        {
            "state_index": index,
            "state_id": state_id,
            "source_capture_id": f"cap-{state_id}-0",
            "pathname": pathname,
            "functional_state": None,
            "rendering_profile_id": "MATERIALIZED_CARRY_FORWARD",
            "source_mode": AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
        }
        for index, state_id, pathname in (
            (1, "STATE_A", "/es/a"),
            (2, "STATE_B", "/es/b"),
        )
    ]

    plan = {
        "schema_version": 1,
        "plan_type": AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
        "plan_id": "matplan-post-learning-seed",
        "twin_key": TWIN_KEY,
        "materialization_mode": "BOOTSTRAP_REAL",
        "generation_source": "REAL_EVIDENCE_ONLY",
        "required_origin": ORIGIN,
        "required_profile_key": "twin_discovery",
        "base_materialized_revision_id": "matrev-golden",
        "source_capture_ids": ["cap-STATE_A-0", "cap-STATE_B-0"],
        "source_evidence_sha256": "a" * 64,
        "artifact_operations": [],
        "state_manifest": manifest,
    }

    return materialize_auto_twin_plan(
        plan=plan,
        source_root=materialized_root.parent / "captures",
        materialized_root=materialized_root,
        procedure_code=SITE_CODE,
        flow_variant="SITE_LEVEL",
    )["revision"]


def _learn_transition(candidate_store, *, event_id="evt-x"):
    return candidate_store.record_observed_transition({
        "changed": True,
        "event_id": event_id,
        "after_observed_at": "2026-09-05T15:10:00Z",
        "site_code": SITE_CODE,
        "environment": "REAL",
        "before_state": None,
        "before_fingerprint": FP_A,
        "kind": "LINK",
        "policy": "NAVIGATION_CANDIDATE",
        "selector": ACTION_SELECTOR,
        "frame_path": "main",
        "after_state": None,
        "after_fingerprint": FP_B,
    })


@pytest.fixture
def world(tmp_path):
    captures = tmp_path / "captures"
    captures.mkdir()
    materialized_root = tmp_path / "materialized"

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

    # State A: older baseline, then action-X capture, then a LATER
    # unrelated capture -> X capture is no longer last_capture_id.
    _observe(observation_store, site, capture_id="cap-A-0",
             fingerprint=FP_A, pathname="/es/a", second=0)
    _observe(observation_store, site, capture_id="cap-A-X",
             fingerprint=FP_A, pathname="/es/a", second=1)
    # State B: Y capture, then a later unrelated capture.
    _observe(observation_store, site, capture_id="cap-B-0",
             fingerprint=FP_B, pathname="/es/b", second=2)
    _observe(observation_store, site, capture_id="cap-B-Y",
             fingerprint=FP_B, pathname="/es/b", second=3)
    _observe(observation_store, site, capture_id="cap-A-LATER",
             fingerprint=FP_A, pathname="/es/a", second=4)
    _observe(observation_store, site, capture_id="cap-B-LATER",
             fingerprint=FP_B, pathname="/es/b", second=5)

    for capture_id in (
        "cap-A-0", "cap-A-X", "cap-A-LATER",
        "cap-B-0", "cap-B-Y", "cap-B-LATER",
    ):
        _write_capture(captures, capture_id)

    seed = _seed_revision(materialized_root)

    return SimpleNamespace(
        captures=captures,
        materialized_root=materialized_root,
        managed_store=managed_store,
        observation_store=observation_store,
        candidate_store=HumanNavigationCandidateStore(
            root=tmp_path / "candidates"
        ),
        seed=seed,
    )


def _reconcile(world, *, trigger, twin_key=None):
    return reconcile_auto_twin_discovery_materialization(
        managed_site_store=world.managed_store,
        observation_store=world.observation_store,
        capture_root=world.captures,
        trigger_capture_id=trigger,
        twin_key=twin_key,
        materialized_root=world.materialized_root,
        human_navigation_candidate_store=world.candidate_store,
    )


def _transitions(world, revision_id):
    path = (
        world.materialized_root
        / TWIN_KEY
        / revision_id
        / "runtime"
        / "navigation_transitions.json"
    )

    return json.loads(path.read_text(encoding="utf-8"))


def test_seed_revision_has_no_navigation_transitions(world):
    assert _transitions(
        world, world.seed["materialized_revision_id"]
    )["transition_count"] == 0


def test_historical_action_capture_is_not_resolvable_without_authority(world):
    # Root cause reproduction: X capture is neither baseline nor
    # last_capture_id of any state, so the artifact-trigger resolver
    # (deliberately unchanged) refuses it.
    _learn_transition(world.candidate_store)

    result = _reconcile(world, trigger="cap-A-X")

    assert result["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    assert result["reason"] == "TRIGGER_NOT_LINKED_TO_OBSERVED_TWIN"


def test_post_learning_real_reconcile_materializes_navigation(world):
    seed_id = world.seed["materialized_revision_id"]

    _learn_transition(world.candidate_store)

    # Trigger = exact Y capture (X -> Y is finalized against Y.before),
    # which is not last_capture_id either. Twin authority is explicit.
    result = _reconcile(
        world,
        trigger="cap-B-Y",
        twin_key=TWIN_KEY,
    )

    assert result["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    assert result["twin_key"] == TWIN_KEY
    assert result["trigger_capture_id"] == "cap-B-Y"
    assert result["materialized_revision_id"] != seed_id

    stored = AutoTwinMaterializedRevisionStore(
        root=world.materialized_root
    ).list(twin_key=TWIN_KEY)

    assert result["materialized_revision_id"] in {
        item["materialized_revision_id"] for item in stored
    }

    payload = _transitions(world, result["materialized_revision_id"])

    assert payload["transition_count"] >= 1

    # Privacy: only the structural selector is ever materialized.
    serialized = json.dumps(payload)
    assert "continuar('INI')" not in serialized
    assert "validarYEnviar('AB')" not in serialized

    # Fixed point: same knowledge -> no further revision.
    again = _reconcile(
        world,
        trigger="cap-B-Y",
        twin_key=TWIN_KEY,
    )

    assert again["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    assert (
        again["materialized_revision_id"]
        == result["materialized_revision_id"]
    )


def test_candidate_only_change_revises_twin_with_same_states(world):
    seed_id = world.seed["materialized_revision_id"]
    seed_state_count = len(world.seed["state_manifest"])

    # Same materialized states, no candidates yet.
    before = _reconcile(world, trigger="cap-B-Y", twin_key=TWIN_KEY)

    assert before["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    assert before["materialized_revision_id"] == seed_id

    # Only the CandidateStore changes.
    _learn_transition(world.candidate_store)

    after = _reconcile(world, trigger="cap-B-Y", twin_key=TWIN_KEY)

    assert after["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    assert after["materialized_revision_id"] != seed_id
    assert after["added_state_count"] == 0
    assert after["state_count"] == seed_state_count
    assert _transitions(
        world, after["materialized_revision_id"]
    )["transition_count"] >= 1


def test_unrelated_later_capture_cannot_hijack_explicit_twin(world):
    _learn_transition(world.candidate_store)

    # A later capture of another state is a legitimate observation,
    # but the explicit authority still pins exactly this Twin/trigger.
    result = _reconcile(world, trigger="cap-B-Y", twin_key=TWIN_KEY)

    assert result["twin_key"] == TWIN_KEY
    assert result["trigger_capture_id"] == "cap-B-Y"

    # An unknown twin_key never falls back to capture rediscovery.
    other = _reconcile(world, trigger="cap-B-Y", twin_key="other_twin")

    assert other["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    assert other["reason"] == "MANAGED_TWIN_NOT_FOUND"


# ---------------------------------------------------------
# Bridge helper: authority derivation
# ---------------------------------------------------------


class _Registry:
    def __init__(self, sites):
        self._sites = sites

    def get_by_site_code(self, site_code):
        twin_key = self._sites.get(site_code)

        return (
            SimpleNamespace(twin_key=twin_key, site_code=site_code)
            if twin_key
            else None
        )


def _server(tmp_path, sites, *, coordinator=True):
    server = SimpleNamespace(
        qcc_auto_twin_store=_Registry(sites),
        qcc_auto_twin_observation_store=object(),
        qcc_human_navigation_candidate_store=object(),
        qcc_site_architecture_ingestor=SimpleNamespace(
            output_root=tmp_path
        ),
    )

    if coordinator:
        # Same wiring as QccBridgeServer: the worker runs the existing
        # synchronous helper, no reconciliation logic is duplicated.
        server.qcc_auto_twin_materialization_coordinator = (
            AutoTwinMaterializationCoordinator(
                processor=lambda *, twin_key, trigger_capture_id: (
                    _qcc_project_auto_twin_materialization_after_artifact(
                        server=server,
                        capture_id=trigger_capture_id,
                        twin_key=twin_key,
                    )
                )
            )
        )

    return server


def _drain(server):
    coordinator = server.qcc_auto_twin_materialization_coordinator

    assert coordinator.wait_until_idle(timeout=5.0)

    return coordinator.snapshot()


@pytest.fixture
def recorded(monkeypatch):
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return {"status": "NO_CHANGE"}

    monkeypatch.setattr(
        auto_materialization,
        "reconcile_auto_twin_discovery_materialization",
        fake,
    )

    return calls


def test_bridge_derives_twin_key_from_trusted_site_and_uses_exact_trigger(
    tmp_path, recorded
):
    server = _server(
        tmp_path,
        {"RED_SARA": "red_sara", "MERCURIO": "mercurio"},
    )

    result = _qcc_project_auto_twin_materialization_after_human_learning(
        server=server,
        site_code="mercurio",
        next_action_site_code="MERCURIO",
        trigger_capture_id="cap-Y-exact",
    )

    # Scheduling result only: reconciliation runs on the worker.
    assert result == {
        "status": "QUEUED",
        "twin_key": "mercurio",
        "trigger_capture_id": "cap-Y-exact",
    }

    snapshot = _drain(server)

    assert snapshot["last_result"]["status"] == "NO_CHANGE"
    assert len(recorded) == 1
    assert recorded[0]["twin_key"] == "mercurio"
    assert recorded[0]["trigger_capture_id"] == "cap-Y-exact"


def test_bridge_skips_when_next_action_site_differs(tmp_path, recorded):
    server = _server(tmp_path, {"RED_SARA": "red_sara"})

    result = _qcc_project_auto_twin_materialization_after_human_learning(
        server=server,
        site_code="RED_SARA",
        next_action_site_code="OTHER",
        trigger_capture_id="cap-Y",
    )

    assert result["status"] == "SKIPPED"
    assert recorded == []


def test_bridge_skips_unmanaged_site_and_missing_capture(tmp_path, recorded):
    server = _server(tmp_path, {"RED_SARA": "red_sara"})

    unmanaged = _qcc_project_auto_twin_materialization_after_human_learning(
        server=server,
        site_code="UNKNOWN",
        next_action_site_code="UNKNOWN",
        trigger_capture_id="cap-Y",
    )

    no_capture = _qcc_project_auto_twin_materialization_after_human_learning(
        server=server,
        site_code="RED_SARA",
        next_action_site_code="RED_SARA",
        trigger_capture_id=None,
    )

    assert unmanaged["reason"] == "POST_LEARNING_MANAGED_TWIN_NOT_FOUND"
    assert no_capture["reason"] == "CAPTURE_ID_EMPTY"
    assert recorded == []


def test_bridge_post_learning_failure_is_fail_open(tmp_path, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        auto_materialization,
        "reconcile_auto_twin_discovery_materialization",
        boom,
    )

    server = _server(tmp_path, {"RED_SARA": "red_sara"})

    result = _qcc_project_auto_twin_materialization_after_human_learning(
        server=server,
        site_code="RED_SARA",
        next_action_site_code="RED_SARA",
        trigger_capture_id="cap-Y",
    )

    # Scheduling succeeds; the worker failure is isolated and visible.
    assert result["status"] == "QUEUED"

    snapshot = _drain(server)

    assert snapshot["worker_alive"] is True
    assert snapshot["last_result"]["status"] == "ERROR"


def test_bridge_scheduling_failure_is_fail_open(tmp_path):
    server = _server(tmp_path, {"RED_SARA": "red_sara"})

    class _BrokenCoordinator:
        def enqueue(self, **kwargs):
            raise RuntimeError("cannot schedule")

    server.qcc_auto_twin_materialization_coordinator = _BrokenCoordinator()

    result = _qcc_project_auto_twin_materialization_after_human_learning(
        server=server,
        site_code="RED_SARA",
        next_action_site_code="RED_SARA",
        trigger_capture_id="cap-Y",
    )

    assert result["status"] == "ERROR"


def test_bridge_skips_when_coordinator_unavailable(tmp_path, recorded):
    server = _server(
        tmp_path,
        {"RED_SARA": "red_sara"},
        coordinator=False,
    )

    result = _qcc_project_auto_twin_materialization_after_human_learning(
        server=server,
        site_code="RED_SARA",
        next_action_site_code="RED_SARA",
        trigger_capture_id="cap-Y",
    )

    assert result["status"] == "SKIPPED"
    assert (
        result["reason"]
        == "AUTO_TWIN_MATERIALIZATION_COORDINATOR_UNAVAILABLE"
    )
    assert recorded == []


def test_bridge_helper_does_not_reconcile_in_calling_thread(
    tmp_path, monkeypatch
):
    import threading

    threads = []

    def fake(**kwargs):
        threads.append(threading.current_thread())
        return {"status": "NO_CHANGE"}

    monkeypatch.setattr(
        auto_materialization,
        "reconcile_auto_twin_discovery_materialization",
        fake,
    )

    server = _server(tmp_path, {"RED_SARA": "red_sara"})

    _qcc_project_auto_twin_materialization_after_human_learning(
        server=server,
        site_code="RED_SARA",
        next_action_site_code="RED_SARA",
        trigger_capture_id="cap-Y",
    )

    _drain(server)

    assert len(threads) == 1
    assert threads[0] is not threading.current_thread()
    assert threads[0].daemon is True


# ---------------------------------------------------------
# Backend-owned capture identity carriers
# ---------------------------------------------------------


def test_live_action_evidence_capture_id_is_normalized():
    def build(capture_id):
        return QccLiveActionEvidence(
            session_id="s1",
            site_code="red_sara",
            environment="real",
            before_state=None,
            before_fingerprint=FP_A,
            actions=(),
            captured_at=datetime.now(timezone.utc),
            capture_id=capture_id,
        )

    assert build("  cap-1 ").capture_id == "cap-1"
    assert build("").capture_id is None
    assert build(None).capture_id is None

    with pytest.raises(ValueError):
        build("x" * 129)


def test_observed_action_capture_id_never_affects_identity():
    def build(capture_id):
        return QccObservedHumanAction(
            event_id="evt-1",
            session_id="s1",
            site_code="RED_SARA",
            environment="REAL",
            before_state=None,
            before_fingerprint=FP_A,
            kind="LINK",
            policy="NAVIGATION_CANDIDATE",
            selector=ACTION_SELECTOR,
            frame_path="main",
            observed_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            evidence_capture_id=capture_id,
        )

    assert build(" cap-Y ").evidence_capture_id == "cap-Y"
    assert build(None).evidence_capture_id is None
    assert build("cap-1") == build("cap-2")
