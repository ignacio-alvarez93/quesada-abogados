from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)

from scripts.tests.test_whatsapp_runtime_service import (
    FakeCommunicationService,
    FakeConnector,
)


def test_passive_sidebar_snapshot_does_not_mutate_watcher_baseline():
    FakeConnector.instances = []

    runtime = WhatsAppRuntimeService(
        profile_key="test_profile",
        headless=True,
        communication_service=(
            FakeCommunicationService()
        ),
        connector_factory=(
            FakeConnector
        ),
    )

    connector = runtime.start()

    sidebar = {
        "jafet": {
            "identity":
                "jafet",
            "display_name":
                "Jafet",
            "preview":
                "Mensaje pendiente",
            "primary_detail":
                "10:42",
            "unread_count":
                3,
            "position":
                0,
            "virtual_offset":
                0,
            "ambiguous":
                False,
        },
    }

    connector.sidebar_chat_fingerprints = [
        sidebar,
    ]

    result = (
        runtime
        .read_sidebar_chat_fingerprint(
            wait_timeout=1,
        )
    )

    assert result == sidebar

    # La lectura de hidratación no suplanta el baseline
    # perteneciente al watcher realtime.
    assert (
        runtime
        ._sidebar_chat_fingerprint
        is None
    )

    runtime.close()
