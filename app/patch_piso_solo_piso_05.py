
"""
Patch mínimo: seleccionar SOLO "PISO 05", nunca "ATICO 05".

Ejecutar desde la raíz del proyecto:

    python app/patch_piso_solo_piso_05.py

Solo modifica app/run_presentacion_asistida.py:
- extPiso
- notPisoNotificacion

Prioridad:
1) option text/value EXACTO = "PISO 05"
2) option text/value empieza por "PISO" y contiene "05"
3) si input, escribe "PISO 05"

No usa fallback genérico por número para evitar coger "ATICO 05".
"""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "app" / "run_presentacion_asistida.py"

HELPER = """
def format_piso_mercurio(value):
    raw = "" if value is None else str(value).strip()
    if not raw:
        return ""

    m = re.search(r"\\\\d+", raw)
    if not m:
        return raw

    return "PISO " + m.group(0).zfill(2)


def set_piso_mercurio(browser, field_id, value=None, session_dir=None):
    \"""
    Fuerza selección estricta de PISO XX.
    Evita seleccionar ATICO 05, BAJO 05, etc.
    \"""
    formatted = format_piso_mercurio(value)

    if not formatted:
        if session_dir:
            write_log(session_dir, f"VACIO piso {field_id}")
        return False

    num = formatted.replace("PISO ", "").strip()

    script = f\"\"\"
    (function(){{
        const id = {json.dumps(field_id)};
        const formatted = {json.dumps(formatted)};
        const num = {json.dumps(num)};

        const el = document.getElementById(id);
        if (!el) return {{ ok: false, reason: 'NO_EXISTE' }};

        function norm(v) {{
            return (v || '').toString().trim().toUpperCase()
                .normalize('NFD').replace(/[\\\\u0300-\\\\u036f]/g, '')
                .replace(/\\\\s+/g, ' ');
        }}

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

        const wanted = norm(formatted);

        // 1) EXACTO: value/text = PISO 05
        for (const opt of el.options || []) {{
            const ov = norm(opt.value);
            const ot = norm(opt.textContent || opt.innerText || '');
            if (ov === wanted || ot === wanted) {{
                el.value = opt.value;
                fire();
                return {{ ok: true, mode: 'exact_piso', selectedValue: opt.value, selectedText: opt.textContent, wanted: formatted }};
            }}
        }}

        // 2) ESTRICTO: debe empezar por PISO y contener 05
        for (const opt of el.options || []) {{
            const ov = norm(opt.value);
            const ot = norm(opt.textContent || opt.innerText || '');

            if ((ov.startsWith('PISO') && ov.includes(num)) || (ot.startsWith('PISO') && ot.includes(num))) {{
                el.value = opt.value;
                fire();
                return {{ ok: true, mode: 'strict_piso_contains', selectedValue: opt.value, selectedText: opt.textContent, wanted: formatted }};
            }}
        }}

        // 3) Último fallback: si hay option con value 05 y texto PISO.
        for (const opt of el.options || []) {{
            const ov = norm(opt.value);
            const ot = norm(opt.textContent || opt.innerText || '');

            if ((ov === num || ov === String(parseInt(num, 10))) && ot.startsWith('PISO')) {{
                el.value = opt.value;
                fire();
                return {{ ok: true, mode: 'value_num_text_piso', selectedValue: opt.value, selectedText: opt.textContent, wanted: formatted }};
            }}
        }}

        return {{
            ok: false,
            reason: 'NO_MATCH_PISO_ESTRICTO',
            wanted: formatted,
            num: num,
            options: Array.from(el.options || []).map(o => [o.value, o.textContent]).slice(0, 160)
        }};
    }})();
    \"\"\"

    result = js(browser, script)
    if session_dir:
        write_log(session_dir, f"set_piso_mercurio_STRICT {field_id} value={value!r} formatted={formatted!r} -> {result}")
    return result
"""

PISO_BRANCH = """        elif field_id in ("extPiso", "notPisoNotificacion"):
            set_piso_mercurio(browser, field_id, value=value, session_dir=session_dir)
"""


def remove_old_piso_branches(text):
    patterns = [
        '        elif field_id in ("extPiso", "notPisoNotificacion"):\n            select_piso_by_options(browser, field_id, value=value, session_dir=session_dir)\n',
        '        elif field_id in ("extPiso", "notPisoNotificacion"):\n            set_value(browser, field_id, value, session_dir=session_dir, trigger_change=True)\n',
        '        elif field_id in ("extPiso", "notPisoNotificacion"):\n            set_piso_mercurio(browser, field_id, value=value, session_dir=session_dir)\n',
    ]
    for p in patterns:
        text = text.replace(p, "")
    return text


def replace_helper(text):
    start = text.find("\ndef format_piso_mercurio(")
    if start == -1:
        return text

    end = text.find("\ndef fill_section(browser, values, session_dir):", start)
    if end == -1:
        return text

    return text[:start] + "\n" + HELPER + text[end:]


def main():
    if not RUNNER.exists():
        raise FileNotFoundError(f"No existe {RUNNER}")

    text = RUNNER.read_text(encoding="utf-8")

    backup = RUNNER.with_suffix(".py.bak_piso_solo_piso_05")
    shutil.copy2(RUNNER, backup)

    # Reemplazar helper anterior si existe.
    if "def format_piso_mercurio(" in text:
        text = replace_helper(text)
    elif "def set_piso_mercurio(" not in text:
        if "\ndef fill_section(browser, values, session_dir):" not in text:
            raise RuntimeError("No encuentro fill_section()")
        text = text.replace(
            "\ndef fill_section(browser, values, session_dir):",
            HELPER + "\ndef fill_section(browser, values, session_dir):",
            1,
        )

    text = remove_old_piso_branches(text)

    marker = '        elif field_id.startswith("extTipoVia") or field_id.startswith("notTipoVia"):'
    if marker in text:
        text = text.replace(marker, PISO_BRANCH + marker, 1)
    else:
        marker2 = "        else:\n            set_value(browser, field_id, value, session_dir=session_dir, trigger_change=True)"
        if marker2 not in text:
            raise RuntimeError("No encuentro punto de inserción para piso")
        text = text.replace(marker2, PISO_BRANCH + marker2, 1)

    RUNNER.write_text(text, encoding="utf-8")

    print("OK: piso estricto aplicado. Ahora prioriza SOLO PISO 05, no ATICO 05.")
    print(f"Backup creado: {backup}")


if __name__ == "__main__":
    main()
