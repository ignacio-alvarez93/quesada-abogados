from pathlib import Path


APP_MAIN = Path(
    "app/main.py"
)


def _source():
    return APP_MAIN.read_text(
        encoding="utf-8"
    )


def test_app_imports_qcc_bridge_server():
    source = _source()

    assert (
        "from backend.qcc.bridge.server import ("
        in source
    )

    assert (
        "QccBridgeServer,"
        in source
    )


def test_app_has_single_qcc_bridge_owner():
    source = _source()

    assert (
        "qcc_bridge_owner = {"
        in source
    )

    assert (
        '"server": None'
        in source
    )

    assert (
        "def start_qcc_bridge_session_services():"
        in source
    )

    assert (
        "def close_qcc_bridge_session_services():"
        in source
    )


def test_qcc_bridge_start_is_fail_open():
    source = _source()

    start = source.index(
        "def start_qcc_bridge_session_services():"
    )

    end = source.index(
        "def close_qcc_bridge_session_services():",
        start,
    )

    block = source[start:end]

    assert (
        "server = QccBridgeServer()"
        in block
    )

    assert (
        "server.start()"
        in block
    )

    assert (
        "server.is_running"
        in block
    )

    assert (
        "except Exception as exc:"
        in block
    )

    assert (
        'qcc_bridge_owner[\n                "server"\n            ] = None'
        in block
    )

    assert (
        "return False"
        in block
    )


def test_qcc_bridge_close_is_idempotent():
    source = _source()

    start = source.index(
        "def close_qcc_bridge_session_services():"
    )

    end = source.index(
        "def on_whatsapp_startup_history_done(",
        start,
    )

    block = source[start:end]

    assert (
        "if server is None:"
        in block
    )

    assert (
        "server.close()"
        in block
    )

    assert (
        "return False"
        in block
    )


def test_qcc_bridge_starts_after_page_close_handler_is_installed():
    source = _source()

    close_handler_position = (
        source.index(
            "page.on_close = on_page_close"
        )
    )

    start_position = (
        source.index(
            "start_qcc_bridge_session_services()",
            close_handler_position,
        )
    )

    assert (
        close_handler_position
        < start_position
    )


def test_page_close_closes_qcc_bridge_last():
    source = _source()

    start = source.index(
        "def on_page_close("
    )

    end = source.index(
        "page.on_close = on_page_close",
        start,
    )

    block = source[start:end]

    whatsapp = block.index(
        "close_whatsapp_session_services()"
    )

    dehu = block.index(
        "close_dehu_session_services()"
    )

    icpplus = block.index(
        "close_icpplus_session_services()"
    )

    qcc = block.index(
        "close_qcc_bridge_session_services()"
    )

    assert (
        whatsapp
        < dehu
        < icpplus
        < qcc
    )

    assert (
        "or qcc_result"
        in block
    )
