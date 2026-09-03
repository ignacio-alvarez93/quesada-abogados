import json

from backend.qcc.site_architecture.ingestor import (
    QccSiteArchitectureIngestor,
)


MODE = (
    "PROFILE_ORIGIN_ARCHITECTURE_SCOPE_RING"
)


def _ingestor(
    tmp_path,
    *,
    limit=3,
):
    return QccSiteArchitectureIngestor(
        output_root=tmp_path,
        recognizer_registry=object(),
        retention_limit=limit,
    )


def _capture(
    root,
    capture_id,
    *,
    scope="FORM_EX01",
    state=None,
    profile="profile-a",
    origin="https://example.com",
):
    folder = root / capture_id
    folder.mkdir()

    metadata = {
        "capture_id":
            capture_id,

        "retention": {
            "mode":
                MODE,

            "browser_profile_key":
                profile,

            "origin":
                origin,

            "architecture_scope":
                scope,

            "functional_state":
                state,
        },
    }

    (
        folder
        / "metadata.json"
    ).write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    return folder


def _scope(
    *,
    architecture_scope="FORM_EX01",
):
    return {
        "browser_profile_key":
            "profile-a",

        "origin":
            "https://example.com",

        "architecture_scope":
            architecture_scope,
    }


def test_retention_scope_defaults_to_general(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path
    )

    result = ingestor._retention_scope(
        {
            "browser_profile_key":
                "profile-a",
        },
        page_url="https://example.com/a",
    )

    assert (
        result["architecture_scope"]
        == "GENERAL"
    )


def test_retention_scope_carries_functional_state(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path
    )

    result = ingestor._retention_scope(
        {
            "browser_profile_key":
                "profile-a",
        },
        page_url="https://example.com/a",
        architecture_scope="FORM_EX01",
        functional_state="EX01_PERSONAL",
    )

    assert (
        result["architecture_scope"]
        == "FORM_EX01"
    )

    assert (
        result["functional_state"]
        == "EX01_PERSONAL"
    )


def test_different_forms_have_independent_rings(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path,
        limit=2,
    )

    _capture(
        tmp_path,
        "001-ex01-old",
        scope="FORM_EX01",
    )

    _capture(
        tmp_path,
        "002-ex01-middle",
        scope="FORM_EX01",
    )

    _capture(
        tmp_path,
        "003-ex26",
        scope="FORM_EX26",
    )

    _capture(
        tmp_path,
        "004-ex01-new",
        scope="FORM_EX01",
    )

    removed = (
        ingestor._prune_retention_scope(
            current_capture_id=
                "004-ex01-new",
            scope=_scope(
                architecture_scope=
                    "FORM_EX01"
            ),
        )
    )

    assert removed == [
        "001-ex01-old"
    ]

    assert (
        tmp_path
        / "003-ex26"
    ).exists()


def test_latest_capture_of_each_state_is_protected(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path,
        limit=3,
    )

    _capture(
        tmp_path,
        "001-auth-old",
        state="EX01_AUTHORIZATION",
    )

    _capture(
        tmp_path,
        "002-personal",
        state="EX01_PERSONAL",
    )

    _capture(
        tmp_path,
        "003-notification",
        state="EX01_NOTIFICATION",
    )

    _capture(
        tmp_path,
        "004-auth-new",
        state="EX01_AUTHORIZATION",
    )

    removed = (
        ingestor._prune_retention_scope(
            current_capture_id=
                "004-auth-new",
            scope=_scope(),
        )
    )

    assert removed == [
        "001-auth-old"
    ]

    assert (
        tmp_path
        / "002-personal"
    ).exists()

    assert (
        tmp_path
        / "003-notification"
    ).exists()

    assert (
        tmp_path
        / "004-auth-new"
    ).exists()


def test_old_duplicate_state_can_be_removed(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path,
        limit=2,
    )

    _capture(
        tmp_path,
        "001-personal-old",
        state="EX01_PERSONAL",
    )

    _capture(
        tmp_path,
        "002-notification",
        state="EX01_NOTIFICATION",
    )

    _capture(
        tmp_path,
        "003-personal-new",
        state="EX01_PERSONAL",
    )

    removed = (
        ingestor._prune_retention_scope(
            current_capture_id=
                "003-personal-new",
            scope=_scope(),
        )
    )

    assert removed == [
        "001-personal-old"
    ]


def test_semantic_protection_can_temporarily_exceed_limit(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path,
        limit=2,
    )

    _capture(
        tmp_path,
        "001-auth",
        state="EX01_AUTHORIZATION",
    )

    _capture(
        tmp_path,
        "002-personal",
        state="EX01_PERSONAL",
    )

    _capture(
        tmp_path,
        "003-notification",
        state="EX01_NOTIFICATION",
    )

    removed = (
        ingestor._prune_retention_scope(
            current_capture_id=
                "003-notification",
            scope=_scope(),
        )
    )

    assert removed == []

    assert len(
        list(
            tmp_path.iterdir()
        )
    ) == 3


def test_general_and_form_scope_do_not_mix(
    tmp_path,
):
    ingestor = _ingestor(
        tmp_path,
        limit=1,
    )

    _capture(
        tmp_path,
        "001-general",
        scope="GENERAL",
    )

    _capture(
        tmp_path,
        "002-form-old",
        scope="FORM_EX01",
    )

    _capture(
        tmp_path,
        "003-form-new",
        scope="FORM_EX01",
    )

    ingestor._prune_retention_scope(
        current_capture_id=
            "003-form-new",
        scope=_scope(),
    )

    assert (
        tmp_path
        / "001-general"
    ).exists()
