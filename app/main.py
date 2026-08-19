import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(
    PROJECT_ROOT / ".env.local",
    override=False,
)


import flet as ft

from backend.services.sqlite_runtime_service import configure_sqlite_runtime
from backend.repositories.sqlite_communication_repository import (
    SQLiteCommunicationRepository,
)
from backend.services.communication_call_service import (
    CommunicationCallService,
)
from backend.services.communication_service import (
    CommunicationService,
)
from backend.services.call_ui_event_service import (
    CallUIEvent,
    CallUIEventService,
)
from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)
from backend.services.dehu_runtime_service import (
    DehuRuntimeService,
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
from frontend.views.calls_view import calls_view
from frontend.layouts.main_layout import main_layout
from frontend.layouts.sidebar import sidebar_menu
from frontend.components.global_call_ui_coordinator import (
    GlobalCallUICoordinator,
)


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

    # Vista actualmente propietaria de la UI central.
    #
    # Los runtimes de sesión pueden continuar vivos al navegar,
    # pero un callback perteneciente a una vista desmontada jamás
    # debe volver a tocar sus controles Flet.
    active_view = {
        "value": None,
    }

    main_container = ft.Container(expand=True)

    # Composition root de Comunicaciones.
    #
    # Una única abstracción repository alimenta mensajes
    # y llamadas. SQLite sigue encapsulado en backend/app:
    # ninguna vista conoce persistencia física.
    communication_repository = (
        SQLiteCommunicationRepository()
    )

    communication_service = (
        CommunicationService(
            repository=(
                communication_repository
            )
        )
    )

    communication_call_service = (
        CommunicationCallService(
            repository=(
                communication_repository
            )
        )
    )

    # Runtime único durante toda la sesión del ERP.
    #
    # El navegador sigue iniciándose de forma perezosa.
    # La persistencia realtime de llamadas queda habilitada
    # porque CallService se inyecta explícitamente.
    whatsapp_runtime = WhatsAppRuntimeService(
        communication_service=(
            communication_service
        ),
        call_service=(
            communication_call_service
        ),
    )

    whatsapp_runtime_closed = {
        "value": False,
    }

    # CALL-UX-4 · presentación global de llamadas.
    #
    # El evento es provider-neutral y la UI no conoce
    # Selenium, SQLite ni WhatsAppConnector.
    call_ui_event_service = (
        CallUIEventService(
            call_service=(
                communication_call_service
            ),
        )
    )

    def accept_global_call(
        event,
    ):
        return (
            whatsapp_runtime
            .accept_incoming_call(
                event.call_id,
                expected_provider_call_id=(
                    event.provider_call_id
                ),
                expected_external_call_key=(
                    event.external_call_key
                ),
                wait_timeout=5,
                confirm_timeout=3,
            )
        )

    def reject_global_call(
        event,
    ):
        return (
            whatsapp_runtime
            .reject_incoming_call(
                event.call_id,
                expected_provider_call_id=(
                    event.provider_call_id
                ),
                expected_external_call_key=(
                    event.external_call_key
                ),
                wait_timeout=5,
                confirm_timeout=3,
            )
        )

    call_reason_options = tuple(
        {
            "code": option.code,
            "label": option.label,
        }
        for option
        in communication_call_service
        .list_reason_options()
    )

    def save_global_post_call(
        event,
        *,
        reason_code,
        reason_detail=None,
        notes=None,
    ):
        saved = (
            communication_call_service
            .save_post_call_details(
                event.call_id,
                reason_code=reason_code,
                reason_detail=(
                    reason_detail
                ),
                notes=notes,
            )
        )

        return {
            "ok": True,
            "call_id": saved.id,
            "reason_code":
                saved.reason_code,
            "reason_detail":
                saved.reason_detail,
            "notes":
                saved.notes,
        }


    global_call_ui = (
        GlobalCallUICoordinator(
            page=page,
            on_accept=(
                accept_global_call
            ),
            on_reject=(
                reject_global_call
            ),
            on_save_post_call=(
                save_global_post_call
            ),
            reason_options=(
                call_reason_options
            ),
        )
    )

    def on_whatsapp_call_watch_change(
        realtime_result,
    ):
        event = (
            call_ui_event_service
            .project_whatsapp_realtime_result(
                realtime_result
            )
        )

        if event is None:
            return False

        return (
            global_call_ui
            .handle_event(
                event
            )
        )

    call_ui_smoke_started = {
        "value": False,
    }

    post_call_ui_smoke_started = {
        "value": False,
    }

    # CALL-SYNC-10 · recuperación histórica única por sesión.
    #
    # Se envía al executor gobernado de WhatsApp y nunca usa
    # un thread/browser alternativo.
    call_history_startup_sync_started = {
        "value": False,
    }

    call_history_startup_sync_future = {
        "value": None,
    }

    # Runtime DEHú global y perezoso.
    #
    # Se construye con la sesión ERP pero NO abre Chrome
    # hasta que un caso de uso solicite realmente DEHú.
    dehu_runtime = DehuRuntimeService()

    dehu_runtime_closed = {
        "value": False,
    }

    def on_whatsapp_startup_history_done(
        future,
    ):
        """
        Observa únicamente el resultado del Future.

        Nunca toca browser, connector ni controles Flet.
        """
        try:
            result = future.result()

        except Exception as exc:
            print(
                "[WA-CALL-SYNC] recuperación histórica "
                "de inicio falló:",
                repr(
                    exc
                ),
                flush=True,
            )

            return False

        if result.get(
            "skipped"
        ):
            print(
                "[WA-CALL-SYNC] recuperación histórica "
                "omitida:",
                result.get(
                    "reason"
                ),
                flush=True,
            )

            return False

        history = (
            result.get(
                "history"
            )
            or {}
        )

        plan = (
            result.get(
                "plan"
            )
            or {}
        )

        execution = (
            result.get(
                "execution"
            )
            or {}
        )

        history_items = len(
            history.get(
                "items"
            )
            or []
        )

        plan_errors = len(
            plan.get(
                "errors"
            )
            or []
        )

        execution_errors = len(
            execution.get(
                "errors"
            )
            or []
        )

        print(
            "[WA-CALL-SYNC] recuperación histórica "
            "de inicio completada:",
            "items=",
            history_items,
            "planned=",
            plan.get(
                "planned"
            ),
            "reconciled=",
            execution.get(
                "reconciled"
            ),
            "errors=",
            (
                plan_errors
                + execution_errors
            ),
            flush=True,
        )

        return True


    def start_whatsapp_call_history_recovery():
        """
        Programa como máximo una recuperación histórica
        automática durante esta sesión ERP.

        La llamada es no bloqueante para Flet.
        """
        if whatsapp_runtime_closed[
            "value"
        ]:
            return False

        if call_history_startup_sync_started[
            "value"
        ]:
            return False

        try:
            future = (
                whatsapp_runtime
                .submit_call_history_sync(
                    wait_timeout=60,
                    navigation_timeout=5,
                    dry_run=False,
                )
            )

            future.add_done_callback(
                on_whatsapp_startup_history_done
            )

        except Exception as exc:
            print(
                "[WA-CALL-SYNC] no se pudo programar "
                "la recuperación histórica de inicio:",
                repr(
                    exc
                ),
                flush=True,
            )

            return False

        call_history_startup_sync_started[
            "value"
        ] = True

        call_history_startup_sync_future[
            "value"
        ] = future

        return True


    def start_whatsapp_session_services():
        """
        Activa servicios WhatsApp globales de la sesión ERP.

        Se llama únicamente después de autenticación correcta.
        start_call_watch() es no bloqueante: el navegador y
        cualquier espera de READY ocurren en background.
        """
        if whatsapp_runtime_closed[
            "value"
        ]:
            return False

        try:
            whatsapp_runtime.start_call_watch(
                interval_seconds=0.25,
                wait_timeout=5,
                on_change=(
                    on_whatsapp_call_watch_change
                ),
            )

            # Realtime queda activo primero.
            # Después se encola una única recuperación
            # histórica en el mismo worker gobernado.
            start_whatsapp_call_history_recovery()

            return True

        except Exception as exc:
            # WhatsApp nunca debe impedir entrar en el ERP.
            print(
                "[WA-CALL] no se pudo iniciar "
                "el watcher de sesión:",
                repr(
                    exc
                ),
                flush=True,
            )

            return False


    def close_whatsapp_session_services():
        """
        Cierre idempotente del runtime global WhatsApp.

        Se ejecuta desde el lifecycle explícito de Flet,
        antes de que Python comience a desmontar executors
        y otros recursos globales.
        """
        if whatsapp_runtime_closed[
            "value"
        ]:
            return False

        try:
            result = (
                whatsapp_runtime.close()
            )

            # El latch representa ausencia real de ownership,
            # no simplemente que se haya intentado cerrar.
            #
            # close() puede devolver False cuando nunca hubo
            # connector. Ese caso está igualmente cerrado.
            #
            # Si un shutdown falla conservando connector,
            # mantenemos el latch abierto para permitir retry.
            whatsapp_runtime_closed[
                "value"
            ] = (
                whatsapp_runtime.connector
                is None
            )

            return result

        except Exception as exc:
            # Un cierre excepcional no se declara definitivo.
            #
            # El Runtime puede conservar connector/browser/
            # executor precisamente para permitir otro intento.
            whatsapp_runtime_closed[
                "value"
            ] = False

            print(
                "[WA-CALL] error cerrando "
                "runtime de sesión:",
                repr(
                    exc
                ),
                flush=True,
            )

            return False


    def close_dehu_session_services():
        """
        Cierra DEHú únicamente si llegó a adquirir
        ownership de un connector.

        Un fallo conserva runtime/connector/worker para
        permitir un retry gobernado.
        """

        if dehu_runtime_closed[
            "value"
        ]:
            return False

        # Runtime lazy nunca utilizado:
        # no creamos un executor solo para cerrarlo.
        if dehu_runtime.connector is None:
            dehu_runtime_closed[
                "value"
            ] = True

            return False

        try:
            result = (
                dehu_runtime.close()
            )

            dehu_runtime_closed[
                "value"
            ] = (
                dehu_runtime.connector
                is None
            )

            return result

        except Exception as exc:
            dehu_runtime_closed[
                "value"
            ] = False

            print(
                "[DEHU] error cerrando "
                "runtime de sesión:",
                repr(
                    exc
                ),
                flush=True,
            )

            return False


    def on_page_close(
        e=None,
    ):
        """
        Cierra independientemente los runtimes globales.

        Un fallo en un provider nunca debe impedir
        intentar el shutdown gobernado del otro.
        """

        whatsapp_result = False
        dehu_result = False

        try:
            whatsapp_result = (
                close_whatsapp_session_services()
            )
        except Exception as exc:
            print(
                "[WA-CALL] error inesperado "
                "en cierre global:",
                repr(
                    exc
                ),
                flush=True,
            )

        try:
            dehu_result = (
                close_dehu_session_services()
            )
        except Exception as exc:
            print(
                "[DEHU] error inesperado "
                "en cierre global:",
                repr(
                    exc
                ),
                flush=True,
            )

        return bool(
            whatsapp_result
            or dehu_result
        )


    page.on_close = on_page_close


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
        previous_view = (
            active_view.get(
                "value"
            )
        )

        # El active-chat watcher pertenece a la sesión WhatsApp,
        # no a la vida visual de communications_view().
        #
        # Al abandonar WhatsApp:
        # - NO detenemos el watcher;
        # - NO cerramos browser/runtime;
        # - solo retiramos el consumidor Flet perteneciente
        #   a la vista que va a ser desmontada.
        if (
            previous_view
            == "WhatsApp"
            and view_name
            != "WhatsApp"
        ):
            try:
                whatsapp_runtime.set_active_chat_watch_callback(
                    None
                )

            except Exception as exc:
                print(
                    "[WA-FLET] view callback detach failed",
                    repr(exc),
                    flush=True,
                )

        # Se publica antes de construir la nueva vista.
        # De este modo cualquier tarea ya encolada de la vista
        # anterior se considera obsoleta inmediatamente.
        active_view[
            "value"
        ] = view_name

        if view_name == "Clientes":
            return_context = kwargs.get(
                "return_context"
            )

            new_client_source_thread_id = (
                kwargs.get(
                    "new_client_source_thread_id"
                )
            )

            def _after_whatsapp_client_created(
                client_id,
            ):
                if new_client_source_thread_id:
                    communication_service.link_whatsapp_thread_to_client(
                        int(
                            new_client_source_thread_id
                        ),
                        int(
                            client_id
                        ),
                    )

                    navigate(
                        "WhatsApp",
                        thread_id=int(
                            new_client_source_thread_id
                        ),
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
                new_client_defaults=kwargs.get(
                    "new_client_defaults"
                ),
                on_client_created=(
                    _after_whatsapp_client_created
                    if new_client_source_thread_id
                    else None
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
                on_open_dehu_portal=(
                    lambda url:
                        dehu_runtime.open_portal(
                            url
                        )
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
                service=(
                    communication_service
                ),
                whatsapp_runtime=(
                    whatsapp_runtime
                ),
                is_view_active=(
                    lambda:
                        active_view.get(
                            "value"
                        )
                        == "WhatsApp"
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
                on_create_cliente=(
                    lambda phone,
                    display_name,
                    thread_id,
                    return_context:
                        navigate(
                            "Clientes",
                            new_client_defaults={
                                "nombre": (
                                    display_name
                                    or ""
                                ),
                                "telefono": (
                                    phone
                                    or ""
                                ),
                            },
                            new_client_source_thread_id=(
                                thread_id
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
        elif view_name == "Llamadas":
            content = calls_view(
                page,
                call_service=(
                    communication_call_service
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

    async def run_global_call_ui_smoke():
        """
        Smoke exclusivamente visual.

        No persiste.
        No toca WhatsApp.
        No usa Selenium.
        """

        await asyncio.sleep(
            8
        )

        ringing = CallUIEvent(
            event_key=(
                "SMOKE:GLOBAL-CALL-1"
            ),
            channel="WHATSAPP",
            direction="INBOUND",
            status="RINGING",
            phone_number=(
                "+34639156371"
            ),
            display_name=(
                "JEAN PIERRY MUÑOZ VALDEZ"
            ),
            client_id=30,
            provider="WHATSAPP",
            provider_call_id=(
                "SMOKE-PROVIDER-1"
            ),
            external_call_key=(
                "SMOKE-EXTERNAL-1"
            ),
            # Nunca permitimos que el smoke sintético
            # ejecute acciones reales de provider.
            can_accept=False,
            can_reject=False,
            can_hangup=False,
            incoming_ringing=True,
            terminal=False,
            source=(
                "SYNTHETIC_UI_SMOKE"
            ),
        )

        print(
            "[CALL-UI-SMOKE] OPEN",
            flush=True,
        )

        page.run_thread(
            global_call_ui.handle_event,
            ringing,
        )

        # El evento entra ahora por la misma frontera
        # background -> Page.run_task que usará el watcher.
        await asyncio.sleep(
            0.5
        )

        print(
            "[CALL-UI-SMOKE] AFTER_OPEN:",
            global_call_ui.debug_state(),
            flush=True,
        )

        await asyncio.sleep(
            2
        )

        page.run_thread(
            global_call_ui.handle_event,
            ringing,
        )

        # El evento entra ahora por la misma frontera
        # background -> Page.run_task que usará el watcher.
        await asyncio.sleep(
            0.5
        )

        print(
            "[CALL-UI-SMOKE] AFTER_DUPLICATE:",
            global_call_ui.debug_state(),
            flush=True,
        )

        await asyncio.sleep(
            8
        )

        terminal = CallUIEvent(
            event_key=(
                ringing.event_key
            ),
            channel=(
                ringing.channel
            ),
            direction=(
                ringing.direction
            ),
            status="MISSED",
            phone_number=(
                ringing.phone_number
            ),
            display_name=(
                ringing.display_name
            ),
            client_id=(
                ringing.client_id
            ),
            provider=(
                ringing.provider
            ),
            provider_call_id=(
                ringing.provider_call_id
            ),
            external_call_key=(
                ringing.external_call_key
            ),
            incoming_ringing=False,
            terminal=True,
            source=(
                "SYNTHETIC_UI_SMOKE"
            ),
        )

        print(
            "[CALL-UI-SMOKE] TERMINAL",
            flush=True,
        )

        page.run_thread(
            global_call_ui.handle_event,
            terminal,
        )

        await asyncio.sleep(
            0.5
        )

        print(
            "[CALL-UI-SMOKE] AFTER_TERMINAL:",
            global_call_ui.debug_state(),
            flush=True,
        )


    def maybe_start_global_call_ui_smoke():
        enabled = str(
            os.getenv(
                "QUESADA_CALL_UI_SMOKE",
                "",
            )
            or ""
        ).strip().lower()

        if enabled not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return False

        if call_ui_smoke_started[
            "value"
        ]:
            return False

        call_ui_smoke_started[
            "value"
        ] = True

        page.run_task(
            run_global_call_ui_smoke
        )

        return True


    async def run_post_call_ui_smoke():
        """
        Smoke visual seguro del formulario post-llamada.

        Garantías:
        - no crea CommunicationCall;
        - no persiste;
        - no toca Selenium;
        - no toca WhatsApp;
        - call_id=None mantiene Guardar deshabilitado;
        - entra por la misma frontera background -> run_task
          que utilizará un evento realtime productivo.
        """

        await asyncio.sleep(
            8
        )

        ended = CallUIEvent(
            event_key=(
                "SMOKE:POST-CALL-1"
            ),

            # Sin identidad DB deliberadamente.
            # El smoke jamás podrá ejecutar Guardar.
            call_id=None,

            channel="WHATSAPP",
            direction="INBOUND",
            status="ENDED",

            phone_number=(
                "+34639156371"
            ),

            display_name=(
                "JEAN PIERRY MUÑOZ VALDEZ"
            ),

            client_id=30,

            provider="WHATSAPP",

            provider_call_id=(
                "SMOKE-POST-PROVIDER-1"
            ),

            external_call_key=(
                "SMOKE-POST-EXTERNAL-1"
            ),

            incoming_ringing=False,
            terminal=True,

            post_call_required=True,

            # Verificamos también prefill real
            # mediante los códigos del catálogo backend.
            reason_code=(
                "LEGAL_CONSULTATION"
            ),

            reason_detail=(
                "Consulta sobre renovación"
            ),

            notes=(
                "Prueba visual del formulario "
                "post-llamada."
            ),

            source=(
                "SYNTHETIC_POST_CALL_UI_SMOKE"
            ),
        )

        print(
            "[POST-CALL-UI-SMOKE] OPEN",
            flush=True,
        )

        print(
            "[POST-CALL-UI-SMOKE] "
            "REASON_OPTIONS_COUNT:",
            len(
                call_reason_options
            ),
            flush=True,
        )

        print(
            "[POST-CALL-UI-SMOKE] "
            "NO_DB_WRITE: True",
            flush=True,
        )

        # Simula exactamente una entrada procedente
        # de background/watcher.
        page.run_thread(
            global_call_ui.handle_event,
            ended,
        )

        await asyncio.sleep(
            0.5
        )

        print(
            "[POST-CALL-UI-SMOKE] AFTER_OPEN:",
            global_call_ui.debug_state(),
            flush=True,
        )

        save_button = (
            global_call_ui
            ._post_call_save_button
        )

        reason_control = (
            global_call_ui
            ._post_call_reason
        )

        detail_control = (
            global_call_ui
            ._post_call_reason_detail
        )

        notes_control = (
            global_call_ui
            ._post_call_notes
        )

        print(
            "[POST-CALL-UI-SMOKE] FORM_STATE:",
            {
                "save_disabled":
                    (
                        getattr(
                            save_button,
                            "disabled",
                            None,
                        )
                    ),
                "reason":
                    (
                        getattr(
                            reason_control,
                            "value",
                            None,
                        )
                    ),
                "reason_detail":
                    (
                        getattr(
                            detail_control,
                            "value",
                            None,
                        )
                    ),
                "notes":
                    (
                        getattr(
                            notes_control,
                            "value",
                            None,
                        )
                    ),
            },
            flush=True,
        )

        # Tiempo suficiente para abrir el desplegable
        # y revisar visualmente el formulario.
        await asyncio.sleep(
            15
        )

        print(
            "[POST-CALL-UI-SMOKE] AUTO_OMIT",
            flush=True,
        )

        # Estamos dentro de page.run_task:
        # la mutación Flet sigue ocurriendo en su contexto.
        global_call_ui._on_post_call_skip_click()

        await asyncio.sleep(
            0.25
        )

        print(
            "[POST-CALL-UI-SMOKE] AFTER_OMIT:",
            global_call_ui.debug_state(),
            flush=True,
        )


    def maybe_start_post_call_ui_smoke():
        enabled = str(
            os.getenv(
                "QUESADA_POST_CALL_UI_SMOKE",
                "",
            )
            or ""
        ).strip().lower()

        if enabled not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return False

        if post_call_ui_smoke_started[
            "value"
        ]:
            return False

        post_call_ui_smoke_started[
            "value"
        ] = True

        page.run_task(
            run_post_call_ui_smoke
        )

        return True


    def on_login_success(user):
        current_user["value"] = user

        # La UI autenticada se muestra primero.
        #
        # WhatsApp arranca después en background para que
        # un QR, un timeout o cualquier indisponibilidad
        # del provider nunca bloquee el acceso al ERP.
        navigate("Clientes")

        start_whatsapp_session_services()

        maybe_start_global_call_ui_smoke()

        maybe_start_post_call_ui_smoke()

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
