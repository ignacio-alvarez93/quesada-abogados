import flet as ft

Q_PRIMARY = "#003B7A"
Q_PRIMARY_2 = "#0057B8"
Q_ACCENT = "#18BFEA"
Q_WHITE = "#FFFFFF"
Q_MUTED = "#BFD7FF"
Q_ITEM_BG = "#0B4A92"
Q_ITEM_HOVER = "#1261B8"
Q_GROUP_LABEL = "#8FBDF5"
Q_FOOTER_BG = "#002B5C"


MENU_GROUPS = [
    {
        "title": "Contactos",
        "items": [
            ("Clientes", "👥"),
            ("Empresas", "🏢"),
            ("Proveedores", "🚚"),
        ],
    },
    {
        "title": "Expedientes",
        "items": [
            ("Expedientes", "📁"),
            ("Colas de presentación", "⏳"),
            ("Notificaciones", "🔔"),
        ],
    },
    {
        "title": "Económico",
        "items": [
            ("Cobros", "💶"),
            ("Ingresos", "📈"),
            ("Gastos", "📉"),
            ("Conciliación", "🧾"),
        ],
    },
    {
        "title": "Documentos / Box",
        "items": [
            ("Documentos / Box", "☁️"),
            ("Bandeja documental", "📥"),
        ],
    },
    {
        "title": "Reporting",
        "items": [
            ("Reporting", "📊"),
            ("Reporting contactos", "👥"),
            ("Reporting expedientes", "📁"),
            ("Reporting económico", "💶"),
            ("Reporting Box", "☁️"),
        ],
    },
    {
        "title": "Marketing",
        "items": [
            ("Redes sociales", "📣"),
            ("Campañas", "🎯"),
            ("Competidores", "🕵️"),
            ("Comunidad Telegram", "💬"),
        ],
    },
    {
        "title": "Comunicaciones",
        "items": [
            ("Email", "✉️"),
            ("WhatsApp", "🟢"),
            ("Google Contacts", "📇"),
            ("Llamadas", "📞"),
        ],
    },
    {
        "title": "Conocimiento",
        "items": [
            ("BOE", "🏛️"),
            ("Resoluciones", "⚖️"),
            ("Requerimientos", "📌"),
            ("Jurisprudencia", "📚"),
            ("Base interna", "🧠"),
        ],
    },
    {
        "title": "Automatización",
        "items": [
            ("Mercurio / Selenium", "🤖"),
            ("Búsquedas internet", "🌐"),
            ("NotebookLM", "📓"),
            ("OCR documental", "🔎"),
            ("Tareas programadas", "⏱️"),
        ],
    },
    {
        "title": "Sistema",
        "items": [
            ("Configuración", "⚙️"),
            ("Legacy", "🕘"),
        ],
    },
]


def sidebar_menu(on_navigate):
    def group_label(title):
        return ft.Container(
            padding=ft.padding.only(left=4, top=10, bottom=2),
            content=ft.Text(
                title.upper(),
                color=Q_GROUP_LABEL,
                size=11,
                weight=ft.FontWeight.BOLD,
            ),
        )

    def menu_item(title, icon):
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Text(icon, size=16),
                    ft.Text(
                        title,
                        color=Q_WHITE,
                        size=13,
                        weight=ft.FontWeight.W_500,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=9),
            border_radius=10,
            bgcolor=Q_ITEM_BG,
            ink=True,
            on_click=lambda e, view=title: on_navigate(view),
        )

    menu_controls = []
    for group in MENU_GROUPS:
        menu_controls.append(group_label(group["title"]))
        for title, icon in group["items"]:
            menu_controls.append(menu_item(title, icon))

    return ft.Container(
        width=282,
        bgcolor=Q_PRIMARY,
        padding=ft.padding.only(left=16, right=16, top=20, bottom=16),
        content=ft.Column(
            controls=[
                ft.Column(
                    controls=[
                        ft.Image(
                            src="Captura.PNG",
                            width=128,
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

                ft.Divider(color=Q_ACCENT, height=22),

                ft.Container(
                    expand=True,
                    content=ft.Column(
                        controls=menu_controls,
                        spacing=6,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),

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
                    bgcolor=Q_FOOTER_BG,
                ),
            ],
            spacing=0,
            expand=True,
        ),
    )
