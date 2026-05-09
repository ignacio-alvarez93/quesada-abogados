from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
CLIENTS_VIEW = ROOT / "frontend" / "views" / "clients_view.py"

if not CLIENTS_VIEW.exists():
    raise FileNotFoundError(f"No existe: {CLIENTS_VIEW}")

backup = CLIENTS_VIEW.with_suffix(".py.autocomplete_fix.bak")
shutil.copy2(CLIENTS_VIEW, backup)

text = CLIENTS_VIEW.read_text(encoding="utf-8")

replacements = [
    (
        'ft.Row([nacionalidad, fecha_nacimiento, telefono], wrap=True, spacing=10),',
        'ft.Row([nacionalidad_autocomplete.control, fecha_nacimiento, telefono], wrap=True, spacing=10),'
    ),
    (
        'ft.Row([nacionalidad, fecha_nacimiento, telefono], wrap=True),',
        'ft.Row([nacionalidad_autocomplete.control, fecha_nacimiento, telefono], wrap=True),'
    ),
    (
        'ft.Row([localidad_nacimiento, pais_nacimiento], wrap=True, spacing=10),',
        'ft.Row([localidad_nacimiento, pais_nacimiento_autocomplete.control], wrap=True, spacing=10),'
    ),
    (
        'ft.Row([localidad_nacimiento, pais_nacimiento], wrap=True),',
        'ft.Row([localidad_nacimiento, pais_nacimiento_autocomplete.control], wrap=True),'
    ),
    (
        'set_dropdown_options(nacionalidad, nacionalidad_options, cliente.get("nacionalidad") or "")',
        'nacionalidad_autocomplete.set_value(cliente.get("nacionalidad") or "", update=False)'
    ),
    (
        'set_dropdown_options(pais_nacimiento, pais_options, cliente.get("pais_nacimiento") or "")',
        'pais_nacimiento_autocomplete.set_value(cliente.get("pais_nacimiento") or "", update=False)'
    ),
    (
        '            nacionalidad,\n',
        ''
    ),
    (
        '            pais_nacimiento,\n',
        ''
    ),
]

for old, new in replacements:
    text = text.replace(old, new)

if 'nacionalidad_autocomplete.set_value("", update=False)' not in text:
    marker = '        estado_cliente.value = "Asesoramiento inicial"\n'
    replacement = (
        '        estado_cliente.value = "Asesoramiento inicial"\n'
        '        nacionalidad_autocomplete.set_value("", update=False)\n'
        '        pais_nacimiento_autocomplete.set_value("", update=False)\n'
    )
    text = text.replace(marker, replacement, 1)

CLIENTS_VIEW.write_text(text, encoding="utf-8")

print("Fix aplicado correctamente.")
print(f"Backup: {backup}")
print("Ahora ejecuta:")
print("python -m app.main")
