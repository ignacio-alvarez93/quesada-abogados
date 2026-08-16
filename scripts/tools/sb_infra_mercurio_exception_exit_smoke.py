import subprocess
import sys
from pathlib import Path


CHILD = r'''
import io
import runpy
import sys
import tempfile

sys.stdout.reconfigure(
    encoding="utf-8",
    errors="backslashreplace",
)

from backend.automation.connectors.mercurio_connector import (
    MercurioConnector,
)


print(
    "CHILD_START",
    flush=True,
)


original_close_browser = (
    MercurioConnector.close_browser
)

close_calls = []


def observed_close_browser(
    self,
):
    print(
        "FINALIZER_CLOSE_CALLED",
        flush=True,
    )

    result = (
        original_close_browser(
            self
        )
    )

    close_calls.append(
        result
    )

    print(
        "FINALIZER_CLOSE_RESULT:",
        result,
        flush=True,
    )

    print(
        "FINALIZER_BROWSER_AFTER_CLOSE:",
        self.browser,
        flush=True,
    )

    print(
        "FINALIZER_SESSION_AFTER_CLOSE:",
        self._browser_session,
        flush=True,
    )

    return result


MercurioConnector.close_browser = (
    observed_close_browser
)


with tempfile.TemporaryDirectory(
    prefix="sb-infra-mercurio-5c2-"
) as temp_dir:

    sys.argv = [
        "app/run_presentacion_asistida.py",
        "--url",
        "about:blank",
        "--expediente-id",
        "SB-INFRA-5C2",
        "--numero-expediente",
        "SMOKE-5C2",
        "--tipo",
        "SMOKE",
        "--provincia-codigo",
        "33",
        "--session-dir",
        temp_dir,
    ]

    # El runner abre Chrome primero y después llega
    # al prompt "presentacion>".
    #
    # stdin vacío provoca EOFError exactamente ahí.
    sys.stdin = io.StringIO(
        ""
    )

    try:
        runpy.run_path(
            "app/run_presentacion_asistida.py",
            run_name="__main__",
        )

    except EOFError:
        print(
            "EXPECTED_EXCEPTION: EOFError",
            flush=True,
        )

    else:
        raise AssertionError(
            "El runner debía terminar mediante EOFError"
        )


print(
    "FINAL_CLOSE_CALLS:",
    close_calls,
    flush=True,
)


assert close_calls == [
    True
]


print(
    "MERCURIO_EXCEPTION_EXIT_ASSERTIONS_OK",
    flush=True,
)

print(
    "CHILD_MAIN_END",
    flush=True,
)
'''


print(
    "Launching isolated Mercurio exceptional-exit smoke..."
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
    and "FINALIZER_CLOSE_CALLED"
    in stdout
    and "FINALIZER_CLOSE_RESULT: True"
    in stdout
    and "FINALIZER_BROWSER_AFTER_CLOSE: None"
    in stdout
    and "FINALIZER_SESSION_AFTER_CLOSE: None"
    in stdout
    and "EXPECTED_EXCEPTION: EOFError"
    in stdout
    and "FINAL_CLOSE_CALLS: [True]"
    in stdout
    and "MERCURIO_EXCEPTION_EXIT_ASSERTIONS_OK"
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
    "MERCURIO EXCEPTION EXIT SMOKE:",
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
        "Mercurio exceptional-exit smoke failed"
    )
