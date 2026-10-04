import json
from pathlib import Path

import pytest

from backend.qcc.auto_twin.form_effect_evidence_store import (
    AutoTwinFormEffectEvidenceStore,
)

from backend.qcc.auto_twin.form_effect_runtime import (
    AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID,
    AUTO_TWIN_FORM_EFFECT_RUNTIME_SCRIPT_MARKER,
)

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

            "network_sterilizer_version":
                AUTO_TWIN_NETWORK_STERILIZER_VERSION,
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


def test_form_effect_runtime_artifacts_survive_carry_forward(
    tmp_path,
    monkeypatch,
):
    """UWT-6B3-1C2: a historically materialized form-effect runtime
    (JSON payload artifact + adapter script + HTML wiring) must be
    preserved byte-for-byte by MATERIALIZED_CARRY_FORWARD, without the
    builder ever consulting the current form-effect evidence store."""

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "MATERIALIZED_CARRY_FORWARD must never load form-effect "
            "evidence"
        )

    monkeypatch.setattr(
        AutoTwinFormEffectEvidenceStore,
        "get",
        fail_if_called,
    )

    materialized_root = (
        tmp_path
        / "materialized"
    )

    base_revision = (
        materialized_root
        / "red_sara"
        / "matrev-golden-form"
    )

    state_root = (
        base_revision
        / "states"
        / "01-STATE_GOLDEN_FORM"
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

            "network_sterilizer_version":
                AUTO_TWIN_NETWORK_STERILIZER_VERSION,
        }),
        encoding="utf-8",
    )

    golden_payload = {
        "schema_version": 1,
        "record_type": "QCC_AUTO_TWIN_FORM_EFFECT_RUNTIME_PLAN",
        "contextual_effects": "NO",
        "route_count": 1,
        "routes": [
            {
                "trigger": {
                    "state_id": "STATE_GOLDEN_FORM",
                    "action": {
                        "kind": "SELECT",
                        "selector": "#plan",
                        "frame_path": "main",
                    },
                    "mutation_identity": {
                        "kind": "SELECT",
                        "selected_index": 1,
                    },
                },
                "status": "EXECUTABLE",
                "blocked_effect_kinds": [],
                "executable_effects": [],
                "delegated_effects": [],
            },
        ],
    }

    (
        runtime
        / AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME
    ).write_text(
        json.dumps(golden_payload),
        encoding="utf-8",
    )

    golden_adapter_js = "/* GOLDEN FORM EFFECT ADAPTER */\n"

    (
        runtime
        / AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME
    ).write_text(
        golden_adapter_js,
        encoding="utf-8",
    )

    golden_html = (
        "<html><body>GOLDEN-FORM-RUNTIME-EXACT"
        '<script type="application/json" id="'
        + AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID
        + '">'
        + json.dumps(golden_payload)
        + "</script>"
        + "<script "
        + AUTO_TWIN_FORM_EFFECT_RUNTIME_SCRIPT_MARKER
        + '="1" src="'
        + AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME
        + '"></script>'
        + "</body></html>"
    )

    (
        runtime
        / "index.html"
    ).write_text(
        golden_html,
        encoding="utf-8",
    )

    state_metadata = {
        "state_id":
            "STATE_GOLDEN_FORM",

        "source_capture_id":
            "capture-historical-form",

        "pathname":
            "/es/nuevo-registro",

        "functional_state":
            None,

        "form_effect_runtime_adapter_version":
            1,

        "form_effect_runtime_fingerprint":
            "f" * 64,

        "form_effect_route_count":
            1,

        "form_effect_evidence_ids": [
            "e" * 64,
        ],
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
            "matplan-carry-forward-form-effect-test",

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
            "matrev-golden-form",

        "source_capture_ids": [
            "capture-historical-form",
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
                    "STATE_GOLDEN_FORM",

                "source_capture_id":
                    "capture-historical-form",

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

                # Carry-forward never requires form_effect_evidence_ids
                # in the NEW plan -- the copied state owns its already-
                # materialized runtime byte content.
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
        / "01-STATE_GOLDEN_FORM"
        / "runtime"
    )

    assert (
        carried
        / AUTO_TWIN_FORM_EFFECT_RUNTIME_FILENAME
    ).read_text(
        encoding="utf-8"
    ) == json.dumps(golden_payload)

    assert (
        carried
        / AUTO_TWIN_FORM_EFFECT_RUNTIME_ADAPTER_FILENAME
    ).read_text(
        encoding="utf-8"
    ) == golden_adapter_js

    carried_html = (
        carried
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert carried_html == golden_html

    # No duplicate payload/script markers after the (already existing)
    # second-pass Navigation Runtime wiring.
    assert carried_html.count(
        'id="' + AUTO_TWIN_FORM_EFFECT_RUNTIME_PAYLOAD_ELEMENT_ID + '"'
    ) == 1

    assert carried_html.count(
        AUTO_TWIN_FORM_EFFECT_RUNTIME_SCRIPT_MARKER + '="'
    ) == 1

    carried_state_metadata = json.loads(
        (
            carried
            / "state.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        carried_state_metadata[
            "form_effect_runtime_fingerprint"
        ]
        == "f" * 64
    )

    assert (
        carried_state_metadata[
            "form_effect_evidence_ids"
        ]
        == ["e" * 64]
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


# =============================================================================
# UWT-7A1-FIX2: a MATERIALIZED_CARRY_FORWARD base revision is physically
# compatible only when BOTH the renderer version AND the network
# sterilizer version are current -- carried-forward runtime HTML is
# adopted byte-for-byte and is never re-sterilized, so a stale/missing/
# invalid sterilizer marker must fail closed exactly like a renderer
# mismatch.
# =============================================================================


def _minimal_carry_forward_plan(
    base_revision_id,
):
    return {
        "plan_type":
            AUTO_TWIN_MATERIALIZATION_PLAN_TYPE,

        "twin_key":
            "red_sara",

        "base_materialized_revision_id":
            base_revision_id,

        "state_manifest": [
            {
                "state_index":
                    1,

                "state_id":
                    "STATE_GOLDEN",

                "source_mode":
                    (
                        AUTO_TWIN_STATE_SOURCE_MATERIALIZED_CARRY_FORWARD
                    ),
            },
        ],
    }


def test_carry_forward_rejects_stale_network_sterilizer_version(
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

            "network_sterilizer_version":
                AUTO_TWIN_NETWORK_STERILIZER_VERSION
                - 1,
        }),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CARRY_FORWARD_STERILIZER_MISMATCH"
        ),
    ):
        materialize_auto_twin_plan(
            plan=(
                _minimal_carry_forward_plan(
                    "matrev-golden"
                )
            ),
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


def test_carry_forward_rejects_missing_network_sterilizer_version(
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

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CARRY_FORWARD_STERILIZER_INVALID"
        ),
    ):
        materialize_auto_twin_plan(
            plan=(
                _minimal_carry_forward_plan(
                    "matrev-golden"
                )
            ),
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


def test_carry_forward_rejects_stale_renderer_version(
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
                AUTO_TWIN_RUNTIME_RENDERER_VERSION
                - 1,

            "network_sterilizer_version":
                AUTO_TWIN_NETWORK_STERILIZER_VERSION,
        }),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_AUTO_TWIN_CARRY_FORWARD_RENDERER_MISMATCH"
        ),
    ):
        materialize_auto_twin_plan(
            plan=(
                _minimal_carry_forward_plan(
                    "matrev-golden"
                )
            ),
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
