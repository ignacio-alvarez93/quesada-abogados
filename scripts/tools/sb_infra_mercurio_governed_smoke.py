import subprocess
import sys
from pathlib import Path


CHILD = r'''
import sys
import tempfile

sys.stdout.reconfigure(
    encoding="utf-8",
    errors="backslashreplace",
)

from backend.automation.browser_contracts import (
    BrowserSessionMode,
    BrowserSessionState,
)
from backend.automation.connectors.mercurio_connector import (
    MercurioConnector,
)


print(
    "CHILD_START",
    flush=True,
)


with tempfile.TemporaryDirectory(
    prefix="sb-infra-mercurio-"
) as temp_dir:

    connector = MercurioConnector(
        session_dir=temp_dir,
        expediente_id="SB-INFRA-5B2",
        headless=False,
    )

    browser = None
    session = None
    close_result = False
    error = None

    try:
        browser = connector.start_browser(
            "about:blank"
        )

        session = (
            connector._browser_session
        )

        print(
            "START_RETURNED_BROWSER:",
            browser is not None,
            flush=True,
        )

        print(
            "CONNECTOR_BROWSER_AVAILABLE:",
            connector.browser is browser,
            flush=True,
        )

        print(
            "BROWSER_SESSION_AVAILABLE:",
            session is not None,
            flush=True,
        )

        print(
            "SESSION_MODE:",
            (
                session.config.mode.value
                if session is not None
                else None
            ),
            flush=True,
        )

        health = (
            session.health()
            if session is not None
            else None
        )

        print(
            "SESSION_STATE:",
            (
                health.state.value
                if health is not None
                else None
            ),
            flush=True,
        )

    except Exception as exc:
        error = (
            f"{type(exc).__name__}: {exc}"
        )

        print(
            "SMOKE_ERROR:",
            error,
            flush=True,
        )

    finally:
        print(
            "BEFORE_CONNECTOR_CLOSE",
            flush=True,
        )

        try:
            close_result = (
                connector.close_browser()
            )

            print(
                "CONNECTOR_CLOSE_RESULT:",
                close_result,
                flush=True,
            )

        except Exception as exc:
            print(
                "CONNECTOR_CLOSE_EXCEPTION:",
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )


    print(
        "FINAL_ERROR:",
        error,
        flush=True,
    )

    print(
        "CONNECTOR_BROWSER_AFTER_CLOSE:",
        connector.browser,
        flush=True,
    )

    print(
        "CONNECTOR_SESSION_AFTER_CLOSE:",
        connector._browser_session,
        flush=True,
    )


    assert error is None

    assert browser is not None

    assert session is not None

    assert (
        session.config.mode
        == BrowserSessionMode.ASSISTED
    )

    assert (
        close_result
        is True
    )

    assert (
        connector.browser
        is None
    )

    assert (
        connector._browser_session
        is None
    )

    assert (
        session.health().state
        == BrowserSessionState.CLOSED
    )


    print(
        "MERCURIO_GOVERNED_ASSERTIONS_OK",
        flush=True,
    )


print(
    "CHILD_MAIN_END",
    flush=True,
)
'''


print(
    "Launching isolated Mercurio BrowserSession smoke..."
)


completed = subprocess.run(
    [
        sys.executable,
        "-u",
        "-c",
        CHILD,
    ],
    cwd=str(
        Path.cwd()
    ),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    errors="backslashreplace",
    timeout=90,
)


print()
print(
    "RETURN_CODE:",
    completed.returncode,
)

if completed.returncode >= 0:
    print(
        "RETURN_CODE_HEX:",
        hex(
            completed.returncode
        ),
    )


print()
print(
    "================ STDOUT ================"
)

print(
    completed.stdout
    or "<empty>"
)


print()
print(
    "================ STDERR ================"
)

print(
    completed.stderr
    or "<empty>"
)


stdout = (
    completed.stdout
    or ""
)

stderr = (
    completed.stderr
    or ""
)


native_crash = (
    completed.returncode
    == 3221225477
    or "0xc0000005"
    in stdout.lower()
    or "0xc0000005"
    in stderr.lower()
)


ok = (
    completed.returncode == 0
    and not native_crash
    and "START_RETURNED_BROWSER: True"
    in stdout
    and "CONNECTOR_BROWSER_AVAILABLE: True"
    in stdout
    and "BROWSER_SESSION_AVAILABLE: True"
    in stdout
    and "SESSION_MODE: ASSISTED"
    in stdout
    and "SESSION_STATE: READY"
    in stdout
    and "CONNECTOR_CLOSE_RESULT: True"
    in stdout
    and "CONNECTOR_BROWSER_AFTER_CLOSE: None"
    in stdout
    and "CONNECTOR_SESSION_AFTER_CLOSE: None"
    in stdout
    and "MERCURIO_GOVERNED_ASSERTIONS_OK"
    in stdout
    and "CHILD_MAIN_END"
    in stdout
    and "Traceback"
    not in stderr
)


print()
print(
    "========================================"
)

print(
    "MERCURIO GOVERNED SMOKE:",
    "OK"
    if ok
    else "FAILED",
)

print(
    "NATIVE_CRASH:",
    native_crash,
)

print(
    "========================================"
)


if not ok:
    raise AssertionError(
        "Mercurio governed BrowserSession smoke failed"
    )
