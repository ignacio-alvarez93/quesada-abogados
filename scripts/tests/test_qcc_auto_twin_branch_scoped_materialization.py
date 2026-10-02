from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

import backend.qcc.auto_twin.materialization_plan as plan_module

from backend.qcc.auto_twin.automatic_materialization import (
    AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED,
    AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE,
    REQUIRED_ARTIFACTS,
    reconcile_auto_twin_discovery_materialization,
)
from backend.qcc.auto_twin import (
    automatic_materialization as automatic_materialization_module,
)

from backend.qcc.auto_twin.materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS,
    AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
    build_auto_twin_materialization_plan,
)

from backend.qcc.auto_twin.materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
    build_auto_twin_materialized_revision,
    validate_auto_twin_materialized_revision,
)


# ======================================================================
# PLAN-LEVEL: materialization_plan.py branch_context_id propagation
# ======================================================================


REAL_ORIGIN = "https://example.gob.es"

CTX_A = "1" * 64
CTX_B = "2" * 64


def _write_source_files(
    root,
    capture_id,
):
    directory = (
        Path(
            root
        )
        / capture_id
    )

    directory.mkdir(
        parents=True
    )

    for index, (
        _kind,
        filename,
        _destination,
    ) in enumerate(
        AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS,
        start=1,
    ):
        (
            directory
            / filename
        ).write_bytes(
            (
                capture_id
                + ":"
                + filename
                + ":"
                + str(
                    index
                )
            ).encode(
                "utf-8"
            )
        )


def _fake_bundle(
    *,
    capture_id,
    pathname,
    functional_state,
    profile="twin_discovery",
    origin=REAL_ORIGIN,
):
    return {
        "capture_id":
            capture_id,

        "capture": {
            "capture_id":
                capture_id,

            "pathname":
                pathname,

            "functional_state":
                functional_state,

            "browser_profile_key":
                profile,
        },

        "snapshot": {
            "page": {
                "origin":
                    origin,

                "pathname":
                    pathname,
            },
        },

        "rendering_profile": {
            "rendering_profile_id":
                "render-profile-1",
        },

        "fingerprint":
            (
                "fingerprint-"
                + capture_id
            ),
    }


def _install_loader(
    monkeypatch,
    bundles,
):
    def fake_loader(
        *,
        capture_id,
        root,
        require_viewport_image,
    ):
        return deepcopy(
            bundles[
                capture_id
            ]
        )

    monkeypatch.setattr(
        plan_module,
        "load_auto_twin_persisted_capture_bundle",
        fake_loader,
    )


def test_plan_real_capture_preserves_branch_context_id(
    tmp_path,
    monkeypatch,
):
    _write_source_files(
        tmp_path,
        "cap-a",
    )

    _install_loader(
        monkeypatch,
        {
            "cap-a":
                _fake_bundle(
                    capture_id="cap-a",
                    pathname="/es/",
                    functional_state="EX01_PERSONAL",
                ),
        },
    )

    plan = (
        build_auto_twin_materialization_plan(
            twin_key="twin_x",
            materialization_mode=(
                AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
            ),
            state_sources=[
                {
                    "state_id":
                        "TWIN_X_STATE",

                    "capture_id":
                        "cap-a",

                    "pathname":
                        "/es/",

                    "functional_state":
                        "EX01_PERSONAL",

                    "branch_context_id":
                        CTX_A,
                },
            ],
            required_origin=REAL_ORIGIN,
            required_profile_key="twin_discovery",
            root=tmp_path,
        )
    )

    assert (
        plan["state_manifest"][0][
            "branch_context_id"
        ]
        == CTX_A
    )


def test_plan_carry_forward_preserves_branch_context_id(
    tmp_path,
):
    plan = (
        build_auto_twin_materialization_plan(
            twin_key="twin_x",
            materialization_mode="DISCOVERY_EXTENSION",
            state_sources=[
                {
                    "state_id":
                        "TWIN_X_STATE",

                    "capture_id":
                        "cap-a",

                    "pathname":
                        "/es/",

                    "functional_state":
                        "EX01_PERSONAL",

                    "source_mode":
                        AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,

                    "branch_context_id":
                        CTX_A,
                },
            ],
            required_origin=REAL_ORIGIN,
            required_profile_key="twin_discovery",
            base_materialized_revision_id="matrev-base",
            root=tmp_path,
        )
    )

    assert (
        plan["state_manifest"][0][
            "branch_context_id"
        ]
        == CTX_A
    )


def test_plan_rejects_malformed_branch_context_id(
    tmp_path,
):
    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_MATERIALIZATION_PLAN_BRANCH_CONTEXT_ID_INVALID"
        ),
    ):
        build_auto_twin_materialization_plan(
            twin_key="twin_x",
            materialization_mode="DISCOVERY_EXTENSION",
            state_sources=[
                {
                    "state_id":
                        "TWIN_X_STATE",

                    "capture_id":
                        "cap-a",

                    "pathname":
                        "/es/",

                    "functional_state":
                        "EX01_PERSONAL",

                    "source_mode":
                        AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,

                    "branch_context_id":
                        "not-a-valid-context-id",
                },
            ],
            required_origin=REAL_ORIGIN,
            required_profile_key="twin_discovery",
            base_materialized_revision_id="matrev-base",
            root=tmp_path,
        )


# ======================================================================
# REVISION-LEVEL: materialized_revision.py branch_context_id propagation
# ======================================================================


def _revision_payload(
    **overrides,
):
    payload = {
        "twin_key":
            "twin_x",

        "materialization_mode":
            AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,

        "source_capture_ids": [
            "cap-a",
        ],

        "candidate_refs": [],

        "state_manifest": [
            {
                "state_id":
                    "TWIN_X_STATE_A",

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    "EX01_PERSONAL",

                "branch_context_id":
                    CTX_A,
            },
        ],

        "artifact_manifest": [
            {
                "path":
                    "states/a/page.html",

                "kind":
                    "HTML",

                "sha256":
                    "a" * 64,

                "size_bytes":
                    10,
            },
        ],

        "content_sha256":
            "c" * 64,

        "created_at":
            "2026-09-05T13:30:00Z",
    }

    payload.update(
        overrides
    )

    return payload


def test_revision_state_manifest_preserves_branch_context_id():
    record = build_auto_twin_materialized_revision(
        **_revision_payload()
    )

    assert (
        record["state_manifest"][0][
            "branch_context_id"
        ]
        == CTX_A
    )


def test_revision_two_branch_contexts_coexist_in_state_manifest():
    payload = _revision_payload(
        source_capture_ids=[
            "cap-a",
            "cap-b",
        ],
        state_manifest=[
            {
                "state_id":
                    "TWIN_X_STATE_A",

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    "EX01_PERSONAL",

                "branch_context_id":
                    CTX_A,
            },
            {
                "state_id":
                    "TWIN_X_STATE_B",

                "source_capture_id":
                    "cap-b",

                "pathname":
                    "/es/",

                "functional_state":
                    "EX01_PERSONAL",

                "branch_context_id":
                    CTX_B,
            },
        ],
    )

    record = build_auto_twin_materialized_revision(
        **payload
    )

    branch_context_ids = {
        entry["branch_context_id"]
        for entry in record[
            "state_manifest"
        ]
    }

    assert branch_context_ids == {
        CTX_A,
        CTX_B,
    }


def test_revision_validate_round_trip_preserves_branch_context_id():
    record = build_auto_twin_materialized_revision(
        **_revision_payload()
    )

    revalidated = validate_auto_twin_materialized_revision(
        record
    )

    assert (
        revalidated["state_manifest"][0][
            "branch_context_id"
        ]
        == CTX_A
    )

    assert (
        revalidated
        == record
    )


def test_revision_legacy_manifest_without_branch_context_id_remains_valid():
    payload = _revision_payload(
        state_manifest=[
            {
                "state_id":
                    "TWIN_X_STATE_A",

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    "EX01_PERSONAL",
            },
        ],
    )

    record = build_auto_twin_materialized_revision(
        **payload
    )

    assert (
        "branch_context_id"
        not in record["state_manifest"][0]
    )

    revalidated = validate_auto_twin_materialized_revision(
        record
    )

    assert (
        revalidated
        == record
    )


def test_revision_rejects_malformed_branch_context_id():
    payload = _revision_payload(
        state_manifest=[
            {
                "state_id":
                    "TWIN_X_STATE_A",

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    "EX01_PERSONAL",

                "branch_context_id":
                    "not-a-valid-context-id",
            },
        ],
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_MATERIALIZED_STATE_BRANCH_CONTEXT_ID_INVALID"
        ),
    ):
        build_auto_twin_materialized_revision(
            **payload
        )


# ======================================================================
# RECONCILE-LEVEL: automatic_materialization.py branch-scoped gating
# ======================================================================


class ManagedStore:
    def get(
        self,
        twin_key,
    ):
        if twin_key != "twin_x":
            return None

        return SimpleNamespace(
            twin_key="twin_x",
            site_code="TWIN_X",
            origins=(
                "https://example.gob.es",
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
                "twin_x": {
                    "twin_key":
                        "twin_x",

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


def observed_state(
    key,
    pathname,
    capture_id,
    *,
    functional_state=None,
    branch_context_id=None,
):
    result = {
        "state_key":
            key,

        "pathname":
            pathname,

        "functional_state":
            functional_state,

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

    if branch_context_id:
        result[
            "branch_context_id"
        ] = branch_context_id

    return result


def write_capture(
    root,
    capture_id,
):
    directory = (
        root
        / capture_id
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    for filename in REQUIRED_ARTIFACTS:
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

        manifest = []

        for item in plan[
            "state_sources"
        ]:
            entry = {
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

            manifest.append(
                entry
            )

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


KEY_A = "a" * 64
KEY_B = "b" * 64


def test_two_branch_contexts_do_not_collapse_into_one_physical_state(
    tmp_path,
):
    # Regression for section 3/16 of the UWT-5 work order: a previously
    # materialized ACTIVE physical state scoped to branch A must never
    # silently absorb a newly observed state sharing the exact same
    # (pathname, functional_state) but scoped to a DIFFERENT branch B.
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

    state_id_a = (
        automatic_materialization_module
        ._state_id(
            KEY_A
        )
    )

    previous = {
        "twin_key":
            "twin_x",

        "materialized_revision_id":
            "matrev-active",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    state_id_a,

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    "EX01_PERSONAL",

                # Deliberately NOT persisting branch_context_id here,
                # mirroring materialization_builder.py's current
                # physical/runtime manifest shape -- the governing
                # Observation Store entry below is the sole source of
                # truth UWT-5 is authorized to rely on.
            },
        ],
    }

    states = {
        KEY_A:
            observed_state(
                KEY_A,
                "/es/",
                "cap-a",
                functional_state="EX01_PERSONAL",
                branch_context_id=CTX_A,
            ),

        KEY_B:
            observed_state(
                KEY_B,
                "/es/",
                "cap-b",
                functional_state="EX01_PERSONAL",
                branch_context_id=CTX_B,
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
            capture_root=captures,
            trigger_capture_id="cap-b",
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
        result["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    assert (
        result["added_state_count"]
        == 1
    )

    assert (
        result["state_count"]
        == 2
    )

    state_sources = plan_calls[0][
        "state_sources"
    ]

    assert len(
        state_sources
    ) == 2

    branch_context_ids = {
        source.get(
            "branch_context_id"
        )
        for source in state_sources
    }

    assert branch_context_ids == {
        CTX_A,
        CTX_B,
    }


def test_active_branch_a_delta_branch_a_converges_without_duplicate(
    tmp_path,
):
    # Section 16: ACTIVE branch A + delta branch A must converge --
    # never create a duplicate physical representative.
    captures = (
        tmp_path
        / "captures"
    )

    write_capture(
        captures,
        "cap-a",
    )

    state_id_a = (
        automatic_materialization_module
        ._state_id(
            KEY_A
        )
    )

    previous = {
        "twin_key":
            "twin_x",

        "materialized_revision_id":
            "matrev-active",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    state_id_a,

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    "EX01_PERSONAL",
            },
        ],
    }

    states = {
        KEY_A:
            observed_state(
                KEY_A,
                "/es/",
                "cap-a",
                functional_state="EX01_PERSONAL",
                branch_context_id=CTX_A,
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
            capture_root=captures,
            trigger_capture_id="cap-a",
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
        result["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_NO_CHANGE
    )

    assert (
        result["added_state_count"]
        == 0
    )

    assert plan_calls == []


def test_carry_forward_preserves_branch_context_id_in_state_sources(
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

    state_id_a = (
        automatic_materialization_module
        ._state_id(
            KEY_A
        )
    )

    previous = {
        "twin_key":
            "twin_x",

        "materialized_revision_id":
            "matrev-active",

        "materialization_mode":
            "BOOTSTRAP_REAL",

        "state_manifest": [
            {
                "state_id":
                    state_id_a,

                "source_capture_id":
                    "cap-a",

                "pathname":
                    "/es/",

                "functional_state":
                    "EX01_PERSONAL",
            },
        ],
    }

    # A brand-new, unrelated state_key triggers a real
    # DISCOVERY_EXTENSION pass so the carry-forward loop actually runs
    # for the already-materialized branch-A state above.
    states = {
        KEY_A:
            observed_state(
                KEY_A,
                "/es/",
                "cap-a",
                functional_state="EX01_PERSONAL",
                branch_context_id=CTX_A,
            ),

        KEY_B:
            observed_state(
                KEY_B,
                "/es/otro",
                "cap-b",
                functional_state=None,
            ),
    }

    plan_calls = []

    reconcile_auto_twin_discovery_materialization(
        managed_site_store=(
            ManagedStore()
        ),
        observation_store=(
            ObservationStore(
                states
            )
        ),
        capture_root=captures,
        trigger_capture_id="cap-b",
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

    state_sources = plan_calls[0][
        "state_sources"
    ]

    carried = next(
        source
        for source in state_sources
        if source["state_id"]
        == state_id_a
    )

    assert (
        carried["branch_context_id"]
        == CTX_A
    )


def test_unscoped_states_remain_legacy_compatible(
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

    states = {
        KEY_A:
            observed_state(
                KEY_A,
                "/es/",
                "cap-a",
                functional_state="EX01_PERSONAL",
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
            capture_root=captures,
            trigger_capture_id="cap-a",
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
                materializer_spy([])
            ),
        )
    )

    assert (
        result["status"]
        == AUTO_TWIN_AUTO_MATERIALIZATION_MATERIALIZED
    )

    state_sources = plan_calls[0][
        "state_sources"
    ]

    assert (
        "branch_context_id"
        not in state_sources[0]
    )


def test_genuine_duplicate_state_id_still_fails_closed_with_branch_scope(
    tmp_path,
):
    # Two distinct branch-scoped observations whose state_key happens
    # to collide on the first 24 safe characters _state_id() truncates
    # to must still raise the existing collision guard -- branch
    # awareness must never weaken it.
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

    colliding_prefix = "f" * 24

    key_one = (
        colliding_prefix
        + "1" * 40
    )

    key_two = (
        colliding_prefix
        + "2" * 40
    )

    assert (
        automatic_materialization_module
        ._state_id(
            key_one
        )
        == automatic_materialization_module
        ._state_id(
            key_two
        )
    )

    states = {
        key_one:
            observed_state(
                key_one,
                "/es/uno",
                "cap-a",
            ),

        key_two:
            observed_state(
                key_two,
                "/es/dos",
                "cap-b",
            ),
    }

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_DISCOVERY_STATE_ID_COLLISION"
        ),
    ):
        reconcile_auto_twin_discovery_materialization(
            managed_site_store=(
                ManagedStore()
            ),
            observation_store=(
                ObservationStore(
                    states
                )
            ),
            capture_root=captures,
            trigger_capture_id="cap-b",
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


def test_identity_helper_does_not_alter_functional_state_or_pathname():
    identity_without_branch = (
        automatic_materialization_module
        ._identity(
            "/es/",
            "EX01_PERSONAL",
        )
    )

    identity_with_branch = (
        automatic_materialization_module
        ._identity(
            "/es/",
            "EX01_PERSONAL",
            CTX_A,
        )
    )

    assert (
        identity_without_branch[0]
        == identity_with_branch[0]
        == "/es/"
    )

    assert (
        identity_without_branch[1]
        == identity_with_branch[1]
        == "EX01_PERSONAL"
    )

    assert len(identity_without_branch) == 2
    assert identity_with_branch[2] == CTX_A
