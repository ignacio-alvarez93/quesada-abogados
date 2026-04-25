import flet as ft

Q_PRIMARY_DARK = "#003B7A"


def form_dialog(title, content, actions):
    return ft.AlertDialog(
        modal=True,
        title=ft.Text(title, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
        content=content,
        actions=actions or [],
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(radius=14),
    )
