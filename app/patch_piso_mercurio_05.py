
"""
Patch mínimo: PISO Mercurio en formato "PISO 05".

Ejecutar desde la raíz del proyecto:

    python app/patch_piso_mercurio_05.py

Solo modifica app/run_presentacion_asistida.py para que:
- extPiso
- notPisoNotificacion

se escriban/seleccionen como:
    PISO 05

No toca sexo, estado civil, país, nacionalidad, municipio, localidad, tipo vía ni número.
"""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "app" / "run_presentacion_asistida.py"

HELPER = """
def format_piso_mercurio(value):
    \"""
    Convierte:
        5     -> PISO 05
        05    -> PISO 05
        5 C   -> PISO 05
        PISO 5 -> PISO 05
    \"""
    raw = "" if value is None else str(value).strip()
    if not raw:
        return ""

    m = re.search(r"\\\\d+", raw)
    if not m:
        return raw

    return "PISO " + m.group(0).zfill(2)


def set_piso_mercurio(browser, field_id, value=None, session_dir=None):
    \"""
    Fuerza el piso en formato exacto Mercurio: PISO 05.

    Si el campo es select, busca option por value/text:
        PISO 05
        05
        5
    Si es input, escribe:
        PISO 05
    \"""
    formatted = format_piso_mercurio(value)

    if not formatted:
        if session_dir:
            write_log(session_dir, f"VACIO piso {field_id}")
        return False

    num = formatted.replace("PISO ", "").strip()
    raw = "" if value is None else str(value).strip()

    script = f\"\"\"
    (function(){{
        const id = {json.dumps(field_id)};
        const formatted = {json.dumps(formatted)};
        const num = {json.dumps(num)};
        const raw = {json.dumps(raw)};

        const el = document.getElementById(id);
        if (!el) return {{ ok: false, reason: 'NO_EXISTE' }};

        function fire() {{
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            if (window.jQuery) window.jQuery(el).trigger('change');
        }}

        if (!el.options) {{
            el.value = formatted;
            fire();
            return {{ ok: true, mode: 'input', value: el.value }};
        }}

        const candidates = [formatted, num, String(parseInt(num, 10)), raw];

        for (const opt of el.options || []) {{
            const ov = (opt.value || '').toString().trim();
            const ot = (opt.textContent || opt.innerText || '').toString().trim();

            for (const candidate of candidates) {{
                if (ov === candidate || ot === candidate) {{
                    el.value = opt.value;
                    fire();
                    return {{ ok: true, mode: 'select_exact', selectedValue: opt.value, selectedText: ot, wanted: formatted }};
                }}
            }}
        }}

        // Fallback: buscar por contenido exacto del número con 2 dígitos en texto/value.
        for (const opt of el.options || []) {{
            const ov = (opt.value || '').toString().trim();
            const ot = (opt.textContent || opt.innerText || '').toString().trim();

            if (ov.includes(num) || ot.includes(num)) {{
                el.value = opt.value;
                fire();
                return {{ ok: true, mode: 'select_contains_num', selectedValue: opt.value, selectedText: ot, wanted: formatted }};
            }}
        }}

        return {{
            ok: false,
            reason: 'NO_MATCH_PISO_05',
            wanted: formatted,
            num: num,
            options: Array.from(el.options || []).map(o => [o.value, o.textContent]).slice(0, 120)
        }};
    }})();
    \"\"\"

    result = js(browser, script)
    if session_dir:
        write_log(session_dir, f"set_piso_mercurio {field_id} value={value!r} formatted={formatted!r} -> {result}")
    return result
"""

PISO_BRANCH = """        elif field_id in ("extPiso", "notPisoNotificacion"):
            set_piso_mercurio(browser, field_id, value=value, session_dir=session_dir)
"""


def main():
    if not RUNNER.exists():
        raise FileNotFoundError(f"No existe {RUNNER}")

    text = RUNNER.read_text(encoding="utf-8")

    backup = RUNNER.with_suffix(".py.bak_piso_mercurio_05")
    shutil.copy2(RUNNER, backup)

    # Quitar ramas anteriores de piso si existen.
    text = text.replace(
        '        elif field_id in ("extPiso", "notPisoNotificacion"):\n            select_piso_by_options(browser, field_id, value=value, session_dir=session_dir)\n',
        ''
    )
    text = text.replace(
        '        elif field_id in ("extPiso", "notPisoNotificacion"):\n            set_value(browser, field_id, value, session_dir=session_dir, trigger_change=True)\n',
        ''
    )
    text = text.replace(
        '        elif field_id in ("extPiso", "notPisoNotificacion"):\n            set_piso_mercurio(browser, field_id, value=value, session_dir=session_dir)\n',
        ''
    )

    if "def set_piso_mercurio(" not in text:
        if "\ndef fill_section(browser, values, session_dir):" not in text:
            raise RuntimeError("No encuentro fill_section()")
        text = text.replace(
            "\ndef fill_section(browser, values, session_dir):",
            HELPER + "\ndef fill_section(browser, values, session_dir):",
            1,
        )

    marker = '        elif field_id.startswith("extTipoVia") or field_id.startswith("notTipoVia"):'
    if marker in text:
        text = text.replace(marker, PISO_BRANCH + marker, 1)
    else:
        marker2 = "        else:\n            set_value(browser, field_id, value, session_dir=session_dir, trigger_change=True)"
        if marker2 not in text:
            raise RuntimeError("No encuentro punto de inserción para piso")
        text = text.replace(marker2, PISO_BRANCH + marker2, 1)

    RUNNER.write_text(text, encoding="utf-8")

    print("OK: piso Mercurio forzado a formato PISO 05")
    print(f"Backup creado: {backup}")


if __name__ == "__main__":
    main()
