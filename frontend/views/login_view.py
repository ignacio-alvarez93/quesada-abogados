import flet as ft

from backend.services.auth_service import authenticate_user
from frontend.components import error_alert


Q_PRIMARY = "#1463D7"
Q_PRIMARY_DARK = "#173B7A"
Q_TEXT = "#183153"
Q_MUTED = "#6E7F99"
Q_BORDER = "#D7E1EE"
Q_BG = "#F6F9FD"
Q_SOFT = "#EEF4FB"
Q_CARD = "#FFFFFF"


def _feature_chip(icon, text):
    return ft.Container(
        width=160,
        height=48,
        padding=ft.padding.symmetric(horizontal=16, vertical=10),
        bgcolor="#FFFFFF",
        border_radius=16,
        border=ft.border.all(1, "#E6EDF6"),
        shadow=ft.BoxShadow(
            blur_radius=10,
            spread_radius=0,
            color="#0F274D0D",
            offset=ft.Offset(0, 3),
        ),
        content=ft.Row(
            controls=[
                ft.Icon(icon, size=22, color=Q_PRIMARY),
                ft.Text(
                    text,
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color=Q_PRIMARY_DARK,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def _metric_chip(icon, value, label):
    return ft.Container(
        width=190,
        height=66,
        padding=ft.padding.symmetric(horizontal=18, vertical=12),
        bgcolor="#FFFFFF",
        border_radius=18,
        border=ft.border.all(1, "#E6EDF6"),
        shadow=ft.BoxShadow(
            blur_radius=10,
            spread_radius=0,
            color="#0F274D0D",
            offset=ft.Offset(0, 3),
        ),
        content=ft.Row(
            controls=[
                ft.Container(
                    width=40,
                    height=40,
                    border_radius=20,
                    bgcolor="#F0F5FD",
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(icon, size=22, color=Q_PRIMARY),
                ),
                ft.Column(
                    controls=[
                        ft.Text(
                            value,
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY,
                        ),
                        ft.Text(
                            label,
                            size=11,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=1,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def _field_label(text):
    return ft.Text(
        text,
        size=14,
        weight=ft.FontWeight.W_700,
        color=Q_PRIMARY_DARK,
    )


def _login_input(
    hint,
    *,
    prefix_icon,
    password=False,
    on_submit=None,
):
    field = ft.TextField(
        hint_text=hint,
        width=488,
        height=60,
        border_radius=14,
        border_color=Q_BORDER,
        focused_border_color=Q_PRIMARY,
        cursor_color=Q_PRIMARY,
        bgcolor="#FFFFFF",
        content_padding=ft.padding.only(left=16, right=16, top=12, bottom=12),
        text_size=14,
        hint_style=ft.TextStyle(
            size=14,
            color="#8A9AB1",
        ),
        prefix_icon=prefix_icon,
        password=password,
        can_reveal_password=password,
        on_submit=on_submit,
    )
    return field


def _login_button(on_click):
    return ft.ElevatedButton(
        width=488,
        height=60,
        on_click=on_click,
        style=ft.ButtonStyle(
            bgcolor=Q_PRIMARY,
            color="#FFFFFF",
            elevation=2,
            shape=ft.RoundedRectangleBorder(radius=16),
            padding=ft.padding.symmetric(horizontal=24, vertical=14),
        ),
        content=ft.Row(
            controls=[
                ft.Container(expand=True),
                ft.Text(
                    "Entrar",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color="#FFFFFF",
                ),
                ft.Container(expand=True),
                ft.Icon(
                    ft.Icons.ARROW_FORWARD_ROUNDED,
                    color="#FFFFFF",
                    size=24,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def login_view(page, on_login_success):
    username = _login_input(
        "Ingresa tu usuario",
        prefix_icon=ft.Icons.PERSON_OUTLINE,
    )
    password = _login_input(
        "Ingresa tu contraseña",
        prefix_icon=ft.Icons.LOCK_OUTLINE,
        password=True,
    )

    error_container = ft.Column(controls=[], visible=False)

    def login(e):
        error_container.controls.clear()
        error_container.visible = False

        user = authenticate_user(username.value, password.value)
        if user:
            on_login_success(user)
            return

        error_container.controls.append(
            error_alert("Usuario o contraseña incorrectos")
        )
        error_container.visible = True
        page.update()

    password.on_submit = login

    left_panel = ft.Container(
        expand=11,
        padding=ft.padding.only(left=86, right=56, top=46, bottom=42),
        content=ft.Stack(
            expand=True,
            controls=[
                ft.Container(
                    expand=True,
                    border_radius=0,
                    bgcolor="#FFFFFF",
                ),
                ft.Container(
                    left=-180,
                    top=-240,
                    width=980,
                    height=980,
                    border_radius=490,
                    bgcolor="#F8FBFF",
                    border=ft.border.all(1, "#EEF4FB"),
                ),
                ft.Container(
                    left=-190,
                    bottom=-250,
                    width=470,
                    height=470,
                    border_radius=240,
                    gradient=ft.LinearGradient(
                        begin=ft.Alignment(1, -1),
                        end=ft.Alignment(-1, 1),
                        colors=["#2D7FF0", "#1D58C9"],
                    ),
                    opacity=0.95,
                ),
                ft.Container(
                    left=0,
                    top=0,
                    bottom=0,
                    width=160,
                    gradient=ft.LinearGradient(
                        begin=ft.Alignment(0, -1),
                        end=ft.Alignment(0, 1),
                        colors=["#F3F7FC", "#EDF3FA"],
                    ),
                    opacity=0.95,
                ),
                ft.Container(
                    left=64,
                    top=26,
                    width=720,
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Image(
                                        src="captura.png",
                                        width=84,
                                        height=84,
                                        fit=ft.BoxFit.CONTAIN,
                                    ),
                                    ft.Column(
                                        controls=[
                                            ft.Text(
                                                "Quesada Abogados",
                                                size=28,
                                                weight=ft.FontWeight.BOLD,
                                                color=Q_PRIMARY_DARK,
                                            ),
                                            ft.Text(
                                                "ERP interno del despacho",
                                                size=15,
                                                color=Q_MUTED,
                                            ),
                                        ],
                                        spacing=3,
                                    ),
                                ],
                                spacing=18,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Container(height=38),
                            ft.Container(
                                width=720,
                                content=ft.Column(
                                    controls=[
                                        ft.Image(
                                            src="captura.png",
                                            width=170,
                                            height=170,
                                            fit=ft.BoxFit.CONTAIN,
                                        ),
                                        ft.Text(
                                            "Quesada Abogados",
                                            size=56,
                                            weight=ft.FontWeight.BOLD,
                                            color=Q_PRIMARY_DARK,
                                            text_align=ft.TextAlign.CENTER,
                                        ),
                                        ft.Text(
                                            "ERP interno del despacho",
                                            size=25,
                                            color=Q_PRIMARY,
                                            text_align=ft.TextAlign.CENTER,
                                        ),
                                        ft.Row(
                                            controls=[
                                                ft.Container(
                                                    width=110,
                                                    height=2,
                                                    bgcolor="#C6D7EE",
                                                    border_radius=4,
                                                ),
                                                ft.Container(
                                                    width=12,
                                                    height=12,
                                                    border_radius=6,
                                                    bgcolor=Q_PRIMARY,
                                                ),
                                                ft.Container(
                                                    width=110,
                                                    height=2,
                                                    bgcolor="#C6D7EE",
                                                    border_radius=4,
                                                ),
                                            ],
                                            alignment=ft.MainAxisAlignment.CENTER,
                                            spacing=14,
                                        ),
                                        ft.Text(
                                            "Plataforma integral para la gestión legal y de inmigración.",
                                            size=16,
                                            color=Q_PRIMARY_DARK,
                                            text_align=ft.TextAlign.CENTER,
                                        ),
                                        ft.Text(
                                            "Centraliza clientes, expedientes, documentación y automatizaciones",
                                            size=16,
                                            color=Q_PRIMARY_DARK,
                                            text_align=ft.TextAlign.CENTER,
                                        ),
                                        ft.Text(
                                            "para impulsar la eficiencia y la excelencia jurídica.",
                                            size=16,
                                            color=Q_PRIMARY_DARK,
                                            text_align=ft.TextAlign.CENTER,
                                        ),
                                    ],
                                    spacing=8,
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ),
                            ft.Container(height=26),
                            ft.Row(
                                controls=[
                                    _feature_chip(ft.Icons.PEOPLE_OUTLINE, "Clientes"),
                                    _feature_chip(ft.Icons.FOLDER_OUTLINED, "Expedientes"),
                                    _feature_chip(ft.Icons.AUTO_AWESOME_OUTLINED, "Automatizaciones"),
                                    _feature_chip(ft.Icons.DESCRIPTION_OUTLINED, "Documentación"),
                                ],
                                spacing=14,
                                wrap=True,
                                alignment=ft.MainAxisAlignment.CENTER,
                            ),
                            ft.Container(height=20),
                            ft.Row(
                                controls=[
                                    _metric_chip(ft.Icons.SHIELD_OUTLINED, "100%", "Entorno seguro"),
                                    _metric_chip(ft.Icons.ACCESS_TIME_OUTLINED, "24/7", "Disponibilidad"),
                                    _metric_chip(ft.Icons.LOCK_OUTLINE, "Acceso", "Controlado"),
                                ],
                                spacing=16,
                                wrap=True,
                                alignment=ft.MainAxisAlignment.CENTER,
                            ),
                            ft.Container(height=36),
                            ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons.VERIFIED_USER_OUTLINED,
                                        size=22,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(
                                        "Protegemos tu información con los más altos estándares de seguridad.",
                                        size=16,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                ],
                                spacing=12,
                                alignment=ft.MainAxisAlignment.CENTER,
                            ),
                            ft.Container(height=28),
                            ft.Column(
                                controls=[
                                    ft.Row(
                                        controls=[
                                            ft.Icon(
                                                ft.Icons.SECURITY_OUTLINED,
                                                size=16,
                                                color=Q_MUTED,
                                            ),
                                            ft.Text(
                                                "Sistema privado de uso interno · Quesada Abogados",
                                                size=12,
                                                color=Q_MUTED,
                                            ),
                                        ],
                                        spacing=8,
                                        alignment=ft.MainAxisAlignment.CENTER,
                                    ),
                                    ft.Row(
                                        controls=[
                                            ft.Icon(
                                                ft.Icons.CODE,
                                                size=15,
                                                color=Q_PRIMARY,
                                            ),
                                            ft.Text(
                                                "Desarrollado por Ignacio Alvarez Cañal",
                                                size=12,
                                                color=Q_MUTED,
                                            ),
                                        ],
                                        spacing=8,
                                        alignment=ft.MainAxisAlignment.CENTER,
                                    ),
                                ],
                                spacing=7,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=0,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
            ],
        ),
    )

    login_card = ft.Container(
        width=560,
        padding=ft.padding.only(left=38, right=38, top=34, bottom=34),
        bgcolor=Q_CARD,
        border_radius=28,
        border=ft.border.all(1, "#E6EDF6"),
        shadow=ft.BoxShadow(
            blur_radius=28,
            spread_radius=0,
            color="#14346318",
            offset=ft.Offset(0, 10),
        ),
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(
                            width=94,
                            height=94,
                            border_radius=47,
                            bgcolor="#EEF4FD",
                            alignment=ft.Alignment.CENTER,
                            content=ft.Icon(
                                ft.Icons.ADMIN_PANEL_SETTINGS_OUTLINED,
                                size=42,
                                color=Q_PRIMARY,
                            ),
                        ),
                        ft.Container(expand=True),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "Iniciar sesión",
                                    size=36,
                                    weight=ft.FontWeight.BOLD,
                                    color=Q_PRIMARY_DARK,
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                                ft.Text(
                                    "Accede a tu entorno privado",
                                    size=18,
                                    color=Q_PRIMARY_DARK,
                                    text_align=ft.TextAlign.RIGHT,
                                ),
                            ],
                            spacing=5,
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=24),
                _field_label("Usuario"),
                username,
                ft.Container(height=8),
                _field_label("Contraseña"),
                password,
                ft.Container(height=18),
                _login_button(login),
                error_container,
                ft.Container(height=22),
                ft.Row(
                    controls=[
                        ft.Container(
                            expand=True,
                            height=2,
                            bgcolor="#DCE6F2",
                            border_radius=4,
                        ),
                        ft.Row(
                            controls=[
                                ft.Icon(
                                    ft.Icons.SHIELD_OUTLINED,
                                    size=22,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    "Acceso seguro",
                                    size=16,
                                    color=Q_PRIMARY_DARK,
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Container(
                            expand=True,
                            height=2,
                            bgcolor="#DCE6F2",
                            border_radius=4,
                        ),
                    ],
                    spacing=18,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=0,
        ),
    )

    right_panel = ft.Container(
        expand=8,
        padding=ft.padding.only(left=36, right=72, top=78, bottom=78),
        content=ft.Stack(
            expand=True,
            controls=[
                ft.Container(
                    expand=True,
                    bgcolor="#FFFFFF",
                ),
                ft.Container(
                    right=-40,
                    bottom=-24,
                    width=170,
                    height=170,
                    border_radius=85,
                    border=ft.border.all(3, "#D7E6F8"),
                    opacity=0.9,
                ),
                ft.Container(
                    right=36,
                    bottom=62,
                    width=120,
                    height=120,
                    border_radius=20,
                    border=ft.border.all(2, "#E2ECF8"),
                    opacity=0.85,
                ),
                ft.Container(
                    alignment=ft.Alignment.CENTER,
                    content=login_card,
                ),
            ],
        ),
    )

    return ft.Container(
        expand=True,
        bgcolor=Q_BG,
        content=ft.Row(
            controls=[
                left_panel,
                right_panel,
            ],
            spacing=0,
            expand=True,
        ),
    )
