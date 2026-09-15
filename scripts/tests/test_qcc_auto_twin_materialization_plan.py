from copy import deepcopy
from pathlib import Path

import pytest

import backend.qcc.auto_twin.materialization_plan as plan_module

from backend.qcc.auto_twin.materialized_revision import (
    AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL,
)

from backend.qcc.auto_twin.materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS,
    build_auto_twin_materialization_plan,
)


REAL_ORIGIN = (
    "https://mercurio.delegaciondelgobierno.gob.es"
)


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
    profile="qcc_assisted",
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
    calls = []

    def fake_loader(
        *,
        capture_id,
        root,
        require_viewport_image,
    ):
        calls.append({
            "capture_id":
                capture_id,

            "root":
                Path(
                    root
                ),

            "require_viewport_image":
                require_viewport_image,
        })

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

    return calls


def _states():
    return [
        {
            "state_id":
                "MERCURIO_MODEL_SELECTION",

            "capture_id":
                "capture-model",

            "pathname":
                "/mercurio/seleccionModelo-33.html",

            "functional_state":
                "MERCURIO_MODEL_SELECTION",
        },
        {
            "state_id":
                "EX01_PERSONAL",

            "capture_id":
                "capture-personal",

            "pathname":
                "/mercurio/nuevaSolicitud-EX01.html",

            "functional_state":
                "EX01_PERSONAL",
        },
        {
            "state_id":
                "FINALIZATION",

            "capture_id":
                "capture-final",

            "pathname":
                "/mercurio/finalizacionSolicitud.html",

            "functional_state":
                None,
        },
    ]


def _bundles():
    return {
        "capture-model":
            _fake_bundle(
                capture_id=(
                    "capture-model"
                ),
                pathname=(
                    "/mercurio/seleccionModelo-33.html"
                ),
                functional_state=(
                    "MERCURIO_MODEL_SELECTION"
                ),
            ),

        "capture-personal":
            _fake_bundle(
                capture_id=(
                    "capture-personal"
                ),
                pathname=(
                    "/mercurio/nuevaSolicitud-EX01.html"
                ),
                functional_state=(
                    "EX01_PERSONAL"
                ),
            ),

        "capture-final":
            _fake_bundle(
                capture_id=(
                    "capture-final"
                ),
                pathname=(
                    "/mercurio/finalizacionSolicitud.html"
                ),
                functional_state=None,
            ),
    }


def _prepare(
    tmp_path,
):
    for capture_id in (
        "capture-model",
        "capture-personal",
        "capture-final",
    ):
        _write_source_files(
            tmp_path,
            capture_id,
        )


def _build(
    *,
    tmp_path,
    monkeypatch,
    states=None,
    bundles=None,
):
    _prepare(
        tmp_path
    )

    bundles = (
        _bundles()
        if bundles is None
        else bundles
    )

    calls = _install_loader(
        monkeypatch,
        bundles,
    )

    plan = (
        build_auto_twin_materialization_plan(
            twin_key="mercurio",
            materialization_mode=(
                AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
            ),
            state_sources=(
                _states()
                if states is None
                else states
            ),
            required_origin=(
                REAL_ORIGIN
            ),
            required_profile_key=(
                "qcc_assisted"
            ),
            root=tmp_path,
        )
    )

    return plan, calls


def test_plan_loads_only_explicit_capture_ids(
    tmp_path,
    monkeypatch,
):
    plan, calls = _build(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    assert [
        call[
            "capture_id"
        ]
        for call in calls
    ] == [
        "capture-model",
        "capture-personal",
        "capture-final",
    ]

    assert (
        plan[
            "source_capture_ids"
        ]
        == [
            "capture-model",
            "capture-personal",
            "capture-final",
        ]
    )


def test_plan_requires_registered_viewport_bundle(
    tmp_path,
    monkeypatch,
):
    _plan, calls = _build(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    assert all(
        call[
            "require_viewport_image"
        ]
        is True
        for call
        in calls
    )


def test_plan_contains_all_required_source_artifacts(
    tmp_path,
    monkeypatch,
):
    plan, _calls = _build(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    expected_per_state = len(
        AUTO_TWIN_MATERIALIZATION_SOURCE_ARTIFACTS
    )

    assert len(
        plan[
            "artifact_operations"
        ]
    ) == (
        3
        * expected_per_state
    )

    kinds = {
        item[
            "kind"
        ]
        for item
        in plan[
            "artifact_operations"
        ]
    }

    assert kinds == {
        "RAW_CAPTURE",
        "SITE_ARCHITECTURE",
        "STATE_OBSERVATION",
        "METADATA",
        "PAGE_HTML",
        "PAGE_MHTML",
        "SCREENSHOT_VIEWPORT",
    }


def test_full_page_screenshot_is_not_required(
    tmp_path,
    monkeypatch,
):
    plan, _calls = _build(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    assert all(
        item[
            "source_filename"
        ]
        != "screenshot_full_page.png"
        for item
        in plan[
            "artifact_operations"
        ]
    )


def test_plan_has_no_absolute_local_source_paths(
    tmp_path,
    monkeypatch,
):
    plan, _calls = _build(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    serialized = repr(
        plan
    )

    assert (
        str(
            tmp_path
        )
        not in serialized
    )

    assert all(
        not Path(
            operation[
                "source_reference"
            ]
        ).is_absolute()
        for operation
        in plan[
            "artifact_operations"
        ]
    )


def test_destination_paths_are_deterministic_and_state_scoped(
    tmp_path,
    monkeypatch,
):
    plan, _calls = _build(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    html_ops = [
        item
        for item
        in plan[
            "artifact_operations"
        ]
        if item[
            "kind"
        ]
        == "PAGE_HTML"
    ]

    assert [
        item[
            "destination_path"
        ]
        for item
        in html_ops
    ] == [
        (
            "states/01-MERCURIO_MODEL_SELECTION/"
            "source/page.html"
        ),
        (
            "states/02-EX01_PERSONAL/"
            "source/page.html"
        ),
        (
            "states/03-FINALIZATION/"
            "source/page.html"
        ),
    ]


def test_plan_id_and_source_hash_are_deterministic(
    tmp_path,
    monkeypatch,
):
    first, _calls = _build(
        tmp_path=(
            tmp_path
            / "first"
        ),
        monkeypatch=monkeypatch,
    )

    second_root = (
        tmp_path
        / "second"
    )

    # Reinstall because the monkeypatch target is the same but each
    # build has its own explicit source root.
    second, _calls = _build(
        tmp_path=second_root,
        monkeypatch=monkeypatch,
    )

    assert (
        first[
            "plan_id"
        ]
        == second[
            "plan_id"
        ]
    )

    assert (
        first[
            "source_evidence_sha256"
        ]
        == second[
            "source_evidence_sha256"
        ]
    )


def test_origin_mismatch_is_rejected(
    tmp_path,
    monkeypatch,
):
    bundles = _bundles()

    bundles[
        "capture-personal"
    ][
        "snapshot"
    ][
        "page"
    ][
        "origin"
    ] = "http://127.0.0.1:8767"

    with pytest.raises(
        ValueError,
        match=(
            "ORIGIN_MISMATCH"
        ),
    ):
        _build(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            bundles=bundles,
        )


def test_profile_mismatch_is_rejected(
    tmp_path,
    monkeypatch,
):
    bundles = _bundles()

    bundles[
        "capture-personal"
    ][
        "capture"
    ][
        "browser_profile_key"
    ] = "qcc_smoke_local"

    with pytest.raises(
        ValueError,
        match=(
            "PROFILE_MISMATCH"
        ),
    ):
        _build(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            bundles=bundles,
        )


def test_pathname_mismatch_is_rejected(
    tmp_path,
    monkeypatch,
):
    bundles = _bundles()

    bundles[
        "capture-personal"
    ][
        "capture"
    ][
        "pathname"
    ] = "/wrong"

    with pytest.raises(
        ValueError,
        match=(
            "PATHNAME_MISMATCH"
        ),
    ):
        _build(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            bundles=bundles,
        )


def test_functional_state_mismatch_is_rejected(
    tmp_path,
    monkeypatch,
):
    bundles = _bundles()

    bundles[
        "capture-personal"
    ][
        "capture"
    ][
        "functional_state"
    ] = "EX01_PRESENTER"

    with pytest.raises(
        ValueError,
        match=(
            "FUNCTIONAL_STATE_MISMATCH"
        ),
    ):
        _build(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            bundles=bundles,
        )


def test_duplicate_state_id_is_rejected(
    tmp_path,
    monkeypatch,
):
    states = _states()

    states[1][
        "state_id"
    ] = states[0][
        "state_id"
    ]

    with pytest.raises(
        ValueError,
        match=(
            "STATE_ID_DUPLICATE"
        ),
    ):
        _build(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            states=states,
        )


def test_duplicate_capture_id_is_rejected(
    tmp_path,
    monkeypatch,
):
    states = _states()

    states[1][
        "capture_id"
    ] = states[0][
        "capture_id"
    ]

    with pytest.raises(
        ValueError,
        match=(
            "CAPTURE_ID_DUPLICATE"
        ),
    ):
        _build(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            states=states,
        )


def test_missing_required_artifact_is_rejected(
    tmp_path,
    monkeypatch,
):
    _prepare(
        tmp_path
    )

    (
        tmp_path
        / "capture-personal"
        / "page.mhtml"
    ).unlink()

    _install_loader(
        monkeypatch,
        _bundles(),
    )

    with pytest.raises(
        ValueError,
        match=(
            "SOURCE_ARTIFACT_MISSING"
        ),
    ):
        build_auto_twin_materialization_plan(
            twin_key="mercurio",
            materialization_mode=(
                AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
            ),
            state_sources=_states(),
            required_origin=(
                REAL_ORIGIN
            ),
            required_profile_key=(
                "qcc_assisted"
            ),
            root=tmp_path,
        )


def test_planner_does_not_create_files_or_directories_outside_sources(
    tmp_path,
    monkeypatch,
):
    source_root = (
        tmp_path
        / "source"
    )

    plan, _calls = _build(
        tmp_path=source_root,
        monkeypatch=monkeypatch,
    )

    before = sorted(
        path.relative_to(
            tmp_path
        ).as_posix()
        for path
        in tmp_path.rglob("*")
    )

    # Build a second time: pure operation must not alter filesystem.
    build_auto_twin_materialization_plan(
        twin_key="mercurio",
        materialization_mode=(
            AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
        ),
        state_sources=_states(),
        required_origin=(
            REAL_ORIGIN
        ),
        required_profile_key=(
            "qcc_assisted"
        ),
        root=source_root,
    )

    after = sorted(
        path.relative_to(
            tmp_path
        ).as_posix()
        for path
        in tmp_path.rglob("*")
    )

    assert before == after

    assert plan[
        "generation_source"
    ] == "REAL_EVIDENCE_ONLY"


def test_plan_contains_no_candidate_validation_or_active_contract(
    tmp_path,
    monkeypatch,
):
    plan, _calls = _build(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    serialized = repr(
        plan
    ).lower()

    assert "candidate_id" not in serialized
    assert "validation_evidence" not in serialized
    assert "active" not in serialized
    assert "promotion" not in serialized
    assert "golden" not in serialized



def test_plan_supports_materialized_carry_forward_without_live_capture(
    tmp_path,
):
    from backend.qcc.auto_twin.materialization_plan import (
        AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
    )

    plan = build_auto_twin_materialization_plan(
        twin_key="red_sara",
        materialization_mode=(
            AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
        ),
        state_sources=[
            {
                "state_id":
                    "STATE_GOLDEN",

                "capture_id":
                    "capture-historical",

                "pathname":
                    "/es/nuevo-registro",

                "functional_state":
                    None,

                "source_mode":
                    (
                        AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
                    ),
            },
        ],
        required_origin=(
            "https://reg.redsara.es"
        ),
        required_profile_key=(
            "twin_discovery"
        ),
        base_materialized_revision_id=(
            "matrev-golden"
        ),
        root=tmp_path,
    )

    assert (
        plan[
            "base_materialized_revision_id"
        ]
        == "matrev-golden"
    )

    assert (
        plan[
            "state_manifest"
        ][0][
            "source_mode"
        ]
        == (
            AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
        )
    )

    assert (
        plan[
            "artifact_operations"
        ]
        == []
    )

    assert (
        plan[
            "source_capture_ids"
        ]
        == [
            "capture-historical"
        ]
    )


def test_plan_carry_forward_requires_base_revision(
    tmp_path,
):
    from backend.qcc.auto_twin.materialization_plan import (
        AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
    )

    with pytest.raises(
        ValueError,
        match=(
            "CARRY_FORWARD_BASE_REVISION_REQUIRED"
        ),
    ):
        build_auto_twin_materialization_plan(
            twin_key="red_sara",
            materialization_mode=(
                AUTO_TWIN_MATERIALIZATION_MODE_BOOTSTRAP_REAL
            ),
            state_sources=[
                {
                    "state_id":
                        "STATE_GOLDEN",

                    "capture_id":
                        "capture-historical",

                    "pathname":
                        "/es/nuevo-registro",

                    "functional_state":
                        None,

                    "source_mode":
                        (
                            AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
                        ),
                },
            ],
            required_origin=(
                "https://reg.redsara.es"
            ),
            required_profile_key=(
                "twin_discovery"
            ),
            root=tmp_path,
        )
