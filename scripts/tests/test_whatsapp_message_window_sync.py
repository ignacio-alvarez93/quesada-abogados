import threading
from types import SimpleNamespace

from backend.automation.connectors.whatsapp_connector import (
    WhatsAppActiveChatFingerprint,
)
from backend.services.whatsapp_runtime_service import (
    WhatsAppRuntimeService,
)


def fingerprint(
    count,
):
    return WhatsAppActiveChatFingerprint(
        chat_open=True,
        active_display_name="Mi Amor",
        active_identity="mi amor",
        visible_message_count=count,
        last_provider_message_id="MSG-LAST",
        last_provider_message_status="READ",
    )


class FakeConnector:
    def get_sidebar_chat_fingerprint(
        self,
        *,
        viewport_only=True,
    ):
        return {}


class FakeCommunicationService:
    def __init__(
        self,
    ):
        self.resolve_calls = []
        self.latest_provider_calls = []

    def get_latest_thread_provider_message_id(
        self,
        thread_id,
    ):
        self.latest_provider_calls.append(
            thread_id
        )

        return "MSG-LAST"

    def resolve_whatsapp_thread_by_identity(
        self,
        identity,
    ):
        self.resolve_calls.append(
            identity
        )

        return {
            "matched":
                True,

            "ambiguous":
                False,

            "match_basis":
                "DISPLAY_NAME",

            "thread":
                SimpleNamespace(
                    thread_id=2
                ),

            "matches":
                [],

            "identity":
                identity,
        }


class FakeSyncService:
    def __init__(
        self,
    ):
        self.calls = []

    def sync_open_chat_messages(
        self,
        **kwargs,
    ):
        self.calls.append(
            dict(
                kwargs
            )
        )

        return {
            "summary": {
                "thread_id":
                    kwargs[
                        "thread_id"
                    ],

                "scanned":
                    30,

                "created":
                    29,

                "reused":
                    1,

                "status_advanced":
                    0,

                "skipped":
                    0,

                "errors":
                    0,
            },

            "items":
                [],

            "aborted":
                False,

            "abort_reason":
                None,
        }


class RuntimeProbe:
    _observe_and_sync_active_chat_impl = (
        WhatsAppRuntimeService
        ._observe_and_sync_active_chat_impl
    )

    def __init__(
        self,
        *,
        previous,
        current,
        change_type=(
            "MESSAGE_WINDOW_CHANGED"
        ),
        desired_thread_id=None,
    ):
        self._connector = (
            FakeConnector()
        )

        self._sidebar_chat_fingerprint = {}

        self._desired_thread_lock = (
            threading.Lock()
        )

        self._desired_thread_id = (
            desired_thread_id
        )

        self.communication_service = (
            FakeCommunicationService()
        )

        self.sync_service = (
            FakeSyncService()
        )

        self.observation = {
            "changed":
                True,

            "change_type":
                change_type,

            "previous":
                previous,

            "current":
                current,
        }

    def _observe_active_chat_impl(
        self,
        *,
        wait_timeout=60,
    ):
        return dict(
            self.observation
        )

    def _get_sync_service(
        self,
    ):
        return self.sync_service


def test_window_expansion_runs_full_visible_sync():
    runtime = RuntimeProbe(
        previous=fingerprint(1),
        current=fingerprint(30),
    )

    result = (
        runtime
        ._observe_and_sync_active_chat_impl(
            wait_timeout=1
        )
    )

    assert (
        result["change_type"]
        == "MESSAGE_WINDOW_CHANGED"
    )

    assert (
        result[
            "message_window_expanded"
        ]
        is True
    )

    assert (
        runtime
        .communication_service
        .resolve_calls
        == ["mi amor"]
    )

    assert len(
        runtime.sync_service.calls
    ) == 1

    call = (
        runtime
        .sync_service
        .calls[0]
    )

    assert (
        call["thread_id"]
        == 2
    )

    # Punto crítico del fix:
    # una expansión NO puede usar el último
    # provider id como anchor incremental.
    assert (
        call[
            "after_provider_message_id"
        ]
        is None
    )

    assert (
        call[
            "expected_active_identity"
        ]
        == "mi amor"
    )

    assert (
        call[
            "expected_last_provider_message_id"
        ]
        == "MSG-LAST"
    )


def test_window_contraction_does_not_sync():
    runtime = RuntimeProbe(
        previous=fingerprint(30),
        current=fingerprint(1),
    )

    result = (
        runtime
        ._observe_and_sync_active_chat_impl(
            wait_timeout=1
        )
    )

    assert (
        result["change_type"]
        == "MESSAGE_WINDOW_CHANGED"
    )

    assert (
        "message_window_expanded"
        not in result
    )

    assert (
        runtime
        .communication_service
        .resolve_calls
        == []
    )

    assert (
        runtime.sync_service.calls
        == []
    )

    assert (
        result["sync"]
        is None
    )

def test_initial_without_selected_thread_remains_baseline():
    runtime = RuntimeProbe(
        previous=None,
        current=fingerprint(30),
        change_type="INITIAL",
        desired_thread_id=None,
    )

    result = (
        runtime
        ._observe_and_sync_active_chat_impl(
            wait_timeout=1
        )
    )

    assert (
        result["change_type"]
        == "INITIAL"
    )

    assert (
        result["resolution"]
        is None
    )

    assert (
        result["sync"]
        is None
    )

    assert (
        runtime
        .communication_service
        .resolve_calls
        == []
    )


def test_initial_selected_thread_runs_full_visible_sync():
    runtime = RuntimeProbe(
        previous=None,
        current=fingerprint(30),
        change_type="INITIAL",
        desired_thread_id=2,
    )

    result = (
        runtime
        ._observe_and_sync_active_chat_impl(
            wait_timeout=1
        )
    )

    assert (
        result[
            "initial_selection_recovery"
        ]
        is True
    )

    assert (
        runtime
        .communication_service
        .resolve_calls
        == ["mi amor"]
    )

    assert len(
        runtime.sync_service.calls
    ) == 1

    call = (
        runtime
        .sync_service
        .calls[0]
    )

    assert (
        call["thread_id"]
        == 2
    )

    # INITIAL seleccionado recupera toda la
    # ventana ya materializada.
    assert (
        call[
            "after_provider_message_id"
        ]
        is None
    )


def test_initial_selected_thread_mismatch_fails_closed():
    runtime = RuntimeProbe(
        previous=None,
        current=fingerprint(30),
        change_type="INITIAL",
        desired_thread_id=99,
    )

    result = (
        runtime
        ._observe_and_sync_active_chat_impl(
            wait_timeout=1
        )
    )

    assert (
        result["change_type"]
        == "INITIAL"
    )

    assert (
        runtime
        .communication_service
        .resolve_calls
        == ["mi amor"]
    )

    assert (
        runtime.sync_service.calls
        == []
    )

    assert (
        result["sync"]
        is None
    )

    assert (
        "initial_selection_recovery"
        not in result
    )

def test_chat_changed_runs_full_visible_sync_without_db_checkpoint():
    runtime = RuntimeProbe(
        previous=fingerprint(20),
        current=fingerprint(30),
        change_type="CHAT_CHANGED",
    )

    result = (
        runtime
        ._observe_and_sync_active_chat_impl(
            wait_timeout=1
        )
    )

    assert (
        result["change_type"]
        == "CHAT_CHANGED"
    )

    assert (
        runtime
        .communication_service
        .resolve_calls
        == ["mi amor"]
    )

    assert len(
        runtime.sync_service.calls
    ) == 1

    call = (
        runtime
        .sync_service
        .calls[0]
    )

    assert (
        call["thread_id"]
        == 2
    )

    # Punto crítico:
    # CHAT_CHANGED jamás usa como checkpoint el
    # último provider id almacenado en DB.
    assert (
        runtime
        .communication_service
        .latest_provider_calls
        == []
    )

    assert (
        call[
            "after_provider_message_id"
        ]
        is None
    )

    assert (
        call[
            "expected_active_identity"
        ]
        == "mi amor"
    )

    assert (
        call[
            "expected_last_provider_message_id"
        ]
        == "MSG-LAST"
    )

