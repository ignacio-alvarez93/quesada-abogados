import unittest

from backend.trend_intelligence.acquisition.contracts import (
    CollectorBatch,
    CollectorError,
    NormalizationError,
    RawCollectedItem,
)
from backend.trend_intelligence.acquisition.models import (
    ERROR_NETWORK,
    ERROR_UNKNOWN,
)
from backend.trend_intelligence.acquisition.provenance import (
    build_provenance,
    with_provenance,
)


class TrendIntelligenceAcquisitionContractTest(unittest.TestCase):
    def test_raw_collected_item_holds_opaque_payload(self):
        item = RawCollectedItem(raw_payload={"foo": "bar"})
        self.assertEqual(item.raw_payload, {"foo": "bar"})

    def test_collector_batch_defaults_cursor_to_none(self):
        batch = CollectorBatch(items=())
        self.assertIsNone(batch.next_cursor)

    def test_collector_error_classification_defaults_to_unknown(self):
        error = CollectorError("boom", classification="NOT_A_REAL_CLASSIFICATION")
        self.assertEqual(error.classification, ERROR_UNKNOWN)

    def test_collector_error_preserves_valid_classification(self):
        error = CollectorError("boom", classification=ERROR_NETWORK)
        self.assertEqual(error.classification, ERROR_NETWORK)

    def test_normalization_error_is_a_plain_exception(self):
        with self.assertRaises(NormalizationError):
            raise NormalizationError("malformed payload")

    def test_build_provenance_requires_identity_fields(self):
        with self.assertRaises(ValueError):
            build_provenance(
                collector_key="",
                collector_version="1.0.0",
                provider="RSS",
                source_identity="guid-1",
            )

    def test_build_provenance_produces_structured_fields(self):
        provenance = build_provenance(
            collector_key="RSS_FEED",
            collector_version="1.0.0",
            provider="RSS",
            source_identity="guid-1",
        )

        self.assertEqual(
            provenance,
            {
                "collector_key": "RSS_FEED",
                "collector_version": "1.0.0",
                "provider": "RSS",
                "source_identity": "guid-1",
            },
        )

    def test_with_provenance_namespaces_under_acquisition_key(self):
        metadata = with_provenance(
            {"custom": "value"},
            {"collector_key": "RSS_FEED"},
        )

        self.assertEqual(metadata["custom"], "value")
        self.assertEqual(metadata["acquisition"], {"collector_key": "RSS_FEED"})

    def test_with_provenance_does_not_mutate_input_metadata(self):
        original = {"custom": "value"}
        with_provenance(original, {"collector_key": "RSS_FEED"})
        self.assertNotIn("acquisition", original)


if __name__ == "__main__":
    unittest.main()
