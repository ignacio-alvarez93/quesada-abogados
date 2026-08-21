from pathlib import Path


VIEW = (
    Path(__file__)
    .resolve()
    .parents[2]
    / "frontend"
    / "views"
    / "icpplus_view.py"
)


def test_profile_and_query_are_inside_modal_not_main_dashboard():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        "check_dialog = ft.AlertDialog("
        in text
    )

    assert (
        "open_check_button = ft.ElevatedButton("
        in text
    )

    final_return = text[
        text.rfind(
            "    return ft.Container("
        ):
    ]

    assert (
        "profile_card,"
        not in final_return
    )

    assert (
        "query_card,"
        not in final_return
    )

    assert (
        "dashboard_three_panel,"
        in final_return
    )

    assert (
        "persistent_state_card,"
        not in final_return
    )


def test_dashboard_contains_test_reservation_chip():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        "icpplus_test_reservation_service"
        in text
    )

    assert (
        "test_reservation_chip"
        in text
    )

    assert (
        '"Cita reservada · 0"'
        in text
    )

    assert (
        '"Cita reservada · 1"'
        in text
    )

    assert (
        "appointment_history_header"
        in text
    )

    final_return = text[
        text.rfind(
            "    return ft.Container("
        ):
    ]

    assert (
        '"Cita de prueba reservada"'
        not in final_return
    )

    assert (
        "test_reservation_panel,"
        not in final_return
    )


def test_test_profile_is_explicitly_not_a_client():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        "No corresponde a ningún cliente."
        in text
        or
        "No representan a ningún cliente."
        in text
    )

    assert (
        "perfil técnico"
        in text.lower()
    )


def test_dashboard_materializes_unchecked_configured_offices():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        "def build_dashboard_cards("
        in text
    )

    assert (
        '"pending":'
        in text
    )

    assert (
        '"PENDING"'
        in text
    )

    assert (
        "service.list_offices("
        in text
    )

    assert (
        "Pendiente de primera comprobación."
        in text
    )


def test_dashboard_uses_three_scrollable_panels():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        'title="Monitorización por provincia"'
        in text
    )

    assert (
        'title="Historial de citas"'
        in text
    )

    assert (
        'title="Historial de comprobaciones"'
        in text
    )

    assert (
        "province_monitor_column"
        in text
    )

    assert (
        "appointment_history_column"
        in text
    )

    assert (
        "check_history_column"
        in text
    )

    final_return = text[
        text.rfind(
            "    return ft.Container("
        ):
    ]

    assert (
        "dashboard_three_panel,"
        in final_return
    )

    assert (
        "persistent_state_card,"
        not in final_return
    )


def test_root_page_does_not_scroll_and_panels_do():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    final_return = text[
        text.rfind(
            "    return ft.Container("
        ):
    ]

    assert (
        "scroll=ft.ScrollMode.AUTO"
        not in final_return
    )

    assert (
        "province_monitor_column = ft.Column("
        in text
    )

    assert (
        "appointment_history_column = ft.Column("
        in text
    )

    assert (
        "check_history_column = ft.Column("
        in text
    )


def test_test_reservation_is_chip_not_dashboard_kpi():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    final_return = text[
        text.rfind(
            "    return ft.Container("
        ):
    ]

    assert (
        "test_reservation_chip"
        in text
    )

    assert (
        "appointment_history_header"
        in text
    )

    assert (
        '"Cita de prueba reservada"'
        not in final_return
    )

    assert (
        "test_reservation_panel,"
        not in final_return
    )


def test_appointment_history_is_grouped_by_check_run():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        "def _appointment_run_card("
        in text
    )

    assert (
        "Citas obtenidas en "
        in text
    )

    assert (
        'item.get(\n                    "appointments"'
        in text
        or
        'item.get(\n                    "appointments"\n'
        in text
    )


def test_three_panels_have_no_fixed_505_height():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        "height=505"
        not in text
    )

    assert (
        "ft.CrossAxisAlignment.STRETCH"
        in text
    )

    assert (
        "dashboard_three_panel = ft.Row("
        in text
    )


def test_dashboard_filters_use_app_autocomplete():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        "AppAutocomplete("
        in text
    )

    assert (
        "dashboard_province_filter.control"
        in text
    )

    assert (
        "dashboard_status_filter.control"
        in text
    )


def test_appointment_history_is_paginated_by_ten_runs():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        "APPOINTMENT_HISTORY_PAGE_SIZE = 10"
        in text
    )

    assert (
        "compact_pagination_bar("
        in text
    )

    assert (
        "page_runs = runs["
        in text
    )

    assert (
        "appointment_pagination_host"
        in text
    )


def test_bot_dialog_has_four_governed_steps():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        'modal_profile_step'
        in text
    )

    assert (
        'modal_query_step'
        in text
    )

    assert (
        'modal_execution_step'
        in text
    )

    assert (
        'modal_result_step'
        in text
    )

    assert (
        '"Ejecución"'
        in text
    )


def test_bot_dialog_query_uses_app_autocomplete():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        "province_dd = AppAutocomplete("
        in text
    )

    assert (
        "procedure_dd = AppAutocomplete("
        in text
    )

    assert (
        "office_dd = AppAutocomplete("
        in text
    )

    assert (
        "province_dd.control"
        in text
    )

    assert (
        "procedure_dd.control"
        in text
    )

    assert (
        "office_dd.control"
        in text
    )


def test_bot_execution_stays_inside_dialog():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    on_check_start = text.index(
        "    def on_check("
    )

    on_check_end = text.index(
        "    check_button.on_click",
        on_check_start,
    )

    on_check = text[
        on_check_start:
        on_check_end
    ]

    assert (
        "close_check_dialog()"
        not in on_check
    )

    assert (
        'set_dialog_step(\n            "execution"'
        in on_check
    )


def test_worker_moves_dialog_to_result():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    worker_start = text.index(
        "    def check_worker("
    )

    worker_end = text.index(
        "    def on_check(",
        worker_start,
    )

    worker = text[
        worker_start:
        worker_end
    ]

    assert (
        "render_dialog_result("
        in worker
    )

    assert (
        'set_dialog_step(\n                "result"'
        in worker
    )


def test_final_launch_button_name():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    assert (
        '"Lanzar comprobación"'
        in text
    )


def test_check_dialog_uses_explicit_overlay_lifecycle():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "    def open_check_dialog("
    )

    end = text.index(
        "    open_check_button = ft.ElevatedButton(",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "page.overlay.append("
        in block
    )

    assert (
        "check_dialog.open = True"
        in block
    )

    assert (
        'set_dialog_step(\n            "profile"'
        in block
    )


def test_check_dialog_close_is_explicit():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "    def close_check_dialog("
    )

    end = text.index(
        "    dialog_back_button.on_click",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "check_dialog.open = False"
        in block
    )


def test_worker_shows_result_before_dashboard_refresh():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "    def check_worker("
    )

    end = text.index(
        "    def on_check(",
        start,
    )

    worker = text[
        start:end
    ]

    result_pos = worker.index(
        "render_dialog_result("
    )

    result_step_pos = worker.index(
        'set_dialog_step(\n                "result"',
        result_pos,
    )

    dashboard_pos = worker.index(
        "refresh_persistent_cards()",
        result_step_pos,
    )

    assert (
        result_pos
        < result_step_pos
        < dashboard_pos
    )


def test_legacy_appointment_cards_merge_with_new_history():
    text = VIEW.read_text(
        encoding="utf-8"
    )

    start = text.index(
        "    def refresh_appointment_history("
    )

    end = text.index(
        "    def refresh_check_history",
        start,
    )

    block = text[
        start:end
    ]

    assert (
        "history_office_keys = {"
        in block
    )

    assert (
        "last_known_appointments"
        in block
    )

    assert (
        "last_valid"
        in block
    )

    # Regresión:
    # el fallback legacy no puede depender de que TODO el
    # histórico esté vacío.
    #
    # Puede existir otro `if not runs:` legítimo más abajo
    # para representar el estado vacío del panel.
    legacy_merge_start = block.index(
        "history_office_keys = {"
    )

    legacy_merge_end = block.index(
        "runs.sort(",
        legacy_merge_start,
    )

    legacy_merge = block[
        legacy_merge_start:
        legacy_merge_end
    ]

    assert (
        "if not runs:"
        not in legacy_merge
    )

    assert (
        "for card in ("
        in legacy_merge
    )

    assert (
        "if office_key:"
        in legacy_merge
    )
