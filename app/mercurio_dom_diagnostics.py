"""
Diagnóstico DOM para Presentación Asistida Mercurio.

Objetivo:
- Guardar evidencias de la pantalla de selección de supuesto.
- Detectar candidatos clicables de forma no destructiva.
- No realiza clicks ni modifica la pantalla.
"""

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path


DEFAULT_FORM_LABELS = {
    "EX01": ["EX01", "RESIDENCIA TEMPORAL NO LUCRATIVA", "NO LUCRATIVA"],
    "EX02": ["EX02", "REAGRUPACION FAMILIAR", "REAGRUPACIÓN FAMILIAR"],
    "EX32": ["EX32", "FAMILIAR DE CIUDADANO DE LA UNION", "FAMILIAR DE CIUDADANO DE LA UNIÓN"],
}


def normalize(value):
    value = "" if value is None else str(value)
    value = value.strip().upper()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"\s+", " ", value)
    return value


def _js(browser, code):
    if hasattr(browser, "execute_script"):
        return browser.execute_script(code)
    if hasattr(browser, "evaluate"):
        return browser.evaluate(code)
    raise RuntimeError("El navegador no soporta execute_script/evaluate")


def _get_source(browser):
    if hasattr(browser, "get_page_source"):
        return browser.get_page_source()
    if hasattr(browser, "get_source"):
        return browser.get_source()
    if hasattr(browser, "page_source"):
        return browser.page_source
    if hasattr(browser, "driver") and hasattr(browser.driver, "page_source"):
        return browser.driver.page_source
    return _js(browser, "return document.documentElement.outerHTML;")


def _safe_attr(value, max_len=500):
    value = "" if value is None else str(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_len]


def _save_screenshot(browser, path):
    path = Path(path)

    for obj in (browser, getattr(browser, "driver", None)):
        if obj is None:
            continue
        method = getattr(obj, "save_screenshot", None)
        if callable(method):
            try:
                ok = method(str(path))
                if ok is not False and path.exists():
                    return True
            except Exception:
                pass

    # Algunos wrappers CDP exponen métodos alternativos.
    for name in ("get_screenshot_as_file", "screenshot"):
        method = getattr(browser, name, None)
        if callable(method):
            try:
                result = method(str(path))
                if path.exists() or result is True:
                    return True
            except Exception:
                pass

    return False


def collect_dom_candidates(browser):
    """
    Extrae candidatos clicables relevantes de la pantalla actual.
    No pulsa nada.
    """
    script = r"""
    (function(){
        function txt(el) {
            return ((el.innerText || el.textContent || el.value || el.title || el.alt || '') + '').replace(/\s+/g, ' ').trim();
        }
        function cssHint(el) {
            if (!el) return '';
            if (el.id) return '#' + el.id;
            if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
            var cls = (el.className || '').toString().trim().split(/\s+/).filter(Boolean).slice(0, 3).join('.');
            return cls ? el.tagName.toLowerCase() + '.' + cls : el.tagName.toLowerCase();
        }
        const nodes = Array.from(document.querySelectorAll('a, button, input, select, option, label, td, th, span, div'));
        const out = [];
        for (const el of nodes) {
            const tag = (el.tagName || '').toLowerCase();
            const text = txt(el);
            const id = el.id || '';
            const name = el.getAttribute('name') || '';
            const value = el.getAttribute('value') || '';
            const href = el.getAttribute('href') || '';
            const onclick = el.getAttribute('onclick') || '';
            const role = el.getAttribute('role') || '';
            const type = el.getAttribute('type') || '';
            const classes = (el.className || '').toString();
            const combined = [text, id, name, value, href, onclick, role, type, classes].join(' ');
            const hasEx = /EX\s*\d{2}/i.test(combined);
            const looksClickable = ['a','button','input','select','option','label'].includes(tag) || !!onclick || role === 'button';
            const hasMercurioText = /supuesto|formulario|solicitud|residencia|reagrupaci[oó]n|lucrativa|ciudadano|uni[oó]n/i.test(combined);
            if (!hasEx && !looksClickable && !hasMercurioText) continue;
            if (!combined.trim()) continue;
            out.push({
                tag: tag,
                text: text,
                id: id,
                name: name,
                value: value,
                href: href,
                onclick: onclick,
                role: role,
                type: type,
                classes: classes,
                selector_hint: cssHint(el)
            });
        }
        return {
            url: window.location.href,
            title: document.title || '',
            candidates: out.slice(0, 300)
        };
    })();
    """
    result = _js(browser, script)
    if not isinstance(result, dict):
        return {"url": "", "title": "", "candidates": []}
    result.setdefault("candidates", [])
    return result


def score_candidates(tipo_formulario_objetivo, candidates):
    tipo = normalize(tipo_formulario_objetivo)
    labels = DEFAULT_FORM_LABELS.get(tipo, [tipo] if tipo else [])
    labels_norm = [normalize(x) for x in labels if normalize(x)]
    matches = []

    for candidate in candidates or []:
        combined = " ".join(
            str(candidate.get(k) or "")
            for k in ("text", "id", "name", "value", "href", "onclick", "classes")
        )
        combined_norm = normalize(combined)
        score = 0
        reasons = []

        if tipo and tipo in combined_norm:
            score += 100
            reasons.append(f"contains {tipo}")

        for label in labels_norm:
            if label and label != tipo and label in combined_norm:
                score += 40
                reasons.append(f"contains label {label}")

        if score:
            item = dict(candidate)
            item["score"] = score
            item["reason"] = "; ".join(reasons)
            matches.append(item)

    matches.sort(key=lambda x: x.get("score", 0), reverse=True)
    return matches


def save_dom_diagnostics(browser, session_dir, tipo_formulario_objetivo="", label="dom_supuesto"):
    """
    Guarda HTML, screenshot opcional y JSON de diagnóstico.
    No interactúa con la página.
    """
    session_dir = Path(session_dir)
    html_dir = session_dir / "html"
    diag_dir = session_dir / "diagnostics"
    html_dir.mkdir(parents=True, exist_ok=True)
    diag_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{label}_{timestamp}"
    html_path = html_dir / f"{base}.html"
    png_path = html_dir / f"{base}.png"
    json_path = diag_dir / f"{base}_diagnostics.json"

    html_path.write_text(_get_source(browser) or "", encoding="utf-8")

    screenshot_saved = _save_screenshot(browser, png_path)
    if not screenshot_saved and png_path.exists():
        screenshot_saved = True

    dom_info = collect_dom_candidates(browser)
    candidates = dom_info.get("candidates", []) or []
    matches = score_candidates(tipo_formulario_objetivo, candidates)

    diagnostic = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "tipo_formulario_objetivo": str(tipo_formulario_objetivo or "").strip().upper(),
        "url": dom_info.get("url", ""),
        "title": dom_info.get("title", ""),
        "html_path": str(html_path),
        "screenshot_path": str(png_path) if screenshot_saved else "",
        "candidatos_count": len(candidates),
        "matches_count": len(matches),
        "candidatos": candidates,
        "matches_objetivo": matches[:50],
        "decision": "diagnostic_only",
    }
    json_path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "html_path": html_path,
        "screenshot_path": png_path if screenshot_saved else None,
        "json_path": json_path,
        "candidates_count": len(candidates),
        "matches_count": len(matches),
    }
