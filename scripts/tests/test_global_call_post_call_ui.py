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


def ended_event():
    return CallUIEvent(
        event_key="CALL:50",
        call_id=50,
        channel="WHATSAPP",
        direction="INBOUND",
        status="ENDED",
        phone_number="+34639156371",
        display_name=(
            "JEAN PIERRY MUÑOZ VALDEZ"
        ),
        client_id=30,
        provider="WHATSAPP",
        provider_call_id="provider-50",
        external_call_key="external-50",
        terminal=True,
        post_call_required=True,
    )


def missed_event():
    return CallUIEvent(
        event_key="CALL:50",
        call_id=50,
        channel="WHATSAPP",
        direction="INBOUND",
        status="MISSED",
        phone_number="+34639156371",
        display_name=(
            "JEAN PIERRY MUÑOZ VALDEZ"
        ),
        terminal=True,
        post_call_required=False,
    )


REASONS = (
    {
        "code":
            "LEGAL_CONSULTATION",
        "label":
            "Consulta jurídica",
    },
    {
        "code":
            "EXPEDIENT_STATUS",
        "label":
            "Estado del expediente",
    },
)


class GlobalPostCallUITest(
    unittest.TestCase
):
    def test_ended_opens_post_call_dialog(
        self,
    ):
        page = FakePage()

        coordinator = (
            GlobalCallUICoordinator(
                page=page,
                reason_options=REASONS,
                on_save_post_call=(
                    lambda event, **kwargs:
                        {"ok": True}
                ),
            )
        )

        asyncio.run(
            coordinator.apply_event(
                ended_event()
            )
        )

        state = (
            coordinator.debug_state()
        )

        self.assertEqual(
            page.show_count,
            1,
        )

        self.assertTrue(
            state[
                "post_call_dialog_open"
            ]
        )

        self.assertEqual(
            state[
                "post_call_event_key"
            ],
            "CALL:50",
        )


    def test_missed_does_not_open_post_call_dialog(
        self,
    ):
        page = FakePage()

        coordinator = (
            GlobalCallUICoordinator(
                page=page,
                reason_options=REASONS,
            )
        )

        asyncio.run(
            coordinator.apply_event(
                missed_event()
            )
        )

        state = (
            coordinator.debug_state()
        )

        self.assertEqual(
            page.show_count,
            0,
        )

        self.assertFalse(
            state[
                "post_call_dialog_open"
            ]
        )


    def test_duplicate_ended_opens_only_once(
        self,
    ):
        page = FakePage()

        coordinator = (
            GlobalCallUICoordinator(
                page=page,
                reason_options=REASONS,
            )
        )

        event = ended_event()

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
                "post_call_dialog_open_count"
            ],
            1,
        )

        self.assertEqual(
            state[
                "post_call_duplicate_count"
            ],
            1,
        )


    def test_reason_is_required_before_save(
        self,
    ):
        page = FakePage()

        calls = []

        def save(
            event,
            **kwargs,
        ):
            calls.append(
                (
                    event,
                    kwargs,
                )
            )

            return {
                "ok": True
            }

        coordinator = (
            GlobalCallUICoordinator(
                page=page,
                reason_options=REASONS,
                on_save_post_call=save,
            )
        )

        asyncio.run(
            coordinator.apply_event(
                ended_event()
            )
        )

        result = (
            coordinator
            ._on_post_call_save_click()
        )

        self.assertFalse(
            result
        )

        self.assertEqual(
            calls,
            [],
        )

        self.assertTrue(
            coordinator
            ._post_call_error
            .visible
        )


    def test_save_uses_backend_callback_and_closes(
        self,
    ):
        page = FakePage()

        calls = []

        def save(
            event,
            *,
            reason_code,
            reason_detail=None,
            notes=None,
        ):
            calls.append(
                {
                    "call_id":
                        event.call_id,
                    "reason_code":
                        reason_code,
                    "reason_detail":
                        reason_detail,
                    "notes":
                        notes,
                }
            )

            return {
                "ok": True,
                "call_id":
                    event.call_id,
            }

        coordinator = (
            GlobalCallUICoordinator(
                page=page,
                reason_options=REASONS,
                on_save_post_call=save,
            )
        )

        asyncio.run(
            coordinator.apply_event(
                ended_event()
            )
        )

        coordinator._post_call_reason.value = (
            "LEGAL_CONSULTATION"
        )

        coordinator._post_call_reason_detail.value = (
            "Renovación"
        )

        coordinator._post_call_notes.value = (
            "Cliente informado"
        )

        result = (
            coordinator
            ._on_post_call_save_click()
        )

        self.assertTrue(
            result
        )

        self.assertEqual(
            calls,
            [
                {
                    "call_id": 50,
                    "reason_code":
                        "LEGAL_CONSULTATION",
                    "reason_detail":
                        "Renovación",
                    "notes":
                        "Cliente informado",
                }
            ],
        )

        state = (
            coordinator.debug_state()
        )

        self.assertFalse(
            state[
                "post_call_dialog_open"
            ]
        )

        self.assertIsNone(
            state[
                "post_call_event_key"
            ]
        )


    def test_skip_marks_event_as_handled(
        self,
    ):
        page = FakePage()

        coordinator = (
            GlobalCallUICoordinator(
                page=page,
                reason_options=REASONS,
            )
        )

        event = ended_event()

        asyncio.run(
            coordinator.apply_event(
                event
            )
        )

        coordinator._on_post_call_skip_click()

        asyncio.run(
            coordinator.apply_event(
                event
            )
        )

        self.assertEqual(
            page.show_count,
            1,
        )

        self.assertFalse(
            coordinator.debug_state()[
                "post_call_dialog_open"
            ]
        )


    def test_existing_values_are_prefilled(
        self,
    ):
        page = FakePage()

        event = CallUIEvent(
            event_key="CALL:70",
            call_id=70,
            status="ENDED",
            display_name="Cliente",
            terminal=True,
            post_call_required=True,
            reason_code=(
                "EXPEDIENT_STATUS"
            ),
            reason_detail=(
                "Consulta de estado"
            ),
            notes=(
                "Notas anteriores"
            ),
        )

        coordinator = (
            GlobalCallUICoordinator(
                page=page,
                reason_options=REASONS,
            )
        )

        asyncio.run(
            coordinator.apply_event(
                event
            )
        )

        self.assertEqual(
            coordinator
            ._post_call_reason
            .value,
            "EXPEDIENT_STATUS",
        )

        self.assertEqual(
            coordinator
            ._post_call_reason_detail
            .value,
            "Consulta de estado",
        )

        self.assertEqual(
            coordinator
            ._post_call_notes
            .value,
            "Notas anteriores",
        )


if __name__ == "__main__":
    unittest.main()
