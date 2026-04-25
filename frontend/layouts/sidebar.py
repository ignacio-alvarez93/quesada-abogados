import flet as ft

Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_ACCENT = "#18BFEA"
Q_WHITE = "#FFFFFF"
Q_MUTED = "#C7D2FE"

_MENU_ITEMS = [
    ("Clientes", ft.Icons.PEOPLE_ALT_OUTLINED),
    ("Expedientes", ft.Icons.FOLDER_COPY_OUTLINED),
    ("Cobros", ft.Icons.EURO_OUTLINED),
    ("Documentos / Box", ft.Icons.CLOUD_QUEUE_OUTLINED),
    ("Fiscal", ft.Icons.ACCOUNT_BALANCE_OUTLINED),
    ("Legacy", ft.Icons.HISTORY_OUTLINED),
]


def sidebar_menu(on_navigate):
    def item(title, icon):
        return ft.Container(
            content=ft.Row(
                controls=[ft.Icon(icon, color=Q_WHITE, size=20), ft.Text(title, color=Q_WHITE, size=14)],
                spacing=12,
            ),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            ink=True,
            on_click=lambda e, view=title: on_navigate(view),
        )

    return ft.Container(
        width=250,
        bgcolor=Q_PRIMARY_DARK,
        padding=20,
        content=ft.Column(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("Quesada", color=Q_WHITE, size=22, weight=ft.FontWeight.BOLD),
                        ft.Text("Abogados ERP", color=Q_MUTED, size=12),
                    ],
                    spacing=0,
                ),
                ft.Divider(color=Q_ACCENT, height=28),
                *[item(title, icon) for title, icon in _MENU_ITEMS],
            ],
            spacing=8,
        ),
    )
