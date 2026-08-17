import ast
from pathlib import Path


APP_PATH = Path(
    "app/main.py"
)


def _function(
    tree,
    name,
):
    for node in ast.walk(
        tree
    ):
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == name
        ):
            return node

    raise AssertionError(
        f"Función no encontrada: {name}"
    )


def _calls(
    function,
):
    result = []

    for node in ast.walk(
        function
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        func = node.func

        if isinstance(
            func,
            ast.Name,
        ):
            result.append(
                (
                    func.id,
                    node.lineno,
                )
            )

        elif isinstance(
            func,
            ast.Attribute,
        ):
            result.append(
                (
                    func.attr,
                    node.lineno,
                )
            )

    return result


def test_startup_recovery_uses_runtime_executor():
    source = APP_PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    recovery = _function(
        tree,
        "start_whatsapp_call_history_recovery",
    )

    names = [
        name
        for name, _line
        in _calls(
            recovery
        )
    ]

    assert (
        "submit_call_history_sync"
        in names
    )

    # Nunca crea una frontera Flet/thread adicional
    # para controlar WhatsApp.
    assert "run_thread" not in names


def test_realtime_starts_before_history_recovery():
    source = APP_PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    start = _function(
        tree,
        "start_whatsapp_session_services",
    )

    calls = _calls(
        start
    )

    watch_lines = [
        line
        for name, line
        in calls
        if name == "start_call_watch"
    ]

    recovery_lines = [
        line
        for name, line
        in calls
        if (
            name
            == "start_whatsapp_call_history_recovery"
        )
    ]

    assert len(
        watch_lines
    ) == 1

    assert len(
        recovery_lines
    ) == 1

    assert (
        watch_lines[0]
        < recovery_lines[0]
    )


def test_startup_recovery_is_persistent_not_dry_run():
    source = APP_PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    recovery = _function(
        tree,
        "start_whatsapp_call_history_recovery",
    )

    submit_calls = [
        node
        for node in ast.walk(
            recovery
        )
        if (
            isinstance(
                node,
                ast.Call,
            )
            and isinstance(
                node.func,
                ast.Attribute,
            )
            and node.func.attr
            == "submit_call_history_sync"
        )
    ]

    assert len(
        submit_calls
    ) == 1

    keywords = {
        item.arg:
            item.value
        for item
        in submit_calls[0].keywords
        if item.arg
    }

    dry_run = keywords.get(
        "dry_run"
    )

    assert isinstance(
        dry_run,
        ast.Constant,
    )

    assert (
        dry_run.value
        is False
    )
