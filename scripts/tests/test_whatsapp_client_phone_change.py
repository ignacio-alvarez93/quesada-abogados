from types import SimpleNamespace

import pytest

from backend.services.communication_service import (
    CommunicationService,
)


def _service():
    return object.__new__(
        CommunicationService
    )


def test_phone_change_links_new_unlinked_thread():
    service = _service()

    thread = SimpleNamespace(
        id=50,
        client_id=None,
    )

    service.get_or_create_whatsapp_thread_by_phone = (
        lambda phone, display_name=None, metadata=None: {
            "thread": thread,
            "match": {
                "matched": True,
                "ambiguous": False,
            },
            "created": True,
        }
    )

    linked = SimpleNamespace(
        id=50,
        client_id=7,
    )

    calls = []

    def link(thread_id, client_id):
        calls.append(
            (
                thread_id,
                client_id,
            )
        )
        return linked

    service.link_whatsapp_thread_to_client = link

    result = (
        service
        .prepare_whatsapp_thread_for_client_phone_change(
            7,
            "611 111 111",
            display_name="Cliente prueba",
        )
    )

    assert calls == [(50, 7)]
    assert result["thread"].client_id == 7
    assert result["phone"] == "+34611111111"


def test_phone_change_preserves_thread_if_already_same_client():
    service = _service()

    thread = SimpleNamespace(
        id=60,
        client_id=7,
    )

    service.get_or_create_whatsapp_thread_by_phone = (
        lambda phone, display_name=None, metadata=None: {
            "thread": thread,
            "match": {
                "matched": True,
                "ambiguous": False,
            },
            "created": False,
        }
    )

    service.link_whatsapp_thread_to_client = (
        lambda *args, **kwargs:
            pytest.fail(
                "No debe relinkear "
                "un thread ya correcto"
            )
    )

    result = (
        service
        .prepare_whatsapp_thread_for_client_phone_change(
            7,
            "+34 611 111 111",
            display_name="Cliente prueba",
        )
    )

    assert result["thread"] is thread


def test_phone_change_rejects_thread_linked_to_other_client():
    service = _service()

    thread = SimpleNamespace(
        id=70,
        client_id=99,
    )

    service.get_or_create_whatsapp_thread_by_phone = (
        lambda phone, display_name=None, metadata=None: {
            "thread": thread,
            "match": {
                "matched": True,
                "ambiguous": False,
            },
            "created": False,
        }
    )

    with pytest.raises(
        RuntimeError,
        match="otro cliente",
    ):
        service.prepare_whatsapp_thread_for_client_phone_change(
            7,
            "611111111",
            display_name="Cliente prueba",
        )


def test_frontend_contract_preserves_old_thread_identity():
    source = open(
        "frontend/views/clients_view.py",
        encoding="utf-8",
    ).read()

    assert "on_client_phone_changed" in source
    assert "editing_original_phone" in source
    assert "La conversación anterior se conservará" in source
    assert "Añadir a WhatsApp" in source


def test_app_uses_explicit_whatsapp_contact_operation():
    source = open(
        "app/main.py",
        encoding="utf-8",
    ).read()

    assert (
        "prepare_whatsapp_thread_for_client_phone_change"
        in source
    )
    assert "add_contact_and_open(" in source
    assert (
        "update_whatsapp_thread_display_name("
        in source
    )
