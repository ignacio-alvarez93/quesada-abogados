import flet as ft

COLORS = {
    "PENDIENTE": ("#FFFAEB", "#B54708"),
    "CONCILIADO": ("#ECFDF3", "#027A48"),
    "DUDOSO": ("#FFF7E6", "#B54708"),
    "NO IDENTIFICADO": ("#FEF3F2", "#B42318"),
    "ERROR": ("#FEF3F2", "#B42318"),
    "DISPONIBLE": ("#EAF3FF", "#0057B8"),
    "APLICADA": ("#ECFDF3", "#027A48"),
    "PENDIENTE FIRMA": ("#FFFAEB", "#B54708"),
    "FIRMADA": ("#ECFDF3", "#027A48"),
    "CANCELADA": ("#FEF3F2", "#B42318"),
}


def traceability_badge(text):
    text = text or "-"
    bg, fg = COLORS.get(text, ("#EAF3FF", "#0057B8"))
    return ft.Container(
        content=ft.Text(text, size=12, color=fg, weight=ft.FontWeight.BOLD),
        bgcolor=bg,
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
    )
