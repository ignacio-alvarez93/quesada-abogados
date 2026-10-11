from pathlib import Path
from types import SimpleNamespace
import json

import pytest


from backend.qcc.auto_twin.automatic_materialization import (
    AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED,
    AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE,
    AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED,
    AUTO_TWIN_AUTO_MATERIALIZATION_WAITING,
    REQUIRED_ARTIFACTS,
    reconcile_auto_twin_discovery_materialization,
)

from backend.qcc.auto_twin.materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
    AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION,
    AUTO_TWIN_MATERIALIZATION_MODES,
)


ROOT = Path(__file__).resolve().parents[2]

BRIDGE = (
    ROOT
    / "backend"
    / "qcc"
    / "bridge"
    / "server.py"
)


class ManagedStore:
    def get(
        self,
        twin_key,
    ):
        if twin_key != "red_sara":
            return None

        return SimpleNamespace(
            twin_key=(
                "red_sara"
            ),
            site_code=(
                "RED_SARA"
            ),
            origins=(
                "https://reg.redsara.es",
            ),
            enabled=True,
            auto_update=True,
            discover_unknown_states=True,
        )


class ObservationStore:
    def __init__(
        self,
        states,
        *,
        supersessions=None,
    ):
        self.states = states

        self.supersessions = (
            supersessions
            or {}
        )

    def snapshot(
        self,
        twin_key=None,
        *,
        current_only=False,
    ):
        # This fixture applies current_only the same way
        # AutoTwinObservationStore does: filter states, but keep the
        # supersessions registry visible either way (historical reads
        # need it too).
        states = self.states

        if (
            current_only
            and self.supersessions
        ):
            states = {
                key: value
                for key, value in states.items()
                if key not in self.supersessions
            }

        return {
            "twins": {
                "red_sara": {
                    "twin_key":
                        "red_sara",

                    "states":
                        states,

                    "supersessions":
                        self.supersessions,
                }
            }
        }


class RevisionStore:
    def __init__(
        self,
        revisions=None,
    ):
        self.revisions = list(
            revisions
            or []
        )

    def list(
        self,
        *,
        twin_key=None,
    ):
        return [
            revision
            for revision
            in self.revisions
            if (
                twin_key is None
                or revision.get(
                    "twin_key"
                )
                == twin_key
            )
        ]


def state(
    key,
    pathname,
    capture_id,
):
    return {
        "state_key":
            key,

        "pathname":
            pathname,

        "functional_state":
            None,

        "baseline_capture_id":
            capture_id,

        "last_capture_id":
            capture_id,

        "first_seen_at":
            (
                "2026-09-05T15:00:00Z"
                + key[:1]
            ),
    }


def write_capture(
    root,
    capture_id,
    *,
    omit=(),
    browser_profile_key="twin_discovery",
):
    directory = (
        root
        / capture_id
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    omit = set(
        omit
    )

    for filename in REQUIRED_ARTIFACTS:
        if filename in omit:
            continue

        path = (
            directory
            / filename
        )

        if filename == "qcc_capture.json":
            path.write_text(
                json.dumps({
                    "browser_profile_key":
                        browser_profile_key,
                }),
                encoding="utf-8",
            )

        elif filename.endswith(
            ".png"
        ):
            path.write_bytes(
                b"\x89PNG\r\n\x1a\nTEST"
            )

        else:
            path.write_text(
                "{}",
                encoding="utf-8",
            )


def plan_spy(
    calls,
):
    def build(
        **kwargs,
    ):
        calls.append(
            kwargs
        )

        return {
            "plan_id":
                "matplan-test",

            "twin_key":
                kwargs[
                    "twin_key"
                ],

            "materialization_mode":
                kwargs[
                    "materialization_mode"
                ],

            "state_sources":
                list(
                    kwargs[
                        "state_sources"
                    ]
                ),
        }

    return build


def materializer_spy(
    calls,
):
    def build(
        **kwargs,
    ):
        calls.append(
            kwargs
        )

        plan = kwargs[
            "plan"
        ]

        manifest = [
            {
                "state_id":
                    item[
                        "state_id"
                    ],

                "source_capture_id":
                    item[
                        "capture_id"
                    ],

                "pathname":
                    item[
                        "pathname"
                    ],

                "functional_state":
                    item.get(
                        "functional_state"
                    ),
            }
            for item
            in plan[
                "state_sources"
            ]
        ]

        return {
            "revision": {
                "materialized_revision_id":
                    (
                        "matrev-test-"
                        + str(
                            len(
                                manifest
                            )
                        )
                    ),

                "materialization_mode":
                    plan[
                        "materialization_mode"
                    ],

                "state_manifest":
                    manifest,
            }
        }

    return build


def test_discovery_extension_is_explicit_mode():
    assert (
        AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION
        == "DISCOVERY_EXTENSION"
    )

    assert (
        AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION
        in AUTO_TWIN_MATERIALIZATION_MODES
    )


def test_first_complete_discovery_builds_bootstrap(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-a",
    )

    write_capture(
        captures,
        "cap-b",
    )

    states = {
        "a" * 64:
            state(
                "a" * 64,
                "/es/",
                "cap-a",
            ),

        "b" * 64:
            state(
                "b" * 64,
                "/es/nuevo-registro",
                "cap-b",
            ),
    }

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-b"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore()
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy(
                    build_calls
                )
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    assert (
        result[
            "materialization_mode"
        ]
        == AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
    )

    assert (
        result[
            "state_count"
        ]
        == 2
    )

    assert (
        result[
            "added_state_count"
        ]
        == 2
    )

    assert len(
        plan_calls
    ) == 1

    assert len(
        build_calls
    ) == 1


# QCC_ASSISTED_POLICY_AUTOTWIN_V3: qcc_assisted passively observes
# managed Twins (see test_qcc_auto_twin_profile_policy.py), but that
# passive observation must never, by itself, escalate into automatic
# materialization or Twin runtime validation. Mirrors the bootstrap
# scenario above exactly, except the trigger capture's OWN persisted
# browser_profile_key is "qcc_assisted" instead of "twin_discovery".
def test_qcc_assisted_trigger_capture_never_auto_materializes(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-a",
    )

    write_capture(
        captures,
        "cap-b",
        browser_profile_key="qcc_assisted",
    )

    states = {
        "a" * 64:
            state(
                "a" * 64,
                "/es/",
                "cap-a",
            ),

        "b" * 64:
            state(
                "b" * 64,
                "/es/nuevo-registro",
                "cap-b",
            ),
    }

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-b"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore()
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy(
                    build_calls
                )
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    )

    assert (
        result[
            "reason"
        ]
        == "TRIGGER_PROFILE_NOT_AUTHORIZED_FOR_AUTO_MATERIALIZATION"
    )

    # Knowledge != execution: the plan/materializer are never invoked.
    assert plan_calls == []
    assert build_calls == []


# A capture that resolves to an ALREADY-known/materialized state (no
# new content at all) never reaches the deeper, mode-specific
# "selected evidence capture" profile check -- it would otherwise
# fall straight through to NO_CHANGE, which the Bridge explicitly
# treats as eligible to re-enqueue Twin navigation validation (see
# ``_qcc_project_auto_twin_materialization_after_artifact``). This is
# the exact leak the escalation boundary closes: a purely passive
# qcc_assisted observation must never reach NO_CHANGE either.
def test_qcc_assisted_known_state_trigger_never_reaches_no_change(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-a",
        browser_profile_key="qcc_assisted",
    )

    key = "a" * 64

    states = {
        key:
            state(
                key,
                "/es/",
                "cap-a",
            )
    }

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    "RED_SARA_HOME",

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    None,
            }
        ],
    }

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-a"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy([])
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    )

    assert (
        result[
            "reason"
        ]
        == "TRIGGER_PROFILE_NOT_AUTHORIZED_FOR_AUTO_MATERIALIZATION"
    )


# QCC_ASSISTED_REAL_SMOKE_V4: ``twin_key is not None`` is NEVER, by
# itself, proof of explicit human/operator Twin authority. The Bridge's
# own artifact-trigger scheduler
# (``_qcc_schedule_auto_twin_materialization_after_artifact``) resolves
# a twin_key AUTOMATICALLY from a capture's own observed link and hands
# it down explicitly -- exactly the REAL smoke's bypass. A
# qcc_assisted-profiled trigger capture must stay blocked even when a
# caller supplies that twin_key explicitly: only the trigger capture's
# OWN recorded browser_profile_key is trusted provenance.
def test_explicit_twin_key_does_not_bypass_trigger_profile_check(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-a",
    )

    write_capture(
        captures,
        "cap-b",
        browser_profile_key="qcc_assisted",
    )

    states = {
        "a" * 64:
            state(
                "a" * 64,
                "/es/",
                "cap-a",
            ),

        "b" * 64:
            state(
                "b" * 64,
                "/es/nuevo-registro",
                "cap-b",
            ),
    }

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-b"
            ),
            twin_key="red_sara",
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore()
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy(
                    build_calls
                )
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    )

    assert (
        result[
            "reason"
        ]
        == "TRIGGER_PROFILE_NOT_AUTHORIZED_FOR_AUTO_MATERIALIZATION"
    )

    assert plan_calls == []
    assert build_calls == []


# Explicit human-confirmed Twin authority (a caller-supplied
# ``twin_key``, e.g. post-learning reconciliation) still works exactly
# as before when the trigger capture's OWN recorded profile is
# genuinely authorized (``twin_discovery``): the provenance fix above
# only closes the qcc_assisted leak, it never blocks a legitimately
# Discovery-profiled trigger.
def test_explicit_twin_key_with_authorized_trigger_profile_still_proceeds(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-a",
    )

    write_capture(
        captures,
        "cap-b",
    )

    states = {
        "a" * 64:
            state(
                "a" * 64,
                "/es/",
                "cap-a",
            ),

        "b" * 64:
            state(
                "b" * 64,
                "/es/nuevo-registro",
                "cap-b",
            ),
    }

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-b"
            ),
            twin_key="red_sara",
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore()
            ),
            plan_builder=(
                plan_spy([])
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "reason"
        ]
        != "TRIGGER_PROFILE_NOT_AUTHORIZED_FOR_AUTO_MATERIALIZATION"
    )


def test_known_state_does_not_create_revision(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-a",
    )

    key = (
        "a"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/",
                "cap-a",
            )
    }

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    "RED_SARA_HOME",

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    None,
            }
        ],
    }

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-a"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy([])
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )


def test_new_state_creates_discovery_extension(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-a",
    )

    write_capture(
        captures,
        "cap-b",
    )

    key_a = (
        "a"
        * 64
    )

    key_b = (
        "b"
        * 64
    )

    states = {
        key_a:
            state(
                key_a,
                "/es/",
                "cap-a",
            ),

        key_b:
            state(
                key_b,
                "/es/nuevo-registro",
                "cap-b",
            ),
    }

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    "RED_SARA_HOME",

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    None,
            }
        ],
    }

    plan_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-b"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    assert (
        result[
            "materialization_mode"
        ]
        == AUTO_TWIN_MATERIALIZATION_MODE_DISCOVERY_EXTENSION
    )

    assert (
        result[
            "added_state_count"
        ]
        == 1
    )

    assert (
        result[
            "state_count"
        ]
        == 2
    )


def test_incomplete_bundle_waits(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-a",
        omit={
            "page.mhtml",
        },
    )

    key = (
        "a"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/",
                "cap-a",
            )
    }

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-a"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore()
            ),
            plan_builder=(
                plan_spy([])
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_WAITING
    )

    assert (
        "page.mhtml"
        in result[
            "reason"
        ]
    )


def test_bridge_hooks_page_and_viewport():
    text = BRIDGE.read_text(
        encoding="utf-8"
    )

    assert (
        "QCC_AUTO_TWIN_AUTOMATIC_MATERIALIZATION_HOOK_V1"
        in text
    )

    assert (
        "QCC_AUTO_TWIN_ARTIFACT_COMPLETION_COORDINATOR_V1"
        in text
    )

    schedule_helper = (
        "_qcc_schedule_auto_twin_materialization_after_artifact("
    )

    process_helper = (
        "_qcc_project_auto_twin_materialization_after_artifact("
    )

    page_start = text.index(
        "POST /qcc/site-architecture/page-artifact"
    )

    visual_start = text.index(
        "POST /qcc/site-architecture/visual-artifact",
        page_start,
    )

    capture_start = text.index(
        "POST /qcc/site-architecture/capture",
        visual_start,
    )

    page = text[
        page_start:
        visual_start
    ]

    visual = text[
        visual_start:
        capture_start
    ]

    # Deep-artifact HTTP hooks only ever SCHEDULE a coordinator job --
    # synchronous in-request reconciliation must never be restored.
    assert schedule_helper in page
    assert schedule_helper in visual
    assert process_helper not in page
    assert process_helper not in visual

    # The REAL synchronous reconciling processor exists exactly once
    # (its own definition) and is used exactly once: bound as the
    # AutoTwinMaterializationCoordinator's default processor.
    assert text.count(process_helper) == 2

    processor_def_start = text.index(
        "def auto_twin_materialization_processor("
    )

    coordinator_wiring_start = text.index(
        "AutoTwinMaterializationCoordinator(",
        processor_def_start,
    )

    assert (
        process_helper
        in text[
            processor_def_start:
            coordinator_wiring_start
        ]
    )



# =============================================================================
# Renderer refresh source rebinding
# =============================================================================


def _write_physical_renderer_marker(
    materialized_root,
    revision_id,
    renderer_version,
    *,
    navigation_adapter_version=None,
):
    from backend.qcc.auto_twin.navigation_transition_runtime import (
        AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,
        AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME,
    )

    from backend.qcc.auto_twin.runtime_network_sterilization import (
        AUTO_TWIN_NETWORK_STERILIZER_VERSION,
    )

    runtime_dir = (
        materialized_root
        / "red_sara"
        / revision_id
        / "runtime"
    )

    runtime_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        runtime_dir
        / "renderer.json"
    ).write_text(
        json.dumps({
            "renderer_version":
                renderer_version,

            # This helper's own concern is renderer/navigation
            # refresh-source rebinding, never the sterilizer
            # dimension -- keep it current so every call site here
            # stays physically current in that independent axis.
            "network_sterilizer_version":
                AUTO_TWIN_NETWORK_STERILIZER_VERSION,
        }),
        encoding="utf-8",
    )

    if navigation_adapter_version is None:
        navigation_adapter_version = (
            AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION
        )

    (
        runtime_dir
        / AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME
    ).write_text(
        json.dumps({
            "adapter_version":
                navigation_adapter_version,
        }),
        encoding="utf-8",
    )


def test_renderer_refresh_rebinds_only_trigger_existing_state_source(
    tmp_path,
):
    import backend.qcc.auto_twin.automatic_materialization as auto_module

    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    write_capture(
        captures,
        "cap-home",
    )

    write_capture(
        captures,
        "cap-old",
    )

    write_capture(
        captures,
        "cap-fresh",
    )

    key_home = (
        "a"
        * 64
    )

    key_register = (
        "b"
        * 64
    )

    state_id_home = (
        auto_module._state_id(
            key_home
        )
    )

    state_id_register = (
        auto_module._state_id(
            key_register
        )
    )

    states = {
        key_home:
            state(
                key_home,
                "/es/",
                "cap-home",
            ),

        key_register:
            state(
                key_register,
                "/es/nuevo-registro",
                "cap-old",
            ),
    }

    # La identidad no cambia.
    # Sólo existe evidencia más reciente.
    states[
        key_register
    ][
        "last_capture_id"
    ] = "cap-fresh"

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    state_id_home,

                "source_capture_id":
                    "cap-home",

                "pathname":
                    "/es/",

                "functional_state":
                    None,
            },
            {
                "state_id":
                    state_id_register,

                "source_capture_id":
                    "cap-old",

                "pathname":
                    "/es/nuevo-registro",

                "functional_state":
                    None,
            },
        ],
    }

    _write_physical_renderer_marker(
        materialized,
        "matrev-old",
        (
            AUTO_TWIN_RUNTIME_RENDERER_VERSION
            - 1
        ),
    )

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-fresh"
            ),
            materialized_root=(
                materialized
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy(
                    build_calls
                )
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    assert (
        result[
            "added_state_count"
        ]
        == 0
    )

    assert len(
        plan_calls
    ) == 1

    sources = {
        item[
            "pathname"
        ]:
            item
        for item in plan_calls[
            0
        ][
            "state_sources"
        ]
    }

    # Estado no relacionado conserva exactamente
    # su source previo.
    assert (
        sources[
            "/es/"
        ][
            "capture_id"
        ]
        == "cap-home"
    )

    assert (
        sources[
            "/es/"
        ][
            "state_id"
        ]
        == state_id_home
    )

    # El estado del trigger conserva state_id,
    # pero Renderer refresh utiliza last_capture_id.
    assert (
        sources[
            "/es/nuevo-registro"
        ][
            "capture_id"
        ]
        == "cap-fresh"
    )

    assert (
        sources[
            "/es/nuevo-registro"
        ][
            "state_id"
        ]
        == state_id_register
    )

    # Renderer-only refresh conserva el modo
    # histórico de la revisión.
    assert (
        plan_calls[
            0
        ][
            "materialization_mode"
        ]
        == "BOOTSTRAP_REAL"
    )


def test_current_renderer_known_last_capture_remains_no_change(
    tmp_path,
):
    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    write_capture(
        captures,
        "cap-old",
    )

    write_capture(
        captures,
        "cap-fresh",
    )

    key = (
        "c"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/nuevo-registro",
                "cap-old",
            )
    }

    states[
        key
    ][
        "last_capture_id"
    ] = "cap-fresh"

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-current",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    "RED_SARA_REGISTER",

                "source_capture_id":
                    "cap-old",

                "pathname":
                    "/es/nuevo-registro",

                "functional_state":
                    None,
            }
        ],
    }

    _write_physical_renderer_marker(
        materialized,
        "matrev-current",
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-fresh"
            ),
            materialized_root=(
                materialized
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy(
                    build_calls
                )
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )

    assert plan_calls == []
    assert build_calls == []


# =============================================================================
# WO 2D-20O: carry-forward consults governed supersession/current
# eligibility BEFORE previous identities/state_ids/fingerprints are
# inserted into the carry-forward sets.
# =============================================================================


def _write_registry(
    materialized_root,
    revision_id,
    states,
    *,
    twin_key="red_sara",
):
    runtime_dir = (
        materialized_root
        / twin_key
        / revision_id
        / "runtime"
    )

    runtime_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        runtime_dir
        / "registry.json"
    ).write_text(
        json.dumps({
            "states":
                list(
                    states
                ),
        }),
        encoding="utf-8",
    )


def test_renderer_refresh_does_not_use_non_trigger_last_capture(
    tmp_path,
):
    import backend.qcc.auto_twin.automatic_materialization as auto_module

    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    for capture_id in (
        "cap-a-old",
        "cap-a-new",
        "cap-b-old",
        "cap-b-new",
    ):
        write_capture(
            captures,
            capture_id,
        )

    key_a = (
        "d"
        * 64
    )

    key_b = (
        "e"
        * 64
    )

    state_id_a = (
        auto_module._state_id(
            key_a
        )
    )

    state_id_b = (
        auto_module._state_id(
            key_b
        )
    )

    states = {
        key_a:
            state(
                key_a,
                "/es/a",
                "cap-a-old",
            ),

        key_b:
            state(
                key_b,
                "/es/b",
                "cap-b-old",
            ),
    }

    states[
        key_a
    ][
        "last_capture_id"
    ] = "cap-a-new"

    states[
        key_b
    ][
        "last_capture_id"
    ] = "cap-b-new"

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "DISCOVERY_EXTENSION",

        "state_manifest": [
            {
                "state_id":
                    state_id_a,

                "source_capture_id":
                    "cap-a-old",

                "pathname":
                    "/es/a",

                "functional_state":
                    None,
            },
            {
                "state_id":
                    state_id_b,

                "source_capture_id":
                    "cap-b-old",

                "pathname":
                    "/es/b",

                "functional_state":
                    None,
            },
        ],
    }

    _write_physical_renderer_marker(
        materialized,
        "matrev-old",
        (
            AUTO_TWIN_RUNTIME_RENDERER_VERSION
            - 1
        ),
    )

    plan_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-b-new"
            ),
            materialized_root=(
                materialized
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    sources = {
        item[
            "pathname"
        ]:
            item[
                "capture_id"
            ]
        for item in plan_calls[
            0
        ][
            "state_sources"
        ]
    }

    # Aunque A también tenga last_capture_id más nuevo,
    # no se migra porque no es el trigger actual.
    assert (
        sources[
            "/es/a"
        ]
        == "cap-a-old"
    )

    assert (
        sources[
            "/es/b"
        ]
        == "cap-b-new"
    )



# F3C2-A4.3B2C CATALOG REFRESH INTEGRATION


def _b2_write_catalog_surface_capture(
    captures,
    capture_id,
):
    """Fixture B2: capture QCC que declara catálogo disponible.

    El contenido real del catálogo no importa en estos tests porque
    decide_catalog_refresh está monkeypatcheado. Lo importante es que
    el reconciler no lo clasifique como capture legacy/pre-catalog.
    """

    write_capture(
        captures,
        capture_id,
    )

    qcc_path = (
        captures
        / capture_id
        / "qcc_capture.json"
    )

    qcc_path.write_text(
        json.dumps({
            "browser_profile_key":
                "twin_discovery",

            "frames": [
                {
                    "frame_id":
                        0,

                    "result": {
                        "pathname":
                            "/es/nuevo-registro",

                        "catalog_probe": {
                            "schema_version":
                                1,

                            "catalog_count":
                                1,

                            "native_catalog_count":
                                0,

                            "custom_catalog_count":
                                1,

                            "elements":
                                [],
                        },
                    },
                },
            ],
        }),
        encoding="utf-8",
    )




def test_catalog_refresh_reuses_visual_source_and_adds_catalog_source(
    tmp_path,
    monkeypatch,
):
    import backend.qcc.auto_twin.automatic_materialization as auto_module

    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    from backend.qcc.auto_twin.materialized_revision import (
        AUTO_TWIN_MATERIALIZATION_MODE_CATALOG_REFRESH,
    )

    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    write_capture(
        captures,
        "cap-visual",
    )

    _b2_write_catalog_surface_capture(
        captures,
        "cap-catalog",
    )

    key = (
        "e"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/nuevo-registro",
                "cap-visual",
            )
    }

    states[
        key
    ][
        "last_capture_id"
    ] = "cap-catalog"

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    "STATE_EXISTING",

                "source_capture_id":
                    "cap-visual",

                "pathname":
                    "/es/nuevo-registro",

                "functional_state":
                    None,
            }
        ],
    }

    _write_physical_renderer_marker(
        materialized,
        "matrev-old",
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    monkeypatch.setattr(
        auto_module,
        "materialized_catalog_provenance",
        lambda **kwargs: {},
    )

    monkeypatch.setattr(
        auto_module,
        "decide_catalog_refresh",
        lambda **kwargs: {
            "status":
                "REFRESH_REQUIRED",

            "reason":
                "CATALOG_NOT_MATERIALIZED",
        },
    )

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-catalog"
            ),
            materialized_root=(
                materialized
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy(
                    build_calls
                )
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    assert (
        plan_calls[
            0
        ][
            "materialization_mode"
        ]
        == AUTO_TWIN_MATERIALIZATION_MODE_CATALOG_REFRESH
    )

    sources = (
        plan_calls[
            0
        ][
            "state_sources"
        ]
    )

    assert len(
        sources
    ) == 1

    assert (
        sources[
            0
        ][
            "state_id"
        ]
        == "STATE_EXISTING"
    )

    # Fuente visual permanece intacta.
    assert (
        sources[
            0
        ][
            "capture_id"
        ]
        == "cap-visual"
    )

    # Evidencia catalogal es suplementaria.
    assert (
        sources[
            0
        ][
            "catalog_capture_id"
        ]
        == "cap-catalog"
    )


def test_catalog_refresh_same_fingerprint_remains_no_change(
    tmp_path,
    monkeypatch,
):
    import backend.qcc.auto_twin.automatic_materialization as auto_module

    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    write_capture(
        captures,
        "cap-visual",
    )

    _b2_write_catalog_surface_capture(
        captures,
        "cap-catalog",
    )

    key = (
        "f"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/nuevo-registro",
                "cap-visual",
            )
    }

    states[
        key
    ][
        "last_capture_id"
    ] = "cap-catalog"

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    "STATE_EXISTING",

                "source_capture_id":
                    "cap-visual",

                "pathname":
                    "/es/nuevo-registro",

                "functional_state":
                    None,
            }
        ],
    }

    _write_physical_renderer_marker(
        materialized,
        "matrev-old",
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    monkeypatch.setattr(
        auto_module,
        "materialized_catalog_provenance",
        lambda **kwargs: {},
    )

    monkeypatch.setattr(
        auto_module,
        "decide_catalog_refresh",
        lambda **kwargs: {
            "status":
                "NO_CHANGE",

            "reason":
                "CATALOG_FINGERPRINT_UNCHANGED",
        },
    )

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-catalog"
            ),
            materialized_root=(
                materialized
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy(
                    build_calls
                )
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )

    assert plan_calls == []
    assert build_calls == []


# =============================================================================
# WO 2D-20O: carry-forward consults governed supersession/current
# eligibility BEFORE previous identities/state_ids/fingerprints are
# inserted into the carry-forward sets.
# =============================================================================


def test_superseded_previous_state_excluded_from_carry_forward(
    tmp_path,
):
    import backend.qcc.auto_twin.automatic_materialization as auto_module

    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    write_capture(
        captures,
        "cap-old",
    )

    write_capture(
        captures,
        "cap-keep",
    )

    write_capture(
        captures,
        "cap-new",
    )

    old_key = "0" * 64
    old_state_id = (
        auto_module._state_id(
            old_key
        )
    )

    new_key = "1" * 64

    states = {
        new_key:
            state(
                new_key,
                "/es/nuevo",
                "cap-new",
            ),
    }

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    old_state_id,

                "source_capture_id":
                    "cap-old",

                "pathname":
                    "/es/personal",

                "functional_state":
                    "PERSONAL",
            },
            {
                "state_id":
                    "RED_SARA_HOME",

                "source_capture_id":
                    "cap-keep",

                "pathname":
                    "/es/",

                "functional_state":
                    None,
            },
        ],
    }

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states,
                    supersessions={
                        old_key: {
                            "old_state_key":
                                old_key,

                            "replacement_state_keys":
                                [
                                    new_key,
                                ],
                        },
                    },
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-new"
            ),
            materialized_root=(
                materialized
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy(
                    build_calls
                )
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    assert (
        result[
            "added_state_count"
        ]
        == 1
    )

    state_ids_in_plan = {
        item[
            "state_id"
        ]
        for item in plan_calls[
            0
        ][
            "state_sources"
        ]
    }

    assert old_state_id not in state_ids_in_plan
    assert "RED_SARA_HOME" in state_ids_in_plan

    # The superseded previous record itself is never mutated.
    assert len(
        previous[
            "state_manifest"
        ]
    ) == 2


def test_superseded_fingerprint_does_not_block_replacement_uniqueness(
    tmp_path,
):
    import backend.qcc.auto_twin.automatic_materialization as auto_module

    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    write_capture(
        captures,
        "cap-old",
    )

    write_capture(
        captures,
        "cap-new",
    )

    old_key = "2" * 64
    old_state_id = (
        auto_module._state_id(
            old_key
        )
    )

    shared_fingerprint = "f" * 64

    new_key = "3" * 64

    new_state = state(
        new_key,
        "/es/otra-pagina",
        "cap-new",
    )

    # Deliberately reuses the SAME physical fingerprint the superseded
    # legacy state was materialized with -- proves it no longer blocks
    # through physical_fingerprints uniqueness.
    new_state[
        "last_fingerprint"
    ] = shared_fingerprint

    states = {
        new_key:
            new_state,
    }

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    old_state_id,

                "source_capture_id":
                    "cap-old",

                "pathname":
                    "/es/personal",

                "functional_state":
                    "PERSONAL",
            },
        ],
    }

    _write_registry(
        materialized,
        "matrev-old",
        [
            {
                "state_id":
                    old_state_id,

                "fingerprint":
                    shared_fingerprint,

                "functional_state":
                    "PERSONAL",
            },
        ],
    )

    plan_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states,
                    supersessions={
                        old_key: {
                            "old_state_key":
                                old_key,

                            "replacement_state_keys":
                                [
                                    new_key,
                                ],
                        },
                    },
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-new"
            ),
            materialized_root=(
                materialized
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    assert (
        result[
            "added_state_count"
        ]
        == 1
    )

    pathnames_in_plan = {
        item[
            "pathname"
        ]
        for item in plan_calls[
            0
        ][
            "state_sources"
        ]
    }

    assert "/es/otra-pagina" in pathnames_in_plan


def test_non_superseded_states_still_carry_forward_unchanged(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    write_capture(
        captures,
        "cap-a",
    )

    write_capture(
        captures,
        "cap-b",
    )

    write_capture(
        captures,
        "cap-new",
    )

    key_new = "4" * 64

    states = {
        key_new:
            state(
                key_new,
                "/es/nuevo",
                "cap-new",
            ),
    }

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    "STATE_A",

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/a",

                "functional_state":
                    None,
            },
            {
                "state_id":
                    "STATE_B",

                "source_capture_id":
                    "cap-b",

                "pathname":
                    "/es/b",

                "functional_state":
                    None,
            },
        ],
    }

    plan_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states,
                    supersessions={},
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-new"
            ),
            materialized_root=(
                materialized
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    sources = {
        item[
            "state_id"
        ]: item
        for item in plan_calls[
            0
        ][
            "state_sources"
        ]
    }

    assert (
        sources[
            "STATE_A"
        ][
            "capture_id"
        ]
        == "cap-a"
    )

    assert (
        sources[
            "STATE_B"
        ][
            "capture_id"
        ]
        == "cap-b"
    )


def test_one_to_many_replacements_planned_with_distinct_state_ids(
    tmp_path,
):
    import backend.qcc.auto_twin.automatic_materialization as auto_module

    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    write_capture(
        captures,
        "cap-old",
    )

    write_capture(
        captures,
        "cap-titular",
    )

    write_capture(
        captures,
        "cap-familiar",
    )

    old_key = "5" * 64
    old_state_id = (
        auto_module._state_id(
            old_key
        )
    )

    titular_key = "6" * 64
    familiar_key = "7" * 64

    shared_pathname = (
        "/es/personal"
    )

    states = {
        titular_key:
            state(
                titular_key,
                shared_pathname,
                "cap-titular",
            ),

        familiar_key:
            state(
                familiar_key,
                shared_pathname,
                "cap-familiar",
            ),
    }

    # Both variants share the SAME (pathname, functional_state) as the
    # legacy collided identity -- exactly the real 130/131 shape.
    states[
        titular_key
    ][
        "functional_state"
    ] = "PERSONAL"

    states[
        familiar_key
    ][
        "functional_state"
    ] = "PERSONAL"

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    old_state_id,

                "source_capture_id":
                    "cap-old",

                "pathname":
                    shared_pathname,

                "functional_state":
                    "PERSONAL",
            },
        ],
    }

    plan_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states,
                    supersessions={
                        old_key: {
                            "old_state_key":
                                old_key,

                            "replacement_state_keys":
                                [
                                    titular_key,
                                    familiar_key,
                                ],
                        },
                    },
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-titular"
            ),
            materialized_root=(
                materialized
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    sources = plan_calls[
        0
    ][
        "state_sources"
    ]

    matching = [
        item
        for item in sources
        if item.get(
            "pathname"
        )
        == shared_pathname
    ]

    # Both variants planned, each with its own distinct new state_id --
    # neither equal to each other nor to the superseded legacy one.
    assert len(
        matching
    ) == 2

    state_ids = {
        item[
            "state_id"
        ]
        for item in matching
    }

    assert len(
        state_ids
    ) == 2

    assert old_state_id not in state_ids


def test_unrelated_supersession_does_not_affect_other_previous_states(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    write_capture(
        captures,
        "cap-a",
    )

    write_capture(
        captures,
        "cap-new",
    )

    key_new = "8" * 64

    states = {
        key_new:
            state(
                key_new,
                "/es/nuevo",
                "cap-new",
            ),
    }

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    "STATE_A",

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/a",

                "functional_state":
                    None,
            },
        ],
    }

    # Supersession referencing a state_key that has nothing to do
    # with any previous state actually present here.
    unrelated_key = "9" * 64

    plan_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states,
                    supersessions={
                        unrelated_key: {
                            "old_state_key":
                                unrelated_key,

                            "replacement_state_keys":
                                [
                                    key_new,
                                ],
                        },
                    },
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-new"
            ),
            materialized_root=(
                materialized
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    state_ids_in_plan = {
        item[
            "state_id"
        ]
        for item in plan_calls[
            0
        ][
            "state_sources"
        ]
    }

    assert "STATE_A" in state_ids_in_plan


def test_absent_supersession_preserves_legacy_behavior(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-a",
    )

    key = (
        "a"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/",
                "cap-a",
            )
    }

    previous = {
        "twin_key":
            "red_sara",

        "materialized_revision_id":
            "matrev-old",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    "RED_SARA_HOME",

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    None,
            }
        ],
    }

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                # No supersessions kwarg at all -- defaults to {}.
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-a"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore([
                    previous
                ])
            ),
            plan_builder=(
                plan_spy([])
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )


# =============================================================================
# WO 2D-20P: governed previous-revision pinning
# =============================================================================


def _two_revisions(
    *,
    older_id="matrev-older",
    newer_id="matrev-newer",
    twin_key="red_sara",
):
    older = {
        "twin_key":
            twin_key,

        "materialized_revision_id":
            older_id,

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    "RED_SARA_HOME",

                "source_capture_id":
                    "cap-home",

                "pathname":
                    "/es/",

                "functional_state":
                    None,
            },
        ],
    }

    newer = {
        "twin_key":
            twin_key,

        "materialized_revision_id":
            newer_id,

        "materialization_mode":
            "DISCOVERY_EXTENSION",

        "state_manifest": [
            {
                "state_id":
                    "RED_SARA_HOME",

                "source_capture_id":
                    "cap-home",

                "pathname":
                    "/es/",

                "functional_state":
                    None,
            },
            {
                "state_id":
                    "RED_SARA_EXTRA",

                "source_capture_id":
                    "cap-extra",

                "pathname":
                    "/es/extra",

                "functional_state":
                    None,
            },
        ],
    }

    # RevisionStore.list() (fixture) preserves insertion order, exactly
    # mirroring the real store's created_at ordering: older first.
    return [
        older,
        newer,
    ]


def test_absent_pin_preserves_default_latest_behavior(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-home",
    )

    write_capture(
        captures,
        "cap-extra",
    )

    key = (
        "a"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/",
                "cap-home",
            ),
    }

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-home"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore(
                    _two_revisions()
                )
            ),
            plan_builder=(
                plan_spy([])
            ),
            materializer=(
                materializer_spy([])
            ),
        )
    )

    assert (
        result[
            "previous_revision_selection_mode"
        ]
        == "DEFAULT_LATEST"
    )

    assert (
        result[
            "base_revision_id"
        ]
        == "matrev-newer"
    )


def test_valid_pin_selects_exactly_requested_revision_even_when_newer_exists(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-home",
    )

    write_capture(
        captures,
        "cap-extra",
    )

    key = (
        "a"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/",
                "cap-home",
            ),
    }

    plan_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-home"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore(
                    _two_revisions()
                )
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy([])
            ),
            previous_revision_id=(
                "matrev-older"
            ),
        )
    )

    assert (
        result[
            "previous_revision_selection_mode"
        ]
        == "PINNED"
    )

    assert (
        result[
            "base_revision_id"
        ]
        == "matrev-older"
    )

    # Pinned to matrev-older: only its single state exists there, so
    # "/es/extra" (only in matrev-newer) must NOT appear as carried
    # forward -- proof the newer revision was never consulted.
    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )


def test_unknown_pin_fails_closed(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-home",
    )

    key = (
        "a"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/",
                "cap-home",
            ),
    }

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-home"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore(
                    _two_revisions()
                )
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy(
                    build_calls
                )
            ),
            previous_revision_id=(
                "matrev-does-not-exist"
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    )

    assert (
        "PREVIOUS_REVISION_PIN_NOT_FOUND"
        in result[
            "reason"
        ]
    )

    assert (
        result[
            "previous_revision_selection_mode"
        ]
        == "PINNED"
    )

    # No fallback to latest (or to bootstrap): nothing was planned or
    # built.
    assert plan_calls == []
    assert build_calls == []


def test_pin_from_another_twin_fails_closed(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-home",
    )

    key = (
        "a"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/",
                "cap-home",
            ),
    }

    other_twin_revision = {
        "twin_key":
            "some_other_twin",

        "materialized_revision_id":
            "matrev-other-twin",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [],
    }

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-home"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore([
                    other_twin_revision,
                ])
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy(
                    build_calls
                )
            ),
            # Belongs to "some_other_twin", not "red_sara".
            previous_revision_id=(
                "matrev-other-twin"
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_SKIPPED
    )

    assert (
        "PREVIOUS_REVISION_PIN_NOT_FOUND"
        in result[
            "reason"
        ]
    )

    assert plan_calls == []
    assert build_calls == []


def test_pinned_base_identified_in_plan_evidence(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-home",
    )

    write_capture(
        captures,
        "cap-extra",
    )

    write_capture(
        captures,
        "cap-new",
    )

    key_new = (
        "b"
        * 64
    )

    states = {
        key_new:
            state(
                key_new,
                "/es/nuevo",
                "cap-new",
            ),
    }

    plan_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=(
                captures
            ),
            trigger_capture_id=(
                "cap-new"
            ),
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=(
                RevisionStore(
                    _two_revisions()
                )
            ),
            plan_builder=(
                plan_spy(
                    plan_calls
                )
            ),
            materializer=(
                materializer_spy([])
            ),
            previous_revision_id=(
                "matrev-older"
            ),
        )
    )

    assert (
        result[
            "status"
        ]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    assert (
        result[
            "base_revision_id"
        ]
        == "matrev-older"
    )

    # The plan's own state_sources reflect the PINNED base's content
    # (only RED_SARA_HOME, from matrev-older) -- proof matrev-newer's
    # extra state ("/es/extra") was never consulted for this plan.
    pathnames_in_plan = {
        item[
            "pathname"
        ]
        for item in plan_calls[
            0
        ][
            "state_sources"
        ]
    }

    assert "/es/" in pathnames_in_plan
    assert "/es/extra" not in pathnames_in_plan


def test_repeated_planning_against_same_pinned_base_is_deterministic(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-home",
    )

    write_capture(
        captures,
        "cap-extra",
    )

    key = (
        "a"
        * 64
    )

    states = {
        key:
            state(
                key,
                "/es/",
                "cap-home",
            ),
    }

    def run():
        return (
            reconcile_auto_twin_discovery_materialization(
                managed_site_store=(
                    ManagedStore()
                ),
                observation_store=(
                    ObservationStore(
                        states
                    )
                ),
                capture_root=(
                    captures
                ),
                trigger_capture_id=(
                    "cap-home"
                ),
                materialized_root=(
                    tmp_path
                    / "materialized"
                ),
                revision_store=(
                    RevisionStore(
                        _two_revisions()
                    )
                ),
                plan_builder=(
                    plan_spy([])
                ),
                materializer=(
                    materializer_spy([])
                ),
                previous_revision_id=(
                    "matrev-older"
                ),
            )
        )

    first = run()
    second = run()

    assert (
        first[
            "base_revision_id"
        ]
        == second[
            "base_revision_id"
        ]
        == "matrev-older"
    )

    assert (
        first[
            "previous_revision_selection_mode"
        ]
        == second[
            "previous_revision_selection_mode"
        ]
        == "PINNED"
    )


# =============================================================================
# QCC C2B-W1 / R03: PER_STATE_FAIL_OPEN_DEFERRAL_V1
#
# A causal-refresh guard failure belonging to ONE already-materialized
# state must never abort the whole reconciliation pass. It must defer
# only that state -- preserving its previous physical
# representative/fingerprint unchanged, never guessing a replacement --
# while an independent, unaffected state proceeds normally in the same
# pass.
# =============================================================================


def _write_navigation_runtime_with_transitions(
    materialized_root,
    revision_id,
    transitions,
    *,
    twin_key="red_sara",
):
    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    from backend.qcc.auto_twin.navigation_transition_runtime import (
        AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,
        AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME,
    )

    from backend.qcc.auto_twin.runtime_network_sterilization import (
        AUTO_TWIN_NETWORK_STERILIZER_VERSION,
    )

    runtime_dir = (
        materialized_root
        / twin_key
        / revision_id
        / "runtime"
    )

    runtime_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Physical renderer already current (both the renderer and
    # network-sterilizer dimensions): this test is exclusively about
    # the causal-refresh existing-state guards, not renderer migration.
    (
        runtime_dir
        / "renderer.json"
    ).write_text(
        json.dumps({
            "renderer_version":
                AUTO_TWIN_RUNTIME_RENDERER_VERSION,

            "network_sterilizer_version":
                AUTO_TWIN_NETWORK_STERILIZER_VERSION,
        }),
        encoding="utf-8",
    )

    (
        runtime_dir
        / AUTO_TWIN_NAVIGATION_RUNTIME_FILENAME
    ).write_text(
        json.dumps({
            "adapter_version":
                AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,

            "transitions":
                list(
                    transitions
                ),
        }),
        encoding="utf-8",
    )


def _write_state_observation(
    captures,
    capture_id,
    *,
    fingerprint,
    functional_state=None,
):
    payload = {
        "fingerprint":
            fingerprint,
    }

    if functional_state is not None:
        payload[
            "state"
        ] = functional_state

    (
        captures
        / capture_id
        / "state_observation.json"
    ).write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )


def _write_capture_with_profile(
    captures,
    capture_id,
    profile_key,
):
    write_capture(
        captures,
        capture_id,
    )

    (
        captures
        / capture_id
        / "qcc_capture.json"
    ).write_text(
        json.dumps({
            "browser_profile_key":
                profile_key,
        }),
        encoding="utf-8",
    )


FP_OLD_BAD = "1" * 64
FP_NEW_BAD = "2" * 64
FP_OLD_GOOD = "3" * 64
FP_NEW_GOOD = "4" * 64


def _navigation_transition_fixture(
    candidate_id,
    before_fingerprint,
    after_fingerprint,
    selector,
):
    return {
        "candidate_id":
            candidate_id,

        "before_fingerprint":
            before_fingerprint,

        "after_fingerprint":
            after_fingerprint,

        "real_observation_count":
            1,

        "candidate_status":
            "UNKNOWN",

        "navigation_context":
            [],

        "action": {
            "kind":
                "LINK",

            "policy":
                "NAVIGATION_CANDIDATE",

            "selector":
                selector,

            "frame_path":
                "main",
        },
    }


@pytest.mark.parametrize(
    "guard_case",
    (
        "CAUSAL_EXISTING_STATE_CAPTURE_ID_MISSING",
        "CAUSAL_EXISTING_STATE_EVIDENCE_INCOMPLETE",
        "CAUSAL_EXISTING_STATE_PROFILE_NOT_AUTHORIZED",
        "CAUSAL_EXISTING_STATE_FINGERPRINT_MISMATCH",
        "CAUSAL_EXISTING_STATE_FUNCTIONAL_STATE_MISMATCH",
    ),
)
def test_per_state_fail_open_deferral_preserves_independent_state(
    tmp_path,
    guard_case,
):
    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    _write_navigation_runtime_with_transitions(
        materialized,
        "matrev-old",
        (
            _navigation_transition_fixture(
                "cand-bad",
                FP_OLD_BAD,
                FP_NEW_BAD,
                "#bad",
            ),
            _navigation_transition_fixture(
                "cand-good",
                FP_OLD_GOOD,
                FP_NEW_GOOD,
                "#good",
            ),
        ),
    )

    _write_registry(
        materialized,
        "matrev-old",
        [
            {
                "state_id": "STATE_BAD",
                "fingerprint": FP_OLD_BAD,
            },
            {
                "state_id": "STATE_GOOD",
                "fingerprint": FP_OLD_GOOD,
            },
        ],
    )

    # Independent valid state: always fully eligible for causal
    # refresh, regardless of which guard the bad state fails.
    write_capture(
        captures,
        "cap-good-new",
    )

    _write_state_observation(
        captures,
        "cap-good-new",
        fingerprint=FP_NEW_GOOD,
    )

    bad_last_capture_id = "cap-bad-new"

    if guard_case == "CAUSAL_EXISTING_STATE_CAPTURE_ID_MISSING":
        bad_last_capture_id = ""

    elif guard_case == "CAUSAL_EXISTING_STATE_EVIDENCE_INCOMPLETE":
        write_capture(
            captures,
            "cap-bad-new",
            omit=("page.html",),
        )

    elif guard_case == "CAUSAL_EXISTING_STATE_PROFILE_NOT_AUTHORIZED":
        _write_capture_with_profile(
            captures,
            "cap-bad-new",
            "qcc_assisted",
        )

    elif guard_case == "CAUSAL_EXISTING_STATE_FINGERPRINT_MISMATCH":
        write_capture(
            captures,
            "cap-bad-new",
        )

        _write_state_observation(
            captures,
            "cap-bad-new",
            fingerprint=("9" * 64),
        )

    elif guard_case == "CAUSAL_EXISTING_STATE_FUNCTIONAL_STATE_MISMATCH":
        write_capture(
            captures,
            "cap-bad-new",
        )

        _write_state_observation(
            captures,
            "cap-bad-new",
            fingerprint=FP_NEW_BAD,
            functional_state="OTHER_STATE",
        )

    else:
        raise AssertionError(
            "unreachable guard_case: "
            + guard_case
        )

    states = {
        "STATE_BAD_OBS": {
            "state_key": "STATE_BAD_OBS",
            "pathname": "/es/bad",
            "functional_state": None,
            "baseline_capture_id": "cap-bad-old",
            "last_capture_id": bad_last_capture_id,
            "last_fingerprint": FP_NEW_BAD,
            "first_seen_at": "2026-09-05T15:00:00Z0",
        },
        "STATE_GOOD_OBS": {
            "state_key": "STATE_GOOD_OBS",
            "pathname": "/es/good",
            "functional_state": None,
            "baseline_capture_id": "cap-good-old",
            "last_capture_id": "cap-good-new",
            "last_fingerprint": FP_NEW_GOOD,
            "first_seen_at": "2026-09-05T15:00:00Z1",
        },
    }

    previous = {
        "twin_key": "red_sara",
        "materialized_revision_id": "matrev-old",
        "materialization_mode": "DISCOVERY_EXTENSION",
        "state_manifest": [
            {
                "state_id": "STATE_BAD",
                "source_capture_id": "cap-bad-old",
                "pathname": "/es/bad",
                "functional_state": None,
            },
            {
                "state_id": "STATE_GOOD",
                "source_capture_id": "cap-good-old",
                "pathname": "/es/good",
                "functional_state": None,
            },
        ],
    }

    plan_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=ManagedStore(),
            observation_store=ObservationStore(states),
            capture_root=captures,
            trigger_capture_id="cap-good-new",
            materialized_root=materialized,
            revision_store=RevisionStore([previous]),
            plan_builder=plan_spy(plan_calls),
            materializer=materializer_spy([]),
        )
    )

    # Reconciliation never aborts because of the bad state's guard
    # failure: the independent good state's refresh is materialized.
    assert (
        result["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    assert len(plan_calls) == 1

    sources = {
        item["pathname"]: item
        for item in plan_calls[0]["state_sources"]
    }

    # The bad state keeps its previous physical representative exactly:
    # no guessed replacement capture/fingerprint/state identity.
    assert (
        sources["/es/bad"]["capture_id"]
        == "cap-bad-old"
    )

    assert (
        sources["/es/bad"]["state_id"]
        == "STATE_BAD"
    )

    # The independent good state proceeds and is safely refreshed.
    assert (
        sources["/es/good"]["capture_id"]
        == "cap-good-new"
    )

    assert (
        sources["/es/good"]["state_id"]
        == "STATE_GOOD"
    )

    # No transition whose endpoint could not be safely refreshed is
    # fabricated: neither of the fixture candidates was already
    # materialized on both endpoints, so none is planned.
    assert (
        plan_calls[0]["navigation_transitions"]
        == ()
    )


# =============================================================================
# QCC C2B-W1 / R03: SELECTED_CAPTURE_FINGERPRINT_DEDUPE_V1
#
# The new-state branch must dedupe against the SELECTED capture's own
# functional fingerprint -- not only the observed state's
# current_fingerprint -- before creating a new physical state.
# =============================================================================


def test_selected_capture_fingerprint_dedupe_prevents_duplicate_physical_state(
    tmp_path,
):
    captures = (
        tmp_path
        / "captures"
    )

    fp_shared = "a" * 64
    fp_x = "b" * 64
    fp_y = "c" * 64
    fp_z = "d" * 64

    # X: baseline capture whose OWN functional fingerprint (fp_shared)
    # differs from the observed state's current_fingerprint (fp_x) and
    # is not yet represented anywhere.
    write_capture(
        captures,
        "cap-x",
    )

    _write_state_observation(
        captures,
        "cap-x",
        fingerprint=fp_shared,
    )

    # Y: a distinct observed state (fp_y is genuinely new) whose
    # baseline capture happens to resolve to the SAME functional
    # fingerprint (fp_shared) already registered by X in this pass.
    write_capture(
        captures,
        "cap-y",
    )

    _write_state_observation(
        captures,
        "cap-y",
        fingerprint=fp_shared,
    )

    # Z: baseline capture with no derivable functional fingerprint at
    # all (legacy/empty state_observation.json) -- existing
    # current_fingerprint-only handling must still apply unmodified.
    write_capture(
        captures,
        "cap-z",
    )

    states = {
        "STATE_X_OBS": {
            "state_key": "STATE_X_OBS",
            "pathname": "/es/x",
            "functional_state": None,
            "baseline_capture_id": "cap-x",
            "last_capture_id": "cap-x",
            "last_fingerprint": fp_x,
            "first_seen_at": "2026-09-05T15:00:00Z0",
        },
        "STATE_Y_OBS": {
            "state_key": "STATE_Y_OBS",
            "pathname": "/es/y",
            "functional_state": None,
            "baseline_capture_id": "cap-y",
            "last_capture_id": "cap-y",
            "last_fingerprint": fp_y,
            "first_seen_at": "2026-09-05T15:00:00Z1",
        },
        "STATE_Z_OBS": {
            "state_key": "STATE_Z_OBS",
            "pathname": "/es/z",
            "functional_state": None,
            "baseline_capture_id": "cap-z",
            "last_capture_id": "cap-z",
            "last_fingerprint": fp_z,
            "first_seen_at": "2026-09-05T15:00:00Z2",
        },
    }

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=ManagedStore(),
            observation_store=ObservationStore(states),
            capture_root=captures,
            trigger_capture_id="cap-y",
            materialized_root=(
                tmp_path
                / "materialized"
            ),
            revision_store=RevisionStore(),
            plan_builder=plan_spy(plan_calls),
            materializer=materializer_spy(build_calls),
        )
    )

    assert (
        result["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    # Y is deduped against X's already-registered selected-capture
    # fingerprint: no duplicate physical state is created for it.
    assert result["added_state_count"] == 2

    pathnames = {
        item["pathname"]
        for item in plan_calls[0]["state_sources"]
    }

    assert pathnames == {
        "/es/x",
        "/es/z",
    }


def test_selected_capture_fingerprint_dedupe_prevents_duplicate_against_previous_revision(
    tmp_path,
):
    """B1-B5 across a revision boundary: the selected capture's OWN
    fingerprint (already physically represented in the PREVIOUS
    revision) is the dedupe authority, not the observed state's own
    current_fingerprint (which is genuinely new/unrepresented).
    """

    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    fp_shared = "a" * 64
    fp_observed_new = "e" * 64

    write_capture(
        captures,
        "cap-old",
    )

    write_capture(
        captures,
        "cap-new",
    )

    # The newly selected capture's OWN functional fingerprint resolves
    # to the SAME physical fingerprint already registered by the
    # PREVIOUS materialized revision -- B2 + B3.
    _write_state_observation(
        captures,
        "cap-new",
        fingerprint=fp_shared,
    )

    states = {
        "STATE_NEW_OBS": {
            "state_key": "STATE_NEW_OBS",
            "pathname": "/es/new",
            "functional_state": None,
            "baseline_capture_id": "cap-new",
            "last_capture_id": "cap-new",
            # B1: observed fingerprint is genuinely new/distinct from
            # the selected capture's own physical fingerprint.
            "last_fingerprint": fp_observed_new,
            "first_seen_at": "2026-09-05T15:00:00Z0",
        },
    }

    previous = {
        "twin_key": "red_sara",
        "materialized_revision_id": "matrev-old",
        "materialization_mode": "BOOTSTRAP_REAL",
        "state_manifest": [
            {
                "state_id": "STATE_OLD",
                "source_capture_id": "cap-old",
                "pathname": "/es/old",
                "functional_state": None,
            },
        ],
    }

    _write_physical_renderer_marker(
        materialized,
        "matrev-old",
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    _write_registry(
        materialized,
        "matrev-old",
        [
            {
                "state_id": "STATE_OLD",
                "fingerprint": fp_shared,
            },
        ],
    )

    plan_calls = []
    build_calls = []

    result = (
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=ManagedStore(),
            observation_store=ObservationStore(states),
            capture_root=captures,
            trigger_capture_id="cap-new",
            materialized_root=materialized,
            revision_store=RevisionStore([previous]),
            plan_builder=plan_spy(plan_calls),
            materializer=materializer_spy(build_calls),
        )
    )

    # B4: no duplicate physical state is created -- the reconcile pass
    # sees nothing new (the selected capture's fingerprint was already
    # physically represented), so it must be a deterministic no-op.
    assert (
        result["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )

    assert result["added_state_count"] == 0

    # B5: proof the dedupe used the SELECTED capture's fingerprint
    # (fp_shared), not the observed state's current_fingerprint
    # (fp_observed_new) -- had current_fingerprint been used, it is
    # NOT already represented, and a duplicate physical state for
    # "/es/new" would have been (incorrectly) planned/built.
    assert plan_calls == []
    assert build_calls == []


# =============================================================================
# QCC C2B-W1 / R03: A5 -- when the ONLY affected state is deferred by a
# causal-refresh guard failure and there is no independent work left to
# do, the reconcile pass must still resolve deterministically (never
# crash, never guess), exactly reusing the pre-existing WAITING/
# SKIPPED/NO_CHANGE status contract.
# =============================================================================


def test_causal_refresh_guard_failure_without_independent_state_stays_deterministic(
    tmp_path,
):
    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    captures = (
        tmp_path
        / "captures"
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    _write_physical_renderer_marker(
        materialized,
        "matrev-old",
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    _write_registry(
        materialized,
        "matrev-old",
        [
            {
                "state_id": "STATE_BAD",
                "fingerprint": FP_OLD_BAD,
            },
        ],
    )

    write_capture(
        captures,
        "cap-bad-old",
    )

    # No TWIN_ELIGIBLE causal evidence at all references FP_NEW_BAD
    # here (no navigation transitions materialized): the only
    # observed, already-materialized state can never qualify for
    # causal refresh and is deferred exactly as its previous physical
    # revision left it.
    states = {
        "STATE_BAD_OBS": {
            "state_key": "STATE_BAD_OBS",
            "pathname": "/es/bad",
            "functional_state": None,
            "baseline_capture_id": "cap-bad-old",
            "last_capture_id": "cap-bad-old",
            "last_fingerprint": FP_NEW_BAD,
            "first_seen_at": "2026-09-05T15:00:00Z0",
        },
    }

    previous = {
        "twin_key": "red_sara",
        "materialized_revision_id": "matrev-old",
        "materialization_mode": "DISCOVERY_EXTENSION",
        "state_manifest": [
            {
                "state_id": "STATE_BAD",
                "source_capture_id": "cap-bad-old",
                "pathname": "/es/bad",
                "functional_state": None,
            },
        ],
    }

    def run():
        plan_calls = []
        build_calls = []

        result = (
            reconcile_auto_twin_discovery_materialization(
                managed_site_store=ManagedStore(),
                observation_store=ObservationStore(states),
                capture_root=captures,
                trigger_capture_id="cap-bad-old",
                materialized_root=materialized,
                revision_store=RevisionStore([previous]),
                plan_builder=plan_spy(plan_calls),
                materializer=materializer_spy(build_calls),
            )
        )

        return result, plan_calls, build_calls

    first_result, first_plan_calls, first_build_calls = run()
    second_result, second_plan_calls, second_build_calls = run()

    # Deterministic across repeated reconcile passes -- never a crash,
    # never a guessed replacement, never an ambiguous outcome.
    assert (
        first_result["status"]
        == second_result["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )

    assert first_plan_calls == second_plan_calls == []
    assert first_build_calls == second_build_calls == []


# =============================================================================
# QCC AUTO TWIN VOLATILE PATH MATERIALIZATION PLAN FIX V1
#
# MaterializationPlan must accept a REAL capture whose raw pathname
# differs from the expected persistent pathname ONLY by the already-
# governed volatile ;jsessionid=... path parameter, while a genuinely
# different route must still fail closed.
# =============================================================================


_VOLATILE_PATH_PLAN_ORIGIN = (
    "https://mercurio.delegaciondelgobierno.gob.es"
)


def _volatile_path_plan_write_artifacts(
    root,
    capture_id,
):
    import backend.qcc.auto_twin.materialization_plan as plan_module

    directory = root / capture_id

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    for (
        _kind,
        filename,
        _destination,
    ) in (
        plan_module.AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS
    ):
        (
            directory
            / filename
        ).write_bytes(
            (
                capture_id
                + ":"
                + filename
            ).encode(
                "utf-8"
            )
        )


def _volatile_path_plan_build(
    tmp_path,
    monkeypatch,
    *,
    expected_pathname,
    actual_pathname,
    capture_id="cap-volatile",
):
    import backend.qcc.auto_twin.materialization_plan as plan_module

    _volatile_path_plan_write_artifacts(
        tmp_path,
        capture_id,
    )

    bundle = {
        "capture_id":
            capture_id,

        "capture": {
            "capture_id":
                capture_id,

            "pathname":
                actual_pathname,

            "functional_state":
                None,

            "browser_profile_key":
                "qcc_assisted",
        },

        "snapshot": {
            "page": {
                "origin":
                    _VOLATILE_PATH_PLAN_ORIGIN,

                "pathname":
                    actual_pathname,
            },
        },

        "rendering_profile": {
            "rendering_profile_id":
                "render-profile-1",
        },

        "fingerprint":
            "fingerprint-"
            + capture_id,
    }

    monkeypatch.setattr(
        plan_module,
        "load_auto_twin_persisted_capture_bundle",
        lambda **kwargs: bundle,
    )

    return plan_module.build_auto_twin_materialization_plan(
        twin_key="mercurio",
        materialization_mode=(
            AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
        ),
        state_sources=[
            {
                "state_id":
                    "MERCURIO_ACCESS_MODE",

                "capture_id":
                    capture_id,

                "pathname":
                    expected_pathname,

                "functional_state":
                    None,
            }
        ],
        required_origin=(
            _VOLATILE_PATH_PLAN_ORIGIN
        ),
        required_profile_key=(
            "qcc_assisted"
        ),
        root=tmp_path,
    )


def test_volatile_session_path_accepted_against_canonical_expected(
    tmp_path,
    monkeypatch,
):
    plan = _volatile_path_plan_build(
        tmp_path,
        monkeypatch,
        expected_pathname=(
            "/mercurio/modoAcceso.html"
        ),
        actual_pathname=(
            "/mercurio/modoAcceso.html;jsessionid=SESSION_A"
        ),
    )

    assert (
        plan[
            "state_manifest"
        ][0][
            "pathname"
        ]
        == "/mercurio/modoAcceso.html"
    )


def test_volatile_session_value_does_not_define_identity(
    tmp_path,
    monkeypatch,
):
    plan_a = _volatile_path_plan_build(
        tmp_path,
        monkeypatch,
        expected_pathname=(
            "/mercurio/modoAcceso.html"
        ),
        actual_pathname=(
            "/mercurio/modoAcceso.html;jsessionid=SESSION_A"
        ),
    )

    plan_b = _volatile_path_plan_build(
        tmp_path,
        monkeypatch,
        expected_pathname=(
            "/mercurio/modoAcceso.html"
        ),
        actual_pathname=(
            "/mercurio/modoAcceso.html;jsessionid=SESSION_B"
        ),
    )

    assert (
        plan_a[
            "state_manifest"
        ]
        == plan_b[
            "state_manifest"
        ]
    )


def test_real_route_mismatch_still_fails_closed(
    tmp_path,
    monkeypatch,
):
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_PATHNAME_MISMATCH"
        ),
    ):
        _volatile_path_plan_build(
            tmp_path,
            monkeypatch,
            expected_pathname=(
                "/mercurio/modoAcceso.html"
            ),
            actual_pathname=(
                "/mercurio/otraRuta.html"
            ),
        )


def test_pathname_without_jsessionid_behavior_unchanged(
    tmp_path,
    monkeypatch,
):
    plan = _volatile_path_plan_build(
        tmp_path,
        monkeypatch,
        expected_pathname=(
            "/mercurio/modoAcceso.html"
        ),
        actual_pathname=(
            "/mercurio/modoAcceso.html"
        ),
    )

    assert (
        plan[
            "state_manifest"
        ][0][
            "pathname"
        ]
        == "/mercurio/modoAcceso.html"
    )


# =============================================================================
# QCC_AUTO_TWIN_SEMANTIC_TARGET_IDEMPOTENCY_R2
#
# G: navigation runtime adapter version migration.
# H: full real plan-builder/materializer reconcile fixed point.
# =============================================================================


def test_navigation_adapter_version_mismatch_requires_refresh(
    tmp_path,
):
    """G. persisted adapter_version=5 vs current=6 -> refresh required."""

    from backend.qcc.auto_twin.automatic_materialization import (
        _navigation_runtime_refresh_required,
    )

    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    _write_physical_renderer_marker(
        materialized,
        "matrev-current",
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
        navigation_adapter_version=5,
    )

    revision = {
        "materialized_revision_id":
            "matrev-current",
    }

    assert (
        _navigation_runtime_refresh_required(
            materialized_root=materialized,
            twin_key="red_sara",
            revision=revision,
        )
        is True
    )


def test_navigation_adapter_version_match_does_not_force_refresh_alone(
    tmp_path,
):
    """G. persisted adapter_version == current -> never forces a
    refresh solely because of the adapter dimension."""

    from backend.qcc.auto_twin.automatic_materialization import (
        _navigation_runtime_refresh_required,
    )

    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    )

    from backend.qcc.auto_twin.navigation_transition_runtime import (
        AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION,
    )

    materialized = (
        tmp_path
        / "materialized"
    )

    _write_physical_renderer_marker(
        materialized,
        "matrev-current",
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
        navigation_adapter_version=(
            AUTO_TWIN_NAVIGATION_RUNTIME_ADAPTER_VERSION
        ),
    )

    revision = {
        "materialized_revision_id":
            "matrev-current",
    }

    assert (
        _navigation_runtime_refresh_required(
            materialized_root=materialized,
            twin_key="red_sara",
            revision=revision,
        )
        is False
    )


def _fixed_point_write_golden_state(
    base,
    index,
    state_id,
    pathname,
    fingerprint,
    *,
    with_action=False,
):
    state_root = (
        base
        / "states"
        / f"{index:02d}-{state_id}"
    )

    runtime = (
        state_root
        / "runtime"
    )

    runtime.mkdir(
        parents=True
    )

    (
        runtime
        / "state.json"
    ).write_text(
        json.dumps({
            "state_id":
                state_id,

            "source_capture_id":
                f"cap-{state_id}-0",

            "pathname":
                pathname,

            "functional_state":
                None,

            "fingerprint":
                fingerprint,
        }),
        encoding="utf-8",
    )

    (
        runtime
        / "index.html"
    ).write_text(
        '<html><head></head><body><a id="go">go</a></body></html>',
        encoding="utf-8",
    )

    (
        runtime
        / "shadow_styles.json"
    ).write_text(
        "{}",
        encoding="utf-8",
    )

    elements = (
        [{
            "tag":
                "a",

            "text":
                "go",

            "attributes": {
                "id":
                    "go",

                "onclick":
                    "continuar();",
            },
        }]
        if with_action
        else []
    )

    evidence = (
        state_root
        / "evidence"
    )

    evidence.mkdir()

    (
        evidence
        / "qcc_capture.json"
    ).write_text(
        json.dumps({
            "frames": [{
                "frame_id":
                    0,

                "result": {
                    "elements":
                        elements,
                },
            }],
        }),
        encoding="utf-8",
    )

    source = (
        state_root
        / "source"
    )

    source.mkdir()

    (
        source
        / "page.html"
    ).write_text(
        "SRC",
        encoding="utf-8",
    )


def _fixed_point_seed_revision(
    materialized_root,
    twin_key,
    site_code,
    fp_a,
    fp_b,
):
    from backend.qcc.auto_twin.materialization_builder import (
        AUTO_TWIN_RUNTIME_RENDERER_VERSION,
        materialize_auto_twin_plan,
    )

    from backend.qcc.auto_twin.materialization_plan import (
        AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
        AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
    )

    from backend.qcc.auto_twin.runtime_network_sterilization import (
        AUTO_TWIN_NETWORK_STERILIZER_VERSION,
    )

    base = (
        materialized_root
        / twin_key
        / "matrev-golden"
    )

    (
        base
        / "runtime"
    ).mkdir(
        parents=True
    )

    (
        base
        / "runtime"
        / "renderer.json"
    ).write_text(
        json.dumps({
            "renderer_version":
                AUTO_TWIN_RUNTIME_RENDERER_VERSION,

            "network_sterilizer_version":
                AUTO_TWIN_NETWORK_STERILIZER_VERSION,
        }),
        encoding="utf-8",
    )

    _fixed_point_write_golden_state(
        base,
        1,
        "STATE_A",
        "/es/a",
        fp_a,
        with_action=True,
    )

    _fixed_point_write_golden_state(
        base,
        2,
        "STATE_B",
        "/es/b",
        fp_b,
    )

    manifest = [
        {
            "state_index":
                index,

            "state_id":
                state_id,

            "source_capture_id":
                f"cap-{state_id}-0",

            "pathname":
                pathname,

            "functional_state":
                None,

            "rendering_profile_id":
                "MATERIALIZED_CARRY_FORWARD",

            "source_mode":
                AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
        }
        for index, state_id, pathname in (
            (1, "STATE_A", "/es/a"),
            (2, "STATE_B", "/es/b"),
        )
    ]

    plan = {
        "schema_version":
            1,

        "plan_type":
            AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,

        "plan_id":
            "matplan-fixed-point-seed",

        "twin_key":
            twin_key,

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "generation_source":
            "REAL_EVIDENCE_ONLY",

        "required_origin":
            "https://reg.redsara.es",

        "required_profile_key":
            "twin_discovery",

        "base_materialized_revision_id":
            "matrev-golden",

        "source_capture_ids": [
            "cap-STATE_A-0",
            "cap-STATE_B-0",
        ],

        "source_evidence_sha256":
            "a" * 64,

        "artifact_operations": [],

        "state_manifest":
            manifest,
    }

    return materialize_auto_twin_plan(
        plan=plan,
        source_root=(
            materialized_root.parent
            / "captures"
        ),
        materialized_root=materialized_root,
        procedure_code=site_code,
        flow_variant="SITE_LEVEL",
    )["revision"]


def test_full_reconcile_reaches_fixed_point_without_revision_growth(
    tmp_path,
):
    """H. pass 1 = MATERIALIZED, pass 2 = NO_CHANGE, pass 3 = NO_CHANGE,
    and the revision count stops increasing -- using the REAL plan
    builder/materializer end to end, exactly like production."""

    from backend.qcc.auto_twin.managed_site_registry import (
        AutoTwinManagedSite,
    )
    from backend.qcc.auto_twin.managed_site_store import (
        AutoTwinManagedSiteStore,
    )
    from backend.qcc.auto_twin.materialized_revision_store import (
        AutoTwinMaterializedRevisionStore,
    )
    from backend.qcc.auto_twin.observation_store import (
        AutoTwinObservationStore,
    )
    from backend.qcc.navigation_learning.human_candidate_store import (
        HumanNavigationCandidateStore,
    )

    origin = "https://reg.redsara.es"
    twin_key = "red_sara"
    site_code = "RED_SARA"

    fp_a = "a" * 64
    fp_b = "b" * 64

    selector = 'a[onclick="continuar();"]'

    captures = (
        tmp_path
        / "captures"
    )

    captures.mkdir()

    materialized_root = (
        tmp_path
        / "materialized"
    )

    site = AutoTwinManagedSite(
        twin_key=twin_key,
        site_code=site_code,
        origins=(origin,),
    )

    managed_store = AutoTwinManagedSiteStore(
        path=(
            tmp_path
            / "managed.json"
        ),
    )

    managed_store.register(
        site
    )

    observation_store = AutoTwinObservationStore(
        path=(
            tmp_path
            / "observation_state.json"
        ),
    )

    observation_store.observe(
        site,
        capture_id="cap-a-0",
        observed_at="2026-10-09T10:00:00.000000Z",
        browser_profile_key="twin_discovery",
        url=(
            origin
            + "/es/a"
        ),
        site_code=(
            site.site_code
        ),
        state_observation={
            "fingerprint":
                fp_a,
        },
    )

    observation_store.observe(
        site,
        capture_id="cap-b-0",
        observed_at="2026-10-09T10:00:01.000000Z",
        browser_profile_key="twin_discovery",
        url=(
            origin
            + "/es/b"
        ),
        site_code=(
            site.site_code
        ),
        state_observation={
            "fingerprint":
                fp_b,
        },
    )

    for capture_id in (
        "cap-a-0",
        "cap-b-0",
    ):
        write_capture(
            captures,
            capture_id,
        )

    seed = _fixed_point_seed_revision(
        materialized_root,
        twin_key,
        site_code,
        fp_a,
        fp_b,
    )

    candidate_store = HumanNavigationCandidateStore(
        root=(
            tmp_path
            / "candidates"
        ),
    )

    revision_counts = []

    def run():
        result = (
            reconcile_auto_twin_discovery_materialization(
                managed_site_store=managed_store,
                observation_store=observation_store,
                capture_root=captures,
                trigger_capture_id="cap-b-0",
                twin_key=twin_key,
                materialized_root=materialized_root,
                human_navigation_candidate_store=candidate_store,
            )
        )

        revision_counts.append(
            len(
                AutoTwinMaterializedRevisionStore(
                    root=materialized_root,
                ).list(
                    twin_key=twin_key
                )
            )
        )

        return result

    # Pass 0: states unchanged, no navigation evidence yet.
    before = run()

    assert (
        before["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )

    assert (
        before["materialized_revision_id"]
        == seed["materialized_revision_id"]
    )

    candidate_store.record_observed_transition({
        "changed":
            True,

        "event_id":
            "evt-fixed-point",

        "after_observed_at":
            "2026-10-09T10:05:00Z",

        "site_code":
            site_code,

        "environment":
            "REAL",

        "before_state":
            None,

        "before_fingerprint":
            fp_a,

        "kind":
            "LINK",

        "policy":
            "NAVIGATION_CANDIDATE",

        "selector":
            selector,

        "frame_path":
            "main",

        "after_state":
            None,

        "after_fingerprint":
            fp_b,
    })

    first = run()

    assert (
        first["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    assert (
        first["materialized_revision_id"]
        != seed["materialized_revision_id"]
    )

    second = run()

    assert (
        second["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )

    assert (
        second["materialized_revision_id"]
        == first["materialized_revision_id"]
    )

    third = run()

    assert (
        third["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )

    assert (
        third["materialized_revision_id"]
        == first["materialized_revision_id"]
    )

    # Fixed point reached: the revision count never grows again.
    assert (
        revision_counts[-1]
        == revision_counts[-2]
        == revision_counts[-3]
    )
