import flet as ft

Q_PRIMARY = "#0057B8"
Q_BORDER = "#E4E7EC"
Q_BG_HEADER = "#F2F7FC"
Q_BG_ROW_ALT = "#FAFBFC"
Q_SELECTED = "#EAF3FF"
Q_TEXT = "#101828"

DEFAULT_WIDTHS = {
    "Nombre": 420,
    "NIE/Pasaporte": 170,
    "NIE / Pasaporte": 170,
    "Documento": 170,
    "Nacionalidad": 160,
    "Edad": 70,
    "Teléfono": 140,
    "Telefono": 140,
    "Estado": 200,
    "Ficha": 120,
    "Errores": 320,
}


def _header_key(header):
    if isinstance(header, dict):
        return header.get("key", "")
    return str(header)


def _header_label(header):
    if isinstance(header, dict):
        return header.get("label", header.get("key", ""))
    return header


def _column_width(header):
    if isinstance(header, dict) and header.get("width"):
        try:
            return int(header.get("width"))
        except (TypeError, ValueError):
            pass
    return DEFAULT_WIDTHS.get(_header_key(header), 170)


def _cell(value):
    if isinstance(value, ft.Control):
        return value

    return ft.Text(
        value=str(value),
        size=13,
        color=Q_TEXT,
        overflow=ft.TextOverflow.ELLIPSIS,
    )


def _header_cell(header):
    label = _header_label(header)
    content = label if isinstance(label, ft.Control) else ft.Text(
        value=str(label),
        weight=ft.FontWeight.W_600,
        size=13,
        color=Q_PRIMARY,
    )

    return ft.Container(
        content=content,
        padding=ft.padding.symmetric(horizontal=12, vertical=10),
        bgcolor=Q_BG_HEADER,
        width=_column_width(header),
    )


def _body_cell(value, header):
    return ft.Container(
        content=_cell(value),
        padding=ft.padding.symmetric(horizontal=12, vertical=8),
        width=_column_width(header),
    )


def _default_row_bg(index):
    return Q_BG_ROW_ALT if index % 2 else "#FFFFFF"


def _row(row_values, headers, index, selected=False, on_click=None, row_ref=None):
    return ft.Container(
        ref=row_ref,
        content=ft.Row(
            controls=[_body_cell(value, headers[i]) for i, value in enumerate(row_values)],
            spacing=0,
        ),
        bgcolor=Q_SELECTED if selected else _default_row_bg(index),
        border=ft.border.only(bottom=ft.BorderSide(1, Q_BORDER)),
        height=58,
        ink=True,
        on_click=on_click,
    )


def app_table(headers, rows, height=430):
    headers = list(headers)
    table_rows = []

    for index, raw_row_values in enumerate(rows):
        row_values = list(raw_row_values)
        selected = False
        on_click = None
        row_ref = None

        if row_values and isinstance(row_values[0], dict):
            meta = row_values.pop(0)
            selected = meta.get("selected", False)
            on_click = meta.get("on_click")
            row_ref = meta.get("row_ref")

        table_rows.append(
            _row(
                row_values=row_values,
                headers=headers,
                index=index,
                selected=selected,
                on_click=on_click,
                row_ref=row_ref,
            )
        )

    header_height = 46
    table_width = sum(_column_width(header) for header in headers) + 80

    header = ft.Container(
        content=ft.Row(
            controls=[_header_cell(header) for header in headers],
            spacing=0,
        ),
        height=header_height,
        bgcolor=Q_BG_HEADER,
        width=table_width,
    )

    body = ft.ListView(
        controls=table_rows,
        spacing=0,
        padding=0,
        auto_scroll=False,
        expand=True,
    )

    table_content = ft.Container(
        width=table_width,
        height=height,
        content=ft.Column(
            controls=[
                header,
                ft.Container(
                    content=body,
                    height=height - header_height,
                    width=table_width,
                ),
            ],
            spacing=0,
        ),
    )

    return ft.Container(
        content=ft.Row(
            controls=[table_content],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
        expand=True,
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=12,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
