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
    find_client_duplicates,
)
from backend.services.client_csv_service import (
    preview_clients_from_csv,
    import_clients_from_csv,
)
from backend.services.hubspot_service import (
    HubSpotImportError,
    preview_contact_import,
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
from backend.services.economic_service import get_deuda_cliente
from backend.services.client_administrative_status_service import (
    get_current_authorization,
    list_administrative_situations,
    list_authorization_types,
    set_current_authorization,
    update_current_authorization_details,
)
from frontend.components.client_context_panel import client_context_panel
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.views.client_detail_view import client_detail_view
from frontend.components.app_snackbar import show_snackbar
from frontend.components.listing import card_item, compact_pagination_bar

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

HEADER_BORDER = "#D9E3F0"

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
    ("Morosos", "morosos"),
    ("Al día", "al_dia"),
    ("Sin documento", "sin_documento"),
    ("Ficha incompleta", "ficha_incompleta"),
    ("Pagos vencidos", "pagos_vencidos"),
    ("Varios trámites", "varios_tramites"),
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
    {"campo": "deuda_pendiente", "visible": 1, "orden": 7, "ancho": 170},
    {"campo": "deuda_tramites", "visible": 1, "orden": 8, "ancho": 260},
    {"campo": "ficha", "visible": 1, "orden": 9, "ancho": 120},
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
    "deuda_pendiente": "Deuda pendiente",
    "deuda_tramites": "Deuda por trámite",
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
            ordered = sorted(
                visible,
                key=lambda col: (int(col.get("orden") or 0), col.get("campo") or ""),
            )
            if not any(col.get("campo") == "deuda_pendiente" for col in ordered):
                ordered.append({"campo": "deuda_pendiente", "visible": 1, "orden": 998, "ancho": 170})
            if not any(col.get("campo") == "deuda_tramites" for col in ordered):
                ordered.append({"campo": "deuda_tramites", "visible": 1, "orden": 999, "ancho": 260})
            return ordered
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
        return estado_economico_cliente_badge(cliente)

    if field == "deuda_pendiente":
        return deuda_badge(cliente)

    if field == "deuda_tramites":
        return deuda_tramites_cell(cliente)

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



EXCLUDED_QUICK_FILTER_STATES = {
    "EN PREPARACION",
    "EN PREPARACIÓN",
    "EN TRAMITE",
    "EN TRÁMITE",
    "FINALIZADO",
}


def normalize_filter_label(value):
    return (value or "").strip().upper()


def title_filter_label(value):
    value = (value or "").strip()
    if not value:
        return ""
    return value.title()


def quick_filter_colors(key):
    if key == "todos":
        return "#0057B8", "#FFFFFF", "#0057B8"
    if key == "morosos":
        return "#FEF3F2", "#B42318", "#FDA29B"
    if key == "al_dia":
        return "#ECFDF3", "#027A48", "#ABEFC6"
    if key == "sin_documento":
        return "#FEF3F2", "#B42318", "#FDA29B"
    if key == "ficha_incompleta":
        return "#FFFAEB", "#B54708", "#FEDF89"
    if key == "pagos_vencidos":
        return "#FFF1F3", "#C01048", "#FECDD6"
    if key == "varios_tramites":
        return "#EEF4FF", "#3538CD", "#C7D7FE"
    if key.startswith("estado::"):
        return "#F0F9FF", "#026AA2", "#B9E6FE"
    return "#EAF3FF", "#0057B8", "#BFD7FF"


def money_display(value):
    try:
        return f"{float(value or 0):.2f} €"
    except Exception:
        return "0.00 €"


def deuda_badge(cliente):
    deuda = cliente.get("_deuda_cliente") or {}
    total = float(deuda.get("deuda_total") or 0)
    tramites = deuda.get("tramites") or []

    if total <= 0:
        color, bg, label = "#027A48", "#ECFDF3", "0.00 €"
    elif total < 500:
        color, bg, label = "#B54708", "#FFFAEB", money_display(total)
    else:
        color, bg, label = "#B42318", "#FEF3F2", money_display(total)

    tooltip_lines = deuda_tooltip_lines(total, tramites)

    return ft.Container(
        content=ft.Text(label, size=12, weight=ft.FontWeight.BOLD, color=color),
        bgcolor=bg,
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
        tooltip="\n".join(tooltip_lines),
    )


def deuda_tooltip_lines(total, tramites):
    tooltip_lines = [f"Deuda total: {money_display(total)}"]

    for item in tramites:
        deuda_item = float(item.get("deuda") or 0)
        if deuda_item <= 0:
            continue

        tramite = item.get("tramite") or "Sin trámite"
        expediente = item.get("numero_expediente") or "Sin expediente"
        tooltip_lines.append(f"{expediente} · {tramite}: {money_display(deuda_item)}")

    return tooltip_lines


def compact_tramite_name(value):
    value = (value or "Sin trámite").strip()
    if len(value) <= 24:
        return value.title()
    return value[:21].title() + "..."


def deuda_tramites_cell(cliente):
    deuda = cliente.get("_deuda_cliente") or {}
    tramites = deuda.get("tramites") or []

    pendientes = [
        item for item in tramites
        if float(item.get("deuda") or 0) > 0
    ]

    if not pendientes:
        return ft.Container(
            content=ft.Text("Sin deuda por trámite", size=12, color="#027A48"),
            bgcolor="#ECFDF3",
            border_radius=14,
            padding=ft.padding.symmetric(horizontal=10, vertical=5),
        )

    visibles = pendientes[:2]
    resumen = " · ".join(
        f"{compact_tramite_name(item.get('tramite'))}: {money_display(item.get('deuda'))}"
        for item in visibles
    )

    restantes = len(pendientes) - len(visibles)
    if restantes > 0:
        resumen += f" · +{restantes}"

    total = float(deuda.get("deuda_total") or 0)
    tooltip_lines = deuda_tooltip_lines(total, pendientes)

    return ft.Container(
        content=ft.Text(
            resumen,
            size=12,
            color="#101828",
            no_wrap=True,
        ),
        bgcolor="#F8FAFC",
        border=ft.border.all(1, "#E4E7EC"),
        border_radius=14,
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
        tooltip="\n".join(tooltip_lines),
    )

CLOSED_EXPEDIENT_STATES = {
    "FINALIZADO",
    "ARCHIVADO",
    "CONCEDIDO",
    "DENEGADO",
    "DESISTIDO",
    "CERRADO",
}


def estado_cliente_tooltip_lines(cliente):
    expedientes = cliente.get("_expedientes_cliente") or []

    if not expedientes:
        return ["Sin expedientes activos"]

    lines = []
    for item in expedientes:
        prioridad = item.get("prioridad") or "Sin prioridad"
        numero = item.get("numero_expediente") or "Sin expediente"
        tramite = item.get("tipo_expediente") or "Sin trámite"
        estado = item.get("estado_administrativo") or item.get("estado_presentacion") or item.get("estado_documental") or "-"
        lines.append(f"{prioridad} · {numero} · {tramite}: {estado}")

    return lines


def estado_cliente_priorizado_badge(cliente):
    estado = cliente.get("estado_cliente") or "-"
    return ft.Container(
        content=status_badge(estado),
        tooltip="\n".join(estado_cliente_tooltip_lines(cliente)),
    )


def cliente_tiene_varios_tramites_en_proceso(cliente):
    expedientes = cliente.get("_expedientes_cliente") or []
    abiertos = []

    for item in expedientes:
        estado = normalize_filter_label(
            item.get("estado_administrativo")
            or item.get("estado_presentacion")
            or item.get("estado_documental")
            or ""
        )

        if estado and estado in CLOSED_EXPEDIENT_STATES:
            continue

        abiertos.append(item)

    return len(abiertos) > 1


def resolver_estado_economico_cliente(cliente):
    deuda = cliente.get("_deuda_cliente") or {}

    importe_hojas = float(deuda.get("importe_hojas") or 0)
    importe_cobros = float(deuda.get("importe_cobros") or 0)
    deuda_total = float(deuda.get("deuda_total") or 0)

    if deuda_total > 0:
        return "MOROSO"

    if importe_hojas > 0 and deuda_total <= 0:
        return "AL DÍA"

    if importe_cobros > 0 and importe_hojas <= 0:
        return "COBROS SIN HOJA"

    return "SIN ACTIVIDAD ECONÓMICA"


def estado_economico_cliente_badge(cliente):
    estado = cliente.get("estado_cliente") or "SIN ACTIVIDAD ECONÓMICA"
    deuda = cliente.get("_deuda_cliente") or {}

    deuda_total = float(deuda.get("deuda_total") or 0)
    importe_hojas = float(deuda.get("importe_hojas") or 0)
    importe_cobros = float(deuda.get("importe_cobros") or 0)

    if estado == "MOROSO":
        color, bg = "#B42318", "#FEF3F2"
    elif estado == "AL DÍA":
        color, bg = "#027A48", "#ECFDF3"
    elif estado == "COBROS SIN HOJA":
        color, bg = "#B54708", "#FFFAEB"
    else:
        color, bg = "#475467", "#F2F4F7"

    tooltip = "\n".join(
        [
            f"Estado económico: {estado}",
            f"Hojas encargo: {money_display(importe_hojas)}",
            f"Cobros: {money_display(importe_cobros)}",
            f"Deuda pendiente: {money_display(deuda_total)}",
        ]
    )

    return ft.Container(
        content=ft.Text(
            estado.title(),
            size=12,
            weight=ft.FontWeight.BOLD,
            color=color,
        ),
        bgcolor=bg,
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
        tooltip=tooltip,
    )


def cliente_deuda_total(cliente):
    deuda = cliente.get("_deuda_cliente") or {}

    try:
        importe_hojas = float(deuda.get("importe_hojas") or 0)
        deuda_total = float(deuda.get("deuda_total") or 0)

        # Solo existe deuda real si:
        # - hay hojas de encargo
        # - y la deuda es positiva
        if importe_hojas <= 0:
            return 0.0

        return max(deuda_total, 0.0)

    except Exception:
        return 0.0


def total_morosos(clientes):
    return sum(1 for cliente in clientes if cliente_deuda_total(cliente) > 0)


def importe_total_deuda(clientes):
    return sum(cliente_deuda_total(cliente) for cliente in clientes)


def table_columns(conn, table_name):
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row["name"] for row in rows]
    except Exception:
        return []


def first_existing_column(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def recalcular_deuda_cliente_sobre_bruto(cliente_id, deuda_base=None):
    """
    Recalcula la deuda usando el importe BRUTO de hojas de encargo.

    Mantiene la estructura de get_deuda_cliente para que la tabla y tooltips
    sigan funcionando, pero sustituye:
    - importe_hojas
    - deuda_total
    - tramites[].deuda

    No cuenta facturas.
    No cuenta cobros sin hoja para generar deuda negativa.
    """
    deuda_base = deuda_base or {
        "importe_hojas": 0.0,
        "importe_cobros": 0.0,
        "deuda_total": 0.0,
        "tramites": [],
    }

    if not cliente_id:
        return deuda_base

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        if not db_table_exists_global(conn, "eco_hojas_encargo"):
            conn.close()
            return deuda_base

        hojas_columns = table_columns(conn, "eco_hojas_encargo")
        cobros_columns = table_columns(conn, "eco_cobros") if db_table_exists_global(conn, "eco_cobros") else []
        expedientes_columns = table_columns(conn, "expedientes") if db_table_exists_global(conn, "expedientes") else []

        bruto_col = first_existing_column(
            hojas_columns,
            [
                "importe_bruto",
                "bruto",
                "total_bruto",
                "importe_total",
                "total",
                "importe_hoja",
                "importe",
            ],
        )

        if not bruto_col:
            conn.close()
            return deuda_base

        hoja_cliente_col = "cliente_id" if "cliente_id" in hojas_columns else None
        hoja_expediente_col = "expediente_id" if "expediente_id" in hojas_columns else None
        hoja_activo_filter = "AND COALESCE(h.activo, 1) = 1" if "activo" in hojas_columns else ""

        if not hoja_cliente_col:
            conn.close()
            return deuda_base

        importe_hojas = conn.execute(
            f"""
            SELECT COALESCE(SUM(h.{bruto_col}), 0) AS total
            FROM eco_hojas_encargo h
            WHERE h.{hoja_cliente_col} = ?
              {hoja_activo_filter}
            """,
            (int(cliente_id),),
        ).fetchone()["total"] or 0

        importe_cobros = 0.0
        if cobros_columns:
            cobro_cliente_col = "cliente_id" if "cliente_id" in cobros_columns else None
            cobro_importe_col = first_existing_column(cobros_columns, ["importe", "importe_cobrado", "total", "cantidad"])
            cobro_hoja_col = "hoja_encargo_id" if "hoja_encargo_id" in cobros_columns else None
            cobro_activo_filter = "AND COALESCE(c.activo, 1) = 1" if "activo" in cobros_columns else ""

            if cobro_importe_col:
                if cobro_hoja_col and "id" in hojas_columns:
                    # Solo cobros vinculados a hojas de encargo.
                    importe_cobros = conn.execute(
                        f"""
                        SELECT COALESCE(SUM(c.{cobro_importe_col}), 0) AS total
                        FROM eco_cobros c
                        INNER JOIN eco_hojas_encargo h ON h.id = c.{cobro_hoja_col}
                        WHERE h.{hoja_cliente_col} = ?
                          {hoja_activo_filter}
                          {cobro_activo_filter}
                        """,
                        (int(cliente_id),),
                    ).fetchone()["total"] or 0
                elif cobro_cliente_col:
                    # Fallback: cobros del cliente solo si no hay columna hoja_encargo_id.
                    importe_cobros = conn.execute(
                        f"""
                        SELECT COALESCE(SUM(c.{cobro_importe_col}), 0) AS total
                        FROM eco_cobros c
                        WHERE c.{cobro_cliente_col} = ?
                          {cobro_activo_filter}
                        """,
                        (int(cliente_id),),
                    ).fetchone()["total"] or 0

        deuda_total = max(float(importe_hojas or 0) - float(importe_cobros or 0), 0.0)

        tramites = []
        if hoja_expediente_col:
            tipo_join = ""
            tipo_select = "'Sin trámite' AS tramite"
            numero_select = "CAST(h.expediente_id AS TEXT) AS numero_expediente"

            if db_table_exists_global(conn, "expedientes") and "id" in expedientes_columns:
                tipo_join = "LEFT JOIN expedientes e ON e.id = h.expediente_id"
                numero_select = "COALESCE(e.numero_expediente, CAST(h.expediente_id AS TEXT)) AS numero_expediente"

                if db_table_exists_global(conn, "config_tipos_expediente"):
                    tipo_join += " LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id"
                    tipo_select = "COALESCE(te.nombre, 'Sin trámite') AS tramite"

            hojas_por_exp = conn.execute(
                f"""
                SELECT
                    h.{hoja_expediente_col} AS expediente_id,
                    {numero_select},
                    {tipo_select},
                    COALESCE(SUM(h.{bruto_col}), 0) AS importe_hojas
                FROM eco_hojas_encargo h
                {tipo_join}
                WHERE h.{hoja_cliente_col} = ?
                  {hoja_activo_filter}
                GROUP BY h.{hoja_expediente_col}
                """,
                (int(cliente_id),),
            ).fetchall()

            cobros_por_exp = {}
            if cobros_columns:
                cobro_importe_col = first_existing_column(cobros_columns, ["importe", "importe_cobrado", "total", "cantidad"])
                cobro_hoja_col = "hoja_encargo_id" if "hoja_encargo_id" in cobros_columns else None
                cobro_expediente_col = "expediente_id" if "expediente_id" in cobros_columns else None
                cobro_activo_filter = "AND COALESCE(c.activo, 1) = 1" if "activo" in cobros_columns else ""

                if cobro_importe_col and cobro_hoja_col and "id" in hojas_columns:
                    rows = conn.execute(
                        f"""
                        SELECT
                            h.{hoja_expediente_col} AS expediente_id,
                            COALESCE(SUM(c.{cobro_importe_col}), 0) AS importe_cobros
                        FROM eco_cobros c
                        INNER JOIN eco_hojas_encargo h ON h.id = c.{cobro_hoja_col}
                        WHERE h.{hoja_cliente_col} = ?
                          {hoja_activo_filter}
                          {cobro_activo_filter}
                        GROUP BY h.{hoja_expediente_col}
                        """,
                        (int(cliente_id),),
                    ).fetchall()
                    cobros_por_exp = {row["expediente_id"]: float(row["importe_cobros"] or 0) for row in rows}
                elif cobro_importe_col and cobro_expediente_col:
                    rows = conn.execute(
                        f"""
                        SELECT
                            c.{cobro_expediente_col} AS expediente_id,
                            COALESCE(SUM(c.{cobro_importe_col}), 0) AS importe_cobros
                        FROM eco_cobros c
                        WHERE c.cliente_id = ?
                          {cobro_activo_filter}
                        GROUP BY c.{cobro_expediente_col}
                        """,
                        (int(cliente_id),),
                    ).fetchall()
                    cobros_por_exp = {row["expediente_id"]: float(row["importe_cobros"] or 0) for row in rows}

            for row in hojas_por_exp:
                importe_hoja = float(row["importe_hojas"] or 0)
                importe_cobro = float(cobros_por_exp.get(row["expediente_id"], 0.0) or 0)
                deuda_exp = max(importe_hoja - importe_cobro, 0.0)

                tramites.append(
                    {
                        "expediente_id": row["expediente_id"],
                        "numero_expediente": row["numero_expediente"],
                        "tramite": row["tramite"],
                        "importe_hojas": importe_hoja,
                        "importe_cobros": importe_cobro,
                        "deuda": deuda_exp,
                    }
                )

        conn.close()

        deuda_base["importe_hojas"] = float(importe_hojas or 0)
        deuda_base["importe_cobros"] = float(importe_cobros or 0)
        deuda_base["deuda_total"] = deuda_total
        deuda_base["tramites"] = tramites

        return deuda_base

    except Exception:
        return deuda_base


def db_table_exists_global(conn, table_name):
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def clients_view(
    page: ft.Page,
    on_create_expediente=None,
    on_open_expediente=None,
    open_client_id=None,
    on_context_back=None,
    new_client_defaults=None,
    on_client_created=None,
    on_client_phone_changed=None,
):
    state = {
        "editing_id": None,
        "editing_original_phone": "",
        "pending_phone_change": None,
        "clients": [],
        "csv_path": None,
        "csv_preview": [],
        "selected_client_ids": set(),
        "quick_filter": "todos",
        "detail_index": 0,
        "context_client_id": None,
        "context_index": 0,
        "page": 1,
        "page_size": 10,
    }

    nacionalidad_options = safe_master_list(get_nacionalidades)
    pais_options = safe_master_list(get_paises_nombres)
    provincia_options = safe_master_list(get_provincias_nombres)
    tipo_via_options = safe_master_list(get_tipos_via, FALLBACK_TIPOS_VIA)
    estado_civil_options = safe_master_list(get_estados_civiles, FALLBACK_ESTADOS_CIVILES)

    try:
        administrative_situations = (
            list_administrative_situations()
        )
    except Exception:
        administrative_situations = []

    try:
        authorization_types = (
            list_authorization_types()
        )
    except Exception:
        authorization_types = []

    situation_by_label = {
        item["nombre"]: item
        for item in administrative_situations
    }

    situation_label_by_id = {
        int(item["id"]): item["nombre"]
        for item in administrative_situations
    }

    authorization_label_by_id = {
        int(item["id"]): item["nombre"]
        for item in authorization_types
    }

    authorization_by_label = {
        item["nombre"]: item
        for item in authorization_types
    }

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
    fecha_caducidad_residencia = text_input(
        "Caducidad NIE/TIE DD/MM/AAAA",
        width=260,
    )
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

    numero_soporte_nie = text_input(
        "Número de soporte NIE/TIE",
        width=240,
    )

    localizacion_actual_autocomplete = AppAutocomplete(
        page=page,
        label="Localización actual",
        options=[
            "EN ESPAÑA",
            "EN PAÍS DE ORIGEN",
            "EN OTRO PAÍS",
            "DESCONOCIDA",
        ],
        width=240,
        max_results=4,
        allow_free_text=False,
    )

    pais_localizacion_actual_autocomplete = AppAutocomplete(
        page=page,
        label="País de localización actual",
        options=pais_options,
        width=280,
        max_results=10,
        allow_free_text=False,
    )

    fecha_entrada_espana = text_input(
        "Entrada en España DD/MM/AAAA",
        width=260,
    )

    fecha_entrada_espana_aproximada = ft.Checkbox(
        label="Fecha aproximada",
        value=False,
    )

    situacion_administrativa_autocomplete = AppAutocomplete(
        page=page,
        label="Situación administrativa",
        options=list(situation_by_label.keys()),
        width=360,
        max_results=10,
        allow_free_text=False,
        on_select=lambda value:
            on_situacion_administrativa_selected(value),
    )

    autorizacion_vigente_autocomplete = AppAutocomplete(
        page=page,
        label="Autorización vigente",
        options=[],
        width=620,
        max_results=12,
        allow_free_text=False,
    )

    autorizacion_vigente_desde = text_input(
        "Vigente desde DD/MM/AAAA",
        width=260,
    )

    autorizacion_vigente_hasta = text_input(
        "Vigente hasta DD/MM/AAAA",
        width=260,
    )

    fecha_inicio_residencia_legal = text_input(
        "Inicio residencia legal DD/MM/AAAA",
        width=280,
    )

    fecha_inicio_residencia_legal_aproximada = ft.Checkbox(
        label="Fecha aproximada",
        value=False,
    )

    continuidad_residencia_legal_autocomplete = AppAutocomplete(
        page=page,
        label="Continuidad de la residencia",
        options=[
            "VERIFICADA",
            "PENDIENTE DE VERIFICAR",
            "POSIBLE INTERRUPCIÓN",
            "INTERRUMPIDA",
            "NO DETERMINADA",
        ],
        width=320,
        max_results=5,
        allow_free_text=False,
    )

    estado_verificacion_residencia_legal_autocomplete = (
        AppAutocomplete(
            page=page,
            label="Estado de verificación",
            options=[
                "ACREDITADA DOCUMENTALMENTE",
                "DECLARADA POR EL CLIENTE",
                "PENDIENTE DE DOCUMENTACIÓN",
                "REQUIERE REVISIÓN",
            ],
            width=340,
            max_results=4,
            allow_free_text=False,
        )
    )

    fecha_verificacion_residencia_legal = text_input(
        "Fecha de verificación DD/MM/AAAA",
        width=290,
    )

    origen_residencia_legal_autocomplete = AppAutocomplete(
        page=page,
        label="Origen del dato",
        options=[
            "RESOLUCIÓN",
            "TIE",
            "CERTIFICADO DE RESIDENCIA",
            "PASAPORTE",
            "EXPEDIENTE ANTERIOR",
            "DECLARACIÓN DEL CLIENTE",
            "OTRO",
        ],
        width=320,
        max_results=7,
        allow_free_text=True,
    )

    observaciones_residencia_legal = ft.TextField(
        label="Observaciones sobre residencia legal",
        multiline=True,
        min_lines=2,
        max_lines=4,
        width=700,
    )

    antiguedad_residencia_legal = ft.Text(
        "Antigüedad computable: sin fecha",
        size=13,
        weight=ft.FontWeight.W_600,
        color="#475569",
    )

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

    hubspot_url_input = text_input("URL o ID de contacto HubSpot", width=680)
    hubspot_message = ft.Column(controls=[], visible=False)
    hubspot_import_data = {
        "hubspot_id": "",
        "hubspot_url": "",
        "hubspot_imported_at": "",
    }

    def authorization_matches_situation(
        authorization,
        situation_code,
    ):
        category = (
            authorization.get("categoria")
            or ""
        ).upper()

        modality = (
            authorization.get("modalidad")
            or ""
        ).upper()

        regime = (
            authorization.get("regimen_juridico")
            or ""
        ).upper()

        if situation_code == "ESTANCIA_CORTA_DURACION":
            return (
                category == "ESTANCIA"
                and modality == "CORTA_DURACION"
            )

        if situation_code == "ESTANCIA_LARGA_DURACION":
            return (
                category == "ESTANCIA"
                and modality != "CORTA_DURACION"
            )

        if situation_code == "RESIDENCIA_TEMPORAL":
            return (
                category.startswith(
                    "RESIDENCIA_TEMPORAL"
                )
                or category == "ARRAIGO"
                or category
                == "OTRAS_CIRCUNSTANCIAS_EXCEPCIONALES"
                or regime
                == "FAMILIAR_PERSONA_ESPANOLA"
                or (
                    regime == "CIUDADANOS_UNION"
                    and category
                    == "FAMILIAR_CIUDADANO_UE"
                )
            )

        if situation_code == "RESIDENCIA_LARGA_DURACION":
            return category == "LARGA_DURACION"

        if situation_code == "CIUDADANO_UE":
            return regime == "CIUDADANOS_UNION"

        if situation_code in {
            "SOLICITANTE_PROTECCION_INTERNACIONAL",
            "PROTECCION_TEMPORAL",
        }:
            return regime in {
                "PROTECCION_INTERNACIONAL",
                "PROTECCION_TEMPORAL",
            }

        return False

    def refresh_authorization_options(
        selected_authorization_id=None,
    ):
        situation = situation_by_label.get(
            situacion_administrativa_autocomplete.get_value()
            or ""
        )

        situation_code = (
            situation.get("codigo")
            if situation
            else None
        )

        filtered = [
            item
            for item in authorization_types
            if authorization_matches_situation(
                item,
                situation_code,
            )
        ]

        labels = [
            item["nombre"]
            for item in filtered
        ]

        selected_label = (
            authorization_label_by_id.get(
                int(selected_authorization_id)
            )
            if selected_authorization_id
            else ""
        )

        if (
            selected_label
            and selected_label not in labels
        ):
            labels.append(
                selected_label
            )

        autorizacion_vigente_autocomplete.set_options(
            labels,
            clear_value=not bool(selected_label),
        )

        autorizacion_vigente_autocomplete.set_value(
            selected_label or "",
            update=False,
        )

    def on_situacion_administrativa_selected(
        value,
    ):
        refresh_authorization_options()
        page.update()

    def on_fecha_entrada_espana_change(e=None):
        formatted = formatear_fecha_ddmmaaaa(
            fecha_entrada_espana.value
        )

        if fecha_entrada_espana.value != formatted:
            fecha_entrada_espana.value = formatted
            page.update()

    fecha_entrada_espana.on_change = (
        on_fecha_entrada_espana_change
    )

    def on_autorizacion_fecha_change(control):
        def handler(e=None):
            formatted = formatear_fecha_ddmmaaaa(
                control.value
            )

            if control.value != formatted:
                control.value = formatted
                page.update()

        return handler

    autorizacion_vigente_desde.on_change = (
        on_autorizacion_fecha_change(
            autorizacion_vigente_desde
        )
    )

    autorizacion_vigente_hasta.on_change = (
        on_autorizacion_fecha_change(
            autorizacion_vigente_hasta
        )
    )

    def actualizar_antiguedad_residencia_legal(
        e=None,
    ):
        from datetime import date, datetime

        value = fecha_a_sql(
            fecha_inicio_residencia_legal.value
        )

        if not value:
            antiguedad_residencia_legal.value = (
                "Antigüedad computable: sin fecha"
            )

            if e is not None:
                page.update()

            return

        try:
            start = datetime.strptime(
                value,
                "%Y-%m-%d",
            ).date()
        except ValueError:
            antiguedad_residencia_legal.value = (
                "Antigüedad computable: fecha no válida"
            )

            if e is not None:
                page.update()

            return

        today = date.today()

        if start > today:
            antiguedad_residencia_legal.value = (
                "Antigüedad computable: la fecha es futura"
            )

            if e is not None:
                page.update()

            return

        years = today.year - start.year
        months = today.month - start.month
        days = today.day - start.day

        if days < 0:
            months -= 1

            previous_month = (
                today.month - 1
                if today.month > 1
                else 12
            )

            previous_year = (
                today.year
                if today.month > 1
                else today.year - 1
            )

            if previous_month == 12:
                next_month = date(
                    previous_year + 1,
                    1,
                    1,
                )
            else:
                next_month = date(
                    previous_year,
                    previous_month + 1,
                    1,
                )

            current_month = date(
                previous_year,
                previous_month,
                1,
            )

            days += (
                next_month - current_month
            ).days

        if months < 0:
            years -= 1
            months += 12

        antiguedad_residencia_legal.value = (
            "Antigüedad computable: "
            f"{years} años, "
            f"{months} meses y "
            f"{days} días"
        )

        if e is not None:
            page.update()

    def on_fecha_inicio_residencia_legal_change(
        e=None,
    ):
        formatted = formatear_fecha_ddmmaaaa(
            fecha_inicio_residencia_legal.value
        )

        if (
            fecha_inicio_residencia_legal.value
            != formatted
        ):
            fecha_inicio_residencia_legal.value = (
                formatted
            )

        actualizar_antiguedad_residencia_legal(
            e
        )

    fecha_inicio_residencia_legal.on_change = (
        on_fecha_inicio_residencia_legal_change
    )

    fecha_verificacion_residencia_legal.on_change = (
        on_autorizacion_fecha_change(
            fecha_verificacion_residencia_legal
        )
    )

    def on_fecha_nacimiento_change(e=None):
        formatted = formatear_fecha_ddmmaaaa(fecha_nacimiento.value)
        if fecha_nacimiento.value != formatted:
            fecha_nacimiento.value = formatted
            page.update()

    fecha_nacimiento.on_change = on_fecha_nacimiento_change

    def on_fecha_caducidad_residencia_change(e=None):
        formatted = formatear_fecha_ddmmaaaa(
            fecha_caducidad_residencia.value
        )
        if (
            fecha_caducidad_residencia.value
            != formatted
        ):
            fecha_caducidad_residencia.value = formatted
            page.update()

    fecha_caducidad_residencia.on_change = (
        on_fecha_caducidad_residencia_change
    )

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
        state["editing_original_phone"] = ""
        state["pending_phone_change"] = None
        for field in [
            nombre,
            primer_apellido,
            segundo_apellido,
            nie,
            pasaporte,
            dni,
            numero_soporte_nie,
            pais_localizacion_actual_autocomplete.control,
            fecha_entrada_espana,
            autorizacion_vigente_desde,
            autorizacion_vigente_hasta,
            fecha_inicio_residencia_legal,
            fecha_verificacion_residencia_legal,
            observaciones_residencia_legal,
            fecha_caducidad_residencia,
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
        localizacion_actual_autocomplete.set_value(
            "",
            update=False,
        )
        pais_localizacion_actual_autocomplete.set_value(
            "",
            update=False,
        )
        situacion_administrativa_autocomplete.set_value(
            "",
            update=False,
        )
        autorizacion_vigente_autocomplete.set_value(
            "",
            update=False,
        )
        fecha_entrada_espana_aproximada.value = False
        fecha_inicio_residencia_legal_aproximada.value = False

        continuidad_residencia_legal_autocomplete.set_value(
            "",
            update=False,
        )

        estado_verificacion_residencia_legal_autocomplete.set_value(
            "",
            update=False,
        )

        origen_residencia_legal_autocomplete.set_value(
            "",
            update=False,
        )

        antiguedad_residencia_legal.value = (
            "Antigüedad computable: sin fecha"
        )

        autorizacion_vigente_autocomplete.set_options(
            [],
            clear_value=True,
        )
        nacionalidad_autocomplete.set_value("", update=False)
        pais_nacimiento_autocomplete.set_value("", update=False)
        provincia_autocomplete.set_value("", update=False)
        localidad_autocomplete.set_options([], clear_value=True)
        localidad_autocomplete.input.label = "Localidad"
        clear_message()

    def cargar_cliente_en_formulario(cliente):
        state["editing_id"] = cliente["id"]
        state["editing_original_phone"] = str(
            cliente.get("telefono")
            or ""
        ).strip()

        nombre.value = cliente.get("nombre") or ""
        primer_apellido.value = cliente.get("primer_apellido") or ""
        segundo_apellido.value = cliente.get("segundo_apellido") or ""
        nie.value = cliente.get("nie") or ""
        pasaporte.value = cliente.get("pasaporte") or ""
        dni.value = cliente.get("dni") or ""
        numero_soporte_nie.value = (
            cliente.get("numero_soporte_nie")
            or ""
        )

        location_display = {
            "EN_ESPANA": "EN ESPAÑA",
            "EN_ORIGEN": "EN PAÍS DE ORIGEN",
            "EN_OTRO_PAIS": "EN OTRO PAÍS",
            "DESCONOCIDA": "DESCONOCIDA",
        }

        localizacion_actual_autocomplete.set_value(
            location_display.get(
                cliente.get("localizacion_actual"),
                cliente.get("localizacion_actual")
                or "",
            ),
            update=False,
        )

        pais_localizacion_actual_autocomplete.set_value(
            cliente.get(
                "pais_localizacion_actual"
            )
            or "",
            update=False,
        )

        fecha_entrada_espana.value = fecha_a_display(
            cliente.get(
                "fecha_entrada_espana"
            )
        )

        fecha_entrada_espana_aproximada.value = bool(
            cliente.get(
                "fecha_entrada_espana_aproximada"
            )
        )

        situation_id = cliente.get(
            "situacion_administrativa_id"
        )

        situacion_administrativa_autocomplete.set_value(
            (
                situation_label_by_id.get(
                    int(situation_id)
                )
                if situation_id
                else ""
            ),
            update=False,
        )

        current_authorization = (
            get_current_authorization(
                cliente["id"]
            )
        )

        current_authorization_id = (
            current_authorization.get(
                "tipo_autorizacion_id"
            )
            if current_authorization
            else None
        )

        refresh_authorization_options(
            current_authorization_id
        )

        autorizacion_vigente_desde.value = (
            fecha_a_display(
                current_authorization.get(
                    "fecha_vigencia_desde"
                )
            )
            if current_authorization
            else ""
        )

        autorizacion_vigente_hasta.value = (
            fecha_a_display(
                current_authorization.get(
                    "fecha_vigencia_hasta"
                )
            )
            if current_authorization
            else ""
        )

        fecha_inicio_residencia_legal.value = fecha_a_display(
            cliente.get(
                "fecha_inicio_residencia_legal"
            )
        )

        fecha_inicio_residencia_legal_aproximada.value = bool(
            cliente.get(
                "fecha_inicio_residencia_legal_aproximada"
            )
        )

        continuidad_residencia_legal_autocomplete.set_value(
            cliente.get(
                "continuidad_residencia_legal"
            )
            or "",
            update=False,
        )

        estado_verificacion_residencia_legal_autocomplete.set_value(
            cliente.get(
                "estado_verificacion_residencia_legal"
            )
            or "",
            update=False,
        )

        fecha_verificacion_residencia_legal.value = (
            fecha_a_display(
                cliente.get(
                    "fecha_verificacion_residencia_legal"
                )
            )
        )

        origen_residencia_legal_autocomplete.set_value(
            cliente.get(
                "origen_residencia_legal"
            )
            or "",
            update=False,
        )

        observaciones_residencia_legal.value = (
            cliente.get(
                "observaciones_residencia_legal"
            )
            or ""
        )

        actualizar_antiguedad_residencia_legal()

        fecha_caducidad_residencia.value = fecha_a_display(
            cliente.get("fecha_caducidad_residencia")
        )
        nacionalidad_autocomplete.set_value(cliente.get("nacionalidad") or "", update=False)
        fecha_nacimiento.value = fecha_a_display(cliente.get("fecha_nacimiento"))
        telefono.value = cliente.get("telefono") or ""
        email.value = cliente.get("email") or ""
        estado_cliente.value = cliente.get("estado_cliente") or "Asesoramiento inicial"

        tipo, via, numero, piso_value = descomponer_domicilio(cliente.get("domicilio_espana"))
        set_dropdown_options(tipo_via, tipo_via_options, cliente.get("tipo_via") or tipo)
        nombre_via.value = cliente.get("nombre_via") or via
        numero_via.value = cliente.get("numero") or numero
        piso.value = cliente.get("piso") or piso_value
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
        hubspot_import_data["hubspot_id"] = cliente.get("hubspot_id") or ""
        hubspot_import_data["hubspot_url"] = cliente.get("hubspot_url") or ""
        hubspot_import_data["hubspot_imported_at"] = cliente.get("hubspot_imported_at") or ""
        clear_message()

    def datos_formulario():
        return {
            "nombre": nombre.value,
            "primer_apellido": primer_apellido.value,
            "segundo_apellido": segundo_apellido.value,
            "nie": nie.value,
            "pasaporte": pasaporte.value,
            "dni": dni.value,
            "numero_soporte_nie":
                numero_soporte_nie.value,
            "localizacion_actual": {
                "EN ESPAÑA": "EN_ESPANA",
                "EN PAÍS DE ORIGEN": "EN_ORIGEN",
                "EN OTRO PAÍS": "EN_OTRO_PAIS",
                "DESCONOCIDA": "DESCONOCIDA",
            }.get(
                localizacion_actual_autocomplete.get_value(),
                localizacion_actual_autocomplete.get_value(),
            ),
            "pais_localizacion_actual":
                pais_localizacion_actual_autocomplete.get_value(),
            "fecha_entrada_espana": fecha_a_sql(
                fecha_entrada_espana.value
            ),
            "fecha_entrada_espana_aproximada":
                bool(
                    fecha_entrada_espana_aproximada.value
                ),
            "situacion_administrativa_id": (
                situation_by_label.get(
                    situacion_administrativa_autocomplete.get_value()
                    or "",
                    {},
                ).get("id")
            ),
            "tipo_autorizacion_id": (
                authorization_by_label.get(
                    autorizacion_vigente_autocomplete.get_value()
                    or "",
                    {},
                ).get("id")
            ),
            "autorizacion_vigente_desde":
                fecha_a_sql(
                    autorizacion_vigente_desde.value
                ),
            "autorizacion_vigente_hasta":
                fecha_a_sql(
                    autorizacion_vigente_hasta.value
                ),
            "fecha_inicio_residencia_legal":
                fecha_a_sql(
                    fecha_inicio_residencia_legal.value
                ),
            "fecha_inicio_residencia_legal_aproximada":
                bool(
                    fecha_inicio_residencia_legal_aproximada.value
                ),
            "continuidad_residencia_legal":
                continuidad_residencia_legal_autocomplete.get_value(),
            "estado_verificacion_residencia_legal":
                (
                    estado_verificacion_residencia_legal_autocomplete
                    .get_value()
                ),
            "fecha_verificacion_residencia_legal":
                fecha_a_sql(
                    fecha_verificacion_residencia_legal.value
                ),
            "origen_residencia_legal":
                origen_residencia_legal_autocomplete.get_value(),
            "observaciones_residencia_legal":
                observaciones_residencia_legal.value,
            "fecha_caducidad_residencia": fecha_a_sql(
                fecha_caducidad_residencia.value
            ),
            "nacionalidad": nacionalidad_autocomplete.get_value(),
            "fecha_nacimiento": fecha_a_sql(fecha_nacimiento.value),
            "telefono": telefono.value,
            "email": email.value,
            "hubspot_id": hubspot_import_data.get("hubspot_id") or "",
            "hubspot_url": hubspot_import_data.get("hubspot_url") or "",
            "hubspot_imported_at": hubspot_import_data.get("hubspot_imported_at") or "",
            "estado_cliente": estado_cliente.value,
            "tipo_via": tipo_via.value,
            "nombre_via": nombre_via.value,
            "numero": numero_via.value,
            "piso": piso.value,
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
        if (
            fecha_entrada_espana.value
            and not fecha_a_sql(
                fecha_entrada_espana.value
            )
        ):
            errores.append(
                "La fecha de entrada en España debe "
                "tener formato DD/MM/AAAA"
            )

        if (
            autorizacion_vigente_desde.value
            and not fecha_a_sql(
                autorizacion_vigente_desde.value
            )
        ):
            errores.append(
                "La fecha de inicio de la autorización "
                "debe tener formato DD/MM/AAAA"
            )

        if (
            autorizacion_vigente_hasta.value
            and not fecha_a_sql(
                autorizacion_vigente_hasta.value
            )
        ):
            errores.append(
                "La fecha final de la autorización "
                "debe tener formato DD/MM/AAAA"
            )

        if (
            autorizacion_vigente_autocomplete.get_value()
            and not (
                situacion_administrativa_autocomplete
                .get_value()
            )
        ):
            errores.append(
                "Selecciona la situación administrativa "
                "de la autorización"
            )

        if (
            fecha_inicio_residencia_legal.value
            and not fecha_a_sql(
                fecha_inicio_residencia_legal.value
            )
        ):
            errores.append(
                "El inicio de residencia legal debe "
                "tener formato DD/MM/AAAA"
            )

        if (
            fecha_verificacion_residencia_legal.value
            and not fecha_a_sql(
                fecha_verificacion_residencia_legal.value
            )
        ):
            errores.append(
                "La fecha de verificación debe "
                "tener formato DD/MM/AAAA"
            )

        inicio_residencia_sql = fecha_a_sql(
            fecha_inicio_residencia_legal.value
        )

        if (
            inicio_residencia_sql
            and inicio_residencia_sql
            > __import__("datetime").date.today().isoformat()
        ):
            errores.append(
                "El inicio de residencia legal "
                "no puede ser una fecha futura"
            )

        if (
            fecha_caducidad_residencia.value
            and not fecha_a_sql(
                fecha_caducidad_residencia.value
            )
        ):
            errores.append(
                "La caducidad NIE/TIE debe tener "
                "formato DD/MM/AAAA"
            )
        return errores

    def cerrar_dialogo(e=None):
        cliente_dialog.open = False
        page.update()

    def format_duplicate_warning(duplicates):
        lines = ["Posible cliente duplicado. Revisa antes de guardar:"]
        for item in duplicates:
            motivos = ", ".join(item.get("motivos") or [])
            nombre_cliente = item.get("nombre") or f"Cliente #{item.get('id')}"
            lines.append(f"- #{item.get('id')} {nombre_cliente} ({motivos})")
            details = []
            if item.get("nie"):
                details.append(f"NIE: {item.get('nie')}")
            if item.get("pasaporte"):
                details.append(f"Pasaporte: {item.get('pasaporte')}")
            if item.get("email"):
                details.append(f"Email: {item.get('email')}")
            if item.get("hubspot_id"):
                details.append(f"HubSpot ID: {item.get('hubspot_id')}")
            if details:
                lines.append("  " + " | ".join(details))
        return "\n".join(lines)

    def guardar_cliente(e):
        creating_new_client = (
            state.get(
                "editing_id"
            )
            in (
                None,
                "",
            )
        )

        errores = validar_formulario()
        if errores:
            show_message(error_alert("\n".join(errores)))
            return
        data = datos_formulario()

        previous_phone = str(
            state.get(
                "editing_original_phone"
            )
            or ""
        ).strip()

        new_phone = str(
            data.get(
                "telefono"
            )
            or ""
        ).strip()

        phone_changed = bool(
            not creating_new_client
            and new_phone
            and previous_phone
            != new_phone
        )

        if state["editing_id"]:
            client_id = int(
                state["editing_id"]
            )

            update_client(
                client_id,
                data,
            )
        else:
            duplicates = find_client_duplicates(data)

            if duplicates:
                show_message(
                    error_alert(
                        format_duplicate_warning(
                            duplicates
                        )
                    )
                )
                return

            client_id = create_client(data)

        situation_id = data.get(
            "situacion_administrativa_id"
        )

        authorization_type_id = data.get(
            "tipo_autorizacion_id"
        )

        if (
            client_id
            and situation_id
            and authorization_type_id
        ):
            current = get_current_authorization(
                client_id
            )

            authorization_data = {
                "situacion_administrativa_id":
                    situation_id,
                "tipo_autorizacion_id":
                    authorization_type_id,
                "estado_autorizacion":
                    "VIGENTE",
                "fecha_vigencia_desde":
                    data.get(
                        "autorizacion_vigente_desde"
                    ),
                "fecha_vigencia_hasta":
                    data.get(
                        "autorizacion_vigente_hasta"
                    ),
                "motivo_inicio":
                    "Registro desde ficha de cliente",
            }

            same_current = bool(
                current
                and int(
                    current.get(
                        "situacion_administrativa_id"
                    )
                    or 0
                ) == int(situation_id)
                and int(
                    current.get(
                        "tipo_autorizacion_id"
                    )
                    or 0
                ) == int(authorization_type_id)
            )

            if same_current:
                update_current_authorization_details(
                    client_id,
                    authorization_data,
                )
            else:
                set_current_authorization(
                    client_id,
                    authorization_data,
                    usuario="FICHA_CLIENTE",
                )

        cerrar_dialogo()

        if (
            creating_new_client
            and client_id
            and callable(
                on_client_created
            )
        ):
            on_client_created(
                int(
                    client_id
                )
            )
            return

        cargar_clientes()
        show_client_list()

        if (
            phone_changed
            and client_id
            and callable(
                on_client_phone_changed
            )
        ):
            display_name = " ".join(
                part
                for part in (
                    str(
                        data.get("nombre")
                        or ""
                    ).strip(),
                    str(
                        data.get("primer_apellido")
                        or ""
                    ).strip(),
                    str(
                        data.get("segundo_apellido")
                        or ""
                    ).strip(),
                )
                if part
            ).strip()

            _open_phone_change_dialog(
                client_id=int(
                    client_id
                ),
                previous_phone=(
                    previous_phone
                ),
                new_phone=(
                    new_phone
                ),
                display_name=(
                    display_name
                    or new_phone
                ),
            )

    def set_hubspot_message(control):
        hubspot_message.controls.clear()
        hubspot_message.controls.append(control)
        hubspot_message.visible = True
        page.update()

    def clear_hubspot_message():
        hubspot_message.controls.clear()
        hubspot_message.visible = False

    def aplicar_datos_hubspot(data):
        from datetime import datetime

        hubspot_import_data["hubspot_id"] = data.get("hubspot_id") or ""
        hubspot_import_data["hubspot_url"] = data.get("hubspot_url") or ""
        hubspot_import_data["hubspot_imported_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        nombre.value = data.get("nombre") or nombre.value
        primer_apellido.value = data.get("primer_apellido") or primer_apellido.value
        segundo_apellido.value = data.get("segundo_apellido") or segundo_apellido.value
        nie.value = data.get("nie") or nie.value
        pasaporte.value = data.get("pasaporte") or pasaporte.value
        dni.value = data.get("dni") or dni.value
        fecha_nacimiento.value = data.get("fecha_nacimiento") or fecha_nacimiento.value
        telefono.value = data.get("telefono") or telefono.value
        email.value = data.get("email") or email.value

        nacionalidad_autocomplete.set_value(data.get("nacionalidad") or nacionalidad_autocomplete.get_value(), update=False)
        pais_nacimiento_autocomplete.set_value(data.get("pais_nacimiento") or pais_nacimiento_autocomplete.get_value(), update=False)

        provincia_value = data.get("provincia") or provincia_autocomplete.get_value()
        provincia_autocomplete.set_value(provincia_value, update=False)

        try:
            localidades = get_localidades_by_provincia(provincia_value) if provincia_value else []
        except Exception:
            localidades = []

        localidad_autocomplete.set_options(localidades, clear_value=False)
        localidad_autocomplete.input.label = f"Localidad ({len(localidades)})" if localidades else "Localidad"
        localidad_autocomplete.set_value(data.get("localidad") or localidad_autocomplete.get_value(), update=False)

        nombre_via.value = data.get("nombre_via") or nombre_via.value
        numero_via.value = data.get("numero") or numero_via.value
        piso.value = data.get("piso") or piso.value
        codigo_postal.value = data.get("codigo_postal") or codigo_postal.value
        localidad_nacimiento.value = data.get("localidad_nacimiento") or localidad_nacimiento.value
        nombre_padre.value = data.get("nombre_padre") or nombre_padre.value
        nombre_madre.value = data.get("nombre_madre") or nombre_madre.value

        if data.get("estado_civil"):
            set_dropdown_options(estado_civil, estado_civil_options, data.get("estado_civil"))

        if data.get("sexo"):
            set_dropdown_options(sexo, ["HOMBRE", "MUJER", "X"], data.get("sexo"))

        extra_lines = []
        if data.get("hubspot_id"):
            extra_lines.append(f"HubSpot ID: {data.get('hubspot_id')}")
        if data.get("hubspot_url"):
            extra_lines.append(f"HubSpot URL: {data.get('hubspot_url')}")
        if data.get("tramite_hubspot"):
            extra_lines.append(f"Trámite HubSpot: {data.get('tramite_hubspot')}")
        if data.get("importe_deuda_hubspot"):
            extra_lines.append(f"Importe deuda HubSpot: {data.get('importe_deuda_hubspot')}")

        if extra_lines:
            current = (observaciones_internas.value or "").strip()
            addition = "\n".join(extra_lines)
            observaciones_internas.value = f"{current}\n{addition}".strip() if current else addition

        clear_message()
        show_message(success_alert("Datos importados desde HubSpot. Revisa la ficha antes de guardar."))

    def consultar_hubspot_contacto(e=None):
        clear_hubspot_message()
        try:
            data = preview_contact_import(hubspot_url_input.value)
        except HubSpotImportError as exc:
            set_hubspot_message(error_alert(str(exc)))
            return
        except Exception as exc:
            set_hubspot_message(error_alert(f"Error importando desde HubSpot: {exc}"))
            return

        aplicar_datos_hubspot(data)
        hubspot_dialog.open = False
        page.update()

    def abrir_importar_hubspot(e=None):
        hubspot_url_input.value = ""
        clear_hubspot_message()
        hubspot_dialog.open = True
        page.update()

    def _close_phone_change_dialog(
        e=None,
    ):
        state[
            "pending_phone_change"
        ] = None

        phone_change_dialog.open = False

        try:
            page.update()
        except Exception:
            pass


    def _confirm_phone_change_whatsapp(
        e=None,
    ):
        pending = (
            state.get(
                "pending_phone_change"
            )
            or {}
        )

        if not pending:
            return False

        try:
            result = (
                on_client_phone_changed(
                    int(
                        pending[
                            "client_id"
                        ]
                    ),
                    pending.get(
                        "previous_phone"
                    ),
                    pending.get(
                        "new_phone"
                    ),
                    pending.get(
                        "display_name"
                    ),
                )
            )

            normalized_phone = str(
                (
                    result.get(
                        "phone"
                    )
                    if isinstance(
                        result,
                        dict,
                    )
                    else None
                )
                or pending.get(
                    "new_phone"
                )
                or ""
            ).strip()

            _close_phone_change_dialog()

            show_snackbar(
                page,
                (
                    "Nuevo teléfono añadido y "
                    "vinculado a WhatsApp: "
                    f"{normalized_phone}"
                ),
                severity="success",
            )

            return True

        except Exception as exc:
            show_snackbar(
                page,
                (
                    "No se pudo añadir el nuevo "
                    "teléfono a WhatsApp: "
                    f"{exc}"
                ),
                severity="error",
            )

            return False


    def _open_phone_change_dialog(
        *,
        client_id,
        previous_phone,
        new_phone,
        display_name,
    ):
        state[
            "pending_phone_change"
        ] = {
            "client_id":
                int(client_id),
            "previous_phone":
                previous_phone,
            "new_phone":
                new_phone,
            "display_name":
                display_name,
        }

        phone_change_summary.value = (
            "Has cambiado el teléfono del cliente.\n\n"
            f"Anterior: {previous_phone or 'Sin teléfono'}\n"
            f"Nuevo: {new_phone}\n\n"
            "La conversación anterior se conservará "
            "como histórico. Puedes añadir ahora el "
            "nuevo número a WhatsApp."
        )

        phone_change_dialog.open = True

        try:
            page.update()
        except Exception:
            pass


    phone_change_summary = ft.Text(
        "",
        size=12,
    )

    phone_change_dialog = form_dialog(
        "Nuevo teléfono del cliente",
        ft.Column(
            controls=[
                phone_change_summary,
            ],
            tight=True,
            spacing=10,
            width=420,
        ),
        [
            secondary_button(
                "Ahora no",
                _close_phone_change_dialog,
            ),
            primary_button(
                "Añadir a WhatsApp",
                _confirm_phone_change_whatsapp,
            ),
        ],
    )

    page.overlay.append(
        phone_change_dialog
    )


    cliente_dialog = form_dialog(
        "Cliente",
        ft.Column(
            controls=[
                ft.Text("Datos básicos", size=16, weight=ft.FontWeight.BOLD, color="#003B7A"),
                ft.Row([nombre, primer_apellido, segundo_apellido], wrap=True, spacing=10),
                ft.Row(
                    [
                        nie,
                        pasaporte,
                        dni,
                        fecha_caducidad_residencia,
                    ],
                    wrap=True,
                    spacing=10,
                ),
                ft.Row([nacionalidad_autocomplete.control, fecha_nacimiento, telefono], wrap=True, spacing=10),
                ft.Row([email, estado_cliente], wrap=True, spacing=10),

                ft.Text(
                    "Situación administrativa",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color="#003B7A",
                ),

                ft.Row(
                    [
                        numero_soporte_nie,
                        localizacion_actual_autocomplete.control,
                        pais_localizacion_actual_autocomplete.control,
                    ],
                    wrap=True,
                    spacing=10,
                ),

                ft.Row(
                    [
                        fecha_entrada_espana,
                        fecha_entrada_espana_aproximada,
                        situacion_administrativa_autocomplete.control,
                    ],
                    wrap=True,
                    spacing=10,
                ),

                ft.Row(
                    [
                        autorizacion_vigente_autocomplete.control,
                    ],
                    wrap=True,
                    spacing=10,
                ),

                ft.Row(
                    [
                        autorizacion_vigente_desde,
                        autorizacion_vigente_hasta,
                    ],
                    wrap=True,
                    spacing=10,
                ),

                ft.Divider(height=12),

                ft.Text(
                    "Residencia legal computable para nacionalidad",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color="#003B7A",
                ),

                ft.Row(
                    [
                        fecha_inicio_residencia_legal,
                        fecha_inicio_residencia_legal_aproximada,
                        continuidad_residencia_legal_autocomplete.control,
                    ],
                    wrap=True,
                    spacing=10,
                ),

                ft.Row(
                    [
                        estado_verificacion_residencia_legal_autocomplete.control,
                        fecha_verificacion_residencia_legal,
                        origen_residencia_legal_autocomplete.control,
                    ],
                    wrap=True,
                    spacing=10,
                ),

                antiguedad_residencia_legal,

                observaciones_residencia_legal,

                ft.Text(
                    "Esta fecha permite valorar inicialmente "
                    "la nacionalidad aunque todavía no se haya "
                    "reconstruido toda la trayectoria administrativa. "
                    "La continuidad debe verificarse documentalmente.",
                    size=12,
                    color="#64748B",
                ),

                ft.Text(
                    "La autorización describe el título "
                    "administrativo actual del cliente. "
                    "Por ejemplo: autorización de residencia "
                    "temporal por reagrupación familiar.",
                    size=12,
                    color="#64748B",
                ),

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
        actions=[
            secondary_button("Importar HubSpot", abrir_importar_hubspot),
            secondary_button("Cancelar", cerrar_dialogo),
            primary_button("Guardar", guardar_cliente),
        ],
    )

    hubspot_dialog = form_dialog(
        "Importar cliente desde HubSpot",
        ft.Column(
            controls=[
                ft.Text(
                    "Pega la URL o el ID del contacto de HubSpot. Se rellenarán los campos del formulario, pero no se guardará automáticamente.",
                    size=13,
                    color="#64748B",
                ),
                hubspot_url_input,
                hubspot_message,
            ],
            spacing=12,
            width=720,
        ),
        actions=[
            secondary_button("Cancelar", lambda e: setattr(hubspot_dialog, "open", False) or page.update()),
            primary_button("Consultar y volcar datos", consultar_hubspot_contacto),
        ],
    )

    page.overlay.append(cliente_dialog)
    page.overlay.append(hubspot_dialog)

    def get_expedientes_priorizados_cliente(cliente):
        cliente_id = cliente.get("id")

        if not cliente_id:
            return []

        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row

            if not db_table_exists(conn, "expedientes"):
                conn.close()
                return []

            has_prioridades = db_table_exists(conn, "config_prioridades")

            if has_prioridades:
                sql = """
                    SELECT
                        e.id,
                        e.numero_expediente,
                        e.estado_presentacion,
                        e.fecha_apertura,
                        e.fecha_presentacion,
                        e.created_at,
                        e.updated_at,
                        te.nombre AS tipo_expediente,
                        ed.nombre AS estado_documental,
                        ea.nombre AS estado_administrativo,
                        cp.nombre AS prioridad,
                        COALESCE(cp.orden, 999) AS prioridad_orden
                    FROM expedientes e
                    LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
                    LEFT JOIN config_estados_documentales ed ON ed.id = e.estado_documental_id
                    LEFT JOIN config_estados_administrativos ea ON ea.id = e.estado_administrativo_id
                    LEFT JOIN config_prioridades cp ON cp.id = e.prioridad_id
                    WHERE e.cliente_id = ?
                      AND COALESCE(e.activo, 1) = 1
                    ORDER BY
                        COALESCE(cp.orden, 999) ASC,
                        COALESCE(e.updated_at, e.created_at) DESC,
                        e.id DESC
                """
            else:
                sql = """
                    SELECT
                        e.id,
                        e.numero_expediente,
                        e.estado_presentacion,
                        e.fecha_apertura,
                        e.fecha_presentacion,
                        e.created_at,
                        e.updated_at,
                        te.nombre AS tipo_expediente,
                        ed.nombre AS estado_documental,
                        ea.nombre AS estado_administrativo,
                        '' AS prioridad,
                        999 AS prioridad_orden
                    FROM expedientes e
                    LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
                    LEFT JOIN config_estados_documentales ed ON ed.id = e.estado_documental_id
                    LEFT JOIN config_estados_administrativos ea ON ea.id = e.estado_administrativo_id
                    WHERE e.cliente_id = ?
                      AND COALESCE(e.activo, 1) = 1
                    ORDER BY
                        COALESCE(e.updated_at, e.created_at) DESC,
                        e.id DESC
                """

            rows = conn.execute(sql, (int(cliente_id),)).fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except Exception:
            return []

    def resolver_estado_cliente(cliente):
        expedientes = cliente.get("_expedientes_cliente") or []

        if not expedientes:
            return cliente.get("estado_cliente") or "Asesoramiento inicial"

        principal = expedientes[0]
        estado = (
            principal.get("estado_administrativo")
            or principal.get("estado_presentacion")
            or principal.get("estado_documental")
        )

        return estado or cliente.get("estado_cliente") or "Asesoramiento inicial"

    def cargar_clientes():
        clientes = get_all_clients()

        for cliente in clientes:
            cliente["_expedientes_cliente"] = get_expedientes_priorizados_cliente(cliente)
            try:
                deuda_base = get_deuda_cliente(cliente["id"])
            except Exception:
                deuda_base = {
                    "importe_hojas": 0.0,
                    "importe_cobros": 0.0,
                    "deuda_total": 0.0,
                    "tramites": [],
                }

            cliente["_deuda_cliente"] = recalcular_deuda_cliente_sobre_bruto(cliente["id"], deuda_base)
            cliente["estado_cliente"] = resolver_estado_economico_cliente(cliente)

        state["clients"] = clientes


    def get_estados_administrativos_disponibles():
        estados = []

        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row

            if db_table_exists(conn, "config_estados_administrativos"):
                rows = conn.execute(
                    """
                    SELECT nombre
                    FROM config_estados_administrativos
                    ORDER BY nombre
                    """
                ).fetchall()

                estados = [
                    (title_filter_label(row["nombre"]), f"estado::{row['nombre']}")
                    for row in rows
                    if row["nombre"]
                    and normalize_filter_label(row["nombre"]) not in EXCLUDED_QUICK_FILTER_STATES
                ]

            conn.close()

        except Exception:
            pass

        return estados

    def cliente_tiene_pagos_vencidos(cliente):
        cliente_id = cliente.get("id")

        if not cliente_id:
            return False

        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row

            if not db_table_exists(conn, "eco_cobros"):
                conn.close()
                return False

            row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM eco_cobros
                WHERE cliente_id = ?
                  AND COALESCE(activo, 1) = 1
                  AND (
                        LOWER(COALESCE(estado, '')) LIKE '%vencido%'
                     OR LOWER(COALESCE(estado_cobro, '')) LIKE '%vencido%'
                     OR LOWER(COALESCE(estado_conciliacion, '')) LIKE '%vencido%'
                  )
                """,
                (int(cliente_id),),
            ).fetchone()

            conn.close()

            return bool(row and int(row["total"] or 0) > 0)

        except Exception:
            return False

    def pasa_quick_filter(cliente):
        qf = state["quick_filter"]
        estado = (cliente.get("estado_cliente") or "").strip()

        if qf == "todos":
            return True

        if qf == "morosos":
            return (cliente.get("estado_cliente") or "").strip().upper() == "MOROSO"

        if qf == "al_dia":
            return (cliente.get("estado_cliente") or "").strip().upper() == "AL DÍA"

        if qf == "sin_documento":
            return not documento_cliente(cliente)

        if qf == "ficha_incompleta":
            return porcentaje_ficha(cliente) < 80

        if qf == "pagos_vencidos":
            return cliente_tiene_pagos_vencidos(cliente)

        if qf == "varios_tramites":
            return cliente_tiene_varios_tramites_en_proceso(cliente)

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
        documento = documento_cliente(cliente) or "Sin documento"

        expedientes = (
            cliente.get("_expedientes_cliente")
            or get_context_expedientes(cliente)
        )

        deuda_total = cliente_deuda_total(cliente)

        telefono = cliente.get("telefono") or "Sin teléfono"
        email = cliente.get("email") or "Sin email"
        nacionalidad = cliente.get("nacionalidad") or "Sin nacionalidad"

        edad = (
            calcular_edad(
                cliente.get("fecha_nacimiento")
            )
            or "-"
        )

        localidad = cliente.get("localidad") or ""
        provincia = cliente.get("provincia") or ""

        ubicacion = ", ".join(
            part.upper()
            for part in [localidad, provincia]
            if part
        ) or "Sin ubicación"

        fecha_alta = (
            fecha_a_display(
                cliente.get("fecha_alta")
            )
            or cliente.get("fecha_alta")
            or "-"
        )

        edit_btn = primary_button(
            "Editar cliente",
            lambda e, c=cliente:
                abrir_editar_cliente(c),
        )
        edit_btn.width = 310

        expediente_btn = secondary_button(
            "Crear expediente",
            lambda e, cid=cliente["id"]:
                crear_expediente_desde_cliente(cid),
        )
        expediente_btn.width = 310
        expediente_btn.disabled = not bool(
            on_create_expediente
        )

        ficha_btn = secondary_button(
            "Ver ficha completa",
            ver_ficha_contextual,
        )
        ficha_btn.width = 310

        return ft.Container(
            width=360,
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                "#D9E3F0",
            ),
            border_radius=18,
            padding=20,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                width=72,
                                height=72,
                                border_radius=36,
                                bgcolor="#EAF3FF",
                                alignment=ft.Alignment.CENTER,
                                content=ft.Text(
                                    client_initials(cliente),
                                    size=25,
                                    weight=ft.FontWeight.BOLD,
                                    color="#0057B8",
                                ),
                            ),
                            ft.Container(expand=True),
                            client_action_menu(cliente),
                        ],
                        vertical_alignment=(
                            ft.CrossAxisAlignment.START
                        ),
                    ),

                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text(
                                    "Cliente activo",
                                    size=10,
                                    weight=ft.FontWeight.W_600,
                                    color="#027A48",
                                ),
                                bgcolor="#ECFDF3",
                                border_radius=14,
                                padding=ft.padding.symmetric(
                                    horizontal=10,
                                    vertical=5,
                                ),
                            ),
                        ],
                    ),

                    ft.Text(
                        nombre.upper(),
                        size=17,
                        weight=ft.FontWeight.BOLD,
                        color="#102A56",
                    ),

                    ft.Text(
                        documento,
                        size=12,
                        color="#667085",
                    ),

                    ft.Container(height=4),

                    ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.PHONE_OUTLINED,
                                size=16,
                                color="#486581",
                            ),
                            ft.Text(
                                telefono,
                                size=12,
                                color="#344054",
                                selectable=True,
                            ),
                        ],
                        spacing=10,
                    ),

                    ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.EMAIL_OUTLINED,
                                size=16,
                                color="#486581",
                            ),
                            ft.Text(
                                email,
                                size=12,
                                color="#344054",
                                selectable=True,
                            ),
                        ],
                        spacing=10,
                    ),

                    ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.LOCATION_ON_OUTLINED,
                                size=16,
                                color="#486581",
                            ),
                            ft.Text(
                                ubicacion,
                                size=12,
                                color="#344054",
                            ),
                        ],
                        spacing=10,
                    ),

                    ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.PUBLIC,
                                size=16,
                                color="#486581",
                            ),
                            ft.Text(
                                nacionalidad.upper(),
                                size=12,
                                color="#344054",
                            ),
                        ],
                        spacing=10,
                    ),

                    ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.PERSON_OUTLINE,
                                size=16,
                                color="#486581",
                            ),
                            ft.Text(
                                f"Edad: {edad} años",
                                size=12,
                                color="#344054",
                            ),
                        ],
                        spacing=10,
                    ),

                    ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.CALENDAR_MONTH_OUTLINED,
                                size=16,
                                color="#486581",
                            ),
                            ft.Text(
                                f"Alta: {fecha_alta}",
                                size=12,
                                color="#344054",
                            ),
                        ],
                        spacing=10,
                    ),

                    ft.Divider(
                        height=22,
                        color="#E4E7EC",
                    ),

                    ft.Row(
                        controls=[
                            ft.Container(
                                expand=True,
                                padding=14,
                                bgcolor="#FAFCFF",
                                border=ft.border.all(
                                    1,
                                    "#E3EAF3",
                                ),
                                border_radius=12,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(
                                            "Importe a deber",
                                            size=11,
                                            weight=ft.FontWeight.W_600,
                                            color="#475467",
                                        ),
                                        ft.Text(
                                            money_display(
                                                deuda_total
                                            ),
                                            size=18,
                                            weight=ft.FontWeight.BOLD,
                                            color=(
                                                "#027A48"
                                                if deuda_total <= 0
                                                else "#B42318"
                                            ),
                                        ),
                                        ft.Text(
                                            (
                                                "Sin deuda"
                                                if deuda_total <= 0
                                                else "Pendiente"
                                            ),
                                            size=10,
                                            color="#667085",
                                        ),
                                    ],
                                    spacing=3,
                                ),
                            ),

                            ft.Container(
                                expand=True,
                                padding=14,
                                bgcolor="#FAFCFF",
                                border=ft.border.all(
                                    1,
                                    "#E3EAF3",
                                ),
                                border_radius=12,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(
                                            "Expedientes activos",
                                            size=11,
                                            weight=ft.FontWeight.W_600,
                                            color="#475467",
                                        ),
                                        ft.Text(
                                            str(len(expedientes)),
                                            size=18,
                                            weight=ft.FontWeight.BOLD,
                                            color="#0057B8",
                                        ),
                                        ft.Text(
                                            "Expedientes",
                                            size=10,
                                            color="#667085",
                                        ),
                                    ],
                                    spacing=3,
                                ),
                            ),
                        ],
                        spacing=10,
                    ),

                    ft.Container(
                        padding=14,
                        bgcolor="#FFFFFF",
                        border=ft.border.all(
                            1,
                            "#E3EAF3",
                        ),
                        border_radius=12,
                        content=ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text(
                                            "Ficha de cliente",
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                            color="#102A56",
                                            expand=True,
                                        ),
                                        ft.Text(
                                            f"{ficha_pct}%",
                                            size=13,
                                            weight=ft.FontWeight.BOLD,
                                            color="#027A48",
                                        ),
                                    ],
                                ),
                                ft.Text(
                                    "Completitud del perfil",
                                    size=10,
                                    color="#667085",
                                ),
                                ft.ProgressBar(
                                    value=ficha_pct / 100,
                                    height=6,
                                    color="#12B76A",
                                    bgcolor="#EAECF0",
                                    border_radius=6,
                                ),
                            ],
                            spacing=7,
                        ),
                    ),

                    ft.Container(
                        padding=14,
                        border=ft.border.all(
                            1,
                            "#E3EAF3",
                        ),
                        border_radius=12,
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    "Etiquetas",
                                    size=12,
                                    weight=ft.FontWeight.BOLD,
                                    color="#102A56",
                                ),
                                ft.Row(
                                    controls=[
                                        estado_cliente_priorizado_badge(
                                            cliente
                                        ),
                                        deuda_tramites_cell(
                                            cliente
                                        ),
                                    ],
                                    spacing=7,
                                    wrap=True,
                                ),
                            ],
                            spacing=9,
                        ),
                    ),

                    ft.Text(
                        "Acciones rápidas",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color="#102A56",
                    ),

                    edit_btn,
                    expediente_btn,
                    ficha_btn,

                    ft.Divider(
                        height=18,
                        color="#E4E7EC",
                    ),

                    ft.Text(
                        (
                            "Sistema de gestión de clientes · "
                            "Quesada Abogados"
                        ),
                        size=9,
                        color="#98A2B3",
                    ),
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
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
    def crear_expediente_desde_cliente(cliente_id):
        if not on_create_expediente:
            show_message(error_alert("No hay navegacion configurada para crear expediente desde cliente."))
            return

        on_create_expediente(cliente_id)

    def crear_expediente_cliente_seleccionado(e=None):
        clientes = selected_clients()
        if len(clientes) != 1:
            show_message(error_alert("Selecciona un unico cliente para crear expediente."))
            return

        crear_expediente_desde_cliente(clientes[0]["id"])

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

    def quick_filter_count(key):
        previous = state["quick_filter"]

        try:
            state["quick_filter"] = key

            return sum(
                1
                for cliente in state["clients"]
                if pasa_quick_filter(cliente)
            )
        finally:
            state["quick_filter"] = previous


    def build_quick_filter_chip(label, key):
        selected = state["quick_filter"] == key
        bg, fg, border_color = quick_filter_colors(key)

        selected_bg = (
            "#0057B8"
            if key == "todos"
            else fg
        )

        return ft.Container(
            height=34,
            padding=ft.padding.symmetric(
                horizontal=13,
                vertical=6,
            ),
            bgcolor=(
                selected_bg
                if selected
                else bg
            ),
            border=ft.border.all(
                1,
                selected_bg
                if selected
                else border_color,
            ),
            border_radius=17,
            ink=True,
            on_click=lambda e, k=key:
                set_quick_filter(k),
            content=ft.Row(
                controls=[
                    ft.Text(
                        title_filter_label(label),
                        size=11,
                        weight=(
                            ft.FontWeight.W_600
                            if selected
                            else ft.FontWeight.W_500
                        ),
                        color=(
                            "#FFFFFF"
                            if selected
                            else fg
                        ),
                    ),
                    ft.Container(
                        width=22,
                        height=20,
                        border_radius=10,
                        alignment=ft.Alignment.CENTER,
                        bgcolor=(
                            "#FFFFFF22"
                            if selected
                            else "#FFFFFF"
                        ),
                        content=ft.Text(
                            str(
                                quick_filter_count(
                                    key
                                )
                            ),
                            size=9,
                            weight=ft.FontWeight.BOLD,
                            color=(
                                "#FFFFFF"
                                if selected
                                else fg
                            ),
                        ),
                    ),
                ],
                spacing=5,
                tight=True,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )

    def refresh_quick_filters():
        quick_filters_container.controls.clear()

        for label, key in QUICK_FILTERS:
            quick_filters_container.controls.append(build_quick_filter_chip(label, key))

    def set_quick_filter(key):
        state["quick_filter"] = key
        state["page"] = 1
        refresh_quick_filters()
        refresh_table()

    def refresh_selection_bar():
        selected_info.value = selected_count_text()

        has_selection = (
            len(state["selected_client_ids"]) > 0
        )

        editar_btn = secondary_button(
            "Editar selección",
            open_bulk_dialog,
        )

        crear_btn = secondary_button(
            "Crear expediente",
            crear_expediente_cliente_seleccionado,
        )

        archivar_btn = danger_button(
            "Archivar selección",
            archivar_seleccionados,
        )

        bulk_actions.disabled = not has_selection
        editar_btn.disabled = not has_selection
        archivar_btn.disabled = not has_selection

        selection_bar.visible = True

        selection_bar.content = ft.Container(
            padding=ft.padding.symmetric(
                horizontal=12,
                vertical=9,
            ),
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                "#DCE5EF",
            ),
            border_radius=12,
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=175,
                        content=selected_info,
                    ),

                    bulk_actions,

                    editar_btn,
                    crear_btn,
                    archivar_btn,
                ],
                spacing=10,
                wrap=True,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
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

    def abrir_nuevo_cliente(
        e=None,
        *,
        defaults=None,
    ):
        limpiar_formulario()

        defaults = (
            defaults
            if isinstance(
                defaults,
                dict,
            )
            else {}
        )

        prefill_name = str(
            defaults.get(
                "nombre"
            )
            or ""
        ).strip()

        prefill_phone = str(
            defaults.get(
                "telefono"
            )
            or ""
        ).strip()

        if prefill_name:
            nombre.value = prefill_name

        if prefill_phone:
            telefono.value = prefill_phone

        cliente_dialog.title = ft.Text(
            "Nuevo cliente"
        )
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

    def ver_ficha(
        cliente,
        *,
        on_back_override=None,
    ):
        content_area.content = client_detail_view(
            page,
            cliente,
            on_back=(
                on_back_override
                or show_client_list
            ),
            on_edit=(
                lambda e, c=cliente:
                    abrir_editar_cliente(c)
            ),
            on_open_expediente=on_open_expediente,
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

    def set_page(page_number):
        state["page"] = max(1, int(page_number or 1))
        table_container.content = build_table()
        refresh_selection_bar()
        refresh_context_panel()
        page.update()

    def client_action_menu(cliente):
        items = [
            ft.PopupMenuItem(
                content=ft.Text("Ver ficha", color="#003B7A", weight=ft.FontWeight.BOLD),
                on_click=lambda e, c=cliente: ver_ficha(c),
            ),
            ft.PopupMenuItem(
                content=ft.Text("Editar", color="#003B7A"),
                on_click=lambda e, c=cliente: abrir_editar_cliente(c),
            ),
        ]

        if on_create_expediente:
            items.append(
                ft.PopupMenuItem(
                    content=ft.Text("Crear expediente", color="#003B7A"),
                    on_click=lambda e, cid=cliente["id"]: crear_expediente_desde_cliente(cid),
                )
            )

        return ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Acciones",
            items=items,
        )

    def build_client_card(cliente, index=0):
        is_selected = (
            cliente["id"]
            in state["selected_client_ids"]
        )

        documento = (
            documento_cliente(cliente)
            or "Sin documento"
        )

        telefono = (
            cliente.get("telefono")
            or "Sin teléfono"
        )

        email = (
            cliente.get("email")
            or "Sin email"
        )

        nacionalidad = (
            cliente.get("nacionalidad")
            or "Sin nacionalidad"
        )

        edad = (
            calcular_edad(
                cliente.get("fecha_nacimiento")
            )
            or "-"
        )

        localidad = (
            cliente.get("localidad")
            or ""
        )

        provincia = (
            cliente.get("provincia")
            or ""
        )

        ubicacion = ", ".join(
            part.upper()
            for part in [localidad, provincia]
            if part
        ) or "Sin ubicación"

        ficha_pct = porcentaje_ficha(cliente)

        deuda = cliente.get(
            "_deuda_cliente"
        ) or {}

        deuda_total = float(
            deuda.get("deuda_total")
            or 0
        )

        checkbox = ft.Checkbox(
            value=is_selected,
            on_change=lambda e, cid=cliente["id"]:
                toggle_client_selection(cid),
        )

        avatar = ft.Container(
            width=56,
            height=56,
            border_radius=28,
            bgcolor=(
                "#E7F0FF"
                if index % 3 == 0
                else
                "#E9F9F0"
                if index % 3 == 1
                else
                "#F2EAFE"
            ),
            alignment=ft.Alignment.CENTER,
            content=ft.Text(
                client_initials(cliente),
                size=20,
                weight=ft.FontWeight.BOLD,
                color=(
                    "#0057B8"
                    if index % 3 == 0
                    else
                    "#079455"
                    if index % 3 == 1
                    else
                    "#7F56D9"
                ),
            ),
        )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                2 if is_selected else 1,
                "#2F80ED"
                if is_selected
                else "#D9E2EC",
            ),
            border_radius=13,
            padding=ft.padding.symmetric(
                horizontal=14,
                vertical=11,
            ),
            shadow=ft.BoxShadow(
                blur_radius=8,
                spread_radius=0,
                color="#102A560A",
                offset=ft.Offset(0, 2),
            ),
            ink=True,
            on_click=lambda e, cid=cliente["id"]:
                toggle_client_selection(cid),
            content=ft.Row(
                controls=[
                    checkbox,

                    avatar,

                    ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        (
                                            nombre_completo(cliente)
                                            or
                                            f"Cliente #{cliente.get('id')}"
                                        ).upper(),
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                        color="#123B73",
                                        expand=True,
                                    ),
                                    client_action_menu(
                                        cliente
                                    ),
                                ],
                                vertical_alignment=(
                                    ft.CrossAxisAlignment.CENTER
                                ),
                            ),

                            ft.Row(
                                controls=[
                                    ft.Text(
                                        f"{documento}",
                                        size=10,
                                        color="#667085",
                                        selectable=True,
                                    ),
                                    ft.Text(
                                        "•",
                                        size=10,
                                        color="#98A2B3",
                                    ),
                                    ft.Text(
                                        telefono,
                                        size=10,
                                        color="#667085",
                                        selectable=True,
                                    ),
                                    ft.Text(
                                        "•",
                                        size=10,
                                        color="#98A2B3",
                                    ),
                                    ft.Text(
                                        email,
                                        size=10,
                                        color="#667085",
                                        selectable=True,
                                    ),
                                ],
                                spacing=8,
                                wrap=True,
                            ),

                            ft.Row(
                                controls=[
                                    ft.Text(
                                        (
                                            "Nacionalidad: "
                                            f"{nacionalidad.upper()}"
                                        ),
                                        size=10,
                                        color="#667085",
                                    ),
                                    ft.Text(
                                        "•",
                                        size=10,
                                        color="#98A2B3",
                                    ),
                                    ft.Text(
                                        f"Edad: {edad}",
                                        size=10,
                                        color="#667085",
                                    ),
                                    ft.Text(
                                        "•",
                                        size=10,
                                        color="#98A2B3",
                                    ),
                                    ft.Text(
                                        (
                                            "Ubicación: "
                                            f"{ubicacion}"
                                        ),
                                        size=10,
                                        color="#667085",
                                    ),
                                ],
                                spacing=8,
                                wrap=True,
                            ),

                            ft.Row(
                                controls=[
                                    ft.Row(
                                        controls=[
                                            estado_cliente_priorizado_badge(
                                                cliente
                                            ),
                                            deuda_tramites_cell(
                                                cliente
                                            ),
                                        ],
                                        spacing=8,
                                        wrap=True,
                                    ),

                                    ft.Row(
                                        controls=[
                                            ft.Text(
                                                "A deber",
                                                size=10,
                                                color="#667085",
                                            ),
                                            ft.Container(
                                                content=ft.Text(
                                                    money_display(
                                                        deuda_total
                                                    ),
                                                    size=11,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=(
                                                        "#027A48"
                                                        if deuda_total <= 0
                                                        else "#B42318"
                                                    ),
                                                ),
                                                bgcolor=(
                                                    "#ECFDF3"
                                                    if deuda_total <= 0
                                                    else "#FEF3F2"
                                                ),
                                                border_radius=14,
                                                padding=ft.padding.symmetric(
                                                    horizontal=10,
                                                    vertical=4,
                                                ),
                                            ),
                                            ft.Text(
                                                "Ficha completa",
                                                size=10,
                                                color="#667085",
                                            ),
                                            ft.Container(
                                                content=ft.Text(
                                                    f"{ficha_pct}%",
                                                    size=11,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=(
                                                        "#027A48"
                                                        if ficha_pct >= 80
                                                        else "#B54708"
                                                    ),
                                                ),
                                                bgcolor=(
                                                    "#ECFDF3"
                                                    if ficha_pct >= 80
                                                    else "#FFFAEB"
                                                ),
                                                border_radius=14,
                                                padding=ft.padding.symmetric(
                                                    horizontal=10,
                                                    vertical=4,
                                                ),
                                            ),
                                        ],
                                        spacing=8,
                                        vertical_alignment=(
                                            ft.CrossAxisAlignment.CENTER
                                        ),
                                    ),
                                ],
                                alignment=(
                                    ft.MainAxisAlignment.SPACE_BETWEEN
                                ),
                                vertical_alignment=(
                                    ft.CrossAxisAlignment.CENTER
                                ),
                            ),
                        ],
                        spacing=5,
                        expand=True,
                    ),
                ],
                spacing=12,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )

    def build_table():
        clients = clientes_filtrados()

        if not clients:
            return ft.Column(
                controls=[
                    selection_bar,
                    empty_state("No hay clientes que coincidan con la búsqueda"),
                ],
                spacing=8,
                expand=True,
            )

        visible_ids = {c["id"] for c in clients}
        all_selected = bool(visible_ids) and visible_ids.issubset(state["selected_client_ids"])
        select_all_checkbox = ft.Checkbox(value=all_selected, on_change=toggle_all_visible_clients)

        total_items = len(clients)
        page_size = int(state.get("page_size") or 20)
        current_page = max(1, int(state.get("page") or 1))
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        current_page = min(current_page, total_pages)
        state["page"] = current_page

        start = (current_page - 1) * page_size
        end = start + page_size
        page_clients = clients[start:end]

        cards_controls = [
            build_client_card(cliente, index=start + index)
            for index, cliente in enumerate(page_clients)
        ]

        first_item = (
            start + 1
            if total_items
            else 0
        )
        last_item = min(
            end,
            total_items,
        )

        previous_button = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT_ROUNDED,
            icon_size=18,
            tooltip="Página anterior",
            disabled=current_page <= 1,
            on_click=lambda e: set_page(
                current_page - 1
            ),
        )

        next_button = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT_ROUNDED,
            icon_size=18,
            tooltip="Página siguiente",
            disabled=current_page >= total_pages,
            on_click=lambda e: set_page(
                current_page + 1
            ),
        )

        toolbar = ft.Container(
            height=52,
            padding=ft.padding.symmetric(
                horizontal=14,
                vertical=6,
            ),
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                "#DCE5EF",
            ),
            border_radius=12,
            content=ft.Row(
                controls=[
                    ft.Row(
                        controls=[
                            select_all_checkbox,

                            ft.Text(
                                "Seleccionar visibles",
                                size=11,
                                color="#475467",
                                weight=ft.FontWeight.W_600,
                            ),

                            ft.Container(
                                width=1,
                                height=22,
                                bgcolor="#E4E7EC",
                            ),

                            ft.Text(
                                "Clientes",
                                size=12,
                                weight=ft.FontWeight.BOLD,
                                color="#102A56",
                            ),

                            ft.Container(
                                width=30,
                                height=24,
                                alignment=ft.Alignment.CENTER,
                                padding=ft.padding.symmetric(
                                    horizontal=8,
                                ),
                                bgcolor="#0057B8",
                                border_radius=12,
                                content=ft.Text(
                                    str(total_items),
                                    size=11,
                                    weight=ft.FontWeight.BOLD,
                                    color="#FFFFFF",
                                ),
                            ),
                        ],
                        spacing=9,
                        vertical_alignment=(
                            ft.CrossAxisAlignment.CENTER
                        ),
                    ),

                    ft.Container(expand=True),

                    ft.Text(
                        (
                            f"Mostrando {first_item}-{last_item} "
                            f"de {total_items}"
                        ),
                        size=11,
                        color="#667085",
                    ),

                    ft.Container(
                        width=1,
                        height=22,
                        bgcolor="#E4E7EC",
                    ),

                    ft.Text(
                        (
                            f"Página {current_page} "
                            f"de {total_pages}"
                        ),
                        size=11,
                        weight=ft.FontWeight.W_600,
                        color="#344054",
                    ),

                    ft.Container(
                        height=34,
                        border=ft.border.all(
                            1,
                            "#DCE5EF",
                        ),
                        border_radius=9,
                        content=ft.Row(
                            controls=[
                                previous_button,
                                ft.Container(
                                    width=1,
                                    height=20,
                                    bgcolor="#E4E7EC",
                                ),
                                next_button,
                            ],
                            spacing=0,
                            tight=True,
                            vertical_alignment=(
                                ft.CrossAxisAlignment.CENTER
                            ),
                        ),
                    ),

                    ft.Container(
                        width=34,
                        height=34,
                        border_radius=9,
                        bgcolor="#0057B8",
                        alignment=ft.Alignment.CENTER,
                        content=ft.Icon(
                            ft.Icons.VIEW_LIST_ROUNDED,
                            size=18,
                            color="#FFFFFF",
                        ),
                    ),
                ],
                spacing=12,
                vertical_alignment=(
                    ft.CrossAxisAlignment.CENTER
                ),
            ),
        )

        return ft.Column(
            controls=[
                selection_bar,
                toolbar,
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        controls=cards_controls,
                        spacing=8,
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ),
            ],
            spacing=10,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
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
                        (
                            "Caducidad NIE/TIE",
                            fecha_a_display(
                                cliente.get(
                                    "fecha_caducidad_residencia"
                                )
                            ),
                        ),
                        ("Teléfono", cliente.get("telefono")),
                        ("Email", cliente.get("email")),
                        ("Estado", cliente.get("estado_cliente")),
                        ("Sexo", cliente.get("sexo")),
                        ("Ficha completada", f"{porcentaje_ficha(cliente)}%"),
                    ],
                ),
                detail_section("Dirección", [("Domicilio", cliente.get("domicilio_espana")), ("Tipo de vía", cliente.get("tipo_via")), ("Nombre de vía", cliente.get("nombre_via")), ("Número", cliente.get("numero")), ("Piso", cliente.get("piso")), ("Localidad", cliente.get("localidad")), ("Provincia", cliente.get("provincia")), ("Código postal", cliente.get("codigo_postal"))]),
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
        cliente["_on_previous"] = prev_selected_detail
        cliente["_on_next"] = next_selected_detail

        return ft.Column(
            controls=[
                ft.Text(f"Ficha seleccionada {pos} de {total}", size=14, color="#64748B"),
                client_detail_view(
                    page,
                    cliente,
                    on_back=show_client_list,
                    on_edit=lambda e, c=cliente: abrir_editar_cliente(c),
                    on_open_expediente=on_open_expediente,
                ),
            ],
            spacing=12,
            expand=True,
        )

    def show_client_list(e=None):
        cargar_clientes()
        filter_column.on_change = refresh_table
        search_input.on_change = refresh_table

        search_input.prefix_icon = ft.Icons.SEARCH
        search_input.hint_text = "Buscar cliente..."

        # Distribución visual de la barra superior.
        filter_column.width = 210
        search_input.width = 420
        search_input.expand = False
        refresh_quick_filters()
        table_container.content = build_table()
        refresh_selection_bar()
        refresh_context_panel()
        content_area.content = ft.Row(
            controls=[
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        controls=[
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Clientes",
                                        size=28,
                                        weight=ft.FontWeight.BOLD,
                                        color="#003B7A",
                                    ),
                                    ft.Text(
                                        "Gestión operativa de clientes del despacho",
                                        size=14,
                                        color="#64748B",
                                    ),
                                ],
                                spacing=2,
                            ),

                            ft.Row(
                                controls=[
                                    ft.Container(
                                        expand=1,
                                        content=metric_card(
                                            "Clientes activos",
                                            len(state["clients"]),
                                            icon=ft.Icons.PEOPLE_OUTLINE,
                                            accent_color="#0057B8",
                                            subtitle="Clientes",
                                            width=None,
                                            horizontal=True,
                                        ),
                                    ),
                                    ft.Container(
                                        expand=1,
                                        content=metric_card(
                                            "Morosos",
                                            total_morosos(
                                                state["clients"]
                                            ),
                                            icon=ft.Icons.ERROR_OUTLINE,
                                            accent_color="#D92D20",
                                            subtitle="Clientes",
                                            width=None,
                                            horizontal=True,
                                        ),
                                    ),
                                    ft.Container(
                                        expand=1,
                                        content=metric_card(
                                            "Importe total a deber",
                                            money_display(
                                                importe_total_deuda(
                                                    state["clients"]
                                                )
                                            ),
                                            icon=ft.Icons.EURO,
                                            accent_color="#0057B8",
                                            subtitle="Total pendiente",
                                            width=None,
                                            horizontal=True,
                                        ),
                                    ),
                                    ft.Container(
                                        expand=1,
                                        content=metric_card(
                                            "Sin documento",
                                            sum(
                                                1
                                                for c in state["clients"]
                                                if not documento_cliente(c)
                                            ),
                                            icon=ft.Icons.DESCRIPTION_OUTLINED,
                                            accent_color="#7F56D9",
                                            subtitle="Clientes",
                                            width=None,
                                            horizontal=True,
                                        ),
                                    ),
                                ],
                                spacing=12,
                                wrap=False,
                                vertical_alignment=(
                                    ft.CrossAxisAlignment.CENTER
                                ),
                            ),

                            ft.Container(
                                height=66,
                                padding=ft.padding.symmetric(
                                    horizontal=12,
                                    vertical=8,
                                ),
                                bgcolor="#FFFFFF",
                                border=ft.border.all(
                                    1,
                                    "#DCE5EF",
                                ),
                                border_radius=12,
                                content=ft.Row(
                                    controls=[
                                        ft.Container(
                                            width=210,
                                            content=filter_column,
                                        ),
                                        ft.Container(
                                            width=420,
                                            content=search_input,
                                        ),
                                        ft.Container(
                                            width=170,
                                            content=primary_button(
                                                "＋  Nuevo cliente",
                                                abrir_nuevo_cliente,
                                            ),
                                        ),
                                        ft.Container(
                                            width=170,
                                            content=secondary_button(
                                                "Importar CSV",
                                                seleccionar_csv,
                                            ),
                                        ),
                                    ],
                                    spacing=12,
                                    alignment=(
                                        ft.MainAxisAlignment.SPACE_BETWEEN
                                    ),
                                    vertical_alignment=(
                                        ft.CrossAxisAlignment.CENTER
                                    ),
                                    wrap=False,
                                ),
                            ),

                            quick_filters_container,
                            table_container,
                        ],
                        spacing=10,
                        expand=True,
                    ),
                ),

                context_panel_container,
            ],
            spacing=18,
            expand=True,
        )
        page.update()

    cargar_clientes()

    pending_open_client_id = (
        open_client_id
    )

    if pending_open_client_id:
        try:
            pending_open_client_id = int(
                pending_open_client_id
            )
        except (TypeError, ValueError):
            pending_open_client_id = None

    pending_client = (
        next(
            (
                client
                for client
                in state["clients"]
                if int(
                    client.get("id")
                    or 0
                )
                == pending_open_client_id
            ),
            None,
        )
        if pending_open_client_id
        else None
    )

    if (
        not pending_client
        and isinstance(
            new_client_defaults,
            dict,
        )
        and new_client_defaults
    ):
        show_client_list()

        abrir_nuevo_cliente(
            defaults=(
                new_client_defaults
            )
        )

    elif pending_client:
        ver_ficha(
            pending_client,
            on_back_override=(
                (
                    lambda e=None:
                        on_context_back()
                )
                if on_context_back
                else None
            ),
        )
    else:
        show_client_list()

    return content_area
