"""AUTO TWIN artifact-completion coordinator race regression (FIX1).

Reproduces the exact missing-MaterializedRevision scenario: a trusted
human navigation candidate is already persisted, a new physical target
state has been observed exactly once (REAL EX04 evidence shape), and
its deep artifacts (MHTML, viewport) arrive as two separate HTTP
requests. Before FIX1, each artifact handler reconciled synchronously
in its own request thread, so whichever request saw an incomplete
bundle first concluded WAITING_EVIDENCE with no later trigger to
notice the bundle had since become complete.

These are true integration tests: the REAL
reconcile_auto_twin_discovery_materialization(), the REAL plan
builder/materializer and REAL temporary managed-site, observation,
candidate and materialized-revision stores are exercised end to end
through the REAL AutoTwinMaterializationCoordinator -- never a fake
processor standing in for the reconciler itself.
"""

import json
import threading
from types import SimpleNamespace

import pytest

import backend.qcc.auto_twin.automatic_materialization as auto_materialization

from backend.qcc.auto_twin.automatic_materialization import (
    AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED,
    AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED,
    AUTO_TWIN_AUTO_MATERIALIZATION_WAITING,
    REQUIRED_ARTIFACTS,
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
from backend.qcc.auto_twin.materialization_coordinator import (
    AutoTwinMaterializationCoordinator,
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
from backend.qcc.bridge.server import (
    _qcc_project_auto_twin_materialization_after_artifact,
    _qcc_project_auto_twin_materialization_after_human_learning,
    _qcc_schedule_auto_twin_materialization_after_artifact,
)
from backend.qcc.navigation_learning.human_candidate_store import (
    HumanNavigationCandidateStore,
)


TIMEOUT = 5.0

ORIGIN = "https://mercurio.example"
TWIN_KEY = "mercurio"
SITE_CODE = "MERCURIO"

FP_A = "a" * 64
FP_B = "b" * 64

PATHNAME_A = "/mercurio/nuevaSolicitud.html"
PATHNAME_B = "/mercurio/nuevaSolicitud-EX04.html"

# Structural, sanitized selector: never a raw onclick literal.
ACTION_SELECTOR = 'a[onclick="continuar();"]'

DEEP_ARTIFACTS = (
    "page.mhtml",
    "screenshot_viewport.png",
)


def _write_capture(root, capture_id, *, filenames):
    directory = root / capture_id
    directory.mkdir(parents=True, exist_ok=True)

    for filename in filenames:
        _write_capture_artifact(directory, filename)


def _write_capture_artifact(directory, filename):
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


def _add_capture_artifact(root, capture_id, filename):
    _write_capture_artifact(root / capture_id, filename)


def _observe(store, site, *, capture_id, fingerprint, pathname, second):
    return store.observe(
        site,
        capture_id=capture_id,
        observed_at=f"2026-09-26T16:53:{second:02d}.000000Z",
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

    # Physically unique action evidence, mirroring the proven
    # navigation-transition-materialization test fixture shape.
    evidence = state_root / "evidence"
    evidence.mkdir()
    (evidence / "qcc_capture.json").write_text(
        json.dumps({
            "frames": [{
                "frame_id": 0,
                "result": {
                    "elements": [{
                        "tag": "a",
                        "text": "go",
                        "attributes": {
                            "id": "go",
                            "onclick": "continuar();",
                        },
                    }],
                },
            }],
        }),
        encoding="utf-8",
    )

    source = state_root / "source"
    source.mkdir()
    (source / "page.html").write_text("SRC", encoding="utf-8")


def _seed_single_state_revision(materialized_root):
    """First REAL revision: exactly ONE physical state, zero transitions.

    Mirrors the REAL EX04 baseline: one already-materialized state, one
    not-yet-materialized target state discovered later by a single
    observation.
    """

    base = materialized_root / TWIN_KEY / "matrev-golden"
    (base / "runtime").mkdir(parents=True)

    (base / "runtime" / "renderer.json").write_text(
        json.dumps({"renderer_version": AUTO_TWIN_RUNTIME_RENDERER_VERSION}),
        encoding="utf-8",
    )

    _write_golden_state(base, 1, "STATE_A", PATHNAME_A, FP_A)

    manifest = [{
        "state_index": 1,
        "state_id": "STATE_A",
        "source_capture_id": "cap-STATE_A-0",
        "pathname": PATHNAME_A,
        "functional_state": None,
        "rendering_profile_id": "MATERIALIZED_CARRY_FORWARD",
        "source_mode": AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
    }]

    plan = {
        "schema_version": 1,
        "plan_type": AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
        "plan_id": "matplan-race-seed",
        "twin_key": TWIN_KEY,
        "materialization_mode": "BOOTSTRAP_REAL",
        "generation_source": "REAL_EVIDENCE_ONLY",
        "required_origin": ORIGIN,
        "required_profile_key": "twin_discovery",
        "base_materialized_revision_id": "matrev-golden",
        "source_capture_ids": ["cap-STATE_A-0"],
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


def _learn_transition(candidate_store, *, event_id="evt-ex04"):
    return candidate_store.record_observed_transition({
        "changed": True,
        "event_id": event_id,
        "after_observed_at": "2026-09-26T16:54:00Z",
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


def _attach_recording_coordinator(server, calls, *, pause=None):
    """Wire the REAL artifact processor, recording every real result.

    ``pause`` (optional): {"at_call": N, "entered": Event, "release": Event}
    blocks the Nth call (1-based) AFTER it has computed its REAL result
    but BEFORE returning it to the coordinator -- creating genuine,
    observable concurrency with a job enqueued for the same twin while
    this one is still "running", without ever faking the reconciler.
    """

    def instrumented_processor(*, twin_key, trigger_capture_id):
        result = _qcc_project_auto_twin_materialization_after_artifact(
            server=server,
            capture_id=trigger_capture_id,
            twin_key=twin_key,
        )

        calls.append((twin_key, trigger_capture_id, result.get("status")))

        if pause is not None and len(calls) == pause["at_call"]:
            pause["entered"].set()
            assert pause["release"].wait(timeout=TIMEOUT)

        return result

    coordinator = AutoTwinMaterializationCoordinator(
        processor=instrumented_processor
    )

    server.qcc_auto_twin_materialization_coordinator = coordinator

    return coordinator


@pytest.fixture
def world(tmp_path):
    captures = tmp_path / "captures"
    captures.mkdir()
    materialized_root = tmp_path / "auto_twin_materialized"

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

    _observe(
        observation_store, site,
        capture_id="cap-A-0", fingerprint=FP_A,
        pathname=PATHNAME_A, second=0,
    )

    # New target state: exactly ONE observation (REAL EX04 shape,
    # observation_count=1). Deep artifacts deliberately withheld: this
    # capture starts life physically incomplete.
    _observe(
        observation_store, site,
        capture_id="cap-B-Y", fingerprint=FP_B,
        pathname=PATHNAME_B, second=1,
    )

    _write_capture(captures, "cap-A-0", filenames=REQUIRED_ARTIFACTS)

    _write_capture(
        captures,
        "cap-B-Y",
        filenames=[
            name for name in REQUIRED_ARTIFACTS
            if name not in DEEP_ARTIFACTS
        ],
    )

    seed = _seed_single_state_revision(materialized_root)

    candidate_store = HumanNavigationCandidateStore(
        root=tmp_path / "candidates"
    )

    learned = _learn_transition(candidate_store)
    candidate_id = learned["candidate"]["candidate_id"]

    server = SimpleNamespace(
        qcc_auto_twin_store=managed_store,
        qcc_auto_twin_observation_store=observation_store,
        qcc_human_navigation_candidate_store=candidate_store,
        qcc_site_architecture_ingestor=SimpleNamespace(
            output_root=captures
        ),
    )

    calls = []
    _attach_recording_coordinator(server, calls)

    return SimpleNamespace(
        captures=captures,
        materialized_root=materialized_root,
        managed_store=managed_store,
        observation_store=observation_store,
        candidate_store=candidate_store,
        candidate_id=candidate_id,
        server=server,
        calls=calls,
        seed=seed,
    )


# ---------------------------------------------------------
# The race regression itself.
# ---------------------------------------------------------


def test_artifact_completion_race_regression(world):
    server = world.server

    entered = threading.Event()
    release = threading.Event()

    coordinator = _attach_recording_coordinator(
        server,
        world.calls,
        pause={
            "at_call": 2,
            "entered": entered,
            "release": release,
        },
    )

    # (1) Post-learning trigger fires too early: neither MHTML nor
    #     viewport exist yet for the new target state's capture.
    post_learning = (
        _qcc_project_auto_twin_materialization_after_human_learning(
            server=server,
            site_code=SITE_CODE,
            trusted_trigger_site_code=SITE_CODE,
            trigger_capture_id="cap-B-Y",
        )
    )

    assert post_learning["status"] == "QUEUED"
    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    assert world.calls[-1][:2] == (TWIN_KEY, "cap-B-Y")
    assert world.calls[-1][2] == AUTO_TWIN_AUTO_MATERIALIZATION_WAITING

    # (2) MHTML artifact request arrives: it attaches the artifact and
    #     only SCHEDULES reconciliation -- never reconciles inline.
    _add_capture_artifact(world.captures, "cap-B-Y", "page.mhtml")

    mhtml_schedule = (
        _qcc_schedule_auto_twin_materialization_after_artifact(
            server=server,
            capture_id="cap-B-Y",
        )
    )

    assert mhtml_schedule["status"] == "QUEUED"
    assert mhtml_schedule["twin_key"] == TWIN_KEY
    assert mhtml_schedule["trigger_capture_id"] == "cap-B-Y"

    # This job is now genuinely running -- paused right after computing
    # its REAL, still-incomplete result. This is exactly the moment the
    # original race let a concurrent viewport request observe an
    # in-flight/incomplete bundle with nothing left to trigger again.
    assert entered.wait(timeout=TIMEOUT)
    assert coordinator.snapshot()["running_count"] == 1
    assert coordinator.snapshot()["pending_count"] == 0

    # (3) Viewport artifact request arrives WHILE the MHTML job is
    #     still running: it completes the bundle on disk and schedules
    #     its own coordinator job concurrently.
    _add_capture_artifact(
        world.captures, "cap-B-Y", "screenshot_viewport.png"
    )

    viewport_schedule = (
        _qcc_schedule_auto_twin_materialization_after_artifact(
            server=server,
            capture_id="cap-B-Y",
        )
    )

    assert viewport_schedule["status"] == "QUEUED"
    assert viewport_schedule["twin_key"] == TWIN_KEY

    # Real, observed concurrency: current job + exactly one guaranteed
    # follow-up carrying the latest trusted trigger.
    assert coordinator.snapshot()["running_count"] == 1
    assert coordinator.snapshot()["pending_count"] == 1

    # (4) Release the MHTML job -- it returns its already-computed
    #     WAITING_EVIDENCE result. The coordinator then runs the
    #     guaranteed follow-up, which observes the NOW-complete bundle.
    release.set()

    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    assert [call[:2] for call in world.calls] == [
        (TWIN_KEY, "cap-B-Y"),
        (TWIN_KEY, "cap-B-Y"),
        (TWIN_KEY, "cap-B-Y"),
    ]

    assert [call[2] for call in world.calls] == [
        AUTO_TWIN_AUTO_MATERIALIZATION_WAITING,
        AUTO_TWIN_AUTO_MATERIALIZATION_WAITING,
        AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED,
    ]

    # (13) No manual extra click/capture was required: exactly the 3
    # naturally-arriving triggers closed the pipeline.
    assert len(world.calls) == 3

    final = coordinator.snapshot()["last_result"]

    assert final["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED

    revision_id = final["materialized_revision_id"]

    assert revision_id != world.seed["materialized_revision_id"]

    stored = AutoTwinMaterializedRevisionStore(
        root=world.materialized_root
    ).list(twin_key=TWIN_KEY)

    assert revision_id in {
        item["materialized_revision_id"] for item in stored
    }

    # (9)/(10) A materialized revision exists and pass 1's new physical
    # target state is present in it.
    registry = json.loads(
        (
            world.materialized_root / TWIN_KEY / revision_id
            / "runtime" / "registry.json"
        ).read_text(encoding="utf-8")
    )

    fingerprints = {
        state["fingerprint"] for state in registry["states"]
    }

    assert FP_A in fingerprints
    assert FP_B in fingerprints

    # (11)/(12) Bounded pass 2's candidate transition is materialized,
    # with the exact candidate_id.
    transitions_payload = json.loads(
        (
            world.materialized_root / TWIN_KEY / revision_id
            / "runtime" / "navigation_transitions.json"
        ).read_text(encoding="utf-8")
    )

    candidate_ids = {
        transition["candidate_id"]
        for transition in transitions_payload["transitions"]
    }

    assert world.candidate_id in candidate_ids

    # Privacy: only the structural selector is ever materialized.
    serialized = json.dumps(transitions_payload)
    assert "SECRET" not in serialized


# ---------------------------------------------------------
# Twin authority resolution: fail-closed, backend-owned.
# ---------------------------------------------------------


def test_artifact_enqueue_for_unknown_capture_fails_closed(world):
    result = _qcc_schedule_auto_twin_materialization_after_artifact(
        server=world.server,
        capture_id="cap-never-observed",
    )

    assert result["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    assert result["reason"] == "TRIGGER_NOT_LINKED_TO_OBSERVED_TWIN"
    assert world.calls == []


def test_unique_capture_resolves_to_its_twin(world):
    resolved = (
        world.observation_store
        .resolve_twin_key_for_capture("cap-B-Y")
    )

    assert resolved == TWIN_KEY


def test_ambiguous_capture_fails_closed(world):
    # A second managed twin, sharing origin, independently observes a
    # state using the EXACT SAME capture_id -- an integrity edge case
    # the resolver must never silently resolve either way.
    other_site = AutoTwinManagedSite(
        twin_key="mercurio_other",
        site_code="MERCURIO_OTHER",
        origins=(ORIGIN,),
    )

    world.managed_store.register(other_site)

    _observe(
        world.observation_store, other_site,
        capture_id="cap-B-Y", fingerprint=FP_B,
        pathname="/mercurio/other.html", second=9,
    )

    resolved = (
        world.observation_store
        .resolve_twin_key_for_capture("cap-B-Y")
    )

    assert resolved is None

    result = _qcc_schedule_auto_twin_materialization_after_artifact(
        server=world.server,
        capture_id="cap-B-Y",
    )

    assert result["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    assert result["reason"] == "TRIGGER_NOT_LINKED_TO_OBSERVED_TWIN"
    assert world.calls == []


def test_resolver_ignores_superseded_states(world):
    site = world.managed_store.get(TWIN_KEY)

    snapshot = world.observation_store.snapshot(TWIN_KEY)
    state_key = next(iter(snapshot["twin"]["states"]))

    # Supersede the only state referencing cap-A-0: the resolver must
    # only ever see CURRENT/ACTIVE observation state, exactly like the
    # reconciler itself.
    world.observation_store.supersede(
        site,
        old_state_key=state_key,
        replacement_state_keys=[
            next(
                key
                for key in snapshot["twin"]["states"]
                if key != state_key
            )
        ],
        reason="TEST_SUPERSESSION",
    )

    assert (
        world.observation_store
        .resolve_twin_key_for_capture("cap-A-0")
        is None
    )


# ---------------------------------------------------------
# Threading contract: never reconcile in the request thread.
# ---------------------------------------------------------


def test_no_materialization_runs_in_artifact_request_thread(
    world, monkeypatch
):
    threads = []

    def fake(**kwargs):
        threads.append(threading.current_thread())
        return {"status": "NO_CHANGE"}

    monkeypatch.setattr(
        auto_materialization,
        "reconcile_auto_twin_discovery_materialization",
        fake,
    )

    calls = []
    coordinator = _attach_recording_coordinator(world.server, calls)

    scheduled = _qcc_schedule_auto_twin_materialization_after_artifact(
        server=world.server,
        capture_id="cap-B-Y",
    )

    assert scheduled["status"] == "QUEUED"

    # Nothing has reconciled synchronously in THIS (the calling) thread.
    assert threads == []

    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    assert len(threads) == 1
    assert threads[0] is not threading.current_thread()
    assert threads[0].daemon is True


def test_multiple_concurrent_artifact_events_do_not_produce_unbounded_jobs(
    world,
):
    entered = threading.Event()
    release = threading.Event()

    coordinator = _attach_recording_coordinator(
        world.server,
        world.calls,
        pause={
            "at_call": 1,
            "entered": entered,
            "release": release,
        },
    )

    first = _qcc_schedule_auto_twin_materialization_after_artifact(
        server=world.server,
        capture_id="cap-B-Y",
    )

    assert first["status"] == "QUEUED"
    assert entered.wait(timeout=TIMEOUT)

    # A burst of further artifact-completion triggers for the SAME
    # twin, all arriving while the first job is still running.
    schedules = [
        _qcc_schedule_auto_twin_materialization_after_artifact(
            server=world.server,
            capture_id="cap-B-Y",
        )
        for _ in range(10)
    ]

    assert schedules[0]["status"] == "QUEUED"
    assert all(item["status"] == "COALESCED" for item in schedules[1:])
    assert coordinator.snapshot()["pending_count"] == 1

    release.set()
    assert coordinator.wait_until_idle(timeout=TIMEOUT)

    # Current job + exactly ONE coalesced follow-up: never unbounded.
    assert len(world.calls) == 2


# ---------------------------------------------------------
# Two-pass materialization gate stays untouched (guard test).
# ---------------------------------------------------------


def test_transition_is_not_eligible_until_both_endpoints_are_physical(
    world,
):
    """Sanity guard: pass 1 and pass 2 remain conservative and split.

    A single reconcile call against a capture whose new state has just
    become complete must materialize the new physical state WITHOUT
    also inventing the transition in that SAME pass -- the transition
    only becomes eligible once the new state exists in the immutable
    latest revision (proving FIX1 did not weaken
    _navigation_refresh_for_latest_revision()).
    """

    _add_capture_artifact(world.captures, "cap-B-Y", "page.mhtml")
    _add_capture_artifact(
        world.captures, "cap-B-Y", "screenshot_viewport.png"
    )

    from backend.qcc.auto_twin.automatic_materialization import (
        reconcile_auto_twin_discovery_materialization,
    )

    first_pass = reconcile_auto_twin_discovery_materialization(
        managed_site_store=world.managed_store,
        observation_store=world.observation_store,
        capture_root=world.captures,
        trigger_capture_id="cap-B-Y",
        twin_key=TWIN_KEY,
        materialized_root=world.materialized_root,
        human_navigation_candidate_store=world.candidate_store,
    )

    assert first_pass["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED

    first_transitions = json.loads(
        (
            world.materialized_root / TWIN_KEY
            / first_pass["materialized_revision_id"]
            / "runtime" / "navigation_transitions.json"
        ).read_text(encoding="utf-8")
    )

    assert first_transitions["transition_count"] == 0

    second_pass = reconcile_auto_twin_discovery_materialization(
        managed_site_store=world.managed_store,
        observation_store=world.observation_store,
        capture_root=world.captures,
        trigger_capture_id="cap-B-Y",
        twin_key=TWIN_KEY,
        materialized_root=world.materialized_root,
        human_navigation_candidate_store=world.candidate_store,
    )

    assert second_pass["status"] == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    assert (
        second_pass["materialized_revision_id"]
        != first_pass["materialized_revision_id"]
    )

    second_transitions = json.loads(
        (
            world.materialized_root / TWIN_KEY
            / second_pass["materialized_revision_id"]
            / "runtime" / "navigation_transitions.json"
        ).read_text(encoding="utf-8")
    )

    assert second_transitions["transition_count"] == 1
    assert (
        second_transitions["transitions"][0]["candidate_id"]
        == world.candidate_id
    )
