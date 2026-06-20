import flet as ft

from database.connection import initialize_database
from frontend.views.login_view import login_view
from frontend.views.clients_view import clients_view
from frontend.views.companies_view import companies_view
from frontend.views.settings_view import settings_view
from frontend.views.expedients_view import expedients_view
from frontend.views.expedient_traceability_view import expedient_traceability_view
from frontend.views.economic_view import economic_view
from frontend.views.box_watch_view import box_watch_view
from frontend.views.reporting_view import reporting_view
from frontend.views.presentation_queue_view import presentation_queue_view
from frontend.layouts.main_layout import main_layout
from frontend.layouts.sidebar import sidebar_menu


def main(page: ft.Page):
    page.title = "Quesada Abogados ERP"

    initialize_database()

    page.window.width = 1650
    page.window.height = 920
    page.window.min_width = 1200
    page.window.min_height = 750
    page.window.full_screen = False
    page.window.maximized = True
    page.window.resizable = True
    page.window.minimizable = True
    page.window.maximizable = True

    try:
        page.window_maximized = True
    except Exception:
        pass

    try:
        page.window_full_screen = False
    except Exception:
        pass

    current_user = {"value": None}
    main_container = ft.Container(expand=True)

    def navigate(view_name, **kwargs):
        if view_name == "Clientes":
            content = clients_view(page)
        elif view_name == "Empresas":
            content = companies_view(page)
        elif view_name == "Expedientes":
            open_expediente_id = kwargs.get("open_expediente_id")
            return_to_queue = bool(kwargs.get("return_to_queue"))

            if open_expediente_id:
                page.open_expediente_id = int(open_expediente_id)
                page.return_to_queue_after_expediente = return_to_queue

            content = expedients_view(
                page,
                on_return_to_queue=lambda: navigate("Colas de presentación"),
            )
        elif view_name == "Colas de presentación":
            content = presentation_queue_view(
                page,
                on_open_expediente=lambda expediente_id: navigate(
                    "Expedientes",
                    open_expediente_id=expediente_id,
                    return_to_queue=True,
                ),
            )
        elif view_name == "Trazabilidad Expedientes":
            content = expedient_traceability_view(page)
        elif view_name == "Cobros":
            content = economic_view(page)
        elif view_name == "Documentos / Box":
            content = box_watch_view(page)
        elif view_name == "Reporting":
            content = reporting_view(page)
        elif view_name == "Configuración":
            content = settings_view(page)
        else:
            content = ft.Container(
                expand=True,
                content=ft.Text(
                    f"Vista {view_name} en construcción",
                    size=24,
                    weight=ft.FontWeight.BOLD,
                    color="#003B7A",
                ),
            )

        main_container.content = main_layout(
            sidebar=sidebar_menu(on_navigate=navigate),
            content=content,
        )
        page.update()

    def on_login_success(user):
        current_user["value"] = user
        navigate("Clientes")

    def start():
        main_container.content = login_view(page, on_login_success=on_login_success)
        page.update()

    page.add(main_container)
    start()

    try:
        page.window.maximized = True
    except Exception:
        pass

    try:
        page.window_maximized = True
    except Exception:
        pass

    page.update()


ft.run(main)
