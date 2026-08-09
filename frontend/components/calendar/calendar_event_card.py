import flet as ft


COLORS = {
    "TASK": {
        "bg": "#EEF6FF",
        "border": "#93C5FD",
        "fg": "#0057B8",
    },
    "ALERT": {
        "bg": "#FFF7E6",
        "border": "#FDBA74",
        "fg": "#B54708",
    },
}

Q_HIGHLIGHT_TASK = "#0057B8"
Q_HIGHLIGHT_ALERT = "#F79009"


PRIORITY_COLORS = {
    "BAJA": "#16A34A",
    "NORMAL": "#64748B",
    "ALTA": "#0057B8",
    "URGENTE": "#D92D20",
}


def _text(value):
    return str(value or "").strip()


def _time_label(value):
    raw = _text(value)

    if not raw:
        return ""

    try:
        return raw.split(" ", 1)[1][:5]
    except Exception:
        return ""


def calendar_event_card(
    item,
    on_click=None,
    highlighted=False,
):
    item_type = (
        _text(item.get("item_type"))
        .upper()
        or "TASK"
    )

    colors = COLORS.get(
        item_type,
        COLORS["TASK"],
    )

    priority = (
        _text(item.get("priority"))
        .upper()
        or "NORMAL"
    )

    title = (
        _text(item.get("title"))
        or "Sin título"
    )

    return ft.Container(
        height=24,
        bgcolor=(
            "#DCEEFF"
            if highlighted
            and item_type == "TASK"
            else (
                "#FFE8C7"
                if highlighted
                and item_type == "ALERT"
                else colors["bg"]
            )
        ),
        border=ft.border.all(
            (
                2
                if highlighted
                else 1
            ),
            (
                Q_HIGHLIGHT_TASK
                if highlighted
                and item_type == "TASK"
                else (
                    Q_HIGHLIGHT_ALERT
                    if highlighted
                    and item_type == "ALERT"
                    else colors["border"]
                )
            ),
        ),
        border_radius=7,
        padding=ft.padding.symmetric(
            horizontal=6,
            vertical=2,
        ),
        ink=True,
        on_click=on_click,
        content=ft.Row(
            controls=[
                ft.Text(
                    _time_label(
                        item.get("date")
                    ),
                    size=9,
                    color=colors["fg"],
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    title,
                    size=9,
                    color=colors["fg"],
                    weight=ft.FontWeight.W_600,
                    max_lines=1,
                    overflow=(
                        ft.TextOverflow.ELLIPSIS
                    ),
                    expand=True,
                ),
                ft.Text(
                    "●",
                    size=7,
                    color=PRIORITY_COLORS.get(
                        priority,
                        "#64748B",
                    ),
                ),
            ],
            spacing=4,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        ),
    )
