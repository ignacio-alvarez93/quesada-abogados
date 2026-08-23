import json
from pathlib import Path


ROOT = Path(__file__).parents[2]

CONTRACT_PATH = (
    ROOT
    / "tools"
    / "mercurio_lab"
    / "contracts"
    / "entry_options_v1.json"
)


def _contract():
    return json.loads(
        CONTRACT_PATH.read_text(
            encoding="utf-8"
        )
    )


def test_entry_options_contract_is_sanitized():
    data = _contract()

    assert set(data) == {
        "schema_version",
        "source",
        "source_capture_id",
        "route",
        "state",
        "operations",
        "provinces",
        "continue_control",
    }

    assert data["schema_version"] == 1
    assert (
        data["source"]
        == "SITE_ARCHITECTURE_SANITIZED"
    )
    assert (
        data["route"]
        == "/mercurio/entradaMercurio.html"
    )
    assert (
        data["state"]
        == "MERCURIO_ENTRY_OPTIONS"
    )

    for operation in data["operations"]:
        assert set(operation) == {
            "id",
            "value",
            "label",
        }

    for province in data["provinces"]:
        assert set(province) == {
            "value",
            "label",
        }

    assert set(data["continue_control"]) == {
        "text",
        "onclick",
    }


def test_entry_options_operations_match_observation():
    data = _contract()

    operations = {
        item["value"]: (
            item["id"],
            item["label"],
        )
        for item in data["operations"]
    }

    assert operations == {
        "BT": (
            "bscTran",
            (
                "Solicitud aplicación disposición "
                "transitoria segunda RD 1155/2024"
            ),
        ),
        "BA": (
            "bscAdae",
            "Aportar documentos a expedientes",
        ),
        "BR": (
            "bscRenovacion",
            (
                "Presentar renovación/"
                "Obtener resguardo renovación"
            ),
        ),
        "BI": (
            "bscIniciales",
            "Presentar nueva solicitud",
        ),
        "BREC": (
            "bscRecurso",
            "Presentar recurso",
        ),
    }


def test_entry_options_province_catalog_matches_observation():
    data = _contract()

    provinces = data["provinces"]

    assert len(provinces) == 52

    assert {
        item["value"]: item["label"]
        for item in provinces
    }["33"] == "ASTURIAS"

    assert len(
        {
            item["value"]
            for item in provinces
        }
    ) == 52


def test_entry_options_continue_contract():
    data = _contract()

    assert data["continue_control"] == {
        "text": "CONTINUAR",
        "onclick": "irOpcion()",
    }
