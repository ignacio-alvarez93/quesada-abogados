from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
CLIENTS_VIEW = ROOT / "frontend" / "views" / "clients_view.py"

if not CLIENTS_VIEW.exists():
    raise FileNotFoundError(f"No existe {CLIENTS_VIEW}")

backup = CLIENTS_VIEW.with_suffix(CLIENTS_VIEW.suffix + ".fix_autocomplete_rows.bak")
shutil.copy2(CLIENTS_VIEW, backup)
print(f"Backup creado: {backup}")

text = CLIENTS_VIEW.read_text(encoding="utf-8")

replacements = {
    "ft.Row([nacionalidad, fecha_nacimiento, telefono], wrap=True, spacing=10),":
        "ft.Row([nacionalidad_autocomplete.control, fecha_nacimiento, telefono], wrap=True, spacing=10),",
    "ft.Row([nacionalidad, fecha_nacimiento, telefono], wrap=True),":
        "ft.Row([nacionalidad_autocomplete.control, fecha_nacimiento, telefono], wrap=True),",
    "ft.Row([localidad_nacimiento, pais_nacimiento], wrap=True, spacing=10),":
        "ft.Row([localidad_nacimiento, pais_nacimiento_autocomplete.control], wrap=True, spacing=10),",
    "ft.Row([localidad_nacimiento, pais_nacimiento], wrap=True),":
        "ft.Row([localidad_nacimiento, pais_nacimiento_autocomplete.control], wrap=True),",
    "set_dropdown_options(nacionalidad, nacionalidad_options, cliente.get("nacionalidad") or "")":
        "nacionalidad_autocomplete.set_value(cliente.get("nacionalidad") or "", update=False)",
    "set_dropdown_options(pais_nacimiento, pais_options, cliente.get("pais_nacimiento") or "")":
        "pais_nacimiento_autocomplete.set_value(cliente.get("pais_nacimiento") or "", update=False)",
}

for old, new in replacements.items():
    text = text.replace(old, new)

# Remove old fields from limpiar_formulario loop if they remained.
text = text.replace("            nacionalidad,\n", "")
text = text.replace("            pais_nacimiento,\n", "")

# Ensure limpiar_formulario resets autocomplete values.
if "nacionalidad_autocomplete.set_value("", update=False)" not in text:
    text = text.replace(
        '        estado_cliente.value = "Asesoramiento inicial"\n',
        '        estado_cliente.value = "Asesoramiento inicial"\n'
        '        nacionalidad_autocomplete.set_value("", update=False)\n'
        '        pais_nacimiento_autocomplete.set_value("", update=False)\n',
        1,
    )

CLIENTS_VIEW.write_text(text, encoding="utf-8")
print("clients_view.py corregido.")
print("Ejecuta: python -m app.main")
