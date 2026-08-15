from dataclasses import FrozenInstanceError
from pathlib import Path

from backend.automation.browser_contracts import (
    BrowserInfrastructureError,
    BrowserSessionConfig,
    BrowserSessionConfigurationError,
    BrowserSessionControlError,
    BrowserSessionHealth,
    BrowserSessionLifecycleError,
    BrowserSessionMode,
    BrowserSessionState,
    BrowserShutdownMode,
)


def test_session_modes():
    assert {
        item.value
        for item in BrowserSessionMode
    } == {
        "EPHEMERAL",
        "PERSISTENT",
        "ASSISTED",
    }


def test_session_states():
    assert {
        item.value
        for item in BrowserSessionState
    } == {
        "CREATED",
        "STARTING",
        "READY",
        "NEEDS_USER_ACTION",
        "DEGRADED",
        "DISCONNECTED",
        "FAILED",
        "STOPPING",
        "CLOSED",
    }


def test_shutdown_modes():
    assert {
        item.value
        for item in BrowserShutdownMode
    } == {
        "DETACH",
        "CLOSE",
        "KILL",
    }


def test_config_normalization():
    config = BrowserSessionConfig(
        consumer="  whatsapp  ",
        mode="persistent",
        profile_key="  whatsapp_dev  ",
    )

    assert config.consumer == "whatsapp"
    assert (
        config.mode
        == BrowserSessionMode.PERSISTENT
    )
    assert config.profile_key == "whatsapp_dev"
    assert config.headless is False


def test_empty_consumer_rejected():
    try:
        BrowserSessionConfig(
            consumer="   ",
        )
    except BrowserSessionConfigurationError:
        return

    raise AssertionError(
        "consumer vacío debería rechazarse"
    )


def test_empty_profile_key_rejected():
    try:
        BrowserSessionConfig(
            consumer="whatsapp",
            profile_key="   ",
        )
    except BrowserSessionConfigurationError:
        return

    raise AssertionError(
        "profile_key vacío debería rechazarse"
    )


def test_invalid_mode_rejected():
    try:
        BrowserSessionConfig(
            consumer="demo",
            mode="UNKNOWN",
        )
    except BrowserSessionConfigurationError:
        return

    raise AssertionError(
        "mode desconocido debería rechazarse"
    )


def test_config_is_immutable():
    config = BrowserSessionConfig(
        consumer="dehu",
    )

    try:
        config.consumer = "other"
    except FrozenInstanceError:
        return

    raise AssertionError(
        "BrowserSessionConfig debe ser immutable"
    )


def test_health_contract():
    health = BrowserSessionHealth(
        state="ready",
        browser_available=True,
        control_available=True,
        worker_available=None,
        detail="ok",
    )

    assert (
        health.state
        == BrowserSessionState.READY
    )
    assert health.browser_available is True
    assert health.control_available is True
    assert health.worker_available is None
    assert health.detail == "ok"
    assert health.last_error == ""


def test_error_hierarchy():
    assert issubclass(
        BrowserSessionLifecycleError,
        BrowserInfrastructureError,
    )

    assert issubclass(
        BrowserSessionControlError,
        BrowserInfrastructureError,
    )

    assert issubclass(
        BrowserSessionConfigurationError,
        BrowserInfrastructureError,
    )


def test_contract_module_has_no_framework_dependency():
    """
    El contrato puede mencionar frameworks en documentación,
    pero no debe importarlos.

    Se inspecciona el AST para validar dependencias reales,
    evitando falsos positivos por docstrings o comentarios.
    """
    import ast

    path = (
        Path(__file__)
        .resolve()
        .parents[2]
        / "backend"
        / "automation"
        / "browser_contracts.py"
    )

    text = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        text
    )

    imported_modules = []

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            imported_modules.extend(
                alias.name
                for alias in node.names
            )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            imported_modules.append(
                node.module
                or ""
            )

    forbidden_prefixes = (
        "seleniumbase",
        "flet",
        "sqlite3",
        "psycopg",
        "supabase",
        "backend.automation.connectors.whatsapp_connector",
        "backend.automation.connectors.mercurio_connector",
        "backend.automation.connectors.dehu_connector",
    )

    for module in imported_modules:
        assert not any(
            module == prefix
            or module.startswith(
                prefix + "."
            )
            for prefix in forbidden_prefixes
        ), (
            "Dependencia prohibida en browser_contracts.py: "
            f"{module}"
        )


TESTS = (
    test_session_modes,
    test_session_states,
    test_shutdown_modes,
    test_config_normalization,
    test_empty_consumer_rejected,
    test_empty_profile_key_rejected,
    test_invalid_mode_rejected,
    test_config_is_immutable,
    test_health_contract,
    test_error_hierarchy,
    test_contract_module_has_no_framework_dependency,
)


def main():
    passed = 0

    for test in TESTS:
        test()
        passed += 1

    print(
        f"BROWSER CONTRACTS {passed}/{len(TESTS)} OK"
    )


if __name__ == "__main__":
    main()
