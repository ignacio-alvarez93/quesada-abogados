import flet as ft

_ALERTS = {
    "error": ("#FEF3F2", "#B42318", ft.Icons.ERROR_OUTLINE),
    "success": ("#ECFDF3", "#027A48", ft.Icons.CHECK_CIRCLE_OUTLINE),
    "warning": ("#FFFAEB", "#B54708", ft.Icons.WARNING_AMBER_ROUNDED),
}


def _alert(message, kind):
    bg, fg, icon = _ALERTS[kind]
    return ft.Container(
        content=ft.Row(
            controls=[ft.Icon(icon, color=fg), ft.Text(message, color=fg, weight=ft.FontWeight.BOLD, expand=True)],
            spacing=10,
        ),
        bgcolor=bg,
        border_radius=12,
        padding=ft.padding.symmetric(horizontal=14, vertical=12),
    )


def error_alert(message):
    return _alert(message, "error")


def success_alert(message):
    return _alert(message, "success")


def warning_alert(message):
    return _alert(message, "warning")
