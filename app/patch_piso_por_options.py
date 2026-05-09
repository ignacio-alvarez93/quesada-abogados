
"""
Patch: piso por options Mercurio.

Ejecutar desde la raíz del proyecto:

    python app/patch_piso_por_options.py

Qué hace:
- Modifica app/run_presentacion_asistida.py
- Añade select_piso_by_options()
- Hace que extPiso y notPisoNotificacion se seleccionen leyendo las <option> reales de Mercurio.
- No toca sexo, estado civil, país, nacionalidad, municipio, localidad, tipo vía ni número.
"""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "app" / "run_presentacion_asistida.py"

HELPER = """
def select_piso_by_options(browser, field_id, value=None, session_dir=None):
    \"""
    Selecciona piso leyendo las <option> reales de Mercurio.

    Casos:
        JSON: "5"    -> option "05"
        JSON: "05"   -> option "05"
        JSON: "5 C"  -> option "05"

    Si el campo no es select, escribe el piso a 2 dígitos.
    \"""
    raw = "" if value is None else str(value).strip()
    if not raw:
        if session_dir:
            write_log(session_dir, f"VACIO piso {field_id}")
        return False

    m = re.search(r"\\d+", raw)
    wanted_num = m.group(0) if m else raw

    try:
        wanted_int = int(wanted_num)
    except Exception:
        wanted_int = None

    script = f\"\"\"
    (function(){{
        const id = {json.dumps(field_id)};
        const raw = {json.dumps(raw)};
        const wantedNum = {json.dumps(wanted_num)};
        const wantedInt = {json.dumps(wanted_int)};

        const el = document.getElementById(id);
        if (!el) return {{ ok: false, reason: 'NO_EXISTE' }};

        function fire() {{
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            if (window.jQuery) window.jQuery(el).trigger('change');
        }}

        const z2 = wantedInt !== null ? String(wantedInt).padStart(2, '0') : raw;

        if (!el.options) {{
            el.value = z2;
            fire();
            return {{ ok: true, mode: 'input', value: el.value }};
        }}

        for (const opt of el.options || []) {{
            const ov = (opt.value || '').toString().trim();
            const ot = (opt.textContent || opt.innerText || '').toString().trim();

            const ovNum = ov.match(/\\\\d+/);
            const otNum = ot.match(/\\\\d+/);

            if (wantedInt !== null) {{
                if (ovNum && parseInt(ovNum[0], 10) === wantedInt) {{
                    el.value = opt.value;
                    fire();
                    return {{ ok: true, mode: 'select_value_num', selectedValue: opt.value, selectedText: ot }};
                }}

                if (otNum && parseInt(otNum[0], 10) === wantedInt) {{
                    el.value = opt.value;
                    fire();
                    return {{ ok: true, mode: 'select_text_num', selectedValue: opt.value, selectedText: ot }};
                }}
            }}
        }}

        for (const opt of el.options || []) {{
            const ov = (opt.value || '').toString().trim();
            const ot = (opt.textContent || opt.innerText || '').toString().trim();

            if (ov === z2 || ot === z2 || ov === raw || ot === raw || ov === wantedNum || ot === wantedNum) {{
                el.value = opt.value;
                fire();
                return {{ ok: true, mode: 'select_exact', selectedValue: opt.value, selectedText: ot }};
            }}
        }}

        return {{
            ok: false,
            reason: 'NO_MATCH_PISO',
            raw: raw,
            wantedNum: wantedNum,
            z2: z2,
            options: Array.from(el.options || []).map(o => [o.value, o.textContent]).slice(0, 80)
        }};
    }})();
    \"\"\"

    result = js(browser, script)
    if session_dir:
        write_log(session_dir, f"select_piso {field_id} raw={raw!r} -> {result}")
    return result
"""

PISO_BRANCH = """        elif field_id in ("extPiso", "notPisoNotificacion"):
            select_piso_by_options(browser, field_id, value=value, session_dir=session_dir)
"""


def main():
    if not RUNNER.exists():
        raise FileNotFoundError(f"No existe {RUNNER}")

    text = RUNNER.read_text(encoding="utf-8")

    backup = RUNNER.with_suffix(".py.bak_piso_options")
    shutil.copy2(RUNNER, backup)

    if "def select_piso_by_options(" not in text:
        if "\ndef fill_section(browser, values, session_dir):" not in text:
            raise RuntimeError("No encuentro fill_section() para insertar helper")
        text = text.replace(
            "\ndef fill_section(browser, values, session_dir):",
            HELPER + "\ndef fill_section(browser, values, session_dir):",
            1,
        )

    if 'field_id in ("extPiso", "notPisoNotificacion")' not in text:
        marker = '        elif field_id.startswith("extTipoVia") or field_id.startswith("notTipoVia"):'
        if marker in text:
            text = text.replace(marker, PISO_BRANCH + marker, 1)
        else:
            marker2 = "        else:\\n            set_value(browser, field_id, value, session_dir=session_dir, trigger_change=True)"
            if marker2 not in text:
                raise RuntimeError("No encuentro punto de inserción para rama de piso")
            text = text.replace(marker2, PISO_BRANCH + marker2, 1)

    RUNNER.write_text(text, encoding="utf-8")

    print("OK: piso por options aplicado")
    print(f"Backup creado: {backup}")


if __name__ == "__main__":
    main()
