import pytest

from backend.qcc.actions.store import (
    QccActionStore,
)
from backend.qcc.contracts.actions import (
    QccActionRequest,
    QccActionType,
)


def _request(
    session_id,
    index,
):
    return QccActionRequest(
        session_id=session_id,
        action=(
            QccActionType
            .DOCUMENT_PREPARE
        ),
        payload={
            "document_index":
                index,
        },
    )


def test_store_is_fifo():
    store = QccActionStore()

    first = store.submit(
        _request(
            "qcc-001",
            1,
        )
    )

    second = store.submit(
        _request(
            "qcc-001",
            2,
        )
    )

    assert (
        first.action_id
        < second.action_id
    )

    assert (
        store.consume_next(
            "qcc-001"
        ).request.payload[
            "document_index"
        ]
        == 1
    )

    assert (
        store.consume_next(
            "qcc-001"
        ).request.payload[
            "document_index"
        ]
        == 2
    )


def test_store_is_session_isolated():
    store = QccActionStore()

    store.submit(
        _request(
            "qcc-A",
            1,
        )
    )

    store.submit(
        _request(
            "qcc-B",
            2,
        )
    )

    assert (
        store.consume_next(
            "qcc-A"
        ).request.session_id
        == "qcc-A"
    )

    assert (
        store.pending_count(
            "qcc-B"
        )
        == 1
    )


def test_consume_is_one_shot():
    store = QccActionStore()

    store.submit(
        _request(
            "qcc-001",
            1,
        )
    )

    assert (
        store.consume_next(
            "qcc-001"
        )
        is not None
    )

    assert (
        store.consume_next(
            "qcc-001"
        )
        is None
    )


def test_clear_session_removes_pending():
    store = QccActionStore()

    store.submit(
        _request(
            "qcc-001",
            1,
        )
    )

    assert (
        store.clear_session(
            "qcc-001"
        )
        == 1
    )

    assert (
        store.pending_count(
            "qcc-001"
        )
        == 0
    )


def test_store_deduplicates_client_action_id():
    store = QccActionStore()

    request = QccActionRequest(
        session_id="qcc-001",
        action=(
            QccActionType
            .DOCUMENT_PREPARE
        ),
        payload={
            "document_index": 1,
        },
        client_action_id=(
            "chrome-action-001"
        ),
    )

    first = store.submit(
        request
    )

    second = store.submit(
        request
    )

    assert (
        second.action_id
        == first.action_id
    )

    assert (
        store.pending_count(
            "qcc-001"
        )
        == 1
    )

    consumed = store.consume_next(
        "qcc-001"
    )

    assert (
        consumed.action_id
        == first.action_id
    )

    assert (
        store.pending_count(
            "qcc-001"
        )
        == 0
    )

    third = store.submit(
        request
    )

    assert (
        third.action_id
        == first.action_id
    )

    # Una repetición posterior al consumo
    # tampoco vuelve a meter la acción
    # en la cola.
    assert (
        store.pending_count(
            "qcc-001"
        )
        == 0
    )


def test_store_rejects_idempotency_conflict():
    store = QccActionStore()

    first = QccActionRequest(
        session_id="qcc-001",
        action=(
            QccActionType
            .DOCUMENT_PREPARE
        ),
        payload={
            "document_index": 1,
        },
        client_action_id=(
            "chrome-action-001"
        ),
    )

    conflicting = QccActionRequest(
        session_id="qcc-001",
        action=(
            QccActionType
            .DOCUMENT_SKIP
        ),
        payload={
            "document_index": 1,
        },
        client_action_id=(
            "chrome-action-001"
        ),
    )

    store.submit(
        first
    )

    with pytest.raises(
        ValueError,
        match=(
            "QCC_ACTION_IDEMPOTENCY_CONFLICT"
        ),
    ):
        store.submit(
            conflicting
        )
