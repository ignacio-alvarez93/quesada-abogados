from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

SW = (
    ROOT
    / "chrome_extension"
    / "qcc"
    / "background"
    / "service_worker.js"
)


def source():
    return SW.read_text(
        encoding="utf-8"
    )


def block(
    text,
    start,
    end,
):
    a = text.index(
        start
    )

    b = text.index(
        end,
        a,
    )

    return text[a:b]


def test_human_page_listener_uses_runtime_port():
    text = source()

    human = block(
        text,
        (
            "function "
            "installQccHumanClickListenerInFrame"
        ),
        (
            "function "
            "qccHumanFrameIdFromPath"
        ),
    )

    assert (
        "chrome.runtime.connect({"
        in human
    )

    assert (
        '"QCC_HUMAN_DOM_ACTION_PORT"'
        in human
    )

    assert (
        "port.postMessage("
        in human
    )

    assert (
        "qccHumanPortSend("
        in human
    )


def test_service_worker_has_human_port_receiver():
    text = source()

    assert (
        "QCC_HUMAN_DOM_ACTION_PORT_RECEIVER"
        in text
    )

    assert (
        "chrome.runtime.onConnect.addListener("
        in text
    )

    assert (
        "port.sender"
        in text
    )


def test_port_reuses_existing_backend_forwarder():
    text = source()

    marker = text.index(
        "QCC_HUMAN_DOM_ACTION_PORT_RECEIVER"
    )

    old_listener = text.index(
        '''chrome.runtime.onMessage.addListener(
  (
    message,
    sender,
    sendResponse
''',
        marker,
    )

    port_block = text[
        marker:
        old_listener
    ]

    assert (
        "forwardQccHumanDomActionSignal("
        in port_block
    )

    assert (
        "policy"
        not in port_block
    )

    assert (
        "before_fingerprint"
        not in port_block
    )
