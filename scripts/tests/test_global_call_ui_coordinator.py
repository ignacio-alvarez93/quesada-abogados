import asyncio
import unittest

from backend.services.call_ui_event_service import (
    CallUIEvent,
)
from frontend.components.global_call_ui_coordinator import (
    GlobalCallUICoordinator,
)


class FakePage:
    def __init__(
        self,
    ):
        self.show_count = 0
        self.update_count = 0
        self.run_task_count = 0
        self.run_thread_count = 0

    def show_dialog(
        self,
        dialog,
    ):
        self.show_count += 1
        dialog.open = True

    def update(
        self,
    ):
        self.update_count += 1

    def run_task(
        self,
        callback,
        *args,
        **kwargs,
    ):
        self.run_task_count += 1

        return asyncio.run(
            callback(
                *args,
                **kwargs,
            )
        )

    def run_thread(
        self,
        callback,
        *args,
        **kwargs,
    ):
        self.run_thread_count += 1

        return callback(
            *args,
            **kwargs,
        )


def ringing():
    return CallUIEvent(
        event_key="CALL:50",
        call_id=50,
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
        provider_call_id="p1",
        external_call_key="e1",
        can_accept=True,
        can_reject=True,
        incoming_ringing=True,
    )


class GlobalCallUICoordinatorTest(
    unittest.TestCase
):
    def test_duplicate_ringing_opens_one_dialog(
        self,
    ):
        page = FakePage()

        coordinator = (
            GlobalCallUICoordinator(
                page=page,
                on_accept=lambda e: {},
                on_reject=lambda e: {},
            )
        )

        event = ringing()

        asyncio.run(
            coordinator.apply_event(
                event
            )
        )

        asyncio.run(
            coordinator.apply_event(
                event
            )
        )

        state = (
            coordinator.debug_state()
        )

        self.assertEqual(
            page.show_count,
            1,
        )

        self.assertEqual(
            state[
                "dialog_open_count"
            ],
            1,
        )

        self.assertEqual(
            state[
                "duplicate_count"
            ],
            1,
        )


    def test_same_call_terminal_closes_dialog(
        self,
    ):
        page = FakePage()

        coordinator = (
            GlobalCallUICoordinator(
                page=page
            )
        )

        event = ringing()

        asyncio.run(
            coordinator.apply_event(
                event
            )
        )

        terminal = CallUIEvent(
            event_key="CALL:50",
            status="MISSED",
            incoming_ringing=False,
            terminal=True,
        )

        asyncio.run(
            coordinator.apply_event(
                terminal
            )
        )

        state = (
            coordinator.debug_state()
        )

        self.assertIsNone(
            state[
                "event_key"
            ]
        )

        self.assertFalse(
            state[
                "dialog_open"
            ]
        )


    def test_unrelated_event_does_not_close_dialog(
        self,
    ):
        page = FakePage()

        coordinator = (
            GlobalCallUICoordinator(
                page=page
            )
        )

        asyncio.run(
            coordinator.apply_event(
                ringing()
            )
        )

        unrelated = CallUIEvent(
            event_key="CALL:99",
            status="DIALING",
            incoming_ringing=False,
        )

        asyncio.run(
            coordinator.apply_event(
                unrelated
            )
        )

        state = (
            coordinator.debug_state()
        )

        self.assertEqual(
            state[
                "event_key"
            ],
            "CALL:50",
        )


    def test_background_entry_uses_page_run_task(
        self,
    ):
        page = FakePage()

        coordinator = (
            GlobalCallUICoordinator(
                page=page
            )
        )

        coordinator.handle_event(
            ringing()
        )

        self.assertEqual(
            page.run_task_count,
            1,
        )


if __name__ == "__main__":
    unittest.main()
