import flet as ft

Q_PRIMARY_DARK = "#003B7A"
Q_PRIMARY = "#0057B8"
Q_BG = "#F5F9FF"
Q_BORDER = "#E4E7EC"
Q_MUTED = "#64748B"


SETTINGS_SECTIONS = [
    ("tipos", "Tipos expediente"),
    ("documentos", "Documentos requeridos"),
    ("estados", "Estados expediente"),
    ("prioridades", "Prioridades"),
    ("box", "Rutas Box"),
    ("nomenclaturas", "Nomenclaturas"),
    ("tablas", "Tablas CRM"),
]


def settings_sidebar(selected_key, on_select):
    controls = [
        ft.Text("CONFIGURACIÓN", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
        ft.Text("Parametrización operativa", size=12, color=Q_MUTED),
    ]

    for key, label in SETTINGS_SECTIONS:
        selected = key == selected_key
        controls.append(
            ft.Container(
                content=ft.Text(
                    label,
                    size=13,
                    color="#FFFFFF" if selected else Q_PRIMARY_DARK,
                    weight=ft.FontWeight.W_600 if selected else ft.FontWeight.NORMAL,
                ),
                bgcolor=Q_PRIMARY if selected else "#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=10,
                padding=ft.padding.symmetric(horizontal=12, vertical=10),
                ink=True,
                on_click=lambda e, k=key: on_select(k),
            )
        )

    return ft.Container(
        width=250,
        bgcolor=Q_BG,
        border=ft.border.all(1, Q_BORDER),
        border_radius=16,
        padding=16,
        content=ft.Column(controls=controls, spacing=10),
    )
