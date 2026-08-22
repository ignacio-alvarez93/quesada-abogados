import pytest

from backend.qcc.contracts.actions import (
    QccActionRequest,
    QccActionType,
)


def test_action_types_are_explicit():
    assert {
        action.value
        for action in QccActionType
    } == {
        "DOCUMENTS_START",
        "DOCUMENT_PREPARE",
        "DOCUMENT_SKIP",
        "DOCUMENT_FORCE_TYPE",
    }


def test_documents_start_has_no_payload():
    request = QccActionRequest(
        session_id="qcc-001",
        action=(
            QccActionType
            .DOCUMENTS_START
        ),
        payload={},
    )

    assert request.to_payload() == {
        "session_id": "qcc-001",
        "action": "DOCUMENTS_START",
        "payload": {},
    }


def test_document_prepare_requires_index():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_ACTION_DOCUMENT_INDEX_INVALID"
        ),
    ):
        QccActionRequest(
            session_id="qcc-001",
            action=(
                QccActionType
                .DOCUMENT_PREPARE
            ),
            payload={},
        )


def test_force_type_requires_value():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_ACTION_DOCUMENT_TYPE_INVALID"
        ),
    ):
        QccActionRequest(
            session_id="qcc-001",
            action=(
                QccActionType
                .DOCUMENT_FORCE_TYPE
            ),
            payload={
                "document_index": 1,
            },
        )


def test_action_rejects_arbitrary_payload():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_ACTION_PAYLOAD_KEY_INVALID"
        ),
    ):
        QccActionRequest(
            session_id="qcc-001",
            action=(
                QccActionType
                .DOCUMENT_PREPARE
            ),
            payload={
                "document_index": 1,
                "path":
                    "C:/secret/file.pdf",
            },
        )


def test_action_round_trip_from_payload():
    request = (
        QccActionRequest
        .from_payload(
            {
                "action":
                    "DOCUMENT_FORCE_TYPE",
                "payload": {
                    "document_index": 2,
                    "value": "43",
                },
            },
            session_id="qcc-001",
        )
    )

    assert (
        request.action
        == QccActionType
        .DOCUMENT_FORCE_TYPE
    )

    assert request.payload == {
        "document_index": 2,
        "value": "43",
    }
