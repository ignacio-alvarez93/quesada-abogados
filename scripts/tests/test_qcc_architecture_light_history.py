import json

from backend.qcc.site_architecture.light_history import (
    QccArchitectureLightHistory,
)


def _history(
    tmp_path,
):
    return QccArchitectureLightHistory(
        root=(
            tmp_path
            / "history"
        )
    )


def _append(
    history,
    *,
    capture_id,
    fingerprint,
    scope="FORM_EX01",
    state="EX01_PERSONAL",
):
    return history.append(
        capture_id=
            capture_id,

        observed_at=
            "2026-09-03T20:00:00+00:00",

        browser_profile_key=
            "qcc-test",

        origin=
            "https://example.com/path",

        site_code=
            "MERCURIO",

        architecture_scope=
            scope,

        functional_state=
            state,

        fingerprint=
            fingerprint,
    )


def test_first_observation_has_no_change_baseline(
    tmp_path,
):
    result = _append(
        _history(
            tmp_path
        ),
        capture_id="capture-001",
        fingerprint="AAA",
    )

    assert (
        result["previous_fingerprint"]
        is None
    )

    assert result["changed"] is None


def test_same_fingerprint_is_not_change(
    tmp_path,
):
    history = _history(
        tmp_path
    )

    _append(
        history,
        capture_id="capture-001",
        fingerprint="AAA",
    )

    result = _append(
        history,
        capture_id="capture-002",
        fingerprint="AAA",
    )

    assert (
        result["previous_fingerprint"]
        == "AAA"
    )

    assert result["changed"] is False


def test_changed_fingerprint_detects_drift(
    tmp_path,
):
    history = _history(
        tmp_path
    )

    _append(
        history,
        capture_id="capture-001",
        fingerprint="AAA",
    )

    result = _append(
        history,
        capture_id="capture-002",
        fingerprint="BBB",
    )

    assert (
        result["previous_fingerprint"]
        == "AAA"
    )

    assert result["fingerprint"] == "BBB"
    assert result["changed"] is True


def test_different_functional_states_have_independent_history(
    tmp_path,
):
    history = _history(
        tmp_path
    )

    _append(
        history,
        capture_id="capture-personal",
        fingerprint="PERSONAL-A",
        state="EX01_PERSONAL",
    )

    result = _append(
        history,
        capture_id="capture-notification",
        fingerprint="NOTIFICATION-A",
        state="EX01_NOTIFICATION",
    )

    assert (
        result["previous_fingerprint"]
        is None
    )

    assert result["changed"] is None


def test_different_forms_have_independent_history(
    tmp_path,
):
    history = _history(
        tmp_path
    )

    _append(
        history,
        capture_id="capture-ex01",
        fingerprint="EX01-A",
        scope="FORM_EX01",
    )

    result = _append(
        history,
        capture_id="capture-ex26",
        fingerprint="EX26-A",
        scope="FORM_EX26",
    )

    assert (
        result["previous_fingerprint"]
        is None
    )


def test_history_is_jsonl_and_contains_only_lightweight_fields(
    tmp_path,
):
    history = _history(
        tmp_path
    )

    _append(
        history,
        capture_id="capture-001",
        fingerprint="AAA",
    )

    files = list(
        history.root.glob(
            "*.jsonl"
        )
    )

    assert len(files) == 1

    rows = [
        json.loads(
            line
        )
        for line in (
            files[0]
            .read_text(
                encoding="utf-8"
            )
            .splitlines()
        )
        if line.strip()
    ]

    assert len(rows) == 1

    row = rows[0]

    assert set(row) == {
        "schema_version",
        "observation_type",
        "observed_at",
        "capture_id",
        "browser_profile_key",
        "origin",
        "architecture_scope",
        "functional_state",
        "site_code",
        "fingerprint",
        "previous_fingerprint",
        "changed",
    }

    serialized = json.dumps(
        row
    ).lower()

    for forbidden in (
        "documents",
        "elements",
        "page_html",
        "mhtml",
        "screenshot",
        "geometry",
        "outerhtml",
    ):
        assert forbidden not in serialized


def test_invalid_unbound_identity_is_not_persisted(
    tmp_path,
):
    history = _history(
        tmp_path
    )

    result = history.append(
        capture_id="capture-001",
        observed_at=None,
        browser_profile_key=None,
        origin="https://example.com",
        site_code=None,
        architecture_scope="GENERAL",
        functional_state=None,
        fingerprint="AAA",
    )

    assert result is None
    assert not history.root.exists()


def test_history_survives_heavy_capture_retention_semantically(
    tmp_path,
):
    history = _history(
        tmp_path
    )

    for number in range(
        1,
        101,
    ):
        _append(
            history,
            capture_id=
                f"capture-{number:03d}",
            fingerprint=(
                "AAA"
                if number < 100
                else "BBB"
            ),
        )

    files = list(
        history.root.glob(
            "*.jsonl"
        )
    )

    assert len(files) == 1

    rows = (
        files[0]
        .read_text(
            encoding="utf-8"
        )
        .splitlines()
    )

    assert len(rows) == 100

    last = json.loads(
        rows[-1]
    )

    assert (
        last["previous_fingerprint"]
        == "AAA"
    )

    assert last["fingerprint"] == "BBB"
    assert last["changed"] is True
