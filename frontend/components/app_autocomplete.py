import unicodedata
import flet as ft

Q_PRIMARY = "#0057B8"
Q_BORDER = "#CBD5E1"
Q_FOCUSED = "#18BFEA"
Q_TEXT = "#101828"
Q_MUTED = "#64748B"
Q_RESULT_BG = "#FFFFFF"


def _normalize(value):
    value = value or ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower().strip()


class AppAutocomplete:
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
    ):
        self.page = page
        self.label = label
        self.options = options or []
        self.value = value or ""
        self.width = width
        self.visible_rows = max_results or 8
        self.on_select = on_select
        self.allow_free_text = allow_free_text

        self.input = ft.TextField(
            label=label,
            value=self.value,
            width=width,
            border_radius=10,
            border_color=Q_BORDER,
            focused_border_color=Q_FOCUSED,
            cursor_color=Q_PRIMARY,
            content_padding=ft.padding.symmetric(horizontal=14, vertical=12),
            on_change=self._on_change,
            on_focus=self._on_focus,
        )

        self.results_list = ft.ListView(
            controls=[],
            spacing=0,
            padding=0,
            height=self.visible_rows * 38,
            auto_scroll=False,
        )

        self.results_box = ft.Container(
            content=self.results_list,
            bgcolor=Q_RESULT_BG,
            border=ft.border.all(1, Q_BORDER),
            border_radius=10,
            padding=0,
            width=width,
            height=self.visible_rows * 38,
            visible=False,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
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

    def _on_focus(self, e=None):
        self._refresh_results(self.input.value or "", show_all=True)
        self.page.update()

    def _on_change(self, e=None):
        typed = self.input.value or ""
        self.value = typed

        if self.allow_free_text and self.on_select:
            self.on_select(self.value)

        self._refresh_results(typed, show_all=False)
        self.page.update()

    def _matches(self, typed, show_all=False):
        if show_all and not typed:
            return list(self.options)

        query = _normalize(typed)

        if not query:
            return []

        matches = []

        for option in self.options:
            if query in _normalize(option):
                matches.append(option)

        return matches

    def _refresh_results(self, typed, show_all=False):
        matches = self._matches(typed, show_all=show_all)

        self.results_list.controls.clear()

        if not matches:
            self.results_box.visible = False
            return

        for option in matches:
            self.results_list.controls.append(self._result_item(option))

        self.results_box.visible = True

    def _result_item(self, option):
        return ft.Container(
            content=ft.Text(
                option,
                size=13,
                color=Q_TEXT,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            bgcolor=Q_RESULT_BG,
            border=ft.border.only(
                bottom=ft.BorderSide(1, "#EEF2F7"),
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=9),
            ink=True,
            on_click=lambda e, selected=option: self.select(selected),
        )

    def select(self, selected):
        self.value = selected or ""
        self.input.value = self.value
        self.results_list.controls.clear()
        self.results_box.visible = False

        if self.on_select:
            self.on_select(self.value)

        self.page.update()

    def set_options(self, options, clear_value=False):
        self.options = options or []

        if clear_value:
            self.set_value("", update=False)

        self.results_list.controls.clear()
        self.results_box.visible = False

    def set_value(self, value, update=True):
        self.value = value or ""
        self.input.value = self.value
        self.results_list.controls.clear()
        self.results_box.visible = False

        if update:
            self.page.update()

    def get_value(self):
        return self.input.value or ""
