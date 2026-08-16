import shutil
import subprocess
import sys
from pathlib import Path


PROFILE_KEY = (
    "dehu_smoke_6b2a"
)

PROJECT_ROOT = (
    Path.cwd()
)

PROFILE_DIR = (
    PROJECT_ROOT
    / "data"
    / "browser_profiles"
    / PROFILE_KEY
)

SENTINEL = (
    PROFILE_DIR
    / "SB_INFRA_6B2A_SENTINEL.txt"
)


CHILD = r'''
import sys

sys.stdout.reconfigure(
    encoding="utf-8",
    errors="backslashreplace",
)

from backend.automation.connectors.dehu_connector import (
    DehuConnector,
    get_dehu_profile_dir,
)


profile_key = sys.argv[1]

print(
    "CHILD_START",
    flush=True,
)

print(
    "PROFILE_KEY:",
    profile_key,
    flush=True,
)

profile_dir = (
    get_dehu_profile_dir(
        profile_key
    )
)

print(
    "PROFILE_DIR:",
    profile_dir,
    flush=True,
)

connector = DehuConnector(
    profile_key=profile_key,
    headless=False,
)

# Para este smoke solo interesa lifecycle/profile.
# Evitamos entrar en DEHú real sustituyendo temporalmente
# la URL de apertura por about:blank.
import backend.automation.connectors.dehu_connector as module

original_open_url = (
    module.open_url
)

module.open_url = (
    lambda browser, url:
        browser.get(
            "about:blank"
        )
        if callable(
            getattr(
                browser,
                "get",
                None,
            )
        )
        else None
)

browser = None
session = None

try:
    browser = (
        connector.start()
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
        "SESSION_AVAILABLE:",
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

    print(
        "SESSION_PROFILE_KEY:",
        (
            session.config.profile_key
            if session is not None
            else None
        ),
        flush=True,
    )

finally:
    module.open_url = (
        original_open_url
    )

    print(
        "BEFORE_CLOSE",
        flush=True,
    )

    close_result = (
        connector.close()
    )

    print(
        "CLOSE_RESULT:",
        close_result,
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


assert browser is not None
assert session is not None
assert session.config.profile_key == profile_key
assert close_result is True
assert connector.browser is None
assert connector._browser_session is None

print(
    "CHILD_ASSERTIONS_OK",
    flush=True,
)

print(
    "CHILD_MAIN_END",
    flush=True,
)
'''


def run_child(
    label,
):
    completed = subprocess.run(
        [
            sys.executable,
            "-u",
            "-c",
            CHILD,
            PROFILE_KEY,
        ],
        cwd=str(
            PROJECT_ROOT
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
        "========================================"
    )
    print(
        label
    )
    print(
        "========================================"
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
        "STDOUT"
    )
    print(
        completed.stdout
        or "<empty>"
    )

    print()
    print(
        "STDERR"
    )
    print(
        completed.stderr
        or "<empty>"
    )

    native_crash = (
        completed.returncode
        == 3221225477
        or "0xc0000005"
        in (
            completed.stdout
            or ""
        ).lower()
        or "0xc0000005"
        in (
            completed.stderr
            or ""
        ).lower()
    )

    ok = (
        completed.returncode
        == 0
        and not native_crash
        and "START_RETURNED_BROWSER: True"
        in completed.stdout
        and "SESSION_MODE: PERSISTENT"
        in completed.stdout
        and (
            "SESSION_PROFILE_KEY: "
            + PROFILE_KEY
        )
        in completed.stdout
        and "CLOSE_RESULT: True"
        in completed.stdout
        and "CHILD_ASSERTIONS_OK"
        in completed.stdout
        and "CHILD_MAIN_END"
        in completed.stdout
        and "Traceback"
        not in completed.stderr
    )

    print(
        "NATIVE_CRASH:",
        native_crash,
    )

    print(
        "CHILD_OK:",
        ok,
    )

    if not ok:
        raise AssertionError(
            f"{label} failed"
        )

    return completed


print(
    "PROFILE_KEY:",
    PROFILE_KEY,
)

print(
    "PROFILE_DIR:",
    PROFILE_DIR,
)


if PROFILE_DIR.exists():
    print(
        "REMOVING_OLD_SMOKE_PROFILE"
    )

    shutil.rmtree(
        PROFILE_DIR
    )


print()
print(
    "=== FIRST PROCESS ==="
)

run_child(
    "DEHU PROFILE RUN #1"
)


assert PROFILE_DIR.exists()

first_entries = sorted(
    str(
        path.relative_to(
            PROFILE_DIR
        )
    )
    for path in PROFILE_DIR.rglob("*")
)

print(
    "PROFILE_ENTRIES_AFTER_RUN1:",
    len(
        first_entries
    ),
)

assert first_entries, (
    "Chrome no dejó contenido en el perfil"
)


SENTINEL.write_text(
    "SB-INFRA-6B2A persistent profile marker\n",
    encoding="utf-8",
)

print(
    "SENTINEL_CREATED:",
    SENTINEL.exists(),
)


print()
print(
    "=== SECOND PROCESS ==="
)

run_child(
    "DEHU PROFILE RUN #2"
)


assert PROFILE_DIR.exists()

assert SENTINEL.exists()

assert SENTINEL.read_text(
    encoding="utf-8"
).strip() == (
    "SB-INFRA-6B2A persistent profile marker"
)


second_entries = sorted(
    str(
        path.relative_to(
            PROFILE_DIR
        )
    )
    for path in PROFILE_DIR.rglob("*")
)


print()
print(
    "PROFILE_ENTRIES_AFTER_RUN2:",
    len(
        second_entries
    ),
)

print(
    "SENTINEL_SURVIVED:",
    SENTINEL.exists(),
)

print(
    "SAME_PROFILE_DIR_REUSED:",
    True,
)


print()
print(
    "========================================"
)

print(
    "DEHU PERSISTENT PROFILE SMOKE: OK"
)

print(
    "TWO_PROCESS_REUSE: True"
)

print(
    "========================================"
)
