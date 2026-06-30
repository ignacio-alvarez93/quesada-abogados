import flet as ft

Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#D0D5DD"
Q_MUTED = "#64748B"


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def pagination_bar(
    page,
    page_size,
    total_items,
    on_page_change,
    label=None,
    compact=False,
):
    """
    Barra de paginación reutilizable.

    No conoce servicios ni módulos concretos.
    Recibe página, tamaño, total y callback.
    """
    current_page = max(1, _safe_int(page, 1))
    safe_page_size = max(1, _safe_int(page_size, 10))
    safe_total = max(0, _safe_int(total_items, 0))

    total_pages = max(1, (safe_total + safe_page_size - 1) // safe_page_size)
    current_page = max(1, min(current_page, total_pages))

    start_index = 0 if safe_total == 0 else ((current_page - 1) * safe_page_size) + 1
    end_index = min(safe_total, current_page * safe_page_size)

    resolved_label = label or (
        f"Mostrando {start_index}-{end_index} de {safe_total} · "
        f"Página {current_page} de {total_pages}"
    )

    previous_disabled = current_page <= 1
    next_disabled = current_page >= total_pages

    button_height = 30 if compact else 34

    return ft.Container(
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=12,
        padding=ft.padding.symmetric(horizontal=8, vertical=6),
        content=ft.Row(
            controls=[
                ft.Text(
                    resolved_label,
                    size=11 if compact else 12,
                    color=Q_MUTED,
                    weight=ft.FontWeight.W_500,
                ),
                ft.Container(expand=True),
                ft.ElevatedButton(
                    "« Primera",
                    height=button_height,
                    disabled=previous_disabled,
                    on_click=lambda e: on_page_change(1),
                ),
                ft.ElevatedButton(
                    "‹ Anterior",
                    height=button_height,
                    disabled=previous_disabled,
                    on_click=lambda e: on_page_change(current_page - 1),
                ),
                ft.Text(
                    f"{current_page}/{total_pages}",
                    size=12,
                    color=Q_PRIMARY_DARK,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.ElevatedButton(
                    "Siguiente ›",
                    height=button_height,
                    disabled=next_disabled,
                    on_click=lambda e: on_page_change(current_page + 1),
                ),
                ft.ElevatedButton(
                    "Última »",
                    height=button_height,
                    disabled=next_disabled,
                    on_click=lambda e: on_page_change(total_pages),
                ),
            ],
            spacing=6,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )
