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
                ast.FunctionDef,
            )
            and node.name == name
        ):
            return node

    raise AssertionError(
        f"Función no encontrada: {name}"
    )


def _segment(
    source,
    tree,
    name,
):
    node = _function(
        tree,
        name,
    )

    return (
        ast.get_source_segment(
            source,
            node,
        )
        or ""
    )


def test_selected_item_never_falls_back_to_first_thread():
    source = PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    selected_item = _segment(
        source,
        tree,
        "selected_item",
    )

    assert "items[0]" not in selected_item

    assert (
        "if selected_id is None"
        in selected_item
    )

    assert "return None" in selected_item


def test_load_data_never_autoselects_first_thread():
    source = PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    load_data = _segment(
        source,
        tree,
        "load_data",
    )

    assert (
        'state["items"][0]'
        not in load_data
    )

    assert (
        '"selected_thread_id"'
        in load_data
    )

    assert (
        "selected_before"
        in load_data
    )


def test_chat_panel_has_explicit_empty_state():
    source = PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    build_chat_panel = _segment(
        source,
        tree,
        "build_chat_panel",
    )

    assert (
        "Selecciona una conversación"
        in build_chat_panel
    )
