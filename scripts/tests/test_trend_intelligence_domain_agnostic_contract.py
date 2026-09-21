import unittest
from pathlib import Path


ROOT = (
    Path(__file__).resolve()
    .parents[2]
)

CORE_FILES = (
    ROOT
    / "backend"
    / "trend_intelligence"
)


FORBIDDEN = (
    "immigration_trends",
    "it_sources",
    "it_topics",
    "it_observations",
    "it_signals",
    "it_trends",
)


class TrendIntelligenceDomainAgnosticContractTest(
    unittest.TestCase
):
    def test_core_has_generic_namespace(
        self,
    ):
        self.assertTrue(
            CORE_FILES.exists()
        )

        for path in (
            CORE_FILES
            .glob("*.py")
        ):
            raw = (
                path.read_text(
                    encoding="utf-8"
                )
                .lower()
            )

            for forbidden in (
                FORBIDDEN
            ):
                self.assertNotIn(
                    forbidden,
                    raw,
                    msg=(
                        f"{forbidden} "
                        f"en {path}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
