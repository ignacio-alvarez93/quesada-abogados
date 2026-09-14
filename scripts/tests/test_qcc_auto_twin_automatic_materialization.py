from pathlib import Path
from types import SimpleNamespace
import json


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
                        "twin_discovery",
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

    helper = (
        "_qcc_project_auto_twin_materialization_after_artifact("
    )

    assert (
        text.count(
            helper
        )
        >= 3
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

    assert helper in page
    assert helper in visual



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
                    "RED_SARA_REGISTER",

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
        == "RED_SARA_HOME"
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
        == "RED_SARA_REGISTER"
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
                    "STATE_A",

                "source_capture_id":
                    "cap-a-old",

                "pathname":
                    "/es/a",

                "functional_state":
                    None,
            },
            {
                "state_id":
                    "STATE_B",

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
