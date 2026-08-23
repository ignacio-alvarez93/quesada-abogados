from pathlib import Path


SOURCE_PATH = Path(
    "frontend/views/communications_view.py"
)


def test_whatsapp_overview_log_is_cp1252_safe():
    payload = {
        "thread_id": 21,
        "display_name": "Mama 😍",
    }

    rendered = ascii(payload)

    rendered.encode("cp1252")

    assert "\\U0001f60d" in rendered


def test_whatsapp_route_uses_safe_ascii_logging():
    source = SOURCE_PATH.read_text(
        encoding="utf-8"
    )

    start = source.index(
        "def _finish_whatsapp_route_ui("
    )

    end = source.index(
        "def _schedule_finish_whatsapp_route_ui(",
        start,
    )

    block = source[start:end]

    assert (
        '"[WA-FLET] thread overview refreshed"'
        in block
    )
    assert "ascii(" in block
    assert "ascii(exc)" in block
