from datetime import (
    datetime,
    timezone,
)

import pytest

from backend.qcc.contracts.protocol import (
    QCC_PROTOCOL_VERSION,
    QccPresentationSession,
    QccPresentationStatus,
)
from backend.qcc.bridge.server import (
    QCC_PROTOCOL_VERSION
    as BRIDGE_PROTOCOL_VERSION,
)


def _session(
    **overrides,
):
    values = {
        "session_id":
            "qcc-session-001",

        "expedient_id":
            1842,

        "client_id":
            321,

        "procedure":
            "REAGRUPACION_FAMILIAR_INICIAL",

        "provider":
            "MERCURIO",

        "runtime":
            "SELENIUMBASE_ASSISTED",

        "started_at":
            datetime(
                2026,
                8,
                22,
                8,
                30,
                tzinfo=timezone.utc,
            ),

        "status":
            QccPresentationStatus.AUTOMATING,

        "current_step":
            "UPLOAD_DOCUMENTS",

        "progress":
            68,

        "requires_user_action":
            False,

        "last_event": {
            "event":
                "presentation.step_started",

            "message":
                "Adjuntando documentación",
        },
    }

    values.update(overrides)

    return QccPresentationSession(
        **values
    )


def test_protocol_version_is_one():
    assert QCC_PROTOCOL_VERSION == 1

    assert (
        BRIDGE_PROTOCOL_VERSION
        == QCC_PROTOCOL_VERSION
    )


def test_presentation_status_contract():
    assert {
        status.value
        for status
        in QccPresentationStatus
    } == {
        "AUTOMATING",
        "WAITING_USER",
        "USER_ACTION_DETECTED",
        "RESUMING",
        "COMPLETED",
        "ERROR",
    }


def test_session_serialization_contract():
    payload = _session().to_payload()

    assert payload == {
        "session_id":
            "qcc-session-001",

        "expedient_id":
            1842,

        "client_id":
            321,

        "procedure":
            "REAGRUPACION_FAMILIAR_INICIAL",

        "provider":
            "MERCURIO",

        "runtime":
            "SELENIUMBASE_ASSISTED",

        "started_at":
            "2026-08-22T08:30:00+00:00",

        "status":
            "AUTOMATING",

        "current_step":
            "UPLOAD_DOCUMENTS",

        "progress":
            68,

        "requires_user_action":
            False,

        "last_event": {
            "event":
                "presentation.step_started",

            "message":
                "Adjuntando documentación",
        },
    }


@pytest.mark.parametrize(
    "progress",
    [-1, 101],
)
def test_session_rejects_invalid_progress(
    progress,
):
    with pytest.raises(
        ValueError,
        match="QCC_PROGRESS_OUT_OF_RANGE",
    ):
        _session(
            progress=progress,
        )


def test_waiting_user_requires_action_flag():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_WAITING_USER_REQUIRES_ACTION"
        ),
    ):
        _session(
            status=(
                QccPresentationStatus
                .WAITING_USER
            ),
            requires_user_action=False,
        )


def test_waiting_user_accepts_action_flag():
    session = _session(
        status=(
            QccPresentationStatus
            .WAITING_USER
        ),
        requires_user_action=True,
    )

    assert (
        session.requires_user_action
        is True
    )


@pytest.mark.parametrize(
    (
        "field_name",
        "value",
        "error",
    ),
    [
        (
            "session_id",
            "",
            "QCC_SESSION_ID_REQUIRED",
        ),
        (
            "expedient_id",
            0,
            "QCC_EXPEDIENT_ID_INVALID",
        ),
        (
            "client_id",
            0,
            "QCC_CLIENT_ID_INVALID",
        ),
        (
            "procedure",
            "",
            "QCC_SESSION_FIELD_REQUIRED:"
            "procedure",
        ),
        (
            "provider",
            "",
            "QCC_SESSION_FIELD_REQUIRED:"
            "provider",
        ),
        (
            "runtime",
            "",
            "QCC_SESSION_FIELD_REQUIRED:"
            "runtime",
        ),
    ],
)
def test_session_rejects_invalid_identity(
    field_name,
    value,
    error,
):
    with pytest.raises(
        ValueError,
        match=error,
    ):
        _session(
            **{
                field_name: value,
            }
        )


def test_session_payload_has_no_browser_secrets():
    payload = _session().to_payload()

    forbidden = {
        "password",
        "cookie",
        "certificate",
        "token",
        "html",
        "dom",
    }

    keys = {
        key.lower()
        for key
        in payload
    }

    assert keys.isdisjoint(
        forbidden
    )



def test_session_supports_seleniumbase_assisted_runtime():
    session = _session(
        provider="MERCURIO",
        runtime="SELENIUMBASE_ASSISTED",
    )

    payload = session.to_payload()

    assert payload["provider"] == "MERCURIO"
    assert (
        payload["runtime"]
        == "SELENIUMBASE_ASSISTED"
    )


def test_session_is_runtime_agnostic():
    session = _session(
        provider="ICP_PLUS",
        runtime="DESKTOP_GUI_ASSISTED",
    )

    payload = session.to_payload()

    assert payload["provider"] == "ICP_PLUS"
    assert (
        payload["runtime"]
        == "DESKTOP_GUI_ASSISTED"
    )
