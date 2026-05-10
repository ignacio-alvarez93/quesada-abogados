import re
import sqlite3
import flet as ft
from datetime import date, datetime
from pathlib import Path

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
from backend.services.master_data_service import (
    get_nacionalidades,
    get_paises_nombres,
    get_provincias_nombres,
    get_localidades_by_provincia,
    get_tipos_via,
    get_estados_civiles,
)
from backend.services.config_service import get_columnas_tabla
from frontend.components.client_context_panel import client_context_panel
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.views.client_detail_view import client_detail_view
from frontend.components import (
    app_table,
    empty_state,
    filter_bar,
    metric_card,
    primary_button,
    secondary_button,
    danger_button,
    select_input,
    text_input,
    required_text_input,
    multiline_input,
    form_dialog,
    detail_section,
    action_row,
    error_alert,
    success_alert,
    warning_alert,
    status_badge,
)


DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"

FILTER_COLUMNS = ["Nombre", "NIE / Pasaporte", "Nacionalidad", "Telefono", "Estado"]

CLIENT_STATES = [
    "Asesoramiento inicial",
    "Pendiente de documentación",
    "Documentación entregada",
    "Expediente abierto",
    "En tramitación",
    "Archivado",
]

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

QUICK_FILTERS = [
    ("Todos", "todos"),
    ("Pendientes", "pendientes"),
    ("Sin documento", "sin_documento"),
    ("Ficha incompleta", "ficha_incompleta"),
    ("En tramitación", "en_tramitacion"),
    ("Archivados", "archivados"),
]

BULK_ACTIONS = [
    "Acciones en lote",
    "Mandar email",
    "Mandar WhatsApp",
    "Exportar CSV",
    "Exportar JSON",
]


CLIENT_TABLE_DEFAULT_COLUMNS = [
    {"campo": "nombre", "visible": 1, "orden": 1, "ancho": 360},
    {"campo": "nie_pasaporte", "visible": 1, "orden": 2, "ancho": 170},
    {"campo": "nacionalidad", "visible": 1, "orden": 3, "ancho": 160},
    {"campo": "edad", "visible": 1, "orden": 4, "ancho": 80},
    {"campo": "telefono", "visible": 1, "orden": 5, "ancho": 140},
    {"campo": "estado_cliente", "visible": 1, "orden": 6, "ancho": 210},
    {"campo": "ficha", "visible": 1, "orden": 7, "ancho": 120},
]

CLIENT_TABLE_LABELS = {
    "id": "ID",
    "nombre": "Nombre",
    "primer_apellido": "Primer apellido",
    "segundo_apellido": "Segundo apellido",
    "nombre_completo": "Nombre completo",
    "nie": "NIE",
    "pasaporte": "Pasaporte",
    "dni": "DNI",
    "nie_pasaporte": "NIE/Pasaporte",
    "documento": "Documento",
    "nacionalidad": "Nacionalidad",
    "fecha_nacimiento": "Fecha nacimiento",
    "edad": "Edad",
    "telefono": "Teléfono",
    "email": "Email",
    "estado_cliente": "Estado",
    "domicilio_espana": "Domicilio",
    "localidad": "Localidad",
    "provincia": "Provincia",
    "codigo_postal": "Código postal",
    "localidad_nacimiento": "Localidad nacimiento",
    "pais_nacimiento": "País nacimiento",
    "nombre_padre": "Nombre padre",
    "nombre_madre": "Nombre madre",
    "estado_civil": "Estado civil",
    "sexo": "Sexo",
    "observaciones": "Observaciones",
    "observaciones_internas": "Observaciones internas",
    "activo": "Activo",
    "created_at": "Creado",
    "updated_at": "Actualizado",
    "fecha_alta": "Fecha alta",
    "ficha": "Ficha",
}


def client_table_label(field):
    return CLIENT_TABLE_LABELS.get(field, field.replace("_", " ").title())


def client_table_columns():
    """
    Lee la configuración real de columnas para la tabla clientes.

    Si aún no existe configuración o hay un error, vuelve a una configuración
    segura para no romper el CRM.
    """
    try:
        configured = get_columnas_tabla("clientes")
        visible = [
            col for col in configured
            if int(col.get("visible", 1)) == 1
        ]
        if visible:
            return sorted(
                visible,
                key=lambda col: (int(col.get("orden") or 0), col.get("campo") or ""),
            )
    except Exception:
        pass

    return CLIENT_TABLE_DEFAULT_COLUMNS


def client_table_value(cliente, field):
    """
    Convierte un campo configurado en una celda visible.

    Admite campos reales de base de datos y campos calculados del CRM.
    """
    if field in ("nombre", "nombre_completo"):
        return nombre_completo(cliente)

    if field in ("nie_pasaporte", "documento"):
        return documento_cliente(cliente)

    if field == "edad":
        return calcular_edad(cliente.get("fecha_nacimiento"))

    if field == "estado" or field == "estado_cliente":
        return status_badge(cliente.get("estado_cliente") or "-")

    if field == "ficha":
        return ficha_badge(cliente)

    if field in ("fecha_nacimiento", "fecha_alta", "created_at", "updated_at"):
        value = cliente.get(field)
        if field == "fecha_nacimiento":
            return fecha_a_display(value)
        return value or ""

    if field == "activo":
        value = cliente.get(field)
        if value in (1, "1", True):
            return "Sí"
        if value in (0, "0", False):
            return "No"
        return value or ""

    return cliente.get(field) or ""


FALLBACK_TIPOS_VIA = ["Calle", "Avenida", "Plaza", "Paseo", "Camino", "Carretera", "Ronda", "Travesía", "Urbanización", "Otro"]
FALLBACK_ESTADOS_CIVILES = ["Soltero/a", "Casado/a", "Divorciado/a", "Separado/a", "Viudo/a", "Pareja de hecho", "No consta"]

def safe_master_list(loader, fallback=None):
    try:
        values = loader()
        if values:
            return values
    except Exception:
        pass
    return fallback or []

def dropdown_values(values):
    return values or []

def set_dropdown_options(dropdown, values, selected_value=""):
    values = values or []
    dropdown.options = [ft.dropdown.Option(value) for value in values]
    dropdown.value = selected_value if selected_value in values else ""

def formatear_fecha_ddmmaaaa(value):
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)[:8]
    if len(digits) <= 2:
        return digits
    if len(digits) <= 4:
        return f"{digits[:2]}/{digits[2:]}"
    return f"{digits[:2]}/{digits[2:4]}/{digits[4:]}"

def componer_domicilio(tipo, nombre, numero, piso):
    partes = []
    if tipo:
        partes.append(tipo.strip())
    if nombre:
        partes.append(nombre.strip())
    if numero:
        partes.append(str(numero).strip())
    domicilio = " ".join(partes).strip()
    if piso:
        domicilio = f"{domicilio}, {piso.strip()}" if domicilio else piso.strip()
    return domicilio

def descomponer_domicilio(domicilio):
    if not domicilio:
        return "", "", "", ""
    domicilio = domicilio.strip()
    tipo_detectado = ""
    resto = domicilio
    for tipo in FALLBACK_TIPOS_VIA:
        if domicilio.lower().startswith(tipo.lower() + " "):
            tipo_detectado = tipo
            resto = domicilio[len(tipo):].strip()
            break
    piso = ""
    if "," in resto:
        resto, piso = resto.split(",", 1)
        piso = piso.strip()
    numero = ""
    via = resto.strip()
    match = re.search(r"^(.*)\s+(\d+[A-Za-z0-9\-ºª]*)$", via)
    if match:
        via = match.group(1).strip()
        numero = match.group(2).strip()
    return tipo_detectado, via, numero, piso


def nombre_completo(cliente):
    return " ".join(
        [
            cliente.get("nombre") or "",
            cliente.get("primer_apellido") or "",
            cliente.get("segundo_apellido") or "",
        ]
    ).strip()


def documento_cliente(cliente):
    return cliente.get("nie") or cliente.get("pasaporte") or cliente.get("dni") or ""


def calcular_edad(fecha_nacimiento):
    if not fecha_nacimiento:
        return ""
    try:
        nacimiento = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
        hoy = date.today()
        edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
        return str(edad)
    except ValueError:
        return ""


def fecha_a_sql(value):
    if not value:
        return ""
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def fecha_a_display(value):
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return value


def porcentaje_ficha(cliente):
    total = len(FICHA_FIELDS)
    completados = sum(1 for field in FICHA_FIELDS if cliente.get(field))
    return int((completados / total) * 100)


def ficha_badge(cliente):
    porcentaje = porcentaje_ficha(cliente)
    if porcentaje >= 80:
        color, bg = "#027A48", "#ECFDF3"
    elif porcentaje >= 50:
        color, bg = "#B54708", "#FFFAEB"
    else:
        color, bg = "#B42318", "#FEF3F2"
    return ft.Container(
        content=ft.Text(f"{porcentaje}%", size=12, weight=ft.FontWeight.BOLD, color=color),
        bgcolor=bg,
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
    )


def clients_view(page: ft.Page):
    state = {
        "editing_id": None,
        "clients": [],
        "csv_path": None,
        "csv_preview": [],
        "selected_client_ids": set(),
        "quick_filter": "todos",
        "detail_index": 0,
        "context_client_id": None,
        "context_index": 0,
    }

    nacionalidad_options = safe_master_list(get_nacionalidades)
    pais_options = safe_master_list(get_paises_nombres)
    provincia_options = safe_master_list(get_provincias_nombres)
    tipo_via_options = safe_master_list(get_tipos_via, FALLBACK_TIPOS_VIA)
    estado_civil_options = safe_master_list(get_estados_civiles, FALLBACK_ESTADOS_CIVILES)

    content_area = ft.Container(expand=True)
    table_container = ft.Container(expand=True)
    quick_filters_container = ft.Row(spacing=8, wrap=True)
    context_panel_container = ft.Container(
        width=360,
        padding=ft.padding.only(top=0),
        margin=ft.margin.only(top=0),
    )

    filter_column = select_input("Filtrar por", FILTER_COLUMNS, value="Nombre", width=220)
    search_input = text_input("Buscar cliente", width=320)

    nombre = required_text_input("Nombre", width=320)
    primer_apellido = text_input("Primer apellido", width=320)
    segundo_apellido = text_input("Segundo apellido", width=320)
    nie = text_input("NIE", width=220)
    pasaporte = text_input("Pasaporte", width=220)
    dni = text_input("DNI", width=220)
    nacionalidad_autocomplete = AppAutocomplete(
        page=page,
        label='Nacionalidad',
        options=nacionalidad_options,
        width=260,
        max_results=8,
    )
    fecha_nacimiento = text_input("Fecha nacimiento DD/MM/AAAA", width=260)
    telefono = text_input("Teléfono", width=220)
    email = text_input("Email", width=320)
    estado_cliente = select_input("Estado cliente", CLIENT_STATES, value="Asesoramiento inicial", width=320)
    sexo = select_input("Sexo", ["HOMBRE", "MUJER", "X"], width=180)

    tipo_via = select_input("Tipo de vía", dropdown_values(tipo_via_options), width=180)
    nombre_via = text_input("Nombre de la vía", width=320)
    numero_via = text_input("Número", width=120)
    piso = text_input("Piso / Puerta", width=160)

    domicilio_espana = text_input("Domicilio en España", width=420)

    localidad_options = []

    def on_provincia_selected(value):
        nonlocal localidad_options
        provincia_value = (value or "").strip()

        if not provincia_value:
            localidad_options = []
            localidad_autocomplete.set_options([], clear_value=True)
            localidad_autocomplete.input.label = "Localidad"
            return

        try:
            localidad_options = get_localidades_by_provincia(provincia_value)
        except Exception:
            localidad_options = []

        localidad_autocomplete.set_options(localidad_options, clear_value=True)
        localidad_autocomplete.input.label = (
            f"Localidad ({len(localidad_options)})" if localidad_options else "Localidad (sin datos)"
        )

    provincia_autocomplete = AppAutocomplete(
        page=page,
        label="Provincia",
        options=provincia_options,
        width=260,
        max_results=12,
        on_select=on_provincia_selected,
        allow_free_text=True,
    )

    localidad_autocomplete = AppAutocomplete(
        page=page,
        label="Localidad",
        options=[],
        width=260,
        max_results=12,
        allow_free_text=True,
    )

    codigo_postal = text_input("Código postal", width=180)
    localidad_nacimiento = text_input("Localidad nacimiento", width=260)
    pais_nacimiento_autocomplete = AppAutocomplete(
        page=page,
        label='País nacimiento',
        options=pais_options,
        width=260,
        max_results=8,
    )
    nombre_padre = text_input("Nombre del padre", width=320)
    nombre_madre = text_input("Nombre de la madre", width=320)
    estado_civil = select_input("Estado civil", dropdown_values(estado_civil_options), width=220)
    observaciones = multiline_input("Observaciones", width=640)
    observaciones_internas = multiline_input("Observaciones internas", width=640)
    form_message = ft.Column(controls=[], visible=False)

    def on_fecha_nacimiento_change(e=None):
        formatted = formatear_fecha_ddmmaaaa(fecha_nacimiento.value)
        if fecha_nacimiento.value != formatted:
            fecha_nacimiento.value = formatted
            page.update()

    fecha_nacimiento.on_change = on_fecha_nacimiento_change

    def show_message(control):
        form_message.controls.clear()
        form_message.controls.append(control)
        form_message.visible = True
        page.update()

    def clear_message():
        form_message.controls.clear()
        form_message.visible = False

    def limpiar_formulario():
        state["editing_id"] = None
        for field in [
            nombre,
            primer_apellido,
            segundo_apellido,
            nie,
            pasaporte,
            dni,
            fecha_nacimiento,
            telefono,
            email,
            tipo_via,
            nombre_via,
            numero_via,
            piso,
            domicilio_espana,
            codigo_postal,
            localidad_nacimiento,
            nombre_padre,
            nombre_madre,
            estado_civil,
            sexo,
            observaciones,
            observaciones_internas,
        ]:
            field.value = ""
        estado_cliente.value = "Asesoramiento inicial"
        nacionalidad_autocomplete.set_value("", update=False)
        pais_nacimiento_autocomplete.set_value("", update=False)
        provincia_autocomplete.set_value("", update=False)
        localidad_autocomplete.set_options([], clear_value=True)
        localidad_autocomplete.input.label = "Localidad"
        clear_message()

    def cargar_cliente_en_formulario(cliente):
        state["editing_id"] = cliente["id"]
        nombre.value = cliente.get("nombre") or ""
        primer_apellido.value = cliente.get("primer_apellido") or ""
        segundo_apellido.value = cliente.get("segundo_apellido") or ""
        nie.value = cliente.get("nie") or ""
        pasaporte.value = cliente.get("pasaporte") or ""
        dni.value = cliente.get("dni") or ""
        nacionalidad_autocomplete.set_value(cliente.get("nacionalidad") or "", update=False)
        fecha_nacimiento.value = fecha_a_display(cliente.get("fecha_nacimiento"))
        telefono.value = cliente.get("telefono") or ""
        email.value = cliente.get("email") or ""
        estado_cliente.value = cliente.get("estado_cliente") or "Asesoramiento inicial"

        tipo, via, numero, piso_value = descomponer_domicilio(cliente.get("domicilio_espana"))
        set_dropdown_options(tipo_via, tipo_via_options, tipo)
        nombre_via.value = via
        numero_via.value = numero
        piso.value = piso_value
        domicilio_espana.value = cliente.get("domicilio_espana") or ""

        provincia_value = cliente.get("provincia") or ""
        provincia_autocomplete.set_value(provincia_value, update=False)
        localidades = get_localidades_by_provincia(provincia_value) if provincia_value else []
        localidad_autocomplete.set_options(localidades, clear_value=False)
        localidad_autocomplete.input.label = f"Localidad ({len(localidades)})" if localidades else "Localidad"
        localidad_autocomplete.set_value(cliente.get("localidad") or "", update=False)

        codigo_postal.value = cliente.get("codigo_postal") or ""
        localidad_nacimiento.value = cliente.get("localidad_nacimiento") or ""
        pais_nacimiento_autocomplete.set_value(cliente.get("pais_nacimiento") or "", update=False)
        nombre_padre.value = cliente.get("nombre_padre") or ""
        nombre_madre.value = cliente.get("nombre_madre") or ""
        set_dropdown_options(estado_civil, estado_civil_options, cliente.get("estado_civil") or "")
        set_dropdown_options(sexo, ["HOMBRE", "MUJER", "X"], cliente.get("sexo") or "")
        observaciones.value = cliente.get("observaciones") or ""
        observaciones_internas.value = cliente.get("observaciones_internas") or ""
        clear_message()

    def datos_formulario():
        return {
            "nombre": nombre.value,
            "primer_apellido": primer_apellido.value,
            "segundo_apellido": segundo_apellido.value,
            "nie": nie.value,
            "pasaporte": pasaporte.value,
            "dni": dni.value,
            "nacionalidad": nacionalidad_autocomplete.get_value(),
            "fecha_nacimiento": fecha_a_sql(fecha_nacimiento.value),
            "telefono": telefono.value,
            "email": email.value,
            "estado_cliente": estado_cliente.value,
            "domicilio_espana": componer_domicilio(
                tipo_via.value,
                nombre_via.value,
                numero_via.value,
                piso.value,
            ),
            "localidad": localidad_autocomplete.get_value(),
            "provincia": provincia_autocomplete.get_value(),
            "codigo_postal": codigo_postal.value,
            "localidad_nacimiento": localidad_nacimiento.value,
            "pais_nacimiento": pais_nacimiento_autocomplete.get_value(),
            "nombre_padre": nombre_padre.value,
            "nombre_madre": nombre_madre.value,
            "estado_civil": estado_civil.value,
            "sexo": sexo.value,
            "observaciones": observaciones.value,
            "observaciones_internas": observaciones_internas.value,
        }

    def validar_formulario():
        errores = []
        if not nombre.value:
            errores.append("El nombre es obligatorio")
        if fecha_nacimiento.value and not fecha_a_sql(fecha_nacimiento.value):
            errores.append("La fecha de nacimiento debe tener formato DD/MM/AAAA")
        return errores

    def cerrar_dialogo(e=None):
        cliente_dialog.open = False
        page.update()

    def guardar_cliente(e):
        errores = validar_formulario()
        if errores:
            show_message(error_alert("\n".join(errores)))
            return
        data = datos_formulario()
        if state["editing_id"]:
            update_client(state["editing_id"], data)
        else:
            create_client(data)
        cerrar_dialogo()
        cargar_clientes()
        show_client_list()

    cliente_dialog = form_dialog(
        "Cliente",
        ft.Column(
            controls=[
                ft.Text("Datos básicos", size=16, weight=ft.FontWeight.BOLD, color="#003B7A"),
                ft.Row([nombre, primer_apellido, segundo_apellido], wrap=True, spacing=10),
                ft.Row([nie, pasaporte, dni], wrap=True, spacing=10),
                ft.Row([nacionalidad_autocomplete.control, fecha_nacimiento, telefono], wrap=True, spacing=10),
                ft.Row([email, estado_cliente], wrap=True, spacing=10),
                ft.Text("Dirección en España", size=16, weight=ft.FontWeight.BOLD, color="#003B7A"),
                ft.Row([tipo_via, nombre_via, numero_via, piso], wrap=True, spacing=10),
                ft.Row([provincia_autocomplete.control, localidad_autocomplete.control, codigo_postal], wrap=True, spacing=10),
                ft.Text("Datos personales", size=16, weight=ft.FontWeight.BOLD, color="#003B7A"),
                ft.Row([localidad_nacimiento, pais_nacimiento_autocomplete.control], wrap=True, spacing=10),
                ft.Row([nombre_padre, nombre_madre, estado_civil, sexo], wrap=True, spacing=10),
                observaciones,
                observaciones_internas,
                form_message,
            ],
            scroll=ft.ScrollMode.AUTO,
            height=620,
            width=900,
        ),
        actions=[secondary_button("Cancelar", cerrar_dialogo), primary_button("Guardar", guardar_cliente)],
    )
    page.overlay.append(cliente_dialog)

    def resolver_estado_cliente(cliente):
        cliente_id = cliente.get("id")

        if not cliente_id:
            return cliente.get("estado_cliente") or "Asesoramiento inicial"

        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row

            if not db_table_exists(conn, "expedientes"):
                conn.close()
                return cliente.get("estado_cliente") or "Asesoramiento inicial"

            row = conn.execute(
                '''
                SELECT
                    ea.nombre AS estado_administrativo
                FROM expedientes e
                LEFT JOIN config_estados_administrativos ea
                    ON ea.id = e.estado_administrativo_id
                WHERE e.cliente_id = ?
                  AND COALESCE(e.activo, 1) = 1
                ORDER BY
                    COALESCE(e.updated_at, e.created_at) DESC,
                    e.id DESC
                LIMIT 1
                ''',
                (int(cliente_id),),
            ).fetchone()

            conn.close()

            if row and row["estado_administrativo"]:
                return row["estado_administrativo"]

        except Exception:
            pass

        return cliente.get("estado_cliente") or "Asesoramiento inicial"

    def cargar_clientes():
        clientes = get_all_clients()

        for cliente in clientes:
            cliente["estado_cliente"] = resolver_estado_cliente(cliente)

        state["clients"] = clientes

    def pasa_quick_filter(cliente):
        qf = state["quick_filter"]
        estado = cliente.get("estado_cliente") or ""
        if qf == "todos":
            return True
        if qf == "pendientes":
            return estado == "Pendiente de documentación"
        if qf == "sin_documento":
            return not documento_cliente(cliente)
        if qf == "ficha_incompleta":
            return porcentaje_ficha(cliente) < 80
        if qf == "en_tramitacion":
            return estado == "En tramitación"
        if qf == "archivados":
            return estado == "Archivado"
        return True

    def cliente_pasa_filtro(cliente):
        if not pasa_quick_filter(cliente):
            return False
        texto = (search_input.value or "").lower().strip()
        if not texto:
            return True
        columna = filter_column.value
        if columna == "Nombre":
            valor = nombre_completo(cliente)
        elif columna == "NIE / Pasaporte":
            valor = documento_cliente(cliente)
        elif columna == "Nacionalidad":
            valor = cliente.get("nacionalidad") or ""
        elif columna == "Telefono":
            valor = cliente.get("telefono") or ""
        elif columna == "Estado":
            valor = cliente.get("estado_cliente") or ""
        else:
            valor = ""
        return texto in valor.lower()

    def clientes_filtrados():
        return [c for c in state["clients"] if cliente_pasa_filtro(c)]

    def selected_clients():
        selected_ids = state["selected_client_ids"]
        return [c for c in state["clients"] if c["id"] in selected_ids]

    def context_selected_clients():
        return selected_clients()

    def context_metrics():
        return {
            "clientes_activos": len(state["clients"]),
            "pendientes_documentacion": sum(1 for c in state["clients"] if c.get("estado_cliente") == "Pendiente de documentación"),
            "sin_documento": sum(1 for c in state["clients"] if not documento_cliente(c)),
            "ficha_incompleta": sum(1 for c in state["clients"] if porcentaje_ficha(c) < 80),
        }

    def context_client():
        clientes = context_selected_clients()
        if not clientes:
            state["context_client_id"] = None
            state["context_index"] = 0
            return None
        state["context_index"] = max(0, min(state["context_index"], len(clientes) - 1))
        cliente = clientes[state["context_index"]]
        state["context_client_id"] = cliente["id"]
        return cliente

    def next_context_client(e=None):
        clientes = context_selected_clients()
        if clientes and state["context_index"] < len(clientes) - 1:
            state["context_index"] += 1
        refresh_context_panel()
        page.update()

    def prev_context_client(e=None):
        if state["context_index"] > 0:
            state["context_index"] -= 1
        refresh_context_panel()
        page.update()

    def db_table_exists(conn, table_name):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    def get_context_expedientes(cliente):
        cliente_id = cliente.get("id")
        if not cliente_id:
            return []

        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row

            if not db_table_exists(conn, "expedientes"):
                conn.close()
                return []

            rows = conn.execute(
                '''
                SELECT
                    e.numero_expediente,
                    e.estado_presentacion,
                    e.fecha_apertura,
                    e.fecha_presentacion,
                    te.nombre AS tipo_expediente,
                    ed.nombre AS estado_documental,
                    ea.nombre AS estado_administrativo
                FROM expedientes e
                LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
                LEFT JOIN config_estados_documentales ed ON ed.id = e.estado_documental_id
                LEFT JOIN config_estados_administrativos ea ON ea.id = e.estado_administrativo_id
                WHERE e.cliente_id = ? AND COALESCE(e.activo, 1) = 1
                ORDER BY e.created_at DESC, e.id DESC
                ''',
                (int(cliente_id),),
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def get_context_economico(cliente):
        cliente_id = cliente.get("id")
        resumen = {
            "cobros": 0,
            "total_cobrado": 0.0,
            "hojas": 0,
            "facturas": 0,
            "pendientes_conciliar": 0,
        }

        if not cliente_id:
            return resumen

        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row

            if db_table_exists(conn, "eco_cobros"):
                row = conn.execute(
                    '''
                    SELECT
                        COUNT(*) AS total_cobros,
                        COALESCE(SUM(importe), 0) AS total_importe,
                        SUM(CASE WHEN COALESCE(estado_conciliacion, '') != 'CONCILIADO' THEN 1 ELSE 0 END) AS pendientes
                    FROM eco_cobros
                    WHERE cliente_id = ? AND COALESCE(activo, 1) = 1
                    ''',
                    (int(cliente_id),),
                ).fetchone()
                if row:
                    resumen["cobros"] = int(row["total_cobros"] or 0)
                    resumen["total_cobrado"] = float(row["total_importe"] or 0)
                    resumen["pendientes_conciliar"] = int(row["pendientes"] or 0)

            if db_table_exists(conn, "eco_hojas_encargo"):
                row = conn.execute(
                    "SELECT COUNT(*) AS total FROM eco_hojas_encargo WHERE cliente_id = ? AND COALESCE(activo, 1) = 1",
                    (int(cliente_id),),
                ).fetchone()
                resumen["hojas"] = int(row["total"] or 0) if row else 0

            if db_table_exists(conn, "eco_facturas"):
                row = conn.execute(
                    "SELECT COUNT(*) AS total FROM eco_facturas WHERE cliente_id = ? AND COALESCE(activo, 1) = 1",
                    (int(cliente_id),),
                ).fetchone()
                resumen["facturas"] = int(row["total"] or 0) if row else 0

            conn.close()
        except Exception:
            pass

        return resumen

    def money_context(value):
        try:
            return f"{float(value or 0):.2f} €"
        except Exception:
            return "0.00 €"

    def context_card(title, controls):
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color="#003B7A"),
                    *controls,
                ],
                spacing=8,
            ),
            bgcolor="#FFFFFF",
            border=ft.border.all(1, "#E4E7EC"),
            border_radius=14,
            padding=12,
        )

    def context_line(label, value):
        return ft.Row(
            controls=[
                ft.Text(label, size=12, color="#64748B", expand=True),
                ft.Text(str(value or "-"), size=12, color="#101828", weight=ft.FontWeight.W_600),
            ],
            spacing=8,
        )

    def build_context_alerts(cliente, expedientes=None, economico=None):
        expedientes = expedientes or []
        economico = economico or {}
        alerts = []

        if not documento_cliente(cliente):
            alerts.append("Sin NIE/Pasaporte/DNI")
        if not cliente.get("telefono"):
            alerts.append("Sin teléfono")
        if not cliente.get("email"):
            alerts.append("Sin email")
        if porcentaje_ficha(cliente) < 80:
            alerts.append("Ficha incompleta")
        if not expedientes:
            alerts.append("Sin expediente activo")
        if economico.get("pendientes_conciliar", 0) > 0:
            alerts.append(f"{economico.get('pendientes_conciliar')} cobro(s) sin conciliar")

        if not alerts:
            alerts.append("Sin alertas críticas")

        return [
            ft.Text(
                alert,
                size=12,
                color="#B42318" if alert != "Sin alertas críticas" else "#027A48",
                weight=ft.FontWeight.W_600,
            )
            for alert in alerts[:5]
        ]

    def client_initials(cliente):
        nombre = (cliente.get("nombre") or "").strip()
        primer_apellido = (cliente.get("primer_apellido") or "").strip()
        segundo_apellido = (cliente.get("segundo_apellido") or "").strip()

        parts = [part for part in [nombre, primer_apellido, segundo_apellido] if part]
        initials = "".join(part[0] for part in parts[:2]).upper()

        return initials or "CL"

    def build_empty_context_panel():
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Icon(ft.Icons.PERSON_SEARCH, size=42, color="#0057B8"),
                        bgcolor="#EAF3FF",
                        border_radius=50,
                        width=82,
                        height=82,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Text(
                        "Sin cliente seleccionado",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color="#003B7A",
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        "Selecciona uno o varios clientes en la tabla para ver aquí su resumen operativo.",
                        size=13,
                        color="#64748B",
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=360,
            bgcolor="#FFFFFF",
            border=ft.border.all(1, "#E4E7EC"),
            border_radius=16,
            padding=18,
            margin=ft.margin.only(top=0),
        )

    def context_header_card(cliente, nombre, ficha_pct):
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Text(
                            client_initials(cliente),
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color="#FFFFFF",
                        ),
                        width=52,
                        height=52,
                        border_radius=26,
                        bgcolor="#0057B8",
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(nombre, size=15, weight=ft.FontWeight.BOLD, color="#101828"),
                            ft.Text(
                                f"Ficha completa: {ficha_pct}%",
                                size=12,
                                color="#64748B",
                            ),
                            status_badge(cliente.get("estado_cliente") or "-"),
                        ],
                        spacing=5,
                        expand=True,
                    ),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="#FFFFFF",
            border=ft.border.all(1, "#E4E7EC"),
            border_radius=16,
            padding=14,
            margin=ft.margin.only(top=0),
        )

    def build_context_panel(cliente, clientes):
        if not cliente:
            return build_empty_context_panel()

        ficha_pct = porcentaje_ficha(cliente)
        nombre = nombre_completo(cliente) or "Cliente sin nombre"
        expedientes = get_context_expedientes(cliente)
        expediente_principal = expedientes[0] if expedientes else None
        economico = get_context_economico(cliente)

        expediente_estado = "-"
        expediente_tipo = "-"
        expediente_numero = "-"

        if expediente_principal:
            expediente_estado = (
                expediente_principal.get("estado_administrativo")
                or expediente_principal.get("estado_presentacion")
                or expediente_principal.get("estado_documental")
                or "-"
            )
            expediente_tipo = expediente_principal.get("tipo_expediente") or "-"
            expediente_numero = expediente_principal.get("numero_expediente") or "-"

        return ft.Column(
            controls=[
                context_header_card(cliente, nombre, ficha_pct),
                context_card(
                    "Resumen ficha",
                    [
                        context_line("Documento", documento_cliente(cliente)),
                        context_line("Teléfono", cliente.get("telefono")),
                        context_line("Email", cliente.get("email")),
                        context_line("Ficha", f"{ficha_pct}%"),
                        primary_button("Ver ficha", ver_ficha_contextual),
                    ],
                ),
                context_card(
                    "Resumen expedientes",
                    [
                        context_line("Activos", len(expedientes)),
                        context_line("Expediente", expediente_numero),
                        context_line("Tipo", expediente_tipo),
                        context_line("Estado", expediente_estado),
                    ],
                ),
                context_card(
                    "Resumen económico",
                    [
                        context_line("Cobros", economico.get("cobros")),
                        context_line("Total cobrado", money_context(economico.get("total_cobrado"))),
                        context_line("Hojas encargo", economico.get("hojas")),
                        context_line("Facturas", economico.get("facturas")),
                        context_line("Sin conciliar", economico.get("pendientes_conciliar")),
                    ],
                ),
                context_card(
                    "Alertas",
                    build_context_alerts(cliente, expedientes, economico),
                ),
                ft.Row(
                    controls=[secondary_button("Anterior", prev_context_client), primary_button("Siguiente", next_context_client)],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.END,
                    visible=len(clientes) > 1,
                ),
                ft.Text(
                    f"Cliente {state['context_index'] + 1} de {len(clientes)} seleccionados",
                    size=12,
                    color="#64748B",
                    visible=len(clientes) > 1,
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )

    def refresh_context_panel():
        cliente = context_client()
        clientes = context_selected_clients()
        context_panel_container.content = build_context_panel(cliente, clientes)

    def ver_ficha_contextual(e=None):
        clientes = selected_clients()
        if not clientes:
            return

        cliente = context_client()
        if cliente:
            for index, selected_cliente in enumerate(clientes):
                if selected_cliente.get("id") == cliente.get("id"):
                    state["detail_index"] = index
                    break
        else:
            state["detail_index"] = 0

        content_area.content = build_selected_detail_view()
        page.update()

    def selected_count_text():
        total = len(state["selected_client_ids"])
        if total == 0:
            return "Ningún cliente seleccionado"
        if total == 1:
            return "1 cliente seleccionado"
        return f"{total} clientes seleccionados"

    selected_info = ft.Text(selected_count_text(), size=13, color="#64748B")
    selection_bar = ft.Container(visible=True)
    bulk_actions = select_input("Acciones en lote", BULK_ACTIONS, value="Acciones en lote", width=220)

    def ejecutar_accion_lote(e=None):
        accion = bulk_actions.value or "Acciones en lote"

        if accion == "Acciones en lote":
            return

        total = len(state["selected_client_ids"])

        if total == 0:
            bulk_actions.value = "Acciones en lote"
            page.snack_bar = ft.SnackBar(ft.Text("Selecciona al menos un cliente para aplicar acciones en lote"))
            page.snack_bar.open = True
            page.update()
            return

        mensajes = {
            "Mandar email": f"Preparado para mandar email a {total} cliente(s)",
            "Mandar WhatsApp": f"Preparado para mandar WhatsApp a {total} cliente(s)",
            "Exportar CSV": f"Preparado para exportar CSV de {total} cliente(s)",
            "Exportar JSON": f"Preparado para exportar JSON de {total} cliente(s)",
        }

        page.snack_bar = ft.SnackBar(ft.Text(mensajes.get(accion, accion)))
        page.snack_bar.open = True
        bulk_actions.value = "Acciones en lote"
        page.update()

    bulk_actions.on_change = ejecutar_accion_lote

    def build_quick_filter_chip(label, key):
        selected = state["quick_filter"] == key
        return ft.Container(
            content=ft.Text(
                label,
                size=13,
                weight=ft.FontWeight.W_600 if selected else ft.FontWeight.NORMAL,
                color="#FFFFFF" if selected else "#0057B8",
            ),
            bgcolor="#0057B8" if selected else "#EAF3FF",
            border=ft.border.all(1, "#BFD7FF"),
            border_radius=20,
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            ink=True,
            on_click=lambda e, k=key: set_quick_filter(k),
        )

    def refresh_quick_filters():
        quick_filters_container.controls.clear()
        for label, key in QUICK_FILTERS:
            quick_filters_container.controls.append(build_quick_filter_chip(label, key))

    def set_quick_filter(key):
        state["quick_filter"] = key
        refresh_quick_filters()
        refresh_table()

    def refresh_selection_bar():
        selected_info.value = selected_count_text()
        has_selection = len(state["selected_client_ids"]) > 0
        editar_btn = secondary_button("Editar selección", open_bulk_dialog)
        archivar_btn = danger_button("Archivar selección", archivar_seleccionados)
        bulk_actions.disabled = not has_selection
        editar_btn.disabled = not has_selection
        archivar_btn.disabled = not has_selection
        selection_bar.visible = True
        selection_bar.content = ft.Row(
            controls=[selected_info, bulk_actions, editar_btn, archivar_btn],
            spacing=12,
            wrap=True,
        )

    def refresh_table(e=None):
        table_container.content = build_table()
        refresh_selection_bar()
        refresh_context_panel()
        page.update()

    def toggle_client_selection(client_id, row_ref=None, checkbox_ref=None, index=0):
        if client_id in state["selected_client_ids"]:
            state["selected_client_ids"].remove(client_id)
            if state.get("context_client_id") == client_id:
                state["context_index"] = 0
        else:
            state["selected_client_ids"].add(client_id)
            clientes = selected_clients()
            for i, cliente in enumerate(clientes):
                if cliente["id"] == client_id:
                    state["context_index"] = i
                    break

        is_selected = client_id in state["selected_client_ids"]
        if row_ref and row_ref.current:
            row_ref.current.bgcolor = "#EAF3FF" if is_selected else ("#FAFBFC" if index % 2 else "#FFFFFF")
        if checkbox_ref and checkbox_ref.current:
            checkbox_ref.current.value = is_selected
        refresh_context_panel()
        refresh_selection_bar()
        page.update()

    def toggle_all_visible_clients(e=None):
        visible_ids = {c["id"] for c in clientes_filtrados()}
        if visible_ids and visible_ids.issubset(state["selected_client_ids"]):
            state["selected_client_ids"].difference_update(visible_ids)
            state["context_client_id"] = None
            state["context_index"] = 0
        else:
            state["selected_client_ids"].update(visible_ids)
            state["context_index"] = 0
        refresh_table()

    def abrir_nuevo_cliente(e=None):
        limpiar_formulario()
        cliente_dialog.title = ft.Text("Nuevo cliente")
        cliente_dialog.open = True
        page.update()

    def abrir_editar_cliente(cliente):
        cargar_cliente_en_formulario(cliente)
        cliente_dialog.title = ft.Text("Editar cliente")
        cliente_dialog.open = True
        page.update()

    def archivar_seleccionados(e=None):
        for client_id in list(state["selected_client_ids"]):
            archive_client(client_id)
        state["selected_client_ids"].clear()
        state["context_client_id"] = None
        state["context_index"] = 0
        cargar_clientes()
        refresh_table()

    def ver_ficha(cliente):
        content_area.content = client_detail_view(
            page,
            cliente,
            on_back=show_client_list,
            on_edit=lambda e, c=cliente: abrir_editar_cliente(c),
        )
        page.update()

    def ver_fichas_seleccionadas(e=None):
        clientes = selected_clients()
        if not clientes:
            return
        state["detail_index"] = 0
        content_area.content = build_selected_detail_view()
        page.update()

    def selected_detail_cliente():
        clientes = selected_clients()
        if not clientes:
            return None
        state["detail_index"] = max(0, min(state["detail_index"], len(clientes) - 1))
        return clientes[state["detail_index"]]

    def next_selected_detail(e=None):
        clientes = selected_clients()
        if state["detail_index"] < len(clientes) - 1:
            state["detail_index"] += 1
            content_area.content = build_selected_detail_view()
            page.update()

    def prev_selected_detail(e=None):
        if state["detail_index"] > 0:
            state["detail_index"] -= 1
            content_area.content = build_selected_detail_view()
            page.update()

    bulk_estado = select_input("Nuevo estado", CLIENT_STATES, value="Asesoramiento inicial", width=320)

    def close_bulk_dialog(e=None):
        bulk_dialog.open = False
        page.update()

    def aplicar_estado_masivo(e=None):
        for cliente in selected_clients():
            data = dict(cliente)
            data["estado_cliente"] = bulk_estado.value
            update_client(cliente["id"], data)
        bulk_dialog.open = False
        cargar_clientes()
        refresh_table()
        page.update()

    bulk_dialog = form_dialog(
        "Editar clientes seleccionados",
        ft.Column(
            controls=[ft.Text("Aplicar cambio masivo de estado", size=14, color="#64748B"), bulk_estado],
            width=420,
            height=140,
        ),
        actions=[secondary_button("Cancelar", close_bulk_dialog), primary_button("Aplicar", aplicar_estado_masivo)],
    )
    page.overlay.append(bulk_dialog)

    def open_bulk_dialog(e=None):
        if not state["selected_client_ids"]:
            return
        bulk_dialog.open = True
        page.update()

    async def seleccionar_csv(e):
        files = await ft.FilePicker().pick_files(allow_multiple=False, allowed_extensions=["csv"])
        if not files:
            return
        state["csv_path"] = files[0].path
        state["csv_preview"] = preview_clients_from_csv(state["csv_path"])
        content_area.content = build_csv_preview()
        page.update()

    def confirmar_importacion(e=None):
        if not state["csv_path"]:
            content_area.content = warning_alert("No se ha seleccionado ningún CSV")
            page.update()
            return
        result = import_clients_from_csv(state["csv_path"])
        cargar_clientes()
        content_area.content = ft.Column(
            controls=[
                success_alert("Importación completada"),
                detail_section("Resultado", [("Importados", result["imported"]), ("Omitidos", result["skipped"])]),
                secondary_button("Volver a clientes", lambda e: show_client_list()),
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        page.update()

    def build_csv_preview():
        rows = []
        for item in state["csv_preview"]:
            c = item["client"]
            rows.append(
                [
                    ft.Text(nombre_completo(c), weight=ft.FontWeight.BOLD, size=14, no_wrap=False),
                    documento_cliente(c),
                    c.get("nacionalidad") or "",
                    c.get("telefono") or "",
                    "OK" if item["valid"] else "ERROR",
                    ", ".join(item["errors"]),
                ]
            )
        return ft.Column(
            controls=[
                ft.Text("Previsualización CSV", size=28, weight=ft.FontWeight.BOLD, color="#003B7A"),
                ft.Text("Revisa los datos antes de importar", size=14, color="#64748B"),
                action_row([secondary_button("Cancelar", lambda e: show_client_list()), primary_button("Confirmar importación", confirmar_importacion)]),
                app_table(headers=["Nombre", "Documento", "Nacionalidad", "Teléfono", "Estado", "Errores"], rows=rows, height=520),
            ],
            spacing=18,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_table():
        clients = clientes_filtrados()
        if not clients:
            return empty_state("No hay clientes que coincidan con la búsqueda")

        visible_ids = {c["id"] for c in clients}
        all_selected = bool(visible_ids) and visible_ids.issubset(state["selected_client_ids"])
        select_all_checkbox = ft.Checkbox(value=all_selected, on_change=toggle_all_visible_clients)

        configured_columns = client_table_columns()

        headers = [
            {
                "key": "__select__",
                "label": ft.Row(
                    controls=[
                        select_all_checkbox,
                        ft.Text("Sel.", weight=ft.FontWeight.W_600, size=13, color="#0057B8"),
                    ],
                    spacing=4,
                ),
                "width": 90,
            }
        ]

        for column in configured_columns:
            field = column.get("campo")
            headers.append(
                {
                    "key": field,
                    "label": client_table_label(field),
                    "width": int(column.get("ancho") or 160),
                }
            )

        rows = []

        for index, c in enumerate(clients):
            is_selected = c["id"] in state["selected_client_ids"]
            row_ref = ft.Ref()
            checkbox_ref = ft.Ref()

            row_checkbox = ft.Checkbox(
                ref=checkbox_ref,
                value=is_selected,
                on_change=lambda e, cid=c["id"], rr=row_ref, cr=checkbox_ref, idx=index: toggle_client_selection(cid, rr, cr, idx),
            )

            row_values = [
                {
                    "selected": is_selected,
                    "row_ref": row_ref,
                    "on_click": lambda e, cid=c["id"], rr=row_ref, cr=checkbox_ref, idx=index: toggle_client_selection(cid, rr, cr, idx),
                },
                row_checkbox,
            ]

            for column in configured_columns:
                field = column.get("campo")
                row_values.append(client_table_value(c, field))

            rows.append(row_values)

        return ft.Column(
            controls=[
                selection_bar,
                app_table(
                    headers=headers,
                    rows=rows,
                    height=390,
                ),
            ],
            spacing=4,
            expand=True,
        )

    def build_client_detail(cliente):
        return ft.Column(
            controls=[
                action_row([secondary_button("Volver", lambda e: show_client_list()), primary_button("Editar", lambda e, c=cliente: abrir_editar_cliente(c))]),
                ft.Text("Ficha del cliente", size=28, weight=ft.FontWeight.BOLD, color="#003B7A"),
                detail_section(
                    "Datos básicos",
                    [
                        ("Nombre completo", nombre_completo(cliente)),
                        ("NIE / Pasaporte", documento_cliente(cliente)),
                        ("Nacionalidad", cliente.get("nacionalidad")),
                        ("Fecha nacimiento", fecha_a_display(cliente.get("fecha_nacimiento"))),
                        ("Edad", calcular_edad(cliente.get("fecha_nacimiento"))),
                        ("Teléfono", cliente.get("telefono")),
                        ("Email", cliente.get("email")),
                        ("Estado", cliente.get("estado_cliente")),
                        ("Sexo", cliente.get("sexo")),
                        ("Ficha completada", f"{porcentaje_ficha(cliente)}%"),
                    ],
                ),
                detail_section("Dirección", [("Domicilio", cliente.get("domicilio_espana")), ("Localidad", cliente.get("localidad")), ("Provincia", cliente.get("provincia")), ("Código postal", cliente.get("codigo_postal"))]),
                detail_section("Datos personales", [("Localidad nacimiento", cliente.get("localidad_nacimiento")), ("País nacimiento", cliente.get("pais_nacimiento")), ("Nombre padre", cliente.get("nombre_padre")), ("Nombre madre", cliente.get("nombre_madre")), ("Estado civil", cliente.get("estado_civil"))]),
                detail_section("Observaciones", [("Observaciones", cliente.get("observaciones")), ("Observaciones internas", cliente.get("observaciones_internas"))]),
            ],
            spacing=18,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_selected_detail_view():
        cliente = selected_detail_cliente()
        clientes = selected_clients()
        if not cliente:
            return empty_state("No hay clientes seleccionados")
        total = len(clientes)
        pos = state["detail_index"] + 1
        return ft.Column(
            controls=[
                action_row([
                    secondary_button("Volver a clientes", lambda e: show_client_list()),
                    secondary_button("Anterior", prev_selected_detail),
                    primary_button("Siguiente", next_selected_detail),
                ]),
                ft.Text(f"Ficha seleccionada {pos} de {total}", size=14, color="#64748B"),
                client_detail_view(
                    page,
                    cliente,
                    on_back=show_client_list,
                    on_edit=lambda e, c=cliente: abrir_editar_cliente(c),
                ),
            ],
            spacing=12,
            expand=True,
        )

    def show_client_list(e=None):
        cargar_clientes()
        filter_column.on_change = refresh_table
        search_input.on_change = refresh_table
        refresh_quick_filters()
        table_container.content = build_table()
        refresh_selection_bar()
        refresh_context_panel()
        content_area.content = ft.Row(
            controls=[
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Column(
                                controls=[
                                    ft.Text("Clientes", size=28, weight=ft.FontWeight.BOLD, color="#003B7A"),
                                    ft.Text("Gestión operativa de clientes del despacho", size=14, color="#64748B"),
                                ],
                                spacing=2,
                            ),
                            ft.Row(
                                controls=[
                                    metric_card("Clientes activos", len(state["clients"])),
                                    metric_card("Pendientes documentación", sum(1 for c in state["clients"] if c.get("estado_cliente") == "Pendiente de documentación")),
                                    metric_card("Sin documento", sum(1 for c in state["clients"] if not documento_cliente(c))),
                                ],
                                spacing=12,
                            ),
                            filter_bar(
                                dropdown=filter_column,
                                search_input=search_input,
                                actions=[primary_button("Nuevo cliente", abrir_nuevo_cliente), secondary_button("Importar CSV", seleccionar_csv)],
                            ),
                            quick_filters_container,
                            table_container,
                        ],
                        spacing=10,
                        expand=True,
                    ),
                    expand=True,
                ),
                context_panel_container,
            ],
            spacing=18,
            expand=True,
        )
        page.update()

    cargar_clientes()
    show_client_list()
    return content_area
