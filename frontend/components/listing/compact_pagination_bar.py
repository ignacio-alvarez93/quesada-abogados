import flet as ft

Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#D0D5DD"
Q_MUTED = "#64748B"


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _pagination_icon_button(label, target_page, on_page_change, disabled=False):
    return ft.Container(
        width=34,
        height=30,
        alignment=ft.Alignment(0, 0),
        border=ft.border.all(1, "#CBD5E1"),
        border_radius=8,
        bgcolor="#F8FAFC" if not disabled else "#F1F5F9",
        ink=not disabled,
        on_click=None if disabled else lambda e, target_page=target_page: on_page_change(target_page),
        content=ft.Text(
            label,
            size=13,
            color=Q_PRIMARY_DARK if not disabled else "#94A3B8",
            weight=ft.FontWeight.BOLD,
        ),
    )


def compact_pagination_bar(
    page,
    page_size,
    total_items,
    on_page_change,
    label_prefix="Página",
):
    """
    Barra compacta de paginación para colocar junto a chips o cabeceras.

    No conoce servicios ni estado global:
    - recibe página actual
    - tamaño de página
    - total de elementos
    - callback on_page_change(page_number)
    """
    current_page = max(1, _safe_int(page, 1))
    safe_page_size = max(1, _safe_int(page_size, 10))
    safe_total = max(0, _safe_int(total_items, 0))

    total_pages = max(1, (safe_total + safe_page_size - 1) // safe_page_size)
    current_page = max(1, min(current_page, total_pages))

    start_index = 0 if safe_total == 0 else ((current_page - 1) * safe_page_size) + 1
    end_index = min(safe_total, current_page * safe_page_size)

    previous_disabled = current_page <= 1
    next_disabled = current_page >= total_pages

    label = f"Mostrando {start_index}-{end_index} de {safe_total} · Página {current_page} de {total_pages}"

    return ft.Container(
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=12,
        padding=ft.padding.symmetric(horizontal=8, vertical=5),
        content=ft.Row(
            controls=[
                ft.Text(label_prefix, size=11, color=Q_MUTED, weight=ft.FontWeight.BOLD),
                _pagination_icon_button("⏮", 1, on_page_change, previous_disabled),
                _pagination_icon_button("◀", current_page - 1, on_page_change, previous_disabled),
                ft.Text(label, color=Q_MUTED, size=12),
                _pagination_icon_button("▶", current_page + 1, on_page_change, next_disabled),
                _pagination_icon_button("⏭", total_pages, on_page_change, next_disabled),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )
