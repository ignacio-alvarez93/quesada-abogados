import unittest
from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

TARGET = (
    ROOT
    / "backend"
    / "trend_intelligence"
    / "detection.py"
)

FORBIDDEN = (
    "arraigo",
    "extranjer",
    "nacionalidad",
    "mercurio",
    "dgt",
    "trafico",
    "tráfico",
    "seguro",
    "insurance",
)


class TrendIntelligenceDetectionIndependenceTest(
    unittest.TestCase
):
    def test_detector_has_no_vertical_terms(
        self,
    ):
        raw = (
            TARGET
            .read_text(
                encoding="utf-8"
            )
            .lower()
        )

        for term in FORBIDDEN:
            self.assertNotIn(
                term,
                raw,
            )


if __name__ == "__main__":
    unittest.main()
