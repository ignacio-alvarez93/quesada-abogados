from pathlib import Path
import inspect

from frontend.views.communications_view import (
    communications_view,
)


ROOT = Path(__file__).resolve().parents[2]


def test_view_accepts_explicit_active_predicate():
    signature = inspect.signature(
        communications_view
    )

    assert (
        "is_view_active"
        in signature.parameters
    )


def test_app_detaches_only_ui_callback_when_leaving_whatsapp():
    text = (
        ROOT
        / "app"
        / "main.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'previous_view\n            == "WhatsApp"'
        in text
    )

    assert (
        "set_active_chat_watch_callback(\n"
        "                    None"
        in text
    )

    assert (
        "is_view_active=("
        in text
    )

    navigate_start = text.index(
        "    def navigate("
    )

    navigate_end = text.index(
        "    def on_login_success",
        navigate_start,
    )

    navigate_block = text[
        navigate_start:
        navigate_end
    ]

    # Navegar no debe apagar transporte/sincronización.
    assert (
        "stop_active_chat_watch("
        not in navigate_block
    )

    assert (
        "whatsapp_runtime.close("
        not in navigate_block
    )


def test_stale_watcher_and_scroll_are_guarded_before_flet_mutation():
    text = (
        ROOT
        / "frontend"
        / "views"
        / "communications_view.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "def _ui_active()"
        in text
    )

    required_markers = (
        "# WA-FLET-LIFE dispatch guard",
        "# WA-FLET-LIFE schedule guard",
        "# WA-FLET-LIFE consumer guard",
        "# WA-FLET-LIFE scroll guard",
        "# WA-FLET-LIFE force-scroll guard",
        "# WA-FLET-LIFE safe-update guard",
        "# WA-FLET-LIFE sidebar guard",
        "# WA-FLET-LIFE history guard",
        "# WA-FLET-LIFE chat-panel guard",
        "# WA-FLET-LIFE context-panel guard",
    )

    for marker in required_markers:
        assert marker in text


def test_returning_to_whatsapp_rebinds_existing_watcher_callback():
    text = (
        ROOT
        / "frontend"
        / "views"
        / "communications_view.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        ".active_chat_watch_running"
        in text
    )

    assert (
        "set_active_chat_watch_callback(\n"
        "                    _schedule_whatsapp_watch_change"
        in text
    )

    # Rebind no debe crear otro watcher.
    tail = text[
        text.index(
            "# Si el watcher ya sobrevivía"
        ):
    ]

    assert (
        "start_active_chat_watch("
        not in tail
    )
