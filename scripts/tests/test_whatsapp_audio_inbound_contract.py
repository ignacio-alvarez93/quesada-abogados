import unittest

from backend.automation.connectors.whatsapp_connector import (
    MESSAGE_TYPE_AUDIO,
    WhatsAppConnector,
)


class FakeBrowser:
    def evaluate(self, _script):
        return [
            {
                "provider_message_id": "WA-AUDIO-1",
                "pre_plain_text": "[11:30, 19/8/2026] CLIENTE:",
                "body_text": "",
                "meta_text": "11:30",
                "arias": ["CLIENTE:"],
                "testids": ["msg-container"],
                "has_tail_in": True,
                "has_tail_out": False,
                "center_ratio": 0.25,
                "has_sticker": False,
                "has_document": False,
                "has_image": False,
                "document_filename": None,
                "document_size_text": None,
                "image_info": [],
                "video_count": 0,
                "audio_count": 1,
                "reaction_labels": [],
                "has_quoted_message": False,
                "quoted_body_text": "",
            }
        ]


class WhatsAppAudioInboundContractTest(unittest.TestCase):
    def test_audio_is_classified_as_audio(self):
        connector = WhatsAppConnector()
        connector.browser = FakeBrowser()

        messages = connector.list_visible_message_snapshots()

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].message_type, MESSAGE_TYPE_AUDIO)
        self.assertEqual(messages[0].metadata["audio_count"], 1)


if __name__ == "__main__":
    unittest.main()
