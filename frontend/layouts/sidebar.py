import flet as ft

Q_PRIMARY = "#003B7A"
Q_PRIMARY_2 = "#0057B8"
Q_ACCENT = "#18BFEA"
Q_WHITE = "#FFFFFF"
Q_MUTED = "#BFD7FF"
Q_ITEM_BG = "#0B4A92"
Q_ITEM_HOVER = "#1261B8"


MENU_ITEMS = [
    ("Clientes", "👥"),
    ("Expedientes", "📁"),
    ("Trazabilidad Expedientes", "🧾"),
    ("Cobros", "💶"),
    ("Documentos / Box", "☁️"),
    ("Fiscal", "⚖️"),
    ("Legacy", "🕘"),
    ("Configuración", "⚙️"),
]


def sidebar_menu(on_navigate):
    def menu_item(title, icon):
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Text(icon, size=18),
                    ft.Text(
                        title,
                        color=Q_WHITE,
                        size=14,
                        weight=ft.FontWeight.W_500,
                    ),
                ],
                spacing=12,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            border_radius=12,
            bgcolor=Q_ITEM_BG,
            ink=True,
            on_click=lambda e, view=title: on_navigate(view),
        )

    return ft.Container(
        width=260,
        bgcolor=Q_PRIMARY,
        padding=ft.padding.only(left=18, right=18, top=22, bottom=18),
        content=ft.Column(
            controls=[
                ft.Column(
                    controls=[
                        ft.Image(
                            src="Captura.PNG",
                            width=130,
                        ),
                        ft.Text(
                            "Quesada Abogados",
                            color=Q_WHITE,
                            size=18,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            "ERP interno",
                            color=Q_MUTED,
                            size=12,
                        ),
                    ],
                    spacing=8,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),

                ft.Divider(color=Q_ACCENT, height=26),

                ft.Column(
                    controls=[
                        menu_item(title, icon)
                        for title, icon in MENU_ITEMS
                    ],
                    spacing=10,
                ),

                ft.Container(expand=True),

                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Quesada ERP",
                                color=Q_WHITE,
                                size=12,
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text(
                                "v0.1 · Desarrollo interno",
                                color=Q_MUTED,
                                size=11,
                            ),
                        ],
                        spacing=2,
                    ),
                    padding=12,
                    border_radius=12,
                    bgcolor="#002B5C",
                ),
            ],
            spacing=0,
            expand=True,
        ),
    )
