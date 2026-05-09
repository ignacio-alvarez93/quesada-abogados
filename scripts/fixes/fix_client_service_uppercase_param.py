from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
CLIENT_SERVICE = ROOT / "backend" / "services" / "client_service.py"

if not CLIENT_SERVICE.exists():
    raise FileNotFoundError(f"No existe: {CLIENT_SERVICE}")

backup = CLIENT_SERVICE.with_suffix(".py.fix_uppercase_param.bak")
shutil.copy2(CLIENT_SERVICE, backup)
print(f"Backup creado: {backup}")

text = CLIENT_SERVICE.read_text(encoding="utf-8")

# Elimina inserciones incorrectas anteriores.
text = text.replace("    client_data = normalize_client_data(client_data)\n", "")


def insert_normalization_for_function(source, function_name):
    pattern = re.compile(rf"(def\s+{function_name}\s*\(([^)]*)\):\n)")
    match = pattern.search(source)

    if not match:
        print(f"No se encontró {function_name}()")
        return source

    params_raw = match.group(2)
    params = [p.strip().split("=")[0].strip() for p in params_raw.split(",") if p.strip()]

    if not params:
        print(f"No se detectaron parámetros en {function_name}()")
        return source

    if function_name == "create_client":
        data_param = params[0]
    elif function_name == "update_client":
        data_param = params[1] if len(params) > 1 else params[0]
    else:
        data_param = params[-1]

    start = match.end()
    preview = source[start:start + 300]

    expected_line = f"    {data_param} = normalize_client_data({data_param})\n"

    if expected_line in preview:
        print(f"{function_name}() ya estaba correcto.")
        return source

    return source[:start] + expected_line + source[start:]


text = insert_normalization_for_function(text, "create_client")
text = insert_normalization_for_function(text, "update_client")

CLIENT_SERVICE.write_text(text, encoding="utf-8")

print("client_service.py corregido.")
print("Ejecuta ahora:")
print("python -m app.main")
