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
)
from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)


class PassiveCommunicationService:
    """
    El smoke no usa persistencia ni mensajes.

    Esta dependencia evita construir infraestructura
    de comunicaciones innecesaria para probar únicamente
    lifecycle/ownership del runtime.
    """
    pass


runtime = WhatsAppRuntimeService(
    profile_key="whatsapp_dev",
    headless=False,
    communication_service=(
        PassiveCommunicationService()
    ),
)

connector = None
status = None
close_result = False
error = None


print(
    "CHILD_START",
    flush=True,
)

print(
    "PROFILE_KEY:",
    runtime.profile_key,
    flush=True,
)


try:
    connector = runtime.start()

    print(
        "RUNTIME_START_RETURNED_CONNECTOR:",
        connector is not None,
        flush=True,
    )

    print(
        "RUNTIME_STARTED:",
        runtime.started,
        flush=True,
    )

    print(
        "RUNTIME_CONNECTOR_OWNED:",
        runtime.connector is connector,
        flush=True,
    )

    print(
        "EXECUTOR_AVAILABLE:",
        runtime._executor is not None,
        flush=True,
    )

    print(
        "WORKER_THREAD_ID:",
        runtime._worker_thread_id,
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
            runtime.get_status()
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
        "BEFORE_RUNTIME_CLOSE",
        flush=True,
    )

    try:
        close_result = (
            runtime.close()
        )

        print(
            "RUNTIME_CLOSE_RESULT:",
            close_result,
            flush=True,
        )

    except Exception as exc:
        print(
            "RUNTIME_CLOSE_EXCEPTION:",
            f"{type(exc).__name__}: {exc}",
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

print(
    "RUNTIME_CONNECTOR_AFTER_CLOSE:",
    runtime.connector,
    flush=True,
)

print(
    "RUNTIME_STARTED_AFTER_CLOSE:",
    runtime.started,
    flush=True,
)

print(
    "RUNTIME_EXECUTOR_AFTER_CLOSE:",
    runtime._executor,
    flush=True,
)

print(
    "RUNTIME_WORKER_AFTER_CLOSE:",
    runtime._worker_thread_id,
    flush=True,
)

print(
    "CONNECTOR_BROWSER_AFTER_CLOSE:",
    (
        connector.browser
        if connector is not None
        else None
    ),
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
    runtime.connector
    is None
)

assert (
    runtime.started
    is False
)

assert (
    runtime._executor
    is None
)

assert (
    runtime._worker_thread_id
    is None
)

assert (
    connector is not None
)

assert (
    connector.browser
    is None
)


print(
    "WHATSAPP_RUNTIME_ASSERTIONS_OK",
    flush=True,
)

print(
    "CHILD_MAIN_END",
    flush=True,
)
'''


print(
    "Launching isolated WhatsApp Runtime smoke..."
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
    and "RUNTIME_CLOSE_RESULT: True"
    in stdout
    and "RUNTIME_CONNECTOR_AFTER_CLOSE: None"
    in stdout
    and "RUNTIME_STARTED_AFTER_CLOSE: False"
    in stdout
    and "RUNTIME_EXECUTOR_AFTER_CLOSE: None"
    in stdout
    and "RUNTIME_WORKER_AFTER_CLOSE: None"
    in stdout
    and "CONNECTOR_BROWSER_AFTER_CLOSE: None"
    in stdout
    and "WHATSAPP_RUNTIME_ASSERTIONS_OK"
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
    "WHATSAPP RUNTIME GOVERNED SMOKE:",
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
        "WhatsApp Runtime governed smoke failed"
    )
