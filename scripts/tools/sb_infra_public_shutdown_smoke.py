import subprocess
import sys
from pathlib import Path


CHILD = r'''
import sys

sys.stdout.reconfigure(
    encoding="utf-8",
    errors="backslashreplace",
)

from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionMode,
    BrowserSessionState,
    BrowserShutdownMode,
)
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)


config = BrowserSessionConfig(
    consumer="sb-infra-public-smoke",
    mode=BrowserSessionMode.EPHEMERAL,
    headless=False,
)

session = SeleniumBaseBrowserSession(
    config=config,
)


print(
    "STATE_INITIAL:",
    session.state.value,
    flush=True,
)

print(
    "HEALTH_INITIAL:",
    session.health(),
    flush=True,
)


browser = session.start()


print(
    "START_RETURNED_BROWSER:",
    browser is not None,
    flush=True,
)

print(
    "STATE_AFTER_START:",
    session.state.value,
    flush=True,
)

print(
    "HEALTH_AFTER_START:",
    session.health(),
    flush=True,
)


result = session.shutdown(
    BrowserShutdownMode.CLOSE
)


print(
    "SHUTDOWN_MODE:",
    result.mode.value,
    flush=True,
)

print(
    "SHUTDOWN_STATE_BEFORE:",
    result.state_before.value,
    flush=True,
)

print(
    "SHUTDOWN_STATE_AFTER:",
    result.state_after.value,
    flush=True,
)

print(
    "SHUTDOWN_CONTROL_RELEASED:",
    result.control_released,
    flush=True,
)

print(
    "SHUTDOWN_BROWSER_CLOSED:",
    result.browser_closed,
    flush=True,
)

print(
    "SHUTDOWN_PROCESS_TERMINATED:",
    result.process_terminated,
    flush=True,
)

print(
    "SHUTDOWN_HAS_ERROR:",
    result.has_error,
    flush=True,
)

print(
    "SHUTDOWN_DETAIL:",
    result.detail,
    flush=True,
)

print(
    "SHUTDOWN_ERROR:",
    result.error,
    flush=True,
)


print(
    "STATE_FINAL:",
    session.state.value,
    flush=True,
)

print(
    "BROWSER_RELEASED:",
    session.browser is None,
    flush=True,
)

print(
    "HEALTH_FINAL:",
    session.health(),
    flush=True,
)


transitions = (
    session.transition_history
)

print(
    "TRANSITION_COUNT:",
    len(transitions),
    flush=True,
)

for index, transition in enumerate(
    transitions,
    start=1,
):
    print(
        "TRANSITION:",
        index,
        transition.previous_state.value,
        "->",
        transition.current_state.value,
        "reason=",
        transition.reason,
        flush=True,
    )


assert (
    session.state
    == BrowserSessionState.CLOSED
)

assert session.browser is None

assert (
    result.state_before
    == BrowserSessionState.READY
)

assert (
    result.state_after
    == BrowserSessionState.CLOSED
)

assert result.control_released is True
assert result.browser_closed is True
assert result.process_terminated is True
assert result.has_error is False

health = session.health()

assert (
    health.state
    == BrowserSessionState.CLOSED
)

assert health.browser_available is False
assert health.control_available is False

assert [
    transition.current_state
    for transition in transitions
] == [
    BrowserSessionState.STARTING,
    BrowserSessionState.READY,
    BrowserSessionState.STOPPING,
    BrowserSessionState.CLOSED,
]


print(
    "PUBLIC_API_ASSERTIONS_OK",
    flush=True,
)

print(
    "CHILD_MAIN_END",
    flush=True,
)
'''


def run_once(
    run_number,
):
    print()
    print(
        "=" * 80
    )

    print(
        f"PUBLIC API RUN {run_number}"
    )

    print(
        "=" * 80
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
        timeout=45,
    )

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

    return completed


results = [
    run_once(
        run_number
    )
    for run_number in (
        1,
        2,
        3,
    )
]


print()
print(
    "=" * 80
)

print(
    "PUBLIC API MATRIX SUMMARY"
)

print(
    "=" * 80
)


failures = []

for index, result in enumerate(
    results,
    start=1,
):
    stdout = (
        result.stdout
        or ""
    )

    stderr = (
        result.stderr
        or ""
    )

    ok = (
        result.returncode == 0
        and "PUBLIC_API_ASSERTIONS_OK"
        in stdout
        and "CHILD_MAIN_END"
        in stdout
        and "STATE_FINAL: CLOSED"
        in stdout
        and "BROWSER_RELEASED: True"
        in stdout
        and "SHUTDOWN_HAS_ERROR: False"
        in stdout
        and "Traceback"
        not in stderr
        and "RuntimeError"
        not in stderr
    )

    print(
        f"RUN {index}:",
        "OK"
        if ok
        else "FAILED",
        "returncode=",
        result.returncode,
    )

    if not ok:
        failures.append(
            index
        )


if failures:
    raise AssertionError(
        "Public shutdown smoke failed: "
        f"{failures}"
    )


print()
print(
    "PUBLIC API SMOKE: 3/3 OK"
)
