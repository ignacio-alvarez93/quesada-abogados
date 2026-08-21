"""
Smoke visual aislado de Citas ICP Plus.

NO:
- login;
- base de datos real;
- Selenium;
- Chrome;
- ICP Plus;
- llamadas de red.

Permite iterar exclusivamente sobre diseño Flet.
"""

from __future__ import annotations

from copy import deepcopy
import importlib

import flet as ft

from frontend.layouts.main_layout import (
    main_layout,
)
from frontend.layouts.sidebar import (
    sidebar_menu,
)


view_module = importlib.import_module(
    "frontend.views.icpplus_view"
)


FLOW = (
    "POLICIA_TOMA_HUELLAS_TIE"
)


OFFICES = {
    "ASTURIAS": [
        (
            "CNP_OVIEDO_EXPEDICION_TIE",
            "CNP Oviedo",
        ),
        (
            "CNP_GIJON",
            "CNP Gijón",
        ),
        (
            "CNP_AVILES",
            "CNP Avilés",
        ),
        (
            "CNP_LUARCA",
            "CNP Luarca",
        ),
    ],

    "MADRID": [
        (
            "CNP_MADRID_ALUCHE",
            "CNP Madrid · Aluche",
        ),
        (
            "CNP_MADRID_CENTRO",
            "CNP Madrid · Centro",
        ),
    ],

    "BARCELONA": [
        (
            "CNP_BARCELONA",
            "CNP Barcelona",
        ),
    ],

    "VALENCIA": [
        (
            "CNP_VALENCIA",
            "CNP Valencia",
        ),
    ],

    "MALAGA": [
        (
            "CNP_MALAGA",
            "CNP Málaga",
        ),
    ],
}


def card(
    province,
    office_key,
    office_text,
    *,
    portal="ONLINE",
    availability="UNAVAILABLE",
    appointments=None,
    checked_at="2026-08-21T10:00:00+02:00",
):
    appointments = list(
        appointments
        or []
    )

    return {
        "key":
            (
                "ICP_PLUS|"
                + province
                + ":"
                + FLOW
                + "|"
                + office_key
            ),

        "provider":
            "ICP_PLUS",

        "flow_key":
            (
                province
                + ":"
                + FLOW
            ),

        "province_key":
            province,

        "province_text":
            province.title(),

        "procedure_key":
            FLOW,

        "procedure_text":
            "Policía · Toma de huellas TIE",

        "office_key":
            office_key,

        "office_text":
            office_text,

        "pending":
            False,

        "current": {
            "checked_at":
                checked_at,

            "portal_status":
                portal,

            "availability_status":
                availability,

            "result_class":
                availability,

            "appointments":
                deepcopy(
                    appointments
                ),

            "appointment_count":
                len(
                    appointments
                ),

            "support_id":
                (
                    "6677429513471345431"
                    if portal == "BLOCKED"
                    else None
                ),

            "navigation_error":
                None,
        },

        "last_valid": {
            "checked_at":
                checked_at,

            "portal_status":
                "ONLINE",

            "availability_status":
                availability,

            "appointments":
                deepcopy(
                    appointments
                ),
        },

        "last_known_appointments":
            deepcopy(
                appointments
            ),
    }


CARDS = [
    card(
        "ASTURIAS",
        "CNP_OVIEDO_EXPEDICION_TIE",
        "CNP Oviedo",
        availability="AVAILABLE",
        appointments=[
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
        checked_at=(
            "2026-08-21T10:24:13+02:00"
        ),
    ),

    card(
        "ASTURIAS",
        "CNP_GIJON",
        "CNP Gijón",
        availability="AVAILABLE",
        appointments=[
            {
                "date":
                    "04/09/2026",
                "time":
                    "09:30",
            },
        ],
        checked_at=(
            "2026-08-21T10:09:52+02:00"
        ),
    ),

    card(
        "ASTURIAS",
        "CNP_AVILES",
        "CNP Avilés",
        availability="UNAVAILABLE",
        checked_at=(
            "2026-08-21T09:54:10+02:00"
        ),
    ),

    card(
        "MADRID",
        "CNP_MADRID_ALUCHE",
        "CNP Madrid · Aluche",
        availability="AVAILABLE",
        appointments=[
            {
                "date":
                    "05/09/2026",
                "time":
                    "10:15",
            },
        ],
        checked_at=(
            "2026-08-21T09:39:08+02:00"
        ),
    ),

    card(
        "BARCELONA",
        "CNP_BARCELONA",
        "CNP Barcelona",
        availability="AVAILABLE",
        appointments=[
            {
                "date":
                    "07/09/2026",
                "time":
                    "11:00",
            },
        ],
        checked_at=(
            "2026-08-21T09:24:05+02:00"
        ),
    ),

    card(
        "VALENCIA",
        "CNP_VALENCIA",
        "CNP Valencia",
        availability="UNAVAILABLE",
        checked_at=(
            "2026-08-21T09:10:22+02:00"
        ),
    ),

    card(
        "MALAGA",
        "CNP_MALAGA",
        "CNP Málaga",
        portal="BLOCKED",
        availability="UNKNOWN",
        checked_at=(
            "2026-08-19T16:12:00+02:00"
        ),
    ),
]


HISTORY = []

for index, item in enumerate(
    CARDS
):
    current = item[
        "current"
    ]

    HISTORY.append(
        {
            "provider":
                "ICP_PLUS",

            "province_key":
                item[
                    "province_key"
                ],

            "procedure_key":
                FLOW,

            "office_key":
                item[
                    "office_key"
                ],

            "office_text":
                item[
                    "office_text"
                ],

            "checked_at":
                current[
                    "checked_at"
                ],

            "portal_status":
                current[
                    "portal_status"
                ],

            "availability_status":
                current[
                    "availability_status"
                ],

            "result_class":
                current[
                    "result_class"
                ],

            "appointment_count":
                current[
                    "appointment_count"
                ],

            "appointments":
                deepcopy(
                    current[
                        "appointments"
                    ]
                ),

            "support_id":
                current[
                    "support_id"
                ],
        }
    )


# Añadimos histórico visual adicional para comprobar
# realmente la paginación 10/página.
#
# Solo afecta al smoke: jamás a producción.
_HISTORY_BASE = [
    item
    for item in HISTORY
    if item.get(
        "appointments"
    )
]

for index in range(
    12
):
    if not _HISTORY_BASE:
        break

    source = deepcopy(
        _HISTORY_BASE[
            index
            % len(
                _HISTORY_BASE
            )
        ]
    )

    hour = 8 + (
        index
        // 4
    )

    minute = (
        index
        * 7
    ) % 60

    source[
        "checked_at"
    ] = (
        "2026-08-20T"
        f"{hour:02d}:"
        f"{minute:02d}:00+02:00"
    )

    # Una pasada visual completa con 3 citas.
    source[
        "appointments"
    ] = [
        {
            "date":
                f"{10 + index:02d}/09/2026",
            "time":
                "09:00",
        },
        {
            "date":
                f"{10 + index:02d}/09/2026",
            "time":
                "11:30",
        },
        {
            "date":
                f"{10 + index:02d}/09/2026",
            "time":
                "13:00",
        },
    ]

    source[
        "appointment_count"
    ] = 3

    HISTORY.append(
        source
    )


PROFILE = {
    "icpplus_nombre":
        "PERFIL PRUEBA",

    "icpplus_nacionalidad":
        "ESPAÑA",

    "icpplus_nie":
        "X0000000A",

    "icpplus_telefono":
        "600000000",

    "icpplus_email":
        "prueba@example.test",
}


class FakeService:
    def list_supported_flows(
        self,
    ):
        result = []

        for province in OFFICES:
            result.append(
                {
                    "province_key":
                        province,

                    "province_text":
                        province.title(),

                    "procedure_key":
                        FLOW,

                    "procedure_text":
                        (
                            "Policía · "
                            "Toma de huellas TIE"
                        ),
                }
            )

        return result


    def list_offices(
        self,
        province_key,
        procedure_key,
    ):
        return [
            {
                "key":
                    key,

                "provider_text":
                    text,
            }
            for key, text
            in OFFICES.get(
                province_key,
                []
            )
        ]


    def check_availability(
        self,
        **kwargs,
    ):
        # Smoke visual: jamás consulta el portal.
        return {
            "page":
                "VISUAL_SMOKE",

            "portal_status":
                "ONLINE",

            "availability_status":
                "AVAILABLE",

            "result_class":
                "AVAILABLE",

            "appointments": [
                {
                    "date":
                        "10/09/2026",
                    "time":
                        "10:00",
                },
            ],

            "support_id":
                None,

            "navigation_error":
                None,
        }


    def close(
        self,
    ):
        return None


def configure_fake_services():
    view_module.icpplus_profile_service.get_profile = (
        lambda:
            deepcopy(
                PROFILE
            )
    )

    view_module.icpplus_profile_service.save_profile = (
        lambda value:
            deepcopy(
                value
            )
    )

    view_module.icpplus_state_service.list_cards = (
        lambda:
            deepcopy(
                CARDS
            )
    )

    view_module.icpplus_state_service.list_history = (
        lambda limit=50:
            deepcopy(
                HISTORY[:limit]
            )
    )

    view_module.icpplus_state_service.record_result = (
        lambda **kwargs:
            None
    )

    view_module.icpplus_test_reservation_service.get_active_reservation = (
        lambda: {
            "provider":
                "ICP_PLUS",

            "province_key":
                "ASTURIAS",

            "procedure_key":
                FLOW,

            "office_key":
                "CNP_OVIEDO_EXPEDICION_TIE",

            "office_text":
                "CNP Oviedo",

            "appointment_date":
                "12/09/2026",

            "appointment_time":
                "09:15",

            "reserved_at":
                "2026-08-21T08:30:00+02:00",
        }
    )


def main(
    page: ft.Page,
):
    configure_fake_services()

    page.title = (
        "ICP Plus · Visual Smoke"
    )

    page.padding = 0
    page.bgcolor = "#F5F9FF"

    # El ERP real se utiliza maximizado.
    # El smoke visual debe reproducir exactamente ese contrato.
    try:
        page.window.maximized = True
    except Exception:
        pass

    content = (
        view_module.icpplus_view(
            page,
            service=FakeService(),
        )
    )

    page.add(
        main_layout(
            sidebar=sidebar_menu(
                on_navigate=lambda _:
                    None
            ),
            content=content,
        )
    )


if __name__ == "__main__":
    ft.run(
        main
    )
