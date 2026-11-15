"""
Editor reutilizable «Conceptos del cobro» (ECO-ML-01B).

Un cobro es un único recibo con 1..N líneas de desglose. Este componente
solo gestiona UI y estado: el total que muestra es informativo y
economic_service recalcula importe, resumen fiscal y reglas al guardar.
No consulta servicios ni accede a base de datos.
"""

from __future__ import annotations

import itertools

import flet as ft

from backend.services import economic_cobro_lineas_service as cobro_lineas
from frontend.components.app_button import secondary_button
from frontend.components.app_text_field import required_text_input


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#D0D5DD"
Q_SUCCESS = "#027A48"
Q_DANGER = "#B42318"
Q_WARNING = "#B54708"

TIPO_ECONOMICO_OPTIONS = (
    ("PROVISION", "Provisión"),
    ("TASA", "Tasa"),
    ("HONORARIOS", "Honorarios"),
    ("OTRO", "Otro"),
)

# La naturaleza fiscal no tiene valor por defecto: debe elegirse
# expresamente en cada línea (TASA no implica SUPLIDO).
TIPO_FISCAL_OPTIONS = (
    ("PROVISION", "Provisión"),
    ("SUPLIDO", "Suplido"),
)


def _dropdown(label, options, value, width, on_change):
    dropdown = ft.Dropdown(
        label=label,
        value=value,
        width=width,
        border_color=Q_BORDER,
        focused_border_color=Q_PRIMARY,
        options=[
            ft.dropdown.Option(key=key, text=text)
            for key, text in options
        ],
    )
    dropdown.on_change = on_change
    if hasattr(dropdown, "on_select"):
        dropdown.on_select = on_change
    return dropdown


def _safe_update(control):
    try:
        control.update()
    except Exception:
        # Control todavía no montado en la página (p. ej. antes de abrir
        # el diálogo o en tests): el valor se pintará en el próximo update.
        pass


class _LineRow:
    def __init__(self, key, editor, linea=None):
        linea = linea or {}
        self.key = key

        centimos = linea.get("importe_centimos")
        importe = (
            cobro_lineas.format_centimos_es(centimos)
            if centimos not in (None, "")
            else str(linea.get("importe") or "")
        )

        self.position_text = ft.Text(
            "1",
            size=12,
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY,
            width=18,
        )
        self.concepto = required_text_input("Concepto", width=250)
        self.concepto.value = str(linea.get("concepto") or "")
        self.concepto.on_change = editor._on_field_change

        self.tipo_economico = _dropdown(
            "Tipo",
            TIPO_ECONOMICO_OPTIONS,
            linea.get("tipo_economico") or "PROVISION",
            150,
            editor._on_field_change,
        )
        self.tipo_fiscal = _dropdown(
            "Naturaleza fiscal *",
            TIPO_FISCAL_OPTIONS,
            linea.get("tipo_fiscal") or None,
            165,
            editor._on_field_change,
        )

        self.importe = required_text_input("Importe €", width=130)
        self.importe.value = importe
        self.importe.on_change = editor._on_field_change

        self.remove_button = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE,
            icon_color=Q_DANGER,
            tooltip="Eliminar línea",
            on_click=lambda e, k=key: editor.remove_line(k),
        )

        self.control = ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, "#E4E7EC"),
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            content=ft.Row(
                controls=[
                    self.position_text,
                    self.concepto,
                    self.tipo_economico,
                    self.tipo_fiscal,
                    self.importe,
                    self.remove_button,
                ],
                spacing=8,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def snapshot(self):
        return (
            " ".join(str(self.concepto.value or "").split()),
            self.tipo_economico.value or "",
            self.tipo_fiscal.value or "",
            str(self.importe.value or "").strip(),
        )

    def raw(self):
        return {
            "concepto": self.concepto.value,
            "tipo_economico": self.tipo_economico.value,
            "tipo_fiscal": self.tipo_fiscal.value,
            "importe": self.importe.value,
        }


class PaymentLinesEditor:
    """
    Sección «Conceptos del cobro» con N filas.

    - `reset()` deja una fila vacía (alta) o carga el desglose recibido
      (edición / prefill desde conciliación).
    - `payload_for_save()` devuelve el fragmento para economic_service:
      `lineas` o, si se trata de la línea sintética de un cobro legacy que
      no se ha tocado, el contrato legacy (`importe` / `tipo_fiscal`).
    """

    def __init__(self, *, on_change=None):
        self.on_change = on_change
        self.rows = []
        self.sinteticas = False
        self.target_centimos = None
        self._initial = ()
        self._keys = itertools.count(1)

        self.rows_column = ft.Column(spacing=8)
        self.add_button = secondary_button("+ Añadir línea", self.add_line)
        self.summary_text = ft.Text("", size=11, color=Q_MUTED)
        self.total_text = ft.Text(
            "",
            size=16,
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        )
        self.status_text = ft.Text("", size=11, color=Q_MUTED)

        self.control = ft.Column(
            controls=[
                self.rows_column,
                ft.Row(
                    controls=[
                        self.add_button,
                        self.summary_text,
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(
                    bgcolor="#EAF3FF",
                    border=ft.border.all(1, "#84CAFF"),
                    border_radius=10,
                    padding=ft.padding.symmetric(horizontal=12, vertical=10),
                    content=ft.Column(
                        controls=[
                            self.total_text,
                            self.status_text,
                        ],
                        spacing=2,
                    ),
                ),
            ],
            spacing=10,
        )

        self.reset()

    # ------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------

    def reset(self, lineas=None, *, sinteticas=False, target_centimos=None):
        self.rows = []
        self.sinteticas = bool(sinteticas and lineas)
        self.target_centimos = (
            int(target_centimos) if target_centimos else None
        )

        for linea in lineas or [{}]:
            self.rows.append(_LineRow(next(self._keys), self, linea))

        self._initial = self.snapshot()
        self.refresh(notify=False)

    def add_line(self, e=None, linea=None):
        self.rows.append(_LineRow(next(self._keys), self, linea))
        self.refresh()

    def remove_line(self, key):
        if len(self.rows) <= 1:
            return
        self.rows = [row for row in self.rows if row.key != key]
        self.refresh()

    def snapshot(self):
        return tuple(row.snapshot() for row in self.rows)

    def is_modified(self):
        return self.snapshot() != self._initial

    def _on_field_change(self, e=None):
        self.refresh()

    # ------------------------------------------------------------
    # Cálculo informativo (el backend recalcula al guardar)
    # ------------------------------------------------------------

    def compute(self):
        total = 0
        errors = []
        for posicion, row in enumerate(self.rows, start=1):
            try:
                total += cobro_lineas.parse_importe_centimos(
                    row.importe.value,
                    campo=f"Línea {posicion}",
                )
            except ValueError as exc:
                errors.append(str(exc))
        return total, errors

    def total_centimos(self):
        return self.compute()[0]

    def resumen_fiscal(self):
        """PROVISION, SUPLIDO, MIXTO o None si falta alguna naturaleza."""
        tipos = [row.tipo_fiscal.value for row in self.rows]
        if not all(tipos):
            return None
        return cobro_lineas.resumen_fiscal(
            [{"tipo_fiscal": tipo} for tipo in tipos]
        )

    def lineas_payload(self):
        """Valida con el dominio y devuelve las líneas en céntimos."""
        lineas = cobro_lineas.validate_lineas(
            [row.raw() for row in self.rows]
        )
        return [
            {
                "concepto": linea["concepto"],
                "tipo_economico": linea["tipo_economico"],
                "tipo_fiscal": linea["tipo_fiscal"],
                "importe_centimos": linea["importe_centimos"],
            }
            for linea in lineas
        ]

    def payload_for_save(self, importe_legacy=None):
        if self.sinteticas and not self.is_modified():
            # Cobro legacy sin filas de detalle y desglose intacto: se
            # mantiene el contrato legacy, sin backfill de líneas.
            concepto, _tipo_economico, tipo_fiscal, importe = self.rows[0].snapshot()
            return {
                "importe": importe_legacy if importe_legacy is not None else importe,
                "tipo_fiscal": tipo_fiscal,
                "concepto": concepto,
            }

        payload = {"lineas": self.lineas_payload()}
        if self.target_centimos is not None:
            # Importe del movimiento: el backend exige igualdad exacta.
            payload["importe"] = cobro_lineas.format_centimos_es(
                self.target_centimos
            )
        return payload

    # ------------------------------------------------------------
    # Render
    # ------------------------------------------------------------

    def refresh(self, notify=True):
        single = len(self.rows) <= 1
        for posicion, row in enumerate(self.rows, start=1):
            row.position_text.value = str(posicion)
            row.remove_button.disabled = single
            row.remove_button.tooltip = (
                "El cobro debe tener al menos una línea"
                if single
                else "Eliminar línea"
            )

        self.rows_column.controls = [row.control for row in self.rows]

        total, errors = self.compute()
        num = len(self.rows)
        self.summary_text.value = "1 concepto" if num == 1 else f"{num} conceptos"
        self.total_text.value = (
            f"TOTAL COBRO {cobro_lineas.format_centimos_es(total)} €"
        )

        if errors:
            self.status_text.value = errors[0]
            self.status_text.color = Q_DANGER
        elif self.target_centimos is not None and total != self.target_centimos:
            diferencia = self.target_centimos - total
            self.status_text.value = (
                "El total debe coincidir con el movimiento "
                f"({cobro_lineas.format_centimos_es(self.target_centimos)} €). "
                + (
                    f"Faltan {cobro_lineas.format_centimos_es(diferencia)} €."
                    if diferencia > 0
                    else f"Sobran {cobro_lineas.format_centimos_es(-diferencia)} €."
                )
            )
            self.status_text.color = Q_WARNING
        elif self.resumen_fiscal() is None:
            self.status_text.value = (
                "Indica la naturaleza fiscal (Provisión o Suplido) de cada línea."
            )
            self.status_text.color = Q_WARNING
        else:
            self.status_text.value = (
                "Importe global calculado a partir de las líneas."
            )
            self.status_text.color = Q_SUCCESS

        if notify and self.on_change is not None:
            self.on_change(self)

        _safe_update(self.control)
