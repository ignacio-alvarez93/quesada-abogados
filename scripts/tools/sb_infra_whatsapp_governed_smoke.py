import subprocess
import sys
from pathlib import Path


CHILD = r'''
import sys
import time

sys.stdout.reconfigure(
    encoding="utf-8",
    errors="backslashreplace",
)

from backend.automation.connectors.whatsapp_connector import (
    SESSION_STATUS_LOADING,
    SESSION_STATUS_NEEDS_LOGIN,
    SESSION_STATUS_READY,
    SESSION_STATUS_UNKNOWN,
    WhatsAppConnector,
)


connector = WhatsAppConnector(
    profile_key="whatsapp_dev",
    headless=False,
)

status = None
close_result = False
error = None


print(
    "CHILD_START",
    flush=True,
)

print(
    "PROFILE_KEY:",
    connector.profile_key,
    flush=True,
)


try:
    browser = connector.start()

    print(
        "START_RETURNED_BROWSER:",
        browser is not None,
        flush=True,
    )

    print(
        "CONNECTOR_BROWSER_AVAILABLE:",
        connector.browser is not None,
        flush=True,
    )

    deadline = (
        time.time()
        + 60
    )

    while (
        time.time()
        < deadline
    ):
        status = (
            connector
            .detect_session_status()
        )

        print(
            "SESSION_STATUS:",
            status,
            flush=True,
        )

        if (
            status
            == SESSION_STATUS_READY
        ):
            break

        if (
            status
            == SESSION_STATUS_NEEDS_LOGIN
        ):
            break

        if status not in {
            SESSION_STATUS_LOADING,
            SESSION_STATUS_UNKNOWN,
        }:
            break

        time.sleep(
            1
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
            connector.close()
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
        "CONNECTOR_BROWSER_AFTER_CLOSE:",
        connector.browser,
        flush=True,
    )


print(
    "FINAL_SESSION_STATUS:",
    status,
    flush=True,
)

print(
    "FINAL_ERROR:",
    error,
    flush=True,
)


assert error is None

assert (
    status
    == SESSION_STATUS_READY
), (
    "WhatsApp no alcanzó READY; "
    f"estado final={status!r}"
)

assert (
    close_result
    is True
)

assert (
    connector.browser
    is None
)


print(
    "WHATSAPP_GOVERNED_ASSERTIONS_OK",
    flush=True,
)

print(
    "CHILD_MAIN_END",
    flush=True,
)
'''


print(
    "Launching isolated WhatsApp smoke..."
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
    and "FINAL_SESSION_STATUS: READY"
    in stdout
    and "CONNECTOR_CLOSE_RESULT: True"
    in stdout
    and "CONNECTOR_BROWSER_AFTER_CLOSE: None"
    in stdout
    and "WHATSAPP_GOVERNED_ASSERTIONS_OK"
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
    "WHATSAPP GOVERNED SMOKE:",
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
        "WhatsApp governed smoke failed"
    )
