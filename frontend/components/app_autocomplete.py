import unicodedata

import flet as ft


Q_PRIMARY = "#0057B8"
Q_BORDER = "#CBD5E1"
Q_FOCUSED = "#18BFEA"
Q_TEXT = "#101828"
Q_MUTED = "#64748B"
Q_RESULT_BG = "#FFFFFF"

_RESULT_HEIGHT = 42
_EMPTY_KEY = "__app_autocomplete_empty__"

# Los catálogos grandes no necesitan miles de controles Text
# enriquecidos dentro del menú. A partir de este umbral se usa
# DropdownOption nativo ligero para opciones simples.
_LARGE_DATASET_THRESHOLD = 500
_LARGE_DATASET_MIN_CHARS = 2
_LARGE_DATASET_RESULT_LIMIT = 30


def _normalize(value):
    value = value or ""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(
        ch
        for ch in value
        if not unicodedata.combining(ch)
    )
    return value.lower().strip()


class _AutocompleteInputCompat:
    """
    Fachada de compatibilidad para consumidores históricos.

    Algunas vistas del ERP acceden directamente a:

        autocomplete.input.value
        autocomplete.input.label
        autocomplete.input.error_text
        autocomplete.input.disabled
        autocomplete.input.on_change

    El control visual real es ahora ft.Dropdown.
    """

    def __init__(self, autocomplete):
        self._autocomplete = autocomplete
        self._on_change = autocomplete._on_change

    @property
    def value(self):
        return self._autocomplete._input_value()

    @value.setter
    def value(self, value):
        self._autocomplete._set_input_value(
            value,
            sync_selection=True,
        )

    @property
    def label(self):
        return self._autocomplete._input_label()

    @label.setter
    def label(self, value):
        self._autocomplete._set_input_label(value)

    @property
    def error_text(self):
        return self._autocomplete.error_text

    @error_text.setter
    def error_text(self, value):
        self._autocomplete._set_input_error(value)

    @property
    def disabled(self):
        return self._autocomplete._input_disabled()

    @disabled.setter
    def disabled(self, value):
        self._autocomplete._set_input_disabled(
            bool(value)
        )

    @property
    def on_change(self):
        return self._on_change

    @on_change.setter
    def on_change(self, callback):
        self._on_change = callback


class AppAutocomplete:
    """
    Autocomplete reutilizable del ERP.

    Compatible hacia atrás con opciones string:

        AppAutocomplete(
            page,
            "Cliente",
            ["Juan", "Ana"],
        )

    También admite opciones estructuradas:

        {
            "id": 1,
            "label": "Juan Pérez",
            "subtitle": "NIE X1234567L",
        }

    La implementación visual utiliza el Dropdown editable nativo
    de Flet para que el menú:

    - se superponga al contenido;
    - no altere el layout;
    - no quede recortado por Columns/Rows/Dialogs;
    - conserve una apariencia coherente con otros dropdowns.

    El componente no accede a backend ni base de datos.
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
        icon=None,
        dropdown_offset=58,
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
        self.icon = icon

        # Se conserva para compatibilidad con código/configuración
        # creada durante la evolución del componente.
        self.dropdown_offset = dropdown_offset

        self.selected_option = None

        self._key_to_option = {}
        self._label_to_key = {}

        self.large_dataset_mode = (
            len(self.options) >= _LARGE_DATASET_THRESHOLD
        )

        self._large_search_index = []
        self._large_visible_options = []

        self.dropdown = ft.Dropdown(
            label=label,
            text=self.value,
            width=width,
            editable=True,
            enable_filter=True,
            enable_search=True,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color=Q_FOCUSED,
            color=Q_TEXT,
            bgcolor=Q_RESULT_BG,
            content_padding=ft.padding.symmetric(
                horizontal=14,
                vertical=12,
            ),
            leading_icon=icon,
            hint_text=hint_text,
            helper_text=helper_text,
            error_text=error_text,
            disabled=disabled,
            menu_width=width,
            elevation=8,
            on_text_change=self._dispatch_text_change,
            on_select=self._on_dropdown_select,
            on_focus=self._on_focus,
            on_blur=self._on_blur,
        )

        self.search_bar = ft.SearchBar(
            value=self.value,
            width=width,
            bar_hint_text=hint_text or label,
            view_hint_text=(
                f"Buscar {label.lower()}"
                if label
                else "Buscar"
            ),
            bar_leading=(
                icon
                if isinstance(icon, ft.Control)
                else (
                    ft.Icon(icon, size=18)
                    if icon
                    else ft.Icon(
                        ft.Icons.SEARCH,
                        size=18,
                    )
                )
            ),
            view_leading=ft.Icon(
                ft.Icons.SEARCH,
                size=18,
            ),
            view_bgcolor=Q_RESULT_BG,
            view_elevation=8,
            shrink_wrap=True,
            full_screen=False,
            controls=[],
            disabled=disabled,
            on_change=self._on_large_change,
            on_tap=self._on_large_tap,
        )

        # API histórica.
        self.input = _AutocompleteInputCompat(self)

        if self.large_dataset_mode:
            self._rebuild_large_search_index()
            self._refresh_large_results(
                self.value,
            )
            active_control = self.search_bar
        else:
            self._set_dropdown_options(
                self.options,
                typed=self.value,
                show_all=True,
            )
            active_control = self.dropdown

        self.control = ft.Container(
            content=active_control,
            width=width,
        )

    def _input_value(self):
        if self.large_dataset_mode:
            return (
                self.search_bar.value
                or self.value
                or ""
            )

        return (
            self.dropdown.text
            or self.value
            or ""
        )

    def _set_input_value(
        self,
        value,
        sync_selection=False,
    ):
        value = str(value or "")
        self.value = value

        if self.large_dataset_mode:
            self.search_bar.value = value

            if sync_selection:
                self.selected_option = None

            return

        self.dropdown.text = value

        if sync_selection:
            self.dropdown.value = self._key_for_label(
                value
            )

    def _input_label(self):
        if self.large_dataset_mode:
            return self.label

        return self.dropdown.label

    def _set_input_label(self, value):
        self.label = value

        if self.large_dataset_mode:
            self.search_bar.bar_hint_text = str(
                value or ""
            )
            return

        self.dropdown.label = value

    def _set_input_error(self, value):
        self.error_text = value

        if not self.large_dataset_mode:
            self.dropdown.error_text = value

    def _input_disabled(self):
        if self.large_dataset_mode:
            return bool(self.search_bar.disabled)

        return bool(self.dropdown.disabled)

    def _set_input_disabled(self, value):
        value = bool(value)

        self.dropdown.disabled = value
        self.search_bar.disabled = value

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
            return str(
                option.get("subtitle")
                or option.get("description")
                or ""
            )

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

            return " ".join(
                str(part)
                for part in parts
                if part not in (None, "")
            )

        return str(option or "")

    def _emit_select(self, value):
        if self.on_select:
            self.on_select(value)

    def _safe_update(self):
        if self.page:
            self.page.update()

    def _matches(self, typed, show_all=False):
        if show_all and not typed:
            return list(self.options)

        query = _normalize(typed)

        if not query:
            return []

        matches = []

        for option in self.options:
            if query in _normalize(
                self._option_search_text(option)
            ):
                matches.append(option)

        return matches

    def _rebuild_large_search_index(self):
        self._large_search_index = [
            (
                option,
                _normalize(
                    self._option_label(option)
                ),
                _normalize(
                    self._option_search_text(option)
                ),
            )
            for option in self.options
        ]

    def _large_matches(self, typed):
        query = _normalize(typed)

        if len(query) < _LARGE_DATASET_MIN_CHARS:
            return []

        ranked = []

        for option, normalized_label, normalized_search in (
            self._large_search_index
        ):
            position = normalized_search.find(query)

            if position < 0:
                continue

            if normalized_label.startswith(query):
                rank = 0
            elif (
                f" {query}" in normalized_label
                or f"-{query}" in normalized_label
            ):
                rank = 1
            elif query in normalized_label:
                rank = 2
            else:
                rank = 3

            ranked.append(
                (
                    rank,
                    position,
                    len(normalized_label),
                    normalized_label,
                    option,
                )
            )

        ranked.sort(
            key=lambda item: item[:4]
        )

        return [
            item[4]
            for item in ranked[
                :_LARGE_DATASET_RESULT_LIMIT
            ]
        ]

    def _large_message_tile(self, text):
        return ft.ListTile(
            title=ft.Text(
                text,
                size=12,
                color=Q_MUTED,
                italic=True,
            ),
            disabled=True,
            dense=True,
        )

    def _large_result_tile(self, option):
        label = self._option_label(option)
        subtitle = self._option_subtitle(option)

        return ft.ListTile(
            title=ft.Text(
                label,
                size=13,
                color=Q_TEXT,
                overflow=ft.TextOverflow.ELLIPSIS,
                tooltip=label,
            ),
            subtitle=(
                ft.Text(
                    subtitle,
                    size=11,
                    color=Q_MUTED,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    tooltip=subtitle,
                )
                if subtitle
                else None
            ),
            dense=True,
            data=option,
            on_click=self._large_select_handler(option),
        )

    def _refresh_large_results(self, typed):
        typed = str(typed or "")
        query = _normalize(typed)

        if len(query) < _LARGE_DATASET_MIN_CHARS:
            self._large_visible_options = []

            self.search_bar.controls = [
                self._large_message_tile(
                    "Escribe al menos "
                    f"{_LARGE_DATASET_MIN_CHARS} "
                    "caracteres"
                )
            ]
            return

        matches = self._large_matches(
            typed
        )

        self._large_visible_options = matches

        if not matches:
            self.search_bar.controls = [
                self._large_message_tile(
                    self.empty_text
                )
            ]
            return

        self.search_bar.controls = [
            self._large_result_tile(option)
            for option in matches
        ]

    def _large_select_handler(self, selected):
        async def handler(e=None):
            self.select(selected)

            try:
                await self.search_bar.close_view()
            except Exception:
                pass

        return handler

    async def _on_large_tap(self, e=None):
        if self._input_disabled():
            return

        try:
            await self.search_bar.open_view()
        except Exception:
            pass

    def _on_large_change(self, e=None):
        typed = (
            getattr(
                getattr(e, "control", None),
                "value",
                None,
            )
            or self.search_bar.value
            or ""
        )

        self.value = typed
        self.selected_option = None

        self._refresh_large_results(
            typed
        )

        callback = self.input.on_change

        if callback:
            callback(e)

        if self.allow_free_text:
            self._emit_select(
                self.value
            )

    def _key_for_option(self, index, option):
        if isinstance(option, dict):
            option_id = option.get("id")

            if option_id not in (None, ""):
                return f"option:{option_id}:{index}"

        return f"option:{index}"

    def _key_for_label(self, label):
        return self._label_to_key.get(
            str(label or "")
        )

    def _option_content(self, option):
        label = self._option_label(option)
        subtitle = self._option_subtitle(option)

        if subtitle:
            return ft.Column(
                controls=[
                    ft.Text(
                        label,
                        size=13,
                        color=Q_TEXT,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        tooltip=label,
                    ),
                    ft.Text(
                        subtitle,
                        size=11,
                        color=Q_MUTED,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        tooltip=subtitle,
                    ),
                ],
                spacing=1,
                tight=True,
            )

        return ft.Text(
            label,
            size=13,
            color=Q_TEXT,
            overflow=ft.TextOverflow.ELLIPSIS,
            tooltip=label,
        )

    def _dropdown_option(self, index, option):
        key = self._key_for_option(
            index,
            option,
        )

        label = self._option_label(option)

        self._key_to_option[key] = option

        if label not in self._label_to_key:
            self._label_to_key[label] = key

        # Los catálogos grandes de strings (CNO, CNAE, etc.)
        # usan la representación nativa más ligera posible.
        #
        # Esto evita crear miles de controles Text/Tooltip
        # innecesarios y reduce sensiblemente el trabajo del
        # motor de filtrado/renderizado de Flutter.
        if (
            self.large_dataset_mode
            and not isinstance(option, dict)
        ):
            return ft.DropdownOption(
                key=key,
                text=label,
            )

        return ft.DropdownOption(
            key=key,
            text=label,
            content=self._option_content(option),
        )

    def _set_menu_height(self, result_count):
        if result_count <= 0:
            visible_count = 1
        else:
            visible_count = min(
                result_count,
                self.visible_rows,
            )

        self.dropdown.menu_height = (
            visible_count * _RESULT_HEIGHT
        )

    def _set_dropdown_options(
        self,
        options,
        typed="",
        show_all=False,
    ):
        if show_all:
            matches = list(options)
        else:
            matches = self._matches(
                typed,
                show_all=False,
            )

        self._key_to_option = {}
        self._label_to_key = {}

        if not matches:
            self._set_menu_height(1)

            if self.show_empty and typed:
                self.dropdown.options = [
                    ft.DropdownOption(
                        key=_EMPTY_KEY,
                        text=self.empty_text,
                        content=ft.Text(
                            self.empty_text,
                            size=12,
                            color=Q_MUTED,
                            italic=True,
                        ),
                    )
                ]
            else:
                self.dropdown.options = []

            return

        self.dropdown.options = [
            self._dropdown_option(
                index,
                option,
            )
            for index, option in enumerate(matches)
        ]

        self._set_menu_height(
            len(matches)
        )

    def _on_focus(self, e=None):
        if self.input.disabled:
            return

        # Las opciones permanecen estables mientras el usuario escribe.
        # El filtrado lo realiza el Dropdown editable nativo de Flet,
        # evitando reconstrucciones que provocarían pérdida de foco.
        return

    def _on_blur(self, e=None):
        return

    def _dispatch_text_change(self, e=None):
        callback = self.input.on_change

        if callback:
            callback(e)

    def _on_change(self, e=None):
        typed = (
            getattr(
                getattr(e, "control", None),
                "text",
                None,
            )
            or self.dropdown.text
            or ""
        )

        self.value = typed
        self.selected_option = None

        if self.allow_free_text:
            self._emit_select(
                self.value
            )

        # IMPORTANTE:
        # No modificar dropdown.options ni ejecutar page.update()
        # durante la escritura.
        #
        # El Dropdown editable mantiene internamente el filtro y el
        # foco del editor. Reconstruir options aquí hace que Flutter
        # vuelva a montar el menú y pierda el foco en cada carácter.

    def _on_dropdown_select(self, e=None):
        key = (
            getattr(
                getattr(e, "control", None),
                "value",
                None,
            )
            or self.dropdown.value
        )

        if not key or key == _EMPTY_KEY:
            return

        selected = self._key_to_option.get(
            key
        )

        if selected is None:
            return

        # Importante:
        # se invoca self.select dinámicamente porque algunas vistas
        # sustituyen este método para añadir comportamiento propio.
        self.select(selected)

    def select(self, selected):
        self.selected_option = selected
        self.value = self._option_label(selected)

        if self.large_dataset_mode:
            self.search_bar.value = self.value
            self._large_visible_options = []

            self._emit_select(
                self.value
            )

            self._safe_update()
            return

        key = None

        for current_key, option in self._key_to_option.items():
            if option is selected or option == selected:
                key = current_key
                break

        if key is None:
            key = self._key_for_label(
                self.value
            )

        self.dropdown.value = key
        self.dropdown.text = self.value

        self._emit_select(
            self.value
        )

        self._safe_update()

    def set_options(
        self,
        options,
        clear_value=False,
    ):
        previous_large_mode = self.large_dataset_mode

        self.options = options or []
        self.large_dataset_mode = (
            len(self.options) >= _LARGE_DATASET_THRESHOLD
        )

        if clear_value:
            self.value = ""
            self.selected_option = None

        if self.large_dataset_mode:
            self._rebuild_large_search_index()

            self.search_bar.value = self.value

            self._refresh_large_results(
                self.value
            )

            if not previous_large_mode:
                self.control.content = self.search_bar
        else:
            self._set_dropdown_options(
                self.options,
                typed="",
                show_all=True,
            )

            self.dropdown.text = self.value
            self.dropdown.value = self._key_for_label(
                self.value
            )

            if previous_large_mode:
                self.control.content = self.dropdown

    def set_value(
        self,
        value,
        update=True,
    ):
        self.value = value or ""
        self.selected_option = None

        if self.large_dataset_mode:
            self.search_bar.value = self.value
            self._refresh_large_results(
                self.value
            )
        else:
            self._set_dropdown_options(
                self.options,
                typed="",
                show_all=True,
            )

            self.dropdown.text = self.value
            self.dropdown.value = self._key_for_label(
                self.value
            )

        if update:
            self._safe_update()

    def set_error(
        self,
        error_text=None,
        update=True,
    ):
        self._set_input_error(
            error_text
        )

        if update:
            self._safe_update()

    def set_disabled(
        self,
        disabled=True,
        update=True,
    ):
        self._set_input_disabled(
            disabled
        )

        if update:
            self._safe_update()

    def close_results(
        self,
        update=True,
    ):
        # El menú pertenece al Dropdown nativo y su apertura/cierre
        # la gestiona Flutter. Conservamos el método para mantener
        # el contrato público histórico.
        if update:
            self._safe_update()

    def clear(
        self,
        update=True,
    ):
        self.set_value(
            "",
            update=update,
        )

    def get_value(self):
        return self._input_value()

    def get_selected(self):
        return self.selected_option
