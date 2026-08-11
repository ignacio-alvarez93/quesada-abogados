import flet as ft

Q_PRIMARY = "#003B7A"
Q_PRIMARY_DARK = "#002B5C"
Q_PRIMARY_2 = "#0057B8"
Q_ACCENT = "#18BFEA"
Q_WHITE = "#FFFFFF"
Q_MUTED = "#BFD7FF"
Q_TEXT_SOFT = "#EAF3FF"
Q_ITEM_BG = "#0B4A92"
Q_ITEM_BG_ACTIVE = "#1261B8"
Q_GROUP_BG = "#073E7D"
Q_GROUP_BG_OPEN = "#0A4D98"
Q_GROUP_BORDER = "#1C6BC6"
Q_FOOTER_BG = "#002B5C"
Q_DISABLED = "#9DBBE4"


MENU_GROUPS = [
    {
        "title": "Contactos",
        "icon": "🗂️",
        "open": True,
        "items": [
            ("Clientes", "👥"),
            ("Empresas", "🏢"),
            ("Proveedores", "🚚"),
            ("Trabajadores", "🧑‍💼"),
        ],
    },
    {
        "title": "Expedientes",
        "icon": "📁",
        "open": True,
        "items": [
            ("Expedientes", "📁"),
            ("Calendario", "📅"),
            ("Colas de presentación", "⏳"),
            ("Notificaciones", "🔔"),
        ],
    },
    {
        "title": "Económico",
        "icon": "💶",
        "open": False,
        "items": [
            ("Cobros", "💶"),
            ("Conciliación", "🧾"),
        ],
    },
    {
        "title": "Contabilidad",
        "icon": "📒",
        "open": False,
        "items": [
            ("Pérdidas y ganancias", "📈"),
        ],
    },
    {
        "title": "Fiscal",
        "icon": "🧮",
        "open": False,
        "items": [
            ("Fiscal", "🧮"),
        ],
    },
    {
        "title": "Nóminas",
        "icon": "🧾",
        "open": False,
        "items": [
            ("Nóminas", "🧾"),
        ],
    },
    {
        "title": "Documentos / Box",
        "icon": "☁️",
        "open": False,
        "items": [
            ("Documentos / Box", "☁️"),
            ("Bandeja documental", "📥"),
        ],
    },
    {
        "title": "Reporting",
        "icon": "📊",
        "open": False,
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
        "icon": "📣",
        "open": False,
        "items": [
            ("Redes sociales", "📣"),
            ("Campañas", "🎯"),
            ("Competidores", "🕵️"),
            ("Comunidad Telegram", "💬"),
        ],
    },
    {
        "title": "Comunicaciones",
        "icon": "✉️",
        "open": False,
        "items": [
            ("Email", "✉️"),
            ("WhatsApp", "🟢"),
            ("Google Contacts", "📇"),
            ("Llamadas", "📞"),
        ],
    },
    {
        "title": "Conocimiento",
        "icon": "🧠",
        "open": False,
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
        "icon": "🤖",
        "open": False,
        "items": [
            ("Mercurio / Selenium", "🤖"),
            ("Búsquedas internet", "🌐"),
            ("NotebookLM", "📓"),
            ("OCR documental", "🔎"),
        ],
    },
    {
        "title": "Sistema",
        "icon": "⚙️",
        "open": False,
        "items": [
            ("Configuración", "⚙️"),
            ("Legacy", "🕘"),
        ],
    },
]


KNOWN_ACTIVE_VIEWS = {
    "Clientes",
    "Empresas",
    "Proveedores",
    "Trabajadores",
    "Expedientes",
    "Calendario",
    "Colas de presentación",
    "Notificaciones",
    "WhatsApp",
    "Cobros",
    "Conciliación",
    "Pérdidas y ganancias",
    "Fiscal",
    "Nóminas",
    "Documentos / Box",
    "Bandeja documental",
    "Reporting",
    "Configuración",
}


def sidebar_menu(on_navigate):
    state = {
        "expanded": {group["title"] for group in MENU_GROUPS if group.get("open")},
        "selected": "Clientes",
    }
    menu_column = ft.Column(controls=[], spacing=8, scroll=ft.ScrollMode.AUTO)

    def safe_update(control=None):
        try:
            if control is not None:
                control.update()
            else:
                menu_column.update()
        except Exception:
            pass

    def item_is_active(title):
        return title in KNOWN_ACTIVE_VIEWS

    def build_item(title, icon):
        active = item_is_active(title)
        selected = state.get("selected") == title
        text_color = Q_WHITE if active else Q_DISABLED
        bg = Q_ITEM_BG_ACTIVE if selected else (Q_ITEM_BG if active else "#07386F")

        def handle_click(e=None, view=title):
            state["selected"] = view
            if active:
                on_navigate(view)
            else:
                on_navigate(view)

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=26,
                        height=26,
                        bgcolor="#0E5CAD" if active else "#063061",
                        border_radius=8,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Text(icon, size=13),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                title,
                                color=text_color,
                                size=13,
                                weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                "Activo" if active else "Próximamente",
                                color=Q_MUTED if active else Q_DISABLED,
                                size=10,
                            ),
                        ],
                        spacing=0,
                        expand=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(left=10, right=10, top=8, bottom=8),
            margin=ft.margin.only(left=8, right=2),
            border_radius=12,
            bgcolor=bg,
            ink=True,
            on_click=handle_click,
        )

    def build_group(group):
        title = group["title"]
        is_open = title in state["expanded"]
        item_count = len(group.get("items") or [])
        body = ft.Column(controls=[], spacing=6, visible=is_open)

        def toggle(e=None):
            if title in state["expanded"]:
                state["expanded"].remove(title)
            else:
                state["expanded"].add(title)
            render_menu()
            safe_update(menu_column)

        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=30,
                        height=30,
                        bgcolor="#0D5AA8" if is_open else "#07386F",
                        border_radius=10,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Text(group.get("icon") or "•", size=15),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                title,
                                color=Q_WHITE,
                                size=13,
                                weight=ft.FontWeight.BOLD,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                f"{item_count} apartados",
                                color=Q_MUTED,
                                size=10,
                            ),
                        ],
                        spacing=0,
                        expand=True,
                    ),
                    ft.Text("▾" if is_open else "▸", color=Q_TEXT_SOFT, size=16),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=10),
            border_radius=14,
            bgcolor=Q_GROUP_BG_OPEN if is_open else Q_GROUP_BG,
            border=ft.border.all(1, Q_GROUP_BORDER if is_open else "#0A4A8E"),
            ink=True,
            on_click=toggle,
        )

        for item_title, item_icon in group.get("items") or []:
            body.controls.append(build_item(item_title, item_icon))

        return ft.Column(controls=[header, body], spacing=6)

    def render_menu():
        menu_column.controls.clear()
        for group in MENU_GROUPS:
            menu_column.controls.append(build_group(group))

    render_menu()

    brand = ft.Container(
        padding=ft.padding.only(bottom=12),
        content=ft.Column(
            controls=[
                ft.Container(
                    alignment=ft.Alignment(0, 0),
                    content=ft.Image(src="Captura.PNG", width=122),
                ),
                ft.Text(
                    "Quesada Abogados",
                    color=Q_WHITE,
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(
                    bgcolor="#0A4D98",
                    border_radius=20,
                    padding=ft.padding.symmetric(horizontal=12, vertical=5),
                    content=ft.Text("ERP interno · escritorio", color=Q_TEXT_SOFT, size=11),
                ),
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    footer = ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("●", color=Q_ACCENT, size=12),
                        ft.Text("Sistema operativo", color=Q_WHITE, size=12, weight=ft.FontWeight.BOLD),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Text("v0.1 · Desarrollo interno", color=Q_MUTED, size=11),
            ],
            spacing=3,
        ),
        padding=12,
        border_radius=14,
        bgcolor=Q_FOOTER_BG,
        border=ft.border.all(1, "#074681"),
    )

    return ft.Container(
        width=310,
        bgcolor=Q_PRIMARY,
        padding=ft.padding.only(left=16, right=16, top=18, bottom=16),
        content=ft.Column(
            controls=[
                brand,
                ft.Divider(color=Q_ACCENT, height=12),
                ft.Container(expand=True, content=menu_column),
                footer,
            ],
            spacing=12,
            expand=True,
        ),
    )
