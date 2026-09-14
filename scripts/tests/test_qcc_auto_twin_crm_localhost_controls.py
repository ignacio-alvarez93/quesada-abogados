from pathlib import Path


def test_frontend_does_not_own_http_server():
    source = Path(
        "frontend/views/twins_view.py"
    ).read_text(
        encoding="utf-8"
    )

    forbidden = (
        "HTTPServer",
        "ThreadingHTTPServer",
        "SimpleHTTPRequestHandler",
        "serve_forever",
        "subprocess",
        "Popen",
    )

    for token in forbidden:
        assert (
            token
            not in source
        )


def test_local_runtime_is_loopback_only():
    source = Path(
        "backend/services/"
        "twin_local_runtime_service.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'host="127.0.0.1"'
        in source
    )

    assert (
        '"0.0.0.0"'
        not in source
    )


def test_local_runtime_contains_no_browser_execution():
    source = Path(
        "backend/services/"
        "twin_local_runtime_service.py"
    ).read_text(
        encoding="utf-8"
    )

    forbidden = (
        "selenium",
        "SeleniumBase",
        "open_url(",
        "webdriver",
        "BrowserSession",
    )

    for token in forbidden:
        assert (
            token
            not in source
        )
