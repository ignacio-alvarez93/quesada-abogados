from unittest.mock import patch

from backend.services import (
    icpplus_state_service
    as service
)


class MemoryConfig:
    def __init__(self):
        self.values = {}

    def get_config(
        self,
        key,
        default="",
    ):
        return self.values.get(
            key,
            default,
        )

    def set_config(
        self,
        key,
        value,
    ):
        self.values[key] = value


def _record():
    return service.record_result(
        provider="ICP_PLUS",
        flow_key=(
            "ASTURIAS:"
            "POLICIA_TOMA_HUELLAS_TIE"
        ),
        province_key="ASTURIAS",
        procedure_key=(
            "POLICIA_TOMA_HUELLAS_TIE"
        ),
        office_key=(
            "CNP_OVIEDO_EXPEDICION_TIE"
        ),
        office_text="CNP Oviedo",
        result={
            "page":
                "OFFER_APPOINTMENT",

            "portal_status":
                "ONLINE",

            "availability_status":
                "AVAILABLE",

            "result_class":
                "AVAILABLE",

            "appointments": [
                {
                    "date":
                        "01/09/2026",
                    "time":
                        "12:00",
                },
                {
                    "date":
                        "03/09/2026",
                    "time":
                        "16:00",
                },
            ],
        },
        checked_at=(
            "2026-08-21T11:30:00+02:00"
        ),
    )


def test_record_result_adds_history():
    memory = MemoryConfig()

    with (
        patch.object(
            service.config_service,
            "get_config",
            side_effect=memory.get_config,
        ),
        patch.object(
            service.config_service,
            "set_config",
            side_effect=memory.set_config,
        ),
    ):
        _record()

        history = service.list_history()

    assert len(history) == 1
    assert history[0]["province_key"] == "ASTURIAS"
    assert history[0]["appointment_count"] == 2
    assert history[0]["availability_status"] == "AVAILABLE"

    assert history[0]["appointments"] == [
        {
            "date":
                "01/09/2026",
            "time":
                "12:00",
        },
        {
            "date":
                "03/09/2026",
            "time":
                "16:00",
        },
    ]


def test_history_is_newest_first():
    memory = MemoryConfig()

    with (
        patch.object(
            service.config_service,
            "get_config",
            side_effect=memory.get_config,
        ),
        patch.object(
            service.config_service,
            "set_config",
            side_effect=memory.set_config,
        ),
    ):
        _record()

        service.record_result(
            provider="ICP_PLUS",
            flow_key=(
                "ASTURIAS:"
                "POLICIA_TOMA_HUELLAS_TIE"
            ),
            province_key="ASTURIAS",
            procedure_key=(
                "POLICIA_TOMA_HUELLAS_TIE"
            ),
            office_key="CNP_GIJON",
            office_text="CNP Gijón",
            result={
                "portal_status":
                    "ONLINE",
                "availability_status":
                    "UNAVAILABLE",
                "appointments":
                    [],
            },
            checked_at=(
                "2026-08-21T11:40:00+02:00"
            ),
        )

        history = service.list_history()

    assert len(history) == 2
    assert history[0]["office_key"] == "CNP_GIJON"
