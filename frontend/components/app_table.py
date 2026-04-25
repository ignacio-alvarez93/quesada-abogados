import flet as ft

Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_HEADER_BG = "#EAF6FF"
Q_ROW_ALT = "#F8FAFC"
Q_BORDER = "#D8E2EE"
Q_TEXT = "#0F172A"
Q_MUTED = "#64748B"


def _cell(value, bold=False):
    if isinstance(value, ft.Control):
        return ft.Container(content=value, padding=ft.padding.symmetric(horizontal=10, vertical=8))
    return ft.Container(
        content=ft.Text(str(value or "-"), size=13, weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL, color=Q_PRIMARY_DARK if bold else Q_TEXT),
        padding=ft.padding.symmetric(horizontal=10, vertical=8),
        alignment=ft.alignment.center_left,
    )


def app_table(headers, rows, actions=None):
    columns = [ft.DataColumn(ft.Text(header, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)) for header in headers]
    data_rows = []

    for index, row in enumerate(rows or []):
        row_values = list(row.values()) if isinstance(row, dict) else list(row)
        if actions:
            row_actions = actions(row) if callable(actions) else actions
            row_values.append(ft.Row(controls=row_actions, spacing=6, alignment=ft.MainAxisAlignment.END))
        data_rows.append(
            ft.DataRow(
                color=Q_ROW_ALT if index % 2 else "#FFFFFF",
                cells=[ft.DataCell(_cell(value)) for value in row_values],
            )
        )

    if not data_rows:
        data_rows = [
            ft.DataRow(
                cells=[ft.DataCell(ft.Text("Sin registros", color=Q_MUTED))] + [ft.DataCell(ft.Text("")) for _ in headers[1:]]
            )
        ]

    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.TABLE_CHART_OUTLINED, color=Q_PRIMARY),
                        ft.Text("Listado", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ],
                    spacing=8,
                ),
                ft.DataTable(
                    columns=columns,
                    rows=data_rows,
                    heading_row_color=Q_HEADER_BG,
                    heading_row_height=46,
                    data_row_min_height=46,
                    data_row_max_height=58,
                    column_spacing=22,
                    divider_thickness=0.6,
                ),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=16,
        expand=True,
    )
