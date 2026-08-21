"""
ICP Plus · LIVE E2E de la vista CRM.

Este launcher:
- NO arranca el ERP completo;
- NO usa FakeService;
- NO modifica la vista;
- usa IcpPlusAvailabilityService productivo;
- usa el perfil ICP Plus persistido real;
- usa la persistencia real del dashboard;
- puede abrir Chrome y consultar ICP Plus;
- mantiene el límite productivo:
  se detiene antes de CAPTCHA / reserva.
"""

import flet as ft

from backend.services.icpplus_availability_service import (
    IcpPlusAvailabilityService,
)
from frontend.layouts.main_layout import main_layout
from frontend.layouts.sidebar import sidebar_menu
from frontend.views.icpplus_view import icpplus_view


def main(
    page: ft.Page,
):
    page.title = (
        "ICP Plus · LIVE E2E"
    )

    page.padding = 0
    page.bgcolor = "#F5F9FF"

    try:
        page.window.maximized = True
    except Exception:
        pass

    service = (
        IcpPlusAvailabilityService()
    )

    def close_live_service(
        e=None,
    ):
        try:
            result = service.close()

            print(
                "[ICPPLUS-LIVE] close =",
                result,
                flush=True,
            )

        except Exception as exc:
            print(
                "[ICPPLUS-LIVE] close error =",
                repr(exc),
                flush=True,
            )

    page.on_close = (
        close_live_service
    )

    print(
        "======================================================",
        flush=True,
    )
    print(
        " ICP PLUS · LIVE E2E",
        flush=True,
    )
    print(
        " Real IcpPlusAvailabilityService",
        flush=True,
    )
    print(
        " Stop boundary: before CAPTCHA / reservation",
        flush=True,
    )
    print(
        "======================================================",
        flush=True,
    )

    content = icpplus_view(
        page,
        service=service,
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
