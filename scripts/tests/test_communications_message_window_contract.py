import ast
from pathlib import Path


PATH = Path(
    "frontend/views/communications_view.py"
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
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name == name
        ):
            return node

    raise AssertionError(
        f"Función no encontrada: {name}"
    )


def test_watcher_consumes_message_window_changed():
    source = PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    function = _function(
        tree,
        "_on_whatsapp_watch_change",
    )

    constants = {
        node.value
        for node in ast.walk(
            function
        )
        if (
            isinstance(
                node,
                ast.Constant,
            )
            and isinstance(
                node.value,
                str,
            )
        )
    }

    assert (
        "MESSAGE_WINDOW_CHANGED"
        in constants
    )

    assert (
        "INITIAL"
        in constants
    )


def test_window_expansion_uses_full_history_refresh():
    source = PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    function = _function(
        tree,
        "_on_whatsapp_watch_change",
    )

    names = [
        node.func.id
        for node in ast.walk(
            function
        )
        if (
            isinstance(
                node,
                ast.Call,
            )
            and isinstance(
                node.func,
                ast.Name,
            )
        )
    ]

    assert (
        "_refresh_message_history_control"
        in names
    )

    assert (
        "full_window_recovery"
        in {
            node.id
            for node in ast.walk(
                function
            )
            if isinstance(
                node,
                ast.Name,
            )
        }
    )
