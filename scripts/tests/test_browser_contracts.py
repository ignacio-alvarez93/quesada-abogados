from dataclasses import FrozenInstanceError
from pathlib import Path

from backend.automation.browser_contracts import (
    BrowserInfrastructureError,
    BrowserSessionConfig,
    BrowserSessionConfigurationError,
    BrowserSessionControlError,
    BrowserSessionHealth,
    BrowserSessionIdentity,
    BrowserSessionLifecycleError,
    BrowserSessionMode,
    BrowserSessionSnapshot,
    BrowserSessionState,
    BrowserSessionTransition,
    BrowserShutdownMode,
    BrowserShutdownResult,
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


def test_identity_from_config():
    config = BrowserSessionConfig(
        consumer="whatsapp",
        mode="persistent",
        profile_key="whatsapp_dev",
    )

    identity = BrowserSessionIdentity.from_config(
        session_id=" session-001 ",
        config=config,
    )

    assert identity.session_id == "session-001"
    assert identity.consumer == "whatsapp"
    assert (
        identity.mode
        == BrowserSessionMode.PERSISTENT
    )
    assert identity.profile_key == "whatsapp_dev"


def test_identity_rejects_empty_session_id():
    try:
        BrowserSessionIdentity(
            session_id=" ",
            consumer="dehu",
            mode=BrowserSessionMode.EPHEMERAL,
        )
    except BrowserSessionConfigurationError:
        return

    raise AssertionError(
        "session_id vacío debería rechazarse"
    )


def test_identity_is_immutable():
    identity = BrowserSessionIdentity(
        session_id="session-002",
        consumer="mercurio",
        mode=BrowserSessionMode.ASSISTED,
    )

    try:
        identity.session_id = "other"
    except FrozenInstanceError:
        return

    raise AssertionError(
        "BrowserSessionIdentity debe ser immutable"
    )


def test_snapshot_contract():
    identity = BrowserSessionIdentity(
        session_id="session-003",
        consumer="dehu",
        mode=BrowserSessionMode.EPHEMERAL,
    )

    health = BrowserSessionHealth(
        state=BrowserSessionState.READY,
        browser_available=True,
        control_available=True,
    )

    snapshot = BrowserSessionSnapshot(
        identity=identity,
        health=health,
    )

    assert snapshot.identity is identity
    assert snapshot.health is health
    assert (
        snapshot.state
        == BrowserSessionState.READY
    )


def test_snapshot_rejects_invalid_contracts():
    health = BrowserSessionHealth(
        state=BrowserSessionState.CREATED,
    )

    try:
        BrowserSessionSnapshot(
            identity="invalid",
            health=health,
        )
    except BrowserSessionConfigurationError:
        pass
    else:
        raise AssertionError(
            "identity inválida debería rechazarse"
        )

    identity = BrowserSessionIdentity(
        session_id="session-004",
        consumer="demo",
        mode=BrowserSessionMode.EPHEMERAL,
    )

    try:
        BrowserSessionSnapshot(
            identity=identity,
            health="invalid",
        )
    except BrowserSessionConfigurationError:
        return

    raise AssertionError(
        "health inválido debería rechazarse"
    )


def test_transition_contract():
    transition = BrowserSessionTransition(
        previous_state="created",
        current_state="starting",
        reason="start_requested",
        detail="Inicio solicitado",
    )

    assert (
        transition.previous_state
        == BrowserSessionState.CREATED
    )

    assert (
        transition.current_state
        == BrowserSessionState.STARTING
    )

    assert transition.reason == "start_requested"
    assert transition.detail == "Inicio solicitado"


def test_transition_rejects_same_state():
    try:
        BrowserSessionTransition(
            previous_state=BrowserSessionState.READY,
            current_state=BrowserSessionState.READY,
        )
    except BrowserSessionLifecycleError:
        return

    raise AssertionError(
        "Una transición sin cambio debería rechazarse"
    )


def test_transition_is_immutable():
    transition = BrowserSessionTransition(
        previous_state=BrowserSessionState.STARTING,
        current_state=BrowserSessionState.READY,
    )

    try:
        transition.current_state = (
            BrowserSessionState.FAILED
        )
    except FrozenInstanceError:
        return

    raise AssertionError(
        "BrowserSessionTransition debe ser immutable"
    )


def test_shutdown_result_contract():
    result = BrowserShutdownResult(
        mode="detach",
        state_before="ready",
        state_after="disconnected",
        control_released=True,
        browser_closed=False,
        process_terminated=None,
        detail="Control entregado",
    )

    assert (
        result.mode
        == BrowserShutdownMode.DETACH
    )

    assert (
        result.state_before
        == BrowserSessionState.READY
    )

    assert (
        result.state_after
        == BrowserSessionState.DISCONNECTED
    )

    assert result.control_released is True
    assert result.browser_closed is False
    assert result.process_terminated is None
    assert result.detail == "Control entregado"
    assert result.has_error is False


def test_shutdown_result_preserves_unknown_facts():
    result = BrowserShutdownResult(
        mode=BrowserShutdownMode.CLOSE,
        state_before=BrowserSessionState.STOPPING,
        state_after=BrowserSessionState.CLOSED,
        control_released=True,
        browser_closed=None,
        process_terminated=None,
    )

    assert result.browser_closed is None
    assert result.process_terminated is None


def test_shutdown_result_error_contract():
    result = BrowserShutdownResult(
        mode=BrowserShutdownMode.KILL,
        state_before=BrowserSessionState.FAILED,
        state_after=BrowserSessionState.FAILED,
        control_released=False,
        browser_closed=None,
        process_terminated=None,
        error="native shutdown unavailable",
    )

    assert result.has_error is True
    assert (
        result.error
        == "native shutdown unavailable"
    )


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
    test_identity_from_config,
    test_identity_rejects_empty_session_id,
    test_identity_is_immutable,
    test_snapshot_contract,
    test_snapshot_rejects_invalid_contracts,
    test_transition_contract,
    test_transition_rejects_same_state,
    test_transition_is_immutable,
    test_shutdown_result_contract,
    test_shutdown_result_preserves_unknown_facts,
    test_shutdown_result_error_contract,
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
