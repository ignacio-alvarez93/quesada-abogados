import unittest

from backend.communications.models import (
    CommunicationThread,
    THREAD_MATCH_UNMATCHED,
)
from scripts.tests.test_communication_service import (
    CommunicationServiceTest,
)


class WhatsAppAudioRefinementTest(unittest.TestCase):

    def setUp(self):
        self.base = CommunicationServiceTest()
        self.base.setUp()
        self.service = self.base.service

    def tearDown(self):
        self.base.tearDown()

    def test_unknown_media_refines_to_audio_without_duplicate(self):
        repository = self.service.repository
        account = self.service.ensure_whatsapp_dev_account()

        thread = repository.get_or_create_thread(
            CommunicationThread(
                id=None,
                account_id=account.id,
                client_id=None,
                external_thread_key="audio-refinement-thread",
                external_address="+34600999222",
                match_status=THREAD_MATCH_UNMATCHED,
            )
        )

        first = self.service.import_provider_message(
            thread_id=thread.id,
            direction="INBOUND",
            body_text="",
            provider_message_id="WA-AUDIO-REFINE-1",
            provider_timestamp="2026-08-19T11:00:00",
            status="RECEIVED",
            metadata={"message_type": "UNKNOWN_MEDIA"},
        )

        second = self.service.import_provider_message(
            thread_id=thread.id,
            direction="INBOUND",
            body_text="",
            provider_message_id="WA-AUDIO-REFINE-1",
            provider_timestamp="2026-08-19T11:00:00",
            status="RECEIVED",
            metadata={
                "message_type": "AUDIO",
                "audio_count": 1,
                "source": "whatsapp_web_message_sync",
            },
        )

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertTrue(second["reused"])
        self.assertTrue(second["metadata_refined"])

        self.assertEqual(
            second["message"].metadata["message_type"],
            "AUDIO",
        )


if __name__ == "__main__":
    unittest.main()
