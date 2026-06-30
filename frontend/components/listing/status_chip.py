import flet as ft

Q_TEXT = "#0F172A"
Q_MUTED = "#64748B"

DEFAULT_STATUS_MAP = {
    "pending": ("Pendiente", "#FFF7E6", "#B54708"),
    "reviewed": ("Revisado", "#ECFDF3", "#027A48"),
    "copied_to_box": ("Copiado a Box", "#EAF6FF", "#0057B8"),
    "discarded": ("Descartado", "#F1F5F9", "#475569"),
    "duplicate": ("Duplicado", "#FEF3C7", "#92400E"),
    "draft": ("Borrador", "#F8FAFC", "#475569"),
    "partial": ("Parcial", "#FFF7E6", "#B54708"),
    "error": ("Error", "#FEF3F2", "#B42318"),
    "archived": ("Archivado", "#F1F5F9", "#475569"),
}


def status_chip(
    status,
    label=None,
    status_map=None,
    compact=True,
    bordered=False,
):
    """
    Chip visual reutilizable para estados.

    No conoce servicios, Box, expedientes ni bandeja documental.
    Recibe estado + mapa visual y devuelve un control Flet.
    """
    normalized_status = str(status or "").strip()
    visual_map = status_map or DEFAULT_STATUS_MAP

    default_label = label or normalized_status or "-"
    resolved = visual_map.get(
        normalized_status,
        (default_label, "#F8FAFC", Q_MUTED),
    )

    if len(resolved) == 4:
        resolved_label, bg, fg, border_color = resolved
    else:
        resolved_label, bg, fg = resolved
        border_color = bg

    if label:
        resolved_label = label

    horizontal_padding = 8 if compact else 10
    vertical_padding = 3 if compact else 5
    text_size = 11 if compact else 12

    return ft.Container(
        content=ft.Text(
            str(resolved_label),
            size=text_size,
            weight=ft.FontWeight.BOLD,
            color=fg,
        ),
        bgcolor=bg,
        border=ft.border.all(1, border_color) if bordered else None,
        border_radius=20,
        padding=ft.padding.symmetric(
            horizontal=horizontal_padding,
            vertical=vertical_padding,
        ),
    )
