import json

from backend.qcc.auto_twin.automatic_materialization import (
    REQUIRED_ARTIFACTS,
    _complete_discovery_capture_for_fingerprint,
    _new_state_navigation_source,
)


FP_PERSONAL = (
    "d0af84caa02f93f585f9df7f3e2ef82"
    "b487348a64550e07c54f481e58e84e2f4"
)

FP_AUTH = (
    "0f048a41feded5af2ceae831e57bf6c1d"
    "79d3d86ccfe991c698a5b21e3e7aca2"
)


def _capture(
    root,
    capture_id,
    *,
    fingerprint,
    functional_state,
    profile="twin_discovery",
    complete=True,
):
    directory = (
        root
        / capture_id
    )

    directory.mkdir(
        parents=True,
    )

    for filename in REQUIRED_ARTIFACTS:

        if (
            not complete
            and filename
            in {
                "page.mhtml",
                "screenshot_viewport.png",
            }
        ):
            continue

        path = (
            directory
            / filename
        )

        if filename == "qcc_capture.json":

            path.write_text(
                json.dumps({
                    "browser_profile_key":
                        profile,
                }),
                encoding="utf-8",
            )

        elif filename == "state_observation.json":

            path.write_text(
                json.dumps({
                    "fingerprint":
                        fingerprint,

                    "state":
                        functional_state,
                }),
                encoding="utf-8",
            )

        elif filename.endswith(
            ".png"
        ):

            path.write_bytes(
                b"QCC_TEST_PNG"
            )

        else:

            path.write_text(
                "{}",
                encoding="utf-8",
            )


def _candidate():
    return {
        "before_fingerprint":
            FP_AUTH,

        "after_fingerprint":
            FP_PERSONAL,
    }


def _state(
    last_capture_id,
):
    return {
        "baseline_capture_id":
            "baseline",

        "last_capture_id":
            last_capture_id,

        "last_fingerprint":
            FP_PERSONAL,

        "functional_state":
            "EX01_PERSONAL",
    }


def test_exact_fingerprint_uses_newest_complete_discovery(
    tmp_path,
):
    _capture(
        tmp_path,
        "20260912_060635_incomplete",
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
        complete=False,
    )

    _capture(
        tmp_path,
        "20260912_060218_complete",
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
    )

    _capture(
        tmp_path,
        "20260912_060631_complete",
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
    )

    result = (
        _complete_discovery_capture_for_fingerprint(
            capture_root=tmp_path,
            fingerprint=FP_PERSONAL,
            functional_state="EX01_PERSONAL",
            exclude_capture_id=(
                "20260912_060635_incomplete"
            ),
        )
    )

    assert (
        result
        == "20260912_060631_complete"
    )


def test_incomplete_causal_last_uses_exact_equivalent(
    tmp_path,
):
    causal = (
        "20260912_060635_incomplete"
    )

    _capture(
        tmp_path,
        causal,
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
        complete=False,
    )

    _capture(
        tmp_path,
        "20260912_060631_complete",
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
    )

    source_id, source_kind = (
        _new_state_navigation_source(
            _state(
                causal
            ),
            (
                _candidate(),
            ),
            capture_root=tmp_path,
        )
    )

    assert (
        source_id
        == "20260912_060631_complete"
    )

    assert (
        source_kind
        == "CAUSAL_EQUIVALENT"
    )


def test_complete_causal_last_remains_primary(
    tmp_path,
):
    causal = (
        "20260912_060635_complete"
    )

    _capture(
        tmp_path,
        causal,
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
    )

    _capture(
        tmp_path,
        "20260912_060700_complete",
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
    )

    source_id, source_kind = (
        _new_state_navigation_source(
            _state(
                causal
            ),
            (
                _candidate(),
            ),
            capture_root=tmp_path,
        )
    )

    assert source_id == causal
    assert source_kind == "CAUSAL_LAST"


def test_wrong_fingerprint_is_never_used(
    tmp_path,
):
    causal = (
        "20260912_060635_incomplete"
    )

    _capture(
        tmp_path,
        causal,
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
        complete=False,
    )

    _capture(
        tmp_path,
        "20260912_060700_wrong",
        fingerprint=FP_AUTH,
        functional_state="EX01_PERSONAL",
    )

    source_id, source_kind = (
        _new_state_navigation_source(
            _state(
                causal
            ),
            (
                _candidate(),
            ),
            capture_root=tmp_path,
        )
    )

    assert source_id == causal
    assert source_kind == "CAUSAL_LAST"


def test_wrong_functional_state_is_never_used(
    tmp_path,
):
    causal = (
        "20260912_060635_incomplete"
    )

    _capture(
        tmp_path,
        causal,
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
        complete=False,
    )

    _capture(
        tmp_path,
        "20260912_060700_wrong_state",
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PRESENTER",
    )

    source_id, source_kind = (
        _new_state_navigation_source(
            _state(
                causal
            ),
            (
                _candidate(),
            ),
            capture_root=tmp_path,
        )
    )

    assert source_id == causal
    assert source_kind == "CAUSAL_LAST"


def test_non_discovery_capture_is_never_used(
    tmp_path,
):
    causal = (
        "20260912_060635_incomplete"
    )

    _capture(
        tmp_path,
        causal,
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
        complete=False,
    )

    _capture(
        tmp_path,
        "20260912_060700_assisted",
        fingerprint=FP_PERSONAL,
        functional_state="EX01_PERSONAL",
        profile="qcc_assisted",
    )

    source_id, source_kind = (
        _new_state_navigation_source(
            _state(
                causal
            ),
            (
                _candidate(),
            ),
            capture_root=tmp_path,
        )
    )

    assert source_id == causal
    assert source_kind == "CAUSAL_LAST"
