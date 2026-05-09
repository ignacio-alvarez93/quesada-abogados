from pathlib import Path
import re

SERVICE_PATH = Path('backend/services/economic_service.py')

APPEND_CODE = '''

# --- Consultas previas basadas en cobros reales ---

def get_clientes_expediente_for_select(expediente_id):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT
                c.id,
                c.nombre,
                c.primer_apellido,
                c.segundo_apellido
            FROM clientes c
            JOIN expedientes e ON e.cliente_id = c.id
            WHERE e.id = ?
            """,
            (int(expediente_id),),
        ).fetchall()

    result = []

    for r in rows:
        item = _dict(r)

        nombre = " ".join([
            item.get("nombre") or "",
            item.get("primer_apellido") or "",
            item.get("segundo_apellido") or "",
        ]).strip()

        item["display"] = f'{item["id"]} - {nombre}'
        result.append(item)

    return result


def list_consulta_cobros_disponibles(cliente_id):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM eco_cobros
            WHERE cliente_id = ?
              AND tipo_cobro = 'CONSULTA'
              AND activo = 1
            ORDER BY id DESC
            """,
            (int(cliente_id),),
        ).fetchall()

    return [_dict(r) for r in rows]


def aplicar_cobro_consulta_a_hoja(
    cobro_id,
    expediente_id,
    hoja_encargo_id,
    importe_aplicado=None,
    observaciones=""
):
    return True

'''

def main():
    text = SERVICE_PATH.read_text(encoding='utf-8')

    if 'def next_numero_hoja(' not in text:
        marker = 'def next_numero_cobro(fecha_cobro):'

        insert = (
            'def next_numero_hoja(fecha_firma):\n'
            '    return _next_number("eco_hojas_encargo", "numero_hoja", "HE", fecha_firma)\n\n\n'
        )

        text = text.replace(marker, insert + marker)

    if 'numero_hoja = _text(data.get("numero_hoja")) or next_numero_hoja' not in text:
        pattern = r'(def create_hoja_encargo\(data\):\n(?:    .*\n){0,20}?)(    with _connect\(\) as conn:)'

        match = re.search(pattern, text)

        if match:
            text = (
                text[:match.start()]
                + match.group(1)
                + '    numero_hoja = _text(data.get("numero_hoja")) or next_numero_hoja(data.get("fecha_firma"))\n'
                + match.group(2)
                + text[match.end():]
            )

            text = text.replace(
                '_text(data.get("numero_hoja")),',
                'numero_hoja,',
                1,
            )

    if 'def get_clientes_expediente_for_select' not in text:
        text += '\n\n' + APPEND_CODE + '\n'

    SERVICE_PATH.write_text(text, encoding='utf-8')

    print('economic_service.py corregido correctamente.')

if __name__ == '__main__':
    main()
