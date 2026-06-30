import unicodedata
import flet as ft

Q_PRIMARY = "#0057B8"
Q_BORDER = "#CBD5E1"
Q_FOCUSED = "#18BFEA"
Q_TEXT = "#101828"
Q_MUTED = "#64748B"
Q_RESULT_BG = "#FFFFFF"
Q_EMPTY_BG = "#F8FAFC"


def _normalize(value):
    value = value or ""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower().strip()


class AppAutocomplete:
    """
    Autocomplete reutilizable del ERP.

    Compatible hacia atrás con opciones string:
        AppAutocomplete(page, "Cliente", ["Juan", "Ana"])

    Compatible con opciones estructuradas:
        {"id": 1, "label": "Juan Pérez", "subtitle": "NIE X1234567L"}

    El componente no accede a backend ni base de datos.
    La vista/servicio debe proporcionar las opciones.
    """

    def __init__(
        self,
        page,
        label,
        options=None,
        value="",
        width=None,
        max_results=8,
        on_select=None,
        allow_free_text=True,
        hint_text=None,
        helper_text=None,
        error_text=None,
        disabled=False,
        empty_text="Sin resultados",
        show_empty=True,
    ):
        self.page = page
        self.label = label
        self.options = options or []
        self.value = value or ""
        self.width = width
        self.visible_rows = max_results or 8
        self.on_select = on_select
        self.allow_free_text = allow_free_text
        self.empty_text = empty_text
        self.show_empty = show_empty
        self.helper_text = helper_text
        self.error_text = error_text
        self._mouse_over_results = False

        self.selected_option = None

        self.input = ft.TextField(
            label=label,
            value=self.value,
            width=width,
            hint_text=hint_text,
            disabled=disabled,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color=Q_FOCUSED,
            cursor_color=Q_PRIMARY,
            content_padding=ft.padding.symmetric(horizontal=14, vertical=12),
            on_change=self._on_change,
            on_focus=self._on_focus,
            on_blur=self._on_blur,
        )

        self.results_list = ft.ListView(
            controls=[],
            spacing=0,
            padding=0,
            height=self.visible_rows * 42,
            auto_scroll=False,
        )

        self.results_box = ft.Container(
            content=self.results_list,
            bgcolor=Q_RESULT_BG,
            border=ft.border.all(1, Q_BORDER),
            border_radius=10,
            padding=0,
            width=width,
            height=self.visible_rows * 42,
            visible=False,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            on_hover=self._on_results_hover,
        )

        self.control = ft.Container(
            content=ft.Column(
                controls=[
                    self.input,
                    self.results_box,
                ],
                spacing=4,
            ),
            width=width,
        )

    def _option_label(self, option):
        if isinstance(option, dict):
            return str(
                option.get("label")
                or option.get("name")
                or option.get("text")
                or option.get("value")
                or ""
            )
        return str(option or "")

    def _option_subtitle(self, option):
        if isinstance(option, dict):
            return str(option.get("subtitle") or option.get("description") or "")
        return ""

    def _option_search_text(self, option):
        if isinstance(option, dict):
            parts = [
                option.get("id"),
                option.get("label"),
                option.get("name"),
                option.get("text"),
                option.get("value"),
                option.get("subtitle"),
                option.get("description"),
            ]
            return " ".join(str(part) for part in parts if part not in (None, ""))
        return str(option or "")

    def _emit_select(self, value):
        if self.on_select:
            self.on_select(value)

    def _safe_update(self):
        if self.page:
            self.page.update()

    def _on_focus(self, e=None):
        if self.input.disabled:
            return

        self._refresh_results(self.input.value or "", show_all=True)
        self._safe_update()

    def _on_results_hover(self, e=None):
        self._mouse_over_results = str(getattr(e, "data", "")).lower() == "true"

    def _on_blur(self, e=None):
        # Si el usuario está pulsando una opción, no cerramos aquí:
        # dejamos que el on_click de la opción ejecute select().
        if self._mouse_over_results:
            return

        self.close_results(update=True)

    def _on_change(self, e=None):
        typed = self.input.value or ""
        self.value = typed
        self.selected_option = None

        if self.allow_free_text:
            self._emit_select(self.value)

        self._refresh_results(typed, show_all=False)
        self._safe_update()

    def _matches(self, typed, show_all=False):
        # max_results / visible_rows controla la altura visible del desplegable,
        # no debe limitar el número total de opciones disponibles.
        if show_all and not typed:
            return list(self.options)

        query = _normalize(typed)

        if not query:
            return []

        matches = []

        for option in self.options:
            if query in _normalize(self._option_search_text(option)):
                matches.append(option)

        return matches

    def _refresh_results(self, typed, show_all=False):
        matches = self._matches(typed, show_all=show_all)

        self.results_list.controls.clear()

        if not matches:
            if self.show_empty and typed:
                self.results_list.controls.append(self._empty_item())
                self.results_box.visible = True
            else:
                self.results_box.visible = False
            return

        for option in matches:
            self.results_list.controls.append(self._result_item(option))

        self.results_box.visible = True

    def _empty_item(self):
        return ft.Container(
            content=ft.Text(
                self.empty_text,
                size=12,
                color=Q_MUTED,
                italic=True,
            ),
            bgcolor=Q_EMPTY_BG,
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
        )

    def _result_item(self, option):
        label = self._option_label(option)
        subtitle = self._option_subtitle(option)

        if subtitle:
            content = ft.Column(
                controls=[
                    ft.Text(
                        label,
                        size=13,
                        color=Q_TEXT,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(
                        subtitle,
                        size=11,
                        color=Q_MUTED,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
                spacing=1,
            )
            padding = ft.padding.symmetric(horizontal=12, vertical=7)
        else:
            content = ft.Text(
                label,
                size=13,
                color=Q_TEXT,
                overflow=ft.TextOverflow.ELLIPSIS,
            )
            padding = ft.padding.symmetric(horizontal=12, vertical=9)

        return ft.Container(
            content=content,
            bgcolor=Q_RESULT_BG,
            border=ft.border.only(
                bottom=ft.BorderSide(1, "#EEF2F7"),
            ),
            padding=padding,
            ink=True,
            on_click=lambda e, selected=option: self.select(selected),
        )

    def select(self, selected):
        self.selected_option = selected
        self.value = self._option_label(selected)
        self.input.value = self.value
        self.results_list.controls.clear()
        self.results_box.visible = False

        # Compatibilidad histórica:
        # las vistas actuales esperan recibir el texto seleccionado.
        self._emit_select(self.value)

        self._safe_update()

    def set_options(self, options, clear_value=False):
        self.options = options or []

        if clear_value:
            self.set_value("", update=False)

        self.results_list.controls.clear()
        self.results_box.visible = False

    def set_value(self, value, update=True):
        self.value = value or ""
        self.input.value = self.value
        self.selected_option = None
        self.results_list.controls.clear()
        self.results_box.visible = False

        if update:
            self._safe_update()

    def set_error(self, error_text=None, update=True):
        self.error_text = error_text

        # Compatibilidad con versiones antiguas de Flet:
        # algunas no exponen error_text en TextField.
        if hasattr(self.input, "error_text"):
            self.input.error_text = error_text

        if update:
            self._safe_update()

    def set_disabled(self, disabled=True, update=True):
        self.input.disabled = disabled
        self.results_list.controls.clear()
        self.results_box.visible = False

        if update:
            self._safe_update()

    def close_results(self, update=True):
        self.results_list.controls.clear()
        self.results_box.visible = False

        if update:
            self._safe_update()

    def clear(self, update=True):
        self.set_value("", update=update)

    def get_value(self):
        return self.input.value or ""

    def get_selected(self):
        return self.selected_option
