from __future__ import annotations

from typing import Any, Callable

import flet as ft

from frontend.components import status_badge
from frontend.components.listing import card_item


Q_PRIMARY = "#0057B8"
Q_MUTED = "#64748B"
Q_SUCCESS = "#027A48"
Q_DANGER = "#B42318"


STATUS_LABELS = {
    "ACTIVE": "Activo",
    "TEMPORARY_LEAVE": "Baja temporal",
    "SICK_LEAVE": "Baja médica",
    "MATERNITY_PATERNITY": "Nacimiento y cuidado",
    "LEAVE_OF_ABSENCE": "Excedencia",
    "TERMINATED": "Finalizado",
}


def _text(value: Any, fallback: str = "") -> str:
    value = str(value or "").strip()
    return value or fallback


def _full_name(worker: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [
            _text(worker.get("first_name")),
            _text(worker.get("last_name_1")),
            _text(worker.get("last_name_2")),
        ]
        if part
    ) or f"Trabajador #{worker.get('id') or '-'}"


def _action_menu(
    worker: dict[str, Any],
    *,
    on_open: Callable[[dict[str, Any]], None] | None,
    on_edit: Callable[[dict[str, Any]], None] | None,
    on_toggle_active: Callable[[dict[str, Any]], None] | None,
) -> ft.Control | None:
    items = []

    if on_open:
        items.append(
            ft.PopupMenuItem(
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.VISIBILITY_OUTLINED,
                            size=16,
                            color=Q_PRIMARY,
                        ),
                        ft.Text("Ver ficha"),
                    ],
                    spacing=8,
                ),
                on_click=lambda e: on_open(worker),
            )
        )

    if on_edit:
        items.append(
            ft.PopupMenuItem(
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.EDIT_OUTLINED,
                            size=16,
                            color=Q_PRIMARY,
                        ),
                        ft.Text("Editar trabajador"),
                    ],
                    spacing=8,
                ),
                on_click=lambda e: on_edit(worker),
            )
        )

    if on_toggle_active:
        active = bool(worker.get("active"))

        items.append(
            ft.PopupMenuItem(
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            (
                                ft.Icons.PERSON_OFF_OUTLINED
                                if active
                                else ft.Icons.PERSON_ADD_OUTLINED
                            ),
                            size=16,
                            color=(
                                Q_DANGER
                                if active
                                else Q_SUCCESS
                            ),
                        ),
                        ft.Text(
                            (
                                "Finalizar relación laboral"
                                if active
                                else "Reactivar trabajador"
                            )
                        ),
                    ],
                    spacing=8,
                ),
                on_click=lambda e: on_toggle_active(worker),
            )
        )

    if not items:
        return None

    return ft.PopupMenuButton(
        icon=ft.Icons.MORE_VERT,
        tooltip="Acciones del trabajador",
        items=items,
    )


def worker_card(
    worker: dict[str, Any],
    *,
    on_open: Callable[[dict[str, Any]], None] | None = None,
    on_edit: Callable[[dict[str, Any]], None] | None = None,
    on_toggle_active: Callable[[dict[str, Any]], None] | None = None,
) -> ft.Control:
    worker = dict(worker or {})

    active = bool(worker.get("active"))
    status = _text(
        worker.get("employment_status"),
        "ACTIVE",
    )

    badges = [
        status_badge(
            STATUS_LABELS.get(status, status)
        )
    ]

    if worker.get("active_contracts_count"):
        badges.append(
            status_badge(
                f"{worker['active_contracts_count']} contrato(s)"
            )
        )

    body = [
        ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.BADGE_OUTLINED,
                    size=15,
                    color=Q_MUTED,
                ),
                ft.Text(
                    " · ".join(
                        value
                        for value in [
                            _text(worker.get("position")),
                            _text(worker.get("department")),
                            _text(worker.get("workplace")),
                        ]
                        if value
                    )
                    or "Sin puesto asignado",
                    size=11,
                    color=Q_MUTED,
                ),
            ],
            spacing=6,
            wrap=True,
        ),
        ft.Row(
            controls=[
                ft.Icon(
                    ft.Icons.CONTACT_PHONE_OUTLINED,
                    size=15,
                    color=Q_MUTED,
                ),
                ft.Text(
                    " · ".join(
                        value
                        for value in [
                            _text(worker.get("phone")),
                            _text(worker.get("email")),
                        ]
                        if value
                    )
                    or "Sin datos de contacto",
                    size=11,
                    color=Q_MUTED,
                    selectable=True,
                ),
            ],
            spacing=6,
            wrap=True,
        ),
    ]

    menu = _action_menu(
        worker,
        on_open=on_open,
        on_edit=on_edit,
        on_toggle_active=on_toggle_active,
    )

    return card_item(
        title=_full_name(worker).upper(),
        subtitle=" · ".join(
            value
            for value in [
                _text(worker.get("worker_code")),
                _text(worker.get("tax_id")),
                _text(worker.get("social_security_number")),
            ]
            if value
        ),
        badges=badges,
        actions=[menu] if menu else [],
        body=body,
        highlight=not active,
        highlight_color="#F8FAFC",
        border_color=(
            "#D0D5DD"
            if active
            else "#98A2B3"
        ),
        on_click=(
            (lambda e: on_open(worker))
            if on_open
            else None
        ),
        padding=11,
    )
