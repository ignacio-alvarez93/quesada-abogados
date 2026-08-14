import asyncio
import time
import math

import flet as ft

from backend.services.communication_service import (
    CommunicationService,
)
from frontend.components.app_autocomplete import (
    AppAutocomplete,
)
from frontend.components.app_button import (
    primary_button,
    secondary_button,
)
from frontend.components.app_card import (
    metric_card,
)
from frontend.components.app_empty_state import (
    empty_state,
)


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#D8E2EE"
Q_MUTED = "#64748B"
Q_TEXT = "#0F172A"
Q_BG = "#F6F8FC"
Q_WHITE = "#FFFFFF"

LINKED_BG = "#ECFDF3"
LINKED_FG = "#027A48"

UNLINKED_BG = "#FFF7E6"
UNLINKED_FG = "#B54708"

SELECTED_BG = "#EAF3FF"


CHANNEL_FILTER_VALUES = {
    "WhatsApp": "WHATSAPP",
}

LINKAGE_FILTER_VALUES = {
    "Todas": "ALL",
    "Vinculadas": "LINKED",
    "Sin vincular": "UNLINKED",
}


def communications_view(
    page: ft.Page,
    *,
    service=None,
    whatsapp_runtime=None,
    current_username=None,
    initial_thread_id=None,
    on_open_cliente=None,
    on_open_expediente=None,
    on_create_expediente=None,
    on_create_task=None,
    on_create_alert=None,
):
    """
    Vista principal de Comunicaciones.

    Reglas arquitectónicas:
    - no contiene SQL;
    - no conoce SQLite;
    - no importa repositories concretos;
    - consume servicios backend inyectables;
    - no construye ni controla WhatsAppConnector.

    `service` es inyectable para mantener la vista
    desacoplada del backend físico y facilitar
    PostgreSQL / Supabase en el futuro.
    """
    communication_service = (
        service
        or CommunicationService()
    )

    state = {
        "summary": {},
        "items": [],
        "selected_thread_id": (
            int(initial_thread_id)
            if initial_thread_id
            else None
        ),
        "context": None,
        "context_error": None,
        "messages": [],
        "messages_error": None,

        # COM-8FA4G · La UI abre únicamente la ventana reciente.
        # El histórico completo permanece persistido en backend.
        "message_history_window_size": 50,
        "message_history_page_size": 50,

        # Estado de navegación histórica.
        "message_history_loading_older": False,
        "message_history_has_more": True,
        "message_history_expanded": False,

        # Un scroll_to() propio también dispara on_scroll.
        # Mientras esté activo no puede solicitar otra página.
        "message_history_programmatic_scroll": False,

        # La carga histórica superior comienza desarmada.
        #
        # Flet puede emitir on_scroll con extent_before == 0
        # durante el montaje inicial. Ese evento no representa
        # intención del usuario y nunca debe cargar otra página.
        "message_history_top_load_armed": False,

        # Antes de permitir armar la paginación superior
        # debemos haber observado el historial correctamente
        # situado en el fondo al menos una vez.
        #
        # Flet puede emitir eventos intermedios durante el
        # montaje; esos eventos no representan scroll humano.
        "message_history_scroll_initialized": False,

        # Después de prepend histórico no permitimos rearmar
        # inmediatamente otra página con eventos residuales
        # del scroll_to(anchor).
        #
        # El usuario deberá alejarse de forma clara del borde
        # superior antes de que pueda solicitar otra página.
        "message_history_top_rearm_required": False,

        # Evidencia semántica de una interacción humana real.
        #
        # Flet 0.84 expone ScrollType.USER + direction.
        # Los UPDATE producidos por relayout/scroll_to no pueden
        # habilitar paginación sin una señal USER previa.
        "message_history_user_scroll_active": False,

        # Última geometría real comunicada por Flet.
        #
        # Se utiliza para preservar exactamente el viewport
        # cuando se insertan mensajes históricos por arriba.
        "message_history_last_scroll_pixels": None,
        "message_history_last_max_scroll_extent": None,

        # Restauración geométrica pendiente después de prepend.
        #
        # No esperamos bloqueando a Flutter. El siguiente evento
        # que comunique un max_scroll_extent mayor aplicará el
        # offset compensatorio exacto.
        "message_history_pending_viewport_preserve": None,

        # True mientras el usuario está siguiendo el final.
        # Si sube a leer histórico, los mensajes realtime se
        # incorporan sin robarle la posición.
        "message_history_follow_bottom": True,

        "sending": False,
        "send_blocked_thread_ids": set(),

        # Routing WhatsApp actualmente solicitado desde CRM.
        #
        # Permite distinguir un evento realmente inactivo
        # de un callback obsoleto perteneciente a una selección
        # anterior mientras el usuario navega rápidamente.
        "routing_target_thread_id": None,
        "routing_generation": 0,

        # COM-8FA3 · estado efímero observado directamente
        # desde el sidebar de WhatsApp Web.
        #
        # No sustituye SQLite ni el modelo persistido.
        # Permite adelantar visualmente:
        # - preview;
        # - hora;
        # - no leídos;
        # - orden reciente.
        "whatsapp_sidebar_realtime": {},

        # Resoluciones inequívocas identity → thread_id.
        "whatsapp_sidebar_identity_cache": {},

        # Resoluciones negativas efímeras.
        #
        # Evita repetir cada tick búsquedas backend de una
        # identidad que acabamos de demostrar que no puede
        # resolverse de forma inequívoca.
        #
        # Se guarda identity → monotonic expiry.
        "whatsapp_sidebar_identity_negative_cache": {},

        # Si el usuario está cambiando activamente de chat,
        # los deltas laterales se pueden absorber en memoria
        # pero su render visual se pospone hasta terminar
        # el routing solicitado.
        "whatsapp_sidebar_render_pending": False,

        "search": "",
        "linkage": "ALL",
        "page": 1,
        "page_size": 20,
        "error": None,
    }

    content_area = ft.Container(
        expand=True,
    )

    search_input = ft.TextField(
        hint_text=(
            "Buscar conversación / teléfono / cliente"
        ),
        prefix_icon=ft.Icons.SEARCH,
        border_radius=10,
        border_color="#CBD5E1",
        focused_border_color=Q_PRIMARY,
        content_padding=ft.padding.symmetric(
            horizontal=14,
            vertical=10,
        ),
        expand=True,
    )

    channel_filter = AppAutocomplete(
        page=page,
        label="Canal",
        options=list(
            CHANNEL_FILTER_VALUES.keys()
        ),
        value="WhatsApp",
        width=175,
        max_results=4,
        allow_free_text=False,
        show_empty=False,
        icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
    )

    linkage_filter = AppAutocomplete(
        page=page,
        label="Vinculación",
        options=list(
            LINKAGE_FILTER_VALUES.keys()
        ),
        value="Todas",
        width=205,
        max_results=4,
        allow_free_text=False,
        show_empty=False,
        icon=ft.Icons.LINK,
    )

    def selected_channel():
        label = str(
            channel_filter.input.value
            or "WhatsApp"
        ).strip()

        return (
            CHANNEL_FILTER_VALUES.get(
                label,
                "WHATSAPP",
            )
        )

    def selected_linkage():
        label = str(
            linkage_filter.input.value
            or "Todas"
        ).strip()

        return (
            LINKAGE_FILTER_VALUES.get(
                label,
                "ALL",
            )
        )

    def _show_message(
        message,
        *,
        error=False,
    ):
        page.snack_bar = ft.SnackBar(
            content=ft.Text(
                str(message),
            ),
            bgcolor=(
                "#FEE4E2"
                if error
                else "#ECFDF3"
            ),
        )

        page.snack_bar.open = True

        try:
            page.update()
        except Exception:
            pass

    def _safe_update():
        try:
            # Full refresh explícito: sincronizar también
            # el contenido de los hosts persistentes antes
            # de reconstruir el shell completo.
            try:
                chat_panel_control.content = (
                    build_chat_panel()
                )
                context_panel_control.content = (
                    build_context_panel()
                )
            except NameError:
                pass

            content_area.content = (
                build_content()
            )

            page.update()

            # Invariante UX WhatsApp:
            # cualquier reconstrucción de la vista que
            # contenga mensajes termina mostrando siempre
            # el mensaje más reciente.
            try:
                _force_message_history_bottom()
            except NameError:
                # Durante la construcción inicial el helper
                # todavía podría no estar definido.
                pass

        except Exception as exc:
            state["error"] = str(exc)

            content_area.content = (
                build_error_content(
                    str(exc)
                )
            )

            try:
                page.update()
            except Exception:
                pass

    def _display_name(item):
        return (
            item.client_name
            or item.external_display_name
            or item.external_address
            or "Conversación sin nombre"
        )

    def _thread_realtime_sidebar_state(
        item,
    ):
        try:
            thread_id = int(
                item.thread_id
            )
        except Exception:
            return {}

        value = (
            state.get(
                "whatsapp_sidebar_realtime"
            )
            or {}
        ).get(
            thread_id
        )

        if not isinstance(
            value,
            dict,
        ):
            return {}

        return value


    def _realtime_unread_badge(
        unread_count,
    ):
        try:
            value = max(
                0,
                int(
                    unread_count
                    or 0
                ),
            )
        except Exception:
            value = 0

        if value <= 0:
            return ft.Container(
                width=0,
                height=0,
            )

        badge_text = (
            "99+"
            if value > 99
            else str(
                value
            )
        )

        return ft.Container(
            width=(
                28
                if value > 99
                else 20
            ),
            height=20,
            bgcolor="#12B76A",
            border_radius=999,
            alignment=ft.Alignment(
                0,
                0,
            ),
            content=ft.Text(
                badge_text,
                size=9,
                weight=ft.FontWeight.BOLD,
                color=Q_WHITE,
                text_align=ft.TextAlign.CENTER,
            ),
        )


    def _mark_realtime_thread_read(
        thread_id,
        *,
        refresh_sidebar=True,
    ):
        """Limpia el badge efímero de un thread ya atendido.

        No modifica persistencia CRM.
        WhatsApp continúa siendo la fuente de verdad y un
        evento posterior puede volver a incrementar unread.
        """
        if thread_id in (
            None,
            "",
        ):
            return False

        thread_id = int(
            thread_id
        )

        realtime = state.setdefault(
            "whatsapp_sidebar_realtime",
            {},
        )

        current = realtime.get(
            thread_id
        )

        if not isinstance(
            current,
            dict,
        ):
            return False

        previous_unread = max(
            0,
            int(
                current.get(
                    "unread_count"
                )
                or 0
            ),
        )

        if previous_unread <= 0:
            return False

        updated = dict(
            current
        )

        updated[
            "unread_count"
        ] = 0

        realtime[
            thread_id
        ] = updated


        if (
            refresh_sidebar
            and not state.get(
                "routing_target_thread_id"
            )
        ):
            try:
                _refresh_conversation_list_control()
            except NameError:
                pass

        return True


    def _flush_pending_whatsapp_sidebar():
        """Renderiza deltas absorbidos durante routing."""
        if not state.get(
            "whatsapp_sidebar_render_pending"
        ):
            return False

        state[
            "whatsapp_sidebar_render_pending"
        ] = False

        try:
            return bool(
                _refresh_conversation_list_control()
            )
        except NameError:
            return False


    def _secondary_name(item):
        if (
            item.client_name
            and item.external_display_name
            and (
                item.client_name
                != item.external_display_name
            )
        ):
            return (
                item.external_display_name
            )

        return ""

    def _is_linked(item):
        return (
            item.client_id
            is not None
        )

    def _status_badge(item):
        linked = _is_linked(
            item
        )

        return ft.Container(
            bgcolor=(
                LINKED_BG
                if linked
                else UNLINKED_BG
            ),
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=9,
                vertical=4,
            ),
            content=ft.Text(
                (
                    "VINCULADO"
                    if linked
                    else "SIN VINCULAR"
                ),
                size=9,
                weight=ft.FontWeight.BOLD,
                color=(
                    LINKED_FG
                    if linked
                    else UNLINKED_FG
                ),
            ),
        )

    def _avatar(
        item,
        *,
        size=42,
    ):
        name = _display_name(
            item
        ).strip()

        initials = "".join(
            part[0]
            for part in name.split()[:2]
            if part
        ).upper()

        if not initials:
            initials = "?"

        size = max(
            30,
            int(size),
        )

        return ft.Container(
            width=size,
            height=size,
            border_radius=(
                size / 2
            ),
            bgcolor=(
                "#DCEBFF"
                if _is_linked(item)
                else "#EEF2F6"
            ),
            alignment=ft.Alignment(
                0,
                0,
            ),
            content=ft.Text(
                initials,
                size=13,
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            ),
        )

    def selected_item():
        selected_id = state.get(
            "selected_thread_id"
        )

        for item in (
            state.get("items")
            or []
        ):
            if (
                item.thread_id
                == selected_id
            ):
                return item

        items = (
            state.get("items")
            or []
        )

        return (
            items[0]
            if items
            else None
        )

    def load_thread_context():
        thread_id = state.get(
            "selected_thread_id"
        )

        if thread_id is None:
            state["context"] = None
            state["context_error"] = None
            return

        try:
            state["context"] = (
                communication_service
                .get_thread_context(
                    int(thread_id)
                )
            )

            state["context_error"] = None

        except Exception as exc:
            state["context"] = None
            state["context_error"] = str(
                exc
            )

    def load_thread_messages():
        thread_id = state.get(
            "selected_thread_id"
        )

        if thread_id is None:
            state["messages"] = []
            state["messages_error"] = None
            return

        try:
            history_window_size = max(
                1,
                int(
                    state.get(
                        "message_history_window_size"
                    )
                    or 50
                ),
            )

            state["messages"] = list(
                communication_service
                .list_latest_thread_messages(
                    int(
                        thread_id
                    ),
                    limit=history_window_size,
                )
                or []
            )

            state["messages_error"] = None

        except Exception as exc:
            state["messages"] = []
            state["messages_error"] = str(
                exc
            )

    def select_thread(
        thread_id,
    ):
        previous_thread_id = (
            state.get(
                "selected_thread_id"
            )
        )

        new_thread_id = int(
            thread_id
        )

        state[
            "selected_thread_id"
        ] = new_thread_id

        # Cada selección invalida cualquier routing anterior.
        # La generación evita que un worker viejo pueda borrar
        # el estado perteneciente a una selección más reciente.
        state[
            "routing_generation"
        ] = (
            int(
                state.get(
                    "routing_generation"
                )
                or 0
            )
            + 1
        )

        state[
            "routing_target_thread_id"
        ] = new_thread_id

        if (
            previous_thread_id
            != new_thread_id
        ):
            # Cada conversación comienza siempre con una
            # ventana reciente limpia de 50 mensajes.
            state[
                "message_history_window_size"
            ] = int(
                state.get(
                    "message_history_page_size"
                )
                or 50
            )

            state[
                "message_history_loading_older"
            ] = False
            state[
                "message_history_has_more"
            ] = True
            state[
                "message_history_expanded"
            ] = False
            state[
                "message_history_programmatic_scroll"
            ] = False
            state[
                "message_history_top_load_armed"
            ] = False
            state[
                "message_history_scroll_initialized"
            ] = False
            state[
                "message_history_top_rearm_required"
            ] = False
            state[
                "message_history_user_scroll_active"
            ] = False
            state[
                "message_history_last_scroll_pixels"
            ] = None
            state[
                "message_history_last_max_scroll_extent"
            ] = None
            state[
                "message_history_pending_viewport_preserve"
            ] = None
            state[
                "message_history_follow_bottom"
            ] = True

            try:
                _clear_composer()
            except NameError:
                pass


        # PRIORIDAD 1 · conversación local.
        #
        # El historial persistido debe aparecer antes que:
        # - contexto lateral;
        # - selección visual del sidebar;
        # - routing/Selenium;
        # - sincronización incremental de WhatsApp.

        load_thread_messages()


        try:
            _refresh_composer_controls()
        except NameError:
            pass

        chat_refreshed = False

        try:
            chat_refreshed = (
                _refresh_chat_panel_control()
            )
        except NameError:
            chat_refreshed = False

        if not chat_refreshed:
            # Fallback conservador para construcción temprana
            # o control todavía no montado.
            _safe_update()


        # PRIORIDAD 2 · contexto CRM.
        #
        # Ya no forma parte del tiempo crítico para mostrar
        # la conversación solicitada.

        load_thread_context()


        if chat_refreshed:
            try:
                _refresh_context_panel_control()
            except NameError:
                pass

            # PRIORIDAD 3 · selección visual del sidebar.
            #
            # Se ejecuta DESPUÉS del chat central para que el
            # panel izquierdo nunca gane perceptivamente al clic.
            try:
                _refresh_conversation_list_control()
            except NameError:
                pass


        # Si WhatsApp ya está abierto, mantener ambas
        # interfaces sincronizadas: seleccionar una
        # conversación en CRM mueve WhatsApp al mismo chat.
        try:
            if whatsapp_runtime is not None:
                _route_whatsapp_thread(
                    new_thread_id,
                    generation=(
                        state.get(
                            "routing_generation"
                        )
                    ),
                )
        except NameError:
            # El helper se define más abajo durante la
            # construcción completa de la vista.
            pass

    def load_data(
        *,
        preserve_selection=True,
    ):
        selected_before = (
            state.get(
                "selected_thread_id"
            )
            if preserve_selection
            else None
        )

        try:
            result = (
                communication_service
                .list_thread_overviews(
                    channel=(
                        selected_channel()
                    ),
                    linkage=(
                        selected_linkage()
                    ),
                    search=(
                        search_input.value
                        or ""
                    ),
                    include_archived=False,
                    limit=5000,
                )
            )

            state[
                "summary"
            ] = (
                result.get(
                    "summary"
                )
                or {}
            )

            state[
                "items"
            ] = list(
                result.get(
                    "items"
                )
                or []
            )

            state[
                "error"
            ] = None

            state[
                "search"
            ] = (
                search_input.value
                or ""
            )

            state[
                "linkage"
            ] = (
                selected_linkage()
            )

            valid_ids = {
                item.thread_id
                for item in state[
                    "items"
                ]
            }

            if (
                selected_before
                in valid_ids
            ):
                state[
                    "selected_thread_id"
                ] = (
                    selected_before
                )

            elif state["items"]:
                state[
                    "selected_thread_id"
                ] = (
                    state["items"][
                        0
                    ].thread_id
                )

            else:
                state[
                    "selected_thread_id"
                ] = None

            selected_id = state.get(
                "selected_thread_id"
            )

            if selected_id is not None:
                selected_index = next(
                    (
                        index
                        for index, item
                        in enumerate(
                            state["items"]
                        )
                        if item.thread_id
                        == selected_id
                    ),
                    None,
                )

                if selected_index is not None:
                    state["page"] = (
                        selected_index
                        // int(
                            state[
                                "page_size"
                            ]
                        )
                    ) + 1

            load_thread_context()
            load_thread_messages()

            # load_data() puede seleccionar automáticamente
            # una conversación después de que el compositor
            # se haya creado inicialmente como deshabilitado.
            # Recalcular aquí garantiza que el estado visual
            # refleje el thread realmente seleccionado.
            try:
                _refresh_composer_controls()
            except NameError:
                # Durante construcción temprana de la vista
                # el helper podría no estar definido todavía.
                pass

            total_pages = max(
                1,
                math.ceil(
                    len(
                        state["items"]
                    )
                    / state[
                        "page_size"
                    ]
                ),
            )

            state["page"] = max(
                1,
                min(
                    int(
                        state.get(
                            "page"
                        )
                        or 1
                    ),
                    total_pages,
                ),
            )

        except Exception as exc:
            state["summary"] = {}
            state["items"] = []
            state["context"] = None
            state["context_error"] = None
            state["error"] = str(
                exc
            )

    def refresh(
        e=None,
    ):
        state["page"] = 1

        load_data(
            preserve_selection=True,
        )

        _safe_update()

    def reconcile_links(
        e=None,
    ):
        try:
            result = (
                communication_service
                .backfill_whatsapp_thread_matches(
                    limit=5000,
                )
            )

            summary = (
                result.get(
                    "summary"
                )
                or {}
            )

            load_data(
                preserve_selection=True,
            )

            _safe_update()

            _show_message(
                (
                    "Reconciliación completada · "
                    f"{summary.get('updated', 0)} "
                    "vínculo(s) actualizado(s)"
                )
            )

        except Exception as exc:
            _show_message(
                (
                    "No se pudo reconciliar: "
                    f"{exc}"
                ),
                error=True,
            )

    def _resolve_whatsapp_sidebar_thread_id(
        identity,
    ):
        """Resuelve una identidad visible del sidebar a thread_id.

        Solo cachea coincidencias inequívocas.
        Una identidad ambigua jamás se elige arbitrariamente.
        """
        normalized = str(
            identity
            or ""
        ).strip()

        if not normalized:
            return None

        cache = state.setdefault(
            "whatsapp_sidebar_identity_cache",
            {},
        )

        cached = cache.get(
            normalized
        )

        if cached not in (
            None,
            "",
        ):
            return int(
                cached
            )

        negative_cache = state.setdefault(
            "whatsapp_sidebar_identity_negative_cache",
            {},
        )

        now = time.monotonic()

        negative_until = negative_cache.get(
            normalized
        )

        if negative_until is not None:
            try:
                negative_until = float(
                    negative_until
                )
            except Exception:
                negative_until = 0.0

            if negative_until > now:
                return None

            negative_cache.pop(
                normalized,
                None,
            )


        try:
            resolution = (
                communication_service
                .resolve_whatsapp_thread_by_identity(
                    normalized
                )
            )

        except Exception as exc:
            print(
                "[WA-FLET] sidebar resolution failed",
                ascii(
                    normalized
                ),
                repr(
                    exc
                ),
                flush=True,
            )
            return None


        if not isinstance(
            resolution,
            dict,
        ):
            return None

        if not resolution.get(
            "matched"
        ):
            negative_cache[
                normalized
            ] = (
                time.monotonic()
                + 15.0
            )


            return None

        if resolution.get(
            "ambiguous"
        ):
            negative_cache[
                normalized
            ] = (
                time.monotonic()
                + 15.0
            )

            print(
                "[WA-FLET] sidebar identity ambiguous",
                ascii(
                    normalized
                ),
                flush=True,
            )

            return None

        thread = resolution.get(
            "thread"
        )

        thread_id = getattr(
            thread,
            "thread_id",
            None,
        )

        if thread_id in (
            None,
            "",
        ):
            return None

        thread_id = int(
            thread_id
        )

        cache[
            normalized
        ] = thread_id

        # Si antes fue unresolved/ambiguous pero ahora existe
        # una coincidencia inequívoca, el positivo gana.
        negative_cache.pop(
            normalized,
            None,
        )

        return thread_id


    def _promote_realtime_thread(
        thread_id,
    ):
        """Promueve actividad reciente al principio del modelo local.

        No fuerza page=1 y no carga datos adicionales.
        """
        items = list(
            state.get(
                "items"
            )
            or []
        )

        index = next(
            (
                index
                for index, item
                in enumerate(
                    items
                )
                if int(
                    item.thread_id
                )
                == int(
                    thread_id
                )
            ),
            None,
        )

        if index is None:
            return False

        if index == 0:
            return False

        item = items.pop(
            index
        )

        items.insert(
            0,
            item,
        )

        state[
            "items"
        ] = items

        return True


    def _hydrate_whatsapp_sidebar_initial(
        result,
    ):
        """Hidrata el primer fingerprint visible de WhatsApp.

        No representa actividad nueva:
        - no promueve conversaciones;
        - no crea deltas artificiales;
        - solo superpone preview/hora/unread observados.
        """
        if not isinstance(
            result,
            dict,
        ):
            return False

        if (
            str(
                result.get(
                    "sidebar_change_type"
                )
                or ""
            ).strip()
            != "SIDEBAR_INITIAL"
        ):
            return False

        sidebar = result.get(
            "sidebar"
        )

        if not isinstance(
            sidebar,
            dict,
        ):
            return False

        if not sidebar:
            return False

        realtime = state.setdefault(
            "whatsapp_sidebar_realtime",
            {},
        )

        hydrated = 0
        unresolved = 0
        ambiguous = 0

        for identity, current in sidebar.items():
            if not isinstance(
                current,
                dict,
            ):
                continue

            if bool(
                current.get(
                    "ambiguous"
                )
            ):
                ambiguous += 1
                continue

            normalized_identity = str(
                identity
                or current.get(
                    "identity"
                )
                or ""
            ).strip()

            if not normalized_identity:
                continue

            thread_id = (
                _resolve_whatsapp_sidebar_thread_id(
                    normalized_identity
                )
            )

            if thread_id is None:
                unresolved += 1
                continue

            try:
                unread_count = max(
                    0,
                    int(
                        current.get(
                            "unread_count"
                        )
                        or 0
                    ),
                )
            except Exception:
                unread_count = 0

            realtime[
                int(
                    thread_id
                )
            ] = {
                "identity":
                    current.get(
                        "identity"
                    ),
                "display_name":
                    current.get(
                        "display_name"
                    ),
                "preview":
                    current.get(
                        "preview"
                    ),
                "primary_detail":
                    current.get(
                        "primary_detail"
                    ),
                "unread_count":
                    unread_count,
                "position":
                    current.get(
                        "position"
                    ),
                "virtual_offset":
                    current.get(
                        "virtual_offset"
                    ),
            }

            hydrated += 1

        if hydrated <= 0:
            return False

        # No promovemos threads durante INITIAL.
        # Se conserva el orden CRM existente.
        if state.get(
            "routing_target_thread_id"
        ):
            state[
                "whatsapp_sidebar_render_pending"
            ] = True


            return False


        refreshed = (
            _refresh_conversation_list_control()
        )



        if not refreshed:
            _safe_update()

        return True


    def _apply_whatsapp_sidebar_changes(
        result,
    ):
        """Aplica deltas del sidebar sin reconstruir toda la vista."""
        if not isinstance(
            result,
            dict,
        ):
            return False

        if not result.get(
            "sidebar_changed"
        ):
            return False

        changes = list(
            result.get(
                "sidebar_changes"
            )
            or []
        )

        if not changes:
            return False

        realtime = state.setdefault(
            "whatsapp_sidebar_realtime",
            {},
        )

        touched = False

        for change in changes:
            if not isinstance(
                change,
                dict,
            ):
                continue

            change_type = str(
                change.get(
                    "change_type"
                )
                or ""
            ).strip()

            # DISAPPEARED puede ser simple virtualización.
            if (
                change_type
                == "SIDEBAR_THREAD_DISAPPEARED"
            ):
                continue

            # REORDERED sin cambio de contenido tampoco
            # significa mensaje nuevo.
            if (
                change_type
                == "SIDEBAR_THREAD_REORDERED"
            ):
                continue

            current = change.get(
                "current"
            )

            if not isinstance(
                current,
                dict,
            ):
                continue

            if bool(
                current.get(
                    "ambiguous"
                )
            ):
                continue

            try:
                unread_count = max(
                    0,
                    int(
                        current.get(
                            "unread_count"
                        )
                        or 0
                    ),
                )
            except Exception:
                unread_count = 0

            # APPEARED es muy frecuente por virtualización.
            #
            # Solo lo consideramos señal funcional si WhatsApp
            # muestra explícitamente mensajes no leídos.
            if (
                change_type
                == "SIDEBAR_THREAD_APPEARED"
                and unread_count <= 0
            ):
                continue

            if (
                change_type
                != "SIDEBAR_THREAD_CHANGED"
                and change_type
                != "SIDEBAR_THREAD_APPEARED"
            ):
                continue

            identity = str(
                change.get(
                    "identity"
                )
                or current.get(
                    "identity"
                )
                or ""
            ).strip()

            if not identity:
                continue

            thread_id = (
                _resolve_whatsapp_sidebar_thread_id(
                    identity
                )
            )

            if thread_id is None:
                continue

            # Semántica CRM:
            #
            # Si el operador está visualizando este thread,
            # los mensajes están siendo atendidos desde el CRM
            # aunque WhatsApp Web, detrás/sin foco, conserve su
            # propio badge de no leídos.
            selected_thread_id = state.get(
                "selected_thread_id"
            )

            visible_in_crm = (
                selected_thread_id
                not in (
                    None,
                    "",
                )
                and int(
                    selected_thread_id
                )
                == int(
                    thread_id
                )
            )

            effective_unread_count = (
                0
                if visible_in_crm
                else unread_count
            )

            realtime[
                int(
                    thread_id
                )
            ] = {
                "identity":
                    current.get(
                        "identity"
                    ),
                "display_name":
                    current.get(
                        "display_name"
                    ),
                "preview":
                    current.get(
                        "preview"
                    ),
                "primary_detail":
                    current.get(
                        "primary_detail"
                    ),
                "unread_count":
                    effective_unread_count,
                "position":
                    current.get(
                        "position"
                    ),
                "virtual_offset":
                    current.get(
                        "virtual_offset"
                    ),
            }

            # Solo promovemos si existe cambio funcional.
            if bool(
                change.get(
                    "content_changed"
                )
            ):
                _promote_realtime_thread(
                    thread_id
                )

            touched = True


        if not touched:
            return False

        # Prioridad UX:
        # una selección explícita del usuario gana siempre
        # frente a una actualización lateral.
        #
        # Los datos realtime ya quedaron absorbidos arriba,
        # pero posponemos su render mientras WhatsApp está
        # encaminándose al chat solicitado.
        if state.get(
            "routing_target_thread_id"
        ):
            state[
                "whatsapp_sidebar_render_pending"
            ] = True


            return False


        refreshed = (
            _refresh_conversation_list_control()
        )


        if not refreshed:
            # Puede ocurrir durante el primer montaje.
            _safe_update()

        return True


    def _reload_conversation_items_for_sidebar_discovery():
        """Recarga únicamente el modelo lateral de conversaciones.

        Se utiliza cuando el watcher acaba de crear un thread
        que todavía no existía cuando Flet cargó state["items"].

        No modifica:
        - selección central;
        - contexto;
        - historial;
        - compositor;
        - routing de WhatsApp.
        """
        selected_before = state.get(
            "selected_thread_id"
        )

        try:
            result = (
                communication_service
                .list_thread_overviews(
                    channel=(
                        selected_channel()
                    ),
                    linkage=(
                        selected_linkage()
                    ),
                    search=(
                        search_input.value
                        or ""
                    ),
                    include_archived=False,
                    limit=5000,
                )
            )

        except Exception as exc:
            print(
                "[WA-FLET] sidebar discovery "
                "model reload failed",
                repr(
                    exc
                ),
                flush=True,
            )

            return False

        state[
            "summary"
        ] = (
            result.get(
                "summary"
            )
            or {}
        )

        state[
            "items"
        ] = list(
            result.get(
                "items"
            )
            or []
        )

        # Una actualización lateral en background jamás
        # modifica la conversación que está viendo el usuario.
        state[
            "selected_thread_id"
        ] = selected_before

        return True


    def _absorb_whatsapp_sidebar_discoveries(
        result,
    ):
        """Integra threads descubiertos por Runtime en el modelo Flet.

        Runtime/CommunicationService ya realizaron la
        persistencia. El frontend:
        - consume thread_id;
        - actualiza cachés;
        - recarga state["items"] solo si nació un thread;
        - nunca crea ni persiste conversaciones.
        """
        if not isinstance(
            result,
            dict,
        ):
            return False

        discoveries = list(
            result.get(
                "sidebar_discoveries"
            )
            or []
        )

        if not discoveries:
            return False

        positive_cache = state.setdefault(
            "whatsapp_sidebar_identity_cache",
            {},
        )

        negative_cache = state.setdefault(
            "whatsapp_sidebar_identity_negative_cache",
            {},
        )

        created_thread_ids = []
        absorbed = False

        for discovery in discoveries:
            if not isinstance(
                discovery,
                dict,
            ):
                continue

            if not discovery.get(
                "discovered"
            ):
                continue

            thread_id = discovery.get(
                "thread_id"
            )

            if thread_id in (
                None,
                "",
            ):
                continue

            try:
                thread_id = int(
                    thread_id
                )
            except Exception:
                continue

            identity = str(
                discovery.get(
                    "identity"
                )
                or ""
            ).strip()

            if identity:
                positive_cache[
                    identity
                ] = thread_id

                # Si el resolver había cacheado previamente
                # "no existe", el descubrimiento backend es
                # ahora la autoridad y elimina ese negativo.
                negative_cache.pop(
                    identity,
                    None,
                )

            if discovery.get(
                "created"
            ):
                created_thread_ids.append(
                    thread_id
                )

            absorbed = True

        if not absorbed:
            return False

        if not created_thread_ids:
            return True

        current_ids = {
            int(
                item.thread_id
            )
            for item in (
                state.get(
                    "items"
                )
                or []
            )
            if getattr(
                item,
                "thread_id",
                None,
            )
            not in (
                None,
                "",
            )
        }

        missing_created_ids = [
            thread_id
            for thread_id
            in created_thread_ids
            if thread_id
            not in current_ids
        ]

        if not missing_created_ids:
            return True

        reloaded = (
            _reload_conversation_items_for_sidebar_discovery()
        )

        if not reloaded:
            return True

        # Un thread recién descubierto con trabajo pendiente
        # debe quedar visible al principio del modelo local.
        #
        # Esto NO selecciona ni abre la conversación.
        reloaded_ids = {
            int(
                item.thread_id
            )
            for item in (
                state.get(
                    "items"
                )
                or []
            )
            if getattr(
                item,
                "thread_id",
                None,
            )
            not in (
                None,
                "",
            )
        }

        for thread_id in created_thread_ids:
            if thread_id not in reloaded_ids:
                # Puede quedar fuera por filtros activos
                # (por ejemplo LINKED o búsqueda).
                continue

            _promote_realtime_thread(
                thread_id
            )

        return True


    def _apply_whatsapp_sidebar_result(
        result,
    ):
        """Aplica el estado lateral en el momento decidido por UX.

        INITIAL mantiene hidratación propia. Los demás eventos
        utilizan el delta realtime existente.
        """
        if not isinstance(
            result,
            dict,
        ):
            return False

        _absorb_whatsapp_sidebar_discoveries(
            result
        )

        if (
            str(
                result.get(
                    "sidebar_change_type"
                )
                or ""
            ).strip()
            == "SIDEBAR_INITIAL"
        ):
            return (
                _hydrate_whatsapp_sidebar_initial(
                    result
                )
            )

        return (
            _apply_whatsapp_sidebar_changes(
                result
            )
        )


    async def _dispatch_whatsapp_watch_change(
        result,
    ):
        """Ejecuta el callback realtime dentro del event loop Flet.

        El watcher de WhatsApp vive en un hilo de background.
        Toda mutación visual se devuelve al event loop de la página
        antes de tocar controles Flet.
        """
        try:
            _on_whatsapp_watch_change(
                result
            )

        except Exception as exc:
            print(
                "[WA-FLET] dispatched watcher callback failed",
                repr(
                    exc
                ),
                flush=True,
            )

    def _schedule_whatsapp_watch_change(
        result,
    ):
        """Puente thread-safe conceptual watcher → página Flet.

        Este callback puede ser invocado desde el hilo supervisor
        de WhatsApp. No actualiza controles directamente.
        """
        runner = getattr(
            page,
            "run_task",
            None,
        )

        if not callable(
            runner
        ):
            print(
                "[WA-FLET] watcher dispatch unavailable: "
                "page.run_task missing",
                flush=True,
            )
            return

        try:
            runner(
                _dispatch_whatsapp_watch_change,
                result,
            )

        except Exception as exc:
            print(
                "[WA-FLET] watcher dispatch schedule failed",
                repr(
                    exc
                ),
                flush=True,
            )


    def _on_whatsapp_watch_change(
        result,
    ):


        if not isinstance(
            result,
            dict,
        ):
            return

        # COM-8FA4B2C · Chat-first.
        #
        # Sidebar y chat activo siguen siendo sensores
        # independientes, pero ya no imponemos que el sidebar
        # se renderice antes de una actualización del chat
        # actualmente visible.
        #
        # Para eventos exclusivamente laterales mantenemos
        # comportamiento inmediato.
        active_change = (
            result.get(
                "change_type"
            )
            in (
                "MESSAGE_CHANGED",
                "CHAT_CHANGED",
            )
        )

        sidebar_refreshed = False

        if not active_change:
            sidebar_refreshed = (
                _apply_whatsapp_sidebar_result(
                    result
                )
            )

        if not active_change:
            return

        sync_result = result.get(
            "sync"
        )

        if not isinstance(
            sync_result,
            dict,
        ):
            # El sensor lateral es independiente del sync
            # profundo del chat activo.
            sidebar_refreshed = (
                _apply_whatsapp_sidebar_result(
                    result
                )
            )

            return

        if (
            sync_result.get(
                "error"
            )
            or sync_result.get(
                "aborted"
            )
        ):
            sidebar_refreshed = (
                _apply_whatsapp_sidebar_result(
                    result
                )
            )

            print(
                "[WA-FLET] sync rejected",
                {
                    "error":
                        sync_result.get("error"),
                    "aborted":
                        sync_result.get("aborted"),
                    "reason":
                        sync_result.get("reason"),
                    "abort_reason":
                        sync_result.get("abort_reason"),
                },
                flush=True,
            )
            return

        summary = (
            sync_result.get(
                "summary"
            )
            or {}
        )

        synced_thread_id = (
            summary.get(
                "thread_id"
            )
        )


        selected_thread_id = (
            state.get(
                "selected_thread_id"
            )
        )

        visible_synced_thread = (
            synced_thread_id
            not in (
                None,
                "",
            )
            and selected_thread_id
            not in (
                None,
                "",
            )
            and int(
                synced_thread_id
            )
            == int(
                selected_thread_id
            )
        )

        routing_target_thread_id = (
            state.get(
                "routing_target_thread_id"
            )
        )

        stale_during_routing = (
            not visible_synced_thread
            and synced_thread_id
            not in (
                None,
                "",
            )
            and routing_target_thread_id
            not in (
                None,
                "",
            )
            and selected_thread_id
            not in (
                None,
                "",
            )
            and int(
                routing_target_thread_id
            )
            == int(
                selected_thread_id
            )
            and int(
                synced_thread_id
            )
            != int(
                selected_thread_id
            )
        )

        if stale_during_routing:
            # Conservamos el sensor lateral. Si existe routing
            # activo, _apply_whatsapp_sidebar_changes() ya sabe
            # absorber los datos y diferir su render.
            sidebar_refreshed = (
                _apply_whatsapp_sidebar_result(
                    result
                )
            )

            # El backend ya persistió el sync.
            #
            # No reconstruimos la UI por un chat anterior
            # mientras existe una selección más reciente
            # todavía encaminándose hacia WhatsApp.

            return

        if visible_synced_thread:
            # FAST PATH:
            # El mensaje pertenece al chat actualmente
            # visible. No reconstruimos:
            # - sidebar de conversaciones,
            # - métricas,
            # - filtros,
            # - panel de contexto.
            #
            # Solo recuperamos el historial persistido
            # actualizado y sustituimos las burbujas.

            previous_messages = list(
                state.get(
                    "messages"
                )
                or []
            )

            created_count = int(
                summary.get(
                    "created"
                )
                or 0
            )

            reused_count = int(
                summary.get(
                    "reused"
                )
                or 0
            )

            status_advanced_count = int(
                summary.get(
                    "status_advanced"
                )
                or 0
            )

            # Los items pertenecen al resultado profundo
            # del sync, no al envelope general del watcher.
            #
            # sync_result["items"] contiene la identidad
            # concreta de cada mensaje cuyo estado avanzó.
            sync_items = list(
                sync_result.get(
                    "items"
                )
                or []
            )

            # Si el usuario ha cargado histórico adicional,
            # conservarlo al entrar mensajes nuevos. Ampliamos
            # temporalmente la ventana por el delta creado para
            # que previous siga siendo prefijo de current.
            if (
                state.get(
                    "message_history_expanded"
                )
                and created_count > 0
            ):
                state[
                    "message_history_window_size"
                ] = (
                    max(
                        len(
                            previous_messages
                        ),
                        int(
                            state.get(
                                "message_history_window_size"
                            )
                            or 0
                        ),
                    )
                    + created_count
                )

            load_thread_messages()

            current_messages = list(
                state.get(
                    "messages"
                )
                or []
            )

            # Transición especial EMPTY -> FIRST MESSAGE.
            #
            # Cuando el thread tenía 0 mensajes,
            # _build_message_history() había montado el empty
            # state en lugar de message_history_control.
            #
            # Si el sync acaba de crear el primer contenido,
            # message_history_control todavía NO pertenece al
            # árbol Flet. No debemos llamar a update() sobre él:
            # remontamos únicamente el host central.
            empty_to_first_message = (
                created_count > 0
                and not previous_messages
                and bool(
                    current_messages
                )
                and not state.get(
                    "messages_error"
                )
            )


            # Caso realtime habitual:
            # uno o varios mensajes NUEVOS al final.
            incremental_candidate = (
                created_count > 0
                and reused_count == 0
                and status_advanced_count == 0
            )

            # Si el sync no crea mensajes y tampoco avanza
            # estados, no existe cambio visual en el historial.
            #
            # Cubre:
            # - reused > 0 sin cambio de estado;
            # - CHAT_CHANGED ya sincronizado con cero delta.
            sync_no_visual_change = (
                created_count == 0
                and status_advanced_count == 0
            )

            light_refreshed = False

            if empty_to_first_message:
                # El historial persistente no estaba montado:
                # el panel central mostraba el empty state.
                #
                # Reconstruimos SOLO chat_panel_control.
                # build_chat_panel() volverá a llamar a
                # _build_message_history(), que ahora sí
                # insertará message_history_control en Flet.
                try:
                    light_refreshed = (
                        _refresh_chat_panel_control()
                    )
                except NameError:
                    light_refreshed = False


            elif incremental_candidate:
                light_refreshed = (
                    _append_new_message_history_controls(
                        previous_messages
                    )
                )

            elif (
                created_count > 0
                and status_advanced_count > 0
            ):
                # Un mensaje entrante puede aparecer en la misma
                # iteración en que uno o varios outbound pasan a
                # DELIVERED/READ.
                #
                # Aplicamos ambos deltas sin reconstruir el Column:
                # append incremental + ticks individuales.
                appended = (
                    _append_new_message_history_controls(
                        previous_messages
                    )
                )

                status_updated = (
                    _update_advanced_message_status_controls(
                        previous_messages,
                        current_messages,
                        sync_items,
                    )
                )

                light_refreshed = (
                    appended
                    and status_updated
                )


            elif (
                status_advanced_count > 0
                and created_count == 0
            ):
                light_refreshed = (
                    _update_advanced_message_status_controls(
                        previous_messages,
                        current_messages,
                        sync_items,
                    )
                )

            elif sync_no_visual_change:
                light_refreshed = True


            if not light_refreshed:
                light_refreshed = (
                    _refresh_message_history_control()
                )

            if not light_refreshed:
                # Estado vacío/error/control todavía no
                # montado: fallback seguro al comportamiento
                # completo existente.
                print(
                    "[WA-FLET] light refresh fallback full",
                    flush=True,
                )

                _safe_update()


            # Punto perceptivo principal:
            # el historial central ya se actualizó antes de
            # reconstruir las cards laterales.

            sidebar_refreshed = (
                _apply_whatsapp_sidebar_result(
                    result
                )
            )

        else:
            # Para una conversación no visible, el sidebar es
            # la única superficie que necesita actualización.
            sidebar_refreshed = (
                _apply_whatsapp_sidebar_result(
                    result
                )
            )

            # COM-8FA4B2B · Un sync de una conversación que
            # NO está visible nunca debe reconstruir toda la
            # pantalla de Comunicaciones.
            #
            # El sidebar realtime ya contiene preview/hora/
            # unread cuando existe un delta de WhatsApp.
            # El mensaje permanece persistido en backend y se
            # cargará normalmente al seleccionar ese thread.


        try:
            _refresh_composer_controls()
        except NameError:
            pass




    async def _dispatch_ui_message(
        message,
        error=False,
    ):
        """Muestra una notificación dentro del event loop de Flet."""
        _show_message(
            str(
                message
                or ""
            ),
            error=bool(
                error
            ),
        )


    def _schedule_ui_message(
        message,
        *,
        error=False,
    ):
        """Programa una notificación UI desde un worker."""
        runner = getattr(
            page,
            "run_task",
            None,
        )

        if not callable(
            runner
        ):
            return False

        try:
            runner(
                _dispatch_ui_message,
                str(
                    message
                    or ""
                ),
                bool(
                    error
                ),
            )

            return True

        except Exception:
            return False


    def open_whatsapp(
        e=None,
    ):
        if whatsapp_runtime is None:
            _show_message(
                "El runtime de WhatsApp no está disponible.",
                error=True,
            )
            return

        def worker():
            try:
                already_started = bool(
                    whatsapp_runtime.started
                )

                whatsapp_runtime.start()

                watch_thread = (
                    whatsapp_runtime
                    .start_active_chat_watch(
                        interval_seconds=0.5,
                        wait_timeout=5,
                        on_change=(
                            _schedule_whatsapp_watch_change
                        ),
                    )
                )


                if already_started:
                    _schedule_ui_message(
                        (
                            "WhatsApp ya estaba abierto "
                            "y seguirá reutilizando "
                            "la misma sesión."
                        )
                    )

                else:
                    _schedule_ui_message(
                        (
                            "WhatsApp Web abierto. "
                            "Selecciona una conversación "
                            "del CRM para abrirla."
                        )
                    )

            except Exception as exc:
                _schedule_ui_message(
                    (
                        "No se pudo abrir WhatsApp Web: "
                        f"{exc}"
                    ),
                    error=True,
                )

        runner = getattr(
            page,
            "run_thread",
            None,
        )

        if not callable(runner):
            _show_message(
                (
                    "Esta versión de Flet no dispone "
                    "de page.run_thread()."
                ),
                error=True,
            )
            return

        runner(
            worker
        )

    def placeholder_sync(
        e=None,
    ):
        _show_message(
            (
                "La sincronización desde WhatsApp Web "
                "se integrará en la siguiente fase."
            )
        )

    def clear_filters(
        e=None,
    ):
        search_input.value = ""
        linkage_filter.input.value = (
            "Todas"
        )

        channel_filter.input.value = (
            "WhatsApp"
        )

        state["page"] = 1

        refresh()

    def previous_page(
        e=None,
    ):
        if state["page"] > 1:
            state["page"] -= 1
            _safe_update()

    def next_page(
        e=None,
    ):
        total = len(
            state.get(
                "items"
            )
            or []
        )

        pages = max(
            1,
            math.ceil(
                total
                / state[
                    "page_size"
                ]
            ),
        )

        if state["page"] < pages:
            state["page"] += 1
            _safe_update()

    def build_error_content(
        message,
    ):
        return ft.Container(
            expand=True,
            padding=24,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Comunicaciones",
                        size=28,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Container(
                        padding=18,
                        bgcolor="#FEF3F2",
                        border_radius=12,
                        border=ft.border.all(
                            1,
                            "#FDA29B",
                        ),
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    (
                                        "No se pudo cargar "
                                        "Comunicaciones"
                                    ),
                                    size=16,
                                    weight=(
                                        ft.FontWeight.BOLD
                                    ),
                                    color="#B42318",
                                ),
                                ft.Text(
                                    str(
                                        message
                                    ),
                                    size=12,
                                    color=Q_TEXT,
                                    selectable=True,
                                ),
                            ],
                            spacing=8,
                        ),
                    ),
                ],
                spacing=14,
            ),
        )

    def set_linkage_filter(
        linkage,
    ):
        normalized = str(
            linkage
            or "ALL"
        ).strip().upper()

        label_by_value = {
            value: label
            for label, value
            in LINKAGE_FILTER_VALUES.items()
        }

        label = (
            label_by_value.get(
                normalized,
                "Todas",
            )
        )

        linkage_filter.input.value = (
            label
        )

        state[
            "linkage"
        ] = normalized

        state[
            "page"
        ] = 1

        load_data(
            preserve_selection=True,
        )

        _safe_update()

    def build_linkage_pill(
        label,
        value,
    ):
        selected = (
            state.get(
                "linkage",
                "ALL",
            )
            == value
        )

        if value == "LINKED":
            inactive_bg = "#ECFDF3"
            inactive_fg = "#027A48"
            inactive_border = "#ABEFC6"

        elif value == "UNLINKED":
            inactive_bg = "#FFF7E6"
            inactive_fg = "#B54708"
            inactive_border = "#FEDF89"

        else:
            inactive_bg = "#F8FAFC"
            inactive_fg = Q_PRIMARY_DARK
            inactive_border = Q_BORDER

        return ft.Container(
            bgcolor=(
                Q_PRIMARY
                if selected
                else inactive_bg
            ),
            border=ft.border.all(
                1,
                (
                    Q_PRIMARY
                    if selected
                    else inactive_border
                ),
            ),
            border_radius=999,
            padding=ft.padding.symmetric(
                horizontal=11,
                vertical=6,
            ),
            ink=True,
            on_click=(
                lambda e,
                linkage=value:
                    set_linkage_filter(
                        linkage
                    )
            ),
            content=ft.Text(
                label,
                size=10,
                weight=ft.FontWeight.W_600,
                color=(
                    Q_WHITE
                    if selected
                    else inactive_fg
                ),
            ),
        )

    def build_conversation_card(
        item,
    ):
        selected = (
            item.thread_id
            == state.get(
                "selected_thread_id"
            )
        )

        realtime = (
            _thread_realtime_sidebar_state(
                item
            )
        )

        realtime_preview = str(
            realtime.get(
                "preview"
            )
            or ""
        ).strip()

        preview = (
            realtime_preview
            or item.last_message_preview
            or (
                "Sin mensajes sincronizados"
                if not item.message_count
                else "Mensaje disponible"
            )
        )

        realtime_detail = str(
            realtime.get(
                "primary_detail"
            )
            or ""
        ).strip()

        try:
            realtime_unread = max(
                0,
                int(
                    realtime.get(
                        "unread_count"
                    )
                    or 0
                ),
            )
        except Exception:
            realtime_unread = 0

        secondary = _secondary_name(
            item
        )

        return ft.Container(
            bgcolor=(
                SELECTED_BG
                if selected
                else Q_WHITE
            ),
            border=ft.border.all(
                (
                    1.5
                    if selected
                    else 1
                ),
                (
                    "#7EB5F5"
                    if selected
                    else Q_BORDER
                ),
            ),
            border_radius=10,
            padding=ft.padding.symmetric(
                horizontal=10,
                vertical=8,
            ),
            ink=True,
            on_click=(
                lambda e,
                thread_id=item.thread_id:
                    select_thread(
                        thread_id
                    )
            ),
            content=ft.Row(
                controls=[
                    _avatar(
                        item,
                        size=36,
                    ),
                    ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        _display_name(
                                            item
                                        ),
                                        size=12,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY_DARK,
                                        expand=True,
                                        overflow=(
                                            ft.TextOverflow.ELLIPSIS
                                        ),
                                    ),
                                    _status_badge(
                                        item
                                    ),
                                    *(
                                        [
                                            ft.Text(
                                                realtime_detail,
                                                size=9,
                                                color=Q_MUTED,
                                            )
                                        ]
                                        if realtime_detail
                                        else []
                                    ),
                                    *(
                                        [
                                            _realtime_unread_badge(
                                                realtime_unread
                                            )
                                        ]
                                        if realtime_unread
                                        else []
                                    ),
                                ],
                                spacing=6,
                            ),
                            ft.Text(
                                (
                                    item.external_address
                                    or "Sin teléfono"
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),
                            (
                                ft.Text(
                                    secondary,
                                    size=10,
                                    color=Q_MUTED,
                                    overflow=(
                                        ft.TextOverflow.ELLIPSIS
                                    ),
                                )
                                if secondary
                                else ft.Container(
                                    height=0,
                                )
                            ),
                            ft.Text(
                                preview,
                                size=10,
                                color="#475467",
                                max_lines=1,
                                overflow=(
                                    ft.TextOverflow.ELLIPSIS
                                ),
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=(
                    ft.CrossAxisAlignment.START
                ),
            ),
        )

    # COM-8FA3 · Sidebar persistente.
    #
    # El CRM puede tener miles de conversaciones,
    # pero este control solo materializa la página visible.
    conversation_list_control = ft.Column(
        controls=[],
        spacing=6,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


    def _visible_conversation_items():
        items = list(
            state.get(
                "items"
            )
            or []
        )

        page_size = max(
            1,
            int(
                state.get(
                    "page_size"
                )
                or 20
            ),
        )

        current_page = max(
            1,
            int(
                state.get(
                    "page"
                )
                or 1
            ),
        )

        start = (
            current_page - 1
        ) * page_size

        return items[
            start:
            start + page_size
        ]


    def _refresh_conversation_list_control():
        visible = (
            _visible_conversation_items()
        )

        if visible:
            controls = [
                build_conversation_card(
                    item
                )
                for item in visible
            ]
        else:
            controls = [
                empty_state(
                    (
                        "No hay conversaciones "
                        "para los filtros actuales"
                    )
                )
            ]

        conversation_list_control.controls = (
            controls
        )

        try:

            conversation_list_control.update()


            return True

        except Exception as exc:
            print(
                "[WA-FLET] realtime sidebar "
                "refresh unavailable",
                repr(
                    exc
                ),
                flush=True,
            )

            return False


    def build_conversation_list():
        items = (
            state.get(
                "items"
            )
            or []
        )

        page_size = int(
            state[
                "page_size"
            ]
        )

        current_page = int(
            state[
                "page"
            ]
        )

        total_pages = max(
            1,
            math.ceil(
                len(items)
                / page_size
            ),
        )

        start = (
            current_page - 1
        ) * page_size

        end = start + page_size

        visible = items[
            start:end
        ]

        cards = [
            build_conversation_card(
                item
            )
            for item in visible
        ]

        if cards:
            conversation_list_control.controls = (
                cards
            )
        else:
            conversation_list_control.controls = [
                empty_state(
                    (
                        "No hay conversaciones "
                        "para los filtros actuales"
                    )
                )
            ]

        list_content = (
            conversation_list_control
        )

        return ft.Container(
            width=385,
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Conversaciones",
                                size=15,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                                expand=True,
                            ),
                            ft.Text(
                                (
                                    f"{len(items)}"
                                ),
                                size=11,
                                color=Q_MUTED,
                            ),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            build_linkage_pill(
                                "Todas",
                                "ALL",
                            ),
                            build_linkage_pill(
                                "Vinculadas",
                                "LINKED",
                            ),
                            build_linkage_pill(
                                "Sin vincular",
                                "UNLINKED",
                            ),
                        ],
                        spacing=6,
                        wrap=True,
                    ),
                    list_content,
                    ft.Divider(
                        height=1,
                        color="#E4E7EC",
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(
                                (
                                    f"Página "
                                    f"{current_page} "
                                    f"de {total_pages}"
                                ),
                                size=10,
                                color=Q_MUTED,
                                expand=True,
                            ),
                            ft.TextButton(
                                "<",
                                on_click=previous_page,
                                disabled=(
                                    current_page
                                    <= 1
                                ),
                            ),
                            ft.TextButton(
                                ">",
                                on_click=next_page,
                                disabled=(
                                    current_page
                                    >= total_pages
                                ),
                            ),
                        ],
                        spacing=2,
                    ),
                ],
                spacing=10,
                expand=True,
            ),
        )

    def _message_type(message):
        metadata = (
            message.metadata
            or {}
        )

        return str(
            metadata.get(
                "message_type"
            )
            or "TEXT"
        ).strip().upper()


    def _message_body(message):
        body = str(
            message.body_text
            or ""
        ).strip()

        message_type = _message_type(
            message
        )

        if body:
            return body

        if message_type == "STICKER":
            return "🖼 Sticker"

        if message_type == "UNKNOWN_MEDIA":
            return "📎 Contenido multimedia"

        return "Mensaje sin contenido"


    def _message_reply(message):
        """Devuelve metadata semántica de respuesta citada."""
        metadata = (
            message.metadata
            or {}
        )

        if not isinstance(
            metadata,
            dict,
        ):
            return None

        reply = metadata.get(
            "reply"
        )

        if not isinstance(
            reply,
            dict,
        ):
            return None

        body_text = str(
            reply.get(
                "body_text"
            )
            or ""
        ).strip()

        if not body_text:
            return None

        sender = str(
            reply.get(
                "sender"
            )
            or ""
        ).strip()

        return {
            "body_text":
                body_text,
            "sender":
                sender or None,
            "provider_message_id":
                reply.get(
                    "provider_message_id"
                ),
        }


    def _message_time(message):
        value = str(
            message.provider_timestamp
            or ""
        ).strip()

        if not value:
            return ""

        if (
            len(value) >= 16
            and "T" in value
        ):
            return value[11:16]

        return value


    # COM-8FA4B2E3 · Índice de controles de estado visibles.
    #
    # Solo contiene controles actualmente construidos para el
    # historial central. Permite avanzar ✓ / ✓✓ sin reconstruir
    # las 50/100/150 burbujas visibles.
    message_status_controls = {}


    def _message_status_identity(
        message,
    ):
        identity = _message_identity(
            message
        )

        if identity in (
            None,
            "",
        ):
            return None

        return identity


    def _message_status_symbol(message):
        if str(
            message.direction
            or ""
        ).strip().upper() != "OUTBOUND":
            return ""

        status = str(
            message.status
            or ""
        ).strip().upper()

        if status == "READ":
            return "✓✓"

        if status == "DELIVERED":
            return "✓✓"

        if status in (
            "SENT",
            "SENDING",
            "QUEUED",
        ):
            return "✓"

        return ""


    def _message_scroll_key(
        message,
    ):
        """Key estable usada para preservar el viewport."""
        message_id = getattr(
            message,
            "id",
            None,
        )

        if message_id not in (
            None,
            "",
        ):
            return (
                "wa-message-db-"
                + str(
                    int(
                        message_id
                    )
                )
            )

        provider_id = str(
            getattr(
                message,
                "provider_message_id",
                None,
            )
            or ""
        ).strip()

        if provider_id:
            return (
                "wa-message-provider-"
                + provider_id
            )

        return None


    def _build_message_bubble(
        message,
    ):
        outbound = (
            str(
                message.direction
                or ""
            ).strip().upper()
            == "OUTBOUND"
        )

        footer_controls = []

        timestamp = _message_time(
            message
        )

        if timestamp:
            footer_controls.append(
                ft.Text(
                    timestamp,
                    size=9,
                    color=Q_MUTED,
                )
            )

        status_symbol = (
            _message_status_symbol(
                message
            )
        )

        if outbound:
            status_control = ft.Text(
                status_symbol,
                size=10,
                color=Q_PRIMARY,
                weight=(
                    ft.FontWeight.BOLD
                ),
            )

            status_identity = (
                _message_status_identity(
                    message
                )
            )

            if status_identity is not None:
                message_status_controls[
                    status_identity
                ] = status_control

            footer_controls.append(
                status_control
            )

        content_controls = []

        reply = _message_reply(
            message
        )

        if reply:
            reply_title = (
                reply.get(
                    "sender"
                )
                or "Respuesta a mensaje"
            )

            content_controls.append(
                ft.Container(
                    padding=ft.padding.symmetric(
                        horizontal=9,
                        vertical=7,
                    ),
                    bgcolor=(
                        "#DDEBFB"
                        if outbound
                        else "#F3F4F6"
                    ),
                    border_radius=8,
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                reply_title,
                                size=9,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY,
                            ),
                            ft.Text(
                                reply[
                                    "body_text"
                                ],
                                size=10,
                                color=Q_MUTED,
                                max_lines=3,
                                overflow=(
                                    ft.TextOverflow.ELLIPSIS
                                ),
                                selectable=True,
                            ),
                        ],
                        spacing=2,
                    ),
                )
            )

        content_controls.append(
            ft.Text(
                _message_body(
                    message
                ),
                size=12,
                color=Q_TEXT,
                selectable=True,
            )
        )

        content_controls.append(
            ft.Row(
                controls=(
                    footer_controls
                ),
                alignment=(
                    ft.MainAxisAlignment.END
                ),
                spacing=4,
            )
        )

        bubble = ft.Container(
            width=360,
            padding=ft.padding.symmetric(
                horizontal=12,
                vertical=9,
            ),
            bgcolor=(
                "#EAF3FF"
                if outbound
                else Q_WHITE
            ),
            border=ft.border.all(
                1,
                (
                    "#C7DCF8"
                    if outbound
                    else Q_BORDER
                ),
            ),
            border_radius=12,
            content=ft.Column(
                controls=content_controls,
                spacing=5,
            ),
        )

        return ft.Row(
            key=_message_scroll_key(
                message
            ),
            controls=[
                bubble,
            ],
            alignment=(
                ft.MainAxisAlignment.END
                if outbound
                else ft.MainAxisAlignment.START
            ),
        )


    # Control persistente del historial.
    #
    # Mantener una referencia estable permite:
    # - refrescar solo los mensajes en fases posteriores;
    # - controlar el scroll de forma imperativa;
    # - garantizar que el último mensaje quede visible.
    message_history_control = ft.Column(
        controls=[],
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
        scroll_interval=50,
        expand=True,
    )


    async def _load_older_message_history():
        """Añade una página anterior sin cambiar lo que lee el usuario."""
        if state.get(
            "message_history_loading_older"
        ):
            return False

        if not state.get(
            "message_history_has_more",
            True,
        ):
            return False

        thread_id = state.get(
            "selected_thread_id"
        )

        messages = list(
            state.get(
                "messages"
            )
            or []
        )

        if (
            thread_id in (
                None,
                "",
            )
            or not messages
        ):
            return False

        oldest_message = messages[
            0
        ]

        oldest_message_id = getattr(
            oldest_message,
            "id",
            None,
        )

        if oldest_message_id in (
            None,
            "",
        ):
            return False

        anchor_key = (
            _message_scroll_key(
                oldest_message
            )
        )

        if not anchor_key:
            return False

        generation = int(
            state.get(
                "routing_generation"
            )
            or 0
        )

        page_size = max(
            1,
            int(
                state.get(
                    "message_history_page_size"
                )
                or 50
            ),
        )

        state[
            "message_history_loading_older"
        ] = True

        # Una llegada deliberada al inicio concede una sola
        # carga. El permiso se consume antes del prepend para
        # impedir encadenar páginas automáticamente.
        state[
            "message_history_top_load_armed"
        ] = False

        # Desde este instante los eventos generados por el
        # prepend y por scroll_to(anchor) no pueden rearmar
        # otra página. Hace falta una separación real del
        # borde superior antes de admitir una nueva carga.
        state[
            "message_history_top_rearm_required"
        ] = True

        # La acción humana que originó esta página queda
        # consumida. Ningún UPDATE tardío del prepend puede
        # solicitar otra página sin un nuevo ScrollType.USER.
        state[
            "message_history_user_scroll_active"
        ] = False

        # En este punto venimos del evento que alcanzó el
        # borde superior, por lo que estas métricas representan
        # exactamente el viewport anterior al prepend.
        previous_scroll_pixels = state.get(
            "message_history_last_scroll_pixels"
        )

        previous_max_scroll_extent = state.get(
            "message_history_last_max_scroll_extent"
        )


        try:
            older_messages = await asyncio.to_thread(
                lambda: list(
                    communication_service
                    .list_thread_messages_before(
                        int(
                            thread_id
                        ),
                        before_message_id=int(
                            oldest_message_id
                        ),
                        limit=page_size,
                    )
                    or []
                )
            )

            # El usuario pudo cambiar de conversación mientras
            # SQLite trabajaba en background.
            if (
                state.get(
                    "selected_thread_id"
                )
                != thread_id
                or int(
                    state.get(
                        "routing_generation"
                    )
                    or 0
                )
                != generation
            ):
                return False

            if not older_messages:
                state[
                    "message_history_has_more"
                ] = False


                return False

            current_messages = list(
                state.get(
                    "messages"
                )
                or []
            )

            current_ids = {
                _message_identity(
                    message
                )
                for message in current_messages
            }

            unique_older = [
                message
                for message in older_messages
                if _message_identity(
                    message
                )
                not in current_ids
            ]

            if not unique_older:
                state[
                    "message_history_has_more"
                ] = False
                return False

            state[
                "messages"
            ] = (
                unique_older
                + current_messages
            )

            state[
                "message_history_window_size"
            ] = len(
                state[
                    "messages"
                ]
            )

            state[
                "message_history_expanded"
            ] = True

            state[
                "message_history_follow_bottom"
            ] = False

            # Si la página vino incompleta ya hemos alcanzado
            # el inicio histórico.
            state[
                "message_history_has_more"
            ] = (
                len(
                    older_messages
                )
                >= page_size
            )

            older_controls = [
                _build_message_bubble(
                    message
                )
                for message in unique_older
            ]

            message_history_control.controls[
                0:0
            ] = older_controls

            # No bloqueamos esperando el relayout de Flutter.
            #
            # Dejamos registrada la geometría anterior. El primer
            # OnScrollEvent que observe que max_scroll_extent ha
            # crecido aplicará la compensación exacta.
            if (
                previous_scroll_pixels
                is not None
                and previous_max_scroll_extent
                is not None
            ):
                state[
                    "message_history_pending_viewport_preserve"
                ] = {
                    "thread_id":
                        thread_id,
                    "generation":
                        generation,
                    "previous_pixels":
                        float(
                            previous_scroll_pixels
                        ),
                    "previous_max":
                        float(
                            previous_max_scroll_extent
                        ),
                }


            else:
                state[
                    "message_history_pending_viewport_preserve"
                ] = None

                # Fallback excepcional: si no disponemos de
                # geometría previa seguimos usando la clave
                # estable del mensaje anterior.
                state[
                    "message_history_programmatic_scroll"
                ] = True

                try:
                    await message_history_control.scroll_to(
                        scroll_key=anchor_key,
                        duration=0,
                    )

                    await asyncio.sleep(
                        0.12
                    )

                finally:
                    state[
                        "message_history_programmatic_scroll"
                    ] = False

                print(
                    "[WA-FLET] history viewport fallback anchor",
                    {
                        "reason":
                            "PREVIOUS_GEOMETRY_MISSING",
                    },
                    flush=True,
                )

            message_history_control.update()


            return True

        except Exception as exc:
            print(
                "[WA-FLET] load older history failed",
                repr(
                    exc
                ),
                flush=True,
            )

            return False

        finally:
            state[
                "message_history_loading_older"
            ] = False


    async def _on_message_history_scroll(
        event,
    ):
        """Gestiona follow-bottom y paginación al alcanzar el inicio."""
        event_type = getattr(
            event,
            "event_type",
            None,
        )

        direction = getattr(
            event,
            "direction",
            None,
        )

        # Guardamos la geometría incluso para eventos que luego
        # serán ignorados por la máquina de estados.
        #
        # Los UPDATE emitidos durante el relayout del prepend son
        # precisamente los que nos indican cuánto creció el
        # contenido por encima del viewport.
        try:
            scroll_pixels = float(
                getattr(
                    event,
                    "pixels",
                    0.0,
                )
                or 0.0
            )

            max_scroll_extent = float(
                getattr(
                    event,
                    "max_scroll_extent",
                    0.0,
                )
                or 0.0
            )

            state[
                "message_history_last_scroll_pixels"
            ] = scroll_pixels

            state[
                "message_history_last_max_scroll_extent"
            ] = max_scroll_extent

        except Exception:
            scroll_pixels = None
            max_scroll_extent = None

        # RESTAURACIÓN DIFERIDA DEL VIEWPORT.
        #
        # Se ejecuta únicamente cuando Flutter ya ha comunicado
        # que el contenido creció después del prepend.
        pending_preserve = state.get(
            "message_history_pending_viewport_preserve"
        )

        if (
            pending_preserve
            and scroll_pixels is not None
            and max_scroll_extent is not None
        ):
            pending_thread_id = (
                pending_preserve.get(
                    "thread_id"
                )
            )

            pending_generation = int(
                pending_preserve.get(
                    "generation"
                )
                or 0
            )

            previous_pixels = float(
                pending_preserve.get(
                    "previous_pixels"
                )
                or 0.0
            )

            previous_max = float(
                pending_preserve.get(
                    "previous_max"
                )
                or 0.0
            )

            # Si el usuario cambió de conversación la restauración
            # anterior deja de ser válida.
            if (
                state.get(
                    "selected_thread_id"
                )
                != pending_thread_id
                or int(
                    state.get(
                        "routing_generation"
                    )
                    or 0
                )
                != pending_generation
            ):
                state[
                    "message_history_pending_viewport_preserve"
                ] = None

            elif (
                max_scroll_extent
                > previous_max + 1.0
            ):
                inserted_extent = max(
                    0.0,
                    max_scroll_extent
                    - previous_max,
                )

                preserved_offset = (
                    previous_pixels
                    + inserted_extent
                )

                # Consumimos la restauración ANTES de scroll_to
                # para que cualquier evento reentrante no pueda
                # aplicar una segunda compensación.
                state[
                    "message_history_pending_viewport_preserve"
                ] = None

                state[
                    "message_history_programmatic_scroll"
                ] = True

                try:
                    await message_history_control.scroll_to(
                        offset=preserved_offset,
                        duration=0,
                    )

                finally:
                    state[
                        "message_history_programmatic_scroll"
                    ] = False


                return

            else:
                # Mientras Flutter no haya comunicado el nuevo
                # extent no interpretamos estos eventos como una
                # nueva navegación histórica.
                return

        # Flet 0.84 distingue explícitamente el evento de
        # navegación del usuario de los UPDATE de posición.
        #
        # Esta es la fuente autoritativa de intención humana
        # para la paginación histórica.
        if event_type == ft.ScrollType.USER:
            if direction == ft.ScrollDirection.IDLE:
                state[
                    "message_history_user_scroll_active"
                ] = False


            else:
                state[
                    "message_history_user_scroll_active"
                ] = True


            # USER comunica intención/dirección.
            # La posición se procesa con UPDATEs posteriores.
            return

        if state.get(
            "message_history_programmatic_scroll"
        ):
            return

        # Mientras una página histórica está siendo insertada,
        # Flet puede emitir múltiples eventos de scroll causados
        # por:
        # - update() del Column;
        # - cambio de extent;
        # - scroll_to(anchor);
        # - relayout progresivo.
        #
        # Ninguno de ellos puede modificar los estados de
        # inicialización, rearme o armado. La carga actual debe
        # terminar completamente antes de interpretar otro
        # movimiento como intención del usuario.
        if state.get(
            "message_history_loading_older"
        ):
            return

        try:
            extent_after = float(
                getattr(
                    event,
                    "extent_after",
                    0.0,
                )
                or 0.0
            )

            extent_before = float(
                getattr(
                    event,
                    "extent_before",
                    0.0,
                )
                or 0.0
            )

        except Exception:
            return

        # Si estamos prácticamente al final, el usuario vuelve
        # a seguir el realtime automáticamente.
        at_bottom = (
            extent_after
            <= 40.0
        )

        state[
            "message_history_follow_bottom"
        ] = at_bottom

        # Estar abajo no puede dejar preparada una carga
        # histórica. También cubre el posicionamiento inicial
        # del historial al último mensaje.
        if at_bottom:
            state[
                "message_history_top_load_armed"
            ] = False

            state[
                "message_history_top_rearm_required"
            ] = False

            if not state.get(
                "message_history_scroll_initialized",
                False,
            ):
                state[
                    "message_history_scroll_initialized"
                ] = True


            return

        # Antes de haber confirmado el fondo, cualquier
        # on_scroll pertenece potencialmente al montaje o
        # reposicionamiento inicial de Flet.
        if not state.get(
            "message_history_scroll_initialized",
            False,
        ):
            return

        # Los cambios de posición por sí solos no son prueba de
        # interacción humana. Flet emite UPDATEs también durante
        # relayout y scroll_to().
        #
        # Para armar/rearmar/cargar histórico exigimos haber
        # recibido antes ScrollType.USER no-idle.
        if not state.get(
            "message_history_user_scroll_active",
            False,
        ):
            return

        # REARME DESPUÉS DE PREPEND.
        #
        # Los eventos residuales observados tras scroll_to(anchor)
        # pueden presentar extent_before pequeño (>40) y volver
        # a disparar otra página sin intervención real.
        #
        # Exigimos alejarnos al menos 300 px del inicio. El evento
        # que libera el gate NO arma todavía: hace falta un evento
        # posterior de navegación para ello.
        if state.get(
            "message_history_top_rearm_required",
            False,
        ):
            if extent_before > 300.0:
                state[
                    "message_history_top_rearm_required"
                ] = False


            return

        # ARMADO DETERMINISTA.
        #
        # Solo interpretamos una futura llegada arriba como
        # intención humana cuando antes observamos el viewport
        # claramente alejado del borde superior.
        #
        # Por tanto, un on_scroll inicial con extent_before=0
        # nunca puede provocar _load_older_message_history().
        if extent_before > 40.0:
            if not state.get(
                "message_history_top_load_armed",
                False,
            ):
                state[
                    "message_history_top_load_armed"
                ] = True


            return

        if (
            extent_before
            > 24.0
            or not state.get(
                "message_history_top_load_armed",
                False,
            )
            or state.get(
                "message_history_loading_older"
            )
            or not state.get(
                "message_history_has_more",
                True,
            )
        ):
            return


        await _load_older_message_history()


    message_history_control.on_scroll = (
        _on_message_history_scroll
    )


    async def _scroll_message_history_to_bottom():
        """Fuerza el historial visible al último mensaje."""
        try:
            if not (
                state.get("messages")
                or []
            ):
                return

            await message_history_control.scroll_to(
                offset=-1,
                duration=0,
            )


        except Exception as exc:
            # El scroll es comportamiento UI. Un control
            # todavía no montado nunca debe romper la vista.
            print(
                "[WA-FLET] bottom scroll skipped",
                repr(exc),
                flush=True,
            )


    def _force_message_history_bottom():
        """Programa el salto al final tras actualizar la UI."""
        if not (
            state.get("messages")
            or []
        ):
            return

        # Si el usuario está leyendo histórico, un mensaje nuevo
        # no puede robarle el viewport.
        if not state.get(
            "message_history_follow_bottom",
            True,
        ):
            return

        runner = getattr(
            page,
            "run_task",
            None,
        )

        if not callable(runner):
            print(
                "[WA-FLET] bottom scroll unavailable: "
                "page.run_task missing",
                flush=True,
            )
            return

        try:
            runner(
                _scroll_message_history_to_bottom
            )
        except Exception as exc:
            print(
                "[WA-FLET] bottom scroll schedule failed",
                repr(exc),
                flush=True,
            )


    def _message_identity(message):
        """Identidad estable para reconciliar controles visibles."""
        message_id = getattr(
            message,
            "id",
            None,
        )

        if message_id not in (
            None,
            "",
        ):
            return (
                "DB",
                int(
                    message_id
                ),
            )

        provider_id = str(
            getattr(
                message,
                "provider_message_id",
                None,
            )
            or ""
        ).strip()

        if provider_id:
            return (
                "PROVIDER",
                provider_id,
            )

        return None


    def _append_new_message_history_controls(
        previous_messages,
    ):
        """Actualiza incrementalmente una ventana reciente.

        Fast paths admitidos:

        1. APPEND NORMAL
           previous es prefijo exacto de current.

        2. VENTANA DESLIZANTE
           current mantiene la cola de previous y añade al final
           el mismo número de mensajes que salieron por arriba.

        Cualquier situación distinta degrada al refresh completo.
        """
        if state.get(
            "messages_error"
        ):
            return False

        current_messages = list(
            state.get(
                "messages"
            )
            or []
        )

        previous_messages = list(
            previous_messages
            or []
        )

        if (
            not previous_messages
            or not current_messages
        ):
            return False

        previous_ids = [
            _message_identity(
                message
            )
            for message in previous_messages
        ]

        current_ids = [
            _message_identity(
                message
            )
            for message in current_messages
        ]

        if (
            any(
                identity is None
                for identity in previous_ids
            )
            or any(
                identity is None
                for identity in current_ids
            )
        ):
            return False


        # --------------------------------------------------
        # FAST PATH 1 · crecimiento sin alcanzar la ventana
        # --------------------------------------------------
        if (
            len(
                current_ids
            )
            > len(
                previous_ids
            )
            and current_ids[
                :len(
                    previous_ids
                )
            ]
            == previous_ids
        ):
            new_messages = current_messages[
                len(
                    previous_messages
                ):
            ]

            if not new_messages:
                return False

            message_history_control.controls.extend(
                [
                    _build_message_bubble(
                        message
                    )
                    for message in new_messages
                ]
            )

            try:
                message_history_control.update()

            except Exception as exc:
                message_history_control.controls = [
                    _build_message_bubble(
                        message
                    )
                    for message in current_messages
                ]

                print(
                    "[WA-FLET] incremental history unavailable",
                    repr(
                        exc
                    ),
                    flush=True,
                )

                return False

            _force_message_history_bottom()


            return True

        # --------------------------------------------------
        # FAST PATH 2 · ventana llena desplazada
        # --------------------------------------------------
        if (
            len(
                current_ids
            )
            == len(
                previous_ids
            )
        ):
            window_size = len(
                current_ids
            )

            shift = None

            # Buscamos cuántos elementos salieron por arriba.
            # El caso habitual es 1; el bucle también cubre
            # ráfagas de varios mensajes.
            for candidate_shift in range(
                1,
                window_size,
            ):
                if (
                    previous_ids[
                        candidate_shift:
                    ]
                    == current_ids[
                        :window_size
                        - candidate_shift
                    ]
                ):
                    shift = candidate_shift
                    break

            if shift is not None:
                new_messages = current_messages[
                    -shift:
                ]

                if (
                    len(
                        message_history_control.controls
                    )
                    != len(
                        previous_messages
                    )
                ):
                    return False

                # Eliminamos solo las burbujas que salieron de
                # la ventana y añadimos únicamente las nuevas.
                del message_history_control.controls[
                    :shift
                ]

                message_history_control.controls.extend(
                    [
                        _build_message_bubble(
                            message
                        )
                        for message in new_messages
                    ]
                )

                try:
                    message_history_control.update()

                except Exception as exc:
                    message_history_control.controls = [
                        _build_message_bubble(
                            message
                        )
                        for message in current_messages
                    ]

                    print(
                        "[WA-FLET] sliding history unavailable",
                        repr(
                            exc
                        ),
                        flush=True,
                    )

                    return False

                _force_message_history_bottom()


                return True

        return False


    def _update_advanced_message_status_controls(
        previous_messages,
        current_messages,
        sync_items,
    ):
        """Actualiza solo los ticks de mensajes cuyo estado avanzó."""
        advanced_items = [
            item
            for item in (
                sync_items
                or []
            )
            if bool(
                item.get(
                    "status_advanced"
                )
            )
        ]

        if not advanced_items:
            return False

        current_by_id = {}

        current_by_provider_id = {}

        for message in (
            current_messages
            or []
        ):
            message_id = getattr(
                message,
                "id",
                None,
            )

            if message_id not in (
                None,
                "",
            ):
                current_by_id[
                    int(
                        message_id
                    )
                ] = message

            provider_id = str(
                getattr(
                    message,
                    "provider_message_id",
                    None,
                )
                or ""
            ).strip()

            if provider_id:
                current_by_provider_id[
                    provider_id
                ] = message

        updated = 0

        missing = 0

        for item in advanced_items:
            message = None

            item_message_id = item.get(
                "message_id"
            )

            if item_message_id not in (
                None,
                "",
            ):
                try:
                    message = current_by_id.get(
                        int(
                            item_message_id
                        )
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    message = None

            if message is None:
                provider_id = str(
                    item.get(
                        "provider_message_id"
                    )
                    or ""
                ).strip()

                if provider_id:
                    message = (
                        current_by_provider_id.get(
                            provider_id
                        )
                    )

            if message is None:
                missing += 1
                continue

            identity = (
                _message_status_identity(
                    message
                )
            )

            if identity is None:
                missing += 1
                continue

            control = (
                message_status_controls.get(
                    identity
                )
            )

            if control is None:
                missing += 1
                continue

            symbol = (
                _message_status_symbol(
                    message
                )
            )

            if str(
                control.value
                or ""
            ) == symbol:
                updated += 1
                continue

            control.value = symbol

            try:
                control.update()

            except Exception as exc:
                print(
                    "[WA-FLET] individual status update unavailable",
                    {
                        "identity":
                            identity,
                        "error":
                            repr(
                                exc
                            ),
                    },
                    flush=True,
                )

                return False

            updated += 1

        success = (
            updated
            == len(
                advanced_items
            )
        )


        return success


    def _refresh_message_history_control():
        """Actualiza únicamente el historial ya montado.

        Devuelve True si pudo aplicar el refresh ligero.
        Si el control no está montado o existe un estado
        vacío/error, el caller puede degradar a _safe_update().
        """
        if state.get(
            "messages_error"
        ):
            return False

        messages = list(
            state.get(
                "messages"
            )
            or []
        )

        if not messages:
            return False

        message_status_controls.clear()

        message_history_control.controls = [
            _build_message_bubble(
                message
            )
            for message in messages
        ]

        try:
            message_history_control.update()

        except Exception as exc:
            print(
                "[WA-FLET] light history refresh unavailable",
                repr(exc),
                flush=True,
            )
            return False

        _force_message_history_bottom()

        return True


    def _build_message_history():
        error = state.get(
            "messages_error"
        )

        if error:
            return ft.Container(
                expand=True,
                alignment=ft.Alignment(
                    0,
                    0,
                ),
                content=ft.Column(
                    controls=[
                        ft.Icon(
                            ft.Icons.ERROR_OUTLINE,
                            color="#B42318",
                            size=30,
                        ),
                        ft.Text(
                            "No se pudo cargar el historial",
                            weight=(
                                ft.FontWeight.BOLD
                            ),
                            color="#B42318",
                        ),
                        ft.Text(
                            str(error),
                            size=10,
                            color=Q_MUTED,
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
            )

        messages = list(
            state.get(
                "messages"
            )
            or []
        )

        if not messages:
            return ft.Container(
                expand=True,
                alignment=ft.Alignment(
                    0,
                    0,
                ),
                content=ft.Column(
                    controls=[
                        ft.Text(
                            "💬",
                            size=40,
                        ),
                        ft.Text(
                            "No hay mensajes sincronizados todavía",
                            size=15,
                            weight=(
                                ft.FontWeight.BOLD
                            ),
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            (
                                "La conversación está registrada, "
                                "pero todavía no contiene historial."
                            ),
                            size=11,
                            color=Q_MUTED,
                            text_align=(
                                ft.TextAlign.CENTER
                            ),
                        ),
                    ],
                    spacing=7,
                    horizontal_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                    alignment=(
                        ft.MainAxisAlignment.CENTER
                    ),
                ),
            )

        message_status_controls.clear()

        message_history_control.controls = [
            _build_message_bubble(
                message
            )
            for message in messages
        ]

        return message_history_control


    composer_input = ft.TextField(
        hint_text="Escribir mensaje...",
        border_radius=10,
        expand=True,
        multiline=True,
        min_lines=1,
        max_lines=4,
    )

    send_button = primary_button(
        "Enviar",
        None,
    )

    def _selected_thread_send_blocked():
        thread_id = state.get(
            "selected_thread_id"
        )

        if thread_id is None:
            return False

        return (
            int(thread_id)
            in state.get(
                "send_blocked_thread_ids",
                set(),
            )
        )

    def _refresh_composer_controls():
        has_thread = (
            state.get(
                "selected_thread_id"
            )
            is not None
        )

        unavailable = (
            whatsapp_runtime is None
        )

        blocked = (
            _selected_thread_send_blocked()
        )

        sending = bool(
            state.get(
                "sending"
            )
        )

        composer_input.disabled = (
            not has_thread
            or unavailable
            or blocked
            or sending
        )

        send_button.disabled = (
            not has_thread
            or unavailable
            or blocked
            or sending
        )

    def _clear_composer():
        composer_input.value = ""

    def _run_background(
        target,
    ):
        runner = getattr(
            page,
            "run_thread",
            None,
        )

        if callable(runner):
            runner(target)
            return

        # No ejecutamos el transporte de WhatsApp
        # en el hilo UI como fallback silencioso.
        raise RuntimeError(
            "Esta versión de Flet no dispone "
            "de page.run_thread()"
        )

    async def _finish_whatsapp_route_ui(
        thread_id,
        generation,
        verified,
    ):
        """Finaliza visualmente un routing dentro del loop Flet."""
        thread_id = int(
            thread_id
        )

        generation = int(
            generation
        )

        current_generation = int(
            state.get(
                "routing_generation"
            )
            or 0
        )

        current_target = state.get(
            "routing_target_thread_id"
        )

        # Worker obsoleto: no puede alterar la selección nueva.
        if (
            current_generation
            != generation
            or current_target
            != thread_id
        ):
            return

        if verified:
            # Si WhatsApp confirmó que realmente abrió el thread
            # solicitado, la conversación está siendo atendida.
            _mark_realtime_thread_read(
                thread_id,
                refresh_sidebar=False,
            )

        state[
            "routing_target_thread_id"
        ] = None


        flushed = (
            _flush_pending_whatsapp_sidebar()
        )

        # Aunque no hubiera deltas pendientes, puede haber cambiado
        # unread del thread seleccionado.
        if (
            verified
            and not flushed
        ):
            try:
                _refresh_conversation_list_control()
            except Exception:
                pass



    def _schedule_finish_whatsapp_route_ui(
        thread_id,
        generation,
        verified,
    ):
        runner = getattr(
            page,
            "run_task",
            None,
        )

        if not callable(
            runner
        ):
            return

        runner(
            _finish_whatsapp_route_ui,
            int(
                thread_id
            ),
            int(
                generation
            ),
            bool(
                verified
            ),
        )


    def _route_whatsapp_thread(
        thread_id,
        *,
        generation=None,
    ):
        if whatsapp_runtime is None:
            return False

        captured_thread_id = int(
            thread_id
        )

        captured_generation = int(
            generation
            if generation is not None
            else (
                state.get(
                    "routing_generation"
                )
                or 0
            )
        )

        def worker():
            verified = False

            try:
                if not whatsapp_runtime.started:
                    whatsapp_runtime.start()

                watch_thread = (
                    whatsapp_runtime
                    .start_active_chat_watch(
                        interval_seconds=0.5,
                        wait_timeout=5,
                        on_change=(
                            _schedule_whatsapp_watch_change
                        ),
                    )
                )



                result = (
                    whatsapp_runtime
                    .open_thread_for_selection(
                        captured_thread_id
                    )
                )


                # Una selección obsoleta se descarta
                # silenciosamente. No es un error para
                # el usuario: existe otra selección más
                # reciente esperando ser aplicada.
                if (
                    isinstance(
                        result,
                        dict,
                    )
                    and result.get(
                        "skipped"
                    )
                ):
                    return

                # Para finalizar visualmente el routing basta
                # con que la navegación solicitada haya abierto
                # correctamente el chat. Esto NO significa que
                # el envío esté pre-verificado.
                verified = bool(
                    isinstance(
                        result,
                        dict,
                    )
                    and (
                        result.get(
                            "routing"
                        )
                        or {}
                    ).get(
                        "opened"
                    )
                )

            except Exception as exc:
                # Una selección anterior puede terminar
                # mientras el usuario ya ha elegido otra.
                # Solo mostramos el error si sigue siendo
                # la conversación actualmente seleccionada.
                if (
                    state.get(
                        "selected_thread_id"
                    )
                    == captured_thread_id
                ):
                    _schedule_ui_message(
                        (
                            "No se pudo abrir la "
                            "conversación en WhatsApp: "
                            f"{exc}"
                        ),
                        error=True,
                    )

            finally:
                # Toda finalización visual vuelve al event loop
                # Flet. El worker Selenium/WhatsApp no toca
                # controles ni libera visualmente el routing.
                _schedule_finish_whatsapp_route_ui(
                    captured_thread_id,
                    captured_generation,
                    verified,
                )

        _run_background(
            worker
        )

        return True

    async def _dispatch_finish_send_ui(
        thread_id,
        sent_text,
        result,
        exception,
    ):
        """Finaliza un envío dentro del event loop de Flet.

        El transporte WhatsApp se ejecuta en background.
        Las mutaciones visuales regresan siempre al loop Flet.
        """
        try:
            _finish_send_ui(
                thread_id=int(
                    thread_id
                ),
                sent_text=str(
                    sent_text
                    or ""
                ),
                result=result,
                exception=exception,
            )

        except Exception as exc:
            print(
                "[WA-FLET] send finish dispatch failed",
                repr(
                    exc
                ),
                flush=True,
            )

    def _schedule_finish_send_ui(
        *,
        thread_id,
        sent_text,
        result=None,
        exception=None,
    ):
        runner = getattr(
            page,
            "run_task",
            None,
        )

        if not callable(
            runner
        ):
            print(
                "[WA-FLET] send finish dispatch unavailable: "
                "page.run_task missing",
                flush=True,
            )
            return False

        try:
            runner(
                _dispatch_finish_send_ui,
                int(
                    thread_id
                ),
                str(
                    sent_text
                    or ""
                ),
                result,
                exception,
            )

            return True

        except Exception as exc:
            print(
                "[WA-FLET] send finish schedule failed",
                repr(
                    exc
                ),
                flush=True,
            )

            return False


    def _finish_send_ui(
        *,
        thread_id,
        sent_text,
        result=None,
        exception=None,
    ):
        uncertain = bool(
            result
            and result.get(
                "uncertain",
                False,
            )
        )

        ok = bool(
            result
            and result.get(
                "ok",
                False,
            )
        )

        if uncertain:
            state.setdefault(
                "send_blocked_thread_ids",
                set(),
            ).add(
                int(thread_id)
            )

        state["sending"] = False

        selected_same_thread = (
            state.get(
                "selected_thread_id"
            )
            == int(thread_id)
        )

        # Actualización ligera de UI tras envío.
        #
        # Si el usuario sigue viendo el mismo thread,
        # no necesitamos recargar sidebar, métricas,
        # filtros ni contexto.
        #
        # El servicio de envío ya ha persistido el estado
        # outbound; recuperamos únicamente el historial.
        light_send_refresh = False

        if selected_same_thread:
            try:
                previous_messages = list(
                    state.get(
                        "messages"
                    )
                    or []
                )

                # Durante lectura histórica conservamos también
                # la página expandida al añadir nuestro outbound.
                if (
                    ok
                    and state.get(
                        "message_history_expanded"
                    )
                ):
                    state[
                        "message_history_window_size"
                    ] = (
                        max(
                            len(
                                previous_messages
                            ),
                            int(
                                state.get(
                                    "message_history_window_size"
                                )
                                or 0
                            ),
                        )
                        + 1
                    )


                load_thread_messages()



                # El servicio de envío ya persistió el outbound.
                # Intentamos exactamente el mismo fast path
                # demostrado con mensajes entrantes: historial
                # anterior como prefijo + mensajes nuevos al final.
                light_send_refresh = (
                    _append_new_message_history_controls(
                        previous_messages
                    )
                )

                if not light_send_refresh:
                    light_send_refresh = (
                        _refresh_message_history_control()
                    )


            except Exception as exc:
                print(
                    "[WA-FLET] send finish light refresh failed",
                    repr(exc),
                    flush=True,
                )

                light_send_refresh = False

        if not light_send_refresh:
            # Si el usuario cambió de conversación durante
            # el envío, o el control visible no está montado,
            # conservamos el refresh completo probado.
            print(
                "[WA-FLET] send finish fallback full",
                {
                    "thread_id": int(thread_id),
                    "selected_thread_id":
                        state.get(
                            "selected_thread_id"
                        ),
                },
                flush=True,
            )

            try:
                load_data(
                    preserve_selection=True,
                )
            except Exception:
                pass

        if (
            ok
            and selected_same_thread
        ):
            # Una respuesta confirmada implica que el thread
            # está siendo atendido desde el CRM.
            _mark_realtime_thread_read(
                thread_id,
                refresh_sidebar=False,
            )

        if (
            ok
            and selected_same_thread
            and str(
                composer_input.value
                or ""
            )
            == sent_text
        ):
            _clear_composer()

        _refresh_composer_controls()

        if light_send_refresh:
            # El historial ya se actualizó de forma parcial.
            # Propagamos compositor y sidebar ligero: una
            # respuesta confirmada debe retirar el badge unread.
            try:
                _refresh_conversation_list_control()
                composer_input.update()
                send_button.update()
            except Exception:
                try:
                    page.update()
                except Exception:
                    pass

            _force_message_history_bottom()

        else:
            _safe_update()

        if exception is not None:
            _show_message(
                (
                    "No se pudo enviar el mensaje: "
                    f"{exception}"
                ),
                error=True,
            )
            return

        if uncertain:
            _show_message(
                (
                    "El estado del envío no pudo "
                    "confirmarse con seguridad. "
                    "No reenvíes este mensaje hasta "
                    "revisar la conversación."
                ),
                error=True,
            )
            return

        if not ok:
            error = (
                result.get(
                    "error"
                )
                if result
                else None
            )

            _show_message(
                (
                    "No se pudo enviar el mensaje"
                    + (
                        f": {error}"
                        if error
                        else "."
                    )
                ),
                error=True,
            )
            return

        _show_message(
            "Mensaje enviado correctamente."
        )

    def send_message(
        e=None,
    ):
        if state.get(
            "sending"
        ):
            return

        thread_id = state.get(
            "selected_thread_id"
        )

        if thread_id is None:
            _show_message(
                "Selecciona una conversación.",
                error=True,
            )
            return

        if _selected_thread_send_blocked():
            _show_message(
                (
                    "Esta conversación tiene un envío "
                    "con estado incierto. Revísalo antes "
                    "de volver a enviar."
                ),
                error=True,
            )
            return

        text_to_send = str(
            composer_input.value
            or ""
        ).strip()

        if not text_to_send:
            return

        if whatsapp_runtime is None:
            _show_message(
                (
                    "El runtime de WhatsApp "
                    "no está disponible."
                ),
                error=True,
            )
            return

        captured_thread_id = int(
            thread_id
        )

        state["sending"] = True
        _refresh_composer_controls()

        try:
            page.update()
        except Exception:
            pass

        username = str(
            current_username
            or "ERP"
        ).strip() or "ERP"

        def worker():
            try:
                result = (
                    whatsapp_runtime
                    .send_text_message(
                        thread_id=(
                            captured_thread_id
                        ),
                        body_text=(
                            text_to_send
                        ),
                        created_by=username,
                        sent_by=username,
                    )
                )

                _schedule_finish_send_ui(
                    thread_id=(
                        captured_thread_id
                    ),
                    sent_text=(
                        text_to_send
                    ),
                    result=result,
                )

            except Exception as exc:
                _schedule_finish_send_ui(
                    thread_id=(
                        captured_thread_id
                    ),
                    sent_text=(
                        text_to_send
                    ),
                    exception=exc,
                )

        try:
            _run_background(
                worker
            )

        except Exception as exc:
            state["sending"] = False
            _refresh_composer_controls()

            _show_message(
                str(exc),
                error=True,
            )

    send_button.on_click = (
        send_message
    )

    _refresh_composer_controls()


    def build_chat_panel():
        item = selected_item()

        if not item:
            return ft.Container(
                expand=True,
                bgcolor=Q_WHITE,
                border=ft.border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=14,
                padding=20,
                content=empty_state(
                    "Selecciona una conversación"
                ),
            )

        linked = _is_linked(
            item
        )

        return ft.Container(
            expand=True,
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            content=ft.Column(
                controls=[
                    ft.Container(
                        padding=16,
                        border=ft.border.only(
                            bottom=ft.BorderSide(
                                1,
                                Q_BORDER,
                            )
                        ),
                        content=ft.Row(
                            controls=[
                                _avatar(
                                    item
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            _display_name(
                                                item
                                            ),
                                            size=16,
                                            weight=(
                                                ft.FontWeight.BOLD
                                            ),
                                            color=Q_PRIMARY_DARK,
                                        ),
                                        ft.Row(
                                            controls=[
                                                ft.Text(
                                                    (
                                                        item.external_address
                                                        or "Sin teléfono"
                                                    ),
                                                    size=11,
                                                    color=Q_MUTED,
                                                ),
                                                ft.Text(
                                                    "•",
                                                    color=Q_MUTED,
                                                ),
                                                ft.Text(
                                                    (
                                                        item.channel
                                                        or "WHATSAPP"
                                                    ),
                                                    size=11,
                                                    color=Q_MUTED,
                                                ),
                                                _status_badge(
                                                    item
                                                ),
                                            ],
                                            spacing=7,
                                        ),
                                    ],
                                    spacing=3,
                                    expand=True,
                                ),
                            ],
                            spacing=10,
                        ),
                    ),
                    ft.Container(
                        expand=True,
                        padding=20,
                        bgcolor="#FAFBFD",
                        content=(
                            _build_message_history()
                        ),
                    ),
                    ft.Container(
                        padding=14,
                        border=ft.border.only(
                            top=ft.BorderSide(
                                1,
                                Q_BORDER,
                            )
                        ),
                        content=ft.Row(
                            controls=[
                                composer_input,
                                send_button,
                            ],
                            spacing=10,
                        ),
                    ),
                ],
                spacing=0,
                expand=True,
            ),
        )

    # COM-8FA4B · Hosts persistentes de la zona operativa.
    #
    # build_content() los monta una sola vez. Los cambios
    # ordinarios de conversación sustituyen únicamente su
    # contenido, sin reconstruir toda Comunicaciones.
    chat_panel_control = ft.Container(
        expand=True,
    )

    context_panel_control = ft.Container(
        width=310,
    )


    def _refresh_chat_panel_control():
        """Actualiza únicamente el panel central del chat."""

        chat_panel_control.content = (
            build_chat_panel()
        )

        try:
            chat_panel_control.update()

        except Exception as exc:
            print(
                "[WA-FLET] chat panel light refresh unavailable",
                repr(
                    exc
                ),
                flush=True,
            )
            return False


        _force_message_history_bottom()

        return True


    def _refresh_context_panel_control():
        """Actualiza únicamente el panel derecho de contexto."""

        context_panel_control.content = (
            build_context_panel()
        )

        try:
            context_panel_control.update()

        except Exception as exc:
            print(
                "[WA-FLET] context panel light refresh unavailable",
                repr(
                    exc
                ),
                flush=True,
            )
            return False


        return True


    def current_return_context():
        return {
            "view": "WhatsApp",
            "thread_id": state.get(
                "selected_thread_id"
            ),
        }

    def build_context_panel():
        item = selected_item()

        if not item:
            return ft.Container(
                width=310,
            )

        context = state.get(
            "context"
        )

        context_error = state.get(
            "context_error"
        )

        linked = _is_linked(
            item
        )

        def context_row(
            label,
            value,
        ):
            return ft.Row(
                controls=[
                    ft.Text(
                        label,
                        size=10,
                        color=Q_MUTED,
                        width=78,
                    ),
                    ft.Text(
                        str(
                            value
                            or "-"
                        ),
                        size=10,
                        color=Q_TEXT,
                        weight=ft.FontWeight.W_600,
                        expand=True,
                        overflow=(
                            ft.TextOverflow.ELLIPSIS
                        ),
                    ),
                ],
                spacing=8,
                vertical_alignment=(
                    ft.CrossAxisAlignment.START
                ),
            )

        if context_error:
            contact_content = [
                ft.Text(
                    "Resumen contacto",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Container(
                    padding=10,
                    border_radius=10,
                    bgcolor="#FEF3F2",
                    content=ft.Text(
                        (
                            "No se pudo cargar el "
                            "contexto del cliente."
                        ),
                        size=10,
                        color="#B42318",
                    ),
                ),
            ]

        elif (
            context
            and context.client
        ):
            client = context.client

            contact_content = [
                ft.Row(
                    controls=[
                        ft.Text(
                            "Resumen contacto",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK,
                            expand=True,
                        ),
                        *(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.OPEN_IN_NEW,
                                    tooltip=(
                                        "Abrir ficha del cliente"
                                    ),
                                    icon_size=18,
                                    icon_color=Q_PRIMARY,
                                    on_click=(
                                        lambda e,
                                        client_id=client.client_id:
                                            on_open_cliente(
                                                client_id,
                                                current_return_context(),
                                            )
                                    ),
                                )
                            ]
                            if on_open_cliente
                            else []
                        ),
                        *(
                            [
                                ft.IconButton(
                                    icon=(
                                        ft.Icons
                                        .CREATE_NEW_FOLDER_OUTLINED
                                    ),
                                    tooltip="Crear expediente",
                                    icon_size=18,
                                    icon_color=Q_PRIMARY,
                                    on_click=(
                                        lambda e,
                                        client_id=client.client_id:
                                            on_create_expediente(
                                                client_id,
                                                current_return_context(),
                                            )
                                    ),
                                )
                            ]
                            if on_create_expediente
                            else []
                        ),
                        *(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.TASK_ALT,
                                    tooltip="Crear tarea",
                                    icon_size=18,
                                    icon_color=Q_PRIMARY,
                                    on_click=(
                                        lambda e,
                                        client_id=client.client_id:
                                            on_create_task(
                                                client_id,
                                                None,
                                                current_return_context(),
                                            )
                                    ),
                                )
                            ]
                            if on_create_task
                            else []
                        ),
                        *(
                            [
                                ft.IconButton(
                                    icon=(
                                        ft.Icons
                                        .NOTIFICATIONS_NONE
                                    ),
                                    tooltip="Crear aviso",
                                    icon_size=18,
                                    icon_color=Q_PRIMARY,
                                    on_click=(
                                        lambda e,
                                        client_id=client.client_id:
                                            on_create_alert(
                                                client_id,
                                                None,
                                                current_return_context(),
                                            )
                                    ),
                                )
                            ]
                            if on_create_alert
                            else []
                        ),
                    ],
                    spacing=4,
                    vertical_alignment=(
                        ft.CrossAxisAlignment.CENTER
                    ),
                ),
                ft.Row(
                    controls=[
                        ft.Container(
                            width=38,
                            height=38,
                            border_radius=19,
                            bgcolor="#EAF3FF",
                            alignment=ft.Alignment(
                                0,
                                0,
                            ),
                            content=ft.Text(
                                "".join(
                                    part[0]
                                    for part
                                    in (
                                        client.full_name
                                        or "CL"
                                    ).split()[:2]
                                    if part
                                ).upper()
                                or "CL",
                                size=12,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                            ),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    client.full_name,
                                    size=12,
                                    weight=(
                                        ft.FontWeight.BOLD
                                    ),
                                    color=Q_PRIMARY_DARK,
                                    overflow=(
                                        ft.TextOverflow.ELLIPSIS
                                    ),
                                ),
                                ft.Text(
                                    (
                                        client.nationality
                                        or "Nacionalidad -"
                                    ),
                                    size=10,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    spacing=9,
                ),
                ft.Divider(
                    height=1,
                    color="#E4E7EC",
                ),
                context_row(
                    "Documento",
                    client.document,
                ),
                context_row(
                    "Teléfono",
                    client.phone,
                ),
                context_row(
                    "Email",
                    client.email,
                ),
                context_row(
                    "Estado",
                    client.status,
                ),
            ]

        else:
            contact_content = [
                ft.Text(
                    "Resumen contacto",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Row(
                    controls=[
                        _status_badge(
                            item
                        ),
                    ],
                ),
                ft.Text(
                    (
                        "No existe ningún cliente CRM "
                        "asociado a esta conversación."
                    ),
                    size=10,
                    color=Q_MUTED,
                ),
                context_row(
                    "WhatsApp",
                    (
                        item.external_address
                        or "-"
                    ),
                ),
                context_row(
                    "Nombre",
                    (
                        item.external_display_name
                        or "-"
                    ),
                ),
            ]

        contact_card = ft.Container(
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=contact_content,
                spacing=8,
            ),
        )

        expedients = (
            list(
                context.expedients
            )
            if (
                context
                and context.client
            )
            else []
        )

        expedient_controls = []

        for expedient in expedients:
            title = (
                expedient.number
                or (
                    f"Expediente "
                    f"{expedient.expedient_id}"
                )
            )

            type_text = " · ".join(
                value
                for value in (
                    expedient.type_name,
                    expedient.subtype_name,
                )
                if value
            )

            status_controls = []

            if (
                expedient.documentary_status
            ):
                status_controls.append(
                    ft.Text(
                        expedient.documentary_status,
                        size=9,
                        color="#175CD3",
                        weight=ft.FontWeight.W_600,
                    )
                )

            if (
                expedient.administrative_status
            ):
                status_controls.append(
                    ft.Text(
                        expedient.administrative_status,
                        size=9,
                        color="#475467",
                        weight=ft.FontWeight.W_600,
                    )
                )

            expedient_controls.append(
                ft.Container(
                    padding=10,
                    border_radius=10,
                    bgcolor="#F8FAFC",
                    border=ft.border.all(
                        1,
                        "#E4E7EC",
                    ),
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        title,
                                        size=11,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY_DARK,
                                        expand=True,
                                    ),
                                    *(
                                        [
                                            ft.IconButton(
                                                icon=(
                                                    ft.Icons
                                                    .OPEN_IN_NEW
                                                ),
                                                tooltip=(
                                                    "Abrir ficha "
                                                    "del expediente"
                                                ),
                                                icon_size=17,
                                                icon_color=(
                                                    Q_PRIMARY
                                                ),
                                                on_click=(
                                                    lambda e,
                                                    expedient_id=(
                                                        expedient
                                                        .expedient_id
                                                    ):
                                                        on_open_expediente(
                                                            expedient_id,
                                                            current_return_context(),
                                                        )
                                                ),
                                            )
                                        ]
                                        if on_open_expediente
                                        else []
                                    ),
                                    *(
                                        [
                                            ft.IconButton(
                                                icon=(
                                                    ft.Icons
                                                    .TASK_ALT
                                                ),
                                                tooltip=(
                                                    "Crear tarea "
                                                    "para este expediente"
                                                ),
                                                icon_size=17,
                                                icon_color=(
                                                    Q_PRIMARY
                                                ),
                                                on_click=(
                                                    lambda e,
                                                    client_id=(
                                                        context
                                                        .client
                                                        .client_id
                                                    ),
                                                    expedient_id=(
                                                        expedient
                                                        .expedient_id
                                                    ):
                                                        on_create_task(
                                                            client_id,
                                                            expedient_id,
                                                            current_return_context(),
                                                        )
                                                ),
                                            )
                                        ]
                                        if on_create_task
                                        else []
                                    ),
                                    *(
                                        [
                                            ft.IconButton(
                                                icon=(
                                                    ft.Icons
                                                    .NOTIFICATIONS_NONE
                                                ),
                                                tooltip=(
                                                    "Crear aviso "
                                                    "para este expediente"
                                                ),
                                                icon_size=17,
                                                icon_color=(
                                                    Q_PRIMARY
                                                ),
                                                on_click=(
                                                    lambda e,
                                                    client_id=(
                                                        context
                                                        .client
                                                        .client_id
                                                    ),
                                                    expedient_id=(
                                                        expedient
                                                        .expedient_id
                                                    ):
                                                        on_create_alert(
                                                            client_id,
                                                            expedient_id,
                                                            current_return_context(),
                                                        )
                                                ),
                                            )
                                        ]
                                        if on_create_alert
                                        else []
                                    ),
                                ],
                                spacing=2,
                            ),
                            (
                                ft.Text(
                                    expedient.family_name,
                                    size=9,
                                    color=Q_MUTED,
                                )
                                if expedient.family_name
                                else ft.Container(
                                    height=0,
                                )
                            ),
                            (
                                ft.Text(
                                    type_text,
                                    size=10,
                                    color=Q_TEXT,
                                    max_lines=2,
                                    overflow=(
                                        ft.TextOverflow.ELLIPSIS
                                    ),
                                )
                                if type_text
                                else ft.Container(
                                    height=0,
                                )
                            ),
                            *status_controls,
                        ],
                        spacing=3,
                    ),
                )
            )

        if not expedient_controls:
            expedient_controls.append(
                ft.Text(
                    (
                        "No hay expedientes activos "
                        "para este cliente."
                        if linked
                        else (
                            "Vincula primero la conversación "
                            "con un cliente."
                        )
                    ),
                    size=10,
                    color=Q_MUTED,
                )
            )

        expedients_card = ft.Container(
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Expedientes activos",
                                size=13,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=Q_PRIMARY_DARK,
                                expand=True,
                            ),
                            ft.Text(
                                str(
                                    len(
                                        expedients
                                    )
                                ),
                                size=10,
                                color=Q_MUTED,
                            ),
                        ],
                    ),
                    *expedient_controls,
                ],
                spacing=8,
            ),
        )

        return ft.Container(
            width=310,
            content=ft.Column(
                controls=[
                    contact_card,
                    expedients_card,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
        )

    def build_filters():
        search_input.on_submit = (
            refresh
        )

        channel_filter.on_select = (
            lambda value:
                refresh()
        )

        linkage_filter.on_select = (
            lambda value:
                set_linkage_filter(
                    selected_linkage()
                )
        )

        return ft.Container(
            bgcolor=Q_WHITE,
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=12,
            content=ft.Row(
                controls=[
                    search_input,
                    channel_filter.control,
                    linkage_filter.control,
                    secondary_button(
                        "Buscar",
                        refresh,
                    ),
                    secondary_button(
                        "Limpiar",
                        clear_filters,
                    ),
                ],
                spacing=10,
            ),
        )

    def build_content():
        if state.get(
            "error"
        ):
            return build_error_content(
                state[
                    "error"
                ]
            )

        summary = (
            state.get(
                "summary"
            )
            or {}
        )

        return ft.Container(
            expand=True,
            bgcolor=Q_BG,
            padding=ft.padding.only(
                left=14,
                top=12,
                right=14,
                bottom=12,
            ),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Comunicaciones",
                                        size=28,
                                        weight=(
                                            ft.FontWeight.BOLD
                                        ),
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        (
                                            "Gestión operativa de "
                                            "conversaciones, WhatsApp "
                                            "y seguimiento con clientes"
                                        ),
                                        size=12,
                                        color=Q_MUTED,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            secondary_button(
                                "Abrir WhatsApp",
                                open_whatsapp,
                            ),
                            secondary_button(
                                "Sincronizar WhatsApp",
                                placeholder_sync,
                            ),
                            secondary_button(
                                "Reconciliar vínculos",
                                reconcile_links,
                            ),
                            primary_button(
                                "Actualizar",
                                refresh,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Row(
                        controls=[
                            metric_card(
                                "Conversaciones",
                                summary.get(
                                    "total",
                                    0,
                                ),
                                width=205,
                            ),
                            metric_card(
                                "Vinculadas",
                                summary.get(
                                    "linked",
                                    0,
                                ),
                                width=205,
                            ),
                            metric_card(
                                "Sin vincular",
                                summary.get(
                                    "unlinked",
                                    0,
                                ),
                                width=205,
                            ),
                            metric_card(
                                "WhatsApp",
                                summary.get(
                                    "whatsapp",
                                    0,
                                ),
                                width=205,
                            ),
                        ],
                        spacing=12,
                    ),
                    build_filters(),
                    ft.Container(
                        expand=True,
                        content=ft.Row(
                            controls=[
                                build_conversation_list(),
                                chat_panel_control,
                                context_panel_control,
                            ],
                            spacing=12,
                            vertical_alignment=(
                                ft.CrossAxisAlignment.START
                            ),
                        ),
                    ),
                ],
                spacing=12,
                expand=True,
            ),
        )

    load_data(
        preserve_selection=True,
    )

    _refresh_composer_controls()

    # Primera construcción: los hosts todavía no están
    # montados, por lo que rellenamos su contenido sin update().
    chat_panel_control.content = (
        build_chat_panel()
    )

    context_panel_control.content = (
        build_context_panel()
    )

    content_area.content = (
        build_content()
    )

    return content_area
