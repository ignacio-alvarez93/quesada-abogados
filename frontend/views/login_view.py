import flet as ft

from backend.services.auth_service import authenticate_user
from frontend.components import primary_button, required_text_input, error_alert


def login_view(page, on_login_success):
    username = required_text_input("Usuario", width=320)
    password = required_text_input("Contraseña", width=320)
    password.password = True
    password.can_reveal_password = True

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

    return ft.Container(
        expand=True,
        content=ft.Column(
            controls=[
                ft.Container(
                    width=420,
                    padding=30,
                    bgcolor="#FFFFFF",
                    border_radius=16,
                    border=ft.Border.all(1, "#D8E2EE"),
                    content=ft.Column(
                        controls=[
                            ft.Image(
                                src="captura.png",
                                width=140,
                            ),
                            ft.Text(
                                "Quesada Abogados",
                                size=28,
                                weight=ft.FontWeight.BOLD,
                                color="#003B7A",
                            ),
                            ft.Text(
                                "Acceso al ERP interno",
                                size=14,
                                color="#64748B",
                            ),
                            username,
                            password,
                            primary_button("Entrar", login),
                            error_container,
                        ],
                        spacing=16,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )