import asyncio
import os
from datetime import (
    datetime,
    timedelta,
)
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
from backend.services.icpplus_availability_service import (
    IcpPlusAvailabilityService,
)
from backend.qcc.bridge.server import (
    QccBridgeServer,
)
from backend.services import (
    icpplus_scheduler_service,
    icpplus_ui_presence_service,
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
from frontend.views.icpplus_view import icpplus_view
from frontend.layouts.main_layout import main_layout
from frontend.layouts.sidebar import sidebar_menu
from frontend.components.global_call_ui_coordinator import (
    GlobalCallUICoordinator,
)


async def main(page: ft.Page):
    page.title = "Quesada Abogados ERP"

    # Arranque nativo oculto.
    # Se maximiza antes del primer frame visible.
    page.window.visible = False
    page.window.full_screen = False
    page.window.minimized = False
    page.window.maximized = True
    page.window.min_width = 1200
    page.window.min_height = 750
    page.window.resizable = True
    page.window.minimizable = True
    page.window.maximizable = True

    configure_sqlite_runtime()
    initialize_database()
    configure_sqlite_runtime()

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

    # ICP Plus es una automatización one-shot.
    #
    # La vista únicamente consume este servicio de aplicación;
    # no conoce Chrome, Observer, Win32 ni el connector.
    icpplus_service = (
        IcpPlusAvailabilityService()
    )

    # ========================================================
    # ICP PLUS · AVISO GLOBAL T-60
    # ========================================================

    icpplus_ui_instance_id = (
        f"ERP-{os.getpid()}"
    )

    icpplus_warning_watch_started = {
        "value":
            False,
    }

    icpplus_warning_watch_shutdown = {
        "value":
            False,
    }

    icpplus_warning_current = {
        "event_id":
            None,
    }

    icpplus_warning_title = ft.Text(
        "Próxima comprobación ICP Plus",
        size=21,
        weight=ft.FontWeight.BOLD,
        color="#003B7A",
    )

    icpplus_warning_province = ft.Text(
        "—",
        size=13,
        weight=ft.FontWeight.BOLD,
        color="#172B4D",
    )

    icpplus_warning_procedure = ft.Text(
        "—",
        size=13,
        color="#172B4D",
    )

    icpplus_warning_office = ft.Text(
        "—",
        size=13,
        color="#66788A",
    )

    icpplus_warning_countdown = ft.Text(
        "00:59",
        size=34,
        weight=ft.FontWeight.BOLD,
        color="#0057B8",
    )

    icpplus_warning_message = ft.Text(
        "",
        size=11,
        color="#B42318",
        visible=False,
    )


    def close_icpplus_warning_dialog():
        icpplus_warning_dialog.open = False

        icpplus_warning_current[
            "event_id"
        ] = None

        try:
            page.update()
        except Exception:
            pass


    def on_icpplus_warning_skip(
        e=None,
    ):
        event_id = (
            icpplus_warning_current.get(
                "event_id"
            )
        )

        if not event_id:
            return

        if event_id.startswith(
            "ICPPLUS-WARNING-SMOKE-"
        ):
            print(
                "[ICPPLUS-SCHEDULER-UI] "
                "SMOKE_ACTION_ONLY",
                event_id,
                flush=True,
            )

            close_icpplus_warning_dialog()
            return

        try:
            icpplus_scheduler_service.handle_warning_action(
                event_id,
                action="SKIP",
            )

            print(
                "[ICPPLUS-SCHEDULER-UI] "
                "WARNING_ACTION=SKIP",
                event_id,
                flush=True,
            )

            close_icpplus_warning_dialog()

        except Exception as exc:
            icpplus_warning_message.value = str(
                exc
            )

            icpplus_warning_message.visible = (
                True
            )

            page.update()


    def on_icpplus_warning_stop(
        e=None,
    ):
        event_id = (
            icpplus_warning_current.get(
                "event_id"
            )
        )

        if not event_id:
            return

        if event_id.startswith(
            "ICPPLUS-WARNING-SMOKE-"
        ):
            print(
                "[ICPPLUS-SCHEDULER-UI] "
                "SMOKE_ACTION_ONLY",
                event_id,
                flush=True,
            )

            close_icpplus_warning_dialog()
            return

        try:
            icpplus_scheduler_service.handle_warning_action(
                event_id,
                action="STOP",
            )

            print(
                "[ICPPLUS-SCHEDULER-UI] "
                "WARNING_ACTION=STOP",
                event_id,
                flush=True,
            )

            close_icpplus_warning_dialog()

        except Exception as exc:
            icpplus_warning_message.value = str(
                exc
            )

            icpplus_warning_message.visible = (
                True
            )

            page.update()


    icpplus_warning_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            [
                ft.Icon(
                    ft.Icons.SCHEDULE,
                    color="#0057B8",
                    size=24,
                ),

                icpplus_warning_title,
            ],
            spacing=9,
        ),

        content=ft.Container(
            width=520,
            content=ft.Column(
                [
                    ft.Container(
                        padding=14,
                        bgcolor="#EAF3FF",
                        border_radius=10,
                        content=ft.Column(
                            [
                                icpplus_warning_province,
                                icpplus_warning_procedure,
                                icpplus_warning_office,
                            ],
                            spacing=5,
                        ),
                    ),

                    ft.Container(
                        padding=18,
                        alignment=ft.Alignment(
                            0,
                            0,
                        ),
                        content=ft.Column(
                            [
                                ft.Text(
                                    (
                                        "La comprobación comenzará "
                                        "automáticamente en"
                                    ),
                                    size=12,
                                    color="#66788A",
                                    text_align=(
                                        ft.TextAlign.CENTER
                                    ),
                                ),

                                icpplus_warning_countdown,

                                ft.Text(
                                    (
                                        "Se respetará el descanso "
                                        "global mínimo de 15 minutos."
                                    ),
                                    size=11,
                                    color="#66788A",
                                    text_align=(
                                        ft.TextAlign.CENTER
                                    ),
                                ),
                            ],
                            horizontal_alignment=(
                                ft.CrossAxisAlignment.CENTER
                            ),
                            spacing=7,
                        ),
                    ),

                    icpplus_warning_message,
                ],
                spacing=10,
                tight=True,
            ),
        ),

        actions=[
            ft.OutlinedButton(
                "Omitir este intento",
                on_click=(
                    on_icpplus_warning_skip
                ),
            ),

            ft.ElevatedButton(
                "Detener vigilancia",
                bgcolor="#B42318",
                color="#FFFFFF",
                on_click=(
                    on_icpplus_warning_stop
                ),
            ),
        ],

        actions_alignment=(
            ft.MainAxisAlignment.END
        ),
    )


    def open_icpplus_warning_dialog(
        event,
    ):
        event = dict(
            event
            or {}
        )

        event_id = str(
            event.get(
                "event_id"
            )
            or ""
        )

        if not event_id:
            return False

        icpplus_warning_current[
            "event_id"
        ] = event_id

        province = str(
            event.get(
                "province_key"
            )
            or "ICP Plus"
        ).replace(
            "_",
            " ",
        ).title()

        icpplus_warning_province.value = (
            province
        )

        icpplus_warning_procedure.value = str(
            event.get(
                "procedure_text"
            )
            or event.get(
                "procedure_key"
            )
            or "Trámite ICP Plus"
        )

        icpplus_warning_office.value = str(
            event.get(
                "office_text"
            )
            or event.get(
                "office_key"
            )
            or "Oficina ICP Plus"
        )

        icpplus_warning_message.visible = (
            False
        )

        if (
            icpplus_warning_dialog
            not in page.overlay
        ):
            page.overlay.append(
                icpplus_warning_dialog
            )

        icpplus_warning_dialog.open = True

        page.update()

        return True


    async def run_icpplus_warning_watch():
        """
        Proyección global del warning persistido por
        icpplus_scheduler_worker.py.

        No ejecuta el bot.
        No controla Chrome.
        No altera el cooldown.
        """

        while (
            not icpplus_warning_watch_shutdown[
                "value"
            ]
        ):
            try:
                try:
                    icpplus_ui_presence_service.mark_alive(
                        icpplus_ui_instance_id
                    )

                except Exception as heartbeat_exc:
                    # Un conflicto temporal del heartbeat nunca
                    # puede impedir proyectar un warning ya
                    # persistido por el worker.
                    print(
                        "[ICPPLUS-SCHEDULER-UI] "
                        "heartbeat error:",
                        repr(
                            heartbeat_exc
                        ),
                        flush=True,
                    )

                event = (
                    icpplus_scheduler_service
                    .get_last_warning_event()
                )

                if isinstance(
                    event,
                    dict,
                ):
                    status = str(
                        event.get(
                            "status"
                        )
                        or "PENDING"
                    ).upper()

                    event_id = str(
                        event.get(
                            "event_id"
                        )
                        or ""
                    )

                    if (
                        status == "PENDING"
                        and event_id
                    ):
                        if (
                            icpplus_warning_current[
                                "event_id"
                            ]
                            != event_id
                        ):
                            open_icpplus_warning_dialog(
                                event
                            )

                        effective_raw = (
                            event.get(
                                "effective_run_at"
                            )
                        )

                        if effective_raw:
                            effective = (
                                datetime.fromisoformat(
                                    str(
                                        effective_raw
                                    )
                                )
                            )

                            now = (
                                datetime.now()
                                .astimezone()
                            )

                            remaining = max(
                                0,
                                int(
                                    (
                                        effective
                                        - now
                                    ).total_seconds()
                                ),
                            )

                            minutes, seconds = divmod(
                                remaining,
                                60,
                            )

                            icpplus_warning_countdown.value = (
                                f"{minutes:02d}:"
                                f"{seconds:02d}"
                            )

                            if (
                                icpplus_warning_dialog.open
                            ):
                                page.update()

                    elif (
                        icpplus_warning_dialog.open
                        and icpplus_warning_current[
                            "event_id"
                        ]
                        == event_id
                    ):
                        close_icpplus_warning_dialog()

            except Exception as exc:
                print(
                    "[ICPPLUS-SCHEDULER-UI] "
                    "warning watch error:",
                    repr(
                        exc
                    ),
                    flush=True,
                )

            await asyncio.sleep(
                1
            )


    def start_icpplus_warning_watch():
        if icpplus_warning_watch_started[
            "value"
        ]:
            return False

        icpplus_warning_watch_started[
            "value"
        ] = True

        icpplus_warning_watch_shutdown[
            "value"
        ] = False

        page.run_task(
            run_icpplus_warning_watch
        )

        return True

    # ========================================================
    # ICP PLUS · SMOKE VISUAL AVISO GLOBAL
    # ========================================================

    icpplus_warning_ui_smoke_started = {
        "value":
            False,
    }


    async def run_icpplus_warning_ui_smoke():
        """
        Smoke exclusivamente visual.

        No crea scheduler.
        No escribe en config_service.
        No ejecuta ICP Plus.
        No abre Chrome.
        """

        await asyncio.sleep(
            2
        )

        effective_run_at = (
            datetime.now()
            .astimezone()
            + timedelta(
                seconds=60
            )
        )

        event = {
            "event_id":
                "ICPPLUS-WARNING-SMOKE-001",

            "scheduler_id":
                "ICPPLUS-SMOKE-001",

            "province_key":
                "ASTURIAS",

            "procedure_key":
                "POLICIA_TOMA_HUELLAS_TIE",

            "procedure_text":
                "Policía · Toma de huellas TIE",

            "office_key":
                "CNP_OVIEDO",

            "office_text":
                (
                    "CNP OVIEDO - EXPEDICION TIE, "
                    "Plaza de España, 3"
                ),

            "effective_run_at":
                effective_run_at.isoformat(
                    timespec="seconds"
                ),

            "status":
                "PENDING",
        }

        print(
            "[ICPPLUS-WARNING-SMOKE] OPEN",
            flush=True,
        )

        open_icpplus_warning_dialog(
            event
        )

        # Dejamos el diálogo visible 20 segundos
        # actualizando el countdown.
        for _ in range(
            20
        ):
            if (
                not icpplus_warning_dialog.open
            ):
                return

            remaining = max(
                0,
                int(
                    (
                        effective_run_at
                        - datetime.now()
                        .astimezone()
                    ).total_seconds()
                ),
            )

            minutes, seconds = divmod(
                remaining,
                60,
            )

            icpplus_warning_countdown.value = (
                f"{minutes:02d}:"
                f"{seconds:02d}"
            )

            page.update()

            await asyncio.sleep(
                1
            )

        if (
            icpplus_warning_dialog.open
        ):
            close_icpplus_warning_dialog()

        print(
            "[ICPPLUS-WARNING-SMOKE] COMPLETE",
            flush=True,
        )


    def maybe_start_icpplus_warning_ui_smoke():
        enabled = str(
            os.getenv(
                "QUESADA_ICPPLUS_WARNING_UI_SMOKE",
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

        if (
            icpplus_warning_ui_smoke_started[
                "value"
            ]
        ):
            return False

        icpplus_warning_ui_smoke_started[
            "value"
        ] = True

        page.run_task(
            run_icpplus_warning_ui_smoke
        )

        return True


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

    # QCC Bridge pertenece al lifecycle global del ERP.
    #
    # No pertenece a Mercurio, SeleniumBase ni a una vista Flet.
    # Debe estar disponible antes de que cualquier presentación
    # asistida publique su primera sesión.
    #
    # El owner se conserva explícitamente para garantizar:
    # - un único Bridge por sesión ERP;
    # - cierre gobernado;
    # - retry posible si un shutdown excepcional falla.
    qcc_bridge_owner = {
        "server": None,
    }


    def start_qcc_bridge_session_services():
        """Inicia QCC Bridge sin bloquear el arranque del ERP."""

        current = qcc_bridge_owner[
            "server"
        ]

        if (
            current is not None
            and current.is_running
        ):
            return True

        server = None

        try:
            server = QccBridgeServer()

            server.start()

            if not server.is_running:
                raise RuntimeError(
                    "QCC_BRIDGE_START_FAILED"
                )

            qcc_bridge_owner[
                "server"
            ] = server

            print(
                "[QCC-BRIDGE] ERP lifecycle listening",
                (
                    f"http://{server.host}:"
                    f"{server.port}"
                ),
                flush=True,
            )

            return True

        except Exception as exc:
            # QCC es una capa auxiliar/contextual.
            # Su indisponibilidad no debe impedir utilizar
            # el resto del ERP.
            if server is not None:
                try:
                    server.close()
                except Exception:
                    pass

            qcc_bridge_owner[
                "server"
            ] = None

            print(
                "[QCC-BRIDGE] no se pudo iniciar:",
                repr(exc),
                flush=True,
            )

            return False


    def close_qcc_bridge_session_services():
        """Cierre idempotente del Bridge propiedad del ERP."""

        server = qcc_bridge_owner[
            "server"
        ]

        if server is None:
            return False

        try:
            was_running = bool(
                server.is_running
            )

            server.close()

            qcc_bridge_owner[
                "server"
            ] = None

            print(
                "[QCC-BRIDGE] ERP lifecycle closed",
                flush=True,
            )

            return was_running

        except Exception as exc:
            # Conservamos ownership para permitir retry.
            print(
                "[QCC-BRIDGE] error cerrando "
                "Bridge de sesión:",
                repr(exc),
                flush=True,
            )

            return False


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


    def close_icpplus_session_services():
        """
        Libera cualquier recurso ICP Plus pendiente.

        El runtime es one-shot e idempotente:
        - si nunca se utilizó, no crea worker;
        - si ya fue cerrado por la vista, no hace trabajo;
        - si queda algún recurso, lo libera.
        """

        try:
            return bool(
                icpplus_service.close()
            )

        except Exception as exc:
            print(
                "[ICPPLUS] error cerrando "
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
        icpplus_warning_watch_shutdown[
            "value"
        ] = True

        try:
            icpplus_ui_presence_service.clear(
                icpplus_ui_instance_id
            )
        except Exception:
            pass

        """
        Cierra independientemente los runtimes globales.

        Un fallo en un provider nunca debe impedir
        intentar el shutdown gobernado del otro.
        """

        whatsapp_result = False
        dehu_result = False
        icpplus_result = False
        qcc_result = False

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

        try:
            icpplus_result = (
                close_icpplus_session_services()
            )
        except Exception as exc:
            print(
                "[ICPPLUS] error inesperado "
                "en cierre global:",
                repr(
                    exc
                ),
                flush=True,
            )

        # QCC se cierra el último.
        #
        # De esta forma cualquier runtime que emita un
        # último estado durante su shutdown todavía puede
        # utilizar el Bridge.
        try:
            qcc_result = (
                close_qcc_bridge_session_services()
            )
        except Exception as exc:
            print(
                "[QCC-BRIDGE] error inesperado "
                "en cierre global:",
                repr(
                    exc
                ),
                flush=True,
            )

        return bool(
            whatsapp_result
            or dehu_result
            or icpplus_result
            or qcc_result
        )


    page.on_close = on_page_close

    # El handler de cierre queda instalado ANTES de adquirir
    # ownership del Bridge.
    #
    # QCC debe existir desde el arranque del ERP y no únicamente
    # cuando se inicia una presentación.
    start_qcc_bridge_session_services()


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

            def _after_client_phone_changed(
                client_id,
                previous_phone,
                new_phone,
                display_name,
            ):
                prepared = (
                    communication_service
                    .prepare_whatsapp_thread_for_client_phone_change(
                        int(
                            client_id
                        ),
                        new_phone,
                        display_name=(
                            display_name
                            or new_phone
                        ),
                    )
                )

                thread = (
                    prepared.get(
                        "thread"
                    )
                )

                if thread is None:
                    raise RuntimeError(
                        "No se pudo preparar "
                        "la conversación WhatsApp"
                    )

                normalized_phone = str(
                    prepared.get(
                        "phone"
                    )
                    or new_phone
                    or ""
                ).strip()

                whatsapp_runtime.add_contact_and_open(
                    normalized_phone,
                    display_name=(
                        display_name
                        or normalized_phone
                    ),
                    wait_timeout=60,
                    routing_timeout=20,
                )

                communication_service.update_whatsapp_thread_display_name(
                    int(
                        thread.id
                    ),
                    (
                        display_name
                        or normalized_phone
                    ),
                )

                return {
                    "thread_id":
                        int(
                            thread.id
                        ),
                    "phone":
                        normalized_phone,
                    "previous_phone":
                        previous_phone,
                }


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
                on_client_phone_changed=(
                    _after_client_phone_changed
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
        elif view_name == "Citas ICP Plus":
            content = icpplus_view(
                page,
                service=icpplus_service,
            )

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

        start_icpplus_warning_watch()

        maybe_start_icpplus_warning_ui_smoke()

        start_whatsapp_session_services()

        maybe_start_global_call_ui_smoke()

        maybe_start_post_call_ui_smoke()

    def start():
        main_container.content = login_view(page, on_login_success=on_login_success)
        page.update()

    page.add(main_container)

    # Construimos el login mientras la ventana sigue oculta.
    start()

    # Aplicamos el estado final antes de mostrarla.
    page.window.full_screen = False
    page.window.minimized = False
    page.window.maximized = True
    page.update()

    await page.window.wait_until_ready_to_show()

    # Primer frame visible: ya maximizado.
    page.window.visible = True
    page.window.focused = True
    page.update()


ft.run(
    main,
    view=ft.AppView.FLET_APP_HIDDEN,
)
