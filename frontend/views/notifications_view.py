import threading

import flet as ft

from backend.services import (
    notification_tracking_service,
)
from backend.services.email_platform import (
    email_sync_orchestrator_service,
)
from frontend.components.app_alert import (
    error_alert,
    success_alert,
    warning_alert,
)
from frontend.components.app_button import (
    primary_button,
    secondary_button,
)
from frontend.components.app_card import metric_card
from frontend.components.app_empty_state import (
    empty_state,
)
from frontend.components.listing import (
    compact_pagination_bar,
    counter_chips,
)


Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"

STATUS_MAP = {
    "ESPERA_NUMERO_EXPEDIENTE": (
        "Espera número",
        "#FFF7E6",
        "#B54708",
    ),
    "ESPERA_ADMISION_TRAMITE": (
        "Espera admisión",
        "#EAF3FF",
        "#0057B8",
    ),
    "ESPERA_RESOLUCION": (
        "Espera resolución",
        "#EEF4FF",
        "#3538CD",
    ),
    "TODOS": (
        "Todos",
        "#F8FAFC",
        "#64748B",
    ),
}


def _full_client_name(item):
    return " ".join(
        [
            item.get("cliente_nombre") or "",
            item.get(
                "cliente_primer_apellido"
            )
            or "",
            item.get(
                "cliente_segundo_apellido"
            )
            or "",
        ]
    ).strip()


def _status_badge(status):
    label, background, foreground = (
        STATUS_MAP.get(
            status,
            (
                status or "-",
                "#F2F4F7",
                "#475467",
            ),
        )
    )

    return ft.Container(
        bgcolor=background,
        border_radius=999,
        padding=ft.padding.symmetric(
            horizontal=10,
            vertical=4,
        ),
        content=ft.Text(
            label.upper(),
            size=11,
            weight=ft.FontWeight.BOLD,
            color=foreground,
        ),
    )


def notifications_view(
    page: ft.Page,
    on_open_expediente=None,
):
    state = {
        "items": [],
        "counts": {},
        "filter": "TODOS",
        "page": 1,
        "page_size": 10,
        "message": None,
        "syncing": False,
        "account_status": None,
    }

    content_area = ft.Container(
        expand=True,
    )

    def safe_update():
        try:
            content_area.content = build_content()
            page.update()
        except Exception as exc:
            import traceback

            print(
                "[NOTIFICACIONES] Error al renderizar la vista:",
                repr(exc),
            )
            traceback.print_exc()

            content_area.content = ft.Container(
                padding=24,
                bgcolor="#FFFFFF",
                border=ft.border.all(1, "#FDA29B"),
                border_radius=12,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            "Error al construir la vista de Notificaciones",
                            size=20,
                            weight=ft.FontWeight.BOLD,
                            color="#B42318",
                        ),
                        ft.Text(
                            str(exc),
                            size=13,
                            color="#344054",
                            selectable=True,
                        ),
                    ],
                    spacing=10,
                ),
            )

            try:
                page.update()
            except Exception:
                traceback.print_exc()

    def start_background_worker(
        target,
        *args,
    ):
        try:
            runner = getattr(
                page,
                "run_thread",
                None,
            )

            if callable(runner):
                runner(target, *args)
                return
        except Exception:
            pass

        threading.Thread(
            target=target,
            args=args,
            daemon=True,
        ).start()

    def set_message(control):
        state["message"] = control

    def load_account_status():
        try:
            state["account_status"] = (
                email_sync_orchestrator_service
                .get_ionos_status()
            )
        except Exception as exc:
            state["account_status"] = {
                "last_sync_status": "ERROR",
                "last_sync_error": str(exc),
                "last_sync_cursor": "",
                "last_sync_at": "",
                "account_email": "",
            }

    def load_tracking():
        items = (
            notification_tracking_service
            .list_active_tracking()
            or []
        )

        counts = {
            "TODOS": len(items),
            "ESPERA_NUMERO_EXPEDIENTE": 0,
            "ESPERA_ADMISION_TRAMITE": 0,
            "ESPERA_RESOLUCION": 0,
        }

        for item in items:
            status = (
                item.get("estado")
                or ""
            )

            if status in counts:
                counts[status] += 1

        state["counts"] = counts

        if state["filter"] == "TODOS":
            state["items"] = items
        else:
            state["items"] = [
                item
                for item in items
                if item.get("estado")
                == state["filter"]
            ]

    def load():
        load_tracking()
        load_account_status()

    def refresh(e=None):
        load()
        safe_update()

    def set_filter(value):
        state["filter"] = value
        state["page"] = 1
        load_tracking()
        safe_update()

    def set_page(page_number):
        state["page"] = max(
            1,
            int(page_number or 1),
        )
        safe_update()

    def open_expediente(expediente_id):
        if on_open_expediente:
            on_open_expediente(
                expediente_id
            )
            return

        set_message(
            error_alert(
                "No hay navegación configurada "
                "para abrir expedientes."
            )
        )
        safe_update()

    def format_sync_summary(result):
        return (
            "Revisión de correo completada.\n"
            f"Mensajes encontrados: "
            f"{result.get('uids_found', 0)}.\n"
            f"Expedientes actualizados: "
            f"{result.get('applied_count', 0)}.\n"
            f"Pendientes de revisión: "
            f"{result.get('review_required_count', 0)}.\n"
            f"Ignorados: "
            f"{result.get('ignored_count', 0)}.\n"
            f"Errores: "
            f"{result.get('error_count', 0)}."
        )

    def sync_worker():
        try:
            result = (
                email_sync_orchestrator_service
                .sync_ionos_extranjeria()
            )

            if result.get("busy"):
                set_message(
                    warning_alert(
                        result.get("message")
                        or (
                            "Ya hay una revisión "
                            "en curso."
                        )
                    )
                )

            elif result.get("ok"):
                set_message(
                    success_alert(
                        format_sync_summary(
                            result
                        )
                    )
                )

            else:
                detail = result.get(
                    "message"
                ) or (
                    "No se pudo completar "
                    "la revisión."
                )

                set_message(
                    error_alert(detail)
                )

        except Exception as exc:
            set_message(
                error_alert(
                    "No se pudo revisar IONOS: "
                    f"{exc}"
                )
            )

        finally:
            state["syncing"] = False
            load()
            safe_update()

    def start_ionos_sync(e=None):
        if state["syncing"]:
            set_message(
                warning_alert(
                    "Ya hay una revisión de "
                    "correo en curso."
                )
            )
            safe_update()
            return

        state["syncing"] = True
        set_message(
            warning_alert(
                "Revisando correo IONOS. "
                "La vista se actualizará "
                "al finalizar."
            )
        )
        safe_update()

        start_background_worker(
            sync_worker
        )

    def tracking_card(item):
        expediente_id = int(
            item["expediente_id"]
        )

        cliente = (
            _full_client_name(item)
            or "Cliente no indicado"
        )

        expediente = (
            item.get("numero_expediente")
            or item.get(
                "numero_expediente_interno"
            )
            or f"Expediente #{expediente_id}"
        )

        tipo_expediente = (
            item.get(
                "tipo_expediente_nombre"
            )
            or "Tipo no indicado"
        )

        mercurio_id = (
            item.get(
                "numero_presentacion_registro"
            )
            or "-"
        )

        official_number = (
            item.get(
                "numero_expediente_extranjeria"
            )
            or "-"
        )

        wait_started_at = (
            item.get(
                "fecha_inicio_espera_numero"
            )
            or item.get(
                "fecha_inicio_espera_admision"
            )
            or item.get(
                "fecha_inicio_espera_resolucion"
            )
            or "-"
        )

        def open_action(e=None):
            open_expediente(
                expediente_id
            )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                "#E4E7EC",
            ),
            border_radius=14,
            padding=ft.padding.symmetric(
                horizontal=16,
                vertical=14,
            ),
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                expand=True,
                                content=ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text(
                                            expediente,
                                            size=15,
                                            weight=ft.FontWeight.BOLD,
                                            color=Q_PRIMARY_DARK,
                                        ),
                                        ft.Text(
                                            cliente,
                                            size=13,
                                            weight=ft.FontWeight.W_600,
                                            color="#344054",
                                        ),
                                        ft.Text(
                                            tipo_expediente,
                                            size=12,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                ),
                            ),
                            _status_badge(
                                item.get("estado")
                            ),
                            ft.IconButton(
                                icon=ft.Icons.OPEN_IN_NEW,
                                tooltip="Abrir expediente",
                                on_click=open_action,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                    ft.Divider(
                        height=1,
                        color="#EAECF0",
                    ),
                    ft.Row(
                        controls=[
                            ft.Container(
                                width=230,
                                content=ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text(
                                            "ID Mercurio",
                                            size=11,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(
                                            str(mercurio_id),
                                            size=12,
                                            weight=ft.FontWeight.W_600,
                                            color="#344054",
                                            selectable=True,
                                        ),
                                    ],
                                ),
                            ),
                            ft.Container(
                                width=230,
                                content=ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text(
                                            "Número oficial",
                                            size=11,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(
                                            str(official_number),
                                            size=12,
                                            weight=ft.FontWeight.W_600,
                                            color="#344054",
                                            selectable=True,
                                        ),
                                    ],
                                ),
                            ),
                            ft.Container(
                                width=210,
                                content=ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text(
                                            "Inicio de espera",
                                            size=11,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(
                                            str(wait_started_at),
                                            size=12,
                                            color="#344054",
                                        ),
                                    ],
                                ),
                            ),
                            ft.Container(
                                width=210,
                                content=ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text(
                                            "Actualizado",
                                            size=11,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(
                                            str(
                                                item.get(
                                                    "updated_at"
                                                )
                                                or "-"
                                            ),
                                            size=12,
                                            color="#344054",
                                        ),
                                    ],
                                ),
                            ),
                        ],
                        spacing=14,
                        wrap=True,
                    ),
                ],
            ),
        )

    def account_panel():
        account = (
            state.get("account_status")
            or {}
        )

        status = (
            account.get(
                "last_sync_status"
            )
            or "SIN DATOS"
        )

        status_color = (
            "#027A48"
            if status == "OK"
            else "#B42318"
            if status == "ERROR"
            else "#64748B"
        )

        controls = [
            ft.Text(
                "Vigilancia IONOS",
                size=14,
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            ),
            ft.Text(
                account.get(
                    "account_email"
                )
                or "Cuenta no disponible",
                size=12,
                color=Q_MUTED,
            ),
            ft.Row(
                controls=[
                    ft.Text(
                        f"Estado: {status}",
                        size=12,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=status_color,
                    ),
                    ft.Text(
                        "Última revisión: "
                        + str(
                            account.get(
                                "last_sync_at"
                            )
                            or "-"
                        ),
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        "Último UID: "
                        + str(
                            account.get(
                                "last_sync_cursor"
                            )
                            or "-"
                        ),
                        size=12,
                        color=Q_MUTED,
                    ),
                ],
                spacing=14,
                wrap=True,
            ),
        ]

        last_error = account.get(
            "last_sync_error"
        )

        if last_error:
            controls.append(
                ft.Text(
                    last_error,
                    size=11,
                    color="#B42318",
                    selectable=True,
                )
            )

        return ft.Container(
            content=ft.Column(
                controls=controls,
                spacing=4,
            ),
            padding=14,
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                "#E4E7EC",
            ),
            border_radius=12,
        )

    def build_content():
        counts = state.get("counts") or {}
        items = state.get("items") or []

        sync_button = primary_button(
            (
                "Revisando correo..."
                if state["syncing"]
                else "Revisar correo IONOS"
            ),
            start_ionos_sync,
        )
        sync_button.disabled = bool(
            state["syncing"]
        )

        controls = [
            ft.Row(
                controls=[
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(
                                "Notificaciones",
                                size=28,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Text(
                                (
                                    "Seguimiento operativo "
                                    "de expedientes y "
                                    "comunicaciones oficiales"
                                ),
                                size=14,
                                color=Q_MUTED,
                            ),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            sync_button,
                            secondary_button(
                                "Actualizar",
                                refresh,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            account_panel(),
            ft.Row(
                controls=[
                    metric_card(
                        "Espera número",
                        counts.get(
                            "ESPERA_NUMERO_EXPEDIENTE",
                            0,
                        ),
                    ),
                    metric_card(
                        "Espera admisión",
                        counts.get(
                            "ESPERA_ADMISION_TRAMITE",
                            0,
                        ),
                    ),
                    metric_card(
                        "Espera resolución",
                        counts.get(
                            "ESPERA_RESOLUCION",
                            0,
                        ),
                    ),
                    metric_card(
                        "Total activo",
                        counts.get(
                            "TODOS",
                            0,
                        ),
                    ),
                ],
                spacing=12,
                wrap=True,
            ),
            counter_chips(
                options=[
                    (
                        "ESPERA_NUMERO_EXPEDIENTE",
                        "Espera número",
                    ),
                    (
                        "ESPERA_ADMISION_TRAMITE",
                        "Espera admisión",
                    ),
                    (
                        "ESPERA_RESOLUCION",
                        "Espera resolución",
                    ),
                ],
                counts=counts,
                active_value=state["filter"],
                on_select=set_filter,
                include_all=True,
                all_label="Todos",
                all_value="TODOS",
                status_map=STATUS_MAP,
                bordered_status=True,
            ),
        ]

        if state.get("message"):
            controls.append(
                state["message"]
            )

        total_items = len(items)
        page_size = int(
            state.get("page_size")
            or 10
        )
        current_page = max(
            1,
            int(state.get("page") or 1),
        )
        total_pages = max(
            1,
            (
                total_items
                + page_size
                - 1
            )
            // page_size,
        )

        current_page = min(
            current_page,
            total_pages,
        )
        state["page"] = current_page

        start = (
            current_page - 1
        ) * page_size
        end = start + page_size
        page_items = items[start:end]

        if total_items:
            controls.append(
                compact_pagination_bar(
                    page=current_page,
                    page_size=page_size,
                    total_items=total_items,
                    on_page_change=set_page,
                    label_prefix="Notificaciones",
                )
            )

        cards_controls = []

        if page_items:
            cards_controls.extend(
                tracking_card(item)
                for item in page_items
            )
        else:
            cards_controls.append(
                empty_state(
                    "No hay expedientes "
                    "en este estado."
                )
            )

        controls.append(
            ft.Container(
                expand=True,
                content=ft.Column(
                    controls=cards_controls,
                    spacing=8,
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
            )
        )

        return ft.Column(
            controls=controls,
            spacing=14,
            expand=True,
        )

    try:
        load()
        content_area.content = build_content()
    except Exception as exc:
        import traceback

        print(
            "[NOTIFICACIONES] Error durante la carga inicial:",
            repr(exc),
        )
        traceback.print_exc()

        content_area.content = ft.Container(
            padding=24,
            bgcolor="#FFFFFF",
            border=ft.border.all(1, "#FDA29B"),
            border_radius=12,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Error al cargar Notificaciones",
                        size=20,
                        weight=ft.FontWeight.BOLD,
                        color="#B42318",
                    ),
                    ft.Text(
                        str(exc),
                        size=13,
                        color="#344054",
                        selectable=True,
                    ),
                ],
                spacing=10,
            ),
        )

    return content_area
