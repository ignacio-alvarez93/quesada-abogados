from pathlib import Path
import re
import shutil


ROOT = Path(__file__).resolve().parent
CLIENTS_VIEW = ROOT / "frontend" / "views" / "clients_view.py"
CLIENT_SERVICE = ROOT / "backend" / "services" / "client_service.py"


def backup(path):
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    print(f"Backup creado: {backup_path}")


def patch_clients_view():
    if not CLIENTS_VIEW.exists():
        raise FileNotFoundError(f"No existe {CLIENTS_VIEW}")

    text = CLIENTS_VIEW.read_text(encoding="utf-8")
    original = text

    if "from frontend.components.app_autocomplete import AppAutocomplete" not in text:
        if "from frontend.components.client_context_panel import client_context_panel\n" in text:
            text = text.replace(
                "from frontend.components.client_context_panel import client_context_panel\n",
                "from frontend.components.client_context_panel import client_context_panel\n"
                "from frontend.components.app_autocomplete import AppAutocomplete\n",
            )
        elif "import flet as ft\n" in text:
            text = text.replace(
                "import flet as ft\n",
                "import flet as ft\nfrom frontend.components.app_autocomplete import AppAutocomplete\n",
                1,
            )

    text = re.sub(
        r'nacionalidad\s*=\s*select_input\("Nacionalidad",\s*dropdown_values\(nacionalidad_options\),\s*width=260\)',
        'nacionalidad_autocomplete = AppAutocomplete(\n'
        '        page=page,\n'
        '        label="Nacionalidad",\n'
        '        options=nacionalidad_options,\n'
        '        width=260,\n'
        '        max_results=8,\n'
        '    )',
        text,
    )

    text = re.sub(
        r'pais_nacimiento\s*=\s*select_input\("País nacimiento",\s*dropdown_values\(pais_options\),\s*width=260\)',
        'pais_nacimiento_autocomplete = AppAutocomplete(\n'
        '        page=page,\n'
        '        label="País nacimiento",\n'
        '        options=pais_options,\n'
        '        width=260,\n'
        '        max_results=8,\n'
        '    )',
        text,
    )

    text = text.replace("            nacionalidad,\n", "")
    text = text.replace("            pais_nacimiento,\n", "")

    if "nacionalidad_autocomplete.set_value(\"\", update=False)" not in text:
        text = text.replace(
            '        estado_cliente.value = "Asesoramiento inicial"\n',
            '        estado_cliente.value = "Asesoramiento inicial"\n'
            '        nacionalidad_autocomplete.set_value("", update=False)\n'
            '        pais_nacimiento_autocomplete.set_value("", update=False)\n',
            1,
        )

    text = re.sub(
        r'set_dropdown_options\(nacionalidad,\s*nacionalidad_options,\s*cliente.get\("nacionalidad"\)\s*or\s*""\)',
        'nacionalidad_autocomplete.set_value(cliente.get("nacionalidad") or "", update=False)',
        text,
    )

    text = re.sub(
        r'set_dropdown_options\(pais_nacimiento,\s*pais_options,\s*cliente.get\("pais_nacimiento"\)\s*or\s*""\)',
        'pais_nacimiento_autocomplete.set_value(cliente.get("pais_nacimiento") or "", update=False)',
        text,
    )

    text = text.replace(
        '"nacionalidad": nacionalidad.value,',
        '"nacionalidad": nacionalidad_autocomplete.get_value(),',
    )

    text = text.replace(
        '"pais_nacimiento": pais_nacimiento.value,',
        '"pais_nacimiento": pais_nacimiento_autocomplete.get_value(),',
    )

    text = text.replace(
        "ft.Row([nacionalidad, fecha_nacimiento, telefono], wrap=True, spacing=10),",
        "ft.Row([nacionalidad_autocomplete.control, fecha_nacimiento, telefono], wrap=True, spacing=10),",
    )
    text = text.replace(
        "ft.Row([nacionalidad, fecha_nacimiento, telefono], wrap=True),",
        "ft.Row([nacionalidad_autocomplete.control, fecha_nacimiento, telefono], wrap=True),",
    )

    text = text.replace(
        "ft.Row([localidad_nacimiento, pais_nacimiento], wrap=True, spacing=10),",
        "ft.Row([localidad_nacimiento, pais_nacimiento_autocomplete.control], wrap=True, spacing=10),",
    )
    text = text.replace(
        "ft.Row([localidad_nacimiento, pais_nacimiento], wrap=True),",
        "ft.Row([localidad_nacimiento, pais_nacimiento_autocomplete.control], wrap=True),",
    )

    if text == original:
        print("clients_view.py: no se detectaron cambios pendientes.")
    else:
        backup(CLIENTS_VIEW)
        CLIENTS_VIEW.write_text(text, encoding="utf-8")
        print("clients_view.py actualizado.")


NORMALIZER_CODE = r