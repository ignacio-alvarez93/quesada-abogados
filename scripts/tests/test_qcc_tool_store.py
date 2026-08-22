import pytest

from backend.qcc.contracts.tools import (
    QccToolRequest,
    QccToolType,
)
from backend.qcc.tools.store import (
    QccToolStore,
)


def _request(
    client_tool_id="tool-1",
):
    return QccToolRequest(
        session_id="session-1",
        tool=QccToolType.DOM_INSPECT,
        payload={},
        client_tool_id=client_tool_id,
    )


def test_tool_store_round_trip():
    store = QccToolStore()

    queued = store.submit(
        _request()
    )

    assert (
        queued.tool_request_id
        == 1
    )

    consumed = store.consume_next(
        "session-1"
    )

    assert consumed is not None

    assert (
        consumed.request.tool
        == QccToolType.DOM_INSPECT
    )

    assert (
        store.consume_next(
            "session-1"
        )
        is None
    )


def test_tool_store_is_idempotent():
    store = QccToolStore()

    request = _request()

    first = store.submit(
        request
    )

    second = store.submit(
        request
    )

    assert (
        first.tool_request_id
        == second.tool_request_id
    )

    assert (
        store.pending_count(
            "session-1"
        )
        == 1
    )


def test_tool_store_rejects_idempotency_conflict():
    store = QccToolStore()

    first = _request(
        client_tool_id="same"
    )

    store.submit(
        first
    )

    conflicting = QccToolRequest(
        session_id="session-1",
        tool=QccToolType.DOM_INSPECT,
        payload={},
        client_tool_id="same",
    )

    # Mismo payload = misma operación.
    assert (
        store.submit(
            conflicting
        ).tool_request_id
        == 1
    )


def test_tool_store_clear_session():
    store = QccToolStore()

    store.submit(
        _request()
    )

    assert (
        store.clear_session(
            "session-1"
        )
        == 1
    )

    assert (
        store.pending_count(
            "session-1"
        )
        == 0
    )
