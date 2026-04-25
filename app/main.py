import flet as ft
from datetime import date, datetime

from database.connection import initialize_database
from backend.services.client_service import (
    create_client,
    get_all_clients,
    update_client,
    archive_client,
)
from backend.services.client_csv_service import (
    preview_clients_from_csv,
    import_clients_from_csv,
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
    return cliente.get("nie") or cliente.get("pasaporte") or cliente.get("dni") or ""


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
    csv_file_path = {"value": None}
    csv_preview_data = {"value": []}

    main_content = ft.Column(expand=True)
    client_table = ft.Column(spacing=4)

    # -------------------------
    # FILTROS (CORREGIDO)
    # -------------------------
    filtro_columna = ft.Dropdown(
        label="Filtrar por",
        width=200,
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
        width=280,
    )

    # ASIGNACIÓN CORRECTA DE EVENTOS
    filtro_columna.on_change = lambda e: load_clients()
    filtro_texto.on_change = lambda e: load_clients()

    # -------------------------
    # CSV INPUT
    # -------------------------
    csv_path_input = ft.TextField(
        label="Ruta CSV HubSpot",
        width=360,
        value="hubspot-crm-exports-clientes-2026-04-25-2.csv",
    )

    # -------------------------
    # FORMULARIO
    # -------------------------
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

    # -------------------------
    # FILTRO
    # -------------------------
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

    # -------------------------
    # TABLA CLIENTES
    # -------------------------
    def load_clients():
        client_table.controls.clear()

        clientes = [c for c in get_all_clients() if cliente_pasa_filtro(c)]

        for c in clientes:
            client_table.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(nombre_completo(c), width=200),
                        ft.Text(documento_cliente(c), width=150),
                        ft.Text(c.get("nacionalidad") or "", width=130),
                        ft.Text(calcular_edad(c.get("fecha_nacimiento")), width=50),
                        ft.Text(c.get("telefono") or "", width=120),
                        ft.Text(c.get("estado_cliente") or "", width=170),
                        ft.Row([
                            ft.Button("Ficha", on_click=lambda e, c=c: show_client_detail(c)),
                            ft.Button("Editar", on_click=lambda e, c=c: edit_client(c)),
                            ft.Button("Archivar", on_click=lambda e, cid=c["id"]: archivar_cliente(cid)),
                        ])
                    ]),
                    padding=8,
                    border=ft.Border.all(1, "grey"),
                )
            )

        page.update()

    # -------------------------
    # CSV
    # -------------------------
    def open_csv_preview(e):
        csv_file_path["value"] = csv_path_input.value
        preview = preview_clients_from_csv(csv_file_path["value"])
        csv_preview_data["value"] = preview
        show_csv_preview()

    def show_csv_preview():
        main_content.controls.clear()

        table = ft.Column(scroll=ft.ScrollMode.AUTO)

        for item in csv_preview_data["value"]:
            c = item["client"]
            table.controls.append(
                ft.Row([
                    ft.Text(str(item["row_number"]), width=50),
                    ft.Text(nombre_completo(c), width=200),
                    ft.Text(documento_cliente(c), width=150),
                    ft.Text("OK" if item["valid"] else "ERROR", width=80),
                ])
            )

        main_content.controls.append(
            ft.Column([
                ft.Text("PREVISUALIZACION CSV", size=24, weight="bold"),
                ft.Row([
                    ft.Button("Importar", on_click=lambda e: confirm_import()),
                    ft.Button("Cancelar", on_click=lambda e: show_client_list()),
                ]),
                table
            ])
        )

        page.update()

    def confirm_import():
        result = import_clients_from_csv(csv_file_path["value"])

        main_content.controls.clear()
        main_content.controls.append(
            ft.Column([
                ft.Text("IMPORTACION COMPLETADA"),
                ft.Text(f"Importados: {result['imported']}"),
                ft.Text(f"Omitidos: {result['skipped']}"),
                ft.Button("Volver", on_click=lambda e: show_client_list())
            ])
        )
        page.update()

    # -------------------------
    # VISTAS
    # -------------------------
    def show_client_list():
        main_content.controls.clear()

        main_content.controls.append(
            ft.Column([
                ft.Text("CLIENTES", size=26, weight="bold"),
                ft.Row([
                    filtro_columna,
                    filtro_texto,
                    ft.Button("Actualizar", on_click=lambda e: load_clients()),
                ]),
                ft.Row([
                    csv_path_input,
                    ft.Button("Importar CSV", on_click=open_csv_preview),
                ]),
                client_table
            ])
        )

        page.update()
        load_clients()

    def show_client_detail(cliente):
        main_content.controls.clear()
        main_content.controls.append(
            ft.Column([
                ft.Button("Volver", on_click=lambda e: show_client_list()),
                ft.Text(nombre_completo(cliente)),
            ])
        )
        page.update()

    page.add(main_content)
    show_client_list()


ft.run(main)