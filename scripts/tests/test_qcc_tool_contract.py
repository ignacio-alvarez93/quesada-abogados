import pytest

from backend.qcc.contracts.tools import (
    QccToolRequest,
    QccToolType,
)


def test_dom_inspect_is_explicit_tool():
    assert (
        QccToolType.DOM_INSPECT.value
        == "DOM_INSPECT"
    )


def test_dom_inspect_has_empty_payload():
    request = QccToolRequest(
        session_id="session-1",
        tool=QccToolType.DOM_INSPECT,
        payload={},
        client_tool_id="tool-1",
    )

    assert request.to_payload() == {
        "session_id":
            "session-1",
        "tool":
            "DOM_INSPECT",
        "payload":
            {},
        "client_tool_id":
            "tool-1",
    }


def test_dom_inspect_rejects_arbitrary_payload():
    with pytest.raises(
        ValueError,
        match=(
            "QCC_TOOL_DOM_INSPECT_"
            "PAYLOAD_INVALID"
        ),
    ):
        QccToolRequest(
            session_id="session-1",
            tool=QccToolType.DOM_INSPECT,
            payload={
                "javascript":
                    "document.body.innerHTML",
            },
        )


def test_unknown_tool_rejected():
    with pytest.raises(
        ValueError,
        match="QCC_TOOL_TYPE_INVALID",
    ):
        QccToolRequest.from_payload(
            {
                "tool":
                    "EXECUTE_JS",
                "payload":
                    {},
            },
            session_id="session-1",
        )
