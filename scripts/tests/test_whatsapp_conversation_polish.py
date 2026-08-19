from pathlib import Path

import pytest

from backend.services.communication_service import (
    CommunicationService,
)


ROOT = Path(__file__).resolve().parents[2]

VIEW_SOURCE = (
    ROOT
    / "frontend"
    / "views"
    / "communications_view.py"
).read_text(
    encoding="utf-8"
)


class ProbeCommunicationService(
    CommunicationService
):
    def __init__(self):
        self.received = None

    def get_or_create_whatsapp_thread(
        self,
        **kwargs,
    ):
        self.received = dict(
            kwargs
        )

        return {
            "thread": "THREAD",
            "created": True,
            "match": {
                "matched": False,
            },
        }


def test_message_bubble_includes_date_and_time():
    assert (
        'f"{day}/{month}/{year}"'
        in VIEW_SOURCE
    )

    assert (
        'f" · {raw_time}"'
        in VIEW_SOURCE
    )


def test_successful_outbound_activity_promotes_sidebar_thread():
    marker = (
        "if completed_operation_count > 0:"
    )

    position = VIEW_SOURCE.find(
        marker
    )

    assert position >= 0

    window = VIEW_SOURCE[
        position:
        position + 500
    ]

    assert (
        "_promote_realtime_thread("
        in window
    )

    assert (
        "thread_id"
        in window
    )


def test_manual_phone_thread_uses_canonical_identity():
    service = (
        ProbeCommunicationService()
    )

    result = (
        service
        .get_or_create_whatsapp_thread_by_phone(
            "600 123 456",
            display_name="Prospecto",
        )
    )

    assert (
        result["phone"]
        == "+34600123456"
    )

    assert (
        result["external_thread_key"]
        == "phone:34600123456"
    )

    assert (
        service.received[
            "external_thread_key"
        ]
        == "phone:34600123456"
    )

    assert (
        service.received[
            "phone"
        ]
        == "+34600123456"
    )

    assert (
        service.received[
            "display_name"
        ]
        == "Prospecto"
    )

    assert (
        service.received[
            "metadata"
        ][
            "source"
        ]
        == "crm_manual_outbound_start"
    )


def test_manual_phone_thread_rejects_invalid_phone():
    service = (
        ProbeCommunicationService()
    )

    with pytest.raises(
        ValueError,
        match=(
            "Teléfono WhatsApp "
            "no válido"
        ),
    ):
        service.get_or_create_whatsapp_thread_by_phone(
            "abc"
        )


CLIENTS_SOURCE = (
    ROOT
    / "frontend"
    / "views"
    / "clients_view.py"
).read_text(
    encoding="utf-8"
)

MAIN_SOURCE = (
    ROOT
    / "app"
    / "main.py"
).read_text(
    encoding="utf-8"
)


def test_new_whatsapp_ui_exists():
    # El CTA ya no significa simplemente abrir una
    # conversación: representa alta explícita en WhatsApp.
    assert (
        '"Añadir contacto"'
        in VIEW_SOURCE
    )

    # Primero se crea/reutiliza la identidad CRM.
    assert (
        "get_or_create_whatsapp_thread_by_phone"
        in VIEW_SOURCE
    )

    # Después se ordena explícitamente el alta real
    # del contacto en WhatsApp Web.
    assert (
        "whatsapp_runtime.add_contact_and_open("
        in VIEW_SOURCE
    )

    # Runtime expone un caso de uso dedicado y serializado.
    assert (
        "def add_contact_and_open("
        in RUNTIME_SOURCE
    )

    assert (
        "def _add_contact_and_open_impl("
        in RUNTIME_SOURCE
    )

def test_unlinked_thread_can_create_client():
    assert (
        '"Crear cliente"'
        in VIEW_SOURCE
    )

    assert (
        "on_create_cliente("
        in VIEW_SOURCE
    )


def test_clients_view_supports_whatsapp_prefill():
    assert (
        "new_client_defaults=None"
        in CLIENTS_SOURCE
    )

    assert (
        'defaults.get(\n'
        '                "telefono"'
        in CLIENTS_SOURCE
    )

    assert (
        "on_client_created"
        in CLIENTS_SOURCE
    )


def test_main_links_created_client_back_to_whatsapp():
    assert (
        "new_client_source_thread_id"
        in MAIN_SOURCE
    )

    assert (
        "link_whatsapp_thread_to_client"
        in MAIN_SOURCE
    )

    assert (
        '"WhatsApp"'
        in MAIN_SOURCE
    )


CONNECTOR_SOURCE = (
    ROOT
    / "backend"
    / "automation"
    / "connectors"
    / "whatsapp_connector.py"
).read_text(
    encoding="utf-8"
)

RUNTIME_SOURCE = (
    ROOT
    / "backend"
    / "services"
    / "whatsapp_runtime_service.py"
).read_text(
    encoding="utf-8"
)


def test_new_contact_route_uses_frozen_whatsapp_selectors():
    assert (
        'button[aria-label="Nuevo chat"]'
        in CONNECTOR_SOURCE
    )

    assert (
        'new-chat-drawer-new-contact-cell'
        in CONNECTOR_SOURCE
    )

    assert (
        '[aria-label="Nombre"]'
        in CONNECTOR_SOURCE
    )

    assert (
        'phone-number-input'
        in CONNECTOR_SOURCE
    )

    assert (
        'save-contact-btn'
        in CONNECTOR_SOURCE
    )

    assert (
        'aria-label="Guardar contacto"'
        in CONNECTOR_SOURCE
    )



def test_new_whatsapp_requires_contact_name():
    assert (
        '"Indica el nombre del contacto."'
        in VIEW_SOURCE
    )

    assert (
        'label="Nombre"'
        in VIEW_SOURCE
    )


CONNECTOR_SOURCE = (
    ROOT
    / "backend"
    / "automation"
    / "connectors"
    / "whatsapp_connector.py"
).read_text(
    encoding="utf-8"
)

RUNTIME_SOURCE = (
    ROOT
    / "backend"
    / "services"
    / "whatsapp_runtime_service.py"
).read_text(
    encoding="utf-8"
)


def test_new_contact_route_uses_frozen_whatsapp_selectors():
    assert (
        'button[aria-label="Nuevo chat"]'
        in CONNECTOR_SOURCE
    )

    assert (
        'new-chat-drawer-new-contact-cell'
        in CONNECTOR_SOURCE
    )

    assert (
        '[aria-label="Nombre"]'
        in CONNECTOR_SOURCE
    )

    assert (
        'phone-number-input'
        in CONNECTOR_SOURCE
    )

    assert (
        'save-contact-btn'
        in CONNECTOR_SOURCE
    )

    assert (
        'aria-label="Guardar contacto"'
        in CONNECTOR_SOURCE
    )


def test_new_whatsapp_requires_contact_name():
    assert (
        '"Indica el nombre del contacto."'
        in VIEW_SOURCE
    )

    assert (
        'label="Nombre"'
        in VIEW_SOURCE
    )


def test_new_contact_never_accepts_old_chat_composer_as_save_success():
    method_start = (
        CONNECTOR_SOURCE.index(
            "def create_and_open_contact("
        )
    )

    method_end = (
        CONNECTOR_SOURCE.index(
            "def open_chat_by_phone(",
            method_start,
        )
    )

    method_source = (
        CONNECTOR_SOURCE[
            method_start:
            method_end
        ]
    )

    assert (
        "SAVE_CONTACT_NOT_CONFIRMED"
        in method_source
    )

    assert (
        "save-contact-drawer"
        in method_source
    )

    assert (
        "contact saved"
        in method_source
    )

    assert (
        "search_and_open_chat_by_phone("
        in method_source
    )

    # El compositor del chat previamente abierto
    # ya no puede validar por sí solo el alta.
    assert (
        "get_message_composer_state()"
        not in method_source
    )


def test_new_contact_save_uses_browser_level_cdp_click():
    method_start = (
        CONNECTOR_SOURCE.index(
            "def create_and_open_contact("
        )
    )

    method_end = (
        CONNECTOR_SOURCE.index(
            "def open_chat_by_phone(",
            method_start,
        )
    )

    method_source = (
        CONNECTOR_SOURCE[
            method_start:
            method_end
        ]
    )

    assert (
        'getattr(\n'
        '            self.browser,\n'
        '            "mouse_click"'
        in method_source
    )

    assert (
        '"click_with_offset"'
        in method_source
    )

    assert (
        "SAVE_CONTACT_NOT_CONFIRMED"
        in method_source
    )



def test_new_contact_save_uses_browser_level_cdp_click():
    method_start = (
        CONNECTOR_SOURCE.index(
            "def create_and_open_contact("
        )
    )

    method_end = (
        CONNECTOR_SOURCE.index(
            "def open_chat_by_phone(",
            method_start,
        )
    )

    method_source = (
        CONNECTOR_SOURCE[
            method_start:
            method_end
        ]
    )

    assert (
        'getattr(\n'
        '            self.browser,\n'
        '            "mouse_click"'
        in method_source
    )

    assert (
        '"click_with_offset"'
        in method_source
    )

    assert (
        "SAVE_CONTACT_NOT_CONFIRMED"
        in method_source
    )


def test_new_contact_fallback_is_restricted_to_manual_crm_threads():
    assert (
        "_thread_allows_new_contact_fallback"
        in RUNTIME_SOURCE
    )

    assert (
        "crm_manual_outbound_start"
        in RUNTIME_SOURCE
    )

    # Runtime delega el flujo proactivo completo.
    assert (
        "open_or_create_manual_chat("
        in RUNTIME_SOURCE
    )

    # La creación real permanece encapsulada
    # dentro del connector.
    assert (
        "def create_and_open_contact("
        in CONNECTOR_SOURCE
    )

def test_new_contact_failure_has_ui_recovery_contract():
    assert (
        "def cancel_new_contact_flow("
        in CONNECTOR_SOURCE
    )

    # El drawer real debe detectarse aunque durante
    # una búsqueda desaparezca la celda Nuevo contacto.
    assert (
        '[data-testid="new-chat-drawer"]'
        in CONNECTOR_SOURCE
    )

    assert (
        "ui_recovered"
        in CONNECTOR_SOURCE
    )

    # El runtime ya no gestiona recovery directamente:
    # delega todo en open_or_create_manual_chat().
    assert (
        "open_or_create_manual_chat("
        in RUNTIME_SOURCE
    )

    assert (
        "cancel_new_contact_flow("
        in CONNECTOR_SOURCE
    )


def test_saved_contact_name_is_reconciled_after_whatsapp_save():
    service_source = Path(
        "backend/services/communication_service.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "def update_whatsapp_thread_display_name("
        in service_source
    )

    assert (
        "update_whatsapp_thread_display_name("
        in VIEW_SOURCE
    )

    add_position = VIEW_SOURCE.index(
        "whatsapp_runtime.add_contact_and_open("
    )

    name_position = VIEW_SOURCE.index(
        "communication_service.update_whatsapp_thread_display_name("
    )

    assert name_position > add_position

    assert (
        "route_whatsapp=False"
        in VIEW_SOURCE
    )



def test_historical_saved_contact_uses_existing_only_fallback():
    assert (
        "allow_create=True"
        in CONNECTOR_SOURCE
    )

    assert (
        "if not allow_create:"
        in CONNECTOR_SOURCE
    )

    assert (
        "NEW_CHAT_EXISTING_NOT_FOUND"
        in CONNECTOR_SOURCE
    )

    assert (
        "allow_create=False"
        in RUNTIME_SOURCE
    )

    # La creación explícita continúa existiendo exclusivamente
    # para el flujo Añadir contacto.
    assert (
        "create_and_open_contact("
        in CONNECTOR_SOURCE
    )



def test_open_thread_reconciles_active_whatsapp_display_name():
    assert (
        "observed_display_name"
        in CONNECTOR_SOURCE
    )

    assert (
        "observed_name"
        in CONNECTOR_SOURCE
    )

    assert (
        '"navigation":\n'
        '                            "NEW_CHAT_EXISTING"'
        in CONNECTOR_SOURCE
    )

    assert (
        "update_whatsapp_thread_display_name"
        in RUNTIME_SOURCE
    )

    assert (
        "[WA-ROUTE] observed display name reconciled"
        in RUNTIME_SOURCE
    )

    # La reconciliación NO puede consumir otro fingerprint:
    # rompería el fast-path del primer envío.
    runtime_start = (
        RUNTIME_SOURCE.index(
            "def _open_thread_impl("
        )
    )

    runtime_end = (
        RUNTIME_SOURCE.index(
            "def _verify_and_open_thread_impl(",
            runtime_start,
        )
    )

    method_source = (
        RUNTIME_SOURCE[
            runtime_start:
            runtime_end
        ]
    )

    assert (
        "get_active_chat_fingerprint()"
        not in method_source
    )



def test_route_completion_refreshes_reconciled_thread_overview():
    assert (
        "[WA-FLET] thread overview refreshed"
        in VIEW_SOURCE
    )

    assert (
        "fresh_item = next("
        in VIEW_SOURCE
    )

    assert (
        'state["items"] = ['
        in VIEW_SOURCE
    )

    # El refresh visual puntual no debe usar load_data(),
    # evitando una reconstrucción completa innecesaria.
    start = VIEW_SOURCE.index(
        "def _finish_whatsapp_route_ui("
    )

    end = VIEW_SOURCE.index(
        "def _schedule_finish_whatsapp_route_ui(",
        start,
    )

    block = VIEW_SOURCE[start:end]

    assert not any(
        line.lstrip().startswith(
            "load_data("
        )
        for line in block.splitlines()
    )
