import subprocess
import sys
from pathlib import Path


CHILD = r'''
import sys
import threading
from pathlib import Path

sys.stdout.reconfigure(
    encoding="utf-8",
    errors="backslashreplace",
)

from backend.automation.connectors.dehu_connector import (
    DEHU_URL,
    DehuConnector,
)
from backend.services.dehu_runtime_service import (
    DehuRuntimeService,
)


MAIN_THREAD_ID = (
    threading.get_ident()
)

events = []


def trace_method(
    method_name,
):
    original = getattr(
        DehuConnector,
        method_name,
    )

    def traced(
        self,
        *args,
        **kwargs,
    ):
        thread_id = (
            threading.get_ident()
        )

        events.append(
            (
                method_name,
                thread_id,
            )
        )

        print(
            "TRACE_"
            + method_name.upper()
            + "_THREAD:",
            thread_id,
            flush=True,
        )

        return original(
            self,
            *args,
            **kwargs,
        )

    setattr(
        DehuConnector,
        method_name,
        traced,
    )


for name in (
    "start",
    "open_portal",
    "capture",
    "close",
):
    trace_method(
        name
    )


print(
    "CHILD_START",
    flush=True,
)

print(
    "MAIN_THREAD_ID:",
    MAIN_THREAD_ID,
    flush=True,
)


runtime = DehuRuntimeService(
    profile_key="dehu",
    headless=False,
)


connector = None
worker_thread_id = None
capture = None
close_result = False


try:
    print(
        "BEFORE_RUNTIME_START",
        flush=True,
    )

    connector = (
        runtime.start()
    )

    worker_thread_id = (
        runtime._worker_thread_id
    )

    print(
        "RUNTIME_STARTED:",
        runtime.started,
        flush=True,
    )

    print(
        "RUNTIME_CONNECTOR_AVAILABLE:",
        runtime.connector
        is connector,
        flush=True,
    )

    print(
        "WORKER_THREAD_ID:",
        worker_thread_id,
        flush=True,
    )

    print(
        "WORKER_DIFFERS_FROM_MAIN:",
        worker_thread_id
        != MAIN_THREAD_ID,
        flush=True,
    )


    print(
        "BEFORE_RUNTIME_OPEN_PORTAL",
        flush=True,
    )

    target = (
        runtime.open_portal(
            DEHU_URL
        )
    )

    print(
        "OPEN_PORTAL_RESULT:",
        target,
        flush=True,
    )


    print(
        "BEFORE_RUNTIME_CAPTURE",
        flush=True,
    )

    capture = (
        runtime.capture(
            "runtime_real_smoke"
        )
    )

    print(
        "CAPTURE_LABEL:",
        capture.get(
            "label"
        ),
        flush=True,
    )

    print(
        "CAPTURE_HTML:",
        capture.get(
            "html_path"
        ),
        flush=True,
    )

    print(
        "CAPTURE_SCREENSHOT:",
        capture.get(
            "screenshot_path"
        ),
        flush=True,
    )


    html_path = Path(
        capture[
            "html_path"
        ]
    )

    screenshot_text = str(
        capture.get(
            "screenshot_path"
        )
        or ""
    )

    print(
        "CAPTURE_HTML_EXISTS:",
        html_path.exists(),
        flush=True,
    )

    print(
        "CAPTURE_SCREENSHOT_REPORTED:",
        bool(
            screenshot_text
        ),
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

    except Exception as exc:
        close_result = False

        print(
            "RUNTIME_CLOSE_EXCEPTION:",
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


    print(
        "RUNTIME_CLOSE_RESULT:",
        close_result,
        flush=True,
    )

    print(
        "RUNTIME_CONNECTOR_AFTER_CLOSE:",
        runtime.connector,
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


print()
print(
    "TRACE_EVENTS:",
    events,
    flush=True,
)


assert connector is not None
assert worker_thread_id is not None

assert worker_thread_id != MAIN_THREAD_ID

assert runtime.connector is None
assert runtime._executor is None
assert runtime._worker_thread_id is None

assert close_result is True

assert capture is not None

assert Path(
    capture[
        "html_path"
    ]
).exists()


event_thread_ids = {
    thread_id
    for _, thread_id
    in events
}

print(
    "EVENT_THREAD_IDS:",
    sorted(
        event_thread_ids
    ),
    flush=True,
)

print(
    "ALL_CONNECTOR_OPS_SAME_WORKER:",
    event_thread_ids
    == {
        worker_thread_id
    },
    flush=True,
)


assert event_thread_ids == {
    worker_thread_id
}


event_names = [
    name
    for name, _
    in events
]

print(
    "EVENT_NAMES:",
    event_names,
    flush=True,
)


assert "start" in event_names
assert "open_portal" in event_names
assert "capture" in event_names
assert "close" in event_names


print(
    "DEHU_RUNTIME_REAL_ASSERTIONS_OK",
    flush=True,
)

print(
    "CHILD_MAIN_END",
    flush=True,
)
'''


print(
    "Launching isolated real DehuRuntimeService smoke..."
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
    timeout=120,
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
    completed.returncode
    == 0
    and not native_crash
    and "RUNTIME_STARTED: True"
    in stdout
    and "WORKER_DIFFERS_FROM_MAIN: True"
    in stdout
    and "CAPTURE_HTML_EXISTS: True"
    in stdout
    and "RUNTIME_CLOSE_RESULT: True"
    in stdout
    and "RUNTIME_CONNECTOR_AFTER_CLOSE: None"
    in stdout
    and "RUNTIME_EXECUTOR_AFTER_CLOSE: None"
    in stdout
    and "RUNTIME_WORKER_AFTER_CLOSE: None"
    in stdout
    and "ALL_CONNECTOR_OPS_SAME_WORKER: True"
    in stdout
    and "DEHU_RUNTIME_REAL_ASSERTIONS_OK"
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
    "DEHU RUNTIME REAL SMOKE:",
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
        "DehuRuntimeService real smoke failed"
    )
