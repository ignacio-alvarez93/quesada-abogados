"""
Servicio de aplicación para disponibilidad de citas ICP Plus.

Responsabilidades:
- leer catálogo de flujos soportados;
- validar provincia/trámite/oficina;
- construir request independiente del portal;
- obtener identidad desde icpplus_profile_service;
- delegar ejecución al IcpPlusRuntimeService;
- normalizar el resultado para Flet.

No contiene SQL.
No contiene SeleniumBase.
No contiene Win32.
No conoce controles Flet.
"""

import json
from pathlib import Path

from backend.services import (
    icpplus_profile_service,
)
from backend.services.icpplus_runtime_service import (
    IcpPlusRuntimeService,
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

SUPPORTED_FLOWS_PATH = (
    PROJECT_ROOT
    / "config"
    / "automation"
    / "icpplus"
    / "supported_flows.json"
)

VALID_PORTAL_STATUSES = {
    "ONLINE",
    "BLOCKED",
    "DEGRADED",
    "DOWN",
    "UNKNOWN",
}

VALID_AVAILABILITY_STATUSES = {
    "AVAILABLE",
    "UNAVAILABLE",
    "UNKNOWN",
}

VALID_OFFICE_SCOPES = {
    "ALL",
    "SINGLE",
}


class IcpPlusAvailabilityService:
    def __init__(
        self,
        *,
        runtime=None,
        flows_path=None,
    ):
        self.runtime = (
            runtime
            or IcpPlusRuntimeService()
        )

        self.flows_path = Path(
            flows_path
            or SUPPORTED_FLOWS_PATH
        )


    def _load_config(self):
        if not self.flows_path.exists():
            raise RuntimeError(
                "ICPPLUS_SUPPORTED_FLOWS_NOT_FOUND:"
                f"{self.flows_path}"
            )

        data = json.loads(
            self.flows_path.read_text(
                encoding="utf-8"
            )
        )

        if (
            data.get("provider")
            != "ICP_PLUS"
        ):
            raise RuntimeError(
                "ICPPLUS_PROVIDER_CONFIG_INVALID"
            )

        flows = (
            data.get("flows")
            or {}
        )

        if not isinstance(
            flows,
            dict,
        ):
            raise RuntimeError(
                "ICPPLUS_FLOWS_CONFIG_INVALID"
            )

        return data


    def list_supported_flows(self):
        data = self._load_config()

        result = []

        for flow_key, flow in (
            data["flows"].items()
        ):
            result.append({
                "flow_key":
                    flow_key,

                "province_key":
                    (
                        flow.get("province")
                        or {}
                    ).get("key"),

                "province_text":
                    (
                        flow.get("province")
                        or {}
                    ).get("provider_text"),

                "procedure_key":
                    (
                        flow.get("procedure")
                        or {}
                    ).get("key"),

                "procedure_text":
                    (
                        flow.get("procedure")
                        or {}
                    ).get("provider_text"),

                "office_scope_supported":
                    list(
                        flow.get(
                            "office_scope_supported"
                        )
                        or []
                    ),
            })

        return result


    def get_flow(
        self,
        province_key,
        procedure_key,
    ):
        province_key = str(
            province_key
            or ""
        ).strip().upper()

        procedure_key = str(
            procedure_key
            or ""
        ).strip().upper()

        if (
            not province_key
            or not procedure_key
        ):
            raise ValueError(
                "Provincia y trámite "
                "son obligatorios"
            )

        flow_key = (
            f"{province_key}:"
            f"{procedure_key}"
        )

        data = self._load_config()

        flow = (
            data["flows"].get(
                flow_key
            )
        )

        if not flow:
            raise ValueError(
                "Flujo ICP Plus "
                "no soportado:"
                f"{flow_key}"
            )

        return (
            flow_key,
            flow,
        )


    def list_offices(
        self,
        province_key,
        procedure_key,
    ):
        _, flow = self.get_flow(
            province_key,
            procedure_key,
        )

        office_config = (
            flow.get(
                "procedure_specific_offices"
            )
            or {}
        )

        return [
            dict(item)
            for item in (
                office_config.get(
                    "items"
                )
                or []
            )
        ]


    @staticmethod
    def _normalize_contact(
        contact,
    ):
        contact = dict(
            contact
            or {}
        )

        phone = str(
            contact.get("telefono")
            or contact.get("phone")
            or ""
        ).strip()

        email = str(
            contact.get("email")
            or ""
        ).strip()

        errors = []

        if not phone:
            errors.append(
                "Teléfono obligatorio"
            )

        if not email:
            errors.append(
                "Email obligatorio"
            )

        elif "@" not in email:
            errors.append(
                "Email no válido"
            )

        if errors:
            raise ValueError(
                "; ".join(errors)
            )

        return {
            "telefono":
                phone,
            "email":
                email,
        }


    def build_request(
        self,
        *,
        province_key,
        procedure_key,
        office_scope="SINGLE",
        office_key=None,
        profile=None,
        contact=None,
    ):
        flow_key, flow = self.get_flow(
            province_key,
            procedure_key,
        )

        office_scope = str(
            office_scope
            or ""
        ).strip().upper()

        if (
            office_scope
            not in VALID_OFFICE_SCOPES
        ):
            raise ValueError(
                "office_scope ICP Plus "
                "no válido"
            )

        supported_scopes = set(
            flow.get(
                "office_scope_supported"
            )
            or []
        )

        if (
            office_scope
            not in supported_scopes
        ):
            raise ValueError(
                "office_scope no soportado "
                "por este flujo"
            )

        office = None

        if office_scope == "SINGLE":

            office_key = str(
                office_key
                or ""
            ).strip().upper()

            if not office_key:
                raise ValueError(
                    "Oficina obligatoria "
                    "para office_scope SINGLE"
                )

            offices = self.list_offices(
                province_key,
                procedure_key,
            )

            office = next(
                (
                    item
                    for item in offices
                    if str(
                        item.get("key")
                        or ""
                    ).strip().upper()
                    == office_key
                ),
                None,
            )

            if office is None:
                raise ValueError(
                    "Oficina ICP Plus "
                    "no soportada:"
                    f"{office_key}"
                )

        identity = (
            icpplus_profile_service
            .build_payload(
                profile
            )
        )

        contact_source = (
            contact
            if contact is not None
            else (
                icpplus_profile_service
                .build_contact_payload(
                    profile
                )
            )
        )

        normalized_contact = (
            self._normalize_contact(
                contact_source
            )
        )

        return {
            "provider":
                "ICP_PLUS",

            "flow_key":
                flow_key,

            "province":
                dict(
                    flow.get(
                        "province"
                    )
                    or {}
                ),

            "procedure":
                dict(
                    flow.get(
                        "procedure"
                    )
                    or {}
                ),

            "office_scope":
                office_scope,

            "office":
                (
                    dict(office)
                    if office
                    else None
                ),

            "identity":
                identity,

            "contact":
                normalized_contact,
        }


    @staticmethod
    def normalize_result(
        result,
    ):
        result = dict(
            result
            or {}
        )

        portal_status = str(
            result.get(
                "portal_status"
            )
            or "UNKNOWN"
        ).strip().upper()

        availability_status = str(
            result.get(
                "availability_status"
            )
            or "UNKNOWN"
        ).strip().upper()

        if (
            portal_status
            not in VALID_PORTAL_STATUSES
        ):
            portal_status = "UNKNOWN"

        if (
            availability_status
            not in VALID_AVAILABILITY_STATUSES
        ):
            availability_status = (
                "UNKNOWN"
            )

        appointments = (
            result.get(
                "appointments"
            )
            or []
        )

        if not isinstance(
            appointments,
            list,
        ):
            appointments = []

        # Nunca inferir disponibilidad cuando el portal
        # no ha proporcionado un resultado fiable.
        if portal_status != "ONLINE":
            availability_status = (
                "UNKNOWN"
            )

        return {
            "provider":
                "ICP_PLUS",

            "flow_key":
                result.get(
                    "flow_key"
                ),

            "page":
                result.get(
                    "page"
                )
                or "UNKNOWN",

            "portal_status":
                portal_status,

            "availability_status":
                availability_status,

            "appointments":
                list(appointments),

            "appointment_count":
                len(appointments),

            "support_id":
                result.get(
                    "support_id"
                ),

            "navigation_error":
                result.get(
                    "navigation_error"
                ),

            "result_class":
                result.get(
                    "result_class"
                )
                or availability_status,

            "process_returncode":
                result.get(
                    "process_returncode"
                ),
        }


    def check_availability(
        self,
        *,
        province_key,
        procedure_key,
        office_scope="SINGLE",
        office_key=None,
        profile=None,
        contact=None,
    ):
        request = self.build_request(
            province_key=(
                province_key
            ),
            procedure_key=(
                procedure_key
            ),
            office_scope=(
                office_scope
            ),
            office_key=(
                office_key
            ),
            profile=profile,
            contact=contact,
        )

        result = (
            self.runtime
            .check_availability(
                request
            )
        )

        result = dict(
            result
            or {}
        )

        result.setdefault(
            "flow_key",
            request[
                "flow_key"
            ],
        )

        return (
            self.normalize_result(
                result
            )
        )


    def close(self):
        return self.runtime.close()
