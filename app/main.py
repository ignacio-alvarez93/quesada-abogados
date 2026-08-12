from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(
    PROJECT_ROOT / ".env.local",
    override=False,
)


import flet as ft

from backend.services.sqlite_runtime_service import configure_sqlite_runtime
from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)
from database.connection import initialize_database
from frontend.views.login_view import login_view
from frontend.views.clients_view import clients_view
from frontend.views.companies_view import companies_view
from frontend.views.suppliers_view import suppliers_view
from frontend.views.workers_view import workers_view
from frontend.views.settings_view import settings_view
from frontend.views.expedients_view import expedients_view
from frontend.views.expedient_traceability_view import expedient_traceability_view
from frontend.views.economic_view import economic_view
from frontend.views.accounting_view import accounting_view
from frontend.views.fiscal_view import fiscal_view
from frontend.views.payrolls_view import payrolls_view
from frontend.views.box_watch_view import box_watch_view
from frontend.views.reporting_view import reporting_view
from frontend.views.presentation_queue_view import presentation_queue_view
from frontend.views.notifications_view import notifications_view
from frontend.views.calendar_view import calendar_view
from frontend.views.document_inbox_view import document_inbox_view
from frontend.views.communications_view import communications_view
from frontend.layouts.main_layout import main_layout
from frontend.layouts.sidebar import sidebar_menu


def main(page: ft.Page):
    page.title = "Quesada Abogados ERP"

    configure_sqlite_runtime()
    initialize_database()
    configure_sqlite_runtime()

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

    # Runtime único durante toda la sesión del ERP.
    # El navegador se inicia de forma perezosa cuando
    # una operación WhatsApp realmente lo necesita.
    whatsapp_runtime = WhatsAppRuntimeService()

    def return_to_context(
        context,
    ):
        context = dict(
            context
            or {}
        )

        target = context.pop(
            "view",
            None,
        )

        if not target:
            return

        navigate(
            target,
            **context,
        )

    def navigate(view_name, **kwargs):
        if view_name == "Clientes":
            return_context = kwargs.get(
                "return_context"
            )

            content = clients_view(
                page,
                on_create_expediente=lambda cliente_id: navigate(
                    "Expedientes",
                    new_for_client_id=cliente_id,
                    return_context=return_context,
                ),
                on_open_expediente=lambda expediente_id: navigate(
                    "Expedientes",
                    open_expediente_id=expediente_id,
                    return_context=return_context,
                ),
                open_client_id=kwargs.get(
                    "open_client_id"
                ),
                on_context_back=(
                    (
                        lambda:
                            return_to_context(
                                return_context
                            )
                    )
                    if return_context
                    else None
                ),
            )
        elif view_name == "Empresas":
            content = companies_view(page)
        elif view_name == "Proveedores":
            content = suppliers_view(page)
        elif view_name == "Trabajadores":
            content = workers_view(page)
        elif view_name == "Expedientes":
            open_expediente_id = kwargs.get(
                "open_expediente_id"
            )
            new_for_client_id = kwargs.get(
                "new_for_client_id"
            )
            return_to_queue = bool(
                kwargs.get(
                    "return_to_queue"
                )
            )
            return_context = kwargs.get(
                "return_context"
            )

            if open_expediente_id:
                page.open_expediente_id = int(
                    open_expediente_id
                )
                page.return_to_queue_after_expediente = (
                    return_to_queue
                )

            if new_for_client_id:
                page.new_expediente_client_id = int(
                    new_for_client_id
                )

            content = expedients_view(
                page,
                on_return_to_queue=lambda: navigate(
                    "Colas de presentación"
                ),
                on_open_document_inbox=lambda item_id=None, batch_id=None: navigate(
                    "Bandeja documental",
                    open_item_id=item_id,
                    open_batch_id=batch_id,
                ),
                on_context_back=(
                    (
                        lambda:
                            return_to_context(
                                return_context
                            )
                    )
                    if return_context
                    else None
                ),
            )
        elif view_name == "Calendario":
            return_context = kwargs.get(
                "return_context"
            )

            content = calendar_view(
                page,
                on_open_expediente=lambda expediente_id: navigate(
                    "Expedientes",
                    open_expediente_id=expediente_id,
                ),
                on_open_cliente=lambda cliente_id: navigate(
                    "Clientes",
                    open_client_id=cliente_id,
                ),
                initial_action=kwargs.get(
                    "initial_action"
                ),
                initial_client_id=kwargs.get(
                    "initial_client_id"
                ),
                initial_expedient_id=kwargs.get(
                    "initial_expedient_id"
                ),
                on_context_back=(
                    (
                        lambda:
                            return_to_context(
                                return_context
                            )
                    )
                    if return_context
                    else None
                ),
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
        elif view_name == "Notificaciones":
            content = notifications_view(
                page,
                on_open_expediente=lambda expediente_id: navigate(
                    "Expedientes",
                    open_expediente_id=expediente_id,
                ),
            )
        elif view_name == "Trazabilidad Expedientes":
            content = expedient_traceability_view(page)
        elif view_name in ("Cobros", "Conciliación"):
            content = economic_view(page)
        elif view_name == "Pérdidas y ganancias":
            content = accounting_view(page)
        elif view_name == "Fiscal":
            content = fiscal_view(page)
        elif view_name == "Nóminas":
            content = payrolls_view(page)
        elif view_name == "Documentos / Box":
            content = box_watch_view(page)
        elif view_name == "Bandeja documental":
            content = document_inbox_view(
                page,
                on_open_expediente=lambda expediente_id: navigate(
                    "Expedientes",
                    open_expediente_id=expediente_id,
                ),
                open_item_id=kwargs.get("open_item_id"),
                open_batch_id=kwargs.get("open_batch_id"),
            )
        elif view_name == "WhatsApp":
            content = communications_view(
                page,
                whatsapp_runtime=(
                    whatsapp_runtime
                ),
                current_username=(
                    (
                        current_user.get(
                            "value"
                        )
                        or {}
                    ).get(
                        "username"
                    )
                    or "ERP"
                ),
                initial_thread_id=kwargs.get(
                    "thread_id"
                ),
                on_open_cliente=(
                    lambda cliente_id,
                    return_context:
                        navigate(
                            "Clientes",
                            open_client_id=cliente_id,
                            return_context=(
                                return_context
                            ),
                        )
                ),
                on_open_expediente=(
                    lambda expediente_id,
                    return_context:
                        navigate(
                            "Expedientes",
                            open_expediente_id=(
                                expediente_id
                            ),
                            return_context=(
                                return_context
                            ),
                        )
                ),
                on_create_expediente=(
                    lambda cliente_id,
                    return_context:
                        navigate(
                            "Expedientes",
                            new_for_client_id=(
                                cliente_id
                            ),
                            return_context=(
                                return_context
                            ),
                        )
                ),
                on_create_task=(
                    lambda cliente_id,
                    expediente_id,
                    return_context:
                        navigate(
                            "Calendario",
                            initial_action="TASK",
                            initial_client_id=(
                                cliente_id
                            ),
                            initial_expedient_id=(
                                expediente_id
                            ),
                            return_context=(
                                return_context
                            ),
                        )
                ),
                on_create_alert=(
                    lambda cliente_id,
                    expediente_id,
                    return_context:
                        navigate(
                            "Calendario",
                            initial_action="ALERT",
                            initial_client_id=(
                                cliente_id
                            ),
                            initial_expedient_id=(
                                expediente_id
                            ),
                            return_context=(
                                return_context
                            ),
                        )
                ),
            )
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
