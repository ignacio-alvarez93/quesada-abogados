import json
from pathlib import Path

from backend.qcc.auto_twin.materialization_builder import (
    AUTO_TWIN_RUNTIME_RENDERER_VERSION,
    materialize_auto_twin_plan,
)

from backend.qcc.auto_twin.materialization_plan import (
    AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,
    AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD,
)


def test_materialized_state_is_carried_forward_byte_for_byte(
    tmp_path,
):
    materialized_root = (
        tmp_path
        / "materialized"
    )

    base_revision = (
        materialized_root
        / "red_sara"
        / "matrev-golden"
    )

    state_root = (
        base_revision
        / "states"
        / "01-STATE_GOLDEN"
    )

    runtime = (
        state_root
        / "runtime"
    )

    runtime.mkdir(
        parents=True
    )

    (
        base_revision
        / "runtime"
    ).mkdir(
        parents=True
    )

    (
        base_revision
        / "runtime"
        / "renderer.json"
    ).write_text(
        json.dumps({
            "renderer_version":
                AUTO_TWIN_RUNTIME_RENDERER_VERSION,
        }),
        encoding="utf-8",
    )

    state_metadata = {
        "state_id":
            "STATE_GOLDEN",

        "source_capture_id":
            "capture-historical",

        "pathname":
            "/es/nuevo-registro",

        "functional_state":
            None,
    }

    (
        runtime
        / "state.json"
    ).write_text(
        json.dumps(
            state_metadata
        ),
        encoding="utf-8",
    )

    golden_html = (
        "<html><body>GOLDEN-RUNTIME-EXACT</body></html>"
    )

    (
        runtime
        / "index.html"
    ).write_text(
        golden_html,
        encoding="utf-8",
    )

    (
        runtime
        / "shadow_styles.json"
    ).write_text(
        '{"golden":true}',
        encoding="utf-8",
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
        '{"golden":"evidence"}',
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
        "GOLDEN-SOURCE",
        encoding="utf-8",
    )

    plan = {
        "schema_version":
            1,

        "plan_type":
            AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,

        "plan_id":
            "matplan-carry-forward-test",

        "twin_key":
            "red_sara",

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
            "capture-historical",
        ],

        "source_evidence_sha256":
            "a" * 64,

        "artifact_operations":
            [],

        "state_manifest": [
            {
                "state_index":
                    1,

                "state_id":
                    "STATE_GOLDEN",

                "source_capture_id":
                    "capture-historical",

                "pathname":
                    "/es/nuevo-registro",

                "functional_state":
                    None,

                "rendering_profile_id":
                    "MATERIALIZED_CARRY_FORWARD",

                "source_mode":
                    (
                        AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
                    ),
            },
        ],
    }

    result = materialize_auto_twin_plan(
        plan=plan,
        source_root=(
            tmp_path
            / "captures"
        ),
        materialized_root=(
            materialized_root
        ),
        procedure_code="RED_SARA",
        flow_variant="SITE_LEVEL",
    )

    revision_dir = Path(
        result[
            "revision_dir"
        ]
    )

    carried = (
        revision_dir
        / "states"
        / "01-STATE_GOLDEN"
    )

    assert (
        carried
        / "runtime"
        / "index.html"
    ).read_text(
        encoding="utf-8"
    ) == golden_html

    assert (
        carried
        / "runtime"
        / "shadow_styles.json"
    ).read_text(
        encoding="utf-8"
    ) == '{"golden":true}'

    assert (
        carried
        / "evidence"
        / "qcc_capture.json"
    ).read_text(
        encoding="utf-8"
    ) == '{"golden":"evidence"}'

    assert (
        result[
            "revision"
        ][
            "state_manifest"
        ][0][
            "source_capture_id"
        ]
        == "capture-historical"
    )


def test_visual_enrichment_requires_known_unchanged_fingerprint(
    tmp_path,
):
    from backend.qcc.auto_twin.automatic_materialization import (
        _visual_enrichment_for_previous_state,
    )

    capture_root = (
        tmp_path
        / "captures"
    )

    trigger = "capture-new"

    trigger_dir = (
        capture_root
        / trigger
    )

    trigger_dir.mkdir(
        parents=True
    )

    (
        trigger_dir
        / "qcc_capture.json"
    ).write_text(
        json.dumps({
            "frames": [
                {
                    "frame_id":
                        0,

                    "result": {
                        "shadow_adopted_stylesheets": [
                            {
                                "readable":
                                    True,

                                "css_text":
                                    "button{display:block}",
                            },
                        ],
                    },
                },
            ],
        }),
        encoding="utf-8",
    )

    revision = (
        tmp_path
        / "matrev"
    )

    embedded = (
        revision
        / "states"
        / "01-STATE_HOME"
        / "evidence"
    )

    embedded.mkdir(
        parents=True
    )

    (
        embedded
        / "qcc_capture.json"
    ).write_text(
        json.dumps({
            "frames": [
                {
                    "frame_id":
                        0,

                    "result": {
                        "shadow_adopted_stylesheets":
                            [],
                    },
                },
            ],
        }),
        encoding="utf-8",
    )

    state = {
        "pathname":
            "/es/",

        "functional_state":
            None,

        "last_capture_id":
            trigger,

        "last_classification":
            "KNOWN",

        "baseline_fingerprint":
            "same",

        "last_fingerprint":
            "same",
    }

    result = (
        _visual_enrichment_for_previous_state(
            renderer_refresh=False,
            capture_root=capture_root,
            revision_dir=revision,
            previous_state_id=(
                "STATE_HOME"
            ),
            identity=(
                "/es/",
                None,
            ),
            observed_states={
                "state-key":
                    state,
            },
            trigger_capture_id=(
                trigger
            ),
        )
    )

    assert result is not None

    assert (
        result[
            "capture_id"
        ]
        == trigger
    )

    state[
        "last_classification"
    ] = "CHANGED"

    blocked = (
        _visual_enrichment_for_previous_state(
            renderer_refresh=False,
            capture_root=capture_root,
            revision_dir=revision,
            previous_state_id=(
                "STATE_HOME"
            ),
            identity=(
                "/es/",
                None,
            ),
            observed_states={
                "state-key":
                    state,
            },
            trigger_capture_id=(
                trigger
            ),
        )
    )

    assert blocked is None
