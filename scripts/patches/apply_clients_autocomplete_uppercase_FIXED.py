from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
CLIENTS_VIEW = ROOT / 'frontend' / 'views' / 'clients_view.py'
CLIENT_SERVICE = ROOT / 'backend' / 'services' / 'client_service.py'


def backup(path):
    backup_path = path.with_suffix(path.suffix + '.bak')
    shutil.copy2(path, backup_path)
    print(f'Backup creado: {backup_path}')


def patch_clients_view():
    if not CLIENTS_VIEW.exists():
        raise FileNotFoundError(f'No existe {CLIENTS_VIEW}')

    text = CLIENTS_VIEW.read_text(encoding='utf-8')
    original = text

    if 'from frontend.components.app_autocomplete import AppAutocomplete' not in text:
        marker = 'from frontend.components.client_context_panel import client_context_panel\n'
        if marker in text:
            text = text.replace(
                marker,
                marker + 'from frontend.components.app_autocomplete import AppAutocomplete\n'
            )

    replacement_nac = """nacionalidad_autocomplete = AppAutocomplete(
        page=page,
        label='Nacionalidad',
        options=nacionalidad_options,
        width=260,
        max_results=8,
    )"""

    replacement_pais = """pais_nacimiento_autocomplete = AppAutocomplete(
        page=page,
        label='País nacimiento',
        options=pais_options,
        width=260,
        max_results=8,
    )"""

    text = re.sub(
        r'nacionalidad\s*=\s*select_input\("Nacionalidad",\s*dropdown_values\(nacionalidad_options\),\s*width=260\)',
        replacement_nac,
        text,
    )

    text = re.sub(
        r'pais_nacimiento\s*=\s*select_input\("País nacimiento",\s*dropdown_values\(pais_options\),\s*width=260\)',
        replacement_pais,
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

    if text != original:
        backup(CLIENTS_VIEW)
        CLIENTS_VIEW.write_text(text, encoding='utf-8')
        print('clients_view.py actualizado.')
    else:
        print('clients_view.py ya estaba actualizado.')


NORMALIZER_CODE = """

UPPERCASE_CLIENT_FIELDS = {
    'nombre',
    'primer_apellido',
    'segundo_apellido',
    'nie',
    'pasaporte',
    'dni',
    'nacionalidad',
    'estado_cliente',
    'domicilio_espana',
    'localidad',
    'provincia',
    'codigo_postal',
    'localidad_nacimiento',
    'pais_nacimiento',
    'nombre_padre',
    'nombre_madre',
    'estado_civil',
    'observaciones',
    'observaciones_internas',
}


def normalize_upper(value):
    if value is None:
        return ''
    return str(value).strip().upper()


def normalize_client_data(data):
    normalized = dict(data)

    for field in UPPERCASE_CLIENT_FIELDS:
        if field in normalized:
            normalized[field] = normalize_upper(normalized.get(field))

    if 'email' in normalized:
        normalized['email'] = (normalized.get('email') or '').strip().lower()

    if 'telefono' in normalized:
        normalized['telefono'] = (normalized.get('telefono') or '').strip()

    return normalized

"""


def patch_client_service():
    if not CLIENT_SERVICE.exists():
        raise FileNotFoundError(f'No existe {CLIENT_SERVICE}')

    text = CLIENT_SERVICE.read_text(encoding='utf-8')
    original = text

    if 'def normalize_client_data(' not in text:
        text = NORMALIZER_CODE + '\n' + text

    for function_name in ['create_client', 'update_client']:
        pattern = rf'(def\s+{function_name}\s*\([^)]*\):\n)'
        match = re.search(pattern, text)

        if match:
            start = match.end()
            preview = text[start:start + 200]

            if 'normalize_client_data' not in preview:
                text = text[:start] + '    client_data = normalize_client_data(client_data)\n' + text[start:]

    if text != original:
        backup(CLIENT_SERVICE)
        CLIENT_SERVICE.write_text(text, encoding='utf-8')
        print('client_service.py actualizado.')
    else:
        print('client_service.py ya estaba actualizado.')


def main():
    patch_clients_view()
    patch_client_service()

    print('')
    print('Actualización completada.')
    print('Ejecuta:')
    print('python -m app.main')


if __name__ == '__main__':
    main()
