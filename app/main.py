import flet as ft
from datetime import date, datetime

from database.connection import initialize_database
from backend.services.client_service import (
    create_client,
    get_all_clients,
    update_client,
    archive_client,
)


def calcular_edad(fecha_nacimiento):
    if not fecha_nacimiento:
        return ""

    try:
        nacimiento = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
        hoy = date.today()
        edad = hoy.year - nacimiento.year - (
            (hoy.month, hoy.day) < (nacimiento.month, nacimiento.day)
        )
        return str(edad)
    except ValueError:
        return ""


def documento_cliente(cliente):
    if cliente.get("nie"):
        return cliente.get("nie")
    if cliente.get("pasaporte"):
        return cliente.get("pasaporte")
    if cliente.get("dni"):
        return cliente.get("dni")
    return ""


def nombre_completo(cliente):
    partes = [
        cliente.get("nombre") or "",
        cliente.get("primer_apellido") or "",
        cliente.get("segundo_apellido") or "",
    ]
    return " ".join([p for p in partes if p]).strip()


def main(page: ft.Page):
    initialize_database()

    page.title = "ERP Quesada Abogados"
    page.window_width = 1200
    page.window_height = 750

    editing_client_id = {"value": None}
    selected_client = {"value": None}

    client_table = ft.Column(spacing=4)

    filtro_columna = ft.Dropdown(
        label="Filtrar por",
        width=220,
        value="nombre",
        options=[
            ft.dropdown.Option("nombre", "Nombre"),
            ft.dropdown.Option("documento", "NIE / Pasaporte"),
            ft.dropdown.Option("nacionalidad", "Nacionalidad"),
            ft.dropdown.Option("telefono", "Telefono"),
            ft.dropdown.Option("estado", "Estado"),
        ],
    )

    filtro_texto = ft.TextField(
        label="Buscar",
        width=350,
        on_change=lambda e: load_clients(),
    )

    nombre = ft.TextField(label="Nombre")
    primer_apellido = ft.TextField(label="Primer apellido")
    segundo_apellido = ft.TextField(label="Segundo apellido")
    nie = ft.TextField(label="NIE")
    pasaporte = ft.TextField(label="Pasaporte")
    nacionalidad = ft.TextField(label="Nacionalidad")
    fecha_nacimiento = ft.TextField(label="Fecha nacimiento (YYYY-MM-DD)")
    telefono = ft.TextField(label="Telefono")
    email = ft.TextField(label="Email")
    estado = ft.TextField(label="Estado cliente", value="Asesoramiento inicial")
    observaciones = ft.TextField(label="Observaciones", multiline=True)

    error_text = ft.Text(color="red", visible=False)

    main_content = ft.Column(expand=True)

    def cliente_pasa_filtro(cliente):
        texto = (filtro_texto.value or "").lower().strip()

        if not texto:
            return True

        columna = filtro_columna.value

        if columna == "nombre":
            valor = nombre_completo(cliente)
        elif columna == "documento":
            valor = documento_cliente(cliente)
        elif columna == "nacionalidad":
            valor = cliente.get("nacionalidad") or ""
        elif columna == "telefono":
            valor = cliente.get("telefono") or ""
        elif columna == "estado":
            valor = cliente.get("estado_cliente") or ""
        else:
            valor = ""

        return texto in valor.lower()

    def load_clients():
        client_table.controls.clear()

        clientes = [c for c in get_all_clients() if cliente_pasa_filtro(c)]

        client_table.controls.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Text("Nombre", width=220, weight="bold"),
                        ft.Text("NIE / Pasaporte", width=150, weight="bold"),
                        ft.Text("Nacionalidad", width=140, weight="bold"),
                        ft.Text("Edad", width=60, weight="bold"),
                        ft.Text("Telefono", width=120, weight="bold"),
                        ft.Text("Estado", width=180, weight="bold"),
                        ft.Text("Acciones", width=250, weight="bold"),
                    ]
                ),
                padding=8,
                border=ft.border.all(1, "grey"),
            )
        )

        for c in clientes:
            client_table.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(nombre_completo(c), width=220),
                            ft.Text(documento_cliente(c), width=150),
                            ft.Text(c.get("nacionalidad") or "", width=140),
                            ft.Text(calcular_edad(c.get("fecha_nacimiento")), width=60),
                            ft.Text(c.get("telefono") or "", width=120),
                            ft.Text(c.get("estado_cliente") or "", width=180),
                            ft.Row(
                                [
                                    ft.Button("Ficha", on_click=lambda e, c=c: show_client_detail(c)),
                                    ft.Button("Editar", on_click=lambda e, c=c: edit_client(c)),
                                    ft.Button("Archivar", on_click=lambda e, cid=c["id"]: archivar_cliente(cid)),
                                ],
                                width=250,
                            ),
                        ]
                    ),
                    padding=8,
                    border=ft.border.all(1, "grey"),
                    border_radius=4,
                )
            )

        page.update()

    def limpiar_form():
        editing_client_id["value"] = None
        nombre.value = ""
        primer_apellido.value = ""
        segundo_apellido.value = ""
        nie.value = ""
        pasaporte.value = ""
        nacionalidad.value = ""
        fecha_nacimiento.value = ""
        telefono.value = ""
        email.value = ""
        estado.value = "Asesoramiento inicial"
        observaciones.value = ""
        error_text.visible = False

    def close_dialog(e=None):
        dialog.open = False
        page.update()

    def guardar_cliente(e):
        errores = []

        if not nombre.value:
            errores.append("El nombre es obligatorio")

        if telefono.value and not telefono.value.isdigit():
            errores.append("El telefono debe ser numerico")

        if fecha_nacimiento.value:
            try:
                datetime.strptime(fecha_nacimiento.value, "%Y-%m-%d")
            except ValueError:
                errores.append("La fecha de nacimiento debe tener formato YYYY-MM-DD")

        if errores:
            error_text.value = "\n".join(errores)
            error_text.visible = True
            page.update()
            return

        data = {
            "nombre": nombre.value,
            "primer_apellido": primer_apellido.value,
            "segundo_apellido": segundo_apellido.value,
            "nie": nie.value,
            "pasaporte": pasaporte.value,
            "nacionalidad": nacionalidad.value,
            "fecha_nacimiento": fecha_nacimiento.value,
            "telefono": telefono.value,
            "email": email.value,
            "estado_cliente": estado.value,
            "observaciones": observaciones.value,
        }

        if editing_client_id["value"]:
            update_client(editing_client_id["value"], data)
        else:
            create_client(data)

        limpiar_form()
        close_dialog()
        show_client_list()

    def open_new_client(e):
        limpiar_form()
        dialog.title = ft.Text("Nuevo cliente")
        dialog.open = True
        page.update()

    def edit_client(cliente):
        editing_client_id["value"] = cliente["id"]

        nombre.value = cliente.get("nombre") or ""
        primer_apellido.value = cliente.get("primer_apellido") or ""
        segundo_apellido.value = cliente.get("segundo_apellido") or ""
        nie.value = cliente.get("nie") or ""
        pasaporte.value = cliente.get("pasaporte") or ""
        nacionalidad.value = cliente.get("nacionalidad") or ""
        fecha_nacimiento.value = cliente.get("fecha_nacimiento") or ""
        telefono.value = cliente.get("telefono") or ""
        email.value = cliente.get("email") or ""
        estado.value = cliente.get("estado_cliente") or "Asesoramiento inicial"
        observaciones.value = cliente.get("observaciones") or ""

        error_text.visible = False
        dialog.title = ft.Text("Editar cliente")
        dialog.open = True
        page.update()

    def archivar_cliente(client_id):
        archive_client(client_id)
        show_client_list()

    def show_client_list():
        main_content.controls.clear()

        main_content.controls.append(
            ft.Column(
                [
                    ft.Text("CLIENTES", size=26, weight="bold"),
                    ft.Row(
                        [
                            filtro_columna,
                            filtro_texto,
                            ft.Button("Nuevo cliente", on_click=open_new_client),
                            ft.Button("Actualizar", on_click=lambda e: load_clients()),
                        ]
                    ),
                    ft.Divider(),
                    client_table,
                ],
                expand=True,
            )
        )

        page.update()
        load_clients()

    def show_client_detail(cliente):
        selected_client["value"] = cliente

        main_content.controls.clear()

        main_content.controls.append(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Button("Volver", on_click=lambda e: show_client_list()),
                            ft.Button("Editar", on_click=lambda e, c=cliente: edit_client(c)),
                        ]
                    ),
                    ft.Text("FICHA DEL CLIENTE", size=26, weight="bold"),
                    ft.Divider(),
                    ft.Text(f"Nombre completo: {nombre_completo(cliente)}"),
                    ft.Text(f"NIE / Pasaporte: {documento_cliente(cliente)}"),
                    ft.Text(f"Nacionalidad: {cliente.get('nacionalidad') or ''}"),
                    ft.Text(f"Fecha nacimiento: {cliente.get('fecha_nacimiento') or ''}"),
                    ft.Text(f"Edad: {calcular_edad(cliente.get('fecha_nacimiento'))}"),
                    ft.Text(f"Telefono: {cliente.get('telefono') or ''}"),
                    ft.Text(f"Email: {cliente.get('email') or ''}"),
                    ft.Text(f"Estado: {cliente.get('estado_cliente') or ''}"),
                    ft.Divider(),
                    ft.Text("Observaciones", size=18, weight="bold"),
                    ft.Text(cliente.get("observaciones") or ""),
                ],
                expand=True,
            )
        )

        page.update()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Nuevo cliente"),
        content=ft.Column(
            [
                nombre,
                primer_apellido,
                segundo_apellido,
                nie,
                pasaporte,
                nacionalidad,
                fecha_nacimiento,
                telefono,
                email,
                estado,
                observaciones,
                error_text,
            ],
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            height=500,
        ),
        actions=[
            ft.Button("Guardar", on_click=guardar_cliente),
            ft.Button("Cancelar", on_click=close_dialog),
        ],
    )

    page.overlay.append(dialog)

    page.add(main_content)
    show_client_list()


ft.run(main)