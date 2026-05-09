import flet as ft

COLORS = {
    "PENDIENTE": ("#FFFAEB", "#B54708"),
    "CONCILIADO": ("#ECFDF3", "#027A48"),
    "PARCIAL": ("#EAF3FF", "#0057B8"),
    "NO IDENTIFICADO": ("#FEF3F2", "#B42318"),
    "ERROR": ("#FEF3F2", "#B42318"),
    "BORRADOR": ("#F1F5F9", "#475569"),
    "EMITIDA": ("#EAF3FF", "#0057B8"),
    "EXPORTADA": ("#ECFDF3", "#027A48"),
    "PENDIENTE FIRMA": ("#FFFAEB", "#B54708"),
    "FIRMADA": ("#ECFDF3", "#027A48"),
}


def economic_badge(text):
    text = text or "-"
    bg, fg = COLORS.get(text, ("#EAF3FF", "#0057B8"))
    return ft.Container(
        content=ft.Text(text, size=12, weight=ft.FontWeight.BOLD, color=fg),
        bgcolor=bg,
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
    )
