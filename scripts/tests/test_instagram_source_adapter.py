"""IT Instagram Collector v1: normalization and source-contract conformance.

No network, no Chrome: these tests only exercise pure normalization and
the TrendSourceAdapter protocol conformance of InstagramTrendSourceAdapter.
"""
import unittest

from backend.trend_intelligence.sources.base import (
    TrendObservationInput,
)
from backend.trend_intelligence.sources.instagram import (
    InstagramRawObservation,
    InstagramTrendSourceAdapter,
    normalize_instagram_post,
)


def _raw(**overrides):
    defaults = dict(
        source_account="example_account",
        external_id="ABC123",
        canonical_url="https://www.instagram.com/p/ABC123/",
        content_type="POST",
        observed_at="2026-10-11T10:00:00+00:00",
    )
    defaults.update(overrides)
    return InstagramRawObservation(**defaults)


class InstagramRawObservationTest(unittest.TestCase):
    def test_required_fields_cannot_be_blank(self):
        for field_name in (
            "source_account",
            "external_id",
            "canonical_url",
            "content_type",
            "observed_at",
        ):
            with self.assertRaises(ValueError):
                _raw(**{field_name: ""})


class NormalizeInstagramPostTest(unittest.TestCase):
    def test_conforms_to_observation_input_contract(self):
        observation = normalize_instagram_post(_raw())

        self.assertIsInstance(observation, TrendObservationInput)
        self.assertEqual(observation.observation_type, "POST")
        self.assertEqual(observation.external_id, "ABC123")
        self.assertEqual(
            observation.url,
            "https://www.instagram.com/p/ABC123/",
        )
        self.assertEqual(observation.author, "example_account")
        self.assertEqual(observation.observed_at, "2026-10-11T10:00:00+00:00")

    def test_caption_and_explicit_hashtags(self):
        observation = normalize_instagram_post(
            _raw(
                caption="Great trip #travel #spain",
                hashtags=("travel", "spain"),
            )
        )

        self.assertEqual(observation.body_text, "Great trip #travel #spain")
        self.assertEqual(observation.metadata["hashtags"], ["travel", "spain"])

    def test_hashtags_are_extracted_from_caption_when_not_explicit(self):
        observation = normalize_instagram_post(
            _raw(caption="Visiting #madrid today")
        )

        self.assertEqual(observation.metadata["hashtags"], ["madrid"])

    def test_missing_hashtags_remain_null_not_guessed(self):
        observation = normalize_instagram_post(_raw(caption="No tags here"))

        self.assertIsNone(observation.metadata["hashtags"])

    def test_missing_metrics_remain_null_not_guessed(self):
        observation = normalize_instagram_post(_raw())

        metrics = observation.metadata["metrics"]
        self.assertIsNone(metrics["like_count"])
        self.assertIsNone(metrics["comment_count"])
        self.assertIsNone(metrics["view_count"])

    def test_visible_metrics_are_preserved(self):
        observation = normalize_instagram_post(
            _raw(like_count=10, comment_count=2, view_count=None)
        )

        metrics = observation.metadata["metrics"]
        self.assertEqual(metrics["like_count"], 10)
        self.assertEqual(metrics["comment_count"], 2)
        self.assertIsNone(metrics["view_count"])

    def test_content_type_is_preserved_per_item(self):
        reel = normalize_instagram_post(
            _raw(
                content_type="REEL",
                external_id="REEL1",
                canonical_url="https://www.instagram.com/reel/REEL1/",
            )
        )
        self.assertEqual(reel.observation_type, "REEL")

    def test_rejects_non_raw_observation(self):
        with self.assertRaises(TypeError):
            normalize_instagram_post({"not": "a raw observation"})


class InstagramTrendSourceAdapterTest(unittest.TestCase):
    def test_source_code_required(self):
        with self.assertRaises(ValueError):
            InstagramTrendSourceAdapter("", [])

    def test_rejects_non_instagram_raw_items(self):
        with self.assertRaises(TypeError):
            InstagramTrendSourceAdapter("INSTAGRAM_TEST", [object()])

    def test_conforms_to_trend_source_adapter_protocol(self):
        adapter = InstagramTrendSourceAdapter(
            "INSTAGRAM_TEST",
            [_raw()],
        )

        # TrendSourceAdapter is a plain (non runtime-checkable) Protocol:
        # conformance is structural, proven via the required members.
        self.assertTrue(hasattr(adapter, "source_code"))
        self.assertTrue(callable(getattr(adapter, "collect", None)))
        self.assertEqual(adapter.source_code, "INSTAGRAM_TEST")

        observations = list(adapter.collect())
        self.assertEqual(len(observations), 1)
        self.assertIsInstance(observations[0], TrendObservationInput)

    def test_two_different_posts_remain_distinct(self):
        adapter = InstagramTrendSourceAdapter(
            "INSTAGRAM_TEST",
            [
                _raw(external_id="POST-1"),
                _raw(
                    external_id="POST-2",
                    canonical_url="https://www.instagram.com/p/POST-2/",
                ),
            ],
        )

        observations = list(adapter.collect())
        external_ids = {item.external_id for item in observations}
        self.assertEqual(external_ids, {"POST-1", "POST-2"})


if __name__ == "__main__":
    unittest.main()
