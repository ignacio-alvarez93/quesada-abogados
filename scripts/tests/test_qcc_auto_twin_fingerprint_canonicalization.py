import json

from backend.qcc.auto_twin.automatic_materialization import (
    _canonical_previous_states_by_fingerprint,
    _observed_state_fingerprint,
)


FP_A = "a" * 64
FP_B = "b" * 64


def _previous(
    state_id,
    capture_id,
    pathname,
    functional_state,
):
    return {
        "state_id":
            state_id,

        "source_capture_id":
            capture_id,

        "pathname":
            pathname,

        "functional_state":
            functional_state,
    }


def test_previous_duplicate_functional_fingerprints_collapse_to_one(
    tmp_path,
):
    revision = (
        tmp_path
        / "matrev-current"
    )

    runtime = (
        revision
        / "runtime"
    )

    runtime.mkdir(
        parents=True
    )

    (
        runtime
        / "registry.json"
    ).write_text(
        json.dumps({
            "states": [
                {
                    "state_id":
                        "STATE_A",

                    "fingerprint":
                        FP_A,
                },
                {
                    "state_id":
                        "STATE_B_SESSION_1",

                    "fingerprint":
                        FP_B,
                },
                {
                    "state_id":
                        "STATE_B_SESSION_2",

                    "fingerprint":
                        FP_B,
                },
                {
                    "state_id":
                        "STATE_B_CANONICAL",

                    "fingerprint":
                        FP_B,
                },
            ],
        }),
        encoding="utf-8",
    )

    previous = [
        _previous(
            "STATE_A",
            "20260909_050000_a",
            "/mercurio/inicio.html",
            "MERCURIO_INICIO",
        ),
        _previous(
            "STATE_B_SESSION_1",
            "20260909_060000_b",
            (
                "/mercurio/modoAcceso.html"
                ";jsessionid=SESSION1"
            ),
            None,
        ),
        _previous(
            "STATE_B_SESSION_2",
            "20260909_061000_c",
            (
                "/mercurio/modoAcceso.html"
                ";jsessionid=SESSION2"
            ),
            None,
        ),
        _previous(
            "STATE_B_CANONICAL",
            "20260909_125000_d",
            "/mercurio/modoAcceso.html",
            "MERCURIO_MODO_ACCESO",
        ),
    ]

    canonical = (
        _canonical_previous_states_by_fingerprint(
            previous,
            revision,
        )
    )

    assert [
        item[
            "state_id"
        ]
        for item in canonical
    ] == [
        "STATE_A",
        "STATE_B_CANONICAL",
    ]


def test_observed_state_prefers_last_functional_fingerprint():
    result = _observed_state_fingerprint(
        "c" * 64,
        {
            "baseline_fingerprint":
                "d" * 64,

            "last_fingerprint":
                FP_B,
        },
    )

    assert result == FP_B
