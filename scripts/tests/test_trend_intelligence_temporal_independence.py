import unittest
from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

FILES = (
    ROOT
    / "backend"
    / "trend_intelligence"
    / "temporal.py",

    ROOT
    / "database"
    / "migrations"
    / "20260921_01_create_trend_intelligence_temporal.sql",
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


class TrendIntelligenceTemporalIndependenceTest(
    unittest.TestCase
):
    def test_temporal_layer_has_no_vertical_leaks(
        self,
    ):
        for path in FILES:
            raw = (
                path.read_text(
                    encoding="utf-8"
                )
                .lower()
            )

            for term in FORBIDDEN:
                self.assertNotIn(
                    term,
                    raw,
                    msg=(
                        f"{term!r} "
                        f"in {path}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
