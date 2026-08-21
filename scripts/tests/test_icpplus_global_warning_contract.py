from pathlib import Path


APP = (
    Path(__file__)
    .resolve()
    .parents[2]
    / "app"
    / "main.py"
)


def test_warning_ui_is_global_not_inside_icp_view():
    text = APP.read_text(
        encoding="utf-8"
    )

    assert (
        "run_icpplus_warning_watch"
        in text
    )

    assert (
        "get_last_warning_event"
        in text
    )

    assert (
        "start_icpplus_warning_watch()"
        in text
    )


def test_warning_dialog_has_skip_and_stop_actions():
    text = APP.read_text(
        encoding="utf-8"
    )

    assert (
        "Omitir este intento"
        in text
    )

    assert (
        "Detener vigilancia"
        in text
    )

    assert (
        'action="SKIP"'
        in text
    )

    assert (
        'action="STOP"'
        in text
    )


def test_warning_dialog_does_not_offer_early_execution():
    text = APP.read_text(
        encoding="utf-8"
    )

    warning_start = text.index(
        "ICP PLUS · AVISO GLOBAL T-60"
    )

    warning_end = text.index(
        "# Composition root de Comunicaciones.",
        warning_start,
    )

    block = text[
        warning_start:warning_end
    ]

    assert (
        "Ejecutar ahora"
        not in block
    )

    assert (
        "15 minutos"
        in block
    )


def test_global_warning_has_safe_visual_smoke():
    text = APP.read_text(
        encoding="utf-8"
    )

    assert (
        "QUESADA_ICPPLUS_WARNING_UI_SMOKE"
        in text
    )

    assert (
        "run_icpplus_warning_ui_smoke"
        in text
    )

    assert (
        "ICPPLUS-WARNING-SMOKE-001"
        in text
    )

    assert (
        "SMOKE_ACTION_ONLY"
        in text
    )

    start = text.index(
        "async def run_icpplus_warning_ui_smoke"
    )

    end = text.index(
        "def maybe_start_icpplus_warning_ui_smoke",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "create_schedule"
        not in block
    )

    assert (
        "check_availability"
        not in block
    )

    assert (
        "record_warning"
        not in block
    )

    assert (
        "handle_warning_action"
        not in block
    )


def test_global_warning_watch_publishes_ui_heartbeat():
    text = APP.read_text(
        encoding="utf-8"
    )

    assert (
        "icpplus_ui_presence_service.mark_alive"
        in text
    )

    assert (
        "icpplus_ui_presence_service.clear"
        in text
    )

    assert (
        'f"ERP-{os.getpid()}"'
        in text
    )


def test_heartbeat_failure_does_not_block_warning_read():
    text = APP.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "async def run_icpplus_warning_watch"
    )

    end = text.index(
        "def start_icpplus_warning_watch",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "heartbeat error:"
        in block
    )

    assert (
        "heartbeat_exc"
        in block
    )

    assert (
        ".get_last_warning_event()"
        in block
    )

    assert (
        block.index(
            "heartbeat error:"
        )
        < block.index(
            ".get_last_warning_event()"
        )
    )
