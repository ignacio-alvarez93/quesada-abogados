import flet as ft

_STATUS_COLORS = {
    "Asesoramiento inicial": ("#EAF6FF", "#0057B8"),
    "Pendiente de documentación": ("#FFF7E6", "#B54708"),
    "Documentación entregada": ("#ECFDF3", "#027A48"),
    "Expediente abierto": ("#EEF4FF", "#3538CD"),
    "En tramitación": ("#E0F2FE", "#026AA2"),
    "Presentado": ("#F0F9FF", "#0369A1"),
    "Pendiente de resolución": ("#FEF3C7", "#92400E"),
    "Finalizado": ("#ECFDF3", "#027A48"),
    "Archivado": ("#F1F5F9", "#475569"),
}


def status_badge(text):
    bg, fg = _STATUS_COLORS.get(text, ("#EAF6FF", "#0057B8"))
    return ft.Container(
        content=ft.Text(text, size=12, weight=ft.FontWeight.BOLD, color=fg),
        bgcolor=bg,
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
    )
