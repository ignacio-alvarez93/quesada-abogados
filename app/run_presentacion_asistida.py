"""
Lanzador externo de Presentación Asistida Mercurio.

Versión ampliada:
- Rellena más campos de extranjero, domicilio y notificación.
- Selecciona países por texto real del desplegable, no por código fijo.
- Guarda log de campos no encontrados/vacíos.
"""

import argparse
import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path


def normalize(value):
    value = "" if value is None else str(value)
    value = value.strip().upper()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"\s+", " ", value)
    return value


def limpiar_piso_runner(value):
    value = "" if value is None else str(value).strip()
    m = re.search(r"\d+", value)
    return m.group(0) if m else value


def resolve_tipo_via_text(value, text=""):
    if text:
        return text
    value = (value or "").strip().upper()
    return {
        "CL": "CALLE",
        "AV": "AVENIDA",
        "PZ": "PLAZA",
        "PS": "PASEO",
        "CM": "CAMINO",
        "CT": "CARRETERA",
        "RD": "RONDA",
        "TR": "TRAVESIA",
        "UR": "URBANIZACION",
        "ZZ": "DESCONOCIDO",
    }.get(value, text or value)


def get_project_root():
    return Path(__file__).resolve().parents[1]


def get_session_dir(arg_session_dir=None, expediente_id="sin_id"):
    if arg_session_dir:
        session_dir = Path(arg_session_dir)
    else:
        session_dir = get_project_root() / "exports" / "presentaciones_asistidas" / f"expediente_{expediente_id}"

    (session_dir / "html").mkdir(parents=True, exist_ok=True)
    (session_dir / "logs").mkdir(parents=True, exist_ok=True)
    return session_dir


def get_browser_source(browser):
    if hasattr(browser, "get_page_source"):
        return browser.get_page_source()
    if hasattr(browser, "get_source"):
        return browser.get_source()
    if hasattr(browser, "page_source"):
        return browser.page_source
    if hasattr(browser, "driver") and hasattr(browser.driver, "page_source"):
        return browser.driver.page_source
    if hasattr(browser, "execute_script"):
        return browser.execute_script("return document.documentElement.outerHTML;")
    if hasattr(browser, "evaluate"):
        return browser.evaluate("document.documentElement.outerHTML")
    raise RuntimeError("No se pudo obtener HTML")


def save_page_source(browser, session_dir, label="page_source"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = session_dir / "html" / f"{label}_{timestamp}.html"
    html_path.write_text(get_browser_source(browser) or "", encoding="utf-8")
    return html_path


def write_log(session_dir, message):
    log_path = session_dir / "logs" / "presentacion.log"
    stamp = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")


def js(browser, code):
    if hasattr(browser, "execute_script"):
        return browser.execute_script(code)
    if hasattr(browser, "evaluate"):
        return browser.evaluate(code)
    raise RuntimeError("El navegador no soporta execute_script/evaluate")


def wait_for_js(browser, condition_js, timeout=30, interval=0.5):
    start = time.time()
    while time.time() - start < timeout:
        try:
            if js(browser, f"return !!({condition_js});"):
                return True
        except Exception:
            pass
        time.sleep(interval)
    raise TimeoutError(f"Timeout esperando condición JS: {condition_js}")


def field_exists(browser, field_id):
    try:
        return bool(js(browser, f"return !!document.getElementById({json.dumps(field_id)});"))
    except Exception:
        return False


def set_value(browser, field_id, value, session_dir=None, trigger_change=True):
    if field_id in ("extPiso", "notPisoNotificacion"):
        value = limpiar_piso_runner(value)

    if value in (None, "", "None"):
        if session_dir:
            write_log(session_dir, f"VACIO: {field_id}")
        return False

    script = f"""
    (function(){{
        const el = document.getElementById({json.dumps(field_id)});
        if (!el) return false;
        el.value = {json.dumps(str(value))};
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        {"el.dispatchEvent(new Event('change', { bubbles: true }));" if trigger_change else ""}
        return true;
    }})();
    """
    ok = bool(js(browser, script))
    if session_dir:
        write_log(session_dir, f"{'OK' if ok else 'NO_EXISTE'} set {field_id}={value}")
    return ok


def set_checkbox(browser, field_id, value=True, session_dir=None):
    """Marca/desmarca checkboxes reales de Mercurio por id."""
    truthy = normalize(value) in {"SI", "S", "TRUE", "1", "YES", "Y"}

    script = f"""
    (function(){{
        const el = document.getElementById({json.dumps(field_id)});
        if (!el) return {{ ok: false, reason: 'NO_EXISTE' }};
        if ((el.type || '').toLowerCase() !== 'checkbox') {{
            return {{ ok: false, reason: 'NO_ES_CHECKBOX', type: el.type || '' }};
        }}
        el.checked = {json.dumps(bool(truthy))};
        if (el.checked && !el.value) el.value = 'true';
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        if (window.jQuery) window.jQuery(el).trigger('change');
        return {{ ok: true, checked: el.checked, value: el.value }};
    }})();
    """

    result = js(browser, script)
    if session_dir:
        write_log(session_dir, f"checkbox {field_id} value={value!r} -> {result}")
    return result


def select_by_text_or_value(browser, field_id, value=None, text=None, session_dir=None):
    """
    Selecciona un <select> por:
    1) value exacto si se aporta
    2) texto normalizado exacto
    3) texto normalizado contenido controlado

    Evita falsos positivos tipo MARRUECOS -> COSTA MARFIL,
    dando prioridad a coincidencia exacta normalizada.
    """
    value = "" if value is None else str(value).strip()
    text = "" if text is None else str(text).strip()
    norm_text = normalize(text)

    script = f"""
    (function(){{
        const id = {json.dumps(field_id)};
        const wantedValue = {json.dumps(value)};
        const wantedText = {json.dumps(norm_text)};

        function norm(v) {{
            return (v || '').toString().trim().toUpperCase()
                .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
                .replace(/\\s+/g, ' ');
        }}

        const el = document.getElementById(id);
        if (!el) return {{ ok: false, reason: 'NO_EXISTE' }};

        let selected = '';

        if (wantedValue) {{
            for (const opt of el.options || []) {{
                if ((opt.value || '').toString() === wantedValue) {{
                    el.value = opt.value;
                    selected = opt.textContent || opt.innerText || opt.value;
                    break;
                }}
            }}
        }}

        if (!selected && wantedText) {{
            for (const opt of el.options || []) {{
                const optText = norm(opt.textContent || opt.innerText || '');
                if (optText === wantedText) {{
                    el.value = opt.value;
                    selected = opt.textContent || opt.innerText || opt.value;
                    break;
                }}
            }}
        }}

        if (!selected && wantedText) {{
            const candidates = [];
            for (const opt of el.options || []) {{
                const optText = norm(opt.textContent || opt.innerText || '');
                if (optText.includes(wantedText) || wantedText.includes(optText)) {{
                    candidates.push(opt);
                }}
            }}
            if (candidates.length === 1) {{
                const opt = candidates[0];
                el.value = opt.value;
                selected = opt.textContent || opt.innerText || opt.value;
            }}
        }}

        if (!selected) return {{
            ok: false,
            reason: 'NO_MATCH',
            wantedText,
            options: Array.from(el.options || []).map(o => [o.value, o.textContent]).slice(0, 120)
        }};

        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        if (window.jQuery) {{
            window.jQuery(el).trigger('change');
        }}
        return {{ ok: true, value: el.value, selected: selected }};
    }})();
    """
    result = js(browser, script)
    if session_dir:
        write_log(session_dir, f"select {field_id} value={value!r} text={text!r} -> {result}")
    return result


def wait_select_options(browser, field_id, min_options=2, timeout=4):
    condition = f"""
    (function(){{
        const el = document.getElementById({json.dumps(field_id)});
        return el && el.options && el.options.length >= {int(min_options)};
    }})()
    """
    return wait_for_js(browser, condition, timeout=timeout)


def select_municipio_localidad(browser, values, session_dir, prefix="ext"):
    """
    Secuencia correcta:
    provincia -> espera municipios -> municipio por texto -> espera localidades -> localidad por texto.
    """
    prov_id = f"{prefix}CodigoProvincia" if prefix == "ext" else f"{prefix}CodigoProvinciaNotificacion"
    mun_id = f"{prefix}CodigoMunicipio" if prefix == "ext" else f"{prefix}CodigoMunicipioNotificacion"
    loc_id = f"{prefix}CodigoLocalidad" if prefix == "ext" else f"{prefix}CodigoLocalidadNotificacion"

    provincia_value = values.get(prov_id, "")
    provincia_text = values.get(prov_id + "_text", "")
    municipio_text = values.get(mun_id + "_text", "")
    localidad_text = values.get(loc_id + "_text", "") or municipio_text

    if provincia_value or provincia_text:
        select_by_text_or_value(browser, prov_id, value=provincia_value, text=provincia_text or provincia_value, session_dir=session_dir)
        time.sleep(1.2)

    if municipio_text and field_exists(browser, mun_id):
        try:
            wait_select_options(browser, mun_id, min_options=2, timeout=4)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL municipio {mun_id}: {exc}")
        select_by_text_or_value(browser, mun_id, text=municipio_text, session_dir=session_dir)
        time.sleep(1.5)

    if localidad_text and field_exists(browser, loc_id):
        try:
            # En muchos Mercurio, localidad carga después de municipio.
            wait_select_options(browser, loc_id, min_options=2, timeout=2)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL localidad {loc_id}: {exc}")
        select_by_text_or_value(browser, loc_id, text=localidad_text, session_dir=session_dir)


def click_js(browser, selector):
    script = f"""
    (function(){{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return false;
        el.click();
        return true;
    }})();
    """
    return js(browser, script)


def load_datos_mercurio(path):
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe datos_mercurio.json: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


FORMULARIO_OBJETIVO_LABELS = {
    "EX01": "EX01 - Residencia temporal no lucrativa",
    "EX02": "EX02 - Reagrupación familiar",
    "EX32": "EX32 - Residencia de familiar de ciudadano de la Unión",
}


MAPPER_CODIGO_LABELS = {
    "MERCURIO_EX01": "EX01 - Titular",
    "MERCURIO_EX01_FAMILIAR": "EX01 - Familiar",
    "MERCURIO_EX02": "EX02 - Reagrupación familiar",
    "MERCURIO_EX32": "EX32 - Familiar de ciudadano UE",
}


def get_tipo_formulario_objetivo(datos_mercurio):
    """
    Lee el formulario objetivo desde datos_mercurio.json.

    No automatiza clicks sobre el supuesto porque Mercurio cambia el DOM y
    una selección errónea podría iniciar un formulario incorrecto.
    El runner lo usa para guiar la pausa humana y dejar trazabilidad en log.
    """
    presentacion = datos_mercurio.get("presentacion", {}) if isinstance(datos_mercurio, dict) else {}
    tipo = str(presentacion.get("tipo_formulario_objetivo") or "").strip().upper()
    return tipo or "EX32"


def describe_tipo_formulario_objetivo(tipo_formulario_objetivo):
    tipo = str(tipo_formulario_objetivo or "").strip().upper()
    label = FORMULARIO_OBJETIVO_LABELS.get(tipo, "")
    return f"{tipo} ({label})" if label else (tipo or "NO DEFINIDO")


def get_mapper_codigo(datos_mercurio):
    """
    Lee el mapper interno desde datos_mercurio.json.

    Diferencia el modo de volcado sin alterar la selección humana del
    formulario/supuesto en Mercurio. Ejemplo:
    - tipo_formulario_objetivo=EX01
    - mapper_codigo=MERCURIO_EX01_FAMILIAR
    """
    presentacion = datos_mercurio.get("presentacion", {}) if isinstance(datos_mercurio, dict) else {}
    mapper_codigo = str(presentacion.get("mapper_codigo") or "").strip().upper()
    if mapper_codigo:
        return mapper_codigo

    # Fallback conservador para exports antiguos sin mapper_codigo.
    tipo = get_tipo_formulario_objetivo(datos_mercurio)
    return {
        "EX01": "MERCURIO_EX01",
        "EX02": "MERCURIO_EX02",
        "EX32": "MERCURIO_EX32",
    }.get(tipo, "")


def describe_mapper_codigo(mapper_codigo):
    mapper = str(mapper_codigo or "").strip().upper()
    label = MAPPER_CODIGO_LABELS.get(mapper, "")
    return f"{mapper} ({label})" if label else (mapper or "NO DEFINIDO")


def get_mercurio_mapper_mode(datos_mercurio):
    """
    Punto único de enrutamiento interno del runner.

    No decide ni selecciona el supuesto Mercurio. Solo informa al código
    qué variante de volcado debe aplicar después de la selección humana.
    """
    mapper_codigo = get_mapper_codigo(datos_mercurio)
    return {
        "mapper_codigo": mapper_codigo,
        "is_ex01": mapper_codigo == "MERCURIO_EX01",
        "is_ex01_familiar": mapper_codigo == "MERCURIO_EX01_FAMILIAR",
        "is_ex02": mapper_codigo == "MERCURIO_EX02",
        "is_ex32": mapper_codigo == "MERCURIO_EX32",
    }


def step_continuar_inicial(browser, session_dir):
    print("[1] Pantalla inicial -> Continuar")
    write_log(session_dir, "Pantalla inicial -> continuar('INI')")
    wait_for_js(browser, "typeof continuar === 'function'")
    js(browser, "continuar('INI');")


def step_continuar_abogacia(browser, session_dir):
    print("[2] Modo acceso -> Continuar Abogacía")
    write_log(session_dir, "Modo acceso -> validarYEnviar('AB')")
    wait_for_js(browser, "typeof validarYEnviar === 'function'")
    js(browser, "validarYEnviar('AB');")


def pause_certificado(session_dir):
    print()
    print("=" * 80)
    print("PAUSA HUMANA: selecciona el certificado digital manualmente.")
    print("Cuando Mercurio haya avanzado a 'Opciones disponibles', vuelve aquí y pulsa ENTER.")
    print("=" * 80)
    write_log(session_dir, "Pausa humana certificado")
    input("Pulsa ENTER para continuar...")


def step_presentar_nueva_solicitud(browser, provincia_codigo, session_dir, tipo_formulario_objetivo=""):
    tipo_desc = describe_tipo_formulario_objetivo(tipo_formulario_objetivo)
    print("[3] Opciones disponibles -> Continuar presentación")
    print(f"Formulario Mercurio objetivo: {tipo_desc}")
    write_log(session_dir, f"Formulario Mercurio objetivo: {tipo_desc}")
    write_log(session_dir, "Opciones disponibles -> mostrarOpcion()")
    wait_for_js(browser, "typeof mostrarOpcion === 'function'")
    js(browser, "mostrarOpcion();")

    print("[4] Modal opciones -> BI Presentar nueva solicitud + provincia")
    write_log(session_dir, f"Seleccionar BI provincia={provincia_codigo}")
    wait_for_js(browser, "document.getElementById('bscIniciales') && document.getElementById('provincia')")

    js(browser, f"""
    (function(){{
        const radio = document.getElementById('bscIniciales');
        const provincia = document.getElementById('provincia');
        radio.checked = true;
        radio.dispatchEvent(new Event('change', {{ bubbles: true }}));
        provincia.value = {json.dumps(str(provincia_codigo))};
        provincia.dispatchEvent(new Event('change', {{ bubbles: true }}));
        if (typeof establecerCodProvincia === 'function') establecerCodProvincia();
    }})();
    """)

    print("[5] Modal opciones -> CONTINUAR")
    wait_for_js(browser, "typeof irOpcion === 'function'")
    js(browser, "irOpcion();")

    print("[6] Aviso Mercurio -> Cerrar")
    wait_for_js(browser, "document.querySelector('.mdCer')")
    click_js(browser, ".mdCer")

    try:
        html_path = save_page_source(browser, session_dir, label="despues_aviso_mercurio")
        write_log(session_dir, f"HTML guardado tras aviso Mercurio: {html_path}")
    except Exception as exc:
        write_log(session_dir, f"No se pudo guardar HTML tras aviso Mercurio: {repr(exc)}")


def pause_supuesto(session_dir, tipo_formulario_objetivo=""):
    tipo_desc = describe_tipo_formulario_objetivo(tipo_formulario_objetivo)
    print()
    print("=" * 80)
    print("PAUSA HUMANA: selecciona manualmente el supuesto concreto.")
    print(f"FORMULARIO OBJETIVO SEGÚN ERP: {tipo_desc}")
    print()
    print("Regla de seguridad:")
    print("- Selecciona en Mercurio el supuesto/formulario que corresponda a ese objetivo.")
    print("- Si Mercurio muestra otra cosa o tienes dudas, NO continúes y guarda HTML.")
    print()
    print("Cuando estés en la pantalla de 'Datos del extranjero/a', pulsa ENTER.")
    print("=" * 80)
    write_log(session_dir, f"Pausa humana supuesto. Formulario objetivo={tipo_desc}")
    input("Pulsa ENTER para continuar...")


def select_piso_by_options(browser, field_id, value=None, session_dir=None):
    """
    Selecciona piso leyendo las <option> reales de Mercurio.

    Casos:
        JSON: "5"    -> option "05"
        JSON: "05"   -> option "05"
        JSON: "5 C"  -> option "05"

    Si el campo no es select, escribe el piso a 2 dígitos.
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        if session_dir:
            write_log(session_dir, f"VACIO piso {field_id}")
        return False

    m = re.search(r"\d+", raw)
    wanted_num = m.group(0) if m else raw

    try:
        wanted_int = int(wanted_num)
    except Exception:
        wanted_int = None

    script = f"""
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

            const ovNum = ov.match(/\\d+/);
            const otNum = ot.match(/\\d+/);

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
    """

    result = js(browser, script)
    if session_dir:
        write_log(session_dir, f"select_piso {field_id} raw={raw!r} -> {result}")
    return result


def classify_piso_mercurio(value):
    """
    Clasifica el piso antes de tocar el DOM.

    Regla clave:
    - Solo selecciona BAJO EXTERIOR/INTERIOR si el valor original es claramente bajo.
    - Si hay número, siempre prevalece el número: "1" -> PISO 01.
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        return {"kind": "empty", "raw": raw, "formatted": "", "num": ""}

    norm = normalize(raw)

    m = re.search(r"\d+", raw)
    if m:
        num = m.group(0).zfill(2)
        return {"kind": "piso", "raw": raw, "formatted": "PISO " + num, "num": num}

    if norm in {"BJ", "BJO", "BAJO", "BJ EXT", "BJO EXT", "BAJO EXT", "BAJO EXTERIOR"}:
        return {"kind": "bajo_exterior", "raw": raw, "formatted": "BAJO EXTERIOR", "num": ""}

    if norm in {"BI", "BJO INT", "BAJO INT", "BAJO INTERIOR"}:
        return {"kind": "bajo_interior", "raw": raw, "formatted": "BAJO INTERIOR", "num": ""}

    return {"kind": "raw", "raw": raw, "formatted": raw, "num": ""}


def format_piso_mercurio(value):
    return classify_piso_mercurio(value)["formatted"]


def set_piso_mercurio(browser, field_id, value=None, session_dir=None):
    """
    Selección segura de piso en Mercurio.

    - BJ/BJ EXT -> PBE / BAJO EXTERIOR.
    - BI        -> PBI / BAJO INTERIOR.
    - 1/01/1 C  -> PISO 01 / P01, sin poder caer en BAJO EXTERIOR.
    """
    info = classify_piso_mercurio(value)
    formatted = info["formatted"]
    kind = info["kind"]
    num = info["num"]
    raw = info["raw"]

    if not formatted:
        if session_dir:
            write_log(session_dir, f"VACIO piso {field_id}")
        return False

    script = f"""
    (function(){{
        const id = {json.dumps(field_id)};
        const raw = {json.dumps(raw)};
        const kind = {json.dumps(kind)};
        const formatted = {json.dumps(formatted)};
        const num = {json.dumps(num)};

        const el = document.getElementById(id);
        if (!el) return {{ ok: false, reason: 'NO_EXISTE', raw, kind, formatted, num }};

        function norm(v) {{
            return (v || '').toString().trim().toUpperCase()
                .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
                .replace(/\s+/g, ' ');
        }}

        function fire() {{
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            if (window.jQuery) window.jQuery(el).trigger('change');
        }}

        if (!el.options) {{
            el.value = formatted;
            fire();
            return {{ ok: true, mode: 'input', value: el.value, raw, kind, formatted, num }};
        }}

        // BAJOS: solo si el valor original fue clasificado explícitamente como bajo.
        if (kind === 'bajo_exterior' || kind === 'bajo_interior') {{
            const wantedCode = kind === 'bajo_exterior' ? 'PBE' : 'PBI';
            const wantedText = kind === 'bajo_exterior' ? 'BAJO EXTERIOR' : 'BAJO INTERIOR';

            for (const opt of el.options || []) {{
                const ov = norm(opt.value);
                const ot = norm(opt.textContent || opt.innerText || '');

                if (ov === wantedCode || ot === wantedText) {{
                    el.value = opt.value;
                    fire();
                    return {{
                        ok: true,
                        mode: 'bajo_exterior_interior',
                        selectedValue: opt.value,
                        selectedText: opt.textContent,
                        raw,
                        kind,
                        wanted: wantedText
                    }};
                }}
            }}
        }}

        // PISOS NUMÉRICOS: si raw trae número, jamás se permite seleccionar PBE/PBI.
        if (kind === 'piso') {{
            const wantedText = 'PISO ' + num;
            const wantedValue = 'P' + num;
            const wantedValueNoZero = 'P' + String(parseInt(num, 10));
            const numericNoZero = String(parseInt(num, 10));

            // 1) Preferencia exacta por value Mercurio habitual: P01, P02...
            for (const opt of el.options || []) {{
                const ov = norm(opt.value);
                const ot = norm(opt.textContent || opt.innerText || '');
                if (ov === wantedValue || ot === wantedText) {{
                    el.value = opt.value;
                    fire();
                    return {{ ok: true, mode: 'piso_exact', selectedValue: opt.value, selectedText: opt.textContent, raw, kind, wanted: wantedText }};
                }}
            }}

            // 2) Fallback numérico, pero exigiendo texto que empiece por PISO.
            for (const opt of el.options || []) {{
                const ov = norm(opt.value);
                const ot = norm(opt.textContent || opt.innerText || '');
                if ((ov === num || ov === numericNoZero || ov === wantedValueNoZero) && ot.startsWith('PISO')) {{
                    el.value = opt.value;
                    fire();
                    return {{ ok: true, mode: 'piso_value_num_text_piso', selectedValue: opt.value, selectedText: opt.textContent, raw, kind, wanted: wantedText }};
                }}
            }}

            return {{
                ok: false,
                reason: 'NO_MATCH_PISO_NUMERICO',
                raw,
                kind,
                formatted,
                num,
                options: Array.from(el.options || []).map(o => [o.value, o.textContent]).slice(0, 160)
            }};
        }}

        // Resto: coincidencia exacta estricta, sin fallback a bajo.
        const wanted = norm(formatted);
        for (const opt of el.options || []) {{
            const ov = norm(opt.value);
            const ot = norm(opt.textContent || opt.innerText || '');
            if (ov === wanted || ot === wanted) {{
                el.value = opt.value;
                fire();
                return {{ ok: true, mode: 'raw_exact', selectedValue: opt.value, selectedText: opt.textContent, raw, kind, wanted: formatted }};
            }}
        }}

        return {{
            ok: false,
            reason: 'NO_MATCH_PISO_RAW',
            raw,
            kind,
            formatted,
            num,
            options: Array.from(el.options || []).map(o => [o.value, o.textContent]).slice(0, 160)
        }};
    }})();
    """

    result = js(browser, script)
    if session_dir:
        write_log(session_dir, f"set_piso_mercurio {field_id} value={value!r} info={info!r} -> {result}")
    return result

def fill_section(browser, values, session_dir):
    """
    Procesa campos normales y también campos solo-texto:
        extCodigoPaisNacimiento_text = "MARRUECOS"
    se convierte en select de:
        extCodigoPaisNacimiento
    """
    processed = set()

    # Primero campos base.
    for field_id, value in values.items():
        if field_id.endswith("_text"):
            continue

        processed.add(field_id)
        text_value = values.get(field_id + "_text", "")

        if field_id.startswith("chk"):
            set_checkbox(browser, field_id, value=value, session_dir=session_dir)
        elif (
            field_id.startswith("extCodigoPais") or field_id.startswith("extCodigoNacionalidad")
            or field_id.startswith("reaCodigoPais") or field_id.startswith("reaCodigoNacionalidad")
        ):
            select_by_text_or_value(browser, field_id, value=value, text=text_value or value, session_dir=session_dir)
        elif field_id.startswith("extCodigoMunicipio") or field_id.startswith("extCodigoLocalidad"):
            # Se gestiona en cascada aparte.
            continue
        elif field_id.startswith("notCodigoMunicipio") or field_id.startswith("notCodigoLocalidad"):
            continue
        elif field_id.startswith("reaCodigoMunicipio") or field_id.startswith("reaCodigoLocalidad"):
            continue
        elif (
            field_id.startswith("extCodigoProvincia") or field_id.startswith("notCodigoProvincia")
            or field_id.startswith("reaCodigoProvincia")
        ):
            # Provincia/municipio/localidad se gestiona en cascada aparte.
            continue
        elif field_id.startswith("preCodigoProvincia") or field_id.startswith("preCodigoMunicipio") or field_id.startswith("preCodigoLocalidad"):
            # Provincia/municipio/localidad del presentador se gestiona en cascada aparte.
            continue
        elif field_id in ("extPiso", "notPisoNotificacion", "prePisoPresentador", "reaPisoReagrupante"):
            set_piso_mercurio(browser, field_id, value=value, session_dir=session_dir)
        elif field_id.startswith("preTipoVia"):
            # Presentador: NO usar variables externas tipo tipo_via.
            # El mapper entrega preTipoViaPresentador y preTipoViaPresentador_text.
            select_by_text_or_value(
                browser,
                field_id,
                value="",
                text=resolve_tipo_via_text(value, text_value),
                session_dir=session_dir,
            )
        elif field_id.startswith("extTipoVia") or field_id.startswith("notTipoVia") or field_id.startswith("reaTipoVia"):
            select_by_text_or_value(
                browser,
                field_id,
                value="",  # Mercurio no usa AV/CL; usa codigos propios como BZ/ED. Seleccionar por texto.
                text=resolve_tipo_via_text(value, text_value),
                session_dir=session_dir,
            )
        elif (
            field_id.startswith("extEstadoCivil") or field_id.startswith("extSexo")
            or field_id.startswith("reaEstadoCivil") or field_id.startswith("reaSexo")
            or field_id.startswith("reaParentesco")
        ):
            select_by_text_or_value(browser, field_id, value=value, text=text_value or value, session_dir=session_dir)
        elif (
            field_id.startswith("notTipodocumento") or field_id.startswith("preTipodocumento")
            or field_id.startswith("reaTipoDocumento")
        ):
            select_by_text_or_value(browser, field_id, value=value, text=text_value or value, session_dir=session_dir)
        else:
            set_value(browser, field_id, value, session_dir=session_dir, trigger_change=True)

    # Después campos que solo vienen como *_text.
    for text_key, text_value in values.items():
        if not text_key.endswith("_text"):
            continue

        base_id = text_key[:-5]
        if base_id in processed:
            continue

        if base_id.startswith("extCodigoMunicipio") or base_id.startswith("extCodigoLocalidad"):
            continue
        if base_id.startswith("notCodigoMunicipio") or base_id.startswith("notCodigoLocalidad"):
            continue
        if base_id.startswith("reaCodigoMunicipio") or base_id.startswith("reaCodigoLocalidad"):
            continue
        if base_id.startswith("extCodigoProvincia") or base_id.startswith("notCodigoProvincia") or base_id.startswith("reaCodigoProvincia"):
            continue
        if base_id.startswith("preCodigoProvincia") or base_id.startswith("preCodigoMunicipio") or base_id.startswith("preCodigoLocalidad"):
            continue

        select_by_text_or_value(browser, base_id, text=text_value, session_dir=session_dir)


def fill_datos_extranjero(browser, datos_mercurio, session_dir):
    print("[7] Rellenando datos completos del extranjero/a")
    write_log(session_dir, "Rellenando datos completos extranjero")

    wait_for_js(browser, "document.getElementById('extPasaporte') || document.getElementById('extNie')")

    extranjero = datos_mercurio.get("extranjero", {})
    domicilio = datos_mercurio.get("domicilio_extranjero", {})
    notificacion = datos_mercurio.get("notificacion", {})

    fill_section(browser, extranjero, session_dir)
    fill_section(browser, domicilio, session_dir)
    select_municipio_localidad(browser, domicilio, session_dir, prefix="ext")

    # Notificación puede estar en otra pestaña, pero si los campos existen, se rellenan.
    fill_section(browser, notificacion, session_dir)
    select_municipio_localidad(browser, notificacion, session_dir, prefix="not")

    print("Datos completos rellenados.")
    write_log(session_dir, "Datos completos rellenados")




def select_municipio_localidad_presentador(browser, values, session_dir):
    """
    Cascada provincia -> municipio -> localidad para Datos del presentador.
    No modifica la función genérica existente para extranjero/notificación.
    """
    prov_id = "preCodigoProvinciaPresentador"
    mun_id = "preCodigoMunicipioPresentador"
    loc_id = "preCodigoLocalidadPresentador"

    provincia_value = values.get(prov_id, "")
    provincia_text = values.get(prov_id + "_text", "")
    municipio_text = values.get(mun_id + "_text", "")
    localidad_text = values.get(loc_id + "_text", "") or municipio_text

    if provincia_value or provincia_text:
        select_by_text_or_value(browser, prov_id, value=provincia_value, text=provincia_text or provincia_value, session_dir=session_dir)
        time.sleep(1.2)

    if municipio_text and field_exists(browser, mun_id):
        try:
            wait_select_options(browser, mun_id, min_options=2, timeout=4)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL municipio presentador {mun_id}: {exc}")
        select_by_text_or_value(browser, mun_id, text=municipio_text, session_dir=session_dir)
        time.sleep(1.5)

    if localidad_text and field_exists(browser, loc_id):
        try:
            wait_select_options(browser, loc_id, min_options=2, timeout=2)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL localidad presentador {loc_id}: {exc}")
        select_by_text_or_value(browser, loc_id, text=localidad_text, session_dir=session_dir)



def select_municipio_localidad_reagrupante(browser, values, session_dir):
    """
    Cascada provincia -> municipio -> localidad para la pestaña Datos del familiar
    de EX01 familiar. Mercurio usa prefijo rea*Reagrupante.
    """
    prov_id = "reaCodigoProvinciaReagrupante"
    mun_id = "reaCodigoMunicipioReagrupante"
    loc_id = "reaCodigoLocalidadReagrupante"

    provincia_value = values.get(prov_id, "")
    provincia_text = values.get(prov_id + "_text", "")
    municipio_text = values.get(mun_id + "_text", "")
    localidad_text = values.get(loc_id + "_text", "") or municipio_text

    if provincia_value or provincia_text:
        select_by_text_or_value(browser, prov_id, value=provincia_value, text=provincia_text or provincia_value, session_dir=session_dir)
        time.sleep(1.2)

    if municipio_text and field_exists(browser, mun_id):
        try:
            wait_select_options(browser, mun_id, min_options=2, timeout=4)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL municipio familiar {mun_id}: {exc}")
        select_by_text_or_value(browser, mun_id, text=municipio_text, session_dir=session_dir)
        time.sleep(1.5)

    if localidad_text and field_exists(browser, loc_id):
        try:
            wait_select_options(browser, loc_id, min_options=2, timeout=2)
        except Exception as exc:
            write_log(session_dir, f"WAIT_FAIL localidad familiar {loc_id}: {exc}")
        select_by_text_or_value(browser, loc_id, text=localidad_text, session_dir=session_dir)


def fill_datos_familiar_ex01(browser, datos_mercurio, session_dir):
    """
    Rellena la pestaña Datos del familiar de EX01 familiar.

    En MERCURIO_EX01_FAMILIAR:
    - Datos del extranjero/a = familiar extranjero solicitante.
    - Datos del familiar = titular de los medios económicos / familiar que da derecho.
    """
    print("[8] Rellenando DATOS DEL FAMILIAR")
    write_log(session_dir, "Rellenando datos del familiar EX01")

    familiar = datos_mercurio.get("familiar", {}) or {}
    if not familiar:
        write_log(session_dir, "Familiar vacío en datos_mercurio.json")
        print("No hay bloque familiar en datos_mercurio.json")
        return False

    wait_for_js(browser, "document.getElementById('reaNombreReagrupante') || document.getElementById('reaDocumentoReagrupante')", timeout=15, interval=0.5)

    fill_section(browser, familiar, session_dir)
    select_municipio_localidad_reagrupante(browser, familiar, session_dir)

    print("Datos del familiar rellenados.")
    write_log(session_dir, "Datos del familiar rellenados")
    return True


def click_continuar_extranjero_to_familiar(browser, session_dir):
    """
    Avance humano desde Datos del extranjero/a a Datos del familiar en EX01 familiar.
    """
    print("[8] PAUSA HUMANA - CONTINUAR a DATOS DEL FAMILIAR")
    write_log(session_dir, "Pausa humana obligatoria: continuar extranjero -> familiar")

    print()
    print("=" * 80)
    print("PAUSA HUMANA")
    print("Pulsa MANUALMENTE CONTINUAR para pasar a Datos del familiar.")
    print("Cuando estés en Datos del familiar, vuelve aquí y pulsa ENTER.")
    print("=" * 80)

    input("Pulsa ENTER cuando estés en Datos del familiar...")

    try:
        wait_for_js(browser, "document.getElementById('reaNombreReagrupante') || document.getElementById('reaDocumentoReagrupante')", timeout=10, interval=0.5)
        write_log(session_dir, "Continuar humano confirmado: pestaña familiar visible")
        return {"ok": True, "mode": "human_required"}
    except Exception as exc:
        write_log(session_dir, f"Continuar a familiar no confirmado: {repr(exc)}")
        return {"ok": False, "mode": "human_required_not_confirmed", "error": repr(exc)}


def click_continuar_familiar_to_presentador(browser, session_dir):
    """
    Avance humano desde Datos del familiar a Datos del presentador en EX01 familiar.
    """
    print("[9] PAUSA HUMANA - CONTINUAR a DATOS DEL PRESENTADOR")
    write_log(session_dir, "Pausa humana obligatoria: continuar familiar -> presentador")

    print()
    print("=" * 80)
    print("PAUSA HUMANA")
    print("Pulsa MANUALMENTE CONTINUAR para pasar desde Datos del familiar a Datos del presentador.")
    print("Cuando estés en Datos del presentador, vuelve aquí y pulsa ENTER.")
    print("=" * 80)

    input("Pulsa ENTER cuando estés en Datos del presentador...")

    try:
        wait_for_js(browser, "document.getElementById('preNombrePresentador')", timeout=10, interval=0.5)
        write_log(session_dir, "Continuar humano confirmado: preNombrePresentador visible")
        return {"ok": True, "mode": "human_required"}
    except Exception as exc:
        write_log(session_dir, f"Continuar a presentador no confirmado: {repr(exc)}")
        return {"ok": False, "mode": "human_required_not_confirmed", "error": repr(exc)}



def click_continuar(browser, session_dir):
    """
    Avance seguro desde Datos del extranjero/a a Datos del presentador.

    Mercurio genera error cuando este click se automatiza.
    Por tanto, este punto queda estrictamente humano:
    - NO click JS
    - NO keyboard
    - NO CDP click
    - NO Selenium click

    El usuario pulsa CONTINUAR manualmente y el script solo espera confirmación.
    """
    print("[8] PAUSA HUMANA - CONTINUAR a DATOS DEL PRESENTADOR")
    write_log(session_dir, "Pausa humana obligatoria: continuar extranjero -> presentador")

    print()
    print("=" * 80)
    print("PAUSA HUMANA")
    print("Pulsa MANUALMENTE el botón CONTINUAR en Mercurio")
    print("para pasar desde Datos del extranjero/a a Datos del presentador.")
    print()
    print("Cuando estés en Datos del presentador, vuelve aquí y pulsa ENTER.")
    print("=" * 80)

    input("Pulsa ENTER cuando estés en Datos del presentador...")

    try:
        wait_for_js(browser, "document.getElementById('preNombrePresentador')", timeout=10, interval=0.5)
        write_log(session_dir, "Continuar humano confirmado: preNombrePresentador visible")
        return {"ok": True, "mode": "human_required"}
    except Exception as exc:
        write_log(session_dir, f"Continuar humano no confirmado: {repr(exc)}")
        return {"ok": False, "mode": "human_required_not_confirmed", "error": repr(exc)}



def hardcode_presentador_asturias_oviedo(browser, session_dir):
    """
    Fuerza SOLO provincia/municipio/localidad del presentador.

    Valores Mercurio:
    - Provincia ASTURIAS = 33
    - Municipio OVIEDO = 44
    - Localidad OVIEDO = 190100

    No espera AJAX: si las options no existen, las crea y selecciona.
    """
    write_log(session_dir, "Hardcode presentador: ASTURIAS / OVIEDO / OVIEDO")

    script = """
    (function(){
        function ensureOption(select, value, text) {
            if (!select) return false;
            let found = false;
            for (const opt of select.options || []) {
                if ((opt.value || '').toString() === value) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                const opt = document.createElement('option');
                opt.value = value;
                opt.textContent = text;
                select.appendChild(opt);
            }
            select.value = value;
            select.dispatchEvent(new Event('input', {bubbles:true}));
            select.dispatchEvent(new Event('change', {bubbles:true}));
            if (window.jQuery) window.jQuery(select).trigger('change');
            return true;
        }

        const provincia = document.getElementById('preCodigoProvinciaPresentador');
        const municipio = document.getElementById('preCodigoMunicipioPresentador');
        const localidad = document.getElementById('preCodigoLocalidadPresentador');

        const okProvincia = ensureOption(provincia, '33', 'ASTURIAS');

        if (typeof controlaProvinciaPRE === 'function') {
            try { controlaProvinciaPRE(); } catch(e) {}
        }

        const okMunicipio = ensureOption(municipio, '44', 'OVIEDO');
        const okLocalidad = ensureOption(localidad, '190100', 'OVIEDO');

        return {
            ok: !!(okProvincia && okMunicipio && okLocalidad),
            provincia: provincia ? provincia.value : null,
            municipio: municipio ? municipio.value : null,
            localidad: localidad ? localidad.value : null
        };
    })();
    """

    result = js(browser, script)
    write_log(session_dir, f"HARDCODE presentador ubicación -> {result}")
    return result


def fill_datos_presentador(browser, datos_mercurio, session_dir):
    """
    Vuelca datos_mercurio['representante'] y fuerza ASTURIAS/OVIEDO.
    """
    print("[9] Rellenando DATOS DEL PRESENTADOR")
    write_log(session_dir, "Rellenando datos del presentador")

    representante = datos_mercurio.get("representante", {}) or {}
    if not representante:
        write_log(session_dir, "Representante vacío en datos_mercurio.json")
        print("No hay bloque representante en datos_mercurio.json")
        return False

    wait_for_js(browser, "document.getElementById('preNombrePresentador')", timeout=15, interval=0.5)

    fill_section(browser, representante, session_dir)
    select_municipio_localidad_presentador(browser, representante, session_dir)

    print("Datos del presentador rellenados.")
    write_log(session_dir, "Datos del presentador rellenados")
    return True


def click_continuar_presentador(browser, session_dir):
    """
    Avance seguro desde Datos del presentador a la siguiente pantalla.

    Mercurio también genera error cuando este CONTINUAR se automatiza.
    Por tanto, este punto queda estrictamente humano:
    - NO click JS
    - NO keyboard
    - NO CDP click
    - NO Selenium click

    El usuario pulsa CONTINUAR manualmente y el script solo espera confirmación.
    """
    print("[10] PAUSA HUMANA - CONTINUAR desde DATOS DEL PRESENTADOR")
    write_log(session_dir, "Pausa humana obligatoria: continuar presentador -> siguiente pantalla")

    print()
    print("=" * 80)
    print("PAUSA HUMANA")
    print("Pulsa MANUALMENTE el botón CONTINUAR en Mercurio")
    print("desde Datos del presentador.")
    print()
    print("Cuando hayas avanzado a la siguiente pantalla, vuelve aquí y pulsa ENTER.")
    print("=" * 80)

    input("Pulsa ENTER cuando hayas avanzado desde Datos del presentador...")

    write_log(session_dir, "Continuar presentador realizado manualmente por usuario")
    return {"ok": True, "mode": "human_required"}



def safe_execute(label, func, session_dir):
    """
    Evita que un error cierre Chrome/proceso.
    """
    try:
        return func()
    except Exception as exc:
        print(f"ERROR en {label}: {exc}")
        write_log(session_dir, f"ERROR en {label}: {repr(exc)}")
        return None



def disconnect_browser_control(browser, session_dir):
    """
    Desconecta SeleniumBase CDP sin cerrar Chrome.

    IMPORTANTE:
    - NO usa stop()
    - NO usa quit()
    - NO usa close()
    - NO intenta desconectar driver/page internos
    - Solo usa browser.disconnect() si existe.
    """
    write_log(session_dir, "Intentando browser.disconnect() para entregar Chrome al humano")

    method = getattr(browser, "disconnect", None)
    if callable(method):
        try:
            result = method()
            write_log(session_dir, f"browser.disconnect() ejecutado correctamente: {result}")
            return True
        except Exception as exc:
            write_log(session_dir, f"browser.disconnect() falló: {repr(exc)}")
            return False

    write_log(session_dir, "browser.disconnect() no existe en esta instancia; no se ejecuta ningún método que pueda cerrar Chrome")
    return False




def pause_humana_final_presentacion(browser, session_dir):
    """
    Pausa humana final SIN disconnect.

    Mantiene Chrome abierto y conectado.
    El bot deja de actuar y el humano pulsa CONCLUIR manualmente.
    """
    print()
    print("=" * 80)
    print("PAUSA HUMANA FINAL")
    print("El bot ha terminado el volcado de datos.")
    print("NO se ejecuta browser.disconnect().")
    print("NO se ejecuta quit(), close() ni stop().")
    print("Chrome queda abierto y conectado.")
    print("Revisa la pantalla y pulsa CONCLUIR manualmente en Mercurio.")
    print("=" * 80)

    write_log(session_dir, "Pausa humana final SIN disconnect: control humano para concluir")

    print()
    input("CONTROL HUMANO: pulsa ENTER aquí solo cuando hayas terminado manualmente en Chrome...")



# =============================================================================
# SUBIDA DOCUMENTAL ASISTIDA - PARA PRESENTAR
# =============================================================================

DOCUMENT_ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff"}


def copy_text_to_clipboard(text_value, session_dir=None):
    """
    Copiado robusto al portapapeles.

    Prioridad:
    1) clip.exe recibiendo bytes UTF-16LE para rutas Windows con acentos/espacios.
    2) powershell Set-Clipboard.
    3) tkinter.
    4) pyperclip si está instalado.

    Devuelve True solo si puede verificar que el portapapeles contiene exactamente la ruta.
    """
    value = "" if text_value is None else str(text_value)

    def log(msg):
        if session_dir:
            write_log(session_dir, msg)

    def verify_clipboard(expected):
        # Verificación por PowerShell Get-Clipboard.
        try:
            import subprocess
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            current = (result.stdout or "").strip()
            if current == expected:
                log(f"CLIPBOARD verified powershell OK: {expected}")
                return True
            log(f"CLIPBOARD verify powershell FAIL current={current!r} expected={expected!r}")
        except Exception as exc:
            log(f"CLIPBOARD verify powershell ERROR: {repr(exc)}")

        # Verificación por tkinter.
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            current = root.clipboard_get()
            root.destroy()
            if current == expected:
                log(f"CLIPBOARD verified tkinter OK: {expected}")
                return True
            log(f"CLIPBOARD verify tkinter FAIL current={current!r} expected={expected!r}")
        except Exception as exc:
            log(f"CLIPBOARD verify tkinter ERROR: {repr(exc)}")

        return False

    # 1) clip.exe con UTF-16LE: suele ser lo más fiable para Windows + rutas con acentos.
    try:
        import subprocess
        subprocess.run(
            ["cmd", "/c", "clip"],
            input=value.encode("utf-16le"),
            check=True,
            timeout=5,
        )
        log(f"CLIPBOARD clip.exe UTF-16LE OK: {value}")
        if verify_clipboard(value):
            return True
    except Exception as exc:
        log(f"CLIPBOARD clip.exe UTF-16LE FAIL: {repr(exc)}")

    # 2) PowerShell Set-Clipboard.
    try:
        import subprocess
        ps_value = value.replace("'", "''")
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value '{ps_value}'"],
            check=True,
            timeout=5,
            capture_output=True,
            text=True,
        )
        log(f"CLIPBOARD powershell Set-Clipboard OK: {value}")
        if verify_clipboard(value):
            return True
    except Exception as exc:
        log(f"CLIPBOARD powershell Set-Clipboard FAIL: {repr(exc)}")

    # 3) tkinter.
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(value)
        root.update()
        root.destroy()
        log(f"CLIPBOARD tkinter OK: {value}")
        if verify_clipboard(value):
            return True
    except Exception as exc:
        log(f"CLIPBOARD tkinter FAIL: {repr(exc)}")

    # 4) pyperclip opcional.
    try:
        import pyperclip
        pyperclip.copy(value)
        log(f"CLIPBOARD pyperclip OK: {value}")
        if verify_clipboard(value):
            return True
    except Exception as exc:
        log(f"CLIPBOARD pyperclip FAIL: {repr(exc)}")

    return False



def get_cliente_nombre_for_documento(datos_mercurio):
    if not isinstance(datos_mercurio, dict):
        return ""

    for source_name in ("extranjero", "cliente", "datos_cliente"):
        source = datos_mercurio.get(source_name, {}) or {}
        if not isinstance(source, dict):
            continue

        nombre = source.get("extNombre") or source.get("nombre") or source.get("nombre_cliente") or ""
        apellido1 = source.get("extApellido1") or source.get("apellido1") or source.get("primer_apellido") or ""
        apellido2 = source.get("extApellido2") or source.get("apellido2") or source.get("segundo_apellido") or ""
        candidate = " ".join(str(x).strip() for x in (nombre, apellido1, apellido2) if str(x).strip())
        if candidate:
            return candidate
    return ""


def build_descripcion_documento(path, datos_mercurio):
    nombre_doc = Path(path).stem.strip()
    nombre_cliente = get_cliente_nombre_for_documento(datos_mercurio).strip()
    descripcion = f"{nombre_doc} - {nombre_cliente}" if nombre_cliente else nombre_doc
    return descripcion[:120]


def resolve_para_presentar_dir(args, datos_mercurio, session_dir):
    candidates = []
    raw = (getattr(args, "documentos_dir", "") or "").strip()
    if raw:
        candidates.append(Path(raw))

    def collect_values(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                yield v
                yield from collect_values(v)
        elif isinstance(obj, list):
            for v in obj:
                yield v
                yield from collect_values(v)

    for value in collect_values(datos_mercurio):
        if isinstance(value, str):
            s = value.strip().strip('"').strip("'")
            if s and not s.lower().startswith(("http://", "https://")):
                if "box" in s.lower() or "para presentar" in normalize(s).lower() or "para_presentar" in normalize(s).lower():
                    candidates.append(Path(s))

    for name in ("datos_mercurio.json", "datos_expediente.json", "session.json", "datos_cliente.json"):
        p = Path(session_dir) / name
        if not p.exists():
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            for value in collect_values(obj):
                if isinstance(value, str):
                    s = value.strip().strip('"').strip("'")
                    if s and not s.lower().startswith(("http://", "https://")):
                        if "box" in s.lower() or "para presentar" in normalize(s).lower() or "para_presentar" in normalize(s).lower():
                            candidates.append(Path(s))
        except Exception:
            pass

    checked = []
    for candidate in candidates:
        try:
            candidate = Path(candidate)
            checked.append(str(candidate))
            if candidate.exists() and candidate.is_dir() and normalize(candidate.name) == "PARA PRESENTAR":
                return candidate
            pp = candidate / "PARA PRESENTAR"
            if pp.exists() and pp.is_dir():
                return pp
            if "PARA PRESENTAR" in normalize(str(candidate)):
                return candidate
        except Exception:
            continue

    write_log(session_dir, f"PARA PRESENTAR no resuelta. Candidatos revisados: {checked}")
    return None


def list_documentos_para_presentar(documentos_dir, session_dir):
    documentos_dir = Path(documentos_dir) if documentos_dir else None
    if not documentos_dir or not documentos_dir.exists() or not documentos_dir.is_dir():
        write_log(session_dir, f"DOCUMENTOS: carpeta PARA PRESENTAR inválida: {documentos_dir}")
        return []

    if normalize(documentos_dir.name) != "PARA PRESENTAR":
        posible = documentos_dir / "PARA PRESENTAR"
        if posible.exists() and posible.is_dir():
            documentos_dir = posible
        else:
            write_log(session_dir, f"DOCUMENTOS: la carpeta no es PARA PRESENTAR: {documentos_dir}")
            return []

    docs = []
    for path in sorted(documentos_dir.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.suffix.lower() in DOCUMENT_ALLOWED_EXTENSIONS:
            docs.append(path.resolve())

    write_log(session_dir, f"DOCUMENTOS PARA PRESENTAR detectados: {[str(p) for p in docs]}")
    return docs


def classify_documento_mercurio(path):
    name = normalize(path.name).lower()
    rules = [
        ("1", ["pasaporte", "passport", "titulo viaje", "cedula"]),
        ("30", ["antecedente", "penal", "penales"]),
        ("3", ["vinculo", "familiar", "familia", "matrimonio", "nacimiento", "parentesco"]),
        ("186", ["convivencia", "unidad familiar"]),
        ("187", ["permanencia", "padron", "padrón", "empadronamiento", "historico", "histórico"]),
        ("43", ["tasa", "790", "052", "pago", "justificante"]),
    ]
    for code, keywords in rules:
        for kw in keywords:
            if normalize(kw).lower() in name:
                return code
    return "999"


def preparar_documento_mercurio(browser, path, code, session_dir):
    """
    Prepara Mercurio para el documento.

    Cambio:
    - Selecciona solo el tipo documental.
    - NO rellena descripción. La descripción la pone el humano.
    - Pulsa Añadir documentación.
    """
    wait_for_js(browser, "document.getElementById('docAdjuntarAdjuntos') && document.getElementById('addDou')", timeout=25)
    select_by_text_or_value(browser, "docAdjuntarAdjuntos", value=code, session_dir=session_dir)
    time.sleep(0.3)

    ok = click_js(browser, "#addDou")
    write_log(session_dir, f"DOCUMENTO click addDou path={path} code={code} ok={ok}")
    return ok



def upload_documentos_mercurio_asistido(browser, documentos_dir, datos_mercurio, session_dir):
    print()
    print("=" * 80)
    print("SUBIDA DOCUMENTAL ASISTIDA - PARA PRESENTAR")
    print("=" * 80)

    docs = list_documentos_para_presentar(documentos_dir, session_dir)
    if not docs:
        print("No hay documentos válidos en la carpeta PARA PRESENTAR.")
        return False

    print("Documentos que se van a preparar, siempre desde PARA PRESENTAR:")
    for i, p in enumerate(docs, 1):
        print(f"  {i}. {p}")

    ans = input("Iniciar preparación asistida? [ENTER=sí / n=no]: ").strip().lower()
    if ans in ("n", "no"):
        write_log(session_dir, "DOCUMENTOS cancelado por usuario antes de iniciar")
        return False

    resultados = []
    for idx, path in enumerate(docs, 1):
        code = classify_documento_mercurio(path)
        print()
        print("-" * 80)
        print(f"Documento {idx}/{len(docs)}")
        print(f"Archivo: {path.name}")
        print(f"Ruta exacta: {path}")
        print(f"Tipo Mercurio propuesto: {code}")
        print("-" * 80)

        ans = input("Preparar este documento? [ENTER=sí / s=saltar / código=forzar tipo]: ").strip().lower()
        if ans in ("s", "skip", "no", "n"):
            resultados.append((str(path), "SALTADO"))
            write_log(session_dir, f"DOCUMENTO saltado: {path}")
            continue
        if ans:
            code = ans
            write_log(session_dir, f"DOCUMENTO código forzado {path}: {code}")

        clipboard_ok = copy_text_to_clipboard(str(path), session_dir=session_dir)
        preparar_documento_mercurio(browser, path, code, session_dir)
        copy_text_to_clipboard(str(path), session_dir=session_dir)

        print()
        print("=" * 80)
        print("ACCIÓN HUMANA")
        print("Se ha pulsado 'Añadir documentación' en Mercurio.")
        print("Ruta copiada al portapapeles:")
        print(str(path))
        print()
        print("1) Pega la ruta en el explorador con CTRL+V y abre el archivo.")
        print("2) Pulsa SUBIR / ADJUNTAR DOCUMENTO en Mercurio.")
        print("3) Comprueba que aparece en la tabla.")
        print("=" * 80)
        if not clipboard_ok:
            print("AVISO: no se pudo verificar el copiado al portapapeles.")
            print("Copia manualmente la ruta mostrada antes de abrir el archivo.")

        input("Pulsa ENTER aquí cuando ESTE documento esté adjuntado en Mercurio...")
        resultados.append((str(path), "ADJUNTADO_HUMANO"))
        write_log(session_dir, f"DOCUMENTO adjuntado por humano: {path}")

    print()
    print("=" * 80)
    print("RESULTADO SUBIDA DOCUMENTAL ASISTIDA")
    print("=" * 80)
    for ruta, estado in resultados:
        print(f"{estado}: {ruta}")
    write_log(session_dir, f"DOCUMENTOS resultado asistido: {resultados}")
    return True


def open_url(browser, url):
    if hasattr(browser, "open"):
        browser.open(url)
    elif hasattr(browser, "get"):
        browser.get(url)
    else:
        raise RuntimeError("La instancia sb_cdp.Chrome no tiene método open/get")


def run_auto(browser, provincia_codigo, datos_mercurio, session_dir):
    tipo_formulario_objetivo = get_tipo_formulario_objetivo(datos_mercurio)
    mapper_mode = get_mercurio_mapper_mode(datos_mercurio)
    write_log(session_dir, f"Mapper interno Mercurio: {describe_mapper_codigo(mapper_mode.get('mapper_codigo'))}")
    step_continuar_inicial(browser, session_dir)
    step_continuar_abogacia(browser, session_dir)
    pause_certificado(session_dir)
    step_presentar_nueva_solicitud(browser, provincia_codigo, session_dir, tipo_formulario_objetivo=tipo_formulario_objetivo)
    pause_supuesto(session_dir, tipo_formulario_objetivo=tipo_formulario_objetivo)
    if datos_mercurio:
        fill_datos_extranjero(browser, datos_mercurio, session_dir)
        if mapper_mode.get("is_ex01_familiar"):
            click_continuar_extranjero_to_familiar(browser, session_dir)
            fill_datos_familiar_ex01(browser, datos_mercurio, session_dir)
            click_continuar_familiar_to_presentador(browser, session_dir)
        else:
            click_continuar(browser, session_dir)
        fill_datos_presentador(browser, datos_mercurio, session_dir)
        click_continuar_presentador(browser, session_dir)
        pause_humana_final_presentacion(browser, session_dir)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--expediente-id", default="")
    parser.add_argument("--numero-expediente", default="")
    parser.add_argument("--tipo", default="")
    parser.add_argument("--provincia-codigo", required=True)
    parser.add_argument("--datos-mercurio-json", default="")
    parser.add_argument("--session-dir", default="")
    parser.add_argument("--documentos-dir", default="")
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()

    session_dir = get_session_dir(args.session_dir, args.expediente_id)
    datos_mercurio = load_datos_mercurio(args.datos_mercurio_json)
    tipo_formulario_objetivo = get_tipo_formulario_objetivo(datos_mercurio)
    mapper_mode = get_mercurio_mapper_mode(datos_mercurio)
    mapper_codigo = mapper_mode.get("mapper_codigo")
    documentos_dir = resolve_para_presentar_dir(args, datos_mercurio, session_dir)

    url = (args.url or "").strip()
    if not url:
        raise ValueError("URL vacía")

    print("=" * 80)
    print("PRESENTACIÓN ASISTIDA - QUESADA ABOGADOS")
    print("=" * 80)
    print(f"Expediente ID: {args.expediente_id or '-'}")
    print(f"Número expediente: {args.numero_expediente or '-'}")
    print(f"Tipo: {args.tipo or '-'}")
    print(f"Provincia código Mercurio: {args.provincia_codigo}")
    print(f"Formulario Mercurio objetivo: {describe_tipo_formulario_objetivo(tipo_formulario_objetivo)}")
    print(f"Mapper interno de volcado: {describe_mapper_codigo(mapper_codigo)}")
    print(f"Carpeta sesión: {session_dir}")
    print(f"datos_mercurio.json: {args.datos_mercurio_json or '-'}")
    print(f"Documentos PARA PRESENTAR: {documentos_dir or '-'}")
    print(f"URL: {url}")
    print("=" * 80)

    write_log(
        session_dir,
        "Iniciando Chrome sb_cdp. "
        f"Formulario objetivo={describe_tipo_formulario_objetivo(tipo_formulario_objetivo)}. "
        f"Mapper interno={describe_mapper_codigo(mapper_codigo)}"
    )
    from seleniumbase import sb_cdp

    browser = sb_cdp.Chrome(headless=False)
    open_url(browser, url)

    if args.auto:
        safe_execute('auto inicial', lambda: run_auto(browser, args.provincia_codigo, datos_mercurio, session_dir), session_dir)
        print("Flujo auto finalizado. Si se ha ejecutado la pausa humana, Chrome queda bajo control manual.")

    print()
    print("MENÚ:")
    print("  ENTER / h  -> guardar HTML actual")
    print("  auto       -> ejecutar flujo parcial")
    print("  fill       -> rellenar datos completos con datos_mercurio.json")
    print("  fillpre    -> rellenar solo datos del presentador")
    print("  fillfam    -> rellenar solo datos del familiar EX01")
    print("  human      -> pausa humana final sin disconnect")
    print("  docs       -> subida documental asistida")
    print("  q          -> salir")
    print()

    while True:
        cmd = input("presentacion> ").strip().lower()

        if cmd in ("", "h", "html", "source"):
            try:
                html_path = save_page_source(browser, session_dir)
                print(f"HTML guardado en: {html_path}")
            except Exception as exc:
                print(f"ERROR guardando HTML: {exc}")

        elif cmd == "auto":
            safe_execute("auto", lambda: run_auto(browser, args.provincia_codigo, datos_mercurio, session_dir), session_dir)

        elif cmd == "fill":
            if not datos_mercurio:
                print("No hay datos_mercurio.json cargado.")
            else:
                fill_datos_extranjero(browser, datos_mercurio, session_dir)

        elif cmd == "fillpre":
            if not datos_mercurio:
                print("No hay datos_mercurio.json cargado.")
            else:
                fill_datos_presentador(browser, datos_mercurio, session_dir)

        elif cmd in ("fillfam", "familiar"):
            if not datos_mercurio:
                print("No hay datos_mercurio.json cargado.")
            else:
                fill_datos_familiar_ex01(browser, datos_mercurio, session_dir)

        elif cmd in ("human", "humano", "pausa"):
            pause_humana_final_presentacion(browser, session_dir)

        elif cmd in ("docs", "documentos", "upload"):
            documentos_dir = resolve_para_presentar_dir(args, datos_mercurio, session_dir)
            if not documentos_dir:
                print("No se ha encontrado carpeta PARA PRESENTAR. Revisa --documentos-dir o la ruta exportada del expediente.")
            else:
                print(f"Usando carpeta PARA PRESENTAR: {documentos_dir}")
                safe_execute("docs", lambda: upload_documentos_mercurio_asistido(browser, documentos_dir, datos_mercurio, session_dir), session_dir)

        elif cmd in ("q", "quit", "exit", "salir"):
            print("Cerrando presentación asistida...")
            write_log(session_dir, "Cerrando presentación asistida")
            try:
                if hasattr(browser, "quit"):
                    browser.quit()
                elif hasattr(browser, "close"):
                    browser.close()
            except Exception:
                pass
            break

        else:
            print("Comando no reconocido.")


if __name__ == "__main__":
    main()
