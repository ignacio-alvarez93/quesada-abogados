import unittest
from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

CORE = (
    ROOT
    / "backend"
    / "trend_intelligence"
)

REPOSITORIES = (
    ROOT
    / "backend"
    / "repositories"
)

MIGRATION = (
    ROOT
    / "database"
    / "migrations"
    / "20260920_01_create_trend_intelligence_core.sql"
)


FORBIDDEN_CORE_TERMS = (
    "arraigo",
    "extranjer",
    "nacionalidad",
    "mercurio",
    "dgt",
    "tráfico",
    "trafico",
    "seguro",
    "insurance",
)


class TrendIntelligenceVerticalIndependenceTest(
    unittest.TestCase
):
    def test_core_has_no_vertical_business_terms(
        self,
    ):
        files = list(
            CORE.rglob(
                "*.py"
            )
        )

        files.extend(
            [
                REPOSITORIES
                / "trend_intelligence_repository.py",

                REPOSITORIES
                / "sqlite_trend_intelligence_repository.py",

                MIGRATION,
            ]
        )

        for path in files:
            raw = (
                path.read_text(
                    encoding="utf-8"
                )
                .lower()
            )

            for term in (
                FORBIDDEN_CORE_TERMS
            ):
                self.assertNotIn(
                    term,
                    raw,
                    msg=(
                        f"Vertical leak: "
                        f"{term!r} in {path}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
