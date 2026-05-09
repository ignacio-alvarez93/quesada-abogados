import flet as ft

from frontend.components.app_button import primary_button
from frontend.components.app_badge import status_badge
from frontend.components.app_card import metric_card

Q_PRIMARY_DARK = "#003B7A"
Q_PRIMARY = "#0057B8"
Q_BG = "#F5F9FF"
Q_TEXT = "#101828"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"
Q_WHITE = "#FFFFFF"

FICHA_FIELDS = [
    "nombre",
    "primer_apellido",
    "segundo_apellido",
    "nie",
    "pasaporte",
    "dni",
    "nacionalidad",
    "fecha_nacimiento",
    "telefono",
    "email",
    "estado_cliente",
    "domicilio_espana",
    "localidad",
    "provincia",
    "codigo_postal",
    "localidad_nacimiento",
    "pais_nacimiento",
    "nombre_padre",
    "nombre_madre",
    "estado_civil",
]


def _value(value):
    return value if value not in (None, "") else "-"


def _nombre_completo(client):
    return " ".join(
        [
            client.get("nombre") or "",
            client.get("primer_apellido") or "",
            client.get("segundo_apellido") or "",
        ]
    ).strip() or "Cliente sin nombre"


def _documento(client):
    return client.get("nie") or client.get("pasaporte") or client.get("dni") or ""


def _iniciales(client):
    nombre = client.get("nombre") or ""
    primer_apellido = client.get("primer_apellido") or ""
    segundo_apellido = client.get("segundo_apellido") or ""

    partes = [p for p in [nombre, primer_apellido, segundo_apellido] if p.strip()]

    if len(partes) >= 2:
        return f"{partes[0][0]}{partes[1][0]}".upper()

    nombre_completo = _nombre_completo(client)
    palabras = [p for p in nombre_completo.split(" ") if p.strip()]

    if len(palabras) >= 2:
        return f"{palabras[0][0]}{palabras[-1][0]}".upper()

    if palabras:
        return palabras[0][:2].upper()

    return "CL"


def _porcentaje_ficha(client):
    total = len(FICHA_FIELDS)
    completados = sum(1 for field in FICHA_FIELDS if client.get(field))
    return int((completados / total) * 100)


def _progress_color(percent):
    if percent >= 80:
        return "#027A48"
    if percent >= 50:
        return "#B54708"
    return "#B42318"


def _alertas(client):
    alerts = []

    if not _documento(client):
        alerts.append("Sin documento")
    if not client.get("telefono"):
        alerts.append("Sin teléfono")
    if not client.get("email"):
        alerts.append("Falta email")
    if _porcentaje_ficha(client) < 80:
        alerts.append("Ficha incompleta")
    if client.get("estado_cliente") == "Pendiente de documentación":
        alerts.append("Pendiente documentación")

    return alerts


def _info_line(label, value):
    return ft.Row(
        controls=[
            ft.Text(label, size=12, color=Q_MUTED, width=90),
            ft.Text(str(_value(value)), size=13, color=Q_TEXT, weight=ft.FontWeight.W_600, expand=True),
        ],
        spacing=8,
    )


def _avatar(client):
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(
                    _iniciales(client),
                    size=22,
                    weight=ft.FontWeight.BOLD,
                    color=Q_WHITE,
                )
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=58,
        height=58,
        bgcolor=Q_PRIMARY,
        border_radius=30,
    )


def _alert_chip(text):
    return ft.Container(
        content=ft.Text(f"⚠ {text}", size=12, color="#B54708", weight=ft.FontWeight.W_600),
        bgcolor="#FFFAEB",
        border=ft.border.all(1, "#FEDF89"),
        border_radius=18,
        padding=ft.padding.symmetric(horizontal=10, vertical=6),
    )


def _empty_panel(metrics=None):
    metrics = metrics or {}

    metric_controls = [
        metric_card("Clientes activos", metrics.get("clientes_activos", "-")),
        metric_card("Pendientes documentación", metrics.get("pendientes_documentacion", "-")),
        metric_card("Sin documento", metrics.get("sin_documento", "-")),
        metric_card("Ficha incompleta", metrics.get("ficha_incompleta", "-")),
    ]

    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text("Resumen de cliente", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text("👤", size=38),
                            ft.Text(
                                "Selecciona un cliente para ver su resumen",
                                size=14,
                                color=Q_MUTED,
                                weight=ft.FontWeight.W_600,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    height=150,
                    bgcolor=Q_WHITE,
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=14,
                ),
                ft.Row(controls=metric_controls, spacing=10, wrap=True),
            ],
            spacing=14,
        ),
        bgcolor=Q_BG,
        border=ft.border.all(1, Q_BORDER),
        border_radius=16,
        padding=16,
    )


def client_context_panel(client=None, on_view_detail=None, metrics=None):
    if not client:
        return _empty_panel(metrics)

    percent = _porcentaje_ficha(client)
    alerts = _alertas(client)

    view_button = primary_button("Ver ficha", on_view_detail or (lambda e: None))
    view_button.disabled = on_view_detail is None

    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        _avatar(client),
                        ft.Column(
                            controls=[
                                ft.Text(_nombre_completo(client), size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text(_value(client.get("nacionalidad")), size=13, color=Q_MUTED),
                            ],
                            spacing=3,
                            expand=True,
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=1, bgcolor=Q_BORDER),
                _info_line("Documento", _documento(client)),
                _info_line("Teléfono", client.get("telefono")),
                _info_line("Email", client.get("email")),
                ft.Row(
                    controls=[
                        ft.Text("Estado", size=12, color=Q_MUTED, width=90),
                        status_badge(client.get("estado_cliente") or "-"),
                    ],
                    spacing=8,
                ),
                ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("Ficha completa", size=12, color=Q_MUTED, expand=True),
                                ft.Text(f"{percent}%", size=12, color=_progress_color(percent), weight=ft.FontWeight.BOLD),
                            ],
                        ),
                        ft.ProgressBar(value=percent / 100, color=_progress_color(percent), bgcolor="#E4E7EC", height=8),
                    ],
                    spacing=6,
                ),
                ft.Column(
                    controls=[
                        ft.Text("Alertas rápidas", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        ft.Row(
                            controls=[_alert_chip(alert) for alert in alerts] or [
                                ft.Container(
                                    content=ft.Text("Sin alertas", size=12, color="#027A48", weight=ft.FontWeight.W_600),
                                    bgcolor="#ECFDF3",
                                    border_radius=18,
                                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                                )
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Row(controls=[view_button], alignment=ft.MainAxisAlignment.END),
            ],
            spacing=14,
        ),
        bgcolor=Q_WHITE,
        border=ft.border.all(1, Q_BORDER),
        border_radius=16,
        padding=18,
    )
