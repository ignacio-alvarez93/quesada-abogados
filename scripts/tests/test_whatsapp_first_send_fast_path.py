from backend.automation.connectors.whatsapp_connector import (
    WhatsAppActiveChatFingerprint,
)
from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)

from scripts.tests.test_whatsapp_runtime_service import (
    FakeConnector,
    FakeCommunicationService,
    FakeSuccessfulOutboundService,
)


def _fingerprint():
    return WhatsAppActiveChatFingerprint(
        chat_open=True,
        active_display_name=(
            "Test Contact"
        ),
        active_identity=(
            "test contact"
        ),
        visible_message_count=10,
        last_provider_message_id=(
            "MSG-10"
        ),
    )


def _runtime():
    FakeConnector.instances = []

    return WhatsAppRuntimeService(
        profile_key="test_profile",
        headless=True,
        communication_service=(
            FakeCommunicationService()
        ),
        connector_factory=(
            FakeConnector
        ),
    )


def _same_thread_resolution(runtime):
    thread = (
        runtime
        .communication_service
        .get_thread(7)
    )

    runtime.communication_service.resolve_whatsapp_thread_by_identity = (
        lambda identity: {
            "matched": True,
            "ambiguous": False,
            "match_basis":
                "DISPLAY_NAME",
            "thread": thread,
            "matches": [
                thread,
            ],
            "identity":
                identity,
        }
    )


def test_explicit_selection_makes_first_send_fast_without_profile():
    runtime = _runtime()
    connector = runtime.start()

    _same_thread_resolution(
        runtime
    )

    # Primera huella:
    # guard de selección.
    #
    # Segunda:
    # revalidación inmediata antes del send.
    connector.active_chat_fingerprints = [
        _fingerprint(),
        _fingerprint(),
    ]

    selected = (
        runtime
        .open_thread_for_selection(
            7,
            wait_timeout=1,
            routing_timeout=3,
        )
    )

    assert (
        selected[
            "routing"
        ][
            "selection_light"
        ]
        is True
    )

    assert (
        selected[
            "routing"
        ][
            "send_preverified"
        ]
        is True
    )

    assert (
        selected[
            "routing"
        ][
            "send_route_basis"
        ]
        ==
        "EXPLICIT_SELECTION_IDENTITY"
    )

    # Una sola navegación, siempre ligera.
    assert len(
        connector.open_phone_calls
    ) == 1

    assert (
        connector
        .open_phone_calls[0][2]
        is False
    )

    # CRÍTICO:
    # seleccionar NO abre el perfil.
    assert (
        connector
        .active_phone_verification_calls
        == []
    )

    outbound = (
        FakeSuccessfulOutboundService()
    )

    runtime._outbound_service = (
        outbound
    )

    sent = runtime.send_text_message(
        thread_id=7,
        body_text=(
            "Primer mensaje rápido"
        ),
        wait_timeout=1,
        routing_timeout=3,
    )

    assert sent["ok"] is True

    # El primer envío no vuelve a navegar.
    assert len(
        connector.open_phone_calls
    ) == 1

    # Y tampoco abre el perfil.
    assert (
        connector
        .active_phone_verification_calls
        == []
    )

    assert len(
        outbound.calls
    ) == 1

    runtime.close()


def test_ambiguous_selection_guard_falls_back_to_strong_route():
    runtime = _runtime()
    connector = runtime.start()

    connector.active_chat_fingerprints = [
        _fingerprint(),
    ]

    runtime.communication_service.resolve_whatsapp_thread_by_identity = (
        lambda identity: {
            "matched": False,
            "ambiguous": True,
            "thread": None,
            "matches": [],
            "identity":
                identity,
        }
    )

    selected = (
        runtime
        .open_thread_for_selection(
            7,
            wait_timeout=1,
            routing_timeout=3,
        )
    )

    assert (
        selected[
            "routing"
        ][
            "send_preverified"
        ]
        is False
    )

    assert (
        runtime
        ._verified_send_thread_id
        is None
    )

    # El fallback fuerte histórico sigue disponible.
    connector.routing_result = {
        "opened": True,
        "verified": True,
        "reason": None,
        "expected_phone":
            "+34600111222",
        "observed_phone":
            "+34600111222",
    }

    outbound = (
        FakeSuccessfulOutboundService()
    )

    runtime._outbound_service = (
        outbound
    )

    sent = runtime.send_text_message(
        thread_id=7,
        body_text=(
            "Fallback fuerte"
        ),
        wait_timeout=1,
        routing_timeout=3,
    )

    assert sent["ok"] is True

    # selección ligera + fallback fuerte
    assert len(
        connector.open_phone_calls
    ) == 2

    assert (
        connector
        .open_phone_calls[0][2]
        is False
    )

    assert (
        connector
        .open_phone_calls[1][2]
        is True
    )

    runtime.close()
