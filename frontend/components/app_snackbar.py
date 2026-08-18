import flet as ft


_SNACKBAR_STYLES = {
    "success": (
        "#ECFDF3",
        "#027A48",
        ft.Icons.CHECK_CIRCLE_OUTLINE,
    ),
    "error": (
        "#FEF3F2",
        "#B42318",
        ft.Icons.ERROR_OUTLINE,
    ),
    "warning": (
        "#FFFAEB",
        "#B54708",
        ft.Icons.WARNING_AMBER_ROUNDED,
    ),
    "info": (
        "#EFF8FF",
        "#175CD3",
        ft.Icons.INFO_OUTLINE,
    ),
}


def build_snackbar(
    message,
    *,
    severity="info",
):
    """
    Construye un SnackBar visual reutilizable del ERP.

    No contiene lógica de dominio.
    """
    normalized = str(
        severity
        or "info"
    ).strip().lower()

    if normalized not in _SNACKBAR_STYLES:
        normalized = "info"

    bgcolor, foreground, icon = (
        _SNACKBAR_STYLES[
            normalized
        ]
    )

    return ft.SnackBar(
        content=ft.Row(
            controls=[
                ft.Icon(
                    icon,
                    size=20,
                    color=foreground,
                ),
                ft.Text(
                    str(
                        message
                        or ""
                    ),
                    size=12,
                    weight=ft.FontWeight.W_600,
                    color=foreground,
                    expand=True,
                ),
            ],
            spacing=10,
            vertical_alignment=(
                ft.CrossAxisAlignment.CENTER
            ),
        ),
        bgcolor=bgcolor,
        behavior=ft.SnackBarBehavior.FLOATING,
        show_close_icon=True,
        close_icon_color=foreground,
        elevation=6,
        margin=ft.Margin.all(
            16
        ),
        padding=ft.Padding.symmetric(
            horizontal=14,
            vertical=12,
        ),
    )


def show_snackbar(
    page,
    message,
    *,
    severity="info",
):
    """
    Muestra el SnackBar usando la API actual de Flet.

    Mantiene fallback para callers/versiones que todavía
    trabajen mediante page.snack_bar.
    """
    snackbar = build_snackbar(
        message,
        severity=severity,
    )

    show_dialog = getattr(
        page,
        "show_dialog",
        None,
    )

    if callable(
        show_dialog
    ):
        show_dialog(
            snackbar
        )

        return snackbar

    page.snack_bar = snackbar
    snackbar.open = True

    updater = getattr(
        page,
        "update",
        None,
    )

    if callable(
        updater
    ):
        updater()

    return snackbar
