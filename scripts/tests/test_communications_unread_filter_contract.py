import ast
from pathlib import Path


VIEW = Path(
    "frontend/views/communications_view.py"
)

SOURCE = VIEW.read_text(
    encoding="utf-8"
)

TREE = ast.parse(
    SOURCE
)


def _function_source(name):
    for node in ast.walk(
        TREE
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
            return ast.get_source_segment(
                SOURCE,
                node,
            ) or ""

    raise AssertionError(
        f"Function not found: {name}"
    )


def test_unread_filter_has_explicit_local_state():
    assert '"unread_only": False' in SOURCE


def test_unread_filter_uses_realtime_sidebar_count():
    source = _function_source(
        "_conversation_item_unread_count"
    )

    assert (
        "_thread_realtime_sidebar_state"
        in source
    )

    assert "unread_count" in source


def test_filtered_items_apply_unread_before_pagination():
    filtered = _function_source(
        "_filtered_conversation_items"
    )

    visible = _function_source(
        "_visible_conversation_items"
    )

    listing = _function_source(
        "build_conversation_list"
    )

    assert "unread_only" in filtered

    assert (
        "_conversation_item_unread_count"
        in filtered
    )

    assert (
        "_filtered_conversation_items"
        in visible
    )

    assert (
        "_filtered_conversation_items"
        in listing
    )


def test_unread_toggle_is_frontend_only():
    source = _function_source(
        "set_unread_filter"
    )

    assert '"unread_only"' in source
    assert '"page"' in source

    assert "communication_service" not in source
    assert "select_thread" not in source
    assert "_route_whatsapp_thread" not in source
    assert "whatsapp_runtime" not in source


def test_unread_chip_is_present_next_to_existing_filters():
    source = _function_source(
        "build_conversation_list"
    )

    assert '"Todas"' in source
    assert '"Vinculadas"' in source
    assert '"Sin vincular"' in source
    assert '"No leídos"' in source
    assert '"UNREAD"' in source


def test_clear_filters_disables_unread_filter():
    source = _function_source(
        "clear_filters"
    )

    assert "unread_only" in source
    assert "False" in source


def test_view_auto_hydrates_sidebar_for_unread_filter():
    source = _function_source(
        "_ensure_whatsapp_view_watch"
    )

    assert (
        "read_sidebar_chat_fingerprint"
        in source
    )

    assert (
        "start_active_chat_watch"
        in source
    )

    assert (
        "_schedule_whatsapp_sidebar_snapshot"
        in source
    )

    # Flet no debe saltarse el runtime.
    assert ".connector" not in source


def test_sidebar_snapshot_reuses_initial_hydration_semantics():
    source = _function_source(
        "_dispatch_whatsapp_sidebar_snapshot"
    )

    assert "SIDEBAR_INITIAL" in source

    assert (
        "_hydrate_whatsapp_sidebar_initial"
        in source
    )
