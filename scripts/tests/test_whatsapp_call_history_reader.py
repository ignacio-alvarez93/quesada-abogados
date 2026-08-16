import unittest
from types import SimpleNamespace

from backend.automation.connectors.whatsapp_call_history_reader import (
    _normalize_result,
    read_whatsapp_call_history,
)
from backend.automation.connectors.whatsapp_connector import (
    WhatsAppConnector,
)


class FakeBrowser:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def evaluate(self, script):
        self.calls += 1
        return self.result


class WhatsAppCallHistoryReaderTest(
    unittest.TestCase
):
    def test_normalizes_and_dedupes(self):
        raw = {
            "version": "CALL-SYNC-4A",
            "read_only": True,
            "rows_scanned": 2,
            "items": [
                {
                    "provider_call_id": "CALL-1",
                    "external_call_key":
                        "false_1@lid_CALL-1",
                    "peer_lid": "1@lid",
                    "peer_phone_id":
                        "34639156371@c.us",
                    "peer_display_name": "Mama",
                    "provider_timestamp":
                        1786892997,
                    "call_duration_seconds": 18,
                    "raw_outcome": "Completed",
                    "raw_final_outcome":
                        "Completed",
                    "row_state": "Entrante",
                    "row_group_count": 1,
                    "is_video": False,
                },
                {
                    "provider_call_id": "CALL-1",
                    "external_call_key":
                        "false_1@lid_CALL-1",
                    "peer_lid": "1@lid",
                    "peer_phone_id":
                        "34639156371@c.us",
                },
            ],
            "skipped_rows": [],
        }

        result = _normalize_result(raw)

        self.assertEqual(
            len(result["items"]),
            1,
        )

        item = result["items"][0]

        self.assertEqual(
            item["provider_call_id"],
            "CALL-1",
        )

        self.assertEqual(
            item["call_duration_seconds"],
            18,
        )

    def test_sentinel_duration_becomes_none(
        self,
    ):
        result = _normalize_result({
            "items": [
                {
                    "provider_call_id":
                        "CALL-2",
                    "external_call_key":
                        "false_1@lid_CALL-2",
                    "peer_lid":
                        "1@lid",
                    "peer_phone_id":
                        "34639156371@c.us",
                    "call_duration_seconds": {
                        "sentinel":
                            "DEFAULT VALUE PLACEHOLDER"
                    },
                },
            ],
        })

        self.assertIsNone(
            result["items"][0][
                "call_duration_seconds"
            ]
        )

    def test_browser_evaluated_once(self):
        browser = FakeBrowser({
            "items": [],
            "rows_scanned": 0,
        })

        result = read_whatsapp_call_history(
            browser
        )

        self.assertEqual(
            browser.calls,
            1,
        )

        self.assertEqual(
            result["items"],
            [],
        )

    def test_connector_delegates(self):
        browser = FakeBrowser({
            "items": [],
            "rows_scanned": 0,
        })

        fake_connector = SimpleNamespace(
            browser=browser
        )

        result = (
            WhatsAppConnector
            .read_visible_call_history(
                fake_connector
            )
        )

        self.assertEqual(
            browser.calls,
            1,
        )

        self.assertEqual(
            result["items"],
            [],
        )

    def test_missing_browser_fails(self):
        with self.assertRaises(
            RuntimeError
        ):
            read_whatsapp_call_history(
                None
            )


if __name__ == "__main__":
    unittest.main()
