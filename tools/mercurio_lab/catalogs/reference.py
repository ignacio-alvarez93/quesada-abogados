import json
from functools import lru_cache
from pathlib import Path


_CATALOG_PATH = (
    Path(__file__).parent
    / "mercurio_reference_catalogs.json"
)


@lru_cache(maxsize=1)
def load_reference_catalogs() -> dict:
    data = json.loads(
        _CATALOG_PATH.read_text(
            encoding="utf-8"
        )
    )

    if data.get("schema_version") != 1:
        raise ValueError(
            "Unsupported Mercurio catalog schema"
        )

    return data


def _pairs(rows) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            str(row.get("value") or ""),
            str(row.get("label") or ""),
        )
        for row in rows
    )


def country_options():
    return _pairs(
        load_reference_catalogs()["countries"]
    )


def nationality_options():
    return _pairs(
        load_reference_catalogs()[
            "nationalities"
        ]
    )


def province_options():
    return _pairs(
        load_reference_catalogs()["provinces"]
    )


def municipality_options(
    province_code: str,
):
    rows = (
        load_reference_catalogs()
        .get("municipalities", {})
        .get(str(province_code), [])
    )

    return _pairs(rows)


def locality_options(
    province_code: str,
    municipality_code: str,
):
    key = (
        f"{province_code}:"
        f"{municipality_code}"
    )

    rows = (
        load_reference_catalogs()
        .get("localities", {})
        .get(key, [])
    )

    if not rows:
        return (("", "--"),)

    return _pairs(rows)
